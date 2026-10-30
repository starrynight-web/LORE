---
type: skill
id: skill:accessibility-engineer/web-a11y-authoring@v1
title: web a11y authoring
persona: persona:accessibility-engineer
status: stable
summary: Builds accessible pages and components with semantic HTML, correct names/roles/states,
  keyboard support, focus management, links, images, SVG, media, and native
---
# Web A11y Authoring

## Core Rules

For concrete markup patterns, see [PATTERNS.md](PATTERNS.md).

1. Prefer native HTML controls before ARIA or custom widgets.
2. Use links for navigation and buttons for actions.
3. Ensure every interactive control has a clear accessible name.
4. Keep DOM order aligned with reading and interaction order.
5. Preserve visible focus and keyboard operation for every interaction.
6. Use ARIA only to supplement semantics that cannot be expressed natively.
7. Classify images, icons, and SVG as decorative, informative, or functional.
8. Communicate unusual link behavior before activation.

## Authoring Checklist

```markdown
Authoring checklist

- [ ] Page has meaningful title, language, landmarks, and heading structure
- [ ] Controls expose role, name, state, and value correctly
- [ ] Interactions work with keyboard alone
- [ ] Focus is visible, logical, and intentionally managed
- [ ] Hidden content is not accidentally focusable or announced
- [ ] Native control behavior is preserved under custom styling
- [ ] Links describe destination/action, including downloads and context changes
- [ ] Images, SVG, and icons have appropriate text alternatives or are hidden correctly
- [ ] Audio/video has controls and alternatives such as captions or transcripts when needed
```

## Common Patterns

- Toggle button: native `button` with synchronized state such as `aria-pressed`.
- Disclosure: button with synchronized `aria-expanded` and hidden content state.
- Dialog: intentional initial focus, contained interaction while open, focus restored on close.
- Icon-only control: visible or programmatic accessible name that describes the action.
- Download/file link: link text includes action, target, file type, and size when useful.
- Functional image/SVG: accessible name describes the action or destination.
- Decorative image/SVG: removed from the accessibility tree without hiding useful text.
- Media: avoid disruptive autoplay, provide controls, and include captions/transcripts when content requires them.

## Output

Describe semantic choices, ARIA states used, non-text content decisions, keyboard behavior, and manual test plan.
