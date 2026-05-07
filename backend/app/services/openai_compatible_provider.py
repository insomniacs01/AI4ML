from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from backend.app.core.config import Settings
from backend.app.models.task import TokenUsageReport
from backend.app.services.token_usage import extract_provider_token_usage, make_provider_tokenizer_usage_report


@dataclass
class ProviderCallResult:
    text: str
    token_usage: TokenUsageReport | None
    token_usage_calculation_method: str | None = None


def call_openai_compatible_provider(
    *,
    prompt: str,
    settings: Settings,
    system_message: str,
    temperature: float = 0,
    max_tokens: int = 1200,
) -> ProviderCallResult:
    base_url = settings.mlzero_provider_base_url.rstrip("/")
    headers = {
        "Authorization": f"Bearer {settings.mlzero_openai_api_key}",
        "Content-Type": "application/json",
        "User-Agent": settings.mlzero_provider_user_agent,
    }

    if settings.mlzero_provider_wire_api == "responses":
        endpoint = f"{base_url}/responses"
        body: dict[str, Any] = {
            "model": settings.mlzero_model_alias,
            "input": f"System instruction:\n{system_message}\n\nUser prompt:\n{prompt}",
        }
    else:
        endpoint = f"{base_url}/chat/completions"
        body = {
            "model": settings.mlzero_model_alias,
            "messages": [
                {"role": "system", "content": system_message},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

    request = Request(endpoint, data=json.dumps(body).encode("utf-8"), headers=headers)
    try:
        with urlopen(request, timeout=settings.mlzero_provider_request_timeout_seconds) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"AI 请求返回 HTTP {exc.code}: {body}") from exc
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"AI 请求失败：{exc}") from exc

    text = _extract_response_text(payload, wire_api=settings.mlzero_provider_wire_api)
    if not text:
        raise RuntimeError("AI 返回了空内容。")

    token_usage = extract_provider_token_usage(payload)
    calculation_method = "provider_reported_usage" if token_usage is not None else None
    if token_usage is None:
        token_usage = make_provider_tokenizer_usage_report(
            prompt=prompt,
            system_message=system_message,
            response_text=text,
            model_name=settings.mlzero_model_alias,
            tokenizer_model_name=settings.mlzero_tokenizer_model_alias or None,
            wire_api=settings.mlzero_provider_wire_api,
        )
        calculation_method = "tokenizer_estimate"

    return ProviderCallResult(
        text=text,
        token_usage=token_usage,
        token_usage_calculation_method=calculation_method,
    )


def _extract_response_text(payload: dict[str, Any], *, wire_api: str) -> str:
    if wire_api == "responses":
        output_text = payload.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text.strip()

        output = payload.get("output")
        if not isinstance(output, list):
            return ""

        parts: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for content_item in content:
                if not isinstance(content_item, dict):
                    continue
                text = content_item.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
        return "\n\n".join(parts).strip()

    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""

    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        return ""

    message = first_choice.get("message")
    if not isinstance(message, dict):
        return ""

    content = message.get("content")
    if isinstance(content, str):
        return content.strip()

    if not isinstance(content, list):
        return ""

    parts: list[str] = []
    for item in content:
        if isinstance(item, str) and item.strip():
            parts.append(item.strip())
            continue
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if isinstance(text, str) and text.strip():
            parts.append(text.strip())
    return "\n\n".join(parts).strip()
