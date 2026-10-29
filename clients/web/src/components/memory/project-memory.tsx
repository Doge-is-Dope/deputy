import { useEffect, useState } from "react"

import { MemoryList } from "@/components/settings/memory"
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog"
import { useT } from "@/lib/i18n"
import {
  loadMemories,
  openProjectMemory,
  useMemories,
  useOpenedProjectMemory,
} from "@/lib/memory"

/** A project's rules, those only its conversations are told, from its menu or a line in the conversation: listed as
 * the settings list the user's own (MemoryList), to edit or delete. Outside the sidebar, beside the settings. */
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

  return (
    <Dialog
      open={opened.project !== null}
      onOpenChange={(open) => !open && close()}
    >
      <DialogContent className="flex max-h-[min(36rem,calc(100dvh-2rem))] flex-col pt-3 sm:max-w-lg">
        <DialogTitle className="flex h-8 items-center pr-8">
          {t.sidebar.projectMemoryTitle(shown ? (names[shown] ?? "") : "")}
        </DialogTitle>
        {list === null || rows.length === 0 ? (
          <p className="text-muted-foreground">
            {list !== null
              ? t.settings.memoryEmpty
              : failed
                ? t.settings.memoryLoadFailed
                : t.common.loading}
          </p>
        ) : (
          // Scrolled within, the rules' light reaching into the dialog's padding, their words under its title's.
          <div className="-mx-4 min-h-0 overflow-y-auto px-3">
            <MemoryList
              memories={rows}
              item={opened.item}
              editing={opened.editing}
              onClose={close}
            />
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
