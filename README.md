# Lore

[![ci](https://github.com/starrynight-web/LORE/actions/workflows/ci.yml/badge.svg)](https://github.com/starrynight-web/LORE/actions/workflows/ci.yml)

Lore gives one developer’s coding agent a persona, the skills filed under that persona, and a short map of the codebase. The agent calls Lore over MCP and gets one persona back, inside a token budget. Every answer is written down as a decision.

The project folder is the database. Personas and skills are markdown under `.lore/`. The setup site only makes those files easier to create. Closing the site does not stop the agent.

The older architecture documents describe the previous Go design.

## Quick start

The setup site needs Node.js. The agent does not. With [uv](https://docs.astral.sh/uv/) installed, the same commands work on macOS, Linux, and Windows:

```bash
uvx lore-solo install
uvx lore-solo setup
```

`install` puts the `lore-solo` command on this computer, in `~/.lore/bin`. `setup` prints an address and keeps running until you press Ctrl+C. Open that link. Run `uvx lore-solo setup` again whenever you want the website back. Save a provider key, add skills, create a persona, then give the connect prompt to your agent. Personas you write stay drafts until you approve them.

The other commands are the same shape:

```bash
uvx lore-solo connect
uvx lore-solo mcp
```

`connect` registers Lore with the editors already installed. The editor then starts `lore-solo mcp` on its own.

From a clone of the `solo` branch, the same four commands are:

```bash
git clone -b solo https://github.com/starrynight-web/LORE.git lore-solo
cd lore-solo
./scripts/lore-solo install
./scripts/lore-solo setup
./scripts/lore-solo connect
```

On Windows, from that clone:

```powershell
.\scripts\lore-solo.ps1 install
.\scripts\lore-solo.ps1 setup
.\scripts\lore-solo.ps1 connect
```

The agent calls Lore from any project. A project with its own `.lore` directory uses that. Every other project uses the personas saved from setup.

Connect shows a prompt to paste into an agent. With uv, that prompt is `uvx lore-solo connect` on macOS, Linux, and Windows. From the clone it runs `scripts/lore-solo connect` (or `scripts/lore-solo.ps1 connect` on Windows). Writing `.cursor/mcp.json` inside one project stays available as a backup:

```json
{
  "mcpServers": {
    "lore": {
      "command": "uvx",
      "args": ["lore-solo", "mcp"]
    }
  }
}
```

Restart the editor. It starts Lore on its own. Lore looks for `.lore/` from the working directory upward, then uses the personas saved from setup.

`examples/persona-pack` is a small project with a frontend persona, a backend persona, and a codebase map.

## What the agent receives

`get_context` returns one-line summaries of the stable skills for that persona, then a few nodes from the codebase map when one exists. `get_skill` returns the full steps for one skill. A draft persona asks you to approve it. An unknown persona returns nothing governed.

## Development

```bash
.venv/bin/pip install -e ".[dev]"
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
| [docs/solo/HOW_IT_WORKS.md](docs/solo/HOW_IT_WORKS.md) | How the solo slice runs |
| [docs/solo/UI.md](docs/solo/UI.md) | Setup site pages and how to change them |
| [docs/solo/TASKLIST.md](docs/solo/TASKLIST.md) | Build record and the current shape |
| [docs/solo/HOSTING.md](docs/solo/HOSTING.md) | What a later paid host would sync |

## License

[MIT](LICENSE)
