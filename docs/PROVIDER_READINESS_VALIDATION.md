# Provider-readiness validation — 2026-10-13

Subsequent [one-shot acceptance preparation](ONE_SHOT_ACCEPTANCE.md) restores the
isolated services and implements/verifies the durable guard and native driver.
The service-unavailable and guard-unimplemented findings below are historical.
The latest handoff now also records English confirmation, configured model names
and one verified isolated local customer. Provider access/version, financial
configuration/admin provisioning and live-approval blockers remain; AI stays disabled.

Scope: offline readiness only. M1–4 were preserved. No provider request, AI
enablement, billing/payment configuration change, service start, database reset,
deployment, commit or push was performed. This document is a proposed acceptance
specification, not permission or a command to execute a paid test.

## Findings

Both keys are present in ignored backend configuration; their values were never
printed. AI_ENABLED remains false. GEMINI_MODEL, DEEPGRAM_MODEL and
DEEPGRAM_VERSION remain empty. FFmpeg and ffprobe resolve. The current short-test
caps are 16 MiB source/output, one 16,000-byte analysis chunk, one candidate,
2,048 output tokens, 120-second provider timeout and 20 GiB storage headroom.

Gemini adapter: fixed v1beta models/<model>:generateContent endpoint,
x-goog-api-key header, JSON content/one candidate, temperature 0.2,
thinkingBudget=0, application/json and generated Moments responseJsonSchema.
Gemini 2.5 Flash-Lite supports structured output and zero thinking budget.
However, the official model page limits 2.5 access to prior active users.
Account/model access and credential authentication cannot be established offline.
Current REST documentation marks older output-format fields as deprecated in
favor of responseFormat; this alone does not prove the existing 2.5 request is
rejected. No adapter migration was made. Unsupported schema constraints must
still be enforced by local Pydantic validation, not assumed enforced remotely.

Deepgram adapter: fixed /v1/listen POST, Authorization: Token, streamed WAV body,
model/version/language parameters, punctuation, disabled diarization/utterances,
and mip_opt_out=true. This matches the documented Nova prerecorded interface.
English nova-3 is the intended monolingual choice.

Version result: Deepgram documents latest as the default and supports explicit
version strings. That is not evidence of a stable English batch version pin.
Public metadata examples include a streaming-only Nova-3 entry and illustrative
versions; they must not be copied as an account-verified batch pin. Obtain the
version from account/support evidence, or separately authorize metadata discovery
and select a Nova-3 English entry with batch=true. No metadata API was called.
Settings requires a nonempty version but does not itself reject latest/beta;
the readiness checker flags moving aliases. Keep DEEPGRAM_VERSION unset until
reviewed rather than treating a moving alias as reproducible configuration.

## Offline evidence and error handling

- Selected existing tests: 19 passed, 45 deselected, two existing HTTPX dependency
  warnings. Tests covered configuration refusal, OpenAPI consistency, transcript
  alignment/chunking, auth headers/no redirects, malformed/oversized/timeout
  responses and token accounting. No PostgreSQL fixtures were selected.
- Target-model MockTransport check: two simulated requests, zero external
  requests; verified Nova-3 parameters, Gemini model path/body/auth, response JSON
  parsing and usage accounting. Its Deepgram version was explicitly a mock-only
  placeholder, not a proposed live version.
- External socket connects and DNS were blocked in both offline checks; live
  keys were excluded from the test process. The initial restricted pytest run
  failed on Windows temporary-directory permissions. The same selected tests
  passed with normal local permissions; no database or provider access occurred.
- TLS verification is enabled, redirects and environment proxy trust disabled.
  Connect timeout is 10 seconds; other HTTPX operation timeouts are 120 seconds.
  Deepgram responses are capped at 8 MiB, Gemini at 256 KiB.
- The monotonic response deadline is checked while chunks arrive. HTTPX timeouts
  are operation timeouts, so 120 seconds is not a strict total wall-clock bound
  for every stalled-request case. A supervised test deadline is still needed.
- Invalid JSON becomes a null body and fails worker validation. Non-STOP Gemini
  responses, invalid suggestions and transcript timings are rejected. Paid-call
  receipts/checkpoints and UNKNOWN spend stop blind retries after uncertain IO.
  Explicit 429 rejection can be requeued for another provider request. This
  differs from an unknown outcome and matters for an exactly-two-request test.

## Local services and source

Read-only probes targeted only the configured isolated loopback readiness
services: PostgreSQL 55439 timed out; Redis 56389 returned ConnectionError.
No services were started or database/Redis contents changed. Current schema,
rates, policy, balances and pending jobs therefore remain unverified; earlier
successful preparation records are historical evidence.

F: has about 85.43 GiB free; D: 21.28 GiB and C: 4.61 GiB at inspection. The
configured F: media root has sufficient raw free space for the short-test caps,
but outstanding reservations cannot be checked while PostgreSQL is unreachable.
The last available-RAM observation was about 1.07 GiB; do not infer worker/build
capacity or start Chrome/builds from free disk alone.

Use the existing separate input test-media/sample-live-test.mp4: 2,828,785 bytes,
previously probed 26.735042 seconds, 720x1280 H.264/mono AAC. Fresh SHA-256 matches:
281841b42e88e04b3eaf4f361111550e4517e477c30f069e754bb5ee884bc3d0.
The earlier readiness record contains the user's source-rights confirmation;
the private F:/ZoClip-LiveAI/source-attestation.json exists and its
live_processing_approved flag remains false. Reconfirm spoken language/content
privately before execution; source-rights consent is not paid-test approval.

## Exact configuration checklist — proposed, not applied

Backend environment:

```text
AI_ENABLED=false
GEMINI_MODEL=gemini-2.5-flash-lite
DEEPGRAM_MODEL=nova-3
DEEPGRAM_VERSION=<verified English batch version; currently unresolved>
DEEPGRAM_LANGUAGE=en
AI_APPROVED_LANGUAGES=["en"]
DEEPGRAM_DIARIZE=false
DEEPGRAM_UTTERANCES=false
DEEPGRAM_MIP_OPT_OUT=true
AI_MAX_CHUNKS=1
AI_CHUNK_BYTES=16000
AI_MAX_CANDIDATES=1
AI_MAX_OUTPUT_TOKENS=2048
AI_CALLS_PER_MINUTE=2
AI_PROVIDER_TIMEOUT_SECONDS=120
```

Keep existing private keys, media root and binary paths; do not copy them into
frontend variables. These lines are a checklist, not an applied env change.
Provider enablement requires all keys/model/version fields plus AI_ENABLED;
keep the persisted flag false. A future reviewed worker-only temporary enablement
requires explicit approval and working DB cost controls. No payment flag changes.

All five versioned cost-rate rows are mandatory PostgreSQL data, not substitutes
in .env. Proposed standard PAYG rates, subject to actual account confirmation:

| Component | Model binding | Unit USD | max_units for this test |
|---|---|---|---|
| deepgram | deepgram_rate_label(settings), fingerprinting model/version/options | 0.0043 per minute | 1 |
| gemini_input | gemini-2.5-flash-lite | 0.0000001 per token | 36000 |
| gemini_output | gemini-2.5-flash-lite | 0.0000004 per token | 2048 |
| render | reviewed local allocation label | actual positive CPU-second rate required | 520 |
| storage | reviewed local allocation label | actual positive GiB-day allocation rate required | 1 |

Do not fabricate local allocation prices. Deepgram's March 5, 2026 pricing update
says PAYG/Growth MIP opt-out no longer changes listed pricing; confirm the actual
account tier rather than applying an old opt-out surcharge.

Proposed BudgetLimits: per_job_usd, user_daily_usd, user_monthly_usd,
global_daily_usd and global_monthly_usd each decimal string "0.05";
max_open_reservations=1; rate_ids=the five real reviewed rate UUIDs;
input_tokens_per_second=1000; max_output_tokens=2048;
render_cpu_seconds_per_output=520; storage_gb_days_per_output=1;
max_attempts_per_job=5. Keep the circuit breaker open during preparation.
Five is an expense-row cap (Deepgram + Gemini input/output + render/storage),
not an exactly-one-call-per-provider guarantee. Rates/policy were not applied.

An active verified test account must already have usable plan consumption rules
and enough legitimate credits. For this 27-second quote, one output, zero edits,
captions/reframing enabled, required credits are:
credits_per_minute + credits_per_output + captions_credits + reframe_credits.
Read these integer values from the actual plan and obtain the normal server
quote; do not invent a credit conversion, mint a balance or alter payment/catalog
configuration for this validation. Those current DB values remain unavailable.

## Cost and bounded acceptance specification

For one transcription and one analysis, without free-tier/discount assumptions:

- Deepgram: one conservatively rounded-up minute * USD 0.0043 = USD 0.0043.
- Current schema-body overhead: 1,354 bytes; prompt prefix: 488 bytes. A 16,000-byte
  word chunk plus JSON escaping and the worker's allowance gives 35,354 bounded
  input units. Round upward to 35,358 for this plan.
- Gemini: 35,358 * 0.0000001 + 2,048 * 0.0000004 = USD 0.004355.
- Provider-only conservative admission estimate: **USD 0.008655**.
- Add **520 * actual render CPU-second rate + 1 * actual storage GiB-day rate**.
  These must fit the remaining USD 0.041345 of the proposed USD 0.05 policy.

The initial quote estimates input from source seconds; the AI worker separately
recalculates serialized-body exposure before dispatch. The USD 0.05 controls must
therefore cover actual admitted exposure, not rely only on the quote estimate.
This is an admission estimate, not a provider-invoice guarantee. The app records
unexpected actual usage and opens the breaker; an already-sent request cannot be
retroactively capped by that breaker. Tax/FX and unrelated account usage are not
included. No exact total can be finalized without actual local allocation rates.

After blockers and explicit approval are resolved, the minimum acceptance is:

1. Recheck sample hash/consent, model access/version, isolated service identity,
   migrations, empty pending work, reviewed rates/policy, available credits and
   real disk/RAM. Use one dedicated account and one fixed source/job.
2. Offline-verify a run-scoped executor/transport guard allowing at most one
   Deepgram POST and one Gemini POST, bound to that job. A rejected/ambiguous
   request must stop, without resetting the guard or making a new job. Existing
   budgets and idempotency do not replace this guard. It is not implemented or
   verified by the current generic live smoke helper: this is a live-test blocker.
3. Use the normal owned upload/validation, quote, explicit credit confirmation
   and job pipeline. No URL ingestion is needed. Process one analysis chunk;
   oversize transcript or empty/invalid suggestions stops the test, no retry.
4. Review the real word-timed transcript and one coherent grounded suggestion;
   approve one classic-caption/center-framed clip. Render one 720x1280 MP4,
   privately download it and review caption timing/audio/framing.
5. Verify exactly two provider dispatches, recorded usage/rate bindings, one
   RESERVE and one SETTLE, zero reserved remainder, and valid owned output.
   Failure must show its real state and release credits without losing sunk costs.
6. Stop the sole executor and remove temporary enablement immediately. Preserve
   receipts/data; no second worker, broad scheduler, automatic provider retry,
   second generation, re-export or restarted one-shot allowance.

The existing ai_live_smoke.py only starts generation zero and checks suggestions;
it depends on external dispatch for later generations and does not render/settle.
Normal worker/maintenance entrypoints contain Linux /tmp paths and broad queue/
cleanup behavior. A narrowly scoped native Windows execution path must be reviewed
and mock-verified first; do not substitute a simulator worker for a live worker.
No live executor was started in this validation.

## Official documentation reviewed

- [Gemini model and account availability](https://ai.google.dev/gemini-api/docs/models/gemini-2.5-flash-lite)
- [GenerateContent thinking budget](https://ai.google.dev/gemini-api/docs/generate-content/thinking)
- [GenerateContent REST contract](https://ai.google.dev/api/generate-content)
- [Structured output limits](https://ai.google.dev/gemini-api/docs/structured-output)
- [Gemini standard prices](https://ai.google.dev/gemini-api/docs/pricing)
- [Deepgram prerecorded contract](https://developers.deepgram.com/reference/speech-to-text/listen-pre-recorded)
- [Deepgram version semantics](https://developers.deepgram.com/docs/version)
- [Deepgram model metadata](https://developers.deepgram.com/guides/fundamentals/model-metadata)
- [Deepgram prices](https://deepgram.com/pricing)
- [MIP pricing update](https://developers.deepgram.com/changelog/2026/3/5)

Readiness: offline validation PASS; live end-to-end execution BLOCKED by services,
account model access, the exact Deepgram version, unapplied/unverified DB rates/
budgets/credits, local allocation rates, the native one-shot execution guard and
explicit paid-test approval. Wait for approval; no live provider call is authorized.
