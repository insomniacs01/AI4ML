from __future__ import annotations

from fastapi import FastAPI

from backend.app.api.routes.connectors import router as connector_router
from backend.app.api.routes.health import router as health_router
from backend.app.api.routes.model_config import router as model_config_router
from backend.app.api.routes.task_artifacts import router as task_artifact_router
from backend.app.api.routes.tasks import router as task_router
from backend.app.api.routes.team import router as team_router
from backend.app.api.routes.team_assets import router as team_asset_router
from backend.app.api.routes.team_quotas import router as team_quota_router
from backend.app.api.routes.team_routing import router as team_routing_router
from backend.app.api.routes.usage import router as usage_router
from backend.app.core.config import Settings


def register_api_routes(app: FastAPI, settings: Settings) -> None:
    app.include_router(health_router, prefix=settings.api_prefix)
    team_prefix = f"{settings.api_prefix}/teams/{{team_id}}"
    app.include_router(task_router, prefix=team_prefix)
    app.include_router(task_artifact_router, prefix=team_prefix)
    app.include_router(connector_router, prefix=team_prefix)
    app.include_router(model_config_router, prefix=team_prefix)
    app.include_router(team_asset_router, prefix=team_prefix)
    app.include_router(team_quota_router, prefix=team_prefix)
    app.include_router(team_routing_router, prefix=team_prefix)
    app.include_router(team_router, prefix=team_prefix)
    app.include_router(usage_router, prefix=team_prefix)
