# One-shot preparation complete — 2026-10-14

**Ready for explicit one-shot live-run authorization.** No live inference or
breaker opening occurred. This is local preparation readiness, not production
readiness or a guarantee of provider acceptance/charges.

## Completed under the latest approval

- Gemini model: `gemini-3.1-flash-lite`. Its request uses
  thinkingConfig.thinkingLevel=minimal, omits temperature for the documented
  default 1.0, and retains one candidate, 2048 output tokens, JSON MIME and the
  existing Moments responseJsonSchema. Legacy model request behavior is retained
  outside this approved model. Acceptance/provisioning model guards now require
  3.1; usage continues counting residual/thinking output tokens.
- Made exactly **one** public unauthenticated GET to
  `https://api.deepgram.com/v1/models`, HTTP 200. No Authorization, audio, POST,
  redirects or retries. A durable consumed marker prevents repeating discovery.
  Public response and receipt remain privately preserved.
- Selected fixed version **2025-07-31.0**, returned entry UUID
  `2187e11a-3532-4498-b076-81fa530bdd49`: name=general,
  canonical_name=nova-3-general, architecture=nova-3, batch=true,
  streaming=false, multilingual=false, languages includes en. It is the newest
  fixed general/monolingual English batch entry in the actual response. The
  older 2024-12-20.0 record and multilingual/medical/pharma records were excluded.
  Version is taken from its version field, not its UUID or a documentation example.
  Existing request remains model=nova-3, language=en, version=2025-07-31.0,
  diarize=false, utterances=false, mip_opt_out=true. Public model/version contract:
  [model options](https://developers.deepgram.com/docs/model),
  [version parameter](https://developers.deepgram.com/docs/version).
- Private .env changed only GEMINI_MODEL and DEEPGRAM_VERSION, in place to
  preserve ACL. Every other dotenv value, including keys/payment/trial settings,
  was compared unchanged. AI_ENABLED=false. No keys printed/shared.
- Original bootstrap manifest and approved sheet are unchanged. Added a new
  private amendment linked to the same admin/customer, approved addendum hash,
  timestamp/operator and user authority. The provisioning command checks both
  original and amendment hashes plus actual metadata digest/version/UUID before
  financial writes. No historical audit evidence was rewritten.

## Installed isolated finances

Installed through existing authenticated admin RBAC/CSRF/reason/idempotency
routes in `127.0.0.1:55439/zoclip_live_readiness` only. No production writes,
new admin/customer/credit grant, paid entitlement or billing changes.

| component | unit USD | maximum units | binding |
|---|---:|---:|---|
| deepgram | 0.0043/minute | 1 | fingerprint of actual pinned Nova-3/en options |
| gemini_input | 0.00000025/token | 36000 | gemini-3.1-flash-lite |
| gemini_output | 0.0000015/token | 2048 | gemini-3.1-flash-lite |
| render | 0.00001/cpu_second | 520 | local-acceptance-cpu-assumption-v1 |
| storage | 0.001/gb_day | 1 | local-acceptance-storage-assumption-v1 |

All five USD budget dimensions are **0.05** (job, user daily/monthly, global
daily/monthly), max_open_reservations=1, max_attempts_per_job=5,
input_tokens_per_second=1000, max_output_tokens=2048, render envelope=520,
storage envelope=1. The policy uses the five actual returned rate UUIDs and
**breaker=true**. Five means expense rows, not five provider calls.

Used approved published standard rates under the user's latest conditional
installation authorization, not a claim of authenticated account-specific price
verification. Rate evidence explicitly records account_specific_price_verified=false.
Render/storage remain approved internal assumptions. Conservative accounting
envelope **USD 0.022572**, initial quote estimate USD 0.020322; neither guarantees
the provider invoice. Sources: [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing),
[Deepgram pricing](https://deepgram.com/pricing). Existing circuit breaker and
unknown-expense accounting remain enforced.

Read-only postconditions: five rates, one policy and six matching immutable
financial audit events; existing customer stays customer; available=1,
reserved=0; exactly one original ADMIN_ADJUST +1 ledger row; zero active
authenticated sessions, jobs, outbox entries, AI inference requests, spend
attempts and provider usage. Actual UUIDs/audit IDs/policy limits were captured
in a private financial receipt. No credit allowance was repeated.

## Verification and artifacts

`scripts/verify_acceptance_offline.py`: **70 passed**, 34.95 seconds. Includes
17 focused new cases for Gemini transport/body/thinking usage, revised guards,
metadata selection/ambiguity and discovery 200/302/429/timeout/restart refusal;
the prior 53 checks also passed. Mock HTTP transports, masked keys and blocked
external networking only; PostgreSQL mock schemas forward-migrated and preserved.
No reset/drop. Evidence:
`var/acceptance-guard-tests-44398057dcc643aa951ce9a4d59d625e/results.xml`.
Ruff and mypy pass (76 application/driver/provisioner/discovery/verifier files).
Existing two HTTPX dependency deprecation warnings remain.

Private artifacts under ignored, current-user/SYSTEM-only
`var/live-ai-readiness/acceptance-admin/`:

- deepgram-models-entered.json / deepgram-models-response.json
- amendment-2026-10-14.json / provider-evidence.json
- financial-receipt-2026-10-14.json

New executable: `scripts/discover_deepgram_once.py` (permission consumed;
**do not rerun or remove its marker**). Applied financial command:
`.venv/Scripts/python.exe scripts/provision_acceptance.py --phase rates-policy`.
No frontend build/browser, deployment, commit or push.

## Remaining live gate

No known model-version/financial preparation blocker remains. Public metadata
and the user's account-availability evidence do not authenticate inference keys
or prove successful provider execution; that is what the approved live test
will establish. Explicit live authorization must also permit the audited breaker
opening and private strict-boolean live attestation. Neither is done now.

Use the existing [one-shot execution procedure](ONE_SHOT_ACCEPTANCE.md#exact-commands-and-stop-conditions)
after that authorization. Persisted AI stays false; only the guarded AI phase
uses enabled process-local settings with all opt-ins. Recheck services, sample,
no competing jobs and resources immediately before running. Latest available
RAM was about 1.21 GiB, commit headroom 2.28 GiB; keep to the small native test,
avoid frontend builds/browser and stop on resource failure. No automatic retry,
replacement job, marker reset or model/version fallback is authorized.
