---
type: skill
id: skill:backend-engineer/backend-standards@v1
title: Project Backend & API Envelope Standards
persona: persona:backend-engineer
status: stable
summary: Standard `{ ok, data, error_code }` API envelope, Devin-a-thon Dhaka metadata
  constants, and readiness scoring.
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
    - src/readiness.ts
    claims_unverifiable: 19
tags:
- backend
- api
- envelope
- registration
- readiness
- checklist
- planner
- dhaka
---
# Project Backend & API Envelope Standards

1. **Result Envelope:** All service functions return `{ ok: true, data: T }` on success or `{ ok: false, error_code: string, message?: string }` on failure.
2. **Devin-a-thon Dhaka Event Constants:**
   - `date`: `"2026-11-21"`
   - `schedule`: `"16:00-18:00 BST (UTC+6)"`
   - `area`: `"North End, Dhaka"`
3. **Readiness Planner (`src/readiness.ts`):**
   - Evaluate the 5 preparation items (`projectIdea`, `laptopCharger`, `githubRepo`, `workflowPlan`, `agentQuestions`).
   - Return `{ ok: true, data: { ready: boolean, score: number, missing: string[] } }` where `score` is `0..100` (20 points per item) and `ready` is `true` only when `score === 100`.
