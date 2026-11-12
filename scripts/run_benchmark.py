"""Timed Antigravity (agy) comparison, quality bake-off, and Lore invocation checks.

    .venv/bin/python scripts/run_benchmark.py confirm
    .venv/bin/python scripts/run_benchmark.py confirm-quality
    .venv/bin/python scripts/run_benchmark.py quality
    .venv/bin/python scripts/run_benchmark.py solution

Uses Gemini via agy (default model gemini-3.8-flash-medium). Full event logs stay
in `.tmp/`. Summaries under examples/bench-library do not include credentials.
Primary Solo claim is quality (see docs/solo/QUALITY_PLAN.md), not token cuts.
"""

from __future__ import annotations

import ast
import hashlib
import json
import math
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Self

from lore.core.instructions import STANDING_INSTRUCTIONS

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "examples" / "bench-app"
QUALITY_APP = ROOT / "examples" / "bench-quality-app"
LIBRARY = ROOT / "examples" / "bench-library"
PACK = ROOT / "examples" / "persona-pack"
TMP = ROOT / ".tmp" / "bench-runs"
LORE = ROOT / ".venv" / "bin" / "lore-solo"
GRAPHIFY = ROOT / ".venv" / "bin" / "graphify"
MODEL = "gemini-3.8-flash-medium"
GLOBAL_MCP = Path.home() / ".gemini" / "config" / "mcp_config.json"
MCP_CACHE_ROOTS = (
    Path.home() / ".gemini" / "antigravity-cli" / "mcp",
    Path.home() / ".gemini" / "antigravity" / "mcp",
)
# Workspace MCP name matches product connect / FastMCP (lore-solo).
WORKSPACE_MCP_NAME = "lore-solo"
LORE_TOOLS = (
    "get_context",
    "map_codebase",
    "check_applied",
    "log_decision",
    "get_skill",
    "list_personas",
    "locate",
    "map_status",
)
CODING_MCP_TOOLS = ["get_context", "get_skill", "map_codebase", "check_applied", "log_decision"]
QUALITY_SCENARIOS = (
    "wrong-file", "a11y-label", "api-shape", "full-skill", "new-file",
    "cross-file", "stale-map", "no-map",
)
# Practical baselines: explicit user pick (right skills) and agent-chosen from disk.
QUALITY_USER_PICKS: dict[str, tuple[str, ...]] = {
    "wrong-file": (
        ".lore/skills/frontend-engineer/frontend-design@v1.md",
        ".lore/skills/frontend-engineer/vercel-react-best-practices@v1.md",
    ),
    "a11y-label": (
        ".lore/skills/accessibility-engineer/web-a11y-authoring@v1.md",
        ".lore/skills/accessibility-engineer/web-a11y-review@v1.md",
    ),
    "api-shape": (
        ".lore/skills/backend-engineer/create-a-backend@v1.md",
        ".lore/skills/backend-engineer/supabase-postgres-best-practices@v1.md",
    ),
    "full-skill": (".lore/skills/frontend-engineer/release-stamp@v1.md",),
    "new-file": (".lore/skills/backend-engineer/create-a-backend@v1.md",),
    "cross-file": (".lore/skills/backend-engineer/create-a-backend@v1.md",),
    "stale-map": (".lore/skills/frontend-engineer/frontend-design@v1.md",),
    "no-map": (".lore/skills/frontend-engineer/frontend-design@v1.md",),
}
AGENT_CHOSEN_RULE = (
    "Skills for this project live under .lore/skills/. "
    "Before editing, choose and read whichever skill files you think apply to the task. "
    "Do not call Lore tools. Do not read every skill file — pick what fits.\n"
)
# Legacy paste-all binder (retired as a primary arm; kept for diagnostics only).
PASTE_STABLE_RULE = (
    "Before editing, read only these files, then do the task. Do not call Lore tools:\n"
    ".lore/skills/frontend-engineer/frontend-design@v1.md\n"
    ".lore/skills/frontend-engineer/tailwind-best-practices@v1.md\n"
    ".lore/skills/frontend-engineer/shadcn-best-practices@v1.md\n"
    ".lore/skills/frontend-engineer/vercel-react-best-practices@v1.md\n"
    ".lore/skills/frontend-engineer/design-taste-frontend@v1.md\n"
    ".lore/skills/frontend-engineer/minimalist-ui@v1.md\n"
    ".lore/skills/accessibility-engineer/web-a11y-authoring@v1.md\n"
    ".lore/skills/accessibility-engineer/web-a11y-review@v1.md\n"
    ".lore/skills/backend-engineer/create-a-backend@v1.md\n"
    ".lore/skills/backend-engineer/supabase-postgres-best-practices@v1.md\n"
    ".lore/skills/reviewer/review-security@v1.md\n"
    ".lore/skills/reviewer/web-design-guidelines@v1.md\n"
)


def _user_picked_rule(scenario: str) -> str:
    picks = QUALITY_USER_PICKS.get(scenario) or ()
    listed = "\n".join(picks)
    return (
        "Before editing, read only these user-selected skill files, then do the task. "
        "Do not call Lore tools:\n"
        f"{listed}\n"
    )


def main() -> None:
    _require_agent_approval()
    command = sys.argv[1] if len(sys.argv) > 1 else "bench"
    if command == "confirm":
        raise SystemExit(confirm())
    if command == "confirm-quality":
        raise SystemExit(confirm_quality())
    if command == "quality":
        runs = int(sys.argv[2]) if len(sys.argv) > 2 else 1
        raise SystemExit(quality(runs=runs))
    if command == "bench":
        raise SystemExit(bench())
    if command == "solution":
        raise SystemExit(
            bench(
                3,
                LIBRARY / "results-agy-solution.json",
                note=(
                    "agy + gemini-3.8-flash-medium. One get_context returns matching "
                    "skill summaries and files."
                ),
                label="agy-solution-",
            )
        )
    if command == "diagnose":
        raise SystemExit(diagnose())
    if command == "stable":
        raise SystemExit(stable())
    if command == "once":
        raise SystemExit(
            bench(
                1,
                LIBRARY / "results-agy-rerun.json",
                label="agy-rerun-",
                note="Single-run agy rerun.",
            )
        )
    print(
        "use confirm, confirm-quality, quality, bench, solution, diagnose, stable, or once",
        file=sys.stderr,
    )
    raise SystemExit(2)


def confirm() -> int:
    TMP.mkdir(parents=True, exist_ok=True)
    with _global_lore_disabled():
        _clear_agy_mcp_cache("lore", WORKSPACE_MCP_NAME)
        work = TMP / "invoke"
        if work.exists():
            shutil.rmtree(work)
        shutil.copytree(PACK, work, ignore=shutil.ignore_patterns(".git"))
        (work / "AGENTS.md").write_text(STANDING_INSTRUCTIONS + "\n", encoding="utf-8")
        _write_workspace_mcp(work, arm="lore", library=work)
        log = TMP / "invoke.jsonl"
        started = time.monotonic()
        code = _agy(
            work,
            "In src/ui/Button.tsx, change the button text to Ready. Open only the files you need.",
            log=log,
            timeout=300,
        )
        elapsed = round(time.monotonic() - started, 1)
        decisions = sorted((work / ".lore" / "decisions").glob("dec-*.md"))
        events = _events(log)
        tools = _tool_order(events)
        mcp_ok = _mcp_get_context_ok(events)
        mcp_error = _mcp_get_context_error(events)
        called = bool(decisions) or mcp_ok
        summary = {
            "runner": "agy",
            "model": MODEL,
            "mcp_server": WORKSPACE_MCP_NAME,
            "exit": code,
            "seconds": elapsed,
            "decisions": [path.name for path in decisions],
            "tools": tools,
            "mcp_get_context_ok": mcp_ok,
            "mcp_get_context_error": mcp_error,
            "called_lore_before_narration": called,
            "event_types": sorted(
                {str(event.get("event") or event.get("type")) for event in events if isinstance(event, dict)}
            ),
        }
        _write(LIBRARY / "invocation-agy.json", summary)
        print(json.dumps(summary, indent=2))
        return 0 if called else 1


def confirm_quality() -> int:
    """Smoke the full quality loop: get_context, check_applied, log_decision."""
    TMP.mkdir(parents=True, exist_ok=True)
    with _global_lore_disabled():
        _clear_agy_mcp_cache("lore", WORKSPACE_MCP_NAME)
        work = TMP / "invoke-quality"
        if work.exists():
            shutil.rmtree(work)
        shutil.copytree(PACK, work, ignore=shutil.ignore_patterns(".git"))
        (work / "AGENTS.md").write_text(STANDING_INSTRUCTIONS + "\n", encoding="utf-8")
        _write_workspace_mcp(work, arm="lore", library=work)
        log = TMP / "invoke-quality.jsonl"
        prompt = (
            "In src/ui/Button.tsx, change the button text to Ready. "
            "Follow the Lore standing instructions: get_context once, edit, "
            "check_applied with the decision_id and cite_ids, then log_decision."
        )
        started = time.monotonic()
        code = _agy(work, prompt, log=log, timeout=300)
        elapsed = round(time.monotonic() - started, 1)
        events = _events(log)
        tools = _tool_order(events)
        process = _lore_process(events, work)
        summary = {
            "runner": "agy",
            "model": MODEL,
            "mcp_server": WORKSPACE_MCP_NAME,
            "exit": code,
            "seconds": elapsed,
            "tools": tools,
            "process": process,
            "passed": process["ok"],
        }
        _write(LIBRARY / "invocation-agy-quality.json", summary)
        print(json.dumps(summary, indent=2))
        return 0 if process["ok"] else 1


def quality(runs: int = 1, dest: Path | None = None) -> int:
    """Quality bake-off: no_skills / user_picked / agent_chosen / lore."""
    _require_agent_approval()
    if runs < 1:
        raise ValueError("runs must be positive")
    TMP.mkdir(parents=True, exist_ok=True)
    session = Path(tempfile.mkdtemp(prefix="quality-", dir=TMP))
    with _global_lore_disabled():
        _clear_agy_mcp_cache("lore", WORKSPACE_MCP_NAME)
        cold = _cold_map(QUALITY_APP, destination=session / "cold-map-quality")
        rows: list[dict[str, Any]] = []
        aborted: str | None = None
        for scenario in QUALITY_SCENARIOS:
            prompt = (QUALITY_APP / "tasks" / f"{scenario}.txt").read_text(encoding="utf-8")
            originals = _quality_snapshots(QUALITY_APP)
            arms = ("no_skills", "user_picked", "agent_chosen", "lore")
            for number in range(1, runs + 1):
                order = (number - 1 + QUALITY_SCENARIOS.index(scenario)) % len(arms)
                for arm in arms[order:] + arms[:order]:
                    if aborted:
                        break
                    work = session / f"{scenario}-{arm}-{number}"
                    shutil.copytree(QUALITY_APP, work)
                    if arm == "lore":
                        (work / "AGENTS.md").write_text(STANDING_INSTRUCTIONS + "\n", encoding="utf-8")
                        shutil.copytree(LIBRARY / ".lore", work / ".lore")
                        decisions = work / ".lore" / "decisions"
                        if decisions.exists():
                            shutil.rmtree(decisions)
                        decisions.mkdir()
                        status = work / ".lore" / "graph-status.json"
                        if status.is_file():
                            status.unlink()
                        _install_map_from(work, str(session / "cold-map-quality"))
                        _write_workspace_mcp(work, arm="lore", library=LIBRARY)
                    elif arm == "user_picked":
                        shutil.copytree(LIBRARY / ".lore", work / ".lore")
                        decisions = work / ".lore" / "decisions"
                        if decisions.exists():
                            shutil.rmtree(decisions)
                        decisions.mkdir()
                        (work / "AGENTS.md").write_text(
                            _user_picked_rule(scenario), encoding="utf-8"
                        )
                        _write_workspace_mcp(work, arm="baseline", library=LIBRARY)
                    elif arm == "agent_chosen":
                        shutil.copytree(LIBRARY / ".lore", work / ".lore")
                        decisions = work / ".lore" / "decisions"
                        if decisions.exists():
                            shutil.rmtree(decisions)
                        decisions.mkdir()
                        (work / "AGENTS.md").write_text(AGENT_CHOSEN_RULE, encoding="utf-8")
                        _write_workspace_mcp(work, arm="baseline", library=LIBRARY)
                    else:
                        _write_workspace_mcp(work, arm="baseline", library=LIBRARY)
                    if arm != "no_skills":
                        _install_quality_skill(work)
                    if scenario == "stale-map":
                        (work / "src/ui/Panel.tsx").rename(work / "src/ui/LivePanel.tsx")
                    if arm == "lore" and scenario == "no-map":
                        path = work / ".agents/mcp_config.json"
                        config = json.loads(path.read_text(encoding="utf-8"))
                        config["mcpServers"][WORKSPACE_MCP_NAME]["env"]["LORE_MAP_ENABLED"] = "0"
                        path.write_text(json.dumps(config), encoding="utf-8")
                        graph = work / "graphify-out"
                        if graph.exists():
                            shutil.rmtree(graph)
                    log = session / f"{scenario}-{arm}-{number}.jsonl"
                    started = time.monotonic()
                    code = _agy(work, prompt, log=log, timeout=600)
                    elapsed = time.monotonic() - started
                    events = _events(log)
                    usage = _usage(events)
                    checks = _quality_rubric(scenario, work, originals)
                    row: dict[str, Any] = {
                        "scenario": scenario,
                        "arm": arm,
                        "run": number,
                        "exit": code,
                        "seconds": elapsed,
                        "input_tokens": usage.get("input_tokens"),
                        "cached_input_tokens": usage.get("cached_input_tokens"),
                        "fresh_input_tokens": _fresh(usage),
                        "output_tokens": usage.get("output_tokens"),
                        "tools": _tool_order(events),
                        "checks": checks,
                        "passed": all(checks.values()) and code == 0,
                        "map_mode": (
                            "disabled" if scenario == "no-map"
                            else "stale" if scenario == "stale-map" else "warm"
                        ),
                    }
                    if arm == "lore":
                        process = _lore_process(events, work)
                        row["process"] = process
                        row["mcp_get_context_ok"] = process["get_context"]
                        row["mcp_get_context_error"] = _mcp_get_context_error(events)
                        if number == 1 and not process["get_context"]:
                            aborted = (
                                f"quality lore/{scenario} missing get_context; "
                                f"error={row.get('mcp_get_context_error')!r}"
                            )
                    rows.append(row)
                    print(json.dumps(rows[-1]), flush=True)
                    if aborted:
                        print(json.dumps({"aborted": aborted}), flush=True)
                        break
            if aborted:
                break
        score = _quality_score(rows, expected_runs=runs)
        result: dict[str, Any] = {
            "runner": "agy",
            "protocol_version": 2,
            "environment": {"platform": sys.platform, "python": sys.version.split()[0]},
            "library_sha256": _quality_library_hash(),
            "task_sha256": {
                name: hashlib.sha256(
                    (QUALITY_APP / "tasks" / f"{name}.txt").read_bytes()
                ).hexdigest() for name in QUALITY_SCENARIOS
            },
            "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "model": MODEL,
            "mcp_server": WORKSPACE_MCP_NAME,
            "cold_map_seconds": cold,
            "runs_per_cell": runs,
            "scenarios": list(QUALITY_SCENARIOS),
            "runs": rows,
            "score": score,
            "note": (
                "Quality bake-off. Primary gates are rubric + lore process; "
                "tokens are secondary only."
            ),
        }
        if aborted:
            result["aborted"] = aborted
            result["note"] += f" ABORTED: {aborted}"
        path = dest or (session / "results.json")
        _write(path, result)
        print(json.dumps(score, indent=2))
        return 0 if score.get("workflow_gate") and not aborted else 1


def _install_quality_skill(work: Path) -> None:
    source = ROOT / "examples/bench-quality-skills/release-stamp@v1.md"
    target = work / ".lore/skills/frontend-engineer/release-stamp@v1.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def _quality_library_hash() -> str:
    digest = hashlib.sha256()
    for root in (LIBRARY / ".lore", ROOT / "examples/bench-quality-skills"):
        for path in sorted(root.rglob("*.md")):
            if "decisions" not in path.relative_to(root).parts:
                digest.update(path.relative_to(ROOT).as_posix().encode("utf-8"))
                digest.update(b"\0")
                digest.update(path.read_bytes())
    return digest.hexdigest()


def bench(runs: int = 3, dest: Path | None = None, note: str = "", label: str = "") -> int:
    TMP.mkdir(parents=True, exist_ok=True)
    with _global_lore_disabled():
        _clear_agy_mcp_cache("lore", WORKSPACE_MCP_NAME)
        cold = _cold_map()
        prompt = (APP / "TASK.txt").read_text(encoding="utf-8")
        readme = (APP / "README.md").read_text(encoding="utf-8")
        rows: list[dict[str, Any]] = []
        aborted: str | None = None
        for arm in ("baseline", "lore"):
            for number in range(1, runs + 1):
                if aborted and arm == "lore":
                    break
                work = TMP / f"{label}{arm}-{number}"
                if work.exists():
                    shutil.rmtree(work)
                shutil.copytree(APP, work)
                if arm == "lore":
                    (work / "AGENTS.md").write_text(STANDING_INSTRUCTIONS + "\n", encoding="utf-8")
                    # The project store is the one the server finds by walking up.
                    shutil.copytree(LIBRARY / ".lore", work / ".lore")
                    decisions = work / ".lore" / "decisions"
                    if decisions.exists():
                        shutil.rmtree(decisions)
                    decisions.mkdir()
                    status = work / ".lore" / "graph-status.json"
                    if status.is_file():
                        status.unlink()
                    _install_map(work)
                _write_workspace_mcp(work, arm=arm, library=LIBRARY)
                log = TMP / f"{label}{arm}-{number}.jsonl"
                started = time.monotonic()
                code = _agy(work, prompt, log=log, timeout=600)
                elapsed = round(time.monotonic() - started, 1)
                events = _events(log)
                usage = _usage(events)
                checks = _checklist(work, readme)
                mcp_ok = _mcp_get_context_ok(events) if arm == "lore" else None
                row: dict[str, Any] = {
                    "arm": arm,
                    "run": number,
                    "exit": code,
                    "seconds": elapsed,
                    "input_tokens": usage.get("input_tokens"),
                    "cached_input_tokens": usage.get("cached_input_tokens"),
                    "fresh_input_tokens": _fresh(usage),
                    "output_tokens": usage.get("output_tokens"),
                    "tools": _tool_order(events),
                    "checks": checks,
                    "passed": all(checks.values()),
                }
                if arm == "lore":
                    row["mcp_get_context_ok"] = mcp_ok
                    row["mcp_get_context_error"] = _mcp_get_context_error(events)
                rows.append(row)
                print(json.dumps(rows[-1]), flush=True)
                if arm == "lore" and number == 1 and not mcp_ok:
                    aborted = (
                        "first lore run had no successful get_context MCP call; "
                        f"error={row.get('mcp_get_context_error')!r}"
                    )
                    print(json.dumps({"aborted": aborted}), flush=True)
                    break
        result: dict[str, Any] = {
            "runner": "agy",
            "model": MODEL,
            "mcp_server": WORKSPACE_MCP_NAME,
            "cold_map_seconds": cold,
            "runs": rows,
            "score": _score(rows),
        }
        if note:
            result["note"] = note
        if aborted:
            result["aborted"] = aborted
            result["note"] = ((note + " ") if note else "") + f"ABORTED: {aborted}"
        _write(dest or (LIBRARY / "results.json"), result)
        print(json.dumps(result["score"], indent=2))
        return 1 if aborted else 0


PASTE_RULE = (
    "Before editing, read every file under .lore/skills. Apply what they say. "
    "Then do the task. Do not call Lore.\n"
)
ONCE_RULE = (
    "Call get_context exactly once, with persona frontend-engineer and the whole task as the intent. "
    "Then edit. Do not call list_personas, locate, map_codebase, or get_skill. "
    "Do not read files under .lore.\n"
)
STABLE_RULE = (
    "Before editing, read only these files, then do the task. Do not read any other file under .lore:\n"
    ".lore/skills/frontend-engineer/frontend-design@v1.md\n"
    ".lore/skills/frontend-engineer/tailwind-best-practices@v1.md\n"
    ".lore/skills/frontend-engineer/shadcn-best-practices@v1.md\n"
    ".lore/skills/frontend-engineer/vercel-react-best-practices@v1.md\n"
    ".lore/skills/frontend-engineer/design-taste-frontend@v1.md\n"
    ".lore/skills/frontend-engineer/minimalist-ui@v1.md\n"
    ".lore/skills/accessibility-engineer/web-a11y-authoring@v1.md\n"
    ".lore/skills/accessibility-engineer/web-a11y-review@v1.md\n"
    ".lore/skills/backend-engineer/create-a-backend@v1.md\n"
    ".lore/skills/backend-engineer/supabase-postgres-best-practices@v1.md\n"
    ".lore/skills/reviewer/review-security@v1.md\n"
    ".lore/skills/reviewer/web-design-guidelines@v1.md\n"
)


STEPS_RULE = (
    "Call get_context once for each of frontend-engineer, accessibility-engineer, "
    "backend-engineer, and reviewer. Pass the matching step as the intent. "
    "Then edit. Do not call list_personas or locate. Do not read files under .lore.\n"
)


def stable() -> int:
    """Read the twelve served skill bodies, and nothing else under .lore."""
    TMP.mkdir(parents=True, exist_ok=True)
    with _global_lore_disabled():
        _clear_agy_mcp_cache("lore", WORKSPACE_MCP_NAME)
        prompt = (APP / "TASK.txt").read_text(encoding="utf-8")
        readme = (APP / "README.md").read_text(encoding="utf-8")
        row = _one("paste-stable", STABLE_RULE, False, prompt, readme)
        print(json.dumps(row), flush=True)
        path = LIBRARY / "diagnostics-agy.json"
        payload = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"runs": []}
        payload.setdefault("question", {})["paste-stable"] = (
            "Cost of reading only the twelve stable skill bodies."
        )
        payload.setdefault("runs", []).append(row)
        _write(path, payload)
        return 0


def diagnose() -> int:
    """Three sessions. Each one is aimed at a different reason Lore can lose."""
    TMP.mkdir(parents=True, exist_ok=True)
    with _global_lore_disabled():
        _clear_agy_mcp_cache("lore", WORKSPACE_MCP_NAME)
        _cold_map()
        prompt = (APP / "TASK.txt").read_text(encoding="utf-8")
        readme = (APP / "README.md").read_text(encoding="utf-8")
        variants = (
            ("paste", PASTE_RULE, False),
            ("lore-steps", STEPS_RULE, True),
            ("lore-once", ONCE_RULE, True),
        )
        rows: list[dict[str, Any]] = []
        for name, rule, use_lore in variants:
            row = _one(name, rule, use_lore, prompt, readme)
            rows.append(row)
            print(json.dumps(row), flush=True)
        payload = {
            "runner": "agy",
            "model": MODEL,
            "question": {
                "paste": "Cost of reading the stable skill bodies before editing.",
                "lore-steps": "Cost of one get_context per step, without list_personas or locate.",
                "lore-once": "Cost of a single get_context for the whole task.",
            },
            "runs": rows,
        }
        _write(LIBRARY / "diagnostics-agy.json", payload)
        return 0


def _one(name: str, rule: str, use_lore: bool, prompt: str, readme: str) -> dict[str, Any]:
    work = TMP / f"diag-{name}"
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(APP, work)
    shutil.copytree(LIBRARY / ".lore", work / ".lore")
    decisions = work / ".lore" / "decisions"
    if decisions.exists():
        shutil.rmtree(decisions)
    decisions.mkdir()
    (work / "AGENTS.md").write_text(rule, encoding="utf-8")
    if use_lore:
        _install_map(work)
    _write_workspace_mcp(work, arm="lore" if use_lore else "baseline", library=work)
    log = TMP / f"diag-{name}.jsonl"
    started = time.monotonic()
    code = _agy(work, prompt, log=log, timeout=600)
    events = _events(log)
    usage = _usage(events)
    fresh = _fresh(usage) if usage else None
    checks = _checklist(work, readme)
    return {
        "arm": name,
        "exit": code,
        "seconds": round(time.monotonic() - started, 1),
        "input_tokens": usage.get("input_tokens"),
        "cached_input_tokens": usage.get("cached_input_tokens"),
        "fresh_input_tokens": fresh,
        "output_tokens": usage.get("output_tokens"),
        "turns": _turn_count(events),
        "tools": _tool_order(events),
        "commands": _commands(events),
        "checks": checks,
        "passed": all(checks.values()),
    }


def _commands(events: list[dict[str, Any]]) -> list[str]:
    found: list[str] = []
    for event in events:
        blob = json.dumps(event)
        if "run_command" not in blob and "command_execution" not in blob:
            continue
        for key in ("command", "cmd", "text"):
            value = _dig(event, key)
            if isinstance(value, str) and value.strip():
                found.append(value.replace("\n", " ")[:180])
                break
    return found


def _dig(payload: Any, key: str) -> Any:
    if isinstance(payload, dict):
        if key in payload:
            return payload[key]
        for value in payload.values():
            found = _dig(value, key)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = _dig(item, key)
            if found is not None:
                return found
    return None


def _cold_map(app: Path | None = None, *, destination: Path | None = None) -> float:
    if not GRAPHIFY.is_file():
        raise SystemExit(
            f"Graphify missing at {GRAPHIFY}. Install map support: uv sync --extra map"
        )
    source = app or APP
    work = destination or TMP / ("cold-map-quality" if app is not None else "cold-map")
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(source, work)
    started = time.monotonic()
    result = subprocess.run(
        [str(GRAPHIFY), "extract", str(work), "--code-only", "--out", str(work)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not (work / "graphify-out/graph.json").is_file():
        raise SystemExit("Cold mapping failed; no evaluation was run.")
    return round(time.monotonic() - started, 1)


def _install_map_from(work: Path, cold_name: str = "cold-map") -> None:
    source = TMP / cold_name / "graphify-out"
    if source.is_dir():
        target = work / "graphify-out"
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source, target)


def _install_map(work: Path) -> None:
    _install_map_from(work, "cold-map")


def _require_agent_approval() -> None:
    if os.environ.get("LORE_BENCH_ALLOW_PAID") != "1":
        raise SystemExit(
            "Agent evaluations require explicit approval. After approval, set "
            "LORE_BENCH_ALLOW_PAID=1. No model request was sent."
        )


def _agy(work: Path, prompt: str, *, log: Path, timeout: int) -> int:
    _require_agent_approval()
    log.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "agy",
        "-p",
        prompt,
        "--model",
        MODEL,
        "--output-format",
        "stream-json",
        "--mode",
        "accept-edits",
        "--dangerously-skip-permissions",
        "--print-timeout",
        f"{timeout}s",
        "--disable-slash-commands",
    ]
    with tempfile.TemporaryDirectory(prefix="lore-benchmark-home-") as isolated:
        env = os.environ.copy()
        env.update({
            "HOME": isolated,
            "USERPROFILE": isolated,
            "XDG_CONFIG_HOME": str(Path(isolated) / "config"),
            "XDG_CACHE_HOME": str(Path(isolated) / "cache"),
            "XDG_DATA_HOME": str(Path(isolated) / "data"),
            "APPDATA": str(Path(isolated) / "appdata"),
            "LOCALAPPDATA": str(Path(isolated) / "localappdata"),
        })
        try:
            completed = subprocess.run(
                cmd,
                cwd=work,
                env=env,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout + 30,
            )
        except subprocess.TimeoutExpired as exc:
            log.write_text((exc.stdout or "") if isinstance(exc.stdout, str) else "", encoding="utf-8")
            return 124
    log.write_text(completed.stdout or "", encoding="utf-8")
    if completed.returncode != 0:
        (log.with_suffix(".err")).write_text(completed.stderr or "", encoding="utf-8")
    return completed.returncode


def _write_workspace_mcp(work: Path, *, arm: str, library: Path) -> None:
    agents = work / ".agents"
    agents.mkdir(parents=True, exist_ok=True)
    if arm == "lore":
        if not LORE.is_file():
            raise SystemExit(f"lore-solo missing at {LORE}")
        payload = {
            "mcpServers": {
                WORKSPACE_MCP_NAME: {
                    "command": str(LORE),
                    "args": ["mcp"],
                    "env": {
                        "LORE_CLIENT": "Antigravity",
                        "LORE_LIBRARY": str(library),
                        "LORE_WORKSPACE": str(work),
                    },
                    "enabledTools": list(CODING_MCP_TOOLS),
                    "timeoutSeconds": 600,
                }
            }
        }
    else:
        payload = {"mcpServers": {}}
    (agents / "mcp_config.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _clear_agy_mcp_cache(*names: str) -> None:
    """Drop stale Antigravity MCP tool-schema caches so lore-solo schemas refresh."""
    del names


class _global_lore_disabled:
    """No-op context manager kept for call sites.

    The deprecated Go ``lore`` binary and its global MCP entry are removed.
    Suites still clear Antigravity schema caches for leftover ``lore`` names.
    """

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None


def _events(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            loaded = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(loaded, dict):
            rows.append(loaded)
    return rows


def _mcp_tool_steps(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return call_mcp_tool step_update payloads (any state)."""
    steps: list[dict[str, Any]] = []
    for event in events:
        if event.get("event") != "step_update":
            continue
        step = event.get("step_update")
        if not isinstance(step, dict):
            continue
        info = step.get("tool_info") if isinstance(step.get("tool_info"), dict) else {}
        name = step.get("tool_name") or info.get("name")
        if name != "call_mcp_tool":
            continue
        steps.append(step)
    return steps


def _mcp_tool_name(step: dict[str, Any]) -> str | None:
    info = step.get("tool_info") if isinstance(step.get("tool_info"), dict) else {}
    params = info.get("parameters") if isinstance(info.get("parameters"), dict) else {}
    tool = params.get("ToolName") or params.get("toolName") or params.get("tool_name")
    return tool if isinstance(tool, str) else None


def _mcp_get_context_ok(events: list[dict[str, Any]]) -> bool:
    """True only when get_context completed successfully via call_mcp_tool."""
    for step in _mcp_tool_steps(events):
        if step.get("state") == "DONE" and _mcp_tool_name(step) == "get_context":
            return True
    return False


def _mcp_get_context_error(events: list[dict[str, Any]]) -> str | None:
    """Latest get_context ERROR message, only when no DONE succeeded."""
    if _mcp_get_context_ok(events):
        return None
    last: str | None = None
    for step in _mcp_tool_steps(events):
        if _mcp_tool_name(step) != "get_context":
            continue
        if step.get("state") != "ERROR":
            continue
        info = step.get("tool_info") if isinstance(step.get("tool_info"), dict) else {}
        err = info.get("error") if isinstance(info.get("error"), dict) else {}
        message = err.get("message")
        if isinstance(message, str) and message.strip():
            last = message.strip()[:400]
        else:
            last = f"get_context MCP call ended in {step.get('state')}"
    return last


def _tool_order(events: list[dict[str, Any]]) -> list[str]:
    """Successful Lore MCP tools only (FAILED attempts are ignored)."""
    found: list[str] = []
    for step in _mcp_tool_steps(events):
        if step.get("state") != "DONE":
            continue
        name = _mcp_tool_name(step)
        if name in LORE_TOOLS and (not found or found[-1] != name):
            found.append(name)
    return found


def _mcp_tool_done(events: list[dict[str, Any]], tool: str) -> bool:
    for step in _mcp_tool_steps(events):
        if step.get("state") == "DONE" and _mcp_tool_name(step) == tool:
            return True
    return False


def _lore_process(events: list[dict[str, Any]], work: Path) -> dict[str, Any]:
    get_ok = _mcp_get_context_ok(events)
    check_ok = _mcp_tool_done(events, "check_applied")
    log_ok = _mcp_tool_done(events, "log_decision")
    # Prefer decision-file evidence for check_applied pass when tool DONE fired.
    check_pass = False
    if check_ok:
        from lore.core.okf import read_doc

        decisions = sorted((work / ".lore" / "decisions").glob("dec-*.md"))
        check_pass = bool(decisions)
        for path in decisions:
            doc = read_doc(path)
            receipts = [
                line.strip() for line in doc.body.splitlines()
                if line.strip() in {
                    "check_applied: pass", "check_applied: fail", "check_applied: skip",
                }
            ]
            served = doc.header.get("included", [])
            if (
                not receipts
                or not isinstance(served, list)
                or receipts[-1] == "check_applied: fail"
                or (
                    receipts[-1] == "check_applied: skip"
                    and isinstance(served, list)
                    and any(str(item).startswith("skill:") for item in served)
                )
            ):
                check_pass = False
                break
    return {
        "get_context": get_ok,
        "get_skill": _mcp_tool_done(events, "get_skill"),
        "check_applied": check_ok and check_pass,
        "log_decision": log_ok,
        "ok": bool(get_ok and check_ok and check_pass and log_ok),
    }


def _quality_snapshots(app: Path) -> dict[str, str]:
    paths = (
        "src/ui/Panel.tsx",
        "src/ui/PanelCopy.tsx",
        "src/api/health.py",
        "src/api/health_probe.py",
    )
    return {rel: _text(app / rel) for rel in paths}


def _quality_rubric(scenario: str, work: Path, originals: dict[str, str]) -> dict[str, bool]:
    panel = _text(work / "src" / "ui" / "Panel.tsx")
    copy = _text(work / "src" / "ui" / "PanelCopy.tsx")
    health = _text(work / "src" / "api" / "health.py")
    probe = _text(work / "src" / "api" / "health_probe.py")
    if scenario in {"stale-map", "no-map"}:
        live = _text(work / "src/ui/LivePanel.tsx") if scenario == "stale-map" else panel
        return {
            "published_label": 'const label = "Published"' in live
            or "const label = 'Published'" in live,
            "theme_import": "./theme" in live,
            "decoy_untouched": copy == originals["src/ui/PanelCopy.tsx"],
        }
    if scenario == "full-skill":
        return {
            "approved_stamp": 'data-release-stamp="lore-approved-2026"' in panel
            or "data-release-stamp='lore-approved-2026'" in panel,
            "api_untouched": health == originals["src/api/health.py"],
            "decoy_untouched": copy == originals["src/ui/PanelCopy.tsx"],
        }
    if scenario == "new-file":
        source = _text(work / "src/api/readiness.py")
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return {"valid_python": False}
        expected = ast.dump(ast.parse(
            "def readiness() -> dict[str, str]:\n    return {'status': 'ready'}\n",
        ))
        return {
            "readiness_function": ast.dump(tree) == expected,
            "api_untouched": health == originals["src/api/health.py"],
            "probe_untouched": probe == originals["src/api/health_probe.py"],
        }
    if scenario == "cross-file":
        try:
            tree = ast.parse(health)
        except SyntaxError:
            return {"valid_python": False}
        expected = ast.parse(
            "from .service_state import ready_state\n"
            "def health() -> dict[str, str]:\n"
            "    return {'status': ready_state()}\n",
        )
        return {
            "helper_supplies_status": ast.dump(tree) == ast.dump(expected),
            "helper_untouched": _text(work / "src/api/service_state.py")
            == "def ready_state() -> str:\n    return \"ready\"\n",
            "probe_untouched": probe == originals["src/api/health_probe.py"],
        }
    if scenario == "wrong-file":
        return {
            "panel_saved": "Saved" in panel,
            "theme_import": "./theme" in panel,
            "decoy_untouched": copy == originals.get("src/ui/PanelCopy.tsx", copy),
        }
    if scenario == "a11y-label":
        compact = " ".join(panel.split())
        return {
            "save_label": (">Save<" in panel)
            or ('>"Save"<' in panel)
            or (">Save</button>" in compact)
            or ("Save" in panel and "<button" in panel),
        }
    if scenario == "api-shape":
        return {
            "status_ready": ('"status"' in health and "ready" in health)
            or ("'status'" in health and "ready" in health)
            or ("status=" in health and "ready" in health),
            "probe_untouched": probe == originals.get("src/api/health_probe.py", probe),
        }
    return {"unknown_scenario": False}


def _quality_score(
    rows: list[dict[str, Any]],
    *,
    expected_runs: int = 5,
    scenarios: tuple[str, ...] = QUALITY_SCENARIOS,
) -> dict[str, Any]:
    if type(expected_runs) is not int or expected_runs < 1:
        raise ValueError("expected_runs must be a positive integer")
    if not scenarios or len(set(scenarios)) != len(scenarios):
        raise ValueError("scenarios must be nonempty and unique")
    arms = ("no_skills", "user_picked", "agent_chosen", "lore")
    expected = {
        (scenario, arm, number)
        for scenario in scenarios
        for arm in arms
        for number in range(1, expected_runs + 1)
    }
    seen: set[tuple[str, str, int]] = set()
    errors: list[str] = []
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {
        (scenario, arm): [] for scenario in scenarios for arm in arms
    }
    for index, row in enumerate(rows):
        scenario, arm, number = row.get("scenario"), row.get("arm"), row.get("run")
        if scenario not in scenarios or arm not in arms or type(number) is not int:
            errors.append(f"row {index}: unknown scenario/arm or invalid run number")
            continue
        key = (scenario, arm, number)
        if key not in expected or key in seen:
            errors.append(f"row {index}: duplicate or unexpected cell {key}")
            continue
        seen.add(key)
        groups[(scenario, arm)].append(row)
        seconds = row.get("seconds")
        checks = row.get("checks")
        if (
            type(seconds) not in (int, float)
            or not math.isfinite(seconds)
            or seconds <= 0
        ):
            errors.append(f"row {index}: missing or invalid duration")
        if not isinstance(checks, dict) or not checks or any(
            type(value) is not bool for value in checks.values()
        ):
            errors.append(f"row {index}: missing or invalid rubric checks")
        if type(row.get("passed")) is not bool:
            errors.append(f"row {index}: missing or invalid passed flag")
        elif isinstance(checks, dict) and checks and row["passed"] != all(
            value is True for value in checks.values()
        ):
            errors.append(f"row {index}: passed flag disagrees with rubric")
        if type(row.get("exit")) is not int or row["exit"] != 0:
            errors.append(f"row {index}: agent did not exit successfully")
    missing = expected - seen
    if missing:
        errors.append(f"{len(missing)} required run cells missing")
    complete = not errors and seen == expected

    def successful(row: dict[str, Any]) -> bool:
        checks = row.get("checks")
        return bool(
            type(row.get("exit")) is int
            and row["exit"] == 0
            and row.get("passed") is True
            and isinstance(checks, dict)
            and checks
            and all(value is True for value in checks.values())
        )

    def arm_rows(arm: str) -> list[dict[str, Any]]:
        return [row for scenario in scenarios for row in groups[(scenario, arm)]]

    def rate(group: list[dict[str, Any]]) -> float:
        return sum(successful(row) for row in group) / len(group) if group else 0.0

    def med_seconds(arm: str) -> float | None:
        group = arm_rows(arm)
        values = [row.get("seconds") for row in group]
        if not values or any(
            type(value) not in (int, float) or not math.isfinite(value) or value <= 0
            for value in values
        ):
            return None
        return float(statistics.median(values))

    by_scenario = {
        scenario: {
            arm: {
                "passed": sum(successful(row) for row in groups[(scenario, arm)]),
                "total": len(groups[(scenario, arm)]),
                "pass_rate": rate(groups[(scenario, arm)]),
            }
            for arm in arms
        }
        for scenario in scenarios
    }
    primary = complete and all(
        result["lore"]["pass_rate"] >= result[arm]["pass_rate"]
        for result in by_scenario.values()
        for arm in arms[:-1]
    )
    observed_improvement = primary and any(
        result["lore"]["pass_rate"] > max(
            result[arm]["pass_rate"] for arm in arms[:-1]
        )
        for result in by_scenario.values()
    )
    lore_rows = arm_rows("lore")
    process_rate = (
        sum(
            isinstance(row.get("process"), dict)
            and all(
                row["process"].get(field) is True
                for field in ("get_context", "check_applied", "log_decision", "ok")
            )
            and (
                row["scenario"] != "full-skill"
                or row["process"].get("get_skill") is True
            )
            for row in lore_rows
        ) / len(lore_rows)
        if lore_rows else 0.0
    )
    process_ok = complete and process_rate == 1.0
    lore_time = med_seconds("lore")
    picked_time = med_seconds("user_picked")
    chosen_time = med_seconds("agent_chosen")
    time_ratio = (
        lore_time / max(picked_time, chosen_time)
        if lore_time is not None and picked_time is not None and chosen_time is not None
        else None
    )
    time_ok = complete and time_ratio is not None and time_ratio <= 1.25
    workflow_gate = bool(primary and process_ok and time_ok)
    return {
        **{f"{arm}_pass_rate": rate(arm_rows(arm)) for arm in arms},
        "complete": complete,
        "validation_errors": errors,
        "expected_runs_per_cell": expected_runs,
        "by_scenario": by_scenario,
        "lore_process_rate": process_rate,
        "lore_median_seconds": lore_time,
        "user_picked_median_seconds": picked_time,
        "agent_chosen_median_seconds": chosen_time,
        "time_ratio_vs_practical": time_ratio,
        "primary": primary,
        "process": process_ok,
        "time_ok": time_ok,
        "workflow_gate": workflow_gate,
        "observed_improvement": observed_improvement,
        "quality_claim": bool(workflow_gate and observed_improvement and expected_runs >= 5),
        "claim_scope": "Observed task outcomes in this finite sample; not statistical proof.",
    }


def _fresh(usage: dict[str, int]) -> int | None:
    incoming = usage.get("input_tokens")
    cached = usage.get("cached_input_tokens")
    if not isinstance(incoming, int) or not isinstance(cached, int):
        return None
    return incoming - cached


def _usage_blob(event: dict[str, Any]) -> dict[str, Any] | None:
    """Pull usage from an agy result or completed step_update event."""
    if event.get("event") == "result":
        result = event.get("result")
        if isinstance(result, dict):
            usage = result.get("usage")
            if isinstance(usage, dict):
                return usage
    if event.get("event") == "step_update":
        step = event.get("step_update")
        if isinstance(step, dict) and step.get("state") == "DONE":
            usage = step.get("usage")
            if isinstance(usage, dict):
                return usage
    # Legacy Codex shape, if ever mixed in.
    if event.get("type") == "turn.completed":
        usage = event.get("usage")
        if isinstance(usage, dict):
            return usage
    return None


def _normalize_usage(raw: dict[str, Any]) -> dict[str, int]:
    """Map agy/Gemini usage into Codex-shaped totals.

    agy reports uncached prompt tokens as ``input_tokens`` and cache hits as
    ``cache_read_tokens`` (often larger than input). Codex reports total prompt
    tokens as ``input_tokens`` with ``cached_input_tokens`` as a subset, so
    fresh = input - cached. Reconstruct that shape here.
    """
    incoming = raw.get("input_tokens")
    cached = raw.get("cache_read_tokens", raw.get("cached_input_tokens", 0))
    outgoing = raw.get("output_tokens", 0)
    thinking = raw.get("thinking_tokens", 0)
    if not isinstance(incoming, int):
        return {}
    if not isinstance(cached, int):
        cached = 0
    if not isinstance(outgoing, int):
        outgoing = 0
    if isinstance(thinking, int):
        outgoing += thinking
    # Codex-compatible: input includes cache; fresh = input - cached.
    if "cache_read_tokens" in raw:
        return {
            "input_tokens": incoming + cached,
            "cached_input_tokens": cached,
            "output_tokens": outgoing,
        }
    return {
        "input_tokens": incoming,
        "cached_input_tokens": cached,
        "output_tokens": outgoing,
    }


def _usage(events: list[dict[str, Any]]) -> dict[str, int]:
    """Prefer the final agy result usage; otherwise sum completed step usages."""
    for event in reversed(events):
        if event.get("event") == "result":
            raw = _usage_blob(event)
            if raw:
                return _normalize_usage(raw)
    total = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0}
    seen = False
    for event in events:
        raw = _usage_blob(event)
        if not raw:
            continue
        piece = _normalize_usage(raw)
        if not piece:
            continue
        seen = True
        for key in total:
            total[key] += piece[key]
    return total if seen else {}


def _turn_count(events: list[dict[str, Any]]) -> int:
    for event in reversed(events):
        if event.get("event") == "result":
            result = event.get("result")
            if isinstance(result, dict):
                turns = result.get("num_turns")
                if isinstance(turns, int):
                    return turns
    return sum(1 for event in events if event.get("event") == "result")


def _checklist(work: Path, readme: str) -> dict[str, bool]:
    panel = _text(work / "src" / "ui" / "Panel.tsx")
    health = _text(work / "src" / "api" / "health.py")
    review = _text(work / "review.txt")
    return {
        "saved": "Saved" in panel,
        "theme_import": "./theme" in panel,
        "save_button": "Save" in panel and "<button" in panel,
        "ready": "ready" in health,
        "review": "Panel.tsx" in review and "health.py" in review,
        "readme": _text(work / "README.md") == readme,
    }


def _score(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def arm(name: str) -> list[dict[str, Any]]:
        return [row for row in rows if row["arm"] == name]

    baseline = arm("baseline")
    lore = arm("lore")

    def med(group: list[dict[str, Any]], key: str) -> float | None:
        values = [row[key] for row in group if isinstance(row.get(key), (int, float))]
        if not values:
            return None
        return statistics.median(values)

    base_in = med(baseline, "input_tokens")
    lore_in = med(lore, "input_tokens")
    base_time = med(baseline, "seconds")
    lore_time = med(lore, "seconds")
    ratio = None if not base_in or lore_in is None else round(lore_in / base_in, 3)
    time_ratio = None if not base_time or lore_time is None else round(lore_time / base_time, 3)
    base_pass = sum(1 for row in baseline if row["passed"]) / len(baseline) if baseline else 0
    lore_pass = sum(1 for row in lore if row["passed"]) / len(lore) if lore else 0
    return {
        "baseline_pass_rate": base_pass,
        "lore_pass_rate": lore_pass,
        "baseline_median_input_tokens": base_in,
        "lore_median_input_tokens": lore_in,
        "input_token_ratio": ratio,
        "baseline_median_fresh_tokens": med(baseline, "fresh_input_tokens"),
        "lore_median_fresh_tokens": med(lore, "fresh_input_tokens"),
        "fresh_token_ratio": (
            None
            if not med(baseline, "fresh_input_tokens") or med(lore, "fresh_input_tokens") is None
            else round(med(lore, "fresh_input_tokens") / med(baseline, "fresh_input_tokens"), 3)
        ),
        "baseline_median_seconds": base_time,
        "lore_median_seconds": lore_time,
        "time_ratio": time_ratio,
        "gate": lore_pass >= base_pass,
        "tokens": ratio is not None and ratio <= 0.70,
        "time": time_ratio is not None and time_ratio <= 1.15,
        "fresh_ok": (
            med(baseline, "fresh_input_tokens") is not None
            and med(lore, "fresh_input_tokens") is not None
            and med(lore, "fresh_input_tokens") <= med(baseline, "fresh_input_tokens")
        ),
        "lore_wins": bool(
            lore_pass >= base_pass
            and ratio is not None
            and ratio <= 0.70
            and time_ratio is not None
            and time_ratio <= 1.15
        ),
        "product_claim": bool(
            lore_pass >= base_pass
            and med(baseline, "fresh_input_tokens") is not None
            and med(lore, "fresh_input_tokens") is not None
            and med(lore, "fresh_input_tokens") <= med(baseline, "fresh_input_tokens")
            and time_ratio is not None
            and time_ratio <= 1.15
        ),
    }


def _text(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
