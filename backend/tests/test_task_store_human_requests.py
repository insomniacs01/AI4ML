from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from backend.app.models.task import (
    HumanInteractionRequestStatus,
    TaskHumanRequestRecord,
    WorkflowStage,
)
from backend.app.services.task_cache import TaskCache
from backend.app.services.task_store_human_requests import TaskStoreHumanRequestMixin


def _request(request_id: str = "request-1") -> TaskHumanRequestRecord:
    now = datetime.now(timezone.utc)
    return TaskHumanRequestRecord(
        id=request_id,
        team_id="team-1",
        task_id="task-1",
        stage=WorkflowStage.training_validation,
        status=HumanInteractionRequestStatus.pending,
        created_at=now,
        updated_at=now,
    )


class Repository:
    def __init__(self) -> None:
        self.list_calls = 0
        self.requests: list[TaskHumanRequestRecord] = []

    def list_human_requests(self, team_id: str, task_id: str, *, access_token: str) -> list[TaskHumanRequestRecord]:
        self.list_calls += 1
        return list(self.requests)

    def create_human_request(self, **kwargs: Any) -> TaskHumanRequestRecord:
        request = _request("created-request")
        self.requests.append(request)
        return request

    def get_human_request(
        self,
        team_id: str,
        task_id: str,
        request_id: str,
        *,
        access_token: str,
    ) -> TaskHumanRequestRecord | None:
        return next((request for request in self.requests if request.id == request_id), None)

    def update_human_request(
        self,
        request: TaskHumanRequestRecord,
        *,
        access_token: str,
    ) -> TaskHumanRequestRecord:
        self.requests = [request if item.id == request.id else item for item in self.requests]
        return request


class Store(TaskStoreHumanRequestMixin):
    def __init__(self, cache: TaskCache, repository: Repository) -> None:
        self.cache = cache
        self.human_request_repository = repository
        self.refresh_calls = 0

    def _refresh_human_requests_cache_in_background(self, team_id: str, task_id: str, *, access_token: str) -> None:
        self.refresh_calls += 1


def test_list_human_requests_uses_cache_only_when_requested() -> None:
    with TemporaryDirectory() as temp_dir:
        repository = Repository()
        repository.requests = [_request()]
        store = Store(TaskCache(Path(temp_dir) / "task_cache.sqlite3", ttl_seconds=60), repository)

        first = store.list_human_requests("team-1", "task-1", access_token="token", prefer_cache=True)
        second = store.list_human_requests(
            "team-1",
            "task-1",
            access_token="token",
            prefer_cache=True,
            allow_stale_cache=True,
        )
        authoritative = store.list_human_requests("team-1", "task-1", access_token="token")

        assert [request.id for request in first] == ["request-1"]
        assert [request.id for request in second] == ["request-1"]
        assert [request.id for request in authoritative] == ["request-1"]
        assert repository.list_calls == 2
        assert store.refresh_calls == 1


def test_empty_human_request_list_is_cached_and_invalidated_on_write() -> None:
    with TemporaryDirectory() as temp_dir:
        repository = Repository()
        store = Store(TaskCache(Path(temp_dir) / "task_cache.sqlite3", ttl_seconds=60), repository)

        assert store.list_human_requests("team-1", "task-1", access_token="token", prefer_cache=True) == []
        assert store.list_human_requests(
            "team-1",
            "task-1",
            access_token="token",
            prefer_cache=True,
            allow_stale_cache=True,
        ) == []
        assert repository.list_calls == 1

        store.create_human_request(
            team_id="team-1",
            task_id="task-1",
            stage=WorkflowStage.training_validation,
            requested_by="user-1",
            access_token="token",
        )

        assert not store.cache.has_human_request_cache("team-1", "task-1")
