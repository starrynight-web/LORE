# Function audit

> Snapshot from 2026-10-26, before map tools and one-call task mode. Current behavior:
> default MCP coding surface is `get_context`, `map_codebase`, `check_applied`,
> `log_decision`; full surface keeps the tools below. See [HOW_IT_WORKS.md](HOW_IT_WORKS.md),
> [FLOW.md](FLOW.md), and [QUALITY_PLAN.md](QUALITY_PLAN.md).

Recorded before the map tools were added. Date: 2026-10-26.

`pytest` in the project virtualenv: 64 passed.

Live `graphify extract --code-only` on a copy of `examples/persona-pack` (the checked-in map was not reused):

| Check | Result |
| --- | --- |
| `graph.json` schema version 1 | pass |
| `get_context` with `file_path=src/ui/Button.tsx` names `Button.tsx` and `theme.ts` | pass |
| `get_context` | pass |
| `get_skill` | pass |
| `list_personas` | pass |
| `ingest` | pass |
| `log_decision` | pass |
| `trace` | pass |

The extract wrote `graphify-out/graph.json` (7 nodes, 6 edges). It did not write `graph.html`; the setup job exports that in a second step.

Gaps at the time of this audit: no MCP tool builds or searches the map, a repo without `.lore` is read from the persona library, and `intent` does not choose files.
