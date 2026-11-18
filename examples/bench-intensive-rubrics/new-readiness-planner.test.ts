import { describe, expect, it } from "vitest"
import { evaluateReadiness, validateDelegationCard } from "./src/readiness"

describe("new-readiness-planner rubric", () => {
  it("scores all 5 checklist items out of 100 and lists missing items", () => {
    const full = evaluateReadiness({
      projectIdea: true,
      laptopCharger: true,
      githubRepo: true,
      workflowPlan: true,
      agentQuestions: true,
    })
    expect(full.ok).toBe(true)
    if (full.ok) {
      expect(full.data.ready).toBe(true)
      expect(full.data.score).toBe(100)
      expect(full.data.missing).toEqual([])
    }

    const partial = evaluateReadiness({
      projectIdea: true,
      laptopCharger: true,
      githubRepo: false,
      workflowPlan: true,
      agentQuestions: false,
    })
    expect(partial.ok).toBe(true)
    if (partial.ok) {
      expect(partial.data.ready).toBe(false)
      expect(partial.data.score).toBe(60)
      expect(partial.data.missing.length).toBe(2)
    }
  })

  it("rejects path traversal and shell injection in delegation cards with ERR_UNSAFE_TARGET_PATH", () => {
    for (const bad of ["../secrets.env", "src/app.ts; rm -rf /", "src/a.ts && whoami", "src/a.ts | cat"]) {
      const res = validateDelegationCard({ title: "Task", targetPath: bad })
      expect(res.ok).toBe(false)
      if (!res.ok) expect(res.error_code).toBe("ERR_UNSAFE_TARGET_PATH")
    }
    const ok = validateDelegationCard({ title: "Build UI", targetPath: "src/components/Board.tsx" })
    expect(ok.ok).toBe(true)
  })
})
