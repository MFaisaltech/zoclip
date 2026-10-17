# Phase 3 ingestion and queue contract

2026-10-15 private staging upload fix: non-billable upload/validation no longer
requires a commercial price catalog in the fully closed private profile. Existing
configured plan limits, ownership, storage/queue limits and all finance fences
remain. [Root cause, deployment and verification](PRIVATE_STAGING_UPLOAD_FIX_2026-10-15.md).
The remaining text records the earlier phase contract.

This phase implements private source ingestion, not AI suggestions or clips.
`COMPLETED` on a VALIDATE/IMPORT job means source validation completed. PROCESS
jobs reserve credits and stop at `WAITING_ENGINE` / `processing_unavailable`.
No production mock engine, provider calls, deliverables or settlement exist.
Canceling that job restores its hold; maintenance cancels waiting jobs after 24h.

## Local operation

Use the README's Docker setup, then `docker compose up --build -d --wait`.
FFmpeg/ffprobe comes from Debian's security-maintained Bookworm package. Record
the actual image digest and binary version at verification, and rebuild regularly
for security updates. Python dependencies remain pinned by `uv.lock`.
API, AI worker, render worker and maintenance share one **private** media volume.
There is one AI worker and one render worker. No render tasks are registered yet.
The maintenance process dispatches committed outbox rows, recovers expired leases
and performs retention every five seconds; it must run alongside the workers.

The storage filesystem must have at least 20 GiB headroom **after** commitments.
Docker Desktop's internal disk may be too small. Configure a shared private bind
mount on a sufficiently large disk for API/AI/render/maintenance if necessary.
Do not lower the production safety floor to make a smoke test pass. Never mount
the directory into a static server. Storage is local/VPS compatible; the Storage
protocol is the future remote-adapter seam, not an implemented cloud adapter.

Configuration (defaults are engineering capacity limits, not purchased quotas):

| Setting | Default |
|---|---|
| MEDIA_ROOT | var/media locally; /app/var/media in Compose |
| MEDIA_MAX_BYTES | 4 GiB, cannot exceed 4 GiB |
| MEDIA_PART_BYTES | 8 MiB; allowed 64 KiB–8 MiB |
| MEDIA_HEADROOM_BYTES | 20 GiB minimum |
| MEDIA_RETAINED_BYTES | 40 GiB aggregate commitments ceiling |
| MEDIA_INGESTION_LIMIT | 2 global sessions |
| MEDIA_USER_INGESTION_LIMIT | 1 session per user |
| MEDIA_PENDING_LIMIT | 10 queued jobs |
| MEDIA_USER_PROCESSING_LIMIT | 1 active processing request per user |
| MEDIA_UPLOAD_TTL_SECONDS | 24h, not extended by writes |
| MEDIA_RETENTION_SECONDS | 7 days |
| MEDIA_ALLOWED_IMPORT_HOSTS | [] (imports disabled until exact hosts configured) |
| FFPROBE_BINARY | ffprobe |

The Phase 2 catalog must have explicit staff-configured Free/paid quota rules.
Ingestion does not grant or deduct credits. Processing requires a valid owned
quote, authoritative media duration, available credits, configured budgets/rates,
closed breaker and production-approved price. No commercial values are seeded.
Admission endpoints also use the existing fail-closed Redis IP/account throttle.
Redis remains transport/throttling only; PostgreSQL owns all durable limits.

## Browser/API flow

All paths below are under `/api/v1`. Use an active verified session cookie. Every
mutation needs the permitted Origin and X-CSRF-Token; JSON admissions/completion
and processing also need Idempotency-Key. Keys are owner scoped; changed payloads
conflict. PROCESS/IMPORT/VALIDATE creation shares the job-key namespace; upload
initiation has its own namespace. A canceled/failed replay returns that same job.

1. Compute source SHA-256 and byte length. POST `/uploads` with
   `{"size_bytes":160793,"sha256":"<64 lowercase hex>","rights_attested":true}`.
   Response gives id, video_id, part_bytes, expiry and received_parts.
2. Split into fixed part_bytes chunks, with a shorter last chunk. PUT
   `/uploads/{id}/parts/{number}` (zero based), Content-Type
   application/octet-stream and X-Content-SHA256 for that part. Stream the body.
   Reordered parts work; identical repeats return the existing part; differing
   bytes/hash conflict. One part writer per upload; busy clients retry after 409.
   Parts must have exact expected length, SHA-256 and finish within 60 seconds.
3. GET `/uploads/{id}` to resume from received_parts. POST
   `/uploads/{id}/complete` returns 202 and the durable validation job. No full
   file is buffered by the API. Assembly and ffprobe run asynchronously.
4. Poll GET `/jobs/{id}` and `/jobs/{id}/events`. Queue position is null because
   RQ cannot supply an authoritative position. Heartbeat and actual stage are
   reported; no invented percent progress. A READY source is listed by GET
   `/videos` and GET `/videos/{id}`. Lists accept limit (max 100) and before UUID.
5. GET `/videos/{id}/content` downloads privately with authorization and no-store.
   It is an attachment without user filenames or public paths. Range requests
   are not implemented. Already-open authorized downloads can finish on deletion;
   subsequent reads are revoked. No expiring public links exist.
6. To request future processing, obtain a Phase 2 quote using the returned integer
   duration_seconds (rounded **up**), then POST `/videos/{id}/generate` with quote_id.
   POST `/jobs` with video_id and quote_id remains a compatible alias: identical
   owner/key/payload across either route returns the same job and credit hold.
   Credits/job/outbox commit atomically. The worker records WAITING_ENGINE until
   Phase 4. POST `/jobs/{id}/cancel` is idempotent. Running ingestion enters
   CANCEL_REQUESTED and frees disk/credits only after worker acknowledgment or
   safe lease expiration. DELETE `/uploads/{id}` or `/videos/{id}` revokes source
   access and schedules cleanup. Active part writers must finish/expire first.

Example authenticated chunk submission (cookie/CSRF values stay private):

```sh
curl --fail-with-body -X PUT "$API/api/v1/uploads/$UPLOAD/parts/0" \
  --cookie "$COOKIE_FILE" -H "Origin: $APP_ORIGIN" \
  -H "X-CSRF-Token: $CSRF" -H 'Content-Type: application/octet-stream' \
  -H "X-Content-SHA256: $PART_SHA256" --data-binary @part-0
curl --fail-with-body "$API/api/v1/jobs/$JOB" --cookie "$COOKIE_FILE"
```

## Supported direct URLs

POST `/videos/import-url` with url, max_bytes and rights_attested:true. max_bytes
is the admitted upper bound, not trusted server metadata. Only explicit exact
DNS hosts in the operator allowlist are supported; no wildcard suffix matching.
HTTPS/443 only, no credentials/fragment/control characters. YouTube/platform
scraping and DRM bypass are unsupported (`unsupported_source`). Do not configure
platform page hosts as direct-media sources.

Each connection resolves all answers in a deadline-bounded subprocess, rejects
non-global/mapped/tunneled addresses, pins a numeric socket destination, checks
its connected peer and validates TLS against the original hostname. Every
redirect is separately checked (max three). Environment proxies, unchecked DNS
re-resolution, cookies and authentication forwarding are absent. Read/connect
timeouts, 120-second download deadline, byte limits, MIME, magic and ffprobe
checks apply even without Content-Length. Imported URLs are private DB payloads,
never API DTOs/log fields, and erased on final success/failure/cancellation.
There is no live public URL smoke dependency; transport tests never fetch users'
real URLs. Host allowlisting is an operational authorization boundary.

## Transactions, recovery and storage

Tables: projects, source_videos, storage_objects, storage_pool, upload_sessions,
upload_parts, jobs, job_events, job_outbox. Migration 7e3fcb0834e3 follows
dd9634e4866b without rewriting prior migrations. Job events reject DB UPDATE,
DELETE and TRUNCATE. Downgrade refuses populated job history. Financial history
is never deleted by retention.

Lock order: owner/wallet, Phase 2 budget mutex when reserving, then storage_pool
and individual media rows. Storage admission uses the PostgreSQL singleton
mutex and actual free space; remaining commitments subtract materialized bytes.
Ingestion reserves three source copies plus 2 GiB scratch/audio headroom.
Future processing reserves an additional 2 GiB plus a conservative 32 MiB per
source minute per requested output. These are capacity envelopes only; Phase 5
must replace/validate them against its actual bounded render contract before
rendering. No rendering allocation promises are made here.

Only one DB-claimed ingestion/placeholder task runs at once, even if additional
workers start accidentally. RQ delivery is at least once. Outbox leases release
DB locks before enqueue; pending rows redeliver every minute until DB claim, so
Redis loss or a crash after enqueue is recoverable. RQ jobs expire in 120 seconds;
delivery results are not business state. Side effects run outside transactions.

Workers have a fixed 900-second fencing lease, a 660-second RQ deadline, a
600-second assembly deadline, 120-second import deadline and 25-second ffprobe
deadline. Heartbeats do not extend that fixed safety window. Publication checks
current token/lease and cancellation under DB locks; stale workers cannot publish
or mutate money. Local transient I/O retries have exponential delay, max three
claims, with equal jitter in [half the exponential delay, full delay], capped at
30 seconds; malformed media fails immediately. Paid requests are absent, so retry
does not risk duplicate provider charges. Phase 4 must add unknown-outcome and
provider-checkpoint semantics before introducing paid stages.

ffprobe only accepts MP4/WebM, one video plus audio, bounded codecs/dimensions,
nonempty sampled packets and finite duration <=7200 seconds. It runs without a
shell, with file-only protocol/format allowlists and bounded metadata. Linux
wrapper applies CPU/address-space/file-size/open-file/core limits in a fresh
process. Windows local checks exercise deadlines/validation; Linux is the
supported worker runtime and verifies resource limits. This is format/packet
validation, not exhaustive decoding of every frame or antivirus certification.

Private files use generated UUID keys and restrictive modes. Writes fsync then
atomically promote; Linux directory fsync persists renames and removals before
their database receipts commit. Crash gaps create private orphans, never public resources.
Retention waits for active writers/worker leases, removes completed upload parts,
releases capacity and deletes unreferenced UUID files older than one hour. Failed
cleanup retries on the next tick. Run maintenance during recovery after an outage.
Backups, restore drills, runtime DB privilege separation, malware isolation beyond
these process limits and real 10/30/60/120-minute capacity measurements remain
production launch requirements; none are claimed by this local phase.

## Recovery and status contract clarifications

Download authorization takes the owner/wallet/storage mutex and refreshes/locks
the source row before testing READY/expiry and opening its descriptor. Deletion
uses that same lock order. A deletion that wins the lock prevents a new download;
an already-authorized open descriptor may finish. Failed DB commit closes the
descriptor. The concurrent regression uses independent PostgreSQL connections.

Job responses add updated_at, stage, progress_percent and estimated_credits.
Stage derives from the durable kind/state: RUNNING ingestion is VALIDATING or
IMPORTING; completed ingestion is SOURCE_READY; queued/canceled/failed/waiting
states report themselves. No fine-grained byte or ffprobe progress is invented.
progress_percent is 100 only for completed ingestion and null otherwise.
Nonbillable ingestion estimates are explicitly zero. PROCESS estimates are the
accepted credit reservation amount, persisted in its checkpoint; legacy jobs
without that snapshot return null. Queue position remains null. WAITING_ENGINE
does not imply clips, provider work or settlement.

Before receipt commit, lost part promotion leaves an unreferenced UUID file;
the client can retry after the writer lease and the orphan sweep removes it.
Before source publication commit, a promoted file remains private and the job
retains its lease; recovery reassembles/revalidates from retained parts and
replaces that object safely. After successful commit/lost acknowledgment, the
terminal job prevents reexecution and completed-part cleanup is safe. Tests
inject process loss at these boundaries; no physical power-cut test is claimed.

Controlled HTTPS verification and exact commands are in
[PHASE3_VERIFICATION.md](PHASE3_VERIFICATION.md). The fixture uses normal TLS
verification and the unchanged production importer; no private-IP exemption exists.

References reviewed for implementation: [RQ queues](https://python-rq.org/docs/),
[ffprobe options](https://ffmpeg.org/ffprobe.html), and
[Python HTTPSConnection](https://docs.python.org/3.12/library/http.client.html).
