import { describe, expect, it } from "vitest"

import { marked } from "@/lib/search"

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
