from __future__ import annotations

import json
from pathlib import Path

from backend.app.services.codex_overview_optimization import (
    derive_optimization_records,
    optimization_result,
)


def test_optimization_result_respects_metric_direction() -> None:
    assert optimization_result("mae", 3.0, 2.0) == "improved"
    assert optimization_result("mae", 2.0, 3.0) == "worse"
    assert optimization_result("accuracy", 0.7, 0.8) == "improved"
    assert optimization_result("accuracy", 0.8, 0.7) == "worse"
    assert optimization_result(None, 1.0, 2.0) == "not_comparable"


def test_derive_optimization_records_reads_worker_payload(tmp_path: Path) -> None:
    optimization_dir = tmp_path / "work" / "subagents" / "optimization_worker"
    optimization_dir.mkdir(parents=True)
    (optimization_dir / "optimization_results.json").write_text(
        json.dumps(
            {
                "parent_first_round_reference": {"validation_mae": 3.0},
                "best_candidate": {
                    "candidate": "candidate-a",
                    "route": "drop noisy columns",
                    "metrics": {"validation": {"mae": 2.0}},
                },
                "candidate_results": [{"candidate": "candidate-a"}, {"candidate": "candidate-b"}],
            }
        ),
        encoding="utf-8",
    )

    records = derive_optimization_records(
        {"diagnostics": {"bounded_optimization_summary": "Kept search within budget."}},
        str(tmp_path),
        "mae",
    )

    assert records[0]["name"] == "bounded_optimization"
    assert records[0]["result"] == "not_comparable"
    assert records[1]["name"] == "candidate-a"
    assert records[1]["before_metric"] == 3.0
    assert records[1]["after_metric"] == 2.0
    assert records[1]["result"] == "improved"
