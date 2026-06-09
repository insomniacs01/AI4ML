from __future__ import annotations

from binascii import Error as BinasciiError
import json
import time
from base64 import urlsafe_b64decode
from dataclasses import dataclass
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.app.core.config import Settings, get_settings


_bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class SupabaseUser:
    id: str
    email: str | None
    raw: dict[str, Any]


@dataclass(frozen=True)
class TeamAccessContext:
    team_id: str
    role: str
    user: SupabaseUser
    access_token: str


TEAM_ADMIN_ROLES = {"admin", "team_owner"}
TEAM_DEVELOPER_ROLES = {"admin", "team_owner", "developer_user"}
TEAM_OWNER_ROLES = {"team_owner"}


AUTH_CACHE_TTL_SECONDS = 300.0


class SupabaseClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._user_cache: dict[str, tuple[float, SupabaseUser]] = {}
        self._membership_cache: dict[tuple[str, str, str], tuple[float, dict[str, Any] | None]] = {}
        repo_root = getattr(settings, "repo_root", None)
        self._membership_cache_dir = (
            Path(repo_root) / "storage" / "auth_cache" / "team_memberships"
            if repo_root is not None
            else None
        )
        self._cache_lock = Lock()

    def get_user(self, access_token: str) -> SupabaseUser:
        token_key = self._token_cache_key(access_token)
        with self._cache_lock:
            cached = self._user_cache.get(token_key)
            if cached and self._cache_is_fresh(cached[0]):
                return cached[1]
            payload = self._request_json(self.settings.supabase_auth_user_url, access_token)
            user_id = payload.get("id")
            if not isinstance(user_id, str) or not user_id:
                raise PermissionError("Supabase token response did not include a valid user id.")
            user = SupabaseUser(
                id=user_id,
                email=payload.get("email"),
                raw=payload,
            )
            self._user_cache[token_key] = (time.monotonic(), user)
            return user

    def get_team_membership(self, access_token: str, *, team_id: str, user_id: str) -> dict[str, Any] | None:
        token_key = self._token_cache_key(access_token)
        cache_key = (token_key, team_id, user_id)
        with self._cache_lock:
            cached = self._membership_cache.get(cache_key)
            if cached and self._cache_is_fresh(cached[0]):
                return cached[1]
            query = (
                "team_members"
                f"?select=team_id,user_id,role,member_status&team_id=eq.{quote(team_id, safe='')}"
                f"&user_id=eq.{quote(user_id, safe='')}&limit=1"
            )
            payload = self._request_json(f"{self.settings.supabase_rest_url}/{query}", access_token)
            if not isinstance(payload, list):
                raise ConnectionError("Unexpected team membership response from Supabase.")
            membership = payload[0] if payload else None
            self._membership_cache[cache_key] = (time.monotonic(), membership)
            return membership

    def get_team_access(self, access_token: str, *, team_id: str) -> tuple[SupabaseUser, dict[str, Any] | None]:
        token_key = self._token_cache_key(access_token)
        user = self._user_from_cached_token(token_key) or self._user_from_jwt_claims(access_token)
        if user is None:
            user = self.get_user(access_token)
        cache_key = (token_key, team_id, user.id)
        cached = self._cached_membership(cache_key)
        if cached is not None:
            return user, cached
        persisted = self._read_persisted_membership(cache_key)
        if persisted is not None:
            with self._cache_lock:
                self._user_cache[token_key] = (time.monotonic(), user)
                self._membership_cache[cache_key] = (time.monotonic(), persisted)
            return user, persisted

        query = (
            "team_members"
            f"?select=team_id,user_id,role,member_status&team_id=eq.{quote(team_id, safe='')}"
            f"&user_id=eq.{quote(user.id, safe='')}&limit=1"
        )
        payload = self._request_json(f"{self.settings.supabase_rest_url}/{query}", access_token)
        if not isinstance(payload, list):
            raise ConnectionError("Unexpected team membership response from Supabase.")
        membership = payload[0] if payload else None
        with self._cache_lock:
            self._user_cache[token_key] = (time.monotonic(), user)
            self._membership_cache[cache_key] = (time.monotonic(), membership)
        if membership is not None:
            self._write_persisted_membership(cache_key, membership)
        return user, membership

    def _user_from_cached_token(self, token_key: str) -> SupabaseUser | None:
        with self._cache_lock:
            cached = self._user_cache.get(token_key)
            if cached and self._cache_is_fresh(cached[0]):
                return cached[1]
        return None

    def _cached_membership(self, cache_key: tuple[str, str, str]) -> dict[str, Any] | None:
        with self._cache_lock:
            cached = self._membership_cache.get(cache_key)
            if cached and self._cache_is_fresh(cached[0]):
                return cached[1]
        return None

    def _read_persisted_membership(self, cache_key: tuple[str, str, str]) -> dict[str, Any] | None:
        cache_path = self._membership_cache_path(cache_key)
        if cache_path is None or not cache_path.exists():
            return None
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            cached_at = float(payload.get("cached_at") or 0)
            if time.time() - cached_at >= AUTH_CACHE_TTL_SECONDS:
                cache_path.unlink(missing_ok=True)
                return None
            membership = payload.get("membership")
            return membership if isinstance(membership, dict) else None
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None

    def _write_persisted_membership(self, cache_key: tuple[str, str, str], membership: dict[str, Any]) -> None:
        cache_path = self._membership_cache_path(cache_key)
        if cache_path is None:
            return
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(
                json.dumps(
                    {
                        "cached_at": time.time(),
                        "membership": membership,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
        except OSError:
            return

    def _membership_cache_path(self, cache_key: tuple[str, str, str]) -> Path | None:
        if self._membership_cache_dir is None:
            return None
        token_key, team_id, user_id = cache_key
        team_key = sha256(team_id.encode("utf-8")).hexdigest()[:16]
        user_key = sha256(user_id.encode("utf-8")).hexdigest()[:16]
        return self._membership_cache_dir / f"{token_key[:24]}-{team_key}-{user_key}.json"

    @staticmethod
    def _user_from_jwt_claims(access_token: str) -> SupabaseUser | None:
        parts = access_token.split(".")
        if len(parts) < 2:
            return None
        payload = parts[1]
        payload += "=" * (-len(payload) % 4)
        try:
            claims = json.loads(urlsafe_b64decode(payload.encode("ascii")).decode("utf-8"))
        except (BinasciiError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        user_id = claims.get("sub")
        if not isinstance(user_id, str) or not user_id:
            return None
        email = claims.get("email")
        return SupabaseUser(
            id=user_id,
            email=email if isinstance(email, str) else None,
            raw=claims,
        )

    @staticmethod
    def _token_cache_key(access_token: str) -> str:
        return sha256(access_token.encode("utf-8")).hexdigest()

    @staticmethod
    def _cache_is_fresh(cached_at: float) -> bool:
        return time.monotonic() - cached_at < AUTH_CACHE_TTL_SECONDS

    def _request_json(self, url: str, access_token: str) -> Any:
        self._ensure_configured()
        headers = {
            "Accept": "application/json",
            "apikey": self.settings.supabase_publishable_key,
            "Authorization": f"Bearer {access_token}",
        }
        if url.startswith(self.settings.supabase_rest_url):
            headers["Accept-Profile"] = "public"
        request = Request(url, headers=headers, method="GET")

        try:
            with urlopen(request, timeout=self.settings.supabase_timeout_seconds) as response:  # noqa: S310
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            payload = exc.read().decode("utf-8", errors="ignore")
            if exc.code in (401, 403):
                raise PermissionError("Supabase rejected the provided access token.") from exc
            raise ConnectionError(
                f"Supabase request failed with HTTP {exc.code}. Response: {payload or '<empty>'}"
            ) from exc
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise ConnectionError("Could not reach Supabase to validate the current session.") from exc

    def _ensure_configured(self) -> None:
        if self.settings.supabase_configured:
            return
        raise RuntimeError(
            "Supabase backend auth is not configured. "
            "Set AI4ML_SUPABASE_URL / AI4ML_SUPABASE_PUBLISHABLE_KEY or keep frontend/.env.local available."
        )


@lru_cache
def get_supabase_client() -> SupabaseClient:
    return SupabaseClient(get_settings())


def get_current_supabase_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    client: SupabaseClient = Depends(get_supabase_client),
) -> tuple[SupabaseUser, str]:
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Supabase Bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = credentials.credentials
    try:
        user = client.get_user(access_token)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except ConnectionError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    return user, access_token


def require_team_access(
    team_id: str | None = None,
    x_team_id: str | None = Header(default=None, alias="X-Team-Id"),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    client: SupabaseClient = Depends(get_supabase_client),
) -> TeamAccessContext:
    resolved_team_id = (team_id or "").strip() or (x_team_id or "").strip()
    if not resolved_team_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Team-Id header is required for task operations.",
        )

    normalized_team_id = resolved_team_id
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Supabase Bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = credentials.credentials

    try:
        user, membership = client.get_team_access(
            access_token,
            team_id=normalized_team_id,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except ConnectionError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to the requested team.",
        )
    member_status = str(membership.get("member_status", "active"))
    if member_status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your membership in the requested team is not active.",
        )

    return TeamAccessContext(
        team_id=normalized_team_id,
        role=str(membership.get("role", "member")),
        user=user,
        access_token=access_token,
    )


def require_team_admin_access(
    team_access: TeamAccessContext = Depends(require_team_access),
) -> TeamAccessContext:
    if team_access.role not in TEAM_ADMIN_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This operation requires a team admin role.",
        )
    return team_access


def require_team_owner_access(
    team_access: TeamAccessContext = Depends(require_team_access),
) -> TeamAccessContext:
    if team_access.role not in TEAM_OWNER_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This operation requires the team owner role.",
        )
    return team_access


def require_team_developer_access(
    team_access: TeamAccessContext = Depends(require_team_access),
) -> TeamAccessContext:
    if team_access.role not in TEAM_DEVELOPER_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This operation requires a developer or team admin role.",
        )
    return team_access
