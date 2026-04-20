from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


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


def _to_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None
