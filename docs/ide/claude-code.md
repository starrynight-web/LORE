# Claude Code

> Config example, not verified. Claude Code needs a paid Claude plan to sign in, so it isn't part of the smoke tests.

Project config: `.mcp.json` at the repo root.

```json
{
  "mcpServers": {
    "lore": {
      "command": "/home/you/go/bin/lore",
      "args": ["serve", "--root", "."]
    }
  }
}
```

Or from the CLI: `claude mcp add lore -- ~/go/bin/lore serve --root "$PWD"`.

Claude Code reads `CLAUDE.md`. `lore connect` writes a Lore section into `~/.claude/CLAUDE.md`.
