import { describe, expect, it } from "vitest"

import type { RunSummary } from "@/lib/api"
import { conversationsOf } from "@/lib/conversations"
import { found, marked } from "@/lib/search"

const run = (over: Partial<RunSummary>): RunSummary => ({
  id: "r1",
  thread: "r1",
  goal: "Open Notepad",
  title: null,
  started: 1,
  actions: 0,
  ended: 2,
  failed: false,
  project: null,
  user: "local",
  ...over,
})

const conversations = conversationsOf([
  run({ id: "r1", thread: "r1", started: 1, title: "Notepad 會議紀錄" }),
  run({ id: "r2", thread: "r2", started: 2, goal: "tidy the desktop" }),
  run({ id: "r3", thread: "r3", started: 3, goal: "open the calculator" }),
])
const ids = (list: ReturnType<typeof found>) =>
  list.map(({ conversation, snippet }) => [conversation.id, snippet])

describe("finding conversations", () => {
  it("lists those it names first, then those only their words hold, in the runtime's order", () => {
    const hits = [
      { thread: "r3", snippet: "…notepad is open" },
      { thread: "r1", snippet: "Open Notepad" }, // named already
      { thread: "r2", snippet: "Open Notepad" }, // by its first message, which is not its name
      { thread: "gone", snippet: "notepad" }, // not in the list (deleted meanwhile)
    ]
    expect(ids(found(conversations, " NOTEPAD ", hits))).toEqual([
      ["r1", undefined],
      ["r3", "…notepad is open"],
      ["r2", "Open Notepad"],
    ])
  })

  it("lists the named ones alone while the runtime's answer is on its way, and every one for no query", () => {
    expect(ids(found(conversations, "會議", null))).toEqual([["r1", undefined]])
    expect(found(conversations, "  ", null)).toHaveLength(3)
  })

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
