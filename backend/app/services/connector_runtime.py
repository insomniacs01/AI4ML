from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

from backend.app.core.config import Settings
from backend.app.models.connector import ConnectorWireApi, StoredConnectorRecord


class ProviderProbeResult:
    def __init__(self, *, ok: bool, detail: str, model_listed: bool, inference_ok: bool) -> None:
        self.ok = ok
        self.detail = detail
        self.model_listed = model_listed
        self.inference_ok = inference_ok


def normalize_provider_config(*, endpoint_url: str | None, base_url: str | None, wire_api: str) -> tuple[str, ConnectorWireApi]:
    raw_url = (endpoint_url or base_url or "").strip()
    if not raw_url:
        raise ValueError("API 地址不能为空。请填写完整 endpoint，或直接填写 base URL。")

    parsed = urlsplit(raw_url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("API 地址必须包含 http:// 或 https://，例如 https://api.example.com/v1/chat/completions")

    normalized_path = parsed.path.rstrip("/")
    inferred_wire_api: ConnectorWireApi | None = None
    suffix_map = {
        "/chat/completions": ConnectorWireApi.chat_completions,
        "/responses": ConnectorWireApi.responses,
        "/models": None,
    }
    for suffix, suffix_wire_api in suffix_map.items():
        if normalized_path.endswith(suffix):
            normalized_path = normalized_path[: -len(suffix)]
            inferred_wire_api = suffix_wire_api
            break

    normalized_base_url = urlunsplit((parsed.scheme, parsed.netloc, normalized_path, "", "")).rstrip("/")
    if not normalized_base_url:
        raise ValueError("无法从输入的 API 地址中解析出有效的 base URL。")

    resolved_wire_api = inferred_wire_api or ConnectorWireApi.chat_completions if wire_api == "auto" else ConnectorWireApi(wire_api)
    return normalized_base_url, resolved_wire_api


def probe_provider(*, base_url: str, api_key: str, model_name: str, wire_api: ConnectorWireApi, timeout_seconds: int, user_agent: str) -> ProviderProbeResult:
    normalized_base_url = base_url.rstrip("/")
    common_headers = {"Authorization": f"Bearer {api_key.strip()}", "User-Agent": user_agent}
    notes: list[str] = []
    model_listed = False
    inference_ok = False

    try:
        models_payload = _request_json(f"{normalized_base_url}/models", headers=common_headers, body=None, timeout_seconds=timeout_seconds)
        model_ids = [item.get("id", "") for item in models_payload.get("data", []) if isinstance(item, dict)]
        model_listed = model_name in model_ids
        notes.append("/models 可访问，且已找到目标模型。" if model_listed else f"/models 可访问，但未列出模型 {model_name}。")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        notes.append(f"/models 返回 HTTP {exc.code}: {body or '<empty>'}")
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        notes.append(f"/models 请求失败: {exc}")

    inference_path = "/responses" if wire_api == ConnectorWireApi.responses else "/chat/completions"
    inference_payload = {"model": model_name, "input": "Reply with exactly: openai-compatible-ok"} if wire_api == ConnectorWireApi.responses else {"model": model_name, "messages": [{"role": "user", "content": "Reply with exactly: openai-compatible-ok"}], "max_tokens": 16, "temperature": 0}

    try:
        inference_response = _request_json(f"{normalized_base_url}{inference_path}", headers={**common_headers, "Content-Type": "application/json"}, body=inference_payload, timeout_seconds=timeout_seconds)
        inference_ok = True
        preview = _extract_preview(inference_response, wire_api)
        notes.append(f"{inference_path} 调用成功，模型返回：{preview}" if preview else f"{inference_path} 调用成功。")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        notes.append(f"{inference_path} 返回 HTTP {exc.code}: {body or '<empty>'}")
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        notes.append(f"{inference_path} 请求失败: {exc}")

    ok = model_listed and inference_ok
    notes.append("这个连接器满足当前 AI Provider 的基本要求。" if ok else "这个连接器已经保存，但目前还不能确认它可以直接驱动当前 AI Provider。")
    return ProviderProbeResult(ok=ok, detail=" ".join(notes), model_listed=model_listed, inference_ok=inference_ok)


def build_runtime_settings(settings: Settings, connector: StoredConnectorRecord) -> Settings:
    return settings.model_copy(
        update={
            "ai_provider_base_url": connector.base_url.rstrip("/"),
            "ai_provider_model_name": connector.model_name,
            "ai_provider_wire_api": connector.wire_api.value,
            "ai_provider_api_key": connector.api_key,
        }
    )


def _request_json(url: str, *, headers: dict[str, str], body: dict | None, timeout_seconds: int) -> dict:
    request = Request(url, data=None if body is None else json.dumps(body).encode("utf-8"), headers=headers)
    with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def _extract_preview(payload: dict, wire_api: ConnectorWireApi) -> str:
    preview = payload.get("output", [{}])[0].get("content", [{}])[0].get("text", "").strip() if wire_api == ConnectorWireApi.responses else payload.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
    return preview.replace("\r", " ").replace("\n", " ").strip()[:160]
