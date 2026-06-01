from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.services.task_code_artifact_descriptors import (
    describe_artifact,
    detect_artifact_language,
    is_editable_artifact,
)


@pytest.mark.parametrize(
    ("relative_path", "filename", "expected"),
    [
        ("output/code/final_modeling.py", "final_modeling.py", ("code", "generation", "final_modeling", True, 0)),
        ("output/predict.py", "predict.py", ("code", "generation", "predict_entrypoint", True, 1)),
        ("generated_code.py", "generated_code.py", ("code", "generation", "generated_code", True, 0)),
        ("summary.txt", "summary.txt", ("result", "result", "run_summary", True, 3)),
        ("node_001/output/summary.txt", "summary.txt", ("result", "result", "node_output_summary", False, 60)),
        ("leaderboard.csv", "leaderboard.csv", ("result", "result", "leaderboard", True, 4)),
        ("validation_predictions.csv", "validation_predictions.csv", ("result", "result", "predictions", True, 5)),
        (
            "node_001/output/validation_predictions.csv",
            "validation_predictions.csv",
            ("result", "result", "node_predictions", False, 61),
        ),
        ("input/dataset.csv", "dataset.csv", ("other", "context", "input_dataset", False, 201)),
        ("input/task_request.json", "task_request.json", ("other", "context", "input_context", False, 202)),
        ("input/logs.txt", "logs.txt", ("other", "context", "input_context", False, 202)),
        ("logs.txt", "logs.txt", ("log", "log", "runtime_log", False, 300)),
        ("stderr_0", "stderr_0", ("log", "log", "process_stream", False, 301)),
        ("validation_score_001.txt", "validation_score_001.txt", ("result", "result", "node_score", False, 62)),
        (
            "node_001/states/python_coder_prompt.txt",
            "python_coder_prompt.txt",
            ("state", "generation", "python_coder_prompt", True, 20),
        ),
        ("node_001/states/error_summary.txt", "error_summary.txt", ("state", "generation", "error_analysis", False, 28)),
        ("description_files.txt", "description_files.txt", ("state", "generation", "task_setup", False, 30)),
        ("python_reader_response.txt", "python_reader_response.txt", ("state", "generation", "reader_stage", False, 31)),
        ("retriever_context.txt", "retriever_context.txt", ("state", "generation", "retrieval_stage", False, 32)),
        ("node_001/states/unknown.json", "unknown.json", ("state", "generation", "generic_state", False, 90)),
        ("scratch/helper.sql", "helper.sql", ("code", "other", "other_code", False, 400)),
        ("scratch/notes.md", "notes.md", ("other", "other", "other_text", False, 401)),
    ],
)
def test_describe_artifact_uses_expected_descriptor(relative_path: str, filename: str, expected: tuple[object, ...]) -> None:
    descriptor = describe_artifact(relative_path, filename)

    assert (
        descriptor.category,
        descriptor.group,
        descriptor.artifact_kind,
        descriptor.is_core,
        descriptor.sort_priority,
    ) == expected


def test_detect_artifact_language_uses_suffix_and_known_stream_names() -> None:
    assert detect_artifact_language(Path("model.py")) == "python"
    assert detect_artifact_language(Path("stdout")) == "log"
    assert detect_artifact_language(Path("stderr")) == "log"
    assert detect_artifact_language(Path("image.png")) is None


def test_editable_artifact_requires_code_category_and_editable_language() -> None:
    final_modeling = describe_artifact("output/code/final_modeling.py", "final_modeling.py")
    leaderboard = describe_artifact("leaderboard.csv", "leaderboard.csv")
    sql_helper = describe_artifact("scratch/helper.sql", "helper.sql")

    assert is_editable_artifact(final_modeling, "python") is True
    assert is_editable_artifact(sql_helper, "sql") is True
    assert is_editable_artifact(leaderboard, "csv") is False
