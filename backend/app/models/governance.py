from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


TeamMemberRole = Literal["admin", "member", "team_owner", "business_user", "developer_user"]
TeamMemberStatus = Literal["invited", "active", "frozen", "removed"]
QuotaStatus = Literal["active", "frozen", "exhausted"]
AssetType = Literal["dataset", "model", "workflow", "report"]


class TeamProfileRecord(BaseModel):
    user_id: str
    email: str | None = None
    display_name: str | None = None


class TeamMemberRecord(BaseModel):
    team_id: str
    user_id: str
    role: TeamMemberRole | str
    member_status: TeamMemberStatus | str = "active"
    invited_by: str | None = None
    joined_at: datetime | None = None
    profile: TeamProfileRecord | None = None


class TeamMembersResponse(BaseModel):
    team_id: str
    items: list[TeamMemberRecord]


class TeamInviteRequest(BaseModel):
    email: str | None = Field(default=None, max_length=320)
    note: str | None = Field(default=None, max_length=1000)


class TeamInviteResponse(BaseModel):
    team_id: str
    team_name: str
    invite_code: str
    share_text: str
    detail: str


class TeamMemberRoleUpdateRequest(BaseModel):
    role: TeamMemberRole | str


class TeamMemberRoleUpdateResponse(BaseModel):
    detail: str
    member: TeamMemberRecord


class TeamMemberStatusUpdateRequest(BaseModel):
    member_status: TeamMemberStatus | str


class TeamMemberStatusUpdateResponse(BaseModel):
    detail: str
    member: TeamMemberRecord


class TeamQuotaRecord(BaseModel):
    team_id: str
    user_id: str
    role: TeamMemberRole | str
    member_status: TeamMemberStatus | str = "active"
    display_name: str | None = None
    email: str | None = None
    token_quota: int = 0
    token_used: int = 0
    token_remaining: int = 0
    status: QuotaStatus = "active"
    warning_threshold: int = 0
    updated_at: datetime | None = None


class TeamQuotasResponse(BaseModel):
    team_id: str
    items: list[TeamQuotaRecord]


class TeamQuotaAdjustRequest(BaseModel):
    token_quota: int | None = Field(default=None, ge=0)
    status: QuotaStatus | None = None
    warning_threshold: int | None = Field(default=None, ge=0)


class TeamQuotaAdjustResponse(BaseModel):
    detail: str
    quota: TeamQuotaRecord


class AIRoutingPolicyRecord(BaseModel):
    id: str | None = None
    team_id: str
    stage: str
    connector_id: str | None = None
    connector_display_name: str | None = None
    model_name: str | None = None
    fallback_connector_id: str | None = None
    fallback_connector_display_name: str | None = None
    fallback_model_name: str | None = None
    config: dict[str, Any] | None = None
    created_by: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AIRoutingPoliciesResponse(BaseModel):
    team_id: str
    items: list[AIRoutingPolicyRecord]


class AIRoutingPolicyUpsertRequest(BaseModel):
    stage: str = Field(min_length=1, max_length=120)
    connector_id: str | None = Field(default=None, max_length=64)
    model_name: str | None = Field(default=None, max_length=200)
    fallback_connector_id: str | None = Field(default=None, max_length=64)
    fallback_model_name: str | None = Field(default=None, max_length=200)
    config: dict[str, Any] | None = None


class AIRoutingPoliciesUpdateRequest(BaseModel):
    items: list[AIRoutingPolicyUpsertRequest] = Field(default_factory=list)


class AIRoutingPoliciesUpdateResponse(BaseModel):
    detail: str
    team_id: str
    items: list[AIRoutingPolicyRecord]


class PlatformAssetRecord(BaseModel):
    id: str
    team_id: str
    created_by: str | None = None
    asset_type: AssetType | str
    title: str
    description: str | None = None
    storage_path: str | None = None
    metadata: dict[str, Any] | None = None
    review_status: str
    creator_display_name: str | None = None
    creator_email: str | None = None
    created_at: datetime
    updated_at: datetime


class PlatformAssetsResponse(BaseModel):
    team_id: str
    items: list[PlatformAssetRecord]


class PlatformAssetCreateRequest(BaseModel):
    asset_type: AssetType
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    storage_path: str | None = Field(default=None, max_length=4000)
    metadata: dict[str, Any] | None = None
    review_status: str = Field(default="private", min_length=1, max_length=80)


class PlatformAssetReviewRequest(BaseModel):
    review_status: str = Field(min_length=1, max_length=80)
    note: str | None = Field(default=None, max_length=4000)


class PlatformAssetMutationResponse(BaseModel):
    detail: str
    asset: PlatformAssetRecord


class AuditLogRecord(BaseModel):
    id: str
    team_id: str | None = None
    actor_id: str | None = None
    actor_display_name: str | None = None
    actor_email: str | None = None
    action: str
    resource_type: str | None = None
    resource_id: str | None = None
    detail: dict[str, Any] | None = None
    created_at: datetime


class AuditLogsResponse(BaseModel):
    team_id: str
    items: list[AuditLogRecord]
