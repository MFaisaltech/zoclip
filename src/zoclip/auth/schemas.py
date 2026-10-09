from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EmailInput(StrictModel):
    email: EmailStr = Field(max_length=320)

    @field_validator("email")
    @classmethod
    def normalize(cls, value: str) -> str:
        return value.lower()


class Credentials(EmailInput):
    password: str = Field(min_length=12, max_length=128)


class TokenInput(StrictModel):
    token: str = Field(min_length=32, max_length=128)


class ResetInput(TokenInput):
    password: str = Field(min_length=12, max_length=128)


class Message(BaseModel):
    message: str


class CsrfResponse(BaseModel):
    csrf_token: str


class Me(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    email: EmailStr
    verified: bool
    role: Literal["customer", "admin"]
    created_at: datetime


class LoginResponse(BaseModel):
    user: Me
    csrf_token: str


class SessionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    created_at: datetime
    expires_at: datetime


class AuditView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    actor_id: UUID | None
    action: str
    target_id: UUID | None
    request_id: str
    created_at: datetime


class AuditPage(BaseModel):
    items: list[AuditView]
    next_cursor: UUID | None = None
