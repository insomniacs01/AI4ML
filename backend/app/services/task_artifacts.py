from __future__ import annotations

from datetime import datetime

from backend.app.core.config import Settings, get_settings
from backend.app.models.task import TaskRecord
from backend.app.services.task_artifact_index import (
    RunArtifactIndex,
    build_run_artifact_index as _build_run_artifact_index,
)


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
