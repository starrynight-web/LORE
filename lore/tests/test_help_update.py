"""Help catalog and update helpers."""

from __future__ import annotations

from pathlib import Path

from lore.help_cmd import print_catalog
from lore.help_cmd import run as run_help
from lore.update_cmd import invalidate_site_cache, latest_spec


def test_help_catalog(capsys) -> None:
    assert run_help([]) == 0
    err = capsys.readouterr().err
    assert "lore-solo <command>" in err
    assert "update" in err
    assert "setup" in err


def test_help_unknown_command(capsys) -> None:
    assert run_help(["nope"]) == 2
    err = capsys.readouterr().err
    assert "unknown command" in err


def test_print_catalog_lists_update() -> None:
    import io

    buf = io.StringIO()
    print_catalog(stream=buf)
    assert "update" in buf.getvalue()


def test_latest_spec_is_unpinned() -> None:
    assert latest_spec(with_map=True) == "lore-solo[map]"
    assert latest_spec(with_map=False) == "lore-solo"


def test_invalidate_site_cache(tmp_path: Path) -> None:
    cache = tmp_path / "site"
    (cache / "0.2.1").mkdir(parents=True)
    (cache / "0.2.1" / "keep.txt").write_text("x", encoding="utf-8")
    invalidate_site_cache(cache)
    assert cache.is_dir()
    assert not (cache / "0.2.1").exists()
