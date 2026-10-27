import { useEffect, useState, type ComponentProps } from "react"
import { cn } from "cn"

type MarkdownProps = ComponentProps<
  typeof import("./markdown-content").Markdown
>

let Content: typeof import("./markdown-content").Markdown | null = null
let loading: Promise<void> | null = null

// A failed chunk still leaves every message readable, including text arriving from the stream.
function PlainMarkdown({ text, className }: MarkdownProps) {
  return (
    <div className={cn("markdown space-y-2.5 whitespace-pre-wrap", className)}>
      {text}
    </div>
  )
}

/** Begin loading before a reply arrives. Every caller shares the same download. */
export function preloadMarkdown(): Promise<void> {
  return (loading ??= import("./markdown-content").then(
    (module) => {
      Content = module.Markdown
    },
    () => {
      Content = PlainMarkdown
    }
  ))
}

/** Keep the conversation's existing placeholder until its text can be laid out once. */
export function useMarkdownReady() {
  const [ready, setReady] = useState(() => Content !== null)
  useEffect(() => {
    let active = true
    void preloadMarkdown().then(() => {
      if (active) setReady(true)
    })
    return () => {
      active = false
    }
  }, [])
  return ready
}

/** RunView reveals these only after preloading; one drawn before the renderer came (hidden, as the conversation loads)
 * draws again when it comes, as nothing else may draw it again. */
export function Markdown(props: MarkdownProps) {
  return useMarkdownReady() && Content && <Content {...props} />
}
