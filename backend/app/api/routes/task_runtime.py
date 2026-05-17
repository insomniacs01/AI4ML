from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.app.core.config import get_settings
from backend.app.core.supabase_auth import TeamAccessContext, require_team_access
from backend.app.models.task import (
    InteractionTriggerMode,
    RunAttempt,
    TaskInteractiveChatRequest,
    TaskInteractiveChatResponse,
    TaskRecord,
    TaskRunProgressResponse,
    TaskRunRequest,
    TaskStatus,
    TokenUsageResponse,
    WorkflowStage,
    WorkflowStageStatus,
)
from backend.app.services.executors.mlzero_executor import MLZeroExecutor
from backend.app.services.task_agent_loop import refresh_agent_loop_after_run, refresh_agent_loop_after_run_failure
from backend.app.services.task_ai_conversations import build_task_ai_conversations
from backend.app.services.task_chat import send_task_chat_message
from backend.app.services.task_incremental_rerun import (
    IncrementalRerunPlan,
    IncrementalRerunPreconditionError,
    IncrementalRerunResult,
    build_incremental_rerun_plan,
    is_strict_incremental_stage,
    run_task_incrementally,
)
from backend.app.services.task_run_progress import build_task_run_progress
from backend.app.services.token_usage import read_token_usage
from backend.app.api.routes.task_route_common import (
    _apply_interaction_policies,
    _assert_quota_allows_action,
    _build_runtime_context,
    _build_runtime_settings_for_selection,
    _build_stage_selection_map,
    _collect_stage_artifacts_by_stage,
    _diagnose_run_failure,
    _generation_stage_statuses_for_incremental_running,
    _is_recoverable_run_exception,
    _mark_rerun_completed,
    _next_policy_cycle,
    _read_run_log_excerpt,
    _record_stage_selection_map,
    _repair_stale_running_task,
    _resolve_preferred_selection,
    _resolve_requested_rerun_stage,
    _run_failure_log_excerpt,
    _run_ai_analysis,
    _run_exception_output_dir,
    _run_exception_retry_stage,
    _run_exception_token_usage,
    _stage_records_for_incremental_failure,
    _stage_records_for_incremental_success,
    _stage_records_for_recoverable_run_block,
    _sync_task_human_collaboration,
    _write_task_audit,
    get_task_human_collaboration_service,
    get_task_store,
)

router = APIRouter(tags=["task-runtime"])

@router.get("/{task_id}/run-progress", response_model=TaskRunProgressResponse)
def get_task_run_progress(
    task_id: str,
    repair_stale: bool = Query(default=True),
    team_access: TeamAccessContext = Depends(require_team_access),
) -> TaskRunProgressResponse:
    task = get_task_store().get_task(team_access.team_id, task_id, access_token=team_access.access_token)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    progress = build_task_run_progress(task, get_settings())
    if repair_stale:
        progress = _repair_stale_running_task(task, team_access, progress)
    return progress


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
        calculation_method=chat_result.token_usage_calculation_method or "provider_reported_usage",
    )
    return TaskInteractiveChatResponse(
        task=saved_task,
        conversation=build_task_ai_conversations(saved_task),
    )

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
        run_error_output_dir = _run_exception_output_dir(exc)
        run_error_token_usage = _run_exception_token_usage(exc)
        run_error_recoverable = _is_recoverable_run_exception(exc)
        if run_error_recoverable:
            retry_stage = _run_exception_retry_stage(exc)
            if retry_stage is None:
                retry_stage = requested_rerun_stage or WorkflowStage.feature_engineering
            diagnosis = _diagnose_run_failure(
                exc,
                retry_stage=retry_stage,
                output_dir=run_error_output_dir,
                recoverable=True,
            )
            run_log_excerpt = _run_failure_log_excerpt(diagnosis)
            task.status = TaskStatus.running
            task.notes = run_log_excerpt
            if run_error_output_dir:
                task.last_run_attempt = RunAttempt(
                    output_dir=run_error_output_dir,
                    token_usage=run_error_token_usage,
                    diagnosis=diagnosis.get("diagnosis"),
                    diagnosis_detail=diagnosis.get("detail"),
                    error_artifact_path=diagnosis.get("error_artifact_path"),
                )
                task_store.upsert_run_attempt(
                    task,
                    output_dir=run_error_output_dir,
                    status="running",
                    token_usage=run_error_token_usage,
                    notes=task.notes,
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
            refresh_agent_loop_after_run_failure(
                task,
                error_summary=run_log_excerpt,
                output_dir=run_error_output_dir,
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
            recoverable_statuses, recoverable_summaries = _stage_records_for_recoverable_run_block(
                retry_stage,
                exc,
            )
            for stage, stage_status in recoverable_statuses.items():
                if stage_status == WorkflowStageStatus.running:
                    recoverable_summaries[stage] = run_log_excerpt
            _record_stage_selection_map(
                saved_task,
                team_access,
                stage_selection_map=stage_selection_map,
                status_by_stage=recoverable_statuses,
                summary_by_stage=recoverable_summaries,
                artifact_refs=[run_error_output_dir] if run_error_output_dir else None,
                artifact_refs_by_stage=_collect_stage_artifacts_by_stage(run_error_output_dir),
                log_excerpt_by_stage={stage: run_log_excerpt for stage in recoverable_statuses},
            )
            _write_task_audit(
                team_access,
                action="task.run",
                task_id=saved_task.id,
                detail={
                    "status": "repair_blocked",
                    "diagnosis": diagnosis.get("diagnosis"),
                    "diagnosis_detail": diagnosis.get("detail"),
                    "error_artifact_path": diagnosis.get("error_artifact_path"),
                    "retry_stage": retry_stage.value if retry_stage else None,
                    "output_dir": run_error_output_dir,
                    "model_name": selection.model_name,
                    "connector_id": selection.connector.id,
                    "rerun_from_stage": requested_rerun_stage.value if requested_rerun_stage else None,
                    "rerun_mode": incremental_plan.mode if incremental_plan else "full_mlzero",
                    "cycle_id": cycle_id,
                },
            )
            return saved_task

        diagnosis = _diagnose_run_failure(
            exc,
            retry_stage=requested_rerun_stage or WorkflowStage.training_validation,
            output_dir=run_error_output_dir,
            recoverable=False,
        )
        run_log_excerpt = _run_failure_log_excerpt(diagnosis)
        task.status = TaskStatus.failed
        task.notes = run_log_excerpt
        if run_error_output_dir:
            task.last_run_attempt = RunAttempt(
                output_dir=run_error_output_dir,
                token_usage=run_error_token_usage,
                diagnosis=diagnosis.get("diagnosis"),
                diagnosis_detail=diagnosis.get("detail"),
                error_artifact_path=diagnosis.get("error_artifact_path"),
            )
            task_store.upsert_run_attempt(
                task,
                output_dir=run_error_output_dir,
                status="failed",
                token_usage=run_error_token_usage,
                notes=task.notes,
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
        refresh_agent_loop_after_run_failure(
            task,
            error_summary=run_log_excerpt,
            output_dir=run_error_output_dir,
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
                WorkflowStage.feature_engineering: run_log_excerpt,
                WorkflowStage.model_selection: run_log_excerpt,
                WorkflowStage.training_validation: run_log_excerpt,
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
            failed_summaries = {stage: run_log_excerpt for stage in failed_summaries}
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
                "diagnosis": diagnosis.get("diagnosis"),
                "diagnosis_detail": diagnosis.get("detail"),
                "error_artifact_path": diagnosis.get("error_artifact_path"),
                "output_dir": run_error_output_dir,
                "model_name": selection.model_name,
                "connector_id": selection.connector.id,
                "rerun_from_stage": requested_rerun_stage.value if requested_rerun_stage else None,
                "rerun_mode": incremental_plan.mode if incremental_plan else "full_mlzero",
                "cycle_id": cycle_id,
            },
        )
        return saved_task

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
    refresh_agent_loop_after_run(task)
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
            WorkflowStage.report_generation: "模型报告摘要已可基于真实任务、数据集画像和运行结果生成。",
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
