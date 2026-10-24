"""The folder window returns a path without the page drawing one."""

from __future__ import annotations

import subprocess

import pytest
from lore.core.picker import pick_folder


def test_cancel_returns_no_folder(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("lore.core.picker.shutil.which", lambda _name: "/usr/bin/zenity")

    def run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")

    assert pick_folder(run) == ""


def test_a_chosen_folder_is_returned(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("lore.core.picker.shutil.which", lambda _name: "/usr/bin/zenity")

    def run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="/home/person/Work/Lore/\n", stderr="")

    assert pick_folder(run) == "/home/person/Work/Lore"


def test_missing_dialog_is_explained(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("lore.core.picker.shutil.which", lambda _name: None)
    with pytest.raises(ValueError, match="folder window"):
        pick_folder()
