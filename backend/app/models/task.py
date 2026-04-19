from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    draft = "draft"
    uploaded = "uploaded"
    running = "running"
    completed = "completed"
    failed = "failed"


class RunSummary(BaseModel):
    best_model: str
    metric_name: str
    metric_value: float
    leaderboard: list[dict[str, Any]] = Field(default_factory=list)
    output_dir: str


class TaskCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=500)
    label_column: str = Field(min_length=1, max_length=80)
    problem_type: Literal["classification", "regression"] = "classification"


class TaskRunRequest(BaseModel):
    time_limit: int = Field(default=20, ge=5, le=300)


class TaskRecord(BaseModel):
    id: str
    name: str
    description: str
    label_column: str
    problem_type: Literal["classification", "regression"]
    status: TaskStatus = TaskStatus.draft
    dataset_filename: Optional[str] = None
    dataset_path: Optional[str] = None
    notes: Optional[str] = None
    last_run: Optional[RunSummary] = None
    created_at: datetime
    updated_at: datetime


class TaskListResponse(BaseModel):
    items: list[TaskRecord]
