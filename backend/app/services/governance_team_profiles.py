from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.app.models.governance import TeamProfileRecord
from backend.app.services.governance_http import unwrap_single_record
from backend.app.services.governance_payload_values import optional_payload_str
from backend.app.services.governance_team_queries import normalized_profile_ids, profile_update_path, profiles_path
from backend.app.services.governance_team_records import profile_records_from_payload

RequestJson = Callable[..., Any]


def list_team_profiles(
    request_json: RequestJson,
    user_ids: list[str],
    *,
    access_token: str,
) -> list[TeamProfileRecord]:
    normalized_ids = normalized_profile_ids(user_ids)
    if not normalized_ids:
        return []
    payload = request_json(
        path=profiles_path(normalized_ids),
        access_token=access_token,
    )
    if not isinstance(payload, list):
        raise ConnectionError("Unexpected profile response from Supabase.")
    return profile_records_from_payload(payload)


def update_team_profile(
    request_json: RequestJson,
    user_id: str,
    *,
    display_name: str | None,
    access_token: str,
) -> TeamProfileRecord:
    payload = request_json(
        path=profile_update_path(user_id),
        access_token=access_token,
        method="PATCH",
        body={"display_name": display_name.strip() if display_name else None},
    )
    row = unwrap_single_record(payload, "profile update")
    return TeamProfileRecord(
        user_id=str(row.get("user_id")),
        email=optional_payload_str(row.get("email")),
        display_name=optional_payload_str(row.get("display_name")),
    )
