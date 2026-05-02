from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from backend.app.core.config import Settings
from backend.app.models.governance import (
    AIRoutingPoliciesUpdateRequest,
    AIRoutingPolicyRecord,
    AuditLogRecord,
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
)


class GovernanceStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

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
            TeamMemberRecord(
                team_id=str(item.get("team_id")),
                user_id=str(item.get("user_id")),
                role=str(item.get("role", "member")),
                member_status=str(item.get("member_status", "active")),
                invited_by=str(item.get("invited_by")) if item.get("invited_by") else None,
                joined_at=item.get("joined_at"),
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
        return TeamMemberRecord(
            team_id=str(updated.get("team_id")),
            user_id=str(updated.get("user_id")),
            role=str(updated.get("role", role)),
            member_status=str(updated.get("member_status", "active")),
            invited_by=str(updated.get("invited_by")) if updated.get("invited_by") else None,
            joined_at=updated.get("joined_at"),
            profile=profile,
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
        return TeamMemberRecord(
            team_id=str(updated.get("team_id")),
            user_id=str(updated.get("user_id")),
            role=str(updated.get("role", "business_user")),
            member_status=str(updated.get("member_status", member_status)),
            invited_by=str(updated.get("invited_by")) if updated.get("invited_by") else None,
            joined_at=updated.get("joined_at"),
            profile=profile,
        )

    def list_quotas(self, team_id: str, *, access_token: str) -> list[TeamQuotaRecord]:
        members = self.list_members(team_id, access_token=access_token)
        quota_payload = self._request_json(
            path=(
                "quota_accounts"
                f"?select=team_id,user_id,token_quota,token_used,status,warning_threshold,updated_at&team_id=eq.{quote(team_id, safe='')}"
            ),
            access_token=access_token,
        )
        if not isinstance(quota_payload, list):
            raise ConnectionError("Unexpected quota response from Supabase.")

        quota_map: dict[str, dict[str, Any]] = {}
        for item in quota_payload:
            if isinstance(item, dict):
                quota_map[str(item.get("user_id"))] = item

        items: list[TeamQuotaRecord] = []
        for member in members:
            quota_row = quota_map.get(member.user_id, {})
            token_quota = _coerce_non_negative_int(quota_row.get("token_quota"))
            token_used = _coerce_non_negative_int(quota_row.get("token_used"))
            token_remaining = max(token_quota - token_used, 0)
            status = "exhausted" if token_quota and token_remaining == 0 else "active"
            items.append(
                TeamQuotaRecord(
                    team_id=team_id,
                    user_id=member.user_id,
                    role=member.role,
                    member_status=member.member_status,
                    display_name=member.profile.display_name if member.profile else None,
                    email=member.profile.email if member.profile else None,
                    token_quota=token_quota,
                    token_used=token_used,
                    token_remaining=token_remaining,
                    status=str(quota_row.get("status") or status),
                    warning_threshold=_coerce_non_negative_int(quota_row.get("warning_threshold")),
                    updated_at=quota_row.get("updated_at"),
                )
            )
        return items

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
        existing = self._request_json(
            path=(
                "quota_accounts"
                f"?select=team_id,user_id,token_quota,token_used,status,warning_threshold,updated_at&team_id=eq.{quote(team_id, safe='')}"
                f"&user_id=eq.{quote(user_id, safe='')}&limit=1"
            ),
            access_token=access_token,
        )
        existing_row = existing[0] if isinstance(existing, list) and existing else {}
        payload = {
            "team_id": team_id,
            "user_id": user_id,
            "token_quota": token_quota if token_quota is not None else _coerce_non_negative_int(existing_row.get("token_quota")),
            "status": status or str(existing_row.get("status") or "active"),
            "warning_threshold": warning_threshold if warning_threshold is not None else _coerce_non_negative_int(existing_row.get("warning_threshold")),
        }
        if isinstance(existing, list) and existing:
            updated = self._request_json(
                path=(
                    "quota_accounts"
                    f"?team_id=eq.{quote(team_id, safe='')}&user_id=eq.{quote(user_id, safe='')}"
                ),
                access_token=access_token,
                method="PATCH",
                body=payload,
            )
        else:
            updated = self._request_json(
                path="quota_accounts",
                access_token=access_token,
                method="POST",
                body=payload,
            )
        row = self._unwrap_single_record(updated, "quota adjust")
        member = next(
            (item for item in self.list_members(team_id, access_token=access_token) if item.user_id == user_id),
            None,
        )
        role = member.role if member is not None else "business_user"
        member_status = member.member_status if member is not None else "active"
        display_name = member.profile.display_name if member and member.profile else None
        email = member.profile.email if member and member.profile else None
        used = _coerce_non_negative_int(row.get("token_used"))
        resolved_quota = _coerce_non_negative_int(row.get("token_quota"))
        remaining = max(resolved_quota - used, 0)
        resolved_status = str(row.get("status") or ("exhausted" if resolved_quota and remaining == 0 else "active"))
        return TeamQuotaRecord(
            team_id=team_id,
            user_id=user_id,
            role=role,
            member_status=member_status,
            display_name=display_name,
            email=email,
            token_quota=resolved_quota,
            token_used=used,
            token_remaining=remaining,
            status=resolved_status,
            warning_threshold=_coerce_non_negative_int(row.get("warning_threshold")),
            updated_at=row.get("updated_at"),
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
                fallback_connector_id=str(item.get("fallback_connector_id")) if item.get("fallback_connector_id") else None,
                fallback_connector_display_name=connector_map.get(str(item.get("fallback_connector_id"))) if item.get("fallback_connector_id") else None,
                fallback_model_name=str(item.get("fallback_model_name")) if item.get("fallback_model_name") else None,
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
                    "fallback_connector_id": None,
                    "fallback_model_name": None,
                    "config": item.config,
                    "created_by": created_by,
                },
                prefer="resolution=merge-duplicates,return=representation",
            )
        return self.list_routing_policies(team_id, access_token=access_token)

    def get_member_quota(self, team_id: str, user_id: str, *, access_token: str) -> TeamQuotaRecord | None:
        items = self.list_quotas(team_id, access_token=access_token)
        return next((item for item in items if item.user_id == user_id), None)

    def list_assets(self, team_id: str, *, access_token: str, asset_type: str | None = None) -> list[PlatformAssetRecord]:
        path = (
            "platform_assets"
            f"?select=*&team_id=eq.{quote(team_id, safe='')}"
            "&order=updated_at.desc"
        )
        if asset_type:
            path += f"&asset_type=eq.{quote(asset_type, safe='')}"
        payload = self._request_json(path=path, access_token=access_token)
        if not isinstance(payload, list):
            raise ConnectionError("Unexpected platform-assets response from Supabase.")
        profiles = self._list_profiles(
            [str(item.get('created_by')) for item in payload if isinstance(item, dict) and item.get("created_by")],
            access_token=access_token,
        )
        profile_map = {item.user_id: item for item in profiles}
        return [self._asset_from_payload(item, profile_map=profile_map) for item in payload if isinstance(item, dict)]

    def get_asset(self, team_id: str, asset_id: str, *, access_token: str) -> PlatformAssetRecord | None:
        payload = self._request_json(
            path=(
                "platform_assets"
                f"?select=*&team_id=eq.{quote(team_id, safe='')}"
                f"&id=eq.{quote(asset_id, safe='')}"
                "&limit=1"
            ),
            access_token=access_token,
        )
        if not isinstance(payload, list):
            raise ConnectionError("Unexpected platform-asset detail response from Supabase.")
        if not payload:
            return None
        creator_id = str(payload[0].get("created_by")) if payload[0].get("created_by") else None
        profiles = self._list_profiles([creator_id] if creator_id else [], access_token=access_token)
        profile_map = {item.user_id: item for item in profiles}
        return self._asset_from_payload(payload[0], profile_map=profile_map)

    def create_asset(
        self,
        team_id: str,
        created_by: str,
        payload: PlatformAssetCreateRequest,
        *,
        access_token: str,
    ) -> PlatformAssetRecord:
        created = self._request_json(
            path="platform_assets",
            access_token=access_token,
            method="POST",
            body={
                "team_id": team_id,
                "created_by": created_by,
                "asset_type": payload.asset_type,
                "title": payload.title,
                "description": payload.description,
                "storage_path": payload.storage_path,
                "metadata": payload.metadata,
                "review_status": payload.review_status,
            },
        )
        record = self._unwrap_single_record(created, "asset create")
        profiles = self._list_profiles([created_by], access_token=access_token)
        profile_map = {item.user_id: item for item in profiles}
        return self._asset_from_payload(record, profile_map=profile_map)

    def review_asset(
        self,
        team_id: str,
        asset_id: str,
        payload: PlatformAssetReviewRequest,
        *,
        access_token: str,
    ) -> PlatformAssetRecord:
        updated = self._request_json(
            path=(
                "platform_assets"
                f"?team_id=eq.{quote(team_id, safe='')}&id=eq.{quote(asset_id, safe='')}"
            ),
            access_token=access_token,
            method="PATCH",
            body={"review_status": payload.review_status},
        )
        record = self._unwrap_single_record(updated, "asset review")
        creator_id = str(record.get("created_by")) if record.get("created_by") else None
        profiles = self._list_profiles([creator_id] if creator_id else [], access_token=access_token)
        profile_map = {item.user_id: item for item in profiles}
        return self._asset_from_payload(record, profile_map=profile_map)

    def publish_asset(
        self,
        team_id: str,
        asset_id: str,
        actor_id: str,
        payload: PlatformAssetPublishRequest,
        *,
        access_token: str,
    ) -> PlatformAssetRecord:
        existing = self.get_asset(team_id, asset_id, access_token=access_token)
        if existing is None:
            raise ValueError("asset not found")
        metadata = dict(existing.metadata or {})
        metadata.update(payload.metadata or {})
        metadata["marketplace"] = {
            **(metadata.get("marketplace") if isinstance(metadata.get("marketplace"), dict) else {}),
            "published": True,
            "published_at": datetime.now(timezone.utc).isoformat(),
            "published_by": actor_id,
            "note": payload.note,
        }
        updated = self._request_json(
            path=(
                "platform_assets"
                f"?team_id=eq.{quote(team_id, safe='')}&id=eq.{quote(asset_id, safe='')}"
            ),
            access_token=access_token,
            method="PATCH",
            body={
                "review_status": "published",
                "metadata": metadata,
            },
        )
        record = self._unwrap_single_record(updated, "asset publish")
        creator_id = str(record.get("created_by")) if record.get("created_by") else None
        profiles = self._list_profiles([creator_id] if creator_id else [], access_token=access_token)
        profile_map = {item.user_id: item for item in profiles}
        return self._asset_from_payload(record, profile_map=profile_map)

    def fork_asset(
        self,
        team_id: str,
        created_by: str,
        source_asset_id: str,
        payload: PlatformAssetForkRequest,
        *,
        access_token: str,
    ) -> PlatformAssetRecord:
        source = self.get_asset(team_id, source_asset_id, access_token=access_token)
        if source is None:
            raise ValueError("asset not found")
        now = datetime.now(timezone.utc).isoformat()
        source_metadata = source.metadata if isinstance(source.metadata, dict) else {}
        fork_metadata = {
            **(payload.metadata or {}),
            "fork": {
                "forked_from_asset_id": source.id,
                "forked_from_team_id": source.team_id,
                "forked_from_title": source.title,
                "forked_from_type": source.asset_type,
                "forked_by": created_by,
                "forked_at": now,
                "source_storage_path": source.storage_path,
                "source_review_status": source.review_status,
            },
            "source_metadata": source_metadata,
        }
        created = self._request_json(
            path="platform_assets",
            access_token=access_token,
            method="POST",
            body={
                "team_id": team_id,
                "created_by": created_by,
                "asset_type": source.asset_type,
                "title": payload.title or f"Fork of {source.title}",
                "description": payload.description if payload.description is not None else source.description,
                "storage_path": source.storage_path,
                "metadata": fork_metadata,
                "review_status": payload.review_status,
            },
        )
        record = self._unwrap_single_record(created, "asset fork")
        profiles = self._list_profiles([created_by], access_token=access_token)
        profile_map = {item.user_id: item for item in profiles}
        return self._asset_from_payload(record, profile_map=profile_map)

    def list_audit_logs(self, team_id: str, *, access_token: str, limit: int = 200) -> list[AuditLogRecord]:
        payload = self._request_json(
            path=(
                "audit_logs"
                f"?select=*&team_id=eq.{quote(team_id, safe='')}"
                f"&order=created_at.desc&limit={limit}"
            ),
            access_token=access_token,
        )
        if not isinstance(payload, list):
            raise ConnectionError("Unexpected audit-log response from Supabase.")
        profiles = self._list_profiles(
            [str(item.get("actor_id")) for item in payload if isinstance(item, dict) and item.get("actor_id")],
            access_token=access_token,
        )
        profile_map = {item.user_id: item for item in profiles}
        items: list[AuditLogRecord] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            actor_id = str(item.get("actor_id")) if item.get("actor_id") else None
            profile = profile_map.get(actor_id or "")
            items.append(
                AuditLogRecord(
                    id=str(item.get("id")),
                    team_id=str(item.get("team_id")) if item.get("team_id") else None,
                    actor_id=actor_id,
                    actor_display_name=profile.display_name if profile else None,
                    actor_email=profile.email if profile else None,
                    action=str(item.get("action")),
                    resource_type=str(item.get("resource_type")) if item.get("resource_type") else None,
                    resource_id=str(item.get("resource_id")) if item.get("resource_id") else None,
                    detail=item.get("detail") if isinstance(item.get("detail"), dict) else None,
                    created_at=item.get("created_at"),
                )
            )
        return items

    def create_audit_log(
        self,
        team_id: str,
        actor_id: str,
        *,
        action: str,
        access_token: str,
        resource_type: str | None = None,
        resource_id: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self._request_json(
            path="audit_logs",
            access_token=access_token,
            method="POST",
            body={
                "team_id": team_id,
                "actor_id": actor_id,
                "action": action,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "detail": detail,
            },
        )

    @staticmethod
    def _team_settings_from_payload(
        payload: dict[str, Any],
        members: list[TeamMemberRecord],
    ) -> TeamSettingsRecord:
        owner = next((item for item in members if item.role == "team_owner" and item.member_status == "active"), None)
        owner_user_id = owner.user_id if owner is not None else str(payload.get("created_by")) if payload.get("created_by") else None
        owner_profile = owner.profile if owner is not None else None
        return TeamSettingsRecord(
            id=str(payload.get("id")),
            name=str(payload.get("name") or ""),
            invite_code=str(payload.get("invite_code") or ""),
            created_by=str(payload.get("created_by") or owner_user_id or ""),
            owner_user_id=owner_user_id,
            owner_display_name=owner_profile.display_name if owner_profile else None,
            owner_email=owner_profile.email if owner_profile else None,
            description=str(payload.get("description")) if payload.get("description") else None,
            status=str(payload.get("status") or "active"),
            created_at=payload.get("created_at"),
            updated_at=payload.get("updated_at"),
        )

    def _asset_from_payload(
        self,
        payload: dict[str, Any],
        *,
        profile_map: dict[str, TeamProfileRecord],
    ) -> PlatformAssetRecord:
        creator_id = str(payload.get("created_by")) if payload.get("created_by") else None
        profile = profile_map.get(creator_id or "")
        return PlatformAssetRecord(
            id=str(payload.get("id")),
            team_id=str(payload.get("team_id")),
            created_by=creator_id,
            asset_type=str(payload.get("asset_type")),
            title=str(payload.get("title")),
            description=str(payload.get("description")) if payload.get("description") else None,
            storage_path=str(payload.get("storage_path")) if payload.get("storage_path") else None,
            metadata=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else None,
            review_status=str(payload.get("review_status", "private")),
            creator_display_name=profile.display_name if profile else None,
            creator_email=profile.email if profile else None,
            created_at=payload.get("created_at"),
            updated_at=payload.get("updated_at"),
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
        return [
            TeamProfileRecord(
                user_id=str(item.get("user_id")),
                email=str(item.get("email")) if item.get("email") else None,
                display_name=str(item.get("display_name")) if item.get("display_name") else None,
            )
            for item in payload
            if isinstance(item, dict) and item.get("user_id")
        ]

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


def _coerce_non_negative_int(value: Any) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return 0
    return max(result, 0)
