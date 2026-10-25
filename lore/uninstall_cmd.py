"""Remove the lore-solo command from this computer.

Personas, skills, and editor registrations stay. The older `lore` command in
~/.lore stays too.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from lore.install_cmd import find_uv, prefix


def tool_uninstall_args(uv: str) -> list[str]:
    return [uv, "tool", "uninstall", "--quiet", "lore-solo"]


def runtime_targets(home: Path | None = None) -> list[Path]:
    """Files and directories that belong to the lore-solo install."""
    root = prefix() if home is None else home
    binary = root / "bin" / "lore-solo"
    if os.name == "nt":
        binary = binary.with_suffix(".exe")
    return [
        binary,
        root / "tools" / "lore-solo",
        root / "site",
        root / "setup.log",
    ]


def remove_targets(paths: list[Path]) -> list[Path]:
    removed: list[Path] = []
    for path in paths:
        if path.is_symlink() or path.is_file():
            path.unlink()
            removed.append(path)
        elif path.is_dir():
            shutil.rmtree(path)
            removed.append(path)
    return removed


def _uv_missing(stderr: str, stdout: str) -> bool:
    return "is not installed" in f"{stderr}\n{stdout}"


def run(argv: list[str] | None = None) -> None:
    del argv
    home = prefix()
    uv = find_uv()
    uv_removed = False
    uv_error: subprocess.CompletedProcess[str] | None = None
    if uv is not None:
        env = os.environ.copy()
        env["UV_TOOL_DIR"] = str(home / "tools")
        env["UV_TOOL_BIN_DIR"] = str(home / "bin")
        result = subprocess.run(
            tool_uninstall_args(uv),
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            uv_removed = True
        elif not _uv_missing(result.stderr, result.stdout):
            uv_error = result
    removed = remove_targets(runtime_targets(home))
    if uv_removed or removed:
        print("Uninstalled. Personas, skills, and editor registrations stay on this computer.")
        return
    if uv_error is not None:
        sys.stderr.write(uv_error.stderr)
        sys.stderr.write(uv_error.stdout)
        raise SystemExit(uv_error.returncode)
    print("Lore Solo is not installed.")


if __name__ == "__main__":
    try:
        run(sys.argv[1:])
    except SystemExit as exc:
        code = exc.code
        raise SystemExit(0 if code is None else code) from None
