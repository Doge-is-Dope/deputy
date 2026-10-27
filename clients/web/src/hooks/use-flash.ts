import { useCallback, useEffect, useState } from "react"

/** How long a passing message (why a click did nothing, what failed) stays. */
export const NUDGE_MS = 2500

/**
 * A value that clears itself `ms` after it is set, as a message said for a moment; each set starts the wait again,
 * and setting null clears it at once.
 */
export function useFlash<T>(ms: number) {
  const [held, setHeld] = useState<{ value: T } | null>(null)
  useEffect(() => {
    if (!held) return
    const timer = window.setTimeout(() => setHeld(null), ms)
    return () => window.clearTimeout(timer)
  }, [held, ms])
  const flash = useCallback(
    (value: T | null) => setHeld(value === null ? null : { value }),
    []
  )
  return [held ? held.value : null, flash] as const
}
