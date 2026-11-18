import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from "react"
import { cn } from "cn"

import { AttachmentView } from "@/components/side-panel/attachment-view"
import {
  CheckIcon,
  ChevronDownIcon,
  CloseIcon,
  DocumentIcon,
  MonitorIcon,
  PhotoIcon,
} from "@/components/icons"
import { Button } from "@/components/ui/button"
import { ActionDialog } from "@/components/ui/dialog"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { previewOf } from "@/lib/attachments"
import { useT } from "@/lib/i18n"
import { reducedMotion } from "@/lib/motion"
import {
  COMPUTER,
  answer,
  closeFile,
  selectTab,
  shownFiles,
  shownTab,
  showing,
  unsaved,
  usePanel,
  type FileTab,
} from "@/lib/side-panel"

/** What the attachment tabs need from the page: the corner button's, and where a marked-up copy goes. */
export type PanelPlace = {
  phone: boolean
  corner: { expanded: boolean; onExpand: () => void } | { onClose: () => void }
  // Expanded over the conversation by the user: one button in place of the tabs.
  expanded: boolean
  // Why the composer takes no file now, else null.
  blocked: string | null
  onAdded: (send: boolean) => void // `send`: ⌘⏎, the message goes with it
}

// How far the tab row fades out where tabs are out of sight.
const FADE = 32

// The narrowest panel whose bar holds the markup tools with 取消 and the copy's button.
const ROOMY = 480

const TAB =
  "group/tab relative flex h-9 shrink-0 items-center rounded-lg transition-colors duration-150"
// A tab's selected fill, and the hover's: the pressed button's and the ghost button's.
const fill = (selected: boolean) =>
  selected
    ? "bg-secondary"
    : "text-muted-foreground hover:bg-muted hover:text-foreground"

type Connection = { label: string; connected: boolean } | null

/** The computer's screen, with the connection's dot on it and, while the user has the desktop, lit in the takeover
 * color, which they are to hand back. */
function ComputerGlyph({
  connection,
  yours,
}: {
  connection: Connection
  yours: boolean
}) {
  return (
    <span className="relative size-5 shrink-0">
      <MonitorIcon
        className={cn(
          "size-5",
          // Its screen lit in the same color, so it shows at a glance; the stand's lines have no inside.
          yours &&
            "text-takeover-glow [fill-opacity:0.22] dark:[fill-opacity:0.3]",
          // Cut out the lines around the dot so the tab's own background shows through.
          connection &&
            "[mask-image:radial-gradient(circle_at_80%_20%,transparent_6px,black_6.5px)]"
        )}
        style={yours ? { fill: "currentColor" } : undefined}
      />
      {connection && (
        <span
          aria-hidden
          className={cn(
            "absolute top-0 right-0 size-2 rounded-full",
            connection.connected ? "bg-success" : "bg-destructive"
          )}
        />
      )}
    </span>
  )
}

/** An attachment's icon: a picture, or any other file. */
function FileIcon({ file, className }: { file: FileTab; className?: string }) {
  return file.thumb || previewOf(file.source.name) === "image" ? (
    <PhotoIcon className={className} />
  ) : (
    <DocumentIcon className={className} />
  )
}

// The widest a name runs in the expanded view's button and its list.
const PICKED_NAME = 256

// How much of a name's end stays whole when it is cut: its last few characters and its extension.
const NAME_END = 4

let ruler: CanvasRenderingContext2D | null = null

/** The name as it fits `room` in `font`, cut in its middle as a file browser cuts one: its start gives way, while its
 * end and extension stay, so two files whose names begin alike still tell apart. */
function fitted(name: string, room: number, font: string) {
  ruler ??= document.createElement("canvas").getContext("2d")!
  ruler.font = font
  const width = (text: string) => ruler!.measureText(text).width
  if (width(name) <= room) return name
  const characters = Array.from(name)
  const dot = name.lastIndexOf(".")
  const stem =
    dot > 0 ? Array.from(name.slice(0, dot)).length : characters.length
  const cut = Math.max(0, stem - NAME_END)
  // The most of `from` that fits in `space`, cut after as many characters.
  const most = (from: string[], space: number) => {
    let low = 0
    let high = from.length
    while (low < high) {
      const middle = Math.ceil((low + high) / 2)
      if (width(from.slice(0, middle).join("")) <= space) low = middle
      else high = middle - 1
    }
    return from.slice(0, low).join("")
  }
  // An end keeps a character of the stem at least: "….png" alone tells no file from another.
  for (let endAt = cut; endAt < stem; endAt++) {
    const end = `…${characters.slice(endAt).join("")}`
    const endWidth = width(end)
    if (endWidth <= room)
      return most(characters.slice(0, endAt), room - endWidth) + end
  }
  // Where no such end fits, the start does.
  return `${most(characters, room - width("…"))}…`
}

/** A name fitted to its element, or to `room` where the element takes the width of what it holds; and whether it was
 * cut, for the full name on hover. */
function useFitted(name: string, room?: number) {
  const ref = useRef<HTMLSpanElement>(null)
  const [shown, setShown] = useState(name)
  useEffect(() => {
    const element = ref.current!
    const fit = () =>
      setShown(
        fitted(
          name,
          room ?? element.clientWidth,
          getComputedStyle(element).font
        )
      )
    const observer = new ResizeObserver(fit)
    observer.observe(element)
    // Measured again in the page's own font once it has come.
    void document.fonts.ready.then(fit)
    return () => observer.disconnect()
  }, [name, room])
  return { ref, shown, cut: shown !== name }
}

/** A file's name, fitted to `room`. */
function FileName({ name, room }: { name: string; room: number }) {
  const { ref, shown } = useFitted(name, room)
  return (
    <span ref={ref} className="overflow-hidden whitespace-nowrap">
      {shown}
    </span>
  )
}

// The narrowest a tab gets, its name still readable: past it the attachments' tabs scroll. And the room between tabs.
const MIN_TAB = 120
const TAB_GAP = 4

/** The computer's tab. Its words go first where the row is short of room (`labelled`), so the attachments keep their
 * names; `onWords` says how wide they are. `width`: its share of the row, where it takes one. */
function ComputerTab({
  selected,
  connection,
  yours,
  labelled,
  width,
  onWords,
}: {
  selected: boolean
  connection: Connection
  yours: boolean
  labelled: boolean
  width?: number
  onWords: (width: number) => void
}) {
  const label = useRef<HTMLSpanElement>(null)
  useEffect(() => {
    const element = label.current!
    // Their own width, whether shown or folded away.
    const observer = new ResizeObserver(() => onWords(element.scrollWidth))
    observer.observe(element)
    return () => observer.disconnect()
  }, [onWords])
  const t = useT()
  const name = connection
    ? t.tabs.computerWith(connection.label)
    : t.tabs.computer
  // Folded to its icon, it says what it is on hover; the connection only to a screen reader, as the dot shows it.
  return (
    <Tooltip disabled={labelled}>
      <TooltipTrigger
        render={
          <button
            type="button"
            role="tab"
            aria-selected={selected}
            aria-label={name}
            onClick={() => selectTab(COMPUTER)}
            style={{ width }}
            className={cn(
              TAB,
              "pl-2 text-sm font-medium transition-[color,background-color,padding] duration-200 ease-(--ease-out)",
              labelled ? "pr-3" : "pr-2",
              fill(selected)
            )}
          />
        }
      >
        <ComputerGlyph connection={connection} yours={yours} />
        <span
          ref={label}
          className={cn(
            "overflow-hidden whitespace-nowrap transition-[max-width,margin,opacity] duration-200 ease-(--ease-out)",
            labelled ? "ml-2.5 max-w-24" : "ml-0 max-w-0 opacity-0"
          )}
        >
          {t.tabs.computer}
        </span>
      </TooltipTrigger>
      <TooltipContent side="bottom">{t.tabs.computer}</TooltipContent>
    </Tooltip>
  )
}

/** An attachment's tab: an even share of the row, no narrower than MIN_TAB. Its close button shows on the chosen tab
 * and under the pointer, over another's name; while it holds markup a dot stands in for it until the pointer comes. */
function FileTabButton({
  file,
  selected,
  shown,
}: {
  file: FileTab
  selected: boolean
  shown: string[]
}) {
  const t = useT()
  const { name } = file.source
  const dirty = unsaved(file)
  // Room kept at the end for the close button or the dot.
  const kept = selected || dirty
  const { ref: nameRef, shown: shownName, cut } = useFitted(name)
  return (
    <div
      data-tab={file.key}
      className={cn(
        TAB,
        "min-w-30 grow basis-0 animate-in duration-200 ease-(--ease-out) zoom-in-95 fade-in motion-reduce:zoom-in-100",
        fill(selected),
        // Its close button reached by keyboard shows as under the pointer.
        !selected && "has-focus-visible:bg-muted"
      )}
    >
      <Tooltip disabled={!cut}>
        <TooltipTrigger
          render={
            <button
              type="button"
              role="tab"
              aria-selected={selected}
              aria-label={name}
              onClick={() => selectTab(file.key)}
              className={cn(
                "flex h-full min-w-0 flex-1 items-center gap-2.5 pl-2 text-sm font-medium",
                kept ? "pr-8" : "pr-2"
              )}
            />
          }
        >
          <FileIcon file={file} className="size-5 shrink-0" />
          <span
            ref={nameRef}
            className="min-w-0 flex-1 overflow-hidden text-left whitespace-nowrap"
          >
            {shownName}
          </span>
        </TooltipTrigger>
        <TooltipContent side="bottom">{name}</TooltipContent>
      </Tooltip>
      {dirty && (
        <span
          aria-hidden
          className="pointer-events-none absolute right-3 size-2 rounded-full bg-foreground/60 transition-opacity [@media(hover:hover)]:group-hover/tab:opacity-0"
        />
      )}
      <button
        type="button"
        aria-label={t.tabs.closeFile(name)}
        onClick={() => closeFile(file.key, shown)}
        className={cn(
          "absolute right-1 flex size-6 items-center justify-center rounded-xs text-muted-foreground transition-opacity hover:bg-foreground/8 hover:text-foreground focus-visible:opacity-100",
          // A hover shows it where there is one; on a touch screen only the chosen tab's, and one unseen takes no tap.
          selected && !dirty
            ? "opacity-100"
            : "opacity-0 [@media(hover:none)]:pointer-events-none",
          "[@media(hover:hover)]:group-hover/tab:opacity-100",
          // In the tab's hover fill, the name fading out before it.
          !kept &&
            "bg-muted before:pointer-events-none before:absolute before:inset-y-0 before:right-full before:w-3 before:bg-linear-to-r before:from-transparent before:to-muted hover:bg-[color-mix(in_oklch,var(--muted),var(--foreground)_8%)]"
        )}
      >
        <CloseIcon className="size-4" />
      </button>
    </div>
  )
}

/** In place of the tabs while the panel fills the page, as a viewer's corner is: the chosen tab's icon, which opens
 * the list of them to choose another. */
function TabPicker({
  files,
  tab,
  connection,
  yours,
}: {
  files: FileTab[]
  tab: string
  connection: Connection
  yours: boolean
}) {
  const t = useT()
  const chosen = files.find((each) => each.key === tab)
  // The button grows with the name up to this, as wide as the name's line in the list.
  const {
    ref: nameRef,
    shown: shownName,
    cut,
  } = useFitted(chosen?.source.name ?? t.tabs.computer, PICKED_NAME)
  const check = (key: string) =>
    key === tab && <CheckIcon className="ml-auto" />
  return (
    <Tooltip disabled={!cut}>
      <DropdownMenu>
        <TooltipTrigger
          render={
            <DropdownMenuTrigger
              render={
                <Button
                  variant="ghost"
                  aria-label={t.tabs.title}
                  className="touch-target absolute top-1.5 left-2.5 z-10 gap-1 pr-2.5 pl-2 md:top-2 md:left-2"
                />
              }
            />
          }
        >
          {chosen ? (
            <FileIcon file={chosen} className="size-5" />
          ) : (
            <ComputerGlyph connection={connection} yours={yours} />
          )}
          <span ref={nameRef} className="ml-1.5 whitespace-nowrap">
            {shownName}
          </span>
          <ChevronDownIcon className="size-4 text-muted-foreground" />
        </TooltipTrigger>
        <DropdownMenuContent align="start" className="max-w-80">
          <DropdownMenuItem onClick={() => selectTab(COMPUTER)}>
            <MonitorIcon />
            {t.tabs.computer}
            {check(COMPUTER)}
          </DropdownMenuItem>
          {files.map((file) => (
            <DropdownMenuItem
              key={file.key}
              onClick={() => selectTab(file.key)}
            >
              <FileIcon file={file} />
              <FileName name={file.source.name} room={PICKED_NAME} />
              {check(file.key)}
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
      {chosen && (
        <TooltipContent side="bottom" align="start">
          {chosen.source.name}
        </TooltipContent>
      )}
    </Tooltip>
  )
}

/** The attachments' tabs, scrolling sideways once even the narrowest don't fit, with no bar; a side with tabs out of
 * sight fades out, and the chosen one is brought into view. */
function FileTabs({ files, tab }: { files: FileTab[]; tab: string }) {
  const row = useRef<HTMLDivElement>(null)
  const [edges, setEdges] = useState({ start: false, end: false })
  const keys = files.map((each) => each.key)
  const measure = () => {
    const element = row.current
    if (!element) return
    const start = element.scrollLeft > 1
    const end =
      element.scrollLeft + element.clientWidth < element.scrollWidth - 1
    setEdges((was) =>
      was.start === start && was.end === end ? was : { start, end }
    )
  }
  useLayoutEffect(() => {
    const element = row.current
    if (!element) return
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    return () => observer.disconnect()
  })
  // A mouse's wheel scrolls it too: only a trackpad scrolls sideways. Not passive, so the page doesn't scroll instead.
  useEffect(() => {
    const element = row.current!
    const wheel = (event: WheelEvent) => {
      const sideways = Math.abs(event.deltaX) >= Math.abs(event.deltaY)
      const overflows = element.scrollWidth > element.clientWidth
      if (sideways || !overflows) return
      event.preventDefault()
      // Pixels a unit of the wheel moves: some wheels count in lines, each about 16 pixels.
      const step = event.deltaMode === WheelEvent.DOM_DELTA_LINE ? 16 : 1
      element.scrollLeft += event.deltaY * step
    }
    element.addEventListener("wheel", wheel, { passive: false })
    return () => element.removeEventListener("wheel", wheel)
  }, [])
  // The row alone scrolls, never the page around it: while the panel slides in, the tab is still off screen, and
  // scrolling it into view would shove the whole page aside. Clear of the 32 fade at either end.
  useEffect(() => {
    const element = row.current
    const chosen = element?.querySelector(`[data-tab="${CSS.escape(tab)}"]`)
    if (!element || !chosen) return
    const bounds = element.getBoundingClientRect()
    const place = chosen.getBoundingClientRect()
    const by =
      place.left < bounds.left + FADE
        ? place.left - bounds.left - FADE
        : place.right > bounds.right - FADE
          ? place.right - bounds.right + FADE
          : 0
    if (by)
      element.scrollBy({
        left: by,
        behavior: reducedMotion() ? "auto" : "smooth",
      })
  }, [tab, files.length])
  const fade = (on: boolean) =>
    on ? `transparent, black ${FADE}px` : "black, black"
  return (
    <div
      ref={row}
      onScroll={measure}
      className="flex min-w-0 flex-1 [scrollbar-width:none] items-center gap-1 overflow-x-auto [&::-webkit-scrollbar]:hidden"
      style={{
        maskImage:
          edges.start || edges.end
            ? `linear-gradient(to right, ${fade(edges.start)}), linear-gradient(to left, ${fade(edges.end)})`
            : undefined,
        maskComposite: "intersect",
      }}
    >
      {files.map((each) => (
        <FileTabButton
          key={each.key}
          file={each}
          selected={each.key === tab}
          shown={keys}
        />
      ))}
    </div>
  )
}

/**
 * The panel beside the conversation: the computer's live view and the conversation's attachments, each a tab along
 * its top. The live view is drawn only while its tab is chosen: unseen, nothing is captured.
 */
export function SidePanel({
  computer,
  runs,
  draft,
  connection,
  yours,
  place,
}: {
  computer: ReactNode
  runs: readonly string[]
  draft: string
  connection: Connection
  yours: boolean
  place: PanelPlace
}) {
  const t = useT()
  const panel = usePanel()
  const files = shownFiles(panel, runs, draft)
  const tab = shownTab(panel, files, draft)
  const file = files.find((each) => each.key === tab) ?? null
  const shown = files.map((each) => each.key)
  useEffect(() => {
    showing(shown)
    return () => showing([])
  })
  // Where the bar under a picture has no room for them (a phone, a narrow panel), marking up puts 取消 and the copy's
  // button in the top row, and the tabs make way.
  const root = useRef<HTMLDivElement>(null)
  const [narrow, setNarrow] = useState(false)
  useLayoutEffect(() => {
    const element = root.current
    if (!element) return
    const observer = new ResizeObserver(([entry]) =>
      setNarrow(entry.contentRect.width < ROOMY)
    )
    observer.observe(element)
    return () => observer.disconnect()
  }, [])
  const compact = place.phone || narrow
  // The tabs share the row evenly while a share holds the computer's words and MIN_TAB. Past that its words fold away,
  // and the attachments' tabs share what is left.
  const [row, setRow] = useState<HTMLDivElement | null>(null)
  const [room, setRoom] = useState(0)
  const [words, setWords] = useState(0)
  useEffect(() => {
    if (!row) return
    const observer = new ResizeObserver(([entry]) =>
      setRoom(entry.contentRect.width)
    )
    observer.observe(row)
    return () => observer.disconnect()
  }, [row])
  const share = (room - files.length * TAB_GAP) / (files.length + 1)
  // pl-2, the icon, the gap to the words, the words, pr-3.
  const computerWide = 8 + 20 + 10 + words + 12
  const shared = files.length > 0 && share >= Math.max(MIN_TAB, computerWide)
  // Its words show while it shares the row, while it is alone in it, and until the row is measured.
  const labelled = shared || !files.length || !room
  const rowTaken = compact && file?.markup != null
  return (
    <div ref={root} className="relative size-full" role="tabpanel">
      {file ? (
        <AttachmentView
          key={file.key}
          file={file}
          draft={draft}
          place={place}
          compact={compact}
        />
      ) : (
        computer
      )}
      {/* Over the panel's top, as the corner buttons are, so the live view keeps its own layout under it. Its end
        leaves room for them. */}
      {rowTaken ? null : place.expanded ? (
        <TabPicker
          files={files}
          tab={tab}
          connection={connection}
          yours={yours}
        />
      ) : (
        <div
          ref={setRow}
          role="tablist"
          aria-label={t.tabs.title}
          className={cn(
            "pointer-events-none absolute inset-x-0 top-0 z-10 flex h-12 items-center gap-1 pr-(--end) pl-2.5 *:pointer-events-auto md:h-13 md:pl-2",
            "onExpand" in place.corner
              ? "[--end:--spacing(23)]"
              : "[--end:--spacing(14)]",
            // Cut where the corner buttons start while the panel slides in (index.css's --slide): they hold their
            // place, and the tabs riding in with the edge never pass under them.
            "[clip-path:inset(-8px_calc(var(--slide)*100%+var(--end))_-8px_-8px)]"
          )}
        >
          <ComputerTab
            selected={tab === COMPUTER}
            connection={connection}
            yours={yours}
            labelled={labelled}
            width={shared ? share : undefined}
            onWords={setWords}
          />
          {files.length > 0 && <FileTabs files={files} tab={tab} />}
        </div>
      )}
      <ActionDialog
        open={panel.confirm !== null}
        onOpenChange={(open) => !open && answer(false, shown)}
        title={t.markup.discard.title}
        action={t.markup.discard.confirm}
        destructive
        onAction={() => answer(true, shown)}
      >
        <p className="text-muted-foreground">{t.markup.discard.body}</p>
      </ActionDialog>
    </div>
  )
}
