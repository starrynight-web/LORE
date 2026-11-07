"""Install the lore-solo command on this computer.

`uvx lore-solo install` and the clone script both call this. The command lands
in ~/.lore/bin on macOS, Linux, and Windows.

Default install tries the optional map extra (Graphify) via wheels. If that
native build fails, core Lore still installs so personas and MCP work. Lore
never downloads Visual Studio Build Tools.
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


def tool_install_args(
    uv: str,
    checkout: Path | None,
    *,
    with_map: bool = True,
) -> list[str]:
    command = [uv, "tool", "install", "--quiet", "--python", "3.12", "--force"]
    if checkout is not None:
        command.extend(["--editable", str(checkout)])
        if with_map:
            command.extend(["--extra", "map"])
    elif with_map:
        command.append("lore-solo[map]")
    else:
        command.append("lore-solo")
    return command


def is_native_build_failure(output: str) -> bool:
    """True when uv failed because a C extension had to compile and could not."""
    text = output.lower()
    needles = (
        "microsoft visual c++",
        "failed building wheel for tree-sitter",
        "error: microsoft visual c++",
        "failed to build 'tree-sitter",
        "failed to build tree-sitter",
        "error: command 'cl.exe' failed",
        "error: command 'cl' failed",
        "unable to find vcvarsall.bat",
        "linker `link.exe` not found",
        "failed to build installable wheels for some pyproject.toml based projects",
    )
    if any(needle in text for needle in needles):
        return True
    return bool(
        "tree-sitter" in text
        and ("failed to build" in text or "building wheel" in text or "error: command" in text)
    )


def map_fallback_message() -> str:
    return (
        "Installed Lore without the codebase map.\n"
        "Personas, skills, and MCP still work. Map support needs a Graphify wheel;\n"
        "if none matches this machine, a C toolchain is required to compile "
        "tree-sitter.\n"
        "On Windows that usually means Visual Studio Build Tools with the C++ "
        "workload (several GB) — only if you need the map and no wheel is "
        "available: https://visualstudio.microsoft.com/visual-cpp-build-tools/\n"
        "MinGW/gcc is not a reliable substitute for this Python extension.\n"
        "Later: lore-solo install --map\n"
        "Or skip the map attempt next time: lore-solo install --no-map"
    )


def _uv_env() -> dict[str, str]:
    home = prefix()
    (home / "bin").mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["UV_TOOL_DIR"] = str(home / "tools")
    env["UV_TOOL_BIN_DIR"] = str(home / "bin")
    return env


def _run_uv(uv: str, checkout: Path | None, *, with_map: bool) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        tool_install_args(uv, checkout, with_map=with_map),
        env=_uv_env(),
        check=False,
        capture_output=True,
        text=True,
    )


def parse_install_flags(argv: list[str]) -> tuple[bool | None, list[str]]:
    """Return (with_map override, leftover). None means default try-map-then-fallback."""
    with_map: bool | None = None
    rest: list[str] = []
    for arg in argv:
        if arg == "--map":
            with_map = True
        elif arg == "--no-map":
            with_map = False
        elif arg in {"-h", "--help"}:
            rest.append(arg)
        else:
            rest.append(arg)
    return with_map, rest


def run(argv: list[str] | None = None) -> None:
    args = list(argv or [])
    with_map, rest = parse_install_flags(args)
    if rest and rest[0] in {"-h", "--help"}:
        print(
            "usage: lore-solo install [--map|--no-map]\n"
            "  (default) try map extra via wheels; fall back to core on compile failure\n"
            "  --map      require map extra (fail if it cannot install)\n"
            "  --no-map   install core only (personas + MCP, no Graphify)",
            file=sys.stderr,
        )
        return
    if rest:
        raise SystemExit(f"unknown install option: {rest[0]}")

    uv = find_uv()
    if uv is None:
        raise SystemExit(
            "uv was not found. Install it, then run lore-solo install again.\n"
            "macOS and Linux: curl -LsSf https://astral.sh/uv/install.sh | sh\n"
            'Windows: powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"'
        )
    checkout = checkout_root()

    if with_map is False:
        result = _run_uv(uv, checkout, with_map=False)
        if result.returncode != 0:
            sys.stderr.write(result.stderr)
            sys.stderr.write(result.stdout)
            raise SystemExit(result.returncode)
        print("Installed (without map). Run lore-solo setup to open the website.")
        return

    if with_map is True:
        result = _run_uv(uv, checkout, with_map=True)
        if result.returncode != 0:
            combined = f"{result.stderr}\n{result.stdout}"
            if is_native_build_failure(combined):
                sys.stderr.write(map_fallback_message() + "\n")
                raise SystemExit(1)
            sys.stderr.write(result.stderr)
            sys.stderr.write(result.stdout)
            raise SystemExit(result.returncode)
        print("Installed with map support. Run lore-solo setup to open the website.")
        return

    result = _run_uv(uv, checkout, with_map=True)
    if result.returncode == 0:
        print("Installed. Run lore-solo setup to open the website.")
        return

    combined = f"{result.stderr}\n{result.stdout}"
    if not is_native_build_failure(combined):
        sys.stderr.write(result.stderr)
        sys.stderr.write(result.stdout)
        raise SystemExit(result.returncode)

    fallback = _run_uv(uv, checkout, with_map=False)
    if fallback.returncode != 0:
        sys.stderr.write(result.stderr)
        sys.stderr.write(result.stdout)
        sys.stderr.write(fallback.stderr)
        sys.stderr.write(fallback.stdout)
        raise SystemExit(fallback.returncode)
    print(map_fallback_message())
    print("Run lore-solo setup to open the website.")


if __name__ == "__main__":
    try:
        run(sys.argv[1:])
    except SystemExit as exc:
        code = exc.code
        raise SystemExit(0 if code is None else code) from None
