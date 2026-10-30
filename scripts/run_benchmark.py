"""Timed Codex comparison, and one unprompted Lore invocation check.

    .venv/bin/python scripts/run_benchmark.py confirm
    .venv/bin/python scripts/run_benchmark.py bench

Full event logs stay in `.tmp/`. The summaries written under examples/bench-library
do not include credentials.
"""

from __future__ import annotations

import json
import os
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from lore.core.instructions import STANDING_INSTRUCTIONS

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "examples" / "bench-app"
LIBRARY = ROOT / "examples" / "bench-library"
PACK = ROOT / "examples" / "persona-pack"
TMP = ROOT / ".tmp" / "bench-runs"
LORE = ROOT / ".venv" / "bin" / "lore-solo"
GRAPHIFY = ROOT / ".venv" / "bin" / "graphify"
MODEL = "gpt-6-luna"
LORE_TOOLS = ("list_personas", "get_context", "get_skill", "locate", "map_codebase", "map_status")


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "bench"
    if command == "confirm":
        raise SystemExit(confirm())
    if command == "bench":
        raise SystemExit(bench())
    if command == "solution":
        raise SystemExit(
            bench(
                3,
                LIBRARY / "results-solution.json",
                note="One get_context call returns the matching skill summaries and the files.",
                label="solution-",
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
                LIBRARY / "results-rerun.json",
                label="rerun-",
                note=(
                    "Rerun after spaced persona names resolve, with the benchmark "
                    "personas copied into the disposable project. The first three-run "
                    "result is results.json. The earlier rerun missed because the MCP "
                    "process never saw the benchmark library."
                ),
            )
        )
    print("use confirm or bench", file=sys.stderr)
    raise SystemExit(2)


def confirm() -> int:
    work = TMP / "invoke"
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(PACK, work, ignore=shutil.ignore_patterns(".git"))
    (work / "AGENTS.md").write_text(STANDING_INSTRUCTIONS + "\n", encoding="utf-8")
    log = TMP / "invoke.jsonl"
    started = time.monotonic()
    code = _codex(
        work,
        "In src/ui/Button.tsx, change the button text to Ready. Open only the files you need.",
        arm="lore",
        library=work,
        log=log,
        timeout=300,
    )
    elapsed = round(time.monotonic() - started, 1)
    decisions = sorted((work / ".lore" / "decisions").glob("dec-*.md"))
    events = _events(log)
    tools = _tool_order(events)
    called = bool(decisions) or any(name in tools for name in ("get_context", "locate"))
    summary = {
        "exit": code,
        "seconds": elapsed,
        "decisions": [path.name for path in decisions],
        "tools": tools,
        "called_lore_before_narration": called,
        "event_types": sorted({str(event.get("type")) for event in events if isinstance(event, dict)}),
    }
    _write(LIBRARY / "invocation.json", summary)
    print(json.dumps(summary, indent=2))
    return 0 if called else 1


def bench(runs: int = 3, dest: Path | None = None, note: str = "", label: str = "") -> int:
    TMP.mkdir(parents=True, exist_ok=True)
    cold = _cold_map()
    prompt = (APP / "TASK.txt").read_text(encoding="utf-8")
    readme = (APP / "README.md").read_text(encoding="utf-8")
    rows: list[dict[str, Any]] = []
    for arm in ("baseline", "lore"):
        for number in range(1, runs + 1):
            work = TMP / f"{label}{arm}-{number}"
            if work.exists():
                shutil.rmtree(work)
            shutil.copytree(APP, work)
            if arm == "lore":
                (work / "AGENTS.md").write_text(STANDING_INSTRUCTIONS + "\n", encoding="utf-8")
                # The project store is the one the server finds by walking up.
                # An env var on the MCP entry is not enough if the editor drops it.
                shutil.copytree(LIBRARY / ".lore", work / ".lore")
                decisions = work / ".lore" / "decisions"
                if decisions.exists():
                    shutil.rmtree(decisions)
                decisions.mkdir()
                status = work / ".lore" / "graph-status.json"
                if status.is_file():
                    status.unlink()
                _install_map(work)
            log = TMP / f"{label}{arm}-{number}.jsonl"
            started = time.monotonic()
            code = _codex(work, prompt, arm=arm, library=LIBRARY, log=log, timeout=600)
            elapsed = round(time.monotonic() - started, 1)
            events = _events(log)
            usage = _usage(events)
            checks = _checklist(work, readme)
            rows.append(
                {
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
            )
            print(json.dumps(rows[-1]), flush=True)
    result = {"cold_map_seconds": cold, "runs": rows, "score": _score(rows)}
    if note:
        result["note"] = note
    _write(dest or (LIBRARY / "results.json"), result)
    print(json.dumps(result["score"], indent=2))
    return 0


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
    prompt = (APP / "TASK.txt").read_text(encoding="utf-8")
    readme = (APP / "README.md").read_text(encoding="utf-8")
    row = _one("paste-stable", STABLE_RULE, False, prompt, readme)
    print(json.dumps(row), flush=True)
    path = LIBRARY / "diagnostics.json"
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
        "question": {
            "paste": "Cost of reading the stable skill bodies before editing.",
            "lore-steps": "Cost of one get_context per step, without list_personas or locate.",
            "lore-once": "Cost of a single get_context for the whole task.",
        },
        "runs": rows,
    }
    _write(LIBRARY / "diagnostics.json", payload)
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
    log = TMP / f"diag-{name}.jsonl"
    started = time.monotonic()
    code = _codex(work, prompt, arm="lore" if use_lore else "paste", library=work, log=log, timeout=600)
    events = _events(log)
    usage = _usage(events)
    fresh = None
    if "input_tokens" in usage:
        fresh = usage["input_tokens"] - usage.get("cached_input_tokens", 0)
    checks = _checklist(work, readme)
    return {
        "arm": name,
        "exit": code,
        "seconds": round(time.monotonic() - started, 1),
        "input_tokens": usage.get("input_tokens"),
        "cached_input_tokens": usage.get("cached_input_tokens"),
        "fresh_input_tokens": fresh,
        "output_tokens": usage.get("output_tokens"),
        "turns": sum(1 for event in events if event.get("type") == "turn.completed"),
        "tools": _tool_calls(events),
        "commands": _commands(events),
        "checks": checks,
        "passed": all(checks.values()),
    }


def _tool_calls(events: list[dict[str, Any]]) -> list[str]:
    found: list[str] = []
    for event in events:
        if event.get("type") != "item.completed":
            continue
        item = event.get("item")
        if not isinstance(item, dict) or item.get("type") != "mcp_tool_call":
            continue
        tool = str(item.get("tool") or "")
        if tool:
            found.append(tool)
    return found


def _commands(events: list[dict[str, Any]]) -> list[str]:
    found: list[str] = []
    for event in events:
        if event.get("type") != "item.completed":
            continue
        item = event.get("item")
        if not isinstance(item, dict) or item.get("type") != "command_execution":
            continue
        command = str(item.get("command") or "").replace("\n", " ")
        if command:
            found.append(command[:180])
    return found


def _cold_map() -> float:
    work = TMP / "cold-map"
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(APP, work)
    started = time.monotonic()
    subprocess.run(
        [str(GRAPHIFY), "extract", str(work), "--code-only", "--out", str(work)],
        check=False,
        capture_output=True,
        text=True,
    )
    return round(time.monotonic() - started, 1)


def _install_map(work: Path) -> None:
    source = TMP / "cold-map" / "graphify-out"
    if source.is_dir():
        shutil.copytree(source, work / "graphify-out")


def _codex(work: Path, prompt: str, *, arm: str, library: Path, log: Path, timeout: int) -> int:
    log.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "codex",
        "exec",
        "--json",
        "--ephemeral",
        "--skip-git-repo-check",
        "-m",
        MODEL,
        "-c",
        'model_reasoning_effort="medium"',
        "-s",
        "workspace-write",
        "--dangerously-bypass-approvals-and-sandbox",
    ]
    env = os.environ.copy()
    if arm == "lore":
        home = _lore_home()
        env["CODEX_HOME"] = str(home)
        command = json.dumps(str(LORE))
        workspace = json.dumps(str(work))
        library_text = json.dumps(str(library))
        env_value = (
            '{LORE_CLIENT="Codex", LORE_LIBRARY='
            + library_text
            + ", LORE_WORKSPACE="
            + workspace
            + "}"
        )
        cmd.extend(
            [
                "-c",
                f"mcp_servers.lore.command={command}",
                "-c",
                'mcp_servers.lore.args=["mcp"]',
                "-c",
                f"mcp_servers.lore.env={env_value}",
            ]
        )
    cmd.append(prompt)
    try:
        completed = subprocess.run(
            cmd,
            cwd=work,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        log.write_text((exc.stdout or "") if isinstance(exc.stdout, str) else "", encoding="utf-8")
        return 124
    log.write_text(completed.stdout or "", encoding="utf-8")
    if completed.returncode != 0:
        (log.with_suffix(".err")).write_text(completed.stderr or "", encoding="utf-8")
    return completed.returncode


def _lore_home() -> Path:
    home = TMP / "codex-home"
    home.mkdir(parents=True, exist_ok=True)
    auth = Path.home() / ".codex" / "auth.json"
    if auth.is_file() and not (home / "auth.json").is_file():
        shutil.copyfile(auth, home / "auth.json")
    config = home / "config.toml"
    if not config.is_file():
        config.write_text(
            'model = "gpt-6-luna"\nmodel_reasoning_effort = "medium"\n',
            encoding="utf-8",
        )
    return home


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


def _tool_order(events: list[dict[str, Any]]) -> list[str]:
    found: list[str] = []
    for event in events:
        blob = json.dumps(event)
        for name in LORE_TOOLS:
            if f'"{name}"' in blob and (not found or found[-1] != name):
                found.append(name)
    return found


def _fresh(usage: dict[str, int]) -> int | None:
    incoming = usage.get("input_tokens")
    cached = usage.get("cached_input_tokens")
    if not isinstance(incoming, int) or not isinstance(cached, int):
        return None
    return incoming - cached


def _usage(events: list[dict[str, Any]]) -> dict[str, int]:
    """Sum each completed turn. Codex reports that turn's tokens, not a running total."""
    total = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0}
    seen = False
    for event in events:
        if event.get("type") != "turn.completed":
            continue
        usage = event.get("usage")
        if not isinstance(usage, dict):
            continue
        seen = True
        for key in total:
            value = usage.get(key)
            if isinstance(value, int):
                total[key] += value
    return total if seen else {}


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
        "lore_wins": bool(
            lore_pass >= base_pass
            and ratio is not None
            and ratio <= 0.70
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
