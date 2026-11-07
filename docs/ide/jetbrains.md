# JetBrains (AI Assistant / Junie)

> Config example; verify locally.

Add an MCP server named **`lore-solo`** that starts Solo over stdio:

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

After `uvx lore-solo install`, you can point `command` at `~/.lore/bin/lore-solo` with `args: ["mcp"]`. Prefer project `AGENTS.md` (written by connect) so the agent calls Lore unprompted.
