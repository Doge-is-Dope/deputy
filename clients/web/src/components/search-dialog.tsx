import {
  useEffect,
  useRef,
  useState,
  type ComponentProps,
  type KeyboardEvent,
} from "react"

import { ComposeIcon } from "@/components/icons"
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog"
import { useNow } from "@/hooks/use-now"
import { useSearch } from "@/hooks/use-search"
import { nameOf, type Conversation } from "@/lib/conversations"
import { timeAgo } from "@/lib/format"
import { useT } from "@/lib/i18n"
import { isComposing } from "@/lib/keys"
import { openRun, runHref } from "@/lib/route"
import { found, marked, type Found } from "@/lib/search"
import { cn } from "cn"

// With no query, the latest 50; the page of every conversation (#/chats) lists the rest.
const RECENT = 50

/** ⌘K search, as ChatGPT's "Search chats": with no query 新增 and the latest conversations; with one, those it names
 * first, then those whose words hold it, with a snippet. Arrows move, Enter opens. */
export function SearchDialog({
  open,
  onOpenChange,
  conversations,
  onNew,
  onOpen,
  finalFocus,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  conversations: Conversation[]
  onNew: () => void
  onOpen: () => void
  finalFocus?: ComponentProps<typeof DialogContent>["finalFocus"]
}) {
  const t = useT()
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {/* One height whatever it finds, so it does not jump as the list changes; the whole screen on a phone. */}
      <DialogContent
        finalFocus={finalFocus}
        className="flex h-[min(30rem,calc(100dvh-2rem))] flex-col gap-0 overflow-hidden p-0 max-sm:h-dvh max-sm:max-w-full max-sm:rounded-none sm:max-w-2xl"
      >
        <DialogTitle className="sr-only">{t.chats.search}</DialogTitle>
        <SearchBody
          conversations={conversations}
          onNew={() => {
            onOpenChange(false)
            onNew()
          }}
          onOpen={() => {
            onOpenChange(false)
            onOpen()
          }}
        />
      </DialogContent>
    </Dialog>
  )
}

/** Mounted with each opening, so it opens empty. */
function SearchBody({
  conversations,
  onNew,
  onOpen,
}: {
  conversations: Conversation[]
  onNew: () => void
  onOpen: () => void
}) {
  const t = useT()
  const [query, setQuery] = useState("")
  const [active, setActive] = useState(0)
  const list = useRef<HTMLDivElement>(null)
  const now = useNow(true, 60_000)
  const hits = useSearch(query)
  const searching = query.trim() !== ""
  const shown: (Found | "new")[] = searching
    ? found(conversations, query, hits)
    : [
        "new",
        ...conversations
          .slice(0, RECENT)
          .map((conversation) => ({ conversation })),
      ]
  const current = Math.min(active, shown.length - 1)

  useEffect(() => {
    list.current
      ?.querySelector(`[data-index="${current}"]`)
      ?.scrollIntoView({ block: "nearest" })
  }, [current])

  const choose = (item: Found | "new") => {
    if (item === "new") return onNew()
    openRun(item.conversation.id)
    onOpen()
  }
  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (isComposing(event.nativeEvent)) return
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault()
      const step = event.key === "ArrowDown" ? 1 : -1
      setActive(Math.max(0, Math.min(shown.length - 1, current + step)))
    } else if (event.key === "Enter" && shown[current]) {
      event.preventDefault()
      choose(shown[current])
    }
  }

  return (
    <>
      {/* 16px on a phone, which zooms in on less. */}
      <input
        autoFocus
        value={query}
        placeholder={t.chats.search}
        aria-label={t.chats.search}
        role="combobox"
        aria-expanded
        aria-controls="search-results"
        aria-activedescendant={
          shown[current] ? `search-result-${current}` : undefined
        }
        onChange={(event) => {
          setQuery(event.target.value)
          setActive(0)
        }}
        onKeyDown={onKeyDown}
        className="h-14 shrink-0 border-b bg-transparent pr-14 pl-5 text-base outline-none placeholder:text-muted-foreground md:text-sm"
      />
      {/* scroll-py matches p, so rows the arrow keys scroll to keep their margin. On a phone, the whole screen, the
          results lie on the page's background under the bar, as the settings' pages do. */}
      <div
        ref={list}
        id="search-results"
        role="listbox"
        aria-label={t.chats.search}
        className="min-h-0 flex-1 scroll-py-2 overflow-y-auto p-2 max-sm:bg-background"
      >
        {searching && hits !== null && shown.length === 0 && (
          <p className="mt-8 text-center text-sm text-muted-foreground">
            {t.chats.none}
          </p>
        )}
        {shown.map((item, index) => (
          <a
            key={item === "new" ? "new" : item.conversation.id}
            id={`search-result-${index}`}
            data-index={index}
            role="option"
            aria-selected={index === current}
            href={
              item === "new" ? runHref(null) : runHref(item.conversation.id)
            }
            tabIndex={-1}
            onMouseMove={() => setActive(index)}
            onClick={(event) => {
              event.preventDefault()
              choose(item)
            }}
            className={cn(
              "block rounded-lg px-3 py-2 outline-none",
              index === current && "bg-muted"
            )}
          >
            {item === "new" ? (
              <span className="flex items-center gap-2.5 text-sm">
                <ComposeIcon />
                {t.sidebar.new}
              </span>
            ) : (
              <>
                <span className="flex items-baseline gap-3 text-sm">
                  <span className="min-w-0 flex-1 truncate">
                    <Marked text={nameOf(item.conversation)} query={query} />
                  </span>
                  <span className="shrink-0 text-xs text-muted-foreground">
                    {timeAgo(item.conversation.updated, now)}
                  </span>
                </span>
                {item.snippet && (
                  <span className="mt-0.5 block truncate text-sm text-muted-foreground">
                    <Marked text={item.snippet} query={query} />
                  </span>
                )}
              </>
            )}
          </a>
        ))}
      </div>
    </>
  )
}

/** The text with each match of the query in the text's own color at weight 500, as ChatGPT marks its matches. */
export function Marked({ text, query }: { text: string; query: string }) {
  return marked(text, query).map((piece, n) =>
    piece.match ? (
      <mark key={n} className="bg-transparent font-medium text-foreground">
        {piece.text}
      </mark>
    ) : (
      piece.text
    )
  )
}
