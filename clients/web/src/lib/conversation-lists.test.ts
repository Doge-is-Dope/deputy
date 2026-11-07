import { describe, expect, it, vi } from "vitest"
import type { Conversation, Project } from "@/lib/api"
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
    ])
    const first = loader.read("p1")
    loader.read("p1")
    await first
    expect(loader.get().pages?.get("p1")?.items).toHaveLength(5)
    await loader.read("p1")
    expect(source.conversations).toHaveBeenCalledTimes(2)
    await loader.refresh()
    expect(source.conversations.mock.calls.map(([q]) => q?.project)).toEqual([
      null,
      "p1",
      null,
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
    ])
    answer(projects)
    await refreshed
    expect(loader.get().projects).toEqual(projects)
    expect(loader.get().pages?.get(null)?.items).toHaveLength(20)
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
