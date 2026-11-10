import { describe, expect, it, vi } from "vitest"
import type { Conversation, Project, RunSummary } from "@/lib/api"
import { ConversationLists } from "@/lib/conversation-lists"
import { merged } from "@/lib/conversations"

vi.mock("@/lib/choices", () => ({ currentChoices: () => ({}) }))
vi.mock("@/lib/i18n", () => ({ locale: () => "en" }))

function fixture() {
  const projects: Project[] = [
    { id: "p1", name: "One", created: 1 },
    { id: "p2", name: "Two", created: 2 },
  ]
  const items = Array.from(
    { length: 140 },
    (_, n) => ({ id: String(n), last: 140 - n }) as Conversation
  )
  const source = {
    projects: vi.fn(async () => projects),
    runsOf: vi.fn(
      async (thread: string) =>
        [
          { id: thread, thread, kind: "turn", ended: null },
          { id: "task", thread, kind: "task", ended: null },
        ] as RunSummary[]
    ),
    conversations: vi.fn(
      async ({
        before,
        limit = 20,
      }: {
        project?: string | null
        before?: string | null
        limit?: number
      } = {}) => {
        const start = Number(before ?? 0)
        const end = Math.min(start + limit, items.length)
        return {
          items: items.slice(start, end),
          next: end < items.length ? String(end) : null,
        }
      }
    ),
  }
  return { source, loader: new ConversationLists(source), items, projects }
}

describe("lazy conversation lists", () => {
  it("fetches only recents until a project opens, and caches its first page", async () => {
    const { source, loader } = fixture()
    await loader.refresh()
    expect(source.conversations.mock.calls.map(([q]) => q?.project)).toEqual([
      null,
      undefined,
    ])
    const first = loader.read("p1")
    loader.read("p1")
    await first
    expect(loader.get().pages?.get("p1")?.items).toHaveLength(5)
    await loader.read("p1")
    expect(source.conversations).toHaveBeenCalledTimes(3)
    await loader.refresh()
    expect(source.conversations.mock.calls.map(([q]) => q?.project)).toEqual([
      null,
      undefined,
      "p1",
      null,
      undefined,
      "p1",
    ])
  })
  it("serializes expansion with refresh and pagination without duplicating rows", async () => {
    const { loader, items } = fixture()
    const refreshing = loader.refresh()
    const reading = loader.read("p1")
    await Promise.all([refreshing, reading])
    const more = loader.load("p1")
    loader.load("p1")
    await more
    expect(loader.get().pages?.get("p1")?.items).toEqual(items.slice(0, 10))
    await loader.refresh()
    expect(loader.get().pages?.get("p1")?.items).toEqual(items.slice(0, 10))
  })
  it("loads opened lists together, and refreshes only once they are in", async () => {
    const { source, loader } = fixture()
    const fetch = source.conversations.getMockImplementation()!
    const order: string[] = []
    source.conversations.mockImplementation(async (query) => {
      order.push(`${query?.project} asked`)
      await new Promise((resolve) => setTimeout(resolve))
      order.push(`${query?.project} answered`)
      return fetch(query)
    })
    await loader.refresh()
    order.length = 0
    const reads = [loader.read("p1"), loader.read("p2")]
    const refreshed = loader.refresh()
    await Promise.all([...reads, refreshed])
    expect(order.slice(0, 5)).toEqual([
      "p1 asked",
      "p2 asked",
      "p1 answered",
      "p2 answered",
      "null asked",
    ])
    expect(loader.get().pages?.get("p1")?.items).toHaveLength(5)
    expect(loader.get().pages?.get("p2")?.items).toHaveLength(5)
  })
  it("asks for the recents together with the project names", async () => {
    const { source, loader, projects } = fixture()
    let answer: (projects: Project[]) => void = () => {}
    source.projects.mockReturnValueOnce(
      new Promise((resolve) => (answer = resolve))
    )
    const refreshed = loader.refresh()
    await new Promise((resolve) => setTimeout(resolve))
    expect(source.conversations.mock.calls.map(([q]) => q?.project)).toEqual([
      null,
      undefined,
    ])
    answer(projects)
    await refreshed
    expect(loader.get().projects).toEqual(projects)
    expect(loader.get().pages?.get(null)?.items).toHaveLength(20)
  })
  it("reads the latest conversations in any project with each refresh, a page only", async () => {
    const { source, loader, items } = fixture()
    await loader.refresh()
    expect(loader.get().latest).toEqual(items.slice(0, 20))
    await loader.load(null)
    expect(
      source.conversations.mock.calls.filter(([q]) => q?.project === undefined)
    ).toHaveLength(1)
    items.shift()
    await loader.refresh()
    expect(loader.get().latest).toEqual(items.slice(0, 20))
  })
  it("reads a running conversation by itself only when no list holds it", async () => {
    const { source, loader } = fixture()
    await loader.refresh(["0", "19"])
    expect(source.runsOf).not.toHaveBeenCalled()
    await loader.refresh(["far"])
    expect(source.runsOf.mock.calls).toEqual([["far"]])
    expect(loader.get().beyond.map((each) => each.id)).toEqual(["far"])
  })
  it("reads it once more as it ends, then keeps it without reading", async () => {
    const { source, loader } = fixture()
    await loader.refresh(["far"])
    source.runsOf.mockResolvedValueOnce([
      { id: "far", thread: "far", kind: "turn", ended: 9 },
    ] as RunSummary[])
    await loader.refresh([])
    expect(source.runsOf).toHaveBeenCalledTimes(2)
    expect(loader.get().beyond[0].latest.ended).toBe(9)
    await loader.refresh([])
    await loader.refresh()
    expect(source.runsOf).toHaveBeenCalledTimes(2)
    expect(loader.get().beyond.map((each) => each.id)).toEqual(["far"])
  })
  it("lets go of one a list holds again, and survives one it cannot read", async () => {
    const { source, loader, items } = fixture()
    await loader.refresh(["far"])
    items.unshift({ id: "far", last: 999 } as Conversation)
    await loader.refresh()
    expect(loader.get().beyond).toEqual([])
    source.runsOf.mockRejectedValueOnce(new Error("gone"))
    await loader.refresh(["lost"])
    expect(loader.get().failed).toBe(false)
    expect(loader.get().beyond).toEqual([])
  })
  it("preserves more than MAX_PAGE loaded rows through a refresh", async () => {
    const { loader, items } = fixture()
    await loader.refresh()
    for (let n = 0; n < 6; n++) await loader.load(null)
    await loader.refresh()
    expect(loader.get().pages?.get(null)?.items).toEqual(items)
    expect(loader.get().pages?.get(null)?.next).toBeNull()
  })
  it("appends older conversations below the existing rows after merging pages", async () => {
    const { loader, items } = fixture()
    await loader.refresh()
    await loader.read("p1")
    const first = loader.get().pages!.get("p1")!.items
    await loader.load("p1")
    const shown = merged([loader.get().pages!.get("p1")!.items])
    expect(shown.slice(0, 5)).toEqual(first)
    expect(shown.slice(5)).toEqual(items.slice(5, 10))
  })
  it("stops retrying a failed next page when refresh has reached the new end", async () => {
    const { source, loader, items } = fixture()
    await loader.refresh()
    await loader.read("p1")
    source.conversations.mockRejectedValueOnce(new Error("offline"))
    await loader.load("p1")
    expect(loader.get().errors.has("p1")).toBe(true)
    items.splice(3)
    await loader.refresh()
    expect(loader.get().pages!.get("p1")!.items).toEqual(items)
    expect(loader.get().pages!.get("p1")!.next).toBeNull()
    expect(loader.get().errors.has("p1")).toBe(false)
  })
  it("keeps a failed next page pending through refresh while older rows remain", async () => {
    const { source, loader, items } = fixture()
    await loader.refresh()
    await loader.read("p1")
    source.conversations.mockRejectedValueOnce(new Error("offline"))
    await loader.load("p1")
    await loader.refresh()
    expect(loader.get().errors.has("p1")).toBe(true)
    await loader.load("p1")
    expect(loader.get().pages!.get("p1")!.items).toEqual(items.slice(0, 10))
    expect(loader.get().errors.has("p1")).toBe(false)
  })
  it("keeps existing lists on refresh failure and retries an unsuccessful expansion", async () => {
    const { source, loader } = fixture()
    await loader.refresh()
    const before = loader.get().pages
    source.projects.mockRejectedValueOnce(new Error("offline"))
    await loader.refresh()
    expect(loader.get().pages).toBe(before)
    expect(loader.get().failed).toBe(true)
    source.conversations.mockRejectedValueOnce(new Error("offline"))
    await loader.read("p1")
    expect(loader.get().errors.has("p1")).toBe(true)
    expect(loader.get().loading.has("p1")).toBe(false)
    await loader.read("p1")
    expect(loader.get().pages?.has("p1")).toBe(true)
    expect(loader.get().errors.has("p1")).toBe(false)
  })
  it("drops deleted projects and ignores queued requests for them", async () => {
    const { source, loader, projects } = fixture()
    await loader.refresh()
    await loader.read("p1")
    source.projects.mockResolvedValueOnce(projects.slice(1))
    const refresh = loader.refresh()
    const more = loader.load("p1")
    await Promise.all([refresh, more])
    expect(loader.get().pages?.has("p1")).toBe(false)
    expect(loader.get().loading.has("p1")).toBe(false)
    expect(
      source.conversations.mock.calls.filter(([q]) => q?.project === "p1")
    ).toHaveLength(1)
  })
})
