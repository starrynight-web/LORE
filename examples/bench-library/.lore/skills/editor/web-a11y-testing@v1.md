---
type: skill
id: skill:editor/web-a11y-testing@v1
title: web a11y testing
persona: persona:editor
status: draft
summary: Validates accessibility with automated checks, keyboard walkthroughs, screen
  reader smoke tests, zoom/preference checks, and focused regression reporting. Use
  w
---
# Web A11y Testing

## Test Order

For repeatable smoke-check steps, see [CHECKS.md](CHECKS.md).

1. Automated scan for changed surfaces.
2. Keyboard-only journey.
3. Screen reader smoke pass.
4. Zoom, reflow, reduced motion, and forced-colors checks where relevant.

## Checklist

```markdown
Testing checklist

- [ ] Automation run completed and findings triaged
- [ ] All controls reachable and operable by keyboard
- [ ] Focus order and focus visibility are logical
- [ ] Names, roles, states, and values are announced correctly
- [ ] Dynamic changes are announced or focus-managed
- [ ] Forms expose errors, hints, and recovery paths
- [ ] Images, SVG, media controls, captions/transcripts, and unusual link behavior are verified where present
- [ ] User preference modes remain usable
```

## Screen Reader Smoke Path

- Check page title, landmarks, and heading map.
- Navigate to critical controls and verify role/name/state.
- Trigger state changes, dialogs, filters, validation, and pagination.
- Confirm no stale or duplicate announcements block task completion.

## Report

Include scope, tools used, pass/fail results, reproduction steps for failures, and residual risk.
