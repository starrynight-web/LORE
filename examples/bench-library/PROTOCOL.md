# Benchmark protocol

Frozen for quality-first scoring. Token cuts are secondary diagnostics only — Solo does not claim an 85–95% (or 70%) total-input win.

The skill pack is this library (`inventory.json` records population). Stable in-scope skills remain: `design-taste-frontend`, `frontend-design`, `minimalist-ui`, `shadcn-best-practices`, `tailwind-best-practices`, `vercel-react-best-practices`, `web-a11y-authoring`, `web-a11y-review`, `create-a-backend`, `supabase-postgres-best-practices`, `review-security`, and `web-design-guidelines`.

## Quality bake-off (primary)

App: `examples/bench-quality-app/`. Tasks: [QUALITY_TASKS.md](QUALITY_TASKS.md).

Same model within a suite (Antigravity: `gemini-3.8-flash-medium`). New headless session each run. Report pass rates across scenarios.

### Arms (practical skill use)

- **no_skills:** runner alone, no Lore MCP, no Lore rule. Models “forgot skills.”
- **user_picked:** no Lore MCP; `AGENTS.md` names the fixed right skill file(s) for that scenario (explicit user pick). Wrong-pick variants may be added later for discrimination.
- **agent_chosen:** no Lore MCP; skills copied on disk; `AGENTS.md` says use whatever skills you need (agent decides).
- **lore:** skills only through Lore. Standing quality rule in `AGENTS.md`. Knowledge store copied into the worktree. Workspace MCP server name `lore-solo` (must not collide with a disabled global `lore` or Enterprise `lore-enterprise-mcp`). Confirm requires DONE `get_context`; lore process gate also requires DONE `check_applied` (pass) and `log_decision`.

Legacy **paste_skills** (read all twelve skill bodies) is retired as a primary comparator; historical numbers stay in HURDLES only.

### Scoreboard

- **Primary:** rubric pass rate for lore ≥ `user_picked`, ≥ `agent_chosen`, and ≥ `no_skills`.
- **Process (lore only):** every completed lore run has successful `get_context`, `check_applied` status pass (or skip when nothing to cite), and `log_decision`.
- **Time (secondary):** lore median seconds ≤ 1.25× max(`agent_chosen`, `user_picked`) medians (whichever practical arm is slower).
- Tokens / fresh tokens may be logged; they are not fail lines.
- Cold Graphify extract is timed once outside the session timer when the lore arm needs a map.

`quality_claim` is true only when primary and process gates pass and the time secondary ceiling holds.

## Legacy token comparison (historical)

Earlier Codex suites used `examples/bench-app/TASK.txt` with a 70% input-token primary gate. Those results remain under `results*.json` / HURDLES for history. That charter token claim is **retired** for Solo product messaging. See [QUALITY_PLAN.md](../../docs/solo/QUALITY_PLAN.md).

## If Lore loses on quality

Read traces in this order and change only the first cause they support, then re-run the failing scenario: the agent skipped Lore; `get_context` returned no skills; the agent edited a decoy file; `check_applied` failed or was skipped wrongly; `user_picked` / `agent_chosen` did not follow their rule; the rubric checked the wrong file.
