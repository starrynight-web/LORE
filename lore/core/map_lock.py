"""Advisory file lock serializing one map build per project.

The lock file is never deleted: a later worker reuses it, and OS process exit
releases the lock whether the worker finished or was killed.
"""

from __future__ import annotations

import errno
import os
from pathlib import Path
from typing import IO, Self

_CONTENTION = {errno.EACCES, errno.EAGAIN, errno.EDEADLK}


class MapLock:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._handle: IO[bytes] | None = None

    def acquire(self) -> bool:
        """False only on contention. Open/permission errors raise OSError."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self._path, "a+b")  # noqa: SIM115 - the lock lives until release()
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)  # type: ignore[attr-defined]
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            if exc.errno in _CONTENTION:
                return False
            raise
        self._handle = handle
        return True

    def release(self) -> None:
        handle, self._handle = self._handle, None
        if handle is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)  # type: ignore[attr-defined]
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            handle.close()

    def locked(self) -> bool:
        return self._handle is not None

    def __enter__(self) -> Self:
        if not self.acquire():
            raise BlockingIOError(f"the map build lock is held: {self._path}")
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()


def lock_held(path: Path) -> bool:
    """True when another process holds the lock right now."""
    probe = MapLock(path)
    if probe.acquire():
        probe.release()
        return False
    return True
