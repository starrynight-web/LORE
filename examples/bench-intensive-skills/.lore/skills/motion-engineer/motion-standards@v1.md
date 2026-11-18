---
type: skill
id: skill:motion-engineer/motion-standards@v1
title: Project Motion & Reduced-Motion Standards
persona: persona:motion-engineer
status: stable
summary: Enforce data-motion-policy='respect-reduced-motion' on interactive boards
  and find bars.
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
    status: current
    verified_at: null
    claims_ok: 0
    claims_stale: []
    claims_unverifiable: 3
tags:
- motion
- animation
- reduced-motion
- sprintboard
- find
- board
- ui
---
# Project Motion & Reduced-Motion Standards

1. Every interactive animated surface (`SprintBoard` root and the desktop Find bar container) must carry `data-motion-policy="respect-reduced-motion"`.
2. Avoid non-composited layout animations; prefer CSS opacity/transform transitions gated by `motion-safe:`.
