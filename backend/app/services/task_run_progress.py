from __future__ import annotations

import csv
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from backend.app.core.config import Settings
from backend.app.models.task import (
    TaskRecord,
    TaskRunProgressArtifactSummary,
    TaskRunProgressResponse,
    TaskStatus,
    WorkflowStage,
)


STALE_RUNNING_SECONDS = 60 * 60
LOG_CANDIDATE_NAMES = (
    "logs.txt",
    "info_logs.txt",
    "detail_logs.txt",
    "debugging_logs.txt",
    "mlzero_stdout.log",
    "mlzero_stderr.log",
)
NODE_SCAN_LIMIT = 16
DIRECT_ARTIFACT_NAMES = (
    "run_summary.json",
    "leaderboard.json",
    "leaderboard.csv",
    "token_usage.json",
    "generated_code.py",
)


def build_task_run_progress(
    task: TaskRecord,
    settings: Settings,
    *,
    stale_after_seconds: int = STALE_RUNNING_SECONDS,
) -> TaskRunProgressResponse:
    output_dir = _resolve_run_output_dir(task, settings)
    warnings: list[str] = []
    if output_dir is None:
        return TaskRunProgressResponse(
            task=task,
            status="not_started" if task.status not in {TaskStatus.running, TaskStatus.failed} else task.status.value,
            current_activity=task.notes or "尚未找到 MLZero 运行目录。",
            warnings=[] if task.status != TaskStatus.running else ["任务仍标记为运行中，但没有找到对应运行目录。"],
        )

    artifacts = _summarize_artifacts(output_dir)
    if artifacts.has_run_summary and artifacts.has_leaderboard and not artifacts.has_token_usage:
        warnings.append("已找到 run_summary 和 leaderboard，但缺少 token_usage.json；当前严格口径不能把它判定为完整成功。")

    last_log_at = _latest_modified_at(output_dir)
    seconds_since_last_update = None
    if last_log_at is not None:
        seconds_since_last_update = max((datetime.now(timezone.utc) - last_log_at).total_seconds(), 0.0)

    latest_log_lines = _read_latest_log_lines(output_dir)
    current_stage, current_activity, progress_percent = _infer_activity(
        latest_log_lines,
        artifacts=artifacts,
        task_status=task.status,
    )

    stale = (
        task.status == TaskStatus.running
        and seconds_since_last_update is not None
        and seconds_since_last_update > stale_after_seconds
    )
    stale_reason = None
    if stale:
        stale_reason = (
            f"运行目录已经 {int(seconds_since_last_update // 60)} 分钟没有新日志或产物写入；"
            "这通常表示 MLZero 子进程已中断或卡死。"
        )

    status = _resolve_progress_status(task, stale=stale, artifacts=artifacts)
    if stale and current_activity:
        current_activity = f"{current_activity}（已长时间无更新）"

    return TaskRunProgressResponse(
        task=task,
        output_dir=str(output_dir),
        status=status,
        progress_percent=progress_percent,
        current_stage=current_stage,
        current_activity=current_activity or task.notes or "暂无可解析的运行活动。",
        last_log_at=last_log_at,
        seconds_since_last_update=seconds_since_last_update,
        stale=stale,
        stale_reason=stale_reason,
        artifacts=artifacts,
        latest_log_lines=latest_log_lines[-80:],
        warnings=warnings,
    )


def _resolve_run_output_dir(task: TaskRecord, settings: Settings) -> Path | None:
    candidates: list[Path] = []
    if task.last_run_attempt and task.last_run_attempt.output_dir:
        candidates.append(Path(task.last_run_attempt.output_dir))
    if task.last_run and task.last_run.output_dir:
        candidates.append(Path(task.last_run.output_dir))

    task_run_root = settings.run_output_dir / task.id
    for task_run_root in _candidate_task_run_roots(task, settings):
        if not task_run_root.exists():
            continue
        candidates.extend(
            sorted(
                (path for path in task_run_root.iterdir() if path.is_dir()),
                key=lambda path: _path_mtime(path),
                reverse=True,
            )
        )

    existing = [path for path in candidates if path.exists()]
    if existing and task.status == TaskStatus.running:
        current_attempt_started_at = _as_utc(task.updated_at) - timedelta(minutes=2)
        current_attempt_paths = [
            path for path in existing
            if _fast_latest_modified_at(path) >= current_attempt_started_at
        ]
        if current_attempt_paths:
            return sorted(current_attempt_paths, key=_fast_latest_mtime_timestamp, reverse=True)[0]
        return None
    if existing:
        return sorted(existing, key=_fast_latest_mtime_timestamp, reverse=True)[0]
    return candidates[0] if candidates else None


def _candidate_task_run_roots(task: TaskRecord, settings: Settings) -> list[Path]:
    roots = [settings.run_output_dir / task.id]
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        roots.append(Path(local_appdata) / "AI4ML" / "mlzero_runs" / task.id)
    roots.append(settings.repo_root / "storage" / "mlzero_runs" / task.id)

    unique: list[Path] = []
    seen: set[str] = set()
    for path in roots:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _summarize_artifacts(output_dir: Path) -> TaskRunProgressArtifactSummary:
    node_dirs = _recent_node_dirs(output_dir)
    summary_path = _first_existing(
        [
            output_dir / "run_summary.json",
            output_dir / "best_run" / "output" / "run_summary.json",
            *(node_dir / "output" / "run_summary.json" for node_dir in node_dirs),
        ]
    )
    leaderboard_path = _first_existing(
        [
            output_dir / "leaderboard.json",
            output_dir / "leaderboard.csv",
            output_dir / "best_run" / "output" / "leaderboard.json",
            output_dir / "best_run" / "output" / "leaderboard.csv",
            *(node_dir / "output" / "leaderboard.json" for node_dir in node_dirs),
            *(node_dir / "output" / "leaderboard.csv" for node_dir in node_dirs),
        ]
    )
    token_usage_path = _first_existing([output_dir / "token_usage.json", *(node_dir / "output" / "token_usage.json" for node_dir in node_dirs)])
    generated_code_path = _first_existing(
        [
            output_dir / "best_run" / "generated_code.py",
            *(node_dir / "generated_code.py" for node_dir in node_dirs),
            *(node_dir / "states" / "python_code.py" for node_dir in node_dirs),
        ]
    )

    payload = _read_summary_payload(summary_path)
    return TaskRunProgressArtifactSummary(
        has_run_summary=summary_path is not None,
        has_leaderboard=leaderboard_path is not None,
        has_token_usage=token_usage_path is not None,
        has_generated_code=generated_code_path is not None,
        run_summary_path=str(summary_path) if summary_path else None,
        leaderboard_path=str(leaderboard_path) if leaderboard_path else None,
        token_usage_path=str(token_usage_path) if token_usage_path else None,
        generated_code_path=str(generated_code_path) if generated_code_path else None,
        best_model=_coerce_str(payload.get("best_model")) if payload else None,
        metric_name=_coerce_str(payload.get("metric_name")) if payload else None,
        metric_value=_coerce_float(payload.get("metric_value")) if payload else None,
        validation_score=_coerce_float(payload.get("validation_score")) if payload else None,
        candidate_model_count=_coerce_int(payload.get("candidate_model_count")) if payload else _count_leaderboard_rows(leaderboard_path),
    )


def _infer_activity(
    lines: list[str],
    *,
    artifacts: TaskRunProgressArtifactSummary,
    task_status: TaskStatus,
) -> tuple[WorkflowStage | None, str, int]:
    text = "\n".join(lines)
    last_line = _last_significant_line(lines)
    current_stage: WorkflowStage | None = None

    if "CoderAgent" in text or "python_coder" in text or "generated_code.py" in text:
        current_stage = WorkflowStage.feature_engineering
    if "Executing code" in text or "ExecuterAgent" in text or "training" in text or "Validation score" in text:
        current_stage = WorkflowStage.training_validation
    if "leaderboard" in text or "Best node" in text or "candidate" in text:
        current_stage = WorkflowStage.model_selection
    if artifacts.has_run_summary and artifacts.has_leaderboard:
        current_stage = WorkflowStage.training_validation

    progress = 0
    iteration_matches = list(re.finditer(r"Starting MCTS iteration\s+(\d+)\s*/\s*(\d+)", text, flags=re.IGNORECASE))
    if iteration_matches:
        current, total = int(iteration_matches[-1].group(1)), int(iteration_matches[-1].group(2))
        if total > 0:
            progress = min(94, max(8, int((current - 1) / total * 100)))
    if artifacts.has_generated_code:
        progress = max(progress, 35)
    if artifacts.has_run_summary or artifacts.has_leaderboard:
        progress = max(progress, 72)
    if artifacts.has_run_summary and artifacts.has_leaderboard and artifacts.has_token_usage:
        progress = max(progress, 95)
    if task_status in {TaskStatus.completed, TaskStatus.failed}:
        progress = 100

    if artifacts.best_model and artifacts.metric_name and artifacts.metric_value is not None:
        activity = f"已产出候选结果：最佳模型 {artifacts.best_model}，{artifacts.metric_name} = {artifacts.metric_value:.6g}。"
    elif last_line:
        activity = _strip_log_prefix(last_line)
    else:
        activity = ""
    return current_stage, activity, progress


def _resolve_progress_status(
    task: TaskRecord,
    *,
    stale: bool,
    artifacts: TaskRunProgressArtifactSummary,
) -> str:
    if stale:
        return "stale"
    if task.status == TaskStatus.completed:
        return "completed"
    if task.status == TaskStatus.failed:
        return "failed"
    if task.status == TaskStatus.running:
        return "running"
    if artifacts.has_run_summary and artifacts.has_leaderboard and artifacts.has_token_usage:
        return "completed"
    if artifacts.has_run_summary or artifacts.has_leaderboard:
        return "unknown"
    return "not_started"


def _latest_modified_at(path: Path) -> datetime | None:
    if not path.exists():
        return None
    latest = _path_mtime(path)
    for child in path.rglob("*"):
        try:
            latest = max(latest, child.stat().st_mtime)
        except OSError:
            continue
    return datetime.fromtimestamp(latest, tz=timezone.utc)


def _fast_latest_modified_at(path: Path) -> datetime:
    latest = _path_mtime(path)
    for name in DIRECT_ARTIFACT_NAMES:
        latest = max(latest, _path_mtime(path / name))
        latest = max(latest, _path_mtime(path / "best_run" / "output" / name))
    for name in LOG_CANDIDATE_NAMES:
        latest = max(latest, _path_mtime(path / name))
    for node_dir in _recent_node_dirs(path):
        latest = max(latest, _path_mtime(node_dir))
        latest = max(latest, _path_mtime(node_dir / "output" / "run_summary.json"))
        latest = max(latest, _path_mtime(node_dir / "output" / "leaderboard.csv"))
        latest = max(latest, _path_mtime(node_dir / "output" / "leaderboard.json"))
        latest = max(latest, _path_mtime(node_dir / "output" / "token_usage.json"))
        latest = max(latest, _path_mtime(node_dir / "generated_code.py"))
        latest = max(latest, _path_mtime(node_dir / "states" / "python_code.py"))
    return datetime.fromtimestamp(latest, tz=timezone.utc)


def _read_latest_log_lines(output_dir: Path, *, max_lines: int = 160) -> list[str]:
    candidates = [output_dir / name for name in LOG_CANDIDATE_NAMES]
    for node_dir in _recent_node_dirs(output_dir):
        candidates.extend(node_dir / name for name in LOG_CANDIDATE_NAMES)
        candidates.extend((node_dir / "output" / name for name in LOG_CANDIDATE_NAMES))
        candidates.extend((node_dir / "logs" / name for name in LOG_CANDIDATE_NAMES))
    candidates = sorted(candidates, key=_path_mtime, reverse=True)
    latest = next((path for path in candidates if path.is_file()), None)
    if latest is None:
        return []
    try:
        text = latest.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return text.strip().splitlines()[-max_lines:]


def _first_existing(paths: Iterable[Path]) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


def _read_summary_payload(path: Path | None) -> dict | None:
    if path is None:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _count_leaderboard_rows(path: Path | None) -> int | None:
    if path is None:
        return None
    try:
        if path.suffix.lower() == ".json":
            payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
            if isinstance(payload, list):
                return len([item for item in payload if isinstance(item, dict)])
            if isinstance(payload, dict) and isinstance(payload.get("leaderboard"), list):
                return len(payload["leaderboard"])
            return None
        with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
            return len(list(csv.DictReader(handle)))
    except (OSError, json.JSONDecodeError, csv.Error):
        return None


def _last_significant_line(lines: list[str]) -> str:
    for line in reversed(lines):
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _strip_log_prefix(line: str) -> str:
    return re.sub(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\s+\w+\s+\[[^\]]+\]\s*", "", line).strip()


def _path_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _fast_latest_mtime_timestamp(path: Path) -> float:
    return _fast_latest_modified_at(path).timestamp()


def _recent_node_dirs(output_dir: Path, *, limit: int = NODE_SCAN_LIMIT) -> list[Path]:
    try:
        node_dirs = [path for path in output_dir.iterdir() if path.is_dir() and path.name.startswith("node_")]
    except OSError:
        return []
    return sorted(node_dirs, key=_path_mtime, reverse=True)[:limit]


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _coerce_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _coerce_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _coerce_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None
