"""Upgrade the installed lore-solo tool and refresh the setup-site cache."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from lore import __version__
from lore.cli_status import status
from lore.install_cmd import (
    PYTHON_PIN,
    _emit,
    _uv_env,
    find_uv,
    is_map_unavailable,
    map_missing_message,
    prefix,
    strict_map_failure,
)
from lore.site_bundle import site_cache_root


def latest_spec(*, with_map: bool) -> str:
    extra = "[map]" if with_map else ""
    return f"lore-solo{extra}"


def _upgrade_args(uv: str, *, with_map: bool) -> list[str]:
    return [
        uv,
        "tool",
        "install",
        "--quiet",
        "--managed-python",
        "--python",
        PYTHON_PIN,
        "--no-build",
        "--force",
        latest_spec(with_map=with_map),
    ]


def _run_upgrade(uv: str, *, with_map: bool) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        _upgrade_args(uv, with_map=with_map),
        env=_uv_env(),
        check=False,
        capture_output=True,
        text=True,
    )


def invalidate_site_cache(root: Path | None = None) -> Path:
    """Drop cached setup-site bundles so the next setup matches the new version."""
    cache = root or site_cache_root()
    if cache.is_dir():
        shutil.rmtree(cache, ignore_errors=True)
    cache.mkdir(parents=True, exist_ok=True)
    return cache


def parse_update_flags(argv: list[str]) -> tuple[bool | None, list[str]]:
    with_map: bool | None = None
    seen: set[bool] = set()
    rest: list[str] = []
    for arg in argv:
        if arg == "--map":
            with_map = True
            seen.add(True)
        elif arg == "--no-map":
            with_map = False
            seen.add(False)
        elif arg in {"-h", "--help"}:
            rest.append(arg)
        else:
            rest.append(arg)
    if len(seen) > 1:
        raise SystemExit("conflicting options: --map and --no-map")
    return with_map, rest


def run(argv: list[str] | None = None) -> None:
    args = list(argv or [])
    with_map, rest = parse_update_flags(args)
    if rest and rest[0] in {"-h", "--help"}:
        print(
            "usage: lore-solo update [--map|--no-map]\n"
            "  Upgrade lore-solo from PyPI and clear the cached setup site.\n"
            "  (default) try map extra via wheels; fall back to core on compile failure\n"
            "  --map      require map extra (fail if it cannot install)\n"
            "  --no-map   upgrade core only (personas + MCP, no Graphify)",
            file=sys.stderr,
        )
        return
    if rest:
        raise SystemExit(f"unknown update option: {rest[0]}")

    status(f"Checking for lore-solo updates (current {__version__})…", force=True)
    uv = find_uv()
    if uv is None:
        raise SystemExit(
            "uv was not found. Install it, then run lore-solo update again.\n"
            "macOS and Linux: curl -LsSf https://astral.sh/uv/install.sh | sh\n"
            'Windows: powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"'
        )

    bin_dir = prefix() / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)

    def finish_ok(message: str) -> None:
        status("Refreshing setup site cache…", force=True)
        invalidate_site_cache()
        status(message, force=True)
        status("Run lore-solo setup to open the website.", force=True)

    if with_map is False:
        status("Upgrading lore-solo (core only)…", force=True)
        result = _run_upgrade(uv, with_map=False)
        if result.returncode != 0:
            _emit(result)
            raise SystemExit(result.returncode)
        finish_ok("Updated (without map).")
        return

    if with_map is True:
        status("Upgrading lore-solo (with map)…", force=True)
        result = _run_upgrade(uv, with_map=True)
        if result.returncode != 0:
            _emit(result)
            combined = f"{result.stderr}\n{result.stdout}"
            sys.stderr.write(strict_map_failure(is_map_unavailable(combined)) + "\n")
            raise SystemExit(result.returncode)
        finish_ok("Updated with map support.")
        return

    status("Upgrading lore-solo…", force=True)
    result = _run_upgrade(uv, with_map=True)
    if result.returncode == 0:
        finish_ok("Updated.")
        return

    combined = f"{result.stderr}\n{result.stdout}"
    if not is_map_unavailable(combined):
        _emit(result)
        raise SystemExit(result.returncode)

    status("Map extra unavailable; upgrading core only…", force=True)
    fallback = _run_upgrade(uv, with_map=False)
    if fallback.returncode != 0:
        _emit(result)
        _emit(fallback)
        raise SystemExit(fallback.returncode)
    print(map_missing_message(), file=sys.stderr)
    finish_ok("Updated (without map).")


if __name__ == "__main__":
    try:
        run(sys.argv[1:])
    except SystemExit as exc:
        code = exc.code
        raise SystemExit(0 if code is None else code) from None
