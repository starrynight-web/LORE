from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def clear_workspace_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """A developer shell may set LORE_WORKSPACE. Tests choose the folder themselves."""
    monkeypatch.delenv("LORE_WORKSPACE", raising=False)
