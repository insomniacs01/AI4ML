from __future__ import annotations

import logging
from typing import Any

from backend.app.core.config import get_settings
from backend.app.core.supabase_auth import TeamAccessContext
from backend.app.models.task import TaskRecord, TaskRuntimeSnapshotResponse, TaskStatus
from backend.app.services.codex_backend import (
    build_codex_overview,
    build_codex_run_progress,
    codex_plan_text,
    fetch_codex_task_status,
    read_codex_artifacts,
)
from backend.app.services.codex_common import CODEX_ACTIVE_STATUSES
from backend.app.services.codex_usage import read_codex_token_usage
from backend.app.services.governance_store import GovernanceStore
from backend.app.services.model_config import read_model_profile
from backend.app.services.quota_runtime_guard import pause_codex_task_for_quota, quota_is_exhausted
from backend.app.services.service_registry import get_task_store
from backend.app.services.task_codex_improvement_review import has_codex_improvement_review
from backend.app.services.task_codex_sync import is_codex_task, sync_codex_task_state
from backend.app.services.task_runtime_progress import (
    ensure_codex_improvement_request,
    ensure_codex_plan_request,
)
from backend.app.services.task_runtime_steps import build_runtime_steps, progress_from_steps


logger = logging.getLogger(__name__)


class TaskRuntimeSnapshotNotFound(LookupError):
    pass


class TaskRuntimeSnapshotSyncError(RuntimeError):
    pass


def build_task_runtime_snapshot_response(
    task_id: str,
    team_access: TeamAccessContext,
    *,
    sync_runtime: bool = True,
) -> TaskRuntimeSnapshotResponse:
    task_store = get_task_store()
    task = task_store.get_task(
        team_access.team_id,
        task_id,
        access_token=team_access.access_token,
        allow_stale_cache=True,
    )
    if task is None:
        raise TaskRuntimeSnapshotNotFound("task not found")

    settings = get_settings()
    should_sync_codex = is_codex_task(task, settings)
    if should_sync_codex:
        progress_response = None
        codex_overview = {}
        codex_artifacts = {}
        if sync_runtime:
            try:
                task, progress_response, codex_overview, codex_artifacts = _sync_codex_runtime_snapshot(
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
        task = _safe_reconcile_codex_runtime_activity(task_store, task, team_access, settings)
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
    plan_text = _safe_codex_plan_text(task, settings) if should_sync_codex else ""
    return TaskRuntimeSnapshotResponse(
        task=task,
        task_run=_build_task_run_payload(
            task,
            steps,
            progress_response,
            progress,
            codex_overview,
            should_sync_codex=should_sync_codex,
            codex_plan=plan_text,
            codex_artifacts=codex_artifacts,
        ),
    )


def _build_fast_codex_runtime_snapshot(task: TaskRecord, settings: Any) -> tuple[Any | None, dict[str, Any]]:
    try:
        return build_codex_run_progress(task, settings), {}
    except Exception as exc:  # noqa: BLE001
        logger.debug("Fast Codex runtime snapshot fell back to cached task state for task %s: %s", task.id, exc)
        return None, {}


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


def _sync_codex_runtime_snapshot(
    task_store: Any,
    task: TaskRecord,
    team_access: TeamAccessContext,
    settings: Any,
) -> tuple[TaskRecord, Any, dict[str, Any], dict[str, Any]]:
    try:
        task.executor_type = "codex"
        task, artifacts = sync_codex_task_state(
            task,
            settings,
            task_store=task_store,
            access_token=team_access.access_token,
        )
        progress_response = build_codex_run_progress(task, settings)
        codex_overview = build_codex_overview(task, settings)
        quota_exhausted = sync_codex_token_ledger(task_store, task, team_access)
        if quota_exhausted:
            task = pause_codex_task_for_quota(task_store, task, team_access)
            progress_response = build_codex_run_progress(task, settings)
        if progress_response.status == "blocked" and task.codex_status != "interrupted":
            try:
                if has_codex_improvement_review(artifacts):
                    ensure_codex_improvement_request(task, team_access, artifacts=artifacts)
                else:
                    ensure_codex_plan_request(task, team_access)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not sync Codex review request for task %s: %s", task.id, exc)
        return task, progress_response, codex_overview, artifacts
    except Exception as exc:  # noqa: BLE001
        raise TaskRuntimeSnapshotSyncError(f"Codex runtime snapshot sync failed: {exc}") from exc


def _safe_reconcile_codex_runtime_activity(
    task_store: Any,
    task: TaskRecord,
    team_access: TeamAccessContext,
    settings: Any,
) -> TaskRecord:
    try:
        return _reconcile_codex_runtime_activity(task_store, task, team_access, settings)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not reconcile Codex runtime activity for task %s: %s", task.id, exc)
        return task


def _reconcile_codex_runtime_activity(
    task_store: Any,
    task: TaskRecord,
    team_access: TeamAccessContext,
    settings: Any,
) -> TaskRecord:
    if not _needs_codex_runtime_probe(task):
        return task
    try:
        status_payload = fetch_codex_task_status(task, settings)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not verify Codex runtime activity for task %s: %s", task.id, exc)
        return task

    if status_payload.get("running") is True:
        return task

    synced_task, _artifacts = sync_codex_task_state(
        task,
        settings,
        task_store=task_store,
        access_token=team_access.access_token,
        fail_on_error=False,
    )
    if not _needs_codex_runtime_probe(synced_task):
        return synced_task

    synced_task.status = TaskStatus.paused_for_review
    synced_task.codex_status = "interrupted"
    synced_task.codex_finished_at = None
    synced_task.notes = "Codex 当前没有运行中的执行轮次，已停止显示为运行中；可从现有工作区继续。"
    try:
        return task_store.save_task(synced_task, access_token=team_access.access_token)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not persist inactive Codex runtime state for task %s: %s", task.id, exc)
        return synced_task


def _needs_codex_runtime_probe(task: TaskRecord) -> bool:
    if not (task.codex_session_id or task.codex_workspace_path):
        return False
    codex_status_value = str(task.codex_status or "").strip()
    return task.status == TaskStatus.running or codex_status_value in CODEX_ACTIVE_STATUSES


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


def _build_task_run_payload(
    task: TaskRecord,
    steps: list[Any],
    progress_response: Any | None,
    progress: dict[str, Any],
    codex_overview: dict[str, Any],
    *,
    should_sync_codex: bool,
    codex_plan: str,
    codex_artifacts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "steps": [step.model_dump(mode="json") for step in steps],
        "leaderboard": _leaderboard_payload(task, progress_response),
        "metrics": _metrics_payload(task),
        "artifacts": progress_response.artifacts.model_dump(mode="json") if progress_response else {},
        "overview": codex_overview,
        "progress_percent": progress_response.progress_percent if progress_response else progress.get("progress_percent"),
        "progress_source": getattr(progress_response, "progress_source", None) if progress_response else progress.get("progress_source"),
        "progress_unavailable_reason": (
            getattr(progress_response, "progress_unavailable_reason", None)
            if progress_response
            else progress.get("progress_unavailable_reason")
        ),
        "current_stage": _current_stage_payload(progress_response, progress),
        "current_activity": progress_response.current_activity if progress_response else progress.get("current_activity", ""),
        "progress_status": progress_response.status if progress_response else progress.get("status", ""),
        "codex": _codex_payload(task, progress_response, codex_plan, codex_artifacts or {}) if should_sync_codex else None,
    }


def _leaderboard_payload(task: TaskRecord, progress_response: Any | None) -> list[Any]:
    if progress_response:
        return progress_response.leaderboard
    if task.last_run:
        return task.last_run.leaderboard
    return []


def _metrics_payload(task: TaskRecord) -> dict[str, float]:
    if not task.last_run:
        return {}
    return {task.last_run.metric_name: task.last_run.metric_value}


def _current_stage_payload(progress_response: Any | None, progress: dict[str, Any]) -> str | None:
    if progress_response and progress_response.current_stage:
        return progress_response.current_stage.value
    return progress.get("current_stage")


def _codex_payload(
    task: TaskRecord,
    progress_response: Any | None,
    codex_plan: str,
    artifacts: dict[str, Any],
) -> dict[str, Any]:
    payload = {
        "workspace_path": progress_response.codex_workspace_path if progress_response else task.codex_workspace_path,
        "session_id": task.codex_session_id,
        "thread_id": task.codex_thread_id,
        "plan_text": codex_plan,
        "progress": progress_response.codex_raw_progress if progress_response else None,
        "steps": progress_response.codex_raw_steps if progress_response else [],
        "status": task.codex_status,
    }
    run_strategy_file = artifacts.get("run_strategy_file") if isinstance(artifacts.get("run_strategy_file"), dict) else {}
    improvement_plan_file = artifacts.get("improvement_plan_file") if isinstance(artifacts.get("improvement_plan_file"), dict) else {}
    advisor_diagnosis_file = artifacts.get("advisor_diagnosis_file") if isinstance(artifacts.get("advisor_diagnosis_file"), dict) else {}
    progress_events_file = artifacts.get("progress_events_file") if isinstance(artifacts.get("progress_events_file"), dict) else {}
    progress_events = artifacts.get("progress_events") if isinstance(artifacts.get("progress_events"), list) else []
    if progress_events:
        payload["progress_events"] = progress_events[-80:]
    if progress_events_file.get("exists"):
        payload["progress_events_path"] = progress_events_file.get("path")
    if isinstance(artifacts.get("run_strategy"), dict):
        payload["run_strategy"] = artifacts["run_strategy"]
    if run_strategy_file.get("exists"):
        payload["run_strategy_path"] = run_strategy_file.get("path")
    if isinstance(artifacts.get("improvement_plan"), str):
        payload["improvement_plan_text"] = artifacts["improvement_plan"]
    if improvement_plan_file.get("exists"):
        payload["improvement_plan_path"] = improvement_plan_file.get("path")
    if isinstance(artifacts.get("advisor_request"), dict):
        payload["advisor_request"] = artifacts["advisor_request"]
    if isinstance(artifacts.get("advisor_diagnosis"), dict):
        payload["advisor_diagnosis"] = artifacts["advisor_diagnosis"]
    if advisor_diagnosis_file.get("exists"):
        payload["advisor_diagnosis_path"] = advisor_diagnosis_file.get("path")
    if isinstance(artifacts.get("token_usage"), dict):
        payload["token_usage"] = artifacts["token_usage"]
    return payload


def sync_codex_token_ledger(task_store, task: TaskRecord, team_access: TeamAccessContext) -> bool:
    output_dir = task.last_run.output_dir if task.last_run else task.last_run_attempt.output_dir if task.last_run_attempt else None
    usage = (
        task.last_run.token_usage if task.last_run and task.last_run.token_usage else
        task.last_run_attempt.token_usage if task.last_run_attempt and task.last_run_attempt.token_usage else
        read_codex_token_usage(output_dir)
    )
    if output_dir is None or usage is None:
        return False

    try:
        model_name = read_model_profile(get_settings())["display_name"]
        task_store.upsert_token_ledger(
            team_id=task.team_id,
            task_id=task.id,
            phase="codex",
            stage_key="codex_native",
            source_key=output_dir,
            usage=usage,
            access_token=team_access.access_token,
            user_id=team_access.user.id,
            connector_display_name=model_name,
            model_name=model_name,
            calculation_method="codex_app_server_token_usage",
        )
        quota = GovernanceStore(get_settings()).get_member_quota(
            team_access.team_id,
            team_access.user.id,
            access_token=team_access.access_token,
        )
        return quota_is_exhausted(quota)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not sync Codex token ledger for task %s: %s", task.id, exc)
        return False
