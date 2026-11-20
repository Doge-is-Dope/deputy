import { useEffect, useRef, useState } from "react"

import { MemoryEmpty, MemoryList } from "@/components/memory/list"
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog"
import { useT } from "@/lib/i18n"
import {
  loadMemories,
  openProjectMemory,
  useMemories,
  useOpenedProjectMemory,
} from "@/lib/memory"

/** A project's rules, those only its conversations are told, from its menu or a line in the conversation: listed as
 * the settings list the user's own (MemoryList), to edit or delete, under a line saying where they are used. Outside
 * the sidebar, beside the settings. */
export function ProjectMemoryDialog({
  names,
}: {
  names: Record<string, string> // each project's, by id
}) {
  const t = useT()
  const opened = useOpenedProjectMemory()
  const { list, failed } = useMemories()
  // The project kept while the dialog fades out, so its name and rules stay until it is gone.
  const [shown, setShown] = useState(opened.project)
  if (opened.project !== null && opened.project !== shown)
    setShown(opened.project)
  useEffect(() => {
    if (opened.project !== null) void loadMemories()
  }, [opened.project])
  const rows = (list ?? []).filter((memory) => memory.project === shown)
  const close = () => openProjectMemory(null)
  // Opened, the focus is on the window itself, as the settings' is, so the close button shows no ring until Tab.
  const popup = useRef<HTMLDivElement>(null)

  return (
    <Dialog
      open={opened.project !== null}
      onOpenChange={(open) => !open && close()}
    >
      <DialogContent
        ref={popup}
        initialFocus={popup}
        className="flex max-h-[min(36rem,calc(100dvh-2rem))] flex-col gap-0 pt-2.5 sm:max-w-lg"
      >
        <DialogTitle className="flex h-8 items-center pr-8">
          {t.sidebar.projectMemoryTitle(shown ? (names[shown] ?? "") : "")}
        </DialogTitle>
        <p className="mb-3 text-muted-foreground">
          {t.sidebar.projectMemoryNote}
        </p>
        {list === null ? (
          <p className="text-muted-foreground">
            {failed ? t.settings.memoryLoadFailed : t.common.loading}
          </p>
        ) : rows.length === 0 ? (
          <MemoryEmpty
            title={t.sidebar.projectMemoryEmpty}
            hint={t.sidebar.projectMemoryEmptyHint}
          />
        ) : (
          // No card: the rules' words on the dialog's 16 column, under its title's. Scrolled within, the box reaches
          // into the dialog's padding so a lit rule's light, 8 past its words, is not cut off.
          <div className="-mx-4 min-h-0 divide-y overflow-y-auto px-4">
            <MemoryList memories={rows} item={opened.item} onClose={close} />
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
