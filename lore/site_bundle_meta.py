"""Shared, dependency-free validation for site-bundle metadata.

Imported by `lore.site_bundle` at runtime, and loaded directly by path from
`build_support.py` inside setuptools' isolated build environment where the
`lore` package itself is not importable. Must stay pure stdlib with no
intra-package imports.
"""

from __future__ import annotations

import re
from typing import Any, TypeGuard

PLATFORMS = ("linux-amd64", "windows-amd64", "macos-arm64")
MAX_ARCHIVE_BYTES = 256 * 1024 * 1024
MAX_EXPANDED_BYTES = 1024 * 1024 * 1024
NODE_MAJOR = 22
INNER_MANIFEST = "site-manifest.json"

_ENTRY_KEYS = {
    "platform": str,
    "url": str,
    "sha256": str,
    "build_id": str,
    "node_major": int,
    "archive_size": int,
    "expanded_size": int,
}
_HEX64_RE = re.compile(r"[0-9a-f]{64}")


def is_hex64(value: Any) -> bool:
    return isinstance(value, str) and _HEX64_RE.fullmatch(value) is not None


def _strict_int(value: Any) -> bool:
    return type(value) is int


def _bounded_size(value: Any, limit: int) -> bool:
    return _strict_int(value) and 0 < value <= limit


def valid_entry(entry: Any, platform_key: str) -> TypeGuard[dict[str, Any]]:
    """Strict shape/content checks shared by manifest, gate, and assembler."""
    if not isinstance(entry, dict):
        return False
    if set(_ENTRY_KEYS) - set(entry):
        return False
    platform = entry["platform"]
    if not isinstance(platform, str) or platform not in PLATFORMS:
        return False
    if platform != platform_key:
        return False
    url = entry["url"]
    if not isinstance(url, str) or not url.startswith("https://"):
        return False
    if not is_hex64(entry["sha256"]) or not is_hex64(entry["build_id"]):
        return False
    if not _strict_int(entry["node_major"]) or entry["node_major"] != NODE_MAJOR:
        return False
    if not _bounded_size(entry["archive_size"], MAX_ARCHIVE_BYTES):
        return False
    return _bounded_size(entry["expanded_size"], MAX_EXPANDED_BYTES)
