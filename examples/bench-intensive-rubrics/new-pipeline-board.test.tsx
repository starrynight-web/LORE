import { act } from "react"
import { createRoot } from "react-dom/client"
import { describe, expect, it } from "vitest"
import { SprintBoard } from "./src/SprintBoard"

describe("new-pipeline-board rubric", () => {
  it("renders 6 stages with data-surface, motion policy, ARIA tablist, keyboard nav, and live region", async () => {
    const container = document.createElement("div")
    document.body.appendChild(container)
    const root = createRoot(container)

    await act(async () => {
      root.render(<SprintBoard />)
    })

    const surface = container.querySelector('[data-surface="devin-dhaka-board"]')
    expect(surface).toBeTruthy()
    const motion = container.querySelector('[data-motion-policy="respect-reduced-motion"]')
    expect(motion).toBeTruthy()

    const tablist = container.querySelector('[role="tablist"]')
    expect(tablist).toBeTruthy()
    const tabs = Array.from(container.querySelectorAll<HTMLElement>('[role="tab"]'))
    expect(tabs.length).toBe(6)
    expect(tabs[0]?.getAttribute("aria-selected")).toBe("true")

    const live = container.querySelector('[aria-live="polite"][data-stage-live]')
    expect(live?.textContent).toContain("Current stage: Brainstorming")

    await act(async () => {
      tabs[0]?.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }))
    })
    expect(tabs[1]?.getAttribute("aria-selected")).toBe("true")
    expect(live?.textContent).toContain("Current stage: Planning")

    await act(async () => {
      tabs[1]?.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowLeft", bubbles: true }))
    })
    expect(tabs[0]?.getAttribute("aria-selected")).toBe("true")

    await act(async () => {
      root.unmount()
    })
    container.remove()
  })
})
