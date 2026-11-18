import { describe, expect, it } from "vitest"
import * as docs from "./src/lib/documents"
import { insertMenu } from "./src/editor/extensions"

describe("old-reading-callout rubric", () => {
  it("exports readingTime with exact 200 wpm ceiling formula", () => {
    const readingTime = (docs as Record<string, unknown>).readingTime as ((text: string) => number) | undefined
    expect(typeof readingTime).toBe("function")
    if (!readingTime) return
    expect(readingTime("")).toBe(0)
    expect(readingTime("   \n\t  ")).toBe(0)
    expect(readingTime("hello world")).toBe(1)
    expect(readingTime(Array.from({ length: 201 }, () => "word").join(" "))).toBe(2)
  })

  it("registers a Callout block in the slash menu", () => {
    const callout = insertMenu.find((item) => item.id === "callout")
    expect(callout).toBeTruthy()
    expect(callout?.label).toBe("Callout")
  })
})
