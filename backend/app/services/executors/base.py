from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from backend.app.models.task import RunSummary, TaskRecord


class BaseExecutor(ABC):
    @abstractmethod
    def run(self, task: TaskRecord, dataset_path: Path, time_limit: int) -> RunSummary:
        raise NotImplementedError
