from __future__ import annotations

from typing import Any

from backend.app.models.governance import TeamMemberRecord, TeamQuotaRecord
from backend.app.services.governance_quota_records import ConnectorSummary, quota_map, quota_record_from_payload


def build_quota_records(
    team_id: str,
    *,
    members: list[TeamMemberRecord],
    connector_map: dict[str, str],
    quota_payload: list[Any],
) -> list[TeamQuotaRecord]:
    quota_rows = quota_map(quota_payload)
    items: list[TeamQuotaRecord] = []
    handled_keys: set[tuple[str, str]] = set()

    for member in members:
        key = ("member", member.user_id)
        items.append(quota_record_from_payload(team_id, quota_rows.get(key, {}), member=member))
        handled_keys.add(key)

    for connector_id, connector_name in connector_map.items():
        key = ("connector", connector_id)
        items.append(
            quota_record_from_payload(
                team_id,
                quota_rows.get(key, {}),
                connector=ConnectorSummary(id=connector_id, display_name=connector_name),
            )
        )
        handled_keys.add(key)

    team_key = ("team", team_id)
    items.append(quota_record_from_payload(team_id, quota_rows.get(team_key, {})))
    handled_keys.add(team_key)

    for key, quota_row in quota_rows.items():
        if key not in handled_keys:
            items.append(quota_record_from_payload(team_id, quota_row))
    return items
