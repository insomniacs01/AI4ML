from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, status

from backend.app.core.config import Settings, get_settings
from backend.app.core.supabase_auth import TeamAccessContext
from backend.app.models.connector import StoredConnectorRecord
from backend.app.models.governance import AIRoutingPolicyRecord, TeamQuotaRecord
from backend.app.models.task import (
    PRIMARY_WORKFLOW_STAGES,
    TaskRecord,
    TaskStageRoutingOverrideInput,
    TaskStageRoutingRecord,
    WorkflowStage,
    normalize_workflow_stage,
)
from backend.app.services.connector_runtime import build_runtime_settings
from backend.app.services.service_registry import (
    get_connector_store,
    get_governance_store,
)


@dataclass(frozen=True)
class _ResolvedStageSelection:
    stage: WorkflowStage
    connector: StoredConnectorRecord
    model_name: str
    selection_source: str
    stage_record: TaskStageRoutingRecord

@dataclass
class _RoutingRuntimeContext:
    team_policies: dict[str, AIRoutingPolicyRecord]
    connector_cache: dict[str, StoredConnectorRecord | None]

def _raise_connector_store_http_error(exc: RuntimeError | PermissionError | ConnectionError) -> None:
    if isinstance(exc, RuntimeError):
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    if isinstance(exc, PermissionError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

def _raise_governance_http_error(exc: RuntimeError | PermissionError | ConnectionError) -> None:
    if isinstance(exc, RuntimeError):
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    if isinstance(exc, PermissionError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

def _build_runtime_context(team_access: TeamAccessContext) -> _RoutingRuntimeContext:
    team_policies: dict[str, AIRoutingPolicyRecord] = {}
    try:
        items = get_governance_store().list_routing_policies(
            team_access.team_id,
            access_token=team_access.access_token,
        )
        team_policies = {normalize_workflow_stage(item.stage).value: item for item in items}
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        _raise_governance_http_error(exc)
    return _RoutingRuntimeContext(
        team_policies=team_policies,
        connector_cache={},
    )

def _get_connector_by_id(
    team_access: TeamAccessContext,
    runtime_context: _RoutingRuntimeContext,
    connector_id: str,
) -> StoredConnectorRecord | None:
    if connector_id in runtime_context.connector_cache:
        return runtime_context.connector_cache[connector_id]
    try:
        connector = get_connector_store().get_connector(
            team_access.team_id,
            connector_id,
            access_token=team_access.access_token,
        )
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        _raise_connector_store_http_error(exc)
    runtime_context.connector_cache[connector_id] = connector
    return connector

def _build_stage_override_map(task: TaskRecord) -> dict[str, TaskStageRoutingRecord]:
    return {normalize_workflow_stage(item.stage).value: item for item in task.stage_routing}

def _raise_incomplete_stage_route(stage: WorkflowStage, selection_source: str) -> None:
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=(
            f"{stage.value} 阶段的 {selection_source} 路由只配置了模型名但没有 connector_id。"
            "请显式选择连接器；系统不会再用当前激活连接器兜底。"
        ),
    )

def _validate_task_stage_routing_overrides(items: list[TaskStageRoutingOverrideInput]) -> None:
    for item in items:
        stage = normalize_workflow_stage(item.stage)
        if item.model_name and item.model_name.strip() and not item.connector_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"{stage.value} 阶段只填写了模型名但没有 connector_id。请显式选择连接器。",
            )

def _resolve_stage_selection(
    task: TaskRecord,
    team_access: TeamAccessContext,
    runtime_context: _RoutingRuntimeContext,
    stage: WorkflowStage,
) -> _ResolvedStageSelection | None:
    normalized_stage = normalize_workflow_stage(stage)
    stage_key = normalized_stage.value
    task_overrides = _build_stage_override_map(task)
    task_override = task_overrides.get(stage_key)
    team_policy = runtime_context.team_policies.get(stage_key)

    candidate_specs: list[tuple[str, str | None, str | None]] = []
    if task_override and (task_override.connector_id or task_override.model_name):
        candidate_specs.append(("task_override", task_override.connector_id, task_override.model_name))
    if team_policy and (team_policy.connector_id or team_policy.model_name):
        candidate_specs.append(("team_policy", team_policy.connector_id, team_policy.model_name))

    for selection_source, connector_id, model_name_override in candidate_specs:
        if not connector_id:
            _raise_incomplete_stage_route(normalized_stage, selection_source)

        connector = _get_connector_by_id(team_access, runtime_context, connector_id)
        if connector is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"{normalized_stage.value} 阶段的 {selection_source} 路由引用了不存在的连接器：{connector_id}",
            )

        resolved_model_name = (model_name_override or connector.model_name or "").strip()
        if not resolved_model_name:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"{normalized_stage.value} 阶段的 {selection_source} 路由没有可用模型名。",
            )

        stage_record = TaskStageRoutingRecord(
            stage=normalized_stage,
            connector_id=connector.id,
            connector_display_name=connector.display_name,
            model_name=resolved_model_name,
            selection_source=selection_source,
        )
        return _ResolvedStageSelection(
            stage=normalized_stage,
            connector=connector,
            model_name=resolved_model_name,
            selection_source=selection_source,
            stage_record=stage_record,
        )

    return None

def _build_stage_selection_map(
    task: TaskRecord,
    team_access: TeamAccessContext,
    runtime_context: _RoutingRuntimeContext,
) -> dict[str, TaskStageRoutingRecord]:
    resolved: dict[str, TaskStageRoutingRecord] = {}
    for stage in PRIMARY_WORKFLOW_STAGES:
        selection = _resolve_stage_selection(
            task,
            team_access,
            runtime_context,
            stage,
        )
        if selection is not None:
            resolved[stage.value] = selection.stage_record
    return resolved

def _resolve_preferred_selection(
    task: TaskRecord,
    team_access: TeamAccessContext,
    runtime_context: _RoutingRuntimeContext,
    stages: list[WorkflowStage],
) -> _ResolvedStageSelection:
    for stage in stages:
        selection = _resolve_stage_selection(
            task,
            team_access,
            runtime_context,
            stage,
        )
        if selection is not None:
            return selection

    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="当前任务没有可用的阶段 AI 路由。请先在默认 AI 页面保存阶段路由，或在任务表单中显式选择阶段连接器。",
    )

def _build_runtime_settings_for_selection(settings: Settings, selection: _ResolvedStageSelection) -> Settings:
    base_settings = build_runtime_settings(settings, selection.connector)
    return base_settings.model_copy(update={"ai_provider_model_name": selection.model_name})

def _assert_quota_allows_action(
    team_access: TeamAccessContext,
    *,
    action_name: str,
    block_at_warning_threshold: bool = False,
) -> TeamQuotaRecord | None:
    try:
        quota = get_governance_store().get_member_quota(
            team_access.team_id,
            team_access.user.id,
            access_token=team_access.access_token,
        )
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        _raise_governance_http_error(exc)

    if quota is None:
        return None
    if quota.status == "frozen":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="当前成员配额已被冻结，请联系团队管理员恢复后再继续。",
        )
    if quota.status == "exhausted":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="当前成员 Token 配额已耗尽，无法继续执行 AI 操作。",
        )
    if quota.token_quota > 0 and quota.token_remaining <= 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="当前成员 Token 配额已用完，无法继续执行该操作。",
        )
    if block_at_warning_threshold and quota.token_quota > 0 and quota.warning_threshold > 0 and quota.token_remaining <= quota.warning_threshold:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"当前剩余额度已低于或等于预警阈值，系统已阻止高开销阶段“{action_name}”。请先提高额度或降低阈值。",
        )
    return quota
