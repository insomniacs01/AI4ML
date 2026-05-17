from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException, status

from backend.app.core.config import Settings, get_settings
from backend.app.core.supabase_auth import (
    TeamAccessContext,
    require_team_access,
)
from backend.app.models.connector import StoredConnectorRecord
from backend.app.models.governance import AIRoutingPolicyRecord, TeamMemberRecord, TeamQuotaRecord
from backend.app.models.task import (
    PRIMARY_WORKFLOW_STAGES,
    InteractionTriggerMode,
    RunAttempt,
    TaskCreateRequest,
    TaskDeleteResponse,
    TaskAgentCollaborationResponse,
    TaskAgentRuntimeRecord,
    TaskHumanCollaborationResponse,
    TaskHumanRequestRecord,
    TaskHumanRequestCreateRequest,
    TaskHumanRequestDecisionRequest,
    TaskInteractionPolicyRecord,
    TaskInteractiveChatRequest,
    TaskInteractiveChatResponse,
    TaskListResponse,
    TaskRecord,
    TaskRunRequest,
    TaskRunProgressResponse,
    TaskSemanticUpdateRequest,
    TaskStageRoutingOverrideInput,
    TaskStageRoutingRecord,
    TaskStatus,
    TokenUsageResponse,
    TaskWorkflowConfigUpdateRequest,
    WorkflowStage,
    WorkflowStageRecord,
    WorkflowStageStatus,
    normalize_workflow_stage,
)
from backend.app.services.ai_task_analyzer import analyze_task_with_ai, apply_analysis_to_task
from backend.app.services.connector_runtime import build_runtime_settings
from backend.app.services.connector_store import ConnectorStore
from backend.app.services.dataset_profile import build_dataset_profile, dataset_profile_to_plain
from backend.app.services.executors.mlzero_executor import MLZeroExecutor, MLZeroRunError
from backend.app.services.governance_store import GovernanceStore
from backend.app.services.task_ai_conversations import build_task_ai_conversations
from backend.app.services.task_chat import send_task_chat_message
from backend.app.services.task_agent_collaboration import (
    append_stage_agent_messages,
    agent_runtime_spec_for_stage,
    build_task_agent_collaboration_response,
)
from backend.app.services.task_human_collaboration import TaskHumanCollaborationService
from backend.app.services.task_human_context import ensure_task_human_loop, get_task_human_loop
from backend.app.services.task_incremental_rerun import (
    IncrementalRerunError,
    IncrementalRerunPlan,
    IncrementalRerunPreconditionError,
    IncrementalRerunResult,
    build_incremental_rerun_plan,
    is_strict_incremental_stage,
    run_task_incrementally,
)
from backend.app.services.task_artifacts import (
    collect_stage_artifacts_by_stage as _collect_stage_artifacts_by_stage,
    read_run_log_excerpt as _read_run_log_excerpt,
    select_run_error_artifact as _select_run_error_artifact,
)
from backend.app.services.task_run_progress import build_task_run_progress
from backend.app.services.task_semantics import apply_human_semantic_update
from backend.app.services.task_store import TaskStore
from backend.app.services.token_usage import read_mlzero_token_usage, read_token_usage


MAX_CSV_UPLOAD_BYTES = 100 * 1024 * 1024
CSV_UPLOAD_CHUNK_BYTES = 1024 * 1024
ALLOWED_CSV_CONTENT_TYPES = {
    "text/csv",
    "application/csv",
    "application/vnd.ms-excel",
    "text/plain",
    "application/octet-stream",
}


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


def _validate_upload_filename(filename: str) -> str:
    normalized = filename.strip()
    if not normalized:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="dataset filename is required")
    if Path(normalized).name != normalized or "\\" in normalized or "/" in normalized:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="dataset filename must not contain path separators")
    if any(ord(char) < 32 for char in normalized):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="dataset filename contains control characters")
    if Path(normalized).suffix.lower() != ".csv":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="only CSV uploads are supported")
    return normalized


def _validate_upload_content_type(content_type: str | None) -> None:
    if not content_type:
        return
    normalized = content_type.split(";")[0].strip().lower()
    if normalized not in ALLOWED_CSV_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"unsupported CSV content type: {content_type}",
        )


def _validate_csv_sample(sample: bytes) -> None:
    if not sample:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="uploaded CSV is empty")
    if b"\x00" in sample:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="uploaded file contains binary null bytes")
    try:
        sample.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"uploaded CSV is not valid UTF-8: {exc}") from exc


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


def _load_team_members_for_human(team_access: TeamAccessContext) -> list[TeamMemberRecord]:
    try:
        return get_governance_store().list_members(
            team_access.team_id,
            access_token=team_access.access_token,
        )
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        _raise_governance_http_error(exc)


def _write_task_audit(
    team_access: TeamAccessContext,
    *,
    action: str,
    task_id: str,
    detail: dict | None = None,
    resource_type: str = "ai_task",
) -> None:
    try:
        get_governance_store().create_audit_log(
            team_access.team_id,
            team_access.user.id,
            action=action,
            resource_type=resource_type,
            resource_id=task_id,
            detail=detail or {},
            access_token=team_access.access_token,
        )
    except (RuntimeError, PermissionError, ConnectionError):
        pass


def _validate_interaction_policy_assignees(
    policies: list[TaskInteractionPolicyRecord],
    team_access: TeamAccessContext,
) -> None:
    if not policies:
        return
    team_members = _load_team_members_for_human(team_access)
    service = get_task_human_collaboration_service()
    for policy in policies:
        try:
            service.resolve_assignee(
                assignee_type=policy.assignee_type,
                assignee_value=policy.assignee_value,
                assigned_to=policy.assignee_value if policy.assignee_type.value == "member" else None,
                default_member_id=team_access.user.id,
                team_members=team_members,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


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
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
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


AGENT_SCHEMA_MISSING_DETAIL = (
    "Supabase schema 缺少 Agent 协同表。请在 Supabase SQL Editor 执行最新 supabase/schema.sql，"
    "确保 task_agent_runs、task_agent_events、task_agent_messages 已创建，并等待 PostgREST schema cache 刷新后重试。"
)


def _is_agent_schema_missing_error(exc: Exception) -> bool:
    text = str(exc)
    return "PGRST205" in text and any(
        table_name in text
        for table_name in ("task_agent_runs", "task_agent_events", "task_agent_messages")
    )


def _raise_agent_schema_http_error(exc: Exception) -> None:
    if _is_agent_schema_missing_error(exc):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=AGENT_SCHEMA_MISSING_DETAIL) from exc
    raise exc


def _is_agent_schema_http_exception(exc: HTTPException) -> bool:
    return exc.status_code == status.HTTP_409_CONFLICT and str(exc.detail) == AGENT_SCHEMA_MISSING_DETAIL


def _record_workflow_stage(
    task: TaskRecord,
    team_access: TeamAccessContext,
    *,
    stage: WorkflowStage,
    stage_status: WorkflowStageStatus,
    summary: str,
    selection: TaskStageRoutingRecord | _ResolvedStageSelection | None = None,
    artifact_refs: list[str] | dict | None = None,
    log_excerpt: str | None = None,
) -> None:
    stage_record = selection.stage_record if isinstance(selection, _ResolvedStageSelection) else selection
    task_store = get_task_store()
    task_store.upsert_stage_record(
        team_id=task.team_id,
        task_id=task.id,
        stage=stage,
        status=stage_status,
        access_token=team_access.access_token,
        selected_connector_id=stage_record.connector_id if stage_record else None,
        model_name=stage_record.model_name if stage_record else None,
        selection_source=stage_record.selection_source if stage_record else None,
        summary=summary,
        artifact_refs=artifact_refs,
        log_excerpt=log_excerpt,
    )
    agent_spec = agent_runtime_spec_for_stage(stage)
    agent_name = str(agent_spec["name"])
    agent_role = str(agent_spec["role"])
    status_value = stage_status.value if hasattr(stage_status, "value") else str(stage_status)
    current_task = summary
    try:
        task_store.upsert_agent_run(
            team_id=task.team_id,
            task_id=task.id,
            agent_id=str(agent_spec["agent_id"]),
            stage=stage,
            name=agent_name,
            role=agent_role,
            short_role=str(agent_spec["short_role"]),
            status=stage_status,
            progress=_agent_progress_for_status(stage_status),
            current_task=current_task,
            access_token=team_access.access_token,
            selected_connector_id=stage_record.connector_id if stage_record else None,
            model_name=stage_record.model_name if stage_record else None,
            selection_source=stage_record.selection_source if stage_record else None,
            artifact_refs=artifact_refs,
            log_excerpt=log_excerpt,
            worker_id=f"backend-agent-worker:{task.id}:{normalize_workflow_stage(stage).value}",
        )
        task_store.append_agent_event(
            team_id=task.team_id,
            task_id=task.id,
            agent_id=str(agent_spec["agent_id"]),
            stage=stage,
            kind="agent",
            status=status_value,
            text=f"{agent_name}（{agent_role}）{_format_stage_status(stage_status)}：{current_task}",
            artifact_refs=artifact_refs,
            access_token=team_access.access_token,
        )
        append_stage_agent_messages(
            task_store,
            task,
            access_token=team_access.access_token,
            stage=stage,
            stage_status=stage_status,
            summary=current_task,
            artifact_refs=artifact_refs,
            log_excerpt=log_excerpt,
        )
    except ConnectionError as exc:
        _raise_agent_schema_http_error(exc)


def _format_stage_status(stage_status: WorkflowStageStatus) -> str:
    labels = {
        WorkflowStageStatus.pending: "待命",
        WorkflowStageStatus.running: "执行中",
        WorkflowStageStatus.waiting_human: "等待人工",
        WorkflowStageStatus.completed: "已完成",
        WorkflowStageStatus.failed: "失败",
    }
    return labels.get(stage_status, stage_status.value if hasattr(stage_status, "value") else str(stage_status))


def _agent_progress_for_status(stage_status: WorkflowStageStatus) -> int:
    if stage_status == WorkflowStageStatus.completed:
        return 100
    if stage_status == WorkflowStageStatus.failed:
        return 100
    if stage_status == WorkflowStageStatus.running:
        return 62
    if stage_status == WorkflowStageStatus.waiting_human:
        return 48
    return 0


_RECOVERABLE_RUN_MARKERS = (
    "apitimeouterror",
    "request timed out",
    "readtimeout",
    "retryerror",
    "modulenotfounderror",
    "no module named",
    "run_summary.json",
    "leaderboard",
)

def _stage_label(stage: WorkflowStage | None) -> str:
    labels = {
        WorkflowStage.requirement_analysis: "需求解析阶段",
        WorkflowStage.data_analysis: "数据分析阶段",
        WorkflowStage.feature_engineering: "代码生成阶段",
        WorkflowStage.model_selection: "模型选择阶段",
        WorkflowStage.training_validation: "训练验证阶段",
        WorkflowStage.report_generation: "报告生成阶段",
    }
    return labels.get(stage, "当前阶段")


def _run_exception_output_dir(exc: Exception) -> str | None:
    return getattr(exc, "output_dir", None) if isinstance(exc, (MLZeroRunError, IncrementalRerunError)) else None


def _run_exception_token_usage(exc: Exception):
    return getattr(exc, "token_usage", None) if isinstance(exc, (MLZeroRunError, IncrementalRerunError)) else None


def _run_exception_retry_stage(exc: Exception) -> WorkflowStage | None:
    raw_stage = getattr(exc, "retry_stage", None)
    if not raw_stage:
        return None
    try:
        return normalize_workflow_stage(raw_stage)
    except ValueError:
        return None


def _is_recoverable_run_exception(exc: Exception) -> bool:
    if isinstance(exc, (MLZeroRunError, IncrementalRerunError)) and bool(getattr(exc, "recoverable", False)):
        return True
    text = str(exc).lower()
    return any(marker in text for marker in _RECOVERABLE_RUN_MARKERS)


def _recoverable_run_note(exc: Exception, retry_stage: WorkflowStage | None) -> str:
    detail = str(exc).strip().splitlines()[0] if str(exc).strip() else "运行器没有返回可读错误。"
    return (
        f"Agent 自动修复受阻：{_stage_label(retry_stage)}遇到可恢复问题，"
        f"已保留本次产物目录并等待重新运行继续修复。原因：{detail}"
    )


def _stage_records_for_recoverable_run_block(
    retry_stage: WorkflowStage | None,
    error: Exception,
) -> tuple[dict[WorkflowStage, WorkflowStageStatus], dict[WorkflowStage, str]]:
    active_stage = retry_stage if retry_stage in PRIMARY_WORKFLOW_STAGES else WorkflowStage.feature_engineering
    active_index = PRIMARY_WORKFLOW_STAGES.index(active_stage)
    status_by_stage: dict[WorkflowStage, WorkflowStageStatus] = {}
    summary_by_stage: dict[WorkflowStage, str] = {}
    for index, stage in enumerate(PRIMARY_WORKFLOW_STAGES):
        if index < active_index:
            status_by_stage[stage] = WorkflowStageStatus.completed
            summary_by_stage[stage] = "上游阶段已交付到本次 MLZero 运行，等待下游自动修复继续使用。"
        elif stage == active_stage:
            status_by_stage[stage] = WorkflowStageStatus.running
            summary_by_stage[stage] = (
                f"Agent 自动修复受阻，当前停在{_stage_label(stage)}；"
                f"下一次运行会基于保留产物继续尝试修复。原因：{str(error).splitlines()[0] if str(error) else '未知'}"
            )
        else:
            status_by_stage[stage] = WorkflowStageStatus.pending
            summary_by_stage[stage] = f"等待{_stage_label(active_stage)}恢复后继续。"
    return status_by_stage, summary_by_stage


def _record_stage_selection_map(
    task: TaskRecord,
    team_access: TeamAccessContext,
    *,
    stage_selection_map: dict[str, TaskStageRoutingRecord],
    status_by_stage: dict[WorkflowStage, WorkflowStageStatus],
    summary_by_stage: dict[WorkflowStage, str],
    artifact_refs: list[str] | dict | None = None,
    artifact_refs_by_stage: dict[WorkflowStage, list[str] | dict] | None = None,
    log_excerpt_by_stage: dict[WorkflowStage, str] | None = None,
) -> None:
    for stage, stage_status in status_by_stage.items():
        _record_workflow_stage(
            task,
            team_access,
            stage=stage,
            stage_status=stage_status,
            summary=summary_by_stage[stage],
            selection=stage_selection_map.get(stage.value),
            artifact_refs=artifact_refs_by_stage.get(stage, artifact_refs) if artifact_refs_by_stage else artifact_refs,
            log_excerpt=log_excerpt_by_stage.get(stage) if log_excerpt_by_stage else None,
        )


def _ensure_agent_runtime_records(
    task: TaskRecord,
    team_access: TeamAccessContext,
    *,
    stages: list[WorkflowStageRecord],
    human_requests: list[TaskHumanRequestRecord],
    agent_runs: list[TaskAgentRuntimeRecord],
) -> list[TaskAgentRuntimeRecord]:
    task_store = get_task_store()
    existing_by_agent = {record.agent_id: record for record in agent_runs}
    stages_by_key = {normalize_workflow_stage(record.stage).value: record for record in stages}
    open_request_stages = {
        normalize_workflow_stage(request.stage).value
        for request in human_requests
        if str(request.status.value if hasattr(request.status, "value") else request.status) in {"pending", "open"}
    }

    created_records: list[TaskAgentRuntimeRecord] = []
    for stage in PRIMARY_WORKFLOW_STAGES:
        stage_key = stage.value
        if stage_key in existing_by_agent:
            continue
        stage_record = stages_by_key.get(stage_key)
        agent_spec = agent_runtime_spec_for_stage(stage)
        resolved_status = stage_record.status if stage_record else WorkflowStageStatus.pending
        if stage_key in open_request_stages:
            resolved_status = WorkflowStageStatus.waiting_human
        current_task = (
            stage_record.summary
            if stage_record and stage_record.summary
            else str(agent_spec["description"])
        )
        created_records.append(
            task_store.upsert_agent_run(
                team_id=task.team_id,
                task_id=task.id,
                agent_id=stage_key,
                stage=stage,
                name=str(agent_spec["name"]),
                role=str(agent_spec["role"]),
                short_role=str(agent_spec["short_role"]),
                status=resolved_status,
                progress=_agent_progress_for_status(resolved_status),
                current_task=current_task,
                access_token=team_access.access_token,
                selected_connector_id=stage_record.selected_connector_id if stage_record else None,
                model_name=stage_record.model_name if stage_record else None,
                selection_source=stage_record.selection_source if stage_record else None,
                artifact_refs=stage_record.artifact_refs if stage_record else None,
                log_excerpt=stage_record.log_excerpt if stage_record else None,
                worker_id=f"backend-agent-worker:{task.id}:{stage_key}",
            )
        )
    return [*agent_runs, *created_records]


def _diagnose_run_failure(
    exc: Exception,
    *,
    retry_stage: WorkflowStage | None,
    output_dir: str | None,
    recoverable: bool,
) -> dict[str, str | None]:
    raw_text = str(exc)
    evidence = "\n".join(part for part in (raw_text, _read_run_log_excerpt(output_dir) or "") if part).lower()
    error_artifact_path = _select_run_error_artifact(output_dir)
    stage_label = _stage_label(retry_stage)

    if "return code: 130" in evidence or "returncode 130" in evidence:
        diagnosis = "诊断结论：自动建模进程被外部中断。"
        detail = (
            "这类退出通常不是模型代码本身的 traceback，而是运行进程被后端重启、开发模式 reload 或人工中断打断；"
            "已保留本次运行目录，修复运行环境后可重新运行。"
        )
    elif any(marker in evidence for marker in ("apitimeouterror", "request timed out", "readtimeout", "retryerror")):
        diagnosis = "诊断结论：AI 服务请求超时，自动修复暂时受阻。"
        detail = "建议稍后重试，或检查当前阶段使用的 AI 服务、网络和超时配置；已保留结果文件用于继续修复。"
    elif any(marker in evidence for marker in ("modulenotfounderror", "no module named")):
        diagnosis = "诊断结论：运行环境缺少 Python 依赖。"
        detail = "需要先补齐日志中指向的依赖包，然后重新运行；系统已保留结果目录用于继续修复。"
    elif "run_summary.json" in evidence or "leaderboard" in evidence:
        diagnosis = "诊断结论：自动建模结果不完整，尚不能判定为成功运行。"
        detail = "训练目录已保留，但缺少完整的结果摘要、候选模型对比或 AI 使用记录；重新运行会继续尝试补齐。"
    elif recoverable:
        diagnosis = f"诊断结论：{stage_label}遇到可恢复问题，自动修复暂时受阻。"
        detail = "已保留本次结果文件，下一次运行会基于这些文件继续尝试修复。"
    else:
        diagnosis = "Agent 诊断：本次 MLZero 运行失败，已保留报错文件。"
        detail = "前端不直接展开原始异常；需要人工排查时，请打开保留的报错文件查看完整日志。"

    if error_artifact_path:
        detail = f"{detail} 报错文件：{error_artifact_path}"

    return {
        "diagnosis": diagnosis,
        "detail": detail,
        "error_artifact_path": error_artifact_path,
    }


def _run_failure_log_excerpt(diagnosis: dict[str, str | None]) -> str:
    lines = [
        diagnosis.get("diagnosis") or "Agent 诊断：运行失败。",
        diagnosis.get("detail") or "完整原始日志已保留在运行目录。",
    ]
    return "\n".join(line for line in lines if line)


def _progress_indicates_terminal_block(progress: TaskRunProgressResponse) -> bool:
    if progress.status != "blocked" or progress.stale:
        return False
    return any(insight.event_type in {"mlzero_max_iterations", "mlzero_interrupted"} for insight in progress.insights)


def _progress_indicates_orphaned_running_process(progress: TaskRunProgressResponse) -> bool:
    if progress.status != "running" or not progress.output_dir:
        return False
    if progress.seconds_since_last_update is None or progress.seconds_since_last_update < 5 * 60:
        return False
    if progress.current_iteration is not None and progress.total_iterations is not None:
        return True
    if progress.artifacts.has_generated_code or progress.artifacts.has_run_summary or progress.artifacts.has_leaderboard:
        return True
    return False


def _repair_stale_running_task(
    task: TaskRecord,
    team_access: TeamAccessContext,
    progress: TaskRunProgressResponse,
) -> TaskRunProgressResponse:
    terminal_block = _progress_indicates_terminal_block(progress)
    orphaned_process = _progress_indicates_orphaned_running_process(progress)
    if task.status != TaskStatus.running or (not progress.stale and not terminal_block and not orphaned_process) or not progress.output_dir:
        return progress
    if task.notes and "Agent 自动修复受阻" in task.notes:
        progress.status = "blocked"
        progress.stale = False
        progress.stale_reason = None
        return progress

    output_dir = progress.output_dir
    if not terminal_block:
        active_process = _has_active_local_run_process(task.id, output_dir)
        if active_process is True:
            progress.warnings.append("检测到仍有当前任务相关的本地 Python/MLZero 进程，暂不自动改写任务状态。")
            return progress
        if active_process is None and (
            progress.seconds_since_last_update is None or progress.seconds_since_last_update < 6 * 60 * 60
        ):
            progress.warnings.append("无法确认本地进程状态，且运行目录未超过 6 小时无更新，暂不自动改写任务状态。")
            return progress

    token_usage = read_mlzero_token_usage(output_dir)
    activity = progress.current_activity or "没有可解析的最后活动。"
    task.status = TaskStatus.running
    interrupted_block = terminal_block and any(insight.event_type == "mlzero_interrupted" for insight in progress.insights)
    if terminal_block:
        terminal_prefix = (
            "Agent 自动修复受阻：MLZero 子进程已被中断，但任务状态仍停留在运行中；"
            if interrupted_block
            else "Agent 自动修复受阻：MLZero 已达到最大搜索轮次并停止，但任务状态仍停留在运行中；"
        )
        task.notes = f"{terminal_prefix}已保留输出目录并等待重新运行继续修复。最后活动：{activity}"
    else:
        task.notes = (
            f"Agent 自动修复受阻：运行目录无更新且未检测到当前任务的活跃 MLZero 子进程，"
            f"已保留输出目录并等待重新运行继续修复。最后活动：{activity}"
        )
    error_artifact_path = progress.artifacts.error_log_path
    task.last_run_attempt = RunAttempt(
        output_dir=output_dir,
        token_usage=token_usage,
        diagnosis=(
            "Agent 诊断：MLZero 子进程已被中断，自动修复暂时受阻。"
            if interrupted_block
            else "Agent 诊断：MLZero 已达到最大搜索轮次，自动修复暂时受阻。" if terminal_block else None
        ),
        diagnosis_detail=task.notes,
        error_artifact_path=error_artifact_path,
    )

    log_excerpt = _read_run_log_excerpt(output_dir) or activity
    feature_status = WorkflowStageStatus.completed if progress.artifacts.has_generated_code else WorkflowStageStatus.running
    model_status = WorkflowStageStatus.completed if progress.artifacts.has_leaderboard else WorkflowStageStatus.pending
    training_status = WorkflowStageStatus.running
    report_status = WorkflowStageStatus.pending
    if progress.artifacts.has_run_summary and progress.artifacts.has_leaderboard and not progress.artifacts.has_token_usage:
        training_summary = "训练已产出 run_summary / leaderboard，但缺少 token_usage.json，严格口径下不能判定为完整成功。"
    elif interrupted_block:
        training_summary = "MLZero 子进程已被中断；本次运行没有被判定为完整成功，等待重新运行继续修复。"
    elif terminal_block:
        training_summary = "MLZero 已达到最大搜索轮次并停止；本次运行没有被判定为完整成功，等待重新运行继续修复。"
    else:
        training_summary = "Agent 判断本次运行已停住；产物目录已保留，下一次运行会继续尝试修复。"

    task_store = get_task_store()
    try:
        saved_task = task_store.save_task(task, access_token=team_access.access_token)
        task_store.upsert_run_attempt(
            saved_task,
            output_dir=output_dir,
            status="running",
            token_usage=token_usage,
            notes=saved_task.notes,
            access_token=team_access.access_token,
        )
        _record_stage_selection_map(
            saved_task,
            team_access,
            stage_selection_map={},
            status_by_stage={
                WorkflowStage.feature_engineering: feature_status,
                WorkflowStage.model_selection: model_status,
                WorkflowStage.training_validation: training_status,
                WorkflowStage.report_generation: report_status,
            },
            summary_by_stage={
                WorkflowStage.feature_engineering: (
                    "已找到生成代码产物。" if feature_status == WorkflowStageStatus.completed else "代码生成阶段需要 Agent 继续修复。"
                ),
                WorkflowStage.model_selection: (
                    "已找到候选模型 leaderboard。" if model_status == WorkflowStageStatus.completed else "候选模型比较等待修复后继续。"
                ),
                WorkflowStage.training_validation: training_summary,
                WorkflowStage.report_generation: "等待训练验证恢复后生成报告。",
            },
            artifact_refs=[output_dir],
            artifact_refs_by_stage=_collect_stage_artifacts_by_stage(output_dir),
            log_excerpt_by_stage={
                WorkflowStage.feature_engineering: log_excerpt,
                WorkflowStage.model_selection: log_excerpt,
                WorkflowStage.training_validation: log_excerpt,
                WorkflowStage.report_generation: log_excerpt,
            },
        )
        _write_task_audit(
            team_access,
            action="task.run.stale_repair",
            task_id=saved_task.id,
            detail={
                "status": "repair_blocked",
                "output_dir": output_dir,
                "stale_reason": progress.stale_reason,
                "terminal_block": terminal_block,
                "last_activity": activity,
                "has_run_summary": progress.artifacts.has_run_summary,
                "has_leaderboard": progress.artifacts.has_leaderboard,
                "has_token_usage": progress.artifacts.has_token_usage,
                "error_artifact_path": error_artifact_path,
            },
        )
        repaired = build_task_run_progress(saved_task, get_settings())
    except Exception as exc:  # noqa: BLE001
        progress.task = task
        progress.status = "blocked"
        progress.stale = False
        progress.stale_reason = None
        progress.warnings.append(f"Agent 已判断运行受阻，但状态落库失败：{exc}")
        repaired = progress

    repaired.repaired = True
    repaired.repair_action = (
        "terminal_running_marked_repair_blocked" if terminal_block else "orphaned_running_marked_repair_blocked" if orphaned_process else "stale_running_marked_repair_blocked"
    )
    return repaired


def _has_active_local_run_process(task_id: str, output_dir: str) -> bool | None:
    needles = [str(task_id), str(output_dir)]
    try:
        if os.name == "nt":
            result = subprocess.run(  # noqa: S603
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "Get-CimInstance Win32_Process | "
                    "Where-Object { $_.Name -match 'python|mamba|uvicorn' } | "
                    "Select-Object -ExpandProperty CommandLine",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=3,
                check=False,
            )
        else:
            result = subprocess.run(  # noqa: S603
                ["ps", "-eo", "args="],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=3,
                check=False,
            )
    except (OSError, subprocess.TimeoutExpired):
        return None

    if result.returncode != 0:
        return None
    current_process_hint = "Get-CimInstance Win32_Process" if os.name == "nt" else "ps -eo"
    for line in result.stdout.splitlines():
        if current_process_hint in line:
            continue
        if any(needle and needle in line for needle in needles):
            return True
    return False


def _resolve_requested_rerun_stage(task: TaskRecord, payload: TaskRunRequest) -> WorkflowStage | None:
    if payload.force_full_run:
        return None
    if payload.rerun_from_stage is not None:
        return normalize_workflow_stage(payload.rerun_from_stage)
    human_loop = get_task_human_loop(task)
    if not human_loop.get("rerun_requested"):
        return None
    raw_stage = human_loop.get("rerun_from_stage")
    if not isinstance(raw_stage, str) or not raw_stage.strip():
        return None
    try:
        return normalize_workflow_stage(raw_stage)
    except ValueError:
        return None


def _generation_stage_statuses_for_incremental_running(
    plan: IncrementalRerunPlan,
) -> tuple[dict[WorkflowStage, WorkflowStageStatus], dict[WorkflowStage, str], dict[WorkflowStage, list[str]]]:
    status_by_stage: dict[WorkflowStage, WorkflowStageStatus] = {}
    summary_by_stage: dict[WorkflowStage, str] = {}
    artifact_refs_by_stage: dict[WorkflowStage, list[str]] = {}
    manifest_path = str(plan.run_output_dir / "incremental_rerun_manifest.json")
    for stage in PRIMARY_WORKFLOW_STAGES:
        if stage in plan.reused_stages:
            status_by_stage[stage] = WorkflowStageStatus.completed
            summary_by_stage[stage] = (
                f"Reused from previous run for strict incremental rerun from {plan.start_stage.value}."
            )
            artifact_refs_by_stage[stage] = [str(plan.source_output_dir), manifest_path]
        elif stage == WorkflowStage.report_generation and plan.start_stage != WorkflowStage.report_generation:
            status_by_stage[stage] = WorkflowStageStatus.pending
            summary_by_stage[stage] = (
                f"Waiting for downstream outputs from strict incremental rerun from {plan.start_stage.value}."
            )
            artifact_refs_by_stage[stage] = [str(plan.run_output_dir), manifest_path]
        else:
            status_by_stage[stage] = WorkflowStageStatus.running
            summary_by_stage[stage] = f"Strict incremental rerun is executing from {plan.start_stage.value}."
            artifact_refs_by_stage[stage] = [str(plan.run_output_dir), manifest_path]
    return status_by_stage, summary_by_stage, artifact_refs_by_stage


def _stage_records_for_incremental_success(
    result: IncrementalRerunResult,
) -> tuple[dict[WorkflowStage, WorkflowStageStatus], dict[WorkflowStage, str], dict[WorkflowStage, list[str]]]:
    summary = result.summary
    status_by_stage: dict[WorkflowStage, WorkflowStageStatus] = {}
    summary_by_stage: dict[WorkflowStage, str] = {}
    artifact_refs_by_stage: dict[WorkflowStage, list[str]] = {}
    collected = _collect_stage_artifacts_by_stage(summary.output_dir)
    for stage in PRIMARY_WORKFLOW_STAGES:
        status_by_stage[stage] = WorkflowStageStatus.completed
        if stage in result.plan.reused_stages:
            summary_by_stage[stage] = (
                f"Reused unchanged from {result.plan.source_output_dir} for strict incremental rerun."
            )
            artifact_refs_by_stage[stage] = result.reused_artifacts_by_stage.get(stage, [str(result.plan.source_output_dir)])
        elif stage == WorkflowStage.model_selection:
            summary_by_stage[stage] = (
                f"Strict incremental rerun parsed {len(summary.leaderboard)} candidate model results; "
                f"best model is {summary.best_model}."
            )
            artifact_refs_by_stage[stage] = collected.get(stage, result.rerun_artifacts_by_stage.get(stage, [summary.output_dir]))
        elif stage == WorkflowStage.training_validation:
            summary_by_stage[stage] = (
                f"Strict incremental rerun completed training/validation: "
                f"{summary.metric_name} = {summary.metric_value:.6g}."
            )
            artifact_refs_by_stage[stage] = collected.get(stage, result.rerun_artifacts_by_stage.get(stage, [summary.output_dir]))
        elif stage == WorkflowStage.report_generation:
            summary_by_stage[stage] = "Strict incremental rerun refreshed report-ready artifacts and manifest."
            artifact_refs_by_stage[stage] = collected.get(stage, result.rerun_artifacts_by_stage.get(stage, [summary.output_dir]))
        else:
            summary_by_stage[stage] = f"Strict incremental rerun completed stage {stage.value}."
            artifact_refs_by_stage[stage] = collected.get(stage, result.rerun_artifacts_by_stage.get(stage, [summary.output_dir]))
        if str(result.manifest_path) not in artifact_refs_by_stage[stage]:
            artifact_refs_by_stage[stage] = [*artifact_refs_by_stage[stage], str(result.manifest_path)]
    return status_by_stage, summary_by_stage, artifact_refs_by_stage


def _stage_records_for_incremental_failure(
    plan: IncrementalRerunPlan,
    error: Exception,
) -> tuple[dict[WorkflowStage, WorkflowStageStatus], dict[WorkflowStage, str], dict[WorkflowStage, list[str]]]:
    status_by_stage: dict[WorkflowStage, WorkflowStageStatus] = {}
    summary_by_stage: dict[WorkflowStage, str] = {}
    artifact_refs_by_stage: dict[WorkflowStage, list[str]] = {}
    manifest_path = str(plan.run_output_dir / "incremental_rerun_manifest.json")
    for stage in PRIMARY_WORKFLOW_STAGES:
        if stage in plan.reused_stages:
            status_by_stage[stage] = WorkflowStageStatus.completed
            summary_by_stage[stage] = (
                f"Reused unchanged from {plan.source_output_dir}; downstream incremental rerun failed."
            )
            artifact_refs_by_stage[stage] = [str(plan.source_output_dir), manifest_path]
        else:
            status_by_stage[stage] = WorkflowStageStatus.failed
            summary_by_stage[stage] = f"Strict incremental rerun from {plan.start_stage.value} failed: {error}"
            artifact_refs_by_stage[stage] = [str(plan.run_output_dir), manifest_path]
    return status_by_stage, summary_by_stage, artifact_refs_by_stage


def _mark_rerun_completed(
    task: TaskRecord,
    *,
    start_stage: WorkflowStage | None,
    mode: str,
    output_dir: str,
) -> None:
    current_human_loop = get_task_human_loop(task)
    if not current_human_loop.get("rerun_requested") and start_stage is None:
        return
    human_loop = ensure_task_human_loop(task)
    human_loop["rerun_requested"] = False
    human_loop["last_rerun_from_stage"] = start_stage.value if start_stage else None
    human_loop["last_rerun_mode"] = mode
    human_loop["last_rerun_output_dir"] = output_dir
    human_loop["last_rerun_completed_at"] = datetime.now(timezone.utc).isoformat()
    human_loop["updated_at"] = datetime.now(timezone.utc).isoformat()


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
    team_members: list[TeamMemberRecord] | None = None

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
        if team_members is None:
            team_members = _load_team_members_for_human(team_access)
        try:
            assignee_type, assignee_value, assigned_to = get_task_human_collaboration_service().resolve_assignee(
                assignee_type=policy.assignee_type,
                assignee_value=policy.assignee_value,
                assigned_to=policy.assignee_value if policy.assignee_type.value == "member" else None,
                default_member_id=team_access.user.id,
                team_members=team_members,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

        task_store.create_human_request(
            team_id=task.team_id,
            task_id=task.id,
            stage=normalized_stage,
            requested_by=team_access.user.id,
            assigned_to=assigned_to,
            assignee_type=assignee_type.value,
            assignee_value=assignee_value,
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
        _record_workflow_stage(
            task,
            team_access,
            stage=WorkflowStage.requirement_analysis,
            stage_status=WorkflowStageStatus.completed,
            summary="任务描述和 CSV 数据已进入 AI 解析流程。",
            selection=stage_selection_map.get(WorkflowStage.requirement_analysis.value),
            artifact_refs=[task.dataset_path],
        )
        _record_workflow_stage(
            task,
            team_access,
            stage=WorkflowStage.data_analysis,
            stage_status=WorkflowStageStatus.running,
            summary="当前运行时 AI 正在读取 CSV 表头和样例行，解析目标列、任务类型和指标。",
            selection=selection,
            artifact_refs=[task.dataset_path],
        )
        analysis = analyze_task_with_ai(task, Path(task.dataset_path), runtime_settings)
    except HTTPException as exc:
        if _is_agent_schema_http_exception(exc):
            raise
        task.status = TaskStatus.planning
        task.notes = f"AI 解析失败：{exc.detail}"
        saved_task = task_store.save_task(task, access_token=team_access.access_token)
        _sync_task_human_collaboration(saved_task, team_access, stage_selection_map=stage_selection_map)
        _record_workflow_stage(
            saved_task,
            team_access,
            stage=WorkflowStage.data_analysis,
            stage_status=WorkflowStageStatus.failed,
            summary=f"AI 解析失败：{exc.detail}",
            selection=stage_selection_map.get(WorkflowStage.data_analysis.value),
            artifact_refs=[saved_task.dataset_path] if saved_task.dataset_path else None,
            log_excerpt=str(exc.detail),
        )
        if fail_on_error:
            raise
        return saved_task
    except Exception as exc:  # noqa: BLE001
        task.status = TaskStatus.planning
        task.notes = f"AI 解析失败：{exc}"
        saved_task = task_store.save_task(task, access_token=team_access.access_token)
        _sync_task_human_collaboration(saved_task, team_access, stage_selection_map=stage_selection_map)
        _record_workflow_stage(
            saved_task,
            team_access,
            stage=WorkflowStage.data_analysis,
            stage_status=WorkflowStageStatus.failed,
            summary=f"AI 解析失败：{exc}",
            selection=stage_selection_map.get(WorkflowStage.data_analysis.value),
            artifact_refs=[saved_task.dataset_path] if saved_task.dataset_path else None,
            log_excerpt=str(exc),
        )
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
        calculation_method=analysis.token_usage_calculation_method or "provider_reported_usage",
    )
    _sync_task_human_collaboration(saved_task, team_access, stage_selection_map=stage_selection_map)
    _record_workflow_stage(
        saved_task,
        team_access,
        stage=WorkflowStage.data_analysis,
        stage_status=WorkflowStageStatus.completed,
        summary=(
            f"AI 已完成数据理解：目标列 {analysis.label_column}，"
            f"任务类型 {analysis.problem_type}，指标 {analysis.metric_name}。"
        ),
        selection=selection,
        artifact_refs=[saved_task.dataset_path] if saved_task.dataset_path else None,
        log_excerpt=analysis.reasoning,
    )
    return saved_task
