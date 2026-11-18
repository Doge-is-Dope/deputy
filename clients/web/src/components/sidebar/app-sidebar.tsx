import {
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
  type ComponentProps,
  type ReactNode,
  type Ref,
  type RefObject,
} from "react"
import { createPortal } from "react-dom"
import {
  DndContext,
  DragOverlay,
  MouseSensor,
  TouchSensor,
  useSensor,
  useSensors,
} from "@dnd-kit/core"
import {
  SortableContext,
  arrayMove,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable"
import { cn } from "cn"

import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupAction,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarMenuSkeleton,
  SidebarTrigger,
  useSidebar,
  useSidebarSheet,
} from "@/components/ui/sidebar"
import { ResizeHandle } from "@/components/resize-handle"
import { Collapsible, CollapsibleContent } from "@/components/ui/collapsible"
import { Kbd } from "@/components/ui/kbd"
import {
  isShortcut,
  shortcutAria,
  shortcutLabel,
  type Shortcut,
} from "@/lib/keys"
import { Skeleton } from "@/components/ui/skeleton"
import {
  runningOf,
  waitingSession,
  type Conversation,
  type Project,
  type Status,
} from "@/lib/api"
import { nameOf } from "@/lib/conversations"
import { useT } from "@/lib/i18n"
import { openSettings } from "@/lib/settings"
import { useSession } from "@/lib/session"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { openProject, openRun, runHref } from "@/lib/route"
import type { Lists } from "@/hooks/use-api"
import {
  ComposeIcon,
  FolderPlusIcon,
  GearIcon,
  SearchIcon,
} from "@/components/icons"
import { SearchDialog } from "@/components/search-dialog"
import { SettingsDialog } from "@/components/settings/settings-dialog"
import { ProjectMemoryDialog } from "@/components/memory/project-memory"
import { ConversationItem } from "@/components/sidebar/conversation-item"
import { UserAvatar } from "@/components/sidebar/user-avatar"
import { NewProjectRow, ProjectGroup } from "@/components/sidebar/projects"
import {
  CreateProjectDialog,
  DeleteProjectDialog,
} from "@/components/sidebar/project-dialogs"
import { RecentsGroup, SectionLabel } from "@/components/sidebar/sections"
import {
  alongList,
  byPointer,
  carriedBy,
  collision,
  DraggedConversation,
  HOME,
  DraggedProject,
  NEW_PROJECT,
  RECENTS,
} from "@/components/sidebar/drag"
import { DROP, FOLD, FOLD_DURATION } from "@/components/sidebar/motion"
import { useStoredNames } from "@/hooks/use-stored-names"
import { useStoredWidth } from "@/hooks/use-stored-width"
import { useSidebarLists } from "@/components/sidebar/use-sidebar-lists"

// 設定 opens with ⌘ , (Ctrl , off a Mac), as in most apps; 新對話 with ⇧ ⌘ O: ⌘ N is the
// browser's, for a new window. 搜尋 with ⌘ K.
const SETTINGS_SHORTCUT: Shortcut = { key: "," }
const NEW_SHORTCUT: Shortcut = { key: "o", shift: true }
const SEARCH_SHORTCUT: Shortcut = { key: "k" }

/** Show shortcuts in rail tooltips or beside expanded labels; omit them on touch screens. */
function ShortcutItem({
  icon,
  label,
  shortcut,
  ...props
}: {
  icon: ReactNode
  label: string
  shortcut: Shortcut
} & ComponentProps<typeof SidebarMenuButton>) {
  const keys = shortcutLabel(shortcut)
  return (
    <SidebarMenuItem>
      <SidebarMenuButton
        tooltip={{
          children: (
            <>
              {label}
              <Kbd>{keys}</Kbd>
            </>
          ),
        }}
        aria-keyshortcuts={shortcutAria(shortcut)}
        // As high as a conversation's row. In the closed rail a 32px square under
        // the trigger's middle, so closing the sidebar moves no icon: the margin and padding change together. At once,
        // not animated: closing, the words go in the first frame; opening, the sidebar's moving edge alone uncovers them.
        className="h-8 pl-row-icon group-data-[collapsible=icon]:ml-1 group-data-[collapsible=icon]:size-8! group-data-[collapsible=icon]:p-1.5! pointer-coarse:h-10"
        {...props}
      >
        {icon}
        {label}
        <Kbd
          row
          className="-mr-1 ml-auto opacity-0 group-hover/menu-item:opacity-100 group-has-[:focus-visible]/menu-item:opacity-100 group-data-[collapsible=icon]:hidden [@media(hover:none)]:hidden"
        >
          {keys}
        </Kbd>
      </SidebarMenuButton>
    </SidebarMenuItem>
  )
}

/** Opens the settings, named with its key when pointed at. 32 square, the gear's middle on the icons' above in the
    rail and the button flush with the row's end beside the name. */
function SettingsButton({
  className,
  children,
}: {
  className: string
  children: ReactNode
}) {
  const t = useT()
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <button
            type="button"
            aria-label={t.settings.title}
            aria-keyshortcuts={shortcutAria(SETTINGS_SHORTCUT)}
            onClick={() => openSettings()}
            className={cn(
              "grid size-8 shrink-0 place-items-center rounded-md outline-none hover:bg-sidebar-accent hover:text-sidebar-accent-foreground focus-visible:ring-2 focus-visible:ring-sidebar-ring pointer-coarse:size-10 [&>svg]:col-start-1 [&>svg]:row-start-1",
              className
            )}
          />
        }
      >
        {children}
      </TooltipTrigger>
      <TooltipContent side="right">
        {t.settings.title}
        <Kbd>{shortcutLabel(SETTINGS_SHORTCUT)}</Kbd>
      </TooltipContent>
    </Tooltip>
  )
}

/** The sidebar's edits to a conversation, for its menu in the page's header: the same as its row's menu, so the row
 * folds and moves as it does from there. */
export type ConversationEdits = {
  projects: Pick<Project, "id" | "name">[] // move targets, in the sidebar's order
  remove: (conversation: Conversation) => void
  move: (conversation: Conversation, project: string | null) => void
  bringIn: (conversation: Conversation) => void // into a new project, named in its dialog
}

// The widths the sidebar can be dragged to.
const SIDEBAR_MIN = 200
const SIDEBAR_MAX = 480

/** The sidebar and the strip on its edge that resizes it. The width is held here, so a drag renders this frame and
 * not the lists inside it, which come in as the same element. */
function ResizableSidebar({
  finalFocus,
  children,
}: Pick<ComponentProps<typeof Sidebar>, "finalFocus" | "children">) {
  const t = useT()
  // Dragged wider or narrower; this browser remembers it.
  const [width, setWidth] = useStoredWidth("sidebar-width", 256)
  const { isMobile, state, setOpen } = useSidebar()
  return (
    <Sidebar finalFocus={finalFocus} width={width}>
      {children}
      {/* Also on the closed rail, so a drag that snapped it shut can open it again, and one from there opens it. */}
      {!isMobile && (
        <ResizeHandle
          from="left"
          width={width}
          min={SIDEBAR_MIN}
          max={SIDEBAR_MAX}
          onWidth={setWidth}
          label={t.sidebar.resize}
          className="-right-1.5"
          collapsed={state === "collapsed"}
          onCollapsed={(collapsed) => setOpen(!collapsed)}
        />
      )}
    </Sidebar>
  )
}

export function AppSidebar({
  conversations,
  conversationsFailed,
  lists,
  status,
  offline,
  openConversation,
  selectedProject,
  isNew,
  onDelete,
  onRename,
  onMove,
  projects: made,
  onCreateProject,
  onRenameProject,
  onDeleteProject,
  composer,
  edits,
}: {
  edits: Ref<ConversationEdits> // its edits, for the header's menu
  composer: RefObject<HTMLTextAreaElement | null> // where 新對話 puts the caret
  conversations: Conversation[] | null
  conversationsFailed: boolean // the list could not be loaded; it loads on its own once the runtime is back
  lists: Lists // their pages: whether a list has more, and loading them
  status: Status | null
  offline: boolean
  openConversation: string | null
  selectedProject: string | null // the project whose home is open
  isNew: (conversation: string, ended: number | null) => boolean // its latest run's end is news to the user
  // Deletes one conversation, or a project with all of its (`project`): true once done.
  onDelete: (
    conversations: string[],
    project: string | null
  ) => Promise<boolean>
  onRename: (
    conversation: string,
    title: string
  ) => Promise<{ title: string } | null>
  onMove: (
    conversation: string,
    project: string | null
  ) => Promise<{ project: string | null } | null>
  projects: Project[] | null // the viewer's, empty ones too
  onCreateProject: (name: string) => Promise<Project | null>
  onRenameProject: (project: string, name: string) => Promise<Project | null>
  onDeleteProject: (project: string) => Promise<unknown>
}) {
  const t = useT()
  const { user } = useSession()
  // Not the sidebar's open state: opening and closing it on a desktop then renders none of the lists.
  const { isMobile, setOpenMobile } = useSidebarSheet()
  const [searchOpen, setSearchOpen] = useState(false)
  const searchedNew = useRef(false) // 新對話 chosen in the search, which hands the focus to the composer as it closes
  // Where the keyboard was when the search opened, which gets it back: ⌘K has no button to give it back to.
  const searchedFrom = useRef<HTMLElement | null>(null)
  const noteFocus = () => {
    const active = document.activeElement
    if (active instanceof HTMLElement && !active.closest("[role=dialog]"))
      searchedFrom.current = active
  }
  // 新對話 puts the caret in the composer, also on the page it is already on (where the
  // composer is not mounted anew to focus itself). On a phone the sheet hands the focus to it as it closes, rather than
  // back to its toggle.
  const choseNew = useRef(false)
  const onNew = () => {
    if (!isMobile) return composer.current?.focus()
    choseNew.current = true
    setOpenMobile(false)
  }
  const sheetFocus = () => {
    const chose = choseNew.current
    choseNew.current = false
    return chose ? (composer.current ?? true) : true
  }
  // The lists as the viewer sees them, and the edits to them.
  const {
    projects,
    names,
    recents,
    closing,
    left,
    opened,
    setOpened,
    setOrder,
    remove,
    deleteProject,
    move,
    createProject,
    renameProject,
  } = useSidebarLists({
    conversations,
    projects: made,
    selectedProject,
    onDelete,
    onMove,
    onCreateProject,
    onRenameProject,
    onDeleteProject,
  })
  // The project being dragged, until it has landed (DROP) and the lists have unfolded after it (FOLD), dropped or
  // not: what the overlay carries meanwhile, and which lists open at once (ProjectGroup). The drop's own end is not
  // told when it has nothing to animate, so its time is waited for instead; and clearing this renders the whole
  // sidebar again, which stalls the lists' unfolding for a frame or two if it comes while they move.
  const [dragged, setDragged] = useState<string | null>(null)
  // While it is dragged, until it is dropped: shut meanwhile (ProjectGroup), and no row under the pointer lit.
  const [sorting, setSorting] = useState(false)
  const landing = useRef(0) // the wait for the last project to land, which the next drag of a project ends
  const land = () => {
    landing.current = window.setTimeout(
      () => setDragged(null),
      DROP.duration + FOLD_DURATION
    )
  }
  // The conversation being carried onto a project or out to the recents, until it is dropped.
  const [carried, setCarried] = useState<Conversation | null>(null)
  // Whether what is under it would take it: its chip is faint otherwise, and a release there, or Escape, puts the
  // chip back on its row (DROP). Kept past the drop, which reads it as the chip goes.
  const [aimed, setAimed] = useState(false)
  // The page marked while anything is dragged, for the system's closed hand over all of it (index.css).
  const grab = (dragging: boolean) =>
    document.documentElement.toggleAttribute("data-dragging", dragging)
  const sensors = useSensors(
    // A click opens or shuts a project, or opens a conversation; a press that moves drags it. On a touch screen, a
    // press held still, so a swipe still scrolls the list.
    useSensor(MouseSensor, { activationConstraint: { distance: 4 } }),
    useSensor(TouchSensor, {
      activationConstraint: { delay: 250, tolerance: 5 },
    })
  )
  // The sections the viewer folded away: "projects", "recents".
  const [folded, setFolded] = useStoredNames("folded-sections")
  const [creating, setCreating] = useState(false)
  // The conversation dropped on the new project row, for the project being named to take in.
  const [bringing, setBringing] = useState<Conversation | null>(null)
  const opensMade = useRef(false) // a project made and opened, whose composer takes the focus as the dialog closes
  // New project in a conversation's menu: the project being named takes it in.
  const bringIn = (conversation: Conversation) => {
    setBringing(conversation)
    setCreating(true)
  }
  // The project whose deletion is asked about, with its conversations; kept while the dialog closes, so its words stay.
  const [condemned, setCondemned] = useState<[string, Conversation[]] | null>(
    null
  )
  const [asking, setAsking] = useState(false)
  const [scrolled, setScrolled] = useState(false) // the list scrolled down from its top
  const [below, setBelow] = useState(false) // more of the list below, under the account row
  const [starting, setStarting] = useState(true) // the placeholder's delayed entrance still has its time to run
  useEffect(() => {
    const timer = window.setTimeout(() => setStarting(false), 500)
    return () => window.clearTimeout(timer)
  }, [])
  const list = useRef<HTMLDivElement>(null)
  const rows = useRef<HTMLDivElement>(null) // everything in the list, which grows and folds within it
  const measure = () => {
    const at = list.current
    if (!at) return
    setScrolled(at.scrollTop > 0)
    setBelow(at.scrollHeight - at.scrollTop - at.clientHeight > 1)
  }
  // Also as the list grows or folds, or the window changes, without a scroll: what it holds or the list resizing.
  useEffect(() => {
    const at = list.current
    if (!at) return
    const observer = new ResizeObserver(measure)
    observer.observe(at)
    if (rows.current) observer.observe(rows.current)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (isShortcut(event, SETTINGS_SHORTCUT)) {
        event.preventDefault()
        openSettings()
      } else if (isShortcut(event, SEARCH_SHORTCUT)) {
        event.preventDefault()
        noteFocus()
        setSearchOpen((open) => !open)
      } else if (isShortcut(event, NEW_SHORTCUT)) {
        event.preventDefault()
        openRun(null)
        // As 新對話 does: also on the page it is already on.
        composer.current?.focus()
      }
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [composer])

  const waiting = waitingSession(status)
  // None left once those being deleted have folded shut: the new project row is there meanwhile, so the list folds
  // straight to it.
  const none = projects.length === closing.length
  // With none (once the list is in), the section does not fold: one folded before opens, so the next project made is
  // in view.
  if (conversations !== null && none && folded.includes("projects"))
    setFolded("projects", false)
  // A project's conversations whose latest run ended since the user saw them, the open one aside.
  const unreadOf = (items: Conversation[]) =>
    items.filter(
      (conversation) =>
        conversation.id !== openConversation &&
        isNew(conversation.id, conversation.latest.ended)
    )
  const ids = useMemo(() => projects.map(([project]) => project), [projects])
  // Every project, for a conversation's menu to move it to.
  const choices = useMemo(
    () => ids.map((id) => ({ id, name: names[id] ?? "" })),
    [ids, names]
  )
  useImperativeHandle(edits, () => ({
    projects: choices,
    remove,
    move,
    bringIn,
  }))
  const isRunning = (conversation: Conversation) =>
    runningOf(status, { thread: conversation.id }) !== null
  const isWaiting = (conversation: Conversation) =>
    conversation.id === waiting?.thread
  const row = (conversation: Conversation, inset = false) => (
    <ConversationItem
      key={conversation.id}
      conversation={conversation}
      inset={inset}
      // The copy left behind closes up; the conversation itself opens where it went, as one coming into the page does.
      moving={
        left.includes(conversation)
          ? "out"
          : left.some((each) => each.id === conversation.id)
            ? "in"
            : undefined
      }
      arriving={lists.arrived.has(conversation.id)}
      active={isRunning(conversation)}
      needsYou={isWaiting(conversation)}
      fresh={isNew(conversation.id, conversation.latest.ended)}
      selected={conversation.id === openConversation}
      projects={choices}
      onDelete={remove}
      onRename={onRename}
      onMove={move}
      onNewProject={bringIn}
    />
  )

  // In place of the list: why there is none. With none yet, the sidebar says nothing.
  const notice =
    conversations === null && conversationsFailed && t.sidebar.loadFailed

  return (
    // Around both lists: a project is dragged along its own, a conversation onto a project or out to the recents.
    <DndContext
      sensors={sensors}
      collisionDetection={collision}
      modifiers={[alongList, byPointer]}
      onDragStart={({ active }) => {
        grab(true)
        const conversation = carriedBy(active)
        if (conversation) {
          setCarried(conversation)
          setAimed(false)
        } else {
          window.clearTimeout(landing.current)
          setDragged(String(active.id))
          setSorting(true)
        }
      }}
      onDragOver={({ active, over }) => {
        const conversation = carriedBy(active)
        if (conversation)
          setAimed(
            over !== null && over.id !== (conversation.project ?? RECENTS)
          )
      }}
      onDragCancel={() => {
        // Escape leaves the keyboard's focus ring on the row the press focused.
        if (document.activeElement instanceof HTMLElement)
          document.activeElement.blur()
        grab(false)
        setCarried(null)
        setSorting(false)
        land()
      }}
      onDragEnd={({ active, over }) => {
        grab(false)
        setCarried(null)
        setSorting(false)
        const conversation = carriedBy(active)
        if (conversation) {
          if (over?.id === NEW_PROJECT) {
            setBringing(conversation)
            // Once dnd-kit has stopped clearing text selections, 50 ms after a drop (its pointer sensor's detach): it
            // would clear the caret the dialog puts in the name field, leaving the field focused with none showing.
            setTimeout(() => setCreating(true), 50)
          } else if (over)
            void move(
              conversation,
              over.id === RECENTS ? null : String(over.id)
            )
          return
        }
        land()
        if (!over || active.id === over.id) return
        setOrder((list) =>
          arrayMove(
            list,
            list.indexOf(String(active.id)),
            list.indexOf(String(over.id))
          )
        )
      }}
    >
      {/* Closed, it narrows to a rail of its toggle, 新對話 and 搜尋, with the account's circle at its foot, each named
          on hover. Open or closed, they stay in one column, their 20px icons centred 28px from the left edge. */}
      <ResizableSidebar finalFocus={sheetFocus}>
        {/* The toggle sits on the page card's header line: 36px with its center 30px from the top, like the header's
            buttons. In the closed rail it is a 32px square like the commands under it, so their tooltips and hover marks
            line up; the margins keep its icon, and the rows under it, where they were. New and search above the list. A
            hairline under them shows while the list is scrolled, fading in and out, so the top of the list reads as
            passing under them. */}
        <SidebarHeader className="relative pt-1 pb-2 md:pt-2.5">
          <SidebarTrigger className="m-0.5 size-9 transition-[width,height,margin] duration-300 ease-(--ease-drawer) group-data-[collapsible=icon]:my-1 group-data-[collapsible=icon]:ml-1 group-data-[collapsible=icon]:size-8 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground dark:hover:bg-sidebar-accent" />
          <SidebarMenu className="gap-0.5">
            <ShortcutItem
              icon={<ComposeIcon />}
              label={t.sidebar.new}
              shortcut={NEW_SHORTCUT}
              isActive={!openConversation && !selectedProject}
              render={<a href={runHref(null)} />}
              onClick={onNew}
            />
            <ShortcutItem
              icon={<SearchIcon />}
              label={t.sidebar.search}
              shortcut={SEARCH_SHORTCUT}
              onClick={() => {
                noteFocus()
                setSearchOpen(true)
              }}
            />
          </SidebarMenu>
          <span
            aria-hidden
            className={cn(
              "pointer-events-none absolute inset-x-0 bottom-0 h-px bg-sidebar-border transition-opacity duration-200 ease-(--ease-out) group-data-[collapsible=icon]:hidden motion-reduce:transition-none",
              scrolled ? "opacity-100" : "opacity-0"
            )}
          />
        </SidebarHeader>

        <SidebarContent
          // While a conversation is carried, no row under the pointer lights or shows its buttons as hovered: only the
          // place it would go into does. Nor while a project is: the others making room light up as it passes over
          // them otherwise. The drag itself does not need them: dnd-kit's sensors listen on the document, and where
          // the row would land comes from the rows' rectangles, not from what is under the pointer.
          className={cn(
            "overflow-x-hidden pt-2 group-data-[collapsible=icon]:*:hidden",
            (carried || sorting) && "pointer-events-none"
          )}
          ref={list}
          onScroll={measure}
        >
          <div ref={rows} className="flex flex-1 flex-col gap-4">
            {notice && (
              // Alone in the list's space, so in the middle of it. As wide as the open sidebar, so while it opens the
              // edge uncovers the notice where it ends up, as it does the labels, instead of wrapping it anew each frame. The
              // list is a pixel narrower, for the sidebar's border, and clips that pixel rather than scrolling sideways.
              <p className="m-auto w-(--sidebar-width) shrink-0 px-4 py-2 text-center text-xs text-balance text-muted-foreground">
                {notice}
              </p>
            )}
            {conversations === null && !conversationsFailed && (
              // Delayed as the page starts to avoid flashing on fast loads; opened after that, there at once. Laid out as
              // the list is once in: Projects with a row, then Recents down to the bottom, cut off there as a long list
              // is. No height of its own (h-0), so its rows do not stretch the list and leave the sidebar something to
              // scroll.
              <div
                aria-hidden
                className={cn(
                  "flex h-0 grow flex-col gap-3 overflow-hidden",
                  starting &&
                    "animate-in delay-300 duration-200 ease-(--ease-out) fill-mode-both fade-in"
                )}
              >
                {[
                  { rows: 1, icon: true },
                  // A row and its gap are 34px: as many as the window is tall.
                  { rows: Math.ceil(window.innerHeight / 34), icon: false },
                ].map(({ rows, icon }, group) => (
                  <SidebarGroup
                    key={group}
                    className="py-0 motion-safe:animate-pulse"
                  >
                    <div className="flex h-8 items-center pr-2 pl-row-text">
                      <Skeleton className="h-3 w-12" />
                    </div>
                    <SidebarMenu className="gap-0.5">
                      {Array.from({ length: rows }, (_, index) => (
                        <SidebarMenuItem key={index}>
                          <SidebarMenuSkeleton
                            showIcon={icon}
                            className={cn(
                              "h-8 pointer-coarse:h-10",
                              !icon && "pl-row-text"
                            )}
                          />
                        </SidebarMenuItem>
                      ))}
                    </SidebarMenu>
                  </SidebarGroup>
                ))}
              </div>
            )}
            {/* The projects above the rest, each shut unless the viewer opened it: an eval's runs out of the way of
              the user's own conversations. A new one is made from the heading's button, shown while the heading is
              hovered; with none yet, from a row in their place. */}
            {conversations !== null && (
              <SidebarGroup className="py-0">
                {/* The heading and its button the hover group: hovering a project shows its own buttons, not this. */}
                <div className="group/heading relative">
                  {/* With none yet, nothing to fold away: the row to make one stays. */}
                  <SectionLabel
                    label={t.sidebar.projects}
                    open={!folded.includes("projects")}
                    onOpen={
                      none ? undefined : (open) => setFolded("projects", !open)
                    }
                  />
                  {!none && (
                    <SidebarGroupAction
                      aria-label={t.sidebar.newProject}
                      onClick={() => setCreating(true)}
                      className="top-0 right-0 size-8 text-muted-foreground group-hover/heading:opacity-100 focus-visible:opacity-100 [&>svg]:size-4 [@media(hover:hover)]:opacity-0"
                    >
                      {/* Its class for the 16px line (index.css); the size is the button's. */}
                      <FolderPlusIcon className="size-4" />
                    </SidebarGroupAction>
                  )}
                </div>
                <Collapsible open={!folded.includes("projects")}>
                  <CollapsibleContent className={FOLD}>
                    <SortableContext
                      items={ids}
                      strategy={verticalListSortingStrategy}
                    >
                      <SidebarMenu className="gap-0.5">
                        {projects.map(([project, items]) => (
                          <ProjectGroup
                            key={project}
                            project={project}
                            name={names[project] ?? ""}
                            items={items}
                            open={opened.includes(project)}
                            held={sorting && project === dragged}
                            selected={project === selectedProject}
                            reading={items.findIndex(
                              (conversation) =>
                                conversation.id === openConversation
                            )}
                            onOpen={(open) => setOpened(project, open)}
                            running={items.some(isRunning)}
                            needsYou={items.some(isWaiting)}
                            unread={unreadOf(items).length}
                            failed={unreadOf(items).some(
                              (conversation) => conversation.latest.failed
                            )}
                            onRename={(name) => renameProject(project, name)}
                            onDelete={() => {
                              // Nothing to ask about an empty project: it goes at once.
                              if (items.length === 0 && lists.loaded(project))
                                return void deleteProject(project, items)
                              setCondemned([project, items])
                              setAsking(true)
                            }}
                            leaving={closing.some(([id]) => id === project)}
                            lists={lists}
                          >
                            {items.map((conversation) =>
                              row(conversation, true)
                            )}
                          </ProjectGroup>
                        ))}
                        {none && (
                          <NewProjectRow
                            onCreate={() => setCreating(true)}
                            opening={closing.length > 0}
                          />
                        )}
                      </SidebarMenu>
                    </SortableContext>
                  </CollapsibleContent>
                </Collapsible>
              </SidebarGroup>
            )}
            {/* Also while a conversation is carried out of a project with none left here, to be dropped on. */}
            {(recents.length > 0 ||
              (carried !== null && carried.project !== null)) && (
              <RecentsGroup
                open={!folded.includes("recents")}
                onOpen={(open) => setFolded("recents", !open)}
                lists={lists}
                scroller={list}
              >
                {recents.map((conversation) => row(conversation))}
              </RecentsGroup>
            )}
          </div>
        </SidebarContent>

        {/* Who is signed in, and the settings beside them, where signing out is too. Its hairline shows while more of
            the list is below. */}
        <SidebarFooter className="relative overflow-hidden">
          <span
            aria-hidden
            className={cn(
              "pointer-events-none absolute inset-x-0 top-0 h-px bg-sidebar-border transition-opacity duration-200 ease-(--ease-out) group-data-[collapsible=icon]:hidden motion-reduce:transition-none",
              below ? "opacity-100" : "opacity-0"
            )}
          />
          <SidebarMenu>
            <SidebarMenuItem>
              {/* The circle a size up from the icons above, its middle on theirs and the name where their words begin.
                  As wide as the open sidebar's row while it opens, so its moving edge uncovers the gear where it ends. */}
              <div className="flex items-center md:w-[calc(var(--sidebar-width)-var(--spacing)*4)]">
                <div className="flex h-8 min-w-0 flex-1 items-center gap-2 pl-2 text-sm group-data-[collapsible=icon]:hidden pointer-coarse:h-10">
                  {user && (
                    <>
                      <UserAvatar id={user.id} className="size-6 shrink-0" />
                      <span className="truncate">{user.name}</span>
                    </>
                  )}
                </div>
                <SettingsButton className="group-data-[collapsible=icon]:hidden">
                  <GearIcon className="size-5" />
                </SettingsButton>
                {/* The rail's own, its circle where the one above was, so closing and opening the sidebar swap nothing
                    that shows. Pointed at or focused, the circle blurs and shrinks away while the gear grows in. */}
                <SettingsButton className="group/settings ml-1 hidden group-data-[collapsible=icon]:grid [&>svg]:transition-[opacity,scale,filter] [&>svg]:duration-200 [&>svg]:ease-(--ease-out) motion-reduce:[&>svg]:transition-none">
                  {user && (
                    <UserAvatar
                      id={user.id}
                      className="size-6 group-[:is(:hover,:focus-visible)]/settings:scale-50 group-[:is(:hover,:focus-visible)]/settings:opacity-0 group-[:is(:hover,:focus-visible)]/settings:blur-xs"
                    />
                  )}
                  <GearIcon
                    className={cn(
                      "size-5",
                      user &&
                        "scale-50 opacity-0 blur-xs group-[:is(:hover,:focus-visible)]/settings:scale-100 group-[:is(:hover,:focus-visible)]/settings:opacity-100 group-[:is(:hover,:focus-visible)]/settings:blur-none"
                    )}
                  />
                </SettingsButton>
              </div>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarFooter>
      </ResizableSidebar>
      {/* Outside it too, so ⌘K opens it from anywhere. 新對話 in it puts the caret in the composer, as 新對話 here does. */}
      <SearchDialog
        open={searchOpen}
        onOpenChange={setSearchOpen}
        conversations={conversations ?? []}
        names={names}
        newShortcut={NEW_SHORTCUT}
        onNew={() => {
          searchedNew.current = true
          openRun(null)
          if (isMobile) setOpenMobile(false)
        }}
        onNewProject={() => setCreating(true)}
        onOpen={() => isMobile && setOpenMobile(false)}
        finalFocus={() => {
          const chose = searchedNew.current
          searchedNew.current = false
          const from = searchedFrom.current
          if (!chose && from?.isConnected && from !== document.body) return from
          // Nowhere to go back to: the composer, but not on a phone, where that would raise the keyboard.
          return chose || !isMobile ? (composer.current ?? true) : true
        }}
      />
      {/* Outside the sidebar, which on a phone is a sheet that is gone while closed, so ⌘, opens it from anywhere. */}
      <SettingsDialog status={status} offline={offline} />
      {/* A project's rules, from its menu or a line in the conversation; outside the sheet, as the settings are. */}
      <ProjectMemoryDialog names={names} />
      {/* Outside it too: in its sheet on a phone they would be dialogs within a dialog, which draw no backdrop of their
          own and leave a press outside them to the sheet. */}
      <CreateProjectDialog
        open={creating}
        onOpenChange={(open) => {
          setCreating(open)
          if (!open) setBringing(null)
        }}
        onCreate={async (name) => {
          // Made for a conversation dropped on the new project row: it goes in, and the page stays as it is.
          const brought = bringing
          opensMade.current = brought === null
          const project = await createProject(name)
          if (project === null) return
          if (brought) return void move(brought, project)
          openProject(project)
          if (isMobile) setOpenMobile(false)
        }}
        // Into the new project's composer, to write its first conversation, rather than back to the button that
        // opened it, ringed if that was from the keyboard.
        finalFocus={() => {
          const opened = opensMade.current
          opensMade.current = false
          return opened ? (composer.current ?? true) : true
        }}
      />
      <DeleteProjectDialog
        open={asking}
        project={condemned ? (names[condemned[0]] ?? "") : ""}
        onOpenChange={setAsking}
        onDelete={() => {
          setAsking(false)
          if (condemned)
            void deleteProject(...condemned, lists.loaded(condemned[0]))
        }}
      />
      {/* Over the page, so neither the sidebar nor a list's fold clips it; as tall as its row, not the project, and a
          conversation's chip as wide as its name. A project settles into its place, and a conversation's chip back onto
          its row where nothing took it (HOME); taken, the chip goes at once, as its row leaves its list (dragged is only a
          project's, held until it has landed). The pointer
          passes through it: released on it, outside the phone's sidebar sheet, the drag's click would count as a
          press outside the sheet, and the next click anywhere would close it. */}
      {createPortal(
        <DragOverlay
          className="pointer-events-none"
          dropAnimation={dragged !== null ? DROP : aimed ? null : HOME}
          style={
            carried ? { height: "auto", width: "auto" } : { height: "auto" }
          }
        >
          {carried ? (
            <DraggedConversation name={nameOf(carried)} faint={!aimed} />
          ) : (
            dragged !== null && <DraggedProject name={names[dragged] ?? ""} />
          )}
        </DragOverlay>,
        document.body
      )}
    </DndContext>
  )
}
