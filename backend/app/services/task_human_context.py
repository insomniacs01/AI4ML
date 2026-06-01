from __future__ import annotations

from typing import Any

from backend.app.models.task import TaskRecord
from backend.app.services.task_human_parameter_guidance import build_task_human_parameter_guidance_lines


HUMAN_LOOP_KEY = "human_loop"
MAX_DECISION_HISTORY = 20
DEFAULT_PROMPT_DECISION_LIMIT = 5
HUMAN_GUIDANCE_TARGETS = [
    "Codex task prompt",
    "Codex output/plan.md",
    "Codex runtime workspace context",
    "Task interactive AI chat context",
]


STAGE_LABELS = {
    "requirement_analysis": "requirement analysis",
    "data_analysis": "data analysis",
    "feature_engineering": "feature engineering",
    "model_selection": "model selection",
    "training_validation": "training and validation",
    "report_generation": "report generation",
    "request_review": "requirement analysis",
    "code_generation": "feature engineering",
    "execution_validation": "training and validation",
    "report_review": "report generation",
}

ACTION_LABELS = {
    "approve": "approved",
    "revise": "revise before the next run",
    "block": "blocked until addressed",
}


def get_task_human_loop(task: TaskRecord) -> dict[str, Any]:
    if not isinstance(task.structured_requirements, dict):
        return {}
    value = task.structured_requirements.get(HUMAN_LOOP_KEY)
    return value if isinstance(value, dict) else {}


def ensure_task_human_loop(task: TaskRecord) -> dict[str, Any]:
    requirements = dict(task.structured_requirements) if isinstance(task.structured_requirements, dict) else {}
    human_loop = requirements.get(HUMAN_LOOP_KEY)
    if not isinstance(human_loop, dict):
        human_loop = {}
    requirements[HUMAN_LOOP_KEY] = human_loop
    task.structured_requirements = requirements
    return human_loop


def get_task_human_decision_history(task: TaskRecord, *, limit: int | None = None) -> list[dict[str, Any]]:
    human_loop = get_task_human_loop(task)
    raw_history = human_loop.get("decision_history")
    if not isinstance(raw_history, list):
        return []

    history = [item for item in raw_history if isinstance(item, dict)]
    if limit is not None and limit >= 0:
        return history[-limit:]
    return history


def append_task_human_decision(task: TaskRecord, entry: dict[str, Any]) -> dict[str, Any]:
    human_loop = ensure_task_human_loop(task)
    history = [item for item in human_loop.get("decision_history", []) if isinstance(item, dict)]
    history.append(entry)
    human_loop["decision_history"] = history[-MAX_DECISION_HISTORY:]
    human_loop["latest_decision"] = entry
    return entry


def build_task_human_guidance_lines(task: TaskRecord, *, limit: int = DEFAULT_PROMPT_DECISION_LIMIT) -> list[str]:
    parameter_lines = build_task_human_parameter_guidance_lines(task)
    history = get_task_human_decision_history(task, limit=limit)
    if not history and not parameter_lines:
        return []

    lines = [
        "Human-reviewed decisions are available below. Treat them as higher-priority instructions for the next run unless the CSV clearly contradicts them.",
    ]
    lines.extend(parameter_lines)

    for index, item in enumerate(history, start=1):
        lines.append(_decision_guidance_line(index, item))

    return lines


def build_task_human_context_block(task: TaskRecord, *, limit: int = DEFAULT_PROMPT_DECISION_LIMIT) -> str:
    lines = build_task_human_guidance_lines(task, limit=limit)
    if not lines:
        return "No recorded human collaboration decisions."
    return "\n".join(f"- {line}" for line in lines)


def build_task_human_description_appendix(task: TaskRecord, *, limit: int = DEFAULT_PROMPT_DECISION_LIMIT) -> str:
    lines = build_task_human_guidance_lines(task, limit=limit)
    if not lines:
        return ""
    return "\n".join(["Human collaboration guidance:", *lines])


def build_task_human_instruction_file(task: TaskRecord, *, limit: int = DEFAULT_PROMPT_DECISION_LIMIT) -> str:
    lines = build_task_human_guidance_lines(task, limit=limit)
    if not lines:
        return ""
    return "\n".join(
        [
            f"Task name: {task.name}",
            "These are human-reviewed decisions that must influence the next Codex run.",
            "Treat them as explicit user-approved corrections unless the dataset itself proves they are impossible.",
            "",
            *lines,
        ]
    )


def build_task_human_initial_instruction_note(task: TaskRecord, *, limit: int = DEFAULT_PROMPT_DECISION_LIMIT) -> str:
    lines = build_task_human_guidance_lines(task, limit=limit)
    if not lines:
        return ""
    return "Follow the recorded human collaboration decisions from the task context and the human_collaboration_instructions.txt file."


def build_task_human_guidance_preview(task: TaskRecord, *, limit: int = DEFAULT_PROMPT_DECISION_LIMIT) -> dict[str, Any]:
    lines = build_task_human_guidance_lines(task, limit=limit)
    return {
        "has_guidance": bool(lines),
        "decision_count": len(get_task_human_decision_history(task)),
        "targets": list(HUMAN_GUIDANCE_TARGETS),
        "prompt_guidance_lines": lines,
        "description_appendix": build_task_human_description_appendix(task, limit=limit),
        "human_instruction_file": build_task_human_instruction_file(task, limit=limit),
        "chat_context_block": build_task_human_context_block(task, limit=limit),
        "initial_instruction_note": build_task_human_initial_instruction_note(task, limit=limit),
    }


def _clip_text(value: str, limit: int) -> str:
    normalized = value.strip()
    if not normalized:
        return ""
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit]}..."


def _decision_guidance_line(index: int, item: dict[str, Any]) -> str:
    stage = STAGE_LABELS.get(str(item.get("stage") or ""), str(item.get("stage") or "unknown stage"))
    action = ACTION_LABELS.get(str(item.get("action") or ""), str(item.get("action") or "unknown action"))
    title = _clip_text(str(item.get("title") or "untitled request"), 160)
    decision_summary = _clip_text(str(item.get("decision_summary") or "no decision summary"), 320)
    request_summary = _clip_text(str(item.get("request_summary") or ""), 220)
    suggested_action = _clip_text(str(item.get("suggested_action") or ""), 220)

    line = (
        f"Human decision {index}: Stage={stage}; request='{title}'; status={action}; "
        f"decision='{decision_summary}'."
    )
    if request_summary:
        line += f" Original issue: {request_summary}."
    if suggested_action:
        line += f" Requested change: {suggested_action}."
    return line + _artifact_paths_text(item.get("artifact_paths"))


def _artifact_paths_text(artifact_paths: Any) -> str:
    if not isinstance(artifact_paths, list):
        return ""

    normalized_paths = [str(path).strip() for path in artifact_paths if str(path).strip()]
    if not normalized_paths:
        return ""
    return f" Relevant artifacts: {', '.join(normalized_paths[:4])}."
