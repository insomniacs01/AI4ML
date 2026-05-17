from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


DEFAULT_TOOL_NAMES = (
    "search",
    "web_search",
    "brave_web_search",
    "tavily_search",
    "tavily_search_results",
)


def search_with_mcp(
    *,
    server_url: str,
    query: str,
    tool_name: str | None = None,
    top_k: int = 5,
    timeout_seconds: float = 20.0,
) -> list[dict[str, Any]]:
    if not server_url or not query:
        return []
    try:
        return asyncio.run(
            _search_with_mcp_async(
                server_url=server_url,
                query=query,
                tool_name=tool_name,
                top_k=top_k,
                timeout_seconds=timeout_seconds,
            )
        )
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                _search_with_mcp_async(
                    server_url=server_url,
                    query=query,
                    tool_name=tool_name,
                    top_k=top_k,
                    timeout_seconds=timeout_seconds,
                )
            )
        finally:
            loop.close()


async def _search_with_mcp_async(
    *,
    server_url: str,
    query: str,
    tool_name: str | None,
    top_k: int,
    timeout_seconds: float,
) -> list[dict[str, Any]]:
    from fastmcp import Client

    async def _run() -> list[dict[str, Any]]:
        async with Client(server_url) as client:
            selected_tool = await _select_tool(client, tool_name)
            if selected_tool is None:
                logger.warning("No compatible MCP web search tool found at %s", server_url)
                return []
            result = await client.call_tool(selected_tool, _search_arguments(query=query, top_k=top_k))
            return _normalize_mcp_result(result)

    return await asyncio.wait_for(_run(), timeout=timeout_seconds)


async def _select_tool(client: Any, configured_tool_name: str | None) -> str | None:
    tools = await client.list_tools()
    names = [tool.name for tool in tools]
    if configured_tool_name:
        return configured_tool_name if configured_tool_name in names else None
    lowered = {name.lower(): name for name in names}
    for candidate in DEFAULT_TOOL_NAMES:
        if candidate in lowered:
            return lowered[candidate]
    for name in names:
        lowered_name = name.lower()
        if "search" in lowered_name or "web" in lowered_name:
            return name
    return None


def _search_arguments(*, query: str, top_k: int) -> dict[str, Any]:
    return {
        "query": query,
        "q": query,
        "search_query": query,
        "max_results": top_k,
        "count": top_k,
        "limit": top_k,
    }


def _normalize_mcp_result(result: Any) -> list[dict[str, Any]]:
    payload = _extract_payload(result)
    candidates = _candidate_items(payload)
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(candidates):
        if isinstance(item, str):
            title = item.splitlines()[0][:120] if item.strip() else f"Search result {index + 1}"
            normalized.append({"title": title, "url": "", "snippet": item.strip(), "content": item.strip()})
            continue
        if not isinstance(item, dict):
            continue
        title = _first_text(item, "title", "name", "heading") or f"Search result {index + 1}"
        url = _first_text(item, "url", "link", "href") or ""
        snippet = _first_text(item, "snippet", "description", "summary", "content", "text") or ""
        content = _first_text(item, "content", "text", "body", "snippet", "description", "summary") or snippet
        if not snippet and content:
            snippet = content[:400]
        normalized.append({"title": title, "url": url, "snippet": snippet, "content": content or snippet})
    return [item for item in normalized if item.get("title") or item.get("snippet") or item.get("content")]


def _extract_payload(result: Any) -> Any:
    if hasattr(result, "content"):
        result = result.content
    if isinstance(result, list):
        values = []
        for item in result:
            text = getattr(item, "text", None)
            if isinstance(text, str):
                values.append(_loads_or_text(text))
            else:
                values.append(item)
        if len(values) == 1:
            return values[0]
        return values
    text = getattr(result, "text", None)
    if isinstance(text, str):
        return _loads_or_text(text)
    return result


def _loads_or_text(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _candidate_items(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("results", "items", "organic_results", "web", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
        return [payload]
    if isinstance(payload, str):
        return [payload]
    return []


def _first_text(item: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None
