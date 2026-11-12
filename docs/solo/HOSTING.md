# Solo vs Enterprise (tiers)

Solo and Enterprise share a story — MCP into the same agent harnesses, small cited results, drafts withheld until approved — but they are different products on different branches.

## Solo (this tree, `solo` branch)

- Local personas and skills under `.lore/` (markdown OKF).
- Optional Graphify map under `graphify-out/` (file store, not a graph database).
- MCP server display name: **`lore-solo`**.
- Coding tools: `get_context`, `get_skill`, `map_codebase`, `check_applied`, `log_decision`.
- Setup key only guards the local website. No accounts, Stripe, or Postgres.

Graphify’s native stack (`graphifyy` → `tree-sitter`) installs from binary wheels under the packaged constraints — no C/C++ toolchain is needed or downloaded. Where no wheel covers the platform, core Lore installs without map; see `lore-solo install --no-map` and `lore-solo install --map` for the explicit choices.

## Enterprise (`enterprise` branch)

Customer-deployed governed knowledge grid: Django + Next.js + Qdrant + Celery, OCR/ingestion, 9-layer governance, tenancy, audit lineage.

- MCP server: **`lore-enterprise-mcp`** (`backend/mcp_server.py` on that branch).
- Tools include governed `get_context`, `search`, `check_compliance`, conflicts, `trace`, `query_as_of`, escalate, OCR, and more — see `docs/enterprise/MCP_TOOL_REFERENCE.md` on `enterprise`.

## Compatibility rules

- Same harnesses (Cursor, VS Code, Antigravity, …) via MCP stdio.
- Keep familiar verbs where possible (`get_context`, `log_decision`, skill fetch).
- Keep the small-result / ~800-token habit so agents do not learn a different pattern per tier.
- Use **distinct MCP server names** (`lore-solo` vs `lore-enterprise-mcp`) so IDE schema caches never collide. The old Go `lore` binary is deprecated and removed; do not re-register a server key named only `lore`.

A later paid host may sync Solo’s `.lore/` and `graphify-out/` across machines. That is not built here. The laptop copy remains what the agent reads.

Inspect Enterprise without mixing trees: `git show origin/enterprise:README.md`.
