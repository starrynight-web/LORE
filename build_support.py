"""Copy the setup site into the wheel. Dependencies and build output stay out."""

from __future__ import annotations

import shutil
from pathlib import Path

from setuptools.command.build_py import build_py


class BuildPy(build_py):
    def run(self) -> None:
        super().run()
        src = Path(__file__).resolve().parent / "web"
        if not (src / "package.json").is_file():
            return
        dest = Path(self.build_lib) / "lore" / "web_src"
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(
            src,
            dest,
            ignore=shutil.ignore_patterns("node_modules", ".next", "tsconfig.tsbuildinfo"),
        )
