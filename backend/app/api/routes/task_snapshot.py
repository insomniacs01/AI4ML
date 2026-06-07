from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.app.core.supabase_auth import TeamAccessContext, require_team_access
from backend.app.models.task import TaskRuntimeSnapshotResponse
from backend.app.services.task_runtime_snapshot import (
    TaskRuntimeSnapshotNotFound,
    TaskRuntimeSnapshotSyncError,
    build_task_runtime_snapshot_response,
)


router = APIRouter(tags=["task-lifecycle"])


@router.get("/{task_id}/runtime-snapshot", response_model=TaskRuntimeSnapshotResponse)
def get_task_runtime_snapshot(
    task_id: str,
    sync: bool = Query(True),
    team_access: TeamAccessContext = Depends(require_team_access),
) -> TaskRuntimeSnapshotResponse:
    try:
        return build_task_runtime_snapshot_response(task_id, team_access, sync_runtime=sync)
    except TaskRuntimeSnapshotNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except TaskRuntimeSnapshotSyncError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ConnectionError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
