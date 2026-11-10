import {
  useCallback,
  useEffect,
  useEffectEvent,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react"

import { api, type RunSummary, type Status } from "@/lib/api"
import { merged } from "@/lib/conversations"
import { ConversationLists, type ListKind } from "@/lib/conversation-lists"

const STATUS_POLL_MS = 1500

/** The runtime's status, polled; null until the first answer, and `offline` while the API cannot be reached. */
export function useStatus() {
  const [status, setStatus] = useState<Status | null>(null)
  const [offline, setOffline] = useState(false)

  const refresh = useCallback(async () => {
    try {
      const next = await api.status()
      // The same answer as last time keeps the same object, so a poll with nothing new draws nothing again.
      setStatus((current) =>
        current && JSON.stringify(current) === JSON.stringify(next)
          ? current
          : current && current.control.since > next.control.since
            ? { ...next, control: current.control }
            : next
      )
      setOffline(false)
    } catch {
      setOffline(true)
    }
  }, [])

  useEffect(() => {
    let timer = 0
    let stopped = false
    const tick = async () => {
      await refresh()
      if (!stopped) timer = window.setTimeout(tick, STATUS_POLL_MS)
    }
    tick()
    return () => {
      stopped = true
      window.clearTimeout(timer)
    }
  }, [refresh])

  // A confirmed handover is usable immediately, even if an older poll is still in flight.
  const confirmControl = useCallback((control: Status["control"]) => {
    setStatus((current) =>
      current && control.since >= current.control.since
        ? { ...current, control }
        : current
    )
  }, [])

  return { status, offline, refresh, confirmControl }
}

export type { ListKind } from "@/lib/conversation-lists"

/** Sidebar pagination and lazy project reads. */
export type Lists = {
  more: (kind: ListKind) => boolean
  loading: (kind: ListKind) => boolean
  loaded: (kind: ListKind) => boolean
  failed: (kind: ListKind) => boolean
  read: (kind: ListKind) => void
  load: (kind: ListKind) => void
  arrived: ReadonlySet<string>
}

/** Project names and recents load first; a project's conversations load when it opens and stay cached. */
export function useConversations(changed: string | null, running: string[]) {
  const [loader] = useState(() => new ConversationLists(api))
  const state = useSyncExternalStore(loader.subscribe, loader.get)
  const refresh = useEffectEvent(() => void loader.refresh(running))
  useEffect(() => {
    if (changed !== null) refresh()
  }, [changed])
  const lists = useMemo<Lists>(
    () => ({
      more: (kind) => (state.pages?.get(kind)?.next ?? null) !== null,
      loading: (kind) => state.loading.has(kind),
      loaded: (kind) => state.pages?.has(kind) ?? false,
      failed: (kind) => state.errors.has(kind),
      read: loader.read,
      load: loader.load,
      arrived: state.arrived,
    }),
    [state, loader]
  )
  const conversations = useMemo(
    () =>
      state.pages &&
      merged([
        state.latest,
        state.beyond,
        ...[...state.pages.values()].map((page) => page.items),
      ]),
    [state.pages, state.latest, state.beyond]
  )
  return {
    conversations,
    projects: state.projects,
    failed: state.failed,
    refresh: loader.refresh,
    lists,
  }
}

/**
 * Loads a conversation's runs, oldest first, as it opens and whenever `changed` does. Accepts a conversation ID or a
 * legacy run ID. `listed` means the request has settled, including failure. Runs are null until available.
 * Failed refreshes keep previously loaded runs.
 */
export function useThreadRuns(opened: string | null, changed: string | null) {
  const [loaded, setLoaded] = useState<{
    for: string
    runs: RunSummary[] | null // null: they could not be read
  } | null>(null)
  const request = useRef(0)
  const refresh = useCallback(() => {
    const id = ++request.current
    if (opened === null) return
    api.runsOf(opened).then(
      (runs) => {
        if (id === request.current) setLoaded({ for: opened, runs })
      },
      () => {
        if (id === request.current)
          setLoaded((current) =>
            current?.for === opened ? current : { for: opened, runs: null }
          )
      }
    )
  }, [opened])
  useEffect(() => {
    const activeRequest = request
    refresh()
    return () => {
      activeRequest.current++
    }
  }, [refresh, changed])
  const listed = loaded?.for === opened
  const current = listed ? loaded.runs : null
  return useMemo(() => {
    // A session (agent/session.py) is named by its first turn; each of its turns and tasks logs on its own.
    const logs = new Map<string, string[]>()
    for (const each of current ?? [])
      logs.set(each.session, [...(logs.get(each.session) ?? []), each.id])
    return {
      thread: current?.[0]?.thread ?? null,
      runs: current?.filter((each) => each.id === each.session) ?? null,
      turns: current?.filter((each) => each.kind === "turn") ?? null,
      logs: logs as ReadonlyMap<string, readonly string[]>,
      listed,
    }
  }, [current, listed])
}
