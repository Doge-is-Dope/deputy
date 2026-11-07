import { describe, expect, it, vi } from "vitest"

import type { Conversation, RunSummary } from "@/lib/api"
import { conversationOf, merged, nameOf, sectionsOf } from "@/lib/conversations"

vi.mock("@/lib/i18n", async () => {
  const { en } = await import("@/locales/en")
  return { t: () => en, locale: () => "en" }
})

const run = (over: Partial<RunSummary>): RunSummary => ({
  id: "r1",
  thread: "r1",
  kind: "turn",
  session: "r1",
  parent: null,
  goal: "Open Notepad and type hello",
  title: null,
  started: 1,
  actions: 0,
  ended: 2,
  failed: false,
  project: null,
  ...over,
})

const conversation = (over: Partial<Conversation>): Conversation => ({
  id: "r1",
  project: null,
  title: null,
  goal: "Open Notepad and type hello",
  last: 1,
  latest: run({}),
  ...over,
})

describe("the sidebar's sections", () => {
  it("lists each project's conversations under it, and the rest as recents, in the order given", () => {
    const { projects, recents } = sectionsOf([
      conversation({ id: "r5", last: 5, project: "probe" }),
      conversation({ id: "r1", last: 4, project: "eval" }),
      conversation({ id: "r3", last: 3, project: "eval" }),
      conversation({ id: "r2", last: 2 }),
    ])
    expect(
      projects.map(([name, items]) => [name, items.map((c) => c.id)])
    ).toEqual([
      ["probe", ["r5"]],
      ["eval", ["r1", "r3"]],
    ])
    expect(recents.map((c) => c.id)).toEqual(["r2"])
  })
})

describe("a conversation's name", () => {
  it("is its first message until it has a title", () => {
    const unnamed = conversation({})
    expect(nameOf(unnamed)).toBe("Open Notepad and type hello")
    expect(nameOf(conversation({ title: "Typing in Notepad" }))).toBe(
      "Typing in Notepad"
    )
    expect(nameOf(conversation({ goal: "" }))).toBe("r1")
  })
})

describe("the lists in one", () => {
  it("has each conversation once, as the list loaded last has it, most recently active first", () => {
    const all = merged([
      [
        conversation({ id: "r1", last: 1 }),
        conversation({ id: "r2", last: 2 }),
      ],
      [
        conversation({ id: "r2", last: 2, project: "eval" }),
        conversation({ id: "r3", last: 3 }),
      ],
    ])
    expect(all.map((c) => [c.id, c.project])).toEqual([
      ["r3", null],
      ["r2", "eval"],
      ["r1", null],
    ])
  })
})

describe("a conversation from its runs", () => {
  it("is what the list shows for it: the first run's message and project, the latest title and run", () => {
    const first = run({ id: "r1", project: "eval", title: "Notepad" })
    const second = run({
      id: "r2",
      goal: "and save it",
      started: 3,
      ended: null,
      title: null,
    })
    expect(conversationOf([first, second])).toEqual({
      id: "r1",
      project: "eval",
      title: "Notepad",
      goal: "Open Notepad and type hello",
      last: 3,
      latest: second,
    })
    expect(conversationOf([])).toBeNull()
  })
})
