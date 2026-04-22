from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.schemas.base import ORMModel
from app.schemas.limits import MAX_TEXT_CHARS


class CharacterProfileHistoryItem(ORMModel):
    version: int | None = None
    profile: str
    captured_at: str | None = None


class CharacterCreate(ORMModel):
    name: str = Field(min_length=1, max_length=255)
    role: str | None = Field(default=None, max_length=255)
    profile: str | None = Field(default=None, max_length=MAX_TEXT_CHARS)
    arc_stages: list[str] = Field(default_factory=list, max_length=50)
    voice_samples: list[str] = Field(default_factory=list, max_length=50)
    notes: str | None = Field(default=None, max_length=MAX_TEXT_CHARS)


class CharacterUpdate(ORMModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    role: str | None = Field(default=None, max_length=255)
    profile: str | None = Field(default=None, max_length=MAX_TEXT_CHARS)
    profile_version: int | None = Field(default=None, ge=0, le=99999)
    arc_stages: list[str] | None = Field(default=None, max_length=50)
    voice_samples: list[str] | None = Field(default=None, max_length=50)
    notes: str | None = Field(default=None, max_length=MAX_TEXT_CHARS)


class CharacterOut(ORMModel):
    id: str
    project_id: str
    name: str
    role: str | None = None
    profile: str | None = None
    profile_version: int = 0
    profile_history: list[CharacterProfileHistoryItem] = Field(default_factory=list)
    arc_stages: list[str] = Field(default_factory=list)
    voice_samples: list[str] = Field(default_factory=list)
    notes: str | None = None
    updated_at: datetime
