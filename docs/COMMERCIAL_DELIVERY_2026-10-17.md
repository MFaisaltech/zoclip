# Commercial delivery execution - 2026-10-17

**Customer pay -> real AI -> download acceptance remains BLOCKED. READY FOR
LIVE-TEST APPROVAL: NO.** No paid inference, live payments, public signup or
public launch was authorized or enabled. This records completed work and the
remaining external dependencies, not commercial readiness.

## Completed and deployed

Production signup previously had no real email transport: development mailboxes
were forbidden in production, and disabled email prevented verification/reset.
Added authenticated SMTP over certificate-verified implicit TLS (465) or mandatory
STARTTLS (587), private single-use token links in URL fragments, sanitized delivery
failures, and production configuration checks. SMTP failure returns the same
generic response for eligible/unknown recipients and records a staff audit.
There is no plaintext fallback, transport debug logging or automatic retry.

Deployed the verified code to the existing protected server as
`staging-20261017-commercial1`, image
`zoclip-private-app@sha256:3e59812136e5b0790d75eed10a4e0d2ddd51c6b8b35a13b0c51d5a2aed0ce58e`.
This code-only rollout applied **no database migration**. The image now includes
the already-installed additive `c910a2e31f40` revision; future migrations must
retain it. Every database table's row-content digest matched before/after rollout.

Fresh backup `20261017T105640-b505ca51.json`, manifest SHA-256
`83040338dc9d4a04f06e13b740230c56e0b6c3a12167a8fa63583d2660534c93`, was
created with workloads stopped, copied off-server, and authenticated through EOF
before rollout. The PostgreSQL archive inventory includes both cap tables; the
streamed media archive includes the exact selected source hash. No plaintext
backup was extracted, recovery key uploaded, or existing database restored.

Seven containers are healthy. Read-only roots, dropped capabilities, network
isolation, runtime environment values, VPN socket/firewall and loopback proxy
bindings remain verified. The first comparison flagged environment-list ordering;
comparison of actual name/value maps confirmed no configuration-value change.
The initial off-server copy needed the existing protected-directory permission;
the exact returned backup was copied and authenticated before rollout continued.

Signed-out custom/current generated frontend URLs redirect to Vercel authentication.
VPN HTTPS liveness/readiness return 200; identity/private source/download return
401 anonymously; docs/admin metrics remain hidden. Public server IP ports
18443/18444/5432/6379 remain blocked. No frontend protection, DNS or unrelated
service changed. These are HTTP/access checks, not a new signed-in browser test.

The image scan matches the prior image: 1 critical and 212 high findings, none
with a fix identified by the existing cached vulnerability database. This is an
unchanged baseline, not a clean security scan or public-launch clearance.

## Isolated AI acceptance

Video `9cced2b6-cf08-410c-b653-318eef1dc5fe`, job
`6271dd2d-5d8e-4549-bc24-87c60cc68703`, duration 25,170 ms (26 seconds rounded),
SHA-256 `4e07da5b61752632ccc5027a9a0156e10b7efe4c6fdb70647796c745995deb80`.
The owner explicitly confirmed ownership/permission and audio-to-Deepgram /
transcript-to-Gemini consent in this session. That consent is not spending approval.

The original four operator file hashes and policy remain unchanged. A fresh
operator process after replacement of both workers reloaded the same PREPARED
entitlement: USD 0.10 maximum aggregate internal allocation; at most one Deepgram
transcription POST, one Gemini analysis POST, one clip and zero paid retries.
Approval and credential binding are absent; dispatches and committed spend are
zero. New-image staging checks rejected five unsafe database mutations inside
rolled-back savepoints and blocked two concurrent unapproved admissions.

Exactly one read-only credential/model GET per provider succeeded locally:
Deepgram `/v1/auth/token` HTTP 200 and Gemini model metadata HTTP 200, with
`generateContent` and sufficient advertised token limits. No media/transcript,
inference POST or credential material was logged/transmitted to staging services.
Deepgram inference permission was not established by the retained scope evidence.
No metadata check or public price is treated as account-specific rate evidence.

Published prices were reviewed at [Deepgram pricing](https://deepgram.com/pricing)
and [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing).
[Deepgram's March 5 change](https://developers.deepgram.com/changelog/2026/3/5)
states MIP participation no longer changes listed Pay As You Go/Growth rates.
The owner confirmed applicable account rates are **not yet verified**. The
entitlement remains closed until rate, account/model access and isolated credential
evidence are verified, followed by separate explicit spending authorization.

## Verification and limits

- **76 passed**, real disposable PostgreSQL 17 with mocked SMTP/provider HTTP:
  signup, verification, login, password reset, repeat login, email TLS/configuration,
  recipient-response privacy, existing authentication and private-staging gates.
- Ruff passed; mypy passed for 81 source files; git diff whitespace check passed.
- The prior unchanged operator package's 157 passing PostgreSQL/mocked-provider /
  real-FFmpeg tests remain applicable; not presented as a fresh paid-provider run.
- No real SMTP email, merchant sandbox payment, paid transcription/analysis or
  new real AI output was generated. Existing mocked MP4 evidence is not live AI.

## Remaining dependencies

1. Verify account-specific Deepgram/Gemini rates, pinned-model permissions and
   isolated credential delivery. Then present one exact bounded spending request.
2. Supply a transactional SMTP account/sender and verify actual delivery before
   customer registration or password recovery can be accepted in production.
3. JazzCash has no merchant sandbox or approved production account (owner-confirmed).
   The existing financial/payment tests use a ZoClip fictional mock protocol,
   **not JazzCash sandbox**. The JazzCash adapter and customer checkout remain
   disabled and incomplete. Merchant-approved current secure server-side checkout,
   callback/signature, inquiry/refund contracts, credentials, fee schedule and
   sandbox acceptance are needed before finishing that integration. Production
   checkout then needs separate owner activation authorization. No merchant secret
   will be placed in browser fields and no frontend success screen grants credits.
4. Contribution margins are scenario estimates until actual provider, compute,
   storage/bandwidth and merchant fee evidence is available. No trial/customer
   credits were granted; public AI and payment breakers remain closed.

Sanitized/private evidence is retained under ignored
`var/commercial-delivery-20261017/`; PostgreSQL test report:
`var/release-regression-59412155/results.xml`. Server rollout evidence is at
`/opt/zoclip-private/build-evidence/staging-20261017-commercial1/`. Existing
backup, previous image and previous release metadata are retained for a compatible
code rollback without a schema downgrade.
