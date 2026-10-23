"""HTTP routes that only read and write the project's files."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from django.http import HttpRequest, HttpResponse, JsonResponse

from lore.connect import agent_prompt, install_command, mcp_entry, register_agents
from lore.core.config import load_config, save_config
from lore.core.decisions import list_decisions
from lore.core.graph import summarize
from lore.core.inbox import (
    add_from_registry,
    add_text,
    adopt_inbox,
    list_inbox,
    remove_inbox,
    search_registry,
)
from lore.core.okf import Doc
from lore.core.paths import library_root, project_name, workspace_root
from lore.core.personas import (
    file_slug,
    find_persona,
    list_personas,
    list_skill_files,
    set_status,
    skill_belongs,
    write_persona,
    write_skill,
)
from lore.core.personas import persona_id as make_persona_id
from lore.core.provider import (
    clear_provider,
    draft_persona,
    list_models,
    public_provider,
    save_provider,
    set_model,
)
from lore.core.workspace import copy_example, copy_persona, init_workspace, ready_personas
from lore.setup.graph_job import start_build

_PROJECT: dict[str, str] = {}


class ApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        self.status = status
        self.message = message
        super().__init__(message)


def _api(fn: Callable[..., JsonResponse]) -> Callable[..., JsonResponse]:
    def wrapper(request: HttpRequest, *args: Any, **kwargs: Any) -> JsonResponse:
        try:
            return fn(request, *args, **kwargs)
        except ApiError as exc:
            return JsonResponse({"error": exc.message}, status=exc.status)
        except FileNotFoundError as exc:
            return JsonResponse({"error": str(exc)}, status=404)
        except ValueError as exc:
            return JsonResponse({"error": str(exc)}, status=400)
        except Exception:  # noqa: BLE001 - the browser must receive JSON, not an HTML error page
            return JsonResponse({"error": "The setup site could not complete that."}, status=500)

    return wrapper


def _json(request: HttpRequest) -> dict[str, Any]:
    if not request.body:
        return {}
    try:
        loaded = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ApiError(400, "Expected a JSON object.") from exc
    if not isinstance(loaded, dict):
        raise ApiError(400, "Expected a JSON object.")
    return loaded


def _roots() -> list[Path]:
    roots = [workspace_root().expanduser().resolve()]
    library = library_root().expanduser().resolve()
    if library not in roots:
        roots.append(library)
    return roots


def _allowed(raw: str) -> Path:
    try:
        resolved = Path(raw).expanduser().resolve()
    except OSError as exc:
        raise ApiError(400, "That folder cannot be opened.") from exc
    for root in _roots():
        if resolved == root or root in resolved.parents:
            return resolved
    raise ApiError(400, "That folder is outside this project.")


def _remember(project: Path) -> None:
    _PROJECT["path"] = str(project)


def _ensure_store() -> dict[str, Any]:
    workspace = workspace_root().expanduser().resolve()
    name = project_name()
    if (workspace / ".lore").is_dir():
        _remember(workspace)
        return {"project": str(workspace), "name": name, "keeps_own": True}
    library = library_root().expanduser().resolve()
    init_workspace(library)
    _remember(library)
    return {"project": str(library), "name": name, "keeps_own": False}


def _project(request: HttpRequest) -> Path:
    raw = request.headers.get("X-Lore-Project") or _PROJECT.get("path")
    if not raw:
        return Path(_ensure_store()["project"])
    project = _allowed(raw)
    if not (project / ".lore").is_dir():
        raise ApiError(400, "That folder has no .lore directory.")
    _remember(project)
    return project


def _persona_payload(doc: Doc) -> dict[str, Any]:
    skill_ids = doc.header.get("skill_ids")
    return {
        "id": doc.get("id"),
        "title": doc.get("title"),
        "summary": doc.get("summary"),
        "status": doc.get("status"),
        "body": doc.body,
        "skill_ids": skill_ids if isinstance(skill_ids, list) else [],
    }


@_api
def health(_request: HttpRequest) -> JsonResponse:
    return JsonResponse({"ok": True})


@_api
def browse(request: HttpRequest) -> JsonResponse:
    raw = request.GET.get("path") or str(workspace_root())
    folder = _allowed(raw)
    if not folder.is_dir():
        raise ApiError(400, "That path is not a folder.")
    children = []
    try:
        entries = sorted(folder.iterdir(), key=lambda item: item.name.lower())
    except OSError as exc:
        raise ApiError(400, "That folder cannot be opened.") from exc
    for child in entries:
        if child.is_dir() and not child.name.startswith("."):
            children.append({"name": child.name, "path": str(child)})
    parent = ""
    for root in _roots():
        if folder != root and root in folder.parents:
            parent = str(folder.parent)
            break
    return JsonResponse({"path": str(folder), "parent": parent, "children": children})


@_api
def workspace(request: HttpRequest) -> JsonResponse:
    if request.method == "GET":
        return JsonResponse(_ensure_store())
    if request.method != "POST":
        raise ApiError(405, "Use POST to choose a folder.")
    payload = _json(request)
    folder = _allowed(str(payload.get("path", "")))
    if not folder.exists():
        folder.mkdir(parents=True)
    if not folder.is_dir():
        raise ApiError(400, "That path is not a folder.")
    init_workspace(folder)
    _remember(folder)
    return JsonResponse({"project": str(folder), "name": project_name(), "keeps_own": True})


@_api
def catalog(request: HttpRequest) -> JsonResponse:
    if request.method != "GET":
        raise ApiError(405, "Use GET to list starters.")
    return JsonResponse({"personas": ready_personas()})


@_api
def catalog_add(request: HttpRequest, persona_id: str) -> JsonResponse:
    if request.method != "POST":
        raise ApiError(405, "Use POST to add a starter.")
    project = _project(request)
    try:
        doc_id = copy_persona(project, persona_id)
    except FileNotFoundError as exc:
        raise ApiError(404, "That starter does not exist.") from exc
    return JsonResponse({"id": doc_id, "status": "stable"})


@_api
def workspace_example(request: HttpRequest) -> JsonResponse:
    if request.method != "POST":
        raise ApiError(405, "Use POST to copy the example.")
    project = _project(request)
    copy_example(project)
    return JsonResponse({"project": str(project), "copied": "examples/persona-pack"})


@_api
def personas(request: HttpRequest) -> JsonResponse:
    project = _project(request)
    if request.method == "POST":
        payload = _json(request)
        name = str(payload.get("name", "")).strip()
        if not name:
            raise ApiError(400, "A persona needs a name.")
        doc = write_persona(
            project,
            name,
            summary=str(payload.get("summary", "")),
            body=str(payload.get("steps", "") or payload.get("rules", "")),
            title=str(payload.get("title", "") or name),
            status="draft",
        )
        if payload.get("adopt"):
            adopt_inbox(project, doc.get("id"))
            saved = find_persona(project, doc.get("id"))
            if saved is not None:
                doc = saved
        return JsonResponse(_persona_payload(doc), status=201)
    if request.method != "GET":
        raise ApiError(405, "Use GET or POST for personas.")
    return JsonResponse({"personas": [_persona_payload(doc) for doc in list_personas(project)]})


@_api
def persona_detail(request: HttpRequest, persona_id: str) -> JsonResponse:
    if request.method != "GET":
        raise ApiError(405, "Use GET to read a persona.")
    project = _project(request)
    doc = find_persona(project, persona_id)
    if doc is None:
        raise ApiError(404, f"No persona {persona_id}.")
    skills = []
    for path, skill in list_skill_files(project):
        if skill_belongs(path, skill, doc.get("id")):
            skills.append(
                {
                    "id": skill.get("id"),
                    "title": skill.get("title"),
                    "summary": skill.get("summary"),
                    "status": skill.get("status"),
                    "body": skill.body,
                }
            )
    payload = _persona_payload(doc)
    payload["skills"] = skills
    return JsonResponse(payload)


@_api
def persona_skills(request: HttpRequest, persona_id: str) -> JsonResponse:
    if request.method != "POST":
        raise ApiError(405, "Use POST to add a skill.")
    project = _project(request)
    if find_persona(project, persona_id) is None:
        raise ApiError(404, f"No persona {persona_id}.")
    payload = _json(request)
    name = str(payload.get("name", "")).strip()
    if not name:
        raise ApiError(400, "A skill needs a name.")
    filename = file_slug(name)
    doc = write_skill(
        project,
        make_persona_id(persona_id),
        filename,
        title=str(payload.get("title", "") or name),
        summary=str(payload.get("summary", "")),
        body=str(payload.get("steps", "")),
        status="draft",
    )
    return JsonResponse(
        {
            "id": doc.get("id"),
            "title": doc.get("title"),
            "summary": doc.get("summary"),
            "status": doc.get("status"),
        },
        status=201,
    )


@_api
def approve(request: HttpRequest, item_id: str) -> JsonResponse:
    if request.method != "POST":
        raise ApiError(405, "Use POST to approve.")
    project = _project(request)
    doc = set_status(project, item_id, "stable")
    return JsonResponse({"id": doc.get("id"), "status": doc.get("status")})


@_api
def provider(request: HttpRequest) -> JsonResponse:
    library = library_root()
    if request.method == "GET":
        return JsonResponse(public_provider(library))
    if request.method == "DELETE":
        clear_provider(library)
        return JsonResponse(public_provider(library))
    if request.method != "POST":
        raise ApiError(405, "Use GET or POST for the provider key.")
    payload = _json(request)
    saved = save_provider(library, str(payload.get("provider", "")), str(payload.get("key", "")))
    return JsonResponse(saved)


@_api
def provider_models(request: HttpRequest) -> JsonResponse:
    library = library_root()
    if request.method == "GET":
        return JsonResponse(list_models(library))
    if request.method != "POST":
        raise ApiError(405, "Use GET or POST for the model list.")
    payload = _json(request)
    return JsonResponse(set_model(library, str(payload.get("model", ""))))


@_api
def provider_draft(request: HttpRequest) -> JsonResponse:
    if request.method != "POST":
        raise ApiError(405, "Use POST to draft a persona.")
    payload = _json(request)
    skills = list_inbox(_project(request))
    drafted = draft_persona(library_root(), skills, str(payload.get("note", "")))
    return JsonResponse(drafted)


@_api
def inbox(request: HttpRequest) -> JsonResponse:
    project = _project(request)
    if request.method == "GET":
        return JsonResponse({"skills": list_inbox(project)})
    if request.method != "POST":
        raise ApiError(405, "Use GET or POST for skills.")
    payload = _json(request)
    content = str(payload.get("content", ""))
    if not content.strip():
        raise ApiError(400, "Choose a skill file.")
    saved = add_text(project, str(payload.get("name", "")), content)
    return JsonResponse(saved, status=201)


@_api
def inbox_remove(request: HttpRequest, skill_id: str) -> JsonResponse:
    if request.method != "DELETE":
        raise ApiError(405, "Use DELETE to remove a waiting skill.")
    remove_inbox(_project(request), skill_id)
    return JsonResponse({"removed": skill_id})


@_api
def skill_search(request: HttpRequest) -> JsonResponse:
    if request.method != "POST":
        raise ApiError(405, "Use POST to search skills.")
    payload = _json(request)
    return JsonResponse({"skills": search_registry(str(payload.get("query", "")))})


@_api
def skill_add(request: HttpRequest) -> JsonResponse:
    if request.method != "POST":
        raise ApiError(405, "Use POST to add a skill.")
    payload = _json(request)
    saved = add_from_registry(
        _project(request),
        str(payload.get("source", "")),
        str(payload.get("skill_id", "")),
    )
    return JsonResponse(saved, status=201)


@_api
def decisions(request: HttpRequest) -> JsonResponse:
    if request.method != "GET":
        raise ApiError(405, "Use GET to list decisions.")
    project = _project(request)
    rows = []
    for doc in list_decisions(project):
        included = doc.header.get("included")
        rows.append(
            {
                "id": doc.get("id"),
                "time": doc.get("time"),
                "persona": doc.get("persona"),
                "verdict": doc.get("verdict"),
                "included": included if isinstance(included, list) else [],
                "summary": doc.body.strip(),
            }
        )
    return JsonResponse({"decisions": rows})


@_api
def connect(request: HttpRequest) -> JsonResponse:
    if request.method == "GET":
        command = install_command()
        return JsonResponse({"command": command, "prompt": agent_prompt(command)})
    if request.method != "POST":
        raise ApiError(405, "Use POST to write the IDE config.")
    project = _project(request)
    cursor = project / ".cursor"
    cursor.mkdir(parents=True, exist_ok=True)
    path = cursor / "mcp.json"
    data: dict[str, Any] = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            loaded = {}
        if isinstance(loaded, dict):
            data = loaded
    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}
    servers["lore"] = mcp_entry("cursor")
    data["mcpServers"] = servers
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return JsonResponse(data)


@_api
def connect_agents(request: HttpRequest) -> JsonResponse:
    if request.method != "POST":
        raise ApiError(405, "Use POST to register Lore with installed agents.")
    return JsonResponse(register_agents())


@_api
def settings_view(request: HttpRequest) -> JsonResponse:
    project = _project(request)
    lore = project / ".lore"
    if request.method == "GET":
        return JsonResponse(load_config(lore))
    if request.method != "POST":
        raise ApiError(405, "Use POST to save settings.")
    payload = _json(request)
    try:
        budget = int(payload["token_budget"])
        items = int(payload["max_items"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ApiError(400, "token_budget and max_items must be whole numbers.") from exc
    saved = save_config(lore, budget, items)
    return JsonResponse(saved)


@_api
def graph_build(request: HttpRequest) -> JsonResponse:
    if request.method != "POST":
        raise ApiError(405, "Use POST to map the codebase.")
    project = _project(request)
    return JsonResponse(start_build(project), status=202)


@_api
def graph(request: HttpRequest) -> JsonResponse:
    if request.method != "GET":
        raise ApiError(405, "Use GET to read the map.")
    return JsonResponse(summarize(_project(request)))


def graph_page(request: HttpRequest) -> HttpResponse:
    try:
        project = _project(request)
    except ApiError as exc:
        return JsonResponse({"error": exc.message}, status=exc.status)
    html = project / "graphify-out" / "graph.html"
    if not html.is_file():
        return HttpResponse("Map this project.", status=404)
    return HttpResponse(html.read_text(encoding="utf-8"), content_type="text/html")

