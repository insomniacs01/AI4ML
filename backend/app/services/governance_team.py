from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.parse import quote

from backend.app.models.governance import (
    TeamMemberRecord,
    TeamProfileRecord,
    TeamSettingsRecord,
    TeamSettingsUpdateRequest,
)
from backend.app.services.governance_http import unwrap_single_record
from backend.app.services.governance_team_ownership import resolve_ownership_transfer
from backend.app.services.governance_team_records import (
    profile_records_from_payload,
    team_member_from_payload,
    team_settings_from_payload,
)

RequestJson = Callable[..., Any]


class GovernanceTeamRepository:
    _team_settings_from_payload = staticmethod(team_settings_from_payload)
    _member_record_from_payload = staticmethod(team_member_from_payload)
    _profile_records_from_payload = staticmethod(profile_records_from_payload)
    _resolve_ownership_transfer = staticmethod(resolve_ownership_transfer)
    _unwrap_single_record = staticmethod(unwrap_single_record)

    def __init__(self, *, request_json: RequestJson) -> None:
        self._request_json = request_json

    def list_members(self, team_id: str, *, access_token: str) -> list[TeamMemberRecord]:
        member_payload = self._request_json(
            path=(
                "team_members"
                f"?select=team_id,user_id,role,member_status,invited_by,joined_at,updated_at&team_id=eq.{quote(team_id, safe='')}"
                "&order=joined_at.asc"
            ),
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
            path=(
                "teams"
                f"?select=id,name,invite_code,created_by,description,status,created_at,updated_at&"
                f"id=eq.{quote(team_id, safe='')}&limit=1"
            ),
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
            path=f"teams?id=eq.{quote(team_id, safe='')}",
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
            path=(
                "team_members"
                f"?team_id=eq.{quote(team_id, safe='')}"
                f"&user_id=eq.{quote(user_id, safe='')}"
            ),
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
            path=(
                "team_members"
                f"?team_id=eq.{quote(team_id, safe='')}"
                f"&user_id=eq.{quote(user_id, safe='')}"
            ),
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
        payload = self._request_json(
            path=f"profiles?user_id=eq.{quote(user_id, safe='')}",
            access_token=access_token,
            method="PATCH",
            body={"display_name": display_name.strip() if display_name else None},
        )
        row = self._unwrap_single_record(payload, "profile update")
        return TeamProfileRecord(
            user_id=str(row.get("user_id")),
            email=str(row.get("email")) if row.get("email") else None,
            display_name=str(row.get("display_name")) if row.get("display_name") else None,
        )

    def list_profiles(self, user_ids: list[str], *, access_token: str) -> list[TeamProfileRecord]:
        normalized_ids = sorted({item for item in user_ids if item})
        if not normalized_ids:
            return []
        in_list = ",".join(f'"{item}"' for item in normalized_ids)
        quoted_in_list = quote(in_list, safe='(),"')
        payload = self._request_json(
            path=f"profiles?select=user_id,email,display_name&user_id=in.({quoted_in_list})",
            access_token=access_token,
        )
        if not isinstance(payload, list):
            raise ConnectionError("Unexpected profile response from Supabase.")
        return self._profile_records_from_payload(payload)
