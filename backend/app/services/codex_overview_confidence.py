from __future__ import annotations

from typing import Any

from backend.app.services.codex_common import lower_is_better


DIRECT_SCORE_METRICS = {"accuracy", "macro_f1", "r2", "within_relative_error_25pct"}


def derive_confidence(
    metric_name: str | None,
    metric_value: float | None,
    baseline_value: float | None,
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    warnings: list[str] = []
    score_parts: list[float] = []
    metric_score = confidence_metric_score(metric_name, metric_value, baseline_value)
    if metric_score is not None:
        score_parts.append(metric_score)
    elif not metric_name or metric_value is None:
        warnings.append("未找到真实主评估指标，无法评估可信度。")

    score_parts.extend(diagnostic_score_parts(diagnostics, warnings))
    if not score_parts:
        return unknown_confidence(warnings)

    score = sum(score_parts) / len(score_parts)
    level = confidence_level(score)
    return {
        "score": round(score, 3),
        "level": level,
        "display": confidence_display(level),
        "rationale": "可信度根据主指标、baseline 对比和诊断风险综合估计。",
        "warnings": warnings,
    }


def confidence_metric_score(metric_name: str | None, metric_value: float | None, baseline_value: float | None) -> float | None:
    if not metric_name or metric_value is None:
        return None
    if baseline_value is not None and baseline_value != 0:
        if lower_is_better(metric_name):
            improvement = (baseline_value - metric_value) / abs(baseline_value)
        else:
            improvement = (metric_value - baseline_value) / abs(baseline_value)
        return bounded_score(0.5 + improvement)
    if metric_name in DIRECT_SCORE_METRICS:
        return bounded_score(metric_value)
    return None


def diagnostic_score_parts(diagnostics: dict[str, Any], warnings: list[str]) -> list[float]:
    score_parts: list[float] = []
    leakage = diagnostics.get("leakage") if isinstance(diagnostics.get("leakage"), dict) else {}
    if leakage:
        warnings.append(str(leakage.get("interpretation") or "存在需要复核的切分或泄漏风险。"))
        score_parts.append(0.35)
    if isinstance(diagnostics.get("target_distribution_note"), str):
        warnings.append(diagnostics["target_distribution_note"])
        score_parts.append(0.55)
    return score_parts


def unknown_confidence(warnings: list[str]) -> dict[str, Any]:
    return {
        "score": None,
        "level": "unknown",
        "display": "未知",
        "rationale": "当前任务没有足够结构化证据计算可信度。",
        "warnings": warnings,
    }


def confidence_level(score: float) -> str:
    return "high" if score >= 0.75 else "medium" if score >= 0.45 else "low"


def confidence_display(level: str) -> str:
    return {"high": "高", "medium": "中", "low": "低"}[level]


def bounded_score(value: float) -> float:
    return max(0.0, min(1.0, value))
