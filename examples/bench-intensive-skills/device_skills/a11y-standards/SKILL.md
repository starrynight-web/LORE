---
name: a11y-standards
description: "ARIA tablist/tab keyboard navigation, aria-live='polite' status regions, and Find bar search landmark."
---

# Project Accessibility Standards

1. **SprintBoard (`src/SprintBoard.tsx`):**
   - Stage selector uses `role="tablist"` with `role="tab"` buttons and `aria-selected`.
   - `ArrowRight` and `ArrowLeft` cycle active stage with wrap-around.
   - Include `<div aria-live="polite" data-stage-live>Current stage: {activeStage}</div>`.
2. **Simple Write Find Bar (`src/App.tsx`):**
   - Find bar wrapper must have `role="search"`, `aria-label="Find in document"`, and `data-motion-policy="respect-reduced-motion"`.
   - Match counter must have `aria-live="polite"` and `data-find-status="match-count"`, showing `"No matches"` when `findQuery` is non-empty and `findCount === 0`, or `"${activeMatch} of ${findCount} matches"` when `findCount > 0`.
