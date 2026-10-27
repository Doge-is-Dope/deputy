import { useEffect, useState } from "react"

/** A panel width the viewer chose, kept in this browser; storage that fails (private mode) keeps it for the visit. */
export function useStoredWidth(key: string, fallback: number) {
  const [width, setWidth] = useState(() => {
    try {
      const stored = Number(localStorage.getItem(key))
      return stored > 0 ? stored : fallback
    } catch {
      return fallback
    }
  })

  useEffect(() => {
    try {
      localStorage.setItem(key, String(width))
    } catch {
      // Not stored; the width still holds until the page reloads.
    }
  }, [key, width])

  return [width, setWidth] as const
}
