# Claude Code

Prefer `uvx lore-solo connect`, which updates `~/.claude.json` (or the Claude Desktop-style config) and upserts `~/.claude/CLAUDE.md`.

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

Or: `claude mcp add lore-solo -- uvx lore-solo mcp`.

Standing instructions in `CLAUDE.md` describe the coding loop. Default surface is four coding tools; use `lore-solo mcp --full` for admin tools.
