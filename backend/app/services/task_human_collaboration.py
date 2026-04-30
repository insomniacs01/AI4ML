from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.app.models.task import (
    HumanInteractionRequestStatus,
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


@dataclass(frozen=True)
class _StageBlueprint:
    stage: WorkflowStage
    status: WorkflowStageStatus
    summary: str


class TaskHumanCollaborationService:
    def __init__(self, task_store: TaskStore) -> None:
        self.task_store = task_store

    def get_snapshot(self, task: TaskRecord, *, access_token: str) -> TaskHumanCollaborationResponse:
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
        existing_records = {
            self._stage_key(record.stage): record
            for record in self.task_store.list_stage_records(task.team_id, task.id, access_token=access_token)
        }
        requests = self.task_store.list_human_requests(task.team_id, task.id, access_token=access_token)
        open_requests_by_stage = {
            self._stage_key(request.stage): request
            for request in requests
            if request.status == HumanInteractionRequestStatus.open
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
    ) -> TaskHumanCollaborationResponse:
        if task.status == TaskStatus.running:
            raise RuntimeError("Current task run is still in progress. Wait until it finishes before creating a human collaboration request.")

        timeout_at = None
        if payload.timeout_minutes is not None:
            timeout_at = datetime.now(timezone.utc) + timedelta(minutes=payload.timeout_minutes)

        self.task_store.create_human_request(
            team_id=task.team_id,
            task_id=task.id,
            stage=normalize_workflow_stage(payload.stage),
            requested_by=requested_by,
            assigned_to=payload.assigned_to,
            assignee_type=payload.assignee_type.value if payload.assignee_type else None,
            assignee_value=payload.assignee_value,
            timeout_at=timeout_at,
            payload={
                "request_type": payload.request_type,
                "title": payload.title,
                "summary": payload.summary,
                "suggested_action": payload.suggested_action,
                "artifact_paths": payload.artifact_paths,
                "details": payload.details,
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
    ) -> TaskHumanCollaborationResponse:
        request = self.task_store.get_human_request(task.team_id, task.id, request_id, access_token=access_token)
        if request is None:
            raise ValueError("human request not found")
        if request.status != HumanInteractionRequestStatus.open:
            raise RuntimeError("human request has already been resolved")

        request.status = HumanInteractionRequestStatus.resolved
        request.decision = {
            "action": payload.action.value,
            "summary": payload.decision_summary,
            "artifact_paths": payload.artifact_paths,
            "details": payload.details,
            "decided_by": decided_by,
            "decided_at": datetime.now(timezone.utc).isoformat(),
        }
        self.task_store.update_human_request(request, access_token=access_token)

        task = self._record_latest_decision(task, request=request, payload=payload)
        remaining_requests = self.task_store.list_human_requests(task.team_id, task.id, access_token=access_token)
        if self._count_open_requests(remaining_requests):
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
        if task.status in {TaskStatus.paused_for_review, TaskStatus.waiting_human}:
            raise RuntimeError("Task is waiting for human collaboration. Resolve or resume it before running MLZero.")
        requests = self.task_store.list_human_requests(task.team_id, task.id, access_token=access_token)
        if self._count_open_requests(requests):
            raise RuntimeError("Task has open human collaboration requests. Resolve them before running MLZero.")

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

        return [
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
        return sum(1 for item in requests if item.status == HumanInteractionRequestStatus.open)

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

    def _resume_task_record(self, task: TaskRecord, *, access_token: str) -> TaskRecord:
        human_loop = self._ensure_human_loop(task)
        human_loop["manual_hold"] = False
        human_loop["resumed_at"] = datetime.now(timezone.utc).isoformat()
        task.status = self._get_previous_status(task)
        return self.task_store.save_task(task, access_token=access_token)

    def _get_previous_status(self, task: TaskRecord) -> TaskStatus:
        human_loop = self._read_human_loop(task)
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
