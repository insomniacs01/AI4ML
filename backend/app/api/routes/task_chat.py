from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from backend.app.core.config import get_settings
from backend.app.core.supabase_auth import TeamAccessContext, require_team_access
from backend.app.models.task import (
    TaskInteractiveChatRequest,
    TaskInteractiveChatResponse,
    WorkflowStage,
)
from backend.app.services.service_registry import get_task_store
from backend.app.services.task_ai_conversations import build_task_ai_conversations
from backend.app.services.task_chat import send_task_chat_message
from backend.app.services.task_routing import (
    _assert_quota_allows_action,
    _build_runtime_context,
    _build_runtime_settings_for_selection,
    _resolve_preferred_selection,
)


router = APIRouter(tags=["task-runtime"])


@router.post("/{task_id}/chat", response_model=TaskInteractiveChatResponse)
def send_task_chat(
    task_id: str,
    payload: TaskInteractiveChatRequest,
    team_access: TeamAccessContext = Depends(require_team_access),
) -> TaskInteractiveChatResponse:
    _assert_quota_allows_action(team_access, action_name="任务 AI 对话")
    task_store = get_task_store()
    task = task_store.get_task(team_access.team_id, task_id, access_token=team_access.access_token)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")

    runtime_context = _build_runtime_context(team_access)
    chat_stages = [WorkflowStage.report_generation] if task.last_run else [
        WorkflowStage.data_analysis,
        WorkflowStage.requirement_analysis,
    ]
    selection = _resolve_preferred_selection(task, team_access, runtime_context, chat_stages)
    runtime_settings = _build_runtime_settings_for_selection(get_settings(), selection)

    try:
        chat_result = send_task_chat_message(task, prompt=payload.prompt, settings=runtime_settings)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    saved_task = task_store.save_task(chat_result.task, access_token=team_access.access_token)
    task_store.upsert_token_ledger(
        team_id=saved_task.team_id,
        task_id=saved_task.id,
        phase="interactive_chat",
        stage_key=selection.stage.value,
        source_key=chat_result.assistant_message.id,
        usage=chat_result.token_usage,
        access_token=team_access.access_token,
        user_id=team_access.user.id,
        connector_id=selection.connector.id,
        connector_display_name=selection.connector.display_name,
        model_name=selection.model_name,
        calculation_method=chat_result.token_usage_calculation_method or "provider_reported_usage",
    )
    return TaskInteractiveChatResponse(
        task=saved_task,
        conversation=build_task_ai_conversations(saved_task),
    )
