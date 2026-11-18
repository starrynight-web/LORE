---
type: skill
id: skill:security-engineer/security-standards@v1
title: Project Security & Input Sanitization Standards
persona: persona:security-engineer
status: stable
summary: URL protocol allowlisting, ERR_UNSAFE_URL, ERR_UNSAFE_TARGET_PATH, sanitizeLinkHref,
  and isSafeWikilinkTarget.
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
    - src/registration.ts
    - src/readiness.ts
    - src/lib/documents.ts
    - data:text/html
    - \0
    - src/components/write-editor.tsx
    - src/App.tsx
    claims_unverifiable: 21
tags:
- security
- sanitize
- url
- wikilink
- links
- traversal
- registration
- readiness
---
# Project Security & Input Sanitization Standards

1. **Registration Repo URLs (`src/registration.ts`):** Reject `javascript:`, `data:`, `vbscript:`, or non-`https://` repo URLs with `{ ok: false, error_code: "ERR_UNSAFE_URL" }`.
2. **Delegation Target Paths (`src/readiness.ts`):** Reject target paths containing `..`, null bytes, `;`, `|`, `&`, or `$()` with `{ ok: false, error_code: "ERR_UNSAFE_TARGET_PATH" }`.
3. **Simple Write Links (`src/lib/documents.ts` & editor):**
   - Export `sanitizeLinkHref(raw: string): string | null`: trim input, reject empty, control chars, `javascript:`, `vbscript:`, and `data:text/html` (case-insensitive); allow `https://`, `http://`, `mailto:`, and `#` anchors.
   - Export `isSafeWikilinkTarget(target: string): boolean`: return `false` if empty or contains `..`, `/`, `\\`, or `\0`.
   - Guard `applyLink` in `src/components/write-editor.tsx` and `openLinked` in `src/App.tsx` using these helpers.
