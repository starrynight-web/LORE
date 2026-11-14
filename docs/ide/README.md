# Connecting Lore Solo to your IDE

Lore Solo runs as a local MCP server over stdio. The IDE starts `lore-solo mcp` (working directory = open project, or `LORE_WORKSPACE`). Nothing listens on a port.

Server display name: **`lore-solo`** (avoids colliding with older Go `lore` and Enterprise `lore-enterprise-mcp`).

## Before you start

1. Install: `uvx --managed-python --python 3.12 --no-build lore-solo==0.2.2 install` (optional map extra; see GitHub #2 / Graphify native build).
2. Register editors: `uvx lore-solo connect` — writes MCP configs + standing rules.
3. Or from a clone of the `solo` branch: `./scripts/lore-solo install` then `connect`.

Default **coding** tools: `get_context`, `map_codebase`, `check_applied`, `log_decision`. Admin tools: `lore-solo mcp --full`.

Product promise and loop: [../solo/QUALITY_PLAN.md](../solo/QUALITY_PLAN.md).

## Clients

| Client | Page | Notes |
| --- | --- | --- |
| Cursor | [cursor.md](cursor.md) | `~/.cursor/mcp.json` + `rules/lore.mdc` |
| VS Code (Copilot agent) | [vscode.md](vscode.md) | user `mcp.json` + `.github/copilot-instructions.md` |
| Google Antigravity | [antigravity.md](antigravity.md) | global Gemini MCP; project `AGENTS.md` / `.agents/rules` |
| Claude Desktop / Code | [claude-desktop.md](claude-desktop.md), [claude-code.md](claude-code.md) | update command to `lore-solo mcp` |
| Devin Desktop | [devin-desktop.md](devin-desktop.md) | `.devin/mcp_config.json` + `AGENTS.md` |
| OpenAI Codex | [codex.md](codex.md) | `[mcp_servers."lore-solo"]` + `AGENTS.md` |
| JetBrains / Zed | [jetbrains.md](jetbrains.md), [zed.md](zed.md) | same MCP shape; verify locally |

Older Go-era smoke notes: [compat-matrix.md](compat-matrix.md), [smoke-test.md](smoke-test.md) — treat as historical until re-run on Solo.

## Making agents call Lore on their own

Connect writes standing instructions from `STANDING_INSTRUCTIONS` into:

- `AGENTS.md` (project + Codex home)
- `.cursor/rules/lore.mdc`
- `.github/copilot-instructions.md` (when VS Code is present)
- `.agents/rules/lore.md` (Antigravity always_on)
- Claude `CLAUDE.md`
