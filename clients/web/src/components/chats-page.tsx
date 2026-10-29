import { useRef, useState } from "react"

import { CloseIcon } from "@/components/icons"
import { Marked } from "@/components/search-dialog"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useNow } from "@/hooks/use-now"
import { useSearch } from "@/hooks/use-search"
import { nameOf, type Conversation } from "@/lib/conversations"
import type { Project } from "@/lib/api"
import { timeAgo } from "@/lib/format"
import { useT } from "@/lib/i18n"
import { runHref } from "@/lib/route"
import { found } from "@/lib/search"

/** Every conversation on one page, as Claude's "All chats": a search over them, as ⌘K's (SearchDialog), then each, most
 * recently active first, with its project and when it was last active. The sidebar lists only the latest few. */
export function ChatsPage({
  conversations,
  projects,
  isNew,
  onOpen,
}: {
  conversations: Conversation[]
  projects: Project[]
  isNew: (conversation: string, ended: number | null) => boolean
  onOpen?: () => void
}) {
  const t = useT()
  const projectName = (id: string | null) =>
    projects.find((project) => project.id === id)?.name
  const [query, setQuery] = useState("")
  const search = useRef<HTMLInputElement>(null)
  const now = useNow(true, 60_000)
  const hits = useSearch(query)
  const shown = found(conversations, query, hits)

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto px-4 pb-10">
      <div className="mx-auto w-full max-w-3xl">
        <h2 className="mt-2 text-2xl tracking-tight">{t.chats.title}</h2>
        {/* The browser's own clear button is hidden for ours: the close cross, muted, while there is text. */}
        <div className="relative mt-5">
          <Input
            ref={search}
            type="search"
            value={query}
            placeholder={t.chats.search}
            aria-label={t.chats.search}
            onChange={(event) => setQuery(event.target.value)}
            className="h-9.5 pr-10 focus-visible:ring-0 [&::-webkit-search-cancel-button]:appearance-none"
          />
          {query && (
            <Button
              variant="ghost"
              size="icon-xs"
              aria-label={t.chats.clear}
              onClick={() => {
                setQuery("")
                search.current?.focus()
              }}
              className="absolute top-1/2 right-1.5 -translate-y-1/2 text-muted-foreground hover:text-foreground"
            >
              <CloseIcon className="size-4" />
            </Button>
          )}
        </div>
        <p className="mt-5 text-xs text-muted-foreground">
          {t.chats.count(shown.length)}
        </p>
        {shown.length === 0 ? (
          hits !== null && (
            <p className="mt-8 text-center text-sm text-muted-foreground">
              {t.chats.none}
            </p>
          )
        ) : (
          // Dense: bordered rows, not cards. Each row reaches 12px past the column, so its text lines up with the heading and its hover keeps the text off its edges.
          <ul className="mt-2 divide-y">
            {shown.map(({ conversation, snippet }) => (
              <li key={conversation.id}>
                <a
                  href={runHref(conversation.id)}
                  onClick={onOpen}
                  className="-mx-3 block rounded-lg px-3 py-3 outline-none hover:bg-muted/50 focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <span className="flex items-baseline gap-3">
                    <span className="min-w-0 flex-1 truncate text-sm">
                      <Marked text={nameOf(conversation)} query={query} />
                      {isNew(conversation.id, conversation.latest.ended) && (
                        <span
                          role="img"
                          aria-label={t.sidebar.unread}
                          className="ml-2 inline-block size-2 rounded-full bg-unread align-middle"
                        />
                      )}
                    </span>
                    {projectName(conversation.project) && (
                      <span className="shrink-0 text-xs text-muted-foreground">
                        {projectName(conversation.project)}
                      </span>
                    )}
                    <span className="shrink-0 text-xs text-muted-foreground">
                      {timeAgo(conversation.updated, now)}
                    </span>
                  </span>
                  {snippet && (
                    <span className="mt-0.5 block truncate text-sm text-muted-foreground">
                      <Marked text={snippet} query={query} />
                    </span>
                  )}
                </a>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
