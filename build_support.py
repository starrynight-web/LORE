"""Release-wheel checks. Web source and build output stay out of the wheel.

The setup site ships as separate per-platform zip artifacts; the wheel carries
only the manifest (`lore/site_bundles.json`) and the pinned constraints
(`lore/release_constraints.txt`). `LORE_RELEASE_BUILD=1` makes a missing or
incomplete manifest a hard error so a release cannot ship without bundles.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tomllib
from pathlib import Path
from typing import Any


def _meta() -> Any:
    """Load lore/site_bundle_meta.py by path (no package import needed)."""
    path = Path(__file__).resolve().parent / "lore" / "site_bundle_meta.py"
    spec = importlib.util.spec_from_file_location("lore_site_bundle_meta", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _release_manifest_errors(root: Path) -> list[str]:
    bundle_meta = _meta()
    errors: list[str] = []
    manifest_path = root / "lore" / "site_bundles.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"lore/site_bundles.json is missing or unreadable: {exc}"]
    version = ""
    try:
        meta = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        version = str(meta["project"]["version"])
    except (OSError, tomllib.TOMLDecodeError, KeyError) as exc:
        errors.append(f"pyproject.toml version is unreadable: {exc}")
    if not isinstance(manifest, dict):
        return ["lore/site_bundles.json: manifest must be an object"]
    if type(manifest.get("schema_version")) is not int or manifest["schema_version"] != 1:
        errors.append("site_bundles.json: schema_version must be 1")
    if version and manifest.get("lore_version") != version:
        errors.append(
            f"site_bundles.json: lore_version {manifest.get('lore_version')!r} != {version!r}"
        )
    bundles = manifest.get("bundles")
    if not isinstance(bundles, dict):
        errors.append("site_bundles.json: bundles must be an object")
        return errors
    for platform_key in bundle_meta.PLATFORMS:
        entry = bundles.get(platform_key)
        if not bundle_meta.valid_entry(entry, platform_key):
            errors.append(f"site_bundles.json: bundle entry for {platform_key} is invalid")
    return errors


def _release_check() -> None:
    if os.environ.get("LORE_RELEASE_BUILD") != "1":
        return
    root = Path(__file__).resolve().parent
    errors = _release_manifest_errors(root)
    if errors:
        sys.stderr.write("LORE_RELEASE_BUILD=1 but the site manifest is incomplete:\n")
        for error in errors:
            sys.stderr.write(f"  - {error}\n")
        raise SystemExit(1)


def __getattr__(name: str) -> Any:
    if name == "BuildPy":
        from setuptools.command.build_py import build_py  # type: ignore[import-untyped]

        class BuildPy(build_py):  # type: ignore[misc]
            def run(self) -> None:
                super().run()
                _release_check()

        return BuildPy
    raise AttributeError(name)
