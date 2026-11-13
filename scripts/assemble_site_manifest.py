#!/usr/bin/env python3
"""Merge per-platform bundle fragments into lore/site_bundles.json.

Reads `lore-site-VERSION-PLATFORM.zip` archives plus their `.json` sidecars
from one artifacts directory, verifies every declared hash/size/platform
against the archive contents, then writes a deterministic manifest. This
script never publishes anything.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lore.release import bundle_url, release_version
from lore.site_bundle import SiteError, safe_extract, validate_inner_manifest
from lore.site_bundle_meta import valid_entry


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _expanded_size(root: Path) -> int:
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def _verify_archive_inner(
    archive: Path, entry: dict[str, Any], version: str, platform_key: str
) -> None:
    """Extract into a temp dir and compare the inner manifest to the fragment."""
    staging = Path(tempfile.mkdtemp(prefix=".verify-", dir=archive.parent))
    try:
        safe_extract(archive, staging, platform_key=platform_key)
        inner = validate_inner_manifest(staging, version, platform_key)
        if inner["build_id"] != entry["build_id"]:
            raise SystemExit(
                f"{archive.name}: inner build id does not match its fragment"
            )
        expanded = _expanded_size(staging)
        if expanded != entry["expanded_size"]:
            raise SystemExit(
                f"{archive.name}: expanded_size {expanded} != fragment "
                f"{entry['expanded_size']}"
            )
    except SiteError as exc:
        raise SystemExit(f"{archive.name}: {exc}") from exc
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def collect(artifacts: Path, version: str) -> dict[str, Any]:
    """Validated bundle entries keyed by platform."""
    entries: dict[str, dict[str, Any]] = {}
    build_ids: set[str] = set()
    for sidecar in sorted(artifacts.glob(f"lore-site-{version}-*.json")):
        try:
            entry = json.loads(sidecar.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{sidecar.name}: not valid JSON: {exc}")
        platform_key = sidecar.name[
            len(f"lore-site-{version}-") : -len(".json")
        ]
        if not isinstance(entry, dict):
            raise SystemExit(f"{sidecar.name}: fragment is not an object")
        if entry.get("platform") != platform_key:
            raise SystemExit(
                f"{sidecar.name}: platform {entry.get('platform')!r} does not "
                "match its filename"
            )
        if not valid_entry(entry, platform_key):
            raise SystemExit(f"{sidecar.name}: fragment fails validation")
        if platform_key in entries:
            raise SystemExit(f"{sidecar.name}: duplicate platform {platform_key!r}")
        if entry["url"] != bundle_url(platform_key, version):
            raise SystemExit(f"{sidecar.name}: url does not match the release layout")
        archive = sidecar.with_suffix(".zip")
        if not archive.is_file():
            raise SystemExit(f"{sidecar.name}: no matching zip {archive.name}")
        if _sha256(archive) != entry["sha256"]:
            raise SystemExit(f"{archive.name}: sha256 does not match its fragment")
        if archive.stat().st_size != entry["archive_size"]:
            raise SystemExit(f"{archive.name}: archive_size does not match its fragment")
        _verify_archive_inner(archive, entry, version, platform_key)
        build_ids.add(str(entry["build_id"]))
        entries[platform_key] = entry
    if not entries:
        found = sorted(path.name for path in artifacts.rglob(f"lore-site-{version}-*.json"))
        hint = f" (found nested: {', '.join(found)})" if found else ""
        raise SystemExit(
            f"no lore-site-{version}-*.json fragments in {artifacts}{hint}"
        )
    if len(build_ids) > 1:
        detail = ", ".join(
            f"{platform}={entry['build_id'][:12]}…"
            for platform, entry in sorted(entries.items())
        )
        raise SystemExit(
            "bundle fragments were built from different sources: " + detail
        )
    return entries


def merge(artifacts: Path, version: str) -> dict[str, Any]:
    entries = collect(artifacts, version)
    return {
        "schema_version": 1,
        "lore_version": version,
        "bundles": {key: entries[key] for key in sorted(entries)},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="assemble_site_manifest.py")
    parser.add_argument("--artifacts", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--version", default=release_version())
    args = parser.parse_args(argv)
    manifest = merge(args.artifacts, args.version)
    args.output.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
