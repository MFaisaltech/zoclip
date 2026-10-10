from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from zoclip.credits.schemas import StrictModel

Millis = Annotated[int, Field(strict=True, ge=0, le=7200000)]


class CaptionWord(StrictModel):
    text: str = Field(min_length=1, max_length=80)
    start_ms: Millis
    end_ms: Millis

    @model_validator(mode="after")
    def interval(self) -> Self:
        if self.end_ms <= self.start_ms:
            raise ValueError("Positive word duration required")
        return self


class Preferences(StrictModel):
    start_ms: Millis
    end_ms: Millis
    title: str = Field(default="", max_length=160)
    hashtags: list[Annotated[str, Field(max_length=60)]] = Field(
        default_factory=list, max_length=10
    )
    captions: bool = True
    preset: Literal["classic", "bold", "karaoke"] = "karaoke"
    font: Literal["DejaVu Sans", "Noto Sans", "Noto Naskh Arabic"] = "DejaVu Sans"
    placement: Literal["bottom", "middle", "top"] = "bottom"
    frame: Literal["track", "center", "pad", "manual"] = "track"
    focal_x: Annotated[int, Field(strict=True, ge=0, le=1000)] = 500
    focal_y: Annotated[int, Field(strict=True, ge=0, le=1000)] = 500
    # Absolute source timestamps; None reuses original stored transcript words.
    words: list[CaptionWord] | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def interval(self) -> Self:
        if not 250 <= self.end_ms - self.start_ms <= 90000:
            raise ValueError("Clip duration must be between 250ms and 90 seconds")
        return self


class CreateClip(StrictModel):
    suggestion_id: UUID


class Selection(StrictModel):
    clip_ids: list[UUID] = Field(min_length=1, max_length=20)


class RenderInput(StrictModel):
    quote_id: UUID | None = None
    revision: Annotated[int, Field(strict=True, ge=1)]


class ClipView(StrictModel):
    id: UUID
    video_id: UUID
    job_id: UUID
    revision: int
    preferences: Preferences
    created_at: datetime


class OutputView(StrictModel):
    id: UUID
    clip_id: UUID
    revision: int
    job_id: UUID
    state: str
    metadata: dict
    created_at: datetime
