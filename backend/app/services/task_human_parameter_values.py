from __future__ import annotations

from typing import Any


HUMAN_PARAMETERS_KEY = "human_parameters"
PARAMETER_HISTORY_KEY = "human_parameter_history"


def ensure_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def stage_parameters(requirements: dict[str, Any], stage: str) -> dict[str, Any]:
    human_parameters = ensure_dict(requirements.get(HUMAN_PARAMETERS_KEY))
    value = human_parameters.get(stage)
    return value if isinstance(value, dict) else {}


def string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw_items = value.replace(";", ",").replace("\n", ",").split(",")
    elif isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    else:
        raw_items = [value]
    items: list[str] = []
    for raw_item in raw_items:
        item = str(raw_item).strip()
        if item and item not in items:
            items.append(item)
    return items


def text_value(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def normalize_metric(value: Any) -> str:
    return text_value(value).lower().replace("-", "_").replace(" ", "_")


def optional_int(value: Any, *, minimum: int, maximum: int) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise RuntimeError("Numeric parameter cannot be boolean.")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"Expected an integer between {minimum} and {maximum}.") from exc
    if parsed < minimum or parsed > maximum:
        raise RuntimeError(f"Expected an integer between {minimum} and {maximum}.")
    return parsed


def join_list(values: list[str], *, limit: int = 12) -> str:
    if len(values) <= limit:
        return ", ".join(values)
    return ", ".join(values[:limit]) + f", and {len(values) - limit} more"
