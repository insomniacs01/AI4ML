from __future__ import annotations

from typing import Any

from backend.app.models.task import (
    TaskAgentEventRecord,
    TaskAgentMessageRecord,
    TaskAgentRuntimeRecord,
    WorkflowStage,
    WorkflowStageStatus,
)


class TaskStoreAgentMixin:
    def list_agent_runs(self, team_id: str, task_id: str, *, access_token: str) -> list[TaskAgentRuntimeRecord]:
        return self.agent_repository.list_agent_runs(team_id, task_id, access_token=access_token)

    def upsert_agent_run(
        self,
        *,
        team_id: str,
        task_id: str,
        agent_id: str,
        stage: WorkflowStage,
        name: str,
        role: str,
        short_role: str,
        status: WorkflowStageStatus,
        progress: int,
        current_task: str,
        access_token: str,
        selected_connector_id: str | None = None,
        model_name: str | None = None,
        selection_source: str | None = None,
        artifact_refs: Any | None = None,
        log_excerpt: str | None = None,
        worker_id: str | None = None,
    ) -> TaskAgentRuntimeRecord:
        return self.agent_repository.upsert_agent_run(
            team_id=team_id,
            task_id=task_id,
            agent_id=agent_id,
            stage=stage,
            name=name,
            role=role,
            short_role=short_role,
            status=status,
            progress=progress,
            current_task=current_task,
            access_token=access_token,
            selected_connector_id=selected_connector_id,
            model_name=model_name,
            selection_source=selection_source,
            artifact_refs=artifact_refs,
            log_excerpt=log_excerpt,
            worker_id=worker_id,
        )

    def list_agent_events(
        self,
        team_id: str,
        task_id: str,
        *,
        access_token: str,
        limit: int = 80,
    ) -> list[TaskAgentEventRecord]:
        return self.agent_repository.list_agent_events(team_id, task_id, access_token=access_token, limit=limit)

    def append_agent_event(
        self,
        *,
        team_id: str,
        task_id: str,
        agent_id: str,
        stage: WorkflowStage,
        kind: str,
        status: str,
        text: str,
        access_token: str,
        artifact_refs: Any | None = None,
    ) -> TaskAgentEventRecord:
        return self.agent_repository.append_agent_event(
            team_id=team_id,
            task_id=task_id,
            agent_id=agent_id,
            stage=stage,
            kind=kind,
            status=status,
            text=text,
            access_token=access_token,
            artifact_refs=artifact_refs,
        )

    def list_agent_messages(
        self,
        team_id: str,
        task_id: str,
        *,
        access_token: str,
        limit: int = 120,
    ) -> list[TaskAgentMessageRecord]:
        return self.agent_repository.list_agent_messages(team_id, task_id, access_token=access_token, limit=limit)

    def append_agent_message(
        self,
        *,
        team_id: str,
        task_id: str,
        from_agent_id: str,
        stage: WorkflowStage,
        message_type: str,
        content: str,
        access_token: str,
        to_agent_id: str | None = None,
        status: str = "sent",
        payload: dict[str, Any] | None = None,
        artifact_refs: Any | None = None,
        correlation_id: str | None = None,
    ) -> TaskAgentMessageRecord:
        return self.agent_repository.append_agent_message(
            team_id=team_id,
            task_id=task_id,
            from_agent_id=from_agent_id,
            stage=stage,
            message_type=message_type,
            content=content,
            access_token=access_token,
            to_agent_id=to_agent_id,
            status=status,
            payload=payload,
            artifact_refs=artifact_refs,
            correlation_id=correlation_id,
        )
