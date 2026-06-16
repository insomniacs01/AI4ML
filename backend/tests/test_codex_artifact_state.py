from __future__ import annotations

from backend.app.services.codex_artifact_state import (
    has_completed_codex_artifacts,
    has_failed_codex_acceptance,
)


def _complete_artifacts(metrics: dict) -> dict:
    return {
        "report": {"exists": True},
        "predict": {"exists": True},
        "metrics": metrics,
    }


def test_completed_artifacts_require_no_failed_acceptance() -> None:
    assert has_completed_codex_artifacts(_complete_artifacts({"acceptance": {"passed": True}})) is True
    assert has_completed_codex_artifacts(_complete_artifacts({"acceptance": {"passed": False}})) is False


def test_failed_result_check_blocks_completion_when_acceptance_missing() -> None:
    artifacts = _complete_artifacts(
        {
            "result_checks": [
                {"name": "success_threshold", "status": "failed"},
            ]
        }
    )

    assert has_failed_codex_acceptance(artifacts) is True
    assert has_completed_codex_artifacts(artifacts) is False


def test_failed_result_check_blocks_completion_even_when_acceptance_passed() -> None:
    artifacts = _complete_artifacts(
        {
            "acceptance": {"passed": True},
            "result_checks": [
                {"name": "artifact_consistency", "status": "failed"},
            ],
        }
    )

    assert has_failed_codex_acceptance(artifacts) is True
    assert has_completed_codex_artifacts(artifacts) is False


def test_legacy_metrics_without_acceptance_keep_completion_compatibility() -> None:
    assert has_failed_codex_acceptance(_complete_artifacts({"selected_model": {"name": "ridge"}})) is False
    assert has_completed_codex_artifacts(_complete_artifacts({"selected_model": {"name": "ridge"}})) is True
