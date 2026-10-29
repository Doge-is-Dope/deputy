// What the agent remembers for the user (runtime/src/computer_use/memory): the rules the main agent saved as the user
// steered its work, and the page's routes to list, edit, forget and put them back (memory/routes.py). The page keeps
// one list of them, which the conversation's lines and the settings page both show and change.

import { useEffect, useSyncExternalStore } from "react"

import { request } from "@/lib/api"

/** What taught it: a message sent while work ran, a declined step's reason, a takeover, or anything else said. */
export type MemoryKind = "steer" | "decline" | "takeover" | "said"

export type Memory = {
  id: string
  project: string | null // the project whose conversations it is told to; null: the user's own, told everywhere
  text: string // the rule itself
  why: string
  applies: string // when it applies: the kind of task, app or site
  source: { thread: string; run: string; kind: MemoryKind }
  created: number
  updated: number
  uses: number // tasks it was handed over with: kept for a later cleanup, not shown
  last_used: number | null
}

/** What the user can change of one. */
export type MemoryEdit = Partial<Pick<Memory, "text" | "why" | "applies">>

/** What a run's remember call saved, as its reply shows it: the rule as given, and its id from the result. */
export type Remembered = { id: string; text: string }

const path = (id: string) => `/api/memory/${encodeURIComponent(id)}`

export const memoryApi = {
  // The user's own and every project's, oldest first; with a project, only those its conversations are told.
  list: (project?: string) =>
    request<Memory[]>(
      project
        ? `/api/memory?project=${encodeURIComponent(project)}`
        : "/api/memory"
    ),
  edit: (id: string, edit: MemoryEdit) =>
    request<Memory>(path(id), { method: "PATCH", body: JSON.stringify(edit) }),
  forget: (id: string) =>
    request<{ deleted: string }>(path(id), { method: "DELETE" }),
  // One forgotten a moment ago, back as it was (復原).
  restore: (memory: Memory) =>
    request<Memory>(path(memory.id), {
      method: "PUT",
      body: JSON.stringify(memory),
    }),
}

type Store = {
  list: Memory[] | null // null until first loaded
  failed: boolean // the last load failed
  loading: boolean
  forgotten: ReadonlyMap<string, Memory> // forgotten on this page, by id, as they were: 復原 puts them back
}

/** Small external stores, read with useSyncExternalStore. */
function store<T>(initial: T) {
  let value = initial
  const listeners = new Set<() => void>()
  const subscribe = (listener: () => void) => {
    listeners.add(listener)
    return () => {
      listeners.delete(listener)
    }
  }
  return {
    get: () => value,
    set: (next: T) => {
      value = next
      for (const listener of listeners) listener()
    },
    use: () => useSyncExternalStore(subscribe, () => value),
  }
}

const memories = store<Store>({
  list: null,
  failed: false,
  loading: false,
  forgotten: new Map(),
})
const byCreated = (list: Memory[]) =>
  list.toSorted((a, b) => a.created - b.created)
let loading: Promise<void> | null = null

/** Loads the list again; one load at a time, which every caller meanwhile waits for. */
export function loadMemories(): Promise<void> {
  if (loading) return loading
  memories.set({ ...memories.get(), loading: true })
  loading = memoryApi
    .list()
    .then(
      (list) => ({ list, failed: false }),
      () => ({ failed: true })
    )
    .then((loaded) => {
      loading = null
      memories.set({ ...memories.get(), ...loaded, loading: false })
    })
  return loading
}

export const useMemories = memories.use

/** One memory as the list has it: undefined until it is loaded with it in, null once it is not (forgotten). A line
 * for one the list does not have yet, as one just remembered, loads it again. */
export function useMemory(id: string): Memory | null | undefined {
  const { list, loading } = useMemories()
  const memory = list?.find((each) => each.id === id)
  const missing = list === null || memory === undefined
  useEffect(() => {
    if (missing) void loadMemories()
  }, [id, missing])
  return memory ?? (list === null || loading ? undefined : null)
}

export async function editMemory(id: string, edit: MemoryEdit) {
  const changed = await memoryApi.edit(id, edit)
  const now = memories.get()
  memories.set({
    ...now,
    list: (now.list ?? []).map((each) => (each.id === id ? changed : each)),
  })
}

/** Forgets one, kept on the page to put back. */
export async function forgetMemory(id: string) {
  const now = memories.get()
  const memory = now.list?.find((each) => each.id === id)
  await memoryApi.forget(id)
  const forgotten = new Map(now.forgotten)
  if (memory) forgotten.set(id, memory)
  memories.set({
    ...memories.get(),
    list: (memories.get().list ?? []).filter((each) => each.id !== id),
    forgotten,
  })
}

export async function restoreMemory(id: string) {
  const memory = memories.get().forgotten.get(id)
  if (!memory) return
  const restored = await memoryApi.restore(memory)
  const now = memories.get()
  const forgotten = new Map(now.forgotten)
  forgotten.delete(id)
  memories.set({
    ...now,
    list: byCreated([
      ...(now.list ?? []).filter((each) => each.id !== id),
      restored,
    ]),
    forgotten,
  })
}

/** Forgets the user's own, past putting back; each project's are kept. Loaded again after, as some may have gone
 * before one failed. */
export async function forgetPersonalMemories() {
  const personal = (memories.get().list ?? []).filter(
    (memory) => memory.project === null
  )
  try {
    await Promise.all(personal.map((memory) => memoryApi.forget(memory.id)))
  } finally {
    memories.set({ ...memories.get(), forgotten: new Map() })
    await loadMemories()
  }
}

// Where the settings open, when a line in the conversation opens them: a page, the item on it to show, and whether
// to edit it. The settings dialog lives in the sidebar, the lines in the conversation: this store is between them.
export type OpenedSettings = {
  open: boolean
  page: string | null
  item: string | null
  editing: boolean
}
const settings = store<OpenedSettings>({
  open: false,
  page: null,
  item: null,
  editing: false,
})

/** Opens the settings at a page, and at an item of it, from anywhere on the page. */
export function openSettings(
  page: string,
  item: string | null = null,
  editing = false
) {
  settings.set({ open: true, page, item, editing })
}

export function closeSettings() {
  settings.set({ ...settings.get(), open: false })
}

// A project's rules, opened from its menu or from a line in the conversation: which project (null: shut), the rule to
// show, and whether to edit it. The dialog lives beside the settings, outside the sidebar's sheet on a phone.
export type OpenedProjectMemory = {
  project: string | null
  item: string | null
  editing: boolean
}
const projectMemory = store<OpenedProjectMemory>({
  project: null,
  item: null,
  editing: false,
})

export function openProjectMemory(
  project: string | null,
  item: string | null = null,
  editing = false
) {
  projectMemory.set({ project, item, editing })
}

export const useOpenedProjectMemory = projectMemory.use

/** Opens a rule where it is kept: a project's in that project's rules, the user's own in the settings. */
export function openMemory(id: string) {
  const project = memories.get().list?.find((each) => each.id === id)?.project
  if (project) openProjectMemory(project, id)
  else openSettings("memory", id)
}

export const useOpenedSettings = settings.use
