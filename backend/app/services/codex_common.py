from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.app.models.task import TaskStatus


CODEX_ACTIVE_STATUSES = {"running", "in_progress", "executing"}
CODEX_WAITING_STATUSES = {"waiting_plan_approval", "plan_ready"}
CODEX_FAILED_STATUSES = {"failed", "error", "interrupted"}


class CodexBackendError(RuntimeError):
    pass


def workspace_path_from_artifacts(artifacts: dict[str, Any]) -> str | None:
    workspace = artifacts.get("workspace")
    if isinstance(workspace, dict) and isinstance(workspace.get("path"), str):
        return workspace["path"]
    return None


def is_quota_guard_paused(task_status: TaskStatus, structured_requirements: Any) -> bool:
    if task_status not in {TaskStatus.paused_for_review, TaskStatus.waiting_human}:
        return False
    structured = structured_requirements if isinstance(structured_requirements, dict) else {}
    quota_guard = structured.get("quota_guard") if isinstance(structured.get("quota_guard"), dict) else {}
    return quota_guard.get("reason") == "member_token_quota_exhausted" and quota_guard.get("status") == "exhausted"


def read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def read_json(path: Path) -> dict[str, Any] | None:
    text = read_text(path)
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def iso_from_mtime(path: Path) -> str:
    return iso_datetime_from_timestamp(path.stat().st_mtime).isoformat()


def iso_datetime_from_timestamp(value: float) -> datetime:
    return datetime.fromtimestamp(value, tz=timezone.utc)


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def latest_workspace_update(workspace_path: Path) -> datetime | None:
    if not workspace_path.exists():
        return None
    latest = workspace_path.stat().st_mtime
    try:
        for child in workspace_path.rglob("*"):
            try:
                latest = max(latest, child.stat().st_mtime)
            except OSError:
                continue
    except OSError:
        return iso_datetime_from_timestamp(latest)
    return iso_datetime_from_timestamp(latest)


def coerce_non_negative_int(value: Any) -> int:
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return 0
    return max(numeric, 0)


def coerce_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def list_of_dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def nested_get(payload: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def lower_is_better(metric_name: str | None) -> bool:
    if not metric_name:
        return True
    lowered = metric_name.lower()
    return any(marker in lowered for marker in ("loss", "error", "mae", "mse", "rmse"))


def format_metric(value: float | None) -> str:
    if value is None:
        return "-"
    abs_value = abs(value)
    if abs_value != 0 and (abs_value >= 1_000_000 or abs_value < 0.0001):
        return f"{value:.4g}"
    return f"{value:.4f}".rstrip("0").rstrip(".")
