import { readFileSync, readdirSync } from "node:fs"
import { resolve } from "node:path"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig, type Plugin } from "vite"

// The runtime's HTTP API (`computer-use-runtime`, port 8000 in docker compose).
const api = process.env.CU_API_URL ?? "http://127.0.0.1:8000"
// No other site may show the page in a frame, where a click meant for it could approve a step (the Caddyfile sets the
// same for the image).
const headers = { "Content-Security-Policy": "frame-ancestors 'none'" }

// What pdf.js reads besides the PDF (src/components/side-panel/pdf-pages.tsx), as its package ships it: the character
// maps for fonts a PDF does not carry (Chinese ones), the standard fonts, the image decoders scans need (JPEG 2000,
// JBIG2) and colour profiles. Served at /pdfjs/ while developing and written into the build there. Not its script
// engine: a PDF's scripts are never run.
const PDFJS = resolve(import.meta.dirname, "node_modules/pdfjs-dist")
const PDFJS_DATA = ["cmaps", "standard_fonts", "wasm", "iccs"].flatMap(
  (folder) =>
    readdirSync(resolve(PDFJS, folder))
      .filter((name) => !name.startsWith("quickjs"))
      .map((name) => `${folder}/${name}`)
)
const TYPES: Record<string, string> = {
  wasm: "application/wasm",
  js: "text/javascript",
}

function pdfjsData(): Plugin {
  return {
    name: "pdfjs-data",
    configureServer(server) {
      server.middlewares.use("/pdfjs", (request, response, next) => {
        const path = decodeURIComponent(
          (request.url ?? "").split("?")[0]
        ).slice(1)
        if (!PDFJS_DATA.includes(path)) return next()
        response.setHeader(
          "Content-Type",
          TYPES[path.split(".").pop()!] ?? "application/octet-stream"
        )
        response.end(readFileSync(resolve(PDFJS, path)))
      })
    },
    generateBundle() {
      for (const path of PDFJS_DATA)
        this.emitFile({
          type: "asset",
          fileName: `pdfjs/${path}`,
          source: readFileSync(resolve(PDFJS, path)),
        })
    },
  }
}

export default defineConfig({
  // The React Compiler memoizes components and what they render, so a change of state in the sidebar's component
  // renders its rows again only where their props changed: with some forty rows, it rendered them all for 20-30ms.
  plugins: [react({ compiler: true }), tailwindcss(), pdfjsData()],
  resolve: {
    alias: {
      "@": resolve(import.meta.dirname, "./src"),
    },
  },
  server: {
    proxy: {
      "/api": api,
    },
    headers,
  },
  preview: { headers },
})
