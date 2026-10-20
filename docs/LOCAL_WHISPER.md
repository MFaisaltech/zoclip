# Local transcription on protected staging

The default is `TRANSCRIPTION_PROVIDER=whisper`: faster-whisper **1.2.1**, model
`small`, CPU, INT8, two inference threads, VAD and word timestamps enabled.
`TRANSCRIPTION_PROVIDER=deepgram` selects the original HTTP implementation.
Unknown providers/models/devices/precision fail configuration validation. This
phase supports only small/cpu/int8. There is no automatic paid fallback.

PyAV is pinned to **17.1.0**: newer releases remove `metadata_errors`, which
faster-whisper 1.2.1 still passes. A real PCM decoder regression covers this API
compatibility independently of fake model tests. See the
[upstream compatibility issue](https://github.com/SYSTRAN/faster-whisper/issues/1589).

## Privacy and compatibility

Source audio is transcribed locally on the ZoClip VPS by default. Speaker 0 is a
placeholder, **not diarization**. Punctuation and absolute word times survive;
PCM sample count supplies original duration, including VAD-removed silence.
Empty speech stays empty. Invalid/truncated audio, missing model files, invalid
timestamps/confidence and model failures stop with a generic `ProviderFailure`.
Sensitive paths and chained native exceptions are suppressed.

Native alignment occasionally emits a zero-length token. If its timestamp lies
at a neighboring timed word boundary, the adapter joins its original text to that
caption word while preserving that word's timestamps and taking the lower
confidence. It invents no interval. An unanchored token in the neighboring
chunk's context is deferred to that neighbor; an owned unanchored token fails
closed. ONNX telemetry is explicitly disabled before VAD inference.

Gemini still receives transcript-related data through the unchanged HTTP adapter
and prompts. This pipeline is **not fully offline** and still involves third-party
processing. Explicit Deepgram fallback sends audio to Deepgram with the existing
privacy settings. Source permission, retention and deletion obligations remain.

`selection.py`, `schemas.py` and API shapes are unchanged. Local transcription
records a durable `AIRequest(provider='whisper', attempt_ids=[])` and fsynced
receipt, never fictitious paid Deepgram usage. Cache identities separate providers
and model/device/precision/language. Legacy pinned jobs retain Deepgram. Recovery
can consume an existing receipt. Bounded local chunk computation can retry the
unfinished chunk within the existing three-failure budget; uncertain paid
outcomes still stop without redispatch.
Migration `e7319c2b504a` only widens the request-provider CHECK; it changes no
existing customer, financial or media rows. Downgrade refuses Whisper history.

## Model image and resources

The Docker build downloads four files from `Systran/faster-whisper-small` at
immutable revision `536b0662742c02347bc0e980a01041f333bce120`, writes their SHA256
manifest and makes them root-owned/readable by UID10001. The model is included at
`/opt/models/faster-whisper-small`, survives container restarts, and occupies a
reusable build layer. This public download uses no credentials. Runtime requires
the local model and tokenizer files, `local_files_only=True` and
`HF_HUB_OFFLINE=1`. No CUDA packages/GPU or runtime download are required.

Initialization is lazy and reused per process. RQ retains fork-per-job isolation:
a fresh work horse loads from disk; model objects never cross PID boundaries.
This does not promise a model resident across RQ work horses. One AI RQ worker
and a shared-volume OS lock serialize transcription, including accidental local
replicas. OS locks release on crash. Multiple hosts/volumes are outside this
single-VPS contract. API concurrency stays 32. AI worker limits are 2 CPUs and
2560 MiB, two inference threads and one native worker. Health checks verify model
availability, a >=2 GiB cgroup limit and heartbeat without inference/download.

Audio extraction writes one bounded PCM WAV to private disk. Each RQ claim reads
at most `WHISPER_CHUNK_SECONDS` (default 120, range 30..180) plus
`WHISPER_OVERLAP_SECONDS` (default 1, range 0..2) on each side. It retains neither
the whole waveform nor decoded PCM in memory. Chunk settings are pinned per job.
Each chunk is durably recorded before progress and requeue. Final assembly reads
one receipt at a time, retaining only the contract's bounded word list. Sample
offsets restore global timestamps; half-open midpoint ownership and overlap-only
duplicate checks handle seams without deleting legitimate repeated words.

Existing RQ timeout 660s, lease 900s and extraction bound 300s remain. The 300s
generator guard applies to each chunk, including model load; a blocking native
operation may only be interrupted by RQ's hard timeout. Cancellation and capacity
checks run between segments and during extraction. Maintenance protects the
active WAV against orphan sweeping; completion, cancellation and retention
cleanup remove it. The render worker is unchanged. Synthetic acceptance does not
guarantee every natural recording or accepted format completes on this host.

## Financial and authorization boundaries

No prices, credits, quotes, catalog, CostRates, Gemini budgets or payment gates
change. Quotes retain the conservative legacy transcription allowance pending a
separately approved cost configuration. Local dispatch rechecks ownership, lease,
reservation, breaker, rates and budgets. Local compute creates no paid API spend
attempt. Gemini retains its existing durable spending admission and reconciliation.
Public AI/payments/signup remain disabled. The separate USD0.10 Deepgram/Gemini
entitlement remains UNAPPROVED and untouched. Local-only benchmark acceptance
does not use that entitlement, grant credits, write customer rows or call Gemini.

## Configuration and rollback

```env
TRANSCRIPTION_PROVIDER=whisper
WHISPER_MODEL=small
WHISPER_DEVICE=cpu
WHISPER_COMPUTE_TYPE=int8
WHISPER_MODEL_PATH=/opt/models/faster-whisper-small
```

For transcription rollback set `TRANSCRIPTION_PROVIDER=deepgram` in the private
deployment environment, then recreate affected app/AI worker containers with the
reviewed Compose profiles. Plain `docker restart` does not update environments.
Verify adapter selection without invoking transcription. Keep private staging's
blank keys and `AI_ENABLED=false`; fallback selection never authorizes spending.
Actual Deepgram processing still requires reviewed credentials, pinned model and
version, account rates and spending authorization. Existing pinned jobs retain
their recorded provider.

For code rollback restore the prior immutable image/release configuration. Leave
the backward-compatible widened CHECK in place; never erase transcription history.
Authenticate an encrypted off-server DB/media backup before migration; compare
all existing rows and media after rollout. Preserve VPN-only API and Vercel
protection. Evidence and the unapplied CPU allocation proposal are recorded in
[release verification](WHISPER_RELEASE_2026-10-19.md).

Official references:
[faster-whisper CPU/VAD/generator usage](https://github.com/SYSTRAN/faster-whisper),
[pinned package](https://pypi.org/project/faster-whisper/1.2.1/),
[immutable model](https://huggingface.co/Systran/faster-whisper-small/tree/536b0662742c02347bc0e980a01041f333bce120).
