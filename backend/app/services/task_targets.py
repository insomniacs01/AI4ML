from __future__ import annotations

from typing import Any


TARGET_SEPARATORS = (",", "，", ";", "；", "\n", "\r", "\t", "|")


def split_target_columns(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        targets: list[str] = []
        for item in value:
            targets.extend(split_target_columns(item))
        return _dedupe(targets)

    text = str(value).strip()
    if not text:
        return []
    for separator in TARGET_SEPARATORS:
        text = text.replace(separator, ",")
    return _dedupe(_clean_target_name(part) for part in text.split(","))


def target_columns_from_requirements(requirements: dict[str, Any] | None) -> list[str]:
    if not isinstance(requirements, dict):
        return []
    for key in ("target_columns", "target_columns_hint"):
        targets = split_target_columns(requirements.get(key))
        if targets:
            return targets
    target_definition = requirements.get("target_definition")
    if isinstance(target_definition, dict):
        targets = split_target_columns(target_definition.get("target_columns") or target_definition.get("targets"))
        if targets:
            return targets
    return split_target_columns(requirements.get("target_hint"))


def target_columns_from_task(task: Any) -> list[str]:
    requirements = task.structured_requirements if isinstance(getattr(task, "structured_requirements", None), dict) else {}
    return target_columns_from_requirements(requirements) or split_target_columns(getattr(task, "label_column", None))


def is_multi_target_value(value: Any) -> bool:
    return len(split_target_columns(value)) > 1


def target_columns_display(targets: list[str]) -> str:
    return "、".join(targets)


def _clean_target_name(value: Any) -> str:
    return str(value or "").strip().strip("`\"'")


def _dedupe(values: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = _clean_target_name(value)
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
