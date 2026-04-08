"""Deterministic sklearn baseline generated for local MLZero validation."""
from __future__ import annotations

import time
from pathlib import Path

import joblib
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.metrics import accuracy_score, mean_squared_error
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

TRAIN_PATH = Path(r"/Users/macbookpro/AI4ML/storage/mlzero_runs/trace_20260401t101222z/20260401T101222Z/input/train.csv")
OUTPUT_DIR = Path(r"/Users/macbookpro/AI4ML/storage/mlzero_runs/trace_20260401t101222z/20260401T101222Z/node_0/output")
LABEL_COLUMN = "label"
PROBLEM_TYPE = "classification"

def build_preprocessor(frame: pd.DataFrame) -> ColumnTransformer:
    numeric_features = frame.select_dtypes(include=["number", "bool"]).columns.tolist()
    categorical_features = [col for col in frame.columns if col not in numeric_features]
    transformers = []
    if numeric_features:
        transformers.append((
            "numeric",
            Pipeline(
                steps=[
                    ("imputer", SimpleImputer(strategy="median")),
                    ("scaler", StandardScaler()),
                ]
            ),
            numeric_features,
        ))
    if categorical_features:
        transformers.append((
            "categorical",
            Pipeline(
                steps=[
                    ("imputer", SimpleImputer(strategy="most_frequent")),
                    ("encoder", OneHotEncoder(handle_unknown="ignore")),
                ]
            ),
            categorical_features,
        ))
    remainder = "drop" if transformers else "passthrough"
    return ColumnTransformer(transformers=transformers, remainder=remainder)

def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    data = pd.read_csv(TRAIN_PATH)
    if LABEL_COLUMN not in data.columns:
        raise ValueError(f"Missing label column: {LABEL_COLUMN}")
    data = data.dropna(subset=[LABEL_COLUMN]).copy()
    y = data.pop(LABEL_COLUMN)
    X = data
    stratify = None
    if PROBLEM_TYPE == "classification" and y.nunique() > 1 and y.value_counts().min() > 1:
        stratify = y
    X_train, X_valid, y_train, y_valid = train_test_split(
        X,
        y,
        test_size=0.2,
        random_state=42,
        stratify=stratify,
    )
    preprocessor = build_preprocessor(X_train)
    model = RandomForestClassifier(n_estimators=200, random_state=42) if PROBLEM_TYPE == "classification" else RandomForestRegressor(n_estimators=200, random_state=42)
    pipeline = Pipeline(
        steps=[
            ("preprocessor", preprocessor),
            ("model", model),
        ]
    )
    pipeline.fit(X_train, y_train)
    predictions = pipeline.predict(X_valid)
    if PROBLEM_TYPE == "classification":
        score = accuracy_score(y_valid, predictions)
    else:
        score = mean_squared_error(y_valid, predictions, squared=False)
    model_dir = OUTPUT_DIR / f"model_{int(time.time())}"
    model_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipeline, model_dir / "pipeline.joblib")
    results = X_valid.copy()
    results[LABEL_COLUMN] = predictions
    results.to_csv(OUTPUT_DIR / "results.csv", index=True)
    print(f"validation_score={score:.6f}")
    print(f"Validation score: {score:.6f}")

if __name__ == "__main__":
    main()
