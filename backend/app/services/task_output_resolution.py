from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from backend.app.core.config import Settings
from backend.app.models.task import TaskRecord


NODE_SCAN_LIMIT = 16
LOG_CANDIDATE_NAMES = (
    "logs.txt",
    "info_logs.txt",
    "detail_logs.txt",
    "debugging_logs.txt",
    "progress.json",
)
DIRECT_ARTIFACT_NAMES = (
    "run_summary.json",
    "metrics.json",
    "leaderboard.json",
    "leaderboard.csv",
    "token_usage.json",
    "generated_code.py",
    "predict.py",
    "report.md",
)


def resolve_task_output_dir(
    task: TaskRecord,
    *,
    settings: Settings | None = None,
    prefer_success: bool = False,
    include_candidate_roots: bool = False,
    require_current_running: bool = False,
    current_attempt_started_at: datetime | None = None,
) -> tuple[Path | None, Path | None]:
    candidates = _task_output_candidates(
        task,
        settings=settings,
        prefer_success=prefer_success,
        include_candidate_roots=include_candidate_roots,
    )
    requested = candidates[0] if candidates else None
    existing = _existing_output_candidates(candidates)
    if require_current_running and existing:
        return requested, _current_running_output_dir(task, existing, current_attempt_started_at)
    if prefer_success:
        success_path = _successful_output_dir(task)
        if success_path is not None:
            return requested, success_path
    return requested, _latest_output_dir(existing)


def candidate_task_run_roots(task: TaskRecord, settings: Settings) -> list[Path]:
    roots = [settings.run_output_dir / task.id]
    if task.codex_workspace_path:
        roots.append(Path(task.codex_workspace_path).parent)
    codex_workspace_root = getattr(settings, "codex_workspace_root", None)
    if codex_workspace_root:
        roots.append(codex_workspace_root)

    unique: list[Path] = []
    seen: set[str] = set()
    for path in roots:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def latest_existing(paths: Iterable[Path]) -> Path | None:
    existing = [path for path in paths if path.exists()]
    if not existing:
        return None
    return max(existing, key=lambda path: (path_mtime(path), str(path)))


def recent_node_dirs(output_dir: Path, *, limit: int = NODE_SCAN_LIMIT) -> list[Path]:
    try:
        node_dirs = [path for path in output_dir.iterdir() if path.is_dir() and path.name.startswith("node_")]
    except OSError:
        return []
    return sorted(node_dirs, key=path_mtime, reverse=True)[:limit]


def latest_modified_at(path: Path) -> datetime | None:
    if not path.exists():
        return None
    latest = path_mtime(path)
    for child in path.rglob("*"):
        try:
            latest = max(latest, child.stat().st_mtime)
        except OSError:
            continue
    return datetime.fromtimestamp(latest, tz=timezone.utc)


def fast_latest_modified_at(path: Path) -> datetime:
    latest = path_mtime(path)
    for name in DIRECT_ARTIFACT_NAMES:
        latest = max(latest, path_mtime(path / name))
        latest = max(latest, path_mtime(path / "best_run" / "output" / name))
    for name in LOG_CANDIDATE_NAMES:
        latest = max(latest, path_mtime(path / name))
    for node_dir in recent_node_dirs(path):
        latest = max(latest, path_mtime(node_dir))
        latest = max(latest, path_mtime(node_dir / "output" / "run_summary.json"))
        latest = max(latest, path_mtime(node_dir / "output" / "leaderboard.csv"))
        latest = max(latest, path_mtime(node_dir / "output" / "leaderboard.json"))
        latest = max(latest, path_mtime(node_dir / "output" / "token_usage.json"))
        latest = max(latest, path_mtime(node_dir / "generated_code.py"))
        latest = max(latest, path_mtime(node_dir / "states" / "python_code.py"))
    return datetime.fromtimestamp(latest, tz=timezone.utc)


def fast_latest_mtime_timestamp(path: Path) -> float:
    return fast_latest_modified_at(path).timestamp()


def path_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _task_output_candidates(
    task: TaskRecord,
    *,
    settings: Settings | None,
    prefer_success: bool,
    include_candidate_roots: bool,
) -> list[Path]:
    candidates = _direct_task_output_candidates(task, prefer_success=prefer_success)
    if settings is not None:
        codex_workspace = _deterministic_codex_workspace_for_task(task, settings)
        if codex_workspace is not None:
            candidates.append(codex_workspace)
    if include_candidate_roots and settings is not None:
        candidates.extend(_candidate_root_output_dirs(task, settings))
    return candidates


def _candidate_root_output_dirs(task: TaskRecord, settings: Settings) -> list[Path]:
    candidates: list[Path] = []
    for root in candidate_task_run_roots(task, settings):
        if not root.exists():
            continue
        candidates.extend(
            sorted(
                (path for path in root.iterdir() if path.is_dir()),
                key=path_mtime,
                reverse=True,
            )
        )
    return candidates


def _existing_output_candidates(candidates: list[Path]) -> list[Path]:
    return [path for path in candidates if path.exists()]


def _current_running_output_dir(
    task: TaskRecord,
    existing: list[Path],
    current_attempt_started_at: datetime | None,
) -> Path | None:
    threshold = current_attempt_started_at or _as_utc(task.updated_at) - timedelta(minutes=2)
    current_paths = [path for path in existing if fast_latest_modified_at(path) >= threshold]
    return _latest_output_dir(current_paths)


def _successful_output_dir(task: TaskRecord) -> Path | None:
    if not task.last_run or not task.last_run.output_dir:
        return None
    success_path = Path(task.last_run.output_dir)
    return success_path if success_path.exists() else None


def _latest_output_dir(existing: list[Path]) -> Path | None:
    if not existing:
        return None
    return sorted(existing, key=fast_latest_mtime_timestamp, reverse=True)[0]


def _direct_task_output_candidates(task: TaskRecord, *, prefer_success: bool) -> list[Path]:
    success = Path(task.last_run.output_dir) if task.last_run and task.last_run.output_dir else None
    attempt = Path(task.last_run_attempt.output_dir) if task.last_run_attempt and task.last_run_attempt.output_dir else None
    ordered = [success, attempt] if prefer_success else [attempt, success]
    return [path for path in ordered if path is not None]


def _deterministic_codex_workspace_for_task(task: TaskRecord, settings: Settings) -> Path | None:
    workspace_root = getattr(settings, "codex_workspace_root", None)
    if workspace_root is None:
        return None
    safe_task_id = "".join(char if char.isalnum() or char in {"_", "-"} else "-" for char in task.id.strip())[:64]
    if not safe_task_id:
        return None
    return Path(workspace_root) / f"ai4ml-{safe_task_id}"


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
