from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.app.models.task import TaskRecord
from backend.app.services.task_agent_baseline_metrics import baseline_completed, compare_metric, metric_snapshot
from backend.app.services.task_agent_improvement import build_next_improvement


def normalize_attempts(raw_attempts: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_attempts, list):
        return []
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(raw_attempts):
        if not isinstance(item, dict):
            continue
        payload = dict(item)
        payload["attempt_index"] = int(payload.get("attempt_index", index))
        normalized.append(payload)
    return normalized[-20:]


def merge_baseline_attempt(attempts: list[dict[str, Any]], baseline: Any) -> list[dict[str, Any]]:
    if not baseline_completed(baseline):
        return attempts
    if any(item.get("correlation_key") == "baseline" for item in attempts):
        return attempts
    attempts.append(
        {
            "attempt_index": len(attempts),
            "correlation_key": "baseline",
            "kind": "baseline",
            "hypothesis": "先用最简单、可解释的方法建立最低参考线。",
            "action": baseline.get("label") or baseline.get("method") or "简单对照",
            "changed_config": {"method": baseline.get("method")},
            "metric_before": None,
            "metric_after": metric_snapshot(baseline),
            "accepted": True,
            "status": "completed",
            "notes": "简单对照已作为后续自动建模的比较对象。",
            "created_at": baseline.get("generated_at") or _now_iso(),
        }
    )
    return attempts


def merge_run_attempt(attempts: list[dict[str, Any]], task: TaskRecord, baseline: Any) -> list[dict[str, Any]]:
    if not task.last_run:
        return attempts
    key = f"run:{task.last_run.output_dir}"
    if any(item.get("correlation_key") == key for item in attempts):
        return attempts
    comparison = None
    if baseline_completed(baseline):
        comparison = compare_metric(
            task.last_run.metric_name,
            task.last_run.metric_value,
            str(baseline.get("metric_name") or ""),
            float(baseline.get("metric_value")),
        )
    accepted = comparison["better"] if comparison else True
    attempts.append(
        {
            "attempt_index": len(attempts),
            "correlation_key": key,
            "kind": "model_run",
            "hypothesis": "使用自动建模搜索候选模型，期望超过简单对照。",
            "action": f"训练并比较 {len(task.last_run.leaderboard or [])} 个候选模型。",
            "changed_config": {
                "best_model": task.last_run.best_model,
                "metric_name": task.last_run.metric_name,
            },
            "metric_before": metric_snapshot(baseline) if baseline_completed(baseline) else None,
            "metric_after": {
                "metric_name": task.last_run.metric_name,
                "metric_value": task.last_run.metric_value,
                "validation_score": task.last_run.validation_score,
            },
            "accepted": bool(accepted),
            "status": "accepted" if accepted else "needs_improvement",
            "output_dir": task.last_run.output_dir,
            "notes": _run_attempt_note(comparison),
            "created_at": _now_iso(),
        }
    )
    return attempts[-20:]


def merge_improvement_suggestion(
    attempts: list[dict[str, Any]],
    task: TaskRecord,
    quality_gates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not task.last_run:
        return attempts
    suggestion = build_next_improvement(task, quality_gates)
    if not suggestion or suggestion.get("status") == "not_needed":
        return attempts
    key = f"proposal:{task.last_run.output_dir}:{suggestion.get('reason_code')}"
    if any(item.get("correlation_key") == key for item in attempts):
        return attempts
    attempts.append(
        {
            "attempt_index": len(attempts),
            "correlation_key": key,
            "kind": "improvement_proposal",
            "hypothesis": suggestion.get("hypothesis"),
            "action": suggestion.get("action"),
            "changed_config": suggestion.get("changed_config") or {},
            "metric_before": {
                "metric_name": task.last_run.metric_name,
                "metric_value": task.last_run.metric_value,
                "validation_score": task.last_run.validation_score,
            },
            "metric_after": None,
            "accepted": False,
            "status": "proposed",
            "output_dir": task.last_run.output_dir,
            "notes": suggestion.get("detail"),
            "created_at": _now_iso(),
        }
    )
    return attempts[-20:]


def merge_run_failure_attempt(
    attempts: list[dict[str, Any]],
    task: TaskRecord,
    baseline: Any,
    *,
    error_summary: str | None = None,
    output_dir: str | None = None,
) -> list[dict[str, Any]]:
    failure_key = f"run_failure:{output_dir or task.updated_at.isoformat()}"
    if not any(item.get("correlation_key") == failure_key for item in attempts):
        attempts.append(
            {
                "attempt_index": len(attempts),
                "correlation_key": failure_key,
                "kind": "run_failure",
                "hypothesis": "自动建模遇到可恢复或失败路径，需要根据日志修复后再继续。",
                "action": "保留失败文件和诊断信息，等待重新运行或人工复核。",
                "changed_config": {},
                "metric_before": metric_snapshot(baseline),
                "metric_after": None,
                "accepted": False,
                "status": "failed",
                "output_dir": output_dir,
                "notes": error_summary or task.notes or "本次运行未产出成功模型。",
                "created_at": _now_iso(),
            }
        )
    return attempts[-20:]


def build_stop_conditions(attempts: Any) -> dict[str, Any]:
    normalized = normalize_attempts(attempts)
    model_attempts = [item for item in normalized if item.get("kind") == "model_run"]
    failed_attempts = [item for item in normalized[-3:] if item.get("status") in {"failed", "needs_improvement"}]
    return {
        "max_attempts": 5,
        "min_relative_improvement": 0.01,
        "max_consecutive_failed_or_unhelpful_attempts": 2,
        "current_model_attempts": len(model_attempts),
        "recent_failed_or_unhelpful_attempts": len(failed_attempts),
        "should_stop": len(model_attempts) >= 5 or len(failed_attempts) >= 2,
    }


def _run_attempt_note(comparison: dict[str, Any] | None) -> str:
    if comparison is None:
        return "模型结果已记录；由于指标口径不同，暂不和简单对照直接比较。"
    if comparison["better"]:
        return f"模型超过简单对照，相对改善 {comparison['relative_delta']:.1%}。"
    return f"模型没有超过简单对照，相对变化 {comparison['relative_delta']:.1%}，建议进入优化或人工复核。"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
