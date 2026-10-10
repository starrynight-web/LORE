# Google Antigravity

Add Lore to the global config, `~/.gemini/config/mcp_config.json` (Settings → Customizations → Installed MCP Servers → **Open MCP Config**). In our test, Antigravity ignored the workspace file `.agents/mcp_config.json`, although it did load the workspace rules. Keep any servers already in the file, and add `lore` next to them:

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

Use absolute paths: the global file applies to every project, so `--root` must name the project explicitly. `examples/demo-app/.agents/mcp_config.json` is kept in case a later Antigravity build reads workspace configs.

Antigravity shares one token budget between rules, skills and MCP tools. When it's over budget (Customizations shows a warning), it drops large customizations, and that can include Lore's tools. Disable unused skills or MCP servers until the Mcp Tools breakdown lists `lore` with nothing excluded.

Rules: Antigravity loads `AGENTS.md` and `.agents/rules/*.md` (legacy `.agent/rules/` still works). `examples/demo-app/.agents/rules/lore.md` uses `trigger: always_on`.

After editing the config, refresh the MCP Servers panel and check that `lore` lists 12 tools.
