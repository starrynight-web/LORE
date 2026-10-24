"""A provider key used only to draft a persona.

The key is stored in the persona library, not in the project. Responses never
include it. The model is chosen on the settings page and stored beside the key.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

PROVIDERS = ("groq", "openrouter", "gemini", "openai", "anthropic")

_MODELS = {
    "groq": "llama-3.3-70b-versatile",
    "openrouter": "openai/gpt-4o-mini",
    "gemini": "gemini-2.5-flash",
    "openai": "gpt-4o-mini",
    "anthropic": "claude-haiku-4-5",
}

_LIST_URLS = {
    "groq": "https://api.groq.com/openai/v1/models",
    "openrouter": "https://openrouter.ai/api/v1/models",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/models",
    "openai": "https://api.openai.com/v1/models",
    "anthropic": "https://api.anthropic.com/v1/models",
}

_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,96}(?:/[A-Za-z0-9][A-Za-z0-9._:-]{0,96})?$")
_SKIP = ("embed", "whisper", "tts", "dall-e", "moderation", "transcri", "image")

_HOSTS = {
    "groq": "api.groq.com",
    "openrouter": "openrouter.ai",
    "gemini": "generativelanguage.googleapis.com",
    "openai": "api.openai.com",
    "anthropic": "api.anthropic.com",
}

Opener = Callable[..., Any]


def provider_path(library: Path) -> Path:
    return library / ".lore" / "provider.json"


def save_provider(library: Path, provider: str, key: str) -> dict[str, str | bool]:
    chosen = provider.strip().lower()
    if chosen not in PROVIDERS:
        raise ValueError("Choose groq, openrouter, gemini, openai, or anthropic.")
    secret = key.strip()
    if len(secret) < 8:
        raise ValueError("That key is too short.")
    previous = _read(library)
    model = previous[2] if previous is not None and previous[0] == chosen else _MODELS[chosen]
    _write(library, chosen, secret, model)
    return _public(chosen, secret, model)


def set_model(library: Path, model: str) -> dict[str, str | bool]:
    """Remember which model drafts use. The key already on disk stays there."""
    loaded = _read(library)
    if loaded is None:
        raise ValueError("Save a provider key before choosing a model.")
    provider, key, _current = loaded
    chosen = model.strip()
    if not _valid_model(chosen):
        raise ValueError("Choose a model id from the list.")
    _write(library, provider, key, chosen)
    return _public(provider, key, chosen)


def list_models(library: Path, opener: Opener | None = None) -> dict[str, Any]:
    """Models this saved key can call. The current choice is first."""
    loaded = _read(library)
    if loaded is None:
        raise ValueError("Save a provider key before choosing a model.")
    provider, key, model = loaded
    found = _fetch_model_ids(provider, key, opener or urllib.request.urlopen)
    return {"provider": provider, "model": model, "models": _present(model, found)}


def clear_provider(library: Path) -> None:
    path = provider_path(library)
    if path.is_file():
        path.unlink()


def public_provider(library: Path) -> dict[str, str | bool]:
    loaded = _read(library)
    if loaded is None:
        return {"provider": "", "configured": False, "last4": "", "model": ""}
    return _public(loaded[0], loaded[1], loaded[2])


def draft_persona(
    library: Path,
    skills: list[dict[str, str]],
    note: str = "",
    opener: Opener | None = None,
) -> dict[str, str]:
    """Ask the saved provider for a persona title, summary, and ruleset."""
    loaded = _read(library)
    if loaded is None:
        raise ValueError("Save a provider key before drafting a persona.")
    provider, key, model = loaded
    lines = [f"- {row.get('title', '')}: {row.get('summary', '')}".strip() for row in skills]
    user = "Skills:\n" + ("\n".join(lines) if lines else "(none yet)")
    if note.strip():
        user += "\n\nNote from the person:\n" + note.strip()
    system = (
        "Write a persona for a coding agent. The persona is a ruleset for the skills listed. "
        "Return only a JSON object with keys title, summary, and rules. "
        "summary is one sentence. rules is the instruction the agent should follow."
    )
    raw = _complete(provider, key, model, system, user, opener or urllib.request.urlopen)
    parsed = _json_object(raw)
    title = str(parsed.get("title", "")).strip()
    summary = str(parsed.get("summary", "")).strip()
    rules = str(parsed.get("rules", "")).strip()
    if not title or not rules:
        raise ValueError("The provider did not return a persona.")
    return {"title": title, "summary": summary, "rules": rules}


def _public(provider: str, key: str, model: str) -> dict[str, str | bool]:
    return {"provider": provider, "configured": True, "last4": key[-4:], "model": model}


def _write(library: Path, provider: str, key: str, model: str) -> None:
    path = provider_path(library)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"provider": provider, "key": key, "model": model}) + "\n",
        encoding="utf-8",
    )
    os.chmod(path, 0o600)


def _read(library: Path) -> tuple[str, str, str] | None:
    path = provider_path(library)
    if not path.is_file():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(loaded, dict):
        return None
    provider = str(loaded.get("provider", "")).lower()
    key = str(loaded.get("key", "")).strip()
    if provider not in PROVIDERS or len(key) < 8:
        return None
    raw_model = str(loaded.get("model", "")).strip()
    model = raw_model if _valid_model(raw_model) else _MODELS[provider]
    return provider, key, model


def _complete(provider: str, key: str, model: str, system: str, user: str, opener: Opener) -> str:
    if provider == "anthropic":
        url = "https://api.anthropic.com/v1/messages"
        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": 1200,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
    elif provider == "gemini":
        quoted = urllib.parse.quote(model, safe="")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{quoted}:generateContent"
        payload = {"contents": [{"parts": [{"text": system + "\n\n" + user}]}]}
    else:
        if provider == "groq":
            url = "https://api.groq.com/openai/v1/chat/completions"
        elif provider == "openrouter":
            url = "https://openrouter.ai/api/v1/chat/completions"
        else:
            url = "https://api.openai.com/v1/chat/completions"
        payload = {
            "model": model,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
    headers = _auth_headers(provider, key)
    if urllib.parse.urlparse(url).hostname != _HOSTS[provider]:
        raise ValueError("The provider could not be reached.")
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with opener(request, timeout=30) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ValueError(_safe(detail or "The provider refused the request.", key)) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ValueError("The provider could not be reached.") from exc
    text = _message_text(provider, body, key)
    return text


def _message_text(provider: str, body: bytes, key: str) -> str:
    try:
        loaded = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("The provider returned an unreadable answer.") from exc
    if not isinstance(loaded, dict):
        raise ValueError("The provider returned an unreadable answer.")  # noqa: TRY004
    if provider == "anthropic":
        blocks = loaded.get("content")
        if isinstance(blocks, list) and blocks and isinstance(blocks[0], dict):
            return str(blocks[0].get("text", ""))
    elif provider == "gemini":
        candidates = loaded.get("candidates")
        if isinstance(candidates, list) and candidates and isinstance(candidates[0], dict):
            content = candidates[0].get("content")
            if isinstance(content, dict):
                parts = content.get("parts")
                if isinstance(parts, list) and parts and isinstance(parts[0], dict):
                    return str(parts[0].get("text", ""))
    else:
        choices = loaded.get("choices")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            message = choices[0].get("message")
            if isinstance(message, dict):
                return str(message.get("content", ""))
    raise ValueError(_safe("The provider returned an unreadable answer.", key))


def _json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        cleaned = cleaned.rsplit("```", 1)[0]
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("The provider did not return a persona.")
    try:
        loaded = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError("The provider did not return a persona.") from exc
    if not isinstance(loaded, dict):
        raise ValueError("The provider did not return a persona.")  # noqa: TRY004
    return loaded


def _safe(message: str, key: str) -> str:
    redacted = message.replace(key, "…") if key else message
    return redacted[:400]


def _valid_model(model: str) -> bool:
    return ".." not in model and _MODEL.fullmatch(model) is not None


def _auth_headers(provider: str, key: str) -> dict[str, str]:
    if provider == "anthropic":
        headers = {
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
    elif provider == "gemini":
        headers = {"x-goog-api-key": key, "content-type": "application/json"}
    else:
        headers = {"Authorization": f"Bearer {key}", "content-type": "application/json"}
    headers["User-Agent"] = "Lore"
    return headers


def _fetch_model_ids(provider: str, key: str, opener: Opener) -> list[str]:
    url: str | None = _LIST_URLS[provider]
    found: list[str] = []
    for _page in range(4):
        if url is None:
            break
        if urllib.parse.urlparse(url).hostname != _HOSTS[provider]:
            raise ValueError("The provider could not be reached.")
        loaded = _get_json(url, provider, key, opener)
        found.extend(_ids_in(provider, loaded))
        url = _next_url(provider, url, loaded)
    return found


def _get_json(url: str, provider: str, key: str, opener: Opener) -> dict[str, Any]:
    request = urllib.request.Request(url, headers=_auth_headers(provider, key), method="GET")
    try:
        with opener(request, timeout=30) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        _ = exc.read()
        if exc.code in {401, 403}:
            raise ValueError("The provider did not accept that key.") from exc
        raise ValueError(
            "The provider did not share its model list. The usual model stays selected."
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ValueError("The provider could not be reached.") from exc
    payload = raw if isinstance(raw, bytes) else bytes(raw)
    try:
        loaded = json.loads(payload.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("The provider returned an unreadable answer.") from exc
    if not isinstance(loaded, dict):
        raise ValueError("The provider returned an unreadable answer.")  # noqa: TRY004
    return loaded


def _ids_in(provider: str, loaded: dict[str, Any]) -> list[str]:
    rows = loaded.get("models") if provider == "gemini" else loaded.get("data")
    if not isinstance(rows, list):
        return []
    ids: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if provider == "gemini":
            methods = row.get("supportedGenerationMethods")
            if isinstance(methods, list) and methods and "generateContent" not in methods:
                continue
            name = str(row.get("name", ""))
            if name.startswith("models/"):
                name = name.removeprefix("models/")
            ids.append(name)
        else:
            ids.append(str(row.get("id", "")))
    return ids


def _next_url(provider: str, url: str, loaded: dict[str, Any]) -> str | None:
    base = url.split("?", 1)[0]
    if provider == "gemini":
        token = str(loaded.get("nextPageToken", "")).strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", token):
            return None
        return f"{base}?pageToken={urllib.parse.quote(token)}"
    if loaded.get("has_more") is not True:
        return None
    last = str(loaded.get("last_id", "")).strip()
    if not _valid_model(last):
        return None
    return f"{base}?after_id={urllib.parse.quote(last)}"


def _present(current: str, found: list[str]) -> list[str]:
    usable = [item for item in found if _chat_model(item)]
    pool = usable or [item for item in found if _valid_model(item)]
    ordered = sorted(set(pool), key=str.lower)
    if current in ordered:
        ordered.remove(current)
    ordered.insert(0, current)
    return ordered[:250]


def _chat_model(model: str) -> bool:
    lowered = model.lower()
    return _valid_model(model) and not any(part in lowered for part in _SKIP)
