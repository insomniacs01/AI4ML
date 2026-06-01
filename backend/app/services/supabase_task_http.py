from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from backend.app.core.config import Settings


class SupabaseTaskHttpClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def request_json(
        self,
        *,
        path: str,
        access_token: str,
        method: str = "GET",
        body: dict[str, Any] | None = None,
        expect_json: bool = True,
        prefer: str | None = None,
    ) -> Any:
        self._ensure_configured()
        url = f"{self.settings.supabase_rest_url.rstrip('/')}/{path.lstrip('/')}"
        headers = {
            "Accept": "application/json",
            "apikey": self.settings.supabase_publishable_key,
            "Authorization": f"Bearer {access_token}",
            "Accept-Profile": "public",
            "Content-Profile": "public",
        }
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            headers["Prefer"] = prefer or "return=representation"
            data = json.dumps(body).encode("utf-8")
        elif prefer:
            headers["Prefer"] = prefer

        request = Request(url, data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.settings.supabase_timeout_seconds) as response:  # noqa: S310
                raw_body = response.read().decode("utf-8")
        except HTTPError as exc:
            payload = exc.read().decode("utf-8", errors="ignore")
            if exc.code in (401, 403):
                raise PermissionError("Supabase rejected the task storage request.") from exc
            if "does not exist" in payload:
                raise RuntimeError("Supabase task schema is missing. Apply supabase/schema.sql before using task storage.") from exc
            raise ConnectionError(f"Supabase task request failed with HTTP {exc.code}. Response: {payload or '<empty>'}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise ConnectionError("Could not reach Supabase to read or write task records.") from exc

        if not raw_body:
            return None if expect_json else True
        try:
            return json.loads(raw_body)
        except json.JSONDecodeError as exc:
            if expect_json:
                raise ConnectionError("Supabase task response was not valid JSON.") from exc
            return True

    def _ensure_configured(self) -> None:
        if self.settings.supabase_configured:
            return
        raise RuntimeError("Supabase task storage is not configured. Set AI4ML_SUPABASE_URL / AI4ML_SUPABASE_PUBLISHABLE_KEY or keep frontend/.env.local available.")
