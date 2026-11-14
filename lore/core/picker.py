"""Open the operating system's folder dialog.

The website runs on this computer, so the dialog can return a real folder.
The page shows the folder's name. The full path stays on the server.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

Runner = Callable[..., subprocess.CompletedProcess[str]]

_TITLE = "Choose a project folder"


def folder_commands(title: str = _TITLE) -> list[list[str]]:
    system = platform.system()
    home = str(Path.home())
    safe = title.replace('"', "'")
    if system == "Darwin":
        script = f'POSIX path of (choose folder with prompt "{safe}")'
        return [["osascript", "-e", script]]
    if system == "Windows":
        command = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$dialog = New-Object System.Windows.Forms.FolderBrowserDialog; "
            f"$dialog.Description = '{safe}'; "
            "if ($dialog.ShowDialog() -eq 'OK') { Write-Output $dialog.SelectedPath }"
        )
        return [["powershell", "-NoProfile", "-STA", "-Command", command]]
    zenity = ["zenity", "--file-selection", "--directory", f"--title={safe}"]
    kdialog = ["kdialog", "--getexistingdirectory", home, "--title", safe]
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "") + os.environ.get("DESKTOP_SESSION", "")
    if "KDE" in desktop or "plasma" in desktop.lower():
        return [kdialog, zenity]
    return [zenity, kdialog]


def pick_folder(run: Runner | None = None, *, title: str = _TITLE) -> str:
    """Return the chosen folder, or an empty string when the person cancels."""
    available = [cmd for cmd in folder_commands(title) if shutil.which(cmd[0])]
    if not available:
        raise ValueError("This computer has no folder window to open.")
    runner = run or subprocess.run
    command = available[0]
    completed = runner(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip().rstrip("/\\")
