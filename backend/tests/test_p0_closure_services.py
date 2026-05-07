from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from backend.app.models.task import (
    HumanInteractionRequestStatus,
    RunAttempt,
    RunSummary,
    TaskAgentEventRecord,
    TaskAgentMessageRecord,
    TaskAgentRuntimeRecord,
    TaskHumanRequestRecord,
    TaskRecord,
    TaskSemanticUpdateRequest,
    TaskStatus,
    WorkflowStage,
    WorkflowStageRecord,
    WorkflowStageStatus,
)
from backend.app.services.executors.mlzero_executor import MLZeroExecutor
from backend.app.services.task_agent_collaboration import append_stage_agent_messages, build_task_agent_collaboration_response
from backend.app.services.task_run_progress import build_task_run_progress
from backend.app.services.task_semantics import apply_human_semantic_update
from backend.app.services.token_usage import (
    TokenizerUnavailableError,
    make_provider_tokenizer_usage_report,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _task(dataset_path: Path | None = None) -> TaskRecord:
    now = _utcnow()
    return TaskRecord(
        id="task-1",
        team_id="team-1",
        created_by="user-1",
        name="P0 Task",
        description="Predict churn from a CSV.",
        label_column="old_label",
        problem_type="regression",
        status=TaskStatus.completed,
        dataset_filename="train.csv" if dataset_path else None,
        dataset_path=str(dataset_path) if dataset_path else None,
        last_run=RunSummary(
            best_model="OldModel",
            metric_name="rmse",
            metric_value=1.23,
            leaderboard=[],
            output_dir="D:/runs/old",
        ),
        last_run_attempt=RunAttempt(output_dir="D:/runs/old"),
        structured_requirements={
            "analysis_source": "ai_connector",
            "metric_name": "rmse",
            "human_loop": {"policy_cycle": 2},
        },
        created_at=now,
        updated_at=now,
    )


class P0ClosureServiceTests(TestCase):
    def test_provider_tokenizer_usage_uses_explicit_tokenizer(self) -> None:
        class FakeEncoding:
            def encode(self, text: str) -> list[str]:
                return text.split()

        fake_tiktoken = SimpleNamespace(
            encoding_for_model=lambda model_name: FakeEncoding(),
            get_encoding=lambda encoding_name: FakeEncoding(),
        )

        with patch.dict(sys.modules, {"tiktoken": fake_tiktoken}):
            report = make_provider_tokenizer_usage_report(
                prompt="hello user",
                system_message="hello system",
                response_text="hello assistant",
                model_name="provider-model",
                tokenizer_model_name="encoding:test",
            )

        self.assertGreater(report.input_tokens, 0)
        self.assertEqual(report.output_tokens, 2)
        self.assertEqual(report.total_tokens, report.input_tokens + report.output_tokens)
        self.assertEqual(report.sessions[0]["calculation_method"], "tokenizer_estimate")

    def test_provider_tokenizer_usage_fails_when_tokenizer_missing(self) -> None:
        with patch.dict(sys.modules, {"tiktoken": None}):
            with self.assertRaises(TokenizerUnavailableError):
                make_provider_tokenizer_usage_report(
                    prompt="hello",
                    system_message="system",
                    response_text="assistant",
                    model_name="provider-model",
                )

    def test_human_semantic_update_validates_csv_and_clears_stale_run(self) -> None:
        with TemporaryDirectory() as tmpdir:
            dataset_path = Path(tmpdir) / "train.csv"
            dataset_path.write_text("feature,churn\n1,yes\n2,no\n", encoding="utf-8")
            task = _task(dataset_path)

            updated = apply_human_semantic_update(
                task,
                TaskSemanticUpdateRequest(
                    label_column="churn",
                    problem_type="classification",
                    metric_name="accuracy",
                    correction_note="churn is the business target",
                ),
                corrected_by="user-2",
            )

        self.assertEqual(updated.label_column, "churn")
        self.assertEqual(updated.problem_type, "classification")
        self.assertEqual(updated.status, TaskStatus.planning)
        self.assertIsNone(updated.last_run)
        self.assertIsNone(updated.last_run_attempt)
        self.assertEqual(updated.dataset_profile.target_column, "churn")
        self.assertEqual(updated.structured_requirements["analysis_source"], "human_correction")
        self.assertEqual(updated.structured_requirements["metric_name"], "accuracy")
        self.assertEqual(updated.structured_requirements["semantic_correction_history"][0]["corrected_by"], "user-2")

    def test_agent_snapshot_marks_open_human_stage_waiting(self) -> None:
        now = _utcnow()
        task = _task()
        stages = [
            WorkflowStageRecord(
                id="stage-1",
                team_id=task.team_id,
                task_id=task.id,
                stage=WorkflowStage.data_analysis,
                status=WorkflowStageStatus.completed,
                selected_connector_id="connector-1",
                model_name="model-a",
                selection_source="task_override",
                summary="Data analysis completed.",
                artifact_refs=["D:/tmp/train.csv"],
                created_at=now,
                updated_at=now,
            )
        ]
        requests = [
            TaskHumanRequestRecord(
                id="request-1",
                team_id=task.team_id,
                task_id=task.id,
                stage=WorkflowStage.feature_engineering,
                status=HumanInteractionRequestStatus.open,
                payload={"title": "Review features", "artifact_paths": ["D:/runs/code.py"]},
                created_at=now,
                updated_at=now,
            )
        ]

        snapshot = build_task_agent_collaboration_response(task, stages=stages, requests=requests)
        agents_by_id = {agent.id: agent for agent in snapshot.agents}

        self.assertEqual(snapshot.runtime_mode, "stage_agent_orchestrator")
        self.assertEqual(agents_by_id["data_analysis"].status, WorkflowStageStatus.completed)
        self.assertEqual(agents_by_id["feature_engineering"].status, WorkflowStageStatus.waiting_human)
        self.assertTrue(any(event.kind == "human_request" for event in snapshot.events))

    def test_agent_snapshot_prefers_persistent_runtime_records(self) -> None:
        now = _utcnow()
        task = _task()
        agent_run = TaskAgentRuntimeRecord(
            id="runtime-1",
            team_id=task.team_id,
            task_id=task.id,
            agent_id=WorkflowStage.training_validation.value,
            stage=WorkflowStage.training_validation,
            name="Agent-Epsilon",
            role="训练验证",
            short_role="训练",
            status=WorkflowStageStatus.running,
            progress=67,
            current_task="MLZero 正在执行训练验证。",
            selected_connector_id="connector-1",
            model_name="model-a",
            selection_source="team_policy",
            artifact_refs=["D:/runs/stdout.txt"],
            started_at=now,
            finished_at=None,
            duration_seconds=None,
            log_excerpt="training loop started",
            worker_id="backend-agent-worker:task-1:training_validation",
            created_at=now,
            updated_at=now,
        )
        agent_event = TaskAgentEventRecord(
            id="event-1",
            team_id=task.team_id,
            task_id=task.id,
            agent_id=WorkflowStage.training_validation.value,
            stage=WorkflowStage.training_validation,
            kind="agent",
            status=WorkflowStageStatus.running.value,
            text="Agent-Epsilon（训练验证）执行中：MLZero 正在执行训练验证。",
            time=now,
            artifact_refs=["D:/runs/stdout.txt"],
        )

        snapshot = build_task_agent_collaboration_response(
            task,
            stages=[],
            requests=[],
            agent_runs=[agent_run],
            agent_events=[agent_event],
        )
        agents_by_id = {agent.id: agent for agent in snapshot.agents}
        training_agent = agents_by_id[WorkflowStage.training_validation.value]

        self.assertEqual(snapshot.runtime_mode, "persistent_agent_runtime")
        self.assertEqual(training_agent.runtime_source, "persistent_agent_runtime")
        self.assertEqual(training_agent.runtime_id, "runtime-1")
        self.assertEqual(training_agent.worker_id, "backend-agent-worker:task-1:training_validation")
        self.assertEqual(training_agent.progress, 67)
        self.assertEqual(training_agent.artifact_count, 1)
        self.assertTrue(any(event.kind == "agent" and event.id == "event-1" for event in snapshot.events))

    def test_agent_snapshot_returns_persisted_agent_messages(self) -> None:
        now = _utcnow()
        task = _task()
        message = TaskAgentMessageRecord(
            id="message-1",
            team_id=task.team_id,
            task_id=task.id,
            from_agent_id=WorkflowStage.data_analysis.value,
            to_agent_id=WorkflowStage.feature_engineering.value,
            stage=WorkflowStage.data_analysis,
            message_type="handoff",
            status="sent",
            content="Agent-Beta 已向 Agent-Gamma 交接数据画像。",
            payload={"from_agent_name": "Agent-Beta", "to_agent_name": "Agent-Gamma"},
            artifact_refs=["D:/tmp/train.csv"],
            correlation_id="agent-msg:test",
            time=now,
        )

        snapshot = build_task_agent_collaboration_response(
            task,
            stages=[],
            requests=[],
            agent_messages=[message],
        )

        self.assertEqual(len(snapshot.messages), 1)
        self.assertEqual(snapshot.messages[0].from_agent_id, WorkflowStage.data_analysis.value)
        self.assertEqual(snapshot.messages[0].to_agent_id, WorkflowStage.feature_engineering.value)
        self.assertEqual(snapshot.messages[0].message_type, "handoff")

    def test_stage_transition_persists_inter_agent_handoff_and_acknowledgement(self) -> None:
        class FakeTaskStore:
            def __init__(self) -> None:
                self.messages: list[TaskAgentMessageRecord] = []

            def append_agent_message(self, **kwargs) -> TaskAgentMessageRecord:
                record = TaskAgentMessageRecord(
                    id=f"message-{len(self.messages) + 1}",
                    team_id=kwargs["team_id"],
                    task_id=kwargs["task_id"],
                    from_agent_id=kwargs["from_agent_id"],
                    to_agent_id=kwargs.get("to_agent_id"),
                    stage=kwargs["stage"],
                    message_type=kwargs["message_type"],
                    status=kwargs.get("status", "sent"),
                    content=kwargs["content"],
                    payload=kwargs.get("payload"),
                    artifact_refs=kwargs.get("artifact_refs") or [],
                    correlation_id=kwargs.get("correlation_id"),
                    time=_utcnow(),
                )
                self.messages.append(record)
                return record

        task = _task()
        store = FakeTaskStore()

        messages = append_stage_agent_messages(
            store,
            task,
            access_token="token",
            stage=WorkflowStage.data_analysis,
            stage_status=WorkflowStageStatus.completed,
            summary="目标列 churn，任务类型 classification，指标 accuracy。",
            artifact_refs=["D:/tmp/train.csv"],
        )

        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0].from_agent_id, WorkflowStage.data_analysis.value)
        self.assertEqual(messages[0].to_agent_id, WorkflowStage.feature_engineering.value)
        self.assertEqual(messages[0].message_type, "handoff")
        self.assertEqual(messages[1].from_agent_id, WorkflowStage.feature_engineering.value)
        self.assertEqual(messages[1].to_agent_id, WorkflowStage.data_analysis.value)
        self.assertEqual(messages[1].message_type, "acknowledgement")

    def test_run_progress_detects_stale_runtime_and_partial_artifacts(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            output_dir = root / "runs" / "task-1" / "20260505T080950Z"
            output_dir.mkdir(parents=True)
            (output_dir / "logs.txt").write_text(
                "\n".join(
                    [
                        "2026-05-05 16:23:40 BRIEF    [autogluon.assistant.coding_agent] Starting MCTS iteration 3/6",
                        "2026-05-05 16:28:33 BRIEF    [autogluon.assistant.managers.node_manager] Task completed successfully! Best node: 1 with validation score 0.0006",
                        "2026-05-05 16:28:34 BRIEF    [autogluon.assistant.coding_agent] Starting MCTS iteration 4/6",
                    ]
                ),
                encoding="utf-8",
            )
            (output_dir / "run_summary.json").write_text(
                '{"best_model":"WeightedEnsemble_L2","metric_name":"rmse","metric_value":0.123,'
                '"validation_score":-0.123,"candidate_model_count":4}',
                encoding="utf-8",
            )
            (output_dir / "leaderboard.csv").write_text("model,validation_score\nWeightedEnsemble_L2,-0.123\n", encoding="utf-8")
            best_run = output_dir / "best_run"
            best_run.mkdir()
            (best_run / "generated_code.py").write_text("print('ok')\n", encoding="utf-8")
            old_timestamp = 1_700_000_000
            for path in [output_dir, output_dir / "logs.txt", output_dir / "run_summary.json", output_dir / "leaderboard.csv", best_run, best_run / "generated_code.py"]:
                path.touch()
                path.stat()
                os.utime(path, (old_timestamp, old_timestamp))

            now = datetime.fromtimestamp(old_timestamp - 3600, tz=timezone.utc)
            task = TaskRecord(
                id="task-1",
                team_id="team-1",
                created_by="user-1",
                name="Long run",
                description="Predict value.",
                label_column="Value",
                problem_type="regression",
                status=TaskStatus.running,
                dataset_filename="train.csv",
                dataset_path=str(root / "train.csv"),
                created_at=now,
                updated_at=now,
            )
            settings = SimpleNamespace(run_output_dir=root / "runs", repo_root=root)

            progress = build_task_run_progress(task, settings, stale_after_seconds=1)

        self.assertEqual(progress.status, "stale")
        self.assertTrue(progress.stale)
        self.assertEqual(progress.current_stage, WorkflowStage.training_validation)
        self.assertTrue(progress.artifacts.has_run_summary)
        self.assertTrue(progress.artifacts.has_leaderboard)
        self.assertFalse(progress.artifacts.has_token_usage)
        self.assertTrue(progress.artifacts.has_generated_code)
        self.assertIn("WeightedEnsemble_L2", progress.current_activity)

    def test_run_progress_ignores_previous_run_when_new_run_has_not_created_output(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            previous_output_dir = root / "old-runs" / "task-1" / "20260504T080950Z"
            previous_output_dir.mkdir(parents=True)
            (previous_output_dir / "run_summary.json").write_text(
                '{"best_model":"OldModel","metric_name":"rmse","metric_value":1.23}',
                encoding="utf-8",
            )
            (previous_output_dir / "leaderboard.csv").write_text("model,validation_score\nOldModel,-1.23\n", encoding="utf-8")
            old_timestamp = 1_700_000_000
            for path in [previous_output_dir, previous_output_dir / "run_summary.json", previous_output_dir / "leaderboard.csv"]:
                os.utime(path, (old_timestamp, old_timestamp))

            now = _utcnow()
            task = TaskRecord(
                id="task-1",
                team_id="team-1",
                created_by="user-1",
                name="Fresh rerun",
                description="Predict value.",
                status=TaskStatus.running,
                dataset_filename="train.csv",
                dataset_path=str(root / "train.csv"),
                last_run=RunSummary(
                    best_model="OldModel",
                    metric_name="rmse",
                    metric_value=1.23,
                    leaderboard=[],
                    output_dir=str(previous_output_dir),
                ),
                last_run_attempt=RunAttempt(output_dir=str(previous_output_dir)),
                created_at=now,
                updated_at=now,
            )
            settings = SimpleNamespace(run_output_dir=root / "runs", repo_root=root)

            progress = build_task_run_progress(task, settings, stale_after_seconds=1)

        self.assertIsNone(progress.output_dir)
        self.assertEqual(progress.status, "running")
        self.assertFalse(progress.stale)
        self.assertFalse(progress.artifacts.has_run_summary)

    def test_mlzero_summary_rejects_target_column_mismatch(self) -> None:
        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            (output_dir / "run_summary.json").write_text(
                """
                {
                  "best_model": "WeightedEnsemble_L2",
                  "metric_name": "rmse",
                  "metric_value": 0.01,
                  "validation_score": -0.01,
                  "tool": "autogluon.tabular",
                  "candidate_model_count": 1,
                  "problem_type": "regression",
                  "target_column": "Source_Year"
                }
                """,
                encoding="utf-8",
            )
            (output_dir / "leaderboard.csv").write_text(
                "model,validation_score\nWeightedEnsemble_L2,-0.01\n",
                encoding="utf-8",
            )
            (output_dir / "token_usage.json").write_text(
                '{"total":{"total_input_tokens":1,"total_output_tokens":1,"total_tokens":2}}',
                encoding="utf-8",
            )
            task = _task()
            task.label_column = "Value"
            task.problem_type = "regression"
            executor = object.__new__(MLZeroExecutor)

            with self.assertRaisesRegex(RuntimeError, "target_column does not match"):
                MLZeroExecutor._build_summary(executor, output_dir, task=task)

    def test_coder_agent_rejects_truncated_python_candidate(self) -> None:
        external_src = Path(__file__).resolve().parents[2] / "external" / "autogluon-assistant" / "src"
        sys.path.insert(0, str(external_src))
        try:
            from autogluon.assistant.agents.coder_agent import _python_code_completion_issue

            issue = _python_code_completion_issue("if run_sum")
        finally:
            try:
                sys.path.remove(str(external_src))
            except ValueError:
                pass

        self.assertIsNotNone(issue)
        self.assertIn("expected ':'", issue)
