import {
  useEffect,
  useEffectEvent,
  useImperativeHandle,
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type Ref,
} from "react"
import { cn } from "cn"

import { TrashIcon } from "@/components/icons"
import { Button } from "@/components/ui/button"
import { useAppearance } from "@/lib/appearance"
import { useT } from "@/lib/i18n"
import {
  COLORS,
  MAX_SCALE,
  UNZOOMED,
  applied,
  commentsOf,
  constrained,
  drawnOf,
  held,
  redone,
  shapePath,
  sizesFor,
  strokePath,
  undone,
  zoomedAt,
  type Color,
  type Drawn as DrawnMark,
  type Mark,
  type Markup,
  type Point,
  type Sizes,
  type Tool,
  type View,
} from "@/lib/markup"

/** A stroke or a shape as the page draws it, from the paths the file is drawn with. */
function Drawn({ mark, sizes }: { mark: DrawnMark; sizes: Sizes }) {
  const color = COLORS[mark.color]
  if (mark.kind === "pen")
    return <path d={strokePath(mark.points, sizes.line)} fill={color} />
  return (
    <path
      d={shapePath(mark.kind, mark.from, mark.to, sizes.line)}
      fill="none"
      stroke={color}
      strokeWidth={sizes.line}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  )
}

// A pin is this tall and wide on the page at any zoom; what is written to it opens this far beside it.
const PIN = 22
const GAP = 8
// The field a new comment is typed in, and the card an earlier one is changed or deleted in.
const FIELD_WIDTH = 240
const CARD_WIDTH = 256

/** Ink or white, whichever reads on `background` (a #rrggbb color). */
function inkOn(background: string) {
  const [r, g, b] = [1, 3, 5].map((at) => {
    const value = parseInt(background.slice(at, at + 2), 16) / 255
    return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4
  })
  const luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
  const inkLuminance = ((13 / 255 + 0.055) / 1.055) ** 2.4
  const whiteContrast = 1.05 / (luminance + 0.05)
  const inkContrast =
    (Math.max(luminance, inkLuminance) + 0.05) /
    (Math.min(luminance, inkLuminance) + 0.05)
  return inkContrast > whiteContrast ? "#0d0d0d" : "#ffffff"
}

/** A comment's pin: a bubble with its number, in the theme's light accent (its notes sit on pictures, mostly light),
 * its pointed corner on the spot it is about, where the comment tool's pointer had it (bubbleCursor). */
function Pin({
  number,
  at,
  accent,
  open,
  label,
  text,
  onOpen,
}: {
  number: number
  at: Point // on the frame, where its corner goes
  accent: string
  open: boolean
  label: string
  text?: string
  onOpen?: () => void
}) {
  return (
    <button
      type="button"
      aria-label={label}
      aria-expanded={open}
      title={text}
      onPointerDown={(event) => event.stopPropagation()}
      onClick={onOpen}
      className="pointer-events-auto absolute flex size-5.5 -translate-y-full items-center justify-center rounded-full rounded-bl-none text-xs font-medium tabular-nums shadow-sm"
      style={{
        left: at[0],
        top: at[1],
        backgroundColor: accent,
        color: inkOn(accent),
      }}
    >
      {number}
    </button>
  )
}

/** The comment tool's pointer: an empty pin, its point the spot it goes to. */
function bubbleCursor(accent: string) {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${PIN}" height="${PIN}"><path d="M0 ${PIN}H11A11 11 0 0 0 11 0A11 11 0 0 0 0 11V${PIN}Z" fill="${accent}"/></svg>`
  return `url("data:image/svg+xml,${encodeURIComponent(svg)}") 0 ${PIN - 1}, crosshair`
}

/** The pen's pointer: a dot of its colour as wide as its line on screen, ringed in white to show on a dark picture. */
function dotCursor(color: string, line: number) {
  const dot = Math.max(6, 2 * Math.round(line / 2))
  const middle = dot / 2 + 1
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${dot + 2}" height="${dot + 2}"><circle cx="${middle}" cy="${middle}" r="${dot / 2}" fill="${color}" stroke="white"/></svg>`
  return `url("data:image/svg+xml,${encodeURIComponent(svg)}") ${middle} ${middle}, crosshair`
}

type Note = { id: string | null; at: Point; value: string }

/** What is written to a pin, beside it: a new comment in one rounded line, or an earlier one in a card that also
 * deletes it. Enter keeps it and Shift+Enter starts a new line; Esc leaves it as it was; while a character is being
 * composed (an input method), its keys are its own. */
function NoteField({
  note,
  place,
  onChange,
  onSave,
  onCancel,
  onDelete,
}: {
  note: Note
  place: { left: number; top: number; translate: string }
  onChange: (value: string) => void
  onSave: () => void
  onCancel: () => void
  onDelete: () => void
}) {
  const t = useT()
  const field = useRef<HTMLTextAreaElement>(null)
  useEffect(() => {
    const element = field.current!
    element.focus({ preventScroll: true })
    element.setSelectionRange(element.value.length, element.value.length)
  }, [])
  const keys = (event: ReactKeyboardEvent) => {
    if (event.nativeEvent.isComposing || event.keyCode === 229) return
    event.stopPropagation()
    if (event.key === "Escape") onCancel()
    else if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault()
      onSave()
    }
  }
  const card = note.id !== null
  return (
    <div
      className={cn(
        "pointer-events-auto absolute bg-background text-foreground shadow-[0_4px_16px_rgb(0_0_0/0.12)] ring-1 ring-foreground/10",
        card
          ? "flex flex-col gap-2 rounded-3xl p-2"
          : "flex h-10 items-center rounded-full px-4"
      )}
      style={{ ...place, width: card ? CARD_WIDTH : FIELD_WIDTH }}
      onPointerDown={(event) => event.stopPropagation()}
    >
      <textarea
        ref={field}
        rows={card ? 3 : 1}
        value={note.value}
        placeholder={t.markup.commentPlaceholder}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={keys}
        // Never under 16 on a phone, which zooms the page in for a smaller field.
        className={cn(
          "w-full resize-none bg-transparent text-base leading-5 outline-none placeholder:text-muted-foreground md:text-sm",
          card ? "px-2 pt-2" : "h-5 overflow-hidden"
        )}
      />
      {card && (
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="icon-sm"
            className="rounded-full"
            aria-label={t.markup.deleteComment}
            onClick={onDelete}
          >
            <TrashIcon className="size-4" />
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="ml-auto rounded-full"
            onClick={onCancel}
          >
            {t.common.cancel}
          </Button>
          <Button size="sm" className="rounded-full" onClick={onSave}>
            {t.markup.saveComment}
          </Button>
        </div>
      )}
    </div>
  )
}

/**
 * The picture, fitted to its place, with its marks drawn over it in its own pixels. Zoomed with ⌘ or Ctrl and the
 * wheel (a trackpad's pinch), or two fingers, and moved once zoomed in. While marking up, the pointer draws with the
 * tool: a stroke, a shape dragged out, or a comment where it taps, a numbered pin whose words go with the message;
 * a pin opens what is written to it, to change or delete. A mark is taken back by undoing it.
 */
export function MarkupStage({
  src,
  under,
  alt,
  width,
  height,
  markup,
  onMarkup,
  tool,
  color,
  onWriting,
  ref,
}: {
  src: string | null // null until the file has come
  under?: string // a small copy shown until it has
  alt: string
  width: number
  height: number
  markup: Markup | null // null unless it is being marked up
  onMarkup: (markup: Markup) => void
  tool: Tool
  color: Color
  onWriting: (writing: boolean) => void // whether a comment's words are typed and not yet kept
  ref?: Ref<{ flush: () => void }> // keeps a comment being written; done too as the picture goes
}) {
  const t = useT()
  const editing = markup !== null
  const accent = useAppearance().themes.light.accent
  const box = useRef<HTMLDivElement>(null)
  const frame = useRef<HTMLDivElement>(null)
  const svg = useRef<SVGSVGElement>(null)
  const [room, setRoom] = useState({ width: 0, height: 0 })
  // How far it is zoomed and moved, moved in shares of its shown size: a panel made wider keeps the same part in sight.
  const [zoom, setZoom] = useState<View>(UNZOOMED)
  const [live, setLive] = useState<DrawnMark | null>(null)
  const [note, setNoteState] = useState<Note | null>(null)
  // Read as it is now: a tap elsewhere, the tool's change and the picture going all keep it, once.
  const writing = useRef<Note | null>(null)
  const setNote = (next: Note | null) => {
    writing.current = next
    setNoteState(next)
  }
  const [shown, setShown] = useState<string | null>(null)
  const pointers = useRef(new Map<number, Point>())
  const gesture = useRef<
    | { kind: "pinch"; distance: number; middle: Point; view: View }
    | { kind: "pan"; from: Point; view: View }
    | null
  >(null)

  useLayoutEffect(() => {
    const element = box.current
    if (!element) return
    const observer = new ResizeObserver(([entry]) =>
      setRoom({
        width: entry.contentRect.width,
        height: entry.contentRect.height,
      })
    )
    observer.observe(element)
    return () => observer.disconnect()
  }, [])
  const fit =
    room.width && room.height
      ? Math.min(room.width / width, room.height / height)
      : 0
  const shownWidth = width * fit
  const shownHeight = height * fit
  const view = {
    scale: zoom.scale,
    x: zoom.x * shownWidth,
    y: zoom.y * shownHeight,
  }
  const setView = (next: View) =>
    setZoom({
      scale: next.scale,
      x: shownWidth ? next.x / shownWidth : 0,
      y: shownHeight ? next.y / shownHeight : 0,
    })
  const sizes = sizesFor(width, height)
  const marks = markup?.marks ?? []
  const comments = commentsOf(marks)

  // Where the pointer is on the picture, in its pixels; and in the frame, for zooming about it.
  const onPicture = (x: number, y: number): Point => {
    const rect = svg.current!.getBoundingClientRect()
    return [
      ((x - rect.left) / rect.width) * width,
      ((y - rect.top) / rect.height) * height,
    ]
  }
  const inFrame = (x: number, y: number): Point => {
    const rect = frame.current!.getBoundingClientRect()
    return [x - rect.left, y - rect.top]
  }
  // A spot on the picture, on the frame as it is zoomed and moved.
  const onFrame = ([x, y]: Point): Point => [
    view.x + (x / width) * shownWidth * view.scale,
    view.y + (y / height) * shownHeight * view.scale,
  ]
  // A comment's spot (in shares of the picture) on the frame.
  const pinned = ([x, y]: Point) => onFrame([x * width, y * height])
  const inSight = ([x, y]: Point) =>
    x >= 0 && x <= shownWidth && y >= 0 && y <= shownHeight

  const change = (next: Mark[]) => onMarkup(applied(markup!, next))

  /** The comment being written kept: a new one with words added, an earlier one changed, or deleted if emptied. */
  function saveNote() {
    const note = writing.current
    if (!note) return
    setNote(null)
    const text = note.value.trim()
    if (note.id === null) {
      if (text)
        change([
          ...marks,
          { id: crypto.randomUUID(), kind: "comment", at: note.at, text },
        ])
      return
    }
    const before = comments.find((each) => each.id === note.id)
    if (!text) change(marks.filter((mark) => mark.id !== note.id))
    else if (before && before.text !== text)
      change(
        marks.map((mark) => (mark.id === note.id ? { ...mark, text } : mark))
      )
  }

  function deleteNote() {
    const note = writing.current
    setNote(null)
    if (note?.id) change(marks.filter((mark) => mark.id !== note.id))
  }

  useImperativeHandle(ref, () => ({ flush: saveNote }))
  const putDown = useEffectEvent(saveNote)
  useEffect(() => () => putDown(), [])
  // Words changed and not yet kept count as a change: closing the tab asks first, and the message waits for them.
  const kept = note?.id
    ? comments.find((each) => each.id === note.id)?.text
    : ""
  const typed = note !== null && note.value.trim() !== (kept ?? "")
  const tell = useEffectEvent(onWriting)
  useEffect(() => tell(typed), [typed])
  useEffect(() => () => tell(false), [])

  // ⌘/Ctrl and the wheel zoom about the pointer; once zoomed in, the wheel alone moves it. Over the pins and what is
  // written to one too, and the room around the picture. Not passive, so the page doesn't zoom or scroll instead.
  const wheel = useEffectEvent((event: WheelEvent) => {
    if (event.ctrlKey || event.metaKey) {
      event.preventDefault()
      const factor = Math.exp(-event.deltaY * 0.01)
      setView(
        zoomedAt(
          view,
          factor,
          inFrame(event.clientX, event.clientY),
          shownWidth,
          shownHeight
        )
      )
    } else if (
      view.scale > 1 &&
      !(event.target as Element).closest("textarea")
    ) {
      event.preventDefault()
      setView(
        held(
          { ...view, x: view.x - event.deltaX, y: view.y - event.deltaY },
          shownWidth,
          shownHeight
        )
      )
    }
  })
  useEffect(() => {
    const element = box.current
    if (!element) return
    element.addEventListener("wheel", wheel, { passive: false })
    return () => element.removeEventListener("wheel", wheel)
  }, [])

  // ⌘Z and ⇧⌘Z undo and redo. Not while a comment is being written.
  const press = useEffectEvent((event: KeyboardEvent) => {
    const target = event.target as HTMLElement
    if (target.closest("input, textarea, [contenteditable]")) return
    if (!markup) return
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "z") {
      event.preventDefault()
      onMarkup(event.shiftKey ? redone(markup) : undone(markup))
    }
  })
  useEffect(() => {
    if (!editing) return
    window.addEventListener("keydown", press)
    return () => window.removeEventListener("keydown", press)
  }, [editing])

  // While a comment is written, wherever the focus went (a button pressed meanwhile leaves it open): Esc or a tap
  // beside it in the panel leaves it as it was, Return keeps it. A tap out of the panel (into the composer) leaves it
  // open, still to be kept.
  const overlay = useRef<HTMLDivElement>(null)
  const noteKey = useEffectEvent((event: KeyboardEvent) => {
    if (event.isComposing || event.keyCode === 229) return
    // A field's keys and an open menu's (Enter picks, Esc closes it) are their own, and so is Enter on a pin (it opens)
    // or on the card's buttons.
    const target = event.target as Element
    if (
      target.closest(
        "input, textarea, [contenteditable], [role^=menu], [role=listbox], [role=dialog]"
      )
    )
      return
    if (
      event.key !== "Escape" &&
      (event.key !== "Enter" ||
        event.shiftKey ||
        overlay.current!.contains(target))
    )
      return
    event.preventDefault()
    event.stopPropagation()
    if (event.key === "Escape") setNote(null)
    else saveNote()
  })
  const noteTap = useEffectEvent((event: PointerEvent) => {
    const target = event.target as Element
    if (frame.current!.contains(target) || overlay.current!.contains(target))
      return
    if (
      !target.closest("[role=tabpanel]") ||
      target.closest("button, a, input, textarea, select, [role^=menu]")
    )
      return
    setNote(null)
  })
  const open = note !== null
  useEffect(() => {
    if (!open) return
    window.addEventListener("keydown", noteKey, true)
    window.addEventListener("pointerdown", noteTap, true)
    return () => {
      window.removeEventListener("keydown", noteKey, true)
      window.removeEventListener("pointerdown", noteTap, true)
    }
  }, [open])

  function down(event: ReactPointerEvent) {
    if (event.button > 0) return
    frame.current!.setPointerCapture(event.pointerId)
    pointers.current.set(event.pointerId, [event.clientX, event.clientY])
    const [a, b] = [...pointers.current.values()]
    if (b) {
      // Two fingers: the stroke under way is dropped, and they zoom and move the picture.
      setLive(null)
      gesture.current = {
        kind: "pinch",
        distance: Math.hypot(b[0] - a[0], b[1] - a[1]),
        middle: inFrame((a[0] + b[0]) / 2, (a[1] + b[1]) / 2),
        view,
      }
      return
    }
    if (!editing) {
      if (view.scale > 1)
        gesture.current = {
          kind: "pan",
          from: [event.clientX, event.clientY],
          view,
        }
      return
    }
    event.preventDefault()
    // The picture takes the keyboard from the tool just clicked, so a key (Shift, to keep a shape square) lights no
    // ring on that button.
    frame.current!.focus({ preventScroll: true })
    // A tap beside a comment being written leaves it as it was, and does nothing else.
    if (writing.current) {
      setNote(null)
      return
    }
    const at = onPicture(event.clientX, event.clientY)
    const id = crypto.randomUUID()
    if (tool === "pen")
      setLive({
        id,
        kind: "pen",
        color,
        points: [[at[0], at[1], event.pressure || 0.5]],
      })
    else if (tool === "rect" || tool === "ellipse" || tool === "arrow")
      setLive({ id, kind: tool, color, from: at, to: at })
    else setNote({ id: null, at: [at[0] / width, at[1] / height], value: "" })
  }

  function move(event: ReactPointerEvent) {
    if (!pointers.current.has(event.pointerId)) return
    pointers.current.set(event.pointerId, [event.clientX, event.clientY])
    const now = gesture.current
    if (now?.kind === "pinch") {
      const [a, b] = [...pointers.current.values()]
      if (!b) return
      const middle = inFrame((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
      const scale = Math.min(
        MAX_SCALE,
        Math.max(
          1,
          now.view.scale * (Math.hypot(b[0] - a[0], b[1] - a[1]) / now.distance)
        )
      )
      const ratio = scale / now.view.scale
      setView(
        held(
          {
            scale,
            x: middle[0] - (now.middle[0] - now.view.x) * ratio,
            y: middle[1] - (now.middle[1] - now.view.y) * ratio,
          },
          shownWidth,
          shownHeight
        )
      )
      return
    }
    if (now?.kind === "pan") {
      setView(
        held(
          {
            ...now.view,
            x: now.view.x + event.clientX - now.from[0],
            y: now.view.y + event.clientY - now.from[1],
          },
          shownWidth,
          shownHeight
        )
      )
      return
    }
    const at = onPicture(event.clientX, event.clientY)
    setLive((mark) => {
      if (!mark) return mark
      if (mark.kind === "pen") {
        const points = (
          event.nativeEvent.getCoalescedEvents?.() ?? [event.nativeEvent]
        ).map((each): [number, number, number] => {
          const [x, y] = onPicture(each.clientX, each.clientY)
          return [x, y, each.pressure || 0.5]
        })
        return { ...mark, points: [...mark.points, ...points] }
      }
      return {
        ...mark,
        to: event.shiftKey ? constrained(mark.kind, mark.from, at) : at,
      }
    })
  }

  function up(event: ReactPointerEvent) {
    if (!pointers.current.delete(event.pointerId)) return
    const now = gesture.current
    if (now?.kind === "pinch") {
      if (pointers.current.size === 0) gesture.current = null
      return
    }
    gesture.current = null
    if (event.type === "pointercancel") {
      setLive(null)
      return
    }
    if (!live) return
    setLive(null)
    // Left while drawing (Esc, Return): there is no markup to keep it in.
    if (!markup) return
    // A shape needs some size to be kept; a tap leaves none.
    if (
      live.kind === "pen" ||
      Math.hypot(live.to[0] - live.from[0], live.to[1] - live.from[1]) >
        sizes.line * 2
    )
      change([...marks, live])
  }

  // Where what is written to a pin opens: beside it, on its right, or its left where the panel has no room; level
  // with its middle, but kept within the room the picture has, clear of the tabs above and the bar below. It is moved
  // up or down by its own height (a share of it), so it needs no measuring.
  const notePlace = (at: Point, wide: number) => {
    const [x, y] = pinned(at)
    const spare = (room.width - shownWidth) / 2
    const right = x + PIN + GAP
    const left =
      right + wide <= shownWidth + spare - GAP
        ? right
        : Math.max(-spare + GAP, x - GAP - wide)
    const top = y - PIN / 2
    const below = (room.height - shownHeight) / 2 // the room above the picture and below it, each
    return {
      left,
      top,
      translate: `0 clamp(${-below + GAP - top}px, -50%, calc(${shownHeight + below - GAP - top}px - 100%))`,
    }
  }
  const cursor = !editing ? view.scale > 1 && "cursor-grab" : "cursor-crosshair"
  const pointer = !editing
    ? undefined
    : tool === "comment"
      ? bubbleCursor(accent)
      : tool === "pen"
        ? dotCursor(COLORS[color], sizes.line * fit * view.scale)
        : undefined
  const pins = [
    ...comments.map((each, index) => ({
      id: each.id,
      at: each.at,
      number: index + 1,
      text: each.text,
    })),
    ...(note && note.id === null
      ? [{ id: null, at: note.at, number: comments.length + 1, text: "" }]
      : []),
  ]
  return (
    <div ref={box} className="flex size-full items-center justify-center">
      <div
        className="relative"
        style={{ width: shownWidth, height: shownHeight }}
      >
        <div
          ref={frame}
          tabIndex={-1}
          className={cn(
            "relative size-full touch-none overflow-hidden bg-muted ring-1 ring-foreground/5 outline-none select-none",
            cursor
          )}
          style={{ cursor: pointer }}
          onPointerDown={down}
          onPointerMove={move}
          onPointerUp={up}
          onPointerCancel={up}
        >
          <div
            className="absolute inset-0 origin-top-left"
            style={{
              transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})`,
            }}
          >
            {under && (
              <img
                src={under}
                alt=""
                draggable={false}
                className="pointer-events-none absolute inset-0 size-full"
              />
            )}
            {/* Fades in over the small copy, or the empty frame, once decoded. */}
            {src && (
              <img
                key={src}
                src={src}
                alt={alt}
                draggable={false}
                onLoad={() => setShown(src)}
                className={cn(
                  "pointer-events-none relative size-full transition-opacity duration-200 ease-(--ease-out)",
                  shown !== src && "opacity-0"
                )}
              />
            )}
            <svg
              ref={svg}
              viewBox={`0 0 ${width} ${height}`}
              className="pointer-events-none absolute inset-0 size-full overflow-visible"
            >
              {[...drawnOf(marks), ...(live ? [live] : [])].map((mark) => (
                <Drawn key={mark.id} mark={mark} sizes={sizes} />
              ))}
            </svg>
          </div>
        </div>
        {/* Over the picture and not cut by its edge, at one size at any zoom: the pins, and what is written to one. */}
        <div ref={overlay} className="pointer-events-none absolute inset-0">
          {pins
            .filter((pin) => inSight(pinned(pin.at)))
            .map((pin) => (
              <Pin
                key={pin.id ?? "new"}
                number={pin.number}
                at={pinned(pin.at)}
                accent={accent}
                open={note !== null && note.id === pin.id}
                label={t.markup.commentNumber(pin.number)}
                text={pin.text || undefined}
                onOpen={
                  pin.id === null
                    ? undefined
                    : () => {
                        saveNote()
                        setNote({ id: pin.id, at: pin.at, value: pin.text })
                      }
                }
              />
            ))}
          {note && (
            <NoteField
              key={note.id ?? "new"}
              note={note}
              place={notePlace(
                note.at,
                note.id === null ? FIELD_WIDTH : CARD_WIDTH
              )}
              onChange={(value) => setNote({ ...note, value })}
              onSave={saveNote}
              onCancel={() => setNote(null)}
              onDelete={deleteNote}
            />
          )}
        </div>
      </div>
    </div>
  )
}
