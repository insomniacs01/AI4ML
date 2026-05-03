from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse

from backend.app.core.config import Settings, get_settings
from backend.app.core.supabase_auth import (
    TeamAccessContext,
    require_team_access,
    require_team_developer_access,
)
from backend.app.models.connector import StoredConnectorRecord
from backend.app.models.governance import AIRoutingPolicyRecord, TeamMemberRecord, TeamQuotaRecord
from backend.app.models.task import (
    PRIMARY_WORKFLOW_STAGES,
    InteractionTriggerMode,
    RunAttempt,
    TaskAIConversationResponse,
    TaskCodeArtifactContentResponse,
    TaskCodeArtifactRerunRequest,
    TaskCodeArtifactRerunResponse,
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
    TaskModelReportResponse,
    TaskPredictionDemoRequest,
    TaskPredictionDemoResponse,
    TaskRecord,
    TaskRunRequest,
    TaskStageRoutingOverrideInput,
    TaskStageRoutingRecord,
    TaskStatus,
    TokenUsageResponse,
    TaskWorkflowConfigUpdateRequest,
    WorkflowStage,
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
from backend.app.services.task_code_workspace import (
    build_task_code_workspace,
    read_task_code_artifact,
    rerun_task_code_artifact,
    resolve_task_code_artifact_file,
    save_task_code_artifact,
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
from backend.app.services.task_reporting import build_prediction_demo_response, build_task_model_report
from backend.app.services.task_store import TaskStore
from backend.app.services.token_usage import read_token_usage


router = APIRouter(prefix="/tasks", tags=["tasks"])

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
    get_task_store().upsert_stage_record(
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


def _collect_stage_artifacts_by_stage(output_dir: str | None) -> dict[WorkflowStage, list[str]]:
    if not output_dir:
        return {}
    root = Path(output_dir)
    if not root.exists():
        return {}

    stage_patterns: dict[WorkflowStage, tuple[str, ...]] = {
        WorkflowStage.feature_engineering: (
            "generated_code.py",
            "python_code.py",
            "python_coder_prompt.txt",
            "python_coder_response.txt",
            "execution_script.sh",
        ),
        WorkflowStage.model_selection: (
            "leaderboard.csv",
            "leaderboard.json",
            "run_summary.json",
            "tool_selector_prompt.txt",
            "tool_selector_response.txt",
        ),
        WorkflowStage.training_validation: (
            "run_summary.json",
            "validation_predictions.csv",
            "results.csv",
            "stdout",
            "stderr",
            "execution_stdout.txt",
            "execution_stderr.txt",
        ),
        WorkflowStage.report_generation: (
            "summary.txt",
            "run_summary.json",
            "feature_importance.csv",
            "feature_importance.json",
            "feature_importances.csv",
            "feature_importances.json",
        ),
    }

    collected: dict[WorkflowStage, list[str]] = {}
    files = [path for path in root.rglob("*") if path.is_file()]
    for stage, names in stage_patterns.items():
        matched: list[str] = []
        wanted = {name.lower() for name in names}
        for path in files:
            if path.name.lower() in wanted:
                matched.append(str(path))
            if len(matched) >= 12:
                break
        if matched:
            collected[stage] = matched
    return collected


def _read_run_log_excerpt(output_dir: str | None, *, max_chars: int = 1800) -> str | None:
    if not output_dir:
        return None
    root = Path(output_dir)
    if not root.exists():
        return None
    candidates = [
        root / "summary.txt",
        root / "mlzero_stderr.log",
        root / "mlzero_stdout.log",
        root / "info_logs.txt",
        root / "detail_logs.txt",
        root / "logs.txt",
    ]
    candidates.extend(sorted(root.rglob("*.log"), key=lambda item: item.stat().st_mtime if item.exists() else 0, reverse=True))
    seen: set[Path] = set()
    for path in candidates:
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        try:
            text = path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        if not text:
            continue
        if len(text) > max_chars:
            text = text[-max_chars:]
        return f"{path.name}\n{text}"
    return None


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
        calculation_method="provider_reported_usage",
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


@router.get("", response_model=TaskListResponse)
def list_tasks(team_access: TeamAccessContext = Depends(require_team_access)) -> TaskListResponse:
    return TaskListResponse(items=get_task_store().list_tasks(team_access.team_id, access_token=team_access.access_token))


@router.post("", response_model=TaskRecord, status_code=status.HTTP_201_CREATED)
def create_task(
    payload: TaskCreateRequest,
    team_access: TeamAccessContext = Depends(require_team_access),
) -> TaskRecord:
    _validate_task_stage_routing_overrides(payload.stage_routing)
    _validate_interaction_policy_assignees(payload.interaction_policies, team_access)
    task = get_task_store().create_task(
        payload,
        team_id=team_access.team_id,
        created_by=team_access.user.id,
        access_token=team_access.access_token,
    )
    _sync_task_human_collaboration(task, team_access, stage_selection_map={})
    _write_task_audit(
        team_access,
        action="task.create",
        task_id=task.id,
        detail={
            "name": task.name,
            "status": task.status.value,
            "stage_routing_count": len(task.stage_routing),
            "interaction_policy_count": len(task.interaction_policies),
        },
    )
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

    _validate_task_stage_routing_overrides(payload.stage_routing)
    _validate_interaction_policy_assignees(payload.interaction_policies, team_access)
    task.stage_routing = [
        TaskStageRoutingRecord(
            stage=normalize_workflow_stage(item.stage),
            connector_id=item.connector_id,
            model_name=item.model_name,
            selection_source="task_override",
        )
        for item in payload.stage_routing
        if item.connector_id
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
    _write_task_audit(
        team_access,
        action="task.workflow_config.update",
        task_id=saved_task.id,
        detail={
            "stage_routing_count": len(saved_task.stage_routing),
            "interaction_policy_count": len(saved_task.interaction_policies),
        },
    )
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
        team_members = _load_team_members_for_human(team_access)
        snapshot = get_task_human_collaboration_service().create_request(
            task,
            payload,
            requested_by=team_access.user.id,
            actor_role=team_access.role,
            team_members=team_members,
            access_token=team_access.access_token,
        )
        _write_task_audit(
            team_access,
            action="task.human_request.create",
            task_id=task.id,
            detail={
                "request_type": payload.request_type,
                "stage": normalize_workflow_stage(payload.stage).value,
                "assigned_to": payload.assigned_to,
                "assignee_type": payload.assignee_type.value if payload.assignee_type else None,
                "assignee_value": payload.assignee_value,
            },
        )
        return snapshot
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
        team_members = _load_team_members_for_human(team_access)
        snapshot = get_task_human_collaboration_service().submit_decision(
            task,
            request_id,
            payload,
            decided_by=team_access.user.id,
            actor_role=team_access.role,
            team_members=team_members,
            access_token=team_access.access_token,
        )
        _write_task_audit(
            team_access,
            action="task.human_request.decide",
            task_id=task.id,
            detail={
                "request_id": request_id,
                "action": payload.action.value,
                "reassign_assignee_type": payload.reassign_assignee_type.value if payload.reassign_assignee_type else None,
                "reassign_assignee_value": payload.reassign_assignee_value,
                "reassign_assigned_to": payload.reassign_assigned_to,
            },
        )
        return snapshot
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
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
        snapshot = get_task_human_collaboration_service().resume_task(task, access_token=team_access.access_token)
        _write_task_audit(
            team_access,
            action="task.resume",
            task_id=task.id,
            detail={"status": snapshot.task.status.value},
        )
        return snapshot
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


@router.get("/{task_id}/report", response_model=TaskModelReportResponse)
def get_task_model_report(
    task_id: str,
    team_access: TeamAccessContext = Depends(require_team_access),
) -> TaskModelReportResponse:
    task = get_task_store().get_task(team_access.team_id, task_id, access_token=team_access.access_token)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    return build_task_model_report(task)


@router.post("/{task_id}/prediction-demo", response_model=TaskPredictionDemoResponse)
def run_task_prediction_demo(
    task_id: str,
    payload: TaskPredictionDemoRequest,
    team_access: TeamAccessContext = Depends(require_team_access),
) -> TaskPredictionDemoResponse:
    task = get_task_store().get_task(team_access.team_id, task_id, access_token=team_access.access_token)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    response = build_prediction_demo_response(task, payload)
    _write_task_audit(
        team_access,
        action="task.prediction_demo.run",
        task_id=task.id,
        detail={
            "supported": response.supported,
            "feature_count": len(payload.features),
            "detail": response.detail,
        },
    )
    return response


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
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

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


@router.get("/{task_id}/code-workspace/download")
def download_task_code_workspace_file(
    task_id: str,
    path: str = Query(..., min_length=1),
    team_access: TeamAccessContext = Depends(require_team_developer_access),
) -> FileResponse:
    task = get_task_store().get_task(team_access.team_id, task_id, access_token=team_access.access_token)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    try:
        artifact_path, entry = resolve_task_code_artifact_file(task, path)
        _write_task_audit(
            team_access,
            action="task.code_workspace.download",
            task_id=task.id,
            detail={
                "path": entry.path,
                "size_bytes": entry.size_bytes,
                "run_output_dir": str(artifact_path.parent),
            },
        )
        return FileResponse(
            path=str(artifact_path),
            filename=entry.name,
            media_type="application/octet-stream",
        )
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
        result = save_task_code_artifact(task, payload)
        _write_task_audit(
            team_access,
            action="task.code_workspace.save",
            task_id=task.id,
            detail={
                "path": result.artifact.path,
                "size_bytes": result.artifact.size_bytes,
                "version_id": result.version_id,
            },
        )
        return result
    except Exception as exc:  # noqa: BLE001
        _raise_code_workspace_http_error(exc)


@router.post("/{task_id}/code-workspace/rerun", response_model=TaskCodeArtifactRerunResponse)
def rerun_task_code_workspace_file(
    task_id: str,
    payload: TaskCodeArtifactRerunRequest,
    team_access: TeamAccessContext = Depends(require_team_developer_access),
) -> TaskCodeArtifactRerunResponse:
    task = get_task_store().get_task(team_access.team_id, task_id, access_token=team_access.access_token)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    try:
        result = rerun_task_code_artifact(task, payload)
        _write_task_audit(
            team_access,
            action="task.code_workspace.rerun",
            task_id=task.id,
            detail={
                "path": result.path,
                "success": result.success,
                "exit_code": result.exit_code,
                "version_id": result.version_id,
            },
        )
        return result
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
    filename = _validate_upload_filename(file.filename or "")
    _validate_upload_content_type(file.content_type)

    dataset_path = task_store.dataset_upload_path(team_access.team_id, task_id, filename)
    size_bytes = 0
    sample = bytearray()
    try:
        with dataset_path.open("wb") as handle:
            while True:
                chunk = await file.read(CSV_UPLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                size_bytes += len(chunk)
                if size_bytes > MAX_CSV_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"CSV upload exceeds {MAX_CSV_UPLOAD_BYTES // (1024 * 1024)} MB limit",
                    )
                if len(sample) < CSV_UPLOAD_CHUNK_BYTES:
                    sample.extend(chunk[: CSV_UPLOAD_CHUNK_BYTES - len(sample)])
                handle.write(chunk)
        _validate_csv_sample(bytes(sample))
        dataset_profile = build_dataset_profile(
            dataset_path,
            filename=filename,
            target_column=None,
        )
        if dataset_profile.column_count == 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="uploaded CSV does not contain a header row")
    except HTTPException:
        if dataset_path.exists():
            dataset_path.unlink()
        raise
    except OSError as exc:
        if dataset_path.exists():
            dataset_path.unlink()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"failed to save uploaded CSV: {exc}") from exc

    task.dataset_filename = filename
    task.dataset_path = str(dataset_path)
    task.dataset_profile = dataset_profile
    task.status = TaskStatus.uploaded
    task.last_run = None
    task.last_run_attempt = None
    task.label_column = None
    task.problem_type = None
    task.analysis_token_usage = None
    task.structured_requirements = {"dataset_profile": dataset_profile_to_plain(dataset_profile)}
    task.notes = "CSV 已上传并完成基础画像，系统会根据当前阶段路由自动执行 AI 解析。"
    task = task_store.save_task(task, access_token=team_access.access_token)
    _record_workflow_stage(
        task,
        team_access,
        stage=WorkflowStage.data_analysis,
        stage_status=WorkflowStageStatus.completed,
        summary=(
            f"CSV 已上传并完成基础画像：{dataset_profile.row_count} 行、"
            f"{dataset_profile.column_count} 列。"
        ),
        artifact_refs=[str(dataset_path)],
        log_excerpt=(
            f"filename={filename}; size_bytes={size_bytes}; "
            f"columns={', '.join(column.name for column in dataset_profile.columns[:12])}"
        ),
    )
    _write_task_audit(
        team_access,
        action="task.dataset.upload",
        task_id=task.id,
        detail={
            "filename": filename,
            "size_bytes": size_bytes,
            "content_type": file.content_type,
            "row_count": dataset_profile.row_count,
            "column_count": dataset_profile.column_count,
            "status": task.status.value,
        },
    )

    return _run_ai_analysis(task, task_store, team_access, fail_on_error=True)


@router.post("/{task_id}/analyze", response_model=TaskRecord)
def analyze_task(
    task_id: str,
    team_access: TeamAccessContext = Depends(require_team_access),
) -> TaskRecord:
    task_store = get_task_store()
    task = task_store.get_task(team_access.team_id, task_id, access_token=team_access.access_token)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    try:
        result = _run_ai_analysis(task, task_store, team_access, fail_on_error=True)
    except HTTPException as exc:
        _write_task_audit(
            team_access,
            action="task.analyze",
            task_id=task.id,
            detail={"status": "failed", "detail": exc.detail},
        )
        raise
    _write_task_audit(
        team_access,
        action="task.analyze",
        task_id=result.id,
        detail={
            "status": "completed",
            "label_column": result.label_column,
            "problem_type": result.problem_type,
        },
    )
    return result


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

    requested_rerun_stage_before_analysis = _resolve_requested_rerun_stage(task, payload)
    if requested_rerun_stage_before_analysis in {WorkflowStage.requirement_analysis, WorkflowStage.data_analysis}:
        task = _run_ai_analysis(task, task_store, team_access, fail_on_error=True)
    elif not task.label_column or not task.problem_type:
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
        _write_task_audit(
            team_access,
            action="task.run",
            task_id=task.id,
            detail={
                "status": "waiting_human",
                "created_human_requests": created_policy_requests,
                "cycle_id": cycle_id,
            },
        )
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
    requested_rerun_stage = requested_rerun_stage_before_analysis or _resolve_requested_rerun_stage(task, payload)
    incremental_plan: IncrementalRerunPlan | None = None
    if requested_rerun_stage is not None and is_strict_incremental_stage(requested_rerun_stage):
        try:
            incremental_plan = build_incremental_rerun_plan(
                task,
                settings=runtime_settings,
                start_stage=requested_rerun_stage,
            )
        except IncrementalRerunPreconditionError as exc:
            _write_task_audit(
                team_access,
                action="task.run",
                task_id=task.id,
                detail={
                    "status": "blocked",
                    "detail": str(exc),
                    "rerun_from_stage": requested_rerun_stage.value,
                    "cycle_id": cycle_id,
                },
            )
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    task.status = TaskStatus.running
    task.notes = "MLZero 正在运行。"
    if incremental_plan is not None:
        task.notes = f"Strict incremental rerun from {incremental_plan.start_stage.value} is running."
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
    _record_stage_selection_map(
        task,
        team_access,
        stage_selection_map=stage_selection_map,
        status_by_stage={
            WorkflowStage.feature_engineering: WorkflowStageStatus.running,
            WorkflowStage.model_selection: WorkflowStageStatus.running,
            WorkflowStage.training_validation: WorkflowStageStatus.running,
            WorkflowStage.report_generation: WorkflowStageStatus.pending,
        },
        summary_by_stage={
            WorkflowStage.feature_engineering: "MLZero 已开始生成和修正特征处理 / 训练代码。",
            WorkflowStage.model_selection: "MLZero 已开始选择并比较候选模型。",
            WorkflowStage.training_validation: "MLZero 正在训练和验证候选模型。",
            WorkflowStage.report_generation: "等待训练验证结束后生成报告摘要。",
        },
        artifact_refs=[task.dataset_path] if task.dataset_path else None,
    )

    if incremental_plan is not None:
        running_statuses, running_summaries, running_artifacts = _generation_stage_statuses_for_incremental_running(
            incremental_plan
        )
        _record_stage_selection_map(
            task,
            team_access,
            stage_selection_map=stage_selection_map,
            status_by_stage=running_statuses,
            summary_by_stage=running_summaries,
            artifact_refs_by_stage=running_artifacts,
        )

    incremental_result: IncrementalRerunResult | None = None
    try:
        if incremental_plan is not None and requested_rerun_stage is not None:
            incremental_result = run_task_incrementally(
                task,
                Path(task.dataset_path),
                settings=runtime_settings,
                start_stage=requested_rerun_stage,
                time_limit=payload.time_limit,
                plan=incremental_plan,
            )
            summary = incremental_result.summary
        else:
            summary = MLZeroExecutor(runtime_settings).run(task, Path(task.dataset_path), payload.time_limit)
    except Exception as exc:  # noqa: BLE001
        task.status = TaskStatus.failed
        task.notes = str(exc)
        run_error_output_dir = exc.output_dir if isinstance(exc, (MLZeroRunError, IncrementalRerunError)) else None
        run_error_token_usage = exc.token_usage if isinstance(exc, (MLZeroRunError, IncrementalRerunError)) else None
        if run_error_output_dir:
            task.last_run_attempt = RunAttempt(
                output_dir=run_error_output_dir,
                token_usage=run_error_token_usage,
            )
            task_store.upsert_run_attempt(
                task,
                output_dir=run_error_output_dir,
                status="failed",
                token_usage=run_error_token_usage,
                notes=str(exc),
                access_token=team_access.access_token,
            )
            task_store.upsert_token_ledger(
                team_id=task.team_id,
                task_id=task.id,
                phase="mlzero",
                stage_key=requested_rerun_stage.value if requested_rerun_stage else selection.stage.value,
                source_key=run_error_output_dir,
                usage=run_error_token_usage,
                access_token=team_access.access_token,
                user_id=team_access.user.id,
                connector_id=selection.connector.id,
                connector_display_name=selection.connector.display_name,
                model_name=selection.model_name,
                calculation_method="strict_incremental_token_usage_json" if incremental_plan else "mlzero_token_usage_json",
            )
        saved_task = task_store.save_task(task, access_token=team_access.access_token)
        saved_task, _ = _apply_interaction_policies(
            saved_task,
            team_access,
            trigger_mode=InteractionTriggerMode.in_run,
            cycle_id=cycle_id,
            stage_selection_map=stage_selection_map,
        )
        run_log_excerpt = _read_run_log_excerpt(run_error_output_dir) or str(exc)
        _sync_task_human_collaboration(saved_task, team_access, stage_selection_map=stage_selection_map)
        _record_stage_selection_map(
            saved_task,
            team_access,
            stage_selection_map=stage_selection_map,
            status_by_stage={
                WorkflowStage.feature_engineering: WorkflowStageStatus.failed,
                WorkflowStage.model_selection: WorkflowStageStatus.failed,
                WorkflowStage.training_validation: WorkflowStageStatus.failed,
                WorkflowStage.report_generation: WorkflowStageStatus.pending,
            },
            summary_by_stage={
                WorkflowStage.feature_engineering: f"本次 MLZero 运行失败，代码生成或修正链路未完成：{exc}",
                WorkflowStage.model_selection: f"本次 MLZero 运行失败，未得到完整候选模型比较：{exc}",
                WorkflowStage.training_validation: f"训练或验证失败：{exc}",
                WorkflowStage.report_generation: "训练验证失败，报告暂未生成。",
            },
            artifact_refs=[run_error_output_dir] if run_error_output_dir else None,
            artifact_refs_by_stage=_collect_stage_artifacts_by_stage(run_error_output_dir),
            log_excerpt_by_stage={
                WorkflowStage.feature_engineering: run_log_excerpt,
                WorkflowStage.model_selection: run_log_excerpt,
                WorkflowStage.training_validation: run_log_excerpt,
                WorkflowStage.report_generation: run_log_excerpt,
            },
        )
        if incremental_plan is not None:
            failed_statuses, failed_summaries, failed_artifacts = _stage_records_for_incremental_failure(
                incremental_plan,
                exc,
            )
            _record_stage_selection_map(
                saved_task,
                team_access,
                stage_selection_map=stage_selection_map,
                status_by_stage=failed_statuses,
                summary_by_stage=failed_summaries,
                artifact_refs_by_stage=failed_artifacts,
                log_excerpt_by_stage={stage: run_log_excerpt for stage in failed_statuses},
            )
        _write_task_audit(
            team_access,
            action="task.run",
            task_id=saved_task.id,
            detail={
                "status": "failed",
                "detail": str(exc),
                "output_dir": run_error_output_dir,
                "model_name": selection.model_name,
                "connector_id": selection.connector.id,
                "rerun_from_stage": requested_rerun_stage.value if requested_rerun_stage else None,
                "rerun_mode": incremental_plan.mode if incremental_plan else "full_mlzero",
                "cycle_id": cycle_id,
            },
        )
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    task.status = TaskStatus.completed
    task.notes = "MLZero 运行完成。"
    task.last_run = summary
    task.last_run_attempt = RunAttempt(
        output_dir=summary.output_dir,
        token_usage=summary.token_usage,
    )
    _mark_rerun_completed(
        task,
        start_stage=requested_rerun_stage,
        mode=incremental_plan.mode if incremental_plan else "full_mlzero",
        output_dir=summary.output_dir,
    )
    if incremental_plan is not None:
        task.notes = f"Strict incremental rerun from {incremental_plan.start_stage.value} completed."
    saved_task = task_store.save_task(task, access_token=team_access.access_token)
    task_store.upsert_run_summary(saved_task, summary, access_token=team_access.access_token)
    task_store.upsert_token_ledger(
        team_id=saved_task.team_id,
        task_id=saved_task.id,
        phase="mlzero",
        stage_key=requested_rerun_stage.value if requested_rerun_stage else selection.stage.value,
        source_key=summary.output_dir,
        usage=summary.token_usage,
        access_token=team_access.access_token,
        user_id=team_access.user.id,
        connector_id=selection.connector.id,
        connector_display_name=selection.connector.display_name,
        model_name=selection.model_name,
        calculation_method="strict_incremental_token_usage_json" if incremental_plan else "mlzero_token_usage_json",
    )
    saved_task, _ = _apply_interaction_policies(
        saved_task,
        team_access,
        trigger_mode=InteractionTriggerMode.in_run,
        cycle_id=cycle_id,
        stage_selection_map=stage_selection_map,
    )
    run_log_excerpt = _read_run_log_excerpt(summary.output_dir)
    _sync_task_human_collaboration(saved_task, team_access, stage_selection_map=stage_selection_map)
    _record_stage_selection_map(
        saved_task,
        team_access,
        stage_selection_map=stage_selection_map,
        status_by_stage={
            WorkflowStage.feature_engineering: WorkflowStageStatus.completed,
            WorkflowStage.model_selection: WorkflowStageStatus.completed,
            WorkflowStage.training_validation: WorkflowStageStatus.completed,
            WorkflowStage.report_generation: WorkflowStageStatus.completed,
        },
        summary_by_stage={
            WorkflowStage.feature_engineering: "MLZero 已产出可查看的代码和中间工件。",
            WorkflowStage.model_selection: f"已解析 {len(summary.leaderboard)} 个候选模型结果，最佳模型为 {summary.best_model}。",
            WorkflowStage.training_validation: f"训练验证完成：{summary.metric_name} = {summary.metric_value:.6g}。",
            WorkflowStage.report_generation: "模型报告摘要已可基于真实任务、数据集画像和运行产物生成。",
        },
        artifact_refs=[summary.output_dir],
        artifact_refs_by_stage=_collect_stage_artifacts_by_stage(summary.output_dir),
        log_excerpt_by_stage={
            WorkflowStage.feature_engineering: run_log_excerpt,
            WorkflowStage.model_selection: run_log_excerpt,
            WorkflowStage.training_validation: run_log_excerpt,
            WorkflowStage.report_generation: run_log_excerpt,
        },
    )
    if incremental_result is not None:
        completed_statuses, completed_summaries, completed_artifacts = _stage_records_for_incremental_success(
            incremental_result
        )
        _record_stage_selection_map(
            saved_task,
            team_access,
            stage_selection_map=stage_selection_map,
            status_by_stage=completed_statuses,
            summary_by_stage=completed_summaries,
            artifact_refs_by_stage=completed_artifacts,
            log_excerpt_by_stage={stage: run_log_excerpt for stage in completed_statuses},
        )
    _write_task_audit(
        team_access,
        action="task.run",
        task_id=saved_task.id,
        detail={
            "status": "completed",
            "output_dir": summary.output_dir,
            "best_model": summary.best_model,
            "metric_name": summary.metric_name,
            "metric_value": summary.metric_value,
            "model_name": selection.model_name,
            "connector_id": selection.connector.id,
            "rerun_from_stage": requested_rerun_stage.value if requested_rerun_stage else None,
            "rerun_mode": incremental_plan.mode if incremental_plan else "full_mlzero",
            "cycle_id": cycle_id,
        },
    )
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

    _write_task_audit(
        team_access,
        action="task.delete",
        task_id=task_id,
        detail={"name": task.name, "status": task.status.value},
    )
    return TaskDeleteResponse(deleted=True, task_id=task_id)
