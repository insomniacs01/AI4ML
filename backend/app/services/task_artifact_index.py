from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from backend.app.core.config import Settings
from backend.app.models.task import TaskRecord
from backend.app.services.task_output_resolution import (
    latest_existing,
    recent_node_dirs,
    resolve_task_output_dir,
)


FEATURE_IMPORTANCE_FILENAMES = {
    "feature_importance.csv",
    "feature_importance.json",
    "feature_importances.csv",
    "feature_importances.json",
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
    settings: Settings,
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
    return RunArtifactIndex(
        requested_output_dir=requested_output_dir or output_dir,
        output_dir=output_dir,
        node_dirs=node_dirs,
        run_summary_path=latest_existing(_run_summary_candidates(output_dir, node_dirs)),
        leaderboard_path=latest_existing(_leaderboard_candidates(output_dir, node_dirs)),
        token_usage_path=latest_existing(_token_usage_candidates(output_dir, node_dirs)),
        generated_code_path=latest_existing(_generated_code_candidates(output_dir, node_dirs)),
        feature_importance_paths=find_feature_importance_paths(output_dir, node_dirs=node_dirs),
    )


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


def _run_summary_candidates(output_dir: Path, node_dirs: list[Path]) -> list[Path]:
    return [
        output_dir / "run_summary.json",
        output_dir / "output" / "metrics.json",
        output_dir / "best_run" / "output" / "run_summary.json",
        *(node_dir / "output" / "run_summary.json" for node_dir in node_dirs),
    ]


def _leaderboard_candidates(output_dir: Path, node_dirs: list[Path]) -> list[Path]:
    return [
        output_dir / "leaderboard.json",
        output_dir / "leaderboard.csv",
        output_dir / "best_run" / "output" / "leaderboard.json",
        output_dir / "best_run" / "output" / "leaderboard.csv",
        *(node_dir / "output" / "leaderboard.json" for node_dir in node_dirs),
        *(node_dir / "output" / "leaderboard.csv" for node_dir in node_dirs),
    ]


def _token_usage_candidates(output_dir: Path, node_dirs: list[Path]) -> list[Path]:
    return [
        output_dir / "token_usage.json",
        *(node_dir / "output" / "token_usage.json" for node_dir in node_dirs),
    ]


def _generated_code_candidates(output_dir: Path, node_dirs: list[Path]) -> list[Path]:
    return [
        output_dir / "generated_code.py",
        output_dir / "output" / "predict.py",
        output_dir / "output" / "code" / "final_modeling.py",
        output_dir / "best_run" / "generated_code.py",
        *(node_dir / "generated_code.py" for node_dir in node_dirs),
        *(node_dir / "states" / "python_code.py" for node_dir in node_dirs),
    ]
