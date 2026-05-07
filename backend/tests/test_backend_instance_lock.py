from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase

from backend.app.core.backend_instance import BackendInstanceAlreadyRunningError, acquire_backend_instance_lock


class BackendInstanceLockTests(TestCase):
    def test_second_backend_instance_lock_fails_until_first_is_released(self) -> None:
        with TemporaryDirectory() as tmpdir:
            settings = SimpleNamespace(
                backend_instance_lock_path=Path(tmpdir) / "backend.lock",
                repo_root=Path(tmpdir),
            )
            first_lock = acquire_backend_instance_lock(settings)
            try:
                with self.assertRaises(BackendInstanceAlreadyRunningError):
                    acquire_backend_instance_lock(settings)
            finally:
                first_lock.release()

            second_lock = acquire_backend_instance_lock(settings)
            second_lock.release()
