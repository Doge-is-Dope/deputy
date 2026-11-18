// Draws the columns of the open popup or dialog (or the page) as dashed lines, so a screenshot shows at a glance what
// is on a column and what is not (../references/layout.md). Run in a browser's JavaScript evaluator on the Vite dev
// server with the popup, dialog or page open, then screenshot.
// Red: a column two or more edges share, and the first and last line boxes. Blue: an edge 1 to 4px off a column, to fix.
// __guidesClear() takes the lines away.
const box =
  [...document.querySelectorAll('[data-slot="dialog-content"], [role="dialog"], [role="menu"], [role="listbox"]')]
    .filter((el) => el.getBoundingClientRect().width > 0)
    .sort((a, b) => b.getBoundingClientRect().width * b.getBoundingClientRect().height -
      a.getBoundingClientRect().width * a.getBoundingClientRect().height)[0] ?? document.body
const B = box.getBoundingClientRect()
const round = (v) => Math.round(v * 2) / 2

// Every edge from the box's own edges: words' line boxes, icons, the close button's icon. What sits in the box's left
// half lines up by its start and what sits in the right half by its end (a number, a time, the close icon), so only
// that edge counts: two words that merely happen to end near each other are not a column.
const left = []
const right = []
const lines = []
const add = (r, label) => {
  if ((r.left + r.right) / 2 < B.left + B.width / 2) left.push({ at: round(r.left - B.left), label })
  else right.push({ at: round(B.right - r.right), label })
}
const walker = document.createTreeWalker(box, NodeFilter.SHOW_TEXT)
for (let node; (node = walker.nextNode()); ) {
  const el = node.parentElement
  if (!node.textContent.trim() || el.closest(".sr-only") || getComputedStyle(el).visibility === "hidden") continue
  const range = document.createRange()
  range.selectNodeContents(node)
  const leading = parseFloat(getComputedStyle(el).lineHeight)
  for (const r of range.getClientRects()) {
    if (r.width === 0 || r.bottom < B.top || r.top > B.bottom) continue
    const label = node.textContent.trim().slice(0, 12)
    add(r, label)
    const half = ((leading || r.height) - r.height) / 2
    lines.push({ top: r.top - half - B.top, bottom: B.bottom - (r.bottom + half), label })
  }
}
for (const svg of box.querySelectorAll("svg")) {
  const r = svg.getBoundingClientRect()
  if (r.width === 0 || r.width > 40) continue
  add(r, svg.closest("[data-slot='dialog-close']") ? "close icon" : "icon")
}

// Columns: values two or more edges share. A miss: an edge within 4px of a column but not on it.
const columns = (edges) => {
  const count = {}
  for (const e of edges) count[e.at] = (count[e.at] ?? 0) + 1
  const shared = Object.keys(count).map(Number).filter((at) => count[at] > 1)
  const misses = edges.filter((e) => !shared.includes(e.at) && shared.some((at) => Math.abs(at - e.at) <= 4))
    .map((e) => ({ ...e, near: shared.find((at) => Math.abs(at - e.at) <= 4) }))
  return { shared: shared.sort((a, b) => a - b), misses }
}
const L = columns(left)
const R = columns(right)
const first = Math.min(...lines.map((l) => l.top)) // not `top`: the window's own
const last = Math.min(...lines.map((l) => l.bottom))

// The lines, on a layer over the box that the pointer goes through.
window.__guidesClear?.()
const layer = document.createElement("div")
layer.style.cssText = `position:fixed;left:${B.left}px;top:${B.top}px;width:${B.width}px;height:${B.height}px;` +
  "pointer-events:none;z-index:2147483647"
const line = (css, color) => {
  const el = document.createElement("div")
  el.style.cssText = `position:absolute;${css};border-color:${color}`
  layer.append(el)
}
const red = "rgba(230,70,60,.8)"
const blue = "rgba(40,110,230,.9)"
for (const at of L.shared) line(`top:0;bottom:0;left:${at}px;border-left:1px dashed`, red)
for (const at of R.shared) line(`top:0;bottom:0;right:${at}px;border-right:1px dashed`, red)
for (const m of L.misses) line(`top:0;bottom:0;left:${m.at}px;border-left:1px dashed`, blue)
for (const m of R.misses) line(`top:0;bottom:0;right:${m.at}px;border-right:1px dashed`, blue)
if (lines.length) {
  line(`left:0;right:0;top:${first}px;border-top:1px dashed`, red)
  line(`left:0;right:0;bottom:${last}px;border-bottom:1px dashed`, red)
}
document.body.append(layer)
window.__guidesClear = () => layer.remove()

JSON.stringify({
  box: `${box.dataset.slot || box.getAttribute("role") || box.tagName.toLowerCase()} ${Math.round(B.width)}x${Math.round(B.height)}`,
  left: L.shared,
  right: R.shared,
  misses: [...L.misses.map((m) => ({ side: "left", ...m })), ...R.misses.map((m) => ({ side: "right", ...m }))],
  firstLineTop: round(first),
  lastLineBottom: round(last),
}, null, 1)
