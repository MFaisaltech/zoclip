from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr

Hash = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class UploadInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    size_bytes: int = Field(gt=0, le=4 * 1024**3)
    sha256: Hash
    rights_attested: Literal[True]


class UploadView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    video_id: UUID
    state: str
    expected_bytes: int
    part_bytes: int
    expires_at: datetime
    received_parts: list[int] = []


class PartView(BaseModel):
    number: int
    size_bytes: int
    sha256: Hash


class ImportInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: SecretStr = Field(min_length=1, max_length=2048)
    max_bytes: int = Field(gt=0, le=4 * 1024**3)
    rights_attested: Literal[True]


class ProcessInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    video_id: UUID
    quote_id: UUID
    auto_render: bool = False


class GenerateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    quote_id: UUID
    auto_render: bool = False


class JobView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    video_id: UUID
    kind: str
    state: str
    error_code: str | None
    attempts: int
    created_at: datetime
    updated_at: datetime
    stage: str
    progress_percent: int | None
    estimated_credits: int | None
    heartbeat_at: datetime | None
    queue_position: None = None
    reservation_id: UUID | None


class VideoView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    state: str
    metadata_json: dict
    created_at: datetime
    expires_at: datetime


class EventView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    state: str
    code: str | None
    created_at: datetime
