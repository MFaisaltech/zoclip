# Phase 1 authentication handoff

Implemented routes are exported from actual FastAPI models in `openapi.json`.
All responses containing session/CSRF data use `Cache-Control: no-store`.
This document describes the backend authentication contract. Current frontend
integration and local evidence are in [PHASE8_AUTH_MILESTONE.md](PHASE8_AUTH_MILESTONE.md).

## Session and CSRF protocol

1. GET `/api/v1/auth/csrf` with credentialed fetch. It creates an anonymous session
   if necessary, sets `zoclip_session` and returns `csrf_token`. For an existing
   session it replaces the CSRF token without extending the session expiry.
2. Every POST requires the cookie, exact `Origin` equal to PUBLIC_APP_URL or
   API_PUBLIC_URL, and `X-CSRF-Token`. This includes register/login/reset/logout.
   Curl clients must explicitly supply Origin and retain the cookie jar.
3. Login rotates and revokes the previous session, returning `user` and a new
   `csrf_token`. POST `/auth/session/rotate` also replaces session and CSRF tokens.
   GET CSRF after Google callback to obtain the authenticated CSRF token.
4. Logout revokes the DB session and deletes its cookie; replay fails. Password
   reset revokes every authenticated session for the user. Each request checks
   expiry, revocation, verified email and active account status.

Session tokens and CSRF tokens have 256 bits of random entropy; PostgreSQL stores
only SHA-256 hashes. These are opaque server-side sessions, not browser JWTs.
No SESSION_SIGNING_SECRET or CSRF_SECRET is needed for this design. Default session
life is 24h, anonymous life 30m; neither is silently renewed by ordinary reads.
Cookies are host-only, HttpOnly, SameSite=Lax, Secure by default, path `/`.
Local HTTP explicitly sets COOKIE_SECURE=false; production validation forbids it.

Use same-site HTTPS `app.<domain>` and `api.<domain>`. Fetch uses credentials:
include, never a localStorage bearer session. CORS allows PUBLIC_APP_URL only and
credentials, GET/POST, Content-Type and X-CSRF-Token; API-origin requests are
same-origin and need no CORS permission. Wildcards are forbidden. Google callbacks
use state/browser binding rather than mutation CSRF header. Proxy forwarding is
disabled in the supplied Uvicorn command: do not trust arbitrary X-Forwarded-For.
A later trusted Nginx deployment must explicitly configure proxy IPs; otherwise IP
throttles see the proxy address and conservatively share its limit.

Responses expose `X-Request-ID` and `Retry-After` to the allowed frontend origin,
so browser clients can read rate-limit retry hints. Later domain routes also allow
their documented methods/headers; see API_HANDOFF.md.

## Endpoints

Paths below are relative to `/api/v1`.

| Method/path | Input | Behavior |
|---|---|---|
| GET /auth/csrf | Cookie optional | Creates/refreshes CSRF token |
| POST /auth/register | email, password | 202 generic response; unverified account + verification message |
| POST /auth/verify-email | token | Single-use verification, does not log in |
| POST /auth/login | email, password | Verified active account only, rotated session + user + CSRF |
| POST /auth/logout | No body | Revokes current session |
| POST /auth/session/rotate | No body | Active verified account, rotated cookie + CSRF |
| POST /auth/password/forgot | email | 202 generic response; only eligible password accounts get message |
| POST /auth/password/reset | token, password | Single-use reset and all-session revocation |
| GET /auth/google/start | No client redirect URL | Google redirect, or 503 google_unconfigured |
| GET /auth/google/callback | state, code | Validated identity -> fixed app redirect and session |
| GET /me | Authenticated cookie | Own safe profile only |
| GET /me/sessions/{session_id} | UUID | Own session id/timestamps; foreign IDs return 404 |
| GET /admin/audit-logs | limit 1..100, optional UUID cursor | Admin only; access itself audited |

Registration/login passwords are 12–128 characters; extra request fields (including
role/verified/user_id) are rejected. Email addresses normalize to lowercase.
Argon2id uses time_cost=3, memory_cost=65536 KiB, parallelism=1. Two simultaneous
hash/verify slots bound auth memory per API process; tune only with measurements.
Unknown login accounts perform dummy password verification. Register duplicates
and forgot unknown accounts share generic status/body with eligible requests;
unverified registration retries issue a replacement verification token without
changing the password. Register/reset flows do comparable password work, but no
constant-time network-delivery guarantee is claimed.

Verification expires after 24h, reset after 1h, both hashed and consumed under user
and token row locks. New same-purpose token issuance invalidates earlier tokens.
Trials are not granted. Account status and roles have DB CHECK constraints.
Staff provision is deliberately not a public API: no self-service role promotion.

Redis Lua atomically increments per-route IP and normalized account hash counters
with a fixed-window TTL (10 attempts/15min by default, configurable). CSRF minting,
OAuth starts/callbacks, login, registration, email verification and recovery are
bounded. Missing Redis fails affected authentication operations with 503; it does
not fall back to unbounded in-process counters. Retry-After is a conservative 60s
hint; retry may still be limited until the fixed window expires.

## Development email and Google

EMAIL_MODE=development writes JSON messages to DEV_MAILBOX_DIR with restrictive
POSIX directory/file modes. Only local development/tests may use it. It has no HTTP
read route. Windows development files inherit host ACL behavior, so keep the directory
private. EMAIL_MODE=disabled returns 503 on register/forgot for all accounts. There
is no implemented SMTP/live email service; EMAIL_MODE=development is forbidden in
production. File delivery and DB commit are separate: a crash can lose a development
message, so register/forgot can be retried to issue a replacement. A future live mail
adapter needs durable delivery/retry semantics, not a claim that files are real emails.

GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI must all be set or all
empty. The redirect URI must exactly equal API_PUBLIC_URL +
`/api/v1/auth/google/callback` and be registered in Google Cloud. Consent screen and
test-user/production access are merchant-independent Google setup tasks.

Authlib handles authorization-code PKCE and OIDC claims; joserfc verifies RS256
against Google's fetched JWKS. Issuer, audience, expiry, issued time, nonce, subject
and authorized party are validated. OAuth state and browser cookie are bound in a
10-minute single-use PostgreSQL flow, consumed before token exchange. No access or
refresh tokens are persisted. On exchange failure, restart login; no replay.
Transient flow nonce/verifier are server-side and cleared when consumed.

An unauthenticated Google identity whose email matches an existing account returns
409 oauth_link_required. Log in to that verified account first, then start Google
to prove both identities; the callback requires matching verified email and a still
valid original session. Existing Google subject ownership cannot be reassigned.
New Google accounts require verified Google email. No fake login or fallback identity
is created when credentials/provider verification are absent.

Reference checks: [Google OIDC](https://developers.google.com/identity/openid-connect/openid-connect),
[Authlib web clients](https://docs.authlib.org/en/latest/oauth2/client/web/),
[FastAPI CORS](https://fastapi.tiangolo.com/tutorial/cors/). Installed Authlib 1.8.0
and joserfc 1.7.5 source interfaces were inspected, and local signed-token tests
exercise the real adapter. HTTPX fallback deprecation warnings are recorded in
implementation status; they do not imply a real Google credential test passed.

## Local request example

```sh
curl -c cookies.txt http://localhost:8000/api/v1/auth/csrf
# Store returned csrf_token locally; never paste real tokens into logs/issues.
curl -b cookies.txt -c cookies.txt \
  -H 'Origin: http://localhost:3000' -H 'X-CSRF-Token: <returned-token>' \
  -H 'Content-Type: application/json' \
  -d '{"email":"local-user@example.com","password":"a local-only long password"}' \
  http://localhost:8000/api/v1/auth/register
```

Read the local verification message privately, then POST its token to verify-email
using the same cookie/header convention; login and retain the replacement cookie
and CSRF token. Remove local cookie jars after use. Password/token bodies and OAuth
query strings must not appear in access logs. Supplied structured request logs only
record generated request ID, method and status, with safe generic error responses.

Audit logs reject UPDATE/DELETE/TRUNCATE via PostgreSQL trigger. This protects normal
application mutations, not a database owner/superuser who can alter schema; split
runtime and migration roles before production. Account deletion/audit retention and
scheduled expired-session/token cleanup are not implemented in Phase 1.
