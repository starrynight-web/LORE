"""Site-bundle build helpers and the release manifest gate."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
BUILD_ID = "b" * 64
OTHER_ID = "c" * 64


def _load(name: str) -> Any:
    existing = sys.modules.get(name)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _fake_web(tmp_path: Path, *, source_body: str = "export {}") -> Path:
    web = tmp_path / "web"
    (web / ".next" / "standalone" / ".next").mkdir(parents=True)
    (web / ".next" / "static").mkdir(parents=True)
    (web / "public").mkdir(parents=True)
    (web / "app").mkdir(parents=True)
    (web / "node_modules" / "dep").mkdir(parents=True)
    (web / "package.json").write_text('{"name":"lore-web"}', encoding="utf-8")
    (web / "package-lock.json").write_text("{}", encoding="utf-8")
    (web / "app" / "page.tsx").write_text(source_body, encoding="utf-8")
    (web / ".next" / "standalone" / "server.js").write_text("// server", encoding="utf-8")
    (web / ".next" / "standalone" / "lib.js").write_text("// lib", encoding="utf-8")
    (web / ".next" / "static" / "chunk.js").write_text("// chunk", encoding="utf-8")
    (web / "public" / "logo.txt").write_text("logo", encoding="utf-8")
    (web / "node_modules" / "dep" / "index.js").write_text("// dep", encoding="utf-8")
    return web


def _ok_runner(command: list[str], **kwargs: object) -> SimpleNamespace:
    return SimpleNamespace(returncode=0)


@pytest.fixture(autouse=True)
def _fake_npm(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _load("build_site_bundle")
    monkeypatch.setattr(mod, "npm_command", lambda *args: ["npm", *args])


def _recipe(tmp_path: Path, body: str = "# recipe") -> Path:
    recipe = tmp_path / "recipe.py"
    recipe.write_text(body, encoding="utf-8")
    return recipe


def test_build_site_bundle_packages_standalone(tmp_path: Path) -> None:
    mod = _load("build_site_bundle")
    web = _fake_web(tmp_path)
    out = tmp_path / "out"
    result = mod.build(web, out, "linux-amd64", "9.9.9", runner=_ok_runner)
    archive = result["archive"]
    assert archive.name == "lore-site-9.9.9-linux-amd64.zip"
    with zipfile.ZipFile(archive) as zf:
        names = set(zf.namelist())
        inner = json.loads(zf.read("site-manifest.json"))
    assert "server.js" in names
    assert "lib.js" in names
    assert ".next/static/chunk.js" in names
    assert "public/logo.txt" in names
    assert inner["lore_version"] == "9.9.9"
    assert inner["platform"] == "linux-amd64"
    assert inner["node_major"] == 22
    entry = result["entry"]
    assert entry["sha256"] == hashlib.sha256(archive.read_bytes()).hexdigest()
    assert entry["archive_size"] == archive.stat().st_size
    assert "node_modules" not in {n.split("/")[0] for n in names}


def test_source_hash_normalizes_crlf(tmp_path: Path) -> None:
    mod = _load("build_site_bundle")
    web_lf = _fake_web(tmp_path / "lf")
    web_crlf = _fake_web(tmp_path / "crlf")
    (web_lf / "app" / "page.tsx").write_bytes(b"export {}\n")
    (web_crlf / "app" / "page.tsx").write_bytes(b"export {}\r\n")
    recipe = _recipe(tmp_path)
    assert mod.source_tree_hash(web_lf, "9.9.9", recipe) == mod.source_tree_hash(
        web_crlf, "9.9.9", recipe
    )


def test_build_id_tracks_source_not_build_output(tmp_path: Path) -> None:
    mod = _load("build_site_bundle")
    recipe = _recipe(tmp_path)
    web_a = _fake_web(tmp_path / "a")
    web_b = _fake_web(tmp_path / "b", source_body="export const x = 1")
    assert mod.source_tree_hash(web_a, "9.9.9", recipe) != mod.source_tree_hash(
        web_b, "9.9.9", recipe
    )
    (web_a / ".next" / "static" / "chunk.js").write_text("// changed", encoding="utf-8")
    (web_a / "node_modules" / "dep" / "index.js").write_text("// changed", encoding="utf-8")
    assert mod.source_tree_hash(web_a, "9.9.9", recipe) == mod.source_tree_hash(
        _fake_web(tmp_path / "c"), "9.9.9", recipe
    )


def test_recipe_and_version_change_the_hash(tmp_path: Path) -> None:
    mod = _load("build_site_bundle")
    web = _fake_web(tmp_path)
    base = mod.source_tree_hash(web, "9.9.9", _recipe(tmp_path))
    assert base != mod.source_tree_hash(web, "9.9.9", _recipe(tmp_path, "# changed"))
    assert base != mod.source_tree_hash(web, "9.9.10", _recipe(tmp_path))


def test_build_id_ignores_env_and_buildinfo(tmp_path: Path) -> None:
    mod = _load("build_site_bundle")
    web = _fake_web(tmp_path)
    recipe = _recipe(tmp_path)
    before = mod.source_tree_hash(web, "9.9.9", recipe)
    (web / ".env.local").write_text("SECRET=1", encoding="utf-8")
    (web / ".env.production").write_text("KEY=2", encoding="utf-8")
    (web / "tsconfig.tsbuildinfo").write_text("{}", encoding="utf-8")
    (web / ".next" / "standalone" / "next-env.d.ts").write_text("", encoding="utf-8")
    assert mod.source_tree_hash(web, "9.9.9", recipe) == before


def test_repackage_reuses_unchanged_standalone(tmp_path: Path) -> None:
    mod = _load("build_site_bundle")
    web = _fake_web(tmp_path)
    out = tmp_path / "out"
    calls: list[list[str]] = []

    def counting(command: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append(command)
        return SimpleNamespace(returncode=0)

    mod.build(web, out, "linux-amd64", "9.9.9", runner=counting)
    assert len(calls) == 2
    mod.build(web, out, "linux-amd64", "9.9.9", runner=counting)
    assert len(calls) == 2


def test_source_change_during_build_fails(tmp_path: Path) -> None:
    mod = _load("build_site_bundle")
    web = _fake_web(tmp_path)

    def mutating(command: list[str], **kwargs: object) -> SimpleNamespace:
        if "build" in command:
            (web / "app" / "late.tsx").write_text("export {}", encoding="utf-8")
        return SimpleNamespace(returncode=0)

    with pytest.raises(SystemExit, match="changed during"):
        mod.build(web, tmp_path / "out", "linux-amd64", "9.9.9", runner=mutating)


@pytest.mark.skipif(
    os.name == "nt", reason="creating symlinks needs privileges on Windows"
)
def test_source_link_inside_web_root_is_hashed(tmp_path: Path) -> None:
    mod = _load("build_site_bundle")
    web = _fake_web(tmp_path)
    recipe = _recipe(tmp_path)
    before = mod.source_tree_hash(web, "9.9.9", recipe)
    (web / "app" / "linked.tsx").symlink_to("page.tsx")
    after = mod.source_tree_hash(web, "9.9.9", recipe)
    assert before != after


@pytest.mark.skipif(
    os.name == "nt", reason="creating symlinks needs privileges on Windows"
)
def test_source_link_outside_web_root_rejected(tmp_path: Path) -> None:
    mod = _load("build_site_bundle")
    web = _fake_web(tmp_path)
    outside = tmp_path / "secret.txt"
    outside.write_text("nope", encoding="utf-8")
    (web / "app" / "escape.tsx").symlink_to(outside)
    with pytest.raises(SystemExit, match="outside"):
        mod.source_tree_hash(web, "9.9.9", _recipe(tmp_path))


@pytest.mark.skipif(
    os.name == "nt", reason="creating symlinks needs privileges on Windows"
)
def test_source_link_cycle_rejected(tmp_path: Path) -> None:
    mod = _load("build_site_bundle")
    web = _fake_web(tmp_path)
    (web / "x").symlink_to("x")
    with pytest.raises(SystemExit):
        mod.source_tree_hash(web, "9.9.9", _recipe(tmp_path))


@pytest.mark.skipif(
    os.name == "nt", reason="creating symlinks needs privileges on Windows"
)
def test_build_flattens_internal_symlinks(tmp_path: Path) -> None:
    mod = _load("build_site_bundle")
    web = _fake_web(tmp_path)
    (web / ".next" / "standalone" / "linked.js").symlink_to("server.js")
    result = mod.build(web, tmp_path / "out", "linux-amd64", "9.9.9", runner=_ok_runner)
    with zipfile.ZipFile(result["archive"]) as zf:
        info = zf.getinfo("linked.js")
        assert info.file_size > 0


@pytest.mark.skipif(
    os.name == "nt", reason="creating symlinks needs privileges on Windows"
)
def test_build_rejects_external_symlinks(tmp_path: Path) -> None:
    from lore.site_bundle import SiteError

    mod = _load("build_site_bundle")
    web = _fake_web(tmp_path)
    (web / ".next" / "standalone" / "escape.js").symlink_to("/etc/hostname")
    with pytest.raises((SystemExit, SiteError), match="outside"):
        mod.build(web, tmp_path / "out", "linux-amd64", "9.9.9", runner=_ok_runner)


def test_build_fails_when_npm_fails(tmp_path: Path) -> None:
    mod = _load("build_site_bundle")
    web = _fake_web(tmp_path)

    def fail(command: list[str], **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(returncode=1)

    with pytest.raises(SystemExit):
        mod.build(web, tmp_path / "out", "linux-amd64", "9.9.9", runner=fail)


def test_build_rejects_unknown_platform_key(tmp_path: Path) -> None:
    mod = _load("build_site_bundle")
    web = _fake_web(tmp_path)
    with pytest.raises(SystemExit, match="platform"):
        mod.build(web, tmp_path / "out", "plan9-mips", "9.9.9", runner=_ok_runner)


def test_main_rejects_foreign_platform(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mod = _load("build_site_bundle")
    monkeypatch.setattr(mod, "current_platform", lambda: "linux-amd64")
    with pytest.raises(SystemExit, match="cross-platform"):
        mod.main(
            [
                "--output-dir",
                str(tmp_path),
                "--platform",
                "windows-amd64",
                "--version",
                "9.9.9",
                "--web-dir",
                str(tmp_path / "web"),
            ]
        )


def test_main_requires_node_22(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mod = _load("build_site_bundle")
    monkeypatch.setattr(mod, "current_platform", lambda: "linux-amd64")
    monkeypatch.setattr(mod, "node_runtime", lambda: None)
    with pytest.raises(SystemExit, match="Node"):
        mod.main(
            [
                "--output-dir",
                str(tmp_path),
                "--platform",
                "linux-amd64",
                "--version",
                "9.9.9",
                "--web-dir",
                str(tmp_path / "web"),
            ]
        )


def _artifact(
    artifacts: Path,
    platform_key: str,
    version: str,
    build_id: str = BUILD_ID,
    inner_overrides: dict[str, object] | None = None,
    entry_overrides: dict[str, object] | None = None,
) -> Path:
    zip_path = artifacts / f"lore-site-{version}-{platform_key}.zip"
    inner: dict[str, object] = {
        "schema_version": 1,
        "lore_version": version,
        "platform": platform_key,
        "build_id": build_id,
        "node_major": 22,
    }
    if inner_overrides:
        inner.update(inner_overrides)
    inner_bytes = json.dumps(inner).encode("utf-8")
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("server.js", "//")
        zf.writestr("site-manifest.json", inner_bytes)
    entry: dict[str, object] = {
        "platform": platform_key,
        "url": (
            "https://github.com/starrynight-web/LORE/releases/download/"
            f"v{version}/lore-site-{version}-{platform_key}.zip"
        ),
        "sha256": hashlib.sha256(zip_path.read_bytes()).hexdigest(),
        "build_id": build_id,
        "node_major": 22,
        "archive_size": zip_path.stat().st_size,
        "expanded_size": 2 + len(inner_bytes),
    }
    if entry_overrides:
        entry.update(entry_overrides)
    zip_path.with_suffix(".json").write_text(json.dumps(entry), encoding="utf-8")
    return zip_path


def test_assemble_manifest_merges_platforms(tmp_path: Path) -> None:
    mod = _load("assemble_site_manifest")
    artifacts = tmp_path / "art"
    artifacts.mkdir()
    for key in ("windows-amd64", "linux-amd64"):
        _artifact(artifacts, key, "9.9.9")
    manifest = mod.merge(artifacts, "9.9.9")
    assert manifest["schema_version"] == 1
    assert manifest["lore_version"] == "9.9.9"
    assert sorted(manifest["bundles"]) == ["linux-amd64", "windows-amd64"]


def test_assemble_manifest_rejects_hash_mismatch(tmp_path: Path) -> None:
    mod = _load("assemble_site_manifest")
    artifacts = tmp_path / "art"
    artifacts.mkdir()
    _artifact(artifacts, "linux-amd64", "9.9.9")
    sidecar = artifacts / "lore-site-9.9.9-linux-amd64.json"
    entry = json.loads(sidecar.read_text(encoding="utf-8"))
    entry["sha256"] = "0" * 64
    sidecar.write_text(json.dumps(entry), encoding="utf-8")
    with pytest.raises(SystemExit, match="sha256"):
        mod.merge(artifacts, "9.9.9")


def test_assemble_manifest_rejects_unknown_platform(tmp_path: Path) -> None:
    mod = _load("assemble_site_manifest")
    artifacts = tmp_path / "art"
    artifacts.mkdir()
    _artifact(artifacts, "linux-amd64", "9.9.9", entry_overrides={"platform": "plan9"})
    with pytest.raises(SystemExit, match="platform|validation"):
        mod.merge(artifacts, "9.9.9")


def test_assemble_manifest_rejects_filename_platform_drift(tmp_path: Path) -> None:
    mod = _load("assemble_site_manifest")
    artifacts = tmp_path / "art"
    artifacts.mkdir()
    _artifact(
        artifacts,
        "linux-amd64",
        "9.9.9",
        inner_overrides={"platform": "windows-amd64"},
    )
    with pytest.raises(SystemExit, match="windows-amd64|platform"):
        mod.merge(artifacts, "9.9.9")


def test_assemble_manifest_rejects_inner_version_drift(tmp_path: Path) -> None:
    mod = _load("assemble_site_manifest")
    artifacts = tmp_path / "art"
    artifacts.mkdir()
    _artifact(
        artifacts, "linux-amd64", "9.9.9", inner_overrides={"lore_version": "9.9.8"}
    )
    with pytest.raises(SystemExit):
        mod.merge(artifacts, "9.9.9")


def test_assemble_manifest_rejects_inner_build_id_drift(tmp_path: Path) -> None:
    mod = _load("assemble_site_manifest")
    artifacts = tmp_path / "art"
    artifacts.mkdir()
    _artifact(
        artifacts, "linux-amd64", "9.9.9", inner_overrides={"build_id": OTHER_ID}
    )
    with pytest.raises(SystemExit, match="build id"):
        mod.merge(artifacts, "9.9.9")


def test_assemble_manifest_rejects_inner_node_drift(tmp_path: Path) -> None:
    mod = _load("assemble_site_manifest")
    artifacts = tmp_path / "art"
    artifacts.mkdir()
    _artifact(artifacts, "linux-amd64", "9.9.9", inner_overrides={"node_major": 18})
    with pytest.raises(SystemExit, match="Node|node"):
        mod.merge(artifacts, "9.9.9")


def test_assemble_manifest_rejects_expanded_size_drift(tmp_path: Path) -> None:
    mod = _load("assemble_site_manifest")
    artifacts = tmp_path / "art"
    artifacts.mkdir()
    _artifact(
        artifacts, "linux-amd64", "9.9.9", entry_overrides={"expanded_size": 7}
    )
    with pytest.raises(SystemExit, match="expanded"):
        mod.merge(artifacts, "9.9.9")


def test_assemble_manifest_rejects_bad_zip(tmp_path: Path) -> None:
    mod = _load("assemble_site_manifest")
    artifacts = tmp_path / "art"
    artifacts.mkdir()
    zip_path = _artifact(artifacts, "linux-amd64", "9.9.9")
    zip_path.write_bytes(b"not a zip")
    sidecar = zip_path.with_suffix(".json")
    entry = json.loads(sidecar.read_text(encoding="utf-8"))
    entry["sha256"] = hashlib.sha256(b"not a zip").hexdigest()
    entry["archive_size"] = len(b"not a zip")
    sidecar.write_text(json.dumps(entry), encoding="utf-8")
    with pytest.raises(SystemExit):
        mod.merge(artifacts, "9.9.9")


def test_assemble_manifest_rejects_mixed_build_ids(tmp_path: Path) -> None:
    mod = _load("assemble_site_manifest")
    artifacts = tmp_path / "art"
    artifacts.mkdir()
    _artifact(artifacts, "linux-amd64", "9.9.9", build_id=BUILD_ID)
    _artifact(artifacts, "macos-arm64", "9.9.9", build_id=OTHER_ID)
    with pytest.raises(SystemExit, match="different sources"):
        mod.merge(artifacts, "9.9.9")


def _build_support() -> Any:
    sys.path.insert(0, str(ROOT))
    try:
        import build_support
    finally:
        sys.path.remove(str(ROOT))
    return build_support


def _gate_root(tmp_path: Path, bundles: dict[str, Any]) -> Path:
    root = tmp_path / "pkg"
    (root / "lore").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        '[project]\nname = "lore-solo"\nversion = "9.9.9"\n', encoding="utf-8"
    )
    (root / "lore" / "site_bundles.json").write_text(
        json.dumps({"schema_version": 1, "lore_version": "9.9.9", "bundles": bundles}),
        encoding="utf-8",
    )
    return root


def _gate_entry(platform_key: str) -> dict[str, object]:
    return {
        "platform": platform_key,
        "url": (
            "https://github.com/starrynight-web/LORE/releases/download/"
            f"v9.9.9/lore-site-9.9.9-{platform_key}.zip"
        ),
        "sha256": "a" * 64,
        "build_id": BUILD_ID,
        "node_major": 22,
        "archive_size": 100,
        "expanded_size": 200,
    }


def test_release_gate_flags_missing_platforms(tmp_path: Path) -> None:
    build_support = _build_support()
    root = _gate_root(tmp_path, {})
    errors = build_support._release_manifest_errors(root)
    assert len(errors) == 3
    assert any("linux-amd64" in e for e in errors)


def test_release_gate_accepts_complete_manifest(tmp_path: Path) -> None:
    build_support = _build_support()
    bundles = {
        key: _gate_entry(key)
        for key in ("linux-amd64", "windows-amd64", "macos-arm64")
    }
    root = _gate_root(tmp_path, bundles)
    assert build_support._release_manifest_errors(root) == []


def test_release_gate_rejects_nonsense_entries(tmp_path: Path) -> None:
    build_support = _build_support()
    entry = {
        "platform": "x",
        "url": "u",
        "sha256": "s",
        "build_id": "b",
        "node_major": 22,
        "archive_size": 1,
        "expanded_size": 2,
    }
    bundles = {
        key: dict(entry) for key in ("linux-amd64", "windows-amd64", "macos-arm64")
    }
    root = _gate_root(tmp_path, bundles)
    errors = build_support._release_manifest_errors(root)
    assert len(errors) == 3


def test_release_gate_rejects_version_drift(tmp_path: Path) -> None:
    build_support = _build_support()
    root = _gate_root(tmp_path, {})
    (root / "lore" / "site_bundles.json").write_text(
        json.dumps({"schema_version": 1, "lore_version": "0.0.1", "bundles": {}}),
        encoding="utf-8",
    )
    errors = build_support._release_manifest_errors(root)
    assert any("lore_version" in e for e in errors)


@pytest.mark.skipif(
    os.name == "nt" or __import__("shutil").which("sh") is None,
    reason="needs a POSIX shell",
)
def test_bootstrap_forwards_args(tmp_path: Path) -> None:
    import subprocess

    home = tmp_path / "home"
    bin_dir = home / ".lore" / "bin"
    bin_dir.mkdir(parents=True)
    fake = bin_dir / "lore-solo"
    fake.write_text('#!/bin/sh\nprintf "%s" "$*"\n', encoding="utf-8")
    fake.chmod(0o755)
    tools = tmp_path / "tools"
    tools.mkdir()
    uv = tools / "uv"
    uv.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    uv.chmod(0o755)
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["PATH"] = str(tools) + os.pathsep + env.get("PATH", "/usr/bin:/bin")
    script = ROOT / "scripts" / "lore-solo"

    def run(*args: str) -> str:
        result = subprocess.run(
            ["sh", str(script), *args],
            check=False,
            env=env,
            capture_output=True,
            text=True,
            cwd=tmp_path,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    assert run() == "setup"
    assert run("setup", "--port", "4100") == "setup --port 4100"
    assert run("connect", "zed") == "connect zed"
    assert run("doctor") == "doctor"
    assert run("map") == "map"


def test_release_gate_rejects_non_dict_manifest(tmp_path: Path) -> None:
    build_support = _build_support()
    root = _gate_root(tmp_path, {})
    (root / "lore" / "site_bundles.json").write_text(
        json.dumps(["not", "an", "object"]), encoding="utf-8"
    )
    errors = build_support._release_manifest_errors(root)
    assert errors


def test_release_gate_rejects_bool_schema_version(tmp_path: Path) -> None:
    build_support = _build_support()
    bundles = {
        key: _gate_entry(key)
        for key in ("linux-amd64", "windows-amd64", "macos-arm64")
    }
    root = _gate_root(tmp_path, bundles)
    (root / "lore" / "site_bundles.json").write_text(
        json.dumps(
            {"schema_version": True, "lore_version": "9.9.9", "bundles": bundles}
        ),
        encoding="utf-8",
    )
    errors = build_support._release_manifest_errors(root)
    assert any("schema_version" in e for e in errors)


def test_assemble_manifest_rejects_non_dict_sidecar(tmp_path: Path) -> None:
    mod = _load("assemble_site_manifest")
    artifacts = tmp_path / "art"
    artifacts.mkdir()
    (artifacts / "lore-site-9.9.9-linux-amd64.json").write_text(
        json.dumps(["list"]), encoding="utf-8"
    )
    with pytest.raises(SystemExit):
        mod.merge(artifacts, "9.9.9")


def test_build_rejects_env_and_provider_in_staging(tmp_path: Path) -> None:
    mod = _load("build_site_bundle")
    web = _fake_web(tmp_path)
    (web / ".next" / "standalone" / ".env").write_text("SECRET=1", encoding="utf-8")
    nested = web / ".next" / "standalone" / "nested"
    nested.mkdir()
    (nested / ".env.production").write_text("X=1", encoding="utf-8")
    (nested / "provider.json").write_text("{}", encoding="utf-8")
    with pytest.raises(Exception, match="secrets"):
        mod.build(web, tmp_path / "out", "linux-amd64", "9.9.9", runner=_ok_runner)


# --- release_image_assets -------------------------------------------------

_RVERSION = "9.9.9"
_RPLATFORM = "linux-amd64"


def _release_wheel(
    path: Path, constraints: bytes, manifest: dict[str, object]
) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("lore/release_constraints.txt", constraints)
        zf.writestr("lore/site_bundles.json", json.dumps(manifest))
        zf.writestr(
            f"lore_solo-{_RVERSION}.dist-info/METADATA",
            f"Name: lore-solo\nVersion: {_RVERSION}\n",
        )
    return path


def _site_zip(
    path: Path, *, version: str = _RVERSION, build_id: str = BUILD_ID
) -> Path:
    inner = {
        "schema_version": 1,
        "lore_version": version,
        "platform": _RPLATFORM,
        "build_id": build_id,
        "node_major": 22,
    }
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("server.js", "// server")
        zf.writestr("site-manifest.json", json.dumps(inner))
    return path


def _release_manifest(archive: Path, build_id: str = BUILD_ID) -> dict[str, object]:
    return {
        "schema_version": 1,
        "lore_version": _RVERSION,
        "bundles": {
            _RPLATFORM: {
                "platform": _RPLATFORM,
                "url": "https://example.test/lore-site.zip",
                "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                "build_id": build_id,
                "node_major": 22,
                "archive_size": archive.stat().st_size,
                "expanded_size": 1024,
            }
        },
    }


def _release_dist(tmp_path: Path) -> tuple[Path, Path, Path]:
    dist = tmp_path / "dist"
    (dist / "site").mkdir(parents=True)
    archive = _site_zip(dist / "site" / f"lore-site-{_RVERSION}-{_RPLATFORM}.zip")
    constraints = b"pinned==1.0\n"
    manifest = _release_manifest(archive)
    wheel = _release_wheel(
        dist / f"lore_solo-{_RVERSION}-py3-none-any.whl", constraints, manifest
    )
    (dist / "release_constraints.txt").write_bytes(constraints)
    return dist, wheel, archive


def test_release_assets_requires_single_wheel(tmp_path: Path) -> None:
    mod = _load("release_image_assets")
    dist, wheel, _archive = _release_dist(tmp_path)
    wheel.unlink()
    with pytest.raises(SystemExit):
        mod.run(dist=dist, wheels_out=tmp_path / "w", site_out=tmp_path / "s")
    wheel2 = dist / f"lore_solo-{_RVERSION}-py3-none-any.whl"
    _release_wheel(wheel2, b"x\n", {})
    extra = dist / "lore_solo-8.0.0-py3-none-any.whl"
    _release_wheel(extra, b"x\n", {})
    with pytest.raises(SystemExit):
        mod.run(dist=dist, wheels_out=tmp_path / "w", site_out=tmp_path / "s")


def test_release_assets_constraints_must_match(tmp_path: Path) -> None:
    mod = _load("release_image_assets")
    dist, _wheel, _archive = _release_dist(tmp_path)
    (dist / "release_constraints.txt").write_bytes(b"other==2.0\n")
    with pytest.raises(SystemExit):
        mod.run(dist=dist, wheels_out=tmp_path / "w", site_out=tmp_path / "s")
    (dist / "release_constraints.txt").unlink()
    with pytest.raises(SystemExit):
        mod.run(dist=dist, wheels_out=tmp_path / "w", site_out=tmp_path / "s")


def test_release_assets_requires_pinned_entry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    mod = _load("release_image_assets")
    dist, wheel, _archive = _release_dist(tmp_path)
    foreign = {"schema_version": 1, "lore_version": _RVERSION, "bundles": {}}
    _release_wheel(wheel, (dist / "release_constraints.txt").read_bytes(), foreign)
    monkeypatch.setattr(mod, "_install_wheel", lambda _w: None)
    with pytest.raises(SystemExit):
        mod.run(dist=dist, wheels_out=tmp_path / "w", site_out=tmp_path / "s")


def test_release_assets_missing_archive_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    mod = _load("release_image_assets")
    dist, _wheel, archive = _release_dist(tmp_path)
    archive.unlink()
    monkeypatch.setattr(mod, "_install_wheel", lambda _w: None)
    with pytest.raises(SystemExit):
        mod.run(dist=dist, wheels_out=tmp_path / "w", site_out=tmp_path / "s")


def test_release_assets_stages_wheel_and_site(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    mod = _load("release_image_assets")
    dist, wheel, _archive = _release_dist(tmp_path)
    monkeypatch.setattr(mod, "_install_wheel", lambda _w: None)
    wheels_out = tmp_path / "wheels"
    site_out = tmp_path / "site"
    mod.run(dist=dist, wheels_out=wheels_out, site_out=site_out)
    assert (wheels_out / wheel.name).is_file()
    assert (wheels_out / "constraints.txt").read_bytes() == (
        dist / "release_constraints.txt"
    ).read_bytes()
    assert (site_out / "server.js").is_file()
    assert (site_out / "site-manifest.json").is_file()


def test_release_assets_wrong_platform_archive_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    mod = _load("release_image_assets")
    dist, _wheel, archive = _release_dist(tmp_path)
    archive.rename(
        dist / "site" / f"lore-site-{_RVERSION}-windows-amd64.zip"
    )
    monkeypatch.setattr(mod, "_install_wheel", lambda _w: None)
    with pytest.raises(SystemExit):
        mod.run(dist=dist, wheels_out=tmp_path / "w", site_out=tmp_path / "s")


# --- smoke script helpers -------------------------------------------------


def test_smoke_install_pick_bundle_matches_version_platform(
    tmp_path: Path,
) -> None:
    mod = _load("smoke_install")
    bundle_dir = tmp_path / "bundles"
    bundle_dir.mkdir()
    (bundle_dir / "lore-site-9.9.9-windows-amd64.zip").write_text("x")
    (bundle_dir / "lore-site-8.0.0-linux-amd64.zip").write_text("x")
    wanted = bundle_dir / "lore-site-9.9.9-linux-amd64.zip"
    wanted.write_text("x")
    assert mod._pick_bundle(bundle_dir, "9.9.9", "linux-amd64") == wanted
    assert mod._pick_bundle(bundle_dir, "9.9.9", "macos-arm64") is None
    assert mod._pick_bundle(None, "9.9.9", "linux-amd64") is None


def test_smoke_install_wheel_constraints_from_wheel(tmp_path: Path) -> None:
    mod = _load("smoke_install")
    wheel = tmp_path / "lore_solo-9.9.9-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as zf:
        zf.writestr("lore/release_constraints.txt", b"a==1\n")
    out = mod.wheel_constraints(wheel, tmp_path)
    assert out.read_bytes() == b"a==1\n"
    assert out.parent == tmp_path


def test_smoke_install_isolated_env_covers_user_dirs(tmp_path: Path) -> None:
    mod = _load("smoke_install")
    env = mod.isolated_env(tmp_path / "home", tmp_path / "ws", tmp_path / "lib")
    for key in (
        "HOME",
        "USERPROFILE",
        "APPDATA",
        "LOCALAPPDATA",
        "XDG_CONFIG_HOME",
        "XDG_CACHE_HOME",
        "XDG_DATA_HOME",
    ):
        assert key in env and str(tmp_path) in env[key]
    assert env["LORE_WORKSPACE"] == str(tmp_path / "ws")
    assert env["LORE_LIBRARY"] == str(tmp_path / "lib")


def test_smoke_helpers_free_port_and_read_until(tmp_path: Path) -> None:
    for name in ("smoke_install", "smoke_container"):
        mod = _load(name)
        port = mod._free_port()
        assert 1 <= port <= 65535
        import subprocess

        silent = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(5)"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            found, _lines = mod._read_until(silent, "marker", 0.5)
            assert found == ""
        finally:
            silent.kill()
            silent.wait()
        talker = subprocess.Popen(
            [sys.executable, "-c", "print('hello ?key=abc')"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        found, _lines = mod._read_until(talker, "?key=", 5)
        talker.wait()
        assert "?key=abc" in found


def test_smoke_container_decision_ids_and_stdio_env(tmp_path: Path) -> None:
    mod = _load("smoke_container")
    decisions = tmp_path / ".lore" / "decisions"
    decisions.mkdir(parents=True)
    (decisions / "a.md").write_text("x")
    (decisions / "b.md").write_text("x")
    assert mod._decision_ids(tmp_path) == {"a.md", "b.md"}
    env = mod._stdio_env()
    for key in ("HOME", "PATH", "LORE_CLIENT"):
        assert key in env


def test_smoke_evidence_fail_closed(tmp_path: Path) -> None:
    for name in ("smoke_install", "smoke_container"):
        mod = _load(name)
        mod.FAILURES.clear()
        mod.EVIDENCE.clear()
        mod.EVIDENCE.update({"checks": [{"ok": True}], "completed": False})
        args = (tmp_path, "core") if name == "smoke_install" else (tmp_path,)

        out = mod._write_evidence(*args)
        assert json.loads(out.read_text())["ok"] is False

        mod.EVIDENCE["completed"] = True
        out = mod._write_evidence(*args)
        assert json.loads(out.read_text())["ok"] is True

        mod.FAILURES.append("x")
        out = mod._write_evidence(*args)
        assert json.loads(out.read_text())["ok"] is False

        mod.FAILURES.clear()
        mod.EVIDENCE["checks"] = []
        out = mod._write_evidence(*args)
        assert json.loads(out.read_text())["ok"] is False


def test_smoke_install_evidence_fail_closed_on_abort(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    mod = _load("smoke_install")
    wheel = tmp_path / "lore_solo-0.1.2-py3-none-any.whl"
    wheel.write_bytes(b"dummy")
    monkeypatch.setattr(
        mod,
        "_main",
        lambda *_a: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    with pytest.raises(RuntimeError):
        mod.main(["--artifacts", str(tmp_path), "--mode", "core"])
    data = json.loads((tmp_path / "smoke-core.json").read_text())
    assert data["completed"] is False
    assert data["ok"] is False
