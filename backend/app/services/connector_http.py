from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from backend.app.core.config import Settings


class ConnectorHttpClient:
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
            headers["Prefer"] = "return=representation"
            data = json.dumps(body).encode("utf-8")

        request = Request(url, data=data, headers=headers, method=method)

        try:
            with urlopen(request, timeout=self.settings.supabase_timeout_seconds) as response:  # noqa: S310
                raw_body = response.read().decode("utf-8")
        except HTTPError as exc:
            payload = exc.read().decode("utf-8", errors="ignore")
            if exc.code in (401, 403):
                raise PermissionError("Supabase rejected the connector storage request.") from exc
            if "ai_connectors" in payload and "does not exist" in payload:
                raise RuntimeError(
                    "Supabase ai_connectors schema is missing. "
                    "Apply supabase/schema.sql before using connector storage."
                ) from exc
            if "activate_ai_connector" in payload and "Could not find the function" in payload:
                raise RuntimeError(
                    "Supabase activate_ai_connector RPC is missing. "
                    "Apply supabase/schema.sql before using connector activation."
                ) from exc
            raise ConnectionError(
                f"Supabase connector request failed with HTTP {exc.code}. Response: {payload or '<empty>'}"
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise ConnectionError("Could not reach Supabase to read or write connector records.") from exc

        if not expect_json:
            return None
        if not raw_body:
            return None

        try:
            return json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise ConnectionError("Supabase connector response was not valid JSON.") from exc

    def _ensure_configured(self) -> None:
        if self.settings.supabase_configured:
            return
        raise RuntimeError(
            "Supabase connector storage is not configured. "
            "Set AI4ML_SUPABASE_URL / AI4ML_SUPABASE_PUBLISHABLE_KEY or keep frontend/.env.local available."
        )


def unwrap_single_record(payload: Any, action: str) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, list) and len(payload) == 1 and isinstance(payload[0], dict):
        return payload[0]
    raise ConnectionError(f"Unexpected Supabase response shape during {action}.")
