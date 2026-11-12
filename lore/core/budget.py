"""Count tokens for the 800-token answer cap.

The count is cl100k_base when the tiktoken encoder is installed. That is the
same encoding the previous Go engine used. If the encoder cannot be loaded,
the count is one token per three UTF-8 bytes, rounded up. Tests pin both
behaviors by name.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Protocol


class _Encoder(Protocol):
    def encode(self, text: str) -> list[int]: ...


@lru_cache(maxsize=1)
def _encoder() -> _Encoder | None:
    try:
        import tiktoken
    except ImportError:
        return None
    try:
        return tiktoken.get_encoding("cl100k_base")
    except (OSError, ValueError, RuntimeError):
        return None


def count_tokens(text: str) -> int:
    encoder = _encoder()
    if encoder is not None:
        return len(encoder.encode(text))
    return _bytes_fallback(text)


def _bytes_fallback(text: str) -> int:
    """One token per three UTF-8 bytes, rounded up. Used only if tiktoken is missing."""
    return (len(text.encode("utf-8")) + 2) // 3


def context_content_text(
    summary: str,
    items: list[dict[str, Any]],
    files: list[dict[str, Any]] | None = None,
) -> str:
    """The exact string the context budget measures.

    Final summary, then each item's title/text pair, then each file's
    path/relation/label triple, joined by newlines. Fixed JSON envelope
    fields, links, and id metadata are not part of the budgeted content.
    """
    parts = [summary]
    for item in items:
        parts.append(f"{item.get('title') or ''}\n{item.get('text') or ''}")
    for entry in files or []:
        parts.append(
            f"{entry.get('path') or ''}\n{entry.get('relation') or ''}\n{entry.get('label') or ''}"
        )
    return "\n".join(parts)


def context_content_tokens(
    summary: str,
    items: list[dict[str, Any]],
    files: list[dict[str, Any]] | None = None,
) -> int:
    return count_tokens(context_content_text(summary, items, files))
