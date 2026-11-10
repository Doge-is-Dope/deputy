import { useLayoutEffect, useRef, useState } from "react"
import { cn } from "cn"

import { reducedMotion } from "@/lib/motion"

/** Show the first message until a title arrives. Animate only titles received while mounted;
 * reduced motion replaces the text immediately. */
export function ConversationName({
  name,
  placeholder,
  naming,
}: {
  name: string | null
  placeholder: string
  naming: boolean // the run works and no name has come yet
}) {
  // Only a name that comes while the item is on the page rolls in.
  const [arrives] = useState(() => name === null && !reducedMotion())
  const [rolled, setRolled] = useState(false)
  const rolling = name !== null && arrives && !rolled
  const line = useRef<HTMLSpanElement>(null)
  useLayoutEffect(() => {
    const element = line.current
    if (!rolling || !element) return
    const { width } = element.getBoundingClientRect()
    const [message, title] = element.children
    const characters = rollingCharacters(
      placed(message, width),
      placed(title, width)
    )
    element.append(...characters)
    // A roll that is cut short rejects: its row has gone, or this effect runs again.
    Promise.all(
      element.getAnimations({ subtree: true }).map(({ finished }) => finished)
    ).then(
      () => setRolled(true),
      () => {}
    )
    return () => characters.forEach((character) => character.remove())
  }, [rolling])
  if (name === null)
    return (
      <span
        className={cn(
          // The shimmer's band matches the row under it: the sidebar, or the accent over it on a hovered or chosen row.
          naming &&
            "shimmer [--shimmer-surface:var(--sidebar)] group-hover/menu-button:[--shimmer-surface:var(--sidebar-accent-solid)] group-data-active/menu-button:[--shimmer-surface:var(--sidebar-accent-solid)]"
        )}
      >
        {placeholder}
      </span>
    )
  // The copies hold the line and show where plain text puts each character; the row around them clips the roll.
  if (rolling)
    return (
      <span ref={line} aria-label={name} className="relative block">
        <span className="invisible absolute">{placeholder}</span>
        <span className="invisible">{name}</span>
      </span>
    )
  return <>{name}</>
}

// How long the wave takes to cross a pixel of the row: a full row in about 600ms.
const MS_PER_PX = 3

// Characters in the same column of the row share their timing, so one never arrives over one still leaving.
const COLUMN_PX = 8

const GRAPHEMES = new Intl.Segmenter(undefined, { granularity: "grapheme" })

/** A character showing in the row, where plain text puts it: on the page (start) and in the row (x). */
type Placed = { segment: string; start: number; x: number }

/** The characters of `copy` that show in the row, read from laid-out text: cells side by side would lose the font's
 * kerning, and any width they gave up would move everything after them. */
function placed(copy: Element, width: number) {
  const text = copy.firstChild as Text
  const { left } = copy.getBoundingClientRect()
  const range = document.createRange()
  const characters: Placed[] = []
  for (const { segment, index } of GRAPHEMES.segment(text.data)) {
    if (!segment.trim()) continue
    range.setStart(text, index)
    range.setEnd(text, index + segment.length)
    const start = range.getBoundingClientRect().left
    if (start - left >= width) break
    characters.push({ segment, start, x: start - left })
  }
  return characters
}

/** The spans that carry the message into the name: what both start with stays where it is, every other character
 * rolls. */
function rollingCharacters(message: Placed[], name: Placed[]) {
  const first = name.findIndex(
    ({ segment, start }, index) =>
      segment !== message[index]?.segment ||
      Math.abs(start - message[index].start) > 0.5
  )
  const same = first < 0 ? name.length : first
  return [
    ...name
      .slice(0, same)
      .map((character) => rollingSpan(character, "name-char-kept")),
    ...message
      .slice(same)
      .map((character) => rollingSpan(character, "name-char-out")),
    ...name
      .slice(same)
      .map((character) => rollingSpan(character, "name-char-in")),
  ]
}

function rollingSpan({ segment, start, x }: Placed, className: string) {
  const span = document.createElement("span")
  span.className = className
  span.textContent = segment
  // Each column lands a little early or late, quick or slow, and leaning: an even wave looks mechanical.
  const column = Math.round(x / COLUMN_PX)
  const at = x * MS_PER_PX * (1 + 0.15 * noise(column, 2))
  const duration = 300 * (1 + 0.27 * noise(column, 1))
  // A leaning box is drawn from a whole device pixel: start it on one and pad the rest of the way, or its text would
  // hop by a fraction of a pixel as it starts and as it lands.
  const edge = Math.floor(start * devicePixelRatio) / devicePixelRatio
  span.style.left = `${x - (start - edge)}px`
  span.style.paddingLeft = `${start - edge}px`
  span.style.setProperty("--at", `${at}ms`)
  span.style.setProperty("--for", `${duration}ms`)
  span.style.setProperty("--tilt", `${3 * noise(column, 3)}deg`)
  return span
}

/** Repeatable noise from -1 to 1 for a column of the row, a different sequence on each channel. */
function noise(column: number, channel: number) {
  const seed = Math.sin(column * 12.9898 + channel * 78.233) * 43758.5453
  return (seed - Math.floor(seed)) * 2 - 1
}
