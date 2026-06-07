from __future__ import annotations

from backend.app.models.task import (
    TaskHumanCollaborationResponse,
    TaskHumanRequestRecord,
    TaskRecord,
    TaskStatus,
    WorkflowStageRecord,
)
from backend.app.services.task_human_access import can_actor_view_human_request
from backend.app.services.task_human_context import (
    build_task_human_guidance_preview,
    get_task_human_decision_history,
)
from backend.app.services.task_human_stages import is_active_request


def build_human_collaboration_snapshot(
    task: TaskRecord,
    *,
    stages: list[WorkflowStageRecord],
    requests: list[TaskHumanRequestRecord],
    actor_id: str | None = None,
    actor_role: str | None = None,
) -> TaskHumanCollaborationResponse:
    open_request_count = count_open_human_requests(requests)
    my_requests = visible_human_requests_for_actor(
        requests,
        actor_id=actor_id,
        actor_role=actor_role,
    )
    return TaskHumanCollaborationResponse(
        task=task,
        stages=stages,
        requests=requests,
        my_requests=my_requests,
        decision_history=get_task_human_decision_history(task),
        next_run_guidance=build_task_human_guidance_preview(task),
        open_request_count=open_request_count,
        my_open_request_count=count_open_human_requests(my_requests),
        can_resume=task.status in {TaskStatus.paused_for_review, TaskStatus.waiting_human}
        and open_request_count == 0,
    )


def count_open_human_requests(requests: list[TaskHumanRequestRecord]) -> int:
    return sum(1 for item in requests if is_active_request(item))


def visible_human_requests_for_actor(
    requests: list[TaskHumanRequestRecord],
    *,
    actor_id: str | None,
    actor_role: str | None,
) -> list[TaskHumanRequestRecord]:
    if not actor_id:
        return requests
    role = actor_role or ""
    return [
        request
        for request in requests
        if can_actor_view_human_request(request, actor_id=actor_id, actor_role=role)
    ]
