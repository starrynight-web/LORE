---
type: skill
id: skill:accessibility-engineer/web-a11y-dynamic-ui@v1
title: web a11y dynamic ui
persona: persona:accessibility-engineer
status: draft
summary: Handles accessible dynamic interfaces such as filtering, sorting, pagination,
  progress, live regions, status messages, data tables, and client-rendered result
  u
---
# Web A11y Dynamic UI

## Rules

1. Client-side updates need non-visual feedback.
2. Use live regions for status updates that should not move focus.
3. Move focus only when it improves task flow and orientation.
4. Use table semantics for tabular relationships, not layout.
5. Communicate sort, current page, result count, and progress state semantically and visually.

## Checklist

```markdown
Dynamic UI checklist

- [ ] Active filters and result counts are discoverable
- [ ] Loading, empty, error, and success states are announced when needed
- [ ] Pagination exposes current page and available movement
- [ ] Progress indicators expose current step/value where meaningful
- [ ] Tables have captions or labels, headers, and sort state
- [ ] Interactive controls inside data views preserve context
```

## Output

Document update announcement strategy, focus strategy, table/result semantics, and regression checks.
