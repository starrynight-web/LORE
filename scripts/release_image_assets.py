#!/usr/bin/env python3
"""Stage verified release artifacts for the image build.

Runs inside the Dockerfile `wheels` stage when LORE_RELEASE_ARTIFACTS=1.
Fail-closed: requires exactly one release wheel, an external constraints
file that matches the wheel's embedded constraints, and — for the `full`
image — the linux-amd64 site archive pinned by the wheel's own manifest.
The pinned archive is extracted only through `lore.site_bundle.ensure_site`,
never a raw unzip.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


def _fail(message: str) -> SystemExit:
    print(f"release artifacts: {message}", file=sys.stderr)
    return SystemExit(2)


def _wheel_metadata(wheel: Path) -> tuple[str, str]:
    try:
        with zipfile.ZipFile(wheel) as zf:
            meta_name = next(
                (n for n in zf.namelist() if n.endswith(".dist-info/METADATA")),
                None,
            )
            if meta_name is None:
                raise _fail(f"{wheel.name} has no dist-info METADATA")
            meta = zf.read(meta_name).decode("utf-8", "replace")
    except zipfile.BadZipFile:
        raise _fail(f"{wheel.name} is not a readable wheel") from None
    name = version = None
    for line in meta.splitlines():
        if line.startswith("Name:"):
            name = line.split(":", 1)[1].strip()
        elif line.startswith("Version:"):
            version = line.split(":", 1)[1].strip()
    if name != "lore-solo" or not version:
        raise _fail(f"{wheel.name} is not a lore-solo wheel (Name={name!r})")
    return name, version


def _wheel_member(wheel: Path, suffix: str) -> bytes:
    with zipfile.ZipFile(wheel) as zf:
        for name in zf.namelist():
            parts = name.split("/")
            if len(parts) == 2 and parts[0] == "lore" and parts[1] == suffix:
                return zf.read(name)
    raise _fail(f"{wheel.name} does not embed lore/{suffix}")


def _install_wheel(wheel: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--no-deps", "--no-cache-dir", str(wheel)],
        check=False,
    )
    if result.returncode != 0:
        raise _fail(f"pip could not install {wheel.name}")


def run(
    *,
    dist: Path,
    wheels_out: Path,
    site_out: Path,
    platform_key: str = "linux-amd64",
) -> None:
    wheels = sorted(dist.glob("lore_solo-*.whl"))
    if len(wheels) != 1:
        raise _fail(
            f"expected exactly one dist/lore_solo-*.whl, found {len(wheels)}"
        )
    wheel = wheels[0]
    constraints = dist / "release_constraints.txt"
    if not constraints.is_file():
        raise _fail("missing dist/release_constraints.txt")
    embedded = _wheel_member(wheel, "release_constraints.txt")
    if embedded != constraints.read_bytes():
        raise _fail(
            "dist/release_constraints.txt does not match the wheel's "
            "embedded release constraints"
        )
    _, version = _wheel_metadata(wheel)
    manifest = json.loads(_wheel_member(wheel, "site_bundles.json"))

    _install_wheel(wheel)
    from lore.site_bundle import bundle_entry, ensure_site

    entry = bundle_entry(manifest, version, platform_key)
    if entry is None:
        raise _fail(
            f"the wheel's site_bundles.json has no valid pinned entry for "
            f"{platform_key} lore {version}"
        )
    archive = dist / "site" / f"lore-site-{version}-{platform_key}.zip"
    if not archive.is_file():
        raise _fail(f"missing the pinned site archive {archive.name}")

    wheels_out.mkdir(parents=True, exist_ok=True)
    shutil.copy2(wheel, wheels_out / wheel.name)
    shutil.copy2(constraints, wheels_out / "constraints.txt")

    site_out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="lore-release-site-") as tmp:
        resolution = ensure_site(
            version=version,
            platform_key=platform_key,
            site_bundle=archive,
            offline=True,
            cache_root=Path(tmp),
            manifest=manifest,
        )
        generation = resolution.server.parent
        for child in generation.iterdir():
            dest = site_out / child.name
            if child.is_dir() and not child.is_symlink():
                shutil.copytree(child, dest)
            else:
                shutil.copy2(child, dest)
    print(
        f"release artifacts staged: {wheel.name} + "
        f"{archive.name} (sha256={entry['sha256'][:12]}…)"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="release_image_assets.py")
    parser.add_argument("--dist", type=Path, required=True)
    parser.add_argument("--wheels", type=Path, required=True)
    parser.add_argument("--site", type=Path, required=True)
    parser.add_argument("--platform", default="linux-amd64")
    args = parser.parse_args(argv)
    try:
        run(
            dist=args.dist,
            wheels_out=args.wheels,
            site_out=args.site,
            platform_key=args.platform,
        )
    except SystemExit:
        raise
    except Exception as exc:  # fail closed on any staging error
        raise _fail(str(exc)) from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
