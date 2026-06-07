from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

from backend.app.core.config import Settings, get_settings
from backend.app.models.task import TaskRecord, WorkflowStage
from backend.app.services.task_artifact_index import (
    RunArtifactIndex,
    build_run_artifact_index as _build_run_artifact_index,
    find_feature_importance_paths,
)
from backend.app.services.task_output_resolution import (
    path_mtime,
)


RUN_ERROR_LOG_NAMES = (
    "logs.txt",
    "info_logs.txt",
    "detail_logs.txt",
    "debugging_logs.txt",
)
STAGE_ARTIFACT_PATTERNS: dict[WorkflowStage, tuple[str, ...]] = {
    WorkflowStage.feature_engineering: (
        "generated_code.py",
        "predict.py",
        "final_modeling.py",
        "python_code.py",
        "python_coder_prompt.txt",
        "python_coder_response.txt",
        "execution_script.sh",
    ),
    WorkflowStage.model_selection: (
        "metrics.json",
        "leaderboard.csv",
        "leaderboard.json",
        "run_summary.json",
        "tool_selector_prompt.txt",
        "tool_selector_response.txt",
    ),
    WorkflowStage.training_validation: (
        "metrics.json",
        "run_summary.json",
        "final_predictions.csv",
        "validation_predictions.csv",
        "results.csv",
        "stdout",
        "stderr",
        "execution_stdout.txt",
        "execution_stderr.txt",
    ),
    WorkflowStage.report_generation: (
        "report.md",
        "metrics.json",
        "progress.json",
        "summary.txt",
        "run_summary.json",
        "feature_importance.csv",
        "feature_importance.json",
        "feature_importances.csv",
        "feature_importances.json",
    ),
}


def build_run_artifact_index(
    task: TaskRecord,
    *,
    settings: Settings | None = None,
    prefer_success: bool = False,
    include_candidate_roots: bool = False,
    require_current_running: bool = False,
    current_attempt_started_at: datetime | None = None,
) -> RunArtifactIndex:
    return _build_run_artifact_index(
        task,
        settings=settings or get_settings(),
        prefer_success=prefer_success,
        include_candidate_roots=include_candidate_roots,
        require_current_running=require_current_running,
        current_attempt_started_at=current_attempt_started_at,
    )


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
        root / "output" / "report.md",
        root / "output" / "progress.json",
        root / "summary.txt",
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
    candidates.extend([root / "output" / "progress.json", root / "output" / "report.md"])
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


def api_path(path: Path | None) -> str | None:
    return path.as_posix() if path else None


def _existing_root(output_dir: str | Path | None) -> Path | None:
    if not output_dir:
        return None
    root = Path(output_dir)
    return root if root.exists() else None
