from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.app.core.supabase_auth import TEAM_ADMIN_ROLES
from backend.app.models.governance import TeamMemberRecord
from backend.app.models.task import (
    HumanInteractionDecisionAction,
    HumanInteractionRequestStatus,
    InteractionAssigneeType,
    PRIMARY_WORKFLOW_STAGES,
    TaskHumanCollaborationResponse,
    TaskHumanRequestCreateRequest,
    TaskHumanRequestDecisionRequest,
    TaskHumanRequestRecord,
    TaskRecord,
    TaskStageRoutingRecord,
    TaskStatus,
    WorkflowStage,
    WorkflowStageRecord,
    WorkflowStageStatus,
    normalize_workflow_stage,
)
from backend.app.services.task_human_context import (
    append_task_human_decision,
    build_task_human_guidance_preview,
    ensure_task_human_loop,
    get_task_human_decision_history,
    get_task_human_loop,
)
from backend.app.services.task_store import TaskStore


STAGE_ORDER = list(PRIMARY_WORKFLOW_STAGES)
ACTIVE_REQUEST_STATUSES = {
    HumanInteractionRequestStatus.pending,
    HumanInteractionRequestStatus.open,
}
RERUN_DECISION_ACTIONS = {
    HumanInteractionDecisionAction.revise,
    HumanInteractionDecisionAction.reject,
}


@dataclass(frozen=True)
class _StageBlueprint:
    stage: WorkflowStage
    status: WorkflowStageStatus
    summary: str


class TaskHumanCollaborationService:
    def __init__(self, task_store: TaskStore) -> None:
        self.task_store = task_store

    def get_snapshot(self, task: TaskRecord, *, access_token: str) -> TaskHumanCollaborationResponse:
        self._expire_overdue_requests(task, access_token=access_token)
        stages = self.sync_task_stages(task, access_token=access_token)
        requests = self.task_store.list_human_requests(task.team_id, task.id, access_token=access_token)
        open_request_count = self._count_open_requests(requests)
        return TaskHumanCollaborationResponse(
            task=task,
            stages=stages,
            requests=requests,
            decision_history=get_task_human_decision_history(task),
            next_run_guidance=build_task_human_guidance_preview(task),
            open_request_count=open_request_count,
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
        open_requests_by_stage = {
            self._stage_key(request.stage): request
            for request in requests
            if self._is_active_request(request)
        }

        normalized_selection_map = {
            self._stage_key(stage_key): value
            for stage_key, value in (stage_selection_map or {}).items()
        }

        synced_records: list[WorkflowStageRecord] = []
        for blueprint in self._build_stage_blueprints(task):
            stage_key = self._stage_key(blueprint.stage)
            existing = existing_records.get(stage_key)
            open_request = open_requests_by_stage.get(stage_key)
            selection = normalized_selection_map.get(stage_key)
            synced_records.append(
                self.task_store.upsert_stage_record(
                    team_id=task.team_id,
                    task_id=task.id,
                    stage=blueprint.stage,
                    status=WorkflowStageStatus.waiting_human if open_request else blueprint.status,
                    access_token=access_token,
                    selected_connector_id=(
                        selection.connector_id
                        if selection is not None and selection.connector_id is not None
                        else existing.selected_connector_id if existing else None
                    ),
                    model_name=(
                        selection.model_name
                        if selection is not None and selection.model_name is not None
                        else existing.model_name if existing else None
                    ),
                    selection_source=(
                        selection.selection_source
                        if selection is not None and selection.selection_source is not None
                        else existing.selection_source if existing else None
                    ),
                    summary=self._build_waiting_summary(open_request) if open_request else blueprint.summary,
                    artifact_refs=self._collect_stage_artifacts(task, blueprint.stage),
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
            payload={
                "request_type": payload.request_type,
                "title": payload.title,
                "summary": payload.summary,
                "suggested_action": payload.suggested_action,
                "artifact_paths": payload.artifact_paths,
                "details": payload.details,
                "created_by_role": actor_role,
            },
            access_token=access_token,
        )
        saved_task = self._mark_task_waiting(task, access_token=access_token, manual_hold=True)
        return self.get_snapshot(saved_task, access_token=access_token)

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
        request.decision = {
            "action": payload.action.value,
            "summary": payload.decision_summary,
            "artifact_paths": payload.artifact_paths,
            "details": payload.details,
            "decided_by": decided_by,
            "decided_by_role": actor_role,
            "decided_at": datetime.now(timezone.utc).isoformat(),
            "requires_rerun": requires_rerun,
            "rerun_from_stage": rerun_from_stage,
        }
        self.task_store.update_human_request(request, access_token=access_token)

        task = self._record_latest_decision(task, request=request, payload=payload)
        remaining_requests = self.task_store.list_human_requests(task.team_id, task.id, access_token=access_token)
        if self._count_open_requests(remaining_requests):
            saved_task = self._mark_task_waiting(task, access_token=access_token, manual_hold=True)
        elif payload.action == HumanInteractionDecisionAction.block:
            saved_task = self._mark_task_waiting(task, access_token=access_token, manual_hold=True)
        elif requires_rerun and payload.resume_task:
            saved_task = self._mark_task_ready_for_rerun(
                task,
                access_token=access_token,
                reason=payload.decision_summary,
                rerun_from_stage=rerun_from_stage,
            )
        elif requires_rerun:
            self._mark_task_rerun_requested(task, reason=payload.decision_summary, rerun_from_stage=rerun_from_stage)
            saved_task = self._mark_task_waiting(task, access_token=access_token, manual_hold=True)
        elif payload.resume_task:
            saved_task = self._resume_task_record(task, access_token=access_token)
        else:
            saved_task = self._mark_task_waiting(task, access_token=access_token, manual_hold=True)

        return self.get_snapshot(saved_task, access_token=access_token)

    def resume_task(self, task: TaskRecord, *, access_token: str) -> TaskHumanCollaborationResponse:
        requests = self.task_store.list_human_requests(task.team_id, task.id, access_token=access_token)
        if self._count_open_requests(requests):
            raise RuntimeError("There are still open human collaboration requests for this task.")
        saved_task = self._resume_task_record(task, access_token=access_token)
        return self.get_snapshot(saved_task, access_token=access_token)

    def assert_task_can_run(self, task: TaskRecord, *, access_token: str) -> None:
        self._expire_overdue_requests(task, access_token=access_token)
        if task.status in {TaskStatus.paused_for_review, TaskStatus.waiting_human}:
            raise RuntimeError("Task is waiting for human collaboration. Resolve or resume it before running MLZero.")
        requests = self.task_store.list_human_requests(task.team_id, task.id, access_token=access_token)
        if self._count_open_requests(requests):
            raise RuntimeError("Task has open human collaboration requests. Resolve them before running MLZero.")

    def resolve_assignee(
        self,
        *,
        assignee_type: InteractionAssigneeType | str | None,
        assignee_value: str | None,
        assigned_to: str | None,
        default_member_id: str,
        team_members: list[TeamMemberRecord],
    ) -> tuple[InteractionAssigneeType, str, str | None]:
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
            return resolved_type, resolved_value, resolved_value

        if resolved_type == InteractionAssigneeType.role:
            if resolved_value not in active_roles:
                raise RuntimeError("human request assignee role has no active member in this team")
            return resolved_type, resolved_value, None

        if resolved_type == InteractionAssigneeType.candidate_pool:
            if not self._parse_candidate_pool(resolved_value):
                raise RuntimeError("human request candidate pool is empty")
            return resolved_type, resolved_value, None

        raise RuntimeError(f"unsupported human request assignee type: {resolved_type}")

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
        request.decision = {
            "action": payload.action.value,
            "summary": payload.decision_summary,
            "artifact_paths": payload.artifact_paths,
            "details": payload.details,
            "decided_by": decided_by,
            "decided_by_role": actor_role,
            "decided_at": now.isoformat(),
            "reassigned_to": {
                "assignee_type": assignee_type.value,
                "assignee_value": assignee_value,
                "assigned_to": assigned_to,
            },
        }
        self.task_store.update_human_request(request, access_token=access_token)

        timeout_at = None
        if payload.reassign_timeout_minutes is not None:
            timeout_at = now + timedelta(minutes=payload.reassign_timeout_minutes)
        elif request.timeout_at and request.timeout_at > now:
            timeout_at = request.timeout_at

        request_payload = request.payload if isinstance(request.payload, dict) else {}
        reassigned_payload = {
            **request_payload,
            "reassigned_from_request_id": request.id,
            "reassigned_by": decided_by,
            "reassigned_by_role": actor_role,
            "reassign_reason": payload.decision_summary,
            "previous_assignee_type": request.assignee_type.value if request.assignee_type else None,
            "previous_assignee_value": request.assignee_value,
        }
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
        return self.get_snapshot(saved_task, access_token=access_token)

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

    def _build_stage_blueprints(self, task: TaskRecord) -> list[_StageBlueprint]:
        effective_status = self._get_progress_status(task)

        requirement_status = WorkflowStageStatus.completed if task.dataset_filename else WorkflowStageStatus.pending
        requirement_summary = (
            "Task description and dataset are available for the next steps."
            if task.dataset_filename
            else "Waiting for task creation details and CSV upload."
        )

        if task.label_column and task.problem_type:
            data_status = WorkflowStageStatus.completed
            data_summary = f"Detected label column '{task.label_column}' and task type '{task.problem_type}'."
        elif task.dataset_filename:
            data_status = WorkflowStageStatus.running if effective_status in {TaskStatus.planning, TaskStatus.uploaded} else WorkflowStageStatus.pending
            data_summary = "Dataset is uploaded. Waiting for AI analysis to infer label column, problem type, and metric."
        else:
            data_status = WorkflowStageStatus.pending
            data_summary = "No dataset is available for AI data analysis yet."

        feature_status = self._build_generation_stage_status(task, effective_status)
        feature_summary = self._build_generation_stage_summary(
            task,
            effective_status,
            pending_summary="Feature engineering has not started yet.",
            completed_summary="A recent MLZero attempt already produced code and intermediate artifacts.",
        )

        model_status = self._build_generation_stage_status(task, effective_status)
        model_summary = self._build_generation_stage_summary(
            task,
            effective_status,
            pending_summary="Model selection has not started yet.",
            completed_summary="A recent MLZero attempt already explored at least one model candidate.",
        )

        if effective_status == TaskStatus.running:
            training_status = WorkflowStageStatus.running
            training_summary = "MLZero is training and validating candidate models."
        elif effective_status == TaskStatus.failed and task.last_run_attempt:
            training_status = WorkflowStageStatus.failed
            training_summary = task.notes or "The latest training or validation attempt failed."
        elif task.last_run:
            training_status = WorkflowStageStatus.completed
            metric_label = task.last_run.metric_name or "validation_score"
            training_summary = f"The latest run completed with {metric_label} = {task.last_run.metric_value}."
        else:
            training_status = WorkflowStageStatus.pending
            training_summary = "Training and validation have not started yet."

        if task.status == TaskStatus.published:
            report_status = WorkflowStageStatus.completed
            report_summary = "The latest report has already been published."
        elif task.last_run:
            report_status = WorkflowStageStatus.completed if effective_status == TaskStatus.completed else WorkflowStageStatus.pending
            report_summary = f"The latest report is ready for review. Best model: {task.last_run.best_model}."
        elif task.last_run_attempt:
            report_status = WorkflowStageStatus.pending
            report_summary = "Artifacts exist from the latest attempt, but a final report is not ready yet."
        else:
            report_status = WorkflowStageStatus.pending
            report_summary = "Report generation has not started yet."

        blueprints = [
            _StageBlueprint(
                stage=WorkflowStage.requirement_analysis,
                status=requirement_status,
                summary=requirement_summary,
            ),
            _StageBlueprint(
                stage=WorkflowStage.data_analysis,
                status=data_status,
                summary=data_summary,
            ),
            _StageBlueprint(
                stage=WorkflowStage.feature_engineering,
                status=feature_status,
                summary=feature_summary,
            ),
            _StageBlueprint(
                stage=WorkflowStage.model_selection,
                status=model_status,
                summary=model_summary,
            ),
            _StageBlueprint(
                stage=WorkflowStage.training_validation,
                status=training_status,
                summary=training_summary,
            ),
            _StageBlueprint(
                stage=WorkflowStage.report_generation,
                status=report_status,
                summary=report_summary,
            ),
        ]
        return self._apply_rerun_stage_hint(task, blueprints)

    def _apply_rerun_stage_hint(self, task: TaskRecord, blueprints: list[_StageBlueprint]) -> list[_StageBlueprint]:
        human_loop = self._read_human_loop(task)
        if not human_loop.get("rerun_requested"):
            return blueprints
        raw_stage = human_loop.get("rerun_from_stage")
        if not isinstance(raw_stage, str) or not raw_stage:
            return blueprints
        try:
            rerun_stage = normalize_workflow_stage(raw_stage)
        except ValueError:
            return blueprints
        order_index = {stage.value: index for index, stage in enumerate(STAGE_ORDER)}
        rerun_index = order_index.get(rerun_stage.value)
        if rerun_index is None:
            return blueprints
        reason = human_loop.get("rerun_reason")
        next_blueprints: list[_StageBlueprint] = []
        for blueprint in blueprints:
            current_index = order_index.get(blueprint.stage.value, len(order_index))
            if current_index >= rerun_index:
                next_blueprints.append(
                    _StageBlueprint(
                        stage=blueprint.stage,
                        status=WorkflowStageStatus.pending,
                        summary=(
                            f"人工协同要求从“{blueprint.stage.value}”所在链路重新运行。"
                            + (f"原因：{reason}" if isinstance(reason, str) and reason else "")
                        ),
                    )
                )
            else:
                next_blueprints.append(blueprint)
        return next_blueprints

    @staticmethod
    def _build_generation_stage_status(task: TaskRecord, effective_status: TaskStatus) -> WorkflowStageStatus:
        if effective_status == TaskStatus.running:
            return WorkflowStageStatus.running
        if task.last_run or task.last_run_attempt:
            return WorkflowStageStatus.completed
        return WorkflowStageStatus.pending

    @staticmethod
    def _build_generation_stage_summary(
        task: TaskRecord,
        effective_status: TaskStatus,
        *,
        pending_summary: str,
        completed_summary: str,
    ) -> str:
        if effective_status == TaskStatus.running:
            return "MLZero is actively generating or refining training logic."
        if task.last_run or task.last_run_attempt:
            return completed_summary
        return pending_summary

    def _collect_stage_artifacts(self, task: TaskRecord, stage: WorkflowStage) -> list[str]:
        artifacts: list[str] = []
        if stage in {WorkflowStage.requirement_analysis, WorkflowStage.data_analysis} and task.dataset_path:
            artifacts.append(task.dataset_path)
        if stage in {
            WorkflowStage.feature_engineering,
            WorkflowStage.model_selection,
            WorkflowStage.training_validation,
            WorkflowStage.report_generation,
        }:
            if task.last_run_attempt and task.last_run_attempt.output_dir:
                artifacts.append(task.last_run_attempt.output_dir)
            elif task.last_run and task.last_run.output_dir:
                artifacts.append(task.last_run.output_dir)
        return artifacts

    @staticmethod
    def _build_waiting_summary(request: TaskHumanRequestRecord | None) -> str:
        if request is None or not isinstance(request.payload, dict):
            return "Waiting for human review."
        title = request.payload.get("title")
        summary = request.payload.get("summary")
        if isinstance(title, str) and isinstance(summary, str) and summary.strip():
            return f"{title.strip()}: {summary.strip()}"
        if isinstance(title, str) and title.strip():
            return title.strip()
        if isinstance(summary, str) and summary.strip():
            return summary.strip()
        return "Waiting for human review."

    @staticmethod
    def _sort_stages(stages: list[WorkflowStageRecord]) -> list[WorkflowStageRecord]:
        order_index = {stage.value: index for index, stage in enumerate(STAGE_ORDER)}
        return sorted(stages, key=lambda item: order_index.get(TaskHumanCollaborationService._stage_key(item.stage), len(order_index)))

    @staticmethod
    def _count_open_requests(requests: list[TaskHumanRequestRecord]) -> int:
        return sum(1 for item in requests if TaskHumanCollaborationService._is_active_request(item))

    @staticmethod
    def _is_active_request(request: TaskHumanRequestRecord) -> bool:
        return request.status in ACTIVE_REQUEST_STATUSES

    @staticmethod
    def _is_overdue(request: TaskHumanRequestRecord) -> bool:
        return (
            request.timeout_at is not None
            and TaskHumanCollaborationService._is_active_request(request)
            and request.timeout_at <= datetime.now(timezone.utc)
        )

    @staticmethod
    def _parse_candidate_pool(value: str | None) -> list[str]:
        return [
            item.strip()
            for item in str(value or "").replace(";", ",").split(",")
            if item.strip()
        ]

    @staticmethod
    def _assert_actor_can_decide(request: TaskHumanRequestRecord, *, actor_id: str, actor_role: str) -> None:
        if actor_role in TEAM_ADMIN_ROLES:
            return
        if request.assignee_type == InteractionAssigneeType.member:
            if actor_id in {request.assigned_to, request.assignee_value}:
                return
            raise PermissionError("Only the assigned member or a team admin can decide this human request.")
        if request.assignee_type == InteractionAssigneeType.role:
            if actor_role == request.assignee_value:
                return
            raise PermissionError("Only members with the assigned role or a team admin can decide this human request.")
        if request.assignee_type == InteractionAssigneeType.candidate_pool:
            candidates = set(TaskHumanCollaborationService._parse_candidate_pool(request.assignee_value))
            if actor_id in candidates or actor_role in candidates:
                return
            raise PermissionError("Only a candidate-pool member or a team admin can decide this human request.")
        if actor_id == request.requested_by:
            return
        raise PermissionError("Only the request owner, assignee, or a team admin can decide this human request.")

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

    def _get_progress_status(self, task: TaskRecord) -> TaskStatus:
        if task.status not in {TaskStatus.paused_for_review, TaskStatus.waiting_human}:
            return task.status
        return self._get_previous_status(task)

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

    def _resume_task_record(self, task: TaskRecord, *, access_token: str) -> TaskRecord:
        human_loop = self._ensure_human_loop(task)
        human_loop["manual_hold"] = False
        human_loop["resumed_at"] = datetime.now(timezone.utc).isoformat()
        task.status = self._get_previous_status(task)
        return self.task_store.save_task(task, access_token=access_token)

    def _get_previous_status(self, task: TaskRecord) -> TaskStatus:
        human_loop = self._read_human_loop(task)
        if human_loop.get("rerun_requested"):
            if task.dataset_filename:
                return TaskStatus.uploaded
            return TaskStatus.draft
        raw_status = human_loop.get("previous_status") if human_loop else None
        if isinstance(raw_status, str):
            try:
                parsed = TaskStatus(raw_status)
            except ValueError:
                parsed = None
            if parsed is not None and parsed not in {TaskStatus.paused_for_review, TaskStatus.waiting_human}:
                return parsed
        if task.last_run:
            return TaskStatus.completed
        if task.last_run_attempt:
            return TaskStatus.failed
        if task.label_column and task.problem_type:
            return TaskStatus.planning
        if task.dataset_filename:
            return TaskStatus.uploaded
        return TaskStatus.draft

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
        return normalize_workflow_stage(stage).value

    @staticmethod
    def _read_human_loop(task: TaskRecord) -> dict[str, Any]:
        return get_task_human_loop(task)

    @staticmethod
    def _ensure_human_loop(task: TaskRecord) -> dict[str, Any]:
        return ensure_task_human_loop(task)
