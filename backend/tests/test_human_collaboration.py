from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4
from unittest import TestCase

from backend.app.models.task import (
    HumanInteractionDecisionAction,
    HumanInteractionRequestStatus,
    TaskHumanRequestCreateRequest,
    TaskHumanRequestDecisionRequest,
    TaskHumanRequestRecord,
    TaskRecord,
    TaskStatus,
    WorkflowStage,
    WorkflowStageRecord,
    WorkflowStageStatus,
)
from backend.app.services.task_human_collaboration import TaskHumanCollaborationService
from backend.app.services.task_human_context import build_task_human_context_block, build_task_human_guidance_preview


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _build_task(*, status: TaskStatus = TaskStatus.uploaded) -> TaskRecord:
    now = _utcnow()
    return TaskRecord(
        id="task-1",
        team_id="team-1",
        created_by="user-1",
        name="Demo Task",
        description="Train a tabular model for the uploaded CSV.",
        status=status,
        dataset_filename="train.csv",
        dataset_path="D:/tmp/train.csv",
        created_at=now,
        updated_at=now,
    )


class FakeTaskStore:
    def __init__(self) -> None:
        self.requests: dict[tuple[str, str, str], TaskHumanRequestRecord] = {}
        self.stage_records: dict[tuple[str, str, str], WorkflowStageRecord] = {}

    def save_task(self, task: TaskRecord, *, access_token: str) -> TaskRecord:
        saved = task.model_copy(deep=True)
        saved.updated_at = _utcnow()
        return saved

    def list_stage_records(self, team_id: str, task_id: str, *, access_token: str) -> list[WorkflowStageRecord]:
        return [
            record.model_copy(deep=True)
            for key, record in self.stage_records.items()
            if key[0] == team_id and key[1] == task_id
        ]

    def upsert_stage_record(
        self,
        *,
        team_id: str,
        task_id: str,
        stage: WorkflowStage,
        status: WorkflowStageStatus,
        access_token: str,
        selected_connector_id: str | None = None,
        model_name: str | None = None,
        selection_source: str | None = None,
        summary: str | None = None,
        artifact_refs=None,
    ) -> WorkflowStageRecord:
        key = (team_id, task_id, stage.value)
        now = _utcnow()
        existing = self.stage_records.get(key)
        if existing is None:
            record = WorkflowStageRecord(
                id=f"stage_{uuid4().hex}",
                team_id=team_id,
                task_id=task_id,
                stage=stage,
                status=status,
                selected_connector_id=selected_connector_id,
                model_name=model_name,
                selection_source=selection_source,
                summary=summary,
                artifact_refs=artifact_refs,
                created_at=now,
                updated_at=now,
            )
        else:
            record = existing.model_copy(deep=True)
            record.status = status
            record.selected_connector_id = selected_connector_id
            record.model_name = model_name
            record.selection_source = selection_source
            record.summary = summary
            record.artifact_refs = artifact_refs
            record.updated_at = now
        self.stage_records[key] = record
        return record.model_copy(deep=True)

    def list_human_requests(self, team_id: str, task_id: str, *, access_token: str) -> list[TaskHumanRequestRecord]:
        items = [
            request.model_copy(deep=True)
            for key, request in self.requests.items()
            if key[0] == team_id and key[1] == task_id
        ]
        return sorted(
            items,
            key=lambda item: (
                0 if item.status == HumanInteractionRequestStatus.open else 1,
                -item.updated_at.timestamp(),
            ),
        )

    def create_human_request(
        self,
        *,
        team_id: str,
        task_id: str,
        stage: WorkflowStage,
        requested_by: str,
        access_token: str,
        assigned_to: str | None = None,
        assignee_type: str | None = None,
        assignee_value: str | None = None,
        timeout_at: datetime | None = None,
        version_id: str | None = None,
        payload: dict | None = None,
    ) -> TaskHumanRequestRecord:
        now = _utcnow()
        request = TaskHumanRequestRecord(
            id=f"req_{uuid4().hex}",
            team_id=team_id,
            task_id=task_id,
            stage=stage,
            status=HumanInteractionRequestStatus.open,
            requested_by=requested_by,
            assigned_to=assigned_to,
            assignee_type=assignee_type,
            assignee_value=assignee_value,
            timeout_at=timeout_at,
            version_id=version_id,
            payload=payload,
            decision=None,
            created_at=now,
            updated_at=now,
        )
        self.requests[(team_id, task_id, request.id)] = request
        return request.model_copy(deep=True)

    def get_human_request(self, team_id: str, task_id: str, request_id: str, *, access_token: str) -> TaskHumanRequestRecord | None:
        request = self.requests.get((team_id, task_id, request_id))
        return request.model_copy(deep=True) if request is not None else None

    def update_human_request(self, request: TaskHumanRequestRecord, *, access_token: str) -> TaskHumanRequestRecord:
        updated = request.model_copy(deep=True)
        updated.updated_at = _utcnow()
        self.requests[(updated.team_id, updated.task_id, updated.id)] = updated
        return updated.model_copy(deep=True)


class TaskHumanCollaborationServiceTests(TestCase):
    def setUp(self) -> None:
        self.store = FakeTaskStore()
        self.service = TaskHumanCollaborationService(self.store)
        self.access_token = "test-token"

    def test_create_request_moves_task_into_waiting_human(self) -> None:
        task = _build_task()
        snapshot = self.service.create_request(
            task,
            TaskHumanRequestCreateRequest(
                stage=WorkflowStage.feature_engineering,
                request_type="code_review",
                title="Review generated code",
                summary="Check whether the generated training code matches the task intent.",
                suggested_action="Inspect generated_code.py before the next run.",
                artifact_paths=["node_0/generated_code.py"],
            ),
            requested_by="user-1",
            access_token=self.access_token,
        )

        self.assertEqual(snapshot.task.status, TaskStatus.paused_for_review)
        self.assertEqual(snapshot.open_request_count, 1)
        self.assertFalse(snapshot.can_resume)
        self.assertEqual(len(snapshot.requests), 1)
        self.assertEqual(snapshot.requests[0].status, HumanInteractionRequestStatus.open)
        self.assertFalse(snapshot.next_run_guidance.has_guidance)

    def test_decision_history_is_exposed_and_resume_restores_previous_status(self) -> None:
        task = _build_task()
        created = self.service.create_request(
            task,
            TaskHumanRequestCreateRequest(
                stage=WorkflowStage.training_validation,
                request_type="result_review",
                title="Confirm validation metric",
                summary="Check whether the metric should stay as accuracy.",
                suggested_action="Switch to F1 if the labels are imbalanced.",
                artifact_paths=["results.csv"],
            ),
            requested_by="user-1",
            access_token=self.access_token,
        )

        request_id = created.requests[0].id
        resolved = self.service.submit_decision(
            created.task,
            request_id,
            TaskHumanRequestDecisionRequest(
                action=HumanInteractionDecisionAction.revise,
                decision_summary="Use F1 for the next run and keep the minority class handling explicit.",
                artifact_paths=["results.csv", "node_0/generated_code.py"],
                resume_task=True,
            ),
            decided_by="reviewer-1",
            access_token=self.access_token,
        )

        self.assertEqual(resolved.task.status, TaskStatus.uploaded)
        self.assertEqual(resolved.open_request_count, 0)
        self.assertFalse(resolved.can_resume)
        self.assertEqual(len(resolved.decision_history), 1)
        self.assertEqual(resolved.decision_history[0].action, "revise")
        self.assertIn("Use F1 for the next run", resolved.decision_history[0].decision_summary or "")

        preview = resolved.next_run_guidance
        self.assertTrue(preview.has_guidance)
        self.assertEqual(preview.decision_count, 1)
        self.assertIn("Human collaboration guidance:", preview.description_appendix)
        self.assertIn("Use F1 for the next run", preview.description_appendix)
        self.assertIn("These are human-reviewed decisions", preview.human_instruction_file)
        self.assertIn("human_collaboration_instructions.txt", preview.initial_instruction_note)
        self.assertIn("- Human-reviewed decisions are available below.", preview.chat_context_block)

    def test_submit_without_resume_keeps_waiting_and_manual_resume_restores_status(self) -> None:
        task = _build_task()
        created = self.service.create_request(
            task,
            TaskHumanRequestCreateRequest(
                stage=WorkflowStage.data_analysis,
                request_type="data_review",
                title="Confirm label column",
                summary="Need a human check before trusting the inferred target column.",
                suggested_action="Decide whether the current label mapping is valid.",
                artifact_paths=["input/descriptions.txt"],
            ),
            requested_by="user-1",
            access_token=self.access_token,
        )

        paused = self.service.submit_decision(
            created.task,
            created.requests[0].id,
            TaskHumanRequestDecisionRequest(
                action=HumanInteractionDecisionAction.approve,
                decision_summary="Label column is correct, but keep the task paused until the team reviews the plan.",
                artifact_paths=["input/descriptions.txt"],
                resume_task=False,
            ),
            decided_by="reviewer-1",
            access_token=self.access_token,
        )

        self.assertEqual(paused.task.status, TaskStatus.paused_for_review)
        self.assertTrue(paused.can_resume)
        with self.assertRaisesRegex(RuntimeError, "waiting for human collaboration"):
            self.service.assert_task_can_run(paused.task, access_token=self.access_token)

        resumed = self.service.resume_task(paused.task, access_token=self.access_token)
        self.assertEqual(resumed.task.status, TaskStatus.uploaded)
        self.assertFalse(resumed.can_resume)

    def test_preview_helpers_return_empty_state_without_decisions(self) -> None:
        task = _build_task()

        preview = build_task_human_guidance_preview(task)
        self.assertFalse(preview["has_guidance"])
        self.assertEqual(preview["decision_count"], 0)
        self.assertEqual(preview["description_appendix"], "")
        self.assertEqual(preview["human_instruction_file"], "")
        self.assertEqual(build_task_human_context_block(task), "No recorded human collaboration decisions.")
