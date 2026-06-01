from __future__ import annotations

import math
from typing import Any


def normalize_report_metric(metric_name: str | None) -> str:
    return str(metric_name or "").strip().lower().replace("-", "_").replace(" ", "_")


def coerce_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def format_metric_value(value: Any) -> str:
    numeric = coerce_float(value)
    if numeric is None:
        return "暂无"
    return f"{numeric:.6g}"


def format_integer(value: Any) -> str:
    if isinstance(value, bool) or value is None:
        return "暂无"
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


def format_percent(value: Any) -> str:
    numeric = coerce_float(value)
    if numeric is None:
        return "暂无"
    return f"{numeric:.1%}"


def escape_table_cell(value: Any) -> str:
    text = "暂无" if value is None or value == "" else str(value)
    return text.replace("\n", " ").replace("\r", " ").replace("|", "\\|")


def status_label(status: Any) -> str:
    mapping = {
        "completed": "已完成",
        "passed": "通过",
        "accepted": "已采纳",
        "blocked": "阻塞",
        "failed": "失败",
        "warning": "需确认",
        "pending": "等待中",
        "running": "运行中",
        "proposed": "建议调优",
        "needs_improvement": "需要改进",
    }
    return mapping.get(str(status or ""), str(status or "未知"))


def artifact_status(path: Any) -> str:
    return "已找到" if path else "未找到"


def path_text(path: Any) -> str:
    return str(path) if path else "未记录"


def markdown_table(headers: list[str], separators: list[str], rows: list[list[str]]) -> list[str]:
    return [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(separators) + " |",
        *["| " + " | ".join(row) + " |" for row in rows],
    ]
