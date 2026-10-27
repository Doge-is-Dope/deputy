import { describe, expect, it, vi } from "vitest"

import type { RunSummary } from "@/lib/api"
import { conversationsOf, nameOf, sectionsOf } from "@/lib/conversations"

vi.mock("@/lib/i18n", async () => {
  const { en } = await import("@/locales/en")
  return { t: () => en, locale: () => "en" }
})

const run = (over: Partial<RunSummary>): RunSummary => ({
  id: "r1",
  thread: "r1",
  goal: "Open Notepad and type hello",
  title: null,
  started: 1,
  actions: 0,
  ended: 2,
  failed: false,
  project: null,
  user: "local",
  ...over,
})

describe("the sidebar's sections", () => {
  it("lists each project's conversations under it, by its first run, and the rest as recents", () => {
    const { projects, recents } = sectionsOf(
      conversationsOf([
        run({ id: "r1", thread: "r1", started: 1, project: "eval" }),
        run({ id: "r2", thread: "r2", started: 2 }),
        run({ id: "r3", thread: "r3", started: 3, project: "eval" }),
        run({ id: "r4", thread: "r1", started: 4 }), // continued from the page: still the eval's
        run({ id: "r5", thread: "r5", started: 5, project: "probe" }),
      ])
    )
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
  it("is its first message until a run of it carries a title, whichever run that is", () => {
    const [unnamed] = conversationsOf([run({})])
    expect(unnamed.title).toBeNull()
    expect(nameOf(unnamed)).toBe("Open Notepad and type hello")

    const [named] = conversationsOf([
      run({ id: "r2", started: 3, title: "Typing in Notepad", goal: "again" }),
      run({}),
    ])
    expect(named.title).toBe("Typing in Notepad")
    expect(nameOf(named)).toBe("Typing in Notepad")
  })

  it("is the latest run's title, where the user renamed it after the runtime named it", () => {
    const [renamed] = conversationsOf([
      run({ title: "Typing in Notepad" }),
      run({ id: "r2", started: 3, title: "Notepad notes", goal: "again" }),
      run({ id: "r3", started: 4, goal: "and again" }),
    ])
    expect(renamed.title).toBe("Notepad notes")
  })
})
