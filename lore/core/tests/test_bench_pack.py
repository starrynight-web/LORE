from __future__ import annotations

import json
from pathlib import Path

from lore.core.personas import list_personas, served_skills

LIBRARY = Path("examples/bench-library")


def test_only_the_reviewed_skills_are_served() -> None:
    inventory = json.loads((LIBRARY / "inventory.json").read_text(encoding="utf-8"))
    stable = set(inventory["stable"])
    assert stable == {
        "create-a-backend",
        "design-taste-frontend",
        "frontend-design",
        "minimalist-ui",
        "review-security",
        "shadcn-best-practices",
        "supabase-postgres-best-practices",
        "tailwind-best-practices",
        "vercel-react-best-practices",
        "web-a11y-authoring",
        "web-a11y-review",
        "web-design-guidelines",
    }
    served: set[str] = set()
    for doc in list_personas(LIBRARY):
        for skill in served_skills(LIBRARY, doc.get("id")):
            served.add(skill.get("id").split("/")[-1].split("@", 1)[0])
        if doc.get("status") != "stable":
            assert served_skills(LIBRARY, doc.get("id")) == []
    assert served == stable
