from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


TeamMemberRole = Literal["admin", "member", "team_owner", "business_user", "developer_user"]
TeamMemberStatus = Literal["invited", "active", "frozen", "removed"]
QuotaStatus = Literal["active", "frozen", "exhausted"]
QuotaScopeType = Literal["member", "team", "connector"]
AssetType = Literal["dataset", "model", "workflow", "report"]
TeamStatus = Literal["active", "disabled", "archived"]


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


class TeamSettingsRecord(BaseModel):
    id: str
    name: str
    invite_code: str
    created_by: str
    owner_user_id: str | None = None
    owner_display_name: str | None = None
    owner_email: str | None = None
    description: str | None = None
    status: TeamStatus | str = "active"
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TeamSettingsResponse(BaseModel):
    team: TeamSettingsRecord


class TeamSettingsUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    status: TeamStatus | None = None


class TeamOwnershipTransferRequest(BaseModel):
    new_owner_user_id: str = Field(min_length=1, max_length=64)


class TeamOwnershipTransferResponse(BaseModel):
    detail: str
    team: TeamSettingsRecord
    previous_owner: TeamMemberRecord
    new_owner: TeamMemberRecord


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
    scope_type: QuotaScopeType = "member"
    scope_key: str = ""
    user_id: str | None = None
    connector_id: str | None = None
    role: TeamMemberRole | str | None = None
    member_status: TeamMemberStatus | str | None = None
    display_name: str | None = None
    email: str | None = None
    connector_display_name: str | None = None
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


class TeamQuotaScopeAdjustRequest(BaseModel):
    scope_type: QuotaScopeType = "member"
    scope_key: str | None = Field(default=None, max_length=200)
    user_id: str | None = Field(default=None, max_length=64)
    connector_id: str | None = Field(default=None, max_length=64)
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
    category: str | None = None
    tags: list[str] = Field(default_factory=list)
    visibility: str = "private"
    version: str | None = None
    source_task_id: str | None = None
    source_asset_id: str | None = None
    model_card: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    review_status: str
    published_at: datetime | None = None
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
    category: str | None = Field(default=None, max_length=120)
    tags: list[str] = Field(default_factory=list)
    visibility: str = Field(default="private", min_length=1, max_length=40)
    version: str | None = Field(default="1.0.0", max_length=80)
    source_task_id: str | None = Field(default=None, max_length=120)
    model_card: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    review_status: str = Field(default="private", min_length=1, max_length=80)


class PlatformAssetReviewRequest(BaseModel):
    review_status: str = Field(min_length=1, max_length=80)
    note: str | None = Field(default=None, max_length=4000)
    category: str | None = Field(default=None, max_length=120)
    tags: list[str] | None = None
    visibility: str | None = Field(default=None, max_length=40)


class PlatformAssetPublishRequest(BaseModel):
    note: str | None = Field(default=None, max_length=4000)
    visibility: str = Field(default="public", min_length=1, max_length=40)
    metadata: dict[str, Any] | None = None


class PlatformAssetForkRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    review_status: str = Field(default="private", min_length=1, max_length=80)
    version: str | None = Field(default=None, max_length=80)
    metadata: dict[str, Any] | None = None


class PlatformAssetMutationResponse(BaseModel):
    detail: str
    asset: PlatformAssetRecord


class TokenLedgerRecord(BaseModel):
    id: str
    team_id: str
    user_id: str | None = None
    user_display_name: str | None = None
    user_email: str | None = None
    task_id: str | None = None
    task_name: str | None = None
    connector_id: str | None = None
    connector_display_name: str | None = None
    phase: str
    stage_key: str | None = None
    source_key: str
    model_name: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    calculation_method: str | None = None
    raw_usage: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime


class TokenLedgersResponse(BaseModel):
    team_id: str
    items: list[TokenLedgerRecord]
    total_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


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
