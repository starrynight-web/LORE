# OpenAI Codex (CLI and IDE extension)

Codex reads MCP servers from `~/.codex/config.toml`. Prefer `uvx lore-solo connect`, which writes a quoted Solo server block and upserts `~/.codex/AGENTS.md`.

```toml
[mcp_servers."lore-solo"]
command = "uvx"
args = ["lore-solo", "mcp"]
```

Or after install: `command = "/home/you/.lore/bin/lore-solo"` with `args = ["mcp"]`.

Run `/mcp` in a Codex session to confirm `lore-solo` is connected. Standing instructions in `AGENTS.md` describe the coding loop (`get_context` → edit → `check_applied` → `log_decision`).
