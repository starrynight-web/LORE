from __future__ import annotations

import importlib.util
import json
from copy import deepcopy
from itertools import count
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "lore_benchmark", Path(__file__).resolve().parents[3] / "scripts" / "run_benchmark.py",
)
assert _SPEC is not None and _SPEC.loader is not None
_BENCHMARK = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_BENCHMARK)
QUALITY_SCENARIOS = _BENCHMARK.QUALITY_SCENARIOS
_quality_score = _BENCHMARK._quality_score


def _rows(runs: int = 5) -> list[dict[str, Any]]:
    return [
        {
            "scenario": scenario,
            "arm": arm,
            "run": number,
            "seconds": 10.0,
            "exit": 0,
            "passed": True,
            "checks": {"target": True},
            **(
                {"process": dict.fromkeys(
                    ("get_context", "get_skill", "check_applied", "log_decision", "ok"), True,
                )}
                if arm == "lore" else {}
            ),
        }
        for scenario in QUALITY_SCENARIOS
        for arm in ("no_skills", "user_picked", "agent_chosen", "lore")
        for number in range(1, runs + 1)
    ]


def test_equal_outcomes_are_workflow_success_not_quality_improvement() -> None:
    result = _quality_score(_rows())
    assert result["complete"]
    assert result["workflow_gate"]
    assert not result["observed_improvement"]
    assert not result["quality_claim"]


def test_full_skill_scenario_requires_retrieval_evidence() -> None:
    rows = _rows()
    for row in rows:
        if row["arm"] == "lore" and row["scenario"] == "full-skill":
            row["process"].pop("get_skill")
    result = _quality_score(rows)
    assert result["complete"]
    assert not result["process"]
    assert not result["workflow_gate"]
    assert not result["quality_claim"]


@pytest.mark.parametrize("damage", ["missing", "duplicate", "legacy", "nan", "exit", "checks"])
def test_incomplete_or_invalid_experiments_fail_closed(damage: str) -> None:
    rows = _rows()
    if damage == "missing":
        rows = [row for row in rows if row["arm"] != "agent_chosen"]
    elif damage == "duplicate":
        rows.append(deepcopy(rows[0]))
    elif damage == "legacy":
        rows[0]["arm"] = "paste_skills"
    elif damage == "nan":
        rows[0]["seconds"] = float("nan")
    elif damage == "exit":
        rows[0]["exit"] = 1
    else:
        rows[0]["checks"] = {}
    result = _quality_score(rows)
    assert not result["complete"]
    assert result["validation_errors"]
    assert not result["workflow_gate"]
    assert not result["quality_claim"]


def test_missing_process_evidence_fails_the_workflow_gate() -> None:
    rows = _rows()
    next(row for row in rows if row["arm"] == "lore")["process"] = {"ok": True}
    assert not _quality_score(rows)["process"]


def test_missing_timing_cannot_pass() -> None:
    rows = _rows()
    for row in rows:
        if row["arm"] in {"user_picked", "agent_chosen"}:
            row["seconds"] = None
    result = _quality_score(rows)
    assert result["time_ratio_vs_practical"] is None
    assert not result["time_ok"]


def test_per_scenario_regression_is_not_hidden_by_aggregate_improvement() -> None:
    rows = _rows()
    for row in rows:
        if (
            row["scenario"] == "wrong-file" and row["arm"] == "lore"
            or row["scenario"] != "wrong-file" and row["arm"] != "lore"
        ):
            row["passed"] = False
            row["checks"]["target"] = False
    result = _quality_score(rows)
    assert result["lore_pass_rate"] > result["agent_chosen_pass_rate"]
    assert not result["primary"]
    assert not result["quality_claim"]


def test_observed_improvement_requires_repeats_and_all_other_gates() -> None:
    for runs in (1, 5):
        rows = _rows(runs)
        for row in rows:
            if row["scenario"] == "wrong-file" and row["arm"] != "lore":
                row["passed"] = False
                row["checks"]["target"] = False
        result = _quality_score(rows, expected_runs=runs)
        assert result["workflow_gate"]
        assert result["observed_improvement"]
        assert result["quality_claim"] is (runs >= 5)


def test_inconsistent_pass_flag_is_invalid() -> None:
    rows = _rows()
    rows[0]["checks"]["target"] = False
    assert not _quality_score(rows)["complete"]


def test_duration_boundary_is_not_rounded_into_a_pass() -> None:
    rows = _rows()
    for row in rows:
        if row["arm"] == "lore":
            row["seconds"] = 12.50001
    assert not _quality_score(rows)["time_ok"]


def test_model_invocation_requires_separate_approval(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LORE_BENCH_ALLOW_PAID", raising=False)
    with pytest.raises(SystemExit, match="explicit approval"):
        _BENCHMARK._agy(tmp_path, "do not run", log=tmp_path / "run.jsonl", timeout=1)
    assert not (tmp_path / "run.jsonl").exists()


def test_cache_cleanup_never_deletes_global_user_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cached = tmp_path / "lore-solo"
    cached.mkdir()
    marker = cached / "keep"
    marker.write_text("user cache", encoding="utf-8")
    monkeypatch.setattr(_BENCHMARK, "MCP_CACHE_ROOTS", (tmp_path,))
    _BENCHMARK._clear_agy_mcp_cache("lore-solo")
    assert marker.read_text(encoding="utf-8") == "user cache"


def test_tool_done_without_a_decision_receipt_is_not_process_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_BENCHMARK, "_mcp_get_context_ok", lambda _events: True)
    monkeypatch.setattr(_BENCHMARK, "_mcp_tool_done", lambda _events, _tool: True)
    assert not _BENCHMARK._lore_process([], tmp_path)["ok"]


@pytest.mark.parametrize("scenario", ["full-skill", "new-file", "cross-file", "stale-map", "no-map"])
def test_new_rubrics_require_the_expected_change(scenario: str, tmp_path: Path) -> None:
    import shutil

    source = _BENCHMARK.QUALITY_APP
    work = tmp_path / "work"
    shutil.copytree(source, work)
    originals = _BENCHMARK._quality_snapshots(source)
    if scenario == "stale-map":
        (work / "src/ui/Panel.tsx").rename(work / "src/ui/LivePanel.tsx")
    assert not all(_BENCHMARK._quality_rubric(scenario, work, originals).values())
    if scenario == "full-skill":
        panel = work / "src/ui/Panel.tsx"
        panel.write_text(
            panel.read_text(encoding="utf-8").replace(
                "<section ", '<section data-release-stamp="lore-approved-2026" ',
            ), encoding="utf-8",
        )
    elif scenario == "new-file":
        (work / "src/api/readiness.py").write_text(
            'def readiness() -> dict[str, str]:\n    return {"status": "ready"}\n',
            encoding="utf-8",
        )
    elif scenario == "cross-file":
        (work / "src/api/health.py").write_text(
            "from .service_state import ready_state\n\n"
            'def health() -> dict[str, str]:\n    return {"status": ready_state()}\n',
            encoding="utf-8",
        )
    else:
        panel = work / ("src/ui/LivePanel.tsx" if scenario == "stale-map" else "src/ui/Panel.tsx")
        panel.write_text(
            panel.read_text(encoding="utf-8").replace('"Draft"', '"Published"'),
            encoding="utf-8",
        )
    assert all(_BENCHMARK._quality_rubric(scenario, work, originals).values())


def test_new_rubrics_do_not_accept_comments_as_backend_implementation(tmp_path: Path) -> None:
    import shutil

    source = _BENCHMARK.QUALITY_APP
    work = tmp_path / "work"
    shutil.copytree(source, work)
    originals = _BENCHMARK._quality_snapshots(source)
    (work / "src/api/health.py").write_text(
        "# from .service_state import ready_state; status: ready_state()\n",
        encoding="utf-8",
    )
    assert not all(_BENCHMARK._quality_rubric("cross-file", work, originals).values())
    (work / "src/api/readiness.py").write_text(
        "# def readiness() -> dict[str, str]: return {'status': 'ready'}\n",
        encoding="utf-8",
    )
    assert not all(_BENCHMARK._quality_rubric("new-file", work, originals).values())


def test_quality_runner_rotates_arms_preserves_history_and_sets_map_modes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticks = count(1)
    clock = SimpleNamespace(**vars(_BENCHMARK.time))
    clock.monotonic = lambda: next(ticks)
    monkeypatch.setattr(_BENCHMARK, "time", clock)
    monkeypatch.setenv("LORE_BENCH_ALLOW_PAID", "1")
    monkeypatch.setattr(_BENCHMARK, "TMP", tmp_path / "runs")
    monkeypatch.setattr(_BENCHMARK, "_cold_map", lambda *_args, **_kw: 0.0)
    monkeypatch.setattr(_BENCHMARK, "_lore_process", lambda *_args: dict.fromkeys(
        ("get_context", "get_skill", "check_applied", "log_decision", "ok"), True,
    ))
    monkeypatch.setattr(_BENCHMARK, "_quality_rubric", lambda *_args: {"target": True})
    calls: list[str] = []

    def agent(work: Path, _prompt: str, *, log: Path, timeout: int) -> int:
        calls.append(work.name)
        log.write_text("", encoding="utf-8")
        config = json.loads((work / ".agents/mcp_config.json").read_text(encoding="utf-8"))
        if work.name == "no-map-lore-1":
            assert config["mcpServers"]["lore-solo"]["env"]["LORE_MAP_ENABLED"] == "0"
            assert not (work / "graphify-out").exists()
        if work.name == "stale-map-lore-1":
            assert (work / "src/ui/LivePanel.tsx").exists()
            assert not (work / "src/ui/Panel.tsx").exists()
        return 0

    monkeypatch.setattr(_BENCHMARK, "_agy", agent)
    historical = (_BENCHMARK.LIBRARY / "results-agy-quality.json").read_bytes()
    assert _BENCHMARK.quality(runs=1) == 0
    assert len(calls) == len(QUALITY_SCENARIOS) * 4
    assert calls[0] == "wrong-file-no_skills-1"
    assert calls[4] == "a11y-label-user_picked-1"
    result_paths = list((tmp_path / "runs").glob("quality-*/results.json"))
    assert len(result_paths) == 1
    result = json.loads(result_paths[0].read_text(encoding="utf-8"))
    assert result["score"]["complete"]
    assert not result["score"]["quality_claim"]
    assert set(result["task_sha256"]) == set(QUALITY_SCENARIOS)
    assert (_BENCHMARK.LIBRARY / "results-agy-quality.json").read_bytes() == historical
