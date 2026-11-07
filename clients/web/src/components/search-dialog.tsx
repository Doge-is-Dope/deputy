import {
  useEffect,
  useRef,
  useState,
  type ComponentProps,
  type KeyboardEvent,
  type ReactNode,
} from "react"

import { ChatIcon, ComposeIcon, FolderPlusIcon } from "@/components/icons"
import { PAGES } from "@/components/settings/settings-dialog"
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog"
import { Kbd } from "@/components/ui/kbd"
import { useNow } from "@/hooks/use-now"
import { useSearch } from "@/hooks/use-search"
import type { Conversation, SearchHit } from "@/lib/api"
import { nameOf } from "@/lib/conversations"
import { timeAgo } from "@/lib/format"
import { everyLanguage, useT } from "@/lib/i18n"
import { isComposing, shortcutLabel, type Shortcut } from "@/lib/keys"
import { openSettings } from "@/lib/settings"
import { openRun, runHref } from "@/lib/route"
import { marked } from "@/lib/search"
import type { Messages } from "@/locales/zh-Hant"
import { cn } from "cn"

// Show loaded recents without a query; search all conversations through the API.
const RECENT = 50

/** A command the search offers above the conversations, with its shortcut if it has one. */
type Action = {
  id: string
  icon: ReactNode
  label: (messages: Messages) => string // in each language, which a query finds it by
  shortcut?: Shortcut
  href?: string
  run: () => void
}
/** A command, or a conversation with the snippet around the match in its words, if there. */
type Item = Action | SearchHit

type SearchProps = {
  conversations: Conversation[]
  names: Record<string, string> // each project's name, by its id
  newShortcut: Shortcut
  onNew: () => void
  onNewProject: () => void
  onOpen: () => void // a conversation was opened
}

/** ⌘K search for actions, settings and conversations. Commands match any supported language.
 * Arrow keys select a result; Enter opens it. */
export function SearchDialog({
  open,
  onOpenChange,
  finalFocus,
  ...props
}: SearchProps & {
  open: boolean
  onOpenChange: (open: boolean) => void
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
        <SearchBody {...props} onClose={() => onOpenChange(false)} />
      </DialogContent>
    </Dialog>
  )
}

/** Mounted with each opening, so it opens empty. Choosing a row closes it, then does what the row says. */
function SearchBody({
  conversations,
  names,
  newShortcut,
  onNew,
  onNewProject,
  onOpen,
  onClose,
}: SearchProps & { onClose: () => void }) {
  const t = useT()
  const [query, setQuery] = useState("")
  const [active, setActive] = useState(0)
  const list = useRef<HTMLDivElement>(null)
  const now = useNow(true, 60_000)
  const hits = useSearch(query)
  const words = query.trim().toLocaleLowerCase()
  const searching = words !== ""
  const matchesLabel = (label: (messages: Messages) => string) =>
    everyLanguage(label).some((name) =>
      name.toLocaleLowerCase().includes(words)
    )
  const actions = (
    [
      {
        id: "new",
        icon: <ComposeIcon />,
        label: (m) => m.sidebar.new,
        shortcut: newShortcut,
        href: runHref(null),
        run: onNew,
      },
      {
        id: "new-project",
        icon: <FolderPlusIcon />,
        label: (m) => m.sidebar.newProject,
        run: onNewProject,
      },
    ] satisfies Action[]
  ).filter((action) => matchesLabel(action.label))
  // A match on "Settings" shows every settings page. Otherwise, match individual page names.
  const matchesSettings = matchesLabel((m) => m.settings.title)
  const settings: Action[] = searching
    ? PAGES.map(({ id, icon: Icon }) => ({
        id,
        icon: <Icon className="size-4 shrink-0" />,
        label: (m: Messages) => m.settings[id],
        run: () => openSettings(id),
      })).filter((page) => matchesSettings || matchesLabel(page.label))
    : []
  const found: SearchHit[] = searching
    ? (hits ?? [])
    : conversations
        .slice(0, RECENT)
        .map((conversation) => ({ conversation, snippet: null }))
  // Use one row index across sections for keyboard navigation.
  const sections: { label: string; items: Item[]; first: number }[] = []
  let start = 0
  for (const [label, items] of [
    [t.chats.actions, actions],
    [t.settings.title, settings],
    [t.chats.chats, found],
  ] as const) {
    if (items.length === 0) continue
    sections.push({ label, items, first: start })
    start += items.length
  }
  const shown = sections.flatMap((section) => section.items)
  const current = Math.min(active, shown.length - 1)

  useEffect(() => {
    list.current
      ?.querySelector(`[data-index="${current}"]`)
      ?.scrollIntoView({ block: "nearest" })
  }, [current])

  const choose = (item: Item) => {
    onClose()
    if ("run" in item) return item.run()
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
        {sections.map(({ label, items, first }) => (
          <Section key={label} label={label}>
            {items.map((item, at) => {
              const row = {
                index: first + at,
                current,
                onHover: setActive,
                onChoose: () => choose(item),
              }
              if ("run" in item)
                return (
                  <ActionRow
                    key={item.id}
                    action={item}
                    query={query}
                    {...row}
                  />
                )
              const project = item.conversation.project
              return (
                <Row
                  key={item.conversation.id}
                  href={runHref(item.conversation.id)}
                  {...row}
                >
                  <span className="flex items-center gap-2.5 text-sm">
                    <ChatIcon className="shrink-0" />
                    <span className="min-w-0 flex-1 truncate">
                      <Marked text={nameOf(item.conversation)} query={query} />
                    </span>
                    {project && names[project] && (
                      <span className="max-w-[40%] shrink-0 truncate text-xs text-muted-foreground">
                        {names[project]}
                      </span>
                    )}
                    <span className="shrink-0 text-xs text-muted-foreground">
                      {timeAgo(item.conversation.last, now)}
                    </span>
                  </span>
                  {/* Under the name, past the icon. */}
                  {item.snippet && (
                    <span className="mt-0.5 block truncate pl-7.5 text-sm text-muted-foreground">
                      <Marked text={item.snippet} query={query} />
                    </span>
                  )}
                </Row>
              )
            })}
          </Section>
        ))}
      </div>
    </>
  )
}

/** A labeled group of search results. */
function Section({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div role="group" aria-label={label} className="not-first:mt-2">
      <div className="px-3 pt-2 pb-1 text-xs text-muted-foreground">
        {label}
      </div>
      {children}
    </div>
  )
}

/** A command's row: its icon, its name and its shortcut. */
function ActionRow({
  action,
  query,
  ...row
}: {
  action: Action
  index: number
  current: number
  query: string
  onHover: (index: number) => void
  onChoose: () => void
}) {
  const t = useT()
  return (
    <Row href={action.href} {...row}>
      <span className="flex items-center gap-2.5 text-sm">
        {action.icon}
        <span className="min-w-0 flex-1 truncate">
          <Marked text={action.label(t)} query={query} />
        </span>
        {/* No keyboard to press it on a touch screen. */}
        {action.shortcut && (
          <Kbd className="pointer-coarse:hidden">
            {shortcutLabel(action.shortcut)}
          </Kbd>
        )}
      </span>
    </Row>
  )
}

/** One choice in the list: lit while the arrows or the pointer are on it. */
function Row({
  index,
  current,
  href,
  onHover,
  onChoose,
  children,
}: {
  index: number
  current: number
  href?: string
  onHover: (index: number) => void
  onChoose: () => void
  children: ReactNode
}) {
  return (
    <a
      id={`search-result-${index}`}
      data-index={index}
      role="option"
      aria-selected={index === current}
      href={href}
      tabIndex={-1}
      onMouseMove={() => onHover(index)}
      onClick={(event) => {
        event.preventDefault()
        onChoose()
      }}
      className={cn(
        "block cursor-pointer rounded-lg px-3 py-2 outline-none",
        index === current && "bg-muted"
      )}
    >
      {children}
    </a>
  )
}

/** Highlights matches and dims surrounding text. Leaves unmatched text unchanged,
 * such as a setting found by its name in another language. */
export function Marked({ text, query }: { text: string; query: string }) {
  const pieces = marked(text, query)
  if (!pieces.some((piece) => piece.match)) return text
  return pieces.map((piece, n) =>
    piece.match ? (
      <mark key={n} className="bg-transparent text-foreground">
        {piece.text}
      </mark>
    ) : (
      <span key={n} className="text-muted-foreground/70">
        {piece.text}
      </span>
    )
  )
}
