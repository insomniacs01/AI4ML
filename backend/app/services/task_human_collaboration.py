from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, NamedTuple

from backend.app.core.supabase_auth import TEAM_ADMIN_ROLES
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
from backend.app.services.task_human_context import (
    append_task_human_decision,
    build_task_human_guidance_preview,
    ensure_task_human_loop,
    get_task_human_decision_history,
    get_task_human_loop,
)
from backend.app.services.task_human_parameters import apply_human_decision_parameters
from backend.app.services.task_human_stages import (
    HumanStageSnapshotBuilder,
    get_previous_status,
    is_active_request,
    sort_stages,
    stage_key,
)
from backend.app.services.task_store import TaskStore


RERUN_DECISION_ACTIONS = {
    HumanInteractionDecisionAction.revise,
    HumanInteractionDecisionAction.reject,
}


class ResolvedHumanAssignee(NamedTuple):
    assignee_type: InteractionAssigneeType
    assignee_value: str
    assigned_to: str | None


class PostDecisionTaskAction(str, Enum):
    wait_for_human = "wait_for_human"
    ready_for_rerun = "ready_for_rerun"
    request_rerun_and_wait = "request_rerun_and_wait"
    resume_task = "resume_task"


WAIT_FOR_HUMAN_ACTION = PostDecisionTaskAction.wait_for_human
READY_FOR_RERUN_ACTION = PostDecisionTaskAction.ready_for_rerun
REQUEST_RERUN_AND_WAIT_ACTION = PostDecisionTaskAction.request_rerun_and_wait
RESUME_TASK_ACTION = PostDecisionTaskAction.resume_task


def resolve_human_decision_task_action(
    action: HumanInteractionDecisionAction,
    *,
    open_request_count: int,
    resume_task: bool,
) -> PostDecisionTaskAction:
    if open_request_count > 0:
        return WAIT_FOR_HUMAN_ACTION
    if action == HumanInteractionDecisionAction.block:
        return WAIT_FOR_HUMAN_ACTION
    if action in RERUN_DECISION_ACTIONS and resume_task:
        return READY_FOR_RERUN_ACTION
    if action in RERUN_DECISION_ACTIONS:
        return REQUEST_RERUN_AND_WAIT_ACTION
    if resume_task:
        return RESUME_TASK_ACTION
    return WAIT_FOR_HUMAN_ACTION


def parse_candidate_pool(value: str | None) -> list[str]:
    return [
        item.strip()
        for item in str(value or "").replace(";", ",").split(",")
        if item.strip()
    ]


def resolve_human_request_assignee(
    *,
    assignee_type: InteractionAssigneeType | str | None,
    assignee_value: str | None,
    assigned_to: str | None,
    default_member_id: str,
    team_members: list[TeamMemberRecord],
) -> ResolvedHumanAssignee:
    resolved_type = assignee_type or InteractionAssigneeType.member
    if not isinstance(resolved_type, InteractionAssigneeType):
        resolved_type = InteractionAssigneeType(str(resolved_type))

    resolved_value = (assignee_value or assigned_to or default_member_id or "").strip()
    if not resolved_value:
        raise RuntimeError("human request assignee is required")

    active_members = [item for item in team_members if item.member_status == "active"]
    active_member_ids = {item.user_id for item in active_members}
    active_roles = {str(item.role) for item in active_members}

    if resolved_type == InteractionAssigneeType.member:
        if resolved_value not in active_member_ids:
            raise RuntimeError("human request assignee member is not an active member of this team")
        return ResolvedHumanAssignee(resolved_type, resolved_value, resolved_value)

    if resolved_type == InteractionAssigneeType.role:
        if resolved_value not in active_roles:
            raise RuntimeError("human request assignee role has no active member in this team")
        return ResolvedHumanAssignee(resolved_type, resolved_value, None)

    if resolved_type == InteractionAssigneeType.candidate_pool:
        if not parse_candidate_pool(resolved_value):
            raise RuntimeError("human request candidate pool is empty")
        return ResolvedHumanAssignee(resolved_type, resolved_value, None)

    raise RuntimeError(f"unsupported human request assignee type: {resolved_type}")


def can_actor_view_human_request(
    request: TaskHumanRequestRecord,
    *,
    actor_id: str,
    actor_role: str,
) -> bool:
    if actor_id == request.requested_by:
        return True
    if request.assignee_type == InteractionAssigneeType.member:
        return actor_id in {request.assigned_to, request.assignee_value}
    if request.assignee_type == InteractionAssigneeType.role:
        return actor_role == request.assignee_value
    if request.assignee_type == InteractionAssigneeType.candidate_pool:
        candidates = set(parse_candidate_pool(request.assignee_value))
        return actor_id in candidates or actor_role in candidates
    return False


def human_request_decision_denial_reason(
    request: TaskHumanRequestRecord,
    *,
    actor_id: str,
    actor_role: str,
) -> str | None:
    if actor_role in TEAM_ADMIN_ROLES:
        return None
    if request.assignee_type == InteractionAssigneeType.member:
        if actor_id in {request.assigned_to, request.assignee_value}:
            return None
        return "Only the assigned member or a team admin can decide this human request."
    if request.assignee_type == InteractionAssigneeType.role:
        if actor_role == request.assignee_value:
            return None
        return "Only members with the assigned role or a team admin can decide this human request."
    if request.assignee_type == InteractionAssigneeType.candidate_pool:
        candidates = set(parse_candidate_pool(request.assignee_value))
        if actor_id in candidates or actor_role in candidates:
            return None
        return "Only a candidate-pool member or a team admin can decide this human request."
    if actor_id == request.requested_by:
        return None
    return "Only the request owner, assignee, or a team admin can decide this human request."


def assert_actor_can_decide_human_request(
    request: TaskHumanRequestRecord,
    *,
    actor_id: str,
    actor_role: str,
) -> None:
    denial_reason = human_request_decision_denial_reason(request, actor_id=actor_id, actor_role=actor_role)
    if denial_reason is not None:
        raise PermissionError(denial_reason)


def build_human_request_payload(payload: TaskHumanRequestCreateRequest, *, actor_role: str) -> dict[str, Any]:
    return {
        "request_type": payload.request_type,
        "title": payload.title,
        "summary": payload.summary,
        "suggested_action": payload.suggested_action,
        "artifact_paths": payload.artifact_paths,
        "details": payload.details,
        "created_by_role": actor_role,
    }


def build_human_decision_payload(
    payload: TaskHumanRequestDecisionRequest,
    *,
    decided_by: str,
    actor_role: str,
    decided_at: datetime,
    requires_rerun: bool,
    rerun_from_stage: str | None,
) -> dict[str, Any]:
    return {
        "action": payload.action.value,
        "summary": payload.decision_summary,
        "artifact_paths": payload.artifact_paths,
        "details": payload.details,
        "decided_by": decided_by,
        "decided_by_role": actor_role,
        "decided_at": decided_at.isoformat(),
        "requires_rerun": requires_rerun,
        "rerun_from_stage": rerun_from_stage,
    }


def build_reassigned_decision_payload(
    payload: TaskHumanRequestDecisionRequest,
    *,
    decided_by: str,
    actor_role: str,
    decided_at: datetime,
    assignee_type: InteractionAssigneeType,
    assignee_value: str,
    assigned_to: str | None,
) -> dict[str, Any]:
    return {
        "action": payload.action.value,
        "summary": payload.decision_summary,
        "artifact_paths": payload.artifact_paths,
        "details": payload.details,
        "decided_by": decided_by,
        "decided_by_role": actor_role,
        "decided_at": decided_at.isoformat(),
        "reassigned_to": {
            "assignee_type": assignee_type.value,
            "assignee_value": assignee_value,
            "assigned_to": assigned_to,
        },
    }


def build_reassigned_request_payload(
    request: TaskHumanRequestRecord,
    payload: TaskHumanRequestDecisionRequest,
    *,
    decided_by: str,
    actor_role: str,
) -> dict[str, Any]:
    request_payload = request.payload if isinstance(request.payload, dict) else {}
    return {
        **request_payload,
        "reassigned_from_request_id": request.id,
        "reassigned_by": decided_by,
        "reassigned_by_role": actor_role,
        "reassign_reason": payload.decision_summary,
        "previous_assignee_type": request.assignee_type.value if request.assignee_type else None,
        "previous_assignee_value": request.assignee_value,
    }


def resolve_reassign_timeout(
    request: TaskHumanRequestRecord,
    *,
    reassign_timeout_minutes: int | None,
    now: datetime,
) -> datetime | None:
    if reassign_timeout_minutes is not None:
        return now + timedelta(minutes=reassign_timeout_minutes)
    if request.timeout_at and request.timeout_at > now:
        return request.timeout_at
    return None


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
            request.status = HumanInteractionRequestStatus.expired
            request.decision = {
                "action": "expired",
                "summary": "Request expired before a human decision was submitted.",
                "decided_at": datetime.now(timezone.utc).isoformat(),
            }
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

        request.status = self._status_for_decision_action(payload.action)
        requires_rerun = payload.action in RERUN_DECISION_ACTIONS
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
            request.decision = {
                "action": "expired",
                "summary": "Request expired before a human decision was submitted.",
                "decided_at": now.isoformat(),
            }
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

    @staticmethod
    def _status_for_decision_action(action: HumanInteractionDecisionAction) -> HumanInteractionRequestStatus:
        if action == HumanInteractionDecisionAction.approve:
            return HumanInteractionRequestStatus.confirmed
        if action == HumanInteractionDecisionAction.revise:
            return HumanInteractionRequestStatus.modified
        if action in {HumanInteractionDecisionAction.block, HumanInteractionDecisionAction.reject}:
            return HumanInteractionRequestStatus.rejected
        if action == HumanInteractionDecisionAction.skip:
            return HumanInteractionRequestStatus.skipped
        raise RuntimeError(f"unsupported human decision action: {action}")

    def _mark_task_waiting(
        self,
        task: TaskRecord,
        *,
        access_token: str,
        manual_hold: bool,
    ) -> TaskRecord:
        human_loop = self._ensure_human_loop(task)
        if task.status not in {TaskStatus.paused_for_review, TaskStatus.waiting_human}:
            human_loop["previous_status"] = task.status.value
        human_loop["manual_hold"] = manual_hold
        human_loop["updated_at"] = datetime.now(timezone.utc).isoformat()
        task.status = TaskStatus.paused_for_review
        return self.task_store.save_task(task, access_token=access_token)

    def _mark_task_rerun_requested(self, task: TaskRecord, *, reason: str, rerun_from_stage: str | None = None) -> None:
        human_loop = self._ensure_human_loop(task)
        human_loop["rerun_requested"] = True
        human_loop["rerun_reason"] = reason
        if rerun_from_stage:
            human_loop["rerun_from_stage"] = rerun_from_stage
        human_loop["rerun_requested_at"] = datetime.now(timezone.utc).isoformat()
        human_loop["manual_hold"] = False
        human_loop["updated_at"] = datetime.now(timezone.utc).isoformat()

    def _mark_task_ready_for_rerun(
        self,
        task: TaskRecord,
        *,
        access_token: str,
        reason: str,
        rerun_from_stage: str | None = None,
    ) -> TaskRecord:
        self._mark_task_rerun_requested(task, reason=reason, rerun_from_stage=rerun_from_stage)
        task.status = TaskStatus.uploaded if task.dataset_filename else TaskStatus.draft
        task.notes = f"人工协同要求重新运行：{reason}"
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
        human_loop = self._ensure_human_loop(task)
        human_loop["manual_hold"] = False
        human_loop["resumed_at"] = datetime.now(timezone.utc).isoformat()
        task.status = self._get_previous_status(task)
        return self.task_store.save_task(task, access_token=access_token)

    def _get_previous_status(self, task: TaskRecord) -> TaskStatus:
        return get_previous_status(task)

    def _record_latest_decision(
        self,
        task: TaskRecord,
        *,
        request: TaskHumanRequestRecord,
        payload: TaskHumanRequestDecisionRequest,
    ) -> TaskRecord:
        request_payload = request.payload if isinstance(request.payload, dict) else {}
        resolved_artifact_paths = payload.artifact_paths
        if not resolved_artifact_paths and isinstance(request_payload.get("artifact_paths"), list):
            resolved_artifact_paths = [str(item).strip() for item in request_payload.get("artifact_paths", []) if str(item).strip()]
        decision_entry = {
            "request_id": request.id,
            "stage": self._stage_key(request.stage),
            "action": payload.action.value,
            "title": request_payload.get("title"),
            "request_type": request_payload.get("request_type"),
            "request_summary": request_payload.get("summary"),
            "suggested_action": request_payload.get("suggested_action"),
            "decision_summary": payload.decision_summary,
            "artifact_paths": resolved_artifact_paths,
            "decision_details": payload.details,
            "resume_task": payload.resume_task,
            "requires_rerun": payload.action in RERUN_DECISION_ACTIONS,
            "reassign_assignee_type": payload.reassign_assignee_type.value if payload.reassign_assignee_type else None,
            "reassign_assignee_value": payload.reassign_assignee_value,
            "reassign_assigned_to": payload.reassign_assigned_to,
            "decided_by": request.decision.get("decided_by") if isinstance(request.decision, dict) else None,
            "decided_at": request.decision.get("decided_at") if isinstance(request.decision, dict) else datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        append_task_human_decision(task, decision_entry)
        return task

    @staticmethod
    def _stage_key(stage: WorkflowStage | str) -> str:
        return stage_key(stage)

    @staticmethod
    def _read_human_loop(task: TaskRecord) -> dict[str, Any]:
        return get_task_human_loop(task)

    @staticmethod
    def _ensure_human_loop(task: TaskRecord) -> dict[str, Any]:
        return ensure_task_human_loop(task)
