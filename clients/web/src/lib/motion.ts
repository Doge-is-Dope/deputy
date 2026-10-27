/** Whether the viewer asked for less motion, read when an animation starts. */
export const reducedMotion = () =>
  matchMedia("(prefers-reduced-motion: reduce)").matches
