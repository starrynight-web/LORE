import { describe, expect, it } from "vitest"
import * as docs from "./src/lib/documents"

describe("old-security-links rubric", () => {
  it("exports sanitizeLinkHref and blocks unsafe schemes", () => {
    const sanitizeLinkHref = (docs as Record<string, unknown>).sanitizeLinkHref as
      | ((raw: string) => string | null)
      | undefined
    expect(typeof sanitizeLinkHref).toBe("function")
    if (!sanitizeLinkHref) return

    expect(sanitizeLinkHref("https://example.com/docs")).toBe("https://example.com/docs")
    expect(sanitizeLinkHref("http://localhost:3000")).toBe("http://localhost:3000")
    expect(sanitizeLinkHref("mailto:test@example.com")).toBe("mailto:test@example.com")
    expect(sanitizeLinkHref("#section-1")).toBe("#section-1")
    expect(sanitizeLinkHref("javascript:alert(1)")).toBeNull()
    expect(sanitizeLinkHref("JAVASCRIPT:alert(1)")).toBeNull()
    expect(sanitizeLinkHref("vbscript:msgbox(1)")).toBeNull()
    expect(sanitizeLinkHref("data:text/html,<script>alert(1)</script>")).toBeNull()
    expect(sanitizeLinkHref("")).toBeNull()
  })

  it("exports isSafeWikilinkTarget and blocks traversal", () => {
    const isSafeWikilinkTarget = (docs as Record<string, unknown>).isSafeWikilinkTarget as
      | ((target: string) => boolean)
      | undefined
    expect(typeof isSafeWikilinkTarget).toBe("function")
    if (!isSafeWikilinkTarget) return

    expect(isSafeWikilinkTarget("meeting-notes")).toBe(true)
    expect(isSafeWikilinkTarget("../secret")).toBe(false)
    expect(isSafeWikilinkTarget("sub/note")).toBe(false)
    expect(isSafeWikilinkTarget("sub\\note")).toBe(false)
    expect(isSafeWikilinkTarget("")).toBe(false)
  })
})
