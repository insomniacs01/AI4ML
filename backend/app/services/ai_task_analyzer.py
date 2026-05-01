from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from backend.app.core.config import Settings
from backend.app.models.task import TaskRecord, TokenUsageReport
from backend.app.services.dataset_profile import build_dataset_profile, dataset_profile_to_plain
from backend.app.services.mlzero_runtime import LocalOpenAIProvider
from backend.app.services.openai_compatible_provider import (
    ProviderCallResult,
    call_openai_compatible_provider,
)


@dataclass
class TaskAnalysisResult:
    label_column: str
    problem_type: str
    metric_name: str
    reasoning: str
    confidence: float
    analysis_model: str
    analyzed_at: str
    column_names: list[str]
    preview_rows: list[dict[str, str]]
    prompt: str
    raw_response: str
    token_usage: TokenUsageReport | None


def analyze_task_with_ai(task: TaskRecord, dataset_path: Path, settings: Settings) -> TaskAnalysisResult:
    provider = LocalOpenAIProvider(settings)
    reason = provider.unavailability_reason()
    if reason is not None:
        raise RuntimeError(f"当前 AI 连接器不可用：{reason}")

    column_names, preview_rows = _read_csv_preview(dataset_path)
    if not column_names:
        raise RuntimeError("CSV 文件没有可读取的表头，AI 无法解析任务。")

    prompt = _build_analysis_prompt(
        task_name=task.name,
        task_description=task.description,
        column_names=column_names,
        preview_rows=preview_rows,
    )
    provider_result = _call_provider(prompt=prompt, settings=settings)
    if provider_result.token_usage is None:
        raise RuntimeError("AI Provider 响应中缺少 usage token 信息，无法记录本次 AI 解析消耗。")
    payload = _parse_analysis_payload(provider_result.text)

    label_column = str(payload.get("label_column", "")).strip()
    if label_column not in column_names:
        raise RuntimeError(
            "AI 返回的目标列不在 CSV 表头中。"
            f" 返回值：{label_column or '<empty>'}；表头：{', '.join(column_names)}"
        )

    problem_type = str(payload.get("problem_type", "")).strip().lower()
    if problem_type not in {"classification", "regression"}:
        raise RuntimeError(
            "AI 返回的任务类型无效。"
            f" 期望 classification 或 regression，实际为：{problem_type or '<empty>'}"
        )

    metric_name = str(payload.get("metric_name", "")).strip().lower()
    if not metric_name:
        raise RuntimeError("AI 返回的 metric_name 为空。")

    reasoning = str(payload.get("reasoning", "")).strip()
    if not reasoning:
        raise RuntimeError("AI 返回的 reasoning 为空。")

    confidence_raw = payload.get("confidence")
    if confidence_raw is None:
        raise RuntimeError("AI 返回中缺少 confidence。")
    try:
        confidence = float(confidence_raw)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"AI 返回的 confidence 不是有效数字：{confidence_raw!r}") from exc
    if not 0.0 <= confidence <= 1.0:
        raise RuntimeError(f"AI 返回的 confidence 超出范围 [0, 1]：{confidence_raw!r}")

    return TaskAnalysisResult(
        label_column=label_column,
        problem_type=problem_type,
        metric_name=metric_name,
        reasoning=reasoning,
        confidence=confidence,
        analysis_model=settings.mlzero_model_alias,
        analyzed_at=datetime.now(timezone.utc).isoformat(),
        column_names=column_names,
        preview_rows=preview_rows,
        prompt=prompt,
        raw_response=provider_result.text,
        token_usage=provider_result.token_usage,
    )


def apply_analysis_to_task(task: TaskRecord, analysis: TaskAnalysisResult) -> TaskRecord:
    task.label_column = analysis.label_column
    task.problem_type = analysis.problem_type
    task.analysis_token_usage = analysis.token_usage
    structured_requirements = dict(task.structured_requirements) if isinstance(task.structured_requirements, dict) else {}
    if task.dataset_path:
        dataset_profile = build_dataset_profile(
            Path(task.dataset_path),
            filename=task.dataset_filename,
            target_column=analysis.label_column,
        )
        structured_requirements["dataset_profile"] = dataset_profile_to_plain(dataset_profile)
    structured_requirements.update({
        "analysis_source": "ai_connector",
        "analysis_model": analysis.analysis_model,
        "metric_name": analysis.metric_name,
        "reasoning": analysis.reasoning,
        "confidence": analysis.confidence,
        "column_names": analysis.column_names,
        "preview_rows": analysis.preview_rows,
        "analyzed_at": analysis.analyzed_at,
        "analysis_prompt": analysis.prompt,
        "raw_response": analysis.raw_response,
        "token_usage": analysis.token_usage.model_dump() if analysis.token_usage is not None else None,
    })
    task.structured_requirements = structured_requirements
    task.notes = (
        f"AI 已解析任务：目标列为 {analysis.label_column}，"
        f"任务类型为 {analysis.problem_type}，建议指标为 {analysis.metric_name}。"
    )
    return task


def _read_csv_preview(dataset_path: Path, *, max_rows: int = 5) -> tuple[list[str], list[dict[str, str]]]:
    with dataset_path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            return [], []

        preview_rows: list[dict[str, str]] = []
        for index, row in enumerate(reader):
            if index >= max_rows:
                break
            preview_rows.append({str(key): ("" if value is None else str(value))[:120] for key, value in row.items()})

    return [str(item) for item in reader.fieldnames], preview_rows


def _build_analysis_prompt(*, task_name: str, task_description: str, column_names: list[str], preview_rows: list[dict[str, str]]) -> str:
    return (
        "You are an expert machine learning task analyst.\n"
        "Infer the label column, problem type, and evaluation metric from the user's task description and the CSV preview.\n"
        "Do not invent a label column that is not present in the provided column list.\n"
        "If the task is about predicting a numeric quantity, prefer regression.\n"
        "Return JSON only with exactly these keys: label_column, problem_type, metric_name, reasoning, confidence.\n"
        "problem_type must be classification or regression. confidence must be a number between 0 and 1.\n\n"
        f"Task name: {task_name}\n"
        f"Task description: {task_description}\n"
        f"CSV columns: {json.dumps(column_names, ensure_ascii=False)}\n"
        f"CSV preview rows: {json.dumps(preview_rows, ensure_ascii=False, indent=2)}\n"
    )


def _call_provider(*, prompt: str, settings: Settings) -> ProviderCallResult:
    return call_openai_compatible_provider(
        prompt=prompt,
        settings=settings,
        system_message="You analyze machine learning tasks and respond with strict JSON only.",
        temperature=0,
        max_tokens=500,
    )


def _parse_analysis_payload(raw_response: str) -> dict:
    cleaned = raw_response.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"AI 返回的 JSON 无法解析：{cleaned}") from exc
        raise RuntimeError(f"AI 没有返回可解析的 JSON：{cleaned}")
