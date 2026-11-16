import { useEffect, useState } from "react"

import { doingNow, lastAsked, type Task } from "@/lib/thread"

/** The shortest time a step stays said as what the agent does, however soon it is done. */
const SHORTEST_MS = 1000

/**
 * What the agent working on a task does now, each step said for a shortest time: a step over in a moment still
 * reads, and the line doesn't jump to it and back. The next step takes its place at once.
 */
export function useDoingNow(task: Task | null): string {
  const asked = task ? lastAsked(task) : null
  const [prev, setPrev] = useState(asked)
  // A step found already there is not new: only one that comes while the line shows is held.
  const [lately, setLately] = useState<string | null>(null)
  if (asked !== prev) {
    setPrev(asked)
    setLately(asked)
  }
  useEffect(() => {
    if (lately === null) return
    const timer = window.setTimeout(() => setLately(null), SHORTEST_MS)
    return () => window.clearTimeout(timer)
  }, [lately])
  return task ? doingNow(task, lately) : ""
}
