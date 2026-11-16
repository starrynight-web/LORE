"""Install the lore-solo command on this computer.

`uvx lore-solo install` and the clone script both call this. The command lands
in ~/.lore/bin on macOS, Linux, and Windows.

Default install tries the optional map extra (Graphify) via wheels. If no
prebuilt wheel matches, core Lore still installs so personas and MCP work.
Lore never compiles native extensions on install and never downloads
Visual Studio Build Tools.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from lore.cli_status import status
from lore.release import export_constraints, packaged_constraints, published_spec

PYTHON_PIN = "3.12"

_MAP_DEP_NAMES = ("graphifyy", "tree-sitter", "tree_sitter")

_RESOLUTION_MISS = (
    "no matching distribution",
    "no solution found",
    "no wheels with a matching",
    "only source distributions",
    "no compatible wheel",
    "not built for this platform",
    "a wheel is not available",
    "resolution failed",
)

_NETWORK_AUTH_MISS = (
    "401",
    "403",
    "unauthorized",
    "forbidden",
    "authentication",
    "permission denied",
    "eacces",
    "tls",
    "ssl",
    "certificate",
    "connection refused",
    "econnreset",
    "econnrefused",
    "timed out",
    "network",
    "proxy",
    "temporary failure in name resolution",
    "dns",
)

_CREDENTIAL_RE = re.compile(r"(://)[^/\s:@]+:[^/\s@]+@", re.IGNORECASE)
_SECRET_RE = re.compile(
    r"((?:api[_-]?key|access[_-]?token|token|secret|password|passwd|authorization)"
    r"[=:]\s*)(?:Bearer\s+)?[^\s&\"']+",
    re.IGNORECASE,
)
_BEARER_RE = re.compile(r"(Bearer\s+)[^\s\"']+", re.IGNORECASE)


def sanitize_output(text: str) -> str:
    """Strip credentials and tokens before echoing tool output."""
    text = _CREDENTIAL_RE.sub(r"\1***@", text)
    text = _SECRET_RE.sub(r"\1***", text)
    return _BEARER_RE.sub(r"\1***", text)


_REEXEC_ENV = "LORE_UPDATE_VIA_UVX"


def prefix() -> Path:
    return Path.home() / ".lore"


def tool_install_root() -> Path:
    """Environment `uv tool install` creates under the Lore prefix."""
    return prefix() / "tools" / "lore-solo"


def installed_binary() -> Path:
    base = prefix() / "bin" / "lore-solo"
    if os.name == "nt":
        return base.with_suffix(".exe")
    return base


def running_from_tool_env(executable: str | None = None) -> bool:
    """True when this process is the installed tool Python under ~/.lore/tools."""
    try:
        exe = Path(executable or sys.executable).resolve()
        root = tool_install_root().resolve()
    except OSError:
        return False
    return exe == root or root in exe.parents


def windows_self_replace_blocked() -> bool:
    """Windows locks the running python.exe, so in-place tool replace fails."""
    return os.name == "nt" and running_from_tool_env() and os.environ.get(_REEXEC_ENV) != "1"


def is_windows_file_lock_error(output: str) -> bool:
    text = output.lower()
    return os.name == "nt" and (
        "access is denied" in text
        or "os error 5" in text
        or ("cannot remove" in text and "scripts" in text)
    )


def self_replace_recovery_message() -> str:
    return (
        "Windows locked the installed lore-solo Python while it was running, so the "
        "upgrade could not finish.\n"
        "Repair from a fresh copy (does not lock ~/.lore\\tools):\n"
        "  uvx lore-solo install\n"
        "Then confirm with: lore-solo doctor"
    )


def handoff_via_uvx(uv: str, command: str, forwarded: list[str]) -> None:
    """Exit this process, then run `uvx lore-solo <command>` so Windows unlocks Scripts.

    The child sets LORE_UPDATE_VIA_UVX=1 and waits for this PID to exit before
    calling uv tool install against ~/.lore.
    """
    if command not in {"install", "update"}:
        raise ValueError(f"unsupported handoff command: {command}")
    status(
        "Windows is locking the installed Python while lore-solo runs; "
        "finishing in a fresh process…",
        force=True,
    )
    bin_dir = prefix() / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    script = bin_dir / f"_lore_solo_{command}_handoff.cmd"
    pid = os.getpid()
    home = prefix()
    child = subprocess.list2cmdline(
        [uv, "tool", "run", "--from", "lore-solo", "lore-solo", command, *forwarded]
    )
    body = "\r\n".join(
        [
            "@echo off",
            f"set {_REEXEC_ENV}=1",
            f'set "UV_TOOL_DIR={home / "tools"}"',
            f'set "UV_TOOL_BIN_DIR={home / "bin"}"',
            ":wait",
            f'tasklist /FI "PID eq {pid}" 2>nul | find "{pid}" >nul',
            "if not errorlevel 1 (",
            "  timeout /t 1 /nobreak >nul",
            "  goto wait",
            ")",
            child,
            "set EXITCODE=%ERRORLEVEL%",
            'del "%~f0" >nul 2>&1',
            "exit /b %EXITCODE%",
            "",
        ]
    )
    script.write_text(body, encoding="utf-8")
    # CREATE_NEW_CONSOLE keeps progress visible after this process exits.
    creationflags = 0
    if hasattr(subprocess, "CREATE_NEW_CONSOLE"):
        creationflags |= subprocess.CREATE_NEW_CONSOLE
    if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
        creationflags |= subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(
        ["cmd.exe", "/c", str(script)],
        cwd=str(bin_dir),
        close_fds=True,
        creationflags=creationflags,
    )
    status(
        f"{command.capitalize()} continuing in a new window. "
        "Run lore-solo doctor when it finishes.",
        force=True,
    )
    raise SystemExit(0)


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
    constraints: Path | None = None,
) -> list[str]:
    command = [
        uv,
        "tool",
        "install",
        "--quiet",
        "--managed-python",
        "--python",
        PYTHON_PIN,
        "--no-build",
        "--force",
    ]
    resolved = constraints if constraints is not None else packaged_constraints()
    if resolved is not None:
        command.extend(["-c", str(resolved)])
    if checkout is not None:
        requirement = str(checkout) + ("[map]" if with_map else "")
        command.extend(["--editable", requirement])
    else:
        command.append(published_spec(with_map=with_map))
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


def is_map_unavailable(output: str) -> bool:
    """True when only the optional map dependency could not install.

    Requires a map-specific package name (graphifyy or tree-sitter) alongside
    a native compile failure or a binary-only resolution miss. Network, auth,
    TLS, and permission problems are real failures, never a map fallback.
    """
    text = output.lower()
    if any(needle in text for needle in _NETWORK_AUTH_MISS):
        return False
    if not any(name in text for name in _MAP_DEP_NAMES):
        return False
    if is_native_build_failure(output):
        return True
    return any(needle in text for needle in _RESOLUTION_MISS)


def map_missing_message() -> str:
    return (
        "Installed Lore without the codebase map.\n"
        "Personas, skills, and MCP still work. The optional map dependencies\n"
        "did not install under the binary-only constraints on this machine.\n"
        "Retry: lore-solo install --map\n"
        "Or use the prebuilt Docker demo image for the full feature set."
    )


def strict_map_failure(map_related: bool) -> str:
    if map_related:
        return (
            "The optional map extra failed to install: the map-specific\n"
            "dependencies did not resolve or build on this machine.\n"
            "Run lore-solo install --no-map for core only, or use the Docker demo image."
        )
    return "lore-solo install --map failed; see the error above."


def _uv_env() -> dict[str, str]:
    home = prefix()
    (home / "bin").mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["UV_TOOL_DIR"] = str(home / "tools")
    env["UV_TOOL_BIN_DIR"] = str(home / "bin")
    return env


def _run_uv(
    uv: str,
    checkout: Path | None,
    *,
    with_map: bool,
    constraints: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        tool_install_args(uv, checkout, with_map=with_map, constraints=constraints),
        env=_uv_env(),
        check=False,
        capture_output=True,
        text=True,
    )


def _emit(result: subprocess.CompletedProcess[str]) -> None:
    for chunk in (result.stderr, result.stdout):
        if chunk:
            sys.stderr.write(sanitize_output(chunk))


def parse_install_flags(argv: list[str]) -> tuple[bool | None, list[str]]:
    """Return (with_map override, leftover). None means default try-map-then-fallback."""
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
    with_map, rest = parse_install_flags(args)
    if rest and rest[0] in {"-h", "--help"}:
        print(
            "usage: lore-solo install [--map|--no-map]\n"
            "  (default) try map extra via wheels; fall back to core on compile failure\n"
            "  --map      require map extra (fail if it cannot install)\n"
            "  --no-map   install core only (personas + MCP, no Graphify)\n"
            "  On Windows, prefer: uvx lore-solo install",
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
    if windows_self_replace_blocked():
        forwarded = []
        if with_map is True:
            forwarded.append("--map")
        elif with_map is False:
            forwarded.append("--no-map")
        handoff_via_uvx(uv, "install", forwarded)
    checkout = checkout_root()
    temp_export: Path | None = None
    try:
        packaged = packaged_constraints()
        if packaged is not None:
            constraints: Path | None = packaged
        elif checkout is not None and (checkout / "uv.lock").is_file():
            try:
                temp_export = export_constraints(uv, checkout)
            except (RuntimeError, OSError) as exc:
                raise SystemExit(
                    f"Could not build the release constraints: {sanitize_output(str(exc))}"
                ) from exc
            constraints = temp_export
        else:
            raise SystemExit(
                "The release constraints are missing from this install and cannot "
                "be exported here; installation would not be pinned. Re-run from a "
                "checkout with uv.lock or a published lore-solo wheel."
            )

        def fail_install(result: subprocess.CompletedProcess[str], extra: str = "") -> None:
            _emit(result)
            combined = f"{result.stderr}\n{result.stdout}"
            if is_windows_file_lock_error(combined):
                sys.stderr.write(self_replace_recovery_message() + "\n")
            if extra:
                sys.stderr.write(extra + "\n")
            raise SystemExit(result.returncode)

        if with_map is False:
            result = _run_uv(uv, checkout, with_map=False, constraints=constraints)
            if result.returncode != 0:
                fail_install(result)
            print("Installed (without map). Run lore-solo setup to open the website.")
            return

        if with_map is True:
            result = _run_uv(uv, checkout, with_map=True, constraints=constraints)
            if result.returncode != 0:
                combined = f"{result.stderr}\n{result.stdout}"
                fail_install(result, strict_map_failure(is_map_unavailable(combined)))
            print("Installed with map support. Run lore-solo setup to open the website.")
            return

        result = _run_uv(uv, checkout, with_map=True, constraints=constraints)
        if result.returncode == 0:
            print("Installed. Run lore-solo setup to open the website.")
            return

        combined = f"{result.stderr}\n{result.stdout}"
        if not is_map_unavailable(combined):
            fail_install(result)

        fallback = _run_uv(uv, checkout, with_map=False, constraints=constraints)
        if fallback.returncode != 0:
            _emit(result)
            fail_install(fallback)
        print(map_missing_message())
        print("Run lore-solo setup to open the website.")
    finally:
        if temp_export is not None:
            try:
                temp_export.unlink()
            except OSError:
                pass


if __name__ == "__main__":
    try:
        run(sys.argv[1:])
    except SystemExit as exc:
        code = exc.code
        raise SystemExit(0 if code is None else code) from None
