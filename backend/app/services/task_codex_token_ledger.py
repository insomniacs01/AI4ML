from __future__ import annotations

import logging
from typing import Any

from backend.app.core.config import get_settings
from backend.app.core.supabase_auth import TeamAccessContext
from backend.app.models.task import TaskRecord, TokenUsageReport
from backend.app.services.codex_usage import read_codex_token_usage
from backend.app.services.governance_store import GovernanceStore
from backend.app.services.model_config import read_model_profile
from backend.app.services.quota_runtime_guard import quota_is_exhausted


logger = logging.getLogger(__name__)


def sync_codex_token_ledger(task_store: Any, task: TaskRecord, team_access: TeamAccessContext) -> bool:
    output_dir, usage = _codex_token_usage_source(task)
    if output_dir is None or usage is None:
        return False

    try:
        settings = get_settings()
        model_name = read_model_profile(settings)["display_name"]
        task_store.upsert_token_ledger(
            team_id=task.team_id,
            task_id=task.id,
            phase="codex",
            stage_key="codex_native",
            source_key=output_dir,
            usage=usage,
            access_token=team_access.access_token,
            user_id=team_access.user.id,
            connector_display_name=model_name,
            model_name=model_name,
            calculation_method="codex_app_server_token_usage",
        )
        quota = GovernanceStore(settings).get_member_quota(
            team_access.team_id,
            team_access.user.id,
            access_token=team_access.access_token,
        )
        return quota_is_exhausted(quota)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not sync Codex token ledger for task %s: %s", task.id, exc)
        return False


def _codex_token_usage_source(task: TaskRecord) -> tuple[str | None, TokenUsageReport | None]:
    if task.last_run:
        output_dir = task.last_run.output_dir
        usage = task.last_run.token_usage
    elif task.last_run_attempt:
        output_dir = task.last_run_attempt.output_dir
        usage = task.last_run_attempt.token_usage
    else:
        output_dir = None
        usage = None
    if usage is None:
        usage = read_codex_token_usage(output_dir)
    return output_dir, usage
