from __future__ import annotations

from backend.app.core.config import get_settings
from backend.app.core.supabase_auth import TeamAccessContext
from backend.app.models.task import (
    TaskRecord,
    TaskStatus,
    WorkflowStage,
    WorkflowStageStatus,
)
from backend.app.services.codex_backend import codex_workspace_plan_path
from backend.app.services.task_run_artifacts import (
    collect_stage_artifacts_by_stage,
    read_run_log_excerpt,
)
from backend.app.services.task_codex_human_requests import ensure_codex_improvement_request, ensure_codex_plan_request
from backend.app.services.task_codex_improvement_review import (
    codex_stage_workspace_path,
    codex_workspace_improvement_plan_path,
    has_codex_improvement_review,
)
from backend.app.services.task_runtime_codex_stage_projection import (
    CodexStageProjection,
    codex_improvement_gate_stage_projection,
    codex_plan_gate_stage_projection,
    codex_running_stage_projection,
    codex_user_paused_stage_projection,
    completed_codex_stage_projection,
)
from backend.app.services.task_workflow_tracking import _record_stage_selection_map


def record_codex_running_stages(task: TaskRecord, team_access: TeamAccessContext) -> None:
    _record_codex_stage_projection(task, team_access, codex_running_stage_projection(task.dataset_path))


def record_user_paused_stages(task: TaskRecord, team_access: TeamAccessContext) -> None:
    workspace_path = task.codex_workspace_path or (task.last_run_attempt.output_dir if task.last_run_attempt else None)
    _record_codex_stage_projection(task, team_access, codex_user_paused_stage_projection(workspace_path))


def record_codex_status_stages(task: TaskRecord, team_access: TeamAccessContext, artifacts: dict) -> None:
    workspace_path = codex_stage_workspace_path(task)
    plan_path = codex_workspace_plan_path(task, get_settings())
    improvement_plan_path = codex_workspace_improvement_plan_path(task, artifacts)
    if is_human_waiting_task(task) and task.codex_status == "interrupted":
        record_user_paused_stages(task, team_access)
        return
    if is_human_waiting_task(task) and has_codex_improvement_review(artifacts):
        record_codex_improvement_gate_stages(
            task,
            team_access,
            artifacts=artifacts,
            workspace_path=workspace_path,
            improvement_plan_path=improvement_plan_path,
        )
        return
    if is_human_waiting_task(task):
        record_codex_plan_gate_stages(task, team_access, workspace_path=workspace_path, plan_path=plan_path)
        return
    if task.status == TaskStatus.completed and task.last_run:
        record_completed_codex_stages(task, team_access, workspace_path=workspace_path)


def is_human_waiting_task(task: TaskRecord) -> bool:
    return task.status in {TaskStatus.paused_for_review, TaskStatus.waiting_human}


def _record_codex_stage_selection_map(
    task: TaskRecord,
    team_access: TeamAccessContext,
    *,
    status_by_stage: dict[WorkflowStage, WorkflowStageStatus],
    summary_by_stage: dict[WorkflowStage, str],
    artifact_refs: list[str] | dict | None = None,
    artifact_refs_by_stage: dict[WorkflowStage, list[str] | dict] | None = None,
    log_excerpt_by_stage: dict[WorkflowStage, str] | None = None,
) -> None:
    try:
        _record_stage_selection_map(
            task,
            team_access,
            stage_selection_map={},
            status_by_stage=status_by_stage,
            summary_by_stage=summary_by_stage,
            artifact_refs=artifact_refs,
            artifact_refs_by_stage=artifact_refs_by_stage,
            log_excerpt_by_stage=log_excerpt_by_stage,
        )
    except ConnectionError:
        return


def _record_codex_stage_projection(
    task: TaskRecord,
    team_access: TeamAccessContext,
    projection: CodexStageProjection,
) -> None:
    _record_codex_stage_selection_map(
        task,
        team_access,
        status_by_stage=projection.status_by_stage,
        summary_by_stage=projection.summary_by_stage,
        artifact_refs=projection.artifact_refs,
        artifact_refs_by_stage=projection.artifact_refs_by_stage,
        log_excerpt_by_stage=projection.log_excerpt_by_stage,
    )


def record_codex_plan_gate_stages(
    task: TaskRecord,
    team_access: TeamAccessContext,
    *,
    workspace_path: str | None,
    plan_path: str | None,
) -> None:
    try:
        ensure_codex_plan_request(task, team_access, plan_path=plan_path)
    except ConnectionError:
        return
    _record_codex_stage_projection(task, team_access, codex_plan_gate_stage_projection(workspace_path, plan_path))


def record_codex_improvement_gate_stages(
    task: TaskRecord,
    team_access: TeamAccessContext,
    *,
    artifacts: dict,
    workspace_path: str | None,
    improvement_plan_path: str | None,
) -> None:
    try:
        ensure_codex_improvement_request(
            task,
            team_access,
            artifacts=artifacts,
            improvement_plan_path=improvement_plan_path,
        )
    except ConnectionError:
        return
    _record_codex_stage_projection(
        task,
        team_access,
        codex_improvement_gate_stage_projection(workspace_path, improvement_plan_path),
    )


def record_completed_codex_stages(
    task: TaskRecord,
    team_access: TeamAccessContext,
    *,
    workspace_path: str | None,
) -> None:
    if not task.last_run:
        return
    _record_codex_stage_projection(
        task,
        team_access,
        completed_codex_stage_projection(
            task.last_run,
            workspace_path=workspace_path,
            artifact_refs_by_stage=collect_stage_artifacts_by_stage(workspace_path),
            log_excerpt=read_run_log_excerpt(workspace_path),
        ),
    )
