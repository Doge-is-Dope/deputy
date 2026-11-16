import { describe, expect, it } from "vitest"

import type { Conversation, SearchHit } from "@/lib/api"
import { marked, sureHits } from "@/lib/search"

const conversation = (id: string, title: string, last: number) =>
  ({ id, title, goal: "", last, project: null }) as Conversation

describe("marking matches", () => {
  it("marks each match, ignoring case, and reads the query as plain text", () => {
    expect(marked("Notepad, then notepad", "NOTE")).toEqual([
      { text: "Note", match: true },
      { text: "pad, then ", match: false },
      { text: "note", match: true },
      { text: "pad", match: false },
    ])
    expect(marked("a (b) c", "(b)")).toEqual([
      { text: "a ", match: false },
      { text: "(b)", match: true },
      { text: " c", match: false },
    ])
  })
})

describe("what a search shows until its answer is in", () => {
  const report = conversation("a", "Export report", 3)
  const notes = conversation("b", "Notes", 2)
  const order = conversation("c", "Submit order", 1)
  const earlier: SearchHit[] = [
    { conversation: order, snippet: "…then report the reference" },
    { conversation: report, snippet: "…the March table" },
  ]

  it("lists loaded conversations named so, latest first", () => {
    expect(sureHits(" REPORT ", [order, notes, report], [])).toEqual([
      { conversation: report, snippet: null },
    ])
  })

  it("keeps earlier hits that still match, and drops a snippet that no longer does", () => {
    expect(sureHits("repo", [notes], earlier)).toEqual([
      { conversation: report, snippet: null },
      { conversation: order, snippet: "…then report the reference" },
    ])
    expect(sureHits("reports", [notes], earlier)).toEqual([])
  })
})
