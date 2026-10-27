/**
 * The glass of the scroll-to-latest button (index.css's glass, run-view.tsx) as a lens, measured off ChatGPT's iOS
 * button: a thick dome of glass. The middle is flat and shows the page right under it; towards the rim the dome bends
 * light more and more steeply, so the rim shows the page from further in, stretched out to the edge, and over the
 * last few pixels from further in again, as a real dome's rim does: under a black bar, what is white below it floats
 * in the glass as an oval with the bar's grey round it. The edge catches the light as cut glass does: a fine dark line
 * on the very edge, where the glass is seen at a graze, deepest at the sides, and just inside it a bright ring at the
 * top and bottom, with the glass lifting towards them. A fragment shader run once per pixel on a canvas, into three
 * images: a displacement map the SVG filter in run-view.tsx bends what is under the button with, and the light laid
 * over it, drawn once for the light mode and once for the dark, which has no dark line and half the light. Only
 * Chromium bends a backdrop with an SVG filter: Safari and Firefox drop the whole backdrop-filter, and no CSS test
 * tells them apart, so the glass is lensed where the browser has user agent client hints, which only Chromium does,
 * and is index.css's plain glass elsewhere.
 */

// The button's size (run-view.tsx's size-8), and how finely the images are drawn: four pixels to a CSS pixel.
export const SIZE = 32
const RES = 4
// The rim: how far in from the edge the dome bends the page, and how far in the edge itself shows it from, the bend
// growing towards the edge as this power. Less than the radius, so the edge never shows the page from beyond the
// middle.
const RIM = 9.3
const DEEPEST = 13.1
const POWER = 2.6
// The dark line on the very edge: how dark at the sides, how much of that at the top and bottom, and how wide.
const LINE = 0.45
const LINE_TOP = 0.3
const LINE_WIDTH = 0.22
// The bright ring: how strong (past 1 it holds full white over more of its width), how far in and how wide, and how
// much of it the sides keep.
const RING = 1.6
const RING_AT = 0.7
const RING_WIDTH = 0.25
const RING_SIDE = 0.08
// The glass lifting towards the top and bottom: how much, and over how many CSS px in from the ring.
const SHEEN = 0.55
const SHEEN_WIDTH = 3
// The dark mode's share of the ring and of the lift.
const DARK_RING = 0.5
const DARK_SHEEN = 0.25

export const LENSED =
  typeof navigator !== "undefined" && "userAgentData" in navigator

export type Lens = {
  /** The displacement map, a data URL the button's size: red and green hold the shift along x and y, 0.5 for none. */
  map: string
  /** The light, a data URL: the dark line and the bright ring over the rim. */
  glint: string
  /** The light for the dark mode, the ring and lift only, dimmer. */
  glintDark: string
  /** The displacement map's largest shift, both ways (feDisplacementMap's scale), in CSS px. */
  scale: number
}

/** How far in from under it the glass `edge` CSS px in from the rim shows the page, in CSS px: none in the flat
 * middle, the most at the edge. */
export function bend(edge: number): number {
  if (edge >= RIM) return 0
  return DEEPEST * (1 - Math.max(edge, 0) / RIM) ** POWER
}

type Fragment = (nx: number, ny: number, edge: number) => number[]

/** `fragment` run for each pixel of the button's image, given the outward direction from the middle and how far in
 * from the rim the pixel is (negative outside the disc), for its red, green, blue and alpha in 0..1; the image as a
 * data URL, or null where there is no canvas to draw on. */
function shade(fragment: Fragment): string | null {
  const n = SIZE * RES
  const canvas = document.createElement("canvas")
  canvas.width = canvas.height = n
  const context = canvas.getContext("2d")
  if (!context) return null
  const image = context.createImageData(n, n)
  for (let py = 0; py < n; py++) {
    for (let px = 0; px < n; px++) {
      const x = (px + 0.5) / RES - SIZE / 2
      const y = (py + 0.5) / RES - SIZE / 2
      const r = Math.hypot(x, y) || 1
      const color = fragment(x / r, y / r, SIZE / 2 - Math.hypot(x, y))
      const i = (py * n + px) * 4
      for (let k = 0; k < 4; k++)
        image.data[i + k] = Math.round(Math.min(Math.max(color[k], 0), 1) * 255)
    }
  }
  context.putImageData(image, 0, 0)
  return canvas.toDataURL()
}

const bump = (at: number, width: number, edge: number) =>
  Math.exp(-(((edge - at) / width) ** 2))

/** The light over the rim: white from the ring and the lift laid over the dark line, as one grey and its alpha. */
const light = (dark: boolean) =>
  shade((nx, ny, edge) => {
    if (edge <= 0) return [1, 1, 1, 0]
    const line = dark
      ? 0
      : LINE *
        (LINE_TOP + (1 - LINE_TOP) * nx * nx) *
        bump(0.12, LINE_WIDTH, edge)
    const ring =
      Math.min(
        1,
        RING *
          (RING_SIDE + (1 - RING_SIDE) * ny * ny) *
          bump(RING_AT, RING_WIDTH, edge)
      ) * (dark ? DARK_RING : 1)
    const sheen =
      SHEEN *
      ny *
      ny *
      Math.exp(-Math.max(edge - RING_AT, 0) / SHEEN_WIDTH) *
      (dark ? DARK_SHEEN : 1)
    const white = 1 - (1 - ring) * (1 - sheen)
    const alpha = 1 - (1 - line) * (1 - white)
    // Only the pixel the edge cuts fades, by how much of it is inside; the button's rounding smooths the rest.
    const inside = Math.min(Math.max(edge * RES + 0.5, 0), 1)
    const grey = alpha ? white / alpha : 1
    return [grey, grey, grey, inside * alpha]
  })

/** The lens drawn; null where the browser has no canvas to draw it on. */
export function drawLens(): Lens | null {
  // Half the map's range each way is the deepest bend, so the scale is twice it; inward is against the direction from
  // the middle.
  const map = shade((nx, ny, edge) => {
    if (edge <= 0) return [0.5, 0.5, 0.5, 1]
    const d = bend(edge) / DEEPEST
    return [0.5 - 0.5 * d * nx, 0.5 - 0.5 * d * ny, 0.5, 1]
  })
  const glint = light(false)
  const glintDark = light(true)
  return map && glint && glintDark
    ? { map, glint, glintDark, scale: 2 * DEEPEST }
    : null
}
