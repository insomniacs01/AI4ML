from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from autogluon.tabular import TabularPredictor
from sklearn.datasets import load_iris
from sklearn.metrics import accuracy_score
from sklearn.model_selection import train_test_split


ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DIR = ROOT / "data" / "samples"
REPORT_DIR = ROOT / "storage" / "autogluon_iris_demo"


def main() -> None:
    iris = load_iris(as_frame=True)
    frame = iris.frame.rename(columns={"target": "label"})

    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    sample_csv = SAMPLE_DIR / "iris.csv"
    frame.to_csv(sample_csv, index=False)

    train_frame, test_frame = train_test_split(
        frame,
        test_size=0.2,
        random_state=42,
        stratify=frame["label"],
    )

    run_dir = REPORT_DIR / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir.mkdir(parents=True, exist_ok=True)

    predictor = TabularPredictor(
        label="label",
        path=str(run_dir),
        problem_type="multiclass",
        eval_metric="accuracy",
    )
    predictor.fit(train_data=train_frame, time_limit=20, presets="medium_quality_faster_train")

    predictions = predictor.predict(test_frame.drop(columns=["label"]))
    accuracy = float(accuracy_score(test_frame["label"], predictions))
    leaderboard = predictor.leaderboard(test_frame, silent=True)[["model", "score_test"]].head(5)

    report = {
        "sample_csv": str(sample_csv),
        "output_dir": str(run_dir),
        "best_model": predictor.model_best,
        "metric_name": "accuracy",
        "metric_value": accuracy,
        "leaderboard": leaderboard.to_dict(orient="records"),
    }
    report_path = REPORT_DIR / "report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("sample_csv =", report["sample_csv"])
    print("output_dir =", report["output_dir"])
    print("best_model =", report["best_model"])
    print("accuracy =", f"{accuracy:.4f}")
    print(leaderboard.to_string(index=False))


if __name__ == "__main__":
    main()
