from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.app.models.task import (
    TaskRecord,
    TaskRunProgressArtifactSummary,
    TaskRunProgressLeaderboardRow,
    TaskRunProgressResponse,
    TaskStatus,
)
from backend.app.services.codex_common import (
    latest_workspace_update,
    read_text,
    workspace_path_from_artifacts,
)
from backend.app.services.codex_metrics import (
    leaderboard_from_metrics,
    primary_metric,
    selected_model_metrics,
)
from backend.app.services.codex_overview import build_codex_overview_from_artifacts
from backend.app.services.codex_progress_state import (
    bootstrap_progress,
    codex_activity_text,
    codex_progress_percent,
    codex_response_status,
    codex_status,
    current_codex_stage,
)
from backend.app.services.codex_progress_timeline import (
    build_codex_progress_events,
    build_codex_progress_insights,
)
from backend.app.services.codex_usage import token_usage_from_artifacts


def build_codex_run_progress_response(task: TaskRecord, artifacts: dict[str, Any]) -> TaskRunProgressResponse:
    workspace = artifacts.get("workspace")
    progress = artifacts.get("progress") if isinstance(artifacts.get("progress"), dict) else {}
    if not progress and task.status == TaskStatus.running:
        progress = bootstrap_progress(workspace, artifacts)
    metrics = artifacts.get("metrics") if isinstance(artifacts.get("metrics"), dict) else {}
    workspace_path = workspace_path_from_artifacts(artifacts)
    status = codex_status(task, progress)
    response_status = codex_response_status(task, status, artifacts)
    current_stage = current_codex_stage(status, progress, artifacts)
    current_activity = codex_activity_text(task, progress, status, artifacts)
    percent = codex_progress_percent(task, progress, status, artifacts)
    latest_log_lines = _latest_codex_log_lines(Path(workspace_path)) if workspace_path else []
    leaderboard = leaderboard_from_metrics(metrics)
    overview = build_codex_overview_from_artifacts(artifacts)
    summary = _artifact_summary(artifacts, metrics, leaderboard, overview)
    insights = build_codex_progress_insights(progress, artifacts)
    events = build_codex_progress_events(progress, artifacts)

    return TaskRunProgressResponse(
        task=task,
        output_dir=workspace_path,
        status=response_status,
        progress_percent=percent.percent,
        progress_source=percent.source,
        progress_unavailable_reason=percent.unavailable_reason,
        current_stage=current_stage,
        current_activity=current_activity,
        observer_status="Codex",
        observer_detail=current_activity,
        observer_stage=current_stage,
        last_log_at=latest_workspace_update(Path(workspace_path)) if workspace_path else None,
        artifacts=summary,
        latest_log_lines=latest_log_lines,
        events=events,
        insights=insights,
        leaderboard=leaderboard,
        current_model=summary.best_model,
        completed_model_count=len(leaderboard) if leaderboard else None,
        total_model_count=len(leaderboard) if leaderboard else None,
        latest_validation_score=summary.metric_value,
        telemetry_note="Progress is read from the Codex-native AI4ML workspace.",
        codex_raw_progress=progress,
        codex_raw_steps=progress.get("steps") if isinstance(progress.get("steps"), list) else [],
        codex_workspace_path=workspace_path,
    )


def _artifact_summary(
    artifacts: dict[str, Any],
    metrics: dict[str, Any],
    leaderboard: list[TaskRunProgressLeaderboardRow],
    overview: dict[str, Any] | None = None,
) -> TaskRunProgressArtifactSummary:
    workspace_path = workspace_path_from_artifacts(artifacts)
    report = artifacts.get("report") if isinstance(artifacts.get("report"), dict) else {}
    predict = artifacts.get("predict") if isinstance(artifacts.get("predict"), dict) else {}
    overview_file = artifacts.get("overview_file") if isinstance(artifacts.get("overview_file"), dict) else {}
    token_usage = token_usage_from_artifacts(artifacts)
    selected = selected_model_metrics(metrics)
    metric_name, metric_value = primary_metric(selected, metrics)
    return TaskRunProgressArtifactSummary(
        has_run_summary=bool(metrics),
        has_leaderboard=bool(leaderboard),
        has_token_usage=token_usage is not None,
        has_generated_code=bool(predict.get("exists")),
        has_overview=bool(overview),
        run_summary_path=str(Path(workspace_path) / "output" / "metrics.json") if workspace_path and metrics else None,
        leaderboard_path=str(Path(workspace_path) / "output" / "metrics.json") if workspace_path and leaderboard else None,
        token_usage_path=str(Path(workspace_path) / "output" / "token_usage.json") if workspace_path and token_usage else None,
        generated_code_path=str(predict.get("path")) if predict.get("exists") else None,
        overview_path=str(overview_file.get("path")) if overview_file.get("exists") else None,
        best_model=str(selected.get("name")) if selected.get("name") else None,
        metric_name=metric_name,
        metric_value=metric_value,
        validation_score=metric_value,
        candidate_model_count=len(leaderboard) if leaderboard else None,
        error_log_path=str(Path(workspace_path) / "output" / "progress.json") if workspace_path else None,
        error_log_name="progress.json" if workspace_path else None,
    )


def _latest_codex_log_lines(workspace_path: Path) -> list[str]:
    candidates = [
        workspace_path / "output" / "progress.json",
        workspace_path / "output" / "report.md",
        workspace_path / "output" / "metrics.json",
    ]
    lines: list[str] = []
    for path in candidates:
        text = read_text(path)
        if text:
            lines.extend(f"{path.name}: {line}" for line in text.splitlines()[-20:])
    return lines[-80:]
