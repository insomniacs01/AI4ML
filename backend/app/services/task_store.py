from __future__ import annotations

from backend.app.core.config import Settings
from backend.app.services.supabase_task_http import SupabaseTaskHttpClient
from backend.app.services.task_agent_repository import TaskAgentRepository
from backend.app.services.task_cache import TaskCache
from backend.app.services.task_human_request_repository import TaskHumanRequestRepository
from backend.app.services.task_local_storage import TaskLocalStorage
from backend.app.services.task_repository import TaskRepository
from backend.app.services.task_stage_repository import TaskStageRepository
from backend.app.services.task_store_agents import TaskStoreAgentMixin
from backend.app.services.task_store_cache import TaskStoreCacheMixin
from backend.app.services.task_store_human_requests import TaskStoreHumanRequestMixin
from backend.app.services.task_store_payloads import TaskPayloadMapper
from backend.app.services.task_store_runs import TaskStoreRunMixin
from backend.app.services.task_store_storage import TaskStoreStorageMixin
from backend.app.services.task_store_tasks import TaskStoreTaskMixin
from backend.app.services.task_token_repository import TaskTokenRepository


class TaskStore(
    TaskStoreTaskMixin,
    TaskStoreAgentMixin,
    TaskStoreHumanRequestMixin,
    TaskStoreRunMixin,
    TaskStoreStorageMixin,
    TaskStoreCacheMixin,
    TaskPayloadMapper,
):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.dataset_root_dir = settings.storage_dir
        self.run_output_dir = settings.run_output_dir
        self.cache = TaskCache(settings.repo_root / "storage" / "task_cache.sqlite3")
        self.http = SupabaseTaskHttpClient(settings)
        self.local_storage = TaskLocalStorage(
            dataset_root_dir=self.dataset_root_dir,
            run_output_dir=self.run_output_dir,
        )
        self.task_repository = TaskRepository(
            http=self.http,
            cache=self.cache,
            local_storage=self.local_storage,
        )
        self.stage_repository = TaskStageRepository(http=self.http, cache=self.cache)
        self.agent_repository = TaskAgentRepository(self.http)
        self.human_request_repository = TaskHumanRequestRepository(self.http)
        self.token_repository = TaskTokenRepository(self.http)
