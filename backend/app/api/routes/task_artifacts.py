from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse

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
from backend.app.services.governance_store import GovernanceStore
from backend.app.services.task_ai_conversations import build_task_ai_conversations
from backend.app.services.task_code_workspace import (
    build_task_code_workspace,
    read_task_code_artifact,
    rerun_task_code_artifact,
    resolve_task_code_artifact_file,
    save_task_code_artifact,
)
from backend.app.services.task_reporting import build_prediction_demo_response, build_task_model_report
from backend.app.services.task_store import TaskStore


router = APIRouter(prefix="/tasks", tags=["task-artifacts"])


@lru_cache
def get_task_store() -> TaskStore:
    return TaskStore(get_settings())


@lru_cache
def get_governance_store() -> GovernanceStore:
    return GovernanceStore(get_settings())


def _get_task_or_404(team_access: TeamAccessContext, task_id: str) -> TaskRecord:
    task = get_task_store().get_task(team_access.team_id, task_id, access_token=team_access.access_token)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    return task


def _write_task_audit(
    team_access: TeamAccessContext,
    *,
    action: str,
    task_id: str,
    detail: dict | None = None,
    resource_type: str = "ai_task",
) -> None:
    try:
        get_governance_store().create_audit_log(
            team_access.team_id,
            team_access.user.id,
            action=action,
            resource_type=resource_type,
            resource_id=task_id,
            detail=detail or {},
            access_token=team_access.access_token,
        )
    except (RuntimeError, PermissionError, ConnectionError):
        pass


def _raise_code_workspace_http_error(exc: Exception) -> None:
    if isinstance(exc, FileNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, PermissionError):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if isinstance(exc, RuntimeError):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


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
    response = build_prediction_demo_response(task, payload)
    _write_task_audit(
        team_access,
        action="task.prediction_demo.run",
        task_id=task.id,
        detail={
            "supported": response.supported,
            "feature_count": len(payload.features),
            "detail": response.detail,
        },
    )
    return response


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
        _write_task_audit(
            team_access,
            action="task.code_workspace.download",
            task_id=task.id,
            detail={
                "path": entry.path,
                "size_bytes": entry.size_bytes,
                "run_output_dir": str(artifact_path.parent),
            },
        )
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
        result = save_task_code_artifact(task, payload)
        _write_task_audit(
            team_access,
            action="task.code_workspace.save",
            task_id=task.id,
            detail={
                "path": result.artifact.path,
                "size_bytes": result.artifact.size_bytes,
                "version_id": result.version_id,
            },
        )
        return result
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
        result = rerun_task_code_artifact(task, payload)
        _write_task_audit(
            team_access,
            action="task.code_workspace.rerun",
            task_id=task.id,
            detail={
                "path": result.path,
                "success": result.success,
                "exit_code": result.exit_code,
                "version_id": result.version_id,
            },
        )
        return result
    except Exception as exc:  # noqa: BLE001
        _raise_code_workspace_http_error(exc)
