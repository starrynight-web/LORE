"""Inventory IDE skills and file them under benchmark personas.

Counts every SKILL.md and editor rule it finds. Files one copy of each skill
name. Only the reviewed in-scope names are marked stable. Re-running replaces
`.lore` in the benchmark library and leaves PROTOCOL.md in place.

    .venv/bin/python scripts/build_bench_library.py
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from lore.core.personas import write_persona, write_skill
from lore.core.workspace import init_workspace

ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "examples" / "bench-library"
HOME = Path.home()

# Reviewed before any timed run. These descriptions apply to changing a web app.
# Everything else is filed as a draft and is not served.
ALLOW: dict[str, str] = {
    "frontend-design": "frontend-engineer",
    "tailwind-best-practices": "frontend-engineer",
    "shadcn-best-practices": "frontend-engineer",
    "vercel-react-best-practices": "frontend-engineer",
    "design-taste-frontend": "frontend-engineer",
    "minimalist-ui": "frontend-engineer",
    "web-a11y-authoring": "accessibility-engineer",
    "web-a11y-review": "accessibility-engineer",
    "create-a-backend": "backend-engineer",
    "supabase-postgres-best-practices": "backend-engineer",
    "review-security": "reviewer",
    "web-design-guidelines": "reviewer",
}

DRAFT_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("payments", ("stripe", "metronome")),
    ("design-tools", ("figma",)),
    ("video", ("remotion",)),
    ("workspace", ("notion",)),
    ("community", ("devrelay", "mlh", "hacktober", "hackathon")),
    ("editor", ("automate", "autopilot", "canvas", "cursor", "codex", "skill-creator", "claude")),
    ("accessibility-engineer", ("a11y", "accessibility")),
    ("reviewer", ("review", "bugbot")),
    ("backend-engineer", ("supabase", "postgres", "backend")),
    ("frontend-engineer", ("react", "tailwind", "frontend", "shadcn", "css", "ui")),
    ("platform", ("vercel",)),
)

SUMMARIES = {
    "frontend-engineer": "UI work uses the React, Tailwind, and design skills filed here.",
    "accessibility-engineer": "Accessibility work uses the authoring and review skills filed here.",
    "backend-engineer": "API and data work uses the backend skills filed here.",
    "reviewer": "Review work uses the security and interface-guideline skills filed here.",
    "payments": "Payment skills. Draft. Not served.",
    "design-tools": "Design-tool skills. Draft. Not served.",
    "video": "Video skills. Draft. Not served.",
    "workspace": "Workspace skills. Draft. Not served.",
    "community": "Community skills. Draft. Not served.",
    "editor": "Editor skills. Draft. Not served.",
    "platform": "Platform skills. Draft. Not served.",
    "other": "Skills that match no reviewed group. Draft. Not served.",
}


def main() -> None:
    skills = _skill_files()
    rules = _rule_files()
    chosen = _dedupe(skills)
    lore = LIBRARY / ".lore"
    if lore.exists():
        shutil.rmtree(lore)
    init_workspace(LIBRARY)
    filed: list[dict[str, Any]] = []
    personas: set[str] = set()
    for name, path in sorted(chosen.items()):
        header, body = _split(path)
        description = _text(header.get("description") or header.get("summary") or "")
        persona, status = _classify(name, description, path)
        personas.add(persona)
        filed.append(
            {
                "name": name,
                "source": str(path),
                "description": description,
                "persona": persona,
                "status": status,
            }
        )
    for persona in sorted(personas):
        write_persona(
            LIBRARY,
            persona,
            SUMMARIES.get(persona, SUMMARIES["other"]),
            f"You are the {persona.replace('-', ' ')}. Use only the skills filed under this persona.\n",
            status="stable" if any(row["status"] == "stable" and row["persona"] == persona for row in filed) else "draft",
        )
    for row in filed:
        header, body = _split(Path(row["source"]))
        title = _text(header.get("name") or row["name"]).replace("-", " ")
        summary = row["description"].split("\n", 1)[0][:160] or title
        write_skill(
            LIBRARY,
            row["persona"],
            row["name"],
            title=title or row["name"],
            summary=summary,
            body=body if body.strip() else summary + "\n",
            status=row["status"],
        )
    inventory = {
        "counted_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "skill_files": len(skills),
        "rule_files": [{"path": str(path), "name": path.name} for path in rules],
        "unique_names": len(chosen),
        "stable": [row["name"] for row in filed if row["status"] == "stable"],
        "files": _every_row(skills, {row["name"]: row for row in filed}),
    }
    (LIBRARY / "inventory.json").write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    print(
        f"skills {len(skills)} unique {len(chosen)} stable {len(inventory['stable'])} rules {len(rules)}"
    )


def _every_row(skills: list[Path], by_name: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in skills:
        header, _body = _split(path)
        name = _name(path, header)
        chosen = by_name.get(name, {})
        description = _text(header.get("description") or header.get("summary") or "")
        rows.append(
            {
                "name": name,
                "source": str(path),
                "description": description[:500],
                "persona": chosen.get("persona", "other"),
                "status": chosen.get("status", "draft"),
                "filed": chosen.get("source") == str(path),
            }
        )
    return rows


def _skill_files() -> list[Path]:
    roots = [
        HOME / ".agents" / "skills",
        HOME / ".cursor" / "skills",
        HOME / ".cursor" / "skills-cursor",
        HOME / ".cursor" / "plugins" / "cache",
        HOME / ".codex",
        HOME / ".claude",
    ]
    found: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        found.extend(path for path in root.rglob("SKILL.md") if path.is_file())
    return sorted(found)


def _rule_files() -> list[Path]:
    roots = [HOME / ".cursor", HOME / ".codex", HOME / ".claude", HOME / ".agents"]
    found: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix == ".mdc" or path.name in {"AGENTS.md", "CLAUDE.md"}:
                found.append(path)
    return sorted(found)


def _dedupe(paths: list[Path]) -> dict[str, Path]:
    groups: dict[str, list[Path]] = {}
    for path in paths:
        header, _body = _split(path)
        groups.setdefault(_name(path, header), []).append(path)
    return {name: min(options, key=_rank) for name, options in groups.items()}


def _rank(path: Path) -> tuple[int, int]:
    text = path.as_posix()
    if "/.tmp/" in text or "/upstream/" in text:
        return (9, len(text))
    if "/.agents/skills/" in text:
        return (0, len(text))
    if "/.cursor/skills/" in text and "/skills-cursor/" not in text:
        return (1, len(text))
    if "/skills-cursor/" in text:
        return (2, len(text))
    if "/.claude/skills/" in text:
        return (3, len(text))
    return (5, len(text))


def _classify(name: str, description: str, path: Path) -> tuple[str, str]:
    if name in ALLOW:
        return ALLOW[name], "stable"
    blob = f"{name} {description} {path.as_posix()}".lower()
    for persona, needles in DRAFT_RULES:
        if any(needle in blob for needle in needles):
            return persona, "draft"
    return "other", "draft"


def _name(path: Path, header: dict[str, Any]) -> str:
    raw = _text(header.get("name") or path.parent.name)
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in raw.strip())
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or path.parent.name


def _split(path: Path) -> tuple[dict[str, Any], str]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}, ""
    if not text.startswith("---"):
        return {}, text
    rest = text[3:].removeprefix("\n")
    end = rest.find("\n---")
    if end < 0:
        return {}, text
    try:
        loaded = yaml.safe_load(rest[:end])
    except yaml.YAMLError:
        loaded = {}
    header = loaded if isinstance(loaded, dict) else {}
    return header, rest[end + 4 :].lstrip("\n")


def _text(value: object) -> str:
    return str(value or "").strip()


if __name__ == "__main__":
    main()
