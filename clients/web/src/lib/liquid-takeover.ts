import {
  buildFullCanvas,
  drawingRatio,
  releaseFullCanvas,
  type FullCanvas,
} from "@/lib/webgl"

/**
 * The takeover's blue as one liquid surface, drawn on a canvas by a fragment shader: the tab (the pill's button
 * widening to the whole tab, up to the screen) and the frame (a stroke drawn on from the tab's ends both ways round
 * the screen, meeting at the top), joined by a smooth union so they always meet in a curve. live-view.tsx uses the CSS
 * takeover in index.css instead where this can't be drawn.
 */

// The timing (index.css: --ease-out, --ease-in-out). Taking over, as the CSS takeover's: the tab widens out of the
// button on the strong ease-out, answering the click at once and settling into place; the frame leaves its ends as it
// is about done and runs round both ways on the strong ease-in-out, so its two heads leave the tab gently and slow
// into each other at the top instead of stopping dead. Returning, quicker, the blue drains back as one: the frame
// runs back into the tab's ends, then the tab narrows into the button, on one strong ease-in-out, each for its share
// of the way by how far it moves. So it hands over at one speed, at the moment the frame is all in, with nothing of it
// left behind, and slows into the button. A switch midway turns back from where it got to, over the time left.
const TAB_MS = 220
const FRAME_DELAY_MS = 170
const FRAME_MS = 520
const RETURN_MS = 520
// Where tab and frame meet, the smooth union's radius; and how much the frame's head swells while it flows (CSS px).
const FUSE = 18
const SWELL = 3
// After a switch, keep drawing at least this long: the pill's label and button resize meanwhile (live-view.tsx).
const SETTLE_MS = 450
// The time animation frames are given: the document timeline's, which DevTools slows along with the page's other
// animations. A switch starts its tweens on that clock too, so the frames that draw them always reach their end.
const clock = () => Number(document.timeline.currentTime ?? performance.now())
// The frame's centerline, which its drawing runs along: its corner radius (10 outer, less half the 11px band) and half
// its width. The frame itself is the box round that centerline's band with rounder outer corners than the band's own,
// less the screen: so it is no wider than the band along the sides and slims a little round each corner, as a
// bezel's corner does, while its inside stays square against the screen. The screen's corner radius (square); the
// pill's and the button's (index.css, live-view.tsx).
const LINE_RADIUS = 4.5
const LINE_HALF = 5.5
const FRAME_RADIUS = 16
const SCREEN_RADIUS = 0
const PILL_RADIUS = 26
const BUTTON_RADIUS = 20

const FRAGMENT = `
precision highp float;
uniform vec2 uSize;     // canvas, CSS px
uniform float uDpr;
uniform vec4 uScreen;   // boxes as x0 y0 x1 y1, y down, in the canvas
uniform vec4 uTab;      // the whole tab: from the screen's bottom edge to the pill's bottom
uniform vec4 uButton;   // where the tab grows from and narrows back into
uniform vec4 uPath;     // the frame's centerline box: center x, center y, half width, half height
uniform float uGrown;   // the tab, 0 (the button) to 1 (the whole tab); below 0, nothing
uniform float uRun;     // how far each half of the frame has run past the tab's end, px
uniform float uTabEnd;  // arc length from the bottom middle to the tab's end, px
uniform float uSwell;   // extra radius at the frame's head, px
uniform vec3 uColor;

const float R = ${LINE_RADIUS.toFixed(1)};
const float W = ${LINE_HALF.toFixed(1)};
const float FRAME_R = ${FRAME_RADIUS.toFixed(1)};
const float FUSE = ${FUSE.toFixed(1)};
const float HALF_PI = 1.5707963;

// A box with its own radius per corner: top left, top right, bottom right, bottom left.
float box(vec2 p, vec4 b, vec4 r) {
  vec2 c = 0.5 * (b.xy + b.zw), h = 0.5 * (b.zw - b.xy), q = p - c;
  float rad = q.x > 0.0 ? (q.y > 0.0 ? r.z : r.y) : (q.y > 0.0 ? r.w : r.x);
  vec2 d = abs(q) - h + rad;
  return min(max(d.x, d.y), 0.0) + length(max(d, 0.0)) - rad;
}

float smin(float a, float b, float k) {
  float h = max(k - abs(a - b), 0.0) / k;
  return min(a, b) - h * h * k * 0.25;
}

// The right half of the centerline, folded about the middle: from the bottom middle (0) round to the top middle.
vec2 pathAt(float s, float hx, float hy) {
  float a = hx - R, q = HALF_PI * R, b = 2.0 * (hy - R);
  if (s <= a) return vec2(s, hy);
  s -= a;
  if (s <= q) { float t = s / R; return vec2(a, hy - R) + R * vec2(sin(t), cos(t)); }
  s -= q;
  if (s <= b) return vec2(hx, hy - R - s);
  s -= b;
  if (s <= q) { float t = s / R; return vec2(a, -(hy - R)) + R * vec2(cos(t), -sin(t)); }
  s -= q;
  return vec2(a - s, -hy);
}

// Distance to the folded centerline, and how far along it the nearest point lies.
vec2 nearest(vec2 f, float hx, float hy) {
  float a = hx - R, q = HALF_PI * R, b = 2.0 * (hy - R);
  vec2 best = vec2(1e9, 0.0);
  vec2 cp = vec2(clamp(f.x, 0.0, a), hy);
  float d = length(f - cp); if (d < best.x) best = vec2(d, cp.x);
  vec2 c = vec2(a, hy - R), v = f - c;
  float t = clamp(atan(v.x, v.y), 0.0, HALF_PI);
  d = length(f - (c + R * vec2(sin(t), cos(t)))); if (d < best.x) best = vec2(d, a + R * t);
  cp = vec2(hx, clamp(f.y, -(hy - R), hy - R));
  d = length(f - cp); if (d < best.x) best = vec2(d, a + q + (hy - R - cp.y));
  c = vec2(a, -(hy - R)); v = f - c;
  t = clamp(atan(-v.y, v.x), 0.0, HALF_PI);
  d = length(f - (c + R * vec2(cos(t), -sin(t)))); if (d < best.x) best = vec2(d, a + q + b + R * t);
  cp = vec2(clamp(f.x, 0.0, a), -hy);
  d = length(f - cp); if (d < best.x) best = vec2(d, a + 2.0 * q + b + (a - cp.x));
  return best;
}

void main() {
  vec2 p = vec2(gl_FragCoord.x, uSize.y * uDpr - gl_FragCoord.y) / uDpr;
  // Most of the canvas lies over the screen, where nothing is drawn but its outermost pixel (the rim below): more than
  // 2px in, the answer is known without working out tab and frame.
  if (box(p, uScreen + vec4(2.0, 2.0, -2.0, -2.0), vec4(${Math.max(SCREEN_RADIUS - 2, 0).toFixed(1)})) < 0.0) {
    gl_FragColor = vec4(0.0);
    return;
  }
  float tab = 1e5;
  if (uGrown >= 0.0) {
    tab = box(p, mix(uButton, uTab, uGrown), mix(vec4(${BUTTON_RADIUS.toFixed(1)}), vec4(0.0, 0.0, ${PILL_RADIUS.toFixed(1)}, ${PILL_RADIUS.toFixed(1)}), uGrown));
  }
  float line = 1e5;
  if (uRun > 0.0) {
    float hx = uPath.z, hy = uPath.w;
    float total = 2.0 * (hx - R) + 2.0 * (hy - R) + 2.0 * HALF_PI * R;
    vec2 f = vec2(abs(p.x - uPath.x), p.y - uPath.y);
    vec2 n = nearest(f, hx, hy);
    // The frame's whole shape, as far as it has been drawn: its outer edge, round at the corners (the screen is cut
    // out below).
    float body = box(p, vec4(uPath.xy - uPath.zw - W, uPath.xy + uPath.zw + W), vec4(FRAME_R));
    float head = min(uTabEnd + uRun, total);
    float tail = uTabEnd - min(uRun, 10.0);
    float swell = head < total - 0.5 ? uSwell : 0.0;
    // Its round head and tail, within that shape, so the head doesn't stick out past a corner as it goes round.
    if (n.y > head) line = max(length(f - pathAt(head, hx, hy)) - (W + swell), body - swell);
    else if (n.y < tail) line = max(length(f - pathAt(tail, hx, hy)) - W, body);
    else { float behind = (head - n.y) / 22.0; line = body - swell * exp(-behind * behind); }
  }
  // Never over the screen: there the blue ends at the screen's own edge, crisp, however the smooth union swells
  // where tab and frame meet (it reaches some 4px over).
  float shape = max(smin(tab, line, FUSE), -box(p, uScreen, vec4(${SCREEN_RADIUS.toFixed(1)})));
  // But for the screen's outermost pixel, wherever tab or frame meets it: covered by their plain union, 1px wider,
  // so the blue and the screen don't meet edge to edge, where their antialiasing would leave a light hairline.
  float rim = max(
    min(tab, line) - 1.0,
    max(-box(p, uScreen + vec4(1.0, 1.0, -1.0, -1.0), vec4(${Math.max(SCREEN_RADIUS - 1, 0).toFixed(1)})),
        box(p, uScreen, vec4(${SCREEN_RADIUS.toFixed(1)})) - 1.0));
  shape = min(shape, rim);
  float alpha = clamp(0.5 - shape * uDpr, 0.0, 1.0);
  gl_FragColor = vec4(uColor * alpha, alpha);
}`

const UNIFORMS = [
  "uSize",
  "uDpr",
  "uScreen",
  "uTab",
  "uButton",
  "uPath",
  "uGrown",
  "uRun",
  "uTabEnd",
  "uSwell",
  "uColor",
] as const

type Program = FullCanvas & {
  gl: WebGLRenderingContext
  uniforms: Record<(typeof UNIFORMS)[number], WebGLUniformLocation | null>
}

function build(gl: WebGLRenderingContext): Program | null {
  const drawn = buildFullCanvas(gl, FRAGMENT)
  if (!drawn) return null
  const uniforms = Object.fromEntries(
    UNIFORMS.map((name) => [name, gl.getUniformLocation(drawn.program, name)])
  ) as Program["uniforms"]
  return { gl, ...drawn, uniforms }
}

const context = (canvas: HTMLCanvasElement) =>
  canvas.getContext("webgl", {
    alpha: true,
    antialias: false,
    premultipliedAlpha: true,
  })

let drawable: boolean | undefined
/** Whether this browser can draw the liquid takeover: WebGL, and the shaders compile. Checked once. */
export function canDrawLiquid() {
  if (drawable !== undefined) return drawable
  const gl = context(document.createElement("canvas"))
  drawable = !!gl && !!build(gl)
  gl?.getExtension("WEBGL_lose_context")?.loseContext()
  return drawable
}

/** A computed CSS color (oklch, oklab or rgb, as browsers give it) as sRGB from 0 to 1. */
function toRgb(css: string): [number, number, number] {
  const numbers = (css.match(/-?[\d.]+%?/g) ?? []).map((n) =>
    n.endsWith("%") ? parseFloat(n) / 100 : parseFloat(n)
  )
  if (!css.startsWith("ok")) {
    const [r = 0, g = 0, b = 0] = numbers
    return css.startsWith("color(") ? [r, g, b] : [r / 255, g / 255, b / 255]
  }
  const l = numbers[0] ?? 0
  let [, a = 0, b = 0] = numbers
  if (css.startsWith("oklch")) {
    const hue = (b * Math.PI) / 180
    ;[a, b] = [a * Math.cos(hue), a * Math.sin(hue)]
  }
  const lms = [
    (l + 0.3963377774 * a + 0.2158037573 * b) ** 3,
    (l - 0.1055613458 * a - 0.0638541728 * b) ** 3,
    (l - 0.0894841775 * a - 1.291485548 * b) ** 3,
  ]
  const linear = [
    4.0767416621 * lms[0] - 3.3077115913 * lms[1] + 0.2309699292 * lms[2],
    -1.2684380046 * lms[0] + 2.6097574011 * lms[1] - 0.3413193965 * lms[2],
    -0.0041960863 * lms[0] - 0.7034186147 * lms[1] + 1.707614701 * lms[2],
  ]
  const [r, g, bl] = linear.map((c) => {
    const v = Math.min(Math.max(c, 0), 1)
    return v <= 0.0031308 ? 12.92 * v : 1.055 * v ** (1 / 2.4) - 0.055
  })
  return [r, g, bl]
}

/** A CSS cubic-bezier() as a function from time to progress, both 0 to 1: x solved by Newton's method, else halving. */
function cubicBezier(css: string): (x: number) => number {
  const [x1, y1, x2, y2] = (css.match(/-?[\d.]+/g) ?? []).map(Number)
  if ([x1, y1, x2, y2].some((n) => !Number.isFinite(n))) return (x) => x
  const curve = (a: number, b: number, t: number) =>
    3 * a * (1 - t) ** 2 * t + 3 * b * (1 - t) * t ** 2 + t ** 3
  const slope = (a: number, b: number, t: number) =>
    3 * a * (1 - t) ** 2 + 6 * (b - a) * (1 - t) * t + 3 * (1 - b) * t ** 2
  return (x) => {
    if (x <= 0) return 0
    if (x >= 1) return 1
    let t = x
    for (let i = 0; i < 8; i++) {
      const d = slope(x1, x2, t)
      if (Math.abs(d) < 1e-6) break
      t -= (curve(x1, x2, t) - x) / d
    }
    if (!(t >= 0 && t <= 1) || Math.abs(curve(x1, x2, t) - x) > 1e-5) {
      let low = 0
      let high = 1
      for (let i = 0; i < 40; i++) {
        t = (low + high) / 2
        if (curve(x1, x2, t) < x) low = t
        else high = t
      }
    }
    return curve(y1, y2, t)
  }
}

/** A value moving from one number to another, from a time on, for a while, on a curve. */
type Tween = {
  from: number
  to: number
  start: number
  duration: number
  ease: (x: number) => number
}

const still = (value: number): Tween => ({
  from: value,
  to: value,
  start: 0,
  duration: 0,
  ease: (x) => x,
})

const valueAt = (tween: Tween, now: number) =>
  now <= tween.start
    ? tween.from
    : now >= tween.start + tween.duration
      ? tween.to
      : tween.from +
        (tween.to - tween.from) *
          tween.ease((now - tween.start) / tween.duration)

const finished = (tween: Tween, now: number) =>
  now >= tween.start + tween.duration

export type LiquidParts = {
  screen: Element
  pill: Element
  button: Element
}

export type LiquidTakeover = {
  /** Toward the takeover (true) or away from it. The first call only places it there. */
  setTarget(on: boolean): void
  dispose(): void
}

/** Draws the takeover on `canvas`, which lies over the screen and the pill; `parts` finds them, laid out as they are. */
export function createLiquidTakeover(
  canvas: HTMLCanvasElement,
  parts: () => LiquidParts | null
): LiquidTakeover | null {
  const found = context(canvas)
  let program = found && build(found)
  if (!found || !program) return null
  const gl = found

  let color: [number, number, number] = [0.3, 0.35, 0.55]
  const readColor = () => {
    const probe = document.createElement("span")
    probe.style.color = "var(--takeover)"
    canvas.parentElement?.append(probe)
    color = toRgb(getComputedStyle(probe).color)
    probe.remove()
  }
  readColor()

  const tokens = getComputedStyle(canvas)
  const easeOut = cubicBezier(tokens.getPropertyValue("--ease-out"))
  const easeInOut = cubicBezier(tokens.getPropertyValue("--ease-in-out"))
  // Taking over, the tab, 0 (the button) to 1 (the whole tab), and the frame, 0 (at the tab's ends) to 1 (closed at
  // the top), each on its own. Returning, both from one drain, 0 (all of it blue) to 1 (back in the button): the frame
  // over its first `share`, the tab over the rest.
  let tab = still(0)
  let run = still(0)
  let drain: { tween: Tween; share: number } | null = null
  let on = false
  let placed = false
  const stateAt = (now: number) => {
    if (!drain) return { grown: valueAt(tab, now), ran: valueAt(run, now) }
    const drained = valueAt(drain.tween, now)
    const { share } = drain
    return drained < share
      ? { grown: 1, ran: 1 - drained / share }
      : { grown: 1 - (drained - share) / (1 - share), ran: 0 }
  }
  const moving = (now: number) =>
    drain
      ? !finished(drain.tween, now)
      : !finished(tab, now) || !finished(run, now)

  /** Screen, pill and button on the canvas; the frame's centerline; how far its heads run and the tab's ends move. */
  function measure(laid: LiquidParts, box: DOMRect) {
    const rect = (element: Element) => {
      const r = element.getBoundingClientRect()
      return [
        r.left - box.left,
        r.top - box.top,
        r.right - box.left,
        r.bottom - box.top,
      ] as const
    }
    const screen = rect(laid.screen)
    const pill = rect(laid.pill)
    const button = rect(laid.button)
    // The centerline: the frame's box (the screen's plus 10px, and 1px more below) less half the band.
    const line = [
      screen[0] - 4.5,
      screen[1] - 4.5,
      screen[2] + 4.5,
      screen[3] + 5.5,
    ] as const
    const hx = (line[2] - line[0]) / 2
    const hy = (line[3] - line[1]) / 2
    const r = LINE_RADIUS
    const total = 2 * (hx - r) + 2 * (hy - r) + Math.PI * r
    const tabEnd = (pill[2] - pill[0]) / 2
    const tabTravel = Math.max(
      button[0] - pill[0],
      pill[2] - button[2],
      button[1] - screen[3],
      1
    )
    return { screen, pill, button, line, hx, hy, total, tabEnd, tabTravel }
  }
  // How fast the frame ran at the last frame drawn, in frames per second, for its head's swell.
  let lastRun = 0
  let lastTime = 0
  let blank = false

  function draw(now = clock()) {
    if (!program || gl.isContextLost()) return
    const { uniforms: u } = program
    const { grown, ran } = stateAt(now)
    const speed =
      now > lastTime ? Math.abs(ran - lastRun) / ((now - lastTime) / 1000) : 0
    lastRun = ran
    lastTime = now
    const laid = parts()
    // Nothing to draw: cleared once and left at its size, so a panel resizing under it (the live view expanding)
    // allocates no new drawing buffer each frame. It is sized again when there is something to draw.
    if (!laid || (!on && grown <= 0.0005 && ran <= 0.0005)) {
      if (!blank) {
        gl.clearColor(0, 0, 0, 0)
        gl.clear(gl.COLOR_BUFFER_BIT)
        blank = true
      }
      return
    }
    blank = false
    const dpr = drawingRatio()
    const box = canvas.getBoundingClientRect()
    const width = Math.round(box.width * dpr)
    const height = Math.round(box.height * dpr)
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width
      canvas.height = height
    }
    gl.viewport(0, 0, width, height)
    gl.clearColor(0, 0, 0, 0)
    gl.clear(gl.COLOR_BUFFER_BIT)
    const { screen, pill, button, line, hx, hy, total, tabEnd } = measure(
      laid,
      box
    )
    gl.uniform2f(u.uSize, box.width, box.height)
    gl.uniform1f(u.uDpr, dpr)
    gl.uniform4f(u.uScreen, ...screen)
    gl.uniform4f(u.uTab, pill[0], screen[3], pill[2], pill[3])
    gl.uniform4f(u.uButton, ...button)
    gl.uniform4f(
      u.uPath,
      (line[0] + line[2]) / 2,
      (line[1] + line[3]) / 2,
      hx,
      hy
    )
    gl.uniform1f(u.uGrown, grown)
    gl.uniform1f(u.uRun, ran * (total - tabEnd))
    gl.uniform1f(u.uTabEnd, tabEnd)
    // The head swells as it runs, fully at speed, and comes to rest round as it slows into the top.
    gl.uniform1f(u.uSwell, SWELL * Math.min(speed / 3, 1))
    gl.uniform3f(u.uColor, ...color)
    gl.drawArrays(gl.TRIANGLES, 0, 3)
  }

  let frame = 0
  let settleUntil = 0
  const tick = (now: number) => {
    draw(now)
    frame = moving(now) || now < settleUntil ? requestAnimationFrame(tick) : 0
  }
  const wake = () => {
    if (frame) return
    lastTime = clock()
    frame = requestAnimationFrame(tick)
  }

  const resized = new ResizeObserver(() => {
    if (!frame) draw()
  })
  resized.observe(canvas)
  // Light or dark and the theme, from the system or from 設定, end up on <html data-mode data-theme>
  // (lib/appearance.ts).
  const scheme = new MutationObserver(() => {
    readColor()
    if (!frame) draw()
  })
  scheme.observe(document.documentElement, {
    attributeFilter: ["data-mode", "data-theme"],
  })
  // The GPU may drop the context; draw again once it is back.
  const lost = (event: Event) => event.preventDefault()
  const restored = () => {
    program = build(gl)
    draw()
  }
  canvas.addEventListener("webglcontextlost", lost)
  canvas.addEventListener("webglcontextrestored", restored)

  return {
    setTarget(next) {
      if (!placed) {
        placed = true
        on = next
        tab = still(next ? 1 : 0)
        run = still(next ? 1 : 0)
        drain = null
        draw()
        return
      }
      const now = clock()
      if (next !== on) {
        on = next
        const { grown, ran } = stateAt(now)
        if (next) {
          drain = null
          tab = {
            from: grown,
            to: 1,
            start: now,
            duration: TAB_MS * (1 - grown),
            ease: easeOut,
          }
          run = {
            from: ran,
            to: 1,
            start: now + FRAME_DELAY_MS * (1 - grown),
            duration: FRAME_MS * (1 - ran),
            ease: easeInOut,
          }
        } else {
          // Each part's share of the way by how far it moves, so the drain keeps one speed from frame to tab.
          const laid = parts()
          const measured = laid && measure(laid, canvas.getBoundingClientRect())
          const share = measured
            ? (measured.total - measured.tabEnd) /
              (measured.total - measured.tabEnd + measured.tabTravel)
            : 0.8
          const from =
            ran > 0 ? share * (1 - ran) : share + (1 - share) * (1 - grown)
          drain = {
            tween: {
              from,
              to: 1,
              start: now,
              duration: RETURN_MS * (1 - from),
              ease: easeInOut,
            },
            share,
          }
        }
      }
      settleUntil = now + SETTLE_MS
      wake()
    },
    dispose() {
      cancelAnimationFrame(frame)
      resized.disconnect()
      scheme.disconnect()
      canvas.removeEventListener("webglcontextlost", lost)
      canvas.removeEventListener("webglcontextrestored", restored)
      // Let go of what the GPU holds for it now, not when the canvas is collected: the program, and the drawing
      // buffer (a canvas sized 0). The context itself goes once the canvas has left the page; until then it may be
      // drawn on again, as React in development disposes and creates anew on the same canvas.
      if (program) releaseFullCanvas(gl, program)
      program = null
      canvas.width = 0
      canvas.height = 0
      setTimeout(() => {
        if (!canvas.isConnected)
          gl.getExtension("WEBGL_lose_context")?.loseContext()
      })
    },
  }
}
