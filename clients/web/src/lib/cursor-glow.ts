import { buildFullCanvas, drawingRatio, releaseFullCanvas } from "@/lib/webgl"

/** Recolors the cursor's existing drop shadows; the silhouette and blur stay exactly the same. */
export const CURSOR_PATH = "M3.85 3.85 16.65 8.65 10.89 10.89 8.65 16.65Z"

// The glow's colors: base + amp * cos(phase + offset), a phase that runs on GLOW_SPEED radians a second and grows
// across the glow along GLOW_DIRECTION, in the shader below.
const BASE = [0.56, 0.59, 0.82]
const AMP = [0.28, 0.27, 0.13]
const OFFSET = [0, 2.094, 4.189]
const GLOW_SPEED = 1.4
const GLOW_DIRECTION = [0.75, 0.55] as const

const vec = (values: readonly number[]) =>
  `vec${values.length}(${values.map((n) => n.toFixed(3)).join(", ")})`

const FRAGMENT = `
precision mediump float;
uniform vec2 uSize;
uniform float uTime;
uniform sampler2D uMask;

void main() {
  vec2 uv = vec2(gl_FragCoord.x, uSize.y - gl_FragCoord.y) / uSize;
  vec2 p = uv * 2.0 - 1.0;
  // Only the colors move. Alpha is the original 1px + 6px drop-shadow mask, never a circle or ribbon.
  float alpha = texture2D(uMask, uv).a;
  // One broad, travelling gradient instead of three angular color sectors. A full color cycle takes ~4.5s.
  float phase = uTime * ${GLOW_SPEED.toFixed(1)} + dot(p, ${vec(GLOW_DIRECTION)});
  vec3 color = ${vec(BASE)} + ${vec(AMP)} * cos(phase + ${vec(OFFSET)});
  gl_FragColor = vec4(color * alpha, alpha);
}`

/** The visible SVG's white outline and its two original CSS drop shadows, rasterized once at 2x. */
function shadowMask() {
  const source = document.createElement("canvas")
  const mask = document.createElement("canvas")
  source.width = source.height = mask.width = mask.height = 128
  const shape = source.getContext("2d")
  const shadow = mask.getContext("2d")
  if (!shape || !shadow || !("filter" in shadow)) return null
  // Canvas starts at (-26, -26); the 24px SVG starts at (-3, -3), so its origin here is (23, 23).
  shape.scale(2, 2)
  shape.translate(23, 23)
  shape.fillStyle = shape.strokeStyle = "white"
  shape.lineWidth = 6.4
  shape.lineJoin = "round"
  const path = new Path2D(CURSOR_PATH)
  shape.fill(path)
  shape.stroke(path)
  shadow.filter = "drop-shadow(0 0 2px white) drop-shadow(0 0 12px white)"
  shadow.drawImage(source, 0, 0)
  return mask
}

function build(gl: WebGLRenderingContext, mask: HTMLCanvasElement) {
  const drawn = buildFullCanvas(gl, FRAGMENT)
  if (!drawn) return null
  const texture = gl.createTexture()
  if (!texture) {
    releaseFullCanvas(gl, drawn)
    return null
  }
  gl.bindTexture(gl.TEXTURE_2D, texture)
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, mask)
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR)
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR)
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE)
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE)
  gl.uniform1i(gl.getUniformLocation(drawn.program, "uMask"), 0)
  return {
    ...drawn,
    texture,
    size: gl.getUniformLocation(drawn.program, "uSize"),
    time: gl.getUniformLocation(drawn.program, "uTime"),
  }
}

/** Starts the recolored shadow. Unsupported/lost rendering keeps the original CSS shadow. */
export function createCursorGlow(canvas: HTMLCanvasElement) {
  const mask = shadowMask()
  if (!mask) return
  const gl = canvas.getContext("webgl", {
    alpha: true,
    antialias: false,
    depth: false,
    stencil: false,
    premultipliedAlpha: true,
  })
  if (!gl) return
  let renderer = build(gl, mask)
  if (!renderer) return
  const motion = window.matchMedia("(prefers-reduced-motion: reduce)")
  let frame = 0
  let last = 0
  let elapsed = 0
  let visible = true

  const stop = () => {
    cancelAnimationFrame(frame)
    frame = 0
    last = 0
  }
  const draw = (now: number) => {
    frame = 0
    if (!renderer || gl.isContextLost() || document.hidden || !visible) return
    // Keep the phase across pauses; reduced motion draws one still frame.
    if (last && !motion.matches) elapsed += Math.min(now - last, 50) / 1000
    last = now
    // Matches the 64px CSS box, capped at 2x density; no layout measurement on each frame.
    const size = Math.round(64 * drawingRatio())
    if (canvas.width !== size || canvas.height !== size) {
      canvas.width = size
      canvas.height = size
    }
    gl.viewport(0, 0, size, size)
    gl.uniform2f(renderer.size, size, size)
    gl.uniform1f(renderer.time, elapsed)
    gl.drawArrays(gl.TRIANGLES, 0, 3)
    canvas.dataset.renderer = "webgl"
    if (!motion.matches) frame = requestAnimationFrame(draw)
  }
  const wake = () => {
    stop()
    if (renderer && !document.hidden && visible)
      frame = requestAnimationFrame(draw)
  }
  const release = () => {
    if (!renderer) return
    gl.deleteTexture(renderer.texture)
    releaseFullCanvas(gl, renderer)
    renderer = null
  }
  const lost = (event: Event) => {
    event.preventDefault()
    stop()
    release()
    delete canvas.dataset.renderer
  }
  const restored = () => {
    renderer = build(gl, mask)
    wake()
  }
  const observer = new IntersectionObserver(([entry]) => {
    visible = entry.isIntersecting
    wake()
  })
  observer.observe(canvas)
  motion.addEventListener("change", wake)
  document.addEventListener("visibilitychange", wake)
  window.addEventListener("resize", wake)
  canvas.addEventListener("webglcontextlost", lost)
  canvas.addEventListener("webglcontextrestored", restored)
  wake()

  return () => {
    stop()
    observer.disconnect()
    motion.removeEventListener("change", wake)
    document.removeEventListener("visibilitychange", wake)
    window.removeEventListener("resize", wake)
    canvas.removeEventListener("webglcontextlost", lost)
    canvas.removeEventListener("webglcontextrestored", restored)
    release()
    delete canvas.dataset.renderer
  }
}
