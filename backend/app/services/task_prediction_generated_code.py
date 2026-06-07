from __future__ import annotations

import ast
import importlib.util
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GeneratedCodePrediction:
    label: Any
    probabilities: Any | None = None


@dataclass(frozen=True)
class GeneratedCodePredictionFailure:
    kind: str
    detail: str


def generated_code_has_predict_contract(generated_code: Path) -> bool:
    try:
        tree = ast.parse(generated_code.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return False
    has_predict = False
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            has_predict = has_predict or node.name == "predict"
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.ClassDef)):
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            continue
        if _is_guarded_main_block(node):
            continue
        return False
    return has_predict


def call_generated_code_prediction(
    generated_code: Path,
    *,
    task_id: str,
    features: dict[str, Any],
    fallback_features: dict[str, Any],
) -> tuple[GeneratedCodePrediction | None, GeneratedCodePredictionFailure | None]:
    module, failure = _load_generated_code_module(generated_code, task_id=task_id)
    if failure is not None:
        return None, failure
    if module is None:
        return None, None

    predict = getattr(module, "predict", None)
    if not callable(predict):
        return None, None

    prediction, prediction_failure = _call_generated_predict(
        predict,
        features=features,
        fallback_features=fallback_features,
    )
    if prediction_failure is not None:
        return None, prediction_failure

    probabilities = _call_generated_predict_proba(task_id, module, features)
    return (
        GeneratedCodePrediction(
            label=json_safe_prediction_value(prediction),
            probabilities=json_safe_prediction_value(probabilities) if probabilities is not None else None,
        ),
        None,
    )


def json_safe_prediction_value(value: Any) -> Any:
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception as exc:
            logger.debug("Could not coerce scalar JSON value %r: %s", value, exc)
    if isinstance(value, dict):
        return {str(key): json_safe_prediction_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe_prediction_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _load_generated_code_module(
    generated_code: Path,
    *,
    task_id: str,
) -> tuple[Any | None, GeneratedCodePredictionFailure | None]:
    module_name = f"_ai4ml_generated_predict_{task_id}_{abs(hash(str(generated_code)))}"
    spec = importlib.util.spec_from_file_location(module_name, generated_code)
    if spec is None or spec.loader is None:
        return None, None

    previous_path = list(sys.path)
    sys.path.insert(0, str(generated_code.parent))
    try:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001
        return None, GeneratedCodePredictionFailure(kind="import", detail=str(exc))
    finally:
        sys.path[:] = previous_path
    return module, None


def _call_generated_predict(
    predict: Any,
    *,
    features: dict[str, Any],
    fallback_features: dict[str, Any],
) -> tuple[Any, GeneratedCodePredictionFailure | None]:
    try:
        return predict(features), None
    except TypeError:
        try:
            return predict(fallback_features), None
        except Exception as exc:  # noqa: BLE001
            return None, GeneratedCodePredictionFailure(kind="predict", detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        return None, GeneratedCodePredictionFailure(kind="predict", detail=str(exc))


def _call_generated_predict_proba(task_id: str, module: Any, features: dict[str, Any]) -> Any | None:
    predict_proba = getattr(module, "predict_proba", None)
    if not callable(predict_proba):
        return None
    try:
        return predict_proba(features)
    except Exception as exc:
        logger.debug("Generated predict_proba failed for task %s: %s", task_id, exc)
        return None


def _is_guarded_main_block(node: ast.AST) -> bool:
    if not isinstance(node, ast.If):
        return False
    test = node.test
    if not isinstance(test, ast.Compare) or len(test.ops) != 1 or len(test.comparators) != 1:
        return False
    if not isinstance(test.ops[0], ast.Eq):
        return False
    left = test.left
    right = test.comparators[0]
    return (
        isinstance(left, ast.Name)
        and left.id == "__name__"
        and isinstance(right, ast.Constant)
        and right.value == "__main__"
    )
