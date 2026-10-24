"""The provider key is stored locally and is not returned."""

from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path
from typing import Self

import pytest
from lore.core.provider import draft_persona, list_models, public_provider, save_provider, set_model


class _Body:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def read(self, _limit: int = -1) -> bytes:
        return self.payload

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def test_saved_key_is_not_in_the_public_record(tmp_path: Path) -> None:
    secret = "groq-test-key-9876"
    shown = save_provider(tmp_path, "groq", secret)
    assert shown == {
        "provider": "groq",
        "configured": True,
        "last4": "9876",
        "model": "llama-3.3-70b-versatile",
    }
    assert secret not in json.dumps(shown)
    assert secret not in json.dumps(public_provider(tmp_path))
    stored = (tmp_path / ".lore" / "provider.json").read_text(encoding="utf-8")
    assert secret in stored
    mode = (tmp_path / ".lore" / "provider.json").stat().st_mode & 0o777
    assert mode == 0o600


def test_draft_sends_the_key_only_to_the_provider(tmp_path: Path) -> None:
    secret = "sk-openai-secret"
    save_provider(tmp_path, "openai", secret)
    seen: dict[str, str] = {}

    def opener(request: object, timeout: int = 30) -> _Body:
        del timeout
        seen["header"] = request.headers["Authorization"]  # type: ignore[attr-defined]
        seen["model"] = json.loads(request.data.decode("utf-8"))["model"]  # type: ignore[attr-defined]
        payload = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "title": "Widget maker",
                                "summary": "Makes widgets.",
                                "rules": "Keep them round.",
                            }
                        )
                    }
                }
            ]
        }
        return _Body(json.dumps(payload).encode("utf-8"))

    drafted = draft_persona(
        tmp_path, [{"title": "Shape", "summary": "Round widgets."}], opener=opener
    )
    assert drafted["title"] == "Widget maker"
    assert seen["header"] == f"Bearer {secret}"
    assert seen["model"] == "gpt-4o-mini"
    assert secret not in json.dumps(drafted)


def test_chosen_model_is_what_the_draft_sends(tmp_path: Path) -> None:
    save_provider(tmp_path, "openai", "sk-openai-secret")
    shown = set_model(tmp_path, "gpt-4.1-mini")
    assert shown["model"] == "gpt-4.1-mini"
    seen: dict[str, str] = {}

    def opener(request: object, timeout: int = 30) -> _Body:
        del timeout
        seen["model"] = json.loads(request.data.decode("utf-8"))["model"]  # type: ignore[attr-defined]
        payload = {
            "choices": [
                {"message": {"content": json.dumps({"title": "A", "summary": "B.", "rules": "C."})}}
            ]
        }
        return _Body(json.dumps(payload).encode("utf-8"))

    draft_persona(tmp_path, [], opener=opener)
    assert seen["model"] == "gpt-4.1-mini"
    assert "sk-openai-secret" not in json.dumps(public_provider(tmp_path))


def test_model_list_uses_the_saved_key(tmp_path: Path) -> None:
    secret = "sk-openai-secret"
    save_provider(tmp_path, "openai", secret)
    seen: dict[str, str] = {}

    def opener(request: object, timeout: int = 30) -> _Body:
        del timeout
        seen["header"] = request.headers["Authorization"]  # type: ignore[attr-defined]
        seen["url"] = request.full_url  # type: ignore[attr-defined]
        payload = {
            "data": [
                {"id": "text-embedding-3-small"},
                {"id": "gpt-4.1-mini"},
                {"id": "gpt-4o-mini"},
            ]
        }
        return _Body(json.dumps(payload).encode("utf-8"))

    listed = list_models(tmp_path, opener=opener)
    assert seen["header"] == f"Bearer {secret}"
    assert seen["url"] == "https://api.openai.com/v1/models"
    assert listed["models"] == ["gpt-4o-mini", "gpt-4.1-mini"]
    assert secret not in json.dumps(listed)


def test_gemini_model_names_drop_the_models_prefix(tmp_path: Path) -> None:
    save_provider(tmp_path, "gemini", "gemini-test-key")

    def opener(request: object, timeout: int = 30) -> _Body:
        del timeout
        del request
        payload = {
            "models": [
                {
                    "name": "models/gemini-2.5-flash",
                    "supportedGenerationMethods": ["generateContent"],
                },
                {
                    "name": "models/text-embedding-004",
                    "supportedGenerationMethods": ["embedContent"],
                },
            ]
        }
        return _Body(json.dumps(payload).encode("utf-8"))

    listed = list_models(tmp_path, opener=opener)
    assert listed["model"] == "gemini-2.5-flash"
    assert listed["models"] == ["gemini-2.5-flash"]


def test_refused_model_list_does_not_include_the_response(tmp_path: Path) -> None:
    save_provider(tmp_path, "openai", "sk-openai-secret")

    def opener(request: object, timeout: int = 30) -> _Body:
        del timeout
        url = request.full_url  # type: ignore[attr-defined]
        raise urllib.error.HTTPError(url, 401, "no", hdrs=None, fp=io.BytesIO(b"sk-openai-secret"))  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="did not accept that key") as exc:
        list_models(tmp_path, opener=opener)
    assert "sk-openai-secret" not in str(exc.value)


def test_unknown_provider_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Choose"):
        save_provider(tmp_path, "local", "long-enough-key")


def test_model_id_must_be_a_single_catalog_id(tmp_path: Path) -> None:
    save_provider(tmp_path, "groq", "groq-test-key-9876")
    with pytest.raises(ValueError, match="model id"):
        set_model(tmp_path, "../llama")
    with pytest.raises(ValueError, match="provider key"):
        set_model(tmp_path / "empty", "llama-3.3-70b-versatile")
