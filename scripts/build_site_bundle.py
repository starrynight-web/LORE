#!/usr/bin/env python3
"""Build the prebuilt setup-site archive for one platform.

Developer/release tooling: runs `npm ci` and `npm run build` in web/, assembles
the Next.js standalone output plus static/public assets into a relocatable
zip, and writes a JSON metadata fragment next to it for
`assemble_site_manifest.py` to merge into lore/site_bundles.json.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lore.release import bundle_url, release_version
from lore.site_bundle import (
    SiteError,
    current_platform,
    node_runtime,
    npm_command,
)
from lore.site_bundle_meta import NODE_MAJOR, PLATFORMS

WEB_DIR = Path(__file__).resolve().parents[1] / "web"
_SKIP_PARTS = {"node_modules", ".next", ".turbo", "out", "__pycache__"}
_SKIP_NAMES = {"tsconfig.tsbuildinfo", "next-env.d.ts"}
_SKIP_SUFFIXES = (".tsbuildinfo", ".log")
_STAMP_NAME = ".lore-source-stamp"


def _file_digest(path: Path) -> bytes:
    """Content digest with text line endings normalized to LF."""
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return hashlib.sha256(raw).digest()
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).digest()


def source_tree_hash(web_dir: Path, version: str, recipe: Path) -> str:
    """SHA-256 over the frontend source inputs plus recipe and version."""
    root = web_dir.resolve()
    digest = hashlib.sha256()
    digest.update(b"version\0" + version.encode("utf-8") + b"\0")
    digest.update(b"recipe\0" + _file_digest(recipe) + b"\0")
    for path in _source_files(root):
        rel = path.relative_to(root).as_posix()
        digest.update(rel.encode("utf-8") + b"\0")
        digest.update(_file_digest(path))
        digest.update(b"\0")
    return digest.hexdigest()


def _inside(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except (OSError, ValueError, RuntimeError):
        return False
    return True


def _is_link(path: Path) -> bool:
    isjunction = getattr(os.path, "isjunction", None)
    return path.is_symlink() or bool(isjunction and isjunction(path))


def _inode(path: Path) -> tuple[int, int]:
    info = path.stat()
    return (info.st_dev, info.st_ino)


def _source_files(root: Path) -> list[Path]:
    """Every hashable file under `root`, following in-tree links safely."""
    files: list[Path] = []
    seen_dirs: set[tuple[int, int]] = set()
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = sorted(current.iterdir())
        except OSError as exc:
            raise SystemExit(f"Could not scan {current}: {exc}") from exc
        for entry in entries:
            rel_parts = entry.relative_to(root).parts
            if any(part in _SKIP_PARTS for part in rel_parts):
                continue
            if entry.name in _SKIP_NAMES or entry.name.startswith(".env"):
                continue
            if entry.name.endswith(_SKIP_SUFFIXES):
                continue
            try:
                if _is_link(entry):
                    target = entry.resolve(strict=True)
                    if not _inside(root, target):
                        raise SystemExit(
                            f"{entry} links outside the web root"
                        )
                    if target.is_dir():
                        marker = _inode(target)
                        if marker in seen_dirs:
                            continue
                        seen_dirs.add(marker)
                        stack.append(target)
                    elif target.is_file():
                        files.append(entry)
                    else:
                        raise SystemExit(f"{entry} links to a special file")
                elif entry.is_dir():
                    stack.append(entry)
                elif entry.is_file():
                    files.append(entry)
                else:
                    raise SystemExit(f"{entry} is a special file")
            except (OSError, RuntimeError) as exc:
                raise SystemExit(f"Could not read {entry}: {exc}") from exc
    return sorted(set(files))


def _remove_link(path: Path) -> None:
    if path.is_symlink():
        path.unlink()
    else:
        os.rmdir(path)


def _flatten_links(root: Path, web_root: Path) -> None:
    """Materialize links that stay inside staging or the web root."""
    allowed = (root.resolve(), web_root.resolve())
    for _round in range(8):
        links = [path for path in root.rglob("*") if _is_link(path)]
        if not links:
            return
        for path in links:
            try:
                target = path.resolve(strict=True)
            except (OSError, RuntimeError) as exc:
                raise SiteError(f"unresolvable link in the site bundle: {path}") from exc
            if not any(_inside(base, target) for base in allowed):
                raise SiteError(
                    f"refusing to package a link outside the web root: {path}"
                )
            _remove_link(path)
            if target.is_dir():
                shutil.copytree(target, path, symlinks=True)
            else:
                shutil.copy2(target, path)
    raise SiteError(f"link flattening did not converge under {root}")


def _copy_tree(source: Path, dest: Path) -> None:
    if not source.is_dir():
        return
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(source, dest, symlinks=True)


def _expanded_size(root: Path) -> int:
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def _forbidden_files(root: Path) -> list[str]:
    """Secrets or provider files that must never ship inside the archive."""
    bad: list[str] = []
    for path in sorted(root.rglob("*")):
        name = path.name
        if name == ".env" or name.startswith(".env.") or name == "provider.json":
            bad.append(path.relative_to(root).as_posix())
    return bad


def _stamp_path(web_dir: Path) -> Path:
    return web_dir / ".next" / "standalone" / _STAMP_NAME


def build(
    web_dir: Path,
    out_dir: Path,
    platform_key: str,
    version: str,
    *,
    runner: Any = subprocess.run,
    recipe: Path | None = None,
) -> dict[str, object]:
    if platform_key not in PLATFORMS:
        raise SystemExit(f"unknown platform key: {platform_key} (expected one of {PLATFORMS})")
    recipe = recipe or Path(__file__)
    build_id = source_tree_hash(web_dir, version, recipe)
    standalone = web_dir / ".next" / "standalone"
    server = standalone / "server.js"
    stamp = _stamp_path(web_dir)
    try:
        stamped = stamp.read_text(encoding="utf-8").strip() if stamp.is_file() else ""
    except OSError:
        stamped = ""
    repackage_only = server.is_file() and stamped == build_id
    if not repackage_only:
        npm_ci = npm_command("ci")
        npm_build = npm_command("run", "build")
        if npm_ci is None or npm_build is None:
            raise SystemExit(
                "npm is required to build the setup site bundle "
                "(an npm CLI JS next to node/npm on Windows)."
            )
        for command in (npm_ci, npm_build):
            result = runner(command, cwd=web_dir, check=False)
            if result.returncode != 0:
                raise SystemExit(f"{' '.join(command)} failed in {web_dir}")
        after = source_tree_hash(web_dir, version, recipe)
        if after != build_id:
            raise SystemExit("the frontend source changed during the build")
        if not server.is_file():
            raise SystemExit("next build did not produce .next/standalone/server.js")
        stamp.write_text(build_id, encoding="utf-8")

    out_dir.mkdir(parents=True, exist_ok=True)
    staging_root = Path(tempfile.mkdtemp(prefix=".bundle-", dir=out_dir))
    staging = staging_root / "site"
    try:
        _copy_tree(standalone, staging)
        stamp_copy = staging / _STAMP_NAME
        if stamp_copy.exists():
            stamp_copy.unlink()
        static = web_dir / ".next" / "static"
        if static.is_dir():
            _copy_tree(static, staging / ".next" / "static")
        _copy_tree(web_dir / "public", staging / "public")
        _flatten_links(staging, web_dir)
        forbidden = _forbidden_files(staging)
        if forbidden:
            raise SiteError(
                "refusing to package secrets in the site bundle: "
                + ", ".join(forbidden)
            )
        manifest = {
            "schema_version": 1,
            "lore_version": version,
            "platform": platform_key,
            "build_id": build_id,
            "node_major": NODE_MAJOR,
        }
        (staging / "site-manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        expanded = _expanded_size(staging)
        archive = out_dir / f"lore-site-{version}-{platform_key}.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(staging.rglob("*")):
                if path.is_dir() and not any(path.iterdir()):
                    continue
                rel = path.relative_to(staging).as_posix()
                zf.write(path, rel)
        sha = hashlib.sha256(archive.read_bytes()).hexdigest()
        entry = {
            "platform": platform_key,
            "url": bundle_url(platform_key, version),
            "sha256": sha,
            "build_id": build_id,
            "node_major": NODE_MAJOR,
            "archive_size": archive.stat().st_size,
            "expanded_size": expanded,
        }
        meta_path = out_dir / f"lore-site-{version}-{platform_key}.json"
        meta_path.write_text(json.dumps(entry, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return {"archive": archive, "meta": meta_path, "entry": entry}
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="build_site_bundle.py")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--platform", default=None)
    parser.add_argument("--version", default=release_version())
    parser.add_argument("--web-dir", default=WEB_DIR, type=Path)
    args = parser.parse_args(argv)
    platform_key = args.platform or current_platform()
    if platform_key is None:
        raise SystemExit("no bundle platform matches this machine; pass --platform")
    if platform_key != current_platform():
        raise SystemExit(
            f"cross-platform bundles are not supported locally: this machine is "
            f"{current_platform()}, not {platform_key}"
        )
    if node_runtime() is None:
        raise SystemExit(f"building the setup site needs Node {NODE_MAJOR} or newer")
    result = build(args.web_dir, args.output_dir, platform_key, args.version)
    print(f"wrote {result['archive']}")
    print(f"wrote {result['meta']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
