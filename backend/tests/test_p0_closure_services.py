from __future__ import annotations

import json
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
from backend.app.api.routes.task_route_common import _repair_stale_running_task
from backend.app.services.executors.mlzero_executor import MLZeroExecutor, MLZeroRunError
from backend.app.services.task_agent_collaboration import append_stage_agent_messages, build_task_agent_collaboration_response
from backend.app.services.task_agent_loop import refresh_agent_loop_after_analysis, refresh_agent_loop_after_run
from backend.app.services.task_reporting import build_task_model_report
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

    def test_agent_snapshot_hides_raw_runtime_error_text(self) -> None:
        now = _utcnow()
        task = _task()
        raw_error = (
            "MLZero run failed. Return code: 130 Output directory: "
            "D:\\333\\AI4ML\\storage\\mlzero_runs\\task-1\\20260509T075524Z logs.txt tail: "
            "2026-05-09 INFO [autogluon.assistant.tools_registry.indexing] Tutorial retrieval is disabled. "
            "2026-05-09 BRIEF [autogluon.assistant.agents.data_perception_agent] Reading file."
        )
        stages = [
            WorkflowStageRecord(
                id="stage-1",
                team_id=task.team_id,
                task_id=task.id,
                stage=WorkflowStage.training_validation,
                status=WorkflowStageStatus.failed,
                summary=f"训练或验证失败：{raw_error}",
                log_excerpt=raw_error,
                created_at=now,
                updated_at=now,
            )
        ]
        message = TaskAgentMessageRecord(
            id="message-1",
            team_id=task.team_id,
            task_id=task.id,
            from_agent_id=WorkflowStage.training_validation.value,
            to_agent_id=WorkflowStage.report_generation.value,
            stage=WorkflowStage.training_validation,
            message_type="blocker",
            status="sent",
            content=f"Agent-Epsilon 遇到阻塞：{raw_error}",
            payload={"summary": raw_error, "log_excerpt": raw_error},
            correlation_id="agent-msg:raw",
            time=now,
        )

        snapshot = build_task_agent_collaboration_response(
            task,
            stages=stages,
            requests=[],
            agent_messages=[message],
        )
        combined = "\n".join(
            [
                *(stage.summary or "" for stage in snapshot.stages),
                *(stage.log_excerpt or "" for stage in snapshot.stages),
                *(agent.current_task for agent in snapshot.agents),
                *(agent.log_excerpt or "" for agent in snapshot.agents),
                *(event.text for event in snapshot.events),
                *(message.content for message in snapshot.messages),
                *(
                    str(message.payload.get("summary", "")) + str(message.payload.get("log_excerpt", ""))
                    for message in snapshot.messages
                    if isinstance(message.payload, dict)
                ),
            ]
        ).lower()

        self.assertNotIn("mlzero run failed", combined)
        self.assertNotIn("return code: 130", combined)
        self.assertNotIn("autogluon.assistant", combined)
        self.assertIn("系统已隐藏原始运行日志", combined)

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
        self.assertEqual(progress.observer_status, "运行目录长时间没有更新")
        self.assertIn("没有新日志或生成文件写入", progress.current_activity)
        self.assertIn("候选模型对比已可用，当前最佳 WeightedEnsemble_L2", [insight.headline for insight in progress.insights])

    def test_run_progress_blocks_when_mlzero_reaches_max_iterations(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            output_dir = root / "runs" / "task-1" / "20260509T092337Z"
            node_output = output_dir / "node_5" / "output"
            node_output.mkdir(parents=True)
            (output_dir / "logs.txt").write_text(
                "\n".join(
                    [
                        "2026-05-09 17:54:18 BRIEF    [autogluon.assistant.coding_agent] Starting MCTS iteration 6/6",
                        "2026-05-09 18:00:09 WARNING  [autogluon.assistant.coding_agent] Warning: Reached maximum iterations (6)",
                        "2026-05-09 18:00:09 BRIEF    [autogluon.assistant.coding_agent] MCTS search completed in 2145.03 seconds",
                        f"2026-05-09 18:00:09 BRIEF    [autogluon.assistant.coding_agent] Output saved in {output_dir}",
                    ]
                ),
                encoding="utf-8",
            )
            (node_output / "run_summary.json").write_text(
                json.dumps(
                    {
                        "best_model": "WeightedEnsemble_L2",
                        "metric_name": "root_mean_squared_error",
                        "metric_value": -6.465405018217532e19,
                        "validation_score": 6.465405018217532e19,
                        "tool": "autogluon.tabular",
                        "candidate_model_count": 4,
                        "target_column": "Value",
                        "problem_type": "regression",
                    }
                ),
                encoding="utf-8",
            )
            (node_output / "leaderboard.csv").write_text(
                "model,validation_score,fit_time,pred_time,rank\n"
                "WeightedEnsemble_L2,-6.465405018217532e19,2.4,3.9,1\n"
                "KNeighbors,-6.465405018217532e19,2.4,3.9,2\n"
                "RandomForest,-7.67907244429533e20,41.7,0.03,3\n"
                "ExtraTrees,-1.3287800167668528e21,27,0.02,4\n",
                encoding="utf-8",
            )
            (output_dir / "token_usage.json").write_text(
                '{"total":{"total_input_tokens":10,"total_output_tokens":20,"total_tokens":30}}',
                encoding="utf-8",
            )
            task = TaskRecord(
                id="task-1",
                team_id="team-1",
                created_by="user-1",
                name="Max iterations run",
                description="Predict value.",
                label_column="Value",
                problem_type="regression",
                status=TaskStatus.running,
                dataset_filename="train.csv",
                dataset_path=str(root / "train.csv"),
                last_run_attempt=RunAttempt(output_dir=str(output_dir)),
                created_at=_utcnow(),
                updated_at=_utcnow(),
            )
            settings = SimpleNamespace(run_output_dir=root / "runs", repo_root=root)

            progress = build_task_run_progress(task, settings, stale_after_seconds=3600)

        self.assertEqual(progress.status, "blocked")
        self.assertFalse(progress.stale)
        self.assertEqual(progress.observer_status, "已达到最大搜索轮次")
        self.assertIn("搜索已经结束", progress.observer_detail or "")
        self.assertEqual(progress.current_iteration, 6)
        self.assertEqual(progress.total_iterations, 6)

    def test_repair_marks_terminal_running_task_blocked_without_waiting_for_stale(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            output_dir = root / "runs" / "task-1" / "20260509T092337Z"
            node_output = output_dir / "node_5" / "output"
            node_output.mkdir(parents=True)
            (output_dir / "logs.txt").write_text(
                "\n".join(
                    [
                        "2026-05-09 18:00:09 WARNING  [autogluon.assistant.coding_agent] Warning: Reached maximum iterations (6)",
                        "2026-05-09 18:00:09 BRIEF    [autogluon.assistant.coding_agent] MCTS search completed in 2145.03 seconds",
                        f"2026-05-09 18:00:09 BRIEF    [autogluon.assistant.coding_agent] Output saved in {output_dir}",
                    ]
                ),
                encoding="utf-8",
            )
            (node_output / "run_summary.json").write_text(
                json.dumps(
                    {
                        "best_model": "WeightedEnsemble_L2",
                        "metric_name": "rmse",
                        "metric_value": 1.0,
                        "validation_score": -1.0,
                        "tool": "autogluon.tabular",
                        "candidate_model_count": 1,
                        "target_column": "Value",
                        "problem_type": "regression",
                    }
                ),
                encoding="utf-8",
            )
            (node_output / "leaderboard.csv").write_text("model,validation_score\nWeightedEnsemble_L2,-1\n", encoding="utf-8")
            (output_dir / "token_usage.json").write_text(
                '{"total":{"total_input_tokens":10,"total_output_tokens":20,"total_tokens":30}}',
                encoding="utf-8",
            )
            task = TaskRecord(
                id="task-1",
                team_id="team-1",
                created_by="user-1",
                name="Terminal run",
                description="Predict value.",
                label_column="Value",
                problem_type="regression",
                status=TaskStatus.running,
                dataset_filename="train.csv",
                dataset_path=str(root / "train.csv"),
                last_run_attempt=RunAttempt(output_dir=str(output_dir)),
                created_at=_utcnow(),
                updated_at=_utcnow(),
            )
            settings = SimpleNamespace(run_output_dir=root / "runs", repo_root=root)
            progress = build_task_run_progress(task, settings, stale_after_seconds=3600)

            class FakeTaskStore:
                def __init__(self) -> None:
                    self.saved_task: TaskRecord | None = None
                    self.run_attempt_status: str | None = None

                def save_task(self, saved_task: TaskRecord, *, access_token: str) -> TaskRecord:
                    self.saved_task = saved_task
                    return saved_task

                def upsert_run_attempt(self, saved_task: TaskRecord, **kwargs) -> None:
                    self.run_attempt_status = kwargs["status"]

                def upsert_workflow_stage(self, **kwargs) -> WorkflowStageRecord:
                    return WorkflowStageRecord(
                        id="stage",
                        team_id=task.team_id,
                        task_id=task.id,
                        stage=kwargs["stage"],
                        status=kwargs["status"],
                        summary=kwargs.get("summary"),
                        artifact_refs=kwargs.get("artifact_refs"),
                        log_excerpt=kwargs.get("log_excerpt"),
                        created_at=_utcnow(),
                        updated_at=_utcnow(),
                    )

                def append_audit_log(self, **kwargs):
                    return None

            fake_store = FakeTaskStore()
            team_access = SimpleNamespace(
                team_id=task.team_id,
                access_token="token",
                user=SimpleNamespace(id="user-1"),
            )

            with patch("backend.app.api.routes.task_route_common.get_task_store", return_value=fake_store), patch(
                "backend.app.api.routes.task_route_common.get_settings",
                return_value=settings,
            ):
                repaired = _repair_stale_running_task(task, team_access, progress)

        self.assertTrue(repaired.repaired)
        self.assertEqual(repaired.repair_action, "terminal_running_marked_repair_blocked")
        self.assertEqual(repaired.status, "blocked")
        self.assertIs(fake_store.saved_task, task)
        self.assertEqual(fake_store.run_attempt_status, "running")
        self.assertIn("已达到最大搜索轮次", fake_store.saved_task.notes)
        self.assertIsNotNone(fake_store.saved_task.last_run_attempt)
        self.assertEqual(fake_store.saved_task.last_run_attempt.error_artifact_path, (output_dir / "logs.txt").as_posix())

    def test_run_progress_blocks_when_mlzero_is_interrupted(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            output_dir = root / "runs" / "task-1" / "20260509T110853Z"
            node_output = output_dir / "node_4" / "output"
            node_output.mkdir(parents=True)
            (output_dir / "logs.txt").write_text(
                "2026-05-09 19:28:22 BRIEF    [autogluon.assistant.coding_agent] Starting MCTS iteration 6/6\n",
                encoding="utf-8",
            )
            (output_dir / "debugging_logs.txt").write_text(
                "\n".join(
                    [
                        "2026-05-09 19:28:24 DEBUG    [httpcore.http11] receive_response_headers.started request=<Request [b'POST']>",
                        "2026-05-09 19:29:49 DEBUG    [httpcore.http11] receive_response_headers.failed exception=KeyboardInterrupt()",
                    ]
                ),
                encoding="utf-8",
            )
            (node_output / "run_summary.json").write_text(
                json.dumps(
                    {
                        "best_model": "LinearModel",
                        "metric_name": "rmse",
                        "metric_value": 1.0,
                        "validation_score": -1.0,
                        "tool": "autogluon.tabular",
                        "candidate_model_count": 1,
                        "target_column": "Value",
                        "problem_type": "regression",
                    }
                ),
                encoding="utf-8",
            )
            (node_output / "leaderboard.json").write_text(
                json.dumps([{"model": "LinearModel", "validation_score": -1.0}]),
                encoding="utf-8",
            )
            task = TaskRecord(
                id="task-1",
                team_id="team-1",
                created_by="user-1",
                name="Interrupted run",
                description="Predict value.",
                label_column="Value",
                problem_type="regression",
                status=TaskStatus.running,
                dataset_filename="train.csv",
                dataset_path=str(root / "train.csv"),
                last_run_attempt=RunAttempt(output_dir=str(output_dir)),
                created_at=_utcnow(),
                updated_at=_utcnow(),
            )
            settings = SimpleNamespace(run_output_dir=root / "runs", repo_root=root)

            progress = build_task_run_progress(task, settings, stale_after_seconds=3600)

        self.assertEqual(progress.status, "blocked")
        self.assertFalse(progress.stale)
        self.assertEqual(progress.observer_status, "自动建模进程已被中断")
        self.assertIn("KeyboardInterrupt", progress.observer_detail or "")
        self.assertIn("mlzero_interrupted", [insight.event_type for insight in progress.insights])

    def test_repair_marks_interrupted_running_task_blocked_without_waiting_for_stale(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            output_dir = root / "runs" / "task-1" / "20260509T110853Z"
            output_dir.mkdir(parents=True)
            (output_dir / "debugging_logs.txt").write_text(
                "2026-05-09 19:29:49 DEBUG    [httpcore.http11] receive_response_headers.failed exception=KeyboardInterrupt()\n",
                encoding="utf-8",
            )
            task = TaskRecord(
                id="task-1",
                team_id="team-1",
                created_by="user-1",
                name="Interrupted repair",
                description="Predict value.",
                label_column="Value",
                problem_type="regression",
                status=TaskStatus.running,
                dataset_filename="train.csv",
                dataset_path=str(root / "train.csv"),
                last_run_attempt=RunAttempt(output_dir=str(output_dir)),
                created_at=_utcnow(),
                updated_at=_utcnow(),
            )
            settings = SimpleNamespace(run_output_dir=root / "runs", repo_root=root)
            progress = build_task_run_progress(task, settings, stale_after_seconds=3600)

            class FakeTaskStore:
                def __init__(self) -> None:
                    self.saved_task: TaskRecord | None = None
                    self.run_attempt_status: str | None = None

                def save_task(self, saved_task: TaskRecord, *, access_token: str) -> TaskRecord:
                    self.saved_task = saved_task
                    return saved_task

                def upsert_run_attempt(self, saved_task: TaskRecord, **kwargs) -> None:
                    self.run_attempt_status = kwargs["status"]

                def upsert_stage_record(self, **kwargs) -> WorkflowStageRecord:
                    return WorkflowStageRecord(
                        id="stage",
                        team_id=task.team_id,
                        task_id=task.id,
                        stage=kwargs["stage"],
                        status=kwargs["status"],
                        summary=kwargs.get("summary"),
                        artifact_refs=kwargs.get("artifact_refs"),
                        log_excerpt=kwargs.get("log_excerpt"),
                        created_at=_utcnow(),
                        updated_at=_utcnow(),
                    )

                def upsert_agent_run(self, **kwargs):
                    return SimpleNamespace(agent_id=kwargs["agent_id"], stage=kwargs["stage"])

                def append_agent_event(self, **kwargs):
                    return None

                def append_agent_message(self, **kwargs):
                    return None

            fake_store = FakeTaskStore()
            team_access = SimpleNamespace(
                team_id=task.team_id,
                access_token="token",
                user=SimpleNamespace(id="user-1"),
            )

            with patch("backend.app.api.routes.task_route_common.get_task_store", return_value=fake_store), patch(
                "backend.app.api.routes.task_route_common.get_settings",
                return_value=settings,
            ):
                repaired = _repair_stale_running_task(task, team_access, progress)

        self.assertTrue(repaired.repaired)
        self.assertEqual(repaired.repair_action, "terminal_running_marked_repair_blocked")
        self.assertEqual(repaired.status, "blocked")
        self.assertIn("自动建模进程已被中断", fake_store.saved_task.notes)

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

    def test_run_progress_prefers_latest_node_summary_over_older_nodes(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            output_dir = root / "runs" / "task-1" / "20260507T081027Z"
            old_node = output_dir / "node_0" / "output"
            new_node = output_dir / "node_4" / "output"
            old_node.mkdir(parents=True)
            new_node.mkdir(parents=True)
            (old_node / "run_summary.json").write_text(
                json.dumps(
                    {
                        "best_model": "OldModel",
                        "metric_name": "rmse",
                        "metric_value": 10.0,
                        "validation_score": -10.0,
                        "tool": "autogluon.tabular",
                        "candidate_model_count": 1,
                        "problem_type": "regression",
                        "target_column": "Source_Year",
                    }
                ),
                encoding="utf-8",
            )
            (old_node / "leaderboard.json").write_text(
                json.dumps([{"model": "OldModel", "validation_score": -10.0}]),
                encoding="utf-8",
            )
            (new_node / "run_summary.json").write_text(
                json.dumps(
                    {
                        "best_model": "WeightedEnsemble_L2",
                        "metric_name": "rmse",
                        "metric_value": 0.338,
                        "validation_score": -0.338,
                        "tool": "autogluon.tabular",
                        "candidate_model_count": 3,
                        "problem_type": "regression",
                        "target_column": "Value",
                    }
                ),
                encoding="utf-8",
            )
            (new_node / "leaderboard.json").write_text(
                json.dumps(
                    [
                        {"model": "WeightedEnsemble_L2", "validation_score": -0.338},
                        {"model": "KNeighbors", "validation_score": -0.4},
                        {"model": "RandomForest", "validation_score": -0.45},
                    ]
                ),
                encoding="utf-8",
            )
            (output_dir / "token_usage.json").write_text(
                '{"total":{"total_input_tokens":10,"total_output_tokens":20,"total_tokens":30}}',
                encoding="utf-8",
            )
            old_timestamp = 1_700_000_000
            new_timestamp = old_timestamp + 600
            for path in [old_node, old_node / "run_summary.json", old_node / "leaderboard.json"]:
                os.utime(path, (old_timestamp, old_timestamp))
            for path in [new_node, new_node / "run_summary.json", new_node / "leaderboard.json"]:
                os.utime(path, (new_timestamp, new_timestamp))

            now = _utcnow()
            task = TaskRecord(
                id="task-1",
                team_id="team-1",
                created_by="user-1",
                name="Latest summary",
                description="Predict value.",
                status=TaskStatus.completed,
                dataset_filename="train.csv",
                dataset_path=str(root / "train.csv"),
                last_run_attempt=RunAttempt(output_dir=str(output_dir)),
                created_at=now,
                updated_at=now,
            )
            settings = SimpleNamespace(run_output_dir=root / "runs", repo_root=root)

            progress = build_task_run_progress(task, settings)

        self.assertTrue(progress.artifacts.run_summary_path.endswith("node_4/output/run_summary.json"))
        self.assertEqual(progress.artifacts.best_model, "WeightedEnsemble_L2")
        self.assertEqual(progress.artifacts.validation_score, -0.338)

    def test_run_progress_preserves_autogluon_model_fit_events_from_node_stderr(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            output_dir = root / "runs" / "task-1" / "20260505T080950Z"
            states_dir = output_dir / "node_0" / "states"
            states_dir.mkdir(parents=True)
            (states_dir / "stderr_b367.txt").write_text(
                "\n".join(
                    [
                        "Fitting 3 L1 models, fit_strategy=\"sequential\" ...",
                        "Fitting model: KNeighbors ... Training model for up to 260.16s of the 260.16s of remaining time.",
                        "\t-0.2238\t = Validation score   (-root_mean_squared_error)",
                        "\t3.13s\t = Training   runtime",
                        "Fitting model: RandomForest ... Training model for up to 252.54s of the 252.54s of remaining time.",
                        "\t-0.0\t = Validation score   (-root_mean_squared_error)",
                        "\t105.4s\t = Training   runtime",
                        "Fitting model: ExtraTrees ... Training model for up to 147.02s of the 147.02s of remaining time.",
                        "\t-0.0002\t = Validation score   (-root_mean_squared_error)",
                        "\t72.25s\t = Training   runtime",
                        "Fitting model: WeightedEnsemble_L2 ... Training model for up to 260.16s of the 74.67s of remaining time.",
                        "\t-0.0\t = Validation score   (-root_mean_squared_error)",
                        "\t0.01s\t = Training   runtime",
                    ]
                ),
                encoding="utf-8",
            )
            (output_dir / "detail_logs.txt").write_text(
                "\n".join(
                    f"2026-05-05 16:29:49 DEBUG    [httpcore.http11] unrelated late log line {index}"
                    for index in range(700)
                ),
                encoding="utf-8",
            )
            now = _utcnow()
            task = TaskRecord(
                id="task-1",
                team_id="team-1",
                created_by="user-1",
                name="Autogluon run",
                description="Fit tabular models.",
                status=TaskStatus.completed,
                dataset_filename="train.csv",
                dataset_path=str(root / "train.csv"),
                last_run_attempt=RunAttempt(output_dir=str(output_dir)),
                created_at=now,
                updated_at=now,
            )
            settings = SimpleNamespace(run_output_dir=root / "runs", repo_root=root)

            progress = build_task_run_progress(task, settings)

        model_events = [event for event in progress.events if event.event_type.startswith("model_fit")]
        self.assertEqual(len(model_events), 8)
        self.assertEqual(progress.current_model, "WeightedEnsemble_L2")
        self.assertEqual(progress.completed_model_count, 4)
        self.assertEqual(progress.total_model_count, 4)
        self.assertEqual(progress.current_model_elapsed_seconds, 0.01)
        self.assertEqual(progress.current_model_time_budget_seconds, 260.16)
        self.assertEqual(progress.latest_validation_score, -0.0)
        self.assertIn("RandomForest", [event.message for event in model_events][2])
        self.assertEqual({event.source for event in model_events}, {"node_0/stderr"})
        insight_headlines = [insight.headline for insight in progress.insights]
        self.assertIn("开始训练候选模型 RandomForest", insight_headlines)
        self.assertIn("候选模型 WeightedEnsemble_L2 训练完成", insight_headlines)
        self.assertEqual(progress.observer_status, "候选模型 WeightedEnsemble_L2 训练完成")
        self.assertIn("真实训练耗时", progress.observer_detail or "")

    def test_run_progress_does_not_use_raw_llm_request_options_as_activity(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            output_dir = root / "runs" / "task-1" / "20260505T080950Z"
            output_dir.mkdir(parents=True)
            (output_dir / "debugging_logs.txt").write_text(
                "2026-05-05 16:29:49 DEBUG    [openai._base_client] Request options: "
                "{'method': 'post', 'url': '/chat/completions', 'headers': {'X-Stainless-Raw-Response': 'true'}, "
                "'idempotency_key': 'retry-key', 'json_data': {'messages': [{'content': 'very long prompt'}]}}\n",
                encoding="utf-8",
            )
            now = _utcnow()
            task = TaskRecord(
                id="task-1",
                team_id="team-1",
                created_by="user-1",
                name="Noisy run",
                description="Fit tabular models.",
                status=TaskStatus.running,
                dataset_filename="train.csv",
                dataset_path=str(root / "train.csv"),
                last_run_attempt=RunAttempt(output_dir=str(output_dir)),
                created_at=now,
                updated_at=now,
            )
            settings = SimpleNamespace(run_output_dir=root / "runs", repo_root=root)

            progress = build_task_run_progress(task, settings)

        self.assertNotIn("Request options", progress.current_activity)
        self.assertNotIn("json_data", progress.current_activity)
        self.assertNotIn("Request options", progress.observer_status or "")
        self.assertNotIn("json_data", progress.observer_detail or "")
        self.assertEqual(progress.observer_status, "暂未收到可解释信号")
        self.assertIn("可解释信号", progress.current_activity)

    def test_run_progress_keeps_stage_when_coder_llm_times_out(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            output_dir = root / "runs" / "task-1" / "20260507T052033Z"
            output_dir.mkdir(parents=True)
            (output_dir / "logs.txt").write_text(
                "\n".join(
                    [
                        "2026-05-07 13:21:20 BRIEF    [autogluon.assistant.coding_agent] Starting MCTS iteration 1/6",
                        "2026-05-07 13:21:22 INFO     [autogluon.assistant.managers.node_manager] CoderAgent: starting to build and send code-generation prompt to the LLM.",
                        "2026-05-07 13:22:53 ERROR    [autogluon.assistant.llm.base_chat] Attempt 1 failed: APITimeoutError: Request timed out.",
                        "2026-05-07 13:24:57 ERROR    [autogluon.assistant.llm.base_chat] Attempt 2 failed: APITimeoutError: Request timed out.",
                    ]
                ),
                encoding="utf-8",
            )
            now = datetime(2026, 5, 7, 5, 20, 33, tzinfo=timezone.utc)
            task = TaskRecord(
                id="task-1",
                team_id="team-1",
                created_by="user-1",
                name="Timeout run",
                description="Fit tabular models.",
                status=TaskStatus.running,
                dataset_filename="train.csv",
                dataset_path=str(root / "train.csv"),
                last_run_attempt=RunAttempt(output_dir=str(output_dir)),
                created_at=now,
                updated_at=now,
            )
            settings = SimpleNamespace(run_output_dir=root / "runs", repo_root=root)

            progress = build_task_run_progress(task, settings, stale_after_seconds=3600)

        self.assertEqual(progress.current_stage, WorkflowStage.feature_engineering)
        self.assertEqual(progress.observer_stage, WorkflowStage.feature_engineering)
        self.assertEqual(progress.current_iteration, 1)
        self.assertEqual(progress.total_iterations, 6)
        self.assertIsNone(progress.current_model)
        self.assertEqual(progress.observer_status, "代码生成阶段 LLM 请求超时")
        self.assertIn("第 2 次请求超时", progress.observer_detail or "")

    def test_recoverable_failed_attempt_is_reported_as_blocked_not_failed(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            output_dir = root / "runs" / "task-1" / "20260507T052033Z"
            output_dir.mkdir(parents=True)
            (output_dir / "logs.txt").write_text(
                "\n".join(
                    [
                        "2026-05-07 13:21:20 BRIEF    [autogluon.assistant.coding_agent] Starting MCTS iteration 1/6",
                        "2026-05-07 13:22:53 ERROR    [autogluon.assistant.llm.base_chat] Attempt 1 failed: APITimeoutError: Request timed out.",
                    ]
                ),
                encoding="utf-8",
            )
            now = datetime(2026, 5, 7, 5, 20, 33, tzinfo=timezone.utc)
            task = TaskRecord(
                id="task-1",
                team_id="team-1",
                created_by="user-1",
                name="Recoverable failed run",
                description="Fit tabular models.",
                status=TaskStatus.failed,
                notes="MLZero run failed. Attempt 1 failed: APITimeoutError: Request timed out.",
                dataset_filename="train.csv",
                dataset_path=str(root / "train.csv"),
                last_run_attempt=RunAttempt(output_dir=str(output_dir)),
                created_at=now,
                updated_at=now,
            )
            settings = SimpleNamespace(run_output_dir=root / "runs", repo_root=root)

            progress = build_task_run_progress(task, settings, stale_after_seconds=3600)

        self.assertEqual(progress.status, "blocked")
        self.assertLess(progress.progress_percent, 100)
        self.assertEqual(progress.observer_status, "自动修复受阻")
        self.assertNotIn("APITimeoutError", progress.observer_detail or "")
        self.assertIn("系统已隐藏原始运行日志", progress.observer_detail or "")

    def test_repair_blocked_running_task_keeps_old_output_dir_visible(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            output_dir = root / "runs" / "task-1" / "20260507T052033Z"
            output_dir.mkdir(parents=True)
            log_path = output_dir / "logs.txt"
            log_path.write_text(
                "2026-05-07 13:22:53 ERROR    [autogluon.assistant.llm.base_chat] Attempt 1 failed: APITimeoutError: Request timed out.",
                encoding="utf-8",
            )
            old_timestamp = datetime(2026, 5, 7, 5, 22, 53, tzinfo=timezone.utc).timestamp()
            os.utime(log_path, (old_timestamp, old_timestamp))
            os.utime(output_dir, (old_timestamp, old_timestamp))
            task = TaskRecord(
                id="task-1",
                team_id="team-1",
                created_by="user-1",
                name="Blocked run",
                description="Fit tabular models.",
                status=TaskStatus.running,
                notes="自动修复受阻：代码生成阶段遇到可恢复问题。原因：APITimeoutError",
                dataset_filename="train.csv",
                dataset_path=str(root / "train.csv"),
                last_run_attempt=RunAttempt(output_dir=str(output_dir)),
                created_at=_utcnow(),
                updated_at=_utcnow(),
            )
            settings = SimpleNamespace(run_output_dir=root / "runs", repo_root=root)

            progress = build_task_run_progress(task, settings, stale_after_seconds=1)

        self.assertEqual(progress.status, "blocked")
        self.assertEqual(progress.output_dir, str(output_dir))
        self.assertFalse(progress.stale)

    def test_mlzero_run_error_carries_recovery_metadata(self) -> None:
        error = MLZeroRunError("provider timeout", recoverable=True, retry_stage="feature_engineering")

        self.assertTrue(error.recoverable)
        self.assertEqual(error.retry_stage, "feature_engineering")

    def test_mlzero_runtime_env_uses_long_provider_timeout(self) -> None:
        executor = object.__new__(MLZeroExecutor)
        executor.settings = SimpleNamespace(
            mlzero_openai_api_key="test-key",
            mlzero_provider_base_url="https://example.test/v1",
            mlzero_provider_wire_api="chat_completions",
            mlzero_provider_user_agent="AI4ML Test",
            mlzero_provider_request_timeout_seconds=30,
            mlzero_hf_endpoint="https://hf-mirror.com",
            mlzero_python_executable=Path(sys.executable),
        )

        env = MLZeroExecutor._build_runtime_env(executor)

        self.assertEqual(env["OPENAI_REQUEST_TIMEOUT"], "180")
        self.assertEqual(env["AI4ML_PYTHON_EXECUTABLE"], str(Path(sys.executable)))

    def test_mlzero_runtime_config_materializes_numeric_timeout(self) -> None:
        with TemporaryDirectory() as tmpdir:
            template_path = Path(tmpdir) / "template.yaml"
            template_path.write_text(
                """
continuous_improvement: false
llm:
  model: gpt-4-local
  proxy_url: http://127.0.0.1:8001/v1
  wire_api: chat_completions
  request_timeout: 60
python_coder:
  max_tokens: 4096
""".strip(),
                encoding="utf-8",
            )
            output_dir = Path(tmpdir) / "run"
            output_dir.mkdir()
            executor = object.__new__(MLZeroExecutor)
            executor.settings = SimpleNamespace(
                mlzero_config_path=template_path,
                mlzero_model_alias="deepseek-v3.2",
                mlzero_provider_base_url="https://example.test/v2",
                mlzero_provider_wire_api="chat_completions",
                mlzero_provider_request_timeout_seconds=30,
            )

            config_path = MLZeroExecutor._build_runtime_config(executor, output_dir, continuous_improvement=False)
            text = config_path.read_text(encoding="utf-8")

        self.assertIn("request_timeout: 180", text)
        self.assertIn('model: "deepseek-v3.2"', text)

    def test_mlzero_runtime_config_materializes_mcp_web_search(self) -> None:
        with TemporaryDirectory() as tmpdir:
            template_path = Path(tmpdir) / "template.yaml"
            template_path.write_text(
                """
continuous_improvement: false
mcp_web_search_enabled: false
mcp_web_search_server_url: ""
mcp_web_search_tool_name: ""
mcp_web_search_top_k: 5
mcp_web_search_timeout_seconds: 20
llm:
  model: gpt-4-local
  proxy_url: http://127.0.0.1:8001/v1
  wire_api: chat_completions
  request_timeout: 60
""".strip(),
                encoding="utf-8",
            )
            output_dir = Path(tmpdir) / "run"
            output_dir.mkdir()
            executor = object.__new__(MLZeroExecutor)
            executor.settings = SimpleNamespace(
                mlzero_config_path=template_path,
                mlzero_model_alias="deepseek-v3.2",
                mlzero_provider_base_url="https://example.test/v2",
                mlzero_provider_wire_api="chat_completions",
                mlzero_provider_request_timeout_seconds=30,
                mlzero_mcp_web_search_enabled=True,
                mlzero_mcp_web_search_server_url="http://127.0.0.1:8765/mcp",
                mlzero_mcp_web_search_tool_name="web_search",
                mlzero_mcp_web_search_top_k=7,
                mlzero_mcp_web_search_timeout_seconds=11,
            )

            config_path = MLZeroExecutor._build_runtime_config(executor, output_dir, continuous_improvement=False)
            text = config_path.read_text(encoding="utf-8")

        self.assertIn("mcp_web_search_enabled: true", text)
        self.assertIn('mcp_web_search_server_url: "http://127.0.0.1:8765/mcp"', text)
        self.assertIn('mcp_web_search_tool_name: "web_search"', text)
        self.assertIn("mcp_web_search_top_k: 7", text)
        self.assertIn("mcp_web_search_timeout_seconds: 11", text)

    def test_mlzero_search_plan_no_longer_depends_on_outer_timeout(self) -> None:
        executor = object.__new__(MLZeroExecutor)
        executor.settings = SimpleNamespace(
            mlzero_max_iterations=6,
            mlzero_continuous_improvement=False,
        )

        max_iterations, continuous_improvement = MLZeroExecutor._resolve_search_plan(executor, 20)

        self.assertEqual(max_iterations, 6)
        self.assertFalse(continuous_improvement)

    def test_mlzero_runtime_guidance_removes_training_time_limit_and_target_transform(self) -> None:
        executor = object.__new__(MLZeroExecutor)

        guidance = "\n".join(MLZeroExecutor._autogluon_runtime_guidance_lines(executor))

        self.assertIn("Do not pass a fit(time_limit=...)", guidance)
        self.assertIn("Do not manually log-transform", guidance)
        self.assertIn("RF/XT n_estimators", guidance)

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

    def test_mlzero_summary_skips_mismatched_candidate_and_uses_later_valid_summary(self) -> None:
        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            wrong_best_run = output_dir / "best_run" / "output"
            right_node = output_dir / "node_1" / "output"
            wrong_best_run.mkdir(parents=True)
            right_node.mkdir(parents=True)

            (wrong_best_run / "run_summary.json").write_text(
                json.dumps(
                    {
                        "best_model": "WrongModel",
                        "metric_name": "rmse",
                        "metric_value": 10.0,
                        "validation_score": -10.0,
                        "tool": "autogluon.tabular",
                        "candidate_model_count": 1,
                        "problem_type": "regression",
                        "target_column": "Source_Year",
                    }
                ),
                encoding="utf-8",
            )
            (wrong_best_run / "leaderboard.json").write_text(
                json.dumps([{"model": "WrongModel", "validation_score": -10.0}]),
                encoding="utf-8",
            )
            (right_node / "run_summary.json").write_text(
                json.dumps(
                    {
                        "best_model": "WeightedEnsemble_L2",
                        "metric_name": "rmse",
                        "metric_value": 0.338,
                        "validation_score": -0.338,
                        "tool": "autogluon.tabular",
                        "candidate_model_count": 2,
                        "problem_type": "regression",
                        "target_column": "Value",
                    }
                ),
                encoding="utf-8",
            )
            (right_node / "leaderboard.json").write_text(
                json.dumps(
                    [
                        {"model": "WeightedEnsemble_L2", "validation_score": -0.338},
                        {"model": "KNeighbors", "validation_score": -0.4},
                    ]
                ),
                encoding="utf-8",
            )
            (output_dir / "token_usage.json").write_text(
                '{"total":{"total_input_tokens":3,"total_output_tokens":4,"total_tokens":7}}',
                encoding="utf-8",
            )
            task = _task()
            task.label_column = "Value"
            task.problem_type = "regression"
            executor = object.__new__(MLZeroExecutor)

            summary = MLZeroExecutor._build_summary(executor, output_dir, task=task)

        self.assertEqual(summary.best_model, "WeightedEnsemble_L2")
        self.assertEqual(summary.metric_name, "rmse")
        self.assertAlmostEqual(summary.metric_value, 0.338)
        self.assertEqual(summary.validation_score, -0.338)
        self.assertEqual(summary.output_dir, str(output_dir))

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

    def test_coder_agent_rejects_inferred_last_column_target_when_label_is_known(self) -> None:
        external_src = Path(__file__).resolve().parents[2] / "external" / "autogluon-assistant" / "src"
        sys.path.insert(0, str(external_src))
        try:
            from autogluon.assistant.agents.coder_agent import _python_code_completion_issue

            issue = _python_code_completion_issue(
                '\n'.join(
                    [
                        'import pandas as pd',
                        'train_df = pd.read_csv("train.csv")',
                        'target_column = train_df.columns[-1]',
                        'validation_score = 0.1',
                        'print(validation_score)',
                    ]
                ),
                expected_label_column="Value",
            )
        finally:
            try:
                sys.path.remove(str(external_src))
            except ValueError:
                pass

        self.assertIsNotNone(issue)
        self.assertIn("Value", issue or "")
        self.assertIn("last dataframe column", issue or "")

    def test_data_perception_reads_text_and_csv_without_generated_reader_code(self) -> None:
        external_src = Path(__file__).resolve().parents[2] / "external" / "autogluon-assistant" / "src"
        sys.path.insert(0, str(external_src))
        try:
            from autogluon.assistant.agents.data_perception_agent import read_file_direct

            with TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                description_path = root / "descriptions.txt"
                csv_path = root / "train.csv"
                description_path.write_text("Task name: predict\nLabel column: Value\n", encoding="utf-8")
                csv_path.write_text("Feature,Value\n1,10\n2,20\n", encoding="utf-8")

                description = read_file_direct(str(description_path), max_chars=1000)
                csv_summary = read_file_direct(str(csv_path), max_chars=1000)
        finally:
            try:
                sys.path.remove(str(external_src))
            except ValueError:
                pass

        self.assertIn("Label column: Value", description)
        self.assertIn("CSV file read directly", csv_summary)
        self.assertIn("Columns (2)", csv_summary)
        self.assertIn("Value", csv_summary)

    def test_retriever_agent_converts_mcp_web_results_to_tutorials(self) -> None:
        external_src = Path(__file__).resolve().parents[2] / "external" / "autogluon-assistant" / "src"
        sys.path.insert(0, str(external_src))
        try:
            from autogluon.assistant.agents.retriever_agent import RetrieverAgent

            agent = object.__new__(RetrieverAgent)
            tutorials = RetrieverAgent._convert_mcp_results_to_tutorial_info(
                agent,
                [
                    {
                        "title": "AutoGluon Tabular Tutorial",
                        "url": "https://auto.gluon.ai/stable/tutorials/tabular/",
                        "snippet": "Train tabular models.",
                        "content": "Use TabularPredictor for tabular classification and regression.",
                    }
                ],
            )
        finally:
            try:
                sys.path.remove(str(external_src))
            except ValueError:
                pass

        self.assertEqual(len(tutorials), 1)
        self.assertEqual(tutorials[0].title, "AutoGluon Tabular Tutorial")
        self.assertTrue(str(tutorials[0].path).startswith("mcp-web://"))
        self.assertIn("Source: https://auto.gluon.ai/stable/tutorials/tabular/", tutorials[0].content or "")
        self.assertIn("TabularPredictor", tutorials[0].content or "")

    def test_model_report_includes_feature_target_relationships(self) -> None:
        with TemporaryDirectory() as tmpdir:
            dataset_path = Path(tmpdir) / "train.csv"
            dataset_path.write_text(
                "\n".join(
                    [
                        "FeatureA,FeatureB,Value",
                        "1,10,2",
                        "2,10,4",
                        "3,9,6",
                        "4,9,8",
                        "5,8,10",
                    ]
                ),
                encoding="utf-8",
            )
            task = _task(dataset_path)
            task.label_column = "Value"
            task.problem_type = "regression"
            task.last_run = RunSummary(
                best_model="RandomForest",
                metric_name="rmse",
                metric_value=0.1,
                validation_score=-0.1,
                leaderboard=[{"model": "RandomForest", "validation_score": -0.1}],
                output_dir=str(Path(tmpdir)),
            )

            report = build_task_model_report(task)

        self.assertGreaterEqual(len(report.feature_importance), 1)
        self.assertEqual(report.feature_importance[0].feature, "FeatureA")
        self.assertIn("FeatureA", "\n".join(report.relationship_notes))
        self.assertIn("特征与目标关系", report.report_markdown)
        self.assertIn("FeatureA", report.report_markdown)

    def test_model_report_includes_categorical_target_relationships(self) -> None:
        with TemporaryDirectory() as tmpdir:
            dataset_path = Path(tmpdir) / "train.csv"
            dataset_path.write_text(
                "\n".join(
                    [
                        "Plan,Age,Churn",
                        "A,20,yes",
                        "A,21,yes",
                        "B,58,no",
                        "B,60,no",
                        "A,22,yes",
                        "B,61,no",
                    ]
                ),
                encoding="utf-8",
            )
            task = _task(dataset_path)
            task.label_column = "Churn"
            task.problem_type = "binary"
            task.last_run = RunSummary(
                best_model="ExtraTrees",
                metric_name="accuracy",
                metric_value=1.0,
                validation_score=1.0,
                leaderboard=[{"model": "ExtraTrees", "validation_score": 1.0}],
                output_dir=str(Path(tmpdir)),
            )

            report = build_task_model_report(task)

        feature_names = [item.feature for item in report.feature_importance]
        self.assertIn("Plan", feature_names)
        self.assertIn("Age", feature_names)
        self.assertIn("Churn", "\n".join(report.relationship_notes))
        self.assertIn("特征与目标关系", report.report_markdown)

    def test_agent_loop_builds_baseline_and_tuning_attempts(self) -> None:
        with TemporaryDirectory() as tmpdir:
            dataset_path = Path(tmpdir) / "train.csv"
            dataset_path.write_text(
                "\n".join(
                    [
                        "Feature,Value",
                        "1,10",
                        "2,11",
                        "3,12",
                        "4,13",
                        "5,14",
                        "6,15",
                        "7,16",
                        "8,17",
                        "9,18",
                        "10,19",
                    ]
                ),
                encoding="utf-8",
            )
            task = _task(dataset_path)
            task.label_column = "Value"
            task.problem_type = "regression"
            task.structured_requirements = {"metric_name": "rmse"}

            refresh_agent_loop_after_analysis(task)
            loop = task.structured_requirements["agent_loop"]

            self.assertEqual(loop["baseline"]["status"], "completed")
            self.assertEqual(loop["baseline"]["metric_name"], "rmse")
            self.assertTrue(any(item["id"] == "target_column" and item["status"] == "passed" for item in loop["checklist"]))

            task.last_run = RunSummary(
                best_model="RandomForest",
                metric_name="rmse",
                metric_value=0.2,
                validation_score=-0.2,
                leaderboard=[{"model": "RandomForest", "validation_score": -0.2}],
                output_dir=str(Path(tmpdir)),
                token_usage=None,
            )
            refresh_agent_loop_after_run(task)
            loop = task.structured_requirements["agent_loop"]

            self.assertTrue(any(item["kind"] == "baseline" for item in loop["tuning_attempts"]))
            self.assertTrue(any(item["kind"] == "model_run" for item in loop["tuning_attempts"]))
            self.assertTrue(any(gate["id"] == "model_vs_baseline" for gate in loop["quality_gates"]))
            self.assertIn("iterative_tuning", [step["key"] for step in loop["workflow"]])

    def test_model_report_uses_detailed_experiment_template(self) -> None:
        with TemporaryDirectory() as tmpdir:
            dataset_path = Path(tmpdir) / "train.csv"
            dataset_path.write_text(
                "\n".join(
                    [
                        "Feature,Segment,Value",
                        "1,A,10",
                        "2,A,11",
                        "3,B,12",
                        "4,B,13",
                        "5,C,14",
                        "6,C,15",
                        "7,A,16",
                        "8,B,17",
                        "9,C,18",
                        "10,A,19",
                    ]
                ),
                encoding="utf-8",
            )
            task = _task(dataset_path)
            task.name = "Detailed Report Task"
            task.label_column = "Value"
            task.problem_type = "regression"
            task.structured_requirements = {"metric_name": "rmse"}
            refresh_agent_loop_after_analysis(task)
            task.last_run = RunSummary(
                best_model="RandomForest",
                metric_name="rmse",
                metric_value=0.2,
                validation_score=-0.2,
                leaderboard=[
                    {"model": "RandomForest", "validation_score": -0.2, "fit_time": 1.2, "pred_time": 0.03},
                    {"model": "KNeighbors", "validation_score": -0.5, "fit_time": 0.4, "pred_time": 0.02},
                ],
                output_dir=str(Path(tmpdir)),
                token_usage=None,
            )
            refresh_agent_loop_after_run(task)

            report = build_task_model_report(task)

        markdown = report.report_markdown
        self.assertIn("# Detailed Report Task 自动建模实验报告", markdown)
        self.assertIn("## 摘要", markdown)
        self.assertIn("## 1. 任务背景与目标", markdown)
        self.assertIn("## 2. 数据整理与质量检查", markdown)
        self.assertIn("## 4. 简单对照实验", markdown)
        self.assertIn("## 5. 自动建模实验", markdown)
        self.assertIn("## 6. 结果检查与优化过程", markdown)
        self.assertIn("## 9. 结论", markdown)
        self.assertIn("| 排名 | 模型 | validation_score | metric_value | fit_time | pred_time |", markdown)
        self.assertIn("正式模型对比", markdown)
        self.assertIn("相对简单对照", markdown)
