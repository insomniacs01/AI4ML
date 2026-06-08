from __future__ import annotations

from typing import Any, NamedTuple

from backend.app.models.task import TaskRecord, TaskStatus
from backend.app.services.codex_artifact_state import has_completed_codex_artifacts
from backend.app.services.codex_common import CODEX_FAILED_STATUSES


class ProgressPercentResult(NamedTuple):
    percent: int | None
    source: str | None
    unavailable_reason: str | None


def codex_progress_percent(
    task: TaskRecord,
    progress: dict[str, Any],
    codex_status_value: str,
    artifacts: dict[str, Any],
) -> ProgressPercentResult:
    if codex_status_value == "completed" or task.status == TaskStatus.completed or has_completed_codex_artifacts(artifacts):
        return ProgressPercentResult(100, "completed", None)
    if task.status in {TaskStatus.draft, TaskStatus.uploaded, TaskStatus.planning}:
        return ProgressPercentResult(0, "not_started", None)

    percent = _explicit_progress_percent(progress)
    if percent is not None:
        source = str(
            progress.get("percent_source")
            or ("progress_json_percent" if "percent" in progress else "progress_json_progress_percent")
        )
        if task.status in {TaskStatus.failed, TaskStatus.cancelled}:
            return ProgressPercentResult(min(99, max(0, percent)), source, None)
        if codex_status_value == "interrupted" and task.status in {TaskStatus.paused_for_review, TaskStatus.waiting_human}:
            return ProgressPercentResult(min(99, max(0, percent)), source, None)
        if codex_status_value in CODEX_FAILED_STATUSES:
            return ProgressPercentResult(min(99, max(0, percent)), source, None)
        return ProgressPercentResult(max(0, min(99, percent)), source, None)

    reason = _progress_unavailable_reason(task, progress, artifacts)
    if task.status in {TaskStatus.failed, TaskStatus.cancelled}:
        return ProgressPercentResult(None, None, reason)
    if codex_status_value == "interrupted" and task.status in {TaskStatus.paused_for_review, TaskStatus.waiting_human}:
        return ProgressPercentResult(None, None, reason)
    if codex_status_value in CODEX_FAILED_STATUSES:
        return ProgressPercentResult(None, None, reason)
    return ProgressPercentResult(None, None, reason)


def _explicit_progress_percent(progress: dict[str, Any]) -> int | None:
    if "percent" in progress:
        raw_percent = progress.get("percent")
    elif "progress_percent" in progress:
        raw_percent = progress.get("progress_percent")
    else:
        return None
    try:
        return int(raw_percent)
    except (TypeError, ValueError):
        return None


def _progress_unavailable_reason(
    task: TaskRecord,
    progress: dict[str, Any],
    artifacts: dict[str, Any],
) -> str:
    progress_file = artifacts.get("progress_file") if isinstance(artifacts.get("progress_file"), dict) else {}
    if progress_file.get("exists") and not progress_file.get("readable"):
        return "progress_file_unreadable"
    if artifacts.get("workspace") and progress_file and not progress_file.get("exists"):
        return "progress_file_missing"
    if not progress:
        if artifacts.get("workspace"):
            return "progress_file_missing"
        if task.status == TaskStatus.running:
            return "workspace_not_ready"
        return "progress_not_available"
    if "percent" in progress or "progress_percent" in progress:
        raw_percent = progress.get("percent") if "percent" in progress else progress.get("progress_percent")
        if raw_percent is None or raw_percent == "":
            return "progress_percent_missing"
        return "progress_percent_invalid"
    return "progress_percent_missing"
