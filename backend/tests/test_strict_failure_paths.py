from __future__ import annotations

from datetime import datetime, timezone
from unittest import TestCase

from fastapi import HTTPException
from pydantic import ValidationError

from backend.app.core.supabase_auth import SupabaseUser, TeamAccessContext
from backend.app.models.connector import ConnectorTestStatus, ConnectorWireApi, StoredConnectorRecord
from backend.app.models.governance import AIRoutingPoliciesUpdateRequest, AIRoutingPolicyRecord, AIRoutingPolicyUpsertRequest
from backend.app.models.task import (
    TaskRecord,
    TaskStageRoutingOverrideInput,
    TaskStageRoutingRecord,
    TaskStatus,
    WorkflowStage,
)
from backend.app.services import task_routing


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _team_access() -> TeamAccessContext:
    return TeamAccessContext(
        team_id="team-1",
        role="admin",
        user=SupabaseUser(id="user-1", email="user@example.com", raw={}),
        access_token="token",
    )


def _connector() -> StoredConnectorRecord:
    now = _utcnow()
    return StoredConnectorRecord(
        id="connector-1",
        team_id="team-1",
        created_by="user-1",
        display_name="Strict Connector",
        base_url="https://example.test/v1",
        model_name="strict-model",
        wire_api=ConnectorWireApi.chat_completions,
        api_key="secret",
        is_active=True,
        last_test_status=ConnectorTestStatus.passed,
        created_at=now,
        updated_at=now,
    )


def _task(*, stage_routing: list[TaskStageRoutingRecord] | None = None) -> TaskRecord:
    now = _utcnow()
    return TaskRecord(
        id="task-1",
        team_id="team-1",
        created_by="user-1",
        name="Strict Task",
        description="Train a tabular model.",
        status=TaskStatus.planning,
        dataset_filename="train.csv",
        dataset_path="D:/tmp/train.csv",
        stage_routing=stage_routing or [],
        created_at=now,
        updated_at=now,
    )


class StrictFailurePathTests(TestCase):
    def test_active_connector_is_not_used_without_explicit_stage_route(self) -> None:
        connector = _connector()
        runtime_context = task_routing._RoutingRuntimeContext(
            team_policies={},
            connector_cache={connector.id: connector},
        )

        with self.assertRaises(HTTPException) as raised:
            task_routing._resolve_preferred_selection(
                _task(),
                _team_access(),
                runtime_context,
                [WorkflowStage.requirement_analysis],
            )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("阶段 AI 路由", str(raised.exception.detail))

    def test_explicit_task_stage_route_still_resolves(self) -> None:
        connector = _connector()
        runtime_context = task_routing._RoutingRuntimeContext(
            team_policies={},
            connector_cache={connector.id: connector},
        )
        task = _task(
            stage_routing=[
                TaskStageRoutingRecord(
                    stage=WorkflowStage.requirement_analysis,
                    connector_id=connector.id,
                    connector_display_name=connector.display_name,
                    model_name="strict-model",
                    selection_source="task_override",
                )
            ]
        )

        selection = task_routing._resolve_preferred_selection(
            task,
            _team_access(),
            runtime_context,
            [WorkflowStage.requirement_analysis],
        )

        self.assertEqual(selection.connector.id, connector.id)
        self.assertEqual(selection.selection_source, "task_override")

    def test_model_only_task_route_is_rejected_instead_of_using_active_connector(self) -> None:
        connector = _connector()
        runtime_context = task_routing._RoutingRuntimeContext(
            team_policies={},
            connector_cache={connector.id: connector},
        )
        task = _task(
            stage_routing=[
                TaskStageRoutingRecord(
                    stage=WorkflowStage.requirement_analysis,
                    model_name="model-without-connector",
                    selection_source="task_override",
                )
            ]
        )

        with self.assertRaises(HTTPException) as raised:
            task_routing._resolve_preferred_selection(
                task,
                _team_access(),
                runtime_context,
                [WorkflowStage.requirement_analysis],
            )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("connector_id", str(raised.exception.detail))

    def test_team_policy_without_primary_route_is_not_used_as_runtime_route(self) -> None:
        connector = _connector()
        runtime_context = task_routing._RoutingRuntimeContext(
            team_policies={
                WorkflowStage.requirement_analysis.value: AIRoutingPolicyRecord(
                    team_id="team-1",
                    stage=WorkflowStage.requirement_analysis.value,
                )
            },
            connector_cache={connector.id: connector},
        )

        with self.assertRaises(HTTPException) as raised:
            task_routing._resolve_preferred_selection(
                _task(),
                _team_access(),
                runtime_context,
                [WorkflowStage.requirement_analysis],
            )

        self.assertEqual(raised.exception.status_code, 409)

    def test_task_stage_input_rejects_model_without_connector(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            task_routing._validate_task_stage_routing_overrides(
                [
                    TaskStageRoutingOverrideInput(
                        stage=WorkflowStage.requirement_analysis,
                        model_name="model-without-connector",
                    )
                ]
            )

        self.assertEqual(raised.exception.status_code, 422)
        self.assertIn("connector_id", str(raised.exception.detail))

    def test_team_routing_update_schema_rejects_fallback_payload(self) -> None:
        with self.assertRaises(ValidationError):
            AIRoutingPoliciesUpdateRequest.model_validate(
                {
                    "items": [
                        {
                            "stage": WorkflowStage.requirement_analysis.value,
                            "fallback_connector_id": "connector-1",
                        }
                    ]
                }
            )
