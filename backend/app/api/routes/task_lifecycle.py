from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status

from backend.app.core.supabase_auth import TeamAccessContext, require_team_access
from backend.app.models.task import (
    TaskCreateRequest,
    TaskDeleteResponse,
    TaskInteractionPolicyRecord,
    TaskListResponse,
    TaskRecord,
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
from backend.app.services.task_agent_loop import initialize_agent_loop_for_upload
from backend.app.services.task_semantics import apply_human_semantic_update
from backend.app.api.routes.task_route_common import (
    CSV_UPLOAD_CHUNK_BYTES,
    MAX_CSV_UPLOAD_BYTES,
    _build_runtime_context,
    _build_stage_selection_map,
    _record_stage_selection_map,
    _record_workflow_stage,
    _run_ai_analysis,
    _sync_task_human_collaboration,
    _validate_csv_sample,
    _validate_interaction_policy_assignees,
    _validate_task_stage_routing_overrides,
    _validate_upload_content_type,
    _validate_upload_filename,
    _write_task_audit,
    get_task_store,
)
from backend.app.api.routes.task_runtime import run_task

router = APIRouter(tags=["task-lifecycle"])

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
            WorkflowStage.feature_engineering: "任务语义已人工修正，等待下一次 MLZero 运行重新生成特征与训练代码。",
            WorkflowStage.model_selection: "任务语义已人工修正，等待下一次 MLZero 运行重新选择候选模型。",
            WorkflowStage.training_validation: "任务语义已人工修正，等待下一次 MLZero 运行重新训练验证。",
            WorkflowStage.report_generation: "任务语义已人工修正，等待新的真实运行结果后生成报告。",
        },
        artifact_refs=[saved_task.dataset_path] if saved_task.dataset_path else None,
    )
    _write_task_audit(
        team_access,
        action="task.semantic_analysis.update",
        task_id=saved_task.id,
        detail={
            "label_column": saved_task.label_column,
            "problem_type": saved_task.problem_type,
            "metric_name": payload.metric_name.strip().lower(),
            "cleared_last_run": True,
        },
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
    initialize_agent_loop_for_upload(task)
    task.notes = "CSV 已上传并完成基础画像，系统会根据当前阶段路由自动执行 AI 解析并启动 MLZero 工作流。"
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
            "auto_run": auto_run,
            "time_limit": time_limit,
        },
    )

    analyzed_task = _run_ai_analysis(task, task_store, team_access, fail_on_error=True)
    if not auto_run:
        return analyzed_task
    return run_task(
        analyzed_task.id,
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

@router.delete("/{task_id}", response_model=TaskDeleteResponse)
def delete_task(task_id: str, team_access: TeamAccessContext = Depends(require_team_access)) -> TaskDeleteResponse:
    task_store = get_task_store()
    task = task_store.get_task(team_access.team_id, task_id, access_token=team_access.access_token)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    if task.status == TaskStatus.running and "Agent 自动修复受阻" not in (task.notes or ""):
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
