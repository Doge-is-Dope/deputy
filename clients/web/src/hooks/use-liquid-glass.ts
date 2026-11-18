import { useEffect } from "react"

import { drawLens, LENSED, type Lens } from "@/lib/liquid-glass"
import { store } from "@/lib/store"

// Drawn once, for the page, when the browser is first idle after it is asked for: one lens all its users read, so a
// redrawn module (a hot reload of the shader) shows its new lens everywhere, not one kept in a component's state.
const lens = store<Lens | null>(null)
const useLens = lens.use
let drawing = false

function draw() {
  if (drawing) return
  drawing = true
  requestIdleCallback(() => lens.set(drawLens()))
}

/** The lens over the glass (lib/liquid-glass.ts): null until it is drawn, and in a browser that cannot bend what is
 * under the glass with it. */
export function useLiquidGlass(): Lens | null {
  const drawn = useLens()
  useEffect(() => {
    if (LENSED && !drawn) draw()
  }, [drawn])
  return drawn
}
