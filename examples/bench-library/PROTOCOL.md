# Benchmark protocol

Frozen before the timed runs. The task text is `examples/bench-app/TASK.txt`. The app is `examples/bench-app`. The skill pack is this library.

## Population

Skill files and editor rules were counted from `~/.agents/skills`, `~/.cursor/skills`, `~/.cursor/skills-cursor`, `~/.cursor/plugins/cache`, `~/.codex`, and `~/.claude`. `inventory.json` records the name, source path, and description. One copy of each skill name is filed here. Duplicate paths are counted and not filed twice.

## Strata

In scope, and the only skills marked stable: UI, accessibility, React, Tailwind, API or data, and review. The stable names are `design-taste-frontend`, `frontend-design`, `minimalist-ui`, `shadcn-best-practices`, `tailwind-best-practices`, `vercel-react-best-practices`, `web-a11y-authoring`, `web-a11y-review`, `create-a-backend`, `supabase-postgres-best-practices`, `review-security`, and `web-design-guidelines`.

Out of scope, filed as drafts and not served: editor meta skills, payments, Figma, video, Notion, hackathon and community workflows, and the rest of the platform catalog.

## Arms

Same model (`gpt-6-luna`, medium effort). New Codex session each run. Three runs. Report the median.

- Baseline: Codex's own skills, no Lore MCP entry, no Lore rule.
- Lore: those in-scope skills served only through Lore. Native skill files are not in that session's Codex home. The standing Lore rule is the project `AGENTS.md`.

The timed IDE is Codex, because it can run a session without a window. Cursor's always-on rule is written by `lore connect` and covered by the connect test. The Cursor CLI does not start a headless chat.

## Scoreboard

- Gate: checklist pass rate at least as high as baseline.
- Primary: median input tokens at or below 70 percent of baseline.
- Time: median wall clock, with the map already built, at or below 1.15 times baseline.
- The cold Graphify extract is timed once and reported on its own line.

The charter's 85 to 95 percent reduction is reported. It is not the first fail line.

## If Lore loses

Read traces in this order and change only the first cause they support, then run the same task once more: the agent walked the repo anyway; `get_context` returned every stable skill; the map answer was large; `get_skill` was called for unused skills; the timer included the cold map build.
