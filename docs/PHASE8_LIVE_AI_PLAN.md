# Safe live Gemini/Deepgram preparation — not executed

Milestone 4 keeps live AI disabled. This plan does not authorize paid calls,
deployment, VPS changes or access to existing user data. Mock validation must pass
first, followed by explicit user approval for a concrete source, model/version,
maximum cost and run window. No live credentials were read or changed during M4.

## Verified implementation

`src/zoclip/ai/providers.py` uses the locked HTTPX REST transport, not a vendor
SDK. Deepgram receives extracted mono 16 kHz WAV at
`https://api.deepgram.com/v1/listen`, with server-side Token authorization.
Gemini receives bounded timed transcript text at the fixed Google
`v1beta/models/<GEMINI_MODEL>:generateContent` destination using x-goog-api-key.
No video or key is sent by the browser. Redirects, implicit retries and environment
proxies are disabled; responses/timeouts are bounded. Provider usage, budget
admission and unknown-outcome handling remain in the existing worker.

The adapter currently sends JSON-schema structured output and
`thinkingConfig.thinkingBudget=0`. Current official REST docs still describe these
fields; response-format fields include deprecation guidance. The newer guide
examples use newer APIs/configuration. This does **not** prove that an arbitrary
current model accepts the existing body. A compatible account-accessible pinned
model must be selected and reviewed before the first paid request. No automatic
provider migration or claim of live compatibility was made in M4.

Official references checked on 2026-10-13:

- [Gemini key setup/security](https://ai.google.dev/gemini-api/docs/api-key).
- [Gemini generateContent REST fields](https://ai.google.dev/api/generate-content).
- [Gemini structured output](https://ai.google.dev/gemini-api/docs/structured-output)
  and [thinking controls](https://ai.google.dev/gemini-api/docs/thinking).
- [Deepgram authentication](https://developers.deepgram.com/guides/fundamentals/authenticating)
  and [pinned versions](https://developers.deepgram.com/docs/version).

## Exact safe configuration steps

1. Create a separate test project/key in each provider's official console. Use a
   Gemini key restricted to the Gemini API and the minimum Deepgram project
   permissions needed for transcription. Apply available project usage/spend
   controls and record the approved maximum exposure. Keep keys out of chat,
   shell command arguments/history, screenshots, logs and source files.
2. Stop the local AI worker/dispatcher before preparing live settings. Review
   existing QUEUED/WAITING_ENGINE jobs: enabling AI can resume them. Use a new
   isolated live-test database/media directory with one authorized test account;
   never point live testing at the mock browser fixtures or an existing account DB.
3. Confirm `backend/.env` is ignored with `git check-ignore .env`. Edit it locally
   in a private editor, or inject secrets into the backend process through the
   approved secret manager. Do not alter `.env.example`. Set the exact names
   below, keeping AI_ENABLED=false during preparation. Frontend environment
   configuration contains only NEXT_PUBLIC_API_ORIGIN; never prefix keys with
   NEXT_PUBLIC_ or store them in frontend files/browser storage.

```dotenv
AI_ENABLED=false
DEEPGRAM_API_KEY=<private key, entered locally>
DEEPGRAM_MODEL=<reviewed account-accessible prerecorded model>
DEEPGRAM_VERSION=<reviewed concrete version, not latest>
DEEPGRAM_LANGUAGE=en
AI_APPROVED_LANGUAGES=["en"]
DEEPGRAM_DIARIZE=false
DEEPGRAM_UTTERANCES=false
DEEPGRAM_MIP_OPT_OUT=true
GEMINI_API_KEY=<private restricted key, entered locally>
GEMINI_MODEL=<reviewed model compatible with this REST body>
```

4. Keep optional paid features off unless explicitly budgeted. Verify the chosen
   Deepgram model/version/language and opt-out pricing; verify Gemini's structured
   schema and zero-thinking-budget support. The application reads GEMINI_API_KEY,
   not GOOGLE_API_KEY. Defaults/caps for AI_PROVIDER_TIMEOUT_SECONDS,
   AI_CALLS_PER_MINUTE, AI_CHUNK_BYTES, AI_MAX_CHUNKS, AI_MAX_OUTPUT_TOKENS,
   AI_MAX_CANDIDATES and clip lengths are in `.env.example` and Settings. Do not
   copy the browser simulator's fictional models/rates into live configuration.
5. Validate configuration offline, without printing settings or secrets:

```powershell
.venv/Scripts/python.exe -c "from zoclip.core.config import Settings; s=Settings(); assert not s.ai_enabled; assert s.deepgram_api_key.get_secret_value() and s.gemini_api_key.get_secret_value(); assert s.deepgram_model and s.deepgram_version and s.gemini_model; print('Required backend configuration is present; AI remains disabled')"
```

6. Through the existing trusted operator configuration (not a new frontend admin
   workflow), configure approved plan rules, audited test-account credits and
   versioned rates/budgets. Deepgram's rate model must equal
   `zoclip.ai.worker.deepgram_rate_label(settings)`; Gemini input/output rate
   models must equal GEMINI_MODEL. Configure per-job, user daily/monthly, global
   daily/monthly limits, token/attempt bounds and breaker state. Include retry/
   unknown exposure. Rendering also requires reviewed CPU/storage rate versions
   and sufficient CPU/retention envelopes. Missing rates/budgets fail closed.
7. Record consent for audio to Deepgram and transcript to Gemini, retention/data-use
   terms and the licensed source. Confirm actual free disk meets configured
   headroom plus reservations. **Never use the synthetic-capacity browser API or
   Simulator for live verification.** No live readiness is inferred from mock QA.

## Proposed controlled test after explicit approval

Use one licensed 20–30 second English clip with clear speech, one output, no extra
features, at most one selected export and no automatic quality reruns. Approve
the exact model/version, options and bounded USD exposure first; do not invent a
price here. Include the existing provider token limits/attempt envelope and the
provider's actual account-specific rates in that approval.

Only after approval: enable AI_ENABLED=true in the isolated backend environment,
start the reviewed local worker/scheduler with those same settings, upload the
source, obtain the actual quote and explicitly confirm it in the UI. Observe one
job through EXTRACTING_AUDIO/TRANSCRIBING/ANALYZING to SUGGESTIONS_READY. Review
word alignment, omissions/hallucinations, selected bounds and usefulness. Approve
one clip, render it locally, download the private MP4 and inspect audio sync,
captions and framing. Check exactly one reservation/settlement and no duplicate
provider usage after a page refresh. Record wall/queue/provider/render timing,
actual usage/cost, output metadata and a private quality rubric. Do not infer
120-minute performance from this small test.

The existing optional `scripts/ai_live_smoke.py` additionally requires both
`--allow-paid` and `ZOCLIP_ALLOW_PAID_SMOKE=1`; it is never run by automated tests.
Those switches are safeguards for that script, not a global guard around normal
RQ workers. Do not enable AI or start a live worker merely to validate key presence.

Stop on invalid schema/model, auth/rate errors, unknown outcomes, budget admission
failure, poor quality or unexpected spend. Cancel the job through the owned API,
inspect its safe state/usage records, and never blindly retry an uncertain paid
request. Reconcile exposure before considering another approved run. Afterwards
disable AI again, stop only the test processes and revoke temporary keys. Retain
the minimal private evidence and remove test media through the existing lifecycle.

**Not run:** live provider requests, subjective live quality/speed, representative
capacity benchmarks, paid credentials/configuration, deployment or VPS changes.
