"""Read and write one markdown file with a YAML header."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class OkfError(ValueError):
    """The file is not a Lore markdown document."""


@dataclass
class Doc:
    header: dict[str, Any]
    body: str
    path: Path | None = field(default=None)

    def get(self, key: str, default: str = "") -> str:
        value = self.header.get(key, default)
        if value is None:
            return default
        return str(value)


def read_doc(path: Path) -> Doc:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise OkfError(f"{path} does not start with a YAML header")
    rest = text[3:]
    rest = rest.removeprefix("\n")
    marker = "\n---"
    end = rest.find(marker)
    if end < 0:
        raise OkfError(f"{path} is missing the closing --- of the YAML header")
    raw_header = rest[:end]
    body = rest[end + len(marker) :]
    body = body.removeprefix("\n")
    loaded = yaml.safe_load(raw_header)
    if loaded is None:
        header: dict[str, Any] = {}
    elif not isinstance(loaded, dict):
        raise OkfError(f"{path} header must be a mapping")
    else:
        header = dict(loaded)
    return Doc(header=header, body=body, path=path)


def write_doc(path: Path, doc: Doc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    dumped = yaml.safe_dump(
        doc.header,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    ).rstrip()
    body = doc.body
    if body and not body.endswith("\n"):
        body += "\n"
    text = f"---\n{dumped}\n---\n{body}"
    path.write_text(text, encoding="utf-8")
