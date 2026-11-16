const SEND_MS = 220

type Point = { x: number; y: number }
type Box = Point & { width: number }

export type SentMessage = {
  thread: string
  run: string
  message: string | null // the message's id, null for the run's opening goal
  origin: Point // where the draft's text started on screen
  tiles: Box[] // where each of its attachments' tiles was in the composer, in the order they went
}

/** Where the text of a visible, single-line draft starts, measured before the draft clears. */
export function messageOrigin(input: HTMLTextAreaElement): Point | null {
  const rect = input.getBoundingClientRect()
  const style = getComputedStyle(input)
  const top = parseFloat(style.paddingTop)
  const oneLine =
    top + parseFloat(style.lineHeight) + parseFloat(style.paddingBottom) + 1
  if (
    !rect.width ||
    input.value !== input.value.trim() ||
    input.scrollTop ||
    input.scrollLeft ||
    input.scrollHeight > oneLine
  )
    return null
  return {
    x:
      rect.left +
      parseFloat(style.borderLeftWidth) +
      parseFloat(style.paddingLeft),
    y: rect.top + parseFloat(style.borderTopWidth) + top,
  }
}

/** Where each attachment tile in the draft's composer is on screen, measured before the draft clears. */
export function tileOrigins(input: HTMLTextAreaElement): Box[] {
  return [...(input.form?.querySelectorAll("[data-tile]") ?? [])].map(
    (tile) => {
      const { left, top, width } = tile.getBoundingClientRect()
      return { x: left, y: top, width }
    }
  )
}

/** Move the sent bubble on screen from where the draft's text was to where it lands, as the view scrolls to
 * `scrollTo` (or stays), its fill fading in and the composer's placeholder after the text has left it; and what went
 * with it from each tile it had in the composer, growing to its size. Null, and nothing done, when the text wraps or
 * either end is out of sight. Returns what stops it. */
export function moveSentMessage(
  bubble: HTMLElement,
  origin: Point,
  tiles: Box[],
  scroller: HTMLElement,
  dock: HTMLElement | null,
  scrollTo: (() => number) | null
) {
  const style = getComputedStyle(bubble)
  const px = (value: string) => parseFloat(value)
  const padLeft = px(style.borderLeftWidth) + px(style.paddingLeft)
  const padTop = px(style.borderTopWidth) + px(style.paddingTop)
  const box = bubble.getBoundingClientRect()
  // Each moves from its tile's top left, scaled from there; its corners keep the tile's radius on screen.
  const attached = [
    ...bubble.parentElement!.querySelectorAll<HTMLElement>("[data-sent-index]"),
  ].flatMap((element) => {
    const from = tiles[Number(element.dataset.sentIndex)]
    if (!from) return []
    const { width } = element.getBoundingClientRect()
    const radius = px(getComputedStyle(element).borderTopLeftRadius)
    return [{ element, from, scale: from.width / width, radius, x: 0, y: 0 }]
  })
  const top = Math.min(
    box.top,
    ...attached.map((each) => each.element.getBoundingClientRect().top)
  )
  const view = scroller.getBoundingClientRect()
  const startScroll = scroller.scrollTop
  const scrollEnd = () =>
    Math.max(
      0,
      Math.min(
        scrollTo?.() ?? startScroll,
        scroller.scrollHeight - scroller.clientHeight
      )
    )
  const rise = scrollEnd() - startScroll
  const textHeight =
    box.height - padTop - px(style.paddingBottom) - px(style.borderBottomWidth)
  const textWidth =
    box.width - padLeft - px(style.paddingRight) - px(style.borderRightWidth)
  const landing = dock?.getBoundingClientRect().top ?? view.bottom
  if (
    textHeight > px(style.lineHeight) + 1 ||
    origin.x < view.left ||
    origin.x + textWidth > view.right ||
    origin.y < view.top ||
    origin.y + textHeight > view.bottom ||
    top - rise < view.top ||
    box.bottom - rise > landing ||
    box.left < view.left ||
    box.right > view.right
  )
    return null

  const input = dock?.querySelector("textarea")
  const fill = bubble.animate([{ backgroundColor: "transparent", offset: 0 }], {
    duration: SEND_MS,
    easing: "ease-in-out",
  })
  // The outgoing text still covers the first line for the first few frames.
  const hint = input?.animate(
    [
      { "--send-placeholder-opacity": 0 },
      { "--send-placeholder-opacity": 0, offset: 0.18 },
      { "--send-placeholder-opacity": 1, offset: 0.58 },
    ],
    SEND_MS
  )
  for (const each of [bubble, ...attached.map((one) => one.element)])
    each.setAttribute("data-sending", "")
  for (const each of attached) each.element.style.transformOrigin = "0 0"
  const started = performance.now()
  let x = 0
  let y = 0
  let scrolled = startScroll
  let frame = 0

  function paint(now: number) {
    const t = Math.min(1, Math.max(0, (now - started) / SEND_MS))
    const p = 1 - (1 - t) ** 3
    const at = bubble.getBoundingClientRect()
    const end = scrollEnd()
    // Where the text comes to rest on screen once the view is at `end`, read again each frame as a reply growing
    // above it moves it.
    const restX = at.left - x + padLeft
    const restY = at.top - y + padTop + scroller.scrollTop - end
    const rests = attached.map((each) => {
      const place = each.element.getBoundingClientRect()
      return {
        x: place.left - each.x,
        y: place.top - each.y + scroller.scrollTop - end,
      }
    })
    if (scrollTo) scroller.scrollTop = startScroll + (end - startScroll) * p
    scrolled = scroller.scrollTop
    // On screen it eases there from the draft, whatever the scroll has done to its place meanwhile.
    x = (origin.x - restX) * (1 - p)
    y = (origin.y - restY) * (1 - p) + scrolled - end
    bubble.style.translate = `${x}px ${y}px`
    attached.forEach((each, index) => {
      const scale = each.scale + (1 - each.scale) * p
      each.x = (each.from.x - rests[index].x) * (1 - p)
      each.y = (each.from.y - rests[index].y) * (1 - p) + scrolled - end
      each.element.style.translate = `${each.x}px ${each.y}px`
      each.element.style.scale = String(scale)
      if (each.radius)
        each.element.style.borderRadius = `${each.radius / scale}px`
    })
  }

  function stop() {
    cancelAnimationFrame(frame)
    fill.cancel()
    hint?.cancel()
    bubble.style.removeProperty("translate")
    bubble.removeAttribute("data-sending")
    for (const { element } of attached) {
      for (const property of [
        "translate",
        "scale",
        "transform-origin",
        "border-radius",
      ])
        element.style.removeProperty(property)
      element.removeAttribute("data-sending")
    }
  }

  function advance(now: number) {
    // Gone, or the user scrolled: it is where it lands at once.
    if (!bubble.isConnected || Math.abs(scroller.scrollTop - scrolled) > 1)
      return stop()
    paint(now)
    if (now - started < SEND_MS) frame = requestAnimationFrame(advance)
    else stop()
  }

  paint(started)
  frame = requestAnimationFrame(advance)
  return stop
}

/** A sent bubble that cannot move from the draft fades in where it lands. */
export function fadeSentMessage(message: HTMLElement) {
  const fade = message.animate([{ opacity: 0, offset: 0 }], {
    duration: 150,
    easing: "ease-out",
  })
  return () => fade.cancel()
}
