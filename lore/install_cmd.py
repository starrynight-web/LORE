"""Install the lore-solo command on this computer.

`uvx lore-solo install` and the clone script both call this. The command lands
in ~/.lore/bin on macOS, Linux, and Windows.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def prefix() -> Path:
    return Path.home() / ".lore"


def installed_binary() -> Path:
    base = prefix() / "bin" / "lore-solo"
    if os.name == "nt":
        return base.with_suffix(".exe")
    return base


def find_uv() -> str | None:
    found = shutil.which("uv")
    if found:
        return found
    home = Path.home()
    names = ("uv.exe", "uv") if os.name == "nt" else ("uv",)
    bases = (
        home / ".local" / "bin",
        home / ".cargo" / "bin",
        home / "AppData" / "Local" / "uv",
    )
    for base in bases:
        for name in names:
            candidate = base / name
            if candidate.is_file():
                return str(candidate)
    return None


def checkout_root() -> Path | None:
    raw = os.environ.get("LORE_CHECKOUT", "").strip()
    if raw:
        root = Path(raw)
        if (root / "pyproject.toml").is_file():
            return root
        return None
    root = Path(__file__).resolve().parents[1]
    if (root / "pyproject.toml").is_file() and (root / "web" / "package.json").is_file():
        return root
    return None


def tool_install_args(uv: str, checkout: Path | None) -> list[str]:
    command = [uv, "tool", "install", "--quiet", "--python", "3.12", "--force"]
    if checkout is not None:
        command.extend(["--editable", str(checkout)])
    else:
        command.append("lore-solo")
    return command


def run(argv: list[str] | None = None) -> None:
    del argv
    uv = find_uv()
    if uv is None:
        raise SystemExit(
            "uv was not found. Install it, then run lore-solo install again.\n"
            "macOS and Linux: curl -LsSf https://astral.sh/uv/install.sh | sh\n"
            'Windows: powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"'
        )
    home = prefix()
    (home / "bin").mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["UV_TOOL_DIR"] = str(home / "tools")
    env["UV_TOOL_BIN_DIR"] = str(home / "bin")
    result = subprocess.run(
        tool_install_args(uv, checkout_root()),
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        sys.stderr.write(result.stdout)
        raise SystemExit(result.returncode)
    print("Installed. Run lore-solo setup to open the website.")


if __name__ == "__main__":
    try:
        run(sys.argv[1:])
    except SystemExit as exc:
        code = exc.code
        raise SystemExit(0 if code is None else code) from None
