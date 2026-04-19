"""File-based user storage — mirrors the existing TaskStore pattern.

Directory layout::

    storage/users/
        index.json          # {username: user_id} mapping for fast lookup
        <user_id>/
            user.json       # serialised UserRecord
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4

from backend.app.core.security import hash_password
from backend.app.models.user import (
    UserRecord,
    UserRegisterRequest,
    UserRole,
    UserUpdateRequest,
)

logger = logging.getLogger(__name__)

_DEFAULT_ADMIN_USERNAME = "admin"
_DEFAULT_ADMIN_PASSWORD = "admin123"
_DEFAULT_ADMIN_EMAIL = "admin@ai4ml.local"


class UserStore:
    """Persistent, file-based user storage."""

    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_default_admin()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_user(self, payload: UserRegisterRequest) -> UserRecord:
        """Create a new user.  Raises ``ValueError`` if username is taken."""
        index = self._load_index()
        if payload.username in index:
            raise ValueError(f"用户名已存在 (username '{payload.username}' already exists)")

        now = datetime.now(timezone.utc)
        user = UserRecord(
            id=uuid4().hex[:8],
            username=payload.username,
            hashed_password=hash_password(payload.password),
            email=payload.email,
            role=payload.role,
            created_at=now,
            updated_at=now,
        )
        self._save_user(user)
        index[user.username] = user.id
        self._save_index(index)
        return user

    def get_user_by_id(self, user_id: str) -> Optional[UserRecord]:
        user_file = self._user_file(user_id)
        if not user_file.exists():
            return None
        return UserRecord.model_validate_json(user_file.read_text(encoding="utf-8"))

    def get_user_by_username(self, username: str) -> Optional[UserRecord]:
        index = self._load_index()
        user_id = index.get(username)
        if user_id is None:
            return None
        return self.get_user_by_id(user_id)

    def list_users(self) -> list[UserRecord]:
        users: list[UserRecord] = []
        for user_dir in sorted(self.root_dir.glob("*")):
            user_file = user_dir / "user.json"
            if not user_file.exists():
                continue
            users.append(UserRecord.model_validate_json(user_file.read_text(encoding="utf-8")))
        return sorted(users, key=lambda u: u.created_at, reverse=True)

    def update_user(self, user_id: str, payload: UserUpdateRequest) -> Optional[UserRecord]:
        user = self.get_user_by_id(user_id)
        if user is None:
            return None
        if payload.email is not None:
            user.email = payload.email
        if payload.password is not None:
            user.hashed_password = hash_password(payload.password)
        self._save_user(user)
        return user

    def update_user_role(self, user_id: str, role: UserRole) -> Optional[UserRecord]:
        user = self.get_user_by_id(user_id)
        if user is None:
            return None
        user.role = role
        self._save_user(user)
        return user

    def update_user_quota(self, user_id: str, quota: int) -> Optional[UserRecord]:
        user = self.get_user_by_id(user_id)
        if user is None:
            return None
        user.api_token_quota = quota
        self._save_user(user)
        return user

    def delete_user(self, user_id: str) -> bool:
        user = self.get_user_by_id(user_id)
        if user is None:
            return False
        # Remove from index
        index = self._load_index()
        index.pop(user.username, None)
        self._save_index(index)
        # Remove user directory
        user_file = self._user_file(user_id)
        user_file.unlink(missing_ok=True)
        user_dir = self._user_dir(user_id)
        if user_dir.exists() and not any(user_dir.iterdir()):
            user_dir.rmdir()
        return True

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _save_user(self, user: UserRecord) -> None:
        user_dir = self._user_dir(user.id)
        user_dir.mkdir(parents=True, exist_ok=True)
        user.updated_at = datetime.now(timezone.utc)
        self._user_file(user.id).write_text(user.model_dump_json(indent=2), encoding="utf-8")

    def _user_dir(self, user_id: str) -> Path:
        return self.root_dir / user_id

    def _user_file(self, user_id: str) -> Path:
        return self._user_dir(user_id) / "user.json"

    # -- Index management --

    def _index_path(self) -> Path:
        return self.root_dir / "index.json"

    def _load_index(self) -> dict[str, str]:
        path = self._index_path()
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def _save_index(self, index: dict[str, str]) -> None:
        self._index_path().write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")

    # -- Bootstrap --

    def _ensure_default_admin(self) -> None:
        """Create the default admin account if no users exist."""
        index = self._load_index()
        if index:
            return  # users already exist
        logger.info("No users found — creating default admin account '%s'", _DEFAULT_ADMIN_USERNAME)
        self.create_user(
            UserRegisterRequest(
                username=_DEFAULT_ADMIN_USERNAME,
                password=_DEFAULT_ADMIN_PASSWORD,
                email=_DEFAULT_ADMIN_EMAIL,
                role=UserRole.admin,
            )
        )
