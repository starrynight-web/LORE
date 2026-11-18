---
name: database-standards
description: "Record schema_version: 1, registration status enum, and venue redaction persistence rules."
---

# Project Database & Schema Versioning Standards

1. Every persisted registration record created by `submitRegistration` must include `schema_version: 1`.
2. Registration status must start as `"pending_approval"` and transition only via `reviewRegistration` to `"approved"` or `"rejected"`.
3. `getVenueInfo(record)` must return `exactAddress: "Revealed after host approval"` whenever `record.status !== "approved"`.
