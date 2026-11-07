# Lore Solo quality plan (plain language)

This page is the product promise in everyday words. Builders: see also [PROTOCOL.md](../../examples/bench-library/PROTOCOL.md), [HOW_IT_WORKS.md](HOW_IT_WORKS.md), and [FLOW.md](FLOW.md).

## What Lore Solo is

Lore Solo is a **gateway + policy layer** for coding skills — not a token-savings product.

Like DevRelay (MCP tools + skills that fire unprompted), Solo has two layers:

| Layer | Role |
| --- | --- |
| **MCP tools** | I/O: `get_context`, `map_codebase`, `check_applied`, `log_decision` |
| **Standing instructions / IDE rules** | Autopilot: call Lore on non-trivial work without being asked |
| **Personas** | Policy router: which approved skills apply to this task |
| **Graphify map** | Codebase orientation (soft auto or manual rebuild) |
| **Project rule `.md` files** | Per-repo reinforcement (`AGENTS.md`, harness-specific rules) |

**Problem Solo solves:** skill overload. People collect many skills, then forget to pick one, pick the wrong one, or leave the choice to the agent. Lore consults **personas**, returns **task-fit summaries**, names **files to open**, and requires a **receipt**.

### End-user workflow

1. Collect skills for your needs.
2. Create persona files that own those skills; approve drafts.
3. Connect Lore MCP to your agent harness (Cursor, VS Code, Antigravity, …).
4. Lore should fire when skills are needed: hand summaries, check what was applied, rebuild the codebase map when needed.

## Old dream vs new promise

**Old dream:** Lore would mainly save money by shrinking how much of the AI’s attention bill each task used.

**New promise:** Lore does **not** guarantee cheaper runs. Lore’s job is better-guided work than forgetting skills, picking the wrong ones, or dumping a whole skill folder into the chat.

## What the agent must do (four steps)

1. Call **get_context** once with the task.
2. **Edit** only the files Lore named, using those skill summaries.
3. Call **check_applied** with the decision id and the skill ids it followed.
4. Call **log_decision** with a one-line outcome.

Do not walk the skill folders or paste the whole library into the chat.

## How we prove it

We run a **quality bake-off**, not a token bake-off. Arms match how people actually use skills:

| Arm | Meaning |
| --- | --- |
| **no_skills** | Forgot / never invoked skills |
| **user_picked** | Told to use fixed skill(s) for the scenario (right pick; wrong-pick variants may be added) |
| **agent_chosen** | Skills on disk; “use whatever skills you need”; no Lore MCP |
| **lore** | Lore’s four-step loop |

(The older **paste_skills** arm — read all twelve skill bodies — remains in historical HURDLES only. It is not a practical baseline.)

Tasks use fixed rubrics (wrong lookalike file, accessible label, API field name). Lore wins when it passes those checks at least as often as the other arms, completes its receipt steps, and does not take wildly longer than `agent_chosen` or `user_picked`.

Token and time numbers may be recorded as side notes. They are **not** the claim.

## Solo vs Enterprise

| | Solo (`solo` branch) | Enterprise (`enterprise` branch) |
| --- | --- | --- |
| Job | Persona-routed skills + codebase map + receipts | Governed org knowledge (policies, PDFs, OCR, conflicts, tenancy) |
| Stack | Local Python + optional setup site | Django + Next.js + Qdrant + Celery |
| MCP name | `lore-solo` | `lore-enterprise-mcp` |
| Flagship | `get_context` → skill summaries + files | `lore.get_context` through a 9-layer governance engine |

Same harness matrix (MCP stdio). Same habit of small, cited results (~800-token budget idea). Distinct server names so schema caches never collide. Enterprise code is **not** part of this Solo tree — see that branch’s README and `docs/enterprise/MCP_TOOL_REFERENCE.md`. Hosting / sync notes: [HOSTING.md](HOSTING.md).

## What we are not promising

- An 85–95% (or 30%) cut in total tokens.
- That Lore always beats a model that already knows a tiny task from memory.
- Full team conflict judging with a separate AI referee (that lives on Enterprise).

## For builders

Technical scoreboard and harness: [examples/bench-library/PROTOCOL.md](../../examples/bench-library/PROTOCOL.md).  
How Solo wires MCP and files: [HOW_IT_WORKS.md](HOW_IT_WORKS.md), [FLOW.md](FLOW.md).
