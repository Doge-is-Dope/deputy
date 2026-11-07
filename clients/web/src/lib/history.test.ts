import { describe, expect, it } from "vitest"
import { historyStart } from "@/lib/history"

describe("conversation history windows", () => {
  const runs = Array.from({ length: 35 }, (_, n) => String(n))
  it("opens only the latest ten turns, including short or missing histories", () => {
    expect(runs.slice(historyStart(runs, null))).toEqual(runs.slice(25))
    expect(historyStart(runs.slice(0, 4), null)).toBe(0)
    expect(historyStart([], null)).toBe(0)
  })
  it("keeps older turns loaded when new turns arrive", () => {
    const newer = [...runs, "35", "36"]
    expect(newer.slice(historyStart(newer, "15"))).toEqual(newer.slice(15))
  })
  it("can restore a previously loaded range and handles a missing boundary", () => {
    expect(historyStart(runs, "5")).toBe(5)
    expect(historyStart(runs, "gone")).toBe(25)
  })
})
