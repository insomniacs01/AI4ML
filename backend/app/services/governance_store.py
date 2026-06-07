from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from backend.app.core.config import Settings
from backend.app.models.governance import (
    AIRoutingPoliciesUpdateRequest,
    AIRoutingPolicyRecord,
    PlatformAssetCreateRequest,
    PlatformAssetForkRequest,
    PlatformAssetRecord,
    PlatformAssetPublishRequest,
    PlatformAssetReviewRequest,
    TeamMemberRecord,
    TeamProfileRecord,
    TeamQuotaRecord,
    TeamSettingsRecord,
    TeamSettingsUpdateRequest,
    TokenLedgerRecord,
)
from backend.app.services.governance_assets import PlatformAssetRepository
from backend.app.services.governance_team_records import (
    profile_records_from_payload,
    team_member_from_payload,
    team_settings_from_payload,
)
from backend.app.services.governance_usage import GovernanceUsageRepository


class GovernanceStore:
    _team_settings_from_payload = staticmethod(team_settings_from_payload)
    _member_record_from_payload = staticmethod(team_member_from_payload)
    _profile_records_from_payload = staticmethod(profile_records_from_payload)

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._asset_repository = PlatformAssetRepository(
            request_json=self._request_json,
            list_profiles=self._list_profiles,
        )
        self._usage_repository = GovernanceUsageRepository(
            request_json=self._request_json,
            list_members=self.list_members,
            list_profiles=self._list_profiles,
        )

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

        profiles = self._list_profiles(
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
        previous_owner = next((item for item in members if item.user_id == current_owner_id), None)
        if previous_owner is None or previous_owner.role != "team_owner":
            raise PermissionError("Only the current team owner can transfer ownership.")

        next_owner = next((item for item in members if item.user_id == new_owner_user_id), None)
        if next_owner is None:
            raise ValueError("new owner is not a member of this team")
        if next_owner.member_status != "active":
            raise ValueError("new owner must be an active team member")

        if next_owner.user_id == previous_owner.user_id:
            settings = self.get_team_settings(team_id, access_token=access_token)
            if settings is None:
                raise ValueError("team not found")
            return settings, previous_owner, next_owner

        promoted = self.update_member_role(
            team_id,
            next_owner.user_id,
            "team_owner",
            access_token=access_token,
        )
        demoted = self.update_member_role(
            team_id,
            previous_owner.user_id,
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
        profiles = self._list_profiles([user_id], access_token=access_token)
        profile = profiles[0] if profiles else None
        return self._member_record_from_payload(
            updated,
            profile=profile,
            default_role=role,
        )

    def update_member_status(self, team_id: str, user_id: str, member_status: str, *, access_token: str) -> TeamMemberRecord:
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
        profiles = self._list_profiles([user_id], access_token=access_token)
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

    def list_quotas(self, team_id: str, *, access_token: str) -> list[TeamQuotaRecord]:
        return self._usage_repository.list_quotas(team_id, access_token=access_token)

    def adjust_quota(
        self,
        team_id: str,
        user_id: str,
        token_quota: int | None,
        *,
        status: str | None = None,
        warning_threshold: int | None = None,
        access_token: str,
    ) -> TeamQuotaRecord:
        return self._usage_repository.adjust_quota(
            team_id,
            user_id,
            token_quota,
            status=status,
            warning_threshold=warning_threshold,
            access_token=access_token,
        )

    def adjust_quota_scope(
        self,
        team_id: str,
        *,
        scope_type: str,
        scope_key: str,
        token_quota: int | None,
        status: str | None = None,
        warning_threshold: int | None = None,
        access_token: str,
    ) -> TeamQuotaRecord:
        return self._usage_repository.adjust_quota_scope(
            team_id,
            scope_type=scope_type,
            scope_key=scope_key,
            token_quota=token_quota,
            status=status,
            warning_threshold=warning_threshold,
            access_token=access_token,
        )

    def list_routing_policies(self, team_id: str, *, access_token: str) -> list[AIRoutingPolicyRecord]:
        payload = self._request_json(
            path=(
                "ai_routing_policies"
                f"?select=*&team_id=eq.{quote(team_id, safe='')}&order=stage.asc"
            ),
            access_token=access_token,
        )
        if not isinstance(payload, list):
            raise ConnectionError("Unexpected routing-policy response from Supabase.")

        connector_payload = self._request_json(
            path=(
                "ai_connectors"
                f"?select=id,display_name&team_id=eq.{quote(team_id, safe='')}"
            ),
            access_token=access_token,
        )
        connector_map = {
            str(item.get("id")): str(item.get("display_name"))
            for item in connector_payload
            if isinstance(item, dict) and item.get("id")
        } if isinstance(connector_payload, list) else {}

        return [
            AIRoutingPolicyRecord(
                id=str(item.get("id")) if item.get("id") else None,
                team_id=str(item.get("team_id")),
                stage=str(item.get("stage")),
                connector_id=str(item.get("connector_id")) if item.get("connector_id") else None,
                connector_display_name=connector_map.get(str(item.get("connector_id"))) if item.get("connector_id") else None,
                model_name=str(item.get("model_name")) if item.get("model_name") else None,
                config=item.get("config") if isinstance(item.get("config"), dict) else None,
                created_by=str(item.get("created_by")) if item.get("created_by") else None,
                created_at=item.get("created_at"),
                updated_at=item.get("updated_at"),
            )
            for item in payload
            if isinstance(item, dict)
        ]

    def save_routing_policies(
        self,
        team_id: str,
        created_by: str,
        payload: AIRoutingPoliciesUpdateRequest,
        *,
        access_token: str,
    ) -> list[AIRoutingPolicyRecord]:
        for item in payload.items:
            has_any_value = bool(
                item.connector_id
                or item.model_name
                or item.config
            )
            stage = item.stage.strip()
            if not has_any_value:
                self._request_json(
                    path=(
                        "ai_routing_policies"
                        f"?team_id=eq.{quote(team_id, safe='')}&stage=eq.{quote(stage, safe='')}"
                    ),
                    access_token=access_token,
                    method="DELETE",
                    expect_json=False,
                )
                continue
            self._request_json(
                path="ai_routing_policies?on_conflict=team_id,stage",
                access_token=access_token,
                method="POST",
                body={
                    "team_id": team_id,
                    "stage": stage,
                    "connector_id": item.connector_id,
                    "model_name": item.model_name,
                    "config": item.config,
                    "created_by": created_by,
                },
                prefer="resolution=merge-duplicates,return=representation",
            )
        return self.list_routing_policies(team_id, access_token=access_token)

    def get_member_quota(self, team_id: str, user_id: str, *, access_token: str) -> TeamQuotaRecord | None:
        return self._usage_repository.get_member_quota(team_id, user_id, access_token=access_token)

    def list_assets(
        self,
        team_id: str,
        *,
        access_token: str,
        asset_type: str | None = None,
        review_status: str | None = None,
        visibility: str | None = None,
        category: str | None = None,
    ) -> list[PlatformAssetRecord]:
        return self._asset_repository.list_assets(
            team_id,
            access_token=access_token,
            asset_type=asset_type,
            review_status=review_status,
            visibility=visibility,
            category=category,
        )

    def get_asset(self, team_id: str, asset_id: str, *, access_token: str) -> PlatformAssetRecord | None:
        return self._asset_repository.get_asset(team_id, asset_id, access_token=access_token)

    def create_asset(
        self,
        team_id: str,
        created_by: str,
        payload: PlatformAssetCreateRequest,
        *,
        access_token: str,
    ) -> PlatformAssetRecord:
        return self._asset_repository.create_asset(
            team_id,
            created_by,
            payload,
            access_token=access_token,
        )

    def review_asset(
        self,
        team_id: str,
        asset_id: str,
        payload: PlatformAssetReviewRequest,
        *,
        access_token: str,
    ) -> PlatformAssetRecord:
        return self._asset_repository.review_asset(
            team_id,
            asset_id,
            payload,
            access_token=access_token,
        )

    def publish_asset(
        self,
        team_id: str,
        asset_id: str,
        actor_id: str,
        payload: PlatformAssetPublishRequest,
        *,
        access_token: str,
    ) -> PlatformAssetRecord:
        return self._asset_repository.publish_asset(team_id, asset_id, actor_id, payload, access_token=access_token)

    def fork_asset(
        self,
        team_id: str,
        created_by: str,
        source_asset_id: str,
        payload: PlatformAssetForkRequest,
        *,
        access_token: str,
    ) -> PlatformAssetRecord:
        return self._asset_repository.fork_asset(
            team_id,
            created_by,
            source_asset_id,
            payload,
            access_token=access_token,
        )

    def delete_asset(self, team_id: str, asset_id: str, *, access_token: str) -> bool:
        return self._asset_repository.delete_asset(team_id, asset_id, access_token=access_token)

    def list_token_ledgers(
        self,
        team_id: str,
        *,
        access_token: str,
        limit: int = 500,
        user_id: str | None = None,
        task_id: str | None = None,
    ) -> list[TokenLedgerRecord]:
        return self._usage_repository.list_token_ledgers(
            team_id,
            access_token=access_token,
            limit=limit,
            user_id=user_id,
            task_id=task_id,
        )

    def _list_profiles(self, user_ids: list[str], *, access_token: str) -> list[TeamProfileRecord]:
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

    def _request_json(
        self,
        *,
        path: str,
        access_token: str,
        method: str = "GET",
        body: Any | None = None,
        expect_json: bool = True,
        prefer: str | None = None,
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
            headers["Prefer"] = prefer or "return=representation"
            data = json.dumps(body).encode("utf-8")

        request = Request(url, data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.settings.supabase_timeout_seconds) as response:  # noqa: S310
                raw_body = response.read().decode("utf-8")
        except HTTPError as exc:
            payload = exc.read().decode("utf-8", errors="ignore")
            if exc.code in (401, 403):
                raise PermissionError("Supabase rejected the team-governance request.") from exc
            raise ConnectionError(
                f"Supabase governance request failed with HTTP {exc.code}. Response: {payload or '<empty>'}"
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise ConnectionError("Could not reach Supabase to read or write team-governance records.") from exc

        if not expect_json:
            return None
        if not raw_body:
            return None
        try:
            return json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise ConnectionError("Supabase governance response was not valid JSON.") from exc

    def _ensure_configured(self) -> None:
        if self.settings.supabase_configured:
            return
        raise RuntimeError(
            "Supabase team-governance storage is not configured. "
            "Set AI4ML_SUPABASE_URL / AI4ML_SUPABASE_PUBLISHABLE_KEY or keep frontend/.env.local available."
        )

    @staticmethod
    def _unwrap_single_record(payload: Any, action: str) -> dict[str, Any]:
        if isinstance(payload, dict):
            return payload
        if isinstance(payload, list) and len(payload) == 1 and isinstance(payload[0], dict):
            return payload[0]
        raise ConnectionError(f"Unexpected Supabase response shape during {action}.")
