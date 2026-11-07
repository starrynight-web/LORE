# VS Code (GitHub Copilot agent mode)

User config (written by connect when VS Code’s user folder exists): `…/Code/User/mcp.json`. VS Code uses `servers`, not `mcpServers`.

```json
{
  "servers": {
    "lore-solo": {
      "type": "stdio",
      "command": "uvx",
      "args": ["lore-solo", "mcp"]
    }
  }
}
```

1. **MCP: List Servers → lore-solo → Start**.
2. Open Copilot Chat in **Agent** mode; confirm coding tools are listed.
3. Connect upserts `.github/copilot-instructions.md` with Lore standing instructions so the agent calls `get_context` before editing, then `check_applied` / `log_decision`.
4. Full surface (`--full`) exposes admin tools that may prompt for confirmation.

Logs: **MCP: List Servers → lore-solo → Show Output**.
