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

### Completeness And Isolation

Each declared scenario must contain exactly one record for every arm and repetition number. The scorer expects five repetitions per cell unless another positive count is explicitly declared. Missing or duplicate cells, unknown arms, nonzero agent exits, empty or non-boolean rubric checks, inconsistent pass flags, and missing/nonpositive/nonfinite durations fail the completeness gate.

The eight scenarios include the original wrong-file, accessibility-label, and API-shape tasks plus full-skill retrieval, new-file creation, cross-file changes, stale-map recovery, and no-map fallback. The Lore full-skill scenario additionally requires successful `get_skill` tool evidence. Citation receipts and agent-reported outcomes are process evidence, not independent verification that code follows a skill.

Arm order rotates between scenarios/repetitions. Each agent process receives an isolated home/configuration/cache environment and its own worktree; the runner does not rewrite global editor/MCP configuration. This is experiment isolation, not an operating-system security sandbox. Model-backed commands require explicit approval and the `LORE_BENCH_ALLOW_PAID=1` gate.

New quality results go to a unique run directory with task/library hashes and environment metadata. Historical result files are not overwritten.

### Scoreboard

- **Primary:** rubric pass rate for lore ≥ `user_picked`, ≥ `agent_chosen`, and ≥ `no_skills`.
- **Process (lore only):** every completed lore run has successful `get_context`, `check_applied` status pass (or skip when nothing to cite), and `log_decision`.
- **Time (secondary):** lore median seconds ≤ 1.25× max(`agent_chosen`, `user_picked`) medians (whichever practical arm is slower).
- Tokens / fresh tokens may be logged; they are not fail lines.
- Cold Graphify extract is timed once outside the session timer when the lore arm needs a map.

`workflow_gate` requires complete cells, the primary non-regression gate, all Lore process receipts, and the time ceiling. Equal pass rates can establish workflow success but are not an observed quality advantage.

`observed_improvement` additionally requires Lore's pass rate to exceed every comparator in at least one scenario without regressing in another. `quality_claim` requires that observed improvement, the workflow gate, and at least five repetitions per cell. It means observed outcomes in this finite fixture sample, not statistical proof or general superiority. Retired `paste_skills` results and historical `quality_claim: true` fields do not qualify under this protocol.

## Legacy token comparison (historical)

Earlier Codex suites used `examples/bench-app/TASK.txt` with a 70% input-token primary gate. Those results remain under `results*.json` / HURDLES for history. That charter token claim is **retired** for Solo product messaging. See [QUALITY_PLAN.md](../../docs/solo/QUALITY_PLAN.md).

## If Lore loses on quality

Read traces in this order and change only the first cause they support, then re-run the failing scenario: the agent skipped Lore; `get_context` returned no skills; the agent edited a decoy file; `check_applied` failed or was skipped wrongly; `user_picked` / `agent_chosen` did not follow their rule; the rubric checked the wrong file.
