from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse

from backend.app.api.errors import raise_code_workspace_http_error
from backend.app.core.config import get_settings
from backend.app.core.supabase_auth import TeamAccessContext, require_team_access, require_team_developer_access
from backend.app.models.task import (
    TaskAIConversationResponse,
    TaskCodeArtifactContentResponse,
    TaskCodeArtifactRerunRequest,
    TaskCodeArtifactRerunResponse,
    TaskCodeArtifactUpdateRequest,
    TaskCodeWorkspaceResponse,
    TaskModelReportResponse,
    TaskPredictionDemoRequest,
    TaskPredictionDemoResponse,
    TaskRecord,
)
from backend.app.services.service_registry import get_task_store
from backend.app.services.task_codex_sync import is_codex_task, sync_codex_task_state
from backend.app.services.task_ai_conversations import build_task_ai_conversations
from backend.app.services.task_code_workspace import (
    build_task_code_workspace,
    read_task_code_artifact,
    rerun_task_code_artifact,
    resolve_task_code_artifact_file,
    save_task_code_artifact,
)
from backend.app.services.task_prediction import build_prediction_demo_response
from backend.app.services.task_reporting import build_task_model_report


router = APIRouter(prefix="/tasks", tags=["task-artifacts"])


def _get_task_or_404(team_access: TeamAccessContext, task_id: str) -> TaskRecord:
    task = get_task_store().get_task(team_access.team_id, task_id, access_token=team_access.access_token)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    settings = get_settings()
    if is_codex_task(task, settings):
        task, _artifacts = sync_codex_task_state(
            task,
            settings,
            task_store=get_task_store(),
            access_token=team_access.access_token,
            fail_on_error=False,
        )
    return task


def _raise_code_workspace_http_error(exc: Exception) -> None:
    raise_code_workspace_http_error(exc)


@router.get("/{task_id}/ai-conversations", response_model=TaskAIConversationResponse)
def get_task_ai_conversations(
    task_id: str,
    team_access: TeamAccessContext = Depends(require_team_access),
) -> TaskAIConversationResponse:
    return build_task_ai_conversations(_get_task_or_404(team_access, task_id))


@router.get("/{task_id}/report", response_model=TaskModelReportResponse)
def get_task_model_report(
    task_id: str,
    team_access: TeamAccessContext = Depends(require_team_access),
) -> TaskModelReportResponse:
    return build_task_model_report(_get_task_or_404(team_access, task_id))


@router.post("/{task_id}/prediction-demo", response_model=TaskPredictionDemoResponse)
def run_task_prediction_demo(
    task_id: str,
    payload: TaskPredictionDemoRequest,
    team_access: TeamAccessContext = Depends(require_team_access),
) -> TaskPredictionDemoResponse:
    task = _get_task_or_404(team_access, task_id)
    return build_prediction_demo_response(task, payload)


@router.get("/{task_id}/code-workspace", response_model=TaskCodeWorkspaceResponse)
def get_task_code_workspace(
    task_id: str,
    team_access: TeamAccessContext = Depends(require_team_developer_access),
) -> TaskCodeWorkspaceResponse:
    return build_task_code_workspace(_get_task_or_404(team_access, task_id))


@router.get("/{task_id}/code-workspace/file", response_model=TaskCodeArtifactContentResponse)
def get_task_code_workspace_file(
    task_id: str,
    path: str = Query(..., min_length=1),
    team_access: TeamAccessContext = Depends(require_team_developer_access),
) -> TaskCodeArtifactContentResponse:
    task = _get_task_or_404(team_access, task_id)
    try:
        return read_task_code_artifact(task, path)
    except Exception as exc:  # noqa: BLE001
        _raise_code_workspace_http_error(exc)


@router.get("/{task_id}/code-workspace/download")
def download_task_code_workspace_file(
    task_id: str,
    path: str = Query(..., min_length=1),
    team_access: TeamAccessContext = Depends(require_team_developer_access),
) -> FileResponse:
    task = _get_task_or_404(team_access, task_id)
    try:
        artifact_path, entry = resolve_task_code_artifact_file(task, path)
        return FileResponse(
            path=str(artifact_path),
            filename=entry.name,
            media_type="application/octet-stream",
        )
    except Exception as exc:  # noqa: BLE001
        _raise_code_workspace_http_error(exc)


@router.put("/{task_id}/code-workspace/file", response_model=TaskCodeArtifactContentResponse)
def update_task_code_workspace_file(
    task_id: str,
    payload: TaskCodeArtifactUpdateRequest,
    team_access: TeamAccessContext = Depends(require_team_developer_access),
) -> TaskCodeArtifactContentResponse:
    task = _get_task_or_404(team_access, task_id)
    try:
        return save_task_code_artifact(task, payload)
    except Exception as exc:  # noqa: BLE001
        _raise_code_workspace_http_error(exc)


@router.post("/{task_id}/code-workspace/rerun", response_model=TaskCodeArtifactRerunResponse)
def rerun_task_code_workspace_file(
    task_id: str,
    payload: TaskCodeArtifactRerunRequest,
    team_access: TeamAccessContext = Depends(require_team_developer_access),
) -> TaskCodeArtifactRerunResponse:
    task = _get_task_or_404(team_access, task_id)
    try:
        return rerun_task_code_artifact(task, payload)
    except Exception as exc:  # noqa: BLE001
        _raise_code_workspace_http_error(exc)
