# TASKLIST — Solo approach

Work this list in order. Check a box only when the exit line under it is true. Each phase should leave something you can run before the next phase starts.

**Branch:** `solo` (renamed from `solo-approach`, which started from `dev`).

**What this slice is.** One developer. One persona (a role, such as “frontend engineer”) owns a set of skills. The IDE’s agent calls Lore and receives that persona, a one-line summary of each of its skills, and a short slice of the codebase map. The setup website is optional. The agent works when the website is closed.

Team and Enterprise are later sections on this same Python engine. They are not in this list.

## Current shape

The phases below are the build record. A few of their lines describe an earlier setup site. The running program matches this section and [HOW_IT_WORKS.md](HOW_IT_WORKS.md). The page layout is in [UI.md](UI.md).

- `lore-solo install` puts the command on this computer. `lore-solo setup` prints `http://127.0.0.1:3000/?key=...` and serves until Ctrl+C. `lore-solo uninstall` removes the command and leaves personas, skills, and editor registrations in place. The editor starts `lore-solo mcp` as a local process. Docker is not used. There is no LAN address. `uvx lore-solo install` and `uvx lore-solo setup` are the same commands on macOS, Linux, and Windows.
- Personas live in the operating system’s application-data folder, or in a project that already has `.lore`. The site does not ask you to pick a folder.
- Setup is four steps: a provider key, skills, a persona, then adding Lore to an editor. The codebase map is the Codebase page.
- Settings lists models from the saved provider. Drafts use the model saved there. Defaults until then: Groq `llama-3.3-70b-versatile`, OpenRouter `openai/gpt-4o-mini`, Gemini `gemini-2.5-flash`, OpenAI `gpt-4o-mini`, Anthropic `claude-haiku-4-5`.
- The site uses the shadcn dashboard shell (inset sidebar, header, cards). `docs/new/` stays on this computer and is not part of the published tree.
- A desktop window around the setup site is possible later. `lore mcp` stays the process the editor starts. That window has not been built.

## Words

- **Persona.** A markdown role file. Calling it returns only the skills filed under it.
- **Skill.** A short instruction pack that belongs to one persona.
- **OKF.** A markdown file with a small YAML header and a body. This is how personas and skills are stored.
- **MCP.** The plug an IDE uses to start a helper program and talk to it as text. The helper is `lore-solo mcp`. It does not use a website.
- **Graphify.** The `graphifyy` library, shipped inside Lore. A button runs it. It leaves a map of the code in the project folder. `lore mcp` only reads that map.
- **Draft / stable.** New personas and skills are drafts. The agent does not receive a draft. Approve flips the file to `stable`.
- **Token budget.** A size cap. 800 tokens is about a page. At most 8 items. `get_context` returns summaries, not full skill text, so this cap stays enough.

## Already done

- [x] **0.1** Deleted the local `demo` branch (`6c739bb`). That branch held the three-mode judge site, the Supabase schema, and the TypeScript MCP.
- [x] **0.2** Removed leftover `demo/` install folders (`node_modules`, `.next`, local env) that Git did not track.
- [x] **0.3** Created `solo-approach` from `dev`. Phase 6 later removed the Go engine and `examples/demo-app`. Untracked notes in `docs/new/` stay.

**Exit:** `git branch` shows `solo`. It does not show `demo`. There is no `demo/` directory.

---

## Phase 1 — File core and the example pack

The agent’s data is files. No database. No web server in this phase.

- [x] **1.1** Add a root `pyproject.toml` for the `lore` package (Python 3.11+). Dependencies for this phase: PyYAML, pytest, ruff, mypy. Do not add Django or Graphify yet.
- [x] **1.2** Create the package layout:

```text
lore/
  __init__.py
  __main__.py          # later: `python -m lore`
  core/
    __init__.py
    okf.py             # read and write one markdown file with a YAML header
    paths.py           # walk up from a start folder until `.lore/` is found
    personas.py        # list, read, write personas and their skills
    decisions.py       # read and write decisions/dec-NNNN.md
    budget.py          # count tokens, stop at 800 and 8 items
lore/py.typed
examples/persona-pack/
```

- [x] **1.3** `okf.py` reads a file whose first block is `---` YAML `---`, and returns the header plus the body. Writing a file round-trips the same text. Unknown header keys are kept, not dropped.
- [x] **1.4** Persona file shape, written by tests and later by the website:

```yaml
type: persona
id: persona:frontend-engineer
title: Frontend engineer
status: draft          # or stable
summary: One line the agent sees first.
skill_ids:
  - skill:frontend-engineer/react-practices@v1
```

Skill file shape:

```yaml
type: skill
id: skill:frontend-engineer/react-practices@v1
title: React practices
persona: persona:frontend-engineer
status: draft
summary: One line. This is what get_context returns.
```

The body under the header is the full steps. `get_context` does not return the body.

- [x] **1.5** A skill is served only when `status` is `stable`, `persona` matches the persona id, and the file lives in `skills/<persona-name>/`. A mismatch stays on disk and is treated as a draft.
- [x] **1.6** `examples/persona-pack/` contains:
  - `.lore/lore.config.yaml` with `token_budget: 800` and `max_items: 8`
  - `.lore/personas/frontend-engineer.md` (`stable`, summary, two skill ids)
  - `.lore/skills/frontend-engineer/react-practices@v1.md` (`stable`, one-line summary, a body longer than a few lines)
  - `.lore/skills/frontend-engineer/tailwind-rules@v1.md` (`stable`)
  - `.lore/personas/backend-engineer.md` (`stable`) and one skill under it, so tests can prove it is not returned for the frontend persona
  - `.lore/personas/draft-persona.md` (`draft`) with one skill
  - a few source files (`src/ui/Button.tsx`, `src/ui/theme.ts`) so a later graph fixture has real paths
- [x] **1.7** `paths.py` finds `.lore/` by walking parents. It fails with a clear error when none exists.
- [x] **1.8** Tests in `lore/core/tests/` with no server process:
  - round-trip a persona file
  - list only stable skills for `frontend-engineer`
  - backend skill is absent from that list
  - mismatched `persona` field is not served
  - missing `.lore/` raises the clear error

**Exit:** `pytest lore/core/tests` passes. `examples/persona-pack` is valid input. No port is opened.

---

## Phase 2 — `get_context` answer

One function builds the answer the agent will see. Still no website and no MCP process.

- [x] **2.1** `lore/core/context.py` implements `get_context(root, persona, intent="", file_path="")`.
- [x] **2.2** It returns the existing envelope shape in `schemas/lore.result.v1.json`:
  - `schema`: `lore.result/1`
  - `tool`: `get_context`
  - `verdict` and `directive` (pairs below)
  - `summary`: one sentence a person can read
  - `items`: persona summary first, then one item per skill (id, title, one-line summary). No skill body.
  - `conflicts` and `violations`: empty lists
  - `budget.limit` 800, `budget.used` the actual count
  - `decision_id`: `dec-0001`, then `dec-0002`, written under `.lore/decisions/`
- [x] **2.3** Verdicts:
  - `ok` / `proceed_and_cite` when the persona is `stable` and at least one skill (or, later, one map node) was returned
  - `abstain` / `ask_user` when the persona exists only as a draft. The summary says to approve it. The draft body is not included.
  - `no_knowledge` / `proceed` when the persona name does not exist
- [x] **2.4** Caps, in this order: include the persona line, then skills in file order, then stop at 8 items or 800 tokens, whichever comes first. A 9th skill is omitted, not truncated mid-sentence. Record the omission in `excluded` or `summary` so the agent knows to call `get_skill` or narrow the persona.
- [x] **2.5** Token count uses a real tokenizer (the same idea as `cl100k_base` in the Go code) or a documented approximation that the tests pin. Do not ship a count of “characters divided by 4” without a test that names the rule.
- [x] **2.6** Every successful or abstain call writes `decisions/dec-NNNN.md` with the persona, the skill ids included, the ids left out, the verdict, and the time. `no_knowledge` writes one too.
- [x] **2.7** Tests against `examples/persona-pack`, copying it to a temp directory so the pack itself is not modified:
  - frontend returns only its two skills, as summaries, and not the backend skill
  - the skill body text is absent from the JSON
  - draft persona returns `abstain` and does not include skill steps
  - unknown persona returns `no_knowledge`
  - a pack with 12 one-line skills returns at most 8 items
  - `budget.used` is never above 800
  - a second call writes `dec-0002`

**Exit:** The temp-directory tests pass with no server running.

---

## Phase 3 — `lore mcp` (the program the IDE starts)

This is the product the agent calls. The setup site does not exist yet. Tests must pass with no website process running.

- [x] **3.1** Add FastMCP. `lore/mcp.py` exposes tools that call `lore.core` only. It does not import Django.
- [x] **3.2** `python -m lore mcp` speaks MCP over stdin/stdout. Cursor’s config will be:

```json
{
  "mcpServers": {
    "lore": {
      "command": "python",
      "args": ["-m", "lore", "mcp"]
    }
  }
}
```

The working directory is the project. The process finds `.lore/` by walking parents. The agent does not pass the project path.

- [x] **3.3** Tools:
  - `get_context(persona, intent?, file_path?)` — Phase 2 function. `file_path` is accepted and ignored until Phase 5.
  - `get_skill(name)` — full markdown body of one stable skill. Refuse a skill that belongs to another persona when `persona` is also passed. Refuse drafts.
  - `list_personas` — id, title, and summary of stable personas only.
  - `ingest(persona, filename, content)` — write a new skill file under that persona as `draft`. Do not serve it.
  - `log_decision(decision_id, outcome, rule_ids?, note?)` — append the outcome to that decision file.
  - `trace(decision_id)` — return the decision file’s contents.
- [x] **3.4** An idempotency key on `ingest` and `log_decision`, stored beside the decision or in `.lore/idempotency.json`. The same key returns the first result instead of writing a second file.
- [x] **3.5** Tests start the MCP handler in-process (FastMCP’s test client, not a live Cursor window) against a temp copy of the persona pack:
  - `get_context` for `frontend-engineer` returns two skill summaries
  - `get_skill` returns the body that `get_context` withheld
  - `list_personas` omits the draft
  - `ingest` creates a draft file that the next `get_context` does not include
  - `trace` reads the decision `get_context` just wrote
  - the test process never binds a TCP port

**Exit:** `python -m lore mcp` stays running in a terminal pointed at `examples/persona-pack` and answers one `get_context` from an MCP inspector. Closing any other program does not matter, because no other program is required.

---

## Phase 4 — Setup site

People who do not want to edit markdown use this. It only writes the same files Phase 3 reads. Closing it must not stop `lore mcp`.

- [x] **4.1** Django project in `lore/setup/`. It listens on `127.0.0.1:7421` only. Next.js in `web/` listens on `0.0.0.0:3000` and forwards `/api` to Django.
- [x] **4.2** `python -m lore setup` starts both, generates a key, and prints:

```text
Lore setup is running.
On this computer: http://127.0.0.1:3000/?key=...
On your network:  http://<lan-ipv4>:3000/?key=...
```

The LAN address is the first IPv4 address that is not `127.0.0.1`. If there is none, print only the local line. The key changes every time the command starts. The files on disk do not.

- [x] **4.3** Requests without the key get a page that says to open the link from the terminal. The key is not required by `lore mcp`.
- [x] **4.4** Routes. Each one calls `lore.core` or writes a file. None of them are on the agent’s path.
  - `GET /api/browse?path=` lists child directories. The path must stay under the user’s home directory.
  - `POST /api/workspace` with a chosen folder creates `.lore/` and `lore.config.yaml` (`token_budget: 800`, `max_items: 8`) if they are missing.
  - `POST /api/workspace/example` copies `examples/persona-pack` personas and skills into that `.lore/`.
  - `POST /api/personas` and `POST /api/personas/<id>/skills` create markdown from form fields (name, summary, steps). New rows are `draft`.
  - `GET /api/personas` and `GET /api/personas/<id>` read the files, including drafts, so the person can approve them.
  - `POST /api/items/<id>/approve` sets `status: stable` in the file.
  - `GET /api/decisions` lists `decisions/*.md`.
  - `POST /api/connect` writes `.cursor/mcp.json` in the chosen project with the command from Phase 3, and returns that JSON for a copy box.
  - `POST /api/settings` writes `token_budget` and `max_items` into `lore.config.yaml`.
- [x] **4.5** Pages in `web/`, light background, near-black text, yellow accent:
  - **Setup.** Shown when no project has been chosen. Four steps: pick folder, add persona and skills (or “Use the frontend example”), map codebase (button disabled until Phase 5), connect the IDE.
  - **Personas.** Cards. Open one to see skills, an add-skill form, and Approve on drafts.
  - **Replay.** Decision files: time, persona, skill ids.
  - **Connect.** The button from `POST /api/connect`, plus the copy box.
  - **Settings.** The two numbers.
- [x] **4.6** A test that does not use a browser: approve a draft through the Django view, stop the Django process, run `get_context` in a new process, and see `ok` with that skill’s summary.

**Exit:** `lore setup` prints a URL. Approving a skill in the browser changes the next `lore mcp` answer after the setup terminal is closed.

---

## Phase 5 — Codebase map

Graphify runs only from the setup site. `lore mcp` only reads the files the button left behind.

- [x] **5.1** Pin `graphifyy` in `pyproject.toml`. The developer does not install it themselves.
- [x] **5.2** `POST /api/graph/build` starts a background job on the chosen project. The job writes `.lore/graph-status.json`:
  - `running`
  - `ready` with the time and `schema_version` from `graph.json`
  - `failed` with a plain-language error
- [x] **5.3** The job calls Graphify in Lore’s own environment and leaves `graphify-out/graph.json` and `graphify-out/graph.html` in the project. If the library only exposes a command, run that command from the same virtualenv. Do not ask the user to run it.
- [x] **5.4** `GET /api/graph` reads the status file and a short list: node, what it links to, and whether the link was read from the code (`EXTRACTED`) or inferred (`INFERRED`).
- [x] **5.5** Codebase page: status line, “Map codebase” / “Update map”, the short list, and the cached `graph.html` embedded from `/graph/view/` on the same site. The developer does not open a file path or a second site.
- [x] **5.6** `lore/core/graph.py` reads `graph.json`:
  - If `file_path` is set, take that file’s node and its direct neighbors (imports and calls).
  - If not, take a few of the most-connected nodes.
  - Unknown `schema_version`, or a missing file, adds no nodes and sets a note: “Map this project”. Skills still return.
- [x] **5.7** `get_context` adds those nodes after skill summaries. Skills and nodes share the 8-item and 800-token cap. Skill summaries win if the cap is tight. The decision file records the node ids included.
- [x] **5.8** Tests use a small checked-in `examples/persona-pack/graphify-out/graph.json` with a handful of nodes. CI does not run a live Graphify build.
  - with the fixture, `file_path=src/ui/Button.tsx` adds that node and a neighbor, and stays inside the cap
  - deleting the fixture still returns the two skill summaries
  - a fixture with a different `schema_version` returns skills and the “Map this project” note
  - the Codebase status file moves from `running` to `ready` in a test that stubs the Graphify call

**Exit:** Map codebase on the site produces `graphify-out/`. After the site is closed, `get_context` with a `file_path` still includes the short map slice.

---

## Phase 6 — Retire the Go engine

Do this only after Phases 1–5 pass. The three-mode `demo` branch is already gone.

- [x] **6.1** Delete `cmd/`, `internal/`, `go.mod`, `go.sum`, and `examples/demo-app/`.
- [x] **6.2** Replace the Go job in `.github/workflows/ci.yml` with `ruff`, `mypy`, and `pytest`.
- [x] **6.3** Rewrite the top of `README.md`: what Lore is for a solo developer, `lore setup`, `lore mcp`, and the persona example. Point the quick start at this engine. Leave a single line that the older architecture docs describe the previous Go design.
- [x] **6.4** Do not rewrite `docs/LORE_ARCHITECTURE.md`, `docs/LORE_OVERVIEW.md`, `docs/PROJECT_CHARTER.md`, or `docs/PROJECT_REQUIREMENTS.md` in this phase. They stay until a later doc pass.
- [x] **6.5** `schemas/lore.result.v1.json` stays. The Python envelope still validates against it.

**Exit:** `go test` is not part of CI. A fresh clone’s README tells you to run the Python commands. `pytest` passes.

---

## Phase 7 — Write down the paid shape, do not build it

- [x] **7.1** Add `docs/solo/HOSTING.md` in a few paragraphs: a later paid host syncs the `.lore/` folder and `graphify-out/`. The laptop folder remains the copy the developer owns. No accounts, no Stripe, no Postgres in this slice.

**Exit:** The note exists. No new service is running.

---

## Done when

- `get_context` with `persona=frontend-engineer` returns that persona and only its stable skill summaries.
- The backend persona’s skill is absent.
- A draft persona returns `abstain` and no skill steps.
- `get_skill` returns the full steps for one skill.
- The answer stays within 8 items and 800 tokens.
- `lore mcp` answers while `lore setup` is stopped.
- `lore setup` prints `http://127.0.0.1:3000/?key=...`. Personas, approval, the codebase map, and editor config happen on that site and only change files.
- After the site is closed, a mapped project still adds a short graph slice.
- A missing map still returns skills.
- The Go engine is deleted and CI runs pytest.

## Not in this list

Shared team rules, pull requests, commit messages. Uploaded enterprise documents, conflict detection, missing-information checks, Slack. Payments. A login beyond the setup key. Rewriting Graphify. A separate graph database. A full rewrite of the old architecture docs.
