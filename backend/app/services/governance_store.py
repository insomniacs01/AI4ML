from __future__ import annotations

from typing import Any

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
from backend.app.services.governance_http import GovernanceHttpClient
from backend.app.services.governance_routing import GovernanceRoutingRepository
from backend.app.services.governance_team import GovernanceTeamRepository
from backend.app.services.governance_usage import GovernanceUsageRepository


class GovernanceStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.http = GovernanceHttpClient(settings)
        self._team_repository = GovernanceTeamRepository(request_json=self._request_json)
        self._routing_repository = GovernanceRoutingRepository(request_json=self._request_json)
        self._asset_repository = PlatformAssetRepository(
            request_json=self._request_json,
            list_profiles=self._team_repository.list_profiles,
        )
        self._usage_repository = GovernanceUsageRepository(
            request_json=self._request_json,
            list_members=self._team_repository.list_members,
            list_profiles=self._team_repository.list_profiles,
        )

    def list_members(self, team_id: str, *, access_token: str) -> list[TeamMemberRecord]:
        return self._team_repository.list_members(team_id, access_token=access_token)

    def get_team(self, team_id: str, *, access_token: str) -> dict[str, Any] | None:
        return self._team_repository.get_team(team_id, access_token=access_token)

    def get_team_settings(self, team_id: str, *, access_token: str) -> TeamSettingsRecord | None:
        return self._team_repository.get_team_settings(team_id, access_token=access_token)

    def update_team_settings(
        self,
        team_id: str,
        payload: TeamSettingsUpdateRequest,
        *,
        access_token: str,
    ) -> TeamSettingsRecord:
        return self._team_repository.update_team_settings(team_id, payload, access_token=access_token)

    def transfer_ownership(
        self,
        team_id: str,
        *,
        current_owner_id: str,
        new_owner_user_id: str,
        access_token: str,
    ) -> tuple[TeamSettingsRecord, TeamMemberRecord, TeamMemberRecord]:
        return self._team_repository.transfer_ownership(
            team_id,
            current_owner_id=current_owner_id,
            new_owner_user_id=new_owner_user_id,
            access_token=access_token,
        )

    def update_member_role(self, team_id: str, user_id: str, role: str, *, access_token: str) -> TeamMemberRecord:
        return self._team_repository.update_member_role(team_id, user_id, role, access_token=access_token)

    def update_member_status(self, team_id: str, user_id: str, member_status: str, *, access_token: str) -> TeamMemberRecord:
        return self._team_repository.update_member_status(team_id, user_id, member_status, access_token=access_token)

    def update_profile(
        self,
        user_id: str,
        *,
        display_name: str | None,
        access_token: str,
    ) -> TeamProfileRecord:
        return self._team_repository.update_profile(user_id, display_name=display_name, access_token=access_token)

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
        return self._routing_repository.list_routing_policies(team_id, access_token=access_token)

    def save_routing_policies(
        self,
        team_id: str,
        created_by: str,
        payload: AIRoutingPoliciesUpdateRequest,
        *,
        access_token: str,
    ) -> list[AIRoutingPolicyRecord]:
        return self._routing_repository.save_routing_policies(
            team_id,
            created_by,
            payload,
            access_token=access_token,
        )

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
        return self.http.request_json(
            path=path,
            access_token=access_token,
            method=method,
            body=body,
            expect_json=expect_json,
            prefer=prefer,
        )

    def _ensure_configured(self) -> None:
        self.http._ensure_configured()  # noqa: SLF001
