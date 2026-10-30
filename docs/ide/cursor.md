# Cursor

Project config, committed with the repo: `.cursor/mcp.json`

```json
{
  "mcpServers": {
    "lore": {
      "command": "${userHome}/go/bin/lore",
      "args": ["serve", "--root", "${workspaceFolder}"]
    }
  }
}
```

For every project at once, put the same block in `~/.cursor/mcp.json` with an absolute `--root`, or leave `--root` out so Lore finds `.lore/` from the working directory.

1. Open **Settings → MCP** (Tools & Integrations) and enable `lore`. The status dot turns green and lists the Lore tools.
2. `lore connect` writes `~/.cursor/rules/lore.mdc` with `alwaysApply: true`, so the agent calls Lore without being asked. The server instructions say the same thing.
3. Prompts show up as slash commands in chat (`/answer_with_lore`, `/validate_change`, `/explain_conflict`, `/prepare_review_packet`).

If the server fails to start, open **Output → MCP Logs**. Lore writes its own errors to stderr, which shows up there. `LORE_DEBUG=1` in an `env` block turns on debug logs.
