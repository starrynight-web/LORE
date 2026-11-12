"""Container path translation, the `lore-solo container` wrapper, and
container-aware connect/setup behavior. All docker calls are stubbed."""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from lore import connect, container_cmd, container_paths
from lore.container_paths import PathMappingError
from lore.setup import views
from lore.setup.views import ApiError


@pytest.fixture()
def container(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Path]:
    workspace = tmp_path / "host-workspace"
    library = tmp_path / "host-library"
    workspace.mkdir()
    library.mkdir()
    monkeypatch.setenv("LORE_CONTAINER", "1")
    monkeypatch.setenv("LORE_HOST_WORKSPACE", str(workspace))
    monkeypatch.setenv("LORE_HOST_LIBRARY", str(library))
    return {"workspace": workspace, "library": library}


@pytest.fixture()
def windows_container(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LORE_CONTAINER", "1")
    monkeypatch.setenv("LORE_HOST_WORKSPACE", "C:\\Users\\dev\\proj")
    monkeypatch.setenv("LORE_HOST_LIBRARY", "\\\\nas\\share\\lib")


def test_native_is_identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LORE_CONTAINER", raising=False)
    assert container_paths.to_runtime("/abs/x") == "/abs/x"
    assert container_paths.to_host("/workspace/x") == "/workspace/x"


def test_posix_host_to_runtime(container: dict[str, Path]) -> None:
    workspace = container["workspace"]
    library = container["library"]
    assert (
        container_paths.to_runtime(str(workspace / "src" / "a.py"))
        == "/workspace/src/a.py"
    )
    assert container_paths.to_runtime(str(workspace)) == "/workspace"
    assert (
        container_paths.to_runtime(str(library / "p.md")) == "/library/p.md"
    )


def test_runtime_absolute_passthrough(container: dict[str, Path]) -> None:
    assert container_paths.to_runtime("/workspace/src/a.py") == "/workspace/src/a.py"
    assert container_paths.to_runtime("/library") == "/library"
    with pytest.raises(PathMappingError):
        container_paths.to_runtime("/workspace2/escape.py")


def test_to_host_round_trip(container: dict[str, Path]) -> None:
    workspace = container["workspace"]
    assert container_paths.to_host("/workspace/src/a.py") == str(
        workspace / "src" / "a.py"
    )
    assert container_paths.to_host("/workspace") == str(workspace)


def test_relative_and_parent_parts(container: dict[str, Path]) -> None:
    assert container_paths.to_runtime("src/./a.py") == "src/a.py"
    assert container_paths.to_host("a/b.py") == "a/b.py"
    with pytest.raises(PathMappingError):
        container_paths.to_runtime("../escape.py")
    with pytest.raises(PathMappingError):
        container_paths.to_host("/workspace/../escape.py")


def test_outside_absolute_rejected(container: dict[str, Path]) -> None:
    with pytest.raises(PathMappingError):
        container_paths.to_runtime("/etc/passwd")
    with pytest.raises(PathMappingError):
        container_paths.to_host("/tmp/ephemeral.txt")


def test_ambiguous_roots_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    same = tmp_path / "same"
    same.mkdir()
    monkeypatch.setenv("LORE_CONTAINER", "1")
    monkeypatch.setenv("LORE_HOST_WORKSPACE", str(same))
    monkeypatch.setenv("LORE_HOST_LIBRARY", str(same))
    with pytest.raises(PathMappingError):
        container_paths.to_runtime(str(same / "x.py"))


def test_nested_roots_longest_match(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    outer = tmp_path / "outer"
    inner = outer / "lib"
    inner.mkdir(parents=True)
    monkeypatch.setenv("LORE_CONTAINER", "1")
    monkeypatch.setenv("LORE_HOST_WORKSPACE", str(outer))
    monkeypatch.setenv("LORE_HOST_LIBRARY", str(inner))
    assert container_paths.to_runtime(str(inner / "x.md")) == "/library/x.md"
    assert container_paths.to_runtime(str(outer / "a.py")) == "/workspace/a.py"


def test_windows_host_paths(windows_container: None) -> None:
    assert (
        container_paths.to_runtime("C:\\Users\\dev\\proj\\src\\a.py")
        == "/workspace/src/a.py"
    )
    assert container_paths.to_runtime("c:/users/dev/proj/x.py") == "/workspace/x.py"
    assert (
        container_paths.to_runtime("\\\\nas\\share\\lib\\p.md") == "/library/p.md"
    )
    assert (
        container_paths.to_host("/workspace/src/a.py")
        == "C:\\Users\\dev\\proj\\src\\a.py"
    )


def test_windows_drive_relative_rejected(windows_container: None) -> None:
    with pytest.raises(PathMappingError):
        container_paths.to_runtime("C:nodot.py")


def test_convert_result_fields(container: dict[str, Path]) -> None:
    workspace = container["workspace"]
    result = {
        "summary": "Files: /workspace/src/a.py.",
        "task": {"file": "/workspace/src/a.py", "intent": "fix it"},
        "items": [{"kind": "skill", "source": {"path": "skills/x.md"}}],
        "files": [{"path": "/workspace/src/a.py", "relation": "match"}],
        "omitted": ["file:src/relative.py"],
    }
    converted = container_paths.convert_result(result)
    assert converted["task"]["file"] == str(workspace / "src" / "a.py")
    assert converted["task"]["intent"] == "fix it"
    assert converted["files"][0]["path"] == str(workspace / "src" / "a.py")
    assert converted["items"][0]["source"]["path"] == "skills/x.md"
    assert converted["omitted"] == ["file:src/relative.py"]
    assert "workspace/src" in converted["summary"]


def test_convert_result_unmappable_left_alone(container: dict[str, Path]) -> None:
    result = {"files": [{"path": "/tmp/outside.py"}]}
    converted = container_paths.convert_result(result)
    assert converted["files"][0]["path"] == "/tmp/outside.py"


def test_validate_image() -> None:
    assert container_cmd._validate_image("lore-solo:0.1.2-mcp") == "lore-solo:0.1.2-mcp"
    digest = "repo/lore@sha256:" + "a" * 64
    assert container_cmd._validate_image(digest) == digest
    for bad in ("", "lore-solo", "lore-solo:latest", "-evil", "repo/x@"):
        with pytest.raises(container_cmd.ContainerError):
            container_cmd._validate_image(bad)


def test_validate_root(tmp_path: Path) -> None:
    ok = container_cmd._validate_root(tmp_path, "workspace")
    assert ok == str(tmp_path.resolve())
    with pytest.raises(container_cmd.ContainerError):
        container_cmd._validate_root(tmp_path / "missing", "workspace")
    with pytest.raises(container_cmd.ContainerError):
        container_cmd._validate_root(Path("/"), "workspace")
    with pytest.raises(container_cmd.ContainerError):
        container_cmd._validate_root(Path.home(), "workspace")
    if os_supports(tmp_path):
        comma = tmp_path / "a,b"
        comma.mkdir()
        with pytest.raises(container_cmd.ContainerError):
            container_cmd._validate_root(comma, "library")


def os_supports(path: Path) -> bool:
    return sys.platform != "win32"


def test_docker_command_shape(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(container_cmd, "_uid_gid", lambda: (1000, 1000))
    monkeypatch.delenv("LORE_CLIENT", raising=False)
    command = container_cmd.docker_command(
        "docker",
        mode="mcp",
        image="lore-solo:0.1.2-mcp",
        workspace="/host/ws",
        library="/host/lib",
        port=3000,
        name="lore-mcp-deadbeef",
    )
    assert command[1:5] == ["run", "--rm", "--init", "--pull=never"]
    assert "-i" in command
    assert "-t" not in command
    assert "--user" in command and "1000:1000" in command
    joined = " ".join(command)
    assert "type=bind,source=/host/ws,target=/workspace" in joined
    assert "type=bind,source=/host/lib,target=/library" in joined
    assert joined.count("type=bind") == 2
    assert command[-2:] == ["lore-solo:0.1.2-mcp", "mcp"]
    assert "-e" in command
    assert any(arg == "LORE_HOST_WORKSPACE=/host/ws" for arg in command)
    assert "--publish" not in command


def test_docker_command_setup_and_map(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(container_cmd, "_uid_gid", lambda: None)
    monkeypatch.setenv("LORE_CLIENT", "cursor")
    setup = container_cmd.docker_command(
        "docker",
        mode="setup",
        image="lore-solo:0.1.2-full",
        workspace="/w",
        library="/l",
        port=8080,
        name="n",
    )
    assert "127.0.0.1:8080:3000" in setup
    assert setup[-3:] == ["setup", "--port", "3000"]
    assert "-i" not in setup
    assert "LORE_CLIENT=cursor" in setup
    mapped = container_cmd.docker_command(
        "docker",
        mode="map",
        image="lore-solo:0.1.2-mcp",
        workspace="/w",
        library="/l",
        port=3000,
        name="n",
    )
    assert mapped[-2:] == ["map", "/workspace"]
    assert "-i" not in mapped


def test_run_refuses_root_uid(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(os, "getuid", lambda: 0, raising=False)
    monkeypatch.setattr(shutil, "which", lambda _n: "/usr/bin/docker")
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: _ok_completed()
    )
    code = container_cmd.run(
        ["mcp", "--image", "x:1", "--workspace", str(tmp_path)]
    )
    assert code == 2


def _ok_completed() -> object:
    import subprocess as sp

    return sp.CompletedProcess([], 0)


def test_run_missing_docker(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(shutil, "which", lambda _n: None)
    code = container_cmd.run(["mcp", "--image", "x:1", "--workspace", str(tmp_path)])
    assert code == 2


def test_run_missing_image(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(shutil, "which", lambda _n: "/usr/bin/docker")

    def fail(*a: object, **k: object) -> object:
        import subprocess as sp

        return sp.CompletedProcess([], 1)

    monkeypatch.setattr(subprocess, "run", fail)
    code = container_cmd.run(["mcp", "--image", "x:1", "--workspace", str(tmp_path)])
    assert code == 2


def test_register_agents_docker_args(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("LORE_CONTAINER", raising=False)
    monkeypatch.setenv("LORE_COMMAND", "/opt/lore/lore-solo")
    monkeypatch.setenv("LORE_WORKSPACE", str(tmp_path))
    (tmp_path / "lib").mkdir()
    monkeypatch.setenv("LORE_LIBRARY", str(tmp_path / "lib"))
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "nohome")
    entries: dict[str, Any] = {}

    monkeypatch.setattr(
        connect, "_write_json", lambda path, key, entry: entries.setdefault(key, entry)
    )
    monkeypatch.setattr(connect, "_write_rules", lambda home: [])
    monkeypatch.setattr(connect, "_write_project_files", lambda *a, **k: [])
    cursor = tmp_path / "nohome" / ".cursor"
    cursor.mkdir(parents=True)
    result = connect.register_agents(runtime="docker", image="lore-solo:0.1.2-mcp")
    entry = entries["mcpServers"]
    args = entry["args"]
    assert args[:4] == [
        "container",
        "mcp",
        "--image",
        "lore-solo:0.1.2-mcp",
    ]
    assert "--workspace" in args and str(tmp_path.resolve()) in args
    assert entry["command"] == "/opt/lore/lore-solo"
    assert result["written"]


def test_register_agents_uvx_docker_args(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("LORE_CONTAINER", raising=False)
    monkeypatch.delenv("LORE_COMMAND", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "nohome")
    monkeypatch.setattr(shutil, "which", lambda _n: None)
    monkeypatch.setenv("LORE_WORKSPACE", str(tmp_path))
    (tmp_path / "lib").mkdir()
    monkeypatch.setenv("LORE_LIBRARY", str(tmp_path / "lib"))
    command, args = connect._docker_invocation(*connect.invocation(), "img:1")
    assert command == "uvx"
    assert "--no-build" in args
    tail = args[args.index("container") :]
    assert tail == [
        "container",
        "mcp",
        "--image",
        "img:1",
        "--workspace",
        str(tmp_path.resolve()),
        "--library",
        str((tmp_path / "lib").resolve()),
    ]


def test_register_agents_refuses_inside_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LORE_CONTAINER", "1")
    with pytest.raises(SystemExit):
        connect.register_agents()


def test_run_connect_passes_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen: dict[str, object] = {}
    monkeypatch.setenv("LORE_WORKSPACE", "sentinel-ws")
    monkeypatch.setenv("LORE_LIBRARY", "sentinel-lib")

    monkeypatch.setattr(
        connect,
        "register_agents",
        lambda home=None, system=None, **kw: seen.update(kw) or {"written": [], "skipped": []},
    )
    connect.run_connect(
        [
            "--runtime",
            "docker",
            "--image",
            "img:1",
            "--workspace",
            str(tmp_path),
            "--library",
            str(tmp_path / "lib"),
        ]
    )
    assert seen == {"runtime": "docker", "image": "img:1"}
    assert os.environ["LORE_WORKSPACE"] == str(tmp_path)
    assert os.environ["LORE_LIBRARY"] == str(tmp_path / "lib")


def test_container_roots_only_mounts(
    container: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LORE_WORKSPACE", "/workspace")
    monkeypatch.setenv("LORE_LIBRARY", "/library")
    roots = views._roots()
    assert roots == [Path("/workspace").resolve(), Path("/library").resolve()]


def test_container_allowed_translates_host(
    container: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LORE_WORKSPACE", "/workspace")
    monkeypatch.setenv("LORE_LIBRARY", "/library")
    host = container["workspace"]
    target = host / "src"
    target.mkdir()
    allowed = views._allowed(str(target))
    assert allowed == Path("/workspace/src")
    with pytest.raises(ApiError):
        views._allowed("/etc")
    with pytest.raises(ApiError):
        views._allowed("/workspace/../outside")


def test_container_codebase_stores_host_path(
    container: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LORE_WORKSPACE", "/workspace")
    monkeypatch.setenv("LORE_LIBRARY", "/library")
    from lore.core import codebases

    host = container["workspace"]
    folder = host / "repo"
    folder.mkdir()
    project = host / "proj"
    (project / ".lore").mkdir(parents=True)
    real_is_dir = Path.is_dir
    monkeypatch.setattr(
        Path,
        "is_dir",
        lambda p: True if str(p).startswith("/workspace") else real_is_dir(p),
    )
    row = codebases.add_codebase(project, "repo", Path("/workspace/repo"))
    assert row["path"] == str(folder.resolve())
    saved = json.loads((project / ".lore" / "codebases.json").read_text())
    assert saved[0]["path"] == str(folder.resolve())


def test_container_codebase_payload_and_rows(
    container: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LORE_WORKSPACE", "/workspace")
    monkeypatch.setenv("LORE_LIBRARY", "/library")
    host = container["workspace"]
    mounted = host / "repo"
    mounted.mkdir()
    project = host / "proj"
    (project / ".lore").mkdir(parents=True)
    row = {"id": "a", "name": "repo", "path": str(mounted)}
    payload = views._codebase_payload(project, row)
    assert payload["path"] == str(mounted)
    foreign = {"id": "b", "name": "gone", "path": "/elsewhere/repo"}
    payload = views._codebase_payload(project, foreign)
    assert payload["path"] == "/elsewhere/repo"
    assert payload["map"]["state"] == "missing"
    assert "not mounted" in payload["note"]
    with pytest.raises(ApiError):
        views._codebase_folder(foreign)


def test_connect_views_refuse_in_container(
    container: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LORE_WORKSPACE", "/workspace")
    monkeypatch.setenv("LORE_LIBRARY", "/library")
    from django.conf import settings

    if not settings.configured:
        settings.configure(DEFAULT_CHARSET="utf-8", SECRET_KEY="test")
    from django.test import RequestFactory

    factory = RequestFactory()
    post = factory.post("/api/connect", data="{}", content_type="application/json")
    response = views.connect(post)
    assert response.status_code == 400
    agents = factory.post("/api/connect/agents")
    response = views.connect_agents(agents)
    assert response.status_code == 400
    get = factory.get("/api/connect")
    response = views.connect(get)
    assert response.status_code == 200
    assert "--runtime docker" in json.loads(response.content)["command"]


def test_validate_image_empty_tag() -> None:
    for bad in ("x:", "repo/x:", "-:", "img@sha256:"):
        with pytest.raises(container_cmd.ContainerError):
            container_cmd._validate_image(bad)


def test_forward_slash_unc(windows_container: None) -> None:
    assert container_paths.to_runtime("//nas/share/lib/p.md") == "/library/p.md"


def test_relative_backslash_normalized(container: dict[str, Path]) -> None:
    assert container_paths.to_runtime("src\\a.py") == "src/a.py"
    assert container_paths.to_runtime("dir\\sub\\x.md") == "dir/sub/x.md"


def test_parent_backslash_rejected(container: dict[str, Path]) -> None:
    with pytest.raises(PathMappingError):
        container_paths.to_runtime("..\\escape.py")


def test_drive_less_root_rejected(container: dict[str, Path]) -> None:
    with pytest.raises(PathMappingError):
        container_paths.to_runtime("\\Windows\\system32\\x.dll")


def test_unicode_and_space_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workspace = tmp_path / "héllo wörld"
    library = tmp_path / "bïbliothèque"
    workspace.mkdir()
    library.mkdir()
    monkeypatch.setenv("LORE_CONTAINER", "1")
    monkeypatch.setenv("LORE_HOST_WORKSPACE", str(workspace))
    monkeypatch.setenv("LORE_HOST_LIBRARY", str(library))
    assert (
        container_paths.to_runtime(str(workspace / "füße datei.py"))
        == "/workspace/füße datei.py"
    )
    assert (
        container_paths.to_runtime(str(library / ".md"))
        == "/library/.md"
    )


def test_docker_command_home_and_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(container_cmd, "_uid_gid", lambda: (1000, 1000))
    command = container_cmd.docker_command(
        "docker",
        mode="mcp",
        image="lore-solo:0.1.2-mcp",
        workspace="/host/ws",
        library="/host/lib",
        port=3000,
        name="lore-mcp-x",
    )
    assert "io.lore.workspace=/host/ws" in command
    assert "HOME=/tmp/lore-home" in command
    monkeypatch.setattr(container_cmd, "_uid_gid", lambda: (1500, 1500))
    command = container_cmd.docker_command(
        "docker",
        mode="mcp",
        image="lore-solo:0.1.2-mcp",
        workspace="/host/ws",
        library="/host/lib",
        port=3000,
        name="lore-mcp-x",
    )
    assert "HOME=/tmp/lore-home-1500" in command
    assert "1500:1500" in command


def test_docker_command_keep_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(container_cmd, "_uid_gid", lambda: (1000, 1000))
    command = container_cmd.docker_command(
        "docker",
        mode="mcp",
        image="x:1",
        workspace="/w",
        library="/l",
        port=3000,
        name="n",
        keep_id=True,
    )
    assert "--userns=keep-id" in command
    assert command.index("--userns=keep-id") < command.index("--user")
    plain = container_cmd.docker_command(
        "docker",
        mode="mcp",
        image="x:1",
        workspace="/w",
        library="/l",
        port=3000,
        name="n",
    )
    assert "--userns=keep-id" not in plain


def test_uses_keep_id_detection(monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess as sp

    def podman(*a: object, **k: object) -> object:
        return sp.CompletedProcess(
            [], 0, stdout="Client: Podman Engine\nVersion: 6.2.0", stderr=""
        )

    monkeypatch.setattr(subprocess, "run", podman)
    assert container_cmd._uses_keep_id("docker") is True

    def docker(*a: object, **k: object) -> object:
        return sp.CompletedProcess(
            [], 0, stdout="Server: Docker Engine - Community", stderr=""
        )

    monkeypatch.setattr(subprocess, "run", docker)
    assert container_cmd._uses_keep_id("docker") is False

    def broken(*a: object, **k: object) -> object:
        raise OSError("no engine")

    monkeypatch.setattr(subprocess, "run", broken)
    assert container_cmd._uses_keep_id("docker") is False


def test_run_identical_roots(tmp_path: Path) -> None:
    same = tmp_path / "same"
    same.mkdir()
    code = container_cmd.run(
        [
            "mcp",
            "--image",
            "x:1",
            "--workspace",
            str(same),
            "--library",
            str(same),
        ]
    )
    assert code == 2


def test_run_inspect_error_concise(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(shutil, "which", lambda _n: "/usr/bin/docker")

    def broken(*a: object, **k: object) -> object:
        raise OSError("engine socket missing")

    monkeypatch.setattr(subprocess, "run", broken)
    code = container_cmd.run(["mcp", "--image", "x:1", "--workspace", str(tmp_path)])
    assert code == 2


def _stub_run_env(
    monkeypatch: pytest.MonkeyPatch, popen: type
) -> list[list[str]]:
    import subprocess as sp

    monkeypatch.setattr(shutil, "which", lambda _n: "/usr/bin/docker")
    monkeypatch.setattr(container_cmd, "_uses_keep_id", lambda _d: False)
    monkeypatch.setattr(container_cmd, "_uid_gid", lambda: (1000, 1000))
    stops: list[list[str]] = []

    def fake_run(cmd: list[str], **kw: object) -> object:
        if "stop" in cmd:
            stops.append(list(cmd))
        return sp.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(subprocess, "Popen", popen)
    return stops


def test_run_returns_child_code_and_restores_sigterm(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import signal as sig

    class Done:
        def __init__(self, *a: object, **k: object) -> None:
            pass

        def poll(self) -> int:
            return 7

        def wait(self, timeout: float | None = None) -> int:
            return 7

        def terminate(self) -> None:
            pass

        def kill(self) -> None:
            pass

    _stub_run_env(monkeypatch, Done)
    lib = tmp_path / "lib"
    lib.mkdir()
    before = sig.getsignal(sig.SIGTERM) if hasattr(sig, "SIGTERM") else None
    code = container_cmd.run(
        ["mcp", "--image", "x:1", "--workspace", str(tmp_path), "--library", str(lib)]
    )
    assert code == 7
    if before is not None:
        assert sig.getsignal(sig.SIGTERM) == before


def test_run_keyboardinterrupt_stops_own_container(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class Hanging:
        def __init__(self, *a: object, **k: object) -> None:
            self.calls = 0

        def poll(self) -> int | None:
            return None if self.calls == 0 else 130

        def wait(self, timeout: float | None = None) -> int:
            self.calls += 1
            if self.calls == 1:
                raise KeyboardInterrupt
            return 130

        def terminate(self) -> None:
            pass

        def kill(self) -> None:
            pass

    lib = tmp_path / "lib"
    lib.mkdir()
    stops = _stub_run_env(monkeypatch, Hanging)
    code = container_cmd.run(
        [
            "mcp",
            "--image",
            "x:1",
            "--workspace",
            str(tmp_path),
            "--library",
            str(lib),
        ]
    )
    assert code == 130
    assert len(stops) == 1
    stop = stops[0]
    assert "stop" in stop
    assert stop[-1].startswith("lore-mcp-")


def test_mcp_entry_honors_args_without_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LORE_COMMAND", raising=False)
    monkeypatch.setattr(shutil, "which", lambda _n: None)
    entry = connect.mcp_entry("vscode", args=["custom", "args"])
    assert entry["args"] == ["custom", "args"]
    assert entry["command"] == connect.invocation()[0]


def test_docker_invocation_rejects_bad_image(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "lib").mkdir()
    monkeypatch.setenv("LORE_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("LORE_LIBRARY", str(tmp_path / "lib"))
    for bad in ("", "img", "img:latest", "img:", "-img:1"):
        with pytest.raises(SystemExit):
            connect._docker_invocation("lore-solo", ["mcp"], bad)


def test_docker_invocation_rejects_missing_library(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("LORE_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("LORE_LIBRARY", str(tmp_path / "missing"))
    with pytest.raises(SystemExit):
        connect._docker_invocation("lore-solo", ["mcp"], "img:1")


def test_docker_invocation_rejects_same_roots(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("LORE_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("LORE_LIBRARY", str(tmp_path))
    with pytest.raises(SystemExit):
        connect._docker_invocation("lore-solo", ["mcp"], "img:1")


def _factory() -> Any:
    from django.conf import settings

    if not settings.configured:
        settings.configure(DEFAULT_CHARSET="utf-8", SECRET_KEY="test")
    from django.test import RequestFactory

    return RequestFactory()


def test_outside_row_delete_preserves_registry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("LORE_CONTAINER", raising=False)
    project = tmp_path / "proj"
    (project / ".lore").mkdir(parents=True)
    monkeypatch.setenv("LORE_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("LORE_LIBRARY", str(tmp_path / "lib"))
    from lore.core import codebases

    outside = tmp_path.parents[1] / "outside-lore-test"
    outside.mkdir(exist_ok=True)
    row = codebases.add_codebase(project, "outside", outside)
    factory = _factory()
    request = factory.delete(f"/api/codebases/{row['id']}")
    request.headers = {**request.headers, "X-Lore-Project": str(project)}
    response = views.codebase_detail(request, row["id"])
    assert response.status_code == 400
    remaining = [r["id"] for r in codebases.list_codebases(project)]
    assert row["id"] in remaining


def test_symlink_escape_rejected_native(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("LORE_CONTAINER", raising=False)
    workspace = tmp_path / "ws"
    inside = workspace / "linkdir"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    try:
        inside.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")
    monkeypatch.setenv("LORE_WORKSPACE", str(workspace))
    monkeypatch.setenv("LORE_LIBRARY", str(tmp_path / "lib"))
    with pytest.raises(ApiError):
        views._allowed(str(inside))


def test_container_reads_native_row_and_back(
    container: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LORE_WORKSPACE", "/workspace")
    monkeypatch.setenv("LORE_LIBRARY", "/library")
    host = container["workspace"]
    # A row written by the native runtime keeps the host path; inside the
    # container it must resolve to the mounted location.
    row = {"id": "n", "name": "repo", "path": str(host / "repo")}
    assert views._codebase_folder(row) == Path("/workspace/repo")
    # A row written by the container runtime stores the host path already;
    # resolving again stays inside the mount, and the native runtime sees
    # the same host path back.
    assert views._codebase_folder(row) == Path("/workspace/repo")
    monkeypatch.delenv("LORE_CONTAINER", raising=False)
    monkeypatch.setenv("LORE_WORKSPACE", str(container["workspace"]))
    monkeypatch.setenv("LORE_LIBRARY", str(container["library"]))
    resolved = views._codebase_folder(row)
    assert resolved == (host / "repo").resolve()
    with pytest.raises(ApiError):
        views._codebase_folder({"id": "x", "name": "x", "path": "/definitely/elsewhere"})


def test_validate_root_rejects_nul_and_symlink_loop(tmp_path: Path) -> None:
    with pytest.raises(container_cmd.ContainerError):
        container_cmd._validate_root(Path("a\x00b"), "workspace")
    loop_a = tmp_path / "loop-a"
    loop_b = tmp_path / "loop-b"
    try:
        loop_a.symlink_to(loop_b.name)
        loop_b.symlink_to(loop_a.name)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")
    with pytest.raises(container_cmd.ContainerError):
        container_cmd._validate_root(loop_a, "workspace")


def test_run_keyboardinterrupt_stop_timeout_still_kills_own_process(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import subprocess as sp

    killed: list[bool] = []

    class Hanging:
        def __init__(self, *a: object, **k: object) -> None:
            self.calls = 0

        def poll(self) -> int | None:
            return None if self.calls == 0 else 130

        def wait(self, timeout: float | None = None) -> int:
            self.calls += 1
            if self.calls == 1:
                raise KeyboardInterrupt
            if self.calls == 2:
                raise sp.TimeoutExpired(["docker"], 15)
            return 0

        def terminate(self) -> None:
            pass

        def kill(self) -> None:
            killed.append(True)

    monkeypatch.setattr(shutil, "which", lambda _n: "/usr/bin/docker")
    monkeypatch.setattr(container_cmd, "_uses_keep_id", lambda _d: False)
    monkeypatch.setattr(container_cmd, "_uid_gid", lambda: (1000, 1000))

    def fake_run(cmd: list[str], **kw: object) -> object:
        if "stop" in cmd:
            raise sp.TimeoutExpired(cmd, 15)
        return sp.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(subprocess, "Popen", Hanging)
    lib = tmp_path / "lib"
    lib.mkdir()
    code = container_cmd.run(
        [
            "mcp",
            "--image",
            "x:1",
            "--workspace",
            str(tmp_path),
            "--library",
            str(lib),
        ]
    )
    assert code == 130
    assert killed == [True]
