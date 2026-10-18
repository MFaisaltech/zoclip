# Local Whisper internal cost proposal — NOT APPLIED

This document does not configure a rate, mutate a wallet, change package pricing
or alter credit quotes/deductions. It requires separate owner approval. Runtime
quotes and all paid Gemini admissions retain existing financial controls.

## Allocation proposal

Proposed future component: `whisper_cpu`, unit `cpu_second`, model identifier
`faster-whisper:small@536b0662742c02347bc0e980a01041f333bce120:cpu:int8`.
Provisional allocation: **USD0.000005 per consumed CPU second**, with an admission
ceiling of **1320 CPU seconds / USD0.006600** for a work horse (2 CPU × 660s RQ
timeout). This is an internal resource allocation, not an external API invoice.
It must include failed/killed attempts when subsequently implemented; CPU data
alone does not provide authoritative billing evidence. It is **not installed**.
Supporting that new component would need separately reviewed financial schema,
admission and metering work; this phase does not modify the financial schemas.

Reference capacity arithmetic: USD13.20 / (30 × 86400 × 4 vCPUs) is approximately
USD0.00000127315 per fully utilized vCPU second. The proposed USD0.000005 includes
about 3.93× utilization/overhead allowance. It does not establish profitability,
new hosting charges or a customer price. Memory/storage/bandwidth share the VPS
allocation; do not add them again as if all were separate cash invoices.

## Projection method and limits

Use the measured cold transcription CPU seconds and wall time in
[release evidence](WHISPER_RELEASE_2026-10-19.md), scaled by source duration.
The 5/30/120-minute numbers there are **linear projections**, not long-source
benchmarks. Cold import/model load is included, so scaling its fixed overhead is
conservative; speech density, language, host contention and long-input memory can
make inference slower. No throughput guarantee follows from one short source.
Any predicted stage exceeding the 300s local segment deadline or 660s RQ limit
may fail closed. Raising those bounds or supporting a long-source strategy needs
separate measured capacity review; do not remove safeguards to meet a projection.

Temporary 16kHz mono PCM16 uses 32000 bytes/second: about 9.16/54.93/219.73 MiB
for 5/30/120 minutes, below the existing 240 MiB audio bound. Float32 decoding is
roughly twice that before model/features and must fit the 2560 MiB worker limit.
Model image storage and peak memory are measured in release evidence. The image
stores one immutable model; restarts do not download it. Normal persistent volume
media, originals, captions and outputs keep their existing quotas and retention.

Local transcription sends **zero audio bytes to Deepgram**. It removes that audio
egress and per-minute Deepgram invoice, but source upload/download traffic and
Gemini transcript requests remain. Gemini still has account rates, token bounds,
budget reservations and spending authorization. No updated CostRate is approved
or installed by this document.
