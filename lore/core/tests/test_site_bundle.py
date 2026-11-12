"""Prebuilt setup-site bundles: verify, extract, cache, and resolve."""

from __future__ import annotations

import json
import os
import platform as platform_mod
import shutil
import stat
import subprocess
import sys
import textwrap
import zipfile
from pathlib import Path

import pytest
from lore import site_bundle
from lore.site_bundle import (
    SiteError,
    bundle_entry,
    current_platform,
    ensure_site,
    node_major,
    safe_extract,
    sha256_file,
    validate_inner_manifest,
)
from lore.site_bundle_meta import valid_entry

VERSION = "0.1.2"
PLATFORM = "linux-amd64"
BUILD = "b" * 64
OTHER_BUILD = "c" * 64


def _inner(
    version: str = VERSION, platform_key: str = PLATFORM, build_id: str = BUILD
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "lore_version": version,
        "platform": platform_key,
        "build_id": build_id,
        "node_major": 22,
    }


def _write_zip(path: Path, entries: dict[str, str]) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, body in entries.items():
            zf.writestr(name, body)
    return path


def _bundle(
    tmp_path: Path,
    *,
    version: str = VERSION,
    platform_key: str = PLATFORM,
    build_id: str = BUILD,
    extra: dict[str, str] | None = None,
    name: str | None = None,
) -> Path:
    entries = {
        "server.js": "// server",
        "site-manifest.json": json.dumps(_inner(version, platform_key, build_id)),
    }
    if extra:
        entries.update(extra)
    filename = name or f"bundle-{platform_key}-{build_id[:8]}.zip"
    return _write_zip(tmp_path / filename, entries)


def _manifest_for(
    archive: Path,
    version: str = VERSION,
    platform_key: str = PLATFORM,
    build_id: str = BUILD,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "lore_version": version,
        "bundles": {
            platform_key: {
                "platform": platform_key,
                "url": "https://example.test/lore-site.zip",
                "sha256": sha256_file(archive),
                "build_id": build_id,
                "node_major": 22,
                "archive_size": archive.stat().st_size,
                "expanded_size": 1024,
            }
        },
    }


def test_current_platform_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(platform_mod, "machine", lambda: "x86_64")
    monkeypatch.setattr(platform_mod, "libc_ver", lambda: ("glibc", "2.36"))
    assert current_platform() == "linux-amd64"
    monkeypatch.setattr(platform_mod, "libc_ver", lambda: ("musl", "1.2"))
    assert current_platform() is None
    monkeypatch.setattr(platform_mod, "libc_ver", lambda: ("", ""))
    assert current_platform() is None
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(platform_mod, "machine", lambda: "AMD64")
    assert current_platform() == "windows-amd64"
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(platform_mod, "machine", lambda: "arm64")
    assert current_platform() == "macos-arm64"
    monkeypatch.setattr(platform_mod, "machine", lambda: "riscv64")
    assert current_platform() is None


def test_bundle_entry_requires_matching_version() -> None:
    archive_entry = {"bundles": {PLATFORM: {"platform": PLATFORM}}}
    manifest = {"schema_version": 1, "lore_version": "9.9.9", **archive_entry}
    assert bundle_entry(manifest, VERSION, PLATFORM) is None


def test_bundle_entry_rejects_mistyped_fields() -> None:
    entry = {
        "platform": PLATFORM,
        "url": "https://x/y.zip",
        "sha256": "abc",
        "build_id": BUILD,
        "node_major": "22",
        "archive_size": 5,
        "expanded_size": 10,
    }
    manifest = {"schema_version": 1, "lore_version": VERSION, "bundles": {PLATFORM: entry}}
    assert bundle_entry(manifest, VERSION, PLATFORM) is None


def test_valid_entry_nonsense_fixture() -> None:
    base = {
        "platform": PLATFORM,
        "url": "https://x/y.zip",
        "sha256": "a" * 64,
        "build_id": BUILD,
        "node_major": 22,
        "archive_size": 5,
        "expanded_size": 10,
    }
    assert valid_entry(base, PLATFORM)
    for key, bad in (
        ("platform", "x"),
        ("platform", True),
        ("url", "u"),
        ("url", "http://x/y.zip"),
        ("sha256", "s"),
        ("sha256", "A" * 64),
        ("build_id", "../escape"),
        ("build_id", "b1"),
        ("node_major", 18),
        ("node_major", "22"),
        ("archive_size", True),
        ("archive_size", -3),
        ("archive_size", "5"),
        ("expanded_size", 0),
        ("expanded_size", False),
    ):
        wrong = dict(base, **{key: bad})
        assert not valid_entry(wrong, PLATFORM), f"{key}={bad!r} accepted"
    assert not valid_entry(base, "windows-amd64")
    assert not valid_entry("not-a-dict", PLATFORM)


def test_safe_extract_rejects_traversal(tmp_path: Path) -> None:
    archive = _write_zip(tmp_path / "evil.zip", {"../escape.txt": "x"})
    with pytest.raises(SiteError, match="non-canonical"):
        safe_extract(archive, tmp_path / "out")


@pytest.mark.parametrize(
    "name",
    [
        "C:/evil.txt",
        "c:\\evil.txt",
        "/abs/path.txt",
        "//server/share/f.txt",
        "a//b.txt",
        "./a.txt",
        "sub/../up.txt",
        "dir/.",
        "x.txt:stream",
        "x.txt:$DATA",
        "NUL.txt",
        "aux/dir/f.txt",
        "com1",
        "dir/trailingdot./f.txt",
        "dir/trailingspace /f.txt",
        "dir/trailingdot.txt.",
    ],
)
def test_safe_extract_rejects_alias_and_reserved_names(tmp_path: Path, name: str) -> None:
    archive = _write_zip(tmp_path / "evil.zip", {name: "x"})
    with pytest.raises(SiteError):
        safe_extract(archive, tmp_path / "out")


def test_safe_extract_windows_casefold_collision(tmp_path: Path) -> None:
    archive = _write_zip(tmp_path / "case.zip", {"A/B.txt": "1", "a/b.txt": "2"})
    with pytest.raises(SiteError, match="duplicate|collision"):
        safe_extract(archive, tmp_path / "out", platform_key="windows-amd64")
    out = tmp_path / "posix-out"
    safe_extract(archive, out, platform_key="linux-amd64")
    assert (out / "A" / "B.txt").is_file()
    assert (out / "a" / "b.txt").is_file()


def test_safe_extract_rejects_file_dir_collision(tmp_path: Path) -> None:
    archive = _write_zip(tmp_path / "collide.zip", {"a": "x", "a/b.txt": "y"})
    with pytest.raises(SiteError, match="collide"):
        safe_extract(archive, tmp_path / "out")


def test_safe_extract_rejects_duplicates(tmp_path: Path) -> None:
    archive = tmp_path / "dup.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("a.txt", "one")
        zf.writestr("a.txt", "two")
    with pytest.raises(SiteError, match="duplicate"):
        safe_extract(archive, tmp_path / "out")


def test_safe_extract_rejects_symlinks(tmp_path: Path) -> None:
    archive = tmp_path / "link.zip"
    info = zipfile.ZipInfo("linked.txt")
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(info, "target")
    with pytest.raises(SiteError, match="link"):
        safe_extract(archive, tmp_path / "out")


def test_safe_extract_rejects_special_files(tmp_path: Path) -> None:
    archive = tmp_path / "dev.zip"
    info = zipfile.ZipInfo("fifo")
    info.external_attr = (stat.S_IFIFO | 0o644) << 16
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(info, "x")
    with pytest.raises(SiteError, match="special"):
        safe_extract(archive, tmp_path / "out")


def test_safe_extract_enforces_size_limits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(site_bundle, "MAX_EXPANDED_BYTES", 8)
    archive = _write_zip(tmp_path / "big.zip", {"big.txt": "x" * 32})
    with pytest.raises(SiteError, match="size"):
        safe_extract(archive, tmp_path / "out")


def test_safe_extract_enforces_compressed_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(site_bundle, "MAX_ARCHIVE_BYTES", 16)
    archive = _write_zip(tmp_path / "fat.zip", {"big.txt": "x" * 64})
    with pytest.raises(SiteError, match="compressed|size"):
        safe_extract(archive, tmp_path / "out")


def test_safe_extract_bad_zip(tmp_path: Path) -> None:
    archive = tmp_path / "broken.zip"
    archive.write_bytes(b"this is not a zip archive")
    with pytest.raises(SiteError):
        safe_extract(archive, tmp_path / "out")


@pytest.mark.skipif(
    os.name == "nt", reason="POSIX permission bits are not representable on Windows"
)
def test_extracted_modes_are_safe(tmp_path: Path) -> None:
    archive = _write_zip(tmp_path / "ok.zip", {"run.sh": "echo hi", "data.txt": "x"})
    out = tmp_path / "out"
    safe_extract(archive, out)
    mode = stat.S_IMODE((out / "data.txt").stat().st_mode)
    assert mode & 0o022 == 0


def test_validate_inner_manifest_rejects_wrong_platform(tmp_path: Path) -> None:
    root = tmp_path / "site"
    root.mkdir()
    (root / "site-manifest.json").write_text(
        json.dumps(_inner(platform_key="windows-amd64")), encoding="utf-8"
    )
    with pytest.raises(SiteError, match="windows-amd64"):
        validate_inner_manifest(root, VERSION, PLATFORM)


def test_validate_inner_manifest_rejects_wrong_version(tmp_path: Path) -> None:
    root = tmp_path / "site"
    root.mkdir()
    (root / "site-manifest.json").write_text(
        json.dumps(_inner(version="9.9.9")), encoding="utf-8"
    )
    with pytest.raises(SiteError, match="9.9.9"):
        validate_inner_manifest(root, VERSION, PLATFORM)


@pytest.mark.parametrize("bad_id", ["../escape", "/abs", "C:/x", "\\\\unc\\share", "b1"])
def test_inner_manifest_rejects_malicious_build_id(tmp_path: Path, bad_id: str) -> None:
    archive = _bundle(tmp_path, build_id=bad_id, name="evil.zip")
    (tmp_path / "sentinel.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(SiteError, match="build id"):
        ensure_site(
            version=VERSION,
            platform_key=PLATFORM,
            site_bundle=archive,
            cache_root=tmp_path / "cache",
            manifest={},
        )
    assert (tmp_path / "sentinel.txt").is_file()
    assert not (tmp_path / "escape").exists()


def test_local_bundle_without_pinned_entry_is_noted(tmp_path: Path) -> None:
    archive = _bundle(tmp_path)
    resolved = ensure_site(
        version=VERSION,
        platform_key=PLATFORM,
        site_bundle=archive,
        cache_root=tmp_path / "cache",
        manifest={},
    )
    assert "not verified" in resolved.note
    assert resolved.server.is_file()
    assert (resolved.server.parent / "site-manifest.json").is_file()
    assert (resolved.server.parent / site_bundle.MARKER_NAME).is_file()


def test_local_bundle_pinned_mismatch_rejected(tmp_path: Path) -> None:
    archive = _bundle(tmp_path)
    manifest = _manifest_for(_bundle(tmp_path, build_id=OTHER_BUILD, name="o.zip"))
    with pytest.raises(SiteError, match="pinned"):
        ensure_site(
            version=VERSION,
            platform_key=PLATFORM,
            site_bundle=archive,
            cache_root=tmp_path / "cache",
            manifest=manifest,
        )


def test_local_bundle_pinned_match_is_silent(tmp_path: Path) -> None:
    archive = _bundle(tmp_path)
    manifest = _manifest_for(archive)
    resolved = ensure_site(
        version=VERSION,
        platform_key=PLATFORM,
        site_bundle=archive,
        cache_root=tmp_path / "cache",
        manifest=manifest,
    )
    assert resolved.note == ""
    assert resolved.server.is_file()


def test_local_bundle_for_another_platform_rejected(tmp_path: Path) -> None:
    archive = _bundle(tmp_path, platform_key="windows-amd64")
    with pytest.raises(SiteError, match="windows-amd64"):
        ensure_site(
            version=VERSION,
            platform_key=PLATFORM,
            site_bundle=archive,
            cache_root=tmp_path / "cache",
            manifest={},
        )


def test_missing_manifest_entry_is_actionable(tmp_path: Path) -> None:
    with pytest.raises(SiteError, match="--site-bundle"):
        ensure_site(
            version=VERSION,
            platform_key=PLATFORM,
            cache_root=tmp_path / "cache",
            manifest={},
        )


def test_unsupported_platform_is_actionable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(site_bundle, "current_platform", lambda: None)
    with pytest.raises(SiteError, match="platform"):
        ensure_site(version=VERSION, cache_root=tmp_path / "cache", manifest={})


def test_offline_blocks_download(tmp_path: Path) -> None:
    archive = _bundle(tmp_path)
    manifest = _manifest_for(archive)
    with pytest.raises(SiteError, match="offline"):
        ensure_site(
            version=VERSION,
            platform_key=PLATFORM,
            offline=True,
            cache_root=tmp_path / "cache",
            manifest=manifest,
        )


def test_download_verify_and_cache(tmp_path: Path) -> None:
    archive = _bundle(tmp_path)
    manifest = _manifest_for(archive)
    fetched: list[str] = []

    def fake_download(url: str, dest: Path) -> None:
        fetched.append(url)
        dest.write_bytes(archive.read_bytes())

    resolved = ensure_site(
        version=VERSION,
        platform_key=PLATFORM,
        cache_root=tmp_path / "cache",
        manifest=manifest,
        downloader=fake_download,
    )
    assert fetched == ["https://example.test/lore-site.zip"]
    assert resolved.server.is_file()

    resolved_again = ensure_site(
        version=VERSION,
        platform_key=PLATFORM,
        cache_root=tmp_path / "cache",
        manifest=manifest,
        downloader=lambda _u, _d: pytest.fail("cache miss should not refetch"),
    )
    assert resolved_again.server == resolved.server


def test_download_hash_mismatch_rejected(tmp_path: Path) -> None:
    archive = _bundle(tmp_path)
    manifest = _manifest_for(_bundle(tmp_path, build_id=OTHER_BUILD, name="o.zip"))

    def fake_download(url: str, dest: Path) -> None:
        dest.write_bytes(archive.read_bytes())

    with pytest.raises(SiteError, match="checksum"):
        ensure_site(
            version=VERSION,
            platform_key=PLATFORM,
            cache_root=tmp_path / "cache",
            manifest=manifest,
            downloader=fake_download,
        )


def test_download_build_id_mismatch_rejected(tmp_path: Path) -> None:
    archive = _bundle(tmp_path, build_id=BUILD)
    manifest = _manifest_for(archive, build_id=OTHER_BUILD)

    def fake_download(url: str, dest: Path) -> None:
        dest.write_bytes(archive.read_bytes())

    with pytest.raises(SiteError, match="build id"):
        ensure_site(
            version=VERSION,
            platform_key=PLATFORM,
            cache_root=tmp_path / "cache",
            manifest=manifest,
            downloader=fake_download,
        )


def test_incomplete_generation_retries_and_is_preserved(tmp_path: Path) -> None:
    archive = _bundle(tmp_path)
    manifest = _manifest_for(archive)
    cache = tmp_path / "cache"
    stale = cache / VERSION / BUILD / PLATFORM / (sha256_file(archive) + "abc")
    stale.mkdir(parents=True)
    (stale / "server.js").write_text("partial", encoding="utf-8")

    def fake_download(url: str, dest_path: Path) -> None:
        dest_path.write_bytes(archive.read_bytes())

    resolved = ensure_site(
        version=VERSION,
        platform_key=PLATFORM,
        cache_root=cache,
        manifest=manifest,
        downloader=fake_download,
    )
    assert resolved.server.read_text(encoding="utf-8") == "// server"
    assert stale.is_dir()
    assert resolved.server.parent != stale


def test_old_cache_generation_preserved(tmp_path: Path) -> None:
    old_archive = _bundle(tmp_path, build_id=OTHER_BUILD, name="old.zip")
    new_archive = _bundle(tmp_path, name="new.zip")

    def download_to(dest: Path, archive: Path) -> None:
        dest.write_bytes(archive.read_bytes())

    cache = tmp_path / "cache"
    first = ensure_site(
        version=VERSION,
        platform_key=PLATFORM,
        cache_root=cache,
        manifest=_manifest_for(old_archive, build_id=OTHER_BUILD),
        downloader=lambda _u, d: download_to(d, old_archive),
    )
    second = ensure_site(
        version=VERSION,
        platform_key=PLATFORM,
        cache_root=cache,
        manifest=_manifest_for(new_archive),
        downloader=lambda _u, d: download_to(d, new_archive),
    )
    assert first.server.is_file()
    assert second.server.is_file()
    assert first.server.parent != second.server.parent
    assert (cache / VERSION / OTHER_BUILD).is_dir()


def test_publish_failure_preserves_known_good_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = _bundle(tmp_path)
    manifest = _manifest_for(archive)
    cache = tmp_path / "cache"

    def fake_download(url: str, dest: Path) -> None:
        dest.write_bytes(archive.read_bytes())

    good = ensure_site(
        version=VERSION,
        platform_key=PLATFORM,
        cache_root=cache,
        manifest=manifest,
        downloader=fake_download,
    )
    assert (good.server.parent / site_bundle.MARKER_NAME).is_file()

    other = _bundle(tmp_path, build_id="d" * 64, name="other.zip")

    real_replace = os.replace

    def boom(_src: object, _dst: object) -> None:
        raise OSError("publish failed")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError, match="publish failed"):
        ensure_site(
            version=VERSION,
            platform_key=PLATFORM,
            site_bundle=other,
            cache_root=cache,
            manifest={},
        )
    monkeypatch.setattr(os, "replace", real_replace)
    assert (good.server.parent / site_bundle.MARKER_NAME).is_file()
    assert good.server.read_text(encoding="utf-8") == "// server"

    again = ensure_site(
        version=VERSION,
        platform_key=PLATFORM,
        site_bundle=other,
        cache_root=cache,
        manifest={},
    )
    assert again.server.is_file()
    assert again.server != good.server


def test_parallel_ensure_site_real_processes(tmp_path: Path) -> None:
    archive = _bundle(tmp_path)
    manifest = _manifest_for(archive)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    cache = tmp_path / "cache"

    worker = textwrap.dedent(
        f"""
        import json, shutil, sys
        from pathlib import Path
        from lore.site_bundle import ensure_site
        manifest = json.loads(Path({str(manifest_path)!r}).read_text())
        archive = Path({str(archive)!r})

        def dl(url, dest):
            shutil.copyfile(archive, dest)

        r = ensure_site(
            version={VERSION!r},
            platform_key={PLATFORM!r},
            cache_root=Path({str(cache)!r}),
            manifest=manifest,
            downloader=dl,
        )
        print(r.server)
        """
    )
    worker_file = tmp_path / "worker.py"
    worker_file.write_text(worker, encoding="utf-8")
    env = dict(os.environ)
    root = str(Path(site_bundle.__file__).resolve().parents[1])
    env["PYTHONPATH"] = root + os.pathsep + env.get("PYTHONPATH", "")
    procs = [
        subprocess.Popen(
            [sys.executable, str(worker_file)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        for _ in range(2)
    ]
    outputs = [p.communicate(timeout=60) for p in procs]
    for proc, (out, err) in zip(procs, outputs):
        assert proc.returncode == 0, err
        server = Path(out.strip())
        assert server.is_file()
    servers = {Path(out.strip()) for out, _ in outputs}
    assert len(servers) == 1
    for server in servers:
        assert (server.parent / site_bundle.MARKER_NAME).is_file()


def _node_proc(stdout: str) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], 0, stdout=stdout, stderr="")


def test_node_major_parses_versions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **kw: _node_proc("v22.11.0\n")
    )
    assert node_major("/any/node") == 22


def test_node_major_returns_none_on_garbage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **kw: _node_proc("nonsense\n")
    )
    assert node_major("/any/node") is None


def test_node_runtime_requires_22(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _n: "/usr/bin/node")
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **kw: _node_proc("v18.4.0\n")
    )
    assert site_bundle.node_runtime() is None
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **kw: _node_proc("v22.1.0\n")
    )
    assert site_bundle.node_runtime() == "/usr/bin/node"


def test_npm_command_windows_cli_js(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    node = tmp_path / "node.exe"
    node.write_text("", encoding="utf-8")
    cli = tmp_path / "node_modules" / "npm" / "bin" / "npm-cli.js"
    cli.parent.mkdir(parents=True)
    cli.write_text("// npm", encoding="utf-8")
    npm_cmd = tmp_path / "npm.CMD"
    npm_cmd.write_text("", encoding="utf-8")

    def fake_which(name: str) -> str | None:
        return {"node": str(node), "npm": str(npm_cmd)}.get(name)

    monkeypatch.setattr(shutil, "which", fake_which)
    command = site_bundle.npm_command("ci")
    assert command is not None
    assert command[0] == str(node)
    assert command[1].replace("\\", "/").endswith("npm-cli.js")
    assert command[2:] == ["ci"]


def test_npm_command_windows_missing_cli(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    npm_cmd = tmp_path / "npm.CMD"
    npm_cmd.write_text("", encoding="utf-8")
    node = tmp_path / "node.exe"
    node.write_text("", encoding="utf-8")

    def fake_which(name: str) -> str | None:
        return {"node": str(node), "npm": str(npm_cmd)}.get(name)

    monkeypatch.setattr(shutil, "which", fake_which)
    assert site_bundle.npm_command("ci") is None


def test_safe_extract_rejects_duplicate_dirs(tmp_path: Path) -> None:
    archive = tmp_path / "dupdir.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("dir/", "")
        zf.writestr("dir/", "")
    with pytest.raises(SiteError, match="duplicate"):
        safe_extract(archive, tmp_path / "out")


def test_safe_extract_rejects_dir_named_with_file_mode(tmp_path: Path) -> None:
    archive = tmp_path / "mismatch.zip"
    info = zipfile.ZipInfo("dir/")
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(info, "")
    with pytest.raises(SiteError, match="inconsistent"):
        safe_extract(archive, tmp_path / "out")


def test_safe_extract_rejects_file_named_with_dir_mode(tmp_path: Path) -> None:
    archive = tmp_path / "mismatch2.zip"
    info = zipfile.ZipInfo("file.txt")
    info.external_attr = (stat.S_IFDIR | 0o755) << 16
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(info, "x")
    with pytest.raises(SiteError, match="special"):
        safe_extract(archive, tmp_path / "out")


def test_safe_extract_rejects_special_dir_mode(tmp_path: Path) -> None:
    archive = tmp_path / "mismatch3.zip"
    info = zipfile.ZipInfo("dir/")
    info.external_attr = (stat.S_IFIFO | 0o644) << 16
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(info, "")
    with pytest.raises(SiteError, match="inconsistent|special"):
        safe_extract(archive, tmp_path / "out")


def test_bundle_entry_rejects_non_dict_manifest() -> None:
    assert bundle_entry([], VERSION, PLATFORM) is None  # type: ignore[arg-type]
    assert bundle_entry("x", VERSION, PLATFORM) is None  # type: ignore[arg-type]


def test_bundle_entry_rejects_bool_schema_version() -> None:
    manifest = {"schema_version": True, "lore_version": VERSION, "bundles": {}}
    assert bundle_entry(manifest, VERSION, PLATFORM) is None


def test_inner_manifest_rejects_bool_schema_version(tmp_path: Path) -> None:
    root = tmp_path / "site"
    root.mkdir()
    (root / "server.js").write_text("//", encoding="utf-8")
    inner = _inner()
    inner["schema_version"] = True
    (root / "site-manifest.json").write_text(json.dumps(inner), encoding="utf-8")
    with pytest.raises(SiteError, match="schema"):
        validate_inner_manifest(root, VERSION, PLATFORM)


def test_inner_manifest_rejects_non_dict(tmp_path: Path) -> None:
    root = tmp_path / "site"
    root.mkdir()
    (root / "server.js").write_text("//", encoding="utf-8")
    (root / "site-manifest.json").write_text(json.dumps([1, 2]), encoding="utf-8")
    with pytest.raises(SiteError, match="schema"):
        validate_inner_manifest(root, VERSION, PLATFORM)


def test_local_pinned_bundle_build_id_drift_rejected(tmp_path: Path) -> None:
    archive = _bundle(tmp_path, build_id=BUILD)
    manifest = _manifest_for(archive, build_id=OTHER_BUILD)
    with pytest.raises(SiteError, match="build id"):
        ensure_site(
            version=VERSION,
            platform_key=PLATFORM,
            site_bundle=archive,
            cache_root=tmp_path / "cache",
            manifest=manifest,
        )
