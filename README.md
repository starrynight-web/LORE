# Lore

[![ci](https://github.com/starrynight-web/LORE/actions/workflows/ci.yml/badge.svg)](https://github.com/starrynight-web/LORE/actions/workflows/ci.yml)

**Lore Solo** fixes skill overload for one developer’s coding agent. You collect skills, file them under personas, connect Lore’s MCP to your IDE, and standing rules tell the agent to call Lore unprompted. Lore returns task-fit skill summaries and files to open (not your whole skill binder), then asks for a short receipt. Token savings are not the product promise — see [docs/solo/QUALITY_PLAN.md](docs/solo/QUALITY_PLAN.md).

The project folder is the database. Personas and skills are markdown under `.lore/`. The setup site only makes those files easier to create. Closing the site does not stop the agent. Enterprise (governed org knowledge) is a separate branch — [docs/solo/HOSTING.md](docs/solo/HOSTING.md).

The older architecture documents describe the previous Go design.

## Quick start

The setup site needs Node.js. The agent does not. With [uv](https://docs.astral.sh/uv/) installed, the same commands work on macOS, Linux, and Windows:

```bash
uvx lore-solo install
uvx lore-solo setup
```

`install` puts the `lore-solo` command on this computer, in `~/.lore/bin` (the install prefix). Personas live in the OS library (`~/.local/share/lore`, macOS Application Support, or `%APPDATA%\Lore`), not under that prefix. Install tries the optional map extra (Graphify) via wheels first; if a native build fails, core Lore still installs so personas and MCP work. Use `lore-solo install --no-map` to skip map, or `lore-solo install --map` to require it. Lore never downloads Visual Studio Build Tools.

`setup` prints an address and keeps running until you press Ctrl+C. Open that link. Run `uvx lore-solo setup` again whenever you want the website back. Save a provider key, add skills, create a persona, then give the connect prompt to your agent. Personas you write stay drafts until you approve them. `uvx lore-solo uninstall` removes that command. Personas, skills, and editor registrations stay.

The other commands are the same shape:

```bash
uvx lore-solo connect
uvx lore-solo mcp
uvx lore-solo map
uvx lore-solo uninstall
```

`connect` registers Lore with the editors already installed and sets `LORE_WORKSPACE` to the open folder. The editor then starts `lore-solo mcp` on its own (coding tools by default: `get_context`, `map_codebase`, `check_applied`, `log_decision`; use `lore-solo mcp --full` or `LORE_MCP_SURFACE=full` for the admin tools).

From a clone of the `solo` branch, the same commands are:

```bash
git clone -b solo https://github.com/starrynight-web/LORE.git lore-solo
cd lore-solo
./scripts/lore-solo install
./scripts/lore-solo setup
./scripts/lore-solo connect
./scripts/lore-solo uninstall
```

On Windows, from that clone:

```powershell
.\scripts\lore-solo.ps1 install
.\scripts\lore-solo.ps1 setup
.\scripts\lore-solo.ps1 connect
.\scripts\lore-solo.ps1 uninstall
```

The agent calls Lore from any project. A project with its own `.lore` directory uses that. Every other project uses the personas saved from setup.

Connect shows a prompt to paste into an agent. With uv, that prompt is `uvx lore-solo connect` on macOS, Linux, and Windows. From the clone it runs `scripts/lore-solo connect` (or `scripts/lore-solo.ps1 connect` on Windows). Writing `.cursor/mcp.json` inside one project stays available as a backup:

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

Restart the editor. It starts Lore on its own. Lore looks for `.lore/` from the working directory upward, then uses the personas saved from setup.

`examples/persona-pack` is a small project with a frontend persona, a backend persona, and a codebase map.

## What the agent receives

Call `get_context` once with the task sentence (and optional file path). It returns matching skill summaries and files to open. Edit those files, then call `check_applied` and `log_decision` so the project keeps a receipt of what was followed. If the map is missing or building, call `map_codebase` once and keep working from the summaries. A draft persona asks you to approve it. Full skill bodies and admin tools stay on the optional full MCP surface.

Lore Solo’s product promise is **better-guided work**, not guaranteed token savings. See [docs/solo/QUALITY_PLAN.md](docs/solo/QUALITY_PLAN.md).

## Development

```bash
.venv/bin/pip install -e ".[dev,map]"
.venv/bin/ruff check lore
.venv/bin/mypy
.venv/bin/pytest
```

`lore/core` reads and writes the files. `lore/mcp.py` is the stdio server the IDE starts. `lore/setup` and `web/` are the setup site. `schemas/lore.result.v1.json` is the answer envelope.

## Documentation

| Document | Contents |
| --- | --- |
| [docs/LORE_OVERVIEW.md](docs/LORE_OVERVIEW.md) | Earlier product overview |
| [docs/LORE_ARCHITECTURE.md](docs/LORE_ARCHITECTURE.md) | Earlier target architecture |
| [docs/PROJECT_REQUIREMENTS.md](docs/PROJECT_REQUIREMENTS.md) | Earlier requirements |
| [docs/PROJECT_CHARTER.md](docs/PROJECT_CHARTER.md) | Earlier scope and milestones |
| [docs/solo/FLOW.md](docs/solo/FLOW.md) | Visual flow: user, agent, MCP, and API wiring |
| [docs/solo/HOW_IT_WORKS.md](docs/solo/HOW_IT_WORKS.md) | How the solo slice runs |
| [docs/solo/QUALITY_PLAN.md](docs/solo/QUALITY_PLAN.md) | Plain-language quality promise and bake-off |
| [docs/solo/UI.md](docs/solo/UI.md) | Setup site pages and how to change them |
| [docs/solo/TASKLIST.md](docs/solo/TASKLIST.md) | Build record and the current shape |
| [docs/solo/HOSTING.md](docs/solo/HOSTING.md) | What a later paid host would sync |

## License

[MIT](LICENSE)
