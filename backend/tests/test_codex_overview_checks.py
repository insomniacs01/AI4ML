from __future__ import annotations

from backend.app.services.codex_overview_checks import derive_result_checks


def test_result_checks_report_warnings_when_core_evidence_is_missing() -> None:
    checks = {
        item["name"]: item
        for item in derive_result_checks(
            {},
            metric_name="mae",
            metric_value=2.0,
            baseline_name=None,
            baseline_value=None,
            diagnostics={},
            workspace_path=None,
        )
    }

    assert checks["baseline_comparison"]["status"] == "warning"
    assert checks["validation_split"]["status"] == "warning"
    assert checks["leakage_check"]["status"] == "not_applicable"
    assert checks["artifact_consistency"]["status"] == "warning"
    assert checks["prediction_entrypoint"]["status"] == "warning"
    assert "data_quality" not in checks


def test_result_checks_include_data_quality_when_dataset_payload_exists() -> None:
    checks = derive_result_checks(
        {"dataset": {"raw_rows": 120}},
        metric_name=None,
        metric_value=None,
        baseline_name=None,
        baseline_value=None,
        diagnostics={},
        workspace_path=None,
    )

    assert checks[-1] == {
        "name": "data_quality",
        "status": "passed",
        "detail": "已记录数据规模、缺失处理或分布信息。",
        "evidence": "rows=120",
    }
