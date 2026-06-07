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
    can_actor_view_human_request,
    parse_candidate_pool,
    resolve_human_request_assignee,
)
from backend.app.services.task_human_context import (
    append_task_human_decision,
    build_task_human_guidance_preview,
    get_task_human_decision_history,
)
from backend.app.services.task_human_parameters import apply_human_decision_parameters
from backend.app.services.task_human_payloads import (
    build_human_decision_history_entry,
    build_human_decision_payload,
    build_human_request_payload,
    build_reassigned_decision_payload,
    build_reassigned_request_payload,
    is_rerun_decision_action,
    resolve_reassign_timeout,
)
from backend.app.services.task_human_stages import (
    HumanStageSnapshotBuilder,
    is_active_request,
    sort_stages,
    stage_key,
)
from backend.app.services.task_human_task_state import (
    apply_task_ready_for_human_rerun,
    apply_task_rerun_request,
    apply_task_resume_after_human,
    apply_task_waiting_for_human,
)
from backend.app.services.task_human_transitions import (
    READY_FOR_RERUN_ACTION,
    REQUEST_RERUN_AND_WAIT_ACTION,
    RESUME_TASK_ACTION,
    WAIT_FOR_HUMAN_ACTION,
    PostDecisionTaskAction,
    build_expired_human_decision_payload,
    resolve_human_decision_task_action,
    status_for_human_decision_action,
)
from backend.app.services.task_store import TaskStore


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
        requests = self._expire_overdue_requests(task, access_token=access_token)
        existing_records = {
            self._stage_key(record.stage): record
            for record in self.task_store.list_stage_records(task.team_id, task.id, access_token=access_token)
        }
        stages = self._stage_builder.build_stage_snapshot(
            task,
            existing_records=existing_records,
            requests=requests,
        )
        open_request_count = self._count_open_requests(requests)
        my_requests = self._filter_actor_requests(requests, actor_id=actor_id, actor_role=actor_role)
        my_open_request_count = self._count_open_requests(my_requests)
        return TaskHumanCollaborationResponse(
            task=task,
            stages=stages,
            requests=requests,
            my_requests=my_requests,
            decision_history=get_task_human_decision_history(task),
            next_run_guidance=build_task_human_guidance_preview(task),
            open_request_count=open_request_count,
            my_open_request_count=my_open_request_count,
            can_resume=task.status in {TaskStatus.paused_for_review, TaskStatus.waiting_human} and open_request_count == 0,
        )

    def sync_task_stages(
        self,
        task: TaskRecord,
        *,
        access_token: str,
        stage_selection_map: dict[str, TaskStageRoutingRecord] | None = None,
    ) -> list[WorkflowStageRecord]:
        self._expire_overdue_requests(task, access_token=access_token)
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
            raise RuntimeError("Current task run is still in progress. Wait until it finishes before creating a human collaboration request.")

        assignee_type, assignee_value, assigned_to = self.resolve_assignee(
            assignee_type=payload.assignee_type,
            assignee_value=payload.assignee_value,
            assigned_to=payload.assigned_to,
            default_member_id=requested_by,
            team_members=team_members or [TeamMemberRecord(team_id=task.team_id, user_id=requested_by, role=actor_role, member_status="active")],
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
        saved_task = self._mark_task_waiting(task, access_token=access_token, manual_hold=True)
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
        if self._is_overdue(request):
            expired_at = datetime.now(timezone.utc)
            request.status = HumanInteractionRequestStatus.expired
            request.decision = build_expired_human_decision_payload(expired_at=expired_at)
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
                team_members=team_members or [TeamMemberRecord(team_id=task.team_id, user_id=decided_by, role=actor_role, member_status="active")],
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
        saved_task = self._apply_post_decision_task_action(
            task,
            action=resolve_human_decision_task_action(
                payload.action,
                open_request_count=self._count_open_requests(remaining_requests),
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
        if self._count_open_requests(requests):
            raise RuntimeError("There are still open human collaboration requests for this task.")
        saved_task = self._resume_task_record(task, access_token=access_token)
        return self.get_snapshot(saved_task, access_token=access_token, actor_id=actor_id, actor_role=actor_role)

    def assert_task_can_run(self, task: TaskRecord, *, access_token: str) -> None:
        self._expire_overdue_requests(task, access_token=access_token)
        if task.status in {TaskStatus.paused_for_review, TaskStatus.waiting_human}:
            raise RuntimeError("Task is waiting for human collaboration. Resolve or resume it before running Codex.")
        requests = self.task_store.list_human_requests(task.team_id, task.id, access_token=access_token)
        if self._count_open_requests(requests):
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
        assignee_type, assignee_value, assigned_to = self.resolve_assignee(
            assignee_type=payload.reassign_assignee_type or request.assignee_type,
            assignee_value=payload.reassign_assignee_value,
            assigned_to=payload.reassign_assigned_to,
            default_member_id=decided_by,
            team_members=team_members,
        )
        now = datetime.now(timezone.utc)
        request.status = HumanInteractionRequestStatus.reassigned
        request.decision = build_reassigned_decision_payload(
            payload,
            decided_by=decided_by,
            actor_role=actor_role,
            decided_at=now,
            assignee_type=assignee_type,
            assignee_value=assignee_value,
            assigned_to=assigned_to,
        )
        self.task_store.update_human_request(request, access_token=access_token)

        timeout_at = resolve_reassign_timeout(
            request,
            reassign_timeout_minutes=payload.reassign_timeout_minutes,
            now=now,
        )
        reassigned_payload = build_reassigned_request_payload(
            request,
            payload,
            decided_by=decided_by,
            actor_role=actor_role,
        )
        version_seed = request.version_id or request.id
        self.task_store.create_human_request(
            team_id=task.team_id,
            task_id=task.id,
            stage=normalize_workflow_stage(request.stage),
            requested_by=decided_by,
            assigned_to=assigned_to,
            assignee_type=assignee_type.value,
            assignee_value=assignee_value,
            timeout_at=timeout_at,
            version_id=f"{version_seed}:reassigned:{int(now.timestamp())}",
            payload=reassigned_payload,
            access_token=access_token,
        )
        task = self._record_latest_decision(task, request=request, payload=payload)
        saved_task = self._mark_task_waiting(task, access_token=access_token, manual_hold=True)
        return self.get_snapshot(saved_task, access_token=access_token, actor_id=decided_by, actor_role=actor_role)

    def _expire_overdue_requests(self, task: TaskRecord, *, access_token: str) -> list[TaskHumanRequestRecord]:
        requests = self.task_store.list_human_requests(task.team_id, task.id, access_token=access_token)
        now = datetime.now(timezone.utc)
        expired_any = False
        for request in requests:
            if not self._is_active_request(request) or request.timeout_at is None:
                continue
            if request.timeout_at > now:
                continue
            request.status = HumanInteractionRequestStatus.expired
            request.decision = build_expired_human_decision_payload(expired_at=now)
            self.task_store.update_human_request(request, access_token=access_token)
            expired_any = True
        if not expired_any:
            return requests
        return self.task_store.list_human_requests(task.team_id, task.id, access_token=access_token)

    @staticmethod
    def _sort_stages(stages: list[WorkflowStageRecord]) -> list[WorkflowStageRecord]:
        return sort_stages(stages)

    @staticmethod
    def _count_open_requests(requests: list[TaskHumanRequestRecord]) -> int:
        return sum(1 for item in requests if TaskHumanCollaborationService._is_active_request(item))

    @staticmethod
    def _filter_actor_requests(
        requests: list[TaskHumanRequestRecord],
        *,
        actor_id: str | None,
        actor_role: str | None,
    ) -> list[TaskHumanRequestRecord]:
        if not actor_id:
            return requests
        return [
            request
            for request in requests
            if TaskHumanCollaborationService._is_request_visible_to_actor(
                request,
                actor_id=actor_id,
                actor_role=actor_role or "",
            )
        ]

    @staticmethod
    def _is_request_visible_to_actor(
        request: TaskHumanRequestRecord,
        *,
        actor_id: str,
        actor_role: str,
    ) -> bool:
        return can_actor_view_human_request(request, actor_id=actor_id, actor_role=actor_role)

    @staticmethod
    def _is_active_request(request: TaskHumanRequestRecord) -> bool:
        return is_active_request(request)

    @staticmethod
    def _is_overdue(request: TaskHumanRequestRecord) -> bool:
        return (
            request.timeout_at is not None
            and TaskHumanCollaborationService._is_active_request(request)
            and request.timeout_at <= datetime.now(timezone.utc)
        )

    @staticmethod
    def _parse_candidate_pool(value: str | None) -> list[str]:
        return parse_candidate_pool(value)

    @staticmethod
    def _assert_actor_can_decide(request: TaskHumanRequestRecord, *, actor_id: str, actor_role: str) -> None:
        assert_actor_can_decide_human_request(request, actor_id=actor_id, actor_role=actor_role)

    def _mark_task_waiting(
        self,
        task: TaskRecord,
        *,
        access_token: str,
        manual_hold: bool,
    ) -> TaskRecord:
        apply_task_waiting_for_human(
            task,
            manual_hold=manual_hold,
            updated_at=datetime.now(timezone.utc),
        )
        return self.task_store.save_task(task, access_token=access_token)

    def _mark_task_rerun_requested(self, task: TaskRecord, *, reason: str, rerun_from_stage: str | None = None) -> None:
        apply_task_rerun_request(
            task,
            reason=reason,
            rerun_from_stage=rerun_from_stage,
            requested_at=datetime.now(timezone.utc),
        )

    def _mark_task_ready_for_rerun(
        self,
        task: TaskRecord,
        *,
        access_token: str,
        reason: str,
        rerun_from_stage: str | None = None,
    ) -> TaskRecord:
        apply_task_ready_for_human_rerun(
            task,
            reason=reason,
            rerun_from_stage=rerun_from_stage,
            updated_at=datetime.now(timezone.utc),
        )
        return self.task_store.save_task(task, access_token=access_token)

    def _apply_post_decision_task_action(
        self,
        task: TaskRecord,
        *,
        action: PostDecisionTaskAction,
        access_token: str,
        reason: str,
        rerun_from_stage: str | None = None,
    ) -> TaskRecord:
        if action == WAIT_FOR_HUMAN_ACTION:
            return self._mark_task_waiting(task, access_token=access_token, manual_hold=True)
        if action == READY_FOR_RERUN_ACTION:
            return self._mark_task_ready_for_rerun(
                task,
                access_token=access_token,
                reason=reason,
                rerun_from_stage=rerun_from_stage,
            )
        if action == REQUEST_RERUN_AND_WAIT_ACTION:
            self._mark_task_rerun_requested(task, reason=reason, rerun_from_stage=rerun_from_stage)
            return self._mark_task_waiting(task, access_token=access_token, manual_hold=True)
        if action == RESUME_TASK_ACTION:
            return self._resume_task_record(task, access_token=access_token)
        raise RuntimeError(f"unsupported post decision task action: {action}")

    def _resume_task_record(self, task: TaskRecord, *, access_token: str) -> TaskRecord:
        apply_task_resume_after_human(task, resumed_at=datetime.now(timezone.utc))
        return self.task_store.save_task(task, access_token=access_token)

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
