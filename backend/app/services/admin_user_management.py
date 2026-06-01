from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from backend.app.core.config import Settings


class AdminUserManagementError(RuntimeError):
    pass


def reset_supabase_user_password(settings: Settings, *, user_id: str, password: str) -> None:
    if not settings.supabase_admin_configured:
        raise AdminUserManagementError(
            "Supabase service role key is not configured. Set AI4ML_SUPABASE_SERVICE_ROLE_KEY to enable admin password reset."
        )

    url = f"{settings.supabase_auth_admin_users_url.rstrip('/')}/{user_id}"
    body = json.dumps({"password": password}, ensure_ascii=False).encode("utf-8")
    request = Request(
        url,
        data=body,
        method="PUT",
        headers={
            "Content-Type": "application/json",
            "apikey": settings.supabase_service_role_key,
            "Authorization": f"Bearer {settings.supabase_service_role_key}",
        },
    )
    try:
        with urlopen(request, timeout=settings.supabase_timeout_seconds) as response:  # noqa: S310
            response.read()
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise AdminUserManagementError(f"Supabase password reset failed with HTTP {exc.code}: {detail}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise AdminUserManagementError("Could not reach Supabase admin API to reset password.") from exc


def update_supabase_user_profile(settings: Settings, *, user_id: str, display_name: str | None) -> dict[str, Any]:
    if not settings.supabase_admin_configured:
        raise AdminUserManagementError(
            "Supabase service role key is not configured. Set AI4ML_SUPABASE_SERVICE_ROLE_KEY to enable admin profile updates."
        )

    url = f"{settings.supabase_rest_url.rstrip('/')}/profiles?user_id=eq.{quote(user_id, safe='')}"
    body = json.dumps({"display_name": display_name.strip() if display_name else None}, ensure_ascii=False).encode("utf-8")
    request = Request(
        url,
        data=body,
        method="PATCH",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "apikey": settings.supabase_service_role_key,
            "Authorization": f"Bearer {settings.supabase_service_role_key}",
            "Accept-Profile": "public",
            "Content-Profile": "public",
            "Prefer": "return=representation",
        },
    )
    try:
        with urlopen(request, timeout=settings.supabase_timeout_seconds) as response:  # noqa: S310
            raw_body = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise AdminUserManagementError(f"Supabase profile update failed with HTTP {exc.code}: {detail}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise AdminUserManagementError("Could not reach Supabase admin API to update profile.") from exc

    try:
        payload = json.loads(raw_body) if raw_body else []
    except json.JSONDecodeError as exc:
        raise AdminUserManagementError("Supabase profile update returned invalid JSON.") from exc
    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        return payload[0]
    if isinstance(payload, dict):
        return payload
    raise AdminUserManagementError("Supabase profile update did not return a profile row.")
