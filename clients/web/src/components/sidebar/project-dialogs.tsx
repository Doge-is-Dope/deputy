import { useRef, useState, type ComponentProps } from "react"

import { isComposing } from "@/lib/keys"
import { Input } from "@/components/ui/input"
import { ActionDialog } from "@/components/ui/dialog"
import { useT } from "@/lib/i18n"
import { FolderIcon } from "@/components/icons"

/** Asks a new project's name alone. Enter or 建立 makes it; an empty name makes nothing. */
export function CreateProjectDialog({
  open,
  onOpenChange,
  onCreate,
  finalFocus,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  onCreate: (name: string) => void
  finalFocus?: ComponentProps<typeof ActionDialog>["finalFocus"]
}) {
  const t = useT()
  const [name, setName] = useState("")
  // The focus goes to the name as it opens, however it was opened: a click, or a conversation dropped on the new
  // project row.
  const field = useRef<HTMLInputElement>(null)
  const create = () => {
    const given = name.split(/\s+/).join(" ").trim()
    if (!given) return
    onCreate(given)
    setName("")
    onOpenChange(false)
  }
  return (
    <ActionDialog
      open={open}
      onOpenChange={(next) => {
        if (!next) setName("")
        onOpenChange(next)
      }}
      title={t.sidebar.newProject}
      action={t.sidebar.create}
      onAction={create}
      initialFocus={field}
      finalFocus={finalFocus}
      className="sm:max-w-md"
    >
      {/* A 38px field with a folder in its own cell at the start, divided from the name, a thin ring as it
          focuses. The divider stands inside the field's border, and
          the folder in the middle of the space the borders leave (pl-px for the field's own on the left). */}
      <div className="relative">
        <span className="pointer-events-none absolute inset-y-px left-0 flex w-9 items-center justify-center border-r border-input pl-px text-muted-foreground">
          <FolderIcon className="size-4" />
        </span>
        <Input
          ref={field}
          value={name}
          placeholder={t.sidebar.projectName}
          aria-label={t.sidebar.projectName}
          onChange={(event) => setName(event.target.value)}
          onKeyDown={(event) => {
            if (isComposing(event.nativeEvent)) return
            if (event.key === "Enter") create()
          }}
          className="h-9.5 pl-12 focus-visible:ring-0"
        />
      </div>
    </ActionDialog>
  )
}

/** Asks before a project goes with its conversations. Deleting closes it at once: the project folds shut as it goes,
 * and a notice can bring it back. */
export function DeleteProjectDialog({
  open,
  project,
  count,
  onOpenChange,
  onDelete,
}: {
  open: boolean
  project: string
  count: number // its conversations
  onOpenChange: (open: boolean) => void
  onDelete: () => void
}) {
  const t = useT()
  return (
    <ActionDialog
      open={open}
      onOpenChange={onOpenChange}
      title={t.sidebar.deleteProjectAsk(project, count)}
      action={t.sidebar.deleteProject}
      onAction={onDelete}
      destructive
    />
  )
}
