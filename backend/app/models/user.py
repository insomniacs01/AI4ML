"""User-related Pydantic models for the AI4ML platform.

Defines three user roles based on the "智算" platform requirements:
- admin: 社区与系统管理员 — manages users, permissions, API quotas, datasets and models
- user: 零基础业务领域用户 — interacts via natural language, uploads data, views results
- developer: 有经验的 AI 开发者 — human-in-the-loop intervention, code access, pipeline sharing
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class UserRole(str, Enum):
    admin = "admin"
    user = "user"
    developer = "developer"


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class UserRegisterRequest(BaseModel):
    """Public registration payload."""
    username: str = Field(min_length=3, max_length=32, pattern=r"^[a-zA-Z0-9_]+$")
    password: str = Field(min_length=6, max_length=128)
    email: str = Field(min_length=5, max_length=128)
    role: UserRole = UserRole.user


class UserLoginRequest(BaseModel):
    """Login payload — returns a JWT token on success."""
    username: str
    password: str


class UserUpdateRequest(BaseModel):
    """Self-service profile update (non-admin)."""
    email: Optional[str] = None
    password: Optional[str] = Field(default=None, min_length=6, max_length=128)


class UserRoleUpdateRequest(BaseModel):
    """Admin-only: change a user's role."""
    role: UserRole


class UserQuotaUpdateRequest(BaseModel):
    """Admin-only: set a user's API-token quota."""
    api_token_quota: int = Field(ge=0)


# ---------------------------------------------------------------------------
# Stored record (internal — includes hashed password)
# ---------------------------------------------------------------------------

class UserRecord(BaseModel):
    """Full user record persisted to disk (not exposed via API directly)."""
    id: str
    username: str
    hashed_password: str
    email: str
    role: UserRole = UserRole.user
    api_token_quota: int = 100  # default quota
    is_active: bool = True
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Response models (safe for frontend)
# ---------------------------------------------------------------------------

class UserProfile(BaseModel):
    """User information returned to the frontend (never includes password hash)."""
    id: str
    username: str
    email: str
    role: UserRole
    api_token_quota: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class UserListResponse(BaseModel):
    """Paginated (future) list of user profiles."""
    items: list[UserProfile]


class TokenResponse(BaseModel):
    """JWT token response after successful login."""
    access_token: str
    token_type: str = "bearer"
    user: UserProfile
