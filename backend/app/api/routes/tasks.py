from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status

from backend.app.core.config import Settings, get_settings
from backend.app.core.supabase_auth import (
    TeamAccessContext,
    require_team_access,
    require_team_developer_access,
)
from backend.app.models.connector import StoredConnectorRecord
from backend.app.models.governance import AIRoutingPolicyRecord, TeamQuotaRecord
from backend.app.models.task import (
    PRIMARY_WORKFLOW_STAGES,
    InteractionTriggerMode,
    RunAttempt,
    TaskAIConversationResponse,
    TaskCodeArtifactContentResponse,
    TaskCodeArtifactUpdateRequest,
    TaskCodeWorkspaceResponse,
    TaskCreateRequest,
    TaskDeleteResponse,
    TaskHumanCollaborationResponse,
    TaskHumanRequestCreateRequest,
    TaskHumanRequestDecisionRequest,
    TaskInteractionPolicyRecord,
    TaskInteractiveChatRequest,
    TaskInteractiveChatResponse,
    TaskListResponse,
    TaskRecord,
    TaskRunRequest,
    TaskStageRoutingRecord,
    TaskStatus,
    TokenUsageResponse,
    TaskWorkflowConfigUpdateRequest,
    WorkflowStage,
    normalize_workflow_stage,
)
from backend.app.services.ai_task_analyzer import analyze_task_with_ai, apply_analysis_to_task
from backend.app.services.connector_runtime import build_runtime_settings
from backend.app.services.connector_store import ConnectorStore
from backend.app.services.executors.mlzero_executor import MLZeroExecutor, MLZeroRunError
from backend.app.services.governance_store import GovernanceStore
from backend.app.services.task_ai_conversations import build_task_ai_conversations
from backend.app.services.task_chat import send_task_chat_message
from backend.app.services.task_code_workspace import (
    build_task_code_workspace,
    read_task_code_artifact,
    save_task_code_artifact,
)
from backend.app.services.task_human_collaboration import TaskHumanCollaborationService
from backend.app.services.task_human_context import ensure_task_human_loop, get_task_human_loop
from backend.app.services.task_store import TaskStore
from backend.app.services.token_usage import read_token_usage


router = APIRouter(prefix="/tasks", tags=["tasks"])


@dataclass(frozen=True)
class _ResolvedStageSelection:
    stage: WorkflowStage
    connector: StoredConnectorRecord
    model_name: str
    selection_source: str
    stage_record: TaskStageRoutingRecord


@dataclass
class _RoutingRuntimeContext:
    active_connector: StoredConnectorRecord | None
    team_policies: dict[str, AIRoutingPolicyRecord]
    connector_cache: dict[str, StoredConnectorRecord | None]


@lru_cache
def get_task_store() -> TaskStore:
    return TaskStore(get_settings())


@lru_cache
def get_connector_store() -> ConnectorStore:
    return ConnectorStore(get_settings())


@lru_cache
def get_governance_store() -> GovernanceStore:
    return GovernanceStore(get_settings())


@lru_cache
def get_task_human_collaboration_service() -> TaskHumanCollaborationService:
    return TaskHumanCollaborationService(get_task_store())


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


def _raise_code_workspace_http_error(exc: Exception) -> None:
    if isinstance(exc, FileNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, PermissionError):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if isinstance(exc, RuntimeError):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


def _get_active_connector(team_access: TeamAccessContext) -> StoredConnectorRecord | None:
    try:
        return get_connector_store().get_active_connector(
            team_access.team_id,
            access_token=team_access.access_token,
        )
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        _raise_connector_store_http_error(exc)


def _require_active_connector(team_access: TeamAccessContext) -> StoredConnectorRecord:
    active_connector = _get_active_connector(team_access)
    if active_connector is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="当前团队还没有激活可用的 AI 连接器，无法执行 AI 解析或 MLZero 运行。",
        )
    return active_connector


def _build_runtime_context(team_access: TeamAccessContext) -> _RoutingRuntimeContext:
    active_connector = _get_active_connector(team_access)
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
        active_connector=active_connector,
        team_policies=team_policies,
        connector_cache={active_connector.id: active_connector} if active_connector is not None else {},
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


def _resolve_stage_selection(
    task: TaskRecord,
    team_access: TeamAccessContext,
    runtime_context: _RoutingRuntimeContext,
    stage: WorkflowStage,
    *,
    allow_active_fallback: bool,
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
    if team_policy and (team_policy.fallback_connector_id or team_policy.fallback_model_name):
        candidate_specs.append(("team_policy_fallback", team_policy.fallback_connector_id, team_policy.fallback_model_name))
    if allow_active_fallback:
        candidate_specs.append(("active_connector", runtime_context.active_connector.id if runtime_context.active_connector else None, None))

    for selection_source, connector_id, model_name_override in candidate_specs:
        connector: StoredConnectorRecord | None
        if connector_id:
            connector = _get_connector_by_id(team_access, runtime_context, connector_id)
        elif runtime_context.active_connector is not None:
            connector = runtime_context.active_connector
        else:
            connector = None
        if connector is None:
            continue

        resolved_model_name = (model_name_override or connector.model_name or "").strip()
        if not resolved_model_name:
            continue

        stage_record = TaskStageRoutingRecord(
            stage=normalized_stage,
            connector_id=connector.id,
            connector_display_name=connector.display_name,
            model_name=resolved_model_name,
            fallback_connector_id=team_policy.fallback_connector_id if team_policy else None,
            fallback_connector_display_name=team_policy.fallback_connector_display_name if team_policy else None,
            fallback_model_name=team_policy.fallback_model_name if team_policy else None,
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
            allow_active_fallback=True,
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
            allow_active_fallback=False,
        )
        if selection is not None:
            return selection

    fallback_stage = stages[0]
    fallback_selection = _resolve_stage_selection(
        task,
        team_access,
        runtime_context,
        fallback_stage,
        allow_active_fallback=True,
    )
    if fallback_selection is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="当前团队没有可用的阶段路由或激活连接器，无法启动这一阶段。",
        )
    return fallback_selection


def _build_runtime_settings_for_selection(settings: Settings, selection: _ResolvedStageSelection) -> Settings:
    base_settings = build_runtime_settings(settings, selection.connector)
    return base_settings.model_copy(update={"mlzero_model_alias": selection.model_name})


def _sync_task_human_collaboration(
    task: TaskRecord,
    team_access: TeamAccessContext,
    *,
    stage_selection_map: dict[str, TaskStageRoutingRecord] | None = None,
) -> None:
    get_task_human_collaboration_service().sync_task_stages(
        task,
        access_token=team_access.access_token,
        stage_selection_map=stage_selection_map,
    )


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
            detail="当前成员 Token 配额已耗尽，无法继续执行 AI 或 MLZero 操作。",
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


def _next_policy_cycle(task: TaskRecord) -> int:
    human_loop = ensure_task_human_loop(task)
    current_value = human_loop.get("policy_cycle")
    next_value = int(current_value) + 1 if isinstance(current_value, int) else 1
    human_loop["policy_cycle"] = next_value
    human_loop["current_run_cycle"] = next_value
    return next_value


def _get_current_policy_cycle(task: TaskRecord) -> int:
    human_loop = get_task_human_loop(task)
    current_value = human_loop.get("current_run_cycle")
    if isinstance(current_value, int) and current_value > 0:
        return current_value
    policy_cycle = human_loop.get("policy_cycle")
    if isinstance(policy_cycle, int) and policy_cycle > 0:
        return policy_cycle
    return 1


def _apply_interaction_policies(
    task: TaskRecord,
    team_access: TeamAccessContext,
    *,
    trigger_mode: InteractionTriggerMode,
    cycle_id: int,
    stage_selection_map: dict[str, TaskStageRoutingRecord],
) -> tuple[TaskRecord, int]:
    task_store = get_task_store()
    existing_requests = task_store.list_human_requests(task.team_id, task.id, access_token=team_access.access_token)
    existing_version_ids = {item.version_id for item in existing_requests if item.version_id}

    created_count = 0
    for policy in task.interaction_policies:
        if not policy.enabled or policy.trigger_mode != trigger_mode:
            continue

        normalized_stage = normalize_workflow_stage(policy.stage)
        version_id = f"{policy.policy_id}:{cycle_id}:{trigger_mode.value}"
        if version_id in existing_version_ids:
            continue

        selection = stage_selection_map.get(normalized_stage.value)
        timeout_at = None
        if policy.timeout_minutes is not None:
            timeout_at = task.updated_at + timedelta(minutes=policy.timeout_minutes)

        task_store.create_human_request(
            team_id=task.team_id,
            task_id=task.id,
            stage=normalized_stage,
            requested_by=team_access.user.id,
            assigned_to=policy.assignee_value if policy.assignee_type.value == "member" else None,
            assignee_type=policy.assignee_type.value,
            assignee_value=policy.assignee_value,
            timeout_at=timeout_at,
            version_id=version_id,
            payload={
                "request_type": policy.request_type,
                "title": policy.title,
                "summary": policy.summary,
                "suggested_action": policy.suggested_action,
                "artifact_paths": policy.artifact_paths,
                "trigger_mode": policy.trigger_mode.value,
                "policy_id": policy.policy_id,
                "selected_connector_id": selection.connector_id if selection else None,
                "selected_model_name": selection.model_name if selection else None,
            },
            access_token=team_access.access_token,
        )
        created_count += 1
        existing_version_ids.add(version_id)

    if created_count == 0:
        return task, 0

    task.notes = (
        f"已根据任务的人机协同策略自动创建 {created_count} 个待处理节点，"
        f"当前阶段为 {trigger_mode.value}。"
    )
    paused_task = get_task_human_collaboration_service()._mark_task_waiting(  # noqa: SLF001
        task,
        access_token=team_access.access_token,
        manual_hold=False,
    )
    return paused_task, created_count


def _run_ai_analysis(
    task: TaskRecord,
    task_store: TaskStore,
    team_access: TeamAccessContext,
    *,
    fail_on_error: bool,
) -> TaskRecord:
    if not task.dataset_path:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="dataset has not been uploaded")

    stage_selection_map: dict[str, TaskStageRoutingRecord] = {}

    try:
        _assert_quota_allows_action(team_access, action_name="AI 解析")
        runtime_context = _build_runtime_context(team_access)
        selection = _resolve_preferred_selection(
            task,
            team_access,
            runtime_context,
            [WorkflowStage.requirement_analysis, WorkflowStage.data_analysis],
        )
        runtime_settings = _build_runtime_settings_for_selection(get_settings(), selection)
        stage_selection_map = _build_stage_selection_map(task, team_access, runtime_context)
        analysis = analyze_task_with_ai(task, Path(task.dataset_path), runtime_settings)
    except HTTPException as exc:
        task.status = TaskStatus.planning
        task.notes = f"AI 解析失败：{exc.detail}"
        saved_task = task_store.save_task(task, access_token=team_access.access_token)
        _sync_task_human_collaboration(saved_task, team_access, stage_selection_map=stage_selection_map)
        if fail_on_error:
            raise
        return saved_task
    except Exception as exc:  # noqa: BLE001
        task.status = TaskStatus.planning
        task.notes = f"AI 解析失败：{exc}"
        saved_task = task_store.save_task(task, access_token=team_access.access_token)
        _sync_task_human_collaboration(saved_task, team_access, stage_selection_map=stage_selection_map)
        if fail_on_error:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
        return saved_task

    apply_analysis_to_task(task, analysis)
    task.status = TaskStatus.planning
    saved_task = task_store.save_task(task, access_token=team_access.access_token)
    task_store.upsert_token_ledger(
        team_id=saved_task.team_id,
        task_id=saved_task.id,
        phase="analysis",
        stage_key=selection.stage.value,
        source_key="task_analysis",
        usage=analysis.token_usage,
        access_token=team_access.access_token,
        user_id=team_access.user.id,
        connector_id=selection.connector.id,
        connector_display_name=selection.connector.display_name,
        model_name=selection.model_name,
        calculation_method="provider_reported_usage",
    )
    _sync_task_human_collaboration(saved_task, team_access, stage_selection_map=stage_selection_map)
    return saved_task


@router.get("", response_model=TaskListResponse)
def list_tasks(team_access: TeamAccessContext = Depends(require_team_access)) -> TaskListResponse:
    return TaskListResponse(items=get_task_store().list_tasks(team_access.team_id, access_token=team_access.access_token))


@router.post("", response_model=TaskRecord, status_code=status.HTTP_201_CREATED)
def create_task(
    payload: TaskCreateRequest,
    team_access: TeamAccessContext = Depends(require_team_access),
) -> TaskRecord:
    task = get_task_store().create_task(
        payload,
        team_id=team_access.team_id,
        created_by=team_access.user.id,
        access_token=team_access.access_token,
    )
    _sync_task_human_collaboration(task, team_access, stage_selection_map={})
    return task


@router.get("/{task_id}", response_model=TaskRecord)
def get_task(task_id: str, team_access: TeamAccessContext = Depends(require_team_access)) -> TaskRecord:
    task = get_task_store().get_task(team_access.team_id, task_id, access_token=team_access.access_token)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    return task


@router.get("/{task_id}/token-usage", response_model=TokenUsageResponse)
def get_task_token_usage(
    task_id: str,
    team_access: TeamAccessContext = Depends(require_team_access),
) -> TokenUsageResponse:
    task = get_task_store().get_task(
        team_access.team_id,
        task_id,
        access_token=team_access.access_token,
    )
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    if task.last_run_attempt is not None:
        output_dir = Path(task.last_run_attempt.output_dir)
    elif task.last_run is not None:
        output_dir = Path(task.last_run.output_dir)
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="task has not been run")
    if not output_dir.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run output directory not found")

    stats = read_token_usage(output_dir)
    return TokenUsageResponse(
        task_id=task.id,
        run_output_dir=str(output_dir),
        input_tokens=stats.input_tokens,
        output_tokens=stats.output_tokens,
        total_tokens=stats.total_tokens,
        source=stats.source,
        updated_at=datetime.now(timezone.utc),
    )


@router.put("/{task_id}/workflow-config", response_model=TaskRecord)
def update_task_workflow_config(
    task_id: str,
    payload: TaskWorkflowConfigUpdateRequest,
    team_access: TeamAccessContext = Depends(require_team_access),
) -> TaskRecord:
    task_store = get_task_store()
    task = task_store.get_task(team_access.team_id, task_id, access_token=team_access.access_token)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")

    task.stage_routing = [
        TaskStageRoutingRecord(
            stage=normalize_workflow_stage(item.stage),
            connector_id=item.connector_id,
            model_name=item.model_name,
            selection_source="task_override",
        )
        for item in payload.stage_routing
    ]
    task.interaction_policies = [
        TaskInteractionPolicyRecord(
            policy_id=item.policy_id or f"{normalize_workflow_stage(item.stage).value}:{index + 1}",
            enabled=item.enabled,
            stage=normalize_workflow_stage(item.stage),
            trigger_mode=item.trigger_mode,
            assignee_type=item.assignee_type,
            assignee_value=item.assignee_value,
            request_type=item.request_type,
            title=item.title,
            summary=item.summary,
            suggested_action=item.suggested_action,
            timeout_minutes=item.timeout_minutes,
            artifact_paths=item.artifact_paths,
        )
        for index, item in enumerate(payload.interaction_policies)
    ]
    saved_task = task_store.save_task(task, access_token=team_access.access_token)
    runtime_context = _build_runtime_context(team_access)
    stage_selection_map = _build_stage_selection_map(saved_task, team_access, runtime_context)
    _sync_task_human_collaboration(saved_task, team_access, stage_selection_map=stage_selection_map)
    return saved_task


@router.get("/{task_id}/human-collaboration", response_model=TaskHumanCollaborationResponse)
def get_task_human_collaboration(
    task_id: str,
    team_access: TeamAccessContext = Depends(require_team_access),
) -> TaskHumanCollaborationResponse:
    task = get_task_store().get_task(team_access.team_id, task_id, access_token=team_access.access_token)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    runtime_context = _build_runtime_context(team_access)
    stage_selection_map = _build_stage_selection_map(task, team_access, runtime_context)
    _sync_task_human_collaboration(task, team_access, stage_selection_map=stage_selection_map)
    refreshed_task = get_task_store().get_task(team_access.team_id, task_id, access_token=team_access.access_token) or task
    return get_task_human_collaboration_service().get_snapshot(refreshed_task, access_token=team_access.access_token)


@router.post("/{task_id}/human-requests", response_model=TaskHumanCollaborationResponse, status_code=status.HTTP_201_CREATED)
def create_task_human_request(
    task_id: str,
    payload: TaskHumanRequestCreateRequest,
    team_access: TeamAccessContext = Depends(require_team_access),
) -> TaskHumanCollaborationResponse:
    task = get_task_store().get_task(team_access.team_id, task_id, access_token=team_access.access_token)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    try:
        return get_task_human_collaboration_service().create_request(
            task,
            payload,
            requested_by=team_access.user.id,
            access_token=team_access.access_token,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/{task_id}/human-requests/{request_id}/decision", response_model=TaskHumanCollaborationResponse)
def decide_task_human_request(
    task_id: str,
    request_id: str,
    payload: TaskHumanRequestDecisionRequest,
    team_access: TeamAccessContext = Depends(require_team_access),
) -> TaskHumanCollaborationResponse:
    task = get_task_store().get_task(team_access.team_id, task_id, access_token=team_access.access_token)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    try:
        return get_task_human_collaboration_service().submit_decision(
            task,
            request_id,
            payload,
            decided_by=team_access.user.id,
            access_token=team_access.access_token,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/{task_id}/resume", response_model=TaskHumanCollaborationResponse)
def resume_task_after_human_collaboration(
    task_id: str,
    team_access: TeamAccessContext = Depends(require_team_access),
) -> TaskHumanCollaborationResponse:
    task = get_task_store().get_task(team_access.team_id, task_id, access_token=team_access.access_token)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    try:
        return get_task_human_collaboration_service().resume_task(task, access_token=team_access.access_token)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/{task_id}/ai-conversations", response_model=TaskAIConversationResponse)
def get_task_ai_conversations(
    task_id: str,
    team_access: TeamAccessContext = Depends(require_team_access),
) -> TaskAIConversationResponse:
    task = get_task_store().get_task(team_access.team_id, task_id, access_token=team_access.access_token)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    return build_task_ai_conversations(task)


@router.post("/{task_id}/chat", response_model=TaskInteractiveChatResponse)
def send_task_chat(
    task_id: str,
    payload: TaskInteractiveChatRequest,
    team_access: TeamAccessContext = Depends(require_team_access),
) -> TaskInteractiveChatResponse:
    _assert_quota_allows_action(team_access, action_name="任务 AI 对话")
    task_store = get_task_store()
    task = task_store.get_task(team_access.team_id, task_id, access_token=team_access.access_token)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")

    runtime_context = _build_runtime_context(team_access)
    chat_stages = [WorkflowStage.report_generation] if task.last_run else [WorkflowStage.data_analysis, WorkflowStage.requirement_analysis]
    selection = _resolve_preferred_selection(task, team_access, runtime_context, chat_stages)
    runtime_settings = _build_runtime_settings_for_selection(get_settings(), selection)

    try:
        chat_result = send_task_chat_message(task, prompt=payload.prompt, settings=runtime_settings)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    saved_task = task_store.save_task(chat_result.task, access_token=team_access.access_token)
    task_store.upsert_token_ledger(
        team_id=saved_task.team_id,
        task_id=saved_task.id,
        phase="interactive_chat",
        stage_key=selection.stage.value,
        source_key=chat_result.assistant_message.id,
        usage=chat_result.token_usage,
        access_token=team_access.access_token,
        user_id=team_access.user.id,
        connector_id=selection.connector.id,
        connector_display_name=selection.connector.display_name,
        model_name=selection.model_name,
        calculation_method="provider_reported_usage",
    )
    return TaskInteractiveChatResponse(
        task=saved_task,
        conversation=build_task_ai_conversations(saved_task),
    )


@router.get("/{task_id}/code-workspace", response_model=TaskCodeWorkspaceResponse)
def get_task_code_workspace(
    task_id: str,
    team_access: TeamAccessContext = Depends(require_team_developer_access),
) -> TaskCodeWorkspaceResponse:
    task = get_task_store().get_task(team_access.team_id, task_id, access_token=team_access.access_token)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    return build_task_code_workspace(task)


@router.get("/{task_id}/code-workspace/file", response_model=TaskCodeArtifactContentResponse)
def get_task_code_workspace_file(
    task_id: str,
    path: str = Query(..., min_length=1),
    team_access: TeamAccessContext = Depends(require_team_developer_access),
) -> TaskCodeArtifactContentResponse:
    task = get_task_store().get_task(team_access.team_id, task_id, access_token=team_access.access_token)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    try:
        return read_task_code_artifact(task, path)
    except Exception as exc:  # noqa: BLE001
        _raise_code_workspace_http_error(exc)


@router.put("/{task_id}/code-workspace/file", response_model=TaskCodeArtifactContentResponse)
def update_task_code_workspace_file(
    task_id: str,
    payload: TaskCodeArtifactUpdateRequest,
    team_access: TeamAccessContext = Depends(require_team_developer_access),
) -> TaskCodeArtifactContentResponse:
    task = get_task_store().get_task(team_access.team_id, task_id, access_token=team_access.access_token)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    try:
        return save_task_code_artifact(task, payload)
    except Exception as exc:  # noqa: BLE001
        _raise_code_workspace_http_error(exc)


@router.post("/{task_id}/dataset", response_model=TaskRecord)
async def upload_dataset(
    task_id: str,
    file: UploadFile = File(...),
    team_access: TeamAccessContext = Depends(require_team_access),
) -> TaskRecord:
    task_store = get_task_store()
    task = task_store.get_task(team_access.team_id, task_id, access_token=team_access.access_token)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="only CSV uploads are supported")

    content = await file.read()
    dataset_path = task_store.save_dataset(team_access.team_id, task_id, file.filename, content)
    task.dataset_filename = file.filename
    task.dataset_path = str(dataset_path)
    task.status = TaskStatus.planning
    task.last_run = None
    task.last_run_attempt = None
    task.label_column = None
    task.problem_type = None
    task.analysis_token_usage = None
    task.structured_requirements = None
    task.notes = "CSV 已上传，系统会根据当前阶段路由自动执行 AI 解析。"
    task = task_store.save_task(task, access_token=team_access.access_token)

    return _run_ai_analysis(task, task_store, team_access, fail_on_error=False)


@router.post("/{task_id}/analyze", response_model=TaskRecord)
def analyze_task(
    task_id: str,
    team_access: TeamAccessContext = Depends(require_team_access),
) -> TaskRecord:
    task_store = get_task_store()
    task = task_store.get_task(team_access.team_id, task_id, access_token=team_access.access_token)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    return _run_ai_analysis(task, task_store, team_access, fail_on_error=True)


@router.post("/{task_id}/run", response_model=TaskRecord)
def run_task(
    task_id: str,
    payload: TaskRunRequest,
    team_access: TeamAccessContext = Depends(require_team_access),
) -> TaskRecord:
    task_store = get_task_store()
    human_service = get_task_human_collaboration_service()
    task = task_store.get_task(team_access.team_id, task_id, access_token=team_access.access_token)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    if not task.dataset_path:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="dataset has not been uploaded")

    try:
        human_service.assert_task_can_run(task, access_token=team_access.access_token)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    if not task.label_column or not task.problem_type:
        task = _run_ai_analysis(task, task_store, team_access, fail_on_error=True)

    runtime_context = _build_runtime_context(team_access)
    stage_selection_map = _build_stage_selection_map(task, team_access, runtime_context)

    cycle_id = _next_policy_cycle(task)
    task, created_policy_requests = _apply_interaction_policies(
        task,
        team_access,
        trigger_mode=InteractionTriggerMode.before_run,
        cycle_id=cycle_id,
        stage_selection_map=stage_selection_map,
    )
    if created_policy_requests:
        _sync_task_human_collaboration(task, team_access, stage_selection_map=stage_selection_map)
        return task

    selection = _resolve_preferred_selection(
        task,
        team_access,
        runtime_context,
        [WorkflowStage.model_selection, WorkflowStage.training_validation, WorkflowStage.feature_engineering],
    )
    _assert_quota_allows_action(
        team_access,
        action_name="MLZero 运行",
        block_at_warning_threshold=True,
    )
    runtime_settings = _build_runtime_settings_for_selection(get_settings(), selection)

    task.status = TaskStatus.running
    task.notes = "MLZero 正在运行。"
    task = task_store.save_task(task, access_token=team_access.access_token)

    stage_selection_map.update(
        {
            WorkflowStage.feature_engineering.value: selection.stage_record,
            WorkflowStage.model_selection.value: selection.stage_record,
            WorkflowStage.training_validation.value: selection.stage_record,
            WorkflowStage.report_generation.value: selection.stage_record,
        }
    )
    _sync_task_human_collaboration(task, team_access, stage_selection_map=stage_selection_map)

    try:
        summary = MLZeroExecutor(runtime_settings).run(task, Path(task.dataset_path), payload.time_limit)
    except Exception as exc:  # noqa: BLE001
        task.status = TaskStatus.failed
        task.notes = str(exc)
        if isinstance(exc, MLZeroRunError) and exc.output_dir:
            task.last_run_attempt = RunAttempt(
                output_dir=exc.output_dir,
                token_usage=exc.token_usage,
            )
            task_store.upsert_run_attempt(
                task,
                output_dir=exc.output_dir,
                status="failed",
                token_usage=exc.token_usage,
                notes=str(exc),
                access_token=team_access.access_token,
            )
            task_store.upsert_token_ledger(
                team_id=task.team_id,
                task_id=task.id,
                phase="mlzero",
                stage_key=selection.stage.value,
                source_key=exc.output_dir,
                usage=exc.token_usage,
                access_token=team_access.access_token,
                user_id=team_access.user.id,
                connector_id=selection.connector.id,
                connector_display_name=selection.connector.display_name,
                model_name=selection.model_name,
                calculation_method="mlzero_token_usage_json",
            )
        saved_task = task_store.save_task(task, access_token=team_access.access_token)
        saved_task, _ = _apply_interaction_policies(
            saved_task,
            team_access,
            trigger_mode=InteractionTriggerMode.in_run,
            cycle_id=cycle_id,
            stage_selection_map=stage_selection_map,
        )
        _sync_task_human_collaboration(saved_task, team_access, stage_selection_map=stage_selection_map)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    task.status = TaskStatus.completed
    task.notes = "MLZero 运行完成。"
    task.last_run = summary
    task.last_run_attempt = RunAttempt(
        output_dir=summary.output_dir,
        token_usage=summary.token_usage,
    )
    saved_task = task_store.save_task(task, access_token=team_access.access_token)
    task_store.upsert_run_summary(saved_task, summary, access_token=team_access.access_token)
    task_store.upsert_token_ledger(
        team_id=saved_task.team_id,
        task_id=saved_task.id,
        phase="mlzero",
        stage_key=selection.stage.value,
        source_key=summary.output_dir,
        usage=summary.token_usage,
        access_token=team_access.access_token,
        user_id=team_access.user.id,
        connector_id=selection.connector.id,
        connector_display_name=selection.connector.display_name,
        model_name=selection.model_name,
        calculation_method="mlzero_token_usage_json",
    )
    saved_task, _ = _apply_interaction_policies(
        saved_task,
        team_access,
        trigger_mode=InteractionTriggerMode.in_run,
        cycle_id=cycle_id,
        stage_selection_map=stage_selection_map,
    )
    _sync_task_human_collaboration(saved_task, team_access, stage_selection_map=stage_selection_map)
    return saved_task


@router.delete("/{task_id}", response_model=TaskDeleteResponse)
def delete_task(task_id: str, team_access: TeamAccessContext = Depends(require_team_access)) -> TaskDeleteResponse:
    task_store = get_task_store()
    task = task_store.get_task(team_access.team_id, task_id, access_token=team_access.access_token)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    if task.status == TaskStatus.running:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="任务仍在运行中，请等运行结束后再删除。",
        )

    deleted = task_store.delete_task(team_access.team_id, task_id, access_token=team_access.access_token)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")

    return TaskDeleteResponse(deleted=True, task_id=task_id)
