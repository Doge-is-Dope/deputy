import { resolve } from "node:path"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

// The runtime's HTTP API (`computer-use-runtime`, port 8000 in docker compose).
const api = process.env.CU_API_URL ?? "http://127.0.0.1:8000"

// https://vite.dev/config/
export default defineConfig({
  // The React Compiler memoizes components and what they render, so a change of state in the sidebar's component
  // renders its rows again only where their props changed: with some forty rows, it rendered them all for 20-30ms.
  plugins: [react({ compiler: true }), tailwindcss()],
  resolve: {
    alias: {
      "@": resolve(import.meta.dirname, "./src"),
    },
  },
  server: {
    proxy: {
      "/api": api,
    },
  },
})
