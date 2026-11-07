# Cursor

Prefer `uvx lore-solo connect`, which writes `~/.cursor/mcp.json` and `~/.cursor/rules/lore.mdc`.

Project backup (committed): `.cursor/mcp.json`

```json
{
  "mcpServers": {
    "lore-solo": {
      "command": "uvx",
      "args": ["lore-solo", "mcp"]
    }
  }
}
```

After install, `command` may be `~/.lore/bin/lore-solo` with `args: ["mcp"]`. Connect also sets `LORE_WORKSPACE` to the open folder.

1. Open **Settings → MCP** and enable `lore-solo`. The status should list coding tools: `get_context`, `map_codebase`, `check_applied`, `log_decision`.
2. Standing rule (`alwaysApply: true`) tells the agent to run the Lore quality loop without being asked.
3. If the server fails to start, open **Output → MCP Logs**. `LORE_DEBUG=1` in an `env` block turns on debug logs.

Do not register a server key named only `lore` alongside an old Go binary — Antigravity/Cursor schema caches have collided on that name before.
