"""Stderr status helper."""

from __future__ import annotations

import io

from lore.cli_status import make_reporter, status
from lore.setup_cmd import format_banner, print_ready_banner


def test_status_skips_non_tty() -> None:
    buf = io.StringIO()
    status("hello", stream=buf)
    assert buf.getvalue() == ""


def test_status_force() -> None:
    buf = io.StringIO()
    status("hello", stream=buf, force=True)
    assert buf.getvalue() == "hello\n"


def test_reporter_and_banner(capsys) -> None:
    report = make_reporter(force=True)
    report("Downloading setup site…")
    print_ready_banner("test-key", 3000)
    captured = capsys.readouterr()
    assert "Downloading setup site…" in captured.err
    assert "Lore setup dashboard" in captured.err
    assert format_banner("test-key", 3000) in captured.out
