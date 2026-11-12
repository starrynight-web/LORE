"""Prebuilt setup-site bundles: manifest lookup, download, verify, extract, cache.

A published wheel ships no web source. `lore-solo setup` resolves a platform
archive from `lore/site_bundles.json` (or an explicit local file), verifies
its SHA-256 against the pinned manifest entry, extracts it safely, and runs
the bundled Next.js standalone server with Node 22+.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform as platform_mod
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from lore import __version__
from lore.site_bundle_meta import (
    INNER_MANIFEST,
    MAX_ARCHIVE_BYTES,
    MAX_EXPANDED_BYTES,
    NODE_MAJOR,
    is_hex64,
    valid_entry,
)

DOWNLOAD_TIMEOUT = 30.0
MARKER_NAME = ".lore-site-ok"
POINTER_NAME = ".current"
LOCK_NAME = ".publish.lock"

_GEN_NAME_RE = re.compile(r"[0-9a-f]{64}(?:-[0-9a-f]{32})?")
_COMPONENT_RE = re.compile(r"[0-9A-Za-z][0-9A-Za-z._+~-]*")
_RESERVED_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


class SiteError(Exception):
    """An actionable setup-site resolution failure."""


@dataclass(frozen=True)
class SiteResolution:
    """Where the ready standalone server lives, plus an optional warning."""

    server: Path
    note: str = ""


def _strict_int(value: Any) -> bool:
    return type(value) is int


def _component(value: Any, what: str) -> str:
    if (
        not isinstance(value, str)
        or _COMPONENT_RE.fullmatch(value) is None
        or ".." in value
        or "/" in value
        or "\\" in value
    ):
        raise SiteError(f"Invalid {what} in the site bundle metadata: {value!r}")
    return value


def current_platform() -> str | None:
    """This machine's bundle key, or None when no published bundle exists."""
    system = sys.platform.lower()
    machine = platform_mod.machine().lower()
    if system.startswith("linux") and machine in {"x86_64", "amd64"}:
        libc, _ver = platform_mod.libc_ver()
        return "linux-amd64" if libc == "glibc" else None
    if system.startswith("win") and machine in {"amd64", "x86_64"}:
        return "windows-amd64"
    if system == "darwin" and machine in {"arm64", "aarch64"}:
        return "macos-arm64"
    return None


def load_manifest() -> dict[str, Any]:
    try:
        resource = files("lore").joinpath("site_bundles.json")
        data = json.loads(Path(str(resource)).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def bundle_entry(
    manifest: dict[str, Any], version: str, platform_key: str
) -> dict[str, Any] | None:
    """The validated pinned entry for this platform/version, or None."""
    if (
        not isinstance(manifest, dict)
        or type(manifest.get("schema_version")) is not int
        or manifest["schema_version"] != 1
        or manifest.get("lore_version") != version
    ):
        return None
    bundles = manifest.get("bundles")
    if not isinstance(bundles, dict):
        return None
    entry = bundles.get(platform_key)
    if not valid_entry(entry, platform_key):
        return None
    return dict(entry)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def site_cache_root() -> Path:
    return Path.home() / ".lore" / "site"


class _HttpsOnlyRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Any,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> Any:
        if urllib.parse.urlsplit(newurl).scheme != "https":
            raise SiteError("The setup site download redirected away from HTTPS.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(url: str, dest: Path) -> None:
    """Fetch an archive over HTTPS only, bounded in size and time."""
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https":
        raise SiteError(f"The setup site must download over HTTPS, not {parsed.scheme}:")
    request = urllib.request.Request(
        url, headers={"User-Agent": f"lore-solo/{__version__}"}
    )
    try:
        opener = urllib.request.build_opener(_HttpsOnlyRedirect())
        with opener.open(request, timeout=DOWNLOAD_TIMEOUT) as response:
            declared = response.headers.get("Content-Length")
            try:
                declared_size = int(declared) if declared is not None else 0
            except ValueError:
                declared_size = 0
            if declared_size > MAX_ARCHIVE_BYTES:
                raise SiteError("The setup site bundle is too large to download.")
            written = 0
            with dest.open("wb") as out:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > MAX_ARCHIVE_BYTES:
                        raise SiteError("The setup site bundle exceeded the size limit.")
                    out.write(chunk)
    except urllib.error.URLError as exc:
        raise SiteError(f"The setup site download failed: {exc.reason}") from exc


def _canonical_member(name: str) -> tuple[str, bool]:
    """A normalized member path and whether it names a directory."""
    raw = name.replace("\\", "/")
    is_dir = raw.endswith("/")
    body = raw[:-1] if is_dir else raw
    segments = body.split("/")
    if not segments or any(seg in ("", ".", "..") for seg in segments):
        raise SiteError(f"The bundle has a non-canonical member: {name}")
    for segment in segments:
        if segment.endswith((" ", ".")):
            raise SiteError(f"The bundle has an unsafe member name: {name}")
        if ":" in segment:
            raise SiteError(f"The bundle has an alternate stream or drive: {name}")
        if segment.split(".", 1)[0].lower() in _RESERVED_NAMES:
            raise SiteError(f"The bundle uses a reserved device name: {name}")
    normalized = "/".join(segments)
    if raw.startswith(("/", "//")) or PureWindowsPath(normalized).drive:
        raise SiteError(f"The bundle contains an absolute path: {name}")
    if PurePosixPath(normalized).parts != tuple(segments):
        raise SiteError(f"The bundle escapes its root: {name}")
    return normalized, is_dir


def _member_mode(info: zipfile.ZipInfo) -> int:
    return (info.external_attr >> 16) & 0xFFFF


def _check_members(
    infos: list[zipfile.ZipInfo], *, windows_names: bool
) -> list[tuple[zipfile.ZipInfo, str, bool]]:
    """Validate all members first; return (info, canonical_rel, is_dir) rows."""
    rows: list[tuple[zipfile.ZipInfo, str, bool]] = []
    file_keys: set[str] = set()
    dir_keys: set[str] = set()
    for info in infos:
        rel, is_dir = _canonical_member(info.filename)
        key = rel.casefold() if windows_names else rel
        if key in file_keys or (is_dir and key in dir_keys):
            raise SiteError(f"The bundle contains a duplicate path: {rel}")
        if is_dir:
            dir_keys.add(key)
        else:
            file_keys.add(key)
        mode = _member_mode(info)
        kind = stat.S_IFMT(mode)
        if stat.S_ISLNK(mode):
            raise SiteError(f"The bundle contains a link: {rel}")
        if is_dir and kind not in (0, stat.S_IFDIR):
            raise SiteError(f"The bundle has an inconsistent or special directory: {rel}")
        if not is_dir and kind not in (0, stat.S_IFREG):
            raise SiteError(f"The bundle contains a special file: {rel}")
        rows.append((info, rel, is_dir))
    for _info, rel, _is_dir in rows:
        parts = PurePosixPath(rel).parts
        for index in range(1, len(parts)):
            ancestor = "/".join(parts[:index])
            dir_keys.add(ancestor.casefold() if windows_names else ancestor)
    collisions = file_keys & dir_keys
    if collisions:
        raise SiteError(
            f"The bundle collides a file and a directory: {min(collisions)}"
        )
    return rows


def _extract_members(
    zf: zipfile.ZipFile,
    rows: list[tuple[zipfile.ZipInfo, str, bool]],
    dest: Path,
) -> None:
    remaining = MAX_EXPANDED_BYTES
    for info, rel, is_dir in rows:
        target = dest / rel
        mode = _member_mode(info)
        if is_dir or stat.S_ISDIR(mode):
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        copied = 0
        with zf.open(info) as source, target.open("wb") as out:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                copied += len(chunk)
                remaining -= len(chunk)
                if copied > MAX_EXPANDED_BYTES or remaining < 0:
                    raise SiteError("The bundle expands beyond the size limit.")
                out.write(chunk)
        target.chmod(0o755 if mode & 0o111 else 0o644)


def safe_extract(archive: Path, dest: Path, *, platform_key: str | None = None) -> None:
    """Extract a bundle after rejecting traversal, links, specials, and size."""
    try:
        if archive.stat().st_size > MAX_ARCHIVE_BYTES:
            raise SiteError("The bundle exceeds the compressed size limit.")
        with zipfile.ZipFile(archive) as zf:
            rows = _check_members(
                zf.infolist(), windows_names=platform_key == "windows-amd64"
            )
            _extract_members(zf, rows, dest)
    except SiteError:
        raise
    except (zipfile.BadZipFile, OSError) as exc:
        raise SiteError(f"The bundle could not be read: {exc}") from exc


def _require_server_file(root: Path) -> None:
    server = root / "server.js"
    if not server.is_file() or server.is_symlink():
        raise SiteError("The site bundle has no standalone server.js.")


def validate_inner_manifest(root: Path, version: str, platform_key: str) -> dict[str, Any]:
    path = root / INNER_MANIFEST
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SiteError("The site bundle is missing a readable site-manifest.json.") from exc
    if (
        not isinstance(data, dict)
        or type(data.get("schema_version")) is not int
        or data["schema_version"] != 1
    ):
        raise SiteError("The site bundle has an unknown manifest schema.")
    if data.get("lore_version") != version:
        raise SiteError(
            f"The site bundle targets lore {data.get('lore_version')}, not {version}."
        )
    if data.get("platform") != platform_key:
        raise SiteError(
            f"The site bundle targets {data.get('platform')}, not {platform_key}."
        )
    if data.get("node_major") != NODE_MAJOR or not _strict_int(data.get("node_major")):
        raise SiteError(
            f"The site bundle needs Node {data.get('node_major')}, not Node {NODE_MAJOR}."
        )
    if not is_hex64(data.get("build_id")):
        raise SiteError("The site bundle has an invalid build id.")
    _require_server_file(root)
    return data


def _marker_ok(dest: Path, *, sha256: str, build_id: str) -> bool:
    marker = dest / MARKER_NAME
    server = dest / "server.js"
    if not marker.is_file() or not server.is_file() or server.is_symlink():
        return False
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(data, dict):
        return False
    return bool(data.get("sha256") == sha256 and data.get("build_id") == build_id)


def _platform_dir(root: Path, version: str, build_id: str, platform_key: str) -> Path:
    _component(version, "version")
    _component(platform_key, "platform")
    if not is_hex64(build_id):
        raise SiteError("The site bundle has an invalid build id.")
    base = root.resolve()
    target = base / version / build_id / platform_key
    try:
        target.resolve().relative_to(base)
    except (OSError, ValueError) as exc:
        raise SiteError("The site bundle cache path escapes its root.") from exc
    return target


def _pointer_name(platform_dir: Path) -> str | None:
    try:
        name = (platform_dir / POINTER_NAME).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if _GEN_NAME_RE.fullmatch(name):
        return name
    return None


def _write_pointer(platform_dir: Path, name: str) -> None:
    handle, tmp = tempfile.mkstemp(prefix=".pointer-", dir=platform_dir)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            out.write(name + "\n")
        os.replace(tmp, platform_dir / POINTER_NAME)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _cached_generation(
    platform_dir: Path, sha256: str, build_id: str
) -> Path | None:
    for name in (sha256, _pointer_name(platform_dir)):
        if not name:
            continue
        gen = platform_dir / name
        if _marker_ok(gen, sha256=sha256, build_id=build_id):
            return gen
    return None


@contextmanager
def _site_lock(platform_dir: Path) -> Iterator[None]:
    platform_dir.mkdir(parents=True, exist_ok=True)
    handle = (platform_dir / LOCK_NAME).open("a+b")
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)  # type: ignore[attr-defined]
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)  # type: ignore[attr-defined]
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def _publish_locked(
    staging: Path,
    platform_dir: Path,
    *,
    sha256: str,
    build_id: str,
    version: str,
    platform_key: str,
) -> Path:
    """Publish `staging` as an immutable generation; caller holds the lock."""
    cached = _cached_generation(platform_dir, sha256, build_id)
    if cached is not None:
        shutil.rmtree(staging, ignore_errors=True)
        return cached
    gen_name = sha256
    if (platform_dir / gen_name).exists():
        gen_name = f"{sha256}-{uuid.uuid4().hex}"
    marker = {
        "sha256": sha256,
        "build_id": build_id,
        "version": version,
        "platform": platform_key,
    }
    (staging / MARKER_NAME).write_text(json.dumps(marker) + "\n", encoding="utf-8")
    os.replace(staging, platform_dir / gen_name)
    _write_pointer(platform_dir, gen_name)
    return platform_dir / gen_name


def _stage_checked(
    archive: Path,
    root: Path,
    version: str,
    platform_key: str,
) -> tuple[Path, dict[str, Any]]:
    root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=root))
    try:
        safe_extract(archive, staging, platform_key=platform_key)
        inner = validate_inner_manifest(staging, version, platform_key)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return staging, inner


def _resolve_archive(
    archive: Path,
    root: Path,
    version: str,
    platform_key: str,
    sha256: str,
    *,
    expected_build_id: str | None = None,
) -> Path:
    staging, inner = _stage_checked(archive, root, version, platform_key)
    build_id = str(inner["build_id"])
    if expected_build_id is not None and build_id != expected_build_id:
        shutil.rmtree(staging, ignore_errors=True)
        raise SiteError(
            "The downloaded bundle build id does not match the release entry."
        )
    platform_dir = _platform_dir(root, version, build_id, platform_key)
    with _site_lock(platform_dir):
        try:
            return _publish_locked(
                staging,
                platform_dir,
                sha256=sha256,
                build_id=build_id,
                version=version,
                platform_key=platform_key,
            )
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise


def ensure_site(
    *,
    version: str | None = None,
    platform_key: str | None = None,
    site_bundle: Path | None = None,
    offline: bool = False,
    cache_root: Path | None = None,
    manifest: dict[str, Any] | None = None,
    downloader: Any = None,
) -> SiteResolution:
    """Resolve a ready standalone site directory, or raise SiteError."""
    version = version or __version__
    _component(version, "version")
    platform_key = platform_key or current_platform()
    if platform_key is None:
        raise SiteError(
            "No published setup site exists for this platform "
            f"({sys.platform}/{platform_mod.machine()}). "
            "Run `lore-solo setup --site-bundle PATH` or build the site from source."
        )
    _component(platform_key, "platform")
    manifest = manifest if manifest is not None else load_manifest()
    entry = bundle_entry(manifest, version, platform_key)
    root = cache_root or site_cache_root()

    if site_bundle is not None:
        archive = Path(site_bundle)
        if not archive.is_file():
            raise SiteError(f"The site bundle does not exist: {archive}")
        sha = sha256_file(archive)
        if entry is not None:
            if sha != entry["sha256"]:
                raise SiteError(
                    "The local site bundle does not match the pinned release entry "
                    f"for {platform_key}."
                )
            note = ""
        else:
            note = (
                "Using a local site bundle; it was not verified against the "
                "release registry."
            )
        gen = _resolve_archive(
            archive,
            root,
            version,
            platform_key,
            sha,
            expected_build_id=entry["build_id"] if entry is not None else None,
        )
        return SiteResolution(server=gen / "server.js", note=note)

    if entry is None:
        raise SiteError(
            f"This install has no published setup site for {platform_key} "
            f"(lore {version}). Run `lore-solo setup --site-bundle PATH` or "
            "build the site from source."
        )
    platform_dir = _platform_dir(root, version, entry["build_id"], platform_key)
    with _site_lock(platform_dir):
        cached = _cached_generation(platform_dir, entry["sha256"], entry["build_id"])
    if cached is not None:
        return SiteResolution(server=cached / "server.js")
    if offline:
        raise SiteError(
            "The setup site bundle is not cached and --offline forbids downloads."
        )
    fetch = downloader or download
    root.mkdir(parents=True, exist_ok=True)
    handle, tmp_name = tempfile.mkstemp(prefix=".site-", suffix=".zip", dir=root)
    os.close(handle)
    tmp = Path(tmp_name)
    try:
        fetch(entry["url"], tmp)
        if tmp.stat().st_size > MAX_ARCHIVE_BYTES:
            raise SiteError("The downloaded bundle exceeds the size limit.")
        sha = sha256_file(tmp)
        if sha != entry["sha256"]:
            raise SiteError("The downloaded site bundle failed its checksum.")
        gen = _resolve_archive(
            tmp,
            root,
            version,
            platform_key,
            sha,
            expected_build_id=entry["build_id"],
        )
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass
    return SiteResolution(server=gen / "server.js")


def node_major(executable: str) -> int | None:
    try:
        result = subprocess.run(
            [executable, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    raw = (result.stdout or result.stderr or "").strip().lstrip("vV")
    head = raw.split(".", 1)[0]
    try:
        return int(head)
    except ValueError:
        return None


def node_runtime(minimum: int = NODE_MAJOR) -> str | None:
    """A node binary at `minimum` or newer, or None."""
    node = shutil.which("node")
    if node is None:
        return None
    major = node_major(node)
    if major is None or major < minimum:
        return None
    return node


def npm_command(*args: str) -> list[str] | None:
    """An executable npm invocation, never through a shell.

    On Windows `npm` resolves to npm.cmd, which CreateProcess cannot run
    directly; the real CLI lives in node_modules/npm/bin/npm-cli.js beside
    npm or node, so the command becomes [node, npm-cli.js, *args].
    """
    npm = shutil.which("npm")
    if npm is None:
        return None
    if not sys.platform.startswith("win"):
        return [npm, *args]
    node = shutil.which("node")
    if node is None:
        return None
    cli_candidates = (
        Path(npm).parent / "node_modules" / "npm" / "bin" / "npm-cli.js",
        Path(node).parent / "node_modules" / "npm" / "bin" / "npm-cli.js",
    )
    for cli in cli_candidates:
        if cli.is_file():
            return [node, str(cli), *args]
    return None
