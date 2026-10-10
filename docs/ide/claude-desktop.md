# Claude Desktop

Claude Desktop is a chat app, not an editor, so it can't edit your files. It is still the easiest client for trying Lore's prompts and resources.

Config file:

- Linux: `~/.config/Claude/claude_desktop_config.json`
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

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

There is no workspace folder, so `--root` must be absolute. Claude Desktop reads the file only at startup, so quit the app before editing it and start it again afterwards. Closing the window isn't enough, because it keeps running in the tray. If the file isn't valid JSON, Claude Desktop starts without any MCP servers, and `main.log` says "Refusing config write: the load was degraded".

Claude Desktop runs `lore` on your machine, and Lore reads `.lore/` in the `--root` folder. Claude itself never needs access to the project files, and in Chat mode it can't edit them.

Check:

1. The tools menu in the chat box lists `lore` with 12 tools.
2. Ask: "Using Lore, what rules apply to src/auth/token.go if I add a refresh-token endpoint?" Claude should call `get_context`, report the conflict and ask you to choose.
3. **+ → Add from lore** lists the four prompts and the `lore://` resources.

Logs: `~/.config/Claude/logs/mcp-server-lore.log`.
