from __future__ import annotations

from typing import Any


def has_completed_codex_artifacts(artifacts: dict[str, Any]) -> bool:
    report = artifacts.get("report") if isinstance(artifacts.get("report"), dict) else {}
    predict = artifacts.get("predict") if isinstance(artifacts.get("predict"), dict) else {}
    return bool(report.get("exists") and predict.get("exists") and isinstance(artifacts.get("metrics"), dict))
