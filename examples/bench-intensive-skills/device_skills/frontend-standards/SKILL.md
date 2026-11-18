---
name: frontend-standards
description: "React UI conventions for SprintBoard data-surface, readingTime formula, footer data-stat, and Callout slash block."
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
