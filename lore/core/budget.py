"""Count tokens for the 800-token answer cap.

The count is cl100k_base when the tiktoken encoder is installed. That is the
same encoding the previous Go engine used. If the encoder cannot be loaded,
the count is one token per three UTF-8 bytes, rounded up. Tests pin both
behaviors by name.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Protocol


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
