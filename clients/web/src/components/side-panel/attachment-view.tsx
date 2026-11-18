import { useEffect, useEffectEvent, useRef, useState } from "react"
import { cn } from "cn"

import { showError } from "@/components/notice"
import { CornerButton } from "@/components/side-panel/corner-button"
import { MarkupStage } from "@/components/side-panel/markup-editor"
import {
  PdfPages,
  keepZoom,
  zoomOf,
  type Zoom,
} from "@/components/side-panel/pdf-pages"
import {
  MarkupToolbar,
  TEXT_BUTTON,
} from "@/components/side-panel/markup-toolbar"
import type { PanelPlace } from "@/components/side-panel/side-panel"
import { Button } from "@/components/ui/button"
import { Kbd } from "@/components/ui/kbd"
import { Spinner } from "@/components/ui/spinner"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { useAttachments } from "@/hooks/use-attachments"
import { draftOf, editDraft } from "@/hooks/use-drafts"
import { screenshotUrl, uploadUrl } from "@/lib/api"
import { MAX_FILES, decoded, previewOf } from "@/lib/attachments"
import { useT } from "@/lib/i18n"
import { ENTER_KEYCAP, MAC, MOD_KEYCAP, isComposing } from "@/lib/keys"
import {
  EMPTY,
  commentsIn,
  relabelled,
  withComments,
  drawnOf,
  flattened,
  redone,
  undone,
  type Color,
  type Shape,
  type Tool,
} from "@/lib/markup"
import {
  copyOf,
  getPanel,
  keepCopy,
  keyOf,
  leaveMarkup,
  openFile,
  renameTab,
  setMarkup,
  setWriting,
  type FileTab,
  type Source,
} from "@/lib/side-panel"

// Plain text is shown up to this much: enough to read, not a long log laid out at once.
const TEXT_LIMIT = 256 * 1024

type Loaded =
  | { state: "loading" }
  | { state: "failed" }
  | { state: "image"; blob: Blob; src: string; width: number; height: number }
  | { state: "pdf"; data: ArrayBuffer }
  | { state: "text"; text: string; truncated: boolean }

/** The file, fetched once: what is shown is made here, never by the runtime's own answer, which serves anything but a
 * picture to download. A PDF's pages are drawn here (pdf-pages.tsx); words are only ever text. */
function useLoaded(url: string | null, kind: "image" | "pdf" | "text") {
  const [loaded, setLoaded] = useState<Loaded>({ state: "loading" })
  const [from, setFrom] = useState(url)
  if (from !== url) {
    setFrom(url)
    setLoaded({ state: "loading" })
  }
  useEffect(() => {
    if (url === null) return
    const abort = new AbortController()
    let made: string | null = null
    ;(async () => {
      const response = await fetch(url, { signal: abort.signal })
      if (!response.ok) throw new Error(String(response.status))
      const blob = await response.blob()
      if (kind === "text") {
        const text = decoded(await blob.slice(0, TEXT_LIMIT).arrayBuffer())
        return {
          state: "text",
          text,
          truncated: blob.size > TEXT_LIMIT,
        } as const
      }
      if (kind === "pdf")
        return { state: "pdf", data: await blob.arrayBuffer() } as const
      // Its size as drawn upright, which the marks are measured in, as the file made from them is.
      const bitmap = await createImageBitmap(blob)
      const { width, height } = bitmap
      bitmap.close()
      made = URL.createObjectURL(blob)
      return { state: "image", blob, src: made, width, height } as const
    })().then(
      (each) => !abort.signal.aborted && setLoaded(each),
      () => !abort.signal.aborted && setLoaded({ state: "failed" })
    )
    return () => {
      abort.abort()
      if (made) URL.revokeObjectURL(made)
    }
  }, [url, kind])
  return loaded
}

/** An attachment's tab: the file under the tab row, its bar under it, level with the composer's bottom. A picture
 * can be marked up there, and the marked-up copy added to the message being written (or put in place of the tile it
 * came from). */
export function AttachmentView({
  file,
  draft,
  place,
  compact,
}: {
  file: FileTab
  draft: string
  place: PanelPlace
  compact: boolean // marking up, 取消 and the copy's button take the top row; the bar holds the tools
}) {
  const t = useT()
  const { source, markup } = file
  const attachments = useAttachments(draft)
  // A tile's upload, once it has one: a copy put in its place is shown as soon as it is up.
  const tile =
    source.kind === "draft"
      ? attachments.list.find((each) => each.key === source.key)
      : undefined
  const url =
    source.kind === "sent"
      ? screenshotUrl(source.run, source.file)
      : tile?.id
        ? uploadUrl(tile.id)
        : null
  // A message's picture is kept as one of the kinds a model reads (attachments.tsx), and a tile says whether it is a
  // picture; anything else by its name.
  const kind = (
    source.kind === "sent"
      ? /\.(png|jpg|webp)$/.test(source.file)
      : tile?.kind === "image"
  )
    ? "image"
    : (previewOf(source.name) ?? "text")
  const loaded = useLoaded(url, kind)
  // Opened from a picture the conversation shows: its small copy stands in, at its shape, until the file has come.
  const { thumb } = file
  const picture =
    loaded.state === "image"
      ? loaded
      : loaded.state === "loading" && kind === "image" && thumb
        ? { src: null, width: thumb.width, height: thumb.height }
        : null
  const [tool, setTool] = useState<Tool>("pen")
  const [shape, setShape] = useState<Shape>("rect")
  const [color, setColor] = useState<Color>("red")
  const [busy, setBusy] = useState(false)
  // A PDF's size, and the share of its printed size that fits the panel.
  const [zoom, setZoomShown] = useState<Zoom>(() => zoomOf(file.key))
  const setZoom = (next: Zoom) => {
    keepZoom(file.key, next)
    setZoomShown(next)
  }
  const [fit, setFit] = useState(100)
  const editing = markup !== null
  // Words still being written, put down first: a tap on a button doesn't always take the focus from their field.
  const stage = useRef<{ flush: () => void }>(null)
  const flush = () => stage.current?.flush()
  const now = () => {
    flush()
    return (
      getPanel().files.find((each) => each.key === file.key)?.markup ?? null
    )
  }
  const replacing = source.kind === "draft" && tile !== undefined
  // The name the model receives the picture by, under which the draft holds its comments.
  const named = replacing ? tile.name : source.name

  // `send`: the message goes too, as the composer has it then.
  async function commit(send: boolean) {
    const markup = now()
    if (loaded.state !== "image" || !markup || busy) return
    // Drawn on, it goes as a copy with the strokes and shapes in it; with comments only, as it is: a tile stays as
    // it was, a message's picture goes again. The comments go as words in the message, as ChatGPT sends them.
    const strokes = drawnOf(markup.marks)
    const resend = source.kind === "sent"
    const adds = strokes.length > 0 || resend
    if (place.blocked) return showError(place.blocked)
    if (adds && !replacing && attachments.list.length >= MAX_FILES)
      return showError(t.composer.attachments.many(MAX_FILES))
    setBusy(true)
    try {
      const copy = strokes.length
        ? await flattened(loaded.blob, strokes, source.name)
        : resend
          ? new File([loaded.blob], source.name, { type: loaded.blob.type })
          : null
      setMarkup(file.key, null)
      // As the composer names it, numbered where another tile has its name.
      const added = !copy
        ? undefined
        : replacing
          ? attachments.replace(source.key, copy)
          : attachments.add([copy])[0]
      const name = added?.name ?? named
      if (resend && added) keepCopy(file.key, added.key)
      if (replacing && added) renameTab(file.key, added.name)
      // Its comments, those it began with changed or not, in place of those under its name, which follows the copy.
      editDraft(draft, (text) =>
        withComments(
          replacing ? relabelled(text, named, name) : text,
          markup.marks,
          name
        )
      )
      place.onAdded(send)
    } catch {
      showError(t.markup.failed)
    } finally {
      setBusy(false)
    }
  }

  const cancel = () => {
    flush()
    leaveMarkup(file.key)
  }
  // Esc does what 取消 does, Return what the copy's button does, and ⌘/Ctrl+Return sends the message with it too. From
  // within the panel only, and not from a field; plain Return on a button presses that button. The panel's menus and
  // dialogs are drawn outside it. Heard on the document, before the window's keys that answer a held step. A held
  // key's repeats do nothing: they may come from a press meant for a comment's field, gone once it is kept.
  const root = useRef<HTMLDivElement>(null)
  const keys = useEffectEvent((event: KeyboardEvent) => {
    if (
      event.shiftKey ||
      event.altKey ||
      event.defaultPrevented ||
      isComposing(event)
    )
      return
    const target = event.target as Element
    if (target !== document.body && !root.current!.contains(target)) return
    if (target.closest("input, textarea, select, [contenteditable]")) return
    const send = MAC ? event.metaKey : event.ctrlKey
    const otherModifier = MAC ? event.ctrlKey : event.metaKey
    if (event.key === "Escape" && !event.metaKey && !event.ctrlKey) {
      event.preventDefault()
      if (!event.repeat) cancel()
    } else if (
      event.key === "Enter" &&
      !otherModifier &&
      (send || !target.closest("button, a"))
    ) {
      event.preventDefault()
      if (!event.repeat) void commit(send)
    }
  })
  useEffect(() => {
    if (!editing) return
    document.addEventListener("keydown", keys)
    return () => document.removeEventListener("keydown", keys)
  }, [editing])

  const label = source.kind === "draft" ? t.markup.done : t.markup.add
  const ends = (
    <>
      <Tooltip>
        <TooltipTrigger
          render={
            <Button
              variant="ghost"
              className={TEXT_BUTTON}
              aria-keyshortcuts="Escape"
              onClick={cancel}
            />
          }
        >
          {t.common.cancel}
        </TooltipTrigger>
        <TooltipContent>
          {t.common.cancel}
          <Kbd>Esc</Kbd>
        </TooltipContent>
      </Tooltip>
      <Tooltip>
        <TooltipTrigger
          render={
            <Button
              className="rounded-full"
              disabled={busy}
              aria-keyshortcuts={`Enter ${MAC ? "Meta" : "Control"}+Enter`}
              onClick={() => commit(false)}
            />
          }
        >
          {label}
        </TooltipTrigger>
        <TooltipContent className="grid grid-cols-[auto_auto] gap-x-3 gap-y-1">
          {label}
          <Kbd className="justify-self-end">{ENTER_KEYCAP}</Kbd>
          {t.composer.send}
          <Kbd className="justify-self-end">
            {MOD_KEYCAP} {ENTER_KEYCAP}
          </Kbd>
        </TooltipContent>
      </Tooltip>
    </>
  )
  const corner = place.corner
  return (
    <div
      ref={root}
      className="absolute inset-0 flex flex-col bg-background pt-12 md:pt-13"
    >
      {/* Always there, but on a phone while marking up, where its top row holds 取消 and the copy's button. */}
      {!(place.phone && editing) && (
        <CornerButton
          {...("onExpand" in corner
            ? {
                label: corner.expanded ? t.tabs.shrink : t.tabs.expand,
                pressed: corner.expanded,
                beside: true,
                onClick: corner.onExpand,
              }
            : { label: t.tabs.hide, beside: false, onClick: corner.onClose })}
        />
      )}
      {/* Marking up where the bar has no room for them: leaving and adding take the top row, the tabs make way. */}
      {compact && editing && (
        <div
          className={cn(
            // Its room between them lets taps through, to the corner button under it.
            "pointer-events-none absolute inset-x-0 top-0 z-10 flex h-12 items-center justify-between px-2.5 *:pointer-events-auto md:h-13",
            // Clear of the corner button and the page's toggle beside it, 4 from it as they are from each other.
            !place.phone && "md:pr-22 md:pl-2"
          )}
        >
          {ends}
        </div>
      )}
      <div className="relative min-h-0 flex-1 animate-in px-4 py-2 duration-200 ease-(--ease-out) fade-in zoom-in-[0.98] motion-reduce:zoom-in-100">
        {picture ? (
          <MarkupStage
            ref={stage}
            src={picture.src}
            under={thumb?.src}
            alt={source.name}
            width={picture.width}
            height={picture.height}
            markup={markup}
            onMarkup={(next) => setMarkup(file.key, next)}
            onWriting={(writing) => setWriting(file.key, writing)}
            tool={tool}
            color={color}
          />
        ) : loaded.state === "loading" ? (
          <div className="flex size-full items-center justify-center">
            <Spinner className="size-5 text-muted-foreground" />
          </div>
        ) : loaded.state === "failed" ? (
          <p className="flex size-full items-center justify-center text-sm text-muted-foreground">
            {t.tabs.loadFailed}
          </p>
        ) : loaded.state === "pdf" ? (
          <PdfPages
            data={loaded.data}
            name={source.name}
            memory={file.key}
            zoom={zoom}
            onFit={setFit}
          />
        ) : loaded.state === "text" ? (
          <div className="size-full overflow-auto rounded-xl border bg-muted/40">
            <pre className="p-4 font-mono text-xs leading-5 break-words whitespace-pre-wrap">
              {loaded.text}
            </pre>
            {loaded.truncated && (
              <p className="px-4 pb-4 text-xs text-muted-foreground">
                {t.tabs.truncated}
              </p>
            )}
          </div>
        ) : null}
      </div>
      <div className="flex shrink-0 justify-center px-4 pt-2 pb-4">
        <MarkupToolbar
          editing={editing}
          markable={loaded.state === "image"}
          download={{ href: url ?? undefined, name: source.name }}
          onStart={() => {
            // A message's picture already marked up into the composer: its tile is marked up instead, in its own tab,
            // so what was drawn and written there stays.
            const copied =
              source.kind === "sent"
                ? attachments.list.find((each) => each.key === copyOf(file.key))
                : undefined
            const tab: Source | null = copied
              ? { kind: "draft", draft, key: copied.key, name: copied.name }
              : null
            if (tab) openFile(tab)
            // With the comments already written to it, to change them or add more; a message's picture has none yet.
            setMarkup(tab ? keyOf(tab) : file.key, {
              ...EMPTY,
              marks:
                copied || source.kind === "draft"
                  ? commentsIn(draftOf(draft), copied?.name ?? named)
                  : [],
            })
            setTool("pen")
          }}
          tool={tool}
          onTool={(next) => {
            flush()
            setTool(next)
            if (next === "rect" || next === "ellipse" || next === "arrow")
              setShape(next)
          }}
          shape={shape}
          color={color}
          onColor={setColor}
          canUndo={(markup?.past.length ?? 0) > 0}
          canRedo={(markup?.future.length ?? 0) > 0}
          onUndo={() => {
            const markup = now()
            if (markup) setMarkup(file.key, undone(markup))
          }}
          onRedo={() => {
            const markup = now()
            if (markup) setMarkup(file.key, redone(markup))
          }}
          ends={compact ? null : ends}
          zoom={
            loaded.state === "pdf"
              ? { value: zoom, fit, onChange: setZoom }
              : undefined
          }
        />
      </div>
    </div>
  )
}
