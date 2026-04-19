"""User authentication and management API routes.

Public endpoints:
    POST /auth/register   — register a new user
    POST /auth/login      — login and receive a JWT token

Authenticated endpoints:
    GET    /users/me                  — current user's profile
    PUT    /users/me                  — update own profile (email / password)

Admin-only endpoints:
    GET    /users                     — list all users
    GET    /users/{user_id}           — get a specific user
    PUT    /users/{user_id}/role      — change a user's role
    PUT    /users/{user_id}/quota     — set API-token quota
    DELETE /users/{user_id}           — delete a user
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status

from backend.app.core.deps import get_current_user, get_user_store, require_admin
from backend.app.core.security import create_access_token, verify_password
from backend.app.models.user import (
    TokenResponse,
    UserListResponse,
    UserLoginRequest,
    UserProfile,
    UserQuotaUpdateRequest,
    UserRegisterRequest,
    UserRoleUpdateRequest,
    UserUpdateRequest,
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

auth_router = APIRouter(prefix="/auth", tags=["auth"])
users_router = APIRouter(prefix="/users", tags=["users"])


# ============================= Auth ========================================

@auth_router.post("/register", response_model=UserProfile, status_code=status.HTTP_201_CREATED)
def register(payload: UserRegisterRequest) -> UserProfile:
    """Register a new user account."""
    store = get_user_store()
    try:
        user = store.create_user(payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return UserProfile(**user.model_dump(exclude={"hashed_password"}))


@auth_router.post("/login", response_model=TokenResponse)
def login(payload: UserLoginRequest) -> TokenResponse:
    """Authenticate with username + password and receive a JWT token."""
    store = get_user_store()
    user = store.get_user_by_username(payload.username)
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误 (invalid username or password)",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账户已被禁用 (account is disabled)",
        )
    token = create_access_token({"sub": user.id, "role": user.role.value})
    profile = UserProfile(**user.model_dump(exclude={"hashed_password"}))
    return TokenResponse(access_token=token, user=profile)


# ============================ Users (self) =================================

@users_router.get("/me", response_model=UserProfile)
def get_me(current_user: UserProfile = Depends(get_current_user)) -> UserProfile:
    """Return the currently authenticated user's profile."""
    return current_user


@users_router.put("/me", response_model=UserProfile)
def update_me(
    payload: UserUpdateRequest,
    current_user: UserProfile = Depends(get_current_user),
) -> UserProfile:
    """Update the current user's own profile (email / password)."""
    store = get_user_store()
    updated = store.update_user(current_user.id, payload)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    return UserProfile(**updated.model_dump(exclude={"hashed_password"}))


# ============================ Users (admin) ================================

@users_router.get("", response_model=UserListResponse)
def list_users(
    _admin: UserProfile = Depends(require_admin),
) -> UserListResponse:
    """(Admin) List all users."""
    store = get_user_store()
    users = store.list_users()
    profiles = [UserProfile(**u.model_dump(exclude={"hashed_password"})) for u in users]
    return UserListResponse(items=profiles)


@users_router.get("/{user_id}", response_model=UserProfile)
def get_user(
    user_id: str,
    _admin: UserProfile = Depends(require_admin),
) -> UserProfile:
    """(Admin) Get a specific user's profile."""
    store = get_user_store()
    user = store.get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    return UserProfile(**user.model_dump(exclude={"hashed_password"}))


@users_router.put("/{user_id}/role", response_model=UserProfile)
def update_user_role(
    user_id: str,
    payload: UserRoleUpdateRequest,
    _admin: UserProfile = Depends(require_admin),
) -> UserProfile:
    """(Admin) Change a user's role."""
    store = get_user_store()
    updated = store.update_user_role(user_id, payload.role)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    return UserProfile(**updated.model_dump(exclude={"hashed_password"}))


@users_router.put("/{user_id}/quota", response_model=UserProfile)
def update_user_quota(
    user_id: str,
    payload: UserQuotaUpdateRequest,
    _admin: UserProfile = Depends(require_admin),
) -> UserProfile:
    """(Admin) Set a user's API-token quota."""
    store = get_user_store()
    updated = store.update_user_quota(user_id, payload.api_token_quota)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    return UserProfile(**updated.model_dump(exclude={"hashed_password"}))


@users_router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: str,
    admin: UserProfile = Depends(require_admin),
) -> Response:
    """(Admin) Delete a user account."""
    if user_id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="不能删除自己的账户 (cannot delete your own account)",
        )
    store = get_user_store()
    if not store.delete_user(user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)

