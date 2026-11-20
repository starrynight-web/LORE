# Connecting Lore to your IDE

Lore runs as a local MCP server over stdio: the IDE starts the Lore server process and talks to it over stdin/stdout.

> **Important compatibility rule:** Always register distinct MCP server keys (**`lore-solo`** vs **`lore-enterprise-mcp`**) so IDE schema caches never collide. The earlier Go `lore` binary on `dev` is deprecated.

## Option 1: Lore Solo (`solo` branch)

1. Install with `uv`:
   ```bash
   uvx --managed-python --python 3.12 --no-build lore-solo==0.2.8 install
   ```
2. Run auto-connect to register installed IDEs and standing rules:
   ```bash
   lore-solo connect
   ```
3. Or add `.cursor/mcp.json` / `.mcp.json` manually:
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

## Option 2: LORE Enterprise (`enterprise` branch)

1. Clone the `enterprise` branch and install `backend/requirements.txt`.
2. Verify the server directly:
   ```bash
   cd backend
   python mcp_server.py --list-tools
   python mcp_server.py --test
   ```
3. Register `lore-enterprise-mcp` in your IDE's MCP config:
   ```json
   {
     "mcpServers": {
       "lore-enterprise-mcp": {
         "command": "python",
         "args": ["/path/to/lore-enterprise/backend/mcp_server.py"],
         "env": {
           "PYTHONIOENCODING": "utf-8"
         }
       }
     }
   }
   ```

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

Server instructions are sent at connect time, but not every client shows them to the model. Add a short standing rule file so the agent calls Lore unprompted (`lore-solo connect` writes these automatically for Solo):

- `AGENTS.md`, read by Codex, Antigravity, Devin, Zed, Cursor and others
- `.cursor/rules/lore.mdc` (Cursor)
- `.github/copilot-instructions.md` (VS Code Copilot)
- `.agents/rules/lore.md` (Antigravity)
