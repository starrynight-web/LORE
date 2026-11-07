# Quality bake-off tasks

App: `examples/bench-quality-app/`. Skill pack: this library. Runner: `python scripts/run_benchmark.py quality`.

These tasks punish wrong-file guesses and skill overload. Lore should retrieve the right persona/skills and name the right files.

| Id | Task file | Rubric (deterministic) |
| --- | --- | --- |
| `wrong-file` | `tasks/wrong-file.txt` | `Panel.tsx` has `Saved` and `./theme`; `PanelCopy.tsx` unchanged |
| `a11y-label` | `tasks/a11y-label.txt` | `Panel.tsx` button visible text includes `Save` |
| `api-shape` | `tasks/api-shape.txt` | `health.py` has `"status"` / `status` with `ready`; `health_probe.py` unchanged |

Arms per scenario (practical skill use):

- `no_skills` — no Lore MCP, no Lore AGENTS.md
- `user_picked` — no Lore MCP; AGENTS.md names the fixed right skill file(s) for that scenario
- `agent_chosen` — no Lore MCP; skills on disk; AGENTS.md says pick whatever fits
- `lore` — Lore quality standing instructions + lore-solo MCP + cold map

Primary claim: Lore rubric pass rate ≥ `user_picked`, ≥ `agent_chosen`, and ≥ `no_skills`; Lore process gate (`get_context` DONE, `check_applied` pass, `log_decision`) complete on lore runs. Time secondary vs the slower of `user_picked` / `agent_chosen`. Tokens are side notes only.

The old `paste_skills` (read all twelve bodies) arm is retired; historical numbers stay in HURDLES.
