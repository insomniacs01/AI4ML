from __future__ import annotations

from fastapi import FastAPI

from backend.app.api.router import register_api_routes
from backend.app.core.config import Settings


def test_task_run_route_remains_registered_under_task_prefix() -> None:
    app = FastAPI()
    register_api_routes(app, Settings(AI4ML_SUPABASE_URL="", AI4ML_SUPABASE_PUBLISHABLE_KEY=""))
    route_methods = {
        (method, route.path)
        for route in app.routes
        for method in getattr(route, "methods", set())
    }

    assert ("POST", "/api/teams/{team_id}/tasks/{task_id}/run") in route_methods
