import { useEffect, useLayoutEffect, useRef, useState } from "react"
import type { PDFDocumentProxy, PDFPageProxy, RenderTask } from "pdfjs-dist"
import worker from "pdfjs-dist/build/pdf.worker.min.mjs?url"

import { Spinner } from "@/components/ui/spinner"
import { useT } from "@/lib/i18n"

/** The document, read by pdf.js, which loads the first time a PDF is shown: most visits never need it. A copy of the
 * bytes goes, as pdf.js takes what it is given. */
async function read(data: ArrayBuffer) {
  const pdfjs = await import("pdfjs-dist")
  pdfjs.GlobalWorkerOptions.workerSrc = worker
  // What it reads besides the PDF (vite.config.ts): without it, Chinese in fonts the file does not carry and scanned
  // pages (JPEG 2000, JBIG2) come out blank.
  const at = (folder: string) =>
    new URL(`${import.meta.env.BASE_URL}pdfjs/${folder}/`, location.href).href
  return pdfjs.getDocument({
    data: data.slice(0),
    cMapUrl: at("cmaps"),
    cMapPacked: true,
    standardFontDataUrl: at("standard_fonts"),
    wasmUrl: at("wasm"),
    iccUrl: at("iccs"),
  })
}

/** How large the pages are shown: as wide as the panel, or a share of their printed size. */
export type Zoom = "fit" | number

// Where each PDF was left, by its tab: its zoom and how far it was scrolled. Kept while the page is open, so a tab
// switched away from (to approve a step on the computer) comes back where it was.
const left = new Map<string, { zoom: Zoom; top: number; left: number }>()
const place = (key: string) => left.get(key) ?? { zoom: "fit", top: 0, left: 0 }
export const zoomOf = (key: string) => place(key).zoom
export const keepZoom = (key: string, zoom: Zoom) =>
  left.set(key, { ...place(key), zoom })

// A PDF measures in points, 72 to the inch, and the page in CSS pixels, 96 to it: at 100% a page is as large as printed.
const POINT = 96 / 72

type Size = { width: number; height: number } // in points

// A zoom or a panel being dragged wider redraws the pages near the view once it has held still this long; meanwhile
// what was drawn stretches to the new size, so nothing goes blank.
const SETTLE_MS = 150
// The most pixels a page is drawn with: past about this a phone's browser draws nothing at all.
const MOST_PIXELS = 16_000_000

/** One page at `scale` (CSS pixels to its points): drawn in view, blank outside it. Its size is the first
 * page's until it has been read. A new scale draws it again beside what is shown, which it replaces once done. */
function Page({
  doc,
  number,
  size,
  scale,
  maxWidth,
  scroller,
}: {
  doc: PDFDocumentProxy
  number: number
  size: Size
  scale: number
  maxWidth: number
  scroller: HTMLElement
}) {
  const t = useT()
  const box = useRef<HTMLDivElement>(null)
  const canvas = useRef<HTMLCanvasElement>(null)
  const [own, setOwn] = useState<Size | null>(null)
  // In view; drawn at least once since it entered; failed to draw.
  const [visible, setVisible] = useState(false)
  const [drawn, setDrawn] = useState(false)
  const [broken, setBroken] = useState(false)
  useEffect(() => {
    const observer = new IntersectionObserver(
      ([entry]) => {
        setVisible(entry.isIntersecting)
        if (!entry.isIntersecting) {
          setDrawn(false)
          setBroken(false)
        }
      },
      { root: scroller }
    )
    observer.observe(box.current!)
    return () => observer.disconnect()
  }, [scroller])
  useEffect(() => {
    const target = canvas.current!
    if (!visible) {
      target.width = target.height = 0
      return
    }
    let gone = false
    let task: RenderTask | null = null
    // Keep the current pixels on screen until their replacement is ready.
    const draw = async () => {
      let page: PDFPageProxy | undefined
      const offscreen = document.createElement("canvas")
      try {
        page = await doc.getPage(number)
        if (gone) return
        const base = page.getViewport({ scale: 1 })
        setOwn({ width: base.width, height: base.height })
        const wanted = Math.min(scale, maxWidth / base.width) * devicePixelRatio
        const pixels = base.width * base.height * wanted * wanted
        const viewport = page.getViewport({
          scale: wanted * Math.min(1, Math.sqrt(MOST_PIXELS / pixels)),
        })
        offscreen.width = Math.round(viewport.width)
        offscreen.height = Math.round(viewport.height)
        task = page.render({ canvas: offscreen, viewport })
        await task.promise
        if (gone) return
        target.width = offscreen.width
        target.height = offscreen.height
        target.getContext("2d")!.drawImage(offscreen, 0, 0)
        setDrawn(true)
      } catch (error) {
        // Cancelled for a newer drawing, or as it scrolled away; anything else stops its spinner and says so.
        if (!gone && (error as Error).name !== "RenderingCancelledException")
          setBroken(true)
      } finally {
        // The displayed canvas already has the pixels. Release the render surface and decoded page objects.
        offscreen.width = offscreen.height = 0
        page?.cleanup()
      }
    }
    // At once the first time; after a change of size, once it has held still.
    const timer = window.setTimeout(draw, target.width ? SETTLE_MS : 0)
    return () => {
      gone = true
      window.clearTimeout(timer)
      task?.cancel()
    }
  }, [doc, number, visible, scale, maxWidth])
  const shown = own ?? size
  return (
    <div
      ref={box}
      className="relative shrink-0 bg-white ring-1 ring-foreground/5"
      style={{
        width: Math.min(shown.width * scale, maxWidth),
        aspectRatio: `${shown.width} / ${shown.height}`,
      }}
    >
      <canvas
        ref={canvas}
        width={0}
        height={0}
        aria-hidden
        className="absolute inset-0 size-full"
      />
      {broken ? (
        <p className="absolute inset-0 flex items-center justify-center text-sm text-neutral-500">
          {t.tabs.pageFailed}
        </p>
      ) : (
        visible &&
        !drawn && (
          <div className="absolute inset-0 flex items-center justify-center">
            {/* A page that takes a while (a scan) says it is coming. */}
            <Spinner className="size-5 animate-in text-neutral-400 delay-300 duration-200 fill-mode-backwards fade-in" />
          </div>
        )
      )}
    </div>
  )
}

/** A PDF's pages, one under another, as wide as the panel or at `zoom` of their printed size: drawn here, the same in
 * every browser, rather than by a browser's own viewer, which some have not (a phone's). Says what share of the
 * printed size fits the panel (`onFit`), for the zoom's menu. */
export function PdfPages({
  data,
  name,
  memory,
  zoom,
  onFit,
}: {
  data: ArrayBuffer
  name: string
  memory: string // whose place it keeps (zoomOf)
  zoom: Zoom
  onFit: (percent: number) => void
}) {
  const t = useT()
  const [doc, setDoc] = useState<{ doc: PDFDocumentProxy; first: Size } | null>(
    null
  )
  const [failed, setFailed] = useState(false)
  const [scroller, setScroller] = useState<HTMLElement | null>(null)
  const [column, setColumn] = useState(0)
  useEffect(() => {
    let gone = false
    // Its reading, which lets go of the document and its worker once the tab goes.
    const task = read(data)
    task
      .then(async (loading) => {
        const opened = await loading.promise
        if (gone) return
        const first = (await opened.getPage(1)).getViewport({ scale: 1 })
        if (!gone)
          setDoc({
            doc: opened,
            first: { width: first.width, height: first.height },
          })
      })
      .catch(() => !gone && setFailed(true))
    return () => {
      gone = true
      void task.then((loading) => loading.destroy()).catch(() => {})
    }
  }, [data])
  // The room across the panel, less its padding.
  useEffect(() => {
    if (!scroller) return
    const observer = new ResizeObserver(([entry]) =>
      setColumn(entry.contentRect.width)
    )
    observer.observe(scroller)
    return () => observer.disconnect()
  }, [scroller])
  // The whole percentage is only a label. Rounding the drawing scale up can create a horizontal scrollbar.
  const fitScale = doc ? column / doc.first.width : 0
  const fitPercent = Math.round((fitScale / POINT) * 100)
  useEffect(() => {
    if (fitPercent) onFit(fitPercent)
  }, [fitPercent, onFit])
  // Back where it was left once its pages are laid out, and kept as it scrolls.
  const laidOut = !!scroller && fitScale > 0
  useLayoutEffect(() => {
    if (!laidOut) return
    const { top, left: across } = place(memory)
    scroller!.scrollTo(across, top)
  }, [laidOut, memory, scroller])
  const keepPlace = () => {
    if (scroller)
      left.set(memory, {
        ...place(memory),
        top: scroller.scrollTop,
        left: scroller.scrollLeft,
      })
  }
  if (failed)
    return (
      <p className="flex size-full items-center justify-center text-sm text-muted-foreground">
        {t.tabs.loadFailed}
      </p>
    )
  if (!doc)
    return (
      <div className="flex size-full items-center justify-center">
        <Spinner className="size-5 text-muted-foreground" />
      </div>
    )
  const scale = zoom === "fit" ? fitScale : (zoom / 100) * POINT
  // A wider page in a mixed-size document still has to fit the column.
  const maxWidth = zoom === "fit" ? column : Infinity
  return (
    // To the panel's edges, so the scroll bars sit at its sides and the pages' shadows are not cut. Wider than the
    // panel, the pages scroll sideways too, from their left edge.
    <div
      ref={setScroller}
      onScroll={keepPlace}
      aria-label={name}
      className="-mx-4 h-full overflow-auto px-4 py-2"
    >
      {laidOut && (
        <div className="flex w-max min-w-full flex-col items-center gap-4">
          {Array.from({ length: doc.doc.numPages }, (_, index) => (
            <Page
              key={index}
              doc={doc.doc}
              number={index + 1}
              size={doc.first}
              scale={scale}
              maxWidth={maxWidth}
              scroller={scroller}
            />
          ))}
        </div>
      )}
    </div>
  )
}
