# JetBrains IDEs (AI Assistant and Junie)

> Config example, not verified.

**AI Assistant:** **Settings → Tools → AI Assistant → Model Context Protocol (MCP) → Add**, choose **As JSON**, and paste:

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

**Junie:** **Settings → Tools → Junie → MCP Settings** takes the same `mcpServers` JSON. At project level it lives in `.junie/mcp/mcp.json`.

For rules, Junie reads `.junie/guidelines.md`. Copy the contents of `examples/demo-app/AGENTS.md` into it.
