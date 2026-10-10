# Phase 5 rendering handoff

Scope: local CPU rendering only. Phase 4 real Deepgram/Gemini gate remains PENDING;
production readiness is NOT APPROVED. No payments, frontend, deployment or Phase 6.

## API flow

All paths below are under `/api/v1`. Authentication, verified active account,
Origin and CSRF are required for mutations. JSON bodies reject extra fields.
Private UUID storage paths, lease tokens and subprocess diagnostics are never returned.

1. Existing upload/import -> validated source -> quote -> generate -> saved suggestions.
2. `POST /clips {"suggestion_id":"..."}` creates an owner-scoped draft exactly once
   per candidate. Maximum drafts equals the original quote's output_count.
3. `GET /clips`, `GET /clips/{id}` return current preferences and revision.
   Listing supports limit 1..100 and exclusive owned before UUID.
4. `PATCH /clips/{id}` replaces allowed preferences with `If-Match: "1"`.
   A new immutable revision is inserted; stale revision returns 409. No live render
   may be overwritten. No AI provider is called. Revision history is capped at 101.
5. `POST /jobs/{process_job_id}/renders {"clip_ids":["..."]}` approves a fixed
   nonempty selection, at most the reserved output_count, using Idempotency-Key.
   This explicitly accepts the original quote for that selection, including when
   fewer candidates than the requested maximum exist. The quote is not prorated.
   Same key/selection replays; changed selection or key after approval returns 409.
6. Existing `GET /jobs/{id}` and `/events` report RENDER_QUEUED / RENDERING,
   heartbeat and safe errors. Progress is null until verified completion (100).
7. `GET /clips/{id}/renders` lists revision/job links, state, verified dimensions,
   codecs, durations, SHA-256, bytes and actual framing mode.
8. `GET /clips/{id}/download[?revision=1]` streams a private MP4 attachment only
   after the entire associated job completes. Default is the current revision;
   an edited but unrendered revision returns 404. No public directory or range URL.
9. `POST /clips/{id}/render {"revision":2}` renders one completed selection's
   edited clip. A prepaid original edit allowance is used first, without another
   customer debit. Otherwise request a normal one-output `/jobs/quote`, with
   source_seconds matching the original, edit_count=0, matching captions/reframe,
   and send its quote_id. This uses the existing configurable source-based quote
   calculation, including its source-minute charge; no separate edit tariff is
   invented. Same operation key/payload replays. An already requested revision
   cannot create another output; use a new revision after a final failure.

Preferences: integer absolute-source start_ms/end_ms (250ms..90s within source),
title (160 chars), hashtags (10 x 60), captions, preset classic/bold/karaoke,
font DejaVu Sans/Noto Sans/Noto Naskh Arabic, placement bottom/middle/top,
frame track/center/pad/manual, focal_x/focal_y in 0..1000. Optional words have
text (80 chars), absolute start_ms/end_ms, ordered nonoverlapping within trim;
null reuses stored transcript, [] intentionally removes text. Crop/captions must
have been included in the original quote; padding is available without crop.

## Durability, credits and budgets

Initial rendering continues the original PROCESS job and reservation. Each claim
encodes at most one selected clip; completed outputs checkpoint before the next
outbox generation. PostgreSQL leases fence claims, publication and financial changes.
Dispatch routes render selections and new RENDER jobs to `render`; other work stays
on `ai`. PostgreSQL allows one live render and one live AI/ingestion task separately.
Redis loss/redelivery is safe through the existing outbox and claim fences.

Only after all approved outputs pass ffprobe, complete decode and timing checks does
the worker atomically mark COMPLETED and SETTLE once. Partial failure/cancellation
releases the original HELD reservation once, hides partial exports, keeps sunk
expense records and cleans files. Re-render jobs with fresh quotes behave likewise.
Prepaid edits have no new debit/refund: the successful initial deliverable already
settled its quote. Active/completed edits consume the shared original allowance;
failed edits free that allowance, while their server expenses and attempt counts
remain. Plan max_edits also caps active/completed re-exports. Refunding the original
settlement disables remaining prepaid exports. Ordinary paid-provider admissions
still require HELD credits; only durable internally approved prepaid render jobs
can charge render/storage expense against their original SETTLED evidence.

Versioned CPU/storage rates and all existing per-job/user/global daily/monthly
budgets apply. Render admission requires render_cpu_seconds_per_output >=
2*RENDER_DEADLINE_SECONDS+40 (520 default), and retention units sufficient for
the byte cap/TTL (2 GB-days default). These are resource ceilings, not invented
provider prices. CPU expense uses integer-ceiled child CPU seconds on Linux;
Windows uses conservative two-thread wall seconds. A lost worker records its
admitted ceiling before another bounded attempt; it never drops sunk exposure.
Retention uses integer-ceiled byte-seconds/GB-day, with no float money arithmetic.
Each subsequent CPU/retention admission includes existing exposure and retry costs.
Oversized actual usage opens the existing breaker. Configure adequate total attempt
caps for AI plus two expenses per output; defaults never authorize unlimited work.

Owner/wallet -> storage_pool -> job -> cost policy remains the lock order. No DB
transaction spans FFmpeg/OpenCV IO. Per-output disk commitments cover output plus
scratch; global outstanding/retained capacity and 20GiB minimum headroom are checked
before admission, execution and publication. Encodes are capped at 256MiB by default.
RENDER_DEADLINE_SECONDS is 240 (10..300); RENDER_MAX_BYTES is 256MiB (1..512MiB).
One render worker, two FFmpeg threads, one filter thread; OpenCV decoder and detector
use one thread. Linux child resource limits cover CPU, 1.5GiB address space, file
size, descriptors and disabled core dumps. RQ stays 660s with 900s fenced leases.
Linux parent-death signals kill the child if its RQ workhorse dies, with a PID
race check before exec. `scripts/render_boundary_smoke.py` verifies this boundary.

Transient OS/deadline failures retry at most three times per output with existing
bounded jitter. Bad output or budget/configuration errors fail finally. Cancellation
is polled every second and kills/reaps a running child; final lease/token checks
precede rename. Fsync+atomic promotion precedes the DB receipt. A crash-promoted file
is revalidated and decoded on recovery, without another encode. File/object and
revision uniqueness prevent duplicate exports. Original-media deletion revokes
downloads immediately, requests live cancellation, waits for leases, erases caption
revisions/candidate links and deletes output bytes. Expiry follows the source TTL;
financial/job history is preserved. Abandoned generated subtitle directories have
a bounded, no-symlink, one-hour cleanup sweep. Backup removal remains Phase 7 policy.

## Rendering and quality boundaries

H.264/yuv420p + AAC stereo 48kHz, 30fps, faststart MP4, 720x1280. Input seek decodes
only selected intervals with FFmpeg accurate transcoding seek; no whole-source
re-encode or unsafe keyframe stream-copy. Cropping, captions and exact cuts require
encoding, so no copy fast path is advertised. Input display rotation is honored.
Common seek-relative audio/video timestamps are preserved; resampling/padding fills
real leading/trailing audio gaps without independently resetting away source offsets.
Validation requires expected dimensions/codecs, duration within 100ms, stream starts
within 100ms and duration difference <=100ms, playable packets and full short-output
decode. Fine sample/frame timing has codec quantization; no sample-exact claim.

ASS files use allowlisted fonts/styles/placement, contrast outlines, 70px side and
180px vertical safe margins, 24-character wrapping and bounded groups. Long tokens
can wrap to additional lines. Karaoke highlights the current stored word interval
with a short fade; classic/bold show phrase intervals. Missing/bad timestamps are
skipped; overlaps are clamped deterministically; clipping rebases to output time.
Client braces/backslashes become literal Unicode glyphs; control/newline injection
is removed. Neither text nor a path from a client enters a filter command.
Docker installs reviewed font families. English glyphs/actual burn-in are tested;
Urdu shaping, fallback fonts, emoji and subjective readability need visual QA.

Tracking is sampled OpenCV Haar frontal-face focus, capped at 24 frames, >=2s apart,
20s CPU stage deadline within the overall render deadline, largest/nearest-prior
face weighting, low-pass smoothing and bounded pan changes. No detection/tool/time
budget -> center_fallback. Manual focal crop and padding are deterministic. This
is face sampling, not speaker identification, identity recognition or external AI
vision. Profile/occluded/small faces, rapid motion and multiple speakers may select
the wrong subject. No automatic diarization-to-face association is claimed.

Official implementation references reviewed: [FFmpeg CLI](https://ffmpeg.org/ffmpeg.html),
[filters/ASS/crop](https://ffmpeg.org/ffmpeg-filters.html),
[OpenCV CascadeClassifier](https://docs.opencv.org/4.12.0/d1/de5/classcv_1_1CascadeClassifier.html).
OpenCV headless 4.12.0.88 and compatible NumPy 2.2.6 are pinned in uv.lock.

## Opt-in representative benchmarks

Linux: `python scripts/benchmark_render.py /private/10min.mp4 /private/bench.mp4
--minutes 10 --allow-local-benchmark` (single line). Repeat with 30/60/120-minute
representative, legally authorized sources. Outputs must not exist. It measures
start/middle/end selected renders, wall time, child CPU/RSS and output bytes. Record
disk headroom/peak scratch externally; for full pipeline also record authenticated
upload, queue wait, mocked/live transcription/analysis wait and cost receipts.
The direct engine script explicitly labels those unmeasured fields. No large-input
throughput, VPS capacity, face-detection accuracy or real provider price is inferred
from the local short fixture gate. Representative benchmarks are opt-in and unrun.
