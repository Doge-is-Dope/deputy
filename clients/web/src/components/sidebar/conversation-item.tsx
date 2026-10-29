import { memo, useLayoutEffect, useRef, useState } from "react"
import { useDraggable } from "@dnd-kit/core"
import { cn } from "cn"

import {
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar"
import { isComposing } from "@/lib/keys"
import { Spinner } from "@/components/ui/spinner"
import type { Project } from "@/lib/api"
import { nameOf, type Conversation } from "@/lib/conversations"
import { useT } from "@/lib/i18n"
import { runHref } from "@/lib/route"
import {
  EllipsisIcon,
  FolderIcon,
  FolderPlusIcon,
  FolderRemoveIcon,
  PencilIcon,
  TrashIcon,
} from "@/components/icons"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { ConversationName } from "@/components/sidebar/conversation-name"
import { fold } from "@/components/sidebar/motion"

/** One trailing slot, by priority: needs user, running, unread, then the menu.
 * Memoized, its callbacks taking the conversation, so a sidebar re-render skips unchanged rows. */
export const ConversationItem = memo(function ConversationItem({
  conversation,
  active,
  needsYou,
  fresh,
  selected,
  inset = false,
  moving,
  projects,
  onDelete,
  onRename,
  onMove,
  onNewProject,
}: {
  conversation: Conversation
  inset?: boolean // in a project: name indented, highlight full width
  moving?: "in" | "out" // just moved: its row opens here, or closes up
  active: boolean
  needsYou: boolean // its run waits for the user: an approval or a takeover
  fresh: boolean // its latest run ended since the user last saw it
  selected: boolean
  projects: Pick<Project, "id" | "name">[] // move targets
  onDelete: (conversation: Conversation) => void
  onRename: (id: string, title: string) => Promise<{ title: string } | null>
  onMove: (conversation: Conversation, project: string | null) => void
  onNewProject: (conversation: Conversation) => void // move it into a new project
}) {
  const t = useT()
  const { isMobile, setOpenMobile } = useSidebar()
  // Enter or blur saves a changed, nonempty title; Escape cancels.
  const [draft, setDraft] = useState<string | null>(null)
  // The new name shows until the list has it, or the rename fails.
  const [given, setGiven] = useState<string | null>(null)
  if (given !== null && conversation.title === given) setGiven(null)
  const name = given ?? conversation.title
  // A user's rename remounts the name, skipping ConversationName's roll-in.
  const [renames, setRenames] = useState(0)
  const commit = () => {
    if (draft === null) return
    const title = draft.trim()
    setDraft(null)
    if (!title || title === (name ?? nameOf(conversation))) return
    setGiven(title)
    setRenames((count) => count + 1)
    // As the runtime saved it: spaces collapsed, length capped.
    void onRename(conversation.id, title).then((renamed) =>
      setGiven(renamed?.title ?? null)
    )
  }
  const [first] = conversation.runs
  const mark = active
    ? needsYou
      ? { color: "bg-warning", label: t.sidebar.needsAttention }
      : null
    : fresh && !selected
      ? conversation.latest.failed
        ? { color: "bg-destructive", label: t.sidebar.failed }
        : { color: "bg-unread", label: t.sidebar.unread }
      : null
  const actionable = !active
  const others = projects.filter(
    (project) => project.id !== conversation.project
  )
  const own = projects.find((project) => project.id === conversation.project)
  // Draggable onto a project or back to the recents (AppSidebar).
  const { setNodeRef, listeners, isDragging } = useDraggable({
    id: `conversation:${conversation.id}`,
    data: { conversation },
    disabled: draft !== null || moving === "out",
  })
  // Moved or deleted, the row opens or closes up; the only row in a list fades.
  const item = useRef<HTMLLIElement>(null)
  useLayoutEffect(() => {
    const row = item.current
    if (!row || !moving) return
    return fold(row, moving, "fade")
  }, [moving])

  return (
    <SidebarMenuItem
      ref={item}
      className={cn(moving === "out" && "pointer-events-none")}
    >
      {/* 32px rows, 40px on touch screens. */}
      <SidebarMenuButton
        ref={setNodeRef}
        {...listeners}
        className={cn(
          "h-8 pointer-coarse:h-10",
          inset && "pl-10",
          isDragging && "opacity-50"
        )}
        isActive={selected}
        render={<a href={runHref(conversation.id)} />}
        onClick={() => isMobile && setOpenMobile(false)}
      >
        {/* A long title fades out instead of an ellipsis, ending short of the trailing slot when it is filled. */}
        <span
          className={cn(
            "min-w-0 flex-1 overflow-hidden mask-[linear-gradient(to_right,#000_calc(100%-2rem),transparent)] text-clip! whitespace-nowrap",
            (mark || active) &&
              "mask-[linear-gradient(to_right,#000_calc(100%-3.375rem),transparent_calc(100%-1.875rem))]",
            actionable &&
              "group-hover/menu-item:mask-[linear-gradient(to_right,#000_calc(100%-3.375rem),transparent_calc(100%-1.875rem))] group-has-data-popup-open/menu-item:mask-[linear-gradient(to_right,#000_calc(100%-3.375rem),transparent_calc(100%-1.875rem))] group-has-[:focus-visible]/menu-item:mask-[linear-gradient(to_right,#000_calc(100%-3.375rem),transparent_calc(100%-1.875rem))] [@media(hover:none)]:mask-[linear-gradient(to_right,#000_calc(100%-3.375rem),transparent_calc(100%-1.875rem))]"
          )}
        >
          <ConversationName
            key={renames}
            name={name}
            placeholder={first.goal || first.id}
            naming={active && name === null}
          />
        </span>
        {/* Inside the link so its label is announced; on an idle row it gives way to the menu button. */}
        {(mark || active) && (
          <span
            className={cn(
              "pointer-events-none absolute inset-y-0 right-0 flex w-8 items-center justify-center",
              actionable &&
                "group-hover/menu-item:opacity-0 group-has-data-popup-open/menu-item:opacity-0 group-has-[:focus-visible]/menu-item:opacity-0 [@media(hover:none)]:opacity-0"
            )}
          >
            {mark ? (
              <span
                role="img"
                aria-label={mark.label}
                className={cn("size-2 rounded-full", mark.color)}
              />
            ) : (
              <Spinner
                aria-label={t.sidebar.running}
                className="text-muted-foreground"
              />
            )}
          </span>
        )}
      </SidebarMenuButton>
      {draft !== null && (
        <input
          autoFocus
          value={draft}
          aria-label={t.sidebar.renameConversation}
          onChange={(event) => setDraft(event.target.value)}
          onFocus={(event) => event.currentTarget.select()}
          onBlur={commit}
          onKeyDown={(event) => {
            // Enter or Esc mid-composition belongs to the input method.
            if (isComposing(event.nativeEvent)) return
            if (event.key === "Enter") commit()
            if (event.key === "Escape") setDraft(null)
          }}
          className={cn(
            "absolute inset-0 z-10 h-full w-full rounded-md bg-sidebar-accent px-2 text-sm text-sidebar-accent-foreground outline-none",
            inset && "pl-10"
          )}
        />
      )}
      {actionable && draft === null && (
        // Shown on hover, keyboard focus or while open; always on touch screens.
        <DropdownMenu>
          <DropdownMenuTrigger
            aria-label={t.sidebar.more}
            className="absolute inset-y-0 right-0 flex w-8 items-center justify-center rounded-md text-muted-foreground outline-none group-hover/menu-item:opacity-100 group-has-[:focus-visible]/menu-item:opacity-100 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground focus-visible:ring-2 focus-visible:ring-sidebar-ring data-popup-open:bg-sidebar-accent data-popup-open:text-sidebar-accent-foreground data-popup-open:opacity-100 [@media(hover:hover)]:opacity-0"
          >
            <EllipsisIcon className="size-[18px]" />
          </DropdownMenuTrigger>
          {/* Opens out over the page, not held to the narrow sidebar. */}
          <DropdownMenuContent align="start" finalFocus={false}>
            {/* No focus back to the button (finalFocus): the rename input takes it. */}
            <DropdownMenuItem
              onClick={() => setDraft(given ?? nameOf(conversation))}
            >
              <PencilIcon />
              {t.sidebar.renameConversation}
            </DropdownMenuItem>
            {/* New project first, removal from its own last. */}
            <DropdownMenuSub>
              <DropdownMenuSubTrigger>
                <FolderIcon />
                {t.sidebar.project}
              </DropdownMenuSubTrigger>
              <DropdownMenuContent
                side="inline-end"
                align="start"
                sideOffset={0}
                alignOffset={-4}
                className="max-w-60"
              >
                <DropdownMenuItem onClick={() => onNewProject(conversation)}>
                  <FolderPlusIcon />
                  {t.sidebar.newProject}
                </DropdownMenuItem>
                {others.length > 0 && <DropdownMenuSeparator />}
                {others.map((project) => (
                  <DropdownMenuItem
                    key={project.id}
                    onClick={() => onMove(conversation, project.id)}
                  >
                    <FolderIcon />
                    <span className="truncate">{project.name}</span>
                  </DropdownMenuItem>
                ))}
                {own !== undefined && (
                  <>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem
                      onClick={() => onMove(conversation, null)}
                    >
                      <FolderRemoveIcon />
                      <span className="truncate">
                        {t.sidebar.removeFromProject(own.name)}
                      </span>
                    </DropdownMenuItem>
                  </>
                )}
              </DropdownMenuContent>
            </DropdownMenuSub>
            <DropdownMenuItem
              variant="destructive"
              onClick={() => onDelete(conversation)}
            >
              <TrashIcon />
              {t.sidebar.deleteConversation}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      )}
    </SidebarMenuItem>
  )
})
