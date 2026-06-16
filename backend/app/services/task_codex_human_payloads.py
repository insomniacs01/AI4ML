from __future__ import annotations

from backend.app.models.task import TaskRecord


def build_codex_plan_approval_payload(
    task: TaskRecord,
    *,
    plan_path: str | None,
    plan_text: str,
    run_strategy: dict | None = None,
) -> dict:
    payload = {
        "request_type": "codex_plan_approval",
        "title": "确认 Codex 建模计划",
        "summary": "Codex 已写入 output/plan.md。请确认预测目标、成功阈值、最大改进轮数和第一轮候选模型；确认后将按该计划继续执行训练、验证和交付。",
        "suggested_action": "确认并继续 Codex 执行。",
        "plan_text": plan_text,
        "artifact_paths": [path for path in [plan_path, task.codex_workspace_path] if path],
        "checkpoint_mode": "codex_plan_gate",
    }
    if isinstance(run_strategy, dict):
        payload["run_strategy"] = run_strategy
    return payload


def build_codex_improvement_review_payload(
    task: TaskRecord,
    *,
    improvement_plan_path: str | None,
    improvement_plan_text: str,
    artifacts: dict | None,
) -> dict:
    payload = {
        "request_type": "codex_improvement_review",
        "title": "确认是否继续改进",
        "summary": "Codex 已写入 output/improvement_plan.md。当前结果未满足验收或继续改进需要人工确认。",
        "suggested_action": "选择继续改进，或不继续改进并按当前结果生成报告。",
        "improvement_plan_text": improvement_plan_text,
        "artifact_paths": [path for path in [improvement_plan_path, task.codex_workspace_path] if path],
        "checkpoint_mode": "codex_improvement_gate",
        "options": [
            {"id": "continue_improvement", "label": "继续改进"},
            {"id": "stop_and_report", "label": "按当前结果生成报告"},
        ],
    }
    advisor_diagnosis = artifacts.get("advisor_diagnosis") if isinstance(artifacts, dict) else None
    if isinstance(advisor_diagnosis, dict):
        payload["advisor_diagnosis"] = advisor_diagnosis
    return payload
