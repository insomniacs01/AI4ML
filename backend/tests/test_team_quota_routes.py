from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI

from backend.app.api.router import register_api_routes
from backend.app.api.routes.team_quotas import token_ledger_totals
from backend.app.core.config import Settings
from backend.app.models.governance import TokenLedgerRecord


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _ledger(total_tokens: int, input_tokens: int, output_tokens: int) -> TokenLedgerRecord:
    return TokenLedgerRecord(
        id=f"ledger-{total_tokens}",
        team_id="team-1",
        phase="codex",
        source_key=f"source-{total_tokens}",
        total_tokens=total_tokens,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        created_at=NOW,
        updated_at=NOW,
    )


def test_token_ledger_totals_sums_token_fields() -> None:
    totals = token_ledger_totals(
        [
            _ledger(total_tokens=10, input_tokens=4, output_tokens=6),
            _ledger(total_tokens=20, input_tokens=8, output_tokens=12),
        ]
    )

    assert totals == {
        "total_tokens": 30,
        "input_tokens": 12,
        "output_tokens": 18,
    }


def test_team_quota_routes_remain_registered_under_team_prefix() -> None:
    app = FastAPI()
    register_api_routes(app, Settings(AI4ML_SUPABASE_URL="", AI4ML_SUPABASE_PUBLISHABLE_KEY=""))
    route_paths = {route.path for route in app.routes}

    assert "/api/teams/{team_id}/quotas" in route_paths
    assert "/api/teams/{team_id}/quotas/adjust" in route_paths
    assert "/api/teams/{team_id}/quotas/{member_id}/adjust" in route_paths
    assert "/api/teams/{team_id}/token-ledgers" in route_paths
