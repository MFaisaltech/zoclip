from datetime import datetime
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

Finite = Annotated[float, Field(allow_inf_nan=False)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Word(Strict):
    word: str = Field(min_length=1, max_length=200)
    punctuated_word: str = Field(min_length=1, max_length=200)
    start: Finite = Field(ge=0)
    end: Finite = Field(gt=0)
    confidence: Finite = Field(ge=0, le=1)
    speaker: int | None = Field(default=None, ge=0, le=1000)

    @model_validator(mode="after")
    def interval(self) -> Self:
        if self.end <= self.start:
            raise ValueError("Word interval must be positive")
        return self


class TranscriptData(Strict):
    text: str = Field(max_length=1000000)
    words: list[Word] = Field(max_length=40000)
    confidence: Finite = Field(ge=0, le=1)
    duration_seconds: Finite = Field(gt=0, le=7201)
    utterances: list[dict] = Field(default_factory=list, max_length=10000)


class Moment(Strict):
    start_sec: Finite
    end_sec: Finite
    title: str = Field(min_length=1, max_length=160)
    hook: str = Field(min_length=1, max_length=300)
    reason: str = Field(min_length=1, max_length=500)
    score: Finite = Field(ge=0, le=100)
    keywords: list[Annotated[str, Field(min_length=1, max_length=60)]] = Field(max_length=10)
    hashtags: list[Annotated[str, Field(min_length=1, max_length=60)]] = Field(max_length=10)


class Moments(Strict):
    moments: list[Moment] = Field(max_length=20)


class TranscriptView(Strict):
    id: UUID
    video_id: UUID
    job_id: UUID
    model: str
    language: str
    created_at: datetime
    data: TranscriptData


class SuggestionView(Moment):
    id: UUID
    rank: int
    job_id: UUID
    transcript_id: UUID


class SuggestionsView(Strict):
    job_id: UUID
    state: str
    stage: str
    error_code: str | None
    items: list[SuggestionView]
    rendered: bool = False
