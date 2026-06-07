from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from backend.app.models.task import (
    TaskHumanRequestRecord,
    TaskRecord,
    TaskStageRoutingRecord,
    WorkflowStage,
    WorkflowStageRecord,
    WorkflowStageStatus,
    normalize_workflow_stage,
)
from backend.app.services.task_human_stage_blueprints import (
    STAGE_ORDER,
    StageBlueprint,
    build_stage_blueprints,
)
from backend.app.services.task_human_request_status import ACTIVE_HUMAN_REQUEST_STATUSES


ACTIVE_REQUEST_STATUSES = ACTIVE_HUMAN_REQUEST_STATUSES


@dataclass(frozen=True)
class StageSnapshotInput:
    blueprint: StageBlueprint
    stage_key: str
    open_request: TaskHumanRequestRecord | None
    selection: TaskStageRoutingRecord | None
    existing: WorkflowStageRecord | None
    summary: str
    artifact_refs: list[str]

    @property
    def stage(self) -> WorkflowStage:
        return self.blueprint.stage

    @property
    def status(self) -> WorkflowStageStatus:
        if self.open_request is not None:
            return WorkflowStageStatus.waiting_human
        return self.blueprint.status

    @property
    def selected_connector_id(self) -> str | None:
        if self.selection is not None and self.selection.connector_id is not None:
            return self.selection.connector_id
        return self.existing.selected_connector_id if self.existing else None

    @property
    def model_name(self) -> str | None:
        if self.selection is not None and self.selection.model_name is not None:
            return self.selection.model_name
        return self.existing.model_name if self.existing else None

    @property
    def selection_source(self) -> str | None:
        if self.selection is not None and self.selection.selection_source is not None:
            return self.selection.selection_source
        return self.existing.selection_source if self.existing else None


class HumanStageSnapshotBuilder:
    def build_stage_snapshot(
        self,
        task: TaskRecord,
        *,
        existing_records: dict[str, WorkflowStageRecord],
        requests: list[TaskHumanRequestRecord],
    ) -> list[WorkflowStageRecord]:
        now = datetime.now(timezone.utc)
        records = [
            self._workflow_stage_record(task, item, now=now)
            for item in self.iter_stage_snapshot_inputs(
                task,
                existing_records=existing_records,
                requests=requests,
                selection_map={stage_key(record.stage): record for record in task.stage_routing},
            )
        ]
        return sort_stages(records)

    def iter_stage_snapshot_inputs(
        self,
        task: TaskRecord,
        *,
        existing_records: dict[str, WorkflowStageRecord],
        requests: list[TaskHumanRequestRecord],
        selection_map: dict[str, TaskStageRoutingRecord],
    ):
        open_requests_by_stage = {
            stage_key(request.stage): request
            for request in requests
            if is_active_request(request)
        }
        for blueprint in self.build_stage_blueprints(task):
            key = stage_key(blueprint.stage)
            open_request = open_requests_by_stage.get(key)
            yield StageSnapshotInput(
                blueprint=blueprint,
                stage_key=key,
                open_request=open_request,
                selection=selection_map.get(key),
                existing=existing_records.get(key),
                summary=build_waiting_summary(open_request) if open_request else blueprint.summary,
                artifact_refs=collect_stage_artifacts(task, blueprint.stage),
            )

    def build_stage_blueprints(self, task: TaskRecord) -> list[StageBlueprint]:
        return build_stage_blueprints(task)

    @staticmethod
    def _workflow_stage_record(
        task: TaskRecord,
        item: StageSnapshotInput,
        *,
        now: datetime,
    ) -> WorkflowStageRecord:
        existing = item.existing
        return WorkflowStageRecord(
            id=existing.id if existing else f"virtual-{task.id}-{item.stage_key}",
            team_id=task.team_id,
            task_id=task.id,
            stage=item.stage,
            status=item.status,
            selected_connector_id=item.selected_connector_id,
            model_name=item.model_name,
            selection_source=item.selection_source,
            summary=item.summary,
            artifact_refs=item.artifact_refs,
            started_at=existing.started_at if existing else None,
            finished_at=existing.finished_at if existing else None,
            duration_seconds=existing.duration_seconds if existing else None,
            log_excerpt=existing.log_excerpt if existing else None,
            created_at=existing.created_at if existing else task.created_at,
            updated_at=existing.updated_at if existing else (task.updated_at or now),
        )


def collect_stage_artifacts(task: TaskRecord, stage: WorkflowStage) -> list[str]:
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


def build_waiting_summary(request: TaskHumanRequestRecord | None) -> str:
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


def sort_stages(stages: list[WorkflowStageRecord]) -> list[WorkflowStageRecord]:
    order_index = {stage.value: index for index, stage in enumerate(STAGE_ORDER)}
    return sorted(stages, key=lambda item: order_index.get(stage_key(item.stage), len(order_index)))


def is_active_request(request: TaskHumanRequestRecord) -> bool:
    return request.status in ACTIVE_REQUEST_STATUSES


def stage_key(stage: WorkflowStage | str) -> str:
    return normalize_workflow_stage(stage).value
