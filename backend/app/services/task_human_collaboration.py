from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.app.models.governance import TeamMemberRecord
from backend.app.models.task import (
    HumanInteractionDecisionAction,
    HumanInteractionRequestStatus,
    InteractionAssigneeType,
    TaskHumanCollaborationResponse,
    TaskHumanRequestCreateRequest,
    TaskHumanRequestDecisionRequest,
    TaskHumanRequestRecord,
    TaskRecord,
    TaskStageRoutingRecord,
    TaskStatus,
    WorkflowStage,
    WorkflowStageRecord,
    normalize_workflow_stage,
)
from backend.app.services.task_human_access import (
    ResolvedHumanAssignee,
    assert_actor_can_decide_human_request,
    parse_candidate_pool,
    resolve_human_request_assignee,
)
from backend.app.services.task_human_context import (
    append_task_human_decision,
)
from backend.app.services.task_human_expiration import (
    expire_human_request,
    expire_overdue_human_requests,
    is_overdue_human_request,
)
from backend.app.services.task_human_parameters import apply_human_decision_parameters
from backend.app.services.task_human_payloads import (
    build_human_decision_history_entry,
    build_human_decision_payload,
    build_human_request_payload,
    is_rerun_decision_action,
)
from backend.app.services.task_human_post_decision import (
    apply_post_decision_task_action,
    save_task_resume_after_human,
    save_task_waiting_for_human,
)
from backend.app.services.task_human_reassignment import reassign_human_request
from backend.app.services.task_human_stages import (
    HumanStageSnapshotBuilder,
    is_active_request,
    sort_stages,
    stage_key,
)
from backend.app.services.task_human_snapshot import (
    build_human_collaboration_snapshot,
    count_open_human_requests,
)
from backend.app.services.task_human_transitions import (
    resolve_human_decision_task_action,
    status_for_human_decision_action,
)
from backend.app.services.task_store import TaskStore


RUNNING_TASK_HUMAN_REQUEST_ERROR = (
    "Current task run is still in progress. "
    "Wait until it finishes before creating a human collaboration request."
)


class TaskHumanCollaborationService:
    def __init__(self, task_store: TaskStore) -> None:
        self.task_store = task_store
        self._stage_builder = HumanStageSnapshotBuilder()

    def get_snapshot(
        self,
        task: TaskRecord,
        *,
        access_token: str,
        actor_id: str | None = None,
        actor_role: str | None = None,
    ) -> TaskHumanCollaborationResponse:
        requests = expire_overdue_human_requests(self.task_store, task, access_token=access_token)
        existing_records = {
            self._stage_key(record.stage): record
            for record in self.task_store.list_stage_records(task.team_id, task.id, access_token=access_token)
        }
        stages = self._stage_builder.build_stage_snapshot(
            task,
            existing_records=existing_records,
            requests=requests,
        )
        return build_human_collaboration_snapshot(
            task,
            stages=stages,
            requests=requests,
            actor_id=actor_id,
            actor_role=actor_role,
        )

    def sync_task_stages(
        self,
        task: TaskRecord,
        *,
        access_token: str,
        stage_selection_map: dict[str, TaskStageRoutingRecord] | None = None,
    ) -> list[WorkflowStageRecord]:
        expire_overdue_human_requests(self.task_store, task, access_token=access_token)
        existing_records = {
            self._stage_key(record.stage): record
            for record in self.task_store.list_stage_records(task.team_id, task.id, access_token=access_token)
        }
        requests = self.task_store.list_human_requests(task.team_id, task.id, access_token=access_token)
        normalized_selection_map = {
            self._stage_key(stage_key): value
            for stage_key, value in (stage_selection_map or {}).items()
        }

        synced_records: list[WorkflowStageRecord] = []
        for item in self._stage_builder.iter_stage_snapshot_inputs(
            task,
            existing_records=existing_records,
            requests=requests,
            selection_map=normalized_selection_map,
        ):
            synced_records.append(
                self.task_store.upsert_stage_record(
                    team_id=task.team_id,
                    task_id=task.id,
                    stage=item.stage,
                    status=item.status,
                    access_token=access_token,
                    selected_connector_id=item.selected_connector_id,
                    model_name=item.model_name,
                    selection_source=item.selection_source,
                    summary=item.summary,
                    artifact_refs=item.artifact_refs,
                )
            )

        return self._sort_stages(synced_records)

    def create_request(
        self,
        task: TaskRecord,
        payload: TaskHumanRequestCreateRequest,
        *,
        requested_by: str,
        access_token: str,
        actor_role: str = "admin",
        team_members: list[TeamMemberRecord] | None = None,
    ) -> TaskHumanCollaborationResponse:
        if task.status == TaskStatus.running:
            raise RuntimeError(RUNNING_TASK_HUMAN_REQUEST_ERROR)

        assignee_type, assignee_value, assigned_to = self.resolve_assignee(
            assignee_type=payload.assignee_type,
            assignee_value=payload.assignee_value,
            assigned_to=payload.assigned_to,
            default_member_id=requested_by,
            team_members=team_members or [self._default_team_member(task, user_id=requested_by, role=actor_role)],
        )

        timeout_at = None
        if payload.timeout_minutes is not None:
            timeout_at = datetime.now(timezone.utc) + timedelta(minutes=payload.timeout_minutes)

        self.task_store.create_human_request(
            team_id=task.team_id,
            task_id=task.id,
            stage=normalize_workflow_stage(payload.stage),
            requested_by=requested_by,
            assigned_to=assigned_to,
            assignee_type=assignee_type.value,
            assignee_value=assignee_value,
            timeout_at=timeout_at,
            payload=build_human_request_payload(payload, actor_role=actor_role),
            access_token=access_token,
        )
        saved_task = save_task_waiting_for_human(
            self.task_store,
            task,
            access_token=access_token,
            manual_hold=True,
        )
        return self.get_snapshot(saved_task, access_token=access_token, actor_id=requested_by, actor_role=actor_role)

    def submit_decision(
        self,
        task: TaskRecord,
        request_id: str,
        payload: TaskHumanRequestDecisionRequest,
        *,
        decided_by: str,
        access_token: str,
        actor_role: str = "admin",
        team_members: list[TeamMemberRecord] | None = None,
    ) -> TaskHumanCollaborationResponse:
        request = self.task_store.get_human_request(task.team_id, task.id, request_id, access_token=access_token)
        if request is None:
            raise ValueError("human request not found")
        now = datetime.now(timezone.utc)
        if is_overdue_human_request(request, now=now):
            expire_human_request(request, expired_at=now)
            self.task_store.update_human_request(request, access_token=access_token)
            raise RuntimeError("human request has expired")
        if not self._is_active_request(request):
            raise RuntimeError("human request has already been closed")

        self._assert_actor_can_decide(request, actor_id=decided_by, actor_role=actor_role)

        if payload.action == HumanInteractionDecisionAction.reassign:
            return self._reassign_request(
                task,
                request,
                payload,
                decided_by=decided_by,
                actor_role=actor_role,
                team_members=team_members or [self._default_team_member(task, user_id=decided_by, role=actor_role)],
                access_token=access_token,
            )

        request.status = status_for_human_decision_action(payload.action)
        requires_rerun = is_rerun_decision_action(payload.action)
        rerun_from_stage = self._stage_key(request.stage) if requires_rerun else None
        request.decision = build_human_decision_payload(
            payload,
            decided_by=decided_by,
            actor_role=actor_role,
            decided_at=datetime.now(timezone.utc),
            requires_rerun=requires_rerun,
            rerun_from_stage=rerun_from_stage,
        )
        apply_human_decision_parameters(task, request, payload, decided_by=decided_by)
        self.task_store.update_human_request(request, access_token=access_token)

        task = self._record_latest_decision(task, request=request, payload=payload)
        remaining_requests = self.task_store.list_human_requests(task.team_id, task.id, access_token=access_token)
        saved_task = apply_post_decision_task_action(
            self.task_store,
            task,
            action=resolve_human_decision_task_action(
                payload.action,
                open_request_count=count_open_human_requests(remaining_requests),
                resume_task=payload.resume_task,
            ),
            access_token=access_token,
            reason=payload.decision_summary,
            rerun_from_stage=rerun_from_stage,
        )

        return self.get_snapshot(saved_task, access_token=access_token, actor_id=decided_by, actor_role=actor_role)

    def resume_task(
        self,
        task: TaskRecord,
        *,
        access_token: str,
        actor_id: str | None = None,
        actor_role: str | None = None,
    ) -> TaskHumanCollaborationResponse:
        requests = self.task_store.list_human_requests(task.team_id, task.id, access_token=access_token)
        if count_open_human_requests(requests):
            raise RuntimeError("There are still open human collaboration requests for this task.")
        saved_task = save_task_resume_after_human(self.task_store, task, access_token=access_token)
        return self.get_snapshot(saved_task, access_token=access_token, actor_id=actor_id, actor_role=actor_role)

    def assert_task_can_run(self, task: TaskRecord, *, access_token: str) -> None:
        expire_overdue_human_requests(self.task_store, task, access_token=access_token)
        if task.status in {TaskStatus.paused_for_review, TaskStatus.waiting_human}:
            raise RuntimeError("Task is waiting for human collaboration. Resolve or resume it before running Codex.")
        requests = self.task_store.list_human_requests(task.team_id, task.id, access_token=access_token)
        if count_open_human_requests(requests):
            raise RuntimeError("Task has open human collaboration requests. Resolve them before running Codex.")

    def resolve_assignee(
        self,
        *,
        assignee_type: InteractionAssigneeType | str | None,
        assignee_value: str | None,
        assigned_to: str | None,
        default_member_id: str,
        team_members: list[TeamMemberRecord],
    ) -> ResolvedHumanAssignee:
        return resolve_human_request_assignee(
            assignee_type=assignee_type,
            assignee_value=assignee_value,
            assigned_to=assigned_to,
            default_member_id=default_member_id,
            team_members=team_members,
        )

    @staticmethod
    def _default_team_member(task: TaskRecord, *, user_id: str, role: str) -> TeamMemberRecord:
        return TeamMemberRecord(
            team_id=task.team_id,
            user_id=user_id,
            role=role,
            member_status="active",
        )

    def _reassign_request(
        self,
        task: TaskRecord,
        request: TaskHumanRequestRecord,
        payload: TaskHumanRequestDecisionRequest,
        *,
        decided_by: str,
        actor_role: str,
        team_members: list[TeamMemberRecord],
        access_token: str,
    ) -> TaskHumanCollaborationResponse:
        assignee = self.resolve_assignee(
            assignee_type=payload.reassign_assignee_type or request.assignee_type,
            assignee_value=payload.reassign_assignee_value,
            assigned_to=payload.reassign_assigned_to,
            default_member_id=decided_by,
            team_members=team_members,
        )
        updated_request = reassign_human_request(
            self.task_store,
            task,
            request,
            payload,
            assignee=assignee,
            decided_by=decided_by,
            actor_role=actor_role,
            access_token=access_token,
        )
        task = self._record_latest_decision(task, request=updated_request, payload=payload)
        saved_task = save_task_waiting_for_human(
            self.task_store,
            task,
            access_token=access_token,
            manual_hold=True,
        )
        return self.get_snapshot(saved_task, access_token=access_token, actor_id=decided_by, actor_role=actor_role)

    @staticmethod
    def _sort_stages(stages: list[WorkflowStageRecord]) -> list[WorkflowStageRecord]:
        return sort_stages(stages)

    @staticmethod
    def _is_active_request(request: TaskHumanRequestRecord) -> bool:
        return is_active_request(request)

    @staticmethod
    def _parse_candidate_pool(value: str | None) -> list[str]:
        return parse_candidate_pool(value)

    @staticmethod
    def _assert_actor_can_decide(request: TaskHumanRequestRecord, *, actor_id: str, actor_role: str) -> None:
        assert_actor_can_decide_human_request(request, actor_id=actor_id, actor_role=actor_role)

    def _record_latest_decision(
        self,
        task: TaskRecord,
        *,
        request: TaskHumanRequestRecord,
        payload: TaskHumanRequestDecisionRequest,
    ) -> TaskRecord:
        decision_entry = build_human_decision_history_entry(
            request,
            payload,
            updated_at=datetime.now(timezone.utc),
        )
        append_task_human_decision(task, decision_entry)
        return task

    @staticmethod
    def _stage_key(stage: WorkflowStage | str) -> str:
        return stage_key(stage)
