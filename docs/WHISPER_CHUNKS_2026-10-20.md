# Bounded Whisper acceptance - 2026-10-20

Continue from backend `fce15de`; frontend remains `a9105df`. Creator PKR 2,000 / 3,700 credits and Pro PKR 5,000 / 9,500 credits remain **inactive**. No catalog, credit, trial, quote, Gemini, Deepgram or frontend implementation changed. [Machine-readable evidence](evidence/whisper-chunks-20261020.json).

## Root causes and smallest fix

The original 30-minute adapter reproduced failure after **317.95s**. Captured exception location is the old whole-recording 300-second generator guard (`fce15de`, providers.py line 214). It was not an OOM. The original two-hour decode/transcription was Docker OOMKilled after **46.75s** at the real 2,560-MiB worker limit. Passing the full file to faster-whisper caused whole-recording PCM/VAD/features allocations; see [pinned upstream implementation](https://github.com/SYSTRAN/faster-whisper/blob/v1.2.1/faster_whisper/transcribe.py). Increasing timeouts cannot fix that allocation.

Extraction writes one <=240-MiB mono PCM WAV to private disk. Each claim reads only a 120-second core plus <=1-second context on either side (maximum 122s float32 PCM, 7,808,000 bytes). Durations are configurable and pinned per job. A durable local receipt and PostgreSQL checkpoint precede each requeue. Final assembly reads one response at a time and retains only the existing bounded TranscriptData word list. Global sample offsets, half-open ownership, overlap-only duplicate checks and punctuation merging preserve the contract. Silence remains silence; conflicting or unanchored owned timestamps fail closed. Neighbor-owned unanchored context is deferred, with no invented time interval.

A development seam failed on zero-length context tokens outside its owned interval. The exact window and WAV hash were reproduced; the corrected adapter passed in 69.97s. Anchored punctuation still survives at the seam. Local retry, receipt-before-commit recovery, lost work horses, cancellation and source expiry reuse or clean checkpoints without duplicate ledger mutations. An active WAV survives the hourly orphan sweep.

One ASR, one renderer, CPU INT8, two ASR threads, RQ 660s, lease 900s and the cooperative 300s Whisper guard are unchanged. A native inference call can run past the cooperative check until the next segment; RQ remains the hard bound. Paid provider retry behavior is unchanged.

## Actual pipeline measurements

Existing 4-vCPU VPS, AI quota 2 CPUs / 2,560 MiB. Reused 1080p H.264 2.5-Mbps motion and AAC 96-kbps locally generated speech; source files approximately 100 / 599 / 2,396 MB. Disk was checked before generation. These repeated synthetic fixtures test infrastructure, not natural-footage, multilingual or highlight quality. HTTP upload uses the actual ASGI app without WAN transport. PostgreSQL, Redis/RQ, extraction, Whisper, selection, captioned FFmpeg and local storage are real; Gemini is mocked and provider HTTP dispatch forbidden. **Zero paid calls.**

| Minutes | Upload s | Validate s | Extract s | ASR s incl. retries | Caption renders s | End-to-end s | Chunks | Output bytes |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 5 | 2.46 | 2.69 | 6.30 | 199.75 | 19.46 | 235.78 | 3 | 5427717 |
| 30 | 14.47 | 5.62 | 34.31 | 960.11 | 64.56 | 1,102.09 | 15 | 16242178 |
| 120 | 78.37 | 26.98 | 146.22 | 5,119.33 | 133.60 | 5,713.48 | 60 | 16242178 |

5/30-minute measurements use an unforked SimpleWorker controller and process-local model reuse. The two-hour run uses production `rq.Worker`, a fresh fork and cold model for each claim. All use the identical application image `zoclip-private-app@sha256:ee1283ed5c1e5bfe666daa10bf44b12a7874986509c7e73b2c997e83e615da50`. Rerunning the already successful short cases was avoided. Unforked two-hour extraction experiments failed before ASR without OOM; their exact cause is unproven. The same extractor and limits passed both isolated execution and production-class RQ (145.61s wall, 224.42 CPU seconds). Those failed experiments remain separate in evidence.

Peak process RSS: **1,457,540 KiB (1.39 GiB)**. Largest worker claim: **310.08s**. Recovered ASR failures: **2**, retained in the phase evidence and included in worker service time. Successful chunks stayed below 300s; all claims stayed below 660s. No completed source was re-transcribed after retry. Peak cgroup memory also includes reclaimable file cache and the controller: 2,684,383,232 bytes. Minimum host MemAvailable: 5,029,531,648 bytes; minimum sampled free disk: 51,535,736,832 bytes.

CPU seconds and per-stage RSS are recorded in JSON. Concurrent 90-second caption rendering overlapped the five-minute ASR and passed, producing 15,581,139 bytes. Overlapping process/child CPU counters must not be summed. Mock analysis/selection/persistence overhead is included in worker claims, not individually attributed. Actual selected output counts are conditional (one / three / 3); four 90-second renders used for capacity are a conservative projection, not four observed outputs per job.

Queue wait samples are in JSON. Admission remains ten pending / one processing per user, atomic disk reservations, 20-GiB free headroom and 40-GiB retained media. Burst rejection is expected; monthly averages do not promise instant admission. PostgreSQL regressions cover queue/storage rejection rollback. Disposable source-expiry cleanup erased media/private transcript bodies, was idempotent and preserved wallet/reservation/ledger fingerprints.

## Capacity and pricing gate

These are **planning ceilings, not certified sustainable customer capacity**. Assumptions: 50% usable month, 25% retry-work provision, three 90-second outputs plus one edit, seven-day uniformly distributed media retention, existing 229,098,014 media bytes, measured local receipt sizes and current database allocation. Cold-start protocol differs for the short cases; real footage, bursts, larger formats, future database history and actual Gemini latency/cost still require acceptance.

The existing backup guard additionally needs 20 GiB plus twice media+DB before creating a full encrypted local backup. The model reserves this envelope as well as new live media using 65,076,072,448 free bytes after fixture cleanup. No backup retention timer/policy is configured; ten existing archives were preserved. Indefinitely accumulating archives cannot support a sustainable capacity certification.

| Source min | Worker jobs/month | 40-GiB media-only ceiling | With one backup envelope | Planning ceiling |
|---|---:|---:|---:|---:|
| 5 | 2738 | 1128 | 379 | 379 |
| 30 | 1017 | 276 | 93 | 93 |
| 120 | 192 | 74 | 25 | 25 |

Maximum-size 4-GiB source plus four maximum outputs gives only 11 jobs/month by this storage envelope, before CPU/quality certification. Database-history growth and long-term archive retention can lower these figures.

Near-equal Creator/Pro mix, 10% / 35% / 100% credit redemption; entries are jobs for **5/30/120-minute** sources and whether they fit the corresponding planning ceiling. Quotes remain 60 / 158 / 608 credits for three outputs plus one edit.

| Customers | Low 10% | Average 35% | High 100% |
|---|---|---|---|
| 20 | 210/80/10; fits/fits/fits | 760/290/70; over/over/over | 2190/830/210; over/over/over |
| 35 | 363/138/17; fits/over/fits | 1313/501/121; over/over/over | 3784/1434/363; over/over/over |
| 50 | 525/200/25; over/over/fits | 1900/725/175; over/over/over | 5475/2075/525; over/over/over |

**Pricing activation NO.** Full promised redemption for 20-50 customers exceeds existing storage capacity, and high long-video redemption also exceeds the measured worker ceilings; backup retention is unresolved and natural workloads/financial acceptance are not certified. Credits were not reduced. The practical fix is additional retained-media capacity with off-server encrypted backup and an explicit retention policy, plus measured CPU capacity sufficient for the long-video worker shortfall in the table. Re-benchmark that configuration and real workload/cost acceptance before approving these packages. More ASR RAM alone does not resolve these constraints. Existing 60% margin safeguards remain unchanged; mocked costs are not financial evidence.

## Verification and deployment

683 backend tests passed, 82 skipped, 498.03s, using disposable PostgreSQL 17 and Redis. Six focused capacity tests subsequently passed. Ruff passed; mypy checked 84 source files. New regressions cover boundaries, punctuation, global offsets, silence, legitimate repeated words, conflicting overlaps, bounded reads from a sparse two-hour WAV, deadlines, retries, receipt crash recovery, lost leases, cancellation, retention and separate receipts for a new job. Frontend source and its prior verification remain unchanged.

DEPLOYED to protected staging after a fresh encrypted backup, off-server authenticated decryption, isolated empty-database restore and rollback readiness checks. Seven services healthy; runtime environment, network and port bindings preserved. No schema migration. Historical table and retained-media fingerprints unchanged. Whisper remains default; Deepgram inactive; API VPN-only and frontend Vercel-protected. Payments, public AI and provider keys remain disabled.

Replay: `python scripts/chunked_capacity_report.py docs/evidence/whisper-chunks-20261020.json`. The benchmark harness requires explicit isolated opt-in and exact disposable DB identity. No new migration, external provider call or public activation is needed for this fix.
