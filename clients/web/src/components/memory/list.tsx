import { useEffect, useRef, useState } from "react"
import { cn } from "cn"

import {
  EllipsisIcon,
  MemoryIcon,
  PencilIcon,
  TrashIcon,
} from "@/components/icons"
import { memoryDeleted, memoryFailed } from "@/components/memory/notices"
import { FOLD } from "@/components/sidebar/motion"
import { Button } from "@/components/ui/button"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { api, MAX_PAGE } from "@/lib/api"
import { nameOf } from "@/lib/conversations"
import { timeAgo } from "@/lib/format"
import { useT } from "@/lib/i18n"
import {
  editMemory,
  forgetMemory,
  type Memory,
  type MemoryEdit,
} from "@/lib/memory"
import { runHref } from "@/lib/route"

/** The rules, one row each: its rule and, muted under it, when it applies and when it was learned; `item` opened at,
 * from the conversation. Rows only: where they are shown draws the lines between them (a settings card, the project's
 * dialog). Their source conversations named as the sidebar names them, generically
 * until known. */
export function MemoryList({
  memories,
  item,
  onClose,
}: {
  memories: Memory[]
  item: string | null
  onClose?: () => void
}) {
  const [titles, setTitles] = useState(new Map<string, string>())
  useEffect(() => {
    // The latest, a full page: a rule's source older than those goes unnamed.
    api.conversations({ limit: MAX_PAGE }).then(
      (page) =>
        setTitles(new Map(page.items.map((each) => [each.id, nameOf(each)]))),
      () => {}
    )
  }, [])
  return memories.map((memory) => (
    <MemoryRow
      key={memory.id}
      memory={memory}
      source={titles.get(memory.source.thread)}
      focused={item === memory.id}
      onClose={onClose}
    />
  ))
}

/** No rules yet, where they would be: what it holds, and how a rule comes. */
export function MemoryEmpty({ title, hint }: { title: string; hint: string }) {
  return (
    <div className="flex flex-col items-center gap-1.5 py-7 text-center">
      <MemoryIcon className="mb-0.5 size-6 text-muted-foreground" />
      {title}
      <p className="max-w-80 text-xs text-muted-foreground">{hint}</p>
    </div>
  )
}

/** One rule, with when it applies and when it was learned under it; opened, its whole text, why, and the conversation
 * it was learned in. Its menu edits it in place, or deletes it to a notice that puts it back. Opened at from the
 * conversation, it is open, scrolls into view and lights up a moment. */
function MemoryRow({
  memory,
  source,
  focused,
  onClose,
}: {
  memory: Memory
  source?: string // its conversation's name
  focused: boolean
  onClose?: () => void
}) {
  const t = useT()
  const row = useRef<HTMLDivElement>(null)
  const [open, setOpen] = useState(focused)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<Required<MemoryEdit>>(memory)
  const [busy, setBusy] = useState(false)
  const [lit, setLit] = useState(focused)
  useEffect(() => {
    if (!focused) return
    row.current?.scrollIntoView({ block: "center" })
    const timer = window.setTimeout(() => setLit(false), 1500)
    return () => window.clearTimeout(timer)
  }, [focused])

  const act = async (change: () => Promise<void>) => {
    setBusy(true)
    let done = true
    try {
      await change()
    } catch {
      memoryFailed(t)
      done = false
    }
    setBusy(false)
    return done
  }
  const save = async () => {
    const edit: MemoryEdit = {}
    for (const key of ["text", "why", "applies"] as const)
      if (draft[key].trim() && draft[key] !== memory[key])
        edit[key] = draft[key].trim()
    if (
      Object.keys(edit).length &&
      !(await act(() => editMemory(memory.id, edit)))
    )
      return
    setEditing(false)
  }

  const remove = async () => {
    if (await act(() => forgetMemory(memory.id))) memoryDeleted(t, memory.id)
  }

  // The card's divider is on the outer box, square; the light, rounded, on the inner one, so the line runs straight.
  return (
    <div ref={row} data-memory={memory.id} className="py-1">
      <div
        className={cn(
          "-mx-2 rounded-lg px-2 py-2 transition-colors duration-500 ease-(--ease-out) motion-reduce:transition-none",
          lit && "bg-muted"
        )}
      >
        {editing ? (
          // Each field under its name, the buttons after them at the right.
          <form
            className="flex flex-col gap-3 py-1"
            onSubmit={(event) => {
              event.preventDefault()
              void save()
            }}
          >
            {(
              [
                ["text", t.settings.memoryRule],
                ["why", t.settings.memoryWhy],
                ["applies", t.settings.memoryApplies],
              ] as const
            ).map(([key, name]) => (
              <label key={key} className="flex flex-col gap-1">
                <span className="text-xs text-muted-foreground">{name}</span>
                <Input
                  value={draft[key]}
                  autoFocus={key === "text"}
                  onChange={(event) =>
                    setDraft({ ...draft, [key]: event.target.value })
                  }
                />
              </label>
            ))}
            <div className="flex justify-end gap-2">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => {
                  setDraft(memory)
                  setEditing(false)
                }}
              >
                {t.common.cancel}
              </Button>
              <Button
                type="submit"
                size="sm"
                disabled={busy || !draft.text.trim()}
              >
                {t.settings.saveMemory}
              </Button>
            </div>
          </form>
        ) : (
          <div className="flex items-start gap-3">
            <Collapsible
              open={open}
              onOpenChange={setOpen}
              className="min-w-0 flex-1"
            >
              {/* Two lines at most until opened. */}
              <CollapsibleTrigger className="block w-full rounded-sm text-left outline-none focus-visible:ring-3 focus-visible:ring-ring/50">
                <span
                  className={cn("block break-words", !open && "line-clamp-2")}
                >
                  {memory.text}
                </span>
                <span className="mt-0.5 block text-xs text-muted-foreground">
                  {memory.applies} · {timeAgo(memory.updated)}
                </span>
              </CollapsibleTrigger>
              <CollapsibleContent className={FOLD}>
                <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 pt-2 text-xs">
                  {memory.why && (
                    <>
                      <dt className="text-muted-foreground">
                        {t.settings.memoryWhy}
                      </dt>
                      <dd className="break-words">{memory.why}</dd>
                    </>
                  )}
                  <dt className="text-muted-foreground">
                    {t.settings.memoryFrom}
                  </dt>
                  <dd>
                    <a
                      href={runHref(memory.source.thread)}
                      onClick={onClose}
                      className="break-words underline decoration-dotted underline-offset-2 hover:text-muted-foreground"
                    >
                      {source ?? t.settings.memorySource}
                    </a>
                  </dd>
                </dl>
              </CollapsibleContent>
            </Collapsible>
            {/* Its icon ends where the card's words do. */}
            <DropdownMenu>
              <DropdownMenuTrigger
                render={
                  <Button
                    variant="ghost"
                    size="icon-xs"
                    aria-label={t.sidebar.more}
                    className="-mt-1 -mr-1.5 text-muted-foreground"
                  />
                }
              >
                <EllipsisIcon className="size-4" />
              </DropdownMenuTrigger>
              <DropdownMenuContent>
                <DropdownMenuItem
                  onClick={() => {
                    setDraft(memory)
                    setEditing(true)
                  }}
                >
                  <PencilIcon />
                  {t.settings.editMemory}
                </DropdownMenuItem>
                <DropdownMenuItem
                  variant="destructive"
                  disabled={busy}
                  onClick={() => void remove()}
                >
                  <TrashIcon />
                  {t.settings.deleteMemory}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        )}
      </div>
    </div>
  )
}
