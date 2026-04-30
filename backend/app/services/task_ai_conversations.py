from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from backend.app.models.task import (
    TaskAIConversationEntry,
    TaskAIConversationResponse,
    TaskAIInternalStateEntry,
    TaskInteractiveChatMessage,
    TaskRecord,
    TokenUsageReport,
)


MLZERO_STAGE_SPECS = (
    {
        "stage": "python_coder",
        "title": "Python Coder",
        "prompt_prefix": "python_coder_prompt",
        "response_prefix": "python_coder_response",
    },
    {
        "stage": "bash_coder",
        "title": "Shell Wrapper",
        "prompt_prefix": "bash_coder_prompt",
        "response_prefix": "bash_coder_response",
    },
    {
        "stage": "executer",
        "title": "Execution Evaluator",
        "prompt_prefix": "executer_prompt",
        "response_prefix": "executer_response",
    },
    {
        "stage": "error_analyzer",
        "title": "Error Analyzer",
        "prompt_prefix": "error_analyzer_prompt",
        "response_prefix": "error_analyzer_response",
    },
    {
        "stage": "chat",
        "title": "Chat",
        "prompt_prefix": "chat_prompt",
        "response_prefix": "chat_response",
    },
)

STAGE_ORDER = {
    "task_analysis": 0,
    "python_coder": 1,
    "bash_coder": 2,
    "executer": 3,
    "error_analyzer": 4,
    "chat": 5,
}

PHASE_ORDER = {
    "analysis": 0,
    "mlzero": 1,
}

TEXT_STATE_SUFFIXES = {".txt", ".log", ".json", ".yaml", ".yml", ".py", ".sh", ".csv"}

ROOT_STATE_SPECS = {
    "run_summary.json": ("summary", "Run Summary", "Canonical MLZero run summary returned to the backend."),
    "leaderboard.csv": ("artifact", "Leaderboard", "Ranked candidate-model comparison saved by MLZero."),
    "token_usage.json": ("artifact", "Token Usage", "Recorded model-usage totals for the MLZero run."),
    "mlzero-runtime-config.yaml": ("artifact", "Runtime Config", "Resolved runtime configuration used for this MLZero run."),
    "logs.txt": ("log", "Logs", "Main MLZero runtime log stream."),
    "info_logs.txt": ("log", "Info Logs", "Higher-level MLZero progress log."),
    "debugging_logs.txt": ("log", "Debugging Logs", "Detailed debug-oriented MLZero log output."),
    "detail_logs.txt": ("log", "Detail Logs", "Expanded runtime log with additional execution detail."),
    "mlzero_stdout.log": ("log", "Captured STDOUT", "STDOUT captured from the MLZero process."),
    "mlzero_stderr.log": ("log", "Captured STDERR", "STDERR captured from the MLZero process."),
}

NODE_STATE_PREFIX_SPECS = (
    ("decision", "decision", "Planner Decision", "Node expansion or routing decision recorded by the planner."),
    ("error_summary", "error", "Error Summary", "Condensed failure summary used to guide the next repair step."),
    ("stdout", "log", "Node STDOUT", "STDOUT captured while executing this node."),
    ("stderr", "log", "Node STDERR", "STDERR captured while executing this node."),
    ("retriever_prompt", "retrieval", "Retriever Prompt", "Prompt sent into the retrieval agent for this node."),
    ("retriever_response", "retrieval", "Retriever Response", "Raw retrieval-agent response returned for this node."),
    ("tutorial_prompt", "retrieval", "Tutorial Prompt", "Prompt sent into tutorial retrieval for this node."),
    ("tutorial_retrievals", "retrieval", "Tutorial Retrievals", "Retrieved tutorial snippets used as code guidance."),
    ("tutorial_retriever_results", "retrieval", "Retriever Results", "Raw retriever output before reranking."),
    ("parsed_search_query", "retrieval", "Parsed Search Query", "Search query parsed from the retrieval workflow."),
    (
        "python_coder_prompt_before_truncation",
        "code",
        "Python Prompt Before Truncation",
        "Full python-coder prompt before runtime truncation and prompt compaction.",
    ),
    ("python_code", "code", "Python Draft", "Python draft extracted from the model response before execution."),
    ("extracted_bash_script", "code", "Shell Script", "Extracted shell or PowerShell wrapper used for execution."),
    ("validation_score", "metric", "Validation Score", "Recorded validation score snapshot for this node."),
    ("best_run_summary", "summary", "Best Run Summary", "Summary describing the current best node."),
)


def build_task_ai_conversations(task: TaskRecord) -> TaskAIConversationResponse:
    warnings: list[str] = []
    items: list[TaskAIConversationEntry] = []
    interactive_messages = _collect_interactive_messages(task, warnings)
    internal_states: list[TaskAIInternalStateEntry] = []

    analysis_entry = _build_analysis_entry(task, warnings)
    if analysis_entry is not None:
        items.append(analysis_entry)

    requested_run_dir, existing_run_dir = _resolve_run_output_dir(task)
    if requested_run_dir is not None and existing_run_dir is None:
        warnings.append(f"Latest MLZero output directory is missing: {requested_run_dir}")

    if existing_run_dir is not None:
        items.extend(_collect_mlzero_entries(existing_run_dir, warnings))
        excluded_paths = {
            Path(path_string)
            for item in items
            for path_string in (item.prompt_path, item.response_path)
            if isinstance(path_string, str) and path_string.strip()
        }
        internal_states.extend(_collect_mlzero_internal_states(existing_run_dir, warnings, excluded_paths=excluded_paths))

    items.sort(key=_conversation_sort_key)
    internal_states.sort(key=_internal_state_sort_key)

    return TaskAIConversationResponse(
        task_id=task.id,
        task_name=task.name,
        run_output_dir=str(existing_run_dir or requested_run_dir) if (existing_run_dir or requested_run_dir) else None,
        warnings=warnings,
        items=items,
        interactive_messages=interactive_messages,
        internal_states=internal_states,
    )


def _build_analysis_entry(task: TaskRecord, warnings: list[str]) -> TaskAIConversationEntry | None:
    analysis = task.structured_requirements if isinstance(task.structured_requirements, dict) else None
    if analysis is None:
        return None

    raw_response = analysis.get("raw_response")
    if not isinstance(raw_response, str) or not raw_response.strip():
        return None

    prompt = analysis.get("analysis_prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        warnings.append("AI analysis response exists, but the original analysis prompt was not persisted.")
        return None

    return TaskAIConversationEntry(
        id="analysis_task_analysis",
        phase="analysis",
        stage="task_analysis",
        title="Task Analysis",
        origin=_classify_origin("task_analysis", prompt, raw_response),
        prompt=prompt,
        response=raw_response,
        created_at=_parse_datetime(analysis.get("analyzed_at")),
    )


def _collect_interactive_messages(task: TaskRecord, warnings: list[str]) -> list[TaskInteractiveChatMessage]:
    analysis = task.structured_requirements if isinstance(task.structured_requirements, dict) else None
    if analysis is None:
        return []

    history = analysis.get("interactive_chat_history")
    if history is None:
        return []
    if not isinstance(history, list):
        warnings.append("Interactive chat history exists, but it is not stored as a list.")
        return []

    items: list[TaskInteractiveChatMessage] = []
    for index, raw_item in enumerate(history):
        if not isinstance(raw_item, dict):
            warnings.append(f"Interactive chat message #{index + 1} is not a JSON object.")
            continue

        role = raw_item.get("role")
        content = raw_item.get("content")
        if role not in {"user", "assistant"} or not isinstance(content, str) or not content.strip():
            warnings.append(f"Interactive chat message #{index + 1} is missing a valid role/content pair.")
            continue

        origin = raw_item.get("origin")
        if origin not in {"user", "ai_model", "local_runtime"}:
            origin = "user" if role == "user" else "ai_model"

        status = raw_item.get("status")
        if status not in {"ok", "error"}:
            status = "ok"

        token_usage = None
        raw_token_usage = raw_item.get("token_usage")
        if isinstance(raw_token_usage, dict):
            try:
                token_usage = TokenUsageReport.model_validate(raw_token_usage)
            except Exception:  # noqa: BLE001
                token_usage = None

        items.append(
            TaskInteractiveChatMessage(
                id=str(raw_item.get("id") or f"interactive_chat_{index + 1}"),
                role=role,
                origin=origin,
                content=content,
                status=status,
                model_name=raw_item.get("model_name") if isinstance(raw_item.get("model_name"), str) else None,
                composed_prompt=raw_item.get("composed_prompt") if isinstance(raw_item.get("composed_prompt"), str) else None,
                token_usage=token_usage,
                created_at=_parse_datetime(raw_item.get("created_at")),
            )
        )

    return items


def _resolve_run_output_dir(task: TaskRecord) -> tuple[Path | None, Path | None]:
    if task.last_run_attempt and task.last_run_attempt.output_dir:
        requested_path = Path(task.last_run_attempt.output_dir)
    elif task.last_run and task.last_run.output_dir:
        requested_path = Path(task.last_run.output_dir)
    else:
        return None, None
    return requested_path, requested_path if requested_path.exists() else None


def _collect_mlzero_entries(run_output_dir: Path, warnings: list[str]) -> list[TaskAIConversationEntry]:
    items: list[TaskAIConversationEntry] = []
    node_dirs = sorted(path for path in run_output_dir.glob("node_*") if path.is_dir())

    if not node_dirs:
        warnings.append(f"No node directories were found under the MLZero output directory: {run_output_dir}")
        return items

    for node_dir in node_dirs:
        states_dir = node_dir / "states"
        if not states_dir.is_dir():
            continue
        items.extend(_collect_node_entries(node_dir.name, states_dir, warnings))

    if not items:
        warnings.append(f"No prompt/response pairs were found under the MLZero output directory: {run_output_dir}")
    return items


def _collect_mlzero_internal_states(
    run_output_dir: Path,
    warnings: list[str],
    *,
    excluded_paths: set[Path],
) -> list[TaskAIInternalStateEntry]:
    items: list[TaskAIInternalStateEntry] = []

    items.extend(_collect_root_internal_states(run_output_dir, warnings, excluded_paths=excluded_paths))

    node_dirs = sorted(path for path in run_output_dir.glob("node_*") if path.is_dir())
    for node_dir in node_dirs:
        states_dir = node_dir / "states"
        if not states_dir.is_dir():
            continue
        items.extend(_collect_node_internal_states(node_dir.name, states_dir, warnings, excluded_paths=excluded_paths))

    return items


def _collect_node_entries(node_name: str, states_dir: Path, warnings: list[str]) -> list[TaskAIConversationEntry]:
    entries: list[TaskAIConversationEntry] = []
    for spec in MLZERO_STAGE_SPECS:
        pairs = _pair_state_files(
            states_dir=states_dir,
            prompt_prefix=spec["prompt_prefix"],
            response_prefix=spec["response_prefix"],
        )
        for suffix, prompt_path, response_path in pairs:
            prompt = _read_text_file(prompt_path, warnings)
            response = _read_text_file(response_path, warnings)
            if prompt is None or response is None:
                continue
            entries.append(
                TaskAIConversationEntry(
                    id=_build_entry_id(node_name, spec["stage"], suffix),
                    phase="mlzero",
                    stage=spec["stage"],
                    title=f"{node_name} {spec['title']}",
                    origin=_classify_origin(spec["stage"], prompt, response),
                    node=node_name,
                    prompt=prompt,
                    response=response,
                    prompt_path=str(prompt_path),
                    response_path=str(response_path),
                    created_at=_timestamp_from_paths(prompt_path, response_path),
                )
            )
    return entries


def _collect_root_internal_states(
    run_output_dir: Path,
    warnings: list[str],
    *,
    excluded_paths: set[Path],
) -> list[TaskAIInternalStateEntry]:
    items: list[TaskAIInternalStateEntry] = []
    for filename, (category, title, description) in ROOT_STATE_SPECS.items():
        path = run_output_dir / filename
        if path in excluded_paths or not path.is_file():
            continue
        content = _read_text_file(path, warnings)
        if content is None:
            continue
        items.append(
            TaskAIInternalStateEntry(
                id=f"root_{path.stem.replace('.', '_')}",
                phase="mlzero",
                title=title,
                category=category,
                description=description,
                path=str(path),
                content=content,
                created_at=_timestamp_from_paths(path),
            )
        )
    return items


def _collect_node_internal_states(
    node_name: str,
    states_dir: Path,
    warnings: list[str],
    *,
    excluded_paths: set[Path],
) -> list[TaskAIInternalStateEntry]:
    items: list[TaskAIInternalStateEntry] = []
    for path in sorted(states_dir.iterdir()):
        if not path.is_file():
            continue
        if path in excluded_paths:
            continue
        if not _is_supported_state_file(path):
            continue
        if _should_skip_state_file(path.name):
            continue
        category, title, description = _classify_node_state(path.name)
        content = _read_text_file(path, warnings)
        if content is None:
            continue
        items.append(
            TaskAIInternalStateEntry(
                id=f"{node_name}_{path.stem.replace('.', '_')}",
                phase="mlzero",
                title=f"{node_name} / {title}",
                category=category,
                description=description,
                node=node_name,
                path=str(path),
                content=content,
                created_at=_timestamp_from_paths(path),
            )
        )
    return items


def _is_supported_state_file(path: Path) -> bool:
    if path.suffix.lower() in TEXT_STATE_SUFFIXES:
        return True
    return path.suffix == "" and path.name in {"stdout", "stderr"}


def _should_skip_state_file(filename: str) -> bool:
    return ".orig_" in filename


def _classify_node_state(filename: str) -> tuple[str, str, str]:
    for prefix, category, title, description in NODE_STATE_PREFIX_SPECS:
        if filename.startswith(prefix):
            return category, title, description
    return "other", filename, "Additional MLZero internal state persisted for this node."


def _pair_state_files(
    *,
    states_dir: Path,
    prompt_prefix: str,
    response_prefix: str,
) -> list[tuple[str, Path, Path]]:
    prompt_map = _build_suffix_map(states_dir, prompt_prefix)
    response_map = _build_suffix_map(states_dir, response_prefix)
    shared_suffixes = sorted(set(prompt_map).intersection(response_map))
    return [(suffix, prompt_map[suffix], response_map[suffix]) for suffix in shared_suffixes]


def _build_suffix_map(states_dir: Path, prefix: str) -> dict[str, Path]:
    mapping: dict[str, Path] = {}
    for path in states_dir.glob(f"{prefix}*.txt"):
        suffix = _extract_state_suffix(path.name, prefix)
        if suffix is not None:
            mapping[suffix] = path
    return mapping


def _extract_state_suffix(filename: str, prefix: str) -> str | None:
    if not filename.startswith(prefix) or not filename.endswith(".txt"):
        return None
    return filename[len(prefix) : -4]


def _build_entry_id(node_name: str, stage: str, suffix: str) -> str:
    normalized_suffix = suffix.replace(".", "_").replace("-", "_")
    return f"{node_name}_{stage}{normalized_suffix}"


def _read_text_file(path: Path, warnings: list[str]) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        warnings.append(f"Failed to read file {path}: {exc}")
        return None


def _timestamp_from_paths(*paths: Path) -> datetime | None:
    timestamps = []
    for path in paths:
        try:
            timestamps.append(path.stat().st_mtime)
        except OSError:
            continue
    if not timestamps:
        return None
    return datetime.fromtimestamp(max(timestamps), tz=timezone.utc)


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    cleaned = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _classify_origin(stage: str, prompt: str, response: str) -> str:
    combined = f"{prompt}\n{response}".lower()
    if "local deterministic" in combined or "without llm" in combined:
        return "local_runtime"
    if "powershell execution wrapper" in combined:
        return "local_runtime"
    if stage == "task_analysis":
        return "ai_model"
    return "ai_model"


def _conversation_sort_key(item: TaskAIConversationEntry) -> tuple[int, float, int, int, str]:
    phase_order = PHASE_ORDER.get(item.phase, 999)
    timestamp = item.created_at.timestamp() if item.created_at is not None else 0.0
    node_order = _node_sort_order(item.node)
    stage_order = STAGE_ORDER.get(item.stage, 999)
    return (phase_order, timestamp, node_order, stage_order, item.id)


def _internal_state_sort_key(item: TaskAIInternalStateEntry) -> tuple[int, float, int, str, str]:
    phase_order = PHASE_ORDER.get(item.phase, 999)
    timestamp = item.created_at.timestamp() if item.created_at is not None else 0.0
    node_order = _node_sort_order(item.node)
    return (phase_order, timestamp, node_order, item.category, item.id)


def _node_sort_order(node_name: str | None) -> int:
    if not node_name:
        return -1
    try:
        return int(node_name.removeprefix("node_"))
    except ValueError:
        return 999
