from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.app.services.codex_common import iso_from_mtime, read_json, read_text
from backend.app.services.codex_progress_store import ensure_progress_snapshot, progress_events_path, read_progress_events


def read_codex_workspace_artifacts(workspace: Path) -> dict[str, Any]:
    output_dir = workspace / "output"
    progress_path = output_dir / "progress.json"
    run_strategy_path = output_dir / "run_strategy.json"
    improvement_plan_path = output_dir / "improvement_plan.md"
    advisor_request_path = output_dir / "advisor_request.json"
    advisor_diagnosis_path = output_dir / "advisor_diagnosis.json"
    progress_payload = ensure_progress_snapshot(workspace, current_progress=read_json(progress_path))
    events_path = progress_events_path(workspace)
    progress_events = read_progress_events(workspace)
    return {
        "workspace": workspace_metadata(workspace),
        "plan": read_text(output_dir / "plan.md"),
        "run_strategy": read_json(run_strategy_path),
        "progress": progress_payload,
        "progress_events": progress_events,
        "progress_file": {
            **file_status(progress_path),
            "readable": progress_payload is not None,
        },
        "progress_events_file": {
            **file_status(events_path),
            "readable": events_path.is_file(),
        },
        "metrics": read_json(output_dir / "metrics.json"),
        "overview": read_json(output_dir / "overview.json"),
        "token_usage": read_json(output_dir / "token_usage.json"),
        "improvement_plan": read_text(improvement_plan_path),
        "advisor_request": read_json(advisor_request_path),
        "advisor_diagnosis": read_json(advisor_diagnosis_path),
        "run_strategy_file": file_status(run_strategy_path),
        "improvement_plan_file": file_status(improvement_plan_path, include_modified_at=True),
        "advisor_request_file": file_status(advisor_request_path),
        "advisor_diagnosis_file": file_status(advisor_diagnosis_path),
        "overview_file": file_status(output_dir / "overview.json"),
        "report": file_status(output_dir / "report.md"),
        "predict": file_status(output_dir / "predict.py"),
    }


def read_codex_workspace_overview_artifacts(workspace: Path) -> dict[str, Any]:
    output_dir = workspace / "output"
    return {
        "workspace": workspace_metadata(workspace),
        "metrics": read_json(output_dir / "metrics.json"),
        "overview": read_json(output_dir / "overview.json"),
        "overview_file": file_status(output_dir / "overview.json"),
    }


def workspace_metadata(workspace: Path) -> dict[str, Any]:
    return {
        "name": workspace.name,
        "path": str(workspace),
        "modifiedAt": iso_from_mtime(workspace),
    }


def file_status(path: Path, *, include_modified_at: bool = False) -> dict[str, Any]:
    exists = path.is_file()
    status: dict[str, Any] = {
        "path": str(path),
        "exists": exists,
    }
    if include_modified_at:
        status["modifiedAt"] = iso_from_mtime(path) if exists else None
    return status
