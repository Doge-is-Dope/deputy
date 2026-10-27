import { useState } from "react"

/**
 * How long a task has worked, in the whole seconds shown (`seconds`, worked out as it goes): never fewer than it has
 * shown, since the runtime counts a turn of the user's at the desktop in whole seconds, which can take back a fraction
 * of one the moment it comes in.
 */
export function useWorked(seconds: number, task: string) {
  const whole = Math.round(seconds)
  const [most, setMost] = useState({ task, whole })
  const same = most.task === task
  if (!same || whole > most.whole) setMost({ task, whole })
  return same ? Math.max(most.whole, whole) : whole
}
