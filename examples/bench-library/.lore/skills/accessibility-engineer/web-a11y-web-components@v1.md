---
type: skill
id: skill:accessibility-engineer/web-a11y-web-components@v1
title: web a11y web components
persona: persona:accessibility-engineer
status: draft
summary: Applies accessibility guidance to custom elements and Shadow DOM, including
  progressive enhancement, slots, focus delegation, ElementInternals, ARIA limitations
---
# Web A11y Web Components

## Rules

1. Make accessible usage the easiest component API.
2. Prefer progressive enhancement and useful light DOM fallback.
3. Keep semantic reading order correct with slots and DOM order.
4. Avoid brittle cross-root ARIA assumptions.
5. Validate required labels, titles, and relationships at runtime where useful.
6. Test manually because scanners vary in Shadow DOM coverage.

## Checklist

```markdown
Web component checklist

- [ ] Component has usable fallback or failure mode
- [ ] Slot order supports semantic reading order
- [ ] Required accessibility inputs are documented and enforced
- [ ] Focus delegation behavior is intentional
- [ ] ARIA relationships do not depend on unsupported cross-root references
- [ ] Automation is paired with keyboard and screen reader smoke checks
```

## Output

Document component contract, Shadow DOM constraints, focus behavior, and manual verification notes.
