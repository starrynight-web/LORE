---
type: skill
id: skill:accessibility-engineer/web-a11y-orchestrator@v1
title: web a11y orchestrator
persona: persona:accessibility-engineer
status: draft
summary: Central routing and orchestration skill for web accessibility work. Use as
  the default entrypoint for accessibility-related UI tasks to select the right authori
---
# Web A11y Orchestrator

## Goal

Coordinate accessible UI work from scope discovery through implementation, review, remediation, and validation.

## Routing Map

- New pages, app shells, semantic structure -> `web-a11y-authoring`, `web-a11y-navigation`, `web-a11y-css`
- Components, controls, overlays, custom interactions -> `web-a11y-authoring`, `web-a11y-css`
- Links, downloads, external destinations, images, SVG, media -> `web-a11y-authoring`, `web-a11y-testing`
- Forms, validation, search, multi-step flows -> `web-a11y-forms`
- Navigation, landmarks, breadcrumbs, skip links, menus -> `web-a11y-navigation`
- Filtering, sorting, pagination, live updates, tables -> `web-a11y-dynamic-ui`
- Styling, focus, contrast, motion, zoom, forced colors -> `web-a11y-css`
- Web components or Shadow DOM -> `web-a11y-web-components`
- Audits, triage, CI, DevTools, custom checks -> `web-a11y-debugging`, `web-a11y-review`, `web-a11y-testing`

## Workflow

```markdown
A11y workflow

- [ ] Define scope and changed user journeys
- [ ] Select relevant skill passes from routing map
- [ ] Implement semantic-first UI
- [ ] Review for accessibility defects and missing tests
- [ ] Remediate Critical/High issues
- [ ] Validate with automation, keyboard, and screen reader smoke checks
```

## Severity Policy

- Critical: blocks core task completion for keyboard or assistive technology users.
- High: creates major confusion, lost state, or unreliable operation.
- Medium: degrades usability but has a workable path.
- Low: polish, consistency, or non-blocking robustness improvement.

## Public References

Use public references for deeper decisions:

- W3C WCAG
- WAI Tutorials
- WAI-ARIA Authoring Practices Guide
- MDN Web Docs
- WebAIM
- axe documentation and browser DevTools accessibility docs

## Output

End with:

```markdown
Accessibility report

Scope:
- <pages/components/journeys>

Passes run:
- <skills/checks>

Blocking issues:
- <severity> <issue> <status>

Verification:
- Automated: pass/fail/not run
- Keyboard: pass/fail/not run
- Screen reader smoke: pass/fail/not run

Decision:
- Ready | Needs remediation | Needs follow-up
```
