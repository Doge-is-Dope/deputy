import { useLayoutEffect, useRef, useState } from "react"
import { cn } from "cn"
import { slotText } from "slot-text"

import { reducedMotion } from "@/lib/motion"

/** Show the first message until a title arrives. Animate only titles received while mounted;
 * reduced motion replaces the text immediately. Preserve kerning when switching to and from cells. */
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
  const cell = useRef<HTMLSpanElement>(null)
  useLayoutEffect(() => {
    const element = cell.current
    if (!rolling || !element || name === null) return
    // The visible part of the message is enough to roll from: the item shows a few dozen characters at most.
    const from = Array.from(placeholder).slice(0, ROLL_FROM).join("")
    // Every character rolls, the ones the name shares with the message too: one left in place would stay dimmed.
    const label = slotText(element, from, {
      rollBy: "character",
      direction: "up",
      skipUnchanged: false,
    })
    element
      .querySelectorAll<HTMLElement>(".char-face")
      .forEach((face) => (face.style.color = "var(--muted-foreground)"))
    const kerned = kerning(element, from)
    kern(element, kerned)
    // slot-text's 45ms between characters, closer for a long name, so it lands within about a second.
    const stagger = Math.min(45, Math.round(600 / Math.max(1, name.length - 1)))
    label.set(name, { stagger, color: "var(--muted-foreground)" })
    // Each cell takes the name's kerning as its character rolls in, so no character still in place moves.
    const target = kerning(element, name)
    element.querySelectorAll<HTMLElement>(".char-slot").forEach((slot, index) =>
      slot.animate(
        {
          marginRight: [`${kerned[index] ?? 0}px`, `${target[index] ?? 0}px`],
        },
        {
          duration: 300,
          delay: index * stagger,
          easing: "ease-out",
          fill: "both",
        }
      )
    )
    // Its last step puts the settled text in place of the cells, kerned as the name was: then it is plain text again.
    const settled = new MutationObserver(() => {
      kern(element, target)
      setRolled(true)
    })
    settled.observe(element, { childList: true })
    return () => {
      settled.disconnect()
      label.destroy()
    }
  }, [rolling]) // eslint-disable-line react-hooks/exhaustive-deps
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
  // A cell rolling out to nothing keeps the line's height and place: slot-text empties its sizer at once, and the
  // cell, clipped above and below and with no baseline to line up by, would drop or lose its character before it
  // rolls out. A character at rest is drawn with the page, not on a layer of its own (slot-text's will-change), which
  // Chrome puts on whole pixels: drawn so, it sits where plain text puts it, and nothing shifts as the cells go.
  if (rolling)
    return (
      <span
        ref={cell}
        aria-label={name}
        className="[&_.char-face]:will-change-auto! [&_.char-slot]:self-stretch"
      />
    )
  return <>{name}</>
}

// The characters of the message a name rolls in from.
const ROLL_FROM = 64

const GRAPHEMES = new Intl.Segmenter(undefined, { granularity: "grapheme" })

/** Measure per-character kerning from a plain-text copy so animated cells keep the same positions. */
function kerning(element: HTMLElement, text: string): number[] {
  const copy = document.createElement("span")
  copy.style.cssText = "position:absolute;visibility:hidden;white-space:pre"
  copy.textContent = text
  element.after(copy)
  const node = copy.firstChild!
  const range = document.createRange()
  const starts: number[] = []
  let at = 0
  for (const { segment } of GRAPHEMES.segment(text)) {
    range.setStart(node, at)
    range.setEnd(node, (at += segment.length))
    starts.push(range.getBoundingClientRect().left)
  }
  starts.push(copy.getBoundingClientRect().right)
  copy.remove()
  const sizers = element.querySelectorAll(".char-sizer")
  return starts
    .slice(1)
    .map(
      (next, index) =>
        next - starts[index] - sizers[index].getBoundingClientRect().width
    )
}

/** Gives each cell in `element` its character's kerning as room after it, so each character stands as in plain text. */
function kern(element: HTMLElement, kerning: number[]) {
  element
    .querySelectorAll<HTMLElement>(".char-slot")
    .forEach(
      (slot, index) => (slot.style.marginRight = `${kerning[index] ?? 0}px`)
    )
}
