---
name: security-standards
description: "URL protocol allowlisting, ERR_UNSAFE_URL, ERR_UNSAFE_TARGET_PATH, sanitizeLinkHref, and isSafeWikilinkTarget."
---

# Project Security & Input Sanitization Standards

1. **Registration Repo URLs (`src/registration.ts`):** Reject `javascript:`, `data:`, `vbscript:`, or non-`https://` repo URLs with `{ ok: false, error_code: "ERR_UNSAFE_URL" }`.
2. **Delegation Target Paths (`src/readiness.ts`):** Reject target paths containing `..`, null bytes, `;`, `|`, `&`, or `$()` with `{ ok: false, error_code: "ERR_UNSAFE_TARGET_PATH" }`.
3. **Simple Write Links (`src/lib/documents.ts` & editor):**
   - Export `sanitizeLinkHref(raw: string): string | null`: trim input, reject empty, control chars, `javascript:`, `vbscript:`, and `data:text/html` (case-insensitive); allow `https://`, `http://`, `mailto:`, and `#` anchors.
   - Export `isSafeWikilinkTarget(target: string): boolean`: return `false` if empty or contains `..`, `/`, `\\`, or `\0`.
   - Guard `applyLink` in `src/components/write-editor.tsx` and `openLinked` in `src/App.tsx` using these helpers.
