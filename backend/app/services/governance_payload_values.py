from __future__ import annotations

from typing import Any


def optional_payload_str(value: Any) -> str | None:
    return str(value) if value else None


def coerce_non_negative_int(value: Any) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return 0
    return max(result, 0)
