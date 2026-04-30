from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, Depends

from backend.app.core.config import get_settings
from backend.app.core.supabase_auth import TeamAccessContext, require_team_access
from backend.app.models.task import TeamTokenUsageResponse
from backend.app.services.task_store import TaskStore
from backend.app.services.token_usage import build_team_token_usage_response


router = APIRouter(prefix="/usage", tags=["usage"])


@lru_cache
def get_task_store() -> TaskStore:
    return TaskStore(get_settings())


@router.get("", response_model=TeamTokenUsageResponse)
def get_team_token_usage(
    team_access: TeamAccessContext = Depends(require_team_access),
) -> TeamTokenUsageResponse:
    tasks = get_task_store().list_tasks(team_access.team_id, access_token=team_access.access_token)
    return build_team_token_usage_response(team_access.team_id, tasks)
