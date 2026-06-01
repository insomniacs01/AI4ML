from __future__ import annotations

import sys

from backend.app.application import create_app
from backend.app.core.backend_instance import BackendInstanceAlreadyRunningError, acquire_backend_instance_lock
from backend.app.core.config import get_settings


settings = get_settings()
try:
    _backend_instance_lock = acquire_backend_instance_lock(settings)
except BackendInstanceAlreadyRunningError as exc:
    print(f"AI4ML backend startup blocked: {exc}", file=sys.stderr)
    raise SystemExit(1) from exc


app = create_app(settings)
