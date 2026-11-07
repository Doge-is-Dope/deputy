import { useSyncExternalStore } from "react"

import { openRun, projectFromHash, runFromHash } from "@/lib/route"

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
