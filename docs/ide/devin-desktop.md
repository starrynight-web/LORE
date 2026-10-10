# Devin Desktop

> Config example, not verified.

The Devin Local agent reads MCP servers from:

- `.devin/mcp_config.json` in the project (committed)
- `.devin/mcp_config.local.json` (personal, gitignored)
- `~/.config/devin/mcp_config.json` (all projects)

```json
{
  "mcpServers": {
    "lore": {
      "command": "/home/you/go/bin/lore",
      "args": ["serve", "--root", "/home/you/path/to/project"]
    }
  }
}
```

The legacy Cascade agent uses `~/.codeium/windsurf/mcp_config.json` with the same `mcpServers` shape. It supports `${env:VAR}` interpolation, but not `${workspaceFolder}`.

Devin reads `AGENTS.md` for rules.
