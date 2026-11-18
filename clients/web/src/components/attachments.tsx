import { useState, type ReactNode } from "react"
import { createPortal } from "react-dom"
import { cn } from "cn"

import {
  ChevronDownIcon,
  CloseIcon,
  DocumentIcon,
  RetryIcon,
  SpinnerIcon,
  WarningIcon,
} from "@/components/icons"
import { useIsMobile } from "@/hooks/use-mobile"
import { screenshotUrl } from "@/lib/api"
import {
  kindOf,
  previewOf,
  type Attachment,
  type Shown,
} from "@/lib/attachments"
import { useT } from "@/lib/i18n"
import { openFile, type Thumb } from "@/lib/side-panel"

/** The small copy a clicked picture already shows, for its tab to show until the file has come. */
function thumbOf(element: Element): Thumb | undefined {
  const img = element.querySelector("img")
  if (!img?.naturalWidth) return undefined
  return {
    src: img.currentSrc,
    width: img.naturalWidth,
    height: img.naturalHeight,
  }
}

// An image's tile and a file's card are 56 tall, rounded 20: 8 inside the composer's 28 corner.
const TILE = "h-14 rounded-2xl border"

function FileCard({
  name,
  mark,
  className,
}: {
  name: string
  mark?: ReactNode
  className?: string
}) {
  const t = useT()
  return (
    <span
      className={cn(
        TILE,
        "flex w-52 items-center gap-2.5 pr-3 pl-2",
        className
      )}
    >
      {/* 8 inside the card's 20 corner: rounded 12. */}
      <span className="relative flex size-10 shrink-0 items-center justify-center rounded-lg bg-muted">
        {mark || <DocumentIcon />}
      </span>
      <span className="min-w-0 text-left">
        <span className="block truncate text-sm">{name}</span>
        <span className="block text-xs text-muted-foreground">
          {kindOf(name) || t.composer.attachments.file}
        </span>
      </span>
    </span>
  )
}

// A tile's remove button sits on its top right corner, its middle on the rounded edge (6 in from the corner of a 20
// radius), half over the row's 8 above the tiles. Solid in the ink's color, ringed in the composer's own fill so it
// stands apart from any photo under it. Where something can hover it comes as the pointer comes over the tile or the
// keyboard reaches it; on a touch screen it stays.
const REVEAL =
  "transition-[opacity,scale] duration-200 motion-reduce:transition-none [@media(hover:hover)]:scale-90 [@media(hover:hover)]:opacity-0 group-hover/tile:scale-100 group-hover/tile:opacity-100 group-has-[:focus-visible]/tile:scale-100 group-has-[:focus-visible]/tile:opacity-100"

// A failed tile's warning and its retry, in one place: one grows out of a blur as the other shrinks into one.
const SWAP =
  "col-start-1 row-start-1 transition-[opacity,scale,filter] duration-200 motion-reduce:transition-none"
const AWAY =
  "[@media(hover:hover)]:group-hover/tile:scale-50 [@media(hover:hover)]:group-hover/tile:opacity-0 [@media(hover:hover)]:group-hover/tile:blur-[2px] group-has-[:focus-visible]/tile:scale-50 group-has-[:focus-visible]/tile:opacity-0 group-has-[:focus-visible]/tile:blur-[2px]"
const BACK =
  "[@media(hover:hover)]:group-hover/tile:scale-100 [@media(hover:hover)]:group-hover/tile:opacity-100 [@media(hover:hover)]:group-hover/tile:blur-none group-has-[:focus-visible]/tile:scale-100 group-has-[:focus-visible]/tile:opacity-100 group-has-[:focus-visible]/tile:blur-none"

/** What is attached to the message being written in `draft`, at the top of the composer: each with a button to take
 * it off, a spinner while it uploads, and a warning that turns into a way to try again if it failed. A photo that has
 * uploaded opens in the side panel, to mark up. */
export function AttachmentTiles({
  draft,
  list,
  onRemove,
  onRetry,
}: {
  draft: string
  list: Attachment[]
  onRemove: (key: string) => void
  onRetry: (key: string) => void
}) {
  const t = useT()
  // Taken off, a tile goes once it has shrunk away (its fade ends, attach-tile in index.css); the last ones once their
  // row has closed, since the row eases from the height they give it.
  const [leaving, setLeaving] = useState<string[]>([])
  const closing =
    list.length > 0 && list.every((each) => leaving.includes(each.key))
  const gone = (keys: string[]) => {
    keys.forEach(onRemove)
    setLeaving((all) => all.filter((key) => !keys.includes(key)))
  }
  // One row that scrolls sideways when it outgrows the composer, edge to edge: the tiles start 8 in, and one half out
  // of view runs to the border, cut along the composer's corners. The end has 8 more, so the last tile's X clears the
  // corner.
  return (
    <ul
      data-closing={closing || list.length === 0 || undefined}
      onTransitionEnd={(event) => {
        if (
          event.target === event.currentTarget &&
          event.propertyName === "height"
        )
          gone(leaving)
      }}
      className="flex attach-row [scrollbar-width:none] gap-2 overflow-x-auto rounded-t-[calc(2rem-1px)] pt-2 pr-4 pl-2"
    >
      {list.map((each) => {
        const image = each.kind === "image"
        const failed = each.state === "failed"
        const source = {
          kind: "draft",
          draft,
          key: each.key,
          name: each.name,
        } as const
        // A failed upload's warning, its reason said once in a notice: over the whole photo, in a card's icon. Where
        // something can hover, the pointer or the keyboard on the tile turns it into the way to try again; a tap on a
        // touch screen tries again as it is.
        const retry = failed && (
          <button
            type="button"
            onClick={() => onRetry(each.key)}
            aria-label={t.composer.attachments.retry}
            className={cn(
              "absolute inset-0 grid place-items-center",
              image ? "rounded-2xl bg-background/70" : "rounded-lg"
            )}
          >
            <WarningIcon className={cn(SWAP, "text-destructive", AWAY)} />
            <RetryIcon
              className={cn(SWAP, "scale-50 opacity-0 blur-[2px]", BACK)}
            />
          </button>
        )
        // One that cannot go however often it is tried: its warning only, until it is taken off.
        const warning = each.state === "rejected" && (
          <span
            className={cn(
              "absolute inset-0 flex items-center justify-center",
              image ? "rounded-2xl bg-background/70" : "rounded-lg"
            )}
          >
            <WarningIcon className="text-destructive" />
          </span>
        )
        const spinner = each.state === "uploading" && (
          <SpinnerIcon aria-label={t.composer.attachments.uploading} />
        )
        return (
          <li
            key={each.key}
            data-tile
            data-leaving={leaving.includes(each.key) || undefined}
            onTransitionEnd={(event) => {
              if (
                event.target === event.currentTarget &&
                event.propertyName === "opacity" &&
                leaving.includes(each.key) &&
                !closing
              )
                gone([each.key])
            }}
            className="group/tile attach-tile relative shrink-0"
          >
            {image ? (
              // Until its preview is made, or for a file that turns out to be no image: the plain square.
              <span
                className={cn(
                  TILE,
                  "relative block w-14 overflow-hidden bg-muted"
                )}
              >
                {each.preview && (
                  <img
                    src={each.preview}
                    alt=""
                    className="size-full object-cover"
                  />
                )}
                {each.id && (
                  <button
                    type="button"
                    onClick={(event) =>
                      openFile(
                        source,
                        thumbOf(event.currentTarget.parentElement!)
                      )
                    }
                    aria-label={t.composer.attachments.open(each.name)}
                    className="absolute inset-0 rounded-2xl"
                  />
                )}
                {spinner && (
                  <span className="absolute inset-0 flex items-center justify-center bg-background/60">
                    {spinner}
                  </span>
                )}
                {retry}
                {warning}
              </span>
            ) : each.state === "ready" && previewOf(each.name) ? (
              // Once it has uploaded, one that can be shown opens in the side panel, as a message's does.
              <button
                type="button"
                onClick={() => openFile(source)}
                aria-label={t.composer.attachments.open(each.name)}
                className="block text-left"
              >
                <FileCard
                  name={each.name}
                  className="transition-colors hover:bg-muted [@media(hover:none)]:pr-5"
                />
              </button>
            ) : (
              // On a touch screen the button stays, so the name stops short of it.
              <FileCard
                name={each.name}
                mark={spinner || retry || warning}
                className="[@media(hover:none)]:pr-5"
              />
            )}
            {/* None while it uploads. */}
            {each.state !== "uploading" && (
              <button
                type="button"
                onClick={() => setLeaving((keys) => [...keys, each.key])}
                aria-label={t.composer.attachments.remove(each.name)}
                className={cn(
                  "absolute -top-1 -right-1 flex size-5 items-center justify-center rounded-full bg-foreground text-background ring-2 ring-background dark:ring-[color-mix(in_oklch,var(--muted)_40%,var(--background))]",
                  REVEAL
                )}
              >
                <CloseIcon className="size-3" />
              </button>
            )}
          </li>
        )
      })}
    </ul>
  )
}

// The cards in the drop overlay, drawn in the page's ink so they suit every theme: a photo (a sky, the sun and two
// hills) and a page of a document (its corner folded down, a heading and lines of text, whatever its kind). They lift
// off the page a little.
const DROP_CARD = "drop-card absolute"

function DropPhoto() {
  return (
    <span
      className={cn(
        DROP_CARD,
        "top-4 left-0 h-14 w-16 -rotate-10 overflow-hidden rounded-2xl border bg-muted shadow-[0_6px_20px_rgb(0_0_0/0.08)] [--from:1.5rem]"
      )}
    >
      <svg viewBox="0 0 64 56" className="size-full" aria-hidden>
        <circle cx="45" cy="17" r="6" className="fill-foreground/20" />
        <path
          d="M-4 56V41c8-8 18-13 28-7s16 3 24-3 14-5 20 0V56Z"
          className="fill-foreground/10"
        />
        <path
          d="M-4 56V48c11-11 24-14 37-5 8 6 18 3 35-2V56Z"
          className="fill-foreground/20"
        />
      </svg>
    </span>
  )
}

function DropDocument() {
  return (
    <span
      className={cn(
        DROP_CARD,
        "top-0 right-0 h-18 w-14 rotate-8 drop-shadow-[0_6px_10px_rgb(0_0_0/0.08)] [--from:-1.5rem]"
      )}
    >
      <svg
        viewBox="0 0 56 72"
        className="size-full overflow-visible"
        aria-hidden
      >
        <path
          d="M12 .5h27.5l16 16V60A11.5 11.5 0 0 1 44 71.5H12A11.5 11.5 0 0 1 .5 60V12A11.5 11.5 0 0 1 12 .5Z"
          className="fill-background stroke-border"
        />
        <path
          d="M39.5.5V10a6.5 6.5 0 0 0 6.5 6.5h9.5Z"
          className="fill-muted stroke-border"
          strokeLinejoin="round"
        />
        <rect
          x="10"
          y="14"
          width="20"
          height="4"
          rx="2"
          className="fill-foreground/25"
        />
        {[28, 36, 44, 52].map((y, index) => (
          <rect
            key={y}
            x="10"
            y={y}
            width={index === 3 ? 22 : 36}
            height="3"
            rx="1.5"
            className="fill-foreground/15"
          />
        ))}
      </svg>
    </span>
  )
}

/** Over the whole page while files are dragged over it: let go anywhere and they are attached. A photo and a
 * document fan out from one place (drop-card in index.css). */
export function DropOverlay() {
  const t = useT()
  return createPortal(
    <div className="pointer-events-none fixed inset-0 z-50 flex flex-col items-center justify-center gap-1 bg-background/90 backdrop-blur-sm transition-opacity duration-150 motion-reduce:transition-none starting:opacity-0">
      <div className="relative mb-5 h-24 w-28">
        <span className="absolute inset-0 drop-bob">
          <DropPhoto />
        </span>
        <span className="absolute inset-0 drop-bob [animation-delay:-0.8s]">
          <DropDocument />
        </span>
      </div>
      <span className="text-base font-medium">
        {t.composer.attachments.drop}
      </span>
      <span className="text-sm text-muted-foreground">
        {t.composer.attachments.dropHint}
      </span>
    </div>,
    document.body
  )
}

/** What the user attached to a message, over its bubble: images, PDFs and plain text open in the side panel, other
 * files download. Each is marked with its place in the message's list, for its move from the composer's tile when
 * sent from here (message-send.ts). */
export function MessageAttachments({
  run,
  attachments,
}: {
  run: string
  attachments: Shown[]
}) {
  const t = useT()
  const [open, setOpen] = useState(false)
  const phone = useIsMobile()
  // A photo is kept under one of these; any other file is a card to download. One just sent has its preview instead.
  const photo = (each: Shown) =>
    each.file ? /\.(png|jpg|webp)$/.test(each.file) : each.preview !== undefined
  const images = attachments.filter(photo)
  const files = attachments.filter((each) => !photo(each))
  // Four make a square; otherwise rows of up to three.
  const columns = images.length === 4 ? 2 : Math.min(images.length, 3)
  const cards = Math.min(files.length, 2)
  // On a phone they fold to their first row, the rest one tap away.
  const folded = phone && !open
  const shownImages = folded ? images.slice(0, columns) : images
  const shownFiles = folded ? files.slice(0, images.length ? 0 : 1) : files
  const more = attachments.length - shownImages.length - shownFiles.length
  // Images first, up to 128 each, narrower where the message is (a phone); then the files, two cards to a row where
  // they fit, one on a phone. Each group fills its rows from the right, as the message is.
  return (
    <div className="mb-1 flex max-w-[85%] flex-col items-end gap-2">
      {shownImages.length > 0 && (
        <div
          className="flex flex-wrap justify-end gap-2"
          style={{
            width: `min(100%, ${columns * 8}rem + ${columns - 1} * 0.5rem)`,
          }}
        >
          {shownImages.map((each, index) => (
            // Keyed by place, so the preview of one just sent stays up while the kept file loads in its place.
            <button
              key={index}
              type="button"
              disabled={!each.file}
              onClick={(event) =>
                openFile(
                  { kind: "sent", run, file: each.file, name: each.name },
                  thumbOf(event.currentTarget)
                )
              }
              aria-label={t.composer.attachments.open(each.name)}
              style={{
                width: `calc((100% - ${columns - 1} * 0.5rem) / ${columns})`,
              }}
            >
              {/* The 192 thumbnail for a tile up to 128 wide, loaded once it scrolls near. */}
              <img
                data-sent-index={attachments.indexOf(each)}
                src={
                  each.file
                    ? screenshotUrl(run, each.file, 192)
                    : (each.preview ?? undefined)
                }
                alt={each.name}
                loading="lazy"
                decoding="async"
                className="aspect-square w-full rounded-2xl border bg-muted object-cover data-sending:relative data-sending:z-10"
              />
            </button>
          ))}
        </div>
      )}
      {shownFiles.length > 0 && (
        <div
          className="flex flex-wrap justify-end gap-2"
          style={{
            width: `min(100%, ${cards * 13}rem + ${cards - 1} * 0.5rem)`,
          }}
        >
          {shownFiles.map((each, index) => {
            const card = (
              <FileCard
                name={each.name}
                className="transition-colors hover:bg-muted"
              />
            )
            const place = {
              "data-sent-index": attachments.indexOf(each),
              className: "data-sending:relative data-sending:z-10",
            }
            // One that can be shown opens in the side panel; any other downloads, as one just sent waits for its file.
            return each.file && previewOf(each.name) ? (
              <button
                key={index}
                type="button"
                {...place}
                onClick={() =>
                  openFile({
                    kind: "sent",
                    run,
                    file: each.file,
                    name: each.name,
                  })
                }
                aria-label={t.composer.attachments.open(each.name)}
                className={cn(place.className, "text-left")}
              >
                {card}
              </button>
            ) : (
              <a
                key={index}
                {...place}
                href={each.file ? screenshotUrl(run, each.file) : undefined}
                download={each.name}
              >
                {card}
              </a>
            )
          })}
        </div>
      )}
      {phone && (more > 0 || open) && (
        <button
          type="button"
          onClick={() => setOpen(!open)}
          aria-expanded={open}
          className="flex items-center gap-1 text-sm text-muted-foreground"
        >
          {open
            ? t.composer.attachments.fold
            : t.composer.attachments.more(more)}
          <ChevronDownIcon className={cn("size-3.5", open && "rotate-180")} />
        </button>
      )}
    </div>
  )
}
