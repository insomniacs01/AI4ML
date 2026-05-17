from __future__ import annotations

import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from backend.app.core.config import Settings
from backend.app.models.task import (
    TaskRecord,
    TaskRunProgressArtifactSummary,
    TaskRunProgressEvent,
    TaskRunProgressInsight,
    TaskRunProgressLeaderboardRow,
    TaskRunProgressResponse,
    TaskRunProgressTrainingMetric,
    TaskStatus,
    WorkflowStage,
)
from backend.app.services.task_artifacts import (
    LOG_CANDIDATE_NAMES,
    RunArtifactIndex,
    api_path as _api_path,
    build_run_artifact_index,
    count_leaderboard_rows as _count_leaderboard_rows,
    latest_modified_at as _latest_modified_at,
    path_mtime as _path_mtime,
    recent_node_dirs as _recent_node_dirs,
    read_json_payload,
)


STALE_RUNNING_SECONDS = 60 * 60
RECOVERABLE_RUN_MARKERS = (
    "agent 自动修复受阻",
    "apitimeouterror",
    "request timed out",
    "readtimeout",
    "retryerror",
    "modulenotfounderror",
    "no module named",
    "run_summary.json",
    "leaderboard",
)

RAW_RUNTIME_MARKERS = (
    "mlzero run failed",
    "return code:",
    "traceback (most recent call last)",
    "[autogluon.assistant",
    "autogluon.assistant.",
    "\\mlzero_runs\\",
    "/mlzero_runs/",
    "\\storage\\mlzero_runs\\",
    "/storage/mlzero_runs/",
    "logs.txt tail",
    "info_logs.txt tail",
    "detail_logs.txt tail",
    "debugging_logs.txt",
    "captured stdout tail",
    "captured stderr",
    "wire_api=chat_completions",
    "tutorial retrieval is disabled",
    "install faiss-cpu",
)

MLZERO_TERMINAL_MARKERS = (
    "mcts search completed",
    "output saved in",
)
MLZERO_MAX_ITERATION_MARKERS = (
    "reached maximum iterations",
)
MLZERO_INTERRUPTED_MARKERS = (
    "keyboardinterrupt",
    "operation cancelled",
    "operation canceled",
)


def build_task_run_progress(
    task: TaskRecord,
    settings: Settings,
    *,
    stale_after_seconds: int = STALE_RUNNING_SECONDS,
) -> TaskRunProgressResponse:
    repair_blocked = _is_recoverable_run_block(task)
    artifact_index = build_run_artifact_index(
        task,
        settings=settings,
        include_candidate_roots=True,
        require_current_running=task.status == TaskStatus.running and not repair_blocked,
    )
    output_dir = artifact_index.output_dir
    warnings: list[str] = []
    if output_dir is None:
        return TaskRunProgressResponse(
            task=task,
            status="blocked" if repair_blocked else "not_started" if task.status not in {TaskStatus.running, TaskStatus.failed} else task.status.value,
            current_activity=task.notes or "尚未找到自动建模运行目录。",
            warnings=[] if task.status != TaskStatus.running or repair_blocked else ["任务仍标记为运行中，但没有找到对应运行目录。"],
        )

    artifacts = _summarize_artifacts(artifact_index)
    if artifacts.has_run_summary and artifacts.has_leaderboard and not artifacts.has_token_usage:
        warnings.append("已找到结果摘要和候选模型对比，但缺少 AI 使用记录；当前不能把它判定为完整成功。")

    last_log_at = _latest_modified_at(output_dir)
    seconds_since_last_update = None
    if last_log_at is not None:
        seconds_since_last_update = max((datetime.now(timezone.utc) - last_log_at).total_seconds(), 0.0)

    latest_log_lines = _read_latest_log_lines(output_dir)
    terminal_state = _detect_mlzero_terminal_state(latest_log_lines)
    log_records = _read_recent_log_records(output_dir)
    if terminal_state is None:
        terminal_state = _detect_mlzero_terminal_state_from_records(log_records)
    events = _build_progress_events(log_records)
    response_events = _select_response_events(events)
    leaderboard = _read_leaderboard_rows(artifacts.leaderboard_path)
    training_metrics = _read_training_metrics(output_dir)
    realtime_signals = _derive_realtime_signals(
        log_records=log_records,
        events=events,
        leaderboard=leaderboard,
        training_metrics=training_metrics,
        artifacts=artifacts,
    )
    current_stage, current_activity, progress_percent = _infer_activity(
        latest_log_lines,
        artifacts=artifacts,
        task_status=task.status,
        repair_blocked=repair_blocked,
    )
    if realtime_signals.get("current_stage") is not None:
        current_stage = realtime_signals["current_stage"]
    if realtime_signals.get("current_activity"):
        current_activity = str(realtime_signals["current_activity"])
    if realtime_signals.get("progress_percent") is not None:
        progress_percent = max(progress_percent, int(realtime_signals["progress_percent"]))

    stale = (
        task.status == TaskStatus.running
        and not repair_blocked
        and terminal_state is None
        and seconds_since_last_update is not None
        and seconds_since_last_update > stale_after_seconds
    )
    stale_reason = None
    if stale:
        stale_reason = (
            f"运行目录已经 {int(seconds_since_last_update // 60)} 分钟没有新日志或生成文件写入；"
            "这通常表示自动建模进程已中断或卡住。"
        )

    status = _resolve_progress_status(
        task,
        stale=stale,
        artifacts=artifacts,
        repair_blocked=repair_blocked,
        terminal_state=terminal_state,
    )
    if stale and current_activity:
        current_activity = f"{current_activity}（已长时间无更新）"
    if terminal_state == "max_iterations" and task.status == TaskStatus.running and current_activity:
        current_activity = f"{current_activity}（已达到最大搜索轮次）"
    insights = _build_observer_insights(
        log_records=log_records,
        leaderboard=leaderboard,
        training_metrics=training_metrics,
        artifacts=artifacts,
        realtime_signals=realtime_signals,
        task_status=task.status,
        stale=stale,
        stale_reason=stale_reason,
        repair_blocked=repair_blocked,
        terminal_state=terminal_state,
        task_notes=task.notes,
    )
    observer_status, observer_detail, observer_stage = _resolve_observer_state(insights)
    if observer_stage is not None:
        current_stage = observer_stage
    if observer_status:
        current_activity = f"{observer_status}：{observer_detail}" if observer_detail else observer_status

    return TaskRunProgressResponse(
        task=task,
        output_dir=str(output_dir),
        status=status,
        progress_percent=progress_percent,
        current_stage=current_stage,
        current_activity=current_activity or task.notes or "暂无可解析的运行活动。",
        observer_status=observer_status,
        observer_detail=observer_detail,
        observer_stage=observer_stage,
        last_log_at=last_log_at,
        seconds_since_last_update=seconds_since_last_update,
        stale=stale,
        stale_reason=stale_reason,
        artifacts=artifacts,
        latest_log_lines=latest_log_lines[-80:],
        events=response_events,
        insights=insights[-80:],
        leaderboard=leaderboard[:40],
        training_metrics=training_metrics[-200:],
        current_model=_coerce_str(realtime_signals.get("current_model")),
        completed_model_count=_coerce_int(realtime_signals.get("completed_model_count")),
        total_model_count=_coerce_int(realtime_signals.get("total_model_count")),
        current_iteration=_coerce_int(realtime_signals.get("current_iteration")),
        total_iterations=_coerce_int(realtime_signals.get("total_iterations")),
        current_epoch=_coerce_int(realtime_signals.get("current_epoch")),
        total_epochs=_coerce_int(realtime_signals.get("total_epochs")),
        current_model_started_at=realtime_signals.get("current_model_started_at") if isinstance(realtime_signals.get("current_model_started_at"), datetime) else None,
        current_model_elapsed_seconds=_coerce_float(realtime_signals.get("current_model_elapsed_seconds")),
        current_model_time_budget_seconds=_coerce_float(realtime_signals.get("current_model_time_budget_seconds")),
        latest_train_loss=_coerce_float(realtime_signals.get("latest_train_loss")),
        latest_validation_loss=_coerce_float(realtime_signals.get("latest_validation_loss")),
        latest_validation_score=_coerce_float(realtime_signals.get("latest_validation_score")),
        telemetry_note=_coerce_str(realtime_signals.get("telemetry_note")),
        warnings=warnings,
    )


def _is_recoverable_run_block(task: TaskRecord) -> bool:
    text = (task.notes or "").lower()
    if not text:
        return False
    if "agent 自动修复受阻" in text:
        return True
    if task.status not in {TaskStatus.running, TaskStatus.failed}:
        return False
    return any(marker in text for marker in RECOVERABLE_RUN_MARKERS)


def _summarize_artifacts(artifact_index: RunArtifactIndex) -> TaskRunProgressArtifactSummary:
    payload = read_json_payload(artifact_index.run_summary_path)
    error_log_path = _select_error_log_path(artifact_index)
    return TaskRunProgressArtifactSummary(
        has_run_summary=artifact_index.has_run_summary,
        has_leaderboard=artifact_index.has_leaderboard,
        has_token_usage=artifact_index.has_token_usage,
        has_generated_code=artifact_index.has_generated_code,
        run_summary_path=_api_path(artifact_index.run_summary_path),
        leaderboard_path=_api_path(artifact_index.leaderboard_path),
        token_usage_path=_api_path(artifact_index.token_usage_path),
        generated_code_path=_api_path(artifact_index.generated_code_path),
        error_log_path=_api_path(error_log_path),
        error_log_name=error_log_path.name if error_log_path else None,
        best_model=_coerce_str(payload.get("best_model")) if payload else None,
        metric_name=_coerce_str(payload.get("metric_name")) if payload else None,
        metric_value=_coerce_float(payload.get("metric_value")) if payload else None,
        validation_score=_coerce_float(payload.get("validation_score")) if payload else None,
        candidate_model_count=(
            _coerce_int(payload.get("candidate_model_count"))
            if payload
            else _count_leaderboard_rows(artifact_index.leaderboard_path)
        ),
    )


def _select_error_log_path(artifact_index: RunArtifactIndex) -> Path | None:
    output_dir = artifact_index.output_dir
    if output_dir is None or not output_dir.exists():
        return None
    priority_names = (
        "mlzero_stderr.log",
        "logs.txt",
        "info_logs.txt",
        "detail_logs.txt",
        "debugging_logs.txt",
        "mlzero_stdout.log",
    )
    candidates = [output_dir / name for name in priority_names]
    for node_dir in artifact_index.node_dirs:
        candidates.extend(node_dir / name for name in priority_names)
        candidates.extend(node_dir / "output" / name for name in priority_names)
        candidates.extend(node_dir / "logs" / name for name in priority_names)
        states_dir = node_dir / "states"
        if states_dir.exists():
            try:
                candidates.extend(
                    path for path in states_dir.iterdir()
                    if path.is_file() and (path.name.startswith("stderr") or path.name.startswith("error_summary"))
                )
            except OSError:
                pass
    candidates.extend(sorted(output_dir.rglob("*.log"), key=_path_mtime, reverse=True))
    seen: set[Path] = set()
    for path in candidates:
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        try:
            if path.stat().st_size <= 0:
                continue
        except OSError:
            continue
        return path
    return None


def _detect_mlzero_terminal_state(lines: list[str]) -> str | None:
    text = "\n".join(lines).lower()
    if not text:
        return None
    if any(marker in text for marker in MLZERO_INTERRUPTED_MARKERS):
        return "interrupted"
    if any(marker in text for marker in MLZERO_MAX_ITERATION_MARKERS):
        return "max_iterations"
    if all(marker in text for marker in MLZERO_TERMINAL_MARKERS):
        return "completed"
    return None


def _detect_mlzero_terminal_state_from_records(log_records: list[dict[str, object]]) -> str | None:
    lines = [
        _coerce_str(record.get("message")) or _coerce_str(record.get("raw")) or ""
        for record in log_records[-160:]
    ]
    return _detect_mlzero_terminal_state(lines)


def _infer_activity(
    lines: list[str],
    *,
    artifacts: TaskRunProgressArtifactSummary,
    task_status: TaskStatus,
    repair_blocked: bool = False,
) -> tuple[WorkflowStage | None, str, int]:
    text = "\n".join(lines)
    last_line = _last_activity_line(lines)
    current_stage: WorkflowStage | None = None

    if "CoderAgent" in text or "python_coder" in text or "generated_code.py" in text:
        current_stage = WorkflowStage.feature_engineering
    if "Executing code" in text or "ExecuterAgent" in text or "training" in text or "Validation score" in text:
        current_stage = WorkflowStage.training_validation
    if "leaderboard" in text or "Best node" in text or "candidate" in text:
        current_stage = WorkflowStage.model_selection
    if artifacts.has_run_summary and artifacts.has_leaderboard:
        current_stage = WorkflowStage.training_validation

    progress = 0
    iteration_matches = list(re.finditer(r"Starting MCTS iteration\s+(\d+)\s*/\s*(\d+)", text, flags=re.IGNORECASE))
    if iteration_matches:
        current, total = int(iteration_matches[-1].group(1)), int(iteration_matches[-1].group(2))
        if total > 0:
            progress = min(94, max(8, int((current - 1) / total * 100)))
    if artifacts.has_generated_code:
        progress = max(progress, 35)
    if artifacts.has_run_summary or artifacts.has_leaderboard:
        progress = max(progress, 72)
    if artifacts.has_run_summary and artifacts.has_leaderboard and artifacts.has_token_usage:
        progress = max(progress, 95)
    if task_status == TaskStatus.completed or (task_status == TaskStatus.failed and not repair_blocked):
        progress = 100

    if artifacts.best_model and artifacts.metric_name and artifacts.metric_value is not None:
        activity = f"已产出候选结果：最佳模型 {artifacts.best_model}，{artifacts.metric_name} = {artifacts.metric_value:.6g}。"
    elif last_line:
        activity = _strip_log_prefix(last_line)
    else:
        activity = _fallback_activity(current_stage, task_status)
    return current_stage, activity, progress


def _resolve_progress_status(
    task: TaskRecord,
    *,
    stale: bool,
    artifacts: TaskRunProgressArtifactSummary,
    repair_blocked: bool = False,
    terminal_state: str | None = None,
) -> str:
    if repair_blocked:
        return "blocked"
    if task.status == TaskStatus.running and terminal_state in {"max_iterations", "interrupted"}:
        return "blocked"
    if stale:
        return "stale"
    if task.status == TaskStatus.completed:
        return "completed"
    if task.status == TaskStatus.failed:
        return "failed"
    if task.status == TaskStatus.running:
        return "running"
    if artifacts.has_run_summary and artifacts.has_leaderboard and artifacts.has_token_usage:
        return "completed"
    if artifacts.has_run_summary or artifacts.has_leaderboard:
        return "unknown"
    return "not_started"


def _read_latest_log_lines(output_dir: Path, *, max_lines: int = 160) -> list[str]:
    candidates = [output_dir / name for name in LOG_CANDIDATE_NAMES]
    for node_dir in _recent_node_dirs(output_dir):
        candidates.extend(node_dir / name for name in LOG_CANDIDATE_NAMES)
        candidates.extend((node_dir / "output" / name for name in LOG_CANDIDATE_NAMES))
        candidates.extend((node_dir / "logs" / name for name in LOG_CANDIDATE_NAMES))
    candidates = sorted(candidates, key=_path_mtime, reverse=True)
    latest = next((path for path in candidates if path.is_file()), None)
    if latest is None:
        return []
    try:
        text = latest.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return text.strip().splitlines()[-max_lines:]


def _read_recent_log_records(output_dir: Path, *, max_lines_per_file: int = 180, max_records: int = 420) -> list[dict[str, object]]:
    candidates = [output_dir / name for name in LOG_CANDIDATE_NAMES]
    for node_dir in _recent_node_dirs(output_dir):
        candidates.extend(node_dir / name for name in LOG_CANDIDATE_NAMES)
        candidates.extend(node_dir / "output" / name for name in LOG_CANDIDATE_NAMES)
        candidates.extend(node_dir / "logs" / name for name in LOG_CANDIDATE_NAMES)
        states_dir = node_dir / "states"
        if states_dir.exists():
            try:
                candidates.extend(
                    path for path in states_dir.iterdir()
                    if path.is_file() and (
                        path.name.startswith("stdout")
                        or path.name.startswith("stderr")
                        or path.name.startswith("validation_score")
                        or path.name.startswith("decision")
                        or path.name.startswith("error_summary")
                    )
                )
            except OSError:
                pass

    records: list[dict[str, object]] = []
    seen: set[tuple[str, str, int]] = set()
    for file_order, path in enumerate(sorted({candidate for candidate in candidates if candidate.is_file()}, key=lambda item: (_path_mtime(item), str(item)))):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        line_indexes = _log_line_indexes_to_keep(lines, max_tail=max_lines_per_file)
        fallback_time = datetime.fromtimestamp(_path_mtime(path), tz=timezone.utc)
        for index in line_indexes:
            line = lines[index]
            stripped = line.strip()
            if not stripped:
                continue
            parsed_time, source, message = _parse_log_record(stripped)
            source_label = source or _log_source_label(path, output_dir)
            key = (source_label, stripped, index)
            if key in seen:
                continue
            seen.add(key)
            records.append(
                {
                    "time": parsed_time or fallback_time,
                    "time_is_fallback": parsed_time is None,
                    "source": source_label,
                    "message": message or stripped,
                    "raw": stripped,
                    "path": str(path),
                    "line_index": index,
                    "order": file_order + index / 100000,
                }
            )

    sorted_records = sorted(records, key=lambda item: (_record_time_sort_key(item), float(item.get("order") or 0.0)))
    important_records = [record for record in sorted_records if _is_progress_signal_line(_coerce_str(record.get("message")) or _coerce_str(record.get("raw")) or "")]
    recent_records = sorted_records[-max_records:]
    if not important_records:
        return recent_records

    merged: list[dict[str, object]] = []
    merged_seen: set[tuple[str, str, int]] = set()
    for record in [*important_records[-160:], *recent_records]:
        key = (
            _coerce_str(record.get("source")) or "",
            _coerce_str(record.get("raw")) or _coerce_str(record.get("message")) or "",
            _coerce_int(record.get("line_index")) or 0,
        )
        if key in merged_seen:
            continue
        merged_seen.add(key)
        merged.append(record)
    return sorted(merged, key=lambda item: (_record_time_sort_key(item), float(item.get("order") or 0.0)))


def _log_line_indexes_to_keep(lines: list[str], *, max_tail: int) -> list[int]:
    tail_start = max(0, len(lines) - max_tail)
    indexes = set(range(tail_start, len(lines)))
    indexes.update(index for index, line in enumerate(lines) if _is_progress_signal_line(line))
    return sorted(indexes)


def _log_source_label(path: Path, output_dir: Path) -> str:
    try:
        relative = path.relative_to(output_dir)
    except ValueError:
        relative = path
    parts = relative.parts
    if len(parts) >= 3 and parts[-2] == "states":
        node_name = parts[-3]
        file_name = parts[-1]
        if file_name.startswith("stderr"):
            return f"{node_name}/stderr"
        if file_name.startswith("stdout"):
            return f"{node_name}/stdout"
    return relative.as_posix()


def _is_progress_signal_line(line: str) -> bool:
    return bool(
        re.search(r"Fitting\s+\d+\s+L\d+\s+models", line, flags=re.IGNORECASE)
        or re.search(r"Fitting\s+model:", line, flags=re.IGNORECASE)
        or re.search(r"=\s*Training\s+runtime", line, flags=re.IGNORECASE)
        or re.search(r"Validation\s+score", line, flags=re.IGNORECASE)
        or re.search(r"AutoGluon\s+training\s+complete", line, flags=re.IGNORECASE)
        or re.search(r"Best\s+model:", line, flags=re.IGNORECASE)
        or re.search(r"Starting\s+MCTS\s+iteration", line, flags=re.IGNORECASE)
        or re.search(r"Reached\s+maximum\s+iterations", line, flags=re.IGNORECASE)
        or re.search(r"MCTS\s+search\s+completed", line, flags=re.IGNORECASE)
        or re.search(r"Output\s+saved\s+in", line, flags=re.IGNORECASE)
    )


def _parse_log_record(line: str) -> tuple[datetime | None, str | None, str]:
    match = re.match(
        r"^(?P<ts>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+(?P<level>\w+)\s+\[(?P<source>[^\]]+)\]\s*(?P<message>.*)$",
        line,
    )
    if match:
        try:
            local_tz = datetime.now().astimezone().tzinfo
            parsed_time = datetime.strptime(match.group("ts"), "%Y-%m-%d %H:%M:%S").replace(tzinfo=local_tz).astimezone(timezone.utc)
        except ValueError:
            parsed_time = None
        source = match.group("source").split(".")[-1]
        return parsed_time, source, match.group("message").strip()

    match = re.match(r"^(?P<level>BRIEF|INFO|WARNING|ERROR|DETAIL)\s+(?P<message>.*)$", line)
    if match:
        return None, match.group("level").lower(), match.group("message").strip()
    return None, None, line


def _record_time_sort_key(record: dict[str, object]) -> float:
    value = record.get("time")
    if isinstance(value, datetime):
        return value.timestamp()
    return 0.0


def _build_progress_events(log_records: list[dict[str, object]]) -> list[TaskRunProgressEvent]:
    events: list[TaskRunProgressEvent] = []
    for record in log_records:
        raw_message = _coerce_str(record.get("message")) or _coerce_str(record.get("raw")) or ""
        event = _event_from_log_message(
            raw_message,
            time=record.get("time") if isinstance(record.get("time"), datetime) else None,
            source=_coerce_str(record.get("source")),
        )
        if event is not None:
            events.append(event)

    deduped: list[TaskRunProgressEvent] = []
    seen: set[tuple[str, str, str | None]] = set()
    for event in events:
        key = (event.event_type, event.message, event.source)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(event)
    return deduped


def _select_response_events(events: list[TaskRunProgressEvent], *, max_recent: int = 80, max_important: int = 40) -> list[TaskRunProgressEvent]:
    important_types = {"model_fit_started", "model_fit_completed", "validation_metric", "search_iteration"}
    important_keys = {
        (event.event_type, event.message, event.source)
        for event in [event for event in events if event.event_type in important_types][-max_important:]
    }
    recent_keys = {(event.event_type, event.message, event.source) for event in events[-max_recent:]}
    selected_keys = important_keys | recent_keys
    merged: list[TaskRunProgressEvent] = []
    seen: set[tuple[str, str, str | None]] = set()
    for event in events:
        key = (event.event_type, event.message, event.source)
        if key not in selected_keys:
            continue
        if key in seen:
            continue
        seen.add(key)
        merged.append(event)
    return merged[-(max_recent + max_important):]


def _build_observer_insights(
    *,
    log_records: list[dict[str, object]],
    leaderboard: list[TaskRunProgressLeaderboardRow],
    training_metrics: list[TaskRunProgressTrainingMetric],
    artifacts: TaskRunProgressArtifactSummary,
    realtime_signals: dict[str, object],
    task_status: TaskStatus,
    stale: bool,
    stale_reason: str | None,
    repair_blocked: bool = False,
    terminal_state: str | None = None,
    task_notes: str | None = None,
) -> list[TaskRunProgressInsight]:
    insights: list[TaskRunProgressInsight] = []
    active_model: str | None = None
    active_stage: WorkflowStage | None = None

    for record in log_records:
        raw_message = _coerce_str(record.get("message")) or _coerce_str(record.get("raw")) or ""
        if not raw_message or _is_internal_runtime_noise(raw_message):
            continue
        message = _strip_log_prefix(raw_message)
        lowered = message.lower()
        record_time = record.get("time") if isinstance(record.get("time"), datetime) else None
        source = _coerce_str(record.get("source"))
        inferred_stage = _infer_stage_from_log_message(message, source=source, active_stage=active_stage)
        if inferred_stage is not None:
            active_stage = inferred_stage

        iteration = re.search(r"starting mcts iteration\s+(\d+)\s*/\s*(\d+)", message, flags=re.IGNORECASE)
        if iteration:
            insights.append(_make_insight(
                time=record_time,
                stage=WorkflowStage.feature_engineering,
                event_type="search_iteration",
                headline=f"正在进行第 {iteration.group(1)}/{iteration.group(2)} 轮方案搜索",
                detail="系统正在评估或扩展新的候选建模方案。",
                evidence=message,
                source=source,
            ))
            continue

        fit_count = re.search(r"Fitting\s+(\d+)\s+L(\d+)\s+models", message, flags=re.IGNORECASE)
        if fit_count:
            insights.append(_make_insight(
                time=record_time,
                stage=WorkflowStage.training_validation,
                event_type="model_batch_planned",
                headline=f"系统规划了 {fit_count.group(1)} 个 L{fit_count.group(2)} 候选模型",
                detail="后续会按候选模型级 fit 开始/完成事件推进。",
                evidence=message,
                source=source,
            ))
            continue

        fit_model = re.search(r"Fitting model:\s*([A-Za-z0-9_./-]+)(?P<rest>.*)", message, flags=re.IGNORECASE)
        if fit_model:
            active_model = fit_model.group(1).strip(" .,:;")
            rest = fit_model.group("rest") or ""
            budget_match = re.search(r"up to\s+(\d+(?:\.\d+)?)s", rest, flags=re.IGNORECASE)
            budget = _coerce_float(budget_match.group(1)) if budget_match else None
            insights.append(_make_insight(
                time=record_time,
                stage=WorkflowStage.training_validation,
                event_type="model_fit_started",
                headline=f"开始训练候选模型 {active_model}",
                detail=f"该模型的本轮时间预算约 {_format_seconds_for_activity(budget)}。" if budget is not None else "等待该模型写出候选排序分或训练耗时。",
                evidence=message,
                source=source,
            ))
            continue

        training_runtime = _parse_training_runtime_seconds(message)
        if training_runtime is not None:
            headline = f"候选模型 {active_model} 训练完成" if active_model else "候选模型训练完成"
            insights.append(_make_insight(
                time=record_time,
                stage=WorkflowStage.training_validation,
                event_type="model_fit_completed",
                headline=headline,
                detail=f"真实训练耗时 {_format_seconds_for_activity(training_runtime)}。",
                evidence=message,
                source=source,
                severity="success",
            ))
            continue

        validation_score = _parse_validation_score(message)
        if validation_score is not None:
            insights.append(_make_insight(
                time=record_time,
                stage=WorkflowStage.training_validation,
                event_type="validation_metric",
                headline="收到候选模型排序分",
                detail=f"候选排序分 {validation_score:.6g}。",
                evidence=message,
                source=source,
                severity="success",
            ))
            continue

        if "autogluon training complete" in lowered:
            best_match = re.search(r"Best model:\s*([A-Za-z0-9_./-]+)", message, flags=re.IGNORECASE)
            insights.append(_make_insight(
                time=record_time,
                stage=WorkflowStage.training_validation,
                event_type="training_complete",
                headline="训练流程完成",
                detail=f"最佳模型 {best_match.group(1)}。" if best_match else "等待结果文件同步。",
                evidence=message,
                source=source,
                severity="success",
            ))
            continue

        if "saved leaderboard" in lowered or "leaderboard" in lowered and "saved" in lowered:
            insights.append(_make_insight(
                time=record_time,
                stage=WorkflowStage.report_generation,
                event_type="leaderboard_written",
                headline="已写入候选模型对比",
                detail="可以查看各候选模型的候选排序分和训练耗时。",
                evidence=message,
                source=source,
                severity="success",
            ))
            continue

        if "saved run summary" in lowered or "run_summary" in lowered and "saved" in lowered:
            insights.append(_make_insight(
                time=record_time,
                stage=WorkflowStage.report_generation,
                event_type="summary_written",
                headline="已写入运行摘要",
                detail="run_summary 记录了最佳模型、指标和值。",
                evidence=message,
                source=source,
                severity="success",
            ))
            continue

        if "analyzing folder" in lowered or "reading file" in lowered or "grouped into" in lowered:
            insights.append(_make_insight(
                time=record_time,
                stage=WorkflowStage.data_analysis,
                event_type="data_scan",
                headline="正在扫描输入数据和任务文件",
                detail="运行器正在读取 CSV、描述文件或输入目录结构。",
                evidence=message,
                source=source,
            ))
            continue

        if "coderagent" in lowered or "python_coder" in lowered or "code-generation" in lowered or "python_code.py" in lowered:
            insights.append(_make_insight(
                time=record_time,
                stage=WorkflowStage.feature_engineering,
                event_type="code_generation",
                headline="正在生成训练脚本",
                detail="系统正在把任务要求转换成可执行 Python 训练代码。",
                evidence=message,
                source=source,
            ))
            continue

        if "executeragent" in lowered or "executing code" in lowered:
            insights.append(_make_insight(
                time=record_time,
                stage=WorkflowStage.training_validation,
                event_type="code_execution",
                headline="正在执行候选训练脚本",
                detail="系统正在运行生成代码并收集输出信息。",
                evidence=message,
                source=source,
            ))
            continue

        if "error" in lowered or "traceback" in lowered or "failed" in lowered:
            error_stage = inferred_stage or active_stage
            if source == "mlzero_stderr.log" and ("apitimeouterror" in lowered or "retryerror" in lowered):
                continue
            if not _is_meaningful_runtime_error(message):
                continue
            timeout_attempt = re.search(r"Attempt\s+(\d+)\s+failed:\s*APITimeoutError", message, flags=re.IGNORECASE)
            if timeout_attempt:
                stage_text = _stage_short_label(error_stage)
                insights.append(_make_insight(
                    time=record_time,
                    stage=error_stage,
                    event_type="llm_timeout",
                    headline=f"{stage_text} LLM 请求超时",
                    detail=f"第 {timeout_attempt.group(1)} 次请求超时，当前阶段还没有拿到模型返回。",
                    evidence=message,
                    source=source,
                    severity="warning",
                ))
                continue
            if "apitimeouterror" in lowered and "request timed out" in lowered:
                stage_text = _stage_short_label(error_stage)
                insights.append(_make_insight(
                    time=record_time,
                    stage=error_stage,
                    event_type="llm_timeout",
                    headline=f"{stage_text} LLM 请求超时",
                    detail="底层模型请求超时，当前阶段还没有拿到模型返回。",
                    evidence=message,
                    source=source,
                    severity="warning",
                ))
                continue
            if "retryerror" in lowered and "apitimeouterror" in lowered:
                stage_text = _stage_short_label(error_stage)
                insights.append(_make_insight(
                    time=record_time,
                    stage=error_stage,
                    event_type="llm_timeout_exhausted",
                    headline=f"{stage_text} 因 LLM 连续超时中断",
                    detail="底层模型多次请求超时，当前候选步骤未能继续生成代码或结果文件。",
                    evidence=message,
                    source=source,
                    severity="danger",
                ))
                continue
            insights.append(_make_insight(
                time=record_time,
                stage=error_stage,
                event_type="error",
                headline="运行器报告错误",
                detail=_short_observer_text(message, 180),
                evidence=message,
                source=source,
                severity="danger",
            ))

    if training_metrics:
        latest_metric = training_metrics[-1]
        metric_parts = []
        if latest_metric.epoch is not None:
            metric_parts.append(f"epoch {latest_metric.epoch}/{latest_metric.total_epochs or '?'}")
        if latest_metric.train_loss is not None:
            metric_parts.append(f"train loss {latest_metric.train_loss:.6g}")
        if latest_metric.validation_loss is not None:
            metric_parts.append(f"val loss {latest_metric.validation_loss:.6g}")
        if latest_metric.validation_score is not None:
            metric_parts.append(f"score {latest_metric.validation_score:.6g}")
        insights.append(_make_insight(
            time=latest_metric.time,
            stage=WorkflowStage.training_validation,
            event_type="training_metric",
            headline=f"收到 {latest_metric.model or '模型'} 的训练指标",
            detail=" · ".join(metric_parts) or "底层训练代码写出了 telemetry 指标。",
            evidence=None,
            source=latest_metric.source,
            severity="success",
        ))

    if leaderboard:
        best_row = leaderboard[0]
        score_text = f"，候选排序分 {best_row.validation_score:.6g}" if best_row.validation_score is not None else ""
        insights.append(_make_insight(
            time=None,
            stage=WorkflowStage.training_validation,
            event_type="leaderboard_available",
            headline=f"候选模型对比已可用，当前最佳 {best_row.model}",
            detail=f"已解析 {len(leaderboard)} 个候选模型{score_text}。",
            evidence=artifacts.leaderboard_path,
            source="候选模型对比",
            severity="success",
        ))

    current_model = _coerce_str(realtime_signals.get("current_model"))
    completed_count = _coerce_int(realtime_signals.get("completed_model_count"))
    total_count = _coerce_int(realtime_signals.get("total_model_count"))
    if current_model and not leaderboard and task_status == TaskStatus.running:
        elapsed = _coerce_float(realtime_signals.get("current_model_elapsed_seconds"))
        budget = _coerce_float(realtime_signals.get("current_model_time_budget_seconds"))
        count_text = f"，候选进度 {completed_count or 0}/{total_count or '?'}" if completed_count is not None or total_count is not None else ""
        budget_text = f"，预算 {_format_seconds_for_activity(budget)}" if budget is not None else ""
        elapsed_text = f"已耗时 {_format_seconds_for_activity(elapsed)}" if elapsed is not None else "等待训练耗时更新"
        insights.append(_make_insight(
            time=None,
            stage=WorkflowStage.training_validation,
            event_type="current_model_watch",
            headline=f"正在观察候选模型 {current_model}",
            detail=f"{elapsed_text}{budget_text}{count_text}。",
            evidence=None,
            source="runtime_observer",
        ))

    if stale:
        insights.append(_make_insight(
            time=None,
            stage=None,
            event_type="stale",
            headline="运行目录长时间没有更新",
            detail=stale_reason or "没有观察到新的日志或生成文件写入。",
            evidence=None,
            source="runtime_observer",
            severity="warning",
        ))

    if task_status == TaskStatus.running and terminal_state == "max_iterations":
        insights.append(_make_insight(
            time=None,
            stage=WorkflowStage.training_validation,
            event_type="mlzero_max_iterations",
            headline="已达到最大搜索轮次",
            detail="搜索已经结束，但任务仍标记为运行中；系统会把它收口为自动处理受阻并保留结果目录。",
            evidence=None,
            source="runtime_observer",
            severity="warning",
        ))

    if task_status == TaskStatus.running and terminal_state == "interrupted":
        insights.append(_make_insight(
            time=None,
            stage=None,
            event_type="mlzero_interrupted",
            headline="自动建模进程已被中断",
            detail="日志中出现 KeyboardInterrupt；这不是训练耗时过长，而是运行进程被中断，系统会保留结果目录并收口为自动处理受阻。",
            evidence=None,
            source="runtime_observer",
            severity="warning",
        ))

    if repair_blocked:
        blocked_stage = _coerce_stage(realtime_signals.get("current_stage")) or active_stage
        insights.append(_make_insight(
            time=None,
            stage=blocked_stage,
            event_type="agent_repair_blocked",
            headline="自动修复受阻",
            detail=task_notes or "系统判断这是可恢复问题，已保留结果目录，等待重新运行继续修复。",
            evidence=None,
            source="runtime_observer",
            severity="warning",
        ))

    if not insights:
        insights.append(_make_insight(
            time=None,
            stage=None,
            event_type="waiting_signal",
            headline="暂未收到可解释信号",
            detail="当前没有解析到模型训练、搜索轮次、候选模型对比、训练指标或生成文件事件；会继续轮询输出信息与结果目录。",
            evidence=None,
            source="runtime_observer",
            severity="warning" if task_status == TaskStatus.running else "info",
        ))

    return _dedupe_insights(insights)


def _make_insight(
    *,
    time: datetime | None,
    stage: WorkflowStage | None,
    event_type: str,
    headline: str,
    detail: str,
    evidence: str | None,
    source: str | None,
    severity: str = "info",
) -> TaskRunProgressInsight:
    normalized_severity = severity if severity in {"info", "success", "warning", "danger"} else "info"
    return TaskRunProgressInsight(
        time=time,
        stage=stage,
        event_type=event_type,
        headline=_short_observer_text(headline, 120),
        detail=_short_observer_text(detail, 240),
        evidence=_short_observer_text(evidence, 260) if evidence else None,
        source=source,
        severity=normalized_severity,  # type: ignore[arg-type]
    )


def _dedupe_insights(insights: list[TaskRunProgressInsight]) -> list[TaskRunProgressInsight]:
    deduped: list[TaskRunProgressInsight] = []
    seen: set[tuple[str, str, str]] = set()
    for insight in insights:
        key = (insight.event_type, insight.headline, insight.detail)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(insight)
    return deduped


def _resolve_observer_state(insights: list[TaskRunProgressInsight]) -> tuple[str | None, str | None, WorkflowStage | None]:
    if not insights:
        return None, None, None
    latest = insights[-1]
    latest_stage = latest.stage or next((insight.stage for insight in reversed(insights) if insight.stage is not None), None)
    return latest.headline, latest.detail or None, latest_stage


def _short_observer_text(value: str | None, max_length: int) -> str:
    if not value:
        return ""
    text = re.sub(r"\s+", " ", str(value)).strip()
    if _looks_like_raw_runtime_text(text):
        return "系统已隐藏原始运行日志；请查看诊断结论或报错文件。"
    return text if len(text) <= max_length else f"{text[:max_length - 3]}..."


def _looks_like_raw_runtime_text(value: str) -> bool:
    lowered = value.lower()
    if any(marker in lowered for marker in RAW_RUNTIME_MARKERS):
        return True
    if re.search(r"[a-z]:\\[^ ]{10,}", lowered):
        return True
    if len(value) > 420 and any(marker in lowered for marker in (" brief ", " info ", " warning ", "autogluon", "mlzero")):
        return True
    return False


def _infer_stage_from_log_message(
    message: str,
    *,
    source: str | None,
    active_stage: WorkflowStage | None,
) -> WorkflowStage | None:
    lowered = message.lower()
    source_lowered = (source or "").lower()
    if any(marker in lowered for marker in ("analyzing folder", "reading file", "grouped into", "data perception", "error reading file")):
        return WorkflowStage.data_analysis
    if any(marker in lowered for marker in ("taskdescriptoragent", "toolselectoragent", "retrieveragent", "rerankeragent", "tutorial")):
        return WorkflowStage.model_selection
    if any(marker in lowered for marker in ("starting mcts iteration", "coderagent", "python_coder", "code-generation", "python code generation", "python_coder_prompt")):
        return WorkflowStage.feature_engineering
    if any(marker in lowered for marker in ("executeragent", "executing code", "training runtime", "validation score", "fitting model:")):
        return WorkflowStage.training_validation
    if any(marker in lowered for marker in ("leaderboard", "run_summary", "output saved")):
        return WorkflowStage.report_generation
    if "base_chat" in source_lowered and ("apitimeouterror" in lowered or "request timed out" in lowered):
        return active_stage
    return None


def _stage_short_label(stage: WorkflowStage | None) -> str:
    if stage == WorkflowStage.requirement_analysis:
        return "需求解析阶段"
    if stage == WorkflowStage.data_analysis:
        return "数据分析阶段"
    if stage == WorkflowStage.feature_engineering:
        return "代码生成阶段"
    if stage == WorkflowStage.model_selection:
        return "模型选择阶段"
    if stage == WorkflowStage.training_validation:
        return "训练验证阶段"
    if stage == WorkflowStage.report_generation:
        return "报告生成阶段"
    return "当前阶段"


def _is_meaningful_runtime_error(message: str) -> bool:
    stripped = message.strip()
    lowered = stripped.lower()
    if "apitimeouterror" in lowered and "request timed out" not in lowered and "attempt " not in lowered:
        return False
    if "retryerror" in lowered and "apitimeouterror" not in lowered:
        return False
    if "traceback" in lowered:
        return False
    if any(marker in lowered for marker in ("apitimeouterror", "retryerror", "modulenotfounderror", "error reading file", "attempt ")):
        return True
    if not any(marker in lowered for marker in ("error", "failed", "traceback")):
        return False
    if stripped.startswith(("│", "┃", "╭", "╰", "└", "├", "─")):
        return False
    if re.match(r"^(File|Traceback \(most recent call last\)|During handling of the above exception)", stripped):
        return False
    if re.match(r"^[\w.\\/: -]+\.py:\d+\s+in\s+", stripped):
        return False
    return len(stripped) >= 12


def _event_from_log_message(message: str, *, time: datetime | None, source: str | None) -> TaskRunProgressEvent | None:
    lower = message.lower()
    if _looks_like_raw_runtime_text(message):
        if "failed" in lower or "error" in lower or "return code:" in lower or "mlzero run failed" in lower:
            return TaskRunProgressEvent(
                time=time,
                stage=None,
                event_type="error",
                message="系统已隐藏原始运行日志；请查看诊断结论或报错文件。",
                source=source,
            )
        return None
    iteration = re.search(r"starting mcts iteration\s+(\d+)\s*/\s*(\d+)", message, flags=re.IGNORECASE)
    if iteration:
        return TaskRunProgressEvent(
            time=time,
            stage=WorkflowStage.feature_engineering,
            event_type="search_iteration",
            message=f"开始第 {iteration.group(1)}/{iteration.group(2)} 轮方案搜索。",
            source=source,
        )

    fit_model = re.search(r"fitting model:\s*([A-Za-z0-9_./-]+)", message, flags=re.IGNORECASE)
    if fit_model:
        return TaskRunProgressEvent(
            time=time,
            stage=WorkflowStage.training_validation,
            event_type="model_fit_started",
            message=f"开始训练候选模型 {fit_model.group(1)}。",
            source=source,
        )

    runtime = re.search(r"=\s*Training\s+runtime", message, flags=re.IGNORECASE)
    if runtime:
        return TaskRunProgressEvent(
            time=time,
            stage=WorkflowStage.training_validation,
            event_type="model_fit_completed",
            message=message,
            source=source,
        )

    if "analyzing folder" in lower or "reading file" in lower or "grouped into" in lower:
        return TaskRunProgressEvent(time=time, stage=WorkflowStage.data_analysis, event_type="data_scan", message=message, source=source)

    if "retrieveragent" in lower or "rerankeragent" in lower or "tutorial" in lower:
        return TaskRunProgressEvent(time=time, stage=WorkflowStage.model_selection, event_type="knowledge_retrieval", message=message, source=source)

    if "coderagent" in lower or "python_coder" in lower or "code-generation" in lower or "python_code.py" in lower:
        return TaskRunProgressEvent(time=time, stage=WorkflowStage.feature_engineering, event_type="code_generation", message=message, source=source)

    if "executeragent" in lower or "executing code" in lower:
        return TaskRunProgressEvent(time=time, stage=WorkflowStage.training_validation, event_type="code_execution", message=message, source=source)

    if "validation score" in lower:
        return TaskRunProgressEvent(time=time, stage=WorkflowStage.training_validation, event_type="validation_metric", message=message, source=source)

    if "planner decision" in lower:
        return TaskRunProgressEvent(time=time, stage=WorkflowStage.training_validation, event_type="planner_decision", message=message, source=source)

    if "task completed successfully" in lower or "best node" in lower:
        return TaskRunProgressEvent(time=time, stage=WorkflowStage.training_validation, event_type="candidate_completed", message=message, source=source)

    if "leaderboard" in lower or "run_summary" in lower or "output saved" in lower:
        return TaskRunProgressEvent(time=time, stage=WorkflowStage.report_generation, event_type="artifact_written", message=message, source=source)

    if "http request: post" in lower or "using openai model" in lower:
        return TaskRunProgressEvent(time=time, stage=WorkflowStage.requirement_analysis, event_type="llm_call", message=message, source=source)

    if "error" in lower or "traceback" in lower or "failed" in lower:
        return TaskRunProgressEvent(time=time, stage=None, event_type="error", message=message, source=source)

    return None


def _read_leaderboard_rows(path_value: str | None) -> list[TaskRunProgressLeaderboardRow]:
    if not path_value:
        return []
    path = Path(path_value)
    if not path.exists():
        return []
    try:
        if path.suffix.lower() == ".json":
            payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
            if isinstance(payload, list):
                raw_rows = payload
            elif isinstance(payload, dict) and isinstance(payload.get("leaderboard"), list):
                raw_rows = payload["leaderboard"]
            else:
                raw_rows = []
        else:
            with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
                raw_rows = list(csv.DictReader(handle))
    except (OSError, json.JSONDecodeError, csv.Error):
        return []

    rows: list[TaskRunProgressLeaderboardRow] = []
    for index, raw_row in enumerate(raw_rows, start=1):
        if not isinstance(raw_row, dict):
            continue
        model = _coerce_str(raw_row.get("model") or raw_row.get("model_name") or raw_row.get("name"))
        if not model:
            continue
        rows.append(
            TaskRunProgressLeaderboardRow(
                model=model,
                validation_score=_coerce_float(raw_row.get("validation_score") or raw_row.get("score_val") or raw_row.get("score")),
                fit_time=_coerce_float(raw_row.get("fit_time") or raw_row.get("fit_time_marginal")),
                pred_time=_coerce_float(raw_row.get("pred_time") or raw_row.get("pred_time_val") or raw_row.get("pred_time_marginal")),
                rank=_coerce_int(raw_row.get("rank")) or index,
            )
        )
    return sorted(rows, key=lambda row: row.rank or 999999)


def _read_training_metrics(output_dir: Path) -> list[TaskRunProgressTrainingMetric]:
    metric_paths: list[Path] = []
    telemetry_dir = output_dir / "telemetry"
    if telemetry_dir.exists():
        try:
            metric_paths.extend(path for path in telemetry_dir.iterdir() if path.is_file() and path.suffix.lower() in {".ndjson", ".jsonl", ".json"})
        except OSError:
            pass
    for node_dir in _recent_node_dirs(output_dir):
        for relative in (
            Path("telemetry") / "training_metrics.ndjson",
            Path("output") / "training_metrics.ndjson",
            Path("output") / "training_metrics.jsonl",
            Path("output") / "training_metrics.json",
        ):
            path = node_dir / relative
            if path.exists():
                metric_paths.append(path)

    metrics: list[TaskRunProgressTrainingMetric] = []
    for path in sorted({path for path in metric_paths if path.is_file()}, key=_path_mtime):
        metrics.extend(_read_training_metric_file(path))
    return metrics


def _read_training_metric_file(path: Path) -> list[TaskRunProgressTrainingMetric]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    records: list[object] = []
    if path.suffix.lower() == ".json":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, list):
            records = payload
        elif isinstance(payload, dict) and isinstance(payload.get("metrics"), list):
            records = payload["metrics"]
        elif isinstance(payload, dict):
            records = [payload]
    else:
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                records.append(json.loads(stripped))
            except json.JSONDecodeError:
                continue

    metrics: list[TaskRunProgressTrainingMetric] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        metrics.append(
            TaskRunProgressTrainingMetric(
                time=_coerce_datetime(record.get("time") or record.get("timestamp") or record.get("created_at")),
                model=_coerce_str(record.get("model") or record.get("model_name")),
                epoch=_coerce_int(record.get("epoch")),
                total_epochs=_coerce_int(record.get("total_epochs") or record.get("epochs")),
                iteration=_coerce_int(record.get("iteration") or record.get("iter")),
                total_iterations=_coerce_int(record.get("total_iterations") or record.get("iterations")),
                train_loss=_coerce_float(record.get("train_loss") or record.get("loss")),
                validation_loss=_coerce_float(record.get("validation_loss") or record.get("val_loss")),
                validation_score=_coerce_float(record.get("validation_score") or record.get("score") or record.get("metric_value")),
                metric_name=_coerce_str(record.get("metric_name") or record.get("metric")),
                source=str(path),
            )
        )
    return metrics


def _derive_realtime_signals(
    *,
    log_records: list[dict[str, object]],
    events: list[TaskRunProgressEvent],
    leaderboard: list[TaskRunProgressLeaderboardRow],
    training_metrics: list[TaskRunProgressTrainingMetric],
    artifacts: TaskRunProgressArtifactSummary,
) -> dict[str, object]:
    signals: dict[str, object] = {}

    iteration_matches: list[tuple[int, int]] = []
    epoch_matches: list[tuple[int, int]] = []
    best_model_from_logs: str | None = None
    declared_model_count: int | None = None
    validation_scores: list[float] = []
    fit_sequence: list[dict[str, object]] = []
    for record in log_records:
        message = _coerce_str(record.get("message")) or _coerce_str(record.get("raw")) or ""
        record_time = record.get("time") if isinstance(record.get("time"), datetime) else None
        has_real_timestamp = not bool(record.get("time_is_fallback"))
        fit_count = re.search(r"Fitting\s+(\d+)\s+L\d+\s+models", message, flags=re.IGNORECASE)
        if fit_count:
            declared_model_count = int(fit_count.group(1))
        fit_model = re.search(r"Fitting model:\s*([A-Za-z0-9_./-]+)(?P<rest>.*)", message, flags=re.IGNORECASE)
        if fit_model:
            rest = fit_model.group("rest") or ""
            budget_match = re.search(r"up to\s+(\d+(?:\.\d+)?)s", rest, flags=re.IGNORECASE)
            fit_sequence.append(
                {
                    "model": fit_model.group(1).strip(" .,:;"),
                    "started_at": record_time if has_real_timestamp else None,
                    "time_budget_seconds": _coerce_float(budget_match.group(1)) if budget_match else None,
                }
            )
        iteration = re.search(r"starting mcts iteration\s+(\d+)\s*/\s*(\d+)", message, flags=re.IGNORECASE)
        if iteration:
            iteration_matches.append((int(iteration.group(1)), int(iteration.group(2))))
        epoch = re.search(r"\bepoch\s+(\d+)\s*/\s*(\d+)", message, flags=re.IGNORECASE)
        if epoch:
            epoch_matches.append((int(epoch.group(1)), int(epoch.group(2))))
        best_model_match = re.search(r"Best model:\s*([A-Za-z0-9_./-]+)", message, flags=re.IGNORECASE)
        if best_model_match:
            best_model_from_logs = best_model_match.group(1).strip(" .,:;")
        validation_score = _parse_validation_score(message)
        if validation_score is not None:
            validation_scores.append(validation_score)
            if fit_sequence:
                fit_sequence[-1]["validation_score"] = validation_score
        training_runtime = _parse_training_runtime_seconds(message)
        if training_runtime is not None and fit_sequence:
            target_fit = next((item for item in reversed(fit_sequence) if item.get("fit_time_seconds") is None), fit_sequence[-1])
            target_fit["fit_time_seconds"] = training_runtime
            target_fit["completed_at"] = record_time if has_real_timestamp else None

    if iteration_matches:
        current_iteration, total_iterations = iteration_matches[-1]
        signals["current_iteration"] = current_iteration
        signals["total_iterations"] = total_iterations
        signals["current_stage"] = WorkflowStage.feature_engineering
        if total_iterations > 0:
            signals["progress_percent"] = min(94, max(12, int((current_iteration - 1) / total_iterations * 100)))

    if epoch_matches:
        current_epoch, total_epochs = epoch_matches[-1]
        signals["current_epoch"] = current_epoch
        signals["total_epochs"] = total_epochs
        if total_epochs > 0:
            signals["progress_percent"] = max(int(current_epoch / total_epochs * 100), int(signals.get("progress_percent") or 0))

    if training_metrics:
        latest_metric = training_metrics[-1]
        signals["current_model"] = latest_metric.model
        signals["current_epoch"] = latest_metric.epoch
        signals["total_epochs"] = latest_metric.total_epochs
        signals["latest_train_loss"] = latest_metric.train_loss
        signals["latest_validation_loss"] = latest_metric.validation_loss
        signals["latest_validation_score"] = latest_metric.validation_score
        if latest_metric.iteration is not None:
            signals["current_iteration"] = latest_metric.iteration
        if latest_metric.total_iterations is not None:
            signals["total_iterations"] = latest_metric.total_iterations
    else:
        active_fit = next((item for item in reversed(fit_sequence) if item.get("fit_time_seconds") is None), None)
        latest_fit = fit_sequence[-1] if fit_sequence else None
        display_fit = active_fit or latest_fit
        if display_fit is not None:
            signals["current_model"] = _coerce_str(display_fit.get("model"))
            started_at = display_fit.get("started_at")
            if isinstance(started_at, datetime):
                signals["current_model_started_at"] = started_at
            fit_time_seconds = _coerce_float(display_fit.get("fit_time_seconds"))
            if active_fit is not None and isinstance(started_at, datetime):
                signals["current_model_elapsed_seconds"] = max((datetime.now(timezone.utc) - started_at).total_seconds(), 0.0)
            elif fit_time_seconds is not None:
                signals["current_model_elapsed_seconds"] = fit_time_seconds
            time_budget_seconds = _coerce_float(display_fit.get("time_budget_seconds"))
            if time_budget_seconds is not None:
                signals["current_model_time_budget_seconds"] = time_budget_seconds
        elif best_model_from_logs:
            signals["current_model"] = best_model_from_logs

    if validation_scores:
        signals["latest_validation_score"] = validation_scores[-1]
    elif leaderboard and leaderboard[0].validation_score is not None:
        signals["latest_validation_score"] = leaderboard[0].validation_score

    completed_from_logs = len([item for item in fit_sequence if item.get("fit_time_seconds") is not None])
    completed_candidates = max(
        [
            value
            for value in (
                len(leaderboard) if leaderboard else None,
                completed_from_logs or None,
                len([event for event in events if event.event_type == "candidate_completed"]) or None,
            )
            if value is not None
        ],
        default=None,
    )
    signals["completed_model_count"] = completed_candidates
    total_candidates = max(
        [
            value
            for value in (
                artifacts.candidate_model_count,
                len(leaderboard) if leaderboard else None,
                declared_model_count,
                len(fit_sequence) or None,
            )
            if value is not None
        ],
        default=None,
    )
    signals["total_model_count"] = total_candidates
    if completed_candidates is not None and total_candidates:
        signals["progress_percent"] = max(
            int(signals.get("progress_percent") or 0),
            min(95, int(completed_candidates / total_candidates * 100)),
        )

    latest_event = events[-1] if events else None
    latest_stage_event = next((event for event in reversed(events) if event.stage is not None), None)
    if latest_stage_event is not None:
        signals["current_stage"] = latest_stage_event.stage
    if latest_event is not None:
        signals["current_activity"] = latest_event.message

    if leaderboard:
        best_row = leaderboard[0]
        signals["current_stage"] = WorkflowStage.training_validation
        signals["current_model"] = signals.get("current_model") or best_row.model
        if artifacts.has_run_summary and artifacts.has_leaderboard:
            metric_name = artifacts.metric_name or "validation_score"
            metric_value = artifacts.metric_value if artifacts.metric_value is not None else best_row.validation_score
            if metric_value is not None:
                signals["current_activity"] = f"已产出实时候选模型对比：当前最佳 {best_row.model}，{metric_name} = {metric_value:.6g}。"
    elif fit_sequence:
        active_fit = next((item for item in reversed(fit_sequence) if item.get("fit_time_seconds") is None), None)
        latest_fit = fit_sequence[-1]
        display_fit = active_fit or latest_fit
        model_name = _coerce_str(display_fit.get("model")) or "未识别模型"
        elapsed = _coerce_float(signals.get("current_model_elapsed_seconds"))
        elapsed_text = f"，当前模型已耗时 {_format_seconds_for_activity(elapsed)}" if active_fit is not None and elapsed is not None else ""
        fit_time = _coerce_float(display_fit.get("fit_time_seconds"))
        fit_time_text = f"，训练用时 {_format_seconds_for_activity(fit_time)}" if active_fit is None and fit_time is not None else ""
        budget = _coerce_float(display_fit.get("time_budget_seconds"))
        budget_text = f"，时间预算 {_format_seconds_for_activity(budget)}" if budget is not None else ""
        completed_text = ""
        if completed_candidates is not None or total_candidates is not None:
            completed_text = f"，已完成 {completed_candidates or 0}/{total_candidates or '?'} 个候选模型"
        signals["current_stage"] = WorkflowStage.training_validation
        if active_fit is not None:
            signals["current_activity"] = (
                f"正在训练候选模型 {model_name}{elapsed_text}{budget_text}{completed_text}。"
                "RF/KNN/ExtraTrees 这类模型没有 epoch/loss，进度以模型训练事件、心跳和候选模型对比为准。"
            )
        else:
            signals["current_activity"] = f"最近完成候选模型 {model_name}{fit_time_text}{completed_text}，等待下一条训练日志或候选模型对比。"

    if not training_metrics:
        signals["telemetry_note"] = (
            "当前运行还没有上报 epoch/loss 级训练指标；"
            "如果底层模型是 RandomForest、KNN、ExtraTrees 这类非 epoch 训练器，页面只能展示候选模型完成数、候选模型对比、日志和心跳。"
        )
    return signals


def _parse_training_runtime_seconds(message: str) -> float | None:
    match = re.search(r"(-?\d+(?:\.\d+)?)s\s*=\s*Training\s+runtime", message, flags=re.IGNORECASE)
    if not match:
        return None
    return _coerce_float(match.group(1))


def _parse_validation_score(message: str) -> float | None:
    value_pattern = r"(-?\d+(?:\.\d+)?(?:e[+-]?\d+)?)"
    match = re.search(rf"{value_pattern}\s*=\s*Validation\s+score", message, flags=re.IGNORECASE)
    if not match:
        match = re.search(rf"Validation\s+score(?:\s*\([^)]*\))?\s*[:=]\s*{value_pattern}", message, flags=re.IGNORECASE)
    if not match:
        return None
    return _coerce_float(match.group(1))


def _format_seconds_for_activity(value: float | None) -> str:
    if value is None:
        return "未知"
    if value < 60:
        return f"{value:.1f} 秒"
    minutes = int(value // 60)
    seconds = int(round(value % 60))
    return f"{minutes} 分 {seconds} 秒"


def _last_significant_line(lines: list[str]) -> str:
    for line in reversed(lines):
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _last_activity_line(lines: list[str]) -> str:
    for line in reversed(lines):
        stripped = line.strip()
        if stripped and not _is_internal_runtime_noise(stripped) and not _looks_like_raw_runtime_text(stripped):
            return stripped
    return ""


def _is_internal_runtime_noise(line: str) -> bool:
    stripped = _strip_log_prefix(line)
    lowered = stripped.lower()
    if len(stripped) > 500 and any(marker in lowered for marker in ("request options", "json_data", "messages", "chat/completions")):
        return True
    return any(
        marker in lowered
        for marker in (
            "request options:",
            "idempotency_key",
            "x-stainless",
            "json_data",
            "send_request_body.",
            "receive_response_headers.",
            "response_closed.",
            "httpcore.http11",
            "openai._base_client",
            "/chat/completions",
        )
    )


def _fallback_activity(current_stage: WorkflowStage | None, task_status: TaskStatus) -> str:
    if current_stage == WorkflowStage.requirement_analysis:
        return "需求解析阶段，等待更细运行信号。"
    if current_stage == WorkflowStage.data_analysis:
        return "数据分析阶段，等待字段画像或数据扫描信号。"
    if current_stage == WorkflowStage.feature_engineering:
        return "特征工程阶段，等待代码生成或方案搜索信号。"
    if current_stage == WorkflowStage.model_selection:
        return "模型选择阶段，等待候选方案或搜索轮次信号。"
    if current_stage == WorkflowStage.training_validation:
        return "正在执行训练验证，等待下一条模型日志或候选模型对比。"
    if current_stage == WorkflowStage.report_generation:
        return "正在整理结果文件。"
    if task_status == TaskStatus.running:
        return "等待下一条可解释运行信号。"
    return ""


def _strip_log_prefix(line: str) -> str:
    return re.sub(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\s+\w+\s+\[[^\]]+\]\s*", "", line).strip()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _coerce_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _coerce_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _coerce_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _coerce_stage(value: object) -> WorkflowStage | None:
    if isinstance(value, WorkflowStage):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return WorkflowStage(value.strip())
    except ValueError:
        return None


def _coerce_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return _as_utc(value)
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return _as_utc(parsed)
