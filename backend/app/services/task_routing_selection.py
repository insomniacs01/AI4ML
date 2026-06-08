from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from backend.app.models.connector import StoredConnectorRecord
from backend.app.models.governance import AIRoutingPolicyRecord
from backend.app.models.task import (
    PRIMARY_WORKFLOW_STAGES,
    TaskRecord,
    TaskStageRoutingOverrideInput,
    TaskStageRoutingRecord,
    WorkflowStage,
    normalize_workflow_stage,
)


ConnectorResolver = Callable[[str], StoredConnectorRecord | None]


@dataclass(frozen=True)
class ResolvedStageSelection:
    stage: WorkflowStage
    connector: StoredConnectorRecord
    model_name: str
    selection_source: str
    stage_record: TaskStageRoutingRecord


@dataclass
class RoutingRuntimeContext:
    team_policies: dict[str, AIRoutingPolicyRecord]
    connector_cache: dict[str, StoredConnectorRecord | None]


class StageRoutingError(ValueError):
    pass


class IncompleteStageRouteError(StageRoutingError):
    def __init__(self, stage: WorkflowStage, selection_source: str) -> None:
        self.stage = stage
        self.selection_source = selection_source
        super().__init__(
            f"{stage.value} 阶段的 {selection_source} 路由只配置了模型名但没有 connector_id。"
            "请显式选择连接器；系统不会再用当前激活连接器兜底。"
        )


class InvalidTaskStageRoutingOverrideError(StageRoutingError):
    def __init__(self, stage: WorkflowStage) -> None:
        self.stage = stage
        super().__init__(f"{stage.value} 阶段只填写了模型名但没有 connector_id。请显式选择连接器。")


class MissingStageConnectorError(StageRoutingError):
    def __init__(self, stage: WorkflowStage, selection_source: str, connector_id: str) -> None:
        self.stage = stage
        self.selection_source = selection_source
        self.connector_id = connector_id
        super().__init__(f"{stage.value} 阶段的 {selection_source} 路由引用了不存在的连接器：{connector_id}")


class MissingStageModelError(StageRoutingError):
    def __init__(self, stage: WorkflowStage, selection_source: str) -> None:
        self.stage = stage
        self.selection_source = selection_source
        super().__init__(f"{stage.value} 阶段的 {selection_source} 路由没有可用模型名。")


def build_stage_override_map(task: TaskRecord) -> dict[str, TaskStageRoutingRecord]:
    return {normalize_workflow_stage(item.stage).value: item for item in task.stage_routing}


def validate_task_stage_routing_overrides(items: list[TaskStageRoutingOverrideInput]) -> None:
    for item in items:
        stage = normalize_workflow_stage(item.stage)
        if item.model_name and item.model_name.strip() and not item.connector_id:
            raise InvalidTaskStageRoutingOverrideError(stage)


def resolve_stage_selection(
    task: TaskRecord,
    runtime_context: RoutingRuntimeContext,
    stage: WorkflowStage,
    *,
    connector_resolver: ConnectorResolver,
) -> ResolvedStageSelection | None:
    normalized_stage = normalize_workflow_stage(stage)
    stage_key = normalized_stage.value
    task_override = build_stage_override_map(task).get(stage_key)
    team_policy = runtime_context.team_policies.get(stage_key)

    for selection_source, connector_id, model_name_override in _candidate_specs(task_override, team_policy):
        if not connector_id:
            raise IncompleteStageRouteError(normalized_stage, selection_source)

        connector = connector_resolver(connector_id)
        if connector is None:
            raise MissingStageConnectorError(normalized_stage, selection_source, connector_id)

        resolved_model_name = (model_name_override or connector.model_name or "").strip()
        if not resolved_model_name:
            raise MissingStageModelError(normalized_stage, selection_source)

        stage_record = TaskStageRoutingRecord(
            stage=normalized_stage,
            connector_id=connector.id,
            connector_display_name=connector.display_name,
            model_name=resolved_model_name,
            selection_source=selection_source,
        )
        return ResolvedStageSelection(
            stage=normalized_stage,
            connector=connector,
            model_name=resolved_model_name,
            selection_source=selection_source,
            stage_record=stage_record,
        )

    return None


def build_stage_selection_map(
    task: TaskRecord,
    runtime_context: RoutingRuntimeContext,
    *,
    connector_resolver: ConnectorResolver,
) -> dict[str, TaskStageRoutingRecord]:
    resolved: dict[str, TaskStageRoutingRecord] = {}
    for stage in PRIMARY_WORKFLOW_STAGES:
        selection = resolve_stage_selection(
            task,
            runtime_context,
            stage,
            connector_resolver=connector_resolver,
        )
        if selection is not None:
            resolved[stage.value] = selection.stage_record
    return resolved


def resolve_preferred_selection(
    task: TaskRecord,
    runtime_context: RoutingRuntimeContext,
    stages: list[WorkflowStage],
    *,
    connector_resolver: ConnectorResolver,
) -> ResolvedStageSelection | None:
    for stage in stages:
        selection = resolve_stage_selection(
            task,
            runtime_context,
            stage,
            connector_resolver=connector_resolver,
        )
        if selection is not None:
            return selection
    return None


def _candidate_specs(
    task_override: TaskStageRoutingRecord | None,
    team_policy: AIRoutingPolicyRecord | None,
) -> list[tuple[str, str | None, str | None]]:
    candidates: list[tuple[str, str | None, str | None]] = []
    if task_override and (task_override.connector_id or task_override.model_name):
        candidates.append(("task_override", task_override.connector_id, task_override.model_name))
    if team_policy and (team_policy.connector_id or team_policy.model_name):
        candidates.append(("team_policy", team_policy.connector_id, team_policy.model_name))
    return candidates
