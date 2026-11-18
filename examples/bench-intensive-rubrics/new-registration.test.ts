import { describe, expect, it } from "vitest"
import { getVenueInfo, reviewRegistration, submitRegistration } from "./src/registration"

describe("new-registration rubric", () => {
  it("creates a pending_approval registration with schema_version 1", () => {
    const res = submitRegistration({
      name: "Amina Rahman",
      email: "amina@example.com",
      repoUrl: "https://github.com/amina/dhaka-demo",
    })
    expect(res.ok).toBe(true)
    if (!res.ok) return
    expect(res.data.status).toBe("pending_approval")
    expect(res.data.schema_version).toBe(1)
  })

  it("rejects unsafe repo URLs with ERR_UNSAFE_URL", () => {
    for (const bad of ["javascript:alert(1)", "data:text/html,hi", "http://insecure.example.com"]) {
      const res = submitRegistration({
        name: "Test",
        email: "test@example.com",
        repoUrl: bad,
      })
      expect(res.ok).toBe(false)
      if (!res.ok) expect(res.error_code).toBe("ERR_UNSAFE_URL")
    }
  })

  it("redacts exact venue address until host approval", () => {
    const created = submitRegistration({ name: "Test", email: "t@example.com" })
    expect(created.ok).toBe(true)
    if (!created.ok) return

    const pendingVenue = getVenueInfo(created.data, "North End Roastery, Banani Road 11")
    expect(pendingVenue.ok).toBe(true)
    if (pendingVenue.ok) {
      expect(pendingVenue.data.date).toBe("2026-11-21")
      expect(pendingVenue.data.schedule).toBe("16:00-18:00 BST (UTC+6)")
      expect(pendingVenue.data.area).toBe("North End, Dhaka")
      expect(pendingVenue.data.exactAddress).toBe("Revealed after host approval")
    }

    const approved = reviewRegistration(created.data, "approved")
    expect(approved.ok).toBe(true)
    if (!approved.ok) return
    expect(approved.data.status).toBe("approved")

    const approvedVenue = getVenueInfo(approved.data, "North End Roastery, Banani Road 11")
    expect(approvedVenue.ok).toBe(true)
    if (approvedVenue.ok) {
      expect(approvedVenue.data.exactAddress).toBe("North End Roastery, Banani Road 11")
    }
  })
})
