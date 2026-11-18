"""Fetch multi-sector skills from skills.sh and build benchmark skill stores.

Usage:
    .venv/bin/python scripts/fetch_bench_skills.py
"""

from __future__ import annotations

import shutil
import urllib.request
from pathlib import Path
from typing import Any

import yaml
from lore.core.inbox import _fetch_skill
from lore.core.okf import write_doc
from lore.core.personas import write_persona, write_skill

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "examples" / "bench-intensive-skills"
RAW_DIR = DEST / "raw"
DEVICE_DIR = DEST / "device_skills"
LORE_DIR = DEST / ".lore"

# (persona_slug, source, skill_id, lore_status)
REGISTRY_SKILLS: tuple[tuple[str, str, str, str], ...] = (
    # Frontend
    ("frontend-engineer", "anthropics/skills", "frontend-design", "stable"),
    ("frontend-engineer", "leonxlnx/taste-skill", "design-taste-frontend", "stable"),
    ("frontend-engineer", "leonxlnx/taste-skill", "design-taste-frontend-v1", "draft"),
    ("frontend-engineer", "leonxlnx/taste-skill", "imagegen-frontend-web", "draft"),
    ("frontend-engineer", "leonxlnx/taste-skill", "imagegen-frontend-mobile", "draft"),
    # Backend
    ("backend-engineer", "wshobson/agents", "nodejs-backend-patterns", "stable"),
    ("backend-engineer", "affaan-m/ecc", "backend-patterns", "stable"),
    ("backend-engineer", "clerk/skills", "clerk-backend-api", "draft"),
    ("backend-engineer", "wshobson/agents", "dotnet-backend-patterns", "draft"),
    ("backend-engineer", "microsoft/azure-skills", "azure-aigateway", "draft"),
    # Database
    ("database-engineer", "prisma/skills", "prisma-database-setup", "stable"),
    ("database-engineer", "wshobson/agents", "database-migration", "stable"),
    ("database-engineer", "microsoft/azure-skills", "azure-storage", "draft"),
    ("database-engineer", "samber/cc-skills-golang", "golang-database", "draft"),
    # Motion
    ("motion-engineer", "heygen-com/hyperframes", "hyperframes-animation", "stable"),
    ("motion-engineer", "heygen-com/hyperframes", "motion-graphics", "stable"),
    ("motion-engineer", "heygen-com/hyperframes", "remotion-to-hyperframes", "draft"),
    ("motion-engineer", "heygen-com/hyperframes", "hyperframes-creative", "draft"),
    # Security
    ("security-engineer", "addyosmani/agent-skills", "security-and-hardening", "stable"),
    ("security-engineer", "better-auth/skills", "better-auth-security-best-practices", "stable"),
    ("security-engineer", "firebase/agent-skills", "firebase-security-rules-auditor", "draft"),
    ("security-engineer", "samber/cc-skills-golang", "golang-security", "draft"),
    # Accessibility & Testing
    ("accessibility-engineer", "addyosmani/web-quality-skills", "accessibility", "stable"),
    ("accessibility-engineer", "jakubkrehel/skills", "better-accessibility", "stable"),
    ("accessibility-engineer", "ibelick/ui-skills", "fixing-accessibility", "stable"),
    ("accessibility-engineer", "mattpocock/skills", "tdd", "stable"),
)

PERSONAS: dict[str, dict[str, str]] = {
    "frontend-engineer": {
        "title": "Frontend Engineer",
        "summary": "React, TypeScript, Tailwind, UI components, sprint board, reading time footer, and slash menu blocks.",
        "body": "You are the frontend engineer. Follow the approved frontend standards and UI design skills.",
    },
    "backend-engineer": {
        "title": "Backend Engineer",
        "summary": "API envelopes, registration state machines, readiness checklist scoring, and TypeScript service modules.",
        "body": "You are the backend engineer. Follow the approved backend patterns and envelope conventions.",
    },
    "database-engineer": {
        "title": "Database Engineer",
        "summary": "Schema versioning, persistence models, registration records, and data migration integrity.",
        "body": "You are the database engineer. Follow the approved database schema and persistence standards.",
    },
    "motion-engineer": {
        "title": "Motion Engineer",
        "summary": "Reduced-motion policies, stage transitions, find bar animation attributes, and UI motion safety.",
        "body": "You are the motion engineer. Follow the approved motion and reduced-motion standards.",
    },
    "security-engineer": {
        "title": "Security Engineer",
        "summary": "URL sanitization, wikilink traversal protection, path safety, and approval-gated venue redaction.",
        "body": "You are the security engineer. Follow the approved security hardening and input validation standards.",
    },
    "accessibility-engineer": {
        "title": "Accessibility Engineer",
        "summary": "ARIA tablist keyboard navigation, aria-live status announcements, find bar search landmarks, and testing.",
        "body": "You are the accessibility engineer. Follow the approved accessibility and testing standards.",
    },
}

STANDARDS_SKILLS: list[dict[str, Any]] = [
    {
        "persona": "frontend-engineer",
        "id": "frontend-standards",
        "title": "Project Frontend Standards",
        "summary": "React UI conventions for SprintBoard data-surface, readingTime formula, footer data-stat, and Callout slash block.",
        "tags": ["frontend", "react", "sprintboard", "reading", "footer", "callout", "slash", "board", "ui"],
        "body": (
            "# Project Frontend Standards\n\n"
            "1. **Devin-a-thon Dhaka SprintBoard (`src/SprintBoard.tsx`):**\n"
            "   - Render the root container with `data-surface=\"devin-dhaka-board\"`.\n"
            "   - Support the 6 stages: `Brainstorming`, `Planning`, `Writing Code`, `Implementing Features`, `Debugging`, `Shipping`.\n"
            "2. **Simple Write Reading Time & Callout:**\n"
            "   - Export `readingTime(text: string): number` from `src/lib/documents.ts`: return `0` when `wordCount(text) === 0`, otherwise `Math.max(1, Math.ceil(wordCount(text) / 200))`.\n"
            "   - Render `<span data-stat=\"reading-time\">{readingTime(active.draft)} min read</span>` in the desktop editor footer in `src/App.tsx`.\n"
            "   - Add a `callout` item to `slashDefinitions` in `src/editor/extensions.tsx` with `id: \"callout\"`, `label: \"Callout\"`, `keywords: \"note warning info\"` inserting `> **Note:** `.\n"
            "   - Never modify files under `website/`.\n"
        ),
    },
    {
        "persona": "backend-engineer",
        "id": "backend-standards",
        "title": "Project Backend & API Envelope Standards",
        "summary": "Standard `{ ok, data, error_code }` API envelope, Devin-a-thon Dhaka metadata constants, and readiness scoring.",
        "tags": ["backend", "api", "envelope", "registration", "readiness", "checklist", "planner", "dhaka"],
        "body": (
            "# Project Backend & API Envelope Standards\n\n"
            "1. **Result Envelope:** All service functions return `{ ok: true, data: T }` on success or `{ ok: false, error_code: string, message?: string }` on failure.\n"
            "2. **Devin-a-thon Dhaka Event Constants:**\n"
            "   - `date`: `\"2026-11-21\"`\n"
            "   - `schedule`: `\"16:00-18:00 BST (UTC+6)\"`\n"
            "   - `area`: `\"North End, Dhaka\"`\n"
            "3. **Readiness Planner (`src/readiness.ts`):**\n"
            "   - Evaluate the 5 preparation items (`projectIdea`, `laptopCharger`, `githubRepo`, `workflowPlan`, `agentQuestions`).\n"
            "   - Return `{ ok: true, data: { ready: boolean, score: number, missing: string[] } }` where `score` is `0..100` (20 points per item) and `ready` is `true` only when `score === 100`.\n"
        ),
    },
    {
        "persona": "database-engineer",
        "id": "database-standards",
        "title": "Project Database & Schema Versioning Standards",
        "summary": "Record schema_version: 1, registration status enum, and venue redaction persistence rules.",
        "tags": ["database", "schema", "registration", "persistence", "venue", "approval", "storage"],
        "body": (
            "# Project Database & Schema Versioning Standards\n\n"
            "1. Every persisted registration record created by `submitRegistration` must include `schema_version: 1`.\n"
            "2. Registration status must start as `\"pending_approval\"` and transition only via `reviewRegistration` to `\"approved\"` or `\"rejected\"`.\n"
            "3. `getVenueInfo(record)` must return `exactAddress: \"Revealed after host approval\"` whenever `record.status !== \"approved\"`.\n"
        ),
    },
    {
        "persona": "motion-engineer",
        "id": "motion-standards",
        "title": "Project Motion & Reduced-Motion Standards",
        "summary": "Enforce data-motion-policy='respect-reduced-motion' on interactive boards and find bars.",
        "tags": ["motion", "animation", "reduced-motion", "sprintboard", "find", "board", "ui"],
        "body": (
            "# Project Motion & Reduced-Motion Standards\n\n"
            "1. Every interactive animated surface (`SprintBoard` root and the desktop Find bar container) must carry `data-motion-policy=\"respect-reduced-motion\"`.\n"
            "2. Avoid non-composited layout animations; prefer CSS opacity/transform transitions gated by `motion-safe:`.\n"
        ),
    },
    {
        "persona": "security-engineer",
        "id": "security-standards",
        "title": "Project Security & Input Sanitization Standards",
        "summary": "URL protocol allowlisting, ERR_UNSAFE_URL, ERR_UNSAFE_TARGET_PATH, sanitizeLinkHref, and isSafeWikilinkTarget.",
        "tags": ["security", "sanitize", "url", "wikilink", "links", "traversal", "registration", "readiness"],
        "body": (
            "# Project Security & Input Sanitization Standards\n\n"
            "1. **Registration Repo URLs (`src/registration.ts`):** Reject `javascript:`, `data:`, `vbscript:`, or non-`https://` repo URLs with `{ ok: false, error_code: \"ERR_UNSAFE_URL\" }`.\n"
            "2. **Delegation Target Paths (`src/readiness.ts`):** Reject target paths containing `..`, null bytes, `;`, `|`, `&`, or `$()` with `{ ok: false, error_code: \"ERR_UNSAFE_TARGET_PATH\" }`.\n"
            "3. **Simple Write Links (`src/lib/documents.ts` & editor):**\n"
            "   - Export `sanitizeLinkHref(raw: string): string | null`: trim input, reject empty, control chars, `javascript:`, `vbscript:`, and `data:text/html` (case-insensitive); allow `https://`, `http://`, `mailto:`, and `#` anchors.\n"
            "   - Export `isSafeWikilinkTarget(target: string): boolean`: return `false` if empty or contains `..`, `/`, `\\\\`, or `\\0`.\n"
            "   - Guard `applyLink` in `src/components/write-editor.tsx` and `openLinked` in `src/App.tsx` using these helpers.\n"
        ),
    },
    {
        "persona": "accessibility-engineer",
        "id": "a11y-standards",
        "title": "Project Accessibility Standards",
        "summary": "ARIA tablist/tab keyboard navigation, aria-live='polite' status regions, and Find bar search landmark.",
        "tags": ["accessibility", "a11y", "aria", "keyboard", "tablist", "find", "search", "live", "sprintboard"],
        "body": (
            "# Project Accessibility Standards\n\n"
            "1. **SprintBoard (`src/SprintBoard.tsx`):**\n"
            "   - Stage selector uses `role=\"tablist\"` with `role=\"tab\"` buttons and `aria-selected`.\n"
            "   - `ArrowRight` and `ArrowLeft` cycle active stage with wrap-around.\n"
            "   - Include `<div aria-live=\"polite\" data-stage-live>Current stage: {activeStage}</div>`.\n"
            "2. **Simple Write Find Bar (`src/App.tsx`):**\n"
            "   - Find bar wrapper must have `role=\"search\"`, `aria-label=\"Find in document\"`, and `data-motion-policy=\"respect-reduced-motion\"`.\n"
            "   - Match counter must have `aria-live=\"polite\"` and `data-find-status=\"match-count\"`, showing `\"No matches\"` when `findQuery` is non-empty and `findCount === 0`, or `\"${activeMatch} of ${findCount} matches\"` when `findCount > 0`.\n"
        ),
    },
]


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
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
    meta = dict(loaded) if isinstance(loaded, dict) else {}
    body = rest[end + 4 :].removeprefix("\n")
    return meta, body


def _write_native_skill(name: str, description: str, body: str) -> None:
    folder = DEVICE_DIR / name
    folder.mkdir(parents=True, exist_ok=True)
    safe_desc = " ".join(description.split()).replace('"', "'")
    content = f'---\nname: {name}\ndescription: "{safe_desc}"\n---\n\n{body.strip()}\n'
    (folder / "SKILL.md").write_text(content, encoding="utf-8")


def main() -> None:
    if DEVICE_DIR.exists():
        shutil.rmtree(DEVICE_DIR)
    if LORE_DIR.exists():
        shutil.rmtree(LORE_DIR)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    DEVICE_DIR.mkdir(parents=True, exist_ok=True)
    LORE_DIR.mkdir(parents=True, exist_ok=True)
    (LORE_DIR / "lore.config.yaml").write_text("token_budget: 800\nmax_items: 8\n", encoding="utf-8")

    for slug, info in PERSONAS.items():
        write_persona(
            DEST,
            slug,
            info["summary"],
            info["body"],
            title=info["title"],
            status="stable",
        )

    fetched = 0
    for persona, source, skill_id, status in REGISTRY_SKILLS:
        raw_path = RAW_DIR / f"{persona}__{skill_id}.md"
        if raw_path.is_file():
            text = raw_path.read_text(encoding="utf-8")
        else:
            try:
                text = _fetch_skill(source, skill_id, urllib.request.urlopen)
            except ValueError as exc:
                print(f"[skip] {source}/{skill_id}: {exc}")
                continue
            raw_path.write_text(text, encoding="utf-8")
        fetched += 1
        meta, body = _split_frontmatter(text)
        desc = str(meta.get("description") or f"Guidance from {source}/{skill_id}.")[:240]
        title = str(meta.get("name") or skill_id).replace("-", " ")
        _write_native_skill(skill_id, desc, body)
        write_skill(
            DEST,
            persona,
            f"{skill_id}@v1",
            title=title,
            summary=desc,
            body=body,
            status=status,
        )
        print(f"[ok] {source}/{skill_id} -> {persona} ({status})")

    for std in STANDARDS_SKILLS:
        _write_native_skill(std["id"], std["summary"], std["body"])
        doc = write_skill(
            DEST,
            std["persona"],
            f"{std['id']}@v1",
            title=std["title"],
            summary=std["summary"],
            body=std["body"],
            status="stable",
        )
        doc.header["tags"] = std["tags"]
        if doc.path is not None:
            write_doc(doc.path, doc)
        print(f"[std] {std['id']} -> {std['persona']} (stable)")

    print(
        f"Done: {fetched} skills.sh skills + {len(STANDARDS_SKILLS)} standards skills "
        f"written to {DEVICE_DIR} and {LORE_DIR}"
    )


if __name__ == "__main__":
    main()
