from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import socket
import time

from knight.worker.config import settings


class RepositoryLockTimeoutError(TimeoutError):
    """Raised when a repository lock cannot be acquired in time."""


class RepositoryLockManager:
    def __init__(
        self,
        timeout_seconds: int | None = None,
        poll_interval_seconds: float | None = None,
    ) -> None:
        self.timeout_seconds = (
            timeout_seconds
            if timeout_seconds is not None
            else settings.worker_repo_lock_timeout_seconds
        )
        self.poll_interval_seconds = (
            poll_interval_seconds
            if poll_interval_seconds is not None
            else settings.worker_repo_lock_poll_interval_seconds
        )

    @contextmanager
    def acquire(self, lock_path: str | Path):
        path = Path(lock_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            deadline = time.monotonic() + self.timeout_seconds
            while True:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise RepositoryLockTimeoutError(
                            f"timed out acquiring repository lock: {path}"
                        )
                    time.sleep(self.poll_interval_seconds)

            try:
                handle.seek(0)
                handle.truncate()
                handle.write(
                    json.dumps(
                        {
                            "pid": os.getpid(),
                            "hostname": socket.gethostname(),
                            "acquired_at": time.time(),
                        }
                    )
                )
                handle.flush()
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
