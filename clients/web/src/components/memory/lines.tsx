import { useEffect } from "react"
import { toast } from "sonner"

import { MemoryIcon, TrashIcon, WarningIcon } from "@/components/icons"
import { Notice } from "@/components/notice"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog"
import { PlainLine } from "@/components/conversation/steps"
import { useT } from "@/lib/i18n"
import {
  loadMemories,
  openMemory,
  restoreMemory,
  useMemories,
  type Remembered,
} from "@/lib/memory"
import type { Messages } from "@/locales/zh-Hant"

/** Says a change to memory did not go through, at the top of the window as the page's other notices are. */
export function memoryFailed(t: Messages) {
  toast.custom(
    (id) => (
      <Notice
        icon={<WarningIcon aria-hidden className="size-5 shrink-0" />}
        text={t.run.memory.failed}
        onDismiss={() => toast.dismiss(id)}
      />
    ),
    { className: "w-full" }
  )
}

/** Says a rule was deleted, with 還原 to put it back, as deleting a conversation is said (App). */
export function memoryDeleted(t: Messages, id: string) {
  toast.custom(
    (toastId) => (
      <Notice
        icon={<TrashIcon aria-hidden className="size-5 shrink-0" />}
        text={t.settings.memoryDeleted}
        action={t.sidebar.restore}
        onDismiss={() => toast.dismiss(toastId)}
        onAction={() => {
          toast.dismiss(toastId)
          restoreMemory(id).catch(() => memoryFailed(t))
        }}
      />
    ),
    { id: `memory-deleted-${id}`, className: "w-full" }
  )
}

/** Where the main agent remembered, before what it said next, a chip as Claude marks a memory written: saved without
 * asking, so it is in view, but small, as the reply says the same in its words. Hovered, it shows the rules as they
 * are now; it opens the first where it is kept (openMemory), to change or delete. */
export function RememberedChip({
  memories,
  updated,
}: {
  memories: Remembered[]
  updated: boolean
}) {
  const t = useT()
  const { list } = useMemories()
  const words = t.run.memory
  // As they are now, edited or not; as the run saved them until the list is loaded; noted once deleted.
  const rules = memories.map((each) => {
    const now = list?.find((memory) => memory.id === each.id)
    return list && !now ? words.deleted(each.text) : (now?.text ?? each.text)
  })
  const label =
    memories.length > 1
      ? words.rememberedMany(memories.length)
      : updated
        ? words.updated
        : words.remembered
  return (
    <div className="arrive">
      <Tooltip>
        <TooltipTrigger
          render={
            <button
              type="button"
              className="inline-flex h-6 items-center gap-1 rounded-full border border-border pr-2.5 pl-2 text-xs text-muted-foreground outline-none hover:border-foreground/20 hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50"
              onClick={() => openMemory(memories[0].id)}
            />
          }
        >
          <MemoryIcon className="size-3.5 shrink-0" />
          {label}
        </TooltipTrigger>
        <TooltipContent
          side="bottom"
          align="start"
          className="flex-col items-start"
        >
          {rules.map((rule, index) => (
            <span key={memories[index].id}>{rule}</span>
          ))}
        </TooltipContent>
      </Tooltip>
    </div>
  )
}

/** In a task, a rule the user taught that it was handed over with: the rule as it was given, which opens it where it is
 * kept (openMemory). */
export function FollowingLine({ id, text }: { id: string; text: string }) {
  const t = useT()
  return (
    <PlainLine icon={<MemoryIcon />}>
      <button
        type="button"
        className="rounded-sm text-left outline-none hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50"
        onClick={() => openMemory(id)}
      >
        {t.run.memory.following(text)}
      </button>
    </PlainLine>
  )
}

/** The rules a run's tasks were handed over with, from its last reply's details menu: spaced and divided as a
 * project's rules are (MemoryList), each as it is now, which opens it where it is kept (openMemory); one deleted since
 * stays, muted, and opens nothing. Five in view, the rest scrolled to. */
// A list as tall as its first five rules, however many lines each wraps to: up to the sixth's top.
function fitFive(list: HTMLUListElement | null) {
  const sixth = list?.children[5]
  if (list)
    list.style.maxHeight =
      sixth instanceof HTMLElement
        ? `${sixth.offsetTop - list.offsetTop}px`
        : ""
}

export function CitedMemoriesDialog({
  memories,
  open,
  onOpenChange,
}: {
  memories: Remembered[]
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const t = useT()
  const { list } = useMemories()
  useEffect(() => {
    if (open) void loadMemories()
  }, [open])
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[min(36rem,calc(100dvh-2rem))] flex-col pt-3 sm:max-w-lg">
        <DialogTitle className="flex h-8 items-center pr-8">
          {t.run.memory.cited}
        </DialogTitle>
        {/* Scrolled within, a rule's focus ring in the dialog's padding, its words under the title's. */}
        <ul
          ref={(list) => fitFive(list)} // measured again as the rules change
          className="-mx-4 min-h-0 divide-y overflow-y-auto px-4"
        >
          {memories.map((each) => {
            const now = list?.find((memory) => memory.id === each.id)
            return (
              <li key={each.id} className="py-4">
                {list && !now ? (
                  <span className="text-muted-foreground">
                    {t.run.memory.deleted(each.text)}
                  </span>
                ) : (
                  <button
                    type="button"
                    className="w-full rounded-sm text-left underline-offset-2 outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50"
                    onClick={() => {
                      onOpenChange(false)
                      openMemory(each.id)
                    }}
                  >
                    {now?.text ?? each.text}
                  </button>
                )}
              </li>
            )
          })}
        </ul>
      </DialogContent>
    </Dialog>
  )
}
