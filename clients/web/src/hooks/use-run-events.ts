import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useSyncExternalStore,
} from "react"

import { eventsUrl, RETRY_MS, type RunEvent } from "@/lib/api"
import { applyEventBatch, readEvents, type EventBatchItem } from "@/lib/events"
import { mergeSession } from "@/lib/logs"
import { answered } from "@/lib/session"

/**
 * Where a run's stream stands: connecting the first time, open, waiting to connect again after it dropped or could not
 * connect, missing (the runtime has no such run), or done (nothing more will come).
 */
export type StreamPhase =
  "connecting" | "open" | "retrying" | "missing" | "done"

type Stream = {
  events: RunEvent[]
  phase: StreamPhase
  draft: string
  final: boolean
  streamed: ReadonlySet<number>
}

// A run's stream before anything of it has come.
const FRESH: Stream = {
  events: [],
  phase: "connecting",
  draft: "",
  final: false,
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
// A run that has ended logs nothing more its view shows, so its events stay for the next time it is read: the most
// recently read of those no one reads now, oldest first.
const KEEP_ENDED = 100
const ended = new Set<string>()

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
  const write = (draft: string, whole: boolean, final = false) => {
    pending.push({ draft, whole, final })
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
        update(() => ({ phase: "done", draft: "", final: false }))
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
 * A reader that comes once the run has ended (another kept its stream, or it was kept as it ended) is told so at once.
 */
function readStream(run: string, changed: () => void, onEnded: () => void) {
  let shared = streams.get(run)
  if (!shared) streams.set(run, (shared = openStream(run)))
  // Read again, none of its replies is being written as the page looks on.
  else if (ended.delete(run))
    shared.state = { ...shared.state, streamed: FRESH.streamed }
  const reader = { changed, ended: onEnded }
  shared.readers.add(reader)
  if (shared.state.phase === "done") onEnded()
  return () => {
    shared.readers.delete(reader)
    // Closed once nothing reads it after this change: a reader that comes back at once, as when a session's view
    // reads one more of its logs and subscribes again, keeps it as it is, its replies seen being written included.
    queueMicrotask(() => leave(run, shared))
  }
}

/** Close a stream nothing reads any more, keeping it a while if its run has ended. */
function leave(run: string, shared: Shared) {
  if (shared.readers.size || streams.get(run) !== shared) return
  shared.close()
  if (shared.state.phase !== "done") {
    streams.delete(run)
    return
  }
  ended.add(run)
  for (const oldest of ended) {
    if (ended.size <= KEEP_ENDED) break
    ended.delete(oldest)
    streams.delete(oldest)
  }
}

/** A run's logged events; transient draft changes keep the same list and do not redraw the live view. */
export function useRunLog(run: string | null): RunEvent[] {
  const subscribe = useCallback(
    (changed: () => void) =>
      run ? readStream(run, changed, () => {}) : () => {},
    [run]
  )
  return useSyncExternalStore(
    subscribe,
    () => (run && streams.get(run)?.state.events) || FRESH.events
  )
}

const NOTHING_MERGED = { events: [] as RunEvent[], streamed: new Set<number>() }

/** The reply a session's main agent is writing, in whichever of its turns, and whether it is the final one. */
function draftOf(states: readonly Stream[]): { draft: string; final: boolean } {
  const writing = states.find((state) => state.draft || state.final)
  return { draft: writing?.draft ?? "", final: writing?.final ?? false }
}

/** Where the session's streams stand together: missing first log, or the furthest behind. */
function phaseOf(states: readonly Stream[]): StreamPhase {
  if (states[0]?.phase === "missing") return "missing"
  if (
    states.every((state) => state.phase === "done" || state.phase === "missing")
  )
    return "done"
  if (states.some((state) => state.phase === "retrying")) return "retrying"
  if (states.some((state) => state.phase === "open")) return "open"
  return "connecting"
}

/**
 * A session's events, from the streams of all its logs (`logs`: its first turn first, then its later turns and its
 * tasks), merged as the conversation shows them (lib/logs.ts); it ends once it is `quiet`, no longer in progress.
 * Includes the reply the main agent is writing in the turn under way, and those the page saw
 * being written; `onDone` once each log has ended; a change of `wake` tries a dropped stream again at once.
 */
export function useSessionEvents(
  logs: readonly string[],
  quiet: boolean,
  onDone?: () => void,
  wake = 0
) {
  const key = logs.join(" ")
  const onDoneRef = useRef(onDone)
  useEffect(() => {
    onDoneRef.current = onDone
  })
  const subscribe = useCallback(
    (changed: () => void) => {
      const leaving = key
        .split(" ")
        .filter(Boolean)
        .map((run) => readStream(run, changed, () => onDoneRef.current?.()))
      return () => leaving.forEach((leave) => leave())
    },
    [key]
  )
  // The same list while no stream changed: a new one on every read would draw the session again each time.
  const kept = useRef<{ key: string; states: Stream[] } | null>(null)
  const states = useSyncExternalStore(subscribe, () => {
    const now = logs.map((run) => streams.get(run)?.state ?? FRESH)
    const last = kept.current
    if (
      last?.key === key &&
      last.states.every((state, at) => state === now[at])
    )
      return last.states
    kept.current = { key, states: now }
    return now
  })
  useEffect(() => {
    for (const run of key.split(" ")) streams.get(run)?.retryNow()
  }, [key, wake])
  // A session that is over is drawn once all its logs are read, as one run's whole log once was: a task whose own
  // log has yet to come would seem to run on until the session's last event, and a clock shown never goes back.
  const read = states.every(
    (state) => state.phase === "done" || state.phase === "missing"
  )
  const merged = useMemo(
    () =>
      quiet && !read
        ? NOTHING_MERGED
        : mergeSession(
            states.map((state, at) => ({
              id: logs[at],
              events: state.events,
              streamed: state.streamed,
            })),
            quiet
          ),
    // `logs` is read through `states`, which changes with `key`
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [states, quiet, read]
  )
  const phase = phaseOf(states)
  return {
    events: merged.events,
    phase,
    done: phase === "done",
    ...draftOf(states),
    streamed: merged.streamed,
  }
}
