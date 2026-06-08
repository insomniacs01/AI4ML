from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from backend.app.models.task import (
    TaskCodeArtifactEntry,
    TaskCodeArtifactRerunResponse,
    TaskRecord,
)
from backend.app.services.task_code_versions import read_version_history


def rerun_code_workspace_artifact(
    task: TaskRecord,
    run_output_dir: Path,
    artifact: Path,
    entry: TaskCodeArtifactEntry,
    time_limit_seconds: int,
) -> TaskCodeArtifactRerunResponse:
    started_at = datetime.now(timezone.utc)
    stdout_path, stderr_path = _rerun_log_paths(run_output_dir, entry.path, started_at)

    try:
        completed = subprocess.run(  # noqa: S603
            [sys.executable, str(artifact)],
            cwd=str(artifact.parent),
            capture_output=True,
            text=True,
            timeout=time_limit_seconds,
            check=False,
        )
        stdout_path.write_text(completed.stdout or "", encoding="utf-8")
        stderr_path.write_text(completed.stderr or "", encoding="utf-8")
        exit_code = int(completed.returncode)
        success = exit_code == 0
        detail = "代码工作区工件已真实重跑完成。" if success else f"代码工作区工件重跑失败，退出码 {exit_code}。"
    except subprocess.TimeoutExpired as exc:
        stdout_path.write_text(_process_output_text(exc.stdout), encoding="utf-8")
        stderr_path.write_text(
            _process_output_text(exc.stderr) or f"Rerun timed out after {time_limit_seconds} seconds.",
            encoding="utf-8",
        )
        exit_code = -1
        success = False
        detail = f"代码工作区工件重跑超时：{time_limit_seconds} 秒。"

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


def _rerun_log_paths(run_output_dir: Path, relative_path: str, started_at: datetime) -> tuple[Path, Path]:
    run_id = started_at.strftime("%Y%m%dT%H%M%SZ")
    log_dir = run_output_dir / "code_workspace_reruns"
    log_dir.mkdir(parents=True, exist_ok=True)
    safe_name = relative_path.replace("/", "__").replace("\\", "__")
    return (
        log_dir / f"{run_id}_{safe_name}.stdout.log",
        log_dir / f"{run_id}_{safe_name}.stderr.log",
    )


def _process_output_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value
