from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from backend.app.core.config import Settings


class OpenAICompatibleProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def unavailability_reason(self) -> str | None:
        if not self.settings.ai_provider_base_url.strip():
            return "AI provider base URL is missing"
        if not self.settings.ai_provider_api_key.strip():
            return "AI provider api key is missing"
        if not self.settings.ai_provider_model_name.strip():
            return "AI provider model name is missing"
        if self.settings.ai_provider_model_name.startswith("Pro/"):
            return f"Pro models are blocked by project policy. Configured model: {self.settings.ai_provider_model_name}"

        try:
            request = Request(
                f"{self.settings.ai_provider_base_url.rstrip('/')}/models",
                headers={
                    "Authorization": f"Bearer {self.settings.ai_provider_api_key}",
                    "User-Agent": self.settings.ai_provider_user_agent,
                },
            )
            with urlopen(request, timeout=self.settings.ai_provider_request_timeout_seconds) as response:  # noqa: S310
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            return f"AI provider returned HTTP {exc.code}: {body}"
        except (URLError, TimeoutError, OSError) as exc:
            return f"AI provider request failed: {exc}"
        except json.JSONDecodeError as exc:
            return f"AI provider returned invalid JSON: {exc}"

        model_ids = [item.get("id", "") for item in payload.get("data", []) if isinstance(item, dict)]
        if self.settings.ai_provider_model_name not in model_ids:
            return f"configured AI model is not listed by the provider: {self.settings.ai_provider_model_name}"
        return None
