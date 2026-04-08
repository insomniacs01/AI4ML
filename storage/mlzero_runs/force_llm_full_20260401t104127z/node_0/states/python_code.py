"""Train a tiny sklearn baseline on tiny.csv and print a validation score."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score
from sklearn.model_selection import train_test_split

INPUT_PATH = Path(r"/Users/macbookpro/AI4ML/storage/force_llm_small_input/tiny.csv")
OUTPUT_DIR = Path(r"/Users/macbookpro/AI4ML/storage/mlzero_runs/force_llm_full_20260401t104127z/node_0/output")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(INPUT_PATH)
    X = df.drop(columns=["label"])
    y = df["label"]
    X_train, X_valid, y_train, y_valid = train_test_split(
        X, y, test_size=0.25, random_state=42, stratify=y
    )
    model = LogisticRegression(max_iter=1000)
    model.fit(X_train, y_train)
    preds = model.predict(X_valid)
    score = accuracy_score(y_valid, preds)
    out = X_valid.copy()
    out["label"] = preds
    out.to_csv(OUTPUT_DIR / "results.csv", index=False)
    print(f"validation_score={score:.6f}")


if __name__ == "__main__":
    main()
