from __future__ import annotations

from typing import Any


def flatten_artifact_refs(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if isinstance(value, dict):
        flattened: list[str] = []
        for key, item in value.items():
            if isinstance(item, list):
                flattened.extend(str(child) for child in item if child)
            elif item:
                flattened.append(f"{key}: {item}")
        return flattened
    return [str(value)]
