import type { ComponentProps } from "react"
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
import { dollarMath } from "@/lib/math"

/** Fenced code with language and copy controls. Hide an incomplete closing fence
 * while streaming so it does not flash as a final code line. Out of view, it is not
 * drawn: each block scrolls sideways, and every such scroller in the conversation
 * made each frame of a streaming reply costlier to put on screen. It keeps the height
 * it last had, or about one line's until it has been seen. */
function CodeBlock({ code, language }: { code: string; language: string }) {
  const writing = useIsCodeFenceIncomplete()
  const shown = writing ? code.replace(/(^|\n)(`+|~+)$/, "") : code
  return (
    <div className="overflow-hidden rounded-xl bg-muted [contain-intrinsic-size:auto_120px] [content-visibility:auto]">
      {/* A block that names no language is plaintext, as ChatGPT's says in every language. */}
      <div className="flex h-9 items-center gap-2 pr-1.5 pl-4 font-mono text-xs text-muted-foreground">
        <span className="min-w-0 flex-1 truncate">
          {language || "plaintext"}
        </span>
        <CopyButton text={code} disabled={writing} />
      </div>
      <pre className="overflow-x-auto px-4 pb-3 font-mono text-sm leading-5">
        <code>{shown}</code>
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

// Streamdown redraws a message only when a setting it is given is another object, so each is made once, here.
const COMPONENTS: Components = { code: Code, table: Table }
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
      {dollarMath(text, streaming)}
    </Streamdown>
  )
}
