from __future__ import annotations

from fastapi import FastAPI

from backend.app.api.router import register_api_routes
from backend.app.core.config import Settings


def test_team_member_routes_remain_registered_under_team_prefix() -> None:
    app = FastAPI()
    register_api_routes(app, Settings(AI4ML_SUPABASE_URL="", AI4ML_SUPABASE_PUBLISHABLE_KEY=""))
    route_methods = {
        (method, route.path)
        for route in app.routes
        for method in getattr(route, "methods", set())
    }

    assert ("GET", "/api/teams/{team_id}/members") in route_methods
    assert ("POST", "/api/teams/{team_id}/members/invite") in route_methods
    assert ("PATCH", "/api/teams/{team_id}/members/{member_id}/role") in route_methods
    assert ("PATCH", "/api/teams/{team_id}/members/{member_id}/status") in route_methods
