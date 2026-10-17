# Reviewer access — offline verification, 2026-10-15

Owner confirmed staging is not deployed and requested offline preparation checks.
No browser/VPN connectivity or live certificate validation is claimed. No service,
firewall, DNS, keys, production accounts or infrastructure was installed/modified.
Test-only writes used fresh preserved schemas in the separate mock PostgreSQL DB.
Acceptance database/evidence/guards and AI/spending/payment settings are untouched.

| Requirement | Offline evidence | Actual staging status |
|---|---|---|
| Individual reviewer VPN credentials | Per-device private-key placeholders, unique server peer/32 and client server-only route;25 renderer cases pass | Keys not generated; handshake/revocation unverified |
| Private API, SSH for operators | Existing Docker loopback publication guard; VPN-IP/device-bound host socket and dedicated input/forward policy | Linux syntax, isolation and reboot tests pending |
| Browser-to-API | Six mocked browser-client probe cases: exact HTTPS origin, credentialed readable readiness response, redirects denied, failure/timeout without retries | Real browser/VPN/CORS permission check pending |
| HTTPS | Configuration requires canonical same-site HTTPS origins;18 staging config/header cases pass | Real chain/hostname/expiry/TLS handshake pending |
| Authentication/admin | Real PostgreSQL-backed offline invite/login/role test: no auto-login, Secure/HttpOnly/SameSite=Lax host-only cookie, customer admin403/admin success | Named staging reviewer login pending |
| CSRF | Same server test rejects missing token, stale pre-login token and untrusted Origin; authenticated session rotation succeeds only with valid current token | Actual browser CSRF test pending |

Focused results:27 backend cases and36 frontend cases pass. The strengthened
authenticated session/CSRF case was rerun successfully after adding those assertions.
Ruff check/format passes for the changed test. Two existing HTTPX deprecation
warnings remain. No build, heavy full suite, browser automation or paid provider IO.

Relevant commands/tests:

- `pytest tests/test_wireguard_preparation.py`
- `pytest tests/test_private_staging.py::test_cors_exact_origin_and_admin_unauthenticated_denial`
- `pytest tests/test_staging_accounts.py::test_http_invite_csrf_login_admin_and_customer_denial`
  using the saved separate mock DB, never a runtime/acceptance/production target.
- `node tests/staging-access.test.mjs`
- `node tests/auth-api.test.mjs`
- `node tests/staging-config.test.mjs`

Future approved target verification follows
[WIREGUARD_REVIEWER_ACCESS.md](WIREGUARD_REVIEWER_ACCESS.md): reviewed subnet/peers/
UDP source rules, per-device keys, valid owned hostname certificate and Vercel
protection. After approved deployment, connect an authorized device, verify
`/private-access` in its actual browser, sign in through existing authentication,
verify cookie/CORS/admin permission behavior and reject a protected POST with
missing/incorrect CSRF. Use only own session rotation for a positive CSRF mutation,
never financial/policy/provider/job endpoints. Session rotation changes the user's
session/CSRF credentials; reload afterward. Disconnect/revoke VPN and verify API
access denied, including public IPv4/IPv6 exposure and other-host/service isolation.

Preparation: **PASS**. Actual private staging access: **NOT VERIFIED — not deployed**.
Installation, keys, infrastructure changes and deployment still require approval.
