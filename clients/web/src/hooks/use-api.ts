import {
  useCallback,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from "react"

import {
  api,
  eventsUrl,
  type Project,
  type RunEvent,
  type RunSummary,
  type Status,
} from "@/lib/api"

import { applyEventBatch, readEvents, type EventBatchItem } from "@/lib/events"
import { answered } from "@/lib/session"
import {
  chatsFromHash,
  openRun,
  projectFromHash,
  runFromHash,
} from "@/lib/route"

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

/**
 * The runs on disk, newest first, and the viewer's projects, which they are listed under; null until first loaded.
 * `failed`: the last try to load them failed, which keeps the lists loaded before it. Call `refresh` to load them.
 */
export function useRuns() {
  const [runs, setRuns] = useState<RunSummary[] | null>(null)
  const [projects, setProjects] = useState<Project[] | null>(null)
  const [failed, setFailed] = useState(false)

  const refresh = useCallback(async () => {
    try {
      const [nextRuns, nextProjects] = await Promise.all([
        api.runs(),
        api.projects(),
      ])
      setRuns(nextRuns)
      setProjects(nextProjects)
      setFailed(false)
    } catch {
      setFailed(true)
    }
  }, [])

  return { runs, projects, failed, refresh }
}

/**
 * Where a run's stream stands: connecting the first time, open, waiting to connect again after it dropped or could not
 * connect, missing (the runtime has no such run), or done (nothing more will come).
 */
export type StreamPhase =
  "connecting" | "open" | "retrying" | "missing" | "done"

// How long to wait before connecting again, longer the more tries fail in a row; the last wait repeats.
const RETRY_MS = [500, 1000, 2000, 4000, 8000]

type Stream = {
  events: RunEvent[]
  phase: StreamPhase
  draft: string
  streamed: ReadonlySet<number>
}

// A run's stream before anything of it has come.
const FRESH: Stream = {
  events: [],
  phase: "connecting",
  draft: "",
  streamed: new Set(),
}

/** One run's stream, read by everything on the page that shows that run: its conversation and the live view. */
type Shared = {
  state: Stream
  readers: Set<{ changed: () => void; ended: () => void }>
  retryNow: () => void
  close: () => void
}
const streams = new Map<string, Shared>()

/**
 * Starts reading a run's stream, from the run's start. A stream that drops or can't connect is tried again on its own,
 * from the event after the last one received (Last-Event-ID), so what is shown stays. Read with fetch rather than
 * EventSource, which gives up for good on a response that is not 200 (the dev server's 502 while the runtime restarts)
 * and can't tell a missing run (404) from one that can't be reached.
 */
function openStream(run: string): Shared {
  const shared: Shared = {
    state: FRESH,
    readers: new Set(),
    retryNow: () => {},
    close: () => {},
  }
  const update = (change: (current: Stream) => Partial<Stream>) => {
    shared.state = { ...shared.state, ...change(shared.state) }
    for (const reader of shared.readers) reader.changed()
  }
  // A long run replays hundreds of events at once, and a reply comes a few words at a time: render them once per
  // frame, not once each, in the order they came.
  let pending: EventBatchItem[] = []
  let frame = 0
  const flush = () => {
    frame = 0
    const batch = pending
    pending = []
    if (batch.length) update((current) => applyEventBatch(current, batch))
  }
  const write = (draft: string, whole: boolean) => {
    pending.push({ draft, whole })
    frame ||= requestAnimationFrame(flush)
  }
  const url = eventsUrl(run)
  const stop = new AbortController()
  let lastId = ""
  let failures = 0
  let timer = 0
  let waiting = false

  async function connect() {
    waiting = false
    try {
      const response = await fetch(url, {
        headers: {
          Accept: "text/event-stream",
          ...(lastId && { "Last-Event-ID": lastId }),
        },
        cache: "no-store",
        signal: stop.signal,
      })
      answered(response)
      if (response.status === 404) {
        update(() => ({ phase: "missing" }))
        return
      }
      if (!response.ok || !response.body) throw new Error(response.statusText)
      failures = 0
      update(() => ({ phase: "open" }))
      // What was written of a reply before the stream dropped may be logged by now: it comes again, as it is now.
      write("", true)
      const ended = await readEvents(
        response.body,
        (data, id) => {
          pending.push({ event: JSON.parse(data) })
          if (id) lastId = id
          frame ||= requestAnimationFrame(flush)
        },
        write
      )
      if (ended) {
        cancelAnimationFrame(frame)
        flush()
        update(() => ({ phase: "done", draft: "" }))
        for (const reader of shared.readers) reader.ended()
        return
      }
    } catch {
      if (stop.signal.aborted) return
    }
    // It dropped, or could not connect: try again in a while.
    update(() => ({ phase: "retrying" }))
    waiting = true
    timer = window.setTimeout(
      connect,
      RETRY_MS[Math.min(failures++, RETRY_MS.length - 1)]
    )
  }
  shared.retryNow = () => {
    if (!waiting) return
    window.clearTimeout(timer)
    connect()
  }
  shared.close = () => {
    stop.abort()
    window.clearTimeout(timer)
    cancelAnimationFrame(frame)
  }
  connect()
  return shared
}

/**
 * Reads a run's stream as long as anything on the page does: the first reader opens it, the last one to go closes it.
 * A reader that comes once the run has ended (another kept its stream open) is told so at once.
 */
function readStream(run: string, changed: () => void, ended: () => void) {
  let shared = streams.get(run)
  if (!shared) streams.set(run, (shared = openStream(run)))
  const reader = { changed, ended }
  shared.readers.add(reader)
  if (shared.state.phase === "done") ended()
  return () => {
    shared.readers.delete(reader)
    if (shared.readers.size) return
    shared.close()
    streams.delete(run)
  }
}

function useStream<T>(
  run: string | null,
  pick: (stream: Stream) => T,
  onDone?: () => void
): T {
  const onDoneRef = useRef(onDone)
  useEffect(() => {
    onDoneRef.current = onDone
  })
  const subscribe = useCallback(
    (changed: () => void) =>
      run ? readStream(run, changed, () => onDoneRef.current?.()) : () => {},
    [run]
  )
  // Events from a previous run are never shown for the next one: each run has its own stream.
  return useSyncExternalStore(subscribe, () =>
    pick((run && streams.get(run)?.state) || FRESH)
  )
}

/**
 * A run's events, streamed: everything logged so far, then new events while the run is in progress, and the reply its
 * main agent is writing (`draft`), until it is logged; those replies the page saw being written are `streamed`, by their
 * event's place. One stream per run, however many parts of the page show it; a change of `wake` tries again at once to
 * connect a stream that dropped, as when the runtime is back.
 */
export function useRunEvents(
  run: string | null,
  onDone?: () => void,
  wake = 0
) {
  const { events, phase, draft, streamed } = useStream(
    run,
    (stream) => stream,
    onDone
  )
  useEffect(() => {
    if (run) streams.get(run)?.retryNow()
  }, [run, wake])
  return { events, phase, done: phase === "done", draft, streamed }
}

/** A run's events logged so far, from the same stream as useRunEvents: the reply being written draws nothing again. */
export function useRunLog(run: string | null): RunEvent[] {
  return useStream(run, (stream) => stream.events)
}

function subscribeHash(onChange: () => void) {
  window.addEventListener("hashchange", onChange)
  return () => window.removeEventListener("hashchange", onChange)
}

/** The open run, as the URL says (lib/route.ts), and how to open another. */
export function useOpenRun(): [string | null, (run: string | null) => void] {
  return [useSyncExternalStore(subscribeHash, runFromHash), openRun]
}

/** The project whose home is open, as the URL says; null elsewhere. */
export function useOpenProject(): string | null {
  return useSyncExternalStore(subscribeHash, projectFromHash)
}

/** Whether the page of every conversation is open, as the URL says. */
export function useChatsOpen(): boolean {
  return useSyncExternalStore(subscribeHash, chatsFromHash)
}
