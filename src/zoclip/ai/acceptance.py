"""Opt-in, PostgreSQL-persisted one-shot dispatch limits for acceptance jobs.

The caller holds the existing wallet/job locks and commits the consumed slot
BEFORE network IO. A crash may lose a permitted call, never permit a second one.
Ordinary jobs do not acquire acceptance behavior.
"""

from uuid import UUID

from zoclip.core.config import Settings
from zoclip.core.errors import ApiError
from zoclip.media.models import Job

MARKER = "one_shot_acceptance"
CONFIG_FIELDS = (
    "gemini_model",
    "deepgram_model",
    "deepgram_version",
    "deepgram_language",
    "deepgram_diarize",
    "deepgram_utterances",
    "deepgram_mip_opt_out",
    "ai_max_chunks",
    "ai_chunk_bytes",
    "ai_max_candidates",
    "ai_max_output_tokens",
    "ai_provider_timeout_seconds",
)


def configuration(settings: Settings) -> dict:
    """Only public request parameters; never credentials or connection URLs."""
    return {name: getattr(settings, name) for name in CONFIG_FIELDS}


def consume(
    job: Job, settings: Settings, provider: str, request_id: UUID, source_sha256: str
) -> None:
    if MARKER not in job.checkpoint:
        return
    binding = job.checkpoint[MARKER]
    if (
        not isinstance(binding, dict)
        or binding.get("version") != 1
        or binding.get("job") != str(job.id)
        or binding.get("owner") != str(job.user_id)
        or binding.get("video") != str(job.video_id)
        or binding.get("source_sha256") != source_sha256
        or binding.get("configuration") != configuration(settings)
        or provider not in {"deepgram", "gemini"}
        or not isinstance(binding.get("dispatches"), dict)
    ):
        raise ApiError(503, "acceptance_binding_invalid", "Acceptance binding changed; stop.")
    dispatches = binding["dispatches"]
    if provider in dispatches:
        raise ApiError(
            503, "acceptance_request_consumed", "One-shot request already consumed; stop."
        )
    job.checkpoint = {
        **job.checkpoint,
        MARKER: {**binding, "dispatches": {**dispatches, provider: str(request_id)}},
    }
