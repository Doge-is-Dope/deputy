import {
  useEffect,
  useEffectEvent,
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type PointerEvent,
} from "react"
import { cn } from "cn"

import { AgentCursorGlow } from "@/components/desktop/agent-cursor-glow"
import { NUDGE_MS, useFlash } from "@/hooks/use-flash"
import type { LiveInput, ScreenPoint } from "@/hooks/use-live"
import { CURSOR_PATH } from "@/lib/cursor-glow"
import { createCursorSway } from "@/lib/cursor-sway"
import { useT } from "@/lib/i18n"
import { isComposing } from "@/lib/keys"

// Browser key codes (the physical key, whatever the layout) to the runtime's key names (desktop/keys.py).
const KEYS: Record<string, string> = {
  ShiftLeft: "shift",
  ShiftRight: "shift",
  ControlLeft: "ctrl",
  ControlRight: "ctrl",
  AltLeft: "alt",
  AltRight: "alt",
  MetaLeft: "win",
  MetaRight: "win",
  Enter: "enter",
  NumpadEnter: "enter",
  Escape: "esc",
  Tab: "tab",
  Space: "space",
  Backspace: "backspace",
  Delete: "delete",
  Insert: "insert",
  ArrowUp: "up",
  ArrowDown: "down",
  ArrowLeft: "left",
  ArrowRight: "right",
  Home: "home",
  End: "end",
  PageUp: "pageup",
  PageDown: "pagedown",
  Minus: "-",
  Equal: "=",
  BracketLeft: "[",
  BracketRight: "]",
  Backslash: "\\",
  Semicolon: ";",
  Quote: "'",
  Backquote: "`",
  Comma: ",",
  Period: ".",
  Slash: "/",
}

function keyName(code: string): string | null {
  if (code in KEYS) return KEYS[code]
  const match = code.match(/^Key([A-Z])$|^(?:Digit|Numpad)(\d)$|^F(\d{1,2})$/)
  if (!match) return null
  if (match[1]) return match[1].toLowerCase()
  if (match[2]) return match[2]
  return `f${match[3]}`
}

const BUTTONS = ["left", "middle", "right"] as const
// Pixels of wheel or trackpad travel that make one wheel click on the desktop.
const WHEEL_STEP = 100

/** Where a point on the page falls on the desktop, in screen pixels, given how the video is fitted. */
function toScreen(video: HTMLVideoElement, clientX: number, clientY: number) {
  const { videoWidth: width, videoHeight: height } = video
  if (!width || !height) return null
  const rect = video.getBoundingClientRect()
  const scale = Math.min(rect.width / width, rect.height / height)
  const x = (clientX - rect.left - (rect.width - width * scale) / 2) / scale
  const y = (clientY - rect.top - (rect.height - height * scale) / 2) / scale
  if (x < 0 || y < 0 || x >= width || y >= height) return null
  return { x: Math.floor(x), y: Math.floor(y) }
}

/** Where a desktop pixel's middle falls on the video element, in CSS pixels from its top left: toScreen undone. */
function fromScreen(video: HTMLVideoElement, point: ScreenPoint) {
  const { videoWidth: width, videoHeight: height } = video
  if (!width || !height) return null
  const { clientWidth, clientHeight } = video
  const scale = Math.min(clientWidth / width, clientHeight / height)
  return {
    left: (clientWidth - width * scale) / 2 + (point.x + 0.5) * scale,
    top: (clientHeight - height * scale) / 2 + (point.y + 0.5) * scale,
  }
}

/** Show the pointer at a spot on the video element, or hide it. It slides there only when asked to and already shown. */
function showPointer(
  element: HTMLElement | null,
  at: { left: number; top: number } | null,
  glide = false
) {
  if (!element) return
  element.toggleAttribute("data-glide", glide && element.style.opacity === "1")
  element.style.opacity = at ? "1" : "0"
  if (at) element.style.transform = `translate(${at.left}px, ${at.top}px)`
}

/**
 * The video of the desktop. While the user has control it also takes their mouse and keyboard; a hidden text
 * field holds the keyboard focus so that an input method (Chinese) can compose text, which goes as one piece.
 */
export function RemoteScreen({
  stream,
  interactive,
  send,
  pointer,
  thinking,
  notice,
  focus,
  onFocused,
}: {
  stream: MediaStream | null
  interactive: boolean
  send: (event: LiveInput) => void
  /** Where the agent's pointer is, while it has control. */
  pointer: ScreenPoint | null
  /** The agent on the desktop is working out its next step. */
  thinking: boolean
  /** What to say over the screen for a moment, such as a takeover that didn't happen. */
  notice: string | null
  /** The user just took over: the keyboard goes to the desktop as soon as it can. */
  focus: boolean
  onFocused: () => void
}) {
  const t = useT()
  const video = useRef<HTMLVideoElement>(null)
  const keyboard = useRef<HTMLTextAreaElement>(null)
  const pressed = useRef(new Set<string>())
  const buttons = useRef(new Set<(typeof BUTTONS)[number]>())
  const pendingMove = useRef<{ x: number; y: number } | null>(null)
  const frame = useRef(0)
  const wheel = useRef({ x: 0, y: 0 })
  const [typing, setTyping] = useState(false)
  // A click on the screen while the agent has control does nothing on the desktop; say why for a moment.
  const [nudged, setNudged] = useFlash<true>(NUDGE_MS)

  useEffect(() => {
    if (video.current) video.current.srcObject = stream
  }, [stream])

  // Let go of every key and button the desktop still holds, so none stays stuck down.
  const releaseAll = () => {
    for (const key of pressed.current) send({ type: "key", key, down: false })
    for (const button of buttons.current)
      send({ type: "button", button, down: false })
    pressed.current.clear()
    buttons.current.clear()
  }
  const releaseRef = useRef(releaseAll)
  useEffect(() => {
    releaseRef.current = releaseAll
  })
  useEffect(() => {
    if (!interactive) releaseRef.current()
  }, [interactive])

  // Keys go straight to the desktop after a takeover, with no click on the screen first, which would click the desktop
  // as well. Not on a touch screen, where the focus would bring up its keyboard over the screen.
  const focused = useEffectEvent(onFocused)
  useEffect(() => {
    if (!focus || !interactive) return
    if (matchMedia("(pointer: fine)").matches)
      keyboard.current?.focus({ preventScroll: true })
    focused()
  }, [focus, interactive])

  // React attaches wheel listeners as passive; this one must stop the page from scrolling.
  useEffect(() => {
    const element = video.current
    if (!element || !interactive) return
    const onWheel = (event: WheelEvent) => {
      event.preventDefault()
      const point = toScreen(element, event.clientX, event.clientY)
      if (!point) return
      const unit =
        event.deltaMode === 1
          ? WHEEL_STEP / 3
          : event.deltaMode === 2
            ? WHEEL_STEP * 3
            : 1
      wheel.current.x += event.deltaX * unit
      wheel.current.y += event.deltaY * unit
      for (const axis of ["x", "y"] as const) {
        while (Math.abs(wheel.current[axis]) >= WHEEL_STEP) {
          const forward = wheel.current[axis] > 0
          wheel.current[axis] -= forward ? WHEEL_STEP : -WHEEL_STEP
          const direction =
            axis === "y"
              ? forward
                ? "down"
                : "up"
              : forward
                ? "right"
                : "left"
          send({ type: "wheel", direction, ...point })
        }
      }
    }
    element.addEventListener("wheel", onWheel, { passive: false })
    return () => element.removeEventListener("wheel", onWheel)
  }, [interactive, send])

  // The desktop's pointer is drawn here, never in the video, so it is sharp, one size whatever the video's, and in
  // the page's theme. While the user has control it is at the mouse with no delay (the video is a frame or more
  // behind); while the agent has it, where the runtime says the agent's is. The agent's moves are jumps, so the pointer
  // slides to each new spot; when the video resizes it is placed again at once.
  const cursor = useRef<HTMLDivElement>(null)
  function placeCursor(event: PointerEvent<HTMLVideoElement> | null) {
    if (!event) return showPointer(cursor.current, null)
    const rect = event.currentTarget.getBoundingClientRect()
    showPointer(cursor.current, {
      left: event.clientX - rect.left,
      top: event.clientY - rect.top,
    })
  }
  const placeAgent = useEffectEvent((glide: boolean) => {
    const element = video.current
    if (interactive || !element) return
    showPointer(cursor.current, pointer && fromScreen(element, pointer), glide)
  })
  useLayoutEffect(() => placeAgent(true), [interactive, pointer])
  // Apart from the effect above: a new observer reports the size at once, which would cut each slide short.
  useLayoutEffect(() => {
    const element = video.current
    if (interactive || !element) return
    const place = () => placeAgent(false)
    const observer = new ResizeObserver(place)
    observer.observe(element)
    element.addEventListener("resize", place) // the video's own size, known once its first frame is in
    return () => {
      observer.disconnect()
      element.removeEventListener("resize", place)
    }
  }, [interactive])

  // While the agent thinks, its pointer swings about the tip, so the screen does not look stuck.
  const sway = useRef<HTMLDivElement>(null)
  const swaying = useRef<ReturnType<typeof createCursorSway>>(null)
  useEffect(() => {
    if (!sway.current) return
    const created = createCursorSway(sway.current)
    swaying.current = created
    return () => {
      created.dispose()
      swaying.current = null
    }
  }, [])
  const swings = thinking && !interactive && pointer !== null
  useEffect(() => swaying.current?.set(swings), [swings])

  function onPointerMove(event: PointerEvent<HTMLVideoElement>) {
    if (!interactive) return
    placeCursor(event)
    pendingMove.current = toScreen(
      event.currentTarget,
      event.clientX,
      event.clientY
    )
    // At most one move per frame; the runtime also keeps only the latest one it has not applied yet.
    frame.current ||= requestAnimationFrame(() => {
      frame.current = 0
      if (pendingMove.current) send({ type: "move", ...pendingMove.current })
    })
  }

  function onPointerButton(
    event: PointerEvent<HTMLVideoElement>,
    down: boolean
  ) {
    const button = BUTTONS[event.button]
    if (!interactive || !button) return
    event.preventDefault()
    if (down) {
      const point = toScreen(event.currentTarget, event.clientX, event.clientY)
      if (!point) return
      event.currentTarget.setPointerCapture(event.pointerId)
      keyboard.current?.focus({ preventScroll: true })
      send({ type: "move", ...point })
      buttons.current.add(button)
    } else if (!buttons.current.delete(button)) {
      return
    }
    send({ type: "button", button, down })
  }

  function onKey(event: KeyboardEvent<HTMLTextAreaElement>, down: boolean) {
    // Keys that compose text in an input method are its business; the text arrives at compositionend.
    if (isComposing(event.nativeEvent)) return
    const key = keyName(event.code)
    if (!key) return
    event.preventDefault()
    if (down) pressed.current.add(key)
    else if (!pressed.current.delete(key)) return
    send({ type: "key", key, down })
  }

  // One pill at the bottom: what just happened, else how to type, else why a click did nothing.
  const hint = notice
    ? { text: notice, news: true }
    : interactive
      ? !typing && { text: t.liveView.clickToType, news: false }
      : nudged && { text: t.liveView.takeOverFirst, news: true }

  return (
    <>
      <video
        ref={video}
        autoPlay
        muted
        playsInline
        disablePictureInPicture
        onPointerMove={onPointerMove}
        onPointerDown={(event) =>
          interactive ? onPointerButton(event, true) : setNudged(true)
        }
        onPointerUp={(event) => onPointerButton(event, false)}
        onPointerLeave={() => interactive && placeCursor(null)}
        onContextMenu={(event) => interactive && event.preventDefault()}
        className={cn(
          "absolute inset-0 size-full object-contain",
          interactive && "cursor-none touch-none"
        )}
      />
      <div
        ref={cursor}
        aria-hidden
        className="pointer-events-none absolute top-0 left-0 opacity-0 will-change-transform data-glide:duration-180 data-glide:ease-(--ease-out) motion-safe:data-glide:transition-transform"
      >
        <div ref={sway} className="relative origin-top-left">
          {!interactive && pointer !== null && <AgentCursorGlow />}
          {/* The favicon's pointer at 0.8 its size, rounded the same way (a stroke of its own color), black with a 2 px
              white edge and a soft glow; the black tip (3, 3) sits on the point. */}
          <svg
            width="24"
            height="24"
            viewBox="0 0 24 24"
            strokeLinejoin="round"
            className="-translate-x-[3px] -translate-y-[3px] [filter:drop-shadow(0_0_1px_var(--takeover))_drop-shadow(0_0_6px_var(--takeover))]"
          >
            <path
              d={CURSOR_PATH}
              fill="white"
              stroke="white"
              strokeWidth="6.4"
            />
            <path
              d={CURSOR_PATH}
              fill="#171717"
              stroke="#171717"
              strokeWidth="2.4"
            />
          </svg>
        </div>
      </div>
      {interactive && (
        <textarea
          ref={keyboard}
          aria-label={t.liveView.keyboard}
          className="pointer-events-none absolute top-0 left-0 size-px opacity-0"
          onFocus={() => setTyping(true)}
          onBlur={() => {
            setTyping(false)
            releaseAll()
          }}
          onKeyDown={(event) => onKey(event, true)}
          onKeyUp={(event) => onKey(event, false)}
          onCompositionEnd={(event) => {
            if (event.data) send({ type: "text", text: event.data })
            event.currentTarget.value = ""
          }}
          onInput={(event) => {
            // Text that arrived without a key press or a composition, such as dictation.
            const field = event.currentTarget
            if ((event.nativeEvent as InputEvent).isComposing || !field.value)
              return
            send({ type: "text", text: field.value })
            field.value = ""
          }}
        />
      )}
      {hint && (
        // Keyed by its text, so each message fades in as it comes. Only news is announced: "click to type" stands.
        <p
          key={hint.text}
          role={hint.news ? "status" : undefined}
          className="pointer-events-none absolute bottom-2 left-1/2 -translate-x-1/2 animate-in rounded-full bg-black/70 px-3 py-1 text-xs whitespace-nowrap text-white duration-150 fade-in"
        >
          {hint.text}
        </p>
      )}
    </>
  )
}
