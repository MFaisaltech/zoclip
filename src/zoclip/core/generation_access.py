"""Deployment-owned account gate; never trust client flags or job payloads."""

from uuid import UUID

from zoclip.core.config import Settings
from zoclip.core.errors import ApiError


def require_generation_access(settings: Settings, owner: UUID) -> None:
    if not (
        settings.private_staging
        or settings.staging_generation_enabled
        or settings.staging_generation_user_id is not None
    ):
        return
    if (
        settings.app_env != "production"
        or settings.deployment_tier != "protected_staging"
        or not settings.private_staging
        or not settings.staging_generation_enabled
        or settings.staging_generation_user_id != owner
        or settings.ai_enabled
        or settings.transcription_provider != "whisper"
        or settings.analysis_provider != "local"
        or settings.deepgram_api_key.get_secret_value()
        or settings.gemini_api_key.get_secret_value()
        or settings.payment_provider != "disabled"
        or settings.enable_live_payments
        or settings.enable_trial_credits
    ):
        raise ApiError(
            403, "staging_generation_disabled", "Generation is disabled for this account."
        )
