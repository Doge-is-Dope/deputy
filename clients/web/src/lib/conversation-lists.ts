import {
  MAX_PAGE,
  PROJECT_PAGE,
  type api,
  type Conversation,
  type Page,
  type Project,
} from "@/lib/api"

/** A list the sidebar draws from, a page at a time: a project's (its id), or the recents (null: in no project). */
export type ListKind = string | null

/** How many the recents load at a time, enough to fill the sidebar; a project's list loads PROJECT_PAGE. */
const RECENTS_PAGE = 20

const sizeOf = (kind: ListKind) => (kind === null ? RECENTS_PAGE : PROJECT_PAGE)

type State = {
  projects: Project[] | null
  pages: ReadonlyMap<ListKind, Page<Conversation>> | null
  loading: ReadonlySet<ListKind>
  errors: ReadonlySet<ListKind>
  arrived: ReadonlySet<string>
  failed: boolean
}

/** Sidebar pages and their requests, shared across refreshes, expansion and pagination. */
export class ConversationLists {
  private state: State = {
    projects: null,
    pages: null,
    loading: new Set(),
    errors: new Set(),
    arrived: new Set(),
    failed: false,
  }
  private listeners = new Set<() => void>()
  // A refresh replaces every page, so it runs alone: after the loads under way, and loads wait for it. Loads of
  // different lists run together.
  private refreshing = Promise.resolve()
  private loads = new Set<Promise<void>>()
  private waiting: Promise<void> | null = null

  private source: Pick<typeof api, "projects" | "conversations">
  constructor(source: Pick<typeof api, "projects" | "conversations">) {
    this.source = source
  }

  get = () => this.state
  subscribe = (listener: () => void) => {
    this.listeners.add(listener)
    return () => {
      this.listeners.delete(listener)
    }
  }
  private update(change: Partial<State>) {
    this.state = { ...this.state, ...change }
    for (const listener of this.listeners) listener()
  }
  private alone(work: () => Promise<void>) {
    const next = Promise.allSettled([this.refreshing, ...this.loads]).then(work)
    this.refreshing = next.catch(() => {})
    return next
  }
  private together(work: () => Promise<void>) {
    const next = this.refreshing.then(work)
    const settled = next.catch(() => {})
    this.loads.add(settled)
    void settled.then(() => this.loads.delete(settled))
    return next
  }
  private page(kind: ListKind, before: string | null, limit: number) {
    return this.source.conversations({ project: kind, before, limit })
  }
  private async first(kind: ListKind, count: number) {
    const size = (have: number) =>
      Math.min(MAX_PAGE, Math.max(sizeOf(kind), count - have))
    let page = await this.page(kind, null, size(0))
    while (page.next !== null && page.items.length < count) {
      const next = await this.page(kind, page.next, size(page.items.length))
      page = { items: [...page.items, ...next.items], next: next.next }
    }
    return page
  }

  /** Refresh recents and previously requested projects; unopened projects need only their names. */
  refresh = () => {
    if (this.waiting) return this.waiting
    const next = this.alone(async () => {
      this.waiting = null
      try {
        const shown = (kind: ListKind) =>
          this.state.pages?.get(kind)?.items.length ?? 0
        // The recents need no project names; a project's list waits for them, so a deleted one is not asked for.
        const [projects, recents] = await Promise.all([
          this.source.projects(),
          this.first(null, shown(null)),
        ])
        const existing = new Set(projects.map((project) => project.id))
        const kinds = [...(this.state.pages?.keys() ?? [])].filter(
          (kind): kind is string => kind !== null && existing.has(kind)
        )
        const pages = await Promise.all(
          kinds.map(
            async (kind) => [kind, await this.first(kind, shown(kind))] as const
          )
        )
        const refreshed = new Map<ListKind, Page<Conversation>>([
          [null, recents],
          ...pages,
        ])
        this.update({
          projects,
          pages: refreshed,
          // A failed next page still needs retrying unless the list reached its end or its project was deleted.
          errors: new Set(
            [...this.state.errors].filter(
              (kind) =>
                (kind === null || existing.has(kind)) &&
                refreshed.get(kind)?.next !== null
            )
          ),
          failed: false,
        })
      } catch {
        this.update({ failed: true })
      }
    })
    this.waiting = next
    return next
  }

  /** First page on expansion, or the next page on Show more. Concurrent requests for a list share one load. */
  load = (kind: ListKind) => {
    if (this.state.loading.has(kind)) return
    this.update({ loading: new Set(this.state.loading).add(kind) })
    return this.together(async () => {
      const current = this.state.pages?.get(kind)
      try {
        if (
          kind !== null &&
          this.state.projects &&
          !this.state.projects.some((project) => project.id === kind)
        )
          return
        if (current && current.next === null) return
        const page = await this.page(kind, current?.next ?? null, sizeOf(kind))
        this.update({
          pages: new Map(this.state.pages).set(kind, {
            items: [...(current?.items ?? []), ...page.items],
            next: page.next,
          }),
          errors: new Set(
            [...this.state.errors].filter((each) => each !== kind)
          ),
          arrived: new Set(current ? page.items.map((each) => each.id) : []),
        })
      } catch {
        this.update({ errors: new Set(this.state.errors).add(kind) })
      } finally {
        this.update({
          loading: new Set(
            [...this.state.loading].filter((each) => each !== kind)
          ),
        })
      }
    })
  }

  read = (kind: ListKind) => {
    if (!this.state.pages?.has(kind)) return this.load(kind)
  }
}
