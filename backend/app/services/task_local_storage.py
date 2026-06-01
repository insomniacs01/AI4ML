from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Iterable

from backend.app.models.task import TaskRecord


class TaskLocalStorage:
    def __init__(self, *, dataset_root_dir: Path, run_output_dir: Path) -> None:
        self.dataset_root_dir = dataset_root_dir
        self.run_output_dir = run_output_dir
        self.dataset_root_dir.mkdir(parents=True, exist_ok=True)
        self.run_output_dir.mkdir(parents=True, exist_ok=True)

    def save_dataset(self, team_id: str, task_id: str, filename: str, content: bytes) -> Path:
        task_dir = self.task_dir(team_id, task_id)
        task_dir.mkdir(parents=True, exist_ok=True)
        self._validate_csv_filename(filename)
        dataset_path = task_dir / "dataset.csv"
        dataset_path.write_bytes(content)
        return dataset_path

    def save_dataset_chunks(self, team_id: str, task_id: str, filename: str, chunks: Iterable[bytes]) -> Path:
        dataset_path = self.dataset_upload_path(team_id, task_id, filename)
        with dataset_path.open("wb") as handle:
            for chunk in chunks:
                if chunk:
                    handle.write(chunk)
        return dataset_path

    def dataset_upload_path(self, team_id: str, task_id: str, filename: str) -> Path:
        task_dir = self.task_dir(team_id, task_id)
        task_dir.mkdir(parents=True, exist_ok=True)
        self._validate_csv_filename(filename)
        return task_dir / "dataset.csv"

    def delete_task_files(self, team_id: str, task_id: str) -> None:
        shutil.rmtree(self.task_dir(team_id, task_id), ignore_errors=True)
        shutil.rmtree(self.run_output_dir / task_id, ignore_errors=True)

    def write_task_manifest(self, task: TaskRecord) -> None:
        manifest_dir = self.task_dir(task.team_id, task.id)
        manifest_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = manifest_dir / "task.json"
        manifest_path.write_text(
            json.dumps(task.model_dump(mode="json"), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def task_dir(self, team_id: str, task_id: str) -> Path:
        return self.dataset_root_dir / task_id

    @staticmethod
    def task_storage_uri(task_id: str) -> str:
        return f"storage/tasks/{task_id}"

    @staticmethod
    def run_storage_uri(task_id: str, run_id: str) -> str:
        return f"storage/runs/{task_id}/{run_id}"

    @staticmethod
    def _validate_csv_filename(filename: str) -> None:
        suffix = Path(filename).suffix.lower()
        if suffix != ".csv":
            raise ValueError(f"dataset filename must end with .csv: {filename}")
