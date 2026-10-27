// What the page's shaders (cursor-glow.ts, liquid-takeover.ts) share: each fragment shader paints one triangle that
// covers the whole canvas.

const VERTEX = `attribute vec2 p; void main() { gl_Position = vec4(p, 0.0, 1.0); }`

export type FullCanvas = { program: WebGLProgram; buffer: WebGLBuffer }

/**
 * `fragment` linked with the full-canvas vertex shader, in use, with its triangle bound to `p`; null if the browser
 * can't build it, with whatever was made up to then let go again.
 */
export function buildFullCanvas(
  gl: WebGLRenderingContext,
  fragment: string
): FullCanvas | null {
  const program = gl.createProgram()
  if (!program) return null
  for (const [type, source] of [
    [gl.VERTEX_SHADER, VERTEX],
    [gl.FRAGMENT_SHADER, fragment],
  ] as const) {
    const shader = gl.createShader(type)
    if (!shader) {
      gl.deleteProgram(program)
      return null
    }
    gl.shaderSource(shader, source)
    gl.compileShader(shader)
    const compiled = gl.getShaderParameter(shader, gl.COMPILE_STATUS)
    if (compiled) gl.attachShader(program, shader)
    // Kept by the program while it lives, and let go with it.
    gl.deleteShader(shader)
    if (!compiled) {
      gl.deleteProgram(program)
      return null
    }
  }
  gl.linkProgram(program)
  const buffer = gl.getProgramParameter(program, gl.LINK_STATUS)
    ? gl.createBuffer()
    : null
  if (!buffer) {
    gl.deleteProgram(program)
    return null
  }
  gl.useProgram(program)
  gl.bindBuffer(gl.ARRAY_BUFFER, buffer)
  gl.bufferData(
    gl.ARRAY_BUFFER,
    new Float32Array([-1, -1, 3, -1, -1, 3]),
    gl.STATIC_DRAW
  )
  const at = gl.getAttribLocation(program, "p")
  gl.enableVertexAttribArray(at)
  gl.vertexAttribPointer(at, 2, gl.FLOAT, false, 0, 0)
  return { program, buffer }
}

/** Lets go of what the GPU holds for a full-canvas program, unless the context is gone and took it already. */
export function releaseFullCanvas(
  gl: WebGLRenderingContext,
  drawn: FullCanvas
) {
  if (gl.isContextLost()) return
  gl.deleteBuffer(drawn.buffer)
  gl.deleteProgram(drawn.program)
}

/** Canvas pixels per CSS pixel: the screen's, up to 2, past which the shaders cost more than anyone sees. */
export const drawingRatio = () => Math.min(window.devicePixelRatio || 1, 2)
