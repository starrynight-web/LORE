import fs from "node:fs"
import path from "node:path"
import { describe, expect, it } from "vitest"

describe("old-find-a11y rubric", () => {
  it("adds accessible search landmark, motion policy, and polite match-count live region to App.tsx", () => {
    const appSource = fs.readFileSync(path.resolve(import.meta.dirname, "./src/App.tsx"), "utf-8")
    expect(appSource).toContain('role="search"')
    expect(appSource).toContain('aria-label="Find in document"')
    expect(appSource).toContain('data-motion-policy="respect-reduced-motion"')
    expect(appSource).toContain('aria-live="polite"')
    expect(appSource).toContain('data-find-status="match-count"')
    expect(appSource).toContain("No matches")
    expect(appSource).toContain("matches")
  })
})
