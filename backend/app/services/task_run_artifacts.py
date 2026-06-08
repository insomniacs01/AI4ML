from __future__ import annotations

from pathlib import Path

from backend.app.models.task import WorkflowStage
from backend.app.services.task_output_resolution import path_mtime


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


def _existing_root(output_dir: str | Path | None) -> Path | None:
    if not output_dir:
        return None
    root = Path(output_dir)
    return root if root.exists() else None
