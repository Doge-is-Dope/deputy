// Prints each icon's ink box at 20px in grid units: the shape plus half its 1.33px stroke on each side.
// Run in the Browser pane on the Vite dev server (the JavaScript tool, top-level await). Edit `names`; leave it empty
// for every icon in icons.tsx.
const names = []
const icons = await import("/src/components/icons.tsx?t=" + Date.now())
const React = (await import("/node_modules/.vite/deps/react.js")).default
const client = await import("/node_modules/.vite/deps/react-dom_client.js")
const createRoot = client.createRoot || client.default.createRoot
const list = names.length
  ? names
  : Object.keys(icons).filter((n) => /Icon$/.test(n) && n !== "ProviderIcon")
const host = document.createElement("div")
host.style.cssText = "position:fixed;left:-9999px;top:0"
document.body.append(host)
const root = createRoot(host)
root.render(
  React.createElement(
    "div",
    null,
    list.map((n) =>
      React.createElement("span", { key: n, "data-n": n }, React.createElement(icons[n]))
    )
  )
)
await new Promise((r) => setTimeout(r, 300))
const S = 96
const out = []
for (const n of list) {
  const svg = host.querySelector(`[data-n="${n}"] svg`).cloneNode(true)
  svg.setAttribute("width", S)
  svg.setAttribute("height", S)
  // 1.33 screen pixels at 20px is 1.6 grid units.
  svg.setAttribute("stroke-width", 1.6)
  svg.setAttribute("xmlns", "http://www.w3.org/2000/svg")
  svg.querySelectorAll("[opacity]").forEach((e) => e.setAttribute("opacity", 1))
  const img = new Image()
  img.src =
    "data:image/svg+xml;charset=utf-8," +
    encodeURIComponent(svg.outerHTML.replaceAll("currentColor", "#000"))
  await img.decode()
  const canvas = document.createElement("canvas")
  canvas.width = canvas.height = S
  const g = canvas.getContext("2d")
  g.drawImage(img, 0, 0)
  const d = g.getImageData(0, 0, S, S).data
  let x0 = S, y0 = S, x1 = -1, y1 = -1
  for (let y = 0; y < S; y++)
    for (let x = 0; x < S; x++)
      if (d[(y * S + x) * 4 + 3] > 76) {
        x0 = Math.min(x0, x)
        y0 = Math.min(y0, y)
        x1 = Math.max(x1, x)
        y1 = Math.max(y1, y)
      }
  const k = 24 / S
  const box = [x0, y0, x1 + 1, y1 + 1].map((v) => (v * k).toFixed(1))
  out.push(
    `${n}: ${((x1 + 1 - x0) * k).toFixed(1)} x ${((y1 + 1 - y0) * k).toFixed(1)}  [${box.join(", ")}]`
  )
}
root.unmount()
host.remove()
out.join("\n")
