# Lore

[![ci](https://github.com/starrynight-web/LORE/actions/workflows/ci.yml/badge.svg)](https://github.com/starrynight-web/LORE/actions/workflows/ci.yml)

Lore serves a team's governed knowledge (rules, skills, procedures and the conflicts between them) to coding agents over MCP. Before an agent edits a file, it asks Lore what applies. Lore answers with a verdict and a directive (`proceed`, `proceed_and_cite`, `ask_user`, `stop`), cites rule IDs, and refuses to settle contradictions on its own: it raises them to a person. Every answer is recorded as a decision you can trace later.

This repository currently contains the MCP server and its IDE integration. Knowledge lives as plain markdown files in `.lore/`, in the OKF bundle format. The graph database, extraction worker and Jev checker described in [LORE_ARCHITECTURE.md](docs/LORE_ARCHITECTURE.md) will plug in behind the same `Store` interface later.

Status: early prototype, built for the International AI Builders Congress 2026 (InfraSphere AI / Knowledge Grid track). Interfaces may still change.

## Quick start

```bash
go install ./cmd/lore            # installs ~/go/bin/lore
cd /path/to/your/project
lore init --demo                 # .lore/ with sample auth rules, plus IDE config snippets
lore context --file src/auth/token.go --intent "add a refresh token endpoint"
```

The last command shows exactly what an agent would be told: two MUST rules, a skill, and a recorded conflict it must not resolve itself. It exits with code 3, meaning "ask the user".

To connect an IDE, see [docs/ide/](docs/ide/README.md). [`examples/demo-app`](examples/demo-app) is a ready-made workspace with configs for Cursor, VS Code and Antigravity.

## Bring your existing skills

```bash
lore import skills ~/.cursor/skills ~/.agents/skills          # drafts, not served yet
lore stats                                                     # lists drafts
lore promote skill:frontend-design@v1                          # approve one
lore import skills ~/.cursor/skills --stable                   # or approve on import
```

Skills are segmented, never served whole. `get_context` gets a one-line entry per matching skill; `get_skill` returns the section index; `lore://skills/<id>` returns the full text; and `search --unverified` finds individual sections. A skill that applies globally is only served when the task's wording matches it.

## CLI

| Command | What it does |
| --- | --- |
| `lore serve` | MCP server on stdio (started by the IDE) |
| `lore init [--demo]` | create `.lore/` and print IDE config snippets |
| `lore context -f <file> -i <intent>` | what an agent would receive; `--json`, `--agent`, `--diff <file>` |
| `lore search <query> [-u]` | keyword search; `-u` adds unreviewed text |
| `lore conflicts [scope]` | recorded conflicts |
| `lore import skills <dir>...` | import `SKILL.md` folders |
| `lore promote <id>...` | approve drafts (human only; not available over MCP) |
| `lore stats` / `lore trace <dec-id>` | counts and decision provenance |

Every command accepts `--root <project>`; otherwise Lore uses `$LORE_ROOT`, then the nearest parent folder containing `.lore/`.

## MCP surface

- Read tools return `lore.result/1` ([schema](schemas/lore.result.v1.json)) as `structuredContent`, plus a `<lore>` text block and resource links: `get_context`, `check_compliance`, `detect_conflicts`, `get_skill`, `search`, `get_history`, `trace`, `stats`, `ingest_status`.
- Write tools only stage drafts or record outcomes, and take an `idempotency_key`: `ingest`, `update_persona`, `log_decision`.
- Resources: `lore://rules|skills|procedures|sources|conflicts|decisions|schemas/...`
- Prompts: `answer_with_lore`, `validate_change`, `explain_conflict`, `prepare_review_packet`.

Every tool call is appended to `.lore/audit.log`. `get_context` and `check_compliance` also write `.lore/decisions/dec-NNNN.md`.

## Documentation

| Document | Contents |
| --- | --- |
| [docs/LORE_OVERVIEW.md](docs/LORE_OVERVIEW.md) | What Lore is, who it is for, how it works, with diagrams |
| [docs/LORE_ARCHITECTURE.md](docs/LORE_ARCHITECTURE.md) | Target architecture (v2.0) |
| [docs/PROJECT_REQUIREMENTS.md](docs/PROJECT_REQUIREMENTS.md) | Functional and non-functional requirements |
| [docs/PROJECT_CHARTER.md](docs/PROJECT_CHARTER.md) | Scope, milestones, team |
| [docs/ide/](docs/ide/README.md) | IDE setup, smoke test, compatibility matrix |

## Development

```bash
go test ./...
go vet ./...
npx @modelcontextprotocol/inspector go run ./cmd/lore serve --root examples/demo-app
```

Layout: `cmd/lore` (CLI), `internal/mcp` (server), `internal/store/filestore` (retrieval over `.lore/`), `internal/okf` (bundle format), `internal/importer/skills`, `internal/lineage` (decision records), `internal/present` (agent and CLI rendering), `internal/result` + `schemas/` (envelope), `examples/` (demo workspace), `docs/` (design and IDE guides).

## License

[MIT](LICENSE)
