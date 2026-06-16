from __future__ import annotations

from backend.app.core.config import get_settings
from backend.app.core.supabase_auth import TeamAccessContext
from backend.app.models.task import HumanInteractionRequestStatus, TaskRecord, WorkflowStage
from backend.app.services.codex_backend import codex_plan_text, codex_workspace_plan_path, read_codex_artifacts
from backend.app.services.service_registry import get_task_store
from backend.app.services.task_codex_human_gates import (
    CODEX_PLAN_APPROVAL_VERSION_ID,
    codex_improvement_review_version_id,
    has_confirmed_codex_plan_request,
    has_existing_codex_improvement_review_request,
    has_open_codex_plan_request,
)
from backend.app.services.task_codex_human_payloads import (
    build_codex_improvement_review_payload,
    build_codex_plan_approval_payload,
)
from backend.app.services.task_codex_improvement_review import (
    codex_improvement_plan_text,
    codex_workspace_improvement_plan_path,
)


def ensure_codex_plan_request(
    task: TaskRecord,
    team_access: TeamAccessContext,
    *,
    plan_path: str | None = None,
) -> None:
    task_store = get_task_store()
    if plan_path is None:
        plan_path = codex_workspace_plan_path(task, get_settings())
    existing = task_store.list_human_requests(task.team_id, task.id, access_token=team_access.access_token)
    if has_open_codex_plan_request(existing):
        return
    if has_confirmed_codex_plan_request(task, existing):
        return
    request_payload = build_codex_plan_approval_payload(
        task,
        plan_path=plan_path,
        plan_text=codex_plan_text(task, get_settings()),
        run_strategy=_codex_run_strategy(task),
    )
    request = task_store.create_human_request(
        team_id=task.team_id,
        task_id=task.id,
        stage=WorkflowStage.data_analysis,
        requested_by=team_access.user.id,
        assigned_to=team_access.user.id,
        assignee_type="member",
        assignee_value=team_access.user.id,
        version_id=CODEX_PLAN_APPROVAL_VERSION_ID,
        payload=request_payload,
        access_token=team_access.access_token,
    )
    request.status = HumanInteractionRequestStatus.open
    task_store.update_human_request(request, access_token=team_access.access_token)


def _codex_run_strategy(task: TaskRecord) -> dict | None:
    try:
        artifacts = read_codex_artifacts(task, get_settings())
    except Exception:
        return None
    run_strategy = artifacts.get("run_strategy")
    return run_strategy if isinstance(run_strategy, dict) else None


def ensure_codex_improvement_request(
    task: TaskRecord,
    team_access: TeamAccessContext,
    *,
    artifacts: dict | None = None,
    improvement_plan_path: str | None = None,
) -> None:
    task_store = get_task_store()
    if improvement_plan_path is None:
        improvement_plan_path = codex_workspace_improvement_plan_path(task, artifacts)
    improvement_plan_text = codex_improvement_plan_text(task, artifacts)
    if not improvement_plan_path and not improvement_plan_text.strip():
        return

    existing = task_store.list_human_requests(task.team_id, task.id, access_token=team_access.access_token)
    version_id = codex_improvement_review_version_id(improvement_plan_path)
    if has_existing_codex_improvement_review_request(existing, version_id=version_id):
        return

    request_payload = build_codex_improvement_review_payload(
        task,
        improvement_plan_path=improvement_plan_path,
        improvement_plan_text=improvement_plan_text,
        artifacts=artifacts,
    )

    request = task_store.create_human_request(
        team_id=task.team_id,
        task_id=task.id,
        stage=WorkflowStage.training_validation,
        requested_by=team_access.user.id,
        assigned_to=team_access.user.id,
        assignee_type="member",
        assignee_value=team_access.user.id,
        version_id=version_id,
        payload=request_payload,
        access_token=team_access.access_token,
    )
    request.status = HumanInteractionRequestStatus.open
    task_store.update_human_request(request, access_token=team_access.access_token)
