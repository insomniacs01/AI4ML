from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from backend.app.models.task import (
    TaskCodeArtifactContentResponse,
    TaskCodeArtifactEntry,
    TaskCodeArtifactRerunRequest,
    TaskCodeArtifactRerunResponse,
    TaskCodeArtifactUpdateRequest,
    TaskCodeArtifactVersionRecord,
    TaskCodeWorkspaceResponse,
    TaskRecord,
)


TEXT_ARTIFACT_SUFFIXES = {
    ".py": "python",
    ".txt": "text",
    ".md": "markdown",
    ".json": "json",
    ".csv": "csv",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".log": "log",
    ".sh": "shell",
    ".ps1": "powershell",
    ".bat": "batch",
    ".sql": "sql",
}
TEXT_ARTIFACT_FILENAMES = {
    "stdout": "log",
    "stderr": "log",
}
EDITABLE_LANGUAGES = {"python", "shell", "powershell", "batch", "sql"}
MAX_ARTIFACT_SIZE_BYTES = 2 * 1024 * 1024
MAX_SAVE_SIZE_BYTES = 2 * 1024 * 1024
VERSION_MANIFEST_NAME = ".ai4ml_code_workspace_versions.json"
GROUP_ORDER = {
    "generation": 0,
    "result": 1,
    "log": 2,
    "context": 3,
    "other": 4,
}


@dataclass(frozen=True)
class ArtifactDescriptor:
    category: str
    group: str
    artifact_kind: str
    display_name: str
    purpose: str
    editing_guidance: str
    stage: str | None = None
    is_core: bool = False
    sort_priority: int = 999


def build_task_code_workspace(task: TaskRecord) -> TaskCodeWorkspaceResponse:
    warnings: list[str] = []
    requested_run_dir, existing_run_dir = _resolve_run_output_dir(task)

    if requested_run_dir is None:
        warnings.append("这个任务还没有 MLZero 运行产物，暂时没有可查看的 AI 代码。")
        return TaskCodeWorkspaceResponse(
            task_id=task.id,
            task_name=task.name,
            warnings=warnings,
            items=[],
        )

    if existing_run_dir is None:
        warnings.append(f"最新运行目录不存在：{requested_run_dir}")
        return TaskCodeWorkspaceResponse(
            task_id=task.id,
            task_name=task.name,
            run_output_dir=str(requested_run_dir),
            warnings=warnings,
            items=[],
        )

    items = _collect_workspace_entries(existing_run_dir)
    if not items:
        warnings.append("最新运行目录里没有可在前端展示的文本工件。")

    return TaskCodeWorkspaceResponse(
        task_id=task.id,
        task_name=task.name,
        run_output_dir=str(existing_run_dir),
        warnings=warnings,
        items=items,
    )


def read_task_code_artifact(task: TaskRecord, artifact_path: str) -> TaskCodeArtifactContentResponse:
    run_output_dir = _require_existing_run_output_dir(task)
    artifact = _resolve_artifact_path(run_output_dir, artifact_path)
    entry = _artifact_entry_from_path(run_output_dir, artifact)

    if entry is None:
        raise FileNotFoundError(f"Unsupported artifact type: {artifact_path}")
    if entry.size_bytes > MAX_ARTIFACT_SIZE_BYTES:
        raise RuntimeError(
            f"Artifact is too large to load in the browser ({entry.size_bytes} bytes). "
            f"Limit: {MAX_ARTIFACT_SIZE_BYTES} bytes."
        )

    return TaskCodeArtifactContentResponse(
        task_id=task.id,
        task_name=task.name,
        run_output_dir=str(run_output_dir),
        artifact=entry,
        content=artifact.read_text(encoding="utf-8", errors="replace"),
        version_history=_read_version_history(run_output_dir, relative_path=entry.path),
    )


def save_task_code_artifact(
    task: TaskRecord,
    payload: TaskCodeArtifactUpdateRequest,
) -> TaskCodeArtifactContentResponse:
    run_output_dir = _require_existing_run_output_dir(task)
    artifact = _resolve_artifact_path(run_output_dir, payload.path)
    entry = _artifact_entry_from_path(run_output_dir, artifact)

    if entry is None:
        raise FileNotFoundError(f"Unsupported artifact type: {payload.path}")
    if not entry.editable:
        raise PermissionError(f"Artifact is read-only: {payload.path}")

    encoded = payload.content.encode("utf-8")
    if len(encoded) > MAX_SAVE_SIZE_BYTES:
        raise RuntimeError(
            f"Updated artifact is too large to save ({len(encoded)} bytes). "
            f"Limit: {MAX_SAVE_SIZE_BYTES} bytes."
        )

    previous_hash = _sha256_file(artifact)
    artifact.write_text(payload.content, encoding="utf-8")
    next_hash = _sha256_file(artifact)
    refreshed_entry = _artifact_entry_from_path(run_output_dir, artifact)
    if refreshed_entry is None:
        raise RuntimeError(f"Saved artifact could not be reloaded: {payload.path}")
    version = _append_version_record(
        run_output_dir,
        relative_path=refreshed_entry.path,
        size_bytes=len(encoded),
        previous_sha256=previous_hash,
        sha256=next_hash,
    )

    return TaskCodeArtifactContentResponse(
        task_id=task.id,
        task_name=task.name,
        run_output_dir=str(run_output_dir),
        artifact=refreshed_entry,
        content=payload.content,
        version_id=version.version_id,
        version_history=_read_version_history(run_output_dir, relative_path=refreshed_entry.path),
    )


def resolve_task_code_artifact_file(task: TaskRecord, artifact_path: str) -> tuple[Path, TaskCodeArtifactEntry]:
    run_output_dir = _require_existing_run_output_dir(task)
    artifact = _resolve_artifact_path(run_output_dir, artifact_path)
    entry = _artifact_entry_from_path(run_output_dir, artifact)
    if entry is None:
        raise FileNotFoundError(f"Unsupported artifact type: {artifact_path}")
    return artifact, entry


def rerun_task_code_artifact(
    task: TaskRecord,
    payload: TaskCodeArtifactRerunRequest,
) -> TaskCodeArtifactRerunResponse:
    run_output_dir = _require_existing_run_output_dir(task)
    requested_path = payload.path or _find_default_rerun_path(run_output_dir)
    if not requested_path:
        raise FileNotFoundError("No generated_code.py artifact is available to rerun.")

    artifact = _resolve_artifact_path(run_output_dir, requested_path)
    entry = _artifact_entry_from_path(run_output_dir, artifact)
    if entry is None:
        raise FileNotFoundError(f"Unsupported artifact type: {requested_path}")
    if entry.language != "python":
        raise RuntimeError("Only Python code artifacts can be rerun from the code workspace.")
    if entry.category != "code":
        raise RuntimeError("Only code artifacts can be rerun from the code workspace.")

    started_at = datetime.now(timezone.utc)
    run_id = started_at.strftime("%Y%m%dT%H%M%SZ")
    log_dir = run_output_dir / "code_workspace_reruns"
    log_dir.mkdir(parents=True, exist_ok=True)
    safe_name = entry.path.replace("/", "__").replace("\\", "__")
    stdout_path = log_dir / f"{run_id}_{safe_name}.stdout.log"
    stderr_path = log_dir / f"{run_id}_{safe_name}.stderr.log"

    try:
        completed = subprocess.run(  # noqa: S603
            [sys.executable, str(artifact)],
            cwd=str(artifact.parent),
            capture_output=True,
            text=True,
            timeout=payload.time_limit_seconds,
            check=False,
        )
        stdout_path.write_text(completed.stdout or "", encoding="utf-8")
        stderr_path.write_text(completed.stderr or "", encoding="utf-8")
        exit_code = int(completed.returncode)
        success = exit_code == 0
        detail = "代码工作区工件已真实重跑完成。" if success else f"代码工作区工件重跑失败，退出码 {exit_code}。"
    except subprocess.TimeoutExpired as exc:
        stdout_path.write_text(exc.stdout or "", encoding="utf-8")
        stderr_path.write_text(exc.stderr or f"Rerun timed out after {payload.time_limit_seconds} seconds.", encoding="utf-8")
        exit_code = -1
        success = False
        detail = f"代码工作区工件重跑超时：{payload.time_limit_seconds} 秒。"

    finished_at = datetime.now(timezone.utc)
    version_history = _read_version_history(run_output_dir, relative_path=entry.path)
    latest_version = version_history[-1].version_id if version_history else None
    return TaskCodeArtifactRerunResponse(
        task_id=task.id,
        task_name=task.name,
        run_output_dir=str(run_output_dir),
        path=entry.path,
        success=success,
        exit_code=exit_code,
        detail=detail,
        stdout_path=str(stdout_path.relative_to(run_output_dir).as_posix()),
        stderr_path=str(stderr_path.relative_to(run_output_dir).as_posix()),
        version_id=latest_version,
        started_at=started_at,
        finished_at=finished_at,
    )


def _resolve_run_output_dir(task: TaskRecord) -> tuple[Path | None, Path | None]:
    if task.last_run_attempt and task.last_run_attempt.output_dir:
        requested_path = Path(task.last_run_attempt.output_dir)
    elif task.last_run and task.last_run.output_dir:
        requested_path = Path(task.last_run.output_dir)
    else:
        return None, None
    return requested_path, requested_path if requested_path.exists() else None


def _require_existing_run_output_dir(task: TaskRecord) -> Path:
    requested_run_dir, existing_run_dir = _resolve_run_output_dir(task)
    if requested_run_dir is None:
        raise RuntimeError("这个任务还没有 MLZero 运行产物。")
    if existing_run_dir is None:
        raise FileNotFoundError(f"Latest MLZero output directory is missing: {requested_run_dir}")
    return existing_run_dir


def _collect_workspace_entries(run_output_dir: Path) -> list[TaskCodeArtifactEntry]:
    entries: list[TaskCodeArtifactEntry] = []
    for path in sorted(run_output_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.name == VERSION_MANIFEST_NAME:
            continue
        if "best_run" in path.parts:
            continue
        entry = _artifact_entry_from_path(run_output_dir, path)
        if entry is not None:
            entries.append(entry)

    entries.sort(key=_entry_sort_key)
    return entries


def _artifact_entry_from_path(run_output_dir: Path, path: Path) -> TaskCodeArtifactEntry | None:
    language = _detect_artifact_language(path)
    if language is None:
        return None

    relative_path = path.relative_to(run_output_dir).as_posix()
    descriptor = _describe_artifact(relative_path, path.name)
    stats = path.stat()

    return TaskCodeArtifactEntry(
        path=relative_path,
        name=path.name,
        display_name=descriptor.display_name,
        purpose=descriptor.purpose,
        editing_guidance=descriptor.editing_guidance,
        category=descriptor.category,
        group=descriptor.group,
        artifact_kind=descriptor.artifact_kind,
        stage=descriptor.stage,
        node=_extract_node_name(relative_path),
        is_core=descriptor.is_core,
        recommended_order=descriptor.sort_priority,
        language=language,
        size_bytes=stats.st_size,
        editable=_is_editable_artifact(descriptor, language),
        updated_at=datetime.fromtimestamp(stats.st_mtime, tz=timezone.utc),
    )


def _detect_artifact_language(path: Path) -> str | None:
    filename_language = TEXT_ARTIFACT_FILENAMES.get(path.name.lower())
    if filename_language is not None:
        return filename_language
    return TEXT_ARTIFACT_SUFFIXES.get(path.suffix.lower())


def _is_editable_artifact(descriptor: ArtifactDescriptor, language: str) -> bool:
    if language not in EDITABLE_LANGUAGES:
        return False
    return descriptor.category == "code"


def _describe_artifact(relative_path: str, filename: str) -> ArtifactDescriptor:
    lowered_path = relative_path.lower()
    lowered_name = filename.lower()
    in_output_dir = "/output/" in f"/{lowered_path}"

    if lowered_name == "generated_code.py":
        return ArtifactDescriptor(
            category="code",
            group="generation",
            artifact_kind="generated_code",
            display_name="最终执行代码",
            purpose="这是当前节点最终真正执行的 Python 代码，最接近你想要直接修改的 AI 产物。",
            editing_guidance="建议优先编辑这个文件。保存后只会写回本次运行目录，不会自动重跑。",
            stage="final_code",
            is_core=True,
            sort_priority=0,
        )

    if lowered_name == "python_code.py":
        return ArtifactDescriptor(
            category="code",
            group="generation",
            artifact_kind="python_draft",
            display_name="Python 草稿代码",
            purpose="这是 Python coder 阶段整理出的代码草稿，通常是最终执行代码的上游版本。",
            editing_guidance="适合对照 AI 的中间稿；如果要改最终行为，记得同时核对 generated_code.py。",
            stage="python_draft",
            is_core=True,
            sort_priority=1,
        )

    if lowered_name == "execution_script.sh":
        return ArtifactDescriptor(
            category="code",
            group="generation",
            artifact_kind="execution_script",
            display_name="执行脚本",
            purpose="这是把当前节点代码真正跑起来的 shell 脚本，用来组织命令行参数和运行入口。",
            editing_guidance="通常只有运行入口、命令参数或环境问题需要排查时才需要修改它。",
            stage="execution",
            is_core=True,
            sort_priority=2,
        )

    if lowered_name == "extracted_bash_script.sh":
        return ArtifactDescriptor(
            category="code",
            group="generation",
            artifact_kind="bash_draft",
            display_name="提取出的 Bash 草稿",
            purpose="这是从 AI 回复里抽取出的 shell 脚本草稿，属于执行脚本生成过程中的中间态。",
            editing_guidance="更适合拿来理解 AI 生成了什么命令；真正执行时请优先看 execution_script.sh。",
            stage="execution",
            sort_priority=40,
        )

    if lowered_name == "summary.txt" and not in_output_dir:
        return ArtifactDescriptor(
            category="result",
            group="result",
            artifact_kind="run_summary",
            display_name="运行摘要",
            purpose="这是这次运行的总体结果摘要，适合先快速判断 AI 代码有没有跑通以及结果如何。",
            editing_guidance="这是结果快照，默认只读，建议作为概览查看而不是修改入口。",
            stage="summary",
            is_core=True,
            sort_priority=3,
        )

    if lowered_name in {"run_summary.json", "leaderboard.csv", "leaderboard.json"}:
        return ArtifactDescriptor(
            category="result",
            group="result",
            artifact_kind="leaderboard",
            display_name="候选结果对比",
            purpose="这里记录的是候选方案、分数或结构化结果，适合用来比较这次运行产出了什么。",
            editing_guidance="这是结果文件，默认只读，更适合查看和对比而不是手工改写。",
            stage="result_compare",
            is_core=True,
            sort_priority=4,
        )

    if lowered_name in {"validation_predictions.csv", "results.csv"} and not in_output_dir:
        return ArtifactDescriptor(
            category="result",
            group="result",
            artifact_kind="predictions",
            display_name="预测结果表",
            purpose="这里保存了这次运行导出的预测结果或验证结果，方便你核对输出。",
            editing_guidance="这是运行结果，不建议把它当成代码修改入口。",
            stage="predictions",
            is_core=True,
            sort_priority=5,
        )

    if lowered_name == "token_usage.json":
        return ArtifactDescriptor(
            category="result",
            group="result",
            artifact_kind="token_usage",
            display_name="Token 用量记录",
            purpose="这里记录了这次 MLZero 运行中 AI 会话的 token 消耗情况。",
            editing_guidance="这是统计结果文件，默认只读。",
            stage="usage",
            is_core=True,
            sort_priority=6,
        )

    if lowered_name == "summary.txt" and in_output_dir:
        return ArtifactDescriptor(
            category="result",
            group="result",
            artifact_kind="node_output_summary",
            display_name="节点输出摘要",
            purpose="这是某个节点输出目录里的结果摘要，反映该节点自己的运行结果。",
            editing_guidance="这是节点结果快照，适合查看，不建议作为编辑入口。",
            stage="summary",
            sort_priority=60,
        )

    if lowered_name in {"validation_predictions.csv", "results.csv"} and in_output_dir:
        return ArtifactDescriptor(
            category="result",
            group="result",
            artifact_kind="node_predictions",
            display_name="节点预测结果",
            purpose="这是某个节点输出目录里的预测结果文件，用来核对该节点产出的表格结果。",
            editing_guidance="这是节点结果文件，适合查看，不建议作为编辑入口。",
            stage="predictions",
            sort_priority=61,
        )

    if lowered_name == "mlzero-runtime-config.yaml":
        return ArtifactDescriptor(
            category="other",
            group="context",
            artifact_kind="runtime_config",
            display_name="运行时配置快照",
            purpose="这里保存了这次 MLZero 运行使用的配置快照，方便追溯当时的参数和模型设置。",
            editing_guidance="这是运行配置快照，通常用于理解上下文，不建议直接在这里改。",
            stage="context",
            sort_priority=200,
        )

    if lowered_path.startswith("input/"):
        if lowered_name.endswith(".csv"):
            return ArtifactDescriptor(
                category="other",
                group="context",
                artifact_kind="input_dataset",
                display_name="输入数据副本",
                purpose="这是本次运行使用的数据集副本，便于追溯 AI 代码当时面对的数据输入。",
                editing_guidance="这是输入快照，不建议在代码工作区里改数据本身。",
                stage="context",
                sort_priority=201,
            )
        return ArtifactDescriptor(
            category="other",
            group="context",
            artifact_kind="input_context",
            display_name="输入说明文件",
            purpose="这是本次运行用到的输入说明或附加描述，帮助 AI 理解任务背景。",
            editing_guidance="这是输入上下文文件，适合查看，不建议作为代码编辑入口。",
            stage="context",
            sort_priority=202,
        )

    if lowered_name in {"logs.txt", "detail_logs.txt", "info_logs.txt", "debugging_logs.txt"}:
        return ArtifactDescriptor(
            category="log",
            group="log",
            artifact_kind="runtime_log",
            display_name=_humanize_log_name(lowered_name),
            purpose="这是 MLZero 运行过程中的总日志或分级日志，用来排查流程执行情况。",
            editing_guidance="日志文件默认只读，主要用于定位问题，不建议修改。",
            stage="logs",
            sort_priority=300,
        )

    if lowered_name in {"mlzero_stdout.log", "mlzero_stderr.log", "stdout", "stderr"} or lowered_name.startswith(("stdout_", "stderr_")):
        return ArtifactDescriptor(
            category="log",
            group="log",
            artifact_kind="process_stream",
            display_name="标准输出/错误输出",
            purpose="这里保存的是运行过程中的标准输出或标准错误内容，适合直接看报错和执行痕迹。",
            editing_guidance="这是运行输出流，默认只读，主要用来排查错误。",
            stage="logs",
            sort_priority=301,
        )

    if lowered_name.startswith("python_coder_prompt"):
        return ArtifactDescriptor(
            category="state",
            group="generation",
            artifact_kind="python_coder_prompt",
            display_name="写代码 Prompt",
            purpose="这是发给写代码模型的提示词，能直接看到 AI 当时是基于什么要求写代码的。",
            editing_guidance="更适合理解生成过程；如果你要改最终代码，优先看 generated_code.py。",
            stage="python_coder",
            is_core=True,
            sort_priority=20,
        )

    if lowered_name.startswith("python_coder_response"):
        return ArtifactDescriptor(
            category="state",
            group="generation",
            artifact_kind="python_coder_response",
            display_name="写代码 AI 回复",
            purpose="这是写代码模型返回的原始文本，方便对照 AI 原话和最终落地代码之间的差别。",
            editing_guidance="更适合审阅 AI 的原始回答；真正执行的代码仍以 generated_code.py 为准。",
            stage="python_coder",
            is_core=True,
            sort_priority=21,
        )

    if lowered_name.startswith("python_coder_retry_request"):
        return ArtifactDescriptor(
            category="state",
            group="generation",
            artifact_kind="python_coder_retry_request",
            display_name="代码重试请求",
            purpose="这是系统要求 AI 重写代码时发出的补充请求，用来解释为什么会再次生成代码。",
            editing_guidance="这是过程追踪文件，适合理解重试原因，不是最终代码入口。",
            stage="python_coder_retry",
            sort_priority=22,
        )

    if lowered_name.startswith("python_coder_retry_response"):
        return ArtifactDescriptor(
            category="state",
            group="generation",
            artifact_kind="python_coder_retry_response",
            display_name="代码重试回复",
            purpose="这是 AI 针对重试请求给出的回复，适合用来对比修复前后发生了什么变化。",
            editing_guidance="这是过程追踪文件，适合理解重试结果，不是最终代码入口。",
            stage="python_coder_retry",
            sort_priority=23,
        )

    if lowered_name.startswith("bash_coder_prompt"):
        return ArtifactDescriptor(
            category="state",
            group="generation",
            artifact_kind="bash_coder_prompt",
            display_name="执行脚本 Prompt",
            purpose="这是发给脚本生成阶段的提示词，用来生成或整理执行命令。",
            editing_guidance="这是脚本生成过程文件，更适合理解 AI 怎样组织运行命令。",
            stage="bash_coder",
            sort_priority=24,
        )

    if lowered_name.startswith("bash_coder_response"):
        return ArtifactDescriptor(
            category="state",
            group="generation",
            artifact_kind="bash_coder_response",
            display_name="执行脚本 AI 回复",
            purpose="这是脚本生成阶段 AI 的原始回复，通常对应 execution_script.sh 的上游内容。",
            editing_guidance="建议把它当成过程说明来看；真正运行的脚本优先看 execution_script.sh。",
            stage="bash_coder",
            sort_priority=25,
        )

    if lowered_name.startswith("executer_prompt"):
        return ArtifactDescriptor(
            category="state",
            group="generation",
            artifact_kind="executer_prompt",
            display_name="执行阶段 Prompt",
            purpose="这是执行/审查阶段发给 AI 的提示词，通常会携带运行结果或报错信息。",
            editing_guidance="这是过程文件，适合拿来理解系统为什么做出下一步判断。",
            stage="executor",
            sort_priority=26,
        )

    if lowered_name.startswith("executer_response"):
        return ArtifactDescriptor(
            category="state",
            group="generation",
            artifact_kind="executer_response",
            display_name="执行阶段 AI 回复",
            purpose="这是执行/审查阶段 AI 的回复，反映它如何理解运行结果或错误。",
            editing_guidance="这是过程文件，主要用于理解 AI 的判断，不是最终代码入口。",
            stage="executor",
            sort_priority=27,
        )

    if lowered_name.startswith("error_analyzer_prompt") or lowered_name.startswith("error_analyzer_response") or lowered_name.startswith("error_summary") or lowered_name == "error_analysis.txt":
        return ArtifactDescriptor(
            category="state",
            group="generation",
            artifact_kind="error_analysis",
            display_name="错误分析",
            purpose="这里记录了失败分析阶段的提示词、AI 回复或错误总结，用来解释为什么代码没跑通。",
            editing_guidance="这是排错过程文件，适合查看问题来源，不建议作为最终代码入口。",
            stage="repair",
            sort_priority=28,
        )

    if lowered_name.startswith("decision_"):
        return ArtifactDescriptor(
            category="state",
            group="generation",
            artifact_kind="decision",
            display_name="决策记录",
            purpose="这是节点内部的决策说明，帮助你理解系统为什么选择当前这条生成或修复路径。",
            editing_guidance="这是过程说明文件，适合查看，不建议作为代码编辑入口。",
            stage="decision",
            sort_priority=29,
        )

    if lowered_name.startswith("validation_score_") or lowered_name == "best_run_summary.txt":
        return ArtifactDescriptor(
            category="result",
            group="result",
            artifact_kind="node_score",
            display_name="节点分数记录",
            purpose="这里记录了某个节点的验证分数或最佳运行摘要，适合快速判断这个节点表现如何。",
            editing_guidance="这是结果记录文件，主要用于查看和比对。",
            stage="score",
            sort_priority=62,
        )

    if lowered_name in {
        "description_files.txt",
        "description_file_retriever_prompt.txt",
        "description_file_retriever_response.txt",
        "task_description.txt",
        "task_descriptor_prompt.txt",
        "task_descriptor_response.txt",
        "selected_tool.txt",
        "tool_selector_prompt.txt",
        "tool_selector_response.txt",
        "tool_selector_explanation.txt",
    }:
        return ArtifactDescriptor(
            category="state",
            group="generation",
            artifact_kind="task_setup",
            display_name="任务理解过程",
            purpose="这里记录的是任务描述、工具选择和前置理解过程，帮助解释 AI 为什么会走到后面的代码生成步骤。",
            editing_guidance="这是任务理解阶段文件，更适合看 AI 的思路，不建议直接当作代码入口。",
            stage="task_setup",
            sort_priority=30,
        )

    if lowered_name.startswith("python_reader_") or lowered_name in {"chat_prompt.txt", "chat_response.txt", "user_message.txt"}:
        return ArtifactDescriptor(
            category="state",
            group="generation",
            artifact_kind="reader_stage",
            display_name="前置读取阶段",
            purpose="这是前置读取/解释阶段留下的文本或代码，用来说明系统怎样理解输入数据和任务。",
            editing_guidance="这是过程文件，主要用于理解上下文和前置读取逻辑。",
            stage="reader",
            sort_priority=31,
        )

    if (
        lowered_name.startswith("tutorial_")
        or lowered_name.startswith("retriever_")
        or lowered_name.startswith("reranker_")
        or lowered_name in {"parsed_search_query.txt", "selected_tutorials.txt"}
    ):
        return ArtifactDescriptor(
            category="state",
            group="generation",
            artifact_kind="retrieval_stage",
            display_name="检索与教程选择",
            purpose="这里记录的是教程检索、重排和上下文拼装过程，帮助解释 AI 写代码时参考了哪些材料。",
            editing_guidance="这是检索过程文件，更适合排查 AI 参考了什么内容。",
            stage="retrieval",
            sort_priority=32,
        )

    if "/states/" in f"/{lowered_path}" or lowered_path.startswith("states/"):
        return ArtifactDescriptor(
            category="state",
            group="generation",
            artifact_kind="generic_state",
            display_name="过程状态文件",
            purpose="这是运行过程中的中间状态文件，通常用来追踪 AI 在某个阶段产生了什么内容。",
            editing_guidance="这是过程追踪文件，适合理解流程，不建议作为主要代码修改入口。",
            stage="state",
            sort_priority=90,
        )

    if lowered_name.endswith((".py", ".sh", ".ps1", ".bat", ".sql")):
        return ArtifactDescriptor(
            category="code",
            group="other",
            artifact_kind="other_code",
            display_name="其他代码文件",
            purpose="这是最新运行目录里的代码文件，但当前还没有命中特定用途规则。",
            editing_guidance="修改前请先确认它是不是当前真正会被执行的入口文件。",
            stage="other",
            sort_priority=400,
        )

    if lowered_name.endswith((".json", ".csv", ".yaml", ".yml", ".md", ".txt")):
        return ArtifactDescriptor(
            category="other",
            group="other",
            artifact_kind="other_text",
            display_name="其他文本工件",
            purpose="这是最新运行目录里的文本工件，暂时没有命中特定说明规则。",
            editing_guidance="更适合查看，不建议在不了解上下文时直接修改。",
            stage="other",
            sort_priority=401,
        )

    return ArtifactDescriptor(
        category="other",
        group="other",
        artifact_kind="other_text",
        display_name="其他工件",
        purpose="这是最新运行目录里的工件，当前没有识别出更明确的用途。",
        editing_guidance="建议先查看路径和上下文，再决定是否需要操作它。",
        stage="other",
        sort_priority=999,
    )


def _humanize_log_name(lowered_name: str) -> str:
    if lowered_name == "logs.txt":
        return "总日志"
    if lowered_name == "detail_logs.txt":
        return "详细日志"
    if lowered_name == "info_logs.txt":
        return "信息日志"
    if lowered_name == "debugging_logs.txt":
        return "调试日志"
    return "运行日志"


def _entry_sort_key(entry: TaskCodeArtifactEntry) -> tuple[int, int, int, str]:
    return (
        0 if entry.is_core else 1,
        GROUP_ORDER.get(entry.group, 999),
        entry.recommended_order,
        _extract_node_order(entry.path),
        entry.path.lower(),
    )


def _extract_node_name(relative_path: str) -> str | None:
    for part in relative_path.split("/"):
        if part.startswith("node_"):
            return part
    return None


def _extract_node_order(relative_path: str) -> int:
    for part in relative_path.split("/"):
        if not part.startswith("node_"):
            continue
        try:
            return int(part.removeprefix("node_"))
        except ValueError:
            return 999
    return -1


def _resolve_artifact_path(run_output_dir: Path, artifact_path: str) -> Path:
    candidate = artifact_path.strip()
    if not candidate:
        raise FileNotFoundError("Artifact path is required.")

    normalized_relative = Path(candidate.replace("\\", "/"))
    if normalized_relative.is_absolute():
        raise PermissionError("Artifact path must be relative to the latest MLZero output directory.")

    run_root = run_output_dir.resolve()
    resolved_path = (run_root / normalized_relative).resolve()

    if run_root not in resolved_path.parents and resolved_path != run_root:
        raise PermissionError("Artifact path escapes the latest MLZero output directory.")
    if "best_run" in resolved_path.parts:
        raise PermissionError("best_run shadow copies are not editable from the workspace.")
    if not resolved_path.exists() or not resolved_path.is_file():
        raise FileNotFoundError(f"Artifact not found: {artifact_path}")

    return resolved_path


def _find_default_rerun_path(run_output_dir: Path) -> str | None:
    candidates = sorted(
        (
            path
            for path in run_output_dir.rglob("generated_code.py")
            if path.is_file() and "best_run" not in path.parts
        ),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        return None
    return candidates[0].relative_to(run_output_dir).as_posix()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _version_manifest_path(run_output_dir: Path) -> Path:
    return run_output_dir / VERSION_MANIFEST_NAME


def _read_all_version_records(run_output_dir: Path) -> list[TaskCodeArtifactVersionRecord]:
    manifest = _version_manifest_path(run_output_dir)
    if not manifest.exists():
        return []
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = payload.get("versions") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return []
    records: list[TaskCodeArtifactVersionRecord] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            records.append(TaskCodeArtifactVersionRecord.model_validate(row))
        except Exception:
            continue
    return records


def _read_version_history(run_output_dir: Path, *, relative_path: str) -> list[TaskCodeArtifactVersionRecord]:
    return [
        record
        for record in _read_all_version_records(run_output_dir)
        if record.path == relative_path
    ]


def _write_version_records(run_output_dir: Path, records: list[TaskCodeArtifactVersionRecord]) -> None:
    manifest = _version_manifest_path(run_output_dir)
    manifest.write_text(
        json.dumps({"versions": [record.model_dump(mode="json") for record in records]}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _append_version_record(
    run_output_dir: Path,
    *,
    relative_path: str,
    size_bytes: int,
    previous_sha256: str,
    sha256: str,
) -> TaskCodeArtifactVersionRecord:
    now = datetime.now(timezone.utc)
    version = TaskCodeArtifactVersionRecord(
        version_id=f"{now.strftime('%Y%m%dT%H%M%SZ')}-{sha256[:12]}",
        path=relative_path,
        saved_at=now,
        size_bytes=size_bytes,
        previous_sha256=previous_sha256,
        sha256=sha256,
    )
    records = _read_all_version_records(run_output_dir)
    records.append(version)
    _write_version_records(run_output_dir, records)
    return version
