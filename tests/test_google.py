import asyncio
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import RSAKey
from sqlalchemy import select, update
from test_auth import login, register

from zoclip.auth.google import GoogleOIDC
from zoclip.auth.models import OAuthFlow, OAuthIdentity, User
from zoclip.core.db import utcnow
from zoclip.core.security import OAUTH_COOKIE


class FakeGoogle:
    """Explicit test adapter; production factory always uses GoogleOIDC."""

    claims = {"sub": "test-subject", "email": "google@example.com", "email_verified": True}
    calls = 0
    fail = False

    async def authorization_url(self, state, nonce, verifier):
        return f"https://accounts.google.com/authorize?state={state}"

    async def exchange(self, code, nonce, verifier):
        self.calls += 1
        if self.fail:
            raise ValueError("secret provider payload")
        return self.claims.copy()


def configure(app):
    app.state.settings.google_client_id = "test-client"
    fake = FakeGoogle()
    app.state.google = fake
    return fake


def start(client):
    response = client.get("/api/v1/auth/google/start", follow_redirects=False)
    assert response.status_code == 302, response.text
    return parse_qs(urlsplit(response.headers["location"]).query)["state"][0]


@pytest.mark.integration
def test_google_disabled(client):
    for path in ("start", "callback"):
        response = client.get(f"/api/v1/auth/google/{path}")
        assert response.status_code == 503
        assert response.json()["code"] == "google_unconfigured"


@pytest.mark.integration
@pytest.mark.parametrize("invalid", ["wrong-state", "wrong-browser", "expired", "missing-code"])
def test_oauth_state_binding(client, app, invalid):
    fake = configure(app)
    state = start(client)
    code = "test-code"
    if invalid == "wrong-state":
        state = "wrong"
    elif invalid == "wrong-browser":
        client.cookies.clear()
        client.cookies.set(OAUTH_COOKIE, "wrong")
    elif invalid == "expired":
        with app.state.session_factory() as db:
            db.execute(update(OAuthFlow).values(expires_at=utcnow() - timedelta(seconds=1)))
            db.commit()
    else:
        code = ""
    result = client.get("/api/v1/auth/google/callback", params={"state": state, "code": code})
    assert result.status_code == 400
    assert fake.calls == 0


@pytest.mark.integration
def test_google_creates_session_and_replay_rejected(client, app):
    fake = configure(app)
    state = start(client)
    browser = client.cookies.get(OAUTH_COOKIE)
    response = client.get(
        "/api/v1/auth/google/callback",
        params={"state": state, "code": "code"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert client.get("/api/v1/me").json()["email"] == "google@example.com"
    client.cookies.set(OAUTH_COOKIE, browser)
    assert (
        client.get(
            "/api/v1/auth/google/callback",
            params={"state": state, "code": "code"},
            follow_redirects=False,
        ).status_code
        == 400
    )
    assert fake.calls == 1
    with app.state.session_factory() as db:
        assert db.scalar(select(OAuthIdentity)).subject == "test-subject"
        flow = db.scalar(select(OAuthFlow))
        assert flow.consumed_at and not flow.code_verifier and not flow.nonce


@pytest.mark.integration
def test_google_does_not_auto_link_matching_email(client, app):
    register(client, app)
    fake = configure(app)
    fake.claims = fake.claims | {"email": "alice@example.com"}
    state = start(client)
    response = client.get(
        "/api/v1/auth/google/callback",
        params={"state": state, "code": "code"},
        follow_redirects=False,
    )
    assert response.status_code == 409
    assert response.json()["code"] == "oauth_link_required"
    assert client.get("/api/v1/me").status_code == 401


@pytest.mark.integration
def test_google_link_requires_current_session_and_verified_matching_email(client, app):
    login(client, register(client, app))
    fake = configure(app)
    fake.claims = fake.claims | {"email": "alice@example.com"}
    state = start(client)
    response = client.get(
        "/api/v1/auth/google/callback",
        params={"state": state, "code": "code"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    with app.state.session_factory() as db:
        assert db.scalar(select(OAuthIdentity)).user_id == db.scalar(select(User)).id


@pytest.mark.integration
def test_google_link_rechecks_revocation_after_exchange(client, app):
    from zoclip.auth.models import AuthSession

    login(client, register(client, app))
    fake = configure(app)
    fake.claims = fake.claims | {"email": "alice@example.com"}
    original_exchange = fake.exchange

    async def exchange(*args):
        with app.state.session_factory() as db:
            db.execute(update(AuthSession).values(revoked_at=utcnow()))
            db.commit()
        return await original_exchange(*args)

    fake.exchange = exchange
    state = start(client)
    response = client.get(
        "/api/v1/auth/google/callback",
        params={"state": state, "code": "code"},
        follow_redirects=False,
    )
    assert response.status_code == 401
    with app.state.session_factory() as db:
        assert db.scalar(select(OAuthIdentity)) is None


@pytest.mark.integration
@pytest.mark.parametrize("failure", ["unverified", "exchange"])
def test_google_rejects_unverified_or_failed_exchange(client, app, failure):
    fake = configure(app)
    if failure == "unverified":
        fake.claims = fake.claims | {"email_verified": False}
    else:
        fake.fail = True
    state = start(client)
    response = client.get("/api/v1/auth/google/callback", params={"state": state, "code": "code"})
    assert response.status_code == 400 and "secret provider payload" not in response.text
    with app.state.session_factory() as db:
        assert db.scalar(select(User)) is None


@pytest.mark.parametrize("bad_claim", [None, "aud", "iss", "exp", "nonce", "azp", "signature"])
def test_real_adapter_validates_signed_tokens_without_external_network(monkeypatch, bad_claim):
    """Local RSA signatures + mocked HTTP, exercising actual adapter validation."""
    from zoclip.core.config import Settings

    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://test@localhost/test",
        google_client_id="test-client",
        google_client_secret="test-only-client-secret",
        google_redirect_uri="http://localhost:8000/api/v1/auth/google/callback",
    )
    adapter = GoogleOIDC(settings)
    key = RSAKey.generate_key(2048, parameters={"kid": "test-key"})
    now = int(utcnow().timestamp())
    claims = {
        "iss": "https://accounts.google.com",
        "aud": "test-client",
        "exp": now + 600,
        "iat": now,
        "sub": "subject",
        "nonce": "nonce",
    }
    if bad_claim in {"aud", "iss", "nonce", "azp"}:
        claims[bad_claim] = "wrong"
    if bad_claim == "exp":
        claims["exp"] = now - 600
    signing_key = RSAKey.generate_key(2048) if bad_claim == "signature" else key
    encoded = jwt.encode({"alg": "RS256", "kid": "test-key"}, claims, signing_key)

    class TokenClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def fetch_token(self, *args, **kwargs):
            assert kwargs["code_verifier"] == "verifier"
            return {"id_token": encoded}

    monkeypatch.setattr(adapter, "client", lambda: TokenClient())

    async def metadata():
        return {
            "issuer": "https://accounts.google.com",
            "token_endpoint": "https://oauth2.googleapis.com/token",
            "jwks_uri": "https://www.googleapis.com/keys",
        }

    monkeypatch.setattr(adapter, "metadata", metadata)
    actual_client = httpx.AsyncClient

    def handler(request):
        return httpx.Response(200, json={"keys": [key.as_dict(private=False)]})

    monkeypatch.setattr(
        "zoclip.auth.google.httpx.AsyncClient",
        lambda **kwargs: actual_client(transport=httpx.MockTransport(handler)),
    )
    if bad_claim:
        with pytest.raises(JoseError):
            asyncio.run(adapter.exchange("code", "nonce", "verifier"))
    else:
        assert asyncio.run(adapter.exchange("code", "nonce", "verifier"))["sub"] == "subject"


def test_authorization_url_has_pkce_nonce_and_state(monkeypatch):
    from zoclip.core.config import Settings

    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://test@localhost/test",
        google_client_id="test-client",
        google_client_secret="test-only-client-secret",
        google_redirect_uri="http://localhost:8000/api/v1/auth/google/callback",
    )
    adapter = GoogleOIDC(settings)

    async def metadata():
        return {"authorization_endpoint": "https://accounts.google.com/authorize"}

    monkeypatch.setattr(adapter, "metadata", metadata)
    result = asyncio.run(adapter.authorization_url("state", "nonce", "v" * 43))
    query = parse_qs(urlsplit(result).query)
    assert query["code_challenge_method"] == ["S256"]
    assert query["nonce"] == ["nonce"] and query["state"] == ["state"]
    assert "v" * 43 not in result
