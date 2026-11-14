"""Plain-text stderr status lines for lore-solo commands."""

from __future__ import annotations

import sys
from collections.abc import Callable
from typing import TextIO


def status(message: str, *, stream: TextIO[str] | None = None, force: bool = False) -> None:
    """Print a status line to stderr when attached to a TTY (or when forced)."""
    out = stream if stream is not None else sys.stderr
    if not force and not out.isatty():
        return
    print(message, file=out, flush=True)


def make_reporter(*, force: bool = False) -> Callable[[str], None]:
    """Return an `on_status` callback that uses the shared status helper."""

    def report(message: str) -> None:
        status(message, force=force)

    return report
