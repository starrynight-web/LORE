# OpenAI Codex (CLI and IDE extension)

> Config example, not verified.

Codex reads MCP servers from `~/.codex/config.toml`. The CLI and the IDE extension share this file.

```toml
[mcp_servers.lore]
command = "/home/you/go/bin/lore"
args = ["serve", "--root", "/home/you/path/to/project"]
```

Or: `codex mcp add lore -- ~/go/bin/lore serve --root "$PWD"`.

Run `/mcp` in a Codex session to check that `lore` is connected. Codex reads `AGENTS.md` for rules. `lore connect` writes a Lore section into `~/.codex/AGENTS.md`.
