from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.app.models.connector import ConnectorTestStatus, ConnectorWireApi, StoredConnectorRecord
from backend.app.models.governance import AIRoutingPolicyRecord
from backend.app.models.task import (
    TaskRecord,
    TaskStageRoutingOverrideInput,
    TaskStageRoutingRecord,
    TaskStatus,
    WorkflowStage,
)
from backend.app.services.task_routing_selection import (
    IncompleteStageRouteError,
    InvalidTaskStageRoutingOverrideError,
    MissingStageConnectorError,
    MissingStageModelError,
    RoutingRuntimeContext,
    build_stage_override_map,
    build_stage_selection_map,
    resolve_preferred_selection,
    resolve_stage_selection,
    validate_task_stage_routing_overrides,
)


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _connector(
    connector_id: str = "connector-1",
    *,
    model_name: str = "default-model",
    display_name: str = "Connector One",
) -> StoredConnectorRecord:
    return StoredConnectorRecord(
        id=connector_id,
        team_id="team-1",
        created_by="user-1",
        display_name=display_name,
        base_url="https://example.test/v1",
        model_name=model_name,
        wire_api=ConnectorWireApi.chat_completions,
        api_key="secret",
        is_active=True,
        last_test_status=ConnectorTestStatus.passed,
        created_at=NOW,
        updated_at=NOW,
    )


def _task(*, stage_routing: list[TaskStageRoutingRecord] | None = None) -> TaskRecord:
    return TaskRecord(
        id="task-1",
        team_id="team-1",
        created_by="user-1",
        name="Routing Task",
        description="Resolve stage routing.",
        status=TaskStatus.planning,
        dataset_filename="train.csv",
        dataset_path="D:/tmp/train.csv",
        stage_routing=stage_routing or [],
        created_at=NOW,
        updated_at=NOW,
    )


def _context(*, policies: dict[str, AIRoutingPolicyRecord] | None = None) -> RoutingRuntimeContext:
    return RoutingRuntimeContext(team_policies=policies or {}, connector_cache={})


def _resolver(connectors: dict[str, StoredConnectorRecord]):
    return lambda connector_id: connectors.get(connector_id)


def test_build_stage_override_map_normalizes_stage_keys() -> None:
    task = _task(
        stage_routing=[
            TaskStageRoutingRecord(
                stage="code_generation",
                connector_id="connector-1",
                model_name="model-a",
                selection_source="task_override",
            )
        ]
    )

    stage_map = build_stage_override_map(task)

    assert list(stage_map) == [WorkflowStage.feature_engineering.value]


def test_validate_task_stage_routing_overrides_rejects_model_without_connector() -> None:
    with pytest.raises(InvalidTaskStageRoutingOverrideError, match="connector_id"):
        validate_task_stage_routing_overrides(
            [
                TaskStageRoutingOverrideInput(
                    stage=WorkflowStage.requirement_analysis,
                    model_name="model-without-connector",
                )
            ]
        )


def test_resolve_stage_selection_prefers_task_override_over_team_policy() -> None:
    task_connector = _connector("task-connector", model_name="task-default")
    policy_connector = _connector("policy-connector", model_name="policy-default")
    task = _task(
        stage_routing=[
            TaskStageRoutingRecord(
                stage=WorkflowStage.data_analysis,
                connector_id=task_connector.id,
                model_name="task-model",
                selection_source="task_override",
            )
        ]
    )
    context = _context(
        policies={
            WorkflowStage.data_analysis.value: AIRoutingPolicyRecord(
                team_id="team-1",
                stage=WorkflowStage.data_analysis.value,
                connector_id=policy_connector.id,
                model_name="policy-model",
            )
        }
    )

    selection = resolve_stage_selection(
        task,
        context,
        WorkflowStage.data_analysis,
        connector_resolver=_resolver({task_connector.id: task_connector, policy_connector.id: policy_connector}),
    )

    assert selection is not None
    assert selection.connector.id == task_connector.id
    assert selection.model_name == "task-model"
    assert selection.selection_source == "task_override"
    assert selection.stage_record.connector_display_name == "Connector One"


def test_resolve_stage_selection_uses_team_policy_and_connector_model_fallback() -> None:
    connector = _connector("policy-connector", model_name="policy-default")
    context = _context(
        policies={
            WorkflowStage.model_selection.value: AIRoutingPolicyRecord(
                team_id="team-1",
                stage=WorkflowStage.model_selection.value,
                connector_id=connector.id,
            )
        }
    )

    selection = resolve_stage_selection(
        _task(),
        context,
        WorkflowStage.model_selection,
        connector_resolver=_resolver({connector.id: connector}),
    )

    assert selection is not None
    assert selection.connector.id == connector.id
    assert selection.model_name == "policy-default"
    assert selection.selection_source == "team_policy"


def test_resolve_stage_selection_rejects_incomplete_missing_connector_and_missing_model() -> None:
    model_only_task = _task(
        stage_routing=[
            TaskStageRoutingRecord(
                stage=WorkflowStage.requirement_analysis,
                model_name="model-without-connector",
                selection_source="task_override",
            )
        ]
    )
    with pytest.raises(IncompleteStageRouteError, match="connector_id"):
        resolve_stage_selection(
            model_only_task,
            _context(),
            WorkflowStage.requirement_analysis,
            connector_resolver=_resolver({}),
        )

    missing_connector_context = _context(
        policies={
            WorkflowStage.data_analysis.value: AIRoutingPolicyRecord(
                team_id="team-1",
                stage=WorkflowStage.data_analysis.value,
                connector_id="missing-connector",
            )
        }
    )
    with pytest.raises(MissingStageConnectorError, match="missing-connector"):
        resolve_stage_selection(
            _task(),
            missing_connector_context,
            WorkflowStage.data_analysis,
            connector_resolver=_resolver({}),
        )

    empty_model_connector = _connector("connector-empty-model", model_name="")
    missing_model_context = _context(
        policies={
            WorkflowStage.training_validation.value: AIRoutingPolicyRecord(
                team_id="team-1",
                stage=WorkflowStage.training_validation.value,
                connector_id=empty_model_connector.id,
            )
        }
    )
    with pytest.raises(MissingStageModelError, match="没有可用模型名"):
        resolve_stage_selection(
            _task(),
            missing_model_context,
            WorkflowStage.training_validation,
            connector_resolver=_resolver({empty_model_connector.id: empty_model_connector}),
        )


def test_build_stage_selection_map_and_preferred_selection_do_not_use_active_connector_fallback() -> None:
    connector = _connector()
    assert resolve_preferred_selection(
        _task(),
        _context(),
        [WorkflowStage.requirement_analysis],
        connector_resolver=_resolver({connector.id: connector}),
    ) is None

    context = _context(
        policies={
            WorkflowStage.report_generation.value: AIRoutingPolicyRecord(
                team_id="team-1",
                stage=WorkflowStage.report_generation.value,
                connector_id=connector.id,
                model_name="report-model",
            )
        }
    )
    stage_map = build_stage_selection_map(
        _task(),
        context,
        connector_resolver=_resolver({connector.id: connector}),
    )

    assert list(stage_map) == [WorkflowStage.report_generation.value]
    assert stage_map[WorkflowStage.report_generation.value].model_name == "report-model"
