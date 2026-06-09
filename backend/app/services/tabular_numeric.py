from __future__ import annotations

import math
from typing import Any


def parse_tabular_float(value: Any) -> float | None:
    text = str(value or "").strip().replace("\u00a0", "")
    if not text:
        return None
    candidates = [text]
    if "," in text and "." not in text:
        candidates.append(text.replace(",", "."))
    for candidate in candidates:
        try:
            numeric = float(candidate)
        except ValueError:
            continue
        if math.isfinite(numeric):
            return numeric
    return None
