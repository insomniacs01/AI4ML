from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from backend.app.models.task import (
    TaskCodeArtifactContentResponse,
    TaskCodeArtifactEntry,
    TaskCodeArtifactRerunRequest,
    TaskCodeArtifactRerunResponse,
    TaskCodeArtifactUpdateRequest,
    TaskCodeWorkspaceResponse,
    TaskRecord,
)
from backend.app.services.task_code_versions import (
    append_version_record,
    read_version_history,
    sha256_file,
)
from backend.app.services.task_code_workspace_files import (
    artifact_entry_from_path,
    collect_workspace_entries,
    find_default_rerun_path,
    resolve_artifact_path,
)
from backend.app.services.task_artifacts import build_run_artifact_index


MAX_ARTIFACT_SIZE_BYTES = 2 * 1024 * 1024
MAX_SAVE_SIZE_BYTES = 2 * 1024 * 1024


def build_task_code_workspace(task: TaskRecord) -> TaskCodeWorkspaceResponse:
    warnings: list[str] = []
    requested_run_dir, existing_run_dir = _resolve_run_output_dir(task)

    if requested_run_dir is None:
        warnings.append("这个任务还没有自动建模结果，暂时没有可查看的 AI 代码。")
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

    items = collect_workspace_entries(existing_run_dir)
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
    artifact = resolve_artifact_path(run_output_dir, artifact_path)
    entry = artifact_entry_from_path(run_output_dir, artifact)

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
        version_history=read_version_history(run_output_dir, relative_path=entry.path),
    )


def save_task_code_artifact(
    task: TaskRecord,
    payload: TaskCodeArtifactUpdateRequest,
) -> TaskCodeArtifactContentResponse:
    run_output_dir = _require_existing_run_output_dir(task)
    artifact = resolve_artifact_path(run_output_dir, payload.path)
    entry = artifact_entry_from_path(run_output_dir, artifact)

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

    previous_hash = sha256_file(artifact)
    artifact.write_text(payload.content, encoding="utf-8")
    next_hash = sha256_file(artifact)
    refreshed_entry = artifact_entry_from_path(run_output_dir, artifact)
    if refreshed_entry is None:
        raise RuntimeError(f"Saved artifact could not be reloaded: {payload.path}")
    version = append_version_record(
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
        version_history=read_version_history(run_output_dir, relative_path=refreshed_entry.path),
    )


def resolve_task_code_artifact_file(task: TaskRecord, artifact_path: str) -> tuple[Path, TaskCodeArtifactEntry]:
    run_output_dir = _require_existing_run_output_dir(task)
    artifact = resolve_artifact_path(run_output_dir, artifact_path)
    entry = artifact_entry_from_path(run_output_dir, artifact)
    if entry is None:
        raise FileNotFoundError(f"Unsupported artifact type: {artifact_path}")
    return artifact, entry


def rerun_task_code_artifact(
    task: TaskRecord,
    payload: TaskCodeArtifactRerunRequest,
) -> TaskCodeArtifactRerunResponse:
    run_output_dir = _require_existing_run_output_dir(task)
    requested_path = payload.path or find_default_rerun_path(run_output_dir)
    if not requested_path:
        raise FileNotFoundError("No generated_code.py artifact is available to rerun.")

    artifact = resolve_artifact_path(run_output_dir, requested_path)
    entry = artifact_entry_from_path(run_output_dir, artifact)
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
    version_history = read_version_history(run_output_dir, relative_path=entry.path)
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
    artifact_index = build_run_artifact_index(task)
    return artifact_index.requested_output_dir, artifact_index.output_dir


def _require_existing_run_output_dir(task: TaskRecord) -> Path:
    requested_run_dir, existing_run_dir = _resolve_run_output_dir(task)
    if requested_run_dir is None:
        raise RuntimeError("这个任务还没有自动建模结果。")
    if existing_run_dir is None:
        raise FileNotFoundError(f"Latest run output directory is missing: {requested_run_dir}")
    return existing_run_dir
