import {
  useRef,
  type Dispatch,
  type KeyboardEvent,
  type PointerEvent,
  type SetStateAction,
} from "react"
import { cn } from "cn"

// Turns off the panels' width transitions and text selection while dragging (index.css).
function resizing(on: boolean) {
  const flags = document.documentElement.dataset
  if (on) flags.resizing = ""
  else delete flags.resizing
}

/**
 * A strip on a panel's edge that resizes it: drag it, or focus it and press the arrow keys (Shift for bigger
 * steps). `from` is the window side the panel is anchored to, so the width follows the pointer from there.
 * The panel's edge is already drawn (a border, the page card's), so under the pointer it lights only the middle of
 * it: four fifths of the edge, a 1px stroke in the theme's accent that tapers and fades toward both ends. It starts
 * at the strip's middle, the panel's edge, so it lies on the edge's own 1px line.
 *
 * With `onCollapsed`, a panel that can close snaps shut once the pointer is past half its minimum width, and opens
 * again if the pointer comes back out in the same drag; released shut, it opens at the width it had before.
 */
export function ResizeHandle({
  from,
  width,
  min,
  max,
  onWidth,
  label,
  className,
  collapsed = false,
  onCollapsed,
}: {
  from: "left" | "right"
  width: number
  min: number
  max: number
  onWidth: Dispatch<SetStateAction<number>>
  label: string
  className?: string
  collapsed?: boolean
  onCollapsed?: (collapsed: boolean) => void
}) {
  const clamp = (value: number) =>
    Math.min(max, Math.max(min, Math.round(value)))
  // The width as the drag began, which a panel snapped shut opens at again.
  const start = useRef(0)
  // How far the edge is from the pointer, kept through the drag: the edge stays under it wherever the strip was
  // pressed, and the panel's far side need not be the window's (the page card's sits in from it).
  const grab = useRef(0)
  const reach = (event: PointerEvent<HTMLDivElement>) =>
    from === "left" ? event.clientX : window.innerWidth - event.clientX
  // Until when the panel's own snap, shut or open, is still moving: the width follows the pointer with its
  // transition meanwhile, rather than cutting it short.
  const settling = useRef(0)

  function onPointerDown(event: PointerEvent<HTMLDivElement>) {
    event.preventDefault()
    event.currentTarget.setPointerCapture(event.pointerId)
    start.current = width
    // A closed panel opens from its rail, where the pointer is.
    grab.current = collapsed ? 0 : width - reach(event)
    resizing(true)
  }

  function onPointerMove(event: PointerEvent<HTMLDivElement>) {
    if (!event.currentTarget.hasPointerCapture(event.pointerId)) return
    const target = reach(event) + grab.current
    if (onCollapsed) {
      const shut = target < min / 2
      if (shut !== collapsed) {
        // The snap moves with the panel's transition (its duration-300).
        resizing(false)
        settling.current = event.timeStamp + 300
        onCollapsed(shut)
        if (shut) onWidth(start.current)
      }
      if (shut) return
      if (event.timeStamp >= settling.current) resizing(true)
    }
    onWidth(clamp(target))
  }

  function onPointerUp(event: PointerEvent<HTMLDivElement>) {
    if (event.currentTarget.hasPointerCapture(event.pointerId))
      event.currentTarget.releasePointerCapture(event.pointerId)
    resizing(false)
  }

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (collapsed) return
    const step = event.shiftKey ? 64 : 16
    const wider = from === "left" ? "ArrowRight" : "ArrowLeft"
    const narrower = from === "left" ? "ArrowLeft" : "ArrowRight"
    if (event.key === wider) onWidth((current) => clamp(current + step))
    else if (event.key === narrower) onWidth((current) => clamp(current - step))
    else return
    event.preventDefault()
  }

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={label}
      aria-valuenow={width}
      aria-valuemin={min}
      aria-valuemax={max}
      // On the closed rail it is for the pointer only: the keyboard opens the sidebar with its toggle.
      tabIndex={collapsed ? -1 : 0}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
      onKeyDown={onKeyDown}
      className={cn(
        "group/resize absolute inset-y-0 z-20 w-3 cursor-col-resize touch-none outline-none",
        className
      )}
    >
      <span className="absolute top-1/2 left-1/2 h-4/5 w-px -translate-y-1/2 scale-y-50 bg-(--theme-accent) mask-[linear-gradient(transparent,black_30%,black_70%,transparent)] opacity-0 transition-[opacity,scale] duration-200 ease-(--ease-out) [clip-path:ellipse(50%_50%)] group-hover/resize:scale-y-100 group-hover/resize:opacity-50 group-focus-visible/resize:scale-y-100 group-focus-visible/resize:opacity-100 group-active/resize:scale-y-100 group-active/resize:opacity-100 motion-reduce:scale-y-100" />
    </div>
  )
}
