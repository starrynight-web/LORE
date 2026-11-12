"""Run Lore inside a container image with only the two bind mounts.

`lore-solo container mcp|setup|map --image IMAGE [--workspace DIR]
[--library DIR] [--port PORT]` wraps `docker run` so the editor or user
never mounts a home directory, socket, or extra paths.
"""

from __future__ import annotations

import argparse
import os
import platform
import secrets
import shutil
import signal
import subprocess
import sys
from pathlib import Path

from lore.core.paths import library_root, workspace_root

WORKSPACE_MOUNT = "/workspace"
LIBRARY_MOUNT = "/library"
_WEB_INTERNAL_PORT = 3000


class ContainerError(Exception):
    """A container run request is invalid or cannot be fulfilled."""


def _validate_image(image: str) -> str:
    name = image.strip()
    if not name or name.startswith("-"):
        raise ContainerError("an image name is required, for example lore-solo:0.2.0-mcp")
    tail = name.rsplit("/", 1)[-1]
    if "@" in tail:
        digest = tail.rsplit("@", 1)[-1]
        if ":" not in digest or not digest.split(":", 1)[-1]:
            raise ContainerError(f"image digest is not complete: {image}")
        return name
    if ":" not in tail or not tail.rsplit(":", 1)[-1]:
        raise ContainerError(
            f"image {image} has no tag or digest; use a versioned tag like "
            "lore-solo:0.2.0-mcp"
        )
    if tail.rsplit(":", 1)[-1] == "latest":
        raise ContainerError(
            "the :latest tag is not allowed; use a versioned tag like "
            "lore-solo:0.2.0-mcp"
        )
    return name


def _validate_root(raw: Path, label: str) -> str:
    try:
        resolved = raw.expanduser().resolve(strict=True)
    except (OSError, ValueError, RuntimeError) as exc:
        raise ContainerError(f"--{label} must be an existing directory: {exc}") from exc
    if not resolved.is_dir():
        raise ContainerError(f"--{label} must be an existing directory: {resolved}")
    if resolved.parent == resolved:
        raise ContainerError(f"--{label} cannot be the filesystem root")
    if resolved == Path.home().resolve():
        raise ContainerError(f"--{label} cannot be the entire home directory")
    text = str(resolved)
    if any(bad in text for bad in (",", "\x00", "\n", "\r")):
        raise ContainerError(
            f"--{label} contains characters Docker mounts cannot carry: {resolved}"
        )
    return text


def _validate_port(port: int | None) -> int:
    chosen = _WEB_INTERNAL_PORT if port is None else port
    if not 1 <= chosen <= 65535:
        raise ContainerError(f"--port must be between 1 and 65535, got {chosen}")
    return chosen


def _uid_gid() -> tuple[int, int] | None:
    if platform.system() != "Linux" or not hasattr(os, "getuid"):
        return None
    uid, gid = os.getuid(), os.getgid()
    if uid == 0:
        raise ContainerError(
            "refusing to run the container as root; the image uses a non-root "
            "user, so run this command as a regular user"
        )
    return uid, gid


def _uses_keep_id(docker: str) -> bool:
    """Rootless Podman maps container uids through subuids, so --user alone
    cannot write to the caller's bind mounts; --userns=keep-id does."""
    try:
        probe = subprocess.run(
            [docker, "version"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return "podman" in (probe.stdout + probe.stderr).lower()


def _ensure_image(docker: str, image: str, mode: str) -> None:
    try:
        probe = subprocess.run(
            [docker, "image", "inspect", image],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ContainerError(
            f"could not inspect image {image}: is the container engine "
            f"running? ({exc})"
        ) from exc
    if probe.returncode != 0:
        target = "mcp" if mode == "mcp" else "full"
        raise ContainerError(
            f"container image {image} was not found locally. Build it first, for "
            f"example: docker build --target {target} -t {image} ."
        )


def docker_command(
    docker: str,
    *,
    mode: str,
    image: str,
    workspace: str,
    library: str,
    port: int,
    name: str,
    keep_id: bool = False,
) -> list[str]:
    command = [
        docker,
        "run",
        "--rm",
        "--init",
        "--pull=never",
        "--name",
        name,
        "--label",
        f"io.lore.workspace={workspace}",
    ]
    if mode == "mcp":
        command.append("-i")
    ids = _uid_gid()
    if ids is not None:
        if keep_id:
            command += ["--userns=keep-id"]
        command += ["--user", f"{ids[0]}:{ids[1]}"]
    # The image-owned /tmp/lore-home is only writable for uid 1000; other
    # host uids get their own scratch home under /tmp.
    if ids is not None and ids[0] != 1000:
        home = f"/tmp/lore-home-{ids[0]}"
    else:
        home = "/tmp/lore-home"
    env = {
        "HOME": home,
        "LORE_HOST_WORKSPACE": workspace,
        "LORE_HOST_LIBRARY": library,
    }
    client = os.environ.get("LORE_CLIENT", "").strip()
    if client:
        env["LORE_CLIENT"] = client
    for key, value in env.items():
        command += ["-e", f"{key}={value}"]
    command += [
        "--mount",
        f"type=bind,source={workspace},target={WORKSPACE_MOUNT}",
        "--mount",
        f"type=bind,source={library},target={LIBRARY_MOUNT}",
    ]
    if mode == "setup":
        command += ["--publish", f"127.0.0.1:{port}:{_WEB_INTERNAL_PORT}"]
    command.append(image)
    command.append(mode)
    if mode == "setup":
        command += ["--port", str(_WEB_INTERNAL_PORT)]
    elif mode == "map":
        command.append(WORKSPACE_MOUNT)
    return command


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lore-solo container")
    parser.add_argument("mode", choices=["mcp", "setup", "map"])
    parser.add_argument("--image", required=True)
    parser.add_argument("--workspace", type=Path, default=None)
    parser.add_argument("--library", type=Path, default=None)
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args(list(argv or []))
    try:
        image = _validate_image(args.image)
        workspace = _validate_root(
            args.workspace if args.workspace is not None else workspace_root(),
            "workspace",
        )
        library = _validate_root(
            args.library if args.library is not None else library_root(),
            "library",
        )
        if workspace == library:
            raise ContainerError(
                "--workspace and --library must be different directories"
            )
        port = _validate_port(args.port)
        docker = shutil.which("docker")
        if docker is None:
            raise ContainerError(
                "docker is not on PATH; install Docker or Podman to use "
                "container runtimes"
            )
        _ensure_image(docker, image, args.mode)
        _uid_gid()
    except ContainerError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    name = f"lore-{args.mode}-{secrets.token_hex(4)}"
    command = docker_command(
        docker,
        mode=args.mode,
        image=image,
        workspace=workspace,
        library=library,
        port=port,
        name=name,
        keep_id=_uses_keep_id(docker),
    )
    try:
        process = subprocess.Popen(command)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"could not start the container runtime: {exc}", file=sys.stderr)
        return 2

    def _forward(_signum: int, _frame: object) -> None:
        if process.poll() is None:
            process.terminate()

    previous = None
    if hasattr(signal, "SIGTERM"):
        previous = signal.signal(signal.SIGTERM, _forward)
    try:
        try:
            return process.wait()
        except KeyboardInterrupt:
            try:
                subprocess.run(
                    [docker, "stop", "-t", "5", name],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=15,
                    check=False,
                )
            except (OSError, subprocess.SubprocessError):
                pass
            finally:
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
            return 130
    finally:
        if previous is not None and hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, previous)
