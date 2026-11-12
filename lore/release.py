"""Release identity for the published Lore Solo distribution.

The wheel version, the uv tool install spec, the site-bundle download URL,
and the pinned dependency constraints all come from one place so a release
cannot drift between them.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from importlib.resources import files
from pathlib import Path

from lore import __version__


def release_version() -> str:
    return __version__


def release_tag() -> str:
    return f"v{__version__}"


def published_spec(*, with_map: bool) -> str:
    extra = "[map]" if with_map else ""
    return f"lore-solo{extra}=={__version__}"


def bundle_url(platform_key: str, version: str | None = None) -> str:
    version = version or __version__
    return (
        "https://github.com/starrynight-web/LORE/releases/download/"
        f"v{version}/lore-site-{version}-{platform_key}.zip"
    )


def packaged_constraints() -> Path | None:
    try:
        resource = files("lore").joinpath("release_constraints.txt")
    except (FileNotFoundError, TypeError):
        return None
    if resource.is_file():
        return Path(str(resource))
    return None


def export_constraints(uv: str, project: Path) -> Path:
    """Pin the locked dependency set for `uv tool install -c <file>`.

    Runs the packaged export recipe against the checkout's uv.lock into a
    temporary file; the caller owns cleanup.
    """
    handle, name = tempfile.mkstemp(prefix="lore-constraints-", suffix=".txt")
    os.close(handle)
    target = Path(name)
    command = [
        uv,
        "export",
        "--frozen",
        "--extra",
        "map",
        "--no-dev",
        "--no-emit-project",
        "--no-hashes",
        "--output-file",
        str(target),
    ]
    result = subprocess.run(
        command,
        cwd=project,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        try:
            target.unlink()
        except OSError:
            pass
        detail = (result.stderr or result.stdout or "uv export failed").strip()
        raise RuntimeError(detail)
    return target
