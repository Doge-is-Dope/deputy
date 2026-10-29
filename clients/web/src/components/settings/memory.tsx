import { useEffect, useId, useRef, useState, type ReactNode } from "react"
import { cn } from "cn"

import { ChevronDownIcon, PencilIcon, TrashIcon } from "@/components/icons"
import { memoryDeleted, memoryFailed } from "@/components/memory/lines"
import { FOLD } from "@/components/sidebar/motion"
import { Button } from "@/components/ui/button"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import { ActionDialog } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { Card, Section } from "@/components/settings/layout"
import { api } from "@/lib/api"
import { setMemory, useChoices, type MemoryChoice } from "@/lib/choices"
import { conversationsOf, nameOf } from "@/lib/conversations"
import { useT } from "@/lib/i18n"
import {
  editMemory,
  forgetMemory,
  forgetPersonalMemories,
  loadMemories,
  useMemories,
  useOpenedSettings,
  type Memory,
  type MemoryEdit,
} from "@/lib/memory"
import { runHref } from "@/lib/route"

const MODES: (keyof MemoryChoice)[] = ["learn", "use"]

/** What the agent learned from the user's interventions: whether it learns and uses them (kept in this browser and sent
 * with each message, lib/choices.ts), and the user's own rules, told everywhere, to edit or delete, or all deleted. A
 * project's own are in its menu (ProjectMemoryDialog). A line in the conversation opens this page at its rule
 * (openMemory). */
export function MemoryPage({ onClose }: { onClose?: () => void }) {
  const t = useT()
  const id = useId()
  const { memory: choice } = useChoices()
  const { list, failed } = useMemories()
  const opened = useOpenedSettings()
  useEffect(() => void loadMemories(), [])
  // A deleted one goes at once; its notice puts it back (memoryDeleted).
  const rows = (list ?? []).filter((memory) => memory.project === null)

  return (
    <>
      <Section>
        <Card>
          {MODES.map((mode) => {
            // Named, then what it does in a muted line under it, as the approval modes are.
            const words = t.settings.memoryModes[mode]
            return (
              <label
                key={mode}
                className="flex min-h-14 cursor-pointer items-center gap-6 py-3"
              >
                <span className="flex-1">
                  <span id={`${id}-${mode}`} className="block">
                    {words.label}
                  </span>
                  <span
                    id={`${id}-${mode}-description`}
                    className="mt-0.5 block text-xs text-muted-foreground"
                  >
                    {words.description}
                  </span>
                </span>
                <Switch
                  checked={choice[mode]}
                  onCheckedChange={(on) => setMemory({ [mode]: on })}
                  aria-labelledby={`${id}-${mode}`}
                  aria-describedby={`${id}-${mode}-description`}
                />
              </label>
            )
          })}
        </Card>

        {list === null ? (
          <p className="px-1 text-sm text-muted-foreground">
            {failed ? t.settings.memoryLoadFailed : t.common.loading}
          </p>
        ) : rows.length === 0 ? (
          <p className="px-1 text-sm text-muted-foreground">
            {t.settings.memoryEmpty}
          </p>
        ) : (
          <>
            <ResetMemory />
            <MemoryList
              memories={rows}
              item={opened.item}
              editing={opened.editing}
              onClose={onClose}
            />
          </>
        )}
      </Section>
    </>
  )
}

/** Rules as a plain list, no card: a line between them, each one line until opened (MemoryRow); `item` opened at,
 * from the conversation. Their source conversations named as the sidebar names them, their ids until known. */
export function MemoryList({
  memories,
  item,
  editing,
  onClose,
}: {
  memories: Memory[]
  item: string | null
  editing: boolean
  onClose?: () => void
}) {
  const [titles, setTitles] = useState(new Map<string, string>())
  useEffect(() => {
    api.runs().then(
      (runs) =>
        setTitles(
          new Map(conversationsOf(runs).map((each) => [each.id, nameOf(each)]))
        ),
      () => {}
    )
  }, [])
  return (
    <div className="divide-y px-1">
      {memories.map((memory) => (
        <MemoryRow
          key={memory.id}
          memory={memory}
          source={titles.get(memory.source.thread)}
          focused={item === memory.id}
          editing={item === memory.id && editing}
          onClose={onClose}
        />
      ))}
    </div>
  )
}

/** 刪除全部記憶, between the switches and the rules while there are any: asked about first, as it cannot be undone.
 * The user's own only: a project's are kept, in its menu. */
function ResetMemory() {
  const t = useT()
  const [asking, setAsking] = useState(false)
  async function reset() {
    try {
      await forgetPersonalMemories()
      setAsking(false)
    } catch {
      memoryFailed(t)
    }
  }
  return (
    <>
      <Button
        variant="ghost"
        className="-ml-[9px] self-start text-destructive hover:bg-destructive/10 hover:text-destructive"
        onClick={() => setAsking(true)}
      >
        {t.settings.resetMemory}
      </Button>
      <ActionDialog
        open={asking}
        onOpenChange={setAsking}
        title={t.settings.resetMemoryAsk}
        action={t.settings.resetMemory}
        onAction={reset}
        destructive
        className="sm:max-w-md"
      >
        <p className="text-sm text-muted-foreground">
          {t.settings.resetMemoryDetail}
        </p>
      </ActionDialog>
    </>
  )
}

/** One rule, the rule alone as ChatGPT's saved memories are; opened, why, when it applies and where it was learned, to
 * edit in place or delete to a line that puts it back. Opened at from the conversation, it is open, scrolls into view
 * and lights up a moment. */
function MemoryRow({
  memory,
  source,
  focused,
  editing: editingFirst,
  onClose,
}: {
  memory: Memory
  source?: string // its conversation's name
  focused: boolean
  editing: boolean
  onClose?: () => void
}) {
  const t = useT()
  const row = useRef<HTMLDivElement>(null)
  const [open, setOpen] = useState(focused)
  const [editing, setEditing] = useState(editingFirst)
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
    try {
      await change()
      return true
    } catch {
      memoryFailed(t)
      return false
    } finally {
      setBusy(false)
    }
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

  const label = "w-16 shrink-0 text-muted-foreground"
  // The card's divider is on the outer box, square; the light, rounded, on the inner one, so the line runs straight.
  return (
    <div ref={row} data-memory={memory.id} className="py-1">
      <div
        className={cn(
          "-mx-3 rounded-lg px-3 py-3 transition-colors duration-500 ease-(--ease-out) motion-reduce:transition-none",
          lit && "bg-muted"
        )}
      >
        {editing ? (
          <form
            className="flex flex-col gap-2 py-1 text-sm"
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
              <label key={key} className="flex items-center gap-3">
                <span className={label}>{name}</span>
                <Input
                  value={draft[key]}
                  autoFocus={key === "text"}
                  onChange={(event) =>
                    setDraft({ ...draft, [key]: event.target.value })
                  }
                />
              </label>
            ))}
            <div className="flex justify-end gap-2 pt-1">
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
          <Collapsible open={open} onOpenChange={setOpen}>
            <CollapsibleTrigger className="flex w-full items-center gap-3 rounded-sm text-left text-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/50">
              {/* One line, cut short, until opened. */}
              <span
                className={cn(
                  "min-w-0 flex-1",
                  open ? "break-words" : "truncate"
                )}
              >
                {memory.text}
              </span>
              <ChevronDownIcon
                className={cn(
                  "size-4 shrink-0 text-muted-foreground transition-[rotate] duration-200 ease-(--ease-out) motion-reduce:transition-none",
                  open && "rotate-180"
                )}
              />
            </CollapsibleTrigger>
            <CollapsibleContent className={FOLD}>
              <div className="flex items-start gap-4 pt-1.5">
                <dl className="flex min-w-0 flex-1 flex-col gap-0.5 text-xs">
                  {(
                    [
                      [t.settings.memoryWhy, memory.why],
                      [t.settings.memoryApplies, memory.applies],
                    ] as const
                  ).map(
                    ([name, value]) =>
                      value && (
                        <div key={name} className="flex gap-3">
                          <dt className={label}>{name}</dt>
                          <dd className="min-w-0 break-words">{value}</dd>
                        </div>
                      )
                  )}
                  <div className="flex gap-3">
                    <dt className={label}>{t.settings.memoryFrom}</dt>
                    <dd className="min-w-0 text-muted-foreground">
                      <a
                        href={runHref(memory.source.thread)}
                        onClick={onClose}
                        className="break-words underline decoration-dotted underline-offset-2 hover:text-foreground"
                      >
                        {source ?? t.settings.memorySource}
                      </a>
                    </dd>
                  </div>
                </dl>
                <div className="flex shrink-0 items-center gap-0.5">
                  <RowButton
                    label={t.settings.editMemory}
                    onClick={() => {
                      setDraft(memory)
                      setEditing(true)
                    }}
                  >
                    <PencilIcon className="size-4" />
                  </RowButton>
                  <RowButton
                    label={t.settings.deleteMemory}
                    disabled={busy}
                    onClick={async () => {
                      if (await act(() => forgetMemory(memory.id)))
                        memoryDeleted(t, memory.id)
                    }}
                  >
                    <TrashIcon className="size-4" />
                  </RowButton>
                </div>
              </div>
            </CollapsibleContent>
          </Collapsible>
        )}
      </div>
    </div>
  )
}

function RowButton({
  label,
  disabled,
  onClick,
  children,
}: {
  label: string
  disabled?: boolean
  onClick: () => void
  children: ReactNode
}) {
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Button
            variant="ghost"
            size="icon-xs"
            aria-label={label}
            className="text-muted-foreground"
            disabled={disabled}
            onClick={onClick}
          />
        }
      >
        {children}
      </TooltipTrigger>
      <TooltipContent side="bottom">{label}</TooltipContent>
    </Tooltip>
  )
}
