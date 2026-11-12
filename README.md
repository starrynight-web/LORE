# Lore

[![ci](https://github.com/starrynight-web/LORE/actions/workflows/ci.yml/badge.svg)](https://github.com/starrynight-web/LORE/actions/workflows/ci.yml)

**Lore Solo** fixes skill overload for one developer’s coding agent. You collect skills, file them under personas, connect Lore’s MCP to your IDE, and standing rules tell the agent to call Lore unprompted. Lore returns task-fit skill summaries and files to open (not your whole skill binder), then asks for a short receipt. Token savings are not the product promise — see [docs/solo/QUALITY_PLAN.md](docs/solo/QUALITY_PLAN.md).

The project folder is the database. Personas and skills are markdown under `.lore/`. The setup site only makes those files easier to create. Closing the site does not stop the agent. Enterprise (governed org knowledge) is a separate branch — [docs/solo/HOSTING.md](docs/solo/HOSTING.md).

The older architecture documents describe the previous Go design.

## Prerequisites

| Need | Required? | Used for | Get it |
| --- | --- | --- | --- |
| [uv](https://docs.astral.sh/uv/) | Yes | `uvx` / install / Python 3.12 toolchain | macOS/Linux: `curl -LsSf https://astral.sh/uv/install.sh \| sh` · Windows: `irm https://astral.sh/uv/install.ps1 \| iex` |
| [Node.js](https://nodejs.org/) 22 (exact major) | Yes for the setup site | Serving the prebuilt setup website — it is built and checked against the Node 22 line (npm is only needed to build the site from source) | Node 22 LTS from nodejs.org — pick the 22.x release explicitly (`brew install node@22` on macOS) |
| Network to PyPI / GitHub | Yes for first install | Published package install and release downloads (npm is only needed when building the site from source) | Campus Wi‑Fi / VPN as usual |
| Writable home (`~/.lore`, persona library) | Yes | Install prefix and shared personas | A normal user account (lab admin locks may block this) |
| Graphify map | No | Codebase map only | `lore-solo install --map`; installed from binary wheels under pinned constraints — no C/C++ toolchain is ever required |
| An IDE with MCP (Cursor, VS Code, …) | No for setup | Agent calls after connect | Install the editor, then `lore-solo connect` |

Check the machine first (works before install, via PyPI):

```bash
uvx --managed-python --python 3.12 --no-build lore-solo==0.2.0 doctor
```

`--managed-python --python 3.12` selects a managed Python 3.12 interpreter before dependencies are resolved, and `--no-build` accepts prebuilt binary wheels only — nothing compiles on your machine.

From a clone: `./scripts/lore-solo doctor` or `.\scripts\lore-solo.ps1 doctor`. Doctor prints what is missing, OS-specific install links, and which features each gap blocks. Exit code `1` means a required tool is missing.

## Quick start

The setup site needs Node.js 22 (the prebuilt page is produced and verified on the Node 22 line; npm is only needed when building the page from source). The agent needs neither. With [uv](https://docs.astral.sh/uv/) installed, the same commands work on macOS, Linux, and Windows:

```bash
uvx --managed-python --python 3.12 --no-build lore-solo==0.2.0 doctor
uvx --managed-python --python 3.12 --no-build lore-solo==0.2.0 install
lore-solo setup
```

`install` puts the `lore-solo` command on this computer, in `~/.lore/bin` (the install prefix), so after installing you call `lore-solo` directly — via `~/.lore/bin/lore-solo` or wherever your PATH exposes it — instead of going through `uvx` each time. Personas live in the OS library (`~/.local/share/lore`, macOS Application Support, or `%APPDATA%\Lore`), not under that prefix. Install pins every dependency from the packaged constraints and accepts binary wheels only — nothing compiles on your machine. The optional map extra (Graphify and its tree-sitter grammars) is tried first; when its wheels do not cover the platform, core Lore still installs so personas and MCP work, and the output says exactly what was skipped. Use `lore-solo install --no-map` to skip map, or `lore-solo install --map` to require it. Lore never downloads a C toolchain.

`setup` prints an address and keeps running until you press Ctrl+C. Open that link. Run `lore-solo setup` again whenever you want the website back. Save a provider key, add skills, create a persona, then give the connect prompt to your agent. Personas you write stay drafts until you approve them. `lore-solo uninstall` removes that command. Personas, skills, and editor registrations stay.

Once installed, the same subcommands run through `lore-solo` (`uvx lore-solo ...` also works for one-shot calls — the examples below show the command shape):

```bash
lore-solo doctor
lore-solo connect
lore-solo mcp
lore-solo map
lore-solo uninstall
```

Native installs are the supported path, with release targets of Windows x86_64, glibc Linux x86_64, and macOS arm64. A source checkout carries an intentionally **empty** `lore/site_bundles.json` — it is a placeholder, not a release manifest. The release workflow builds and smoke-tests the per-platform site archives, then generates the pinned manifest inside the release wheel — only that released package can auto-download the setup site (see [docs/solo/RELEASING.md](docs/solo/RELEASING.md)). Passing `setup --site-bundle <zip>` performs integrity and format validation, but without a pinned manifest entry it is **not** release-verified; combine it with `--offline` to avoid downloads. Checkouts can also run the site from their own `web/` build. The `lore-solo==0.2.0` install examples above work once that version is published to PyPI; the release packages and assets ship only after the native platform matrix and the Docker image gates pass — see the repository's [Actions](https://github.com/starrynight-web/LORE/actions) and [Releases](https://github.com/starrynight-web/LORE/releases) pages for current evidence.

### Containers (optional)

A container runtime exists for hosts where you would rather keep Lore's toolchain (Node, map dependencies) inside an image. The `lore-solo` Python launcher on the host still drives `container` and `connect` — it is what editors spawn. No official image is published — build the local versioned tags yourself:

```bash
docker build --target mcp  -t lore-solo:0.2.0-mcp .
docker build --target full -t lore-solo:0.2.0-full .
```

The `mcp` target holds the installed wheel plus map dependencies under the packaged constraints — no Node, npm, or compilers. The `full` target adds Node 22 and the prebuilt setup site. A default build always compiles the wheel and frontend from source and ignores whatever happens to be in `dist/`. Release builds opt in explicitly: place the verified artifacts under `dist/` (`dist/lore_solo-*.whl`, `dist/release_constraints.txt`, `dist/site/lore-site-<version>-linux-amd64.zip`) and pass `--build-arg LORE_RELEASE_ARTIFACTS=1`; the build then fails closed unless the constraints match the wheel and the site archive satisfies the pinned linux-amd64 manifest entry. Verified locally against rootless Podman; Docker Engine and Docker Desktop specifics are covered by argument tests, not local runs.

Run Lore inside the image with exactly two writable bind mounts — a workspace and a persona library, both of which must exist:

```bash
lore-solo container mcp   --image lore-solo:0.2.0-mcp  --workspace ~/code/app --library ~/.local/share/lore
lore-solo container setup --image lore-solo:0.2.0-full --workspace ~/code/app --library ~/.local/share/lore --port 3000
lore-solo container map   --image lore-solo:0.2.0-mcp  --workspace ~/code/app --library ~/.local/share/lore
```

Only those two directories cross the boundary — no home directory, socket, or other host paths — and the setup page is published on `127.0.0.1` only. On Linux the container runs as your UID/GID so files it writes stay owned by you. Under Docker Desktop on Windows/macOS the image's own user is used instead, and workspace/library paths may come from the VM's view of your files. Connect the editors from the host so the configs point back at the container:

```bash
lore-solo connect --runtime docker --image lore-solo:0.2.0-mcp \
  --workspace ~/code/app --library ~/.local/share/lore
```

Inside the container, host paths in `file_path` and registry rows are translated to `/workspace` and `/library`; `codebases.json` keeps host-native paths so native and container runs can share the registry. `connect` inside the container refuses and prints the host command instead.

### Conference rehearsal

For a demo or talk, keep everything local and rehearsed:

- Prepare the approved fixture ahead of time: a project folder with `examples/persona-pack/.lore` copied in — stable personas and skills, no provider key and no model calls required for the core flow.
- Show `get_context` returning skill summaries and a `decision_id`, `get_skill` returning the full body, then `check_applied` + `log_decision` for the receipt. Receipts prove which skills were served and cited — they are not a code-compliance verdict.
- With no map, `map_codebase` reports `unavailable` and retrieval keeps working — that is the fallback story. With map support, run `lore-solo map` in the foreground on a small fixture first; the map goes stale when sources change and the status says so honestly.
- Precache everything you can: install the wheel into an isolated env, prebuild the site bundle (`scripts/build_site_bundle.py`), and run `setup --site-bundle <zip> --offline` so nothing downloads. Local core retrieval and receipts need no network at all; provider-backed persona drafting and any inference the external agent itself does are the pieces that need a call out — skip them or record them.
- If the venue has no network, `docker save`/`docker load` the images onto the demo machine ahead of time — that still needs a working Docker daemon on the demo machine, it only removes the registry pull. If there is no daemon at all, fall back to the native `lore-solo` install — the MCP flow is identical. Do not publish images as part of the rehearsal.

`connect` registers Lore with the editors already installed and sets `LORE_WORKSPACE` to the open folder. The editor then starts `lore-solo mcp` on its own (coding tools by default: `get_context`, `get_skill`, `map_codebase`, `check_applied`, `log_decision`; use `lore-solo mcp --full` or `LORE_MCP_SURFACE=full` for the admin tools).

From a clone of the `solo` branch, the same commands are:

```bash
git clone -b solo https://github.com/starrynight-web/LORE.git lore-solo
cd lore-solo
./scripts/lore-solo doctor
./scripts/lore-solo install
./scripts/lore-solo setup
./scripts/lore-solo connect
./scripts/lore-solo uninstall
```

On Windows, from that clone:

```powershell
.\scripts\lore-solo.ps1 doctor
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

Call `get_context` once with the task sentence (and optional file path). It returns matching skill summaries and files to open. Use the guidance in your own edit flow, then call `check_applied` with the cited skill ids and `log_decision` so the project keeps a receipt of what was followed — the receipt records citations, it does not prove code compliance. If the map is missing or building, call `map_codebase` once and keep working from the summaries. `get_skill` fetches the full body of one stable skill on demand. A draft persona asks you to approve it.

Lore Solo’s product promise is **better-guided work**, not guaranteed token savings. See [docs/solo/QUALITY_PLAN.md](docs/solo/QUALITY_PLAN.md).

## Development

```bash
uv sync --frozen --extra dev --extra map
uv run --frozen ruff check lore
uv run --frozen mypy
uv run --frozen pytest
```

`lore/core` reads and writes the files. `lore/mcp_server.py` is the stdio server the IDE starts (`lore/mcp.py` is a thin re-export kept for the module entry point). `lore/setup` and `web/` are the setup site. `schemas/lore.result.v1.json` is the answer envelope.

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
| [docs/solo/GOVERNANCE.md](docs/solo/GOVERNANCE.md) | Content-trust layer: scans, approval, freshness |
| [docs/solo/RELEASING.md](docs/solo/RELEASING.md) | How a release is produced and what ships |
| [docs/solo/DEPENDENCY_AUDIT.md](docs/solo/DEPENDENCY_AUDIT.md) | Dependency audit record and how to repeat it |
| [CHANGELOG.md](CHANGELOG.md) | Release notes |

## License

[MIT](LICENSE)
