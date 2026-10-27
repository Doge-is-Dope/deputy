import { useEffect, useSyncExternalStore } from "react"

import { drawLens, LENSED, type Lens } from "@/lib/liquid-glass"

// Drawn once, for the page, when the browser is first idle after it is asked for: one lens all its users read, so a
// redrawn module (a hot reload of the shader) shows its new lens everywhere, not one kept in a component's state.
let lens: Lens | null = null
let drawing = false
const watchers = new Set<() => void>()

function draw() {
  if (drawing) return
  drawing = true
  requestIdleCallback(() => {
    lens = drawLens()
    for (const watcher of watchers) watcher()
  })
}

const watch = (watcher: () => void) => {
  watchers.add(watcher)
  return () => {
    watchers.delete(watcher)
  }
}
const read = () => lens
const none = () => null

/** The lens over the glass (lib/liquid-glass.ts): null until it is drawn, and in a browser that cannot bend what is
 * under the glass with it. */
export function useLiquidGlass(): Lens | null {
  const drawn = useSyncExternalStore(watch, read, none)
  useEffect(() => {
    if (LENSED && !drawn) draw()
  }, [drawn])
  return drawn
}
