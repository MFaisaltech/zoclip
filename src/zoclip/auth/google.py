from datetime import timedelta
from typing import Any

import httpx
from authlib.integrations.httpx_client import AsyncOAuth2Client
from authlib.oidc.core import CodeIDToken
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from joserfc import jwt
from joserfc.jwk import KeySet
from pydantic import EmailStr, TypeAdapter
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from zoclip.auth.dependencies import DB, CurrentSession
from zoclip.auth.models import AuthSession, OAuthFlow, OAuthIdentity, User
from zoclip.auth.service import audit, new_session
from zoclip.core.config import Settings
from zoclip.core.db import utcnow
from zoclip.core.errors import ApiError
from zoclip.core.rate_limit import rate_limit
from zoclip.core.security import OAUTH_COOKIE, digest, token

DISCOVERY = "https://accounts.google.com/.well-known/openid-configuration"
router = APIRouter(prefix="/api/v1/auth/google", tags=["authentication"])


class GoogleOIDC:
    def __init__(self, settings: Settings):
        self.settings = settings

    def client(self) -> AsyncOAuth2Client:
        return AsyncOAuth2Client(
            client_id=self.settings.google_client_id,
            client_secret=self.settings.google_client_secret.get_secret_value(),
            redirect_uri=self.settings.google_redirect_uri,
            scope="openid email",
            code_challenge_method="S256",
            timeout=10,
            trust_env=False,
        )

    async def metadata(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
            response = await client.get(DISCOVERY)
            response.raise_for_status()
            metadata: dict[str, Any] = response.json()
        if metadata.get("issuer") != "https://accounts.google.com":
            raise ValueError("Unexpected issuer")
        # Metadata is fetched from Google only; do not accept client-supplied endpoints.
        for key in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
            url = httpx.URL(metadata[key])
            if url.scheme != "https" or url.host not in {
                "accounts.google.com",
                "oauth2.googleapis.com",
                "www.googleapis.com",
            }:
                raise ValueError("Unexpected OIDC endpoint")
        return metadata

    async def authorization_url(self, state: str, nonce: str, verifier: str) -> str:
        metadata = await self.metadata()
        async with self.client() as client:
            url, _ = client.create_authorization_url(
                metadata["authorization_endpoint"],
                state=state,
                nonce=nonce,
                code_verifier=verifier,
                prompt="select_account",
            )
        return str(url)

    async def exchange(self, code: str, nonce: str, verifier: str) -> dict[str, Any]:
        metadata = await self.metadata()
        async with self.client() as client:
            result = await client.fetch_token(
                metadata["token_endpoint"],
                code=code,
                code_verifier=verifier,
                grant_type="authorization_code",
            )
        async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
            response = await client.get(metadata["jwks_uri"])
            response.raise_for_status()
            keys = response.json()
        decoded = jwt.decode(result["id_token"], KeySet.import_key_set(keys), algorithms=["RS256"])
        claims = CodeIDToken(
            decoded.claims,
            decoded.header,
            options={
                "iss": {"essential": True, "value": metadata["issuer"]},
                "aud": {"essential": True, "value": self.settings.google_client_id},
                "exp": {"essential": True},
                "iat": {"essential": True},
                "sub": {"essential": True},
            },
            params={
                "nonce": nonce,
                "client_id": self.settings.google_client_id,
                "access_token": result.get("access_token"),
            },
        )
        claims.validate(leeway=30)
        return dict(claims)


def enabled(request: Request) -> None:
    if not request.app.state.settings.google_enabled:
        raise ApiError(503, "google_unconfigured", "Google login is not configured.")


@router.get("/start", status_code=302)
async def start(request: Request, db: DB, session: CurrentSession) -> RedirectResponse:
    enabled(request)
    rate_limit(request, "google_start")
    state, nonce, verifier, browser = token(), token(), token(), token()
    # An authenticated start records linking intent; callback still rechecks that session.
    user_id = session.user_id if session else None
    if user_id:
        user = db.get(User, user_id)
        if not user or not user.verified or user.status != "active":
            raise ApiError(401, "authentication_required", "Active verified account required.")
    db.commit()  # Release dependency read transaction before network I/O.
    try:
        url = await request.app.state.google.authorization_url(state, nonce, verifier)
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        raise ApiError(503, "google_unavailable", "Google login temporarily unavailable.") from exc
    db.add(
        OAuthFlow(
            state_hash=digest(state),
            browser_hash=digest(browser),
            nonce=nonce,
            code_verifier=verifier,
            user_id=user_id,
            expires_at=utcnow() + timedelta(minutes=10),
        )
    )
    db.commit()
    response = RedirectResponse(url, status_code=302)
    response.set_cookie(
        OAUTH_COOKIE,
        browser,
        max_age=600,
        httponly=True,
        secure=request.app.state.settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    return response


@router.get("/callback", status_code=303)
async def callback(
    request: Request, db: DB, session: CurrentSession, state: str = "", code: str = ""
) -> RedirectResponse:
    enabled(request)
    rate_limit(request, "google_callback")
    browser = request.cookies.get(OAUTH_COOKIE, "")
    if not state or len(state) > 128 or not browser or len(browser) > 128 or len(code) > 4096:
        raise ApiError(400, "oauth_state_invalid", "Invalid OAuth state.")
    flow = db.scalar(
        select(OAuthFlow).where(OAuthFlow.state_hash == digest(state)).with_for_update()
    )
    if (
        not flow
        or flow.consumed_at
        or flow.expires_at <= utcnow()
        or flow.browser_hash != digest(browser)
        or not code
    ):
        raise ApiError(400, "oauth_state_invalid", "Invalid OAuth state.")
    if flow.user_id and (not session or session.user_id != flow.user_id):
        raise ApiError(400, "oauth_link_session_invalid", "Restart linking while logged in.")
    nonce, verifier, link_user_id = flow.nonce, flow.code_verifier, flow.user_id
    flow.consumed_at = utcnow()
    # Consume once and erase PKCE material before exchange, even when exchange fails.
    flow.nonce, flow.code_verifier = "", ""
    db.commit()
    try:
        claims = await request.app.state.google.exchange(code, nonce, verifier)
        email = str(TypeAdapter(EmailStr).validate_python(claims.get("email"))).lower()
        subject = claims["sub"]
        if (
            claims.get("email_verified") is not True
            or not isinstance(subject, str)
            or not subject
            or len(subject) > 255
        ):
            raise ValueError("Unverified identity")
    except Exception as exc:
        # Provider validation errors must not leak tokens, claims or response bodies.
        raise ApiError(
            400, "oauth_identity_invalid", "Google identity could not be verified."
        ) from exc
    identity = db.scalar(
        select(OAuthIdentity).where(
            OAuthIdentity.provider == "google", OAuthIdentity.subject == subject
        )
    )
    if identity:
        user = db.scalar(select(User).where(User.id == identity.user_id).with_for_update())
        if link_user_id and identity.user_id != link_user_id:
            raise ApiError(
                409, "oauth_link_conflict", "Identity already belongs to another account."
            )
    elif link_user_id:
        user = db.scalar(select(User).where(User.id == link_user_id).with_for_update())
        if not user or not user.verified or user.email != email:
            raise ApiError(409, "oauth_link_conflict", "Verified matching account required.")
        db.add(
            OAuthIdentity(user_id=user.id, provider="google", subject=subject, verified_email=email)
        )
    else:
        if db.scalar(select(User.id).where(User.email == email)):
            raise ApiError(
                409, "oauth_link_required", "Log in to your existing account to link Google."
            )
        user = User(email=email, verified=True)
        db.add(user)
        db.flush()
        db.add(
            OAuthIdentity(user_id=user.id, provider="google", subject=subject, verified_email=email)
        )
    if not user or user.status != "active" or not user.verified:
        raise ApiError(401, "authentication_required", "Active verified account required.")
    previous = None
    if session:
        previous = db.scalar(
            select(AuthSession)
            .where(AuthSession.id == session.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if link_user_id and (
            not previous or previous.revoked_at or previous.expires_at <= utcnow()
        ):
            raise ApiError(401, "session_expired", "Restart linking while logged in.")
    response = RedirectResponse(request.app.state.settings.public_app_url, status_code=303)
    new_session(db, request, response, user.id, previous)
    audit(db, request, "auth.google_login", actor=user.id, target=user.id)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ApiError(409, "oauth_link_conflict", "Account changed; restart login.") from exc
    response.delete_cookie(
        OAUTH_COOKIE,
        path="/",
        secure=request.app.state.settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return response
