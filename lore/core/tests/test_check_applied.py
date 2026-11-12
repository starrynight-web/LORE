from __future__ import annotations

import shutil
from pathlib import Path

from lore.core.check_applied import check_applied
from lore.core.context import get_context
from lore.core.decisions import allocate
from lore.core.tests.pack import PACK


def _copy(tmp_path: Path) -> Path:
    dest = tmp_path / "app"
    shutil.copytree(PACK, dest)
    return dest


def test_check_applied_pass_fail_skip(tmp_path: Path) -> None:
    project = _copy(tmp_path)
    envelope = get_context(project, "frontend-engineer", "tighten the button", "src/ui/Button.tsx")
    decision_id = str(envelope["decision_id"])
    cite_ids = list(envelope["data"]["cite_ids"])
    assert cite_ids

    ok = check_applied(project, decision_id, cite_ids[:1])
    assert ok["status"] == "pass"
    assert ok["check_kind"] == "citation_receipt"
    assert ok["code_verified"] is False
    assert "not verified" in ok["summary"]

    bad = check_applied(project, decision_id, ["skill:nope/missing@v1"])
    assert bad["status"] == "fail"
    assert bad["check_kind"] == "citation_receipt"
    assert bad["code_verified"] is False
    assert "skill:nope/missing@v1" in bad["unknown"]

    empty = check_applied(project, decision_id, [])
    assert empty["status"] == "fail"

    blank = allocate(
        project,
        {
            "tool": "get_context",
            "verdict": "no_knowledge",
            "directive": "proceed",
            "persona": "task",
            "included": [],
            "omitted": [],
            "client": "test",
        },
        "Nothing.\n",
    )
    skipped = check_applied(project, str(blank.get("id")), ["skill:x"])
    assert skipped["status"] == "skip"
    assert skipped["check_kind"] == "citation_receipt"
    assert skipped["code_verified"] is False
    assert "not verified" in skipped["summary"]
