# Google Antigravity

Add Lore Solo to the global config, `~/.gemini/config/mcp_config.json` (Settings → Customizations → Installed MCP Servers → **Open MCP Config**). Antigravity historically ignored workspace `.agents/mcp_config.json` for MCP (it still loads workspace rules). Keep any servers already in the file, and add **`lore-solo`** (not a bare `lore` key — that collides with older Go binaries and schema caches):

```json
{
  "mcpServers": {
    "lore-solo": {
      "command": "uvx",
      "args": ["lore-solo", "mcp"],
      "env": {
        "LORE_WORKSPACE": "/home/you/path/to/project"
      }
    }
  }
}
```

Or after `uvx lore-solo install`, point `command` at `~/.lore/bin/lore-solo` with `args: ["mcp"]`. Prefer `lore-solo connect`, which writes this entry and standing rules.

## Rules

Antigravity loads `AGENTS.md` and `.agents/rules/*.md`. Connect writes:

- project `AGENTS.md` (Lore standing block)
- `.agents/rules/lore.md` with `trigger: always_on`

Standing text is the coding loop: `get_context` → edit → `check_applied` → `log_decision`.

## Tools

Default coding surface (4 tools): `get_context`, `map_codebase`, `check_applied`, `log_decision`. Full admin surface: `lore-solo mcp --full`.

Antigravity shares one token budget between rules, skills and MCP tools. When over budget, it can drop Lore’s tools — disable unused skills/servers until Customizations lists `lore-solo` with nothing excluded.

After editing the config, refresh the MCP Servers panel and confirm `lore-solo` lists the coding tools.
