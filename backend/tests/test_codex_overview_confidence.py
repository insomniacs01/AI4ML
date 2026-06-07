import math

from backend.app.services.codex_overview_confidence import confidence_metric_score, derive_confidence


def test_confidence_metric_score_uses_baseline_improvement_for_lower_is_better_metric() -> None:
    assert math.isclose(confidence_metric_score("mae", 2.0, 3.0) or 0, 0.8333333333333333)


def test_confidence_metric_score_uses_baseline_improvement_for_higher_is_better_metric() -> None:
    assert math.isclose(confidence_metric_score("accuracy", 0.9, 0.8) or 0, 0.625)


def test_confidence_metric_score_uses_direct_metric_when_baseline_is_missing() -> None:
    assert confidence_metric_score("accuracy", 1.2, None) == 1.0
    assert confidence_metric_score("accuracy", -0.1, None) == 0.0


def test_derive_confidence_averages_metric_and_diagnostic_scores() -> None:
    confidence = derive_confidence(
        "mae",
        2.0,
        3.0,
        {"leakage": {"interpretation": "review leakage"}},
    )

    assert confidence["score"] == 0.592
    assert confidence["level"] == "medium"
    assert confidence["display"] == "中"
    assert confidence["warnings"] == ["review leakage"]


def test_derive_confidence_returns_unknown_when_no_score_evidence_exists() -> None:
    confidence = derive_confidence(None, None, None, {})

    assert confidence["score"] is None
    assert confidence["level"] == "unknown"
    assert confidence["display"] == "未知"
    assert confidence["warnings"] == ["未找到真实主评估指标，无法评估可信度。"]


def test_derive_confidence_preserves_unsupported_metric_without_missing_metric_warning() -> None:
    confidence = derive_confidence("custom_metric", 0.42, None, {})

    assert confidence["score"] is None
    assert confidence["level"] == "unknown"
    assert confidence["warnings"] == []
