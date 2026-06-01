from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any


_CACHE_REFRESH_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="task-cache-refresh")
logger = logging.getLogger(__name__)


class TaskStoreCacheMixin:
    def _refresh_task_list_cache_in_background(
        self,
        team_id: str,
        *,
        access_token: str,
        lightweight: bool,
        limit: int | None,
        offset: int,
    ) -> None:
        _CACHE_REFRESH_EXECUTOR.submit(
            self._refresh_task_list_cache,
            team_id,
            access_token,
            lightweight,
            limit,
            offset,
        )

    def _refresh_task_list_cache(
        self,
        team_id: str,
        access_token: str,
        lightweight: bool,
        limit: int | None,
        offset: int,
    ) -> None:
        try:
            self.__class__(self.settings).list_tasks(
                team_id,
                access_token=access_token,
                lightweight=lightweight,
                limit=limit,
                offset=offset,
                prefer_cache=False,
                allow_stale_cache=False,
            )
        except Exception as exc:
            logger.debug("Task list cache refresh failed for team %s: %s", team_id, exc)
            return

    def _refresh_task_cache_in_background(self, team_id: str, task_id: str, *, access_token: str) -> None:
        _CACHE_REFRESH_EXECUTOR.submit(self._refresh_task_cache, team_id, task_id, access_token)

    def _refresh_task_cache(self, team_id: str, task_id: str, access_token: str) -> None:
        try:
            self.__class__(self.settings).get_task(
                team_id,
                task_id,
                access_token=access_token,
                prefer_cache=False,
                allow_stale_cache=False,
            )
        except Exception as exc:
            logger.debug("Task cache refresh failed for task %s/%s: %s", team_id, task_id, exc)
            return

    def _refresh_stage_records_cache_in_background(self, team_id: str, task_id: str, *, access_token: str) -> None:
        _CACHE_REFRESH_EXECUTOR.submit(self._refresh_stage_records_cache, team_id, task_id, access_token)

    def _refresh_stage_records_cache(self, team_id: str, task_id: str, access_token: str) -> None:
        try:
            self.__class__(self.settings).list_stage_records(
                team_id,
                task_id,
                access_token=access_token,
                prefer_cache=False,
                allow_stale_cache=False,
            )
        except Exception as exc:
            logger.debug("Stage records cache refresh failed for task %s/%s: %s", team_id, task_id, exc)
            return

    def _request_json(
        self,
        *,
        path: str,
        access_token: str,
        method: str = "GET",
        body: dict[str, Any] | None = None,
        expect_json: bool = True,
        prefer: str | None = None,
    ) -> Any:
        return self.http.request_json(
            path=path,
            access_token=access_token,
            method=method,
            body=body,
            expect_json=expect_json,
            prefer=prefer,
        )

    def _ensure_configured(self) -> None:
        self.http._ensure_configured()  # noqa: SLF001
