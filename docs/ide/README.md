# Connecting Lore to your IDE

Lore runs as a local MCP server over stdio: the IDE starts `lore serve --root <project>` and talks to it over stdin/stdout. Nothing listens on a port.

## Before you start

1. Install the binary: `go install github.com/DJRCX/lore/cmd/lore@latest`, or from a checkout, `go install ./cmd/lore`. It lands in `~/go/bin/lore`.
2. In your project, run `lore init` (or `lore init --demo` for the sample auth rules). It creates `.lore/` and prints a ready-to-paste config for each IDE with absolute paths filled in.
3. Check the server by hand first: `npx @modelcontextprotocol/inspector ~/go/bin/lore serve --root /path/to/project`.

Use an absolute path to the binary in configs. IDEs started from a desktop launcher often don't see your shell `PATH`.

If a client passes `${workspaceFolder}` through without expanding it, `lore serve` ignores it and finds `.lore/` by walking up from the working directory.

## Clients

| Client | Page | Status |
| --- | --- | --- |
| Cursor | [cursor.md](cursor.md) | smoke-tested target |
| VS Code (Copilot agent mode) | [vscode.md](vscode.md) | smoke-tested target |
| Google Antigravity | [antigravity.md](antigravity.md) | smoke-tested target |
| Claude Desktop | [claude-desktop.md](claude-desktop.md) | smoke-tested target (chat, prompts, resources) |
| Claude Code | [claude-code.md](claude-code.md) | config example, not verified |
| Devin Desktop | [devin-desktop.md](devin-desktop.md) | config example, not verified |
| OpenAI Codex | [codex.md](codex.md) | config example, not verified |
| JetBrains (AI Assistant, Junie) | [jetbrains.md](jetbrains.md) | config example, not verified |
| Zed | [zed.md](zed.md) | config example, not verified |

Results go in [compat-matrix.md](compat-matrix.md); the test script is [smoke-test.md](smoke-test.md).

## Making agents call Lore on their own

Server instructions are sent at connect time, but not every client shows them to the model. Add a short rule file as well; [`examples/demo-app`](../../examples/demo-app) has one for each client:

- `AGENTS.md`, read by Codex, Antigravity, Devin, Zed, Cursor and others
- `.cursor/rules/lore.mdc` (Cursor)
- `.github/copilot-instructions.md` (VS Code Copilot)
- `.agents/rules/lore.md` (Antigravity)
