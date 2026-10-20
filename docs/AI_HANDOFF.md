# Phase 4 AI transcript and suggestions

2026-10-19: [local faster-whisper](LOCAL_WHISPER.md) is now the default adapter;
Deepgram is an explicit inactive fallback. Gemini still receives transcript data.
Historical Deepgram-specific sections below describe that fallback. API and
TranscriptData shapes and paid authorization requirements remain unchanged.

Local Whisper now checkpoints bounded audio windows across RQ claims. Defaults
are 120-second cores with one second of neighboring context on each side;
settings are pinned per job. Word times in the existing API remain absolute
source seconds. Each claim records its local receipt before advancing, so retry
and lease recovery reuse completed work. An unfinished local window can retry
within the existing failure budget; this does not authorize paid redispatch.
See [local operating details](LOCAL_WHISPER.md).

Phase 4 produces private transcripts and suggestions, not rendered clips. Live
provider acceptance remains unverified. AI is disabled by default. Existing
authentication, CSRF, credits, ingestion and durable outbox contracts still apply.

Checkpoint gates: **local mock/fixture PASS; real Deepgram/Gemini provider PENDING;
production readiness NOT APPROVED**. A user-authorized local checkpoint based on
mock/fixture evidence does not satisfy real-provider acceptance.

## API and lifecycle

Submit an owned READY source through `POST /api/v1/videos/{id}/generate` with a
current quote and Idempotency-Key. The transaction reserves customer credits and
creates the PROCESS job/outbox together. A configured worker advances through
EXTRACTING_AUDIO, TRANSCRIBING and ANALYZING to SUGGESTIONS_READY. Unconfigured AI
remains WAITING_ENGINE; maintenance resumes waiting jobs when configuration is
enabled. Source validation alone is not AI success. Progress remains null.

`GET /api/v1/videos/{id}/transcript` returns validated text/words, confidence,
absolute start/end seconds, optional speaker and utterance boundaries, model,
language and job reference. `GET /api/v1/videos/{id}/suggestions` returns the
selected moments and `rendered: false`. Both select the latest PROCESS job by
default and accept an optional owned `job_id`; suggestions accept limit 1..20.
Another owner's resource and a deleted/expired source return 404. Responses omit
storage paths, raw provider receipts, keys, expense IDs and private checkpoints.

Illustrative **synthetic** suggestion response (IDs omitted here for brevity;
actual DTOs and required UUID fields are in openapi.json):

```json
{
  "state": "SUGGESTIONS_READY",
  "stage": "SUGGESTIONS_READY",
  "error_code": null,
  "rendered": false,
  "items": [{
    "rank": 1, "start_sec": 0.0, "end_sec": 2.5,
    "title": "Useful ideas", "hook": "Learn together",
    "reason": "A coherent insight", "score": 85,
    "keywords": ["learning"], "hashtags": ["#learning"]
  }]
}
```

Suggestions hold credits for a future deliverable; no SETTLE occurs in Phase 4.
Cancellation/final failure releases once. Maintenance cancels WAITING_ENGINE and
SUGGESTIONS_READY holds after 24 hours without an update. This provisional policy
must be disclosed before public use. Rendering/editor/export APIs are Phase 5.

## Providers and configuration

Reviewed against official documentation on 2026-10-10:

- [Deepgram prerecorded API](https://developers.deepgram.com/reference/speech-to-text/listen-pre-recorded)
  and [local audio guide](https://developers.deepgram.com/docs/pre-recorded-audio).
  Fixed destination POST `https://api.deepgram.com/v1/listen`, streamed mono 16kHz
  PCM WAV, Token authorization header, punctuation enabled, configured language,
  model and version. [Version selection](https://developers.deepgram.com/docs/version)
  supports explicit versions: use a reviewed accessible concrete version rather
  than `latest` for reproducible caches. No model/version is seeded or claimed
  accessible to this account. Optional diarization/utterances default off.
  Model-improvement opt-out defaults true and can affect pricing.
- [Gemini generateContent REST reference](https://ai.google.dev/api/generate-content)
  and [structured output guidance](https://ai.google.dev/gemini-api/docs/structured-output).
  Fixed Google HTTPS destination, API key header, text-only timed transcript
  context, one candidate, JSON schema, bounded output tokens. The current adapter
  sends `thinkingBudget: 0`; select a model that supports that setting. Arbitrary
  model compatibility and account availability are not promised. Returned usage
  includes thinking/residual tokens at the output rate, without free-token or
  cached-token discounts. A compatibility rejection stops safely for review.

No vendor SDK was added: HTTPX's locked REST transport is used without implicit
retries, redirects or environment proxy settings. Dependencies remain in uv.lock.
The reviewed REST fields still exist; some Gemini formatting fields are marked
deprecated in the reference. Recheck compatibility before live enablement.

Environment variables are documented in `.env.example` and passed by Compose:
AI_ENABLED, DEEPGRAM_API_KEY/MODEL/VERSION/LANGUAGE, AI_APPROVED_LANGUAGES,
DEEPGRAM_DIARIZE/UTTERANCES/MIP_OPT_OUT, GEMINI_API_KEY/MODEL, FFMPEG_BINARY,
AI_PROVIDER_TIMEOUT_SECONDS (1..180, default 120), AI_CALLS_PER_MINUTE (default 6),
AI_CHUNK_BYTES (default 16000), AI_MAX_CHUNKS (32), AI_MAX_OUTPUT_TOKENS (2048),
AI_MAX_CANDIDATES (10), AI_MIN_CLIP_SECONDS (15), AI_MAX_CLIP_SECONDS (90).
Only English is approved by default. More languages need model/rate review.
No keys or prices belong in source, fixtures, logs or chat.

Staff must configure immutable CostRate versions and all budget dimensions using
the existing audited admin APIs. Deepgram rate model is
the exact return value of `deepgram_rate_label(settings)` (a `deepgram:` prefix
and options fingerprint). It binds model,
version, language, diarization, utterances and opt-out. Gemini input/output rate
models must exactly equal GEMINI_MODEL. Rate mismatch, missing policy/rates,
disabled account, final reservation, budget exhaustion and open breaker block
new paid execution. No commercial rate is invented. Deepgram uses conservatively
rounded-up whole minutes; Gemini reserves an input byte upper bound plus schema
allowance and the configured output ceiling. Rates must include applicable paid
options. Estimates are conservative, not provider invoices or profit guarantees.

## Durability, retries and cancellation

Each network side effect requires a freshly committed PostgreSQL expense
admission with an owned HELD credit reservation. Gemini input/output dimensions
are admitted together or rolled back together. All per-job/user/global daily and
monthly budgets count in-flight, unknown, retry and sunk costs. Recorded overruns
remain visible and open the circuit breaker. Redis is delivery only.

Each RQ claim executes at most one provider call. Local stage/recovery retries
and authenticated 429 rejections use bounded exponential equal jitter. There are
at most three rejected attempts per exact provider cache key and three local
failure recoveries; the configured expense attempt cap also bounds total work.
The global provider admission limit delays dispatch for 60 seconds when full.
HTTP 5xx, redirects, auth errors, missing usage and timeouts do not prove zero
cost: they retain UNKNOWN exposure and stop automatic paid execution. No blind
retry occurs for an uncertain call. Reconciliation requires trustworthy evidence;
there is no automatic provider invoice reconciliation or new admin evidence UI.

Provider responses are bounded and fsynced to private UUID receipts before DB
checkpoint. A crash after receipt persistence recovers without another paid call.
A crash without evidence remains UNKNOWN. Cancellation checks run before
extraction, between stages, during FFmpeg and immediately before dispatch. A
proven unsent admission is voided. Cancellation during a remote call cannot recall
it: returned usage is recorded, missing evidence stays UNKNOWN, then credits
release. Worker recovery and deletion reconcile receipts before privacy erasure.
One fixed 900s lease fences workers; RQ timeout is 660s. No exactly-once remote
billing or instantaneous remote cancellation guarantee is made.

Caches are scoped to owner, source ID/digest, audio transform version, provider
options/model and exact prompt/body version. Unchanged repeated jobs reuse results;
cross-owner deduplication is intentionally absent. Changed source/options/prompt
need a new budget admission. Transcript chunks use absolute word times and bounded
overlap. Pydantic rejects malformed/giant/nonfinite data; selection clamps to real
words, enforces duration/count and removes overlaps. Silence/empty/invalid output
fails clearly and releases credits without fabricating highlights. Titles/hooks
are prompted to be grounded; semantic truth and subjective usefulness need human
QA and cannot be guaranteed by schema validation.

## Privacy and media limits

Deepgram receives extracted customer audio. Gemini receives timed transcript,
confidence and optional speaker context, never the full source video in this
phase. Publish subprocessor/region/retention terms and obtain legal review before
public processing. Deepgram's opt-out setting alone does not establish complete
provider retention or legal compliance. Gemini account data-use terms require
separate review. No transcript/audio or raw provider error is emitted in logs.

FFmpeg uses fixed arguments, shell=False, file-only protocols, two threads, a
300s wall deadline and fresh-process Linux CPU/address-space/file-size limits.
The output is limited to 240 MiB and validated as mono 16kHz WAV. Leading audio
offset is preserved. Audio is removed after the attempt; crash orphans age out
after one hour. Phase 3 atomic capacity envelopes and 20 GiB headroom remain.
Deleting/expiring a source revokes APIs immediately; after live leases finish,
cleanup erases transcripts, suggestions, private candidate checkpoints and response
receipts, retaining financial usage/reference/hash history. Off-server backup
retention/deletion and restore verification remain operational gates.

## Explicit live smoke (NOT RUN)

`scripts/ai_live_smoke.py` is opt-in only and is not called by tests/CI. It requires
both `--allow-paid` and ZOCLIP_ALLOW_PAID_SMOKE=1, configured private keys, reviewed
accessible models/rates/budgets and an isolated development environment. Supply
`--owner <uuid> --job <uuid>` for an already admitted PROCESS job created through
normal authenticated APIs. Run maintenance and the real RQ worker for subsequent
stage dispatch/backoff. The script fabricates no credit/rate/policy and uses the
same fenced worker. Review usefulness privately and cancel the hold afterward.
Do not run it under the current user's prohibition on real paid calls. The real
provider gate remains PENDING. The user authorized a local checkpoint commit based
on mocks/fixtures; passing mocks alone is not real-provider acceptance.
