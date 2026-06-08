from __future__ import annotations

import pytest
from fastapi import HTTPException, status

from backend.app.api.errors import raise_store_http_error


def test_store_http_error_maps_permission_errors_to_forbidden() -> None:
    with pytest.raises(HTTPException) as raised:
        raise_store_http_error(PermissionError("team access denied"))

    assert raised.value.status_code == status.HTTP_403_FORBIDDEN
    assert raised.value.detail == "team access denied"
    assert raised.value.headers is None


def test_store_http_error_keeps_connection_errors_as_bad_gateway() -> None:
    with pytest.raises(HTTPException) as raised:
        raise_store_http_error(ConnectionError("storage unavailable"))

    assert raised.value.status_code == status.HTTP_502_BAD_GATEWAY
