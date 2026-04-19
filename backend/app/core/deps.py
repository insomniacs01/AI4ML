"""FastAPI dependency helpers for authentication and role-based access control."""

from __future__ import annotations

from functools import lru_cache

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.app.core.config import get_settings
from backend.app.core.security import decode_access_token
from backend.app.models.user import UserProfile, UserRecord, UserRole
from backend.app.services.user_store import UserStore

_bearer_scheme = HTTPBearer()


@lru_cache
def get_user_store() -> UserStore:
    """Singleton user-store instance."""
    settings = get_settings()
    return UserStore(settings.user_storage_dir)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> UserProfile:
    """Extract and validate the current user from the Bearer token.

    Returns a :class:`UserProfile` (no password hash).
    """
    token = credentials.credentials
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="无法验证凭证 (could not validate credentials)",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_access_token(token)
        user_id: str | None = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except jwt.PyJWTError:
        raise credentials_exception

    user: UserRecord | None = get_user_store().get_user_by_id(user_id)
    if user is None or not user.is_active:
        raise credentials_exception

    return UserProfile(**user.model_dump(exclude={"hashed_password"}))


def require_admin(
    current_user: UserProfile = Depends(get_current_user),
) -> UserProfile:
    """Dependency that ensures the caller is an admin."""
    if current_user.role != UserRole.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理员权限 (admin role required)",
        )
    return current_user


def require_developer_or_admin(
    current_user: UserProfile = Depends(get_current_user),
) -> UserProfile:
    """Dependency that ensures the caller is a developer or admin."""
    if current_user.role not in (UserRole.developer, UserRole.admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要技术人员或管理员权限 (developer or admin role required)",
        )
    return current_user
