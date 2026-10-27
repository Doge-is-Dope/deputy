// A section's or a project's list folding open and shut: the height on the drawer's curve, quick to start and long to
// settle, the rows fading with it. The rows do not drift into place: a translate on the panel's content comes off the
// height Base UI measures as the panel opens (the overflow follows the transform), the height it unfolds to was 6px
// short, and the list below snapped down by that at the end. No blur: with the rows' fading masks it repaints the
// whole list every frame and stutters. Clipped 2px out from its edge, so a row's focus ring, which reaches 2px past
// the row and so past the list's edge, is not cut off at the sides, nor at the top on the first row
// (overflow-clip-margin; Safari ignores it and clips at the edge, as before).
export const FOLD_DURATION = 300 // its duration-300
export const FOLD =
  "h-(--collapsible-panel-height) overflow-clip [overflow-clip-margin:2px] transition-[height,opacity] duration-300 ease-(--ease-drawer) data-ending-style:h-0 data-ending-style:opacity-0 data-starting-style:h-0 data-starting-style:opacity-0 motion-reduce:transition-none"

// It settles into its new place on the drawer's curve, the project unseen there until it lands.
export const DROP = { duration: 200, easing: "cubic-bezier(0.32, 0.72, 0, 1)" }

/** Opens a row where it goes, or closes it up where it was, as a list folds (FOLD), on a dropped project's curve (DROP):
 * the rows below make room or close up behind it, nothing gliding past the list's edge, the gap between rows opening
 * and closing with it. The only row in its list folds too, or fades alone where something takes its place. Returns
 * what puts the row back as it was. */
export function fold(
  row: HTMLElement,
  way: "in" | "out",
  alone: "fold" | "fade"
) {
  const gap = parseFloat(getComputedStyle(row.parentElement!).rowGap) || 0
  const side = row.previousElementSibling
    ? "marginTop"
    : row.nextElementSibling
      ? "marginBottom"
      : null
  const shut =
    side || alone === "fold"
      ? { height: "0px", opacity: 0, ...(side && { [side]: `${-gap}px` }) }
      : { opacity: 0 }
  const full =
    side || alone === "fold"
      ? {
          height: `${row.offsetHeight}px`,
          opacity: 1,
          ...(side && { [side]: "0px" }),
        }
      : { opacity: 1 }
  row.style.overflow = "hidden"
  const animation = row.animate(way === "in" ? [shut, full] : [full, shut], {
    ...DROP,
    fill: "forwards",
  })
  return () => {
    animation.cancel()
    row.style.overflow = ""
  }
}
