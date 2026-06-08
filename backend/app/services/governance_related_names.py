from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.parse import quote

RequestJson = Callable[..., Any]


def list_task_names(
    request_json: RequestJson,
    team_id: str,
    task_ids: list[str],
    *,
    access_token: str,
) -> dict[str, str]:
    return _list_related_names(
        request_json,
        table="ai_tasks",
        select="id,name",
        label_field="name",
        team_id=team_id,
        item_ids=task_ids,
        access_token=access_token,
        error_detail="Unexpected task-name response from Supabase.",
    )


def list_connector_names(
    request_json: RequestJson,
    team_id: str,
    connector_ids: list[str],
    *,
    access_token: str,
) -> dict[str, str]:
    return _list_related_names(
        request_json,
        table="ai_connectors",
        select="id,display_name",
        label_field="display_name",
        team_id=team_id,
        item_ids=connector_ids,
        access_token=access_token,
        error_detail="Unexpected connector-name response from Supabase.",
    )


def _list_related_names(
    request_json: RequestJson,
    *,
    table: str,
    select: str,
    label_field: str,
    team_id: str,
    item_ids: list[str],
    access_token: str,
    error_detail: str,
) -> dict[str, str]:
    normalized_ids = sorted({item for item in item_ids if item})
    if not normalized_ids:
        return {}
    payload = request_json(
        path=(
            f"{table}"
            f"?select={select}&team_id=eq.{quote(team_id, safe='')}"
            f"&id=in.({_quoted_in_list(normalized_ids)})"
        ),
        access_token=access_token,
    )
    if not isinstance(payload, list):
        raise ConnectionError(error_detail)
    return {
        str(item.get("id")): str(item.get(label_field) or item.get("id"))
        for item in payload
        if isinstance(item, dict) and item.get("id")
    }


def _quoted_in_list(values: list[str]) -> str:
    in_list = ",".join(f'"{item}"' for item in values)
    return quote(in_list, safe='(),"')
