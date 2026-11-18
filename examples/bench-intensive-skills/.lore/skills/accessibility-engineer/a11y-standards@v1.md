---
type: skill
id: skill:accessibility-engineer/a11y-standards@v1
title: Project Accessibility Standards
persona: persona:accessibility-engineer
status: stable
summary: ARIA tablist/tab keyboard navigation, aria-live='polite' status regions,
  and Find bar search landmark.
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
    - src/App.tsx
    claims_unverifiable: 16
tags:
- accessibility
- a11y
- aria
- keyboard
- tablist
- find
- search
- live
- sprintboard
---
# Project Accessibility Standards

1. **SprintBoard (`src/SprintBoard.tsx`):**
   - Stage selector uses `role="tablist"` with `role="tab"` buttons and `aria-selected`.
   - `ArrowRight` and `ArrowLeft` cycle active stage with wrap-around.
   - Include `<div aria-live="polite" data-stage-live>Current stage: {activeStage}</div>`.
2. **Simple Write Find Bar (`src/App.tsx`):**
   - Find bar wrapper must have `role="search"`, `aria-label="Find in document"`, and `data-motion-policy="respect-reduced-motion"`.
   - Match counter must have `aria-live="polite"` and `data-find-status="match-count"`, showing `"No matches"` when `findQuery` is non-empty and `findCount === 0`, or `"${activeMatch} of ${findCount} matches"` when `findCount > 0`.
