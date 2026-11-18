// Marks drawn over an image the user attached: pen strokes and shapes in the image's own pixels, so the copy made
// from them (flattened) has them where they were drawn at any size it is shown; and comments, sent as words.

import { getStroke } from "perfect-freehand"

export type Point = [number, number]

// Fixed sRGB colours, not the theme's: they go into the file.
export const COLORS = {
  red: "#ff3b30",
  yellow: "#ffcc00",
  green: "#34c759",
  blue: "#007aff",
  black: "#000000",
} as const
export type Color = keyof typeof COLORS

export type Shape = "rect" | "ellipse" | "arrow"
export type Tool = "pen" | Shape | "comment"

export type Mark =
  | {
      id: string
      kind: "pen"
      color: Color
      points: [number, number, number][]
    }
  | { id: string; kind: Shape; color: Color; from: Point; to: Point }
  // A note on a spot of the picture: shown as a numbered pin while marking up, and sent as words with the message.
  // Never drawn into the picture, so its spot is in shares of the picture's width and height (0 to 1), the same on
  // the picture and on a smaller copy of it, as the message gives it.
  | { id: string; kind: "comment"; at: Point; text: string }

/** What is drawn, and what was before each change (to undo it) and after each undone (to redo it). */
export type Markup = { marks: Mark[]; past: Mark[][]; future: Mark[][] }

export const EMPTY: Markup = { marks: [], past: [], future: [] }

/** One finished gesture: the marks as it leaves them. */
export function applied(markup: Markup, marks: Mark[]): Markup {
  return { marks, past: [...markup.past, markup.marks], future: [] }
}

export function undone(markup: Markup): Markup {
  const before = markup.past.at(-1)
  if (!before) return markup
  return {
    marks: before,
    past: markup.past.slice(0, -1),
    future: [markup.marks, ...markup.future],
  }
}

export function redone(markup: Markup): Markup {
  const [after, ...rest] = markup.future
  if (!after) return markup
  return { marks: after, past: [...markup.past, markup.marks], future: rest }
}

/** One line's width for an image: from its long side, so it keeps its share of it. */
export function sizesFor(width: number, height: number) {
  return { line: Math.max(2, Math.round(Math.max(width, height) * 0.004)) }
}
export type Sizes = ReturnType<typeof sizesFor>

const n = (value: number) => Math.round(value * 100) / 100

/** A pen stroke's outline, filled: smoothed and thinned as it speeds up. */
export function strokePath(points: [number, number, number][], line: number) {
  const outline = getStroke(points, {
    size: line * 1.6,
    thinning: 0.4,
    smoothing: 0.5,
    streamline: 0.4,
    simulatePressure: true,
  })
  if (outline.length < 2) return ""
  // Through the midpoints between the outline's points, each a curve's end, the points themselves its control.
  const [first, ...rest] = outline
  const parts = [`M${n(first[0])} ${n(first[1])}Q`]
  for (const [index, [x, y]] of outline.entries()) {
    const [nx, ny] = rest[index] ?? first
    parts.push(`${n(x)} ${n(y)} ${n((x + nx) / 2)} ${n((y + ny) / 2)}`)
  }
  return `${parts.join(" ")}Z`
}

/** Where a shape dragged out with Shift held ends: a square or a circle, or an arrow at a multiple of 45°. */
export function constrained(
  kind: Shape,
  [x1, y1]: Point,
  [x2, y2]: Point
): Point {
  const dx = x2 - x1
  const dy = y2 - y1
  if (kind !== "arrow") {
    const side = Math.max(Math.abs(dx), Math.abs(dy))
    return [x1 + Math.sign(dx || 1) * side, y1 + Math.sign(dy || 1) * side]
  }
  const step = Math.PI / 4
  const angle = Math.round(Math.atan2(dy, dx) / step) * step
  const length = Math.hypot(dx, dy)
  return [x1 + Math.cos(angle) * length, y1 + Math.sin(angle) * length]
}

/** A shape's line, stroked: the arrow's head opens 30° either side, its length from the line's width. */
export function shapePath(
  kind: Shape,
  [x1, y1]: Point,
  [x2, y2]: Point,
  line: number
) {
  if (kind === "rect") {
    // Its corners rounded as the tool's icon is, three lines' width, never past half its shorter side.
    const left = Math.min(x1, x2)
    const top = Math.min(y1, y2)
    const right = Math.max(x1, x2)
    const bottom = Math.max(y1, y2)
    const r = Math.min(line * 3, (right - left) / 2, (bottom - top) / 2)
    const arc = (x: number, y: number) =>
      `A${n(r)} ${n(r)} 0 0 1 ${n(x)} ${n(y)}`
    return `M${n(left + r)} ${n(top)}H${n(right - r)}${arc(right, top + r)}V${n(bottom - r)}${arc(right - r, bottom)}H${n(left + r)}${arc(left, bottom - r)}V${n(top + r)}${arc(left + r, top)}Z`
  }
  if (kind === "ellipse") {
    const rx = Math.abs(x2 - x1) / 2
    const ry = Math.abs(y2 - y1) / 2
    const cx = (x1 + x2) / 2
    const cy = (y1 + y2) / 2
    return `M${n(cx - rx)} ${n(cy)}A${n(rx)} ${n(ry)} 0 1 0 ${n(cx + rx)} ${n(cy)}A${n(rx)} ${n(ry)} 0 1 0 ${n(cx - rx)} ${n(cy)}Z`
  }
  const angle = Math.atan2(y2 - y1, x2 - x1)
  const head = Math.min(line * 5, Math.hypot(x2 - x1, y2 - y1) / 2)
  const wing = (turn: number) =>
    `${n(x2 - head * Math.cos(angle + turn))} ${n(y2 - head * Math.sin(angle + turn))}`
  return `M${n(x1)} ${n(y1)}L${n(x2)} ${n(y2)}M${wing(Math.PI / 6)}L${n(x2)} ${n(y2)}L${wing(-Math.PI / 6)}`
}

export type Comment = Extract<Mark, { kind: "comment" }>
export type Drawn = Exclude<Mark, Comment>

/** What goes into the picture: everything but its comments. */
export const drawnOf = (marks: Mark[]) =>
  marks.filter((mark): mark is Drawn => mark.kind !== "comment")

/** The comments, in the order they were put down, as they are numbered. */
export const commentsOf = (marks: Mark[]) =>
  marks.filter((mark): mark is Comment => mark.kind === "comment")

const percent = (share: number) => `${(share * 100).toFixed(1)}%`

const heading = (name: string) => `${name}：`
// A picture's heading as the user may have retyped it: either colon, spaces around.
const headed = (line: string, name: string) => {
  const words = line.trim()
  return /[:：]$/.test(words) && words.slice(0, -1).trimEnd() === name
}
// One comment as the message words it, ChatGPT's way: its number, where it is in shares of the picture, its words;
// read back with the spaces a hand may have changed. Words on more lines than one go on under it, set in, so they
// still read as its own.
const WORDED =
  /^\d+\.\s*\(x:\s*(-?\d+(?:\.\d+)?)%,\s*y:\s*(-?\d+(?:\.\d+)?)%\)\s?(.*)$/
const INDENT = "   "
const within = (share: number) => Math.min(1, Math.max(0, share))

/** The comments on picture `name` in `draft`'s lines, as written: under its last heading, blank lines between them
 * passed over; `end` is after the last of them. */
function placeOf(lines: string[], name: string) {
  const top = lines.findLastIndex((line) => headed(line, name))
  const found: { x: number; y: number; text: string }[] = []
  let end = top + 1
  for (let at = top + 1; top >= 0 && at < lines.length; at++) {
    const line = lines[at]
    const worded = WORDED.exec(line)
    if (worded)
      found.push({
        x: Number(worded[1]),
        y: Number(worded[2]),
        text: worded[3],
      })
    else if (found.length && line.startsWith(INDENT))
      found.at(-1)!.text += `\n${line.slice(INDENT.length)}`
    else if (line.trim()) break
    else continue
    end = at + 1
  }
  return { top, end, found }
}

/** The comments on picture `name` already in `draft`, read back as pins: the draft is where they are kept, so what
 * was changed there is what shows. */
export function commentsIn(draft: string, name: string): Comment[] {
  return placeOf(draft.split("\n"), name).found.map(({ x, y, text }) => ({
    id: crypto.randomUUID(),
    kind: "comment",
    at: [within(x / 100), within(y / 100)], // on the picture, wherever a hand put it
    text,
  }))
}

/** `draft` with the comments on the picture the model receives as `name`, numbered under its name: in place of those
 * it had (commentsIn), or at the end after a blank line. With none left, its heading goes too. */
export function withComments(draft: string, marks: Mark[], name: string) {
  const comments = commentsOf(marks).map(
    ({ at: [x, y], text }, index) =>
      `${index + 1}. (x: ${percent(x)}, y: ${percent(y)}) ${text.replaceAll("\n", `\n${INDENT}`)}`
  )
  const lines = draft.split("\n")
  const { top, end, found } = placeOf(lines, name)
  if (!comments.length && !found.length) return draft
  if (top < 0) {
    const block = [heading(name), ...comments].join("\n")
    return draft.trim() ? `${draft.trimEnd()}\n\n${block}` : block
  }
  if (comments.length)
    return [...lines.slice(0, top + 1), ...comments, ...lines.slice(end)].join(
      "\n"
    )
  // And the blank line that set it apart.
  const before = lines.slice(0, top)
  const after = lines.slice(end)
  if (before.at(-1) === "") before.pop()
  else if (after[0] === "") after.shift()
  return [...before, ...after].join("\n")
}

/** `draft` with a picture's comments labelled now by the name its copy goes as. */
export const relabelled = (draft: string, from: string, to: string) =>
  draft
    .split("\n")
    .map((line) => (headed(line, from) ? heading(to) : line))
    .join("\n")

/** How far in a view is zoomed, and where it has been moved: its content scaled from its top left, then shifted. */
export type View = { scale: number; x: number; y: number }
export const UNZOOMED: View = { scale: 1, x: 0, y: 0 }
export const MAX_SCALE = 8

/** Kept so the content still covers the box it is shown in: never smaller, never moved off an edge. */
export function held(view: View, width: number, height: number): View {
  const scale = Math.min(MAX_SCALE, Math.max(1, view.scale))
  const clamp = (value: number, size: number) =>
    Math.min(0, Math.max(size - size * scale, value))
  return { scale, x: clamp(view.x, width), y: clamp(view.y, height) }
}

/** Zoomed by `factor` about `at` (in the box), which stays where it is. */
export function zoomedAt(
  view: View,
  factor: number,
  [px, py]: Point,
  width: number,
  height: number
): View {
  const scale = Math.min(MAX_SCALE, Math.max(1, view.scale * factor))
  const ratio = scale / view.scale
  return held(
    { scale, x: px - (px - view.x) * ratio, y: py - (py - view.y) * ratio },
    width,
    height
  )
}

/** The marked-up copy's name: the image's, marked once, as a PNG. */
export function markupName(name: string) {
  const dot = name.lastIndexOf(".")
  const stem = (dot > 0 ? name.slice(0, dot) : name).replace(/-markup$/, "")
  return `${stem}-markup.png`
}

/** The image with its strokes and shapes drawn into it, at its own size, as a PNG file: the same paths the page
 * draws. */
export async function flattened(
  image: Blob,
  marks: Drawn[],
  name: string
): Promise<File> {
  const bitmap = await createImageBitmap(image)
  const canvas = new OffscreenCanvas(bitmap.width, bitmap.height)
  const context = canvas.getContext("2d")!
  context.drawImage(bitmap, 0, 0)
  const sizes = sizesFor(bitmap.width, bitmap.height)
  bitmap.close()
  context.lineCap = "round"
  context.lineJoin = "round"
  for (const mark of marks) {
    const color = COLORS[mark.color]
    context.fillStyle = color
    context.strokeStyle = color
    if (mark.kind === "pen") {
      context.fill(new Path2D(strokePath(mark.points, sizes.line)))
    } else {
      context.lineWidth = sizes.line
      context.stroke(
        new Path2D(shapePath(mark.kind, mark.from, mark.to, sizes.line))
      )
    }
  }
  const blob = await canvas.convertToBlob({ type: "image/png" })
  return new File([blob], markupName(name), { type: "image/png" })
}
