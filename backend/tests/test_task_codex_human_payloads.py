from __future__ import annotations

from datetime import datetime, timezone

from backend.app.models.task import TaskRecord, TaskStatus
from backend.app.services.task_codex_human_payloads import (
    build_codex_improvement_review_payload,
    build_codex_plan_approval_payload,
)


def _task(*, workspace_path: str | None = "workspace") -> TaskRecord:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return TaskRecord(
        id="task-codex-human-payloads",
        team_id="team-1",
        created_by="user-1",
        name="Payloads",
        description="Build Codex human payloads.",
        status=TaskStatus.waiting_human,
        codex_workspace_path=workspace_path,
        created_at=now,
        updated_at=now,
    )


def test_build_codex_plan_approval_payload_includes_plan_and_artifacts() -> None:
    payload = build_codex_plan_approval_payload(
        _task(),
        plan_path="workspace/output/plan.md",
        plan_text="Train and report.",
    )

    assert payload == {
        "request_type": "codex_plan_approval",
        "title": "确认 Codex 建模计划",
        "summary": "Codex 已写入 output/plan.md。确认后将按该计划继续执行训练、验证和交付。",
        "suggested_action": "确认并继续 Codex 执行。",
        "plan_text": "Train and report.",
        "artifact_paths": ["workspace/output/plan.md", "workspace"],
        "checkpoint_mode": "codex_plan_gate",
    }


def test_build_codex_plan_approval_payload_filters_empty_artifacts() -> None:
    payload = build_codex_plan_approval_payload(
        _task(workspace_path=None),
        plan_path=None,
        plan_text="",
    )

    assert payload["artifact_paths"] == []


def test_build_codex_improvement_review_payload_includes_options_and_advisor_diagnosis() -> None:
    payload = build_codex_improvement_review_payload(
        _task(),
        improvement_plan_path="workspace/output/improvement_plan.md",
        improvement_plan_text="Try additional features.",
        artifacts={"advisor_diagnosis": {"status": "needs_improvement"}},
    )

    assert payload["request_type"] == "codex_improvement_review"
    assert payload["title"] == "确认是否继续改进"
    assert payload["improvement_plan_text"] == "Try additional features."
    assert payload["artifact_paths"] == ["workspace/output/improvement_plan.md", "workspace"]
    assert payload["checkpoint_mode"] == "codex_improvement_gate"
    assert payload["options"] == [
        {"id": "continue_improvement", "label": "继续改进"},
        {"id": "stop_and_report", "label": "停止并生成报告"},
    ]
    assert payload["advisor_diagnosis"] == {"status": "needs_improvement"}


def test_build_codex_improvement_review_payload_ignores_non_dict_advisor_diagnosis() -> None:
    payload = build_codex_improvement_review_payload(
        _task(),
        improvement_plan_path=None,
        improvement_plan_text="",
        artifacts={"advisor_diagnosis": "raw"},
    )

    assert "advisor_diagnosis" not in payload
