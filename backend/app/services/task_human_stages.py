from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from backend.app.models.task import (
    HumanInteractionRequestStatus,
    PRIMARY_WORKFLOW_STAGES,
    TaskHumanRequestRecord,
    TaskRecord,
    TaskStageRoutingRecord,
    TaskStatus,
    WorkflowStage,
    WorkflowStageRecord,
    WorkflowStageStatus,
    normalize_workflow_stage,
)
from backend.app.services.task_human_context import get_task_human_loop


STAGE_ORDER = list(PRIMARY_WORKFLOW_STAGES)
ACTIVE_REQUEST_STATUSES = {
    HumanInteractionRequestStatus.pending,
    HumanInteractionRequestStatus.open,
}


@dataclass(frozen=True)
class StageBlueprint:
    stage: WorkflowStage
    status: WorkflowStageStatus
    summary: str


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
        effective_status = get_progress_status(task)

        return apply_rerun_stage_hint(
            task,
            [
                requirement_stage_blueprint(task),
                data_analysis_stage_blueprint(task, effective_status),
                feature_engineering_stage_blueprint(task, effective_status),
                model_selection_stage_blueprint(task, effective_status),
                training_validation_stage_blueprint(task, effective_status),
                report_generation_stage_blueprint(task, effective_status),
            ],
        )

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


def requirement_stage_blueprint(task: TaskRecord) -> StageBlueprint:
    status = WorkflowStageStatus.completed if task.dataset_filename else WorkflowStageStatus.pending
    summary = (
        "Task description and dataset are available for the next steps."
        if task.dataset_filename
        else "Waiting for task creation details and CSV upload."
    )
    return StageBlueprint(WorkflowStage.requirement_analysis, status, summary)


def data_analysis_stage_blueprint(task: TaskRecord, effective_status: TaskStatus) -> StageBlueprint:
    if task.label_column and task.problem_type:
        return StageBlueprint(
            WorkflowStage.data_analysis,
            WorkflowStageStatus.completed,
            f"Detected label column '{task.label_column}' and task type '{task.problem_type}'.",
        )
    if task.dataset_filename:
        status = (
            WorkflowStageStatus.running
            if effective_status in {TaskStatus.planning, TaskStatus.uploaded}
            else WorkflowStageStatus.pending
        )
        return StageBlueprint(
            WorkflowStage.data_analysis,
            status,
            "Dataset is uploaded. Waiting for AI analysis to infer label column, problem type, and metric.",
        )
    return StageBlueprint(
        WorkflowStage.data_analysis,
        WorkflowStageStatus.pending,
        "No dataset is available for AI data analysis yet.",
    )


def feature_engineering_stage_blueprint(task: TaskRecord, effective_status: TaskStatus) -> StageBlueprint:
    return StageBlueprint(
        WorkflowStage.feature_engineering,
        build_generation_stage_status(task, effective_status),
        build_generation_stage_summary(
            task,
            effective_status,
            pending_summary="Feature engineering has not started yet.",
            completed_summary="A recent Codex attempt already produced code and intermediate artifacts.",
        ),
    )


def model_selection_stage_blueprint(task: TaskRecord, effective_status: TaskStatus) -> StageBlueprint:
    return StageBlueprint(
        WorkflowStage.model_selection,
        build_generation_stage_status(task, effective_status),
        build_generation_stage_summary(
            task,
            effective_status,
            pending_summary="Model selection has not started yet.",
            completed_summary="A recent Codex attempt already explored at least one model candidate.",
        ),
    )


def training_validation_stage_blueprint(task: TaskRecord, effective_status: TaskStatus) -> StageBlueprint:
    if effective_status == TaskStatus.running:
        return StageBlueprint(
            WorkflowStage.training_validation,
            WorkflowStageStatus.running,
            "Codex is training and validating candidate models.",
        )
    if effective_status == TaskStatus.failed and task.last_run_attempt:
        return StageBlueprint(
            WorkflowStage.training_validation,
            WorkflowStageStatus.failed,
            task.notes or "The latest training or validation attempt failed.",
        )
    if task.last_run:
        metric_label = task.last_run.metric_name or "validation_score"
        return StageBlueprint(
            WorkflowStage.training_validation,
            WorkflowStageStatus.completed,
            f"The latest run completed with {metric_label} = {task.last_run.metric_value}.",
        )
    return StageBlueprint(
        WorkflowStage.training_validation,
        WorkflowStageStatus.pending,
        "Training and validation have not started yet.",
    )


def report_generation_stage_blueprint(task: TaskRecord, effective_status: TaskStatus) -> StageBlueprint:
    if task.status == TaskStatus.published:
        return StageBlueprint(
            WorkflowStage.report_generation,
            WorkflowStageStatus.completed,
            "The latest report has already been published.",
        )
    if task.last_run:
        status = WorkflowStageStatus.completed if effective_status == TaskStatus.completed else WorkflowStageStatus.pending
        return StageBlueprint(
            WorkflowStage.report_generation,
            status,
            f"The latest report is ready for review. Best model: {task.last_run.best_model}.",
        )
    if task.last_run_attempt:
        return StageBlueprint(
            WorkflowStage.report_generation,
            WorkflowStageStatus.pending,
            "Artifacts exist from the latest attempt, but a final report is not ready yet.",
        )
    return StageBlueprint(
        WorkflowStage.report_generation,
        WorkflowStageStatus.pending,
        "Report generation has not started yet.",
    )


def apply_rerun_stage_hint(task: TaskRecord, blueprints: list[StageBlueprint]) -> list[StageBlueprint]:
    human_loop = get_task_human_loop(task)
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
    next_blueprints: list[StageBlueprint] = []
    for blueprint in blueprints:
        current_index = order_index.get(blueprint.stage.value, len(order_index))
        if current_index < rerun_index:
            next_blueprints.append(blueprint)
            continue
        next_blueprints.append(
            StageBlueprint(
                stage=blueprint.stage,
                status=WorkflowStageStatus.pending,
                summary=(
                    f"人工协同要求从“{blueprint.stage.value}”所在链路重新运行。"
                    + (f"原因：{reason}" if isinstance(reason, str) and reason else "")
                ),
            )
        )
    return next_blueprints


def get_progress_status(task: TaskRecord) -> TaskStatus:
    if task.status not in {TaskStatus.paused_for_review, TaskStatus.waiting_human}:
        return task.status
    return get_previous_status(task)


def get_previous_status(task: TaskRecord) -> TaskStatus:
    human_loop = get_task_human_loop(task)
    if human_loop.get("rerun_requested"):
        return TaskStatus.uploaded if task.dataset_filename else TaskStatus.draft
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


def build_generation_stage_status(task: TaskRecord, effective_status: TaskStatus) -> WorkflowStageStatus:
    if effective_status == TaskStatus.running:
        return WorkflowStageStatus.running
    if task.last_run or task.last_run_attempt:
        return WorkflowStageStatus.completed
    return WorkflowStageStatus.pending


def build_generation_stage_summary(
    task: TaskRecord,
    effective_status: TaskStatus,
    *,
    pending_summary: str,
    completed_summary: str,
) -> str:
    if effective_status == TaskStatus.running:
        return "Codex is actively generating or refining training logic."
    if task.last_run or task.last_run_attempt:
        return completed_summary
    return pending_summary


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
