import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type ComponentProps,
  type Dispatch,
  type ReactNode,
  type RefObject,
  type SetStateAction,
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
import { runningOf, waitingOf, type Project, type Status } from "@/lib/api"
import { nameOf, type Conversation } from "@/lib/conversations"
import { useT } from "@/lib/i18n"
import { signOut, useSession } from "@/lib/session"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { CHATS_HREF, openProject, openRun, runHref } from "@/lib/route"
import { useChatsOpen } from "@/hooks/use-api"
import {
  ComposeIcon,
  FolderPlusIcon,
  GearIcon,
  SearchIcon,
  SignOutIcon,
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
  DraggedProject,
  NEW_PROJECT,
  RECENTS,
} from "@/components/sidebar/drag"
import { DROP, FOLD, FOLD_DURATION } from "@/components/sidebar/motion"
import { useStoredNames } from "@/hooks/use-stored-names"
import { useSidebarLists } from "@/components/sidebar/use-sidebar-lists"

/** How many recents the sidebar lists; the rest are on the page of every conversation. */
const PAGE = 20

// 設定 opens with ⌘ , (Ctrl , off a Mac), as in most apps; 新增 with ⇧ ⌘ O, as ChatGPT's does: ⌘ N is the
// browser's, for a new window. 搜尋 with ⌘ K, as ChatGPT's.
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
        // As high as a conversation's row, as ChatGPT's commands are. In the closed rail a 32px square under
        // the trigger's middle, so closing the sidebar moves no icon: the margin and padding change together.
        className="h-8 pl-2.5 transition-[width,height,padding,margin] group-data-[collapsible=icon]:ml-1 group-data-[collapsible=icon]:size-8! group-data-[collapsible=icon]:p-1.5! pointer-coarse:h-10"
        {...props}
      >
        {icon}
        {label}
        <Kbd className="ml-auto opacity-0 group-hover/menu-item:opacity-100 group-has-[:focus-visible]/menu-item:opacity-100 group-data-[collapsible=icon]:hidden [@media(hover:none)]:hidden">
          {keys}
        </Kbd>
      </SidebarMenuButton>
    </SidebarMenuItem>
  )
}

// The widths the sidebar can be dragged to.
export const SIDEBAR_MIN = 200
export const SIDEBAR_MAX = 480

export function AppSidebar({
  conversations,
  conversationsFailed,
  status,
  offline,
  openConversation,
  selectedProject,
  isNew,
  width,
  onWidth,
  onDelete,
  onRename,
  onMove,
  projects: made,
  onCreateProject,
  onRenameProject,
  onDeleteProject,
  composer,
}: {
  composer: RefObject<HTMLTextAreaElement | null> // where 新增 puts the caret
  conversations: Conversation[] | null
  conversationsFailed: boolean // the list could not be loaded; it loads on its own once the runtime is back
  status: Status | null
  offline: boolean
  openConversation: string | null
  selectedProject: string | null // the project whose home is open
  isNew: (conversation: string, ended: number | null) => boolean // its latest run's end is news to the user
  width: number
  onWidth: Dispatch<SetStateAction<number>>
  // Deletes one conversation, or a project's (`project`): true once every one is.
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
  const { isMobile, setOpenMobile, state } = useSidebar()
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [searchOpen, setSearchOpen] = useState(false)
  const { user, login } = useSession()
  const searchedNew = useRef(false) // 新增 chosen in the search, which hands the focus to the composer as it closes
  // 新增 puts the caret in the composer, as ChatGPT's New chat does, also on the page it is already on (where the
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
  const land = (project: string) =>
    setTimeout(
      () => setDragged((held) => (held === project ? null : held)),
      DROP.duration + FOLD_DURATION
    )
  // The conversation being carried onto a project or out to the recents, until it is dropped.
  const [carried, setCarried] = useState<Conversation | null>(null)
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
  const chatsOpen = useChatsOpen()
  const [scrolled, setScrolled] = useState(false) // the list scrolled down from its top
  const [below, setBelow] = useState(false) // more of the list below, under the account row
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
        setSettingsOpen(true)
      } else if (isShortcut(event, SEARCH_SHORTCUT)) {
        event.preventDefault()
        setSearchOpen((open) => !open)
      } else if (isShortcut(event, NEW_SHORTCUT)) {
        event.preventDefault()
        openRun(null)
        // As 新增 does: also on the page it is already on.
        composer.current?.focus()
      }
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [composer])

  const waitingRun = waitingOf(status)?.run
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
  // The first page of recents. A copy closing up where it was is not counted: the next one comes in under the page,
  // opening as the copy closes (entering), so the list keeps its length. Only the rows between move; those above and
  // the All chats link stay put, rather than the link dropping a row and sliding back, or at the end of the list's
  // scroll the rows above sliding down and back up.
  const staying = recents.filter((conversation) => !left.includes(conversation))
  const page =
    staying.length > PAGE
      ? recents.slice(0, recents.indexOf(staying[PAGE]))
      : recents
  const closingUp = page.length - Math.min(staying.length, PAGE)
  const entering = staying.slice(PAGE - closingUp, PAGE)
  const row = (conversation: Conversation, inset = false) => (
    <ConversationItem
      key={conversation.id}
      conversation={conversation}
      inset={inset}
      // The copy left behind closes up; the conversation itself opens where it went, as one coming into the page does.
      moving={
        left.includes(conversation)
          ? "out"
          : left.some((each) => each.id === conversation.id) ||
              entering.includes(conversation)
            ? "in"
            : undefined
      }
      active={runningOf(status, { thread: conversation.id }) !== null}
      needsYou={conversation.runs.some((run) => run.id === waitingRun)}
      fresh={isNew(conversation.id, conversation.latest.ended)}
      selected={conversation.id === openConversation}
      projects={choices}
      onDelete={remove}
      onRename={onRename}
      onMove={move}
      onNewProject={bringIn}
    />
  )

  // In place of the list: why there is none. With none yet, the sidebar says nothing, as ChatGPT's does.
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
        if (conversation) setCarried(conversation)
        else {
          setDragged(String(active.id))
          setSorting(true)
        }
      }}
      onDragCancel={({ active }) => {
        grab(false)
        setCarried(null)
        setSorting(false)
        land(String(active.id))
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
        land(String(active.id))
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
      {/* Closed, it narrows to a rail of its toggle, 新增 and 搜尋, with the account's circle at its foot, each named
          on hover. Open or closed, they stay in one column, their 20px icons centred 28px from the left edge. */}
      <Sidebar collapsible="icon" finalFocus={sheetFocus}>
        {/* The toggle sits on the page header's line: its center 24px from the top, like the header's buttons. In the
            closed rail it is a 32px square like the commands under it, so their tooltips and hover marks line up; the
            margins keep its icon, and the rows under it, where they were. */}
        {/* New and the settings above the list, as ChatGPT's sidebar keeps its commands. A hairline under them shows
            while the list is scrolled, fading in and out, so the top of the list reads as passing under them. */}
        <SidebarHeader className="relative pt-1 pb-2">
          <SidebarTrigger className="size-10 transition-[width,height,margin] duration-300 ease-(--ease-drawer) group-data-[collapsible=icon]:my-1 group-data-[collapsible=icon]:ml-1 group-data-[collapsible=icon]:size-8" />
          <SidebarMenu className="gap-0.5">
            <ShortcutItem
              icon={<ComposeIcon />}
              label={t.sidebar.new}
              shortcut={NEW_SHORTCUT}
              isActive={!openConversation && !selectedProject && !chatsOpen}
              render={<a href={runHref(null)} />}
              onClick={onNew}
            />
            <ShortcutItem
              icon={<SearchIcon />}
              label={t.sidebar.search}
              shortcut={SEARCH_SHORTCUT}
              onClick={() => setSearchOpen(true)}
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
              // Delay the placeholder to avoid flashing on fast loads; share one shimmer across both groups. Laid out as the
              // list is once in: Projects with a row, then Recents down to the bottom, cut off there as a long list is.
              <div
                aria-hidden
                className="@container flex min-h-0 flex-1 animate-in flex-col gap-3 overflow-hidden delay-300 duration-200 ease-(--ease-out) fill-mode-both fade-in"
              >
                {[
                  { rows: 1, icon: true },
                  { rows: 30, icon: false },
                ].map(({ rows, icon }, group) => (
                  <SidebarGroup key={group} className="py-0">
                    <div className="flex h-8 items-center px-2">
                      <Skeleton className="h-3 w-12 [--at:16px]" />
                    </div>
                    <SidebarMenu className="gap-0.5">
                      {Array.from({ length: rows }, (_, index) => (
                        <SidebarMenuItem key={index}>
                          <SidebarMenuSkeleton
                            showIcon={icon}
                            className="h-8 [--row-at:8px] pointer-coarse:h-10"
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
              hovered; with none yet, from a row in their place, as ChatGPT lists New project under
              its Projects. */}
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
                            unread={unreadOf(items).length}
                            failed={unreadOf(items).some(
                              (conversation) => conversation.latest.failed
                            )}
                            onRename={(name) => renameProject(project, name)}
                            onDelete={() => {
                              // Nothing to ask about an empty project: it goes at once.
                              if (items.length === 0)
                                return void deleteProject(project, items)
                              setCondemned([project, items])
                              setAsking(true)
                            }}
                            leaving={closing.some(([id]) => id === project)}
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
              >
                <SidebarMenu className="gap-0.5">
                  {page.map((conversation) => row(conversation))}
                  {/* The rest are on a page of their own, linked as a project's Show more is drawn: muted, to the left. */}
                  {staying.length > PAGE && (
                    <SidebarMenuItem>
                      <SidebarMenuButton
                        className="h-8 text-muted-foreground pointer-coarse:h-10"
                        isActive={chatsOpen}
                        render={<a href={CHATS_HREF} />}
                        onClick={() => isMobile && setOpenMobile(false)}
                      >
                        {t.sidebar.viewAll}
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                  )}
                </SidebarMenu>
              </RecentsGroup>
            )}
          </div>
        </SidebarContent>

        {!isMobile && state === "expanded" && (
          <ResizeHandle
            from="left"
            width={width}
            min={SIDEBAR_MIN}
            max={SIDEBAR_MAX}
            onWidth={onWidth}
            label={t.sidebar.resize}
            className="-right-1.5"
          />
        )}
        {/* Who is signed in, as ChatGPT's account row, opening a menu of the settings and signing out; the gear and 設定
            while the runtime has not said who. Its hairline shows while more of the list is below. */}
        <SidebarFooter className="relative">
          <span
            aria-hidden
            className={cn(
              "pointer-events-none absolute inset-x-0 top-0 h-px bg-sidebar-border transition-opacity duration-200 ease-(--ease-out) group-data-[collapsible=icon]:hidden motion-reduce:transition-none",
              below ? "opacity-100" : "opacity-0"
            )}
          />
          <SidebarMenu>
            <SidebarMenuItem>
              <DropdownMenu>
                <DropdownMenuTrigger
                  render={
                    <SidebarMenuButton
                      tooltip={user?.name ?? t.settings.title}
                      className="h-8 pl-2.5 transition-[width,height,padding,margin] group-data-[collapsible=icon]:ml-1 group-data-[collapsible=icon]:size-8! group-data-[collapsible=icon]:p-1.5! data-popup-open:bg-sidebar-accent pointer-coarse:h-10"
                    />
                  }
                >
                  {user ? (
                    <UserAvatar id={user.id} className="size-5 shrink-0" />
                  ) : (
                    <GearIcon />
                  )}
                  <span className="truncate">
                    {user?.name ?? t.settings.title}
                  </span>
                </DropdownMenuTrigger>
                {/* Above the row, from its start, as ChatGPT's account menu opens. */}
                <DropdownMenuContent
                  side="top"
                  align="start"
                  className="min-w-56"
                >
                  <DropdownMenuItem onClick={() => setSettingsOpen(true)}>
                    <GearIcon />
                    {t.settings.title}
                    {/* No keyboard to press it on a touch screen. */}
                    <Kbd className="ml-auto pointer-coarse:hidden">
                      {shortcutLabel(SETTINGS_SHORTCUT)}
                    </Kbd>
                  </DropdownMenuItem>
                  {login === "token" && (
                    <DropdownMenuItem onClick={() => void signOut()}>
                      <SignOutIcon />
                      {t.sidebar.signOut}
                    </DropdownMenuItem>
                  )}
                </DropdownMenuContent>
              </DropdownMenu>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarFooter>
      </Sidebar>
      {/* Outside it too, so ⌘K opens it from anywhere. 新增 in it puts the caret in the composer, as 新增 here does. */}
      <SearchDialog
        open={searchOpen}
        onOpenChange={setSearchOpen}
        conversations={conversations ?? []}
        onNew={() => {
          searchedNew.current = true
          openRun(null)
          if (isMobile) setOpenMobile(false)
        }}
        onOpen={() => isMobile && setOpenMobile(false)}
        finalFocus={() => {
          const chose = searchedNew.current
          searchedNew.current = false
          return chose ? (composer.current ?? true) : true
        }}
      />
      {/* Outside the sidebar, which on a phone is a sheet that is gone while closed, so ⌘, opens it from anywhere. */}
      <SettingsDialog
        open={settingsOpen}
        onOpenChange={setSettingsOpen}
        status={status}
        offline={offline}
      />
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
        count={condemned?.[1].length ?? 0}
        onOpenChange={setAsking}
        onDelete={() => {
          setAsking(false)
          if (condemned) void deleteProject(...condemned)
        }}
      />
      {/* Over the page, so neither the sidebar nor a list's fold clips it; as tall as its row, not the project, and a
          conversation's chip as wide as its name. A project settles into its place; a conversation's chip goes at
          once, as its row leaves the recents (dragged is only a project's, held until it has landed). The pointer
          passes through it: released on it, outside the phone's sidebar sheet, the drag's click would count as a
          press outside the sheet, and the next click anywhere would close it. */}
      {createPortal(
        <DragOverlay
          className="pointer-events-none"
          dropAnimation={dragged === null ? null : DROP}
          style={
            carried ? { height: "auto", width: "auto" } : { height: "auto" }
          }
        >
          {carried ? (
            <DraggedConversation name={nameOf(carried)} />
          ) : (
            dragged !== null && <DraggedProject name={names[dragged] ?? ""} />
          )}
        </DragOverlay>,
        document.body
      )}
    </DndContext>
  )
}
