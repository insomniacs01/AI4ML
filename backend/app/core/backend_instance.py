from __future__ import annotations

import atexit
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

if os.name == "nt":
    import msvcrt
else:
    import fcntl

from backend.app.core.config import Settings


class BackendInstanceAlreadyRunningError(RuntimeError):
    pass


@dataclass
class BackendInstanceLock:
    path: Path
    handle: TextIO
    released: bool = False

    def release(self) -> None:
        if self.released:
            return
        self.released = True
        if self.handle.closed:
            return
        try:
            if os.name == "nt":
                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        finally:
            self.handle.close()


def acquire_backend_instance_lock(settings: Settings) -> BackendInstanceLock:
    lock_path = settings.backend_instance_lock_path
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+", encoding="utf-8")
    try:
        _try_lock(handle)
    except OSError as exc:
        handle.close()
        raise BackendInstanceAlreadyRunningError(
            "AI4ML backend is already running for this workspace. "
            "Stop the existing uvicorn process on port 8000 before starting another one."
        ) from exc

    handle.seek(0)
    handle.truncate()
    handle.write(f"pid={os.getpid()}\nrepo={settings.repo_root}\n")
    handle.flush()
    lock = BackendInstanceLock(path=lock_path, handle=handle)
    atexit.register(lock.release)
    return lock


def _try_lock(handle: TextIO) -> None:
    if os.name == "nt":
        handle.seek(0)
        if not handle.read(1):
            handle.seek(0)
            handle.write("0")
            handle.flush()
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        return
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
