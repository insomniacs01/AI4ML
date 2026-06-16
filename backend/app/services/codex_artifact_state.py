from __future__ import annotations

from typing import Any


def has_completed_codex_artifacts(artifacts: dict[str, Any]) -> bool:
    if has_failed_codex_acceptance(artifacts):
        return False
    report = artifacts.get("report") if isinstance(artifacts.get("report"), dict) else {}
    predict = artifacts.get("predict") if isinstance(artifacts.get("predict"), dict) else {}
    return bool(report.get("exists") and predict.get("exists") and isinstance(artifacts.get("metrics"), dict))


def has_stop_and_report_codex_artifacts(artifacts: dict[str, Any]) -> bool:
    progress = artifacts.get("progress") if isinstance(artifacts.get("progress"), dict) else {}
    report = artifacts.get("report") if isinstance(artifacts.get("report"), dict) else {}
    predict = artifacts.get("predict") if isinstance(artifacts.get("predict"), dict) else {}
    return bool(
        str(progress.get("status") or "").strip().lower() == "partial"
        and str(progress.get("current_step") or "").strip().lower() == "stop_and_report_completed"
        and report.get("exists")
        and predict.get("exists")
        and isinstance(artifacts.get("metrics"), dict)
    )


def has_failed_codex_acceptance(artifacts: dict[str, Any]) -> bool:
    metrics = artifacts.get("metrics") if isinstance(artifacts.get("metrics"), dict) else {}
    if not metrics:
        return False

    acceptance = metrics.get("acceptance")
    if isinstance(acceptance, dict) and "passed" in acceptance:
        if acceptance.get("passed") is False:
            return True

    result_checks = metrics.get("result_checks")
    if not isinstance(result_checks, list):
        return False
    return any(
        isinstance(check, dict) and str(check.get("status") or "").lower() == "failed"
        for check in result_checks
    )
