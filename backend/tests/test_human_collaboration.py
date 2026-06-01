from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
from unittest import TestCase
from unittest.mock import patch

from backend.app.core.supabase_auth import SupabaseUser, TeamAccessContext
from backend.app.models.governance import TeamMemberRecord
from backend.app.models.task import (
    HumanInteractionDecisionAction,
    HumanInteractionRequestStatus,
    InteractionAssigneeType,
    InteractionTriggerMode,
    TaskHumanRequestCreateRequest,
    TaskHumanRequestDecisionRequest,
    TaskHumanRequestRecord,
    TaskInteractionPolicyRecord,
    TaskRecord,
    TaskStatus,
    TaskStageRoutingRecord,
    WorkflowStage,
    WorkflowStageRecord,
    WorkflowStageStatus,
)
from backend.app.services.task_human_policy import _apply_interaction_policies
from backend.app.api.routes.task_human import decide_task_human_request
from backend.app.services.task_human_collaboration import TaskHumanCollaborationService
from backend.app.services.task_human_context import (
    HUMAN_LOOP_KEY,
    build_task_human_context_block,
    build_task_human_guidance_lines,
    build_task_human_guidance_preview,
)
from backend.app.services.task_human_parameters import resolve_task_run_time_limit


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
        self.task: TaskRecord | None = None

    def save_task(self, task: TaskRecord, *, access_token: str) -> TaskRecord:
        saved = task.model_copy(deep=True)
        saved.updated_at = _utcnow()
        self.task = saved.model_copy(deep=True)
        return saved

    def get_task(self, team_id: str, task_id: str, *, access_token: str) -> TaskRecord | None:
        if self.task is None or self.task.team_id != team_id or self.task.id != task_id:
            return None
        return self.task.model_copy(deep=True)

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

    def test_snapshot_exposes_actor_specific_requests(self) -> None:
        task = _build_task()
        team_members = [
            TeamMemberRecord(team_id="team-1", user_id="user-1", role="developer_user", member_status="active"),
            TeamMemberRecord(team_id="team-1", user_id="reviewer-1", role="developer_user", member_status="active"),
            TeamMemberRecord(team_id="team-1", user_id="reviewer-2", role="developer_user", member_status="active"),
        ]
        first = self.service.create_request(
            task,
            TaskHumanRequestCreateRequest(
                stage=WorkflowStage.data_analysis,
                request_type="data_review",
                title="My review",
                summary="Review assigned to the current user.",
                assigned_to="reviewer-1",
                assignee_value="reviewer-1",
            ),
            requested_by="user-1",
            actor_role="developer_user",
            team_members=team_members,
            access_token=self.access_token,
        )
        self.service.create_request(
            first.task,
            TaskHumanRequestCreateRequest(
                stage=WorkflowStage.training_validation,
                request_type="result_review",
                title="Someone else review",
                summary="Review assigned to another user.",
                assigned_to="reviewer-2",
                assignee_value="reviewer-2",
            ),
            requested_by="user-1",
            actor_role="developer_user",
            team_members=team_members,
            access_token=self.access_token,
        )

        snapshot = self.service.get_snapshot(
            first.task,
            access_token=self.access_token,
            actor_id="reviewer-1",
            actor_role="developer_user",
        )

        self.assertEqual(snapshot.open_request_count, 2)
        self.assertEqual(snapshot.my_open_request_count, 1)
        self.assertEqual(len(snapshot.my_requests), 1)
        self.assertEqual(snapshot.my_requests[0].assigned_to, "reviewer-1")

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

    def test_guidance_lines_preserve_decision_sentence_format(self) -> None:
        task = _build_task()
        task.structured_requirements = {
            HUMAN_LOOP_KEY: {
                "decision_history": [
                    {
                        "stage": "training_validation",
                        "action": "revise",
                        "title": " Confirm validation metric ",
                        "request_summary": "Accuracy hides minority-class errors.",
                        "suggested_action": "Switch to F1.",
                        "decision_summary": "Use F1 for the next run.",
                        "artifact_paths": [" results.csv ", "", "node_0/generated_code.py", None, "plan.md", "notes.txt", "extra.txt"],
                    }
                ]
            }
        }

        lines = build_task_human_guidance_lines(task)

        self.assertEqual(
            lines,
            [
                "Human-reviewed decisions are available below. Treat them as higher-priority instructions for the next run unless the CSV clearly contradicts them.",
                "Human decision 1: Stage=training and validation; request='Confirm validation metric'; status=revise before the next run; decision='Use F1 for the next run.'. Original issue: Accuracy hides minority-class errors.. Requested change: Switch to F1.. Relevant artifacts: results.csv, node_0/generated_code.py, None, plan.md.",
            ],
        )

    def test_stage_checkpoint_decision_updates_data_analysis_parameters(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            dataset_path = Path(tmp_dir) / "train.csv"
            dataset_path.write_text("age,income,churn\n18,2000,yes\n36,6000,no\n", encoding="utf-8")
            task = _build_task()
            task.dataset_path = str(dataset_path)
            created = self.service.create_request(
                task,
                TaskHumanRequestCreateRequest(
                    stage=WorkflowStage.data_analysis,
                    request_type="stage_checkpoint",
                    title="Confirm data analysis",
                    summary="Confirm target column, problem type, and metric.",
                ),
                requested_by="user-1",
                access_token=self.access_token,
            )

            resolved = self.service.submit_decision(
                created.task,
                created.requests[0].id,
                TaskHumanRequestDecisionRequest(
                    action=HumanInteractionDecisionAction.approve,
                    decision_summary="Use churn as the target and optimize F1.",
                    resume_task=True,
                    details={
                        "checkpoint_stage": "data_analysis",
                        "parameters": {
                            "label_column": "churn",
                            "problem_type": "classification",
                            "metric_name": "f1",
                        },
                    },
                ),
                decided_by="reviewer-1",
                access_token=self.access_token,
            )

        self.assertEqual(resolved.task.label_column, "churn")
        self.assertEqual(resolved.task.problem_type, "classification")
        self.assertEqual(resolved.task.structured_requirements["metric_name"], "f1")
        self.assertEqual(resolved.task.dataset_profile.target_column, "churn")
        guidance = resolved.next_run_guidance.prompt_guidance_lines
        self.assertTrue(any("target column=churn" in line for line in guidance))
        self.assertTrue(any("primary metric=f1" in line for line in guidance))

    def test_stage_checkpoint_decision_stores_feature_model_training_and_report_parameters(self) -> None:
        task = _build_task(status=TaskStatus.planning)
        task.label_column = "target"
        task.problem_type = "classification"
        task.structured_requirements = {
            "column_names": ["age", "income", "region", "target"],
            "metric_name": "accuracy",
        }

        feature_created = self.service.create_request(
            task,
            TaskHumanRequestCreateRequest(
                stage=WorkflowStage.feature_engineering,
                request_type="stage_checkpoint",
                title="Confirm features",
                summary="Confirm columns.",
            ),
            requested_by="user-1",
            access_token=self.access_token,
        )
        feature_snapshot = self.service.submit_decision(
            feature_created.task,
            feature_created.requests[0].id,
            TaskHumanRequestDecisionRequest(
                action=HumanInteractionDecisionAction.approve,
                decision_summary="Keep age and income, drop region.",
                resume_task=True,
                details={
                    "parameters": {
                        "include_columns": ["age", "income"],
                        "exclude_columns": ["region"],
                    }
                },
            ),
            decided_by="reviewer-1",
            access_token=self.access_token,
        )

        model_created = self.service.create_request(
            feature_snapshot.task,
            TaskHumanRequestCreateRequest(
                stage=WorkflowStage.model_selection,
                request_type="stage_checkpoint",
                title="Confirm models",
                summary="Confirm model families.",
            ),
            requested_by="user-1",
            access_token=self.access_token,
        )
        model_snapshot = self.service.submit_decision(
            model_created.task,
            model_created.requests[0].id,
            TaskHumanRequestDecisionRequest(
                action=HumanInteractionDecisionAction.approve,
                decision_summary="Use tree models only.",
                resume_task=True,
                details={"parameters": {"allowed_models": ["GBM", "RF"], "excluded_models": ["KNN"]}},
            ),
            decided_by="reviewer-1",
            access_token=self.access_token,
        )

        training_created = self.service.create_request(
            model_snapshot.task,
            TaskHumanRequestCreateRequest(
                stage=WorkflowStage.training_validation,
                request_type="stage_checkpoint",
                title="Confirm training",
                summary="Confirm training settings.",
            ),
            requested_by="user-1",
            access_token=self.access_token,
        )
        training_snapshot = self.service.submit_decision(
            training_created.task,
            training_created.requests[0].id,
            TaskHumanRequestDecisionRequest(
                action=HumanInteractionDecisionAction.approve,
                decision_summary="Use 120 seconds and 5-fold validation.",
                resume_task=True,
                details={"parameters": {"time_limit": 120, "cv_folds": 5, "metric_name": "balanced_accuracy"}},
            ),
            decided_by="reviewer-1",
            access_token=self.access_token,
        )

        report_created = self.service.create_request(
            training_snapshot.task,
            TaskHumanRequestCreateRequest(
                stage=WorkflowStage.report_generation,
                request_type="stage_checkpoint",
                title="Confirm report",
                summary="Confirm report focus.",
            ),
            requested_by="user-1",
            access_token=self.access_token,
        )
        report_snapshot = self.service.submit_decision(
            report_created.task,
            report_created.requests[0].id,
            TaskHumanRequestDecisionRequest(
                action=HumanInteractionDecisionAction.approve,
                decision_summary="Focus on business conclusions.",
                resume_task=True,
                details={"parameters": {"report_focus": ["business conclusion", "model limitations"]}},
            ),
            decided_by="reviewer-1",
            access_token=self.access_token,
        )

        requirements = report_snapshot.task.structured_requirements
        self.assertEqual(requirements["feature_constraints"]["include_columns"], ["age", "income"])
        self.assertEqual(requirements["feature_constraints"]["exclude_columns"], ["region"])
        self.assertEqual(requirements["model_constraints"]["allowed_models"], ["GBM", "RF"])
        self.assertEqual(requirements["model_constraints"]["excluded_models"], ["KNN"])
        self.assertEqual(requirements["training_constraints"]["time_limit"], 120)
        self.assertEqual(requirements["training_constraints"]["cv_folds"], 5)
        self.assertEqual(requirements["metric_name"], "balanced_accuracy")
        self.assertEqual(requirements["report_constraints"]["report_focus"], ["business conclusion", "model limitations"])
        self.assertEqual(resolve_task_run_time_limit(report_snapshot.task, None), 120)
        guidance_text = "\n".join(report_snapshot.next_run_guidance.prompt_guidance_lines)
        self.assertIn("feature engineering", guidance_text)
        self.assertIn("model selection", guidance_text)
        self.assertIn("training validation", guidance_text)
        self.assertIn("report generation", guidance_text)

    def test_stage_checkpoint_policies_are_created_one_node_at_a_time(self) -> None:
        task = _build_task()
        task.interaction_policies = [
            TaskInteractionPolicyRecord(
                policy_id=f"stage-checkpoint:{stage.value}",
                enabled=True,
                stage=stage,
                trigger_mode=InteractionTriggerMode.before_run,
                assignee_type=InteractionAssigneeType.member,
                assignee_value="user-1",
                request_type="stage_checkpoint",
                title=f"Confirm {stage.value}",
                summary=f"Confirm stage {stage.value}.",
            )
            for stage in (WorkflowStage.requirement_analysis, WorkflowStage.data_analysis)
        ]
        team_access = TeamAccessContext(
            team_id=task.team_id,
            role="admin",
            user=SupabaseUser(id="user-1", email=None, raw={}),
            access_token=self.access_token,
        )
        members = [TeamMemberRecord(team_id=task.team_id, user_id="user-1", role="admin", member_status="active")]
        stage_selection_map = {
            stage.value: TaskStageRoutingRecord(stage=stage, selection_source="team_policy")
            for stage in (WorkflowStage.requirement_analysis, WorkflowStage.data_analysis)
        }

        with patch("backend.app.services.task_human_policy.get_task_store", return_value=self.store), patch(
            "backend.app.services.task_human_policy._load_team_members_for_human",
            return_value=members,
        ), patch(
            "backend.app.services.task_human_policy.get_task_human_collaboration_service",
            return_value=self.service,
        ):
            paused_task, created_count = _apply_interaction_policies(
                task,
                team_access,
                trigger_mode=InteractionTriggerMode.before_run,
                cycle_id=1,
                stage_selection_map=stage_selection_map,
            )

            self.assertEqual(created_count, 1)
            self.assertEqual(paused_task.status, TaskStatus.paused_for_review)
            requests = self.store.list_human_requests(task.team_id, task.id, access_token=self.access_token)
            self.assertEqual(len(requests), 1)
            self.assertEqual(requests[0].stage, WorkflowStage.requirement_analysis)

            first_request = requests[0]
            first_request.status = HumanInteractionRequestStatus.confirmed
            self.store.update_human_request(first_request, access_token=self.access_token)
            resumed_task = paused_task.model_copy(deep=True)
            resumed_task.status = TaskStatus.uploaded

            _, second_created_count = _apply_interaction_policies(
                resumed_task,
                team_access,
                trigger_mode=InteractionTriggerMode.before_run,
                cycle_id=2,
                stage_selection_map=stage_selection_map,
            )

        requests = self.store.list_human_requests(task.team_id, task.id, access_token=self.access_token)
        self.assertEqual(second_created_count, 1)
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[0].stage, WorkflowStage.data_analysis)

    def test_policy_application_can_skip_completed_non_checkpoint_policy(self) -> None:
        task = _build_task()
        task.interaction_policies = [
            TaskInteractionPolicyRecord(
                policy_id="model-review",
                enabled=True,
                stage=WorkflowStage.model_selection,
                trigger_mode=InteractionTriggerMode.before_run,
                assignee_type=InteractionAssigneeType.member,
                assignee_value="user-1",
                request_type="model_review",
                title="Confirm model choice",
                summary="Confirm selected model before training.",
            )
        ]
        team_access = TeamAccessContext(
            team_id=task.team_id,
            role="admin",
            user=SupabaseUser(id="user-1", email=None, raw={}),
            access_token=self.access_token,
        )
        members = [TeamMemberRecord(team_id=task.team_id, user_id="user-1", role="admin", member_status="active")]
        stage_selection_map = {
            WorkflowStage.model_selection.value: TaskStageRoutingRecord(
                stage=WorkflowStage.model_selection,
                connector_id="connector-1",
                model_name="model-a",
                selection_source="team_policy",
            )
        }

        with patch("backend.app.services.task_human_policy.get_task_store", return_value=self.store), patch(
            "backend.app.services.task_human_policy._load_team_members_for_human",
            return_value=members,
        ), patch(
            "backend.app.services.task_human_policy.get_task_human_collaboration_service",
            return_value=self.service,
        ):
            paused_task, created_count = _apply_interaction_policies(
                task,
                team_access,
                trigger_mode=InteractionTriggerMode.before_run,
                cycle_id=1,
                stage_selection_map=stage_selection_map,
            )

            self.assertEqual(created_count, 1)
            requests = self.store.list_human_requests(task.team_id, task.id, access_token=self.access_token)
            self.assertEqual(requests[0].version_id, "model-review:1:before_run")
            self.assertEqual(requests[0].payload["selected_connector_id"], "connector-1")
            self.assertEqual(requests[0].payload["selected_model_name"], "model-a")

            completed_request = requests[0]
            completed_request.status = HumanInteractionRequestStatus.confirmed
            self.store.update_human_request(completed_request, access_token=self.access_token)
            resumed_task = paused_task.model_copy(deep=True)
            resumed_task.status = TaskStatus.uploaded

            _, second_created_count = _apply_interaction_policies(
                resumed_task,
                team_access,
                trigger_mode=InteractionTriggerMode.before_run,
                cycle_id=2,
                stage_selection_map=stage_selection_map,
                skip_completed=True,
            )

        requests = self.store.list_human_requests(task.team_id, task.id, access_token=self.access_token)
        self.assertEqual(second_created_count, 0)
        self.assertEqual(len(requests), 1)

    def test_decision_endpoint_advances_to_next_stage_checkpoint(self) -> None:
        task = _build_task()
        task.structured_requirements = {"human_loop": {"policy_cycle": 1, "current_run_cycle": 1}}
        task.interaction_policies = [
            TaskInteractionPolicyRecord(
                policy_id=f"stage-checkpoint:{stage.value}",
                enabled=True,
                stage=stage,
                trigger_mode=InteractionTriggerMode.before_run,
                assignee_type=InteractionAssigneeType.member,
                assignee_value="user-1",
                request_type="stage_checkpoint",
                title=f"Confirm {stage.value}",
                summary=f"Confirm stage {stage.value}.",
            )
            for stage in (WorkflowStage.requirement_analysis, WorkflowStage.data_analysis)
        ]
        self.store.task = task.model_copy(deep=True)
        team_access = TeamAccessContext(
            team_id=task.team_id,
            role="admin",
            user=SupabaseUser(id="user-1", email=None, raw={}),
            access_token=self.access_token,
        )
        members = [TeamMemberRecord(team_id=task.team_id, user_id="user-1", role="admin", member_status="active")]
        stage_selection_map = {
            stage.value: TaskStageRoutingRecord(stage=stage, selection_source="team_policy")
            for stage in (WorkflowStage.requirement_analysis, WorkflowStage.data_analysis)
        }

        with patch("backend.app.services.task_human_policy.get_task_store", return_value=self.store), patch(
            "backend.app.services.task_human_policy._load_team_members_for_human",
            return_value=members,
        ), patch(
            "backend.app.services.task_human_policy.get_task_human_collaboration_service",
            return_value=self.service,
        ):
            paused_task, _ = _apply_interaction_policies(
                task,
                team_access,
                trigger_mode=InteractionTriggerMode.before_run,
                cycle_id=1,
                stage_selection_map=stage_selection_map,
            )
            self.store.task = paused_task.model_copy(deep=True)

        first_request = self.store.list_human_requests(task.team_id, task.id, access_token=self.access_token)[0]
        with patch("backend.app.api.routes.task_human.get_task_store", return_value=self.store), patch(
            "backend.app.api.routes.task_human.get_task_human_collaboration_service",
            return_value=self.service,
        ), patch(
            "backend.app.services.task_human_policy.get_task_store",
            return_value=self.store,
        ), patch(
            "backend.app.services.task_human_policy.get_task_human_collaboration_service",
            return_value=self.service,
        ), patch(
            "backend.app.services.task_workflow_tracking.get_task_human_collaboration_service",
            return_value=self.service,
        ), patch(
            "backend.app.api.routes.task_human._load_team_members_for_human",
            return_value=members,
        ), patch(
            "backend.app.services.task_human_policy._load_team_members_for_human",
            return_value=members,
        ), patch(
            "backend.app.api.routes.task_human._build_runtime_context",
            return_value=object(),
        ), patch(
            "backend.app.api.routes.task_human._build_stage_selection_map",
            return_value=stage_selection_map,
        ):
            snapshot = decide_task_human_request(
                task.id,
                first_request.id,
                TaskHumanRequestDecisionRequest(
                    action=HumanInteractionDecisionAction.approve,
                    decision_summary="Requirement checkpoint approved.",
                    resume_task=True,
                ),
                team_access=team_access,
            )

        requests = self.store.list_human_requests(task.team_id, task.id, access_token=self.access_token)
        self.assertEqual(snapshot.open_request_count, 1)
        self.assertEqual(snapshot.task.status, TaskStatus.paused_for_review)
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[0].stage, WorkflowStage.data_analysis)
