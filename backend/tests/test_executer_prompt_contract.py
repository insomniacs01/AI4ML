from __future__ import annotations

import sys
from pathlib import Path
from unittest import TestCase


EXTERNAL_SRC = Path(__file__).resolve().parents[2] / "external" / "autogluon-assistant" / "src"
if str(EXTERNAL_SRC) not in sys.path:
    sys.path.insert(0, str(EXTERNAL_SRC))

from autogluon.assistant.prompts.executer_prompt import ExecuterPrompt  # noqa: E402


class _DummyManager:
    def __init__(self) -> None:
        self.saved: list[tuple[str, object]] = []

    def save_and_log_states(self, content, save_name, **kwargs) -> None:
        self.saved.append((save_name, content))


def _prompt() -> ExecuterPrompt:
    prompt = ExecuterPrompt.__new__(ExecuterPrompt)
    prompt.manager = _DummyManager()
    return prompt


class ExecuterPromptContractTests(TestCase):
    def test_success_without_score_is_rejected_for_model_validation(self) -> None:
        prompt = _prompt()

        with self.assertRaises(ValueError):
            prompt.parse("DECISION: SUCCESS\nERROR_SUMMARY: None\nVALIDATION_SCORE: None")

    def test_success_without_score_is_allowed_for_file_reader_execution(self) -> None:
        prompt = _prompt()

        decision, error_summary, validation_score = prompt.parse(
            "DECISION: SUCCESS\nERROR_SUMMARY: None\nVALIDATION_SCORE: None",
            require_validation_score=False,
        )

        self.assertEqual(decision, "SUCCESS")
        self.assertIsNone(error_summary)
        self.assertIsNone(validation_score)

    def test_success_with_numeric_score_remains_validated(self) -> None:
        prompt = _prompt()

        decision, error_summary, validation_score = prompt.parse(
            "DECISION: SUCCESS\nERROR_SUMMARY: None\nVALIDATION_SCORE: 0.91"
        )

        self.assertEqual(decision, "SUCCESS")
        self.assertIsNone(error_summary)
        self.assertEqual(validation_score, 0.91)
