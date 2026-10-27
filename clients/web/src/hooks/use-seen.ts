import { useCallback, useEffect, useState } from "react"

import type { RunSummary } from "@/lib/api"

const KEY = "seen"

/** Up to when the user has seen each conversation, and up to when every conversation counts as seen. */
type Seen = { since: number; at: Record<string, number> }

/** What this browser keeps: undefined before anything is (the first time), null when it keeps nothing (private mode). */
function load(): Seen | null | undefined {
  let raw: string | null
  try {
    raw = localStorage.getItem(KEY)
  } catch {
    return null
  }
  try {
    const stored = JSON.parse(raw ?? "null")
    if (
      typeof stored?.since === "number" &&
      stored.at &&
      typeof stored.at === "object"
    )
      return stored
  } catch {
    // Not what this keeps: it starts again.
  }
  return undefined
}

/**
 * How far the user has seen each conversation, so that a reply or a failure that came while they were elsewhere stays
 * marked, across reloads, until they open it. Kept in this browser, in the runtime's time (a run's `ended`) rather than
 * the browser's, so the two clocks need not agree. The first time, everything that has already ended counts as seen,
 * so older conversations are not all marked at once. A browser that keeps nothing marks nothing.
 */
export function useSeen(runs: RunSummary[] | null) {
  const [seen, setSeen] = useState(load)
  if (seen === undefined && runs)
    setSeen({
      since: Math.max(0, ...runs.map((run) => run.ended ?? run.started)),
      at: {},
    })

  useEffect(() => {
    if (!seen) return
    try {
      localStorage.setItem(KEY, JSON.stringify(seen))
    } catch {
      // Not stored: what was seen still holds until the page reloads.
    }
  }, [seen])

  /** The conversation is seen up to `until`, its latest run's end (or start, while it runs). */
  const markSeen = useCallback(
    (conversation: string, until: number) =>
      setSeen((current) => {
        if (!current || (current.at[conversation] ?? current.since) >= until)
          return current
        return { ...current, at: { ...current.at, [conversation]: until } }
      }),
    []
  )

  /** Whether a run that ended at `ended` in the conversation is news to the user. */
  const isNew = useCallback(
    (conversation: string, ended: number | null) =>
      !!seen && ended !== null && ended > (seen.at[conversation] ?? seen.since),
    [seen]
  )

  return { isNew, markSeen }
}
