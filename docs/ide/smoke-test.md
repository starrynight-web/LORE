# IDE smoke test (Solo)

Historical rows in [compat-matrix.md](compat-matrix.md) used the Go `lore serve` demo. That binary is **deprecated and removed**. Use Solo:

1. `uvx --managed-python --python 3.12 --no-build lore-solo==0.2.1 install` (or `./scripts/lore-solo install` from a `solo` checkout).
2. `uvx lore-solo connect` in a sample project (or `examples/persona-pack`).
3. Confirm the editor lists MCP server **`lore-solo`** with the five coding tools: `get_context`, `get_skill`, `map_codebase`, `check_applied`, `log_decision`.
4. Ask the agent to change something small; expect `get_context` before edits, `get_skill` when a summary is not enough, then `check_applied` / `log_decision`.
5. Optional: `lore-solo mcp --full` and re-check admin tools.
6. Optional container path: `docker build --target mcp -t lore-solo:0.2.1-mcp .`, then `lore-solo connect --runtime docker --image lore-solo:0.2.1-mcp --workspace <dir> --library <dir>` on the host and repeat steps 3–4.

Do not install or PATH a Go `~/go/bin/lore`. If an old `"lore"` MCP entry remains in a config file, delete it or re-run connect (connect strips the legacy key).
