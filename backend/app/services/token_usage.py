from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.app.models.task import (
    TaskRecord,
    TaskStatus,
    TaskTokenUsageSummaryItem,
    TeamTokenUsageResponse,
    TokenUsageReport,
)

TOTAL_LINE_RE = re.compile(
    r"Total tokens\s*[^\n]*?input:\s*(\d+)\s*,\s*output:\s*(\d+)\s*,\s*sum:\s*(\d+)",
    re.IGNORECASE,
)
INPUT_RE = re.compile(r"['\"]total_input_tokens['\"]\s*:\s*(\d+)")
OUTPUT_RE = re.compile(r"['\"]total_output_tokens['\"]\s*:\s*(\d+)")
TOTAL_RE = re.compile(r"['\"]total_tokens['\"]\s*:\s*(\d+)")


@dataclass(frozen=True)
class TokenUsageStats:
    input_tokens: int
    output_tokens: int
    total_tokens: int
    source: str


class TokenizerUnavailableError(RuntimeError):
    """Raised when provider usage is missing and no explicit tokenizer can count it."""


def _coerce_non_negative_int(value: Any) -> int:
    try:
        coerced = int(value)
    except (TypeError, ValueError):
        return 0
    return max(coerced, 0)


def _to_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def read_token_usage(output_dir: Path) -> TokenUsageStats:
    json_stats = _read_from_token_usage_json(output_dir)
    if json_stats is not None:
        return json_stats

    log_stats = _read_from_logs(output_dir)
    if log_stats is not None:
        return log_stats

    return TokenUsageStats(input_tokens=0, output_tokens=0, total_tokens=0, source="none")


def _read_from_token_usage_json(output_dir: Path) -> TokenUsageStats | None:
    token_file = output_dir / "token_usage.json"
    if not token_file.exists():
        return None

    try:
        payload = json.loads(token_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    total = payload.get("total") if isinstance(payload, dict) else None
    if not isinstance(total, dict):
        return None

    input_tokens = _to_int(total.get("total_input_tokens"))
    output_tokens = _to_int(total.get("total_output_tokens"))
    total_tokens = _to_int(total.get("total_tokens"))
    if input_tokens is None or output_tokens is None or total_tokens is None:
        return None

    return TokenUsageStats(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        source="token_usage.json",
    )


def _read_from_logs(output_dir: Path) -> TokenUsageStats | None:
    candidates = [
        output_dir / "info_logs.txt",
        output_dir / "detail_logs.txt",
        output_dir / "logs.txt",
        output_dir / "mlzero_stdout.log",
    ]
    for path in candidates:
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        line_match = TOTAL_LINE_RE.search(text)
        if line_match:
            return TokenUsageStats(
                input_tokens=int(line_match.group(1)),
                output_tokens=int(line_match.group(2)),
                total_tokens=int(line_match.group(3)),
                source=path.name,
            )

        input_match = INPUT_RE.search(text)
        output_match = OUTPUT_RE.search(text)
        total_match = TOTAL_RE.search(text)
        if input_match and output_match and total_match:
            return TokenUsageStats(
                input_tokens=int(input_match.group(1)),
                output_tokens=int(output_match.group(1)),
                total_tokens=int(total_match.group(1)),
                source=path.name,
            )
    return None


def make_token_usage_report(
    *,
    input_tokens: Any,
    output_tokens: Any,
    total_tokens: Any | None = None,
    sessions: list[dict[str, Any]] | None = None,
    conversations: list[dict[str, Any]] | None = None,
) -> TokenUsageReport:
    normalized_input = _coerce_non_negative_int(input_tokens)
    normalized_output = _coerce_non_negative_int(output_tokens)
    normalized_total = _coerce_non_negative_int(total_tokens)
    if normalized_total == 0:
        normalized_total = normalized_input + normalized_output

    normalized_sessions = [dict(item) for item in (sessions or [])]
    normalized_conversations = [dict(item) for item in (conversations or [])]
    return TokenUsageReport(
        input_tokens=normalized_input,
        output_tokens=normalized_output,
        total_tokens=normalized_total,
        sessions=normalized_sessions,
        conversations=normalized_conversations,
    )


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
            f"registered for model {tokenizer_name!r}. Configure AI4ML_MLZERO_TOKENIZER_MODEL_ALIAS "
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


def read_mlzero_token_usage(output_dir: str | Path) -> TokenUsageReport | None:
    output_path = Path(output_dir)
    token_usage_path = output_path / "token_usage.json"
    if not token_usage_path.exists():
        return None

    try:
        payload = json.loads(token_usage_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    total = payload.get("total")
    if not isinstance(total, dict):
        return None

    sessions_payload = payload.get("sessions", {})
    normalized_sessions: list[dict[str, Any]] = []
    if isinstance(sessions_payload, dict):
        for session_name, session_usage in sessions_payload.items():
            if not isinstance(session_usage, dict):
                continue
            normalized_sessions.append(
                {
                    "session_name": str(session_name),
                    "input_tokens": _coerce_non_negative_int(session_usage.get("input_tokens")),
                    "output_tokens": _coerce_non_negative_int(session_usage.get("output_tokens")),
                    "total_tokens": _coerce_non_negative_int(session_usage.get("total_tokens")),
                }
            )
    normalized_sessions.sort(key=lambda item: item["total_tokens"], reverse=True)

    conversations_payload = payload.get("conversations", {})
    normalized_conversations: list[dict[str, Any]] = []
    if isinstance(conversations_payload, dict):
        for conversation_id, conversation_usage in conversations_payload.items():
            if not isinstance(conversation_usage, dict):
                continue
            normalized_conversations.append(
                {
                    "conversation_id": str(conversation_id),
                    "input_tokens": _coerce_non_negative_int(conversation_usage.get("input_tokens")),
                    "output_tokens": _coerce_non_negative_int(conversation_usage.get("output_tokens")),
                    "total_tokens": _coerce_non_negative_int(conversation_usage.get("total_tokens")),
                }
            )
    normalized_conversations.sort(key=lambda item: item["total_tokens"], reverse=True)

    return make_token_usage_report(
        input_tokens=total.get("total_input_tokens", total.get("input_tokens")),
        output_tokens=total.get("total_output_tokens", total.get("output_tokens")),
        total_tokens=total.get("total_tokens"),
        sessions=normalized_sessions,
        conversations=normalized_conversations,
    )


def ensure_task_runtime_token_usage(task: TaskRecord) -> TaskRecord:
    if task.last_run is not None and task.last_run.token_usage is None:
        token_usage = read_mlzero_token_usage(task.last_run.output_dir)
        if token_usage is not None:
            task.last_run.token_usage = token_usage

    if task.last_run_attempt is not None and task.last_run_attempt.token_usage is None:
        token_usage = read_mlzero_token_usage(task.last_run_attempt.output_dir)
        if token_usage is not None:
            task.last_run_attempt.token_usage = token_usage

    return task


def get_task_analysis_token_usage(task: TaskRecord) -> TokenUsageReport | None:
    if task.analysis_token_usage is not None:
        return task.analysis_token_usage

    if not isinstance(task.structured_requirements, dict):
        return None

    payload = task.structured_requirements.get("token_usage")
    if not isinstance(payload, dict):
        return None

    return make_token_usage_report(
        input_tokens=payload.get("input_tokens"),
        output_tokens=payload.get("output_tokens"),
        total_tokens=payload.get("total_tokens"),
        sessions=payload.get("sessions") if isinstance(payload.get("sessions"), list) else None,
        conversations=payload.get("conversations") if isinstance(payload.get("conversations"), list) else None,
    )


def sum_token_usage_reports(reports: list[TokenUsageReport]) -> TokenUsageReport:
    total_input_tokens = sum(report.input_tokens for report in reports)
    total_output_tokens = sum(report.output_tokens for report in reports)
    total_tokens = sum(report.total_tokens for report in reports)

    session_totals: dict[str, dict[str, Any]] = {}
    for report in reports:
        for session in report.sessions:
            session_name = str(session.get("session_name", "unknown"))
            bucket = session_totals.setdefault(
                session_name,
                {"session_name": session_name, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            )
            bucket["input_tokens"] += _coerce_non_negative_int(session.get("input_tokens"))
            bucket["output_tokens"] += _coerce_non_negative_int(session.get("output_tokens"))
            bucket["total_tokens"] += _coerce_non_negative_int(session.get("total_tokens"))

    normalized_sessions = sorted(session_totals.values(), key=lambda item: item["total_tokens"], reverse=True)
    return make_token_usage_report(
        input_tokens=total_input_tokens,
        output_tokens=total_output_tokens,
        total_tokens=total_tokens,
        sessions=normalized_sessions,
    )


def build_task_token_usage_item(task: TaskRecord) -> TaskTokenUsageSummaryItem:
    task = ensure_task_runtime_token_usage(task)
    analysis_usage = get_task_analysis_token_usage(task)
    run_usage = None
    if task.last_run_attempt and task.last_run_attempt.token_usage is not None:
        run_usage = task.last_run_attempt.token_usage
    elif task.last_run and task.last_run.token_usage is not None:
        run_usage = task.last_run.token_usage
    combined_usage = sum_token_usage_reports(
        [report for report in (analysis_usage, run_usage) if report is not None]
    )

    return TaskTokenUsageSummaryItem(
        task_id=task.id,
        task_name=task.name,
        status=task.status if isinstance(task.status, TaskStatus) else TaskStatus(str(task.status)),
        dataset_filename=task.dataset_filename,
        metric_name=task.last_run.metric_name if task.last_run else None,
        metric_value=task.last_run.metric_value if task.last_run else None,
        analysis_token_usage=analysis_usage,
        run_token_usage=run_usage,
        combined_token_usage=combined_usage,
        updated_at=task.updated_at,
    )


def build_team_token_usage_response(team_id: str, tasks: list[TaskRecord]) -> TeamTokenUsageResponse:
    items = [build_task_token_usage_item(task) for task in tasks]
    analysis_reports = [item.analysis_token_usage for item in items if item.analysis_token_usage is not None]
    run_reports = [item.run_token_usage for item in items if item.run_token_usage is not None]
    combined_reports = [item.combined_token_usage for item in items if item.combined_token_usage.total_tokens > 0]

    items.sort(key=lambda item: item.updated_at, reverse=True)
    return TeamTokenUsageResponse(
        team_id=team_id,
        task_count=len(tasks),
        tasks_with_analysis_usage=len(analysis_reports),
        tasks_with_run_usage=len(run_reports),
        analysis_totals=sum_token_usage_reports(analysis_reports),
        run_totals=sum_token_usage_reports(run_reports),
        combined_totals=sum_token_usage_reports(combined_reports),
        items=items,
    )
