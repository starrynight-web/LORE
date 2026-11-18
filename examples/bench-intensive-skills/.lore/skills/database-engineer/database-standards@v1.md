---
type: skill
id: skill:database-engineer/database-standards@v1
title: Project Database & Schema Versioning Standards
persona: persona:database-engineer
status: stable
summary: 'Record schema_version: 1, registration status enum, and venue redaction
  persistence rules.'
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
    claims_unverifiable: 9
tags:
- database
- schema
- registration
- persistence
- venue
- approval
- storage
---
# Project Database & Schema Versioning Standards

1. Every persisted registration record created by `submitRegistration` must include `schema_version: 1`.
2. Registration status must start as `"pending_approval"` and transition only via `reviewRegistration` to `"approved"` or `"rejected"`.
3. `getVenueInfo(record)` must return `exactAddress: "Revealed after host approval"` whenever `record.status !== "approved"`.
