import { useEffect, useRef } from "react"

import { createCursorGlow } from "@/lib/cursor-glow"

export function AgentCursorGlow() {
  const canvas = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    if (canvas.current) return createCursorGlow(canvas.current)
  }, [])
  return <canvas ref={canvas} aria-hidden className="agent-cursor-glow" />
}
