import { TrashIcon, WarningIcon } from "@/components/icons"
import { notify } from "@/components/notice"
import { restoreMemory } from "@/lib/memory"
import type { Messages } from "@/locales/zh-Hant"

/** Says a change to memory did not go through, at the top of the window as the page's other notices are. */
export function memoryFailed(t: Messages) {
  notify({
    icon: <WarningIcon aria-hidden className="size-5 shrink-0" />,
    text: t.run.memory.failed,
  })
}

/** Says a rule was deleted, with 還原 to put it back, as deleting a conversation is said (App). */
export function memoryDeleted(t: Messages, id: string) {
  notify(
    {
      icon: <TrashIcon aria-hidden className="size-5 shrink-0" />,
      text: t.settings.memoryDeleted,
      action: t.sidebar.restore,
      onAction: () => restoreMemory(id).catch(() => memoryFailed(t)),
    },
    { id: `memory-deleted-${id}` }
  )
}
