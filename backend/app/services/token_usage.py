from __future__ import annotations

from typing import Any

from backend.app.models.task import TokenUsageReport
from backend.app.services.token_usage_summary import (
    build_task_token_usage_item,
    build_team_token_usage_response,
    coerce_non_negative_int as _coerce_non_negative_int,
    get_task_analysis_token_usage,
    make_token_usage_report,
    sum_token_usage_reports,
)


class TokenizerUnavailableError(RuntimeError):
    """Raised when provider usage is missing and no explicit tokenizer can count it."""


def extract_provider_token_usage(payload: dict[str, Any]) -> TokenUsageReport | None:
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return None

    input_tokens = usage.get("input_tokens", usage.get("prompt_tokens"))
    output_tokens = usage.get("output_tokens", usage.get("completion_tokens"))
    total_tokens = usage.get("total_tokens")
    if input_tokens is None and output_tokens is None and total_tokens is None:
        return None

    return make_token_usage_report(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
    )


def make_provider_tokenizer_usage_report(
    *,
    prompt: str,
    system_message: str,
    response_text: str,
    model_name: str,
    tokenizer_model_name: str | None = None,
    wire_api: str = "chat_completions",
) -> TokenUsageReport:
    tokenizer_name = (tokenizer_model_name or model_name or "").strip()
    if not tokenizer_name:
        raise TokenizerUnavailableError(
            "Provider response did not include token usage and no tokenizer model name is configured."
        )

    encoding = _resolve_tiktoken_encoding(tokenizer_name)
    if wire_api == "responses":
        input_text = f"System instruction:\n{system_message}\n\nUser prompt:\n{prompt}"
        input_tokens = len(encoding.encode(input_text))
    else:
        input_tokens = _count_chat_messages_tokens(
            [
                {"role": "system", "content": system_message},
                {"role": "user", "content": prompt},
            ],
            encoding=encoding,
        )
    output_tokens = len(encoding.encode(response_text))
    return make_token_usage_report(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        sessions=[
            {
                "session_name": "provider_tokenizer_recompute",
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
                "model_name": model_name,
                "tokenizer_model_name": tokenizer_name,
                "wire_api": wire_api,
                "calculation_method": "tokenizer_estimate",
            }
        ],
    )


def _resolve_tiktoken_encoding(tokenizer_name: str) -> Any:
    try:
        import tiktoken  # type: ignore[import-not-found]
    except ImportError as exc:
        raise TokenizerUnavailableError(
            "Provider response did not include token usage and tiktoken is not installed. "
            "Install backend requirements or disable providers that omit usage."
        ) from exc

    if tokenizer_name.startswith("encoding:"):
        encoding_name = tokenizer_name.split(":", 1)[1].strip()
        if not encoding_name:
            raise TokenizerUnavailableError("Tokenizer encoding name is empty.")
        try:
            return tiktoken.get_encoding(encoding_name)
        except Exception as exc:  # noqa: BLE001
            raise TokenizerUnavailableError(f"Unknown tiktoken encoding: {encoding_name}") from exc

    try:
        return tiktoken.encoding_for_model(tokenizer_name)
    except KeyError as exc:
        raise TokenizerUnavailableError(
            "Provider response did not include token usage and tiktoken has no encoding "
            f"registered for model {tokenizer_name!r}. Configure AI4ML_AI_PROVIDER_TOKENIZER_MODEL_ALIAS "
            "to a supported model or to encoding:<encoding_name>."
        ) from exc


def _count_chat_messages_tokens(messages: list[dict[str, str]], *, encoding: Any) -> int:
    tokens_per_message = 3
    tokens_per_name = 1
    total_tokens = 0
    for message in messages:
        total_tokens += tokens_per_message
        for key, value in message.items():
            total_tokens += len(encoding.encode(str(value)))
            if key == "name":
                total_tokens += tokens_per_name
    total_tokens += 3
    return total_tokens
