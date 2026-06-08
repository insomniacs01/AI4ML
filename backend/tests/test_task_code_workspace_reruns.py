from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from backend.app.models.task import TaskCodeArtifactEntry, TaskCodeArtifactRerunRequest, TaskRecord
from backend.app.services import task_code_workspace
from backend.app.services.task_code_workspace_files import artifact_entry_from_path
from backend.app.services.task_code_workspace_reruns import rerun_code_workspace_artifact


def _task() -> TaskRecord:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return TaskRecord(
        id="task-code-rerun",
        team_id="team-1",
        created_by="user-1",
        name="Code Rerun Task",
        description="Rerun generated code.",
        created_at=now,
        updated_at=now,
    )


def _artifact(run_dir: Path, source: str) -> tuple[Path, TaskCodeArtifactEntry]:
    artifact = run_dir / "generated_code.py"
    artifact.write_text(source, encoding="utf-8")
    entry = artifact_entry_from_path(run_dir, artifact)
    assert entry is not None
    return artifact, entry


def test_rerun_code_workspace_artifact_writes_success_logs(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    artifact, entry = _artifact(run_dir, "print('rerun ok')\n")

    response = rerun_code_workspace_artifact(_task(), run_dir, artifact, entry, time_limit_seconds=5)

    assert response.success is True
    assert response.exit_code == 0
    assert response.detail == "代码工作区工件已真实重跑完成。"
    assert (run_dir / response.stdout_path).read_text(encoding="utf-8") == "rerun ok\n"
    assert (run_dir / response.stderr_path).read_text(encoding="utf-8") == ""
    assert response.version_id is None


def test_rerun_code_workspace_artifact_writes_failure_logs(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    artifact, entry = _artifact(
        run_dir,
        "\n".join(
            [
                "import sys",
                "print('bad input', file=sys.stderr)",
                "sys.exit(7)",
                "",
            ]
        ),
    )

    response = rerun_code_workspace_artifact(_task(), run_dir, artifact, entry, time_limit_seconds=5)

    assert response.success is False
    assert response.exit_code == 7
    assert response.detail == "代码工作区工件重跑失败，退出码 7。"
    assert (run_dir / response.stdout_path).read_text(encoding="utf-8") == ""
    assert (run_dir / response.stderr_path).read_text(encoding="utf-8") == "bad input\n"


def test_rerun_code_workspace_artifact_records_timeout(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    artifact, entry = _artifact(
        run_dir,
        "\n".join(
            [
                "import time",
                "print('started', flush=True)",
                "time.sleep(10)",
                "",
            ]
        ),
    )

    response = rerun_code_workspace_artifact(_task(), run_dir, artifact, entry, time_limit_seconds=1)

    assert response.success is False
    assert response.exit_code == -1
    assert response.detail == "代码工作区工件重跑超时：1 秒。"
    assert (run_dir / response.stderr_path).read_text(encoding="utf-8") == "Rerun timed out after 1 seconds."


def test_rerun_task_code_artifact_uses_resolved_workspace(monkeypatch, tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _artifact(run_dir, "print('from facade')\n")
    monkeypatch.setattr(task_code_workspace, "_resolve_run_output_dir", lambda task: (run_dir, run_dir))

    response = task_code_workspace.rerun_task_code_artifact(
        _task(),
        TaskCodeArtifactRerunRequest(path="generated_code.py", time_limit_seconds=5),
    )

    assert response.success is True
    assert response.path == "generated_code.py"
    assert (run_dir / response.stdout_path).read_text(encoding="utf-8") == "from facade\n"
