from __future__ import annotations

import logging
from typing import Any, Literal

from backend.app.core.config import get_settings
from backend.app.core.supabase_auth import TeamAccessContext
from backend.app.models.task import (
    RunAttempt,
    TaskRecord,
    TaskRuntimeSnapshotResponse,
    TaskRuntimeSummaryRecord,
    TaskStatus,
)
from backend.app.services.codex_backend import (
    build_codex_run_progress,
    codex_plan_text,
    read_codex_artifacts,
)
from backend.app.services.codex_common import read_json
from backend.app.services.codex_metrics import build_codex_run_summary
from backend.app.services.codex_overview import build_codex_overview_from_artifacts
from backend.app.services.codex_workspace_artifacts import read_codex_workspace_overview_artifacts
from backend.app.services.codex_workspace_resolution import resolve_known_codex_workspace_path
from backend.app.services.service_registry import get_task_store
from backend.app.services.task_codex_runtime_activity import safe_reconcile_codex_runtime_activity
from backend.app.services.task_codex_runtime_snapshot_sync import (
    TaskRuntimeSnapshotSyncError,
    sync_codex_runtime_snapshot,
)
from backend.app.services.task_codex_sync import is_codex_task
from backend.app.services.task_human_snapshot import count_open_human_requests, visible_human_requests_for_actor
from backend.app.services.task_runtime_snapshot_payload import build_task_run_payload
from backend.app.services.task_runtime_steps import build_runtime_steps, progress_from_steps


logger = logging.getLogger(__name__)


class TaskRuntimeSnapshotNotFound(LookupError):
    pass


def build_task_runtime_snapshot_response(
    task_id: str,
    team_access: TeamAccessContext,
    *,
    sync_runtime: bool = True,
    task_detail: Literal["full", "summary"] = "full",
) -> TaskRuntimeSnapshotResponse:
    task_store = get_task_store()
    task = task_store.get_task(
        team_access.team_id,
        task_id,
        access_token=team_access.access_token,
        prefer_cache=not sync_runtime,
        allow_stale_cache=not sync_runtime,
    )
    if task is None:
        raise TaskRuntimeSnapshotNotFound("task not found")

    settings = get_settings()
    should_sync_codex = is_codex_task(task, settings)
    if should_sync_codex:
        progress_response = None
        codex_overview = {}
        codex_artifacts = {}
        if task.status == TaskStatus.completed:
            codex_artifacts = _safe_read_known_codex_summary_artifacts(task, settings)
            if codex_artifacts:
                task = _safe_backfill_completed_codex_summary(
                    task_store,
                    task,
                    team_access,
                    codex_artifacts,
                )
                codex_overview = build_codex_overview_from_artifacts(codex_artifacts)
        elif sync_runtime:
            try:
                task, progress_response, codex_overview, codex_artifacts = sync_codex_runtime_snapshot(
                    task_store,
                    task,
                    team_access,
                    settings,
                )
            except TaskRuntimeSnapshotSyncError as exc:
                logger.warning(
                    "Codex runtime snapshot sync failed for task %s; returning cached runtime state: %s",
                    task.id,
                    exc,
                )
            task = safe_reconcile_codex_runtime_activity(task_store, task, team_access, settings)
            progress_response = _safe_build_codex_run_progress(task, settings) or progress_response
            if not codex_artifacts:
                codex_artifacts = _safe_read_codex_artifacts(task, settings)
    else:
        progress_response = None
        codex_overview = {}
        codex_artifacts = {}

    stage_records = [] if should_sync_codex else _list_stage_records_for_snapshot(task_store, task_id, team_access)

    steps = build_runtime_steps(task, stage_records, progress=progress_response)
    progress = progress_from_steps(task, steps)
    if should_sync_codex and task.status == TaskStatus.completed and not codex_overview:
        codex_overview = _completed_task_fallback_overview(task)
    plan_text = (
        _safe_codex_plan_text(task, settings)
        if should_sync_codex and sync_runtime and task.status != TaskStatus.completed
        else ""
    )
    task_run = build_task_run_payload(
        task,
        steps,
        progress_response,
        progress,
        codex_overview,
        should_sync_codex=should_sync_codex,
        codex_plan=plan_text,
        codex_artifacts=codex_artifacts,
    )
    task_run.update(_human_request_counts(task_store, task, team_access))
    return TaskRuntimeSnapshotResponse(
        task=_task_payload(task, task_detail=task_detail),
        task_run=task_run,
    )


def _safe_build_codex_run_progress(task: TaskRecord, settings: Any) -> Any | None:
    try:
        return build_codex_run_progress(task, settings)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not build Codex runtime progress for task %s: %s", task.id, exc)
        return None


def _safe_codex_plan_text(task: TaskRecord, settings: Any) -> str:
    try:
        return codex_plan_text(task, settings)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read Codex plan text for task %s: %s", task.id, exc)
        return ""


def _safe_read_codex_artifacts(task: TaskRecord, settings: Any) -> dict[str, Any]:
    try:
        artifacts = read_codex_artifacts(task, settings)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read Codex artifacts for task %s: %s", task.id, exc)
        return {}
    return artifacts if isinstance(artifacts, dict) else {}


def _safe_read_known_codex_summary_artifacts(task: TaskRecord, settings: Any) -> dict[str, Any]:
    try:
        workspace = resolve_known_codex_workspace_path(task, settings)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not resolve known Codex workspace for task %s: %s", task.id, exc)
        return {}
    if workspace is None:
        return {}
    try:
        artifacts = read_codex_workspace_overview_artifacts(workspace)
        token_usage = read_json(workspace / "output" / "token_usage.json")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read Codex summary artifacts for task %s: %s", task.id, exc)
        return {}
    if isinstance(token_usage, dict):
        artifacts["token_usage"] = token_usage
    return artifacts


def _safe_backfill_completed_codex_summary(
    task_store: Any,
    task: TaskRecord,
    team_access: TeamAccessContext,
    artifacts: dict[str, Any],
) -> TaskRecord:
    if task.last_run is not None:
        return task
    metrics = artifacts.get("metrics") if isinstance(artifacts.get("metrics"), dict) else {}
    overview = artifacts.get("overview") if isinstance(artifacts.get("overview"), dict) else None
    workspace = artifacts.get("workspace") if isinstance(artifacts.get("workspace"), dict) else {}
    workspace_path = str(workspace.get("path") or task.codex_workspace_path or "").strip()
    summary = build_codex_run_summary(workspace_path, metrics, overview=overview)
    if summary is None:
        return task
    task.last_run = summary
    task.last_run_attempt = RunAttempt(output_dir=summary.output_dir, token_usage=summary.token_usage)
    task.codex_workspace_path = task.codex_workspace_path or summary.output_dir
    task.codex_status = "completed"
    try:
        return task_store.save_task(task, access_token=team_access.access_token)
    except (AttributeError, RuntimeError, PermissionError, ConnectionError) as exc:
        logger.warning("Could not persist completed Codex summary for task %s: %s", task.id, exc)
        return task


def _list_stage_records_for_snapshot(task_store: Any, task_id: str, team_access: TeamAccessContext) -> list[Any]:
    try:
        return task_store.list_stage_records(
            team_access.team_id,
            task_id,
            access_token=team_access.access_token,
            allow_stale_cache=True,
        )
    except (RuntimeError, PermissionError, ConnectionError):
        return []


def _human_request_counts(task_store: Any, task: TaskRecord, team_access: TeamAccessContext) -> dict[str, int]:
    try:
        requests = task_store.list_human_requests(
            task.team_id,
            task.id,
            access_token=team_access.access_token,
            prefer_cache=True,
            allow_stale_cache=True,
        )
    except (AttributeError, RuntimeError, PermissionError, ConnectionError):
        return {}
    visible_requests = visible_human_requests_for_actor(
        requests,
        actor_id=team_access.user.id,
        actor_role=team_access.role,
    )
    return {
        "open_request_count": count_open_human_requests(requests),
        "my_open_request_count": count_open_human_requests(visible_requests),
    }


def _completed_task_fallback_overview(task: TaskRecord) -> dict[str, Any]:
    output_dir = task.last_run.output_dir if task.last_run else task.codex_workspace_path
    if task.last_run:
        metric_name = task.last_run.metric_name
        metric_value = task.last_run.metric_value
        return {
            "schema_version": "1.0",
            "status": "completed",
            "task_summary": {
                "title": "已记录的建模结果",
                "target": task.label_column or "未记录",
                "target_columns": [task.label_column] if task.label_column else [],
                "task_type": task.problem_type or "other",
                "conclusion": (
                    f"任务已完成；数据库记录显示最佳模型 {task.last_run.best_model} "
                    f"的 {metric_name} = {metric_value:.6g}。"
                ),
                "recommendation": "原始 Codex 产物目录当前不可访问时，先以数据库记录的成功结果为准。",
            },
            "prediction_error": {
                "primary_metric": metric_name,
                "value": metric_value,
                "display": f"{metric_name} = {metric_value:.6g}",
                "split": None,
                "lower_is_better": None,
                "baseline_metric": None,
                "baseline_name": None,
                "interpretation": "该指标来自任务数据库 last_run 记录，不依赖本地 Codex 工作区。",
            },
            "target_columns": [task.label_column] if task.label_column else [],
            "target_metrics": {},
            "key_factors": [],
            "result_checks": [
                {
                    "name": "artifact_access",
                    "status": "warning",
                    "detail": "当前本地环境无法读取原始 Codex 产物目录，已展示数据库中的成功运行摘要。",
                    "evidence": output_dir,
                }
            ],
            "optimization_records": [],
            "charts": {},
            "source_files": {"workspace": output_dir},
        }
    return {
        "schema_version": "1.0",
        "status": "completed",
        "task_summary": {
            "title": "完成状态缺少可读产物",
            "target": task.label_column or "未记录",
            "target_columns": [task.label_column] if task.label_column else [],
            "task_type": task.problem_type or "other",
            "conclusion": "任务标记为已完成，但当前本地环境无法读取 Codex 产物，也没有数据库 last_run 指标。",
            "recommendation": "需要重新同步该任务的 Codex 工作区，或重新运行任务生成可读结果。",
        },
        "prediction_error": {},
        "target_columns": [task.label_column] if task.label_column else [],
        "target_metrics": {},
        "key_factors": [],
        "result_checks": [
            {
                "name": "artifact_access",
                "status": "failed",
                "detail": "没有可展示的 metrics、overview 或 report 产物。",
                "evidence": output_dir,
            }
        ],
        "optimization_records": [],
        "charts": {},
        "source_files": {"workspace": output_dir},
    }


def _task_payload(
    task: TaskRecord,
    *,
    task_detail: Literal["full", "summary"],
) -> TaskRecord | TaskRuntimeSummaryRecord:
    if task_detail != "summary":
        return task
    return TaskRuntimeSummaryRecord(
        id=task.id,
        team_id=task.team_id,
        created_by=task.created_by,
        creator_user_id=task.creator_user_id,
        name=task.name,
        description=task.description,
        label_column=task.label_column,
        problem_type=task.problem_type,
        status=task.status,
        dataset_filename=task.dataset_filename,
        dataset_path=task.dataset_path,
        notes=task.notes,
        last_run=task.last_run,
        executor_type=task.executor_type,
        codex_workspace_path=task.codex_workspace_path,
        codex_session_id=task.codex_session_id,
        codex_thread_id=task.codex_thread_id,
        codex_status=task.codex_status,
        codex_started_at=task.codex_started_at,
        codex_finished_at=task.codex_finished_at,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )
