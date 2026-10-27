import { describe, expect, it } from "vitest"

import { bend, SIZE } from "@/lib/liquid-glass"

describe("bend", () => {
  it("bends nothing in the flat middle, and more and more towards the edge", () => {
    expect(bend(10)).toBe(0)
    expect(bend(4)).toBeGreaterThan(0)
    expect(bend(0)).toBeGreaterThan(bend(2))
    expect(bend(2)).toBeGreaterThan(bend(4))
  })

  it("never shows the page from beyond the middle, which would turn it over", () => {
    for (let edge = 0; edge < SIZE / 2; edge += 0.01)
      expect(bend(edge)).toBeLessThan(SIZE / 2 - edge)
  })
})
