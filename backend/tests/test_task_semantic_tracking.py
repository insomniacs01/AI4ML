from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from backend.app.models.task import (
    TaskRecord,
    TaskSemanticUpdateRequest,
    TaskStageRoutingRecord,
    TaskStatus,
    WorkflowStage,
    WorkflowStageStatus,
)
from backend.app.services import task_semantic_tracking


def _task(*, dataset_path: str | None = "dataset/train.csv") -> TaskRecord:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return TaskRecord(
        id="task-semantic-tracking",
        team_id="team-1",
        created_by="user-1",
        name="Semantic Tracking",
        description="Track semantic corrections.",
        status=TaskStatus.planning,
        dataset_path=dataset_path,
        label_column="target",
        problem_type="classification",
        created_at=now,
        updated_at=now,
    )


def _payload() -> TaskSemanticUpdateRequest:
    return TaskSemanticUpdateRequest(
        label_column="target",
        problem_type="classification",
        metric_name="Macro_F1",
        correction_note="Confirmed by user.",
    )


def test_record_human_semantic_update_stages_records_analysis_and_pending_stages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow_stage_calls: list[dict] = []
    stage_map_calls: list[dict] = []
    selection = TaskStageRoutingRecord(
        stage=WorkflowStage.data_analysis,
        connector_id="connector-1",
        model_name="model-1",
        selection_source="task_override",
    )

    monkeypatch.setattr(
        task_semantic_tracking,
        "_record_workflow_stage",
        lambda *args, **kwargs: workflow_stage_calls.append(kwargs),
    )
    monkeypatch.setattr(
        task_semantic_tracking,
        "_record_stage_selection_map",
        lambda *args, **kwargs: stage_map_calls.append(kwargs),
    )

    task_semantic_tracking.record_human_semantic_update_stages(
        _task(),
        SimpleNamespace(access_token="token"),
        payload=_payload(),
        stage_selection_map={WorkflowStage.data_analysis.value: selection},
    )

    assert workflow_stage_calls == [
        {
            "stage": WorkflowStage.data_analysis,
            "stage_status": WorkflowStageStatus.completed,
            "summary": "用户已人工修正任务语义：目标列 target，任务类型 classification，指标 macro_f1。",
            "selection": selection,
            "artifact_refs": ["dataset/train.csv"],
            "log_excerpt": "Confirmed by user.",
        }
    ]
    assert stage_map_calls == [
        {
            "stage_selection_map": {WorkflowStage.data_analysis.value: selection},
            "status_by_stage": {
                WorkflowStage.feature_engineering: WorkflowStageStatus.pending,
                WorkflowStage.model_selection: WorkflowStageStatus.pending,
                WorkflowStage.training_validation: WorkflowStageStatus.pending,
                WorkflowStage.report_generation: WorkflowStageStatus.pending,
            },
            "summary_by_stage": task_semantic_tracking.SEMANTIC_UPDATE_PENDING_SUMMARIES,
            "artifact_refs": ["dataset/train.csv"],
        }
    ]


def test_record_human_semantic_update_stages_omits_artifacts_without_dataset_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow_stage_calls: list[dict] = []
    stage_map_calls: list[dict] = []
    monkeypatch.setattr(
        task_semantic_tracking,
        "_record_workflow_stage",
        lambda *args, **kwargs: workflow_stage_calls.append(kwargs),
    )
    monkeypatch.setattr(
        task_semantic_tracking,
        "_record_stage_selection_map",
        lambda *args, **kwargs: stage_map_calls.append(kwargs),
    )

    task_semantic_tracking.record_human_semantic_update_stages(
        _task(dataset_path=None),
        SimpleNamespace(access_token="token"),
        payload=_payload(),
        stage_selection_map={},
    )

    assert workflow_stage_calls[0]["artifact_refs"] is None
    assert stage_map_calls[0]["artifact_refs"] is None
