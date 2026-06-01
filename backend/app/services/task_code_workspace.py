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
    VERSION_MANIFEST_NAME,
    append_version_record,
    read_version_history,
    sha256_file,
)
from backend.app.services.task_code_artifact_descriptors import (
    GROUP_ORDER,
    describe_artifact,
    detect_artifact_language,
    is_editable_artifact,
)
from backend.app.services.task_artifacts import build_run_artifact_index, recent_node_dirs


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
        version_history=read_version_history(run_output_dir, relative_path=entry.path),
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

    previous_hash = sha256_file(artifact)
    artifact.write_text(payload.content, encoding="utf-8")
    next_hash = sha256_file(artifact)
    refreshed_entry = _artifact_entry_from_path(run_output_dir, artifact)
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


def _collect_workspace_entries(run_output_dir: Path) -> list[TaskCodeArtifactEntry]:
    entries: list[TaskCodeArtifactEntry] = []
    for path in _iter_workspace_candidate_files(run_output_dir):
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
    language = detect_artifact_language(path)
    if language is None:
        return None

    relative_path = path.relative_to(run_output_dir).as_posix()
    descriptor = describe_artifact(relative_path, path.name)
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
        editable=is_editable_artifact(descriptor, language),
        updated_at=datetime.fromtimestamp(stats.st_mtime, tz=timezone.utc),
    )


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
        raise PermissionError("Artifact path must be relative to the latest run output directory.")

    run_root = run_output_dir.resolve()
    resolved_path = (run_root / normalized_relative).resolve()

    if run_root not in resolved_path.parents and resolved_path != run_root:
        raise PermissionError("Artifact path escapes the latest run output directory.")
    if "best_run" in resolved_path.parts:
        raise PermissionError("best_run shadow copies are not editable from the workspace.")
    if not resolved_path.exists() or not resolved_path.is_file():
        raise FileNotFoundError(f"Artifact not found: {artifact_path}")

    return resolved_path


def _find_default_rerun_path(run_output_dir: Path) -> str | None:
    candidates = [
        path
        for path in [
            run_output_dir / "generated_code.py",
            *[node_dir / "generated_code.py" for node_dir in recent_node_dirs(run_output_dir)],
        ]
        if path.is_file() and "best_run" not in path.parts
    ]
    candidates = sorted(candidates, key=lambda item: item.stat().st_mtime, reverse=True)
    if not candidates:
        return None
    return candidates[0].relative_to(run_output_dir).as_posix()


def _iter_workspace_candidate_files(run_output_dir: Path) -> list[Path]:
    roots = [
        run_output_dir,
        run_output_dir / "output",
        run_output_dir / "output" / "code",
        run_output_dir / "output" / "logs",
        run_output_dir / "input",
        run_output_dir / "state",
    ]
    node_dirs = recent_node_dirs(run_output_dir)
    roots.extend(node_dirs)
    for node_dir in node_dirs:
        roots.extend([node_dir / "states", node_dir / "output", node_dir / "logs"])

    candidates: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        if not root.exists():
            continue
        try:
            children = list(root.iterdir())
        except OSError:
            continue
        for path in children:
            if not path.is_file() or path in seen:
                continue
            seen.add(path)
            candidates.append(path)
    return sorted(candidates)
