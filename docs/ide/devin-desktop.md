# Devin Desktop

Devin Local reads MCP servers from:

- `.devin/mcp_config.json` in the project (committed)
- `.devin/mcp_config.local.json` (personal, gitignored)
- `~/.config/devin/mcp_config.json` (all projects; macOS/Windows paths differ)

```json
{
  "mcpServers": {
    "lore-solo": {
      "command": "uvx",
      "args": ["lore-solo", "mcp"],
      "env": {
        "LORE_CLIENT": "Devin",
        "LORE_WORKSPACE": "/home/you/path/to/project"
      }
    }
  }
}
```

`lore-solo connect` writes the project `.devin/mcp_config.json` when `.devin/` exists or a global Devin config directory is present, and upserts project `AGENTS.md` with Lore standing instructions.

Devin reads `AGENTS.md` for rules. Use the Solo coding surface (`get_context`, `map_codebase`, `check_applied`, `log_decision`). The Go `lore serve` binary is deprecated and removed.

The legacy Cascade / Windsurf agent may still use `~/.codeium/windsurf/mcp_config.json` with the same `mcpServers` shape.
