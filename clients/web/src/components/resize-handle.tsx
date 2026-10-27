import type {
  Dispatch,
  KeyboardEvent,
  PointerEvent,
  SetStateAction,
} from "react"
import { cn } from "cn"

/**
 * A strip on a panel's edge that resizes it: drag it, or focus it and press the arrow keys (Shift for bigger
 * steps). `from` is the window side the panel is anchored to, so the width follows the pointer from there.
 */
export function ResizeHandle({
  from,
  width,
  min,
  max,
  onWidth,
  label,
  className,
}: {
  from: "left" | "right"
  width: number
  min: number
  max: number
  onWidth: Dispatch<SetStateAction<number>>
  label: string
  className?: string
}) {
  const clamp = (value: number) =>
    Math.min(max, Math.max(min, Math.round(value)))

  function onPointerDown(event: PointerEvent<HTMLDivElement>) {
    event.preventDefault()
    event.currentTarget.setPointerCapture(event.pointerId)
    // Turns off the panels' width transitions and text selection while dragging (index.css).
    document.documentElement.dataset.resizing = ""
  }

  function onPointerMove(event: PointerEvent<HTMLDivElement>) {
    if (!event.currentTarget.hasPointerCapture(event.pointerId)) return
    onWidth(
      clamp(from === "left" ? event.clientX : window.innerWidth - event.clientX)
    )
  }

  function onPointerUp(event: PointerEvent<HTMLDivElement>) {
    if (event.currentTarget.hasPointerCapture(event.pointerId))
      event.currentTarget.releasePointerCapture(event.pointerId)
    delete document.documentElement.dataset.resizing
  }

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
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
      tabIndex={0}
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
      <span className="absolute inset-y-0 left-1/2 w-0.5 -translate-x-1/2 rounded-full transition-colors group-hover/resize:bg-border group-focus-visible/resize:bg-ring group-active/resize:bg-ring" />
    </div>
  )
}
