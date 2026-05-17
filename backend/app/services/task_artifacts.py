from __future__ import annotations

import csv
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from backend.app.core.config import Settings
from backend.app.models.task import TaskRecord, TaskStatus, WorkflowStage


NODE_SCAN_LIMIT = 16
LOG_CANDIDATE_NAMES = (
    "logs.txt",
    "info_logs.txt",
    "detail_logs.txt",
    "debugging_logs.txt",
    "mlzero_stdout.log",
    "mlzero_stderr.log",
)
DIRECT_ARTIFACT_NAMES = (
    "run_summary.json",
    "leaderboard.json",
    "leaderboard.csv",
    "token_usage.json",
    "generated_code.py",
)
FEATURE_IMPORTANCE_FILENAMES = {
    "feature_importance.csv",
    "feature_importance.json",
    "feature_importances.csv",
    "feature_importances.json",
}
RUN_ERROR_LOG_NAMES = (
    "mlzero_stderr.log",
    "logs.txt",
    "info_logs.txt",
    "detail_logs.txt",
    "debugging_logs.txt",
    "mlzero_stdout.log",
)
STAGE_ARTIFACT_PATTERNS: dict[WorkflowStage, tuple[str, ...]] = {
    WorkflowStage.feature_engineering: (
        "generated_code.py",
        "python_code.py",
        "python_coder_prompt.txt",
        "python_coder_response.txt",
        "execution_script.sh",
    ),
    WorkflowStage.model_selection: (
        "leaderboard.csv",
        "leaderboard.json",
        "run_summary.json",
        "tool_selector_prompt.txt",
        "tool_selector_response.txt",
    ),
    WorkflowStage.training_validation: (
        "run_summary.json",
        "validation_predictions.csv",
        "results.csv",
        "stdout",
        "stderr",
        "execution_stdout.txt",
        "execution_stderr.txt",
    ),
    WorkflowStage.report_generation: (
        "summary.txt",
        "run_summary.json",
        "feature_importance.csv",
        "feature_importance.json",
        "feature_importances.csv",
        "feature_importances.json",
    ),
}


@dataclass(frozen=True)
class RunArtifactIndex:
    requested_output_dir: Path | None = None
    output_dir: Path | None = None
    node_dirs: list[Path] = field(default_factory=list)
    run_summary_path: Path | None = None
    leaderboard_path: Path | None = None
    token_usage_path: Path | None = None
    generated_code_path: Path | None = None
    predictor_dir: Path | None = None
    feature_importance_paths: list[Path] = field(default_factory=list)

    @property
    def has_run_summary(self) -> bool:
        return self.run_summary_path is not None

    @property
    def has_leaderboard(self) -> bool:
        return self.leaderboard_path is not None

    @property
    def has_token_usage(self) -> bool:
        return self.token_usage_path is not None

    @property
    def has_generated_code(self) -> bool:
        return self.generated_code_path is not None


def build_run_artifact_index(
    task: TaskRecord,
    *,
    settings: Settings | None = None,
    prefer_success: bool = False,
    include_candidate_roots: bool = False,
    require_current_running: bool = False,
    current_attempt_started_at: datetime | None = None,
) -> RunArtifactIndex:
    requested_output_dir, output_dir = resolve_task_output_dir(
        task,
        settings=settings,
        prefer_success=prefer_success,
        include_candidate_roots=include_candidate_roots,
        require_current_running=require_current_running,
        current_attempt_started_at=current_attempt_started_at,
    )
    if output_dir is None:
        return RunArtifactIndex(requested_output_dir=requested_output_dir)

    node_dirs = recent_node_dirs(output_dir)
    run_summary_path = latest_existing(
        [
            output_dir / "run_summary.json",
            output_dir / "best_run" / "output" / "run_summary.json",
            *(node_dir / "output" / "run_summary.json" for node_dir in node_dirs),
        ]
    )
    leaderboard_path = latest_existing(
        [
            output_dir / "leaderboard.json",
            output_dir / "leaderboard.csv",
            output_dir / "best_run" / "output" / "leaderboard.json",
            output_dir / "best_run" / "output" / "leaderboard.csv",
            *(node_dir / "output" / "leaderboard.json" for node_dir in node_dirs),
            *(node_dir / "output" / "leaderboard.csv" for node_dir in node_dirs),
        ]
    )
    token_usage_path = latest_existing(
        [output_dir / "token_usage.json", *(node_dir / "output" / "token_usage.json" for node_dir in node_dirs)]
    )
    generated_code_path = latest_existing(
        [
            output_dir / "generated_code.py",
            output_dir / "best_run" / "generated_code.py",
            *(node_dir / "generated_code.py" for node_dir in node_dirs),
            *(node_dir / "states" / "python_code.py" for node_dir in node_dirs),
        ]
    )
    return RunArtifactIndex(
        requested_output_dir=requested_output_dir or output_dir,
        output_dir=output_dir,
        node_dirs=node_dirs,
        run_summary_path=run_summary_path,
        leaderboard_path=leaderboard_path,
        token_usage_path=token_usage_path,
        generated_code_path=generated_code_path,
        predictor_dir=find_autogluon_predictor_dir(output_dir, node_dirs=node_dirs),
        feature_importance_paths=find_feature_importance_paths(output_dir, node_dirs=node_dirs),
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
    candidates = _direct_task_output_candidates(task, prefer_success=prefer_success)
    if include_candidate_roots and settings is not None:
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

    requested = candidates[0] if candidates else None
    existing = [path for path in candidates if path.exists()]
    if require_current_running and existing:
        threshold = current_attempt_started_at or _as_utc(task.updated_at) - timedelta(minutes=2)
        current_paths = [path for path in existing if fast_latest_modified_at(path) >= threshold]
        if current_paths:
            return requested, sorted(current_paths, key=fast_latest_mtime_timestamp, reverse=True)[0]
        return requested, None
    if prefer_success and task.last_run and task.last_run.output_dir:
        success_path = Path(task.last_run.output_dir)
        if success_path.exists():
            return requested, success_path
    if existing:
        return requested, sorted(existing, key=fast_latest_mtime_timestamp, reverse=True)[0]
    return requested, None


def candidate_task_run_roots(task: TaskRecord, settings: Settings) -> list[Path]:
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


def latest_existing(paths: Iterable[Path]) -> Path | None:
    existing = [path for path in paths if path.exists()]
    if not existing:
        return None
    return max(existing, key=lambda path: (path_mtime(path), str(path)))


def read_json_payload(path: Path | None) -> dict | None:
    if path is None:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def collect_stage_artifacts_by_stage(output_dir: str | Path | None) -> dict[WorkflowStage, list[str]]:
    root = _existing_root(output_dir)
    if root is None:
        return {}
    try:
        files = [path for path in root.rglob("*") if path.is_file()]
    except OSError:
        return {}

    collected: dict[WorkflowStage, list[str]] = {}
    for stage, names in STAGE_ARTIFACT_PATTERNS.items():
        matched: list[str] = []
        wanted = {name.lower() for name in names}
        for path in files:
            if path.name.lower() in wanted:
                matched.append(str(path))
            if len(matched) >= 12:
                break
        if matched:
            collected[stage] = matched
    return collected


def read_run_log_excerpt(output_dir: str | Path | None, *, max_chars: int = 1800) -> str | None:
    root = _existing_root(output_dir)
    if root is None:
        return None
    candidates = [
        root / "summary.txt",
        root / "mlzero_stderr.log",
        root / "mlzero_stdout.log",
        root / "info_logs.txt",
        root / "detail_logs.txt",
        root / "logs.txt",
    ]
    try:
        candidates.extend(sorted(root.rglob("*.log"), key=path_mtime, reverse=True))
    except OSError:
        pass
    seen: set[Path] = set()
    for path in candidates:
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        try:
            text = path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        if not text:
            continue
        if len(text) > max_chars:
            text = text[-max_chars:]
        return f"{path.name}\n{text}"
    return None


def select_run_error_artifact(output_dir: str | Path | None) -> str | None:
    root = _existing_root(output_dir)
    if root is None:
        return None
    candidates = [root / name for name in RUN_ERROR_LOG_NAMES]
    try:
        candidates.extend(
            sorted(
                (path for path in root.rglob("*.log") if path.is_file()),
                key=path_mtime,
                reverse=True,
            )
        )
    except OSError:
        pass
    seen: set[Path] = set()
    for path in candidates:
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        try:
            if path.stat().st_size <= 0:
                continue
        except OSError:
            continue
        return str(path)
    fallback = root / "logs.txt"
    return str(fallback) if fallback.is_file() else str(root)


def count_leaderboard_rows(path: Path | None) -> int | None:
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


def find_autogluon_predictor_dir(output_dir: Path, *, node_dirs: list[Path] | None = None) -> Path | None:
    nodes = node_dirs if node_dirs is not None else recent_node_dirs(output_dir)
    candidates = [
        path.parent
        for path in [
            output_dir / "predictor.pkl",
            output_dir / "best_run" / "predictor.pkl",
            output_dir / "best_run" / "output" / "predictor.pkl",
            *(node_dir / "predictor.pkl" for node_dir in nodes),
            *(node_dir / "output" / "predictor.pkl" for node_dir in nodes),
        ]
        if path.is_file()
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: path_mtime(item), reverse=True)[0]


def find_feature_importance_paths(output_dir: Path, *, node_dirs: list[Path] | None = None) -> list[Path]:
    nodes = node_dirs if node_dirs is not None else recent_node_dirs(output_dir)
    dirs = [output_dir, output_dir / "best_run", output_dir / "best_run" / "output"]
    for node_dir in nodes:
        dirs.extend([node_dir, node_dir / "output"])
    return [
        directory / filename
        for directory in dirs
        for filename in FEATURE_IMPORTANCE_FILENAMES
        if (directory / filename).is_file()
    ]


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


def api_path(path: Path | None) -> str | None:
    return path.as_posix() if path else None


def _existing_root(output_dir: str | Path | None) -> Path | None:
    if not output_dir:
        return None
    root = Path(output_dir)
    return root if root.exists() else None


def _direct_task_output_candidates(task: TaskRecord, *, prefer_success: bool) -> list[Path]:
    success = Path(task.last_run.output_dir) if task.last_run and task.last_run.output_dir else None
    attempt = Path(task.last_run_attempt.output_dir) if task.last_run_attempt and task.last_run_attempt.output_dir else None
    ordered = [success, attempt] if prefer_success else [attempt, success]
    return [path for path in ordered if path is not None]


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
