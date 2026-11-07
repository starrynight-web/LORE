# Claude Desktop

Config: `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS), `%APPDATA%\Claude\claude_desktop_config.json` (Windows), or `~/.config/Claude/claude_desktop_config.json` (Linux).

Prefer `uvx lore-solo connect`, which writes this entry when Claude Desktop’s config folder exists.

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

Quit Claude Desktop completely (including the tray icon) after editing the file, then reopen. Coding tools: `get_context`, `map_codebase`, `check_applied`, `log_decision`.
