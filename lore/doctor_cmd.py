"""Check whether this computer can run Lore Solo.

`uvx lore-solo doctor` works before install. It reports what is present, where
to get anything missing for this OS, and which features that gap blocks.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from lore.connect import host_system
from lore.install_cmd import find_uv, installed_binary, prefix, sanitize_output

MIN_NODE_MAJOR = 22
SETUP_NODE_MAJOR = 22


@dataclass(frozen=True)
class Check:
    """One prerequisite line for the doctor report."""

    id: str
    name: str
    ok: bool
    required: bool
    detail: str
    get_it: str
    without_it: str


def detect_os(value: str | None = None) -> str:
    """Return linux, darwin, or windows."""
    return host_system(value)


def os_label(system: str) -> str:
    return {"darwin": "macOS", "windows": "Windows", "linux": "Linux"}.get(system, system)


def uv_install_hint(system: str) -> str:
    if system == "windows":
        return (
            "Install uv: "
            'powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"\n'
            "    Docs: https://docs.astral.sh/uv/getting-started/installation/"
        )
    return (
        "Install uv: curl -LsSf https://astral.sh/uv/install.sh | sh\n"
        "    Docs: https://docs.astral.sh/uv/getting-started/installation/"
    )


def node_install_hint(system: str) -> str:
    if system == "windows":
        return (
            "Install Node.js 22 from https://nodejs.org/download/release/latest-v22.x/\n"
            "    Pick a 22.x release explicitly — the setup site requires Node 22"
        )
    if system == "darwin":
        return (
            "Install Node.js 22: brew install node@22\n"
            "    node@22 is keg-only — add $(brew --prefix node@22)/bin to PATH"
        )
    return (
        "Install Node.js 22 from https://nodejs.org/download/release/latest-v22.x/\n"
        "    Or install a 22.x release via your package manager / nvm / fnm"
    )


def map_install_hint(system: str) -> str:
    del system
    return (
        "Install map support: lore-solo install --map (or uvx lore-solo install --map)\n"
        "    The map extra needs prebuilt binary packages for this platform; "
        "Lore does not compile native extensions on install.\n"
        "    The prebuilt Docker demo image carries the full feature set. "
        "Core Lore still works without the map."
    )


def _run_version(command: list[str]) -> str | None:
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = (result.stdout or result.stderr or "").strip()
    return text.splitlines()[0].strip() if text else None


def _parse_node_major(version_line: str) -> int | None:
    raw = version_line.strip().lstrip("vV")
    if not raw:
        return None
    head = raw.split(".", 1)[0]
    try:
        return int(head)
    except ValueError:
        return None


def check_uv(system: str, uv_path: str | None = None) -> Check:
    found = uv_path if uv_path is not None else find_uv()
    if found:
        version = _run_version([found, "--version"]) or "found"
        return Check(
            id="uv",
            name="uv",
            ok=True,
            required=True,
            detail=f"{version} ({found})",
            get_it="",
            without_it="",
        )
    return Check(
        id="uv",
        name="uv",
        ok=False,
        required=True,
        detail="not found",
        get_it=uv_install_hint(system),
        without_it=(
            "You cannot run `uvx lore-solo …` or `lore-solo install`. "
            "Clone install scripts also need uv."
        ),
    )


def check_python() -> Check:
    """Implementation, version, and architecture of this interpreter."""
    detail = (
        f"{platform.python_implementation()} {platform.python_version()} "
        f"({platform.machine()})"
    )
    return Check(
        id="python",
        name="Python",
        ok=True,
        required=True,
        detail=detail,
        get_it="",
        without_it="",
    )


def check_node(system: str, *, required: bool = True, minimum: int = MIN_NODE_MAJOR) -> Check:
    node = shutil.which("node")
    if node is None:
        return Check(
            id="node",
            name="Node.js",
            ok=False,
            required=required,
            detail="not found",
            get_it=node_install_hint(system),
            without_it=(
                "You cannot open the setup website (`lore-solo setup`). "
                "MCP/agent tools still work after install if personas already exist."
            ),
        )
    version = _run_version([node, "--version"]) or "found"
    major = _parse_node_major(version)
    if major is None or major < minimum:
        return Check(
            id="node",
            name="Node.js",
            ok=False,
            required=required,
            detail=f"{version} ({node}) — need {minimum}+",
            get_it=node_install_hint(system),
            without_it=(
                "The setup website cannot start. "
                "Upgrade Node.js, then run `lore-solo setup` again."
            ),
        )
    return Check(
        id="node",
        name="Node.js",
        ok=True,
        required=required,
        detail=f"{version} ({node})",
        get_it="",
        without_it="",
    )


def check_npm(system: str, *, required: bool = True) -> Check:
    npm = shutil.which("npm")
    if npm is None:
        return Check(
            id="npm",
            name="npm",
            ok=False,
            required=required,
            detail="not found",
            get_it=(
                "npm ships with Node.js. Reinstall Node.js 22 so `npm` is on PATH.\n"
                f"    {node_install_hint(system)}"
            ),
            without_it=(
                "Only needed to build the setup site from a source checkout. "
                "Published site bundles run without npm."
            ),
        )
    version = _run_version([npm, "--version"]) or "found"
    return Check(
        id="npm",
        name="npm",
        ok=True,
        required=required,
        detail=f"{version} ({npm})",
        get_it="",
        without_it="",
    )


def check_lore_command() -> Check:
    binary = installed_binary()
    if binary.is_file():
        return Check(
            id="lore-solo",
            name="lore-solo command",
            ok=True,
            required=False,
            detail=str(binary),
            get_it="",
            without_it="",
        )
    which = shutil.which("lore-solo")
    if which:
        return Check(
            id="lore-solo",
            name="lore-solo command",
            ok=True,
            required=False,
            detail=which,
            get_it="",
            without_it="",
        )
    return Check(
        id="lore-solo",
        name="lore-solo command",
        ok=False,
        required=False,
        detail="not installed in ~/.lore/bin",
        get_it="Install once: uvx lore-solo install",
        without_it=(
            "Editors and scripts that expect `~/.lore/bin/lore-solo` will not find it. "
            "You can still use `uvx lore-solo …` for install, setup, connect, and mcp."
        ),
    )


def check_map(system: str) -> Check:
    try:
        from lore.setup.graph_job import _graphify

        exe = _graphify()
    except (OSError, RuntimeError, ImportError):
        return Check(
            id="map",
            name="Codebase map (Graphify)",
            ok=False,
            required=False,
            detail="not available in this environment",
            get_it=map_install_hint(system),
            without_it=(
                "You cannot build or refresh `graphify-out/` "
                "(`lore-solo map`, setup Codebase page, `map_codebase`). "
                "Personas, skills, and `get_context` skill routing still work."
            ),
        )
    return Check(
        id="map",
        name="Codebase map (Graphify)",
        ok=True,
        required=False,
        detail=sanitize_output(str(exe)),
        get_it="",
        without_it="",
    )


def check_home_writable() -> Check:
    home = prefix()
    try:
        home.mkdir(parents=True, exist_ok=True)
        probe = home / ".doctor-write-check"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        return Check(
            id="home-write",
            name="Write access to ~/.lore",
            ok=False,
            required=True,
            detail=str(exc),
            get_it=(
                "Use a user account that can write under your home directory, "
                "or set HOME to a writable folder before install."
            ),
            without_it=(
                "Install, setup cache, and the local `lore-solo` command cannot be stored."
            ),
        )
    return Check(
        id="home-write",
        name="Write access to ~/.lore",
        ok=True,
        required=True,
        detail=str(home),
        get_it="",
        without_it="",
    )


def check_editors(system: str, home: Path | None = None) -> Check:
    root = home if home is not None else Path.home()
    from lore.connect import _targets

    found = [label for label, _path, _key, _editor in _targets(root, system)]
    if found:
        return Check(
            id="editors",
            name="Coding editors",
            ok=True,
            required=False,
            detail=", ".join(found),
            get_it="",
            without_it="",
        )
    return Check(
        id="editors",
        name="Coding editors",
        ok=False,
        required=False,
        detail="none detected yet",
        get_it=(
            "Install Cursor, VS Code, Claude Code, Codex, Antigravity, or Devin, "
            "then run `lore-solo connect`."
        ),
        without_it=(
            "`lore-solo connect` has nowhere to register MCP. "
            "You can still write a project `.cursor/mcp.json` from the setup Connect page."
        ),
    )


def check_skillspector() -> Check:
    from lore.core.governance import skillspector

    if skillspector.available():
        return Check(
            id="skillspector",
            name="SkillSpector (optional scan)",
            ok=True,
            required=False,
            detail=skillspector.skillspector_path() or "found",
            get_it="",
            without_it="",
        )
    return Check(
        id="skillspector",
        name="SkillSpector (optional scan)",
        ok=False,
        required=False,
        detail="not on PATH",
        get_it=(
            "Optional: uv tool install git+https://github.com/NVIDIA/skillspector.git\n"
            "    Lore still scans with built-in ATR rules when SkillSpector is missing."
        ),
        without_it=(
            "Approve still runs the built-in ATR static scanner. "
            "NVIDIA SkillSpector enrichment is skipped."
        ),
    )


def check_knowledge() -> Check:
    from lore.core.governance import freshness_of, governance_summary
    from lore.core.paths import LoreNotFound, find_project
    from lore.core.personas import list_personas, list_skill_files

    try:
        project = find_project(Path.cwd())
    except LoreNotFound:
        return Check(
            id="knowledge",
            name="Persona library / .lore",
            ok=False,
            required=False,
            detail="no .lore in this folder",
            get_it="Run lore-solo setup in a project, or open a folder that already has .lore.",
            without_it="Doctor cannot report skill scan or freshness counts for this directory.",
        )
    personas = list_personas(project)
    skills = [doc for _path, doc in list_skill_files(project)]
    high = 0
    aging = 0
    for doc in skills:
        summary = governance_summary(doc)
        if summary["highest_severity"] in {"critical", "high"}:
            high += 1
        if summary["freshness"] == "aging" or freshness_of(doc) == "aging":
            aging += 1
    drafts = sum(1 for doc in personas + skills if doc.get("status") != "stable")
    stable = sum(1 for doc in personas + skills if doc.get("status") == "stable")
    return Check(
        id="knowledge",
        name="Knowledge governance",
        ok=high == 0,
        required=False,
        detail=(
            f"{len(personas)} personas, {len(skills)} skills "
            f"({stable} stable, {drafts} draft); "
            f"{high} with high/critical findings; {aging} aging"
        ),
        get_it="Run: lore-solo govern scan   and review findings before approve.",
        without_it=(
            "Skills with unresolved high/critical findings should not be approved "
            "without accept_risk."
        ),
    )


def gather_checks(system: str | None = None, *, for_setup: bool = False) -> list[Check]:
    host = detect_os(system)
    if for_setup:
        return [
            check_python(),
            check_node(host, required=True, minimum=SETUP_NODE_MAJOR),
            check_npm(host, required=False),
            check_home_writable(),
            check_lore_command(),
        ]
    return [
        check_python(),
        check_uv(host),
        check_node(host, required=False),
        check_npm(host, required=False),
        check_home_writable(),
        check_lore_command(),
        check_map(host),
        check_editors(host),
        check_skillspector(),
        check_knowledge(),
    ]


def format_report(checks: list[Check], system: str) -> str:
    lines = [
        f"Lore Solo doctor ({os_label(system)} · {platform.machine()})",
        "",
    ]
    for check in checks:
        mark = "ok" if check.ok else ("MISSING" if check.required else "optional")
        lines.append(f"[{mark}] {check.name}: {check.detail}")
        if not check.ok:
            for index, part in enumerate(check.get_it.splitlines()):
                prefix = "    → " if index == 0 else "      "
                lines.append(f"{prefix}{part}")
            if check.without_it:
                lines.append(f"    Without this: {check.without_it}")
    required_bad = [c for c in checks if c.required and not c.ok]
    optional_bad = [c for c in checks if not c.required and not c.ok]
    lines.append("")
    if not required_bad and not optional_bad:
        lines.append("All checks passed. You can run: lore-solo install && lore-solo setup")
    elif not required_bad:
        lines.append(
            "Required tools are present. Optional gaps above only limit map or editor connect."
        )
        lines.append("Next: uvx lore-solo install   then   uvx lore-solo setup")
    else:
        names = ", ".join(c.name for c in required_bad)
        lines.append(f"Fix required tools first: {names}")
        lines.append("Then: uvx lore-solo install   and   uvx lore-solo setup")
    return "\n".join(lines) + "\n"


def run(argv: list[str] | None = None) -> int:
    args = list(argv or [])
    if args and args[0] in {"-h", "--help"}:
        print(
            "usage: lore-solo doctor [--setup]\n"
            "Check prerequisites on this computer and print OS-specific install hints.\n"
            "  --setup   check the setup-site requirements (Node.js 22)",
            file=sys.stderr,
        )
        return 0
    for_setup = "--setup" in args
    rest = [arg for arg in args if arg != "--setup"]
    if rest:
        print(f"unknown doctor option: {rest[0]}", file=sys.stderr)
        return 2
    system = detect_os()
    checks = gather_checks(system, for_setup=for_setup)
    sys.stdout.write(format_report(checks, system))
    if any(c.required and not c.ok for c in checks):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
