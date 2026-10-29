import { reducedMotion } from "@/lib/motion"

// A pendulum about the pointer's tip: AMPLITUDE degrees either way, there and back in PERIOD seconds. It swings out
// over SWING_IN ms and comes back upright over SETTLE ms, as the pointer slides to the agent's next spot.
const AMPLITUDE = 8
const PERIOD = 1.6
const SWING_IN = 600
const SETTLE = 160

const easeOut = (x: number) => 1 - (1 - x) ** 3

/**
 * Swings the element, the pointer with its tip at the origin, while `set(true)`: the tip stays on the point and only
 * the rest of the pointer moves. Reduced motion keeps it upright.
 */
export function createCursorSway(element: HTMLElement) {
  let on = false
  let level = 0 // the share of AMPLITUDE it swings at
  let from = 0 // the level when it was last told to swing or settle
  let since = 0
  let swung = 0 // seconds swung; stopped while it settles, so it comes back without a jerk
  let last = 0
  let frame = 0
  let visible = true

  const draw = (now: number) => {
    const progress = Math.min(
      Math.max((now - since) / (on ? SWING_IN : SETTLE), 0),
      1
    )
    level = from + ((on ? 1 : 0) - from) * easeOut(progress)
    if (on) swung += Math.min(Math.max(now - last, 0), 50) / 1000
    last = now
    if (!on && progress === 1) {
      frame = 0
      swung = 0
      element.style.rotate = ""
      return
    }
    element.style.rotate = `${level * AMPLITUDE * Math.sin((2 * Math.PI * swung) / PERIOD)}deg`
    frame = requestAnimationFrame(draw)
  }

  const observer = new IntersectionObserver(([entry]) => {
    if (visible === entry.isIntersecting) return
    visible = entry.isIntersecting
    if (!visible) {
      cancelAnimationFrame(frame)
      frame = 0
    } else if (on || level > 0) {
      // Resume from the last drawn position, leaving time spent hidden out of the swing.
      const now = performance.now()
      since += now - last
      last = now
      frame ||= requestAnimationFrame(draw)
    }
  })
  observer.observe(element)

  return {
    set(next: boolean) {
      next &&= !reducedMotion()
      if (next === on) return
      on = next
      from = level
      since = last = performance.now()
      if (visible) frame ||= requestAnimationFrame(draw)
    },
    dispose() {
      cancelAnimationFrame(frame)
      observer.disconnect()
      element.style.rotate = ""
    },
  }
}
