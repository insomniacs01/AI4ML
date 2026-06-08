from __future__ import annotations

import math
from typing import Any


def coerce_percent(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    if not numeric.is_integer():
        return round(numeric)
    return int(numeric)


def string_or_none(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
