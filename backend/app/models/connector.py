from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class ConnectorWireApi(str, Enum):
    chat_completions = "chat_completions"
    responses = "responses"


class ConnectorTestStatus(str, Enum):
    untested = "untested"
    passed = "passed"
    failed = "failed"


class ConnectorCreateRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)
    endpoint_url: str | None = Field(default=None, max_length=500)
    base_url: str | None = Field(default=None, max_length=500)
    model_name: str = Field(min_length=1, max_length=200)
    api_key: str = Field(min_length=1, max_length=500)
    wire_api: Literal["auto", "chat_completions", "responses"] = "auto"


class ConnectorRecord(BaseModel):
    id: str
    team_id: str
    created_by: str
    display_name: str
    provider_type: str = "openai-compatible"
    endpoint_url: str | None = None
    base_url: str
    model_name: str
    wire_api: ConnectorWireApi
    api_key_masked: str
    is_active: bool = False
    last_tested_at: datetime | None = None
    last_test_status: ConnectorTestStatus = ConnectorTestStatus.untested
    last_test_detail: str | None = None
    created_at: datetime
    updated_at: datetime


class ConnectorListResponse(BaseModel):
    items: list[ConnectorRecord]


class ConnectorTestResponse(BaseModel):
    ok: bool
    detail: str
    model_listed: bool
    inference_ok: bool
    connector: ConnectorRecord


class ConnectorActivateResponse(BaseModel):
    detail: str
    scope: Literal["team_runtime"] = "team_runtime"
    connector: ConnectorRecord


class StoredConnectorRecord(BaseModel):
    id: str
    team_id: str
    created_by: str
    display_name: str
    provider_type: str = "openai-compatible"
    endpoint_url: str | None = None
    base_url: str
    model_name: str
    wire_api: ConnectorWireApi
    api_key: str
    is_active: bool = False
    last_tested_at: datetime | None = None
    last_test_status: ConnectorTestStatus = ConnectorTestStatus.untested
    last_test_detail: str | None = None
    created_at: datetime
    updated_at: datetime

    def to_public(self, *, is_active: bool | None = None) -> ConnectorRecord:
        resolved_is_active = self.is_active if is_active is None else is_active
        return ConnectorRecord(
            id=self.id,
            team_id=self.team_id,
            created_by=self.created_by,
            display_name=self.display_name,
            provider_type=self.provider_type,
            endpoint_url=self.endpoint_url,
            base_url=self.base_url,
            model_name=self.model_name,
            wire_api=self.wire_api,
            api_key_masked=_mask_api_key(self.api_key),
            is_active=resolved_is_active,
            last_tested_at=self.last_tested_at,
            last_test_status=self.last_test_status,
            last_test_detail=self.last_test_detail,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )


def _mask_api_key(api_key: str) -> str:
    trimmed = api_key.strip()
    if len(trimmed) <= 8:
        return "*" * len(trimmed)
    return f"{trimmed[:4]}...{trimmed[-4:]}"
