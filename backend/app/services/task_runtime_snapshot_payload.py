from __future__ import annotations

from typing import Any

from backend.app.models.task import TaskRecord


def build_task_run_payload(
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
    artifacts = progress_response.artifacts.model_dump(mode="json") if progress_response else {}
    progress_percent = progress_response.progress_percent if progress_response else progress.get("progress_percent")
    progress_source = (
        getattr(progress_response, "progress_source", None)
        if progress_response
        else progress.get("progress_source")
    )
    current_activity = (
        progress_response.current_activity
        if progress_response
        else progress.get("current_activity", "")
    )
    codex = (
        _codex_payload(task, progress_response, codex_plan, codex_artifacts or {})
        if should_sync_codex
        else None
    )
    return {
        "steps": [step.model_dump(mode="json") for step in steps],
        "leaderboard": _leaderboard_payload(task, progress_response),
        "metrics": _metrics_payload(task),
        "artifacts": artifacts,
        "overview": codex_overview,
        "progress_percent": progress_percent,
        "progress_source": progress_source,
        "progress_unavailable_reason": (
            getattr(progress_response, "progress_unavailable_reason", None)
            if progress_response
            else progress.get("progress_unavailable_reason")
        ),
        "current_stage": _current_stage_payload(progress_response, progress),
        "current_activity": current_activity,
        "progress_status": progress_response.status if progress_response else progress.get("status", ""),
        "codex": codex,
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
    run_strategy_file = _artifact_file(artifacts, "run_strategy_file")
    improvement_plan_file = _artifact_file(artifacts, "improvement_plan_file")
    advisor_diagnosis_file = _artifact_file(artifacts, "advisor_diagnosis_file")
    progress_events_file = _artifact_file(artifacts, "progress_events_file")
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


def _artifact_file(artifacts: dict[str, Any], key: str) -> dict[str, Any]:
    value = artifacts.get(key)
    return value if isinstance(value, dict) else {}
