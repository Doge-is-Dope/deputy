// Lists every rounded shape on screen that sits near the corner of a rounded parent, with the radius it has and the
// one concentric corners give (outer less the gap, ../references/layout.md), and every odd radius. Run in a browser's
// JavaScript evaluator on the Vite dev server with the popup, dialog or page open. A hairline's 1px is not counted, so
// a radius within 1 of the rule passes.
const radius = (el) => {
  const style = getComputedStyle(el)
  const box = el.getBoundingClientRect()
  const set = Math.max(parseFloat(style.borderTopLeftRadius) || 0, parseFloat(style.borderBottomRightRadius) || 0)
  return Math.min(set, Math.min(box.width, box.height) / 2) // a pill's radius is half its short side
}
const painted = (el) => {
  const style = getComputedStyle(el)
  const clear = style.backgroundColor === "rgba(0, 0, 0, 0)" || /, 0\)$/.test(style.backgroundColor)
  return !clear || parseFloat(style.borderTopWidth) > 0 || style.boxShadow !== "none"
}
// Shapes that show a background only on hover or when chosen.
const pressable = (el) =>
  /^(BUTTON|A|INPUT|TEXTAREA|SELECT)$/.test(el.tagName) || /menuitem|option|tab|radio/.test(el.getAttribute("role") || "")
const name = (el) =>
  `${el.getAttribute("aria-label") || el.getAttribute("role") || el.dataset.slot || el.tagName.toLowerCase()} "${(el.innerText || "").trim().slice(0, 12).replace(/\n/g, " ")}"`

const nested = []
const odd = new Set()
const seen = new Set()
for (const el of document.querySelectorAll("body *")) {
  const box = el.getBoundingClientRect()
  if (box.width < 8 || box.height < 8 || box.bottom < 0 || box.top > innerHeight) continue
  const inner = radius(el)
  if (inner <= 0 || !(painted(el) || pressable(el))) continue
  const set = parseFloat(getComputedStyle(el).borderTopLeftRadius)
  if (set < 1000 && set % 2) odd.add(`${set} on ${name(el)}`)
  let parent = el.parentElement
  while (parent && parent !== document.body && !(radius(parent) > 0 && painted(parent))) parent = parent.parentElement
  if (!parent || parent === document.body) continue
  const outer = radius(parent)
  const around = parent.getBoundingClientRect()
  const left = box.left - around.left
  const top = box.top - around.top
  const right = around.right - box.right
  const bottom = around.bottom - box.bottom
  // The corner it is nearest to, and its distance from that corner's two edges.
  const corner = [[left, top], [right, top], [left, bottom], [right, bottom]].sort(
    (a, b) => Math.max(...a) - Math.max(...b),
  )[0]
  const gap = Math.max(...corner)
  if (Math.min(...corner) < -1 || gap >= outer) continue // outside it, or clear of the corner
  if (inner === 28 && parent.dataset.slot === "sidebar-inset") continue // the composer keeps its 28 (layout.md)
  const key = `${name(parent).split(" ")[0]}>${name(el).split(" ")[0]}:${inner}:${gap}`
  if (seen.has(key)) continue
  seen.add(key)
  const rule = outer - gap
  nested.push({ outer: name(parent), radius: outer, inner: name(el), has: inner, gap, rule, ok: Math.abs(inner - rule) <= 1 })
}
console.table(nested)
JSON.stringify({ nested, odd: [...odd] }, null, 1)
