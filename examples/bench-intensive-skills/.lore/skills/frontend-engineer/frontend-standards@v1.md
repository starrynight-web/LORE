---
type: skill
id: skill:frontend-engineer/frontend-standards@v1
title: Project Frontend Standards
persona: persona:frontend-engineer
status: stable
summary: React UI conventions for SprintBoard data-surface, readingTime formula, footer
  data-stat, and Callout slash block.
governance:
  scan:
    tool: lore-static
    at: '2026-11-16T23:46:39Z'
    score: 0
    findings: []
    accepted_risk: false
    accepted_at: null
    accepted_note: null
  freshness:
    status: aging
    verified_at: null
    claims_ok: 0
    claims_stale:
    - src/SprintBoard.tsx
    - src/lib/documents.ts
    - Math.max(1, Math.ceil(wordCount(text) / 200))
    - src/App.tsx
    - src/editor/extensions.tsx
    - website/
    claims_unverifiable: 17
tags:
- frontend
- react
- sprintboard
- reading
- footer
- callout
- slash
- board
- ui
---
# Project Frontend Standards

1. **Devin-a-thon Dhaka SprintBoard (`src/SprintBoard.tsx`):**
   - Render the root container with `data-surface="devin-dhaka-board"`.
   - Support the 6 stages: `Brainstorming`, `Planning`, `Writing Code`, `Implementing Features`, `Debugging`, `Shipping`.
2. **Simple Write Reading Time & Callout:**
   - Export `readingTime(text: string): number` from `src/lib/documents.ts`: return `0` when `wordCount(text) === 0`, otherwise `Math.max(1, Math.ceil(wordCount(text) / 200))`.
   - Render `<span data-stat="reading-time">{readingTime(active.draft)} min read</span>` in the desktop editor footer in `src/App.tsx`.
   - Add a `callout` item to `slashDefinitions` in `src/editor/extensions.tsx` with `id: "callout"`, `label: "Callout"`, `keywords: "note warning info"` inserting `> **Note:** `.
   - Never modify files under `website/`.
