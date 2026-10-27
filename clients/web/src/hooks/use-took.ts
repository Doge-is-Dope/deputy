import { useState } from "react"

/**
 * Since when the user has had the desktop a task uses: by the runtime's status (`since`, while it says so), which
 * knows before the task's log does, and kept while the log still has the agent waiting for it (`waiting`), as the
 * status may hear first that it is back. Its timer stays stopped till the log says how long the user had it.
 */
export function useTook(since: number | null, waiting: boolean) {
  const [took, setTook] = useState<number | null>(null)
  if (took !== since && (since !== null || !waiting)) setTook(since)
  return took
}
