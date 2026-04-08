from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from typing import Optional

from backend.app.models.task import TaskCreateRequest, TaskRecord


class TaskStore:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def list_tasks(self) -> list[TaskRecord]:
        tasks: list[TaskRecord] = []
        for task_dir in sorted(self.root_dir.glob("*")):
            task_file = task_dir / "task.json"
            if not task_file.exists():
                continue
            tasks.append(TaskRecord.model_validate_json(task_file.read_text(encoding="utf-8")))
        return sorted(tasks, key=lambda item: item.created_at, reverse=True)

    def create_task(self, payload: TaskCreateRequest) -> TaskRecord:
        now = datetime.now(timezone.utc)
        task = TaskRecord(
            id=uuid4().hex[:8],
            name=payload.name,
            description=payload.description,
            label_column=payload.label_column,
            problem_type=payload.problem_type,
            created_at=now,
            updated_at=now,
        )
        self.save_task(task)
        return task

    def get_task(self, task_id: str) -> Optional[TaskRecord]:
        task_file = self._task_file(task_id)
        if not task_file.exists():
            return None
        return TaskRecord.model_validate_json(task_file.read_text(encoding="utf-8"))

    def save_task(self, task: TaskRecord) -> TaskRecord:
        task_dir = self._task_dir(task.id)
        task_dir.mkdir(parents=True, exist_ok=True)
        task.updated_at = datetime.now(timezone.utc)
        task_path = self._task_file(task.id)
        task_path.write_text(task.model_dump_json(indent=2), encoding="utf-8")
        return task

    def save_dataset(self, task_id: str, filename: str, content: bytes) -> Path:
        task_dir = self._task_dir(task_id)
        task_dir.mkdir(parents=True, exist_ok=True)
        suffix = Path(filename).suffix.lower() or ".csv"
        dataset_path = task_dir / f"dataset{suffix}"
        dataset_path.write_bytes(content)
        return dataset_path

    def _task_dir(self, task_id: str) -> Path:
        return self.root_dir / task_id

    def _task_file(self, task_id: str) -> Path:
        return self._task_dir(task_id) / "task.json"
