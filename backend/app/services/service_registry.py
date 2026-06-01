from __future__ import annotations

from functools import lru_cache

from backend.app.core.config import get_settings
from backend.app.services.connector_store import ConnectorStore
from backend.app.services.governance_store import GovernanceStore
from backend.app.services.task_human_collaboration import TaskHumanCollaborationService
from backend.app.services.task_store import TaskStore


@lru_cache
def get_task_store() -> TaskStore:
    return TaskStore(get_settings())


@lru_cache
def get_connector_store() -> ConnectorStore:
    return ConnectorStore(get_settings())


@lru_cache
def get_governance_store() -> GovernanceStore:
    return GovernanceStore(get_settings())


@lru_cache
def get_task_human_collaboration_service() -> TaskHumanCollaborationService:
    return TaskHumanCollaborationService(get_task_store())
