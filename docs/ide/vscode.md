# VS Code (GitHub Copilot agent mode)

Project config: `.vscode/mcp.json`. VS Code uses `servers`, not `mcpServers`.

```json
{
  "servers": {
    "lore": {
      "type": "stdio",
      "command": "${userHome}/go/bin/lore",
      "args": ["serve", "--root", "${workspaceFolder}"]
    }
  }
}
```

1. Open the file; a **Start** code lens appears above `lore`. Click it, or run **MCP: List Servers → lore → Start**.
2. Open Copilot Chat in **Agent** mode and check the tools picker: Lore's 12 tools should be listed and ticked.
3. Add `.github/copilot-instructions.md` (see `examples/demo-app`) so the agent calls `get_context` before editing.
4. Prompts appear as `/mcp.lore.<name>`; resources via **Add Context → MCP Resources**.

Read tools are annotated `readOnlyHint`, so VS Code may run them without asking. Write tools (`ingest`, `update_persona`, `log_decision`) will ask for confirmation.

Logs: **MCP: List Servers → lore → Show Output**.
