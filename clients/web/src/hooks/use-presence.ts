import { useEffect, useState } from "react"

/**
 * Whether something shown is still on screen: from when it shows until its way out (`ms`) is over. Returns that, and
 * whether it is on its way out; shown again meanwhile, it stays.
 */
export function usePresence(open: boolean, ms: number) {
  const [mounted, setMounted] = useState(open)
  if (open && !mounted) setMounted(true)
  useEffect(() => {
    if (open || !mounted) return
    const timer = window.setTimeout(() => setMounted(false), ms)
    return () => window.clearTimeout(timer)
  }, [open, mounted, ms])
  return [mounted, mounted && !open] as const
}
