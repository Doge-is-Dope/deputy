// Lists every font size rendered on the current page, with its line height, how many text runs use it and a few
// examples, and flags a size off the type scale (../SKILL.md). Run in the Browser pane on the Vite dev server (the
// JavaScript tool). Hidden text and text at zero opacity are left out.
const scale = [12, 14, 16, 18, 20, 24]
const sizes = {}
const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT)
let node
while ((node = walker.nextNode())) {
  const text = node.textContent.trim()
  if (!text) continue
  const el = node.parentElement
  const box = el.getBoundingClientRect()
  if (!box.width || !box.height) continue
  const style = getComputedStyle(el)
  if (style.visibility === "hidden" || Number(style.opacity) === 0) continue
  const key = `${style.fontSize} / ${style.lineHeight}`
  const entry = (sizes[key] ||= { runs: 0, examples: [] })
  entry.runs++
  if (entry.examples.length < 4 && !entry.examples.includes(text.slice(0, 24)))
    entry.examples.push(text.slice(0, 24))
}
Object.entries(sizes)
  .sort((a, b) => parseFloat(b[0]) - parseFloat(a[0]))
  .map(([key, { runs, examples }]) => {
    const off = scale.includes(parseFloat(key)) ? "" : "  <- off the scale"
    return `${key} x${runs}: ${examples.join(" | ")}${off}`
  })
  .join("\n")
