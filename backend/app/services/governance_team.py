from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.app.models.governance import (
    TeamMemberRecord,
    TeamProfileRecord,
    TeamSettingsRecord,
    TeamSettingsUpdateRequest,
)
from backend.app.services.governance_http import unwrap_single_record
from backend.app.services.governance_team_ownership import resolve_ownership_transfer
from backend.app.services.governance_team_records import (
    team_member_from_payload,
    team_settings_from_payload,
)
from backend.app.services.governance_team_profiles import list_team_profiles, update_team_profile
from backend.app.services.governance_team_queries import (
    team_member_update_path,
    team_members_path,
    team_path,
    team_update_path,
)

RequestJson = Callable[..., Any]


class GovernanceTeamRepository:
    _team_settings_from_payload = staticmethod(team_settings_from_payload)
    _member_record_from_payload = staticmethod(team_member_from_payload)
    _resolve_ownership_transfer = staticmethod(resolve_ownership_transfer)
    _unwrap_single_record = staticmethod(unwrap_single_record)

    def __init__(self, *, request_json: RequestJson) -> None:
        self._request_json = request_json

    def list_members(self, team_id: str, *, access_token: str) -> list[TeamMemberRecord]:
        member_payload = self._request_json(
            path=team_members_path(team_id),
            access_token=access_token,
        )
        if not isinstance(member_payload, list):
            raise ConnectionError("Unexpected team-members response from Supabase.")

        profiles = self.list_profiles(
            [str(item.get("user_id")) for item in member_payload if isinstance(item, dict)],
            access_token=access_token,
        )
        profile_map = {item.user_id: item for item in profiles}
        return [
            self._member_record_from_payload(
                item,
                profile=profile_map.get(str(item.get("user_id"))),
            )
            for item in member_payload
            if isinstance(item, dict)
        ]

    def get_team(self, team_id: str, *, access_token: str) -> dict[str, Any] | None:
        payload = self._request_json(
            path=team_path(team_id),
            access_token=access_token,
        )
        if not isinstance(payload, list):
            raise ConnectionError("Unexpected team response from Supabase.")
        return payload[0] if payload else None

    def get_team_settings(self, team_id: str, *, access_token: str) -> TeamSettingsRecord | None:
        team = self.get_team(team_id, access_token=access_token)
        if team is None:
            return None
        members = self.list_members(team_id, access_token=access_token)
        return self._team_settings_from_payload(team, members)

    def update_team_settings(
        self,
        team_id: str,
        payload: TeamSettingsUpdateRequest,
        *,
        access_token: str,
    ) -> TeamSettingsRecord:
        body: dict[str, Any] = {}
        if payload.name is not None:
            body["name"] = payload.name.strip()
        if payload.description is not None:
            body["description"] = payload.description.strip() or None
        if payload.status is not None:
            body["status"] = payload.status
        if not body:
            current = self.get_team_settings(team_id, access_token=access_token)
            if current is None:
                raise ValueError("team not found")
            return current

        updated_payload = self._request_json(
            path=team_update_path(team_id),
            access_token=access_token,
            method="PATCH",
            body=body,
        )
        updated = self._unwrap_single_record(updated_payload, "team settings update")
        members = self.list_members(team_id, access_token=access_token)
        return self._team_settings_from_payload(updated, members)

    def transfer_ownership(
        self,
        team_id: str,
        *,
        current_owner_id: str,
        new_owner_user_id: str,
        access_token: str,
    ) -> tuple[TeamSettingsRecord, TeamMemberRecord, TeamMemberRecord]:
        members = self.list_members(team_id, access_token=access_token)
        plan = self._resolve_ownership_transfer(
            members,
            current_owner_id=current_owner_id,
            new_owner_user_id=new_owner_user_id,
        )

        if plan.is_noop:
            settings = self.get_team_settings(team_id, access_token=access_token)
            if settings is None:
                raise ValueError("team not found")
            return settings, plan.previous_owner, plan.next_owner

        promoted = self.update_member_role(
            team_id,
            plan.next_owner.user_id,
            "team_owner",
            access_token=access_token,
        )
        demoted = self.update_member_role(
            team_id,
            plan.previous_owner.user_id,
            "admin",
            access_token=access_token,
        )
        settings = self.get_team_settings(team_id, access_token=access_token)
        if settings is None:
            raise ValueError("team not found")
        return settings, demoted, promoted

    def update_member_role(self, team_id: str, user_id: str, role: str, *, access_token: str) -> TeamMemberRecord:
        payload = self._request_json(
            path=team_member_update_path(team_id, user_id),
            access_token=access_token,
            method="PATCH",
            body={"role": role},
        )
        try:
            updated = self._unwrap_single_record(payload, "team member role update")
        except ConnectionError as exc:
            raise RuntimeError(
                "Supabase team_members update did not return a row. "
                "Apply the latest team_members update policy from supabase/schema.sql."
            ) from exc
        profiles = self.list_profiles([user_id], access_token=access_token)
        profile = profiles[0] if profiles else None
        return self._member_record_from_payload(
            updated,
            profile=profile,
            default_role=role,
        )

    def update_member_status(
        self,
        team_id: str,
        user_id: str,
        member_status: str,
        *,
        access_token: str,
    ) -> TeamMemberRecord:
        payload = self._request_json(
            path=team_member_update_path(team_id, user_id),
            access_token=access_token,
            method="PATCH",
            body={"member_status": member_status},
        )
        try:
            updated = self._unwrap_single_record(payload, "team member status update")
        except ConnectionError as exc:
            raise RuntimeError(
                "Supabase team_members update did not return a row. "
                "Apply the latest team_members update policy from supabase/schema.sql."
            ) from exc
        profiles = self.list_profiles([user_id], access_token=access_token)
        profile = profiles[0] if profiles else None
        return self._member_record_from_payload(
            updated,
            profile=profile,
            default_role="business_user",
            default_status=member_status,
        )

    def update_profile(
        self,
        user_id: str,
        *,
        display_name: str | None,
        access_token: str,
    ) -> TeamProfileRecord:
        return update_team_profile(
            self._request_json,
            user_id,
            display_name=display_name,
            access_token=access_token,
        )

    def list_profiles(self, user_ids: list[str], *, access_token: str) -> list[TeamProfileRecord]:
        return list_team_profiles(
            self._request_json,
            user_ids,
            access_token=access_token,
        )
