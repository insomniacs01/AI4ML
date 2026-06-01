from __future__ import annotations

from pydantic import BaseModel
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status

from backend.app.core.config import get_settings
from backend.app.core.supabase_auth import TeamAccessContext, require_team_access
from backend.app.models.task import (
    HumanInteractionRequestStatus,
    TaskCreateRequest,
    TaskDeleteResponse,
    TaskInteractionPolicyRecord,
    TaskListResponse,
    TaskRecord,
    TaskRuntimeSnapshotResponse,
    TaskRunRequest,
    TaskSemanticUpdateRequest,
    TaskStageRoutingRecord,
    TaskStatus,
    TaskWorkflowConfigUpdateRequest,
    WorkflowStage,
    WorkflowStageStatus,
    normalize_workflow_stage,
)
from backend.app.services.dataset_profile import build_dataset_profile, dataset_profile_to_plain
from backend.app.services.task_codex_sync import sync_codex_task_state
from backend.app.services.task_agent_loop import initialize_agent_loop_for_upload
from backend.app.services.task_semantics import apply_human_semantic_update
from backend.app.services.service_registry import get_task_store
from backend.app.services.task_routing import (
    _build_runtime_context,
    _build_stage_selection_map,
    _validate_task_stage_routing_overrides,
)
from backend.app.services.platform_limits import PlatformLimitError, assert_user_can_create_task
from backend.app.services.task_human_policy import _validate_interaction_policy_assignees
from backend.app.services.task_runtime_snapshot import (
    TaskRuntimeSnapshotNotFound,
    TaskRuntimeSnapshotSyncError,
    build_task_runtime_snapshot_response,
)
from backend.app.services.task_uploads import (
    CSV_UPLOAD_CHUNK_BYTES,
    MAX_DATASET_UPLOAD_BYTES,
    is_csv_upload_filename as _is_csv_upload_filename,
    validate_csv_sample as _validate_csv_sample,
    validate_upload_content_type as _validate_upload_content_type,
    validate_upload_filename as _validate_upload_filename,
)
from backend.app.services.task_targets import split_target_columns, target_columns_from_requirements
from backend.app.services.task_workflow_tracking import (
    _record_stage_selection_map,
    _record_workflow_stage,
    _sync_task_human_collaboration,
)
from backend.app.api.routes.task_runtime import run_task

router = APIRouter(tags=["task-lifecycle"])


class TaskCacheWarmupResponse(BaseModel):
    warmed: bool
    task_count: int = 0
    detail_task_id: str | None = None


def _raise_task_store_http_error(exc: RuntimeError | PermissionError | ConnectionError) -> None:
    if isinstance(exc, RuntimeError):
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    if isinstance(exc, PermissionError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


def _enum_value(value: object) -> str:
    return value.value if hasattr(value, "value") else str(value)

@router.post("/cache/warmup", response_model=TaskCacheWarmupResponse)
def warmup_task_cache(team_access: TeamAccessContext = Depends(require_team_access)) -> TaskCacheWarmupResponse:
    try:
        task_store = get_task_store()
        tasks = task_store.list_tasks(
            team_access.team_id,
            access_token=team_access.access_token,
            prefer_cache=False,
        )
        detail_task_id = tasks[0].id if tasks else None
        if detail_task_id:
            task_store.get_task(
                team_access.team_id,
                detail_task_id,
                access_token=team_access.access_token,
                prefer_cache=False,
            )
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        _raise_task_store_http_error(exc)
    return TaskCacheWarmupResponse(warmed=True, task_count=len(tasks), detail_task_id=detail_task_id)


@router.get("", response_model=TaskListResponse)
def list_tasks(team_access: TeamAccessContext = Depends(require_team_access)) -> TaskListResponse:
    try:
        task_store = get_task_store()
        items = task_store.list_tasks(
            team_access.team_id,
            access_token=team_access.access_token,
            allow_stale_cache=True,
        )
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        _raise_task_store_http_error(exc)
    return TaskListResponse(items=items)


@router.post("", response_model=TaskRecord, status_code=status.HTTP_201_CREATED)
def create_task(
    payload: TaskCreateRequest,
    team_access: TeamAccessContext = Depends(require_team_access),
) -> TaskRecord:
    _validate_task_stage_routing_overrides(payload.stage_routing)
    _validate_interaction_policy_assignees(payload.interaction_policies, team_access)
    task_store = get_task_store()
    try:
        tasks = task_store.list_tasks(
            team_access.team_id,
            access_token=team_access.access_token,
            lightweight=True,
            prefer_cache=False,
        )
        assert_user_can_create_task(get_settings(), tasks=tasks, user_id=team_access.user.id)
    except PlatformLimitError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        _raise_task_store_http_error(exc)

    task = task_store.create_task(
        payload,
        team_id=team_access.team_id,
        created_by=team_access.user.id,
        access_token=team_access.access_token,
    )
    _sync_task_human_collaboration(task, team_access, stage_selection_map={})
    return task


@router.get("/{task_id}", response_model=TaskRecord)
def get_task(task_id: str, team_access: TeamAccessContext = Depends(require_team_access)) -> TaskRecord:
    try:
        task = get_task_store().get_task(
            team_access.team_id,
            task_id,
            access_token=team_access.access_token,
            allow_stale_cache=True,
        )
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        _raise_task_store_http_error(exc)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    task.executor_type = "codex"
    task, _artifacts = sync_codex_task_state(
        task,
        get_settings(),
        task_store=get_task_store(),
        access_token=team_access.access_token,
        fail_on_error=False,
    )
    return task


@router.get("/{task_id}/runtime-snapshot", response_model=TaskRuntimeSnapshotResponse)
def get_task_runtime_snapshot(
    task_id: str,
    sync: bool = Query(True),
    team_access: TeamAccessContext = Depends(require_team_access),
) -> TaskRuntimeSnapshotResponse:
    try:
        return build_task_runtime_snapshot_response(task_id, team_access, sync_runtime=sync)
    except TaskRuntimeSnapshotNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except TaskRuntimeSnapshotSyncError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except (RuntimeError, PermissionError, ConnectionError) as exc:
        _raise_task_store_http_error(exc)

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
    return saved_task


@router.put("/{task_id}/semantic-analysis", response_model=TaskRecord)
def update_task_semantic_analysis(
    task_id: str,
    payload: TaskSemanticUpdateRequest,
    team_access: TeamAccessContext = Depends(require_team_access),
) -> TaskRecord:
    task_store = get_task_store()
    task = task_store.get_task(team_access.team_id, task_id, access_token=team_access.access_token)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")

    try:
        updated_task = apply_human_semantic_update(
            task,
            payload,
            corrected_by=team_access.user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    saved_task = task_store.save_task(updated_task, access_token=team_access.access_token)
    runtime_context = _build_runtime_context(team_access)
    stage_selection_map = _build_stage_selection_map(saved_task, team_access, runtime_context)
    _sync_task_human_collaboration(saved_task, team_access, stage_selection_map=stage_selection_map)
    _record_workflow_stage(
        saved_task,
        team_access,
        stage=WorkflowStage.data_analysis,
        stage_status=WorkflowStageStatus.completed,
        summary=(
            f"用户已人工修正任务语义：目标列 {saved_task.label_column}，"
            f"任务类型 {saved_task.problem_type}，指标 {payload.metric_name.strip().lower()}。"
        ),
        selection=stage_selection_map.get(WorkflowStage.data_analysis.value),
        artifact_refs=[saved_task.dataset_path] if saved_task.dataset_path else None,
        log_excerpt=payload.correction_note,
    )
    _record_stage_selection_map(
        saved_task,
        team_access,
        stage_selection_map=stage_selection_map,
        status_by_stage={
            WorkflowStage.feature_engineering: WorkflowStageStatus.pending,
            WorkflowStage.model_selection: WorkflowStageStatus.pending,
            WorkflowStage.training_validation: WorkflowStageStatus.pending,
            WorkflowStage.report_generation: WorkflowStageStatus.pending,
        },
        summary_by_stage={
            WorkflowStage.feature_engineering: "任务语义已人工修正，等待下一次 Codex 运行重新生成特征与训练代码。",
            WorkflowStage.model_selection: "任务语义已人工修正，等待下一次 Codex 运行重新选择候选模型。",
            WorkflowStage.training_validation: "任务语义已人工修正，等待下一次 Codex 运行重新训练验证。",
            WorkflowStage.report_generation: "任务语义已人工修正，等待新的真实运行结果后生成报告。",
        },
        artifact_refs=[saved_task.dataset_path] if saved_task.dataset_path else None,
    )
    return saved_task

@router.post("/{task_id}/dataset", response_model=TaskRecord)
async def upload_dataset(
    task_id: str,
    auto_run: bool = Query(default=True),
    time_limit: int | None = Query(default=None, ge=5, le=300),
    file: UploadFile = File(...),
    team_access: TeamAccessContext = Depends(require_team_access),
) -> TaskRecord:
    task_store = get_task_store()
    task = task_store.get_task(team_access.team_id, task_id, access_token=team_access.access_token)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    filename = _validate_upload_filename(file.filename or "")
    _validate_upload_content_type(file.content_type)

    dataset_dir = task_store.clear_dataset_upload_dir(team_access.team_id, task_id)
    uploaded_file_path = task_store.dataset_upload_path(team_access.team_id, task_id, filename)
    size_bytes = 0
    sample = bytearray()
    dataset_profile = None
    profile_error = ""
    try:
        with uploaded_file_path.open("wb") as handle:
            while True:
                chunk = await file.read(CSV_UPLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                size_bytes += len(chunk)
                if size_bytes > MAX_DATASET_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"dataset upload exceeds {MAX_DATASET_UPLOAD_BYTES // (1024 * 1024)} MB limit",
                    )
                if len(sample) < CSV_UPLOAD_CHUNK_BYTES:
                    sample.extend(chunk[: CSV_UPLOAD_CHUNK_BYTES - len(sample)])
                handle.write(chunk)
        if size_bytes == 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="uploaded dataset file is empty")
        if _is_csv_upload_filename(filename):
            try:
                _validate_csv_sample(bytes(sample))
                csv_profile = build_dataset_profile(
                    uploaded_file_path,
                    filename=filename,
                    target_column=None,
                )
                if csv_profile.column_count > 0:
                    dataset_profile = csv_profile
                else:
                    profile_error = "uploaded CSV does not contain a header row"
            except HTTPException as exc:
                profile_error = str(exc.detail)
    except HTTPException:
        if uploaded_file_path.exists():
            uploaded_file_path.unlink()
        raise
    except OSError as exc:
        if uploaded_file_path.exists():
            uploaded_file_path.unlink()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"failed to save uploaded dataset: {exc}") from exc

    task.dataset_filename = filename
    task.dataset_path = str(dataset_dir)
    task.dataset_profile = dataset_profile
    task.status = TaskStatus.uploaded
    task.executor_type = "codex"
    task.codex_workspace_path = None
    task.codex_session_id = None
    task.codex_thread_id = None
    task.codex_status = None
    task.codex_started_at = None
    task.codex_finished_at = None
    task.last_run = None
    task.last_run_attempt = None
    task.analysis_token_usage = None
    structured_requirements = (
        dict(task.structured_requirements)
        if isinstance(task.structured_requirements, dict)
        else {}
    )
    structured_requirements["dataset_input"] = {
        "path": str(dataset_dir),
        "path_type": "directory",
        "files": [
            {
                "filename": filename,
                "path": str(uploaded_file_path),
                "size_bytes": size_bytes,
                "content_type": file.content_type,
            }
        ],
    }
    structured_requirements["dataset_files"] = structured_requirements["dataset_input"]["files"]
    if dataset_profile is not None:
        structured_requirements["dataset_profile"] = dataset_profile_to_plain(dataset_profile)
        structured_requirements.pop("dataset_profile_error", None)
    else:
        structured_requirements.pop("dataset_profile", None)
        if profile_error:
            structured_requirements["dataset_profile_error"] = profile_error
    target_columns = target_columns_from_requirements(structured_requirements) or split_target_columns(task.label_column)
    if target_columns:
        structured_requirements["target_hint"] = structured_requirements.get("target_hint") or task.label_column
        structured_requirements["target_columns_hint"] = target_columns
        structured_requirements["target_definition"] = {
            "target_mode": "multi_target" if len(target_columns) > 1 else "single_target",
            "target_columns": target_columns,
            "source": "user_input",
        }
    task.structured_requirements = structured_requirements
    initialize_agent_loop_for_upload(task)
    task.notes = "数据文件已上传到任务数据目录，Codex 将读取目录内容并生成建模计划。"
    task = task_store.save_task(task, access_token=team_access.access_token)
    _record_workflow_stage(
        task,
        team_access,
        stage=WorkflowStage.data_analysis,
        stage_status=WorkflowStageStatus.completed,
        summary=(
            f"数据文件已上传：{filename}，大小 {size_bytes} 字节。"
            + (
                f" CSV 画像：{dataset_profile.row_count} 行、{dataset_profile.column_count} 列。"
                if dataset_profile is not None
                else " 数据结构将由 Codex 在任务工作区内解析。"
            )
        ),
        artifact_refs=[str(uploaded_file_path), str(dataset_dir)],
        log_excerpt=(
            f"filename={filename}; size_bytes={size_bytes}; "
            + (
                f"columns={', '.join(column.name for column in dataset_profile.columns[:12])}"
                if dataset_profile is not None
                else f"dataset_dir={dataset_dir}"
            )
        ),
    )

    if not auto_run:
        return task
    return run_task(
        task.id,
        TaskRunRequest(time_limit=time_limit),
        team_access,
    )


@router.post("/{task_id}/analyze", response_model=TaskRecord)
def analyze_task(
    task_id: str,
    team_access: TeamAccessContext = Depends(require_team_access),
) -> TaskRecord:
    task_store = get_task_store()
    task = task_store.get_task(team_access.team_id, task_id, access_token=team_access.access_token)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    task.executor_type = "codex"
    task.status = TaskStatus.planning if task.dataset_path else TaskStatus.draft
    task.notes = "Codex 会在运行时读取数据并生成计划；当前不再调用独立语义解析。"
    return task_store.save_task(task, access_token=team_access.access_token)

@router.delete("/{task_id}", response_model=TaskDeleteResponse)
def delete_task(task_id: str, team_access: TeamAccessContext = Depends(require_team_access)) -> TaskDeleteResponse:
    task_store = get_task_store()
    task = task_store.get_task(team_access.team_id, task_id, access_token=team_access.access_token)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    if task.status == TaskStatus.running and "Agent 自动修复受阻" not in (task.notes or ""):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="任务仍在运行中，请先取消任务后再删除。",
        )

    deleted = task_store.delete_task(team_access.team_id, task_id, access_token=team_access.access_token)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")

    return TaskDeleteResponse(deleted=True, task_id=task_id)
