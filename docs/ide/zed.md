# Zed

> Config example, not verified.

Add the server under **Settings → AI → MCP Servers → Add Server → Add Local Server**, or edit `settings.json` directly (`zed: open settings file`):

```json
{
  "context_servers": {
    "lore": {
      "command": "/home/you/go/bin/lore",
      "args": ["serve", "--root", "/home/you/path/to/project"],
      "env": {}
    }
  }
}
```

Keep `args` even when empty. Older Zed builds fail to load an entry without it, and the only sign is the log line "did not match any variant of untagged enum ContextServerSettingsContent".

Zed's agent reads `AGENTS.md` for rules. Prompts appear as slash commands in the agent panel.
