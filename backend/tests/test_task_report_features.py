from __future__ import annotations

from backend.app.services.task_report_features import parse_feature_importance_payload


def test_parse_feature_importance_payload_accepts_feature_list_aliases() -> None:
    entries = parse_feature_importance_payload(
        {
            "features": [
                {"feature_name": " age ", "score": "0.8"},
                {"column": "income", "value": -0.25},
                {"name": "", "importance": 1.0},
                "invalid",
            ]
        },
        source="feature_importance.json",
    )

    assert [(entry.feature, entry.importance, entry.source) for entry in entries] == [
        ("age", 0.8, "feature_importance.json"),
        ("income", -0.25, "feature_importance.json"),
    ]


def test_parse_feature_importance_payload_accepts_mapping_payload() -> None:
    entries = parse_feature_importance_payload(
        {"age": "1.5", "income": "-0.3", "bad": "not-numeric"},
        source="feature_importance.json",
    )

    assert [(entry.feature, entry.importance) for entry in entries] == [("age", 1.5), ("income", -0.3)]
