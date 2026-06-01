from __future__ import annotations

from backend.app.services.openai_compatible_provider import _extract_response_text


def test_extract_response_text_prefers_responses_output_text() -> None:
    payload = {
        "output_text": "  final answer  ",
        "output": [
            {"content": [{"text": "ignored"}]},
        ],
    }

    assert _extract_response_text(payload, wire_api="responses") == "final answer"


def test_extract_response_text_joins_responses_output_content() -> None:
    payload = {
        "output": [
            {"content": [{"text": " first "}, {"type": "image"}]},
            {"content": [{"text": "second"}]},
            {"content": "not-a-list"},
        ]
    }

    assert _extract_response_text(payload, wire_api="responses") == "first\n\nsecond"


def test_extract_response_text_reads_chat_message_string() -> None:
    payload = {"choices": [{"message": {"content": "  hello  "}}]}

    assert _extract_response_text(payload, wire_api="chat_completions") == "hello"


def test_extract_response_text_joins_chat_content_parts() -> None:
    payload = {
        "choices": [
            {
                "message": {
                    "content": [
                        " first ",
                        {"text": "second"},
                        {"type": "image_url", "image_url": {"url": "ignored"}},
                    ]
                }
            }
        ]
    }

    assert _extract_response_text(payload, wire_api="chat_completions") == "first\n\nsecond"
