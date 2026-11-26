import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, EmailStr, Field

from app.models.enums import BlueprintStatus, Role
from app.schemas.common import ORMModel


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)


class ProjectPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)


class ProjectOut(ORMModel):
    id: uuid.UUID
    name: str
    description: str
    is_sandbox: bool
    created_at: datetime
    my_role: Role | None = None


class MemberIn(BaseModel):
    email: EmailStr
    role: Role


class MemberRoleIn(BaseModel):
    role: Role


class MemberOut(BaseModel):
    user_id: uuid.UUID
    email: str
    display_name: str
    role: Role


class BlueprintIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    brief: str = Field(min_length=20, max_length=4000)
    settings: dict[str, Any] = Field(default_factory=dict)


class BlueprintPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    brief: str | None = Field(default=None, min_length=20, max_length=4000)


class BlueprintOut(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    brief: str
    settings: dict[str, Any]
    status: BlueprintStatus
    version: int
    quality_score: int | None
    provider: str | None
    is_sample: bool
    created_at: datetime
    updated_at: datetime
