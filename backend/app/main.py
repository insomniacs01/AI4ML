from __future__ import annotations

import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.routes.connectors import router as connector_router
from backend.app.api.routes.health import router as health_router
from backend.app.api.routes.tasks import router as task_router
from backend.app.api.routes.team import router as team_router
from backend.app.api.routes.usage import router as usage_router
from backend.app.core.backend_instance import BackendInstanceAlreadyRunningError, acquire_backend_instance_lock
from backend.app.core.config import get_settings


settings = get_settings()
try:
    _backend_instance_lock = acquire_backend_instance_lock(settings)
except BackendInstanceAlreadyRunningError as exc:
    print(f"AI4ML backend startup blocked: {exc}", file=sys.stderr)
    raise SystemExit(1) from exc


app = FastAPI(title=settings.app_name, version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router, prefix=settings.api_prefix)
app.include_router(task_router, prefix=settings.api_prefix)
app.include_router(task_router, prefix=f"{settings.api_prefix}/teams/{{team_id}}")
app.include_router(connector_router, prefix=settings.api_prefix)
app.include_router(connector_router, prefix=f"{settings.api_prefix}/teams/{{team_id}}")
app.include_router(team_router, prefix=f"{settings.api_prefix}/team")
app.include_router(team_router, prefix=f"{settings.api_prefix}/teams/{{team_id}}")
app.include_router(usage_router, prefix=settings.api_prefix)
app.include_router(usage_router, prefix=f"{settings.api_prefix}/teams/{{team_id}}")
