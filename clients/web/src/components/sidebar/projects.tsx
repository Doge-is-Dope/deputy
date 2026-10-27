import {
  Children,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from "react"
import { useDroppable } from "@dnd-kit/core"
import { useSortable } from "@dnd-kit/sortable"
import { CSS } from "@dnd-kit/utilities"
import { cn } from "cn"

import {
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarMenuSub,
  useSidebar,
} from "@/components/ui/sidebar"
import { Collapsible, CollapsibleContent } from "@/components/ui/collapsible"
import { isComposing } from "@/lib/keys"
import { type Conversation } from "@/lib/conversations"
import { useT } from "@/lib/i18n"
import { reducedMotion } from "@/lib/motion"
import { projectHref } from "@/lib/route"
import {
  ComposeIcon,
  EllipsisIcon,
  FolderIcon,
  FolderOpenIcon,
  FolderPlusIcon,
  PencilIcon,
  TrashIcon,
} from "@/components/icons"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { carriedBy, NEW_PROJECT } from "@/components/sidebar/drag"
import { FOLD, fold } from "@/components/sidebar/motion"

/** How many conversations a project lists as it opens; Show more lists as many again, as ChatGPT's projects do. */
const PROJECT_PAGE = 5

/** The row that makes a project while there is none, as ChatGPT lists New project under its Projects: a folder with a
 * plus on the folders' column, as a project's row has its folder. A conversation dropped on it goes into the project it makes, the
 * row lit meanwhile as a project's is. Where the last project is folding shut, it opens as that closes up, so the list
 * below moves one way only. */
export function NewProjectRow({
  onCreate,
  opening,
}: {
  onCreate: () => void
  opening: boolean // takes the place of the last project, being deleted
}) {
  const t = useT()
  const { setNodeRef, isOver, active } = useDroppable({ id: NEW_PROJECT })
  const item = useRef<HTMLLIElement | null>(null)
  const [grows] = useState(opening && !reducedMotion())
  useLayoutEffect(() => {
    if (grows && item.current) return fold(item.current, "in", "fold")
  }, [grows])
  return (
    <SidebarMenuItem
      ref={(node) => {
        setNodeRef(node)
        item.current = node
      }}
    >
      <SidebarMenuButton
        className={cn(
          "h-8 pl-2.5 pointer-coarse:h-10",
          isOver &&
            carriedBy(active) &&
            "bg-sidebar-accent text-sidebar-accent-foreground"
        )}
        onClick={onCreate}
      >
        <FolderPlusIcon className="shrink-0" />
        {t.sidebar.newProject}
      </SidebarMenuButton>
    </SidebarMenuItem>
  )
}

/** A project's row and its conversations set in under it, as Codex's sidebar lists a project: a folder (open while
 * its conversations are shown) and its name, a click showing or hiding them, a dot while shut for replies that came
 * meanwhile, and on hover a menu that renames it or deletes it with them, and a link to begin a conversation in it (its
 * home). Dragged by its row, it takes another place in the list, the others making room; a conversation dropped on it
 * goes into it. */
export function ProjectGroup({
  project,
  items,
  open,
  held,
  selected,
  onOpen,
  unread,
  failed,
  onRename,
  onDelete,
  leaving = false,
  reading,
  children,
}: {
  project: string
  items: Conversation[]
  open: boolean // its conversations shown
  held: boolean // being dragged, until it is dropped
  selected: boolean // its home is the page open
  reading: number // which of its conversations is the page open, or -1
  onOpen: (open: boolean) => void
  unread: number // conversations whose latest run ended since the user saw them
  failed: boolean // one of those ended in an error
  onRename: (name: string) => Promise<void>
  onDelete: () => void // its menu's 刪除: asked about first, unless it is empty
  leaving?: boolean // deleted: its row and its conversations fold shut as one
  children: ReactNode
}) {
  const t = useT()
  const { isMobile, setOpenMobile } = useSidebar()
  // Enter or blur renames it to a changed, nonempty name; Escape cancels, as a conversation's rename does.
  const [draft, setDraft] = useState<string | null>(null)
  const commit = () => {
    if (draft === null) return
    const name = draft.split(/\s+/).join(" ").trim()
    setDraft(null)
    if (name && name !== project) void onRename(name)
  }
  // The others make room on the drawer's curve, as the lists fold (FOLD).
  const {
    setNodeRef,
    setActivatorNodeRef,
    listeners,
    transform,
    transition,
    isDragging,
    isOver,
    active,
  } = useSortable({
    id: project,
    disabled: draft !== null,
    transition: reducedMotion()
      ? null
      : { duration: 200, easing: "cubic-bezier(0.32, 0.72, 0, 1)" },
  })
  // Shut as it is picked up, so it moves as one row and the others make room for that alone, the others left as they
  // are; open again as it is dropped, if it was, unfolding under its row as that glides into place (DROP).
  const shown = open && !held
  // A conversation from elsewhere carried over it, or over its conversations: its row lit and its folder open, to take
  // it in. One of its own is home already.
  const carried = carriedBy(active)
  const target = isOver && carried !== undefined && carried.project !== project
  const Folder = shown || target ? FolderOpenIcon : FolderIcon
  const mark = !shown && unread > 0
  // Deleted, it closes up where it was with its conversations, as a conversation's row does, the only project too: the
  // new project row that takes its place is shorter than a project open on its conversations.
  const item = useRef<HTMLLIElement | null>(null)
  useLayoutEffect(() => {
    const row = item.current
    if (!row || !leaving) return
    return fold(row, "out", "fold")
  }, [leaving])
  return (
    // A plain item, not SidebarMenuItem: its conversations are inside it, and hovering one must not show this row's
    // buttons. The row alone is the hover group, and what its buttons and dot are placed against. Dragged, it stays
    // unseen where it would land, holding its place, while its row is carried (DraggedProject).
    <li
      ref={(node) => {
        setNodeRef(node)
        item.current = node
      }}
      style={{ transform: CSS.Translate.toString(transform), transition }}
      className={cn(
        "relative",
        isDragging && "opacity-0",
        leaving && "pointer-events-none"
      )}
    >
      <Collapsible open={shown}>
        <div className="group/menu-item relative">
          <SidebarMenuButton
            // Its folder as the commands' icons above it: 20px, in the text's color, on the same column (pl-2.5).
            ref={setActivatorNodeRef}
            {...listeners}
            // Lit as a hovered row is while it would take a carried conversation.
            className={cn(
              "h-8 pl-2.5 pointer-coarse:h-10",
              target && "bg-sidebar-accent text-sidebar-accent-foreground"
            )}
            isActive={selected}
            aria-expanded={shown}
            onClick={() => onOpen(!open)}
          >
            <Folder className="shrink-0" />
            {/* The name fades out before the trailing slot: the dot, or on hover the two buttons. */}
            <span
              className={cn(
                "min-w-0 flex-1 overflow-hidden mask-[linear-gradient(to_right,#000_calc(100%-2rem),transparent)] text-clip! whitespace-nowrap",
                mark &&
                  "mask-[linear-gradient(to_right,#000_calc(100%-3.375rem),transparent_calc(100%-1.875rem))]",
                "group-hover/menu-item:mask-[linear-gradient(to_right,#000_calc(100%-5.375rem),transparent_calc(100%-3.875rem))] group-has-data-popup-open/menu-item:mask-[linear-gradient(to_right,#000_calc(100%-5.375rem),transparent_calc(100%-3.875rem))] group-has-[:focus-visible]/menu-item:mask-[linear-gradient(to_right,#000_calc(100%-5.375rem),transparent_calc(100%-3.875rem))] [@media(hover:none)]:mask-[linear-gradient(to_right,#000_calc(100%-5.375rem),transparent_calc(100%-3.875rem))]"
              )}
            >
              {project}
            </span>
            {mark && (
              <span className="pointer-events-none absolute inset-y-0 right-0 flex w-8 items-center justify-center group-hover/menu-item:opacity-0 group-has-data-popup-open/menu-item:opacity-0 group-has-[:focus-visible]/menu-item:opacity-0 [@media(hover:none)]:opacity-0">
                <span
                  role="img"
                  aria-label={t.sidebar.newReplies(unread)}
                  className={cn(
                    "size-2 rounded-full",
                    failed ? "bg-destructive" : "bg-unread"
                  )}
                />
              </span>
            )}
          </SidebarMenuButton>
          {/* Over the row, its folder and the name kept in place: the row's gap between them (gap-2.5), or the name
              jumps as the field opens. */}
          {draft !== null && (
            <div className="absolute inset-0 z-10 flex items-center gap-2.5 rounded-md bg-sidebar-accent pr-2 pl-2.5 text-sidebar-accent-foreground">
              <Folder className="shrink-0" />
              <input
                autoFocus
                value={draft}
                aria-label={t.sidebar.projectName}
                onChange={(event) => setDraft(event.target.value)}
                onFocus={(event) => event.currentTarget.select()}
                onBlur={commit}
                onKeyDown={(event) => {
                  if (isComposing(event.nativeEvent)) return
                  if (event.key === "Enter") commit()
                  if (event.key === "Escape") setDraft(null)
                }}
                className="h-full min-w-0 flex-1 bg-transparent text-sm outline-none"
              />
            </div>
          )}
          {/* Shown on hover where a pointer can hover, and while the menu is open; on a touch screen they stay. */}
          <span className="absolute inset-y-0 right-0 flex group-hover/menu-item:opacity-100 group-has-data-popup-open/menu-item:opacity-100 group-has-[:focus-visible]/menu-item:opacity-100 [@media(hover:hover)]:opacity-0">
            <DropdownMenu>
              <DropdownMenuTrigger
                aria-label={t.sidebar.more}
                className="flex w-8 items-center justify-center rounded-md text-muted-foreground outline-none hover:bg-sidebar-accent hover:text-sidebar-accent-foreground focus-visible:ring-2 focus-visible:ring-sidebar-ring data-popup-open:bg-sidebar-accent data-popup-open:text-sidebar-accent-foreground"
              >
                <EllipsisIcon className="size-[18px]" />
              </DropdownMenuTrigger>
              {/* As a conversation's menu: no focus back to the button, which would take it from the name's field. */}
              <DropdownMenuContent align="start" finalFocus={false}>
                <DropdownMenuItem onClick={() => setDraft(project)}>
                  <PencilIcon />
                  {t.sidebar.renameProject}
                </DropdownMenuItem>
                <DropdownMenuItem variant="destructive" onClick={onDelete}>
                  <TrashIcon />
                  {t.sidebar.deleteProject}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
            <a
              href={projectHref(project)}
              aria-label={t.sidebar.newInProject}
              title={t.sidebar.newInProject}
              onClick={() => {
                onOpen(true)
                if (isMobile) setOpenMobile(false)
              }}
              className="flex w-8 items-center justify-center rounded-md text-muted-foreground outline-none hover:bg-sidebar-accent hover:text-sidebar-accent-foreground focus-visible:ring-2 focus-visible:ring-sidebar-ring"
            >
              <ComposeIcon className="size-4" />
            </a>
          </span>
        </div>
        {/* Its conversations under it, their names set in to the project's name's column by their own padding, so
            a row's highlight spans the sidebar as the project's does; a little room after them. An empty project
            says so in their place, fading in as the last row moved out fades away. */}
        {/* Gone at once as the project is picked up (hidden), not folded away a commit later: dnd-kit measures the row
            as the drag starts, and a fold that follows leaves it holding its open height, the others making room
            for all of it while the row carried is one line, and the lower ones pushed out of the list's box. */}
        <CollapsibleContent
          className={cn(FOLD, held && "hidden transition-none")}
        >
          {/* The rows' gap above the first one too, as between any two rows. The room after the list is inside the
              panel, not on it: the panel's own padding would hold its height above zero until it unmounts, and the
              list below would jump by that much at the end. */}
          <SidebarMenuSub className="mx-0 translate-x-0 gap-0.5 border-0 pt-0.5 pr-0 pb-1.5 pl-0">
            {items.length > 0 ? (
              <ProjectRows reading={reading}>{children}</ProjectRows>
            ) : (
              <li className="flex h-8 animate-in items-center pr-2 pl-10 text-sm text-muted-foreground duration-200 ease-(--ease-out) fade-in motion-reduce:animate-none pointer-coarse:h-10">
                {t.sidebar.noChats}
              </li>
            )}
          </SidebarMenuSub>
        </CollapsibleContent>
      </Collapsible>
    </li>
  )
}

/** A project's conversations: the first five, and five more for each Show more under them, as ChatGPT's projects list
 * theirs; and the one whose page is open, after them, while it is further down, so the page open is always in the
 * list, with Show more only while some are still unlisted. In the project's panel, which unmounts as the project
 * shuts, so an opened project lists five again. */
function ProjectRows({
  reading,
  children,
}: {
  reading: number // the index of the conversation whose page is open, or -1
  children: ReactNode
}) {
  const t = useT()
  const [limit, setLimit] = useState(PROJECT_PAGE)
  const rows = Children.toArray(children)
  // The one whose page is open, listed after the first five while it is further down; no Show more for it alone.
  const appended = reading >= limit
  return (
    <>
      {rows.slice(0, limit)}
      {appended && rows[reading]}
      {rows.length > limit + (appended ? 1 : 0) && (
        <SidebarMenuItem>
          <SidebarMenuButton
            className="h-8 pl-10 text-muted-foreground pointer-coarse:h-10"
            onClick={() => setLimit((n) => n + PROJECT_PAGE)}
          >
            {t.sidebar.showMore}
          </SidebarMenuButton>
        </SidebarMenuItem>
      )}
    </>
  )
}
