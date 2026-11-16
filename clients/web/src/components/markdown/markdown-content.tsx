import { useState, type ComponentProps, type ReactNode } from "react"
import { cn } from "cn"
import { cjk } from "@streamdown/cjk"
import { math } from "@streamdown/math"
import remarkBreaks from "remark-breaks"
import {
  defaultComponents,
  defaultRehypePlugins,
  defaultRemarkPlugins,
  Streamdown,
  useIsCodeFenceIncomplete,
  type Components,
  type ExtraProps,
} from "streamdown"

import { CopyButton } from "@/components/copy-button"
import { ScreenshotViewer } from "@/components/screenshot-viewer"
import { useT } from "@/lib/i18n"
import { dollarMath } from "@/lib/math"

// A code block's label row (h-9), each line of its code (leading-5) and its foot (pb-3), in px.
const blockHeight = (code: string) => 36 + 20 * code.split("\n").length + 12

// The start of a fence still coming at the end of a streaming reply: backticks or tildes opening a line and, after
// three or more, what follows them on it, the block's language. Held back until its line ends, it opens as a block
// naming its language rather than as a stray backtick, then a plaintext block, then one renamed letter by letter.
const OPENING_FENCE = /(^|\n)(`{1,2}|~{1,2}|(`{3,}|~{3,})[^\n`]*)$/
// A table's delimiter row, under its header: cells of dashes, each perhaps with a colon either side.
const DELIMITER = /^\|?[ \t]*:?-+:?[ \t]*(\|[ \t]*:?-+:?[ \t]*)*\|?[ \t]*$/

/** A streaming reply's text with a table at its end drawn only as a table, a whole row at a time: the row still coming
 * held back (with a line break just after a row, which would draw the table as words for a moment), and the table
 * with it until its header and delimiter rows are whole. Otherwise a paragraph of pipes turns into a shorter table. */
function wholeRows(text: string): string {
  const lines = text.split("\n")
  if (lines.at(-1)?.startsWith("|")) lines.pop()
  else if (lines.at(-1) === "" && lines.at(-2)?.startsWith("|")) lines.pop()
  let start = lines.length
  while (start > 0 && lines[start - 1].startsWith("|")) start--
  const table = lines.slice(start)
  if (table.length && !(table.length >= 2 && DELIMITER.test(table[1])))
    lines.length = start
  return lines.join("\n")
}

/** A streaming reply's text without what would draw as something else until it is whole: a fence or a table row
 * still coming. */
const unfinished = (text: string) =>
  wholeRows(text.replace(OPENING_FENCE, "$1"))

/** Fenced code with language and copy controls. Hide an incomplete closing fence
 * while streaming so it does not flash as a final code line. Out of view, it is not
 * drawn: each block scrolls sideways, and every such scroller in the conversation
 * made each frame of a streaming reply costlier to put on screen. It keeps the height
 * it last had, or its lines' until it has been seen: a block drawn anew (as a reply
 * that has streamed is drawn again whole) holds its place from its first frame. */
function CodeBlock({ code, language }: { code: string; language: string }) {
  const writing = useIsCodeFenceIncomplete()
  const shown = writing ? code.replace(/(^|\n)(`+|~+)$/, "") : code
  return (
    <div
      className="overflow-hidden rounded-xl bg-muted [content-visibility:auto]"
      style={{ containIntrinsicSize: `auto ${blockHeight(shown)}px` }}
    >
      {/* A block that names no language is plaintext, in every language. */}
      <div className="flex h-9 items-center gap-2 pr-1.5 pl-4 font-mono text-xs text-muted-foreground">
        <span className="min-w-0 flex-1 truncate">
          {language || "plaintext"}
        </span>
        <CopyButton text={code} disabled={writing} />
      </div>
      <pre className="overflow-x-auto px-4 pb-3 font-mono text-sm leading-5">
        {/* A line's room before its first character, so the block does not grow when it comes. */}
        <code>{shown || " "}</code>
      </pre>
    </div>
  )
}

/** Streamdown marks fenced blocks with data-block; leave inline code styling unchanged. */
function Code(props: ComponentProps<"code"> & ExtraProps) {
  if (!("data-block" in props)) return <defaultComponents.code {...props} />
  const { className, children } = props
  return (
    <CodeBlock
      code={typeof children === "string" ? children.replace(/\n$/, "") : ""}
      language={/language-(\S+)/.exec(className ?? "")?.[1] ?? ""}
    />
  )
}

/** Scrollable table with row separators; styles live in index.css. */
function Table({ children }: ComponentProps<"table"> & ExtraProps) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse">{children}</table>
    </div>
  )
}

/** A file in a conversation's workspace, where the coding agent reports what it made: its address through the
 * authenticated API, and its name. */
function workspaceFile(href: string | undefined) {
  const file = /^\/workspace\/([A-Za-z0-9][A-Za-z0-9._-]{0,99})\/(.+)$/.exec(
    href ?? ""
  )
  return file
    ? {
        url: `/api/conversations/${file[1]}/files/${file[2]}`,
        name: file[2].split("/").at(-1)!,
      }
    : null
}
// A picture the page shows where it is linked; any other file only downloads.
const PICTURE = /\.(png|jpe?g|webp)$/i

/** A picture the coding agent made, where the reply links it: up to 320 tall, full size in the viewer on a click, the
 * link to download it under it. */
function Picture({
  url,
  name,
  children,
}: {
  url: string
  name: string
  children: ReactNode
}) {
  const t = useT()
  const [open, setOpen] = useState(false)
  return (
    <span className="my-1 flex flex-col items-start gap-1.5">
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label={t.composer.attachments.open(name)}
      >
        <img
          src={url}
          alt={name}
          loading="lazy"
          decoding="async"
          className="max-h-80 max-w-full rounded-2xl border object-contain sm:max-w-sm"
        />
      </button>
      <defaultComponents.a href={url} download target="_self">
        {children}
      </defaultComponents.a>
      <ScreenshotViewer
        shots={[{ name, label: name, src: url }]}
        index={open ? 0 : null}
        onIndexChange={(index) => setOpen(index !== null)}
      />
    </span>
  )
}

/** An image is shown as its alt text: loading it would send its address, which text the agent read on a page could
 * have filled with what it saw, to any site. One the coding agent made, in its workspace, is shown. */
function Image({ src, alt }: ComponentProps<"img"> & ExtraProps) {
  const file = workspaceFile(typeof src === "string" ? src : undefined)
  if (file && PICTURE.test(file.name))
    return (
      <Picture url={file.url} name={file.name}>
        {alt || file.name}
      </Picture>
    )
  return alt ?? null
}

/** The coding agent reports paths in its conversation's workspace. Downloads go through the authenticated API; a
 * picture shows where it is linked. */
function Link({ href, children, ...props }: ComponentProps<"a"> & ExtraProps) {
  const file = workspaceFile(href)
  if (file && PICTURE.test(file.name))
    return (
      <Picture url={file.url} name={file.name}>
        {children}
      </Picture>
    )
  if (file)
    return (
      <defaultComponents.a {...props} href={file.url} download target="_self">
        {children}
      </defaultComponents.a>
    )
  return (
    <defaultComponents.a {...props} href={href}>
      {children}
    </defaultComponents.a>
  )
}

// Streamdown redraws a message only when a setting it is given is another object, so each is made once, here.
const COMPONENTS: Components = { code: Code, table: Table, img: Image, a: Link }
// Math is drawn by KaTeX (its stylesheet is index.css's), from $$ only: a single $ is a price (lib/math.ts).
const PLUGINS = { cjk, math }
// A line break the model wrote stays one, as the plain text showed it.
const REMARK = [...Object.values(defaultRemarkPlugins), remarkBreaks]
// Render raw HTML as text so content such as <Enter> is preserved.
const REHYPE = [defaultRehypePlugins.sanitize, defaultRehypePlugins.harden]
const LINKS = { enabled: false }
// Animate by character: word-based splitting would reveal an entire Chinese phrase at once.
const FADE = { sep: "char" } as const

/** Render static or streaming markdown with Streamdown and the app's element styles. */
export function Markdown({
  text,
  streaming = false,
  className,
}: {
  text: string
  streaming?: boolean
  className?: string
}) {
  return (
    <Streamdown
      mode={streaming ? "streaming" : "static"}
      isAnimating={streaming}
      animated={FADE}
      className={cn("markdown space-y-2.5", className)}
      components={COMPONENTS}
      plugins={PLUGINS}
      remarkPlugins={REMARK}
      rehypePlugins={REHYPE}
      controls={false}
      linkSafety={LINKS}
    >
      {dollarMath(
        (streaming ? unfinished(text) : text).replaceAll(
          "](sandbox:/workspace/",
          "](/workspace/"
        ),
        streaming
      )}
    </Streamdown>
  )
}
