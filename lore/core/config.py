"""Read `.lore/lore.config.yaml`. Missing keys use the solo defaults."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

DEFAULT_TOKEN_BUDGET = 800
DEFAULT_MAX_ITEMS = 8


def save_config(lore_dir: Path, token_budget: int, max_items: int) -> dict[str, int]:
    if token_budget < 1 or max_items < 1:
        raise ValueError("token_budget and max_items must be at least 1")
    path = lore_dir / "lore.config.yaml"
    loaded: dict[str, Any] = {}
    if path.is_file():
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            loaded = raw
    loaded["token_budget"] = int(token_budget)
    loaded["max_items"] = int(max_items)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(loaded, sort_keys=False), encoding="utf-8")
    return {"token_budget": int(token_budget), "max_items": int(max_items)}


def load_config(lore_dir: Path) -> dict[str, int]:
    path = lore_dir / "lore.config.yaml"
    loaded: dict[str, Any] = {}
    if path.is_file():
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            loaded = raw
    budget = loaded.get("token_budget", DEFAULT_TOKEN_BUDGET)
    items = loaded.get("max_items", DEFAULT_MAX_ITEMS)
    return {"token_budget": int(budget), "max_items": int(items)}
