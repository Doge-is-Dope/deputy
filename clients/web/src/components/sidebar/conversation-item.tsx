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

/** Status priority: needs user, running, unread failure/reply, then the menu.
 * Share one trailing slot so status and menu changes do not shift the row.
 * Memoized (memo), its callbacks taking the conversation rather than closing over it: the sidebar renders anew on any
 * change of its state, a drop or a scroll, and its rows, some forty, rendered again with it, for 20-30ms; with their
 * props unchanged they are skipped. */
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
  inset?: boolean // in a project: its name on the project's name's column, its highlight still the full row's width
  moving?: "in" | "out" // just moved: into this list, its row opening, or out of it, a copy of its row closing up
  active: boolean
  needsYou: boolean // its run waits for the user (a step to approve, a takeover it asked for), as Grok Bot marks a bot that needs attention
  fresh: boolean // its latest run ended since the user last saw it
  selected: boolean
  projects: string[] // every project, for it to be moved to
  onDelete: (conversation: Conversation) => void
  onRename: (id: string, title: string) => Promise<{ title: string } | null>
  onMove: (conversation: Conversation, project: string | null) => void
  onNewProject: (conversation: Conversation) => void // a project to be named, for it to go into
}) {
  const t = useT()
  const { isMobile, setOpenMobile } = useSidebar()
  // Enter or blur saves a changed, nonempty title; Escape cancels.
  const [draft, setDraft] = useState<string | null>(null)
  // The name just given stands from the moment it is, as the runtime saves it and the list comes back with it: the
  // name it had does not show again meanwhile. It goes once the list has it, or if the rename failed.
  const [given, setGiven] = useState<string | null>(null)
  if (given !== null && conversation.title === given) setGiven(null)
  const name = given ?? conversation.title
  // A name the user gives is there at once, not rolled in as one the runtime makes arrives (ConversationName): the
  // name is drawn anew with it.
  const [renames, setRenames] = useState(0)
  const commit = () => {
    if (draft === null) return
    const title = draft.trim()
    setDraft(null)
    if (!title || title === (name ?? nameOf(conversation))) return
    setGiven(title)
    setRenames((count) => count + 1)
    // As the runtime saved it, its spaces collapsed and a long one cut.
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
  const actionable = !active && !mark
  const others = projects.filter((project) => project !== conversation.project)
  // It can be carried onto a project, or out of one to the recents (AppSidebar), its row staying faded in its place
  // meanwhile.
  const { setNodeRef, listeners, isDragging } = useDraggable({
    id: `conversation:${conversation.id}`,
    data: { conversation },
    disabled: draft !== null || moving === "out",
  })
  // Moved, its row opens where it went and closes up where it was; deleted, it closes up. The only row in its list
  // fades alone, as the empty list's line takes or gives up its place.
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
      {/* Rows of 32px, and of 40px on a touch screen, for a finger to tap. */}
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
        {/* A long title fades out, without the ellipsis the menu button gives its last span. While something holds the
            place at the end (a mark, or the delete button: on hover, or always where nothing hovers), the fade starts
            earlier and ends short of it, leaving a gap. */}
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
        {/* In the link, so its name says it; placed on the item, where the delete button is. */}
        {(mark || active) && (
          <span className="pointer-events-none absolute inset-y-0 right-0 flex w-8 items-center justify-center">
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
            // Enter or Esc while an input method composes picks or drops what it composes, as in the composer.
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
        // Shown on hover where a pointer can hover, and while its menu is open; on a touch screen it stays, as there
        // is nothing to hover. Keyboard focus shows it too, but not the focus a click leaves behind, so it goes once
        // the pointer leaves.
        <DropdownMenu>
          <DropdownMenuTrigger
            aria-label={t.sidebar.more}
            className="absolute inset-y-0 right-0 flex w-8 items-center justify-center rounded-md text-muted-foreground outline-none group-hover/menu-item:opacity-100 group-has-[:focus-visible]/menu-item:opacity-100 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground focus-visible:ring-2 focus-visible:ring-sidebar-ring data-popup-open:bg-sidebar-accent data-popup-open:text-sidebar-accent-foreground data-popup-open:opacity-100 [@media(hover:hover)]:opacity-0"
          >
            <EllipsisIcon className="size-[18px]" />
          </DropdownMenuTrigger>
          {/* From the button's start, out over the page, as ChatGPT's and Claude's sidebar menus open: not held to
              the sidebar, which is narrow. */}
          <DropdownMenuContent align="start" finalFocus={false}>
            {/* The menu does not hand focus back to the button as it closes (finalFocus): the input mounts in the
                same commit, focused, and would lose that to the button. */}
            <DropdownMenuItem
              onClick={() => setDraft(given ?? nameOf(conversation))}
            >
              <PencilIcon />
              {t.sidebar.renameConversation}
            </DropdownMenuItem>
            {/* As ChatGPT's: its projects beside the menu, a new one first and out of its own last. */}
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
                    key={project}
                    onClick={() => onMove(conversation, project)}
                  >
                    <FolderIcon />
                    <span className="truncate">{project}</span>
                  </DropdownMenuItem>
                ))}
                {conversation.project !== null && (
                  <>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem
                      onClick={() => onMove(conversation, null)}
                    >
                      <FolderRemoveIcon />
                      <span className="truncate">
                        {t.sidebar.removeFromProject(conversation.project)}
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
