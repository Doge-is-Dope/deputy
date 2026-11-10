import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react"
import { cn } from "cn"
import { toast } from "sonner"

import { AppSidebar } from "@/components/sidebar/app-sidebar"
import { Composer } from "@/components/composer/composer"
import { LiveView } from "@/components/desktop/live-view"
import { RunView, type AskedQuestion } from "@/components/conversation/run-view"
import { ENTER_KEY } from "@/lib/keys"
import { preloadMarkdown } from "@/components/markdown/markdown"
import { Button } from "@/components/ui/button"
import { Toaster } from "@/components/ui/sonner"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import {
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { useConversations, useStatus, useThreadRuns } from "@/hooks/use-api"
import { useOpenProject, useOpenRun } from "@/hooks/use-route"
import { Notice, notify } from "@/components/notice"
import { NEW_TASK, setDraft } from "@/hooks/use-drafts"
import { useConversationActions } from "@/hooks/use-conversation-actions"
import { useSeen } from "@/hooks/use-seen"
import { useIsMobile } from "@/hooks/use-mobile"
import { useStoredWidth } from "@/hooks/use-stored-width"
import { ResizeHandle } from "@/components/resize-handle"
import { runningOf, waitingOf } from "@/lib/api"
import { conversationOf, nameOf } from "@/lib/conversations"
import { connectionOf, greeting } from "@/lib/format"
import { useT } from "@/lib/i18n"
import { HandIcon, MonitorIcon, PlanIcon, TrashIcon } from "@/components/icons"

// The banner that another conversation waits for the user: one wait at a time, as one run at a time has the desktop.
const WAITING_NOTICE = "waiting"
/** Capture the greeting time on mount so it stays stable while the page is open. */
function Greeting() {
  useT()
  const [since] = useState(() => new Date())
  return (
    <h2 className="mb-7 text-center text-2xl tracking-tight">
      {greeting(since)}
    </h2>
  )
}

// Narrowest, the stage (less the panel's border and its padding, 2.5rem) still holds the control pill with its label
// (~320px in English: 「Your agent has control」 and 「Take over」) with room either side; it is never so narrow that
// the pill keeps only its button (live-view.tsx). Expand for a larger view.
const LIVE_MIN = 384
const LIVE_MAX = 640
const MAIN_MIN = 560
// How long a deleted conversation's notice offers 還原 before the runtime is asked to erase it.
const UNDO_MS = 5000

export default function App() {
  const say = useT()
  const {
    status,
    offline,
    refresh: refreshStatus,
    confirmControl,
  } = useStatus()
  // Changes whenever a run starts or ends anywhere, or names its conversation, which the list then shows by its name
  // in a second or two, not once the run ends; a new list from every poll would not do. Null until the runtime first
  // answers, so the lists load once, and while it can't be reached: once it can again, a list it couldn't give
  // meanwhile loads.
  const listsChanged =
    offline || !status
      ? null
      : `${status.titles_revision}:${status.running.map((each) => each.run).join()}`
  const {
    conversations,
    projects,
    failed: conversationsFailed,
    refresh: refreshConversations,
    lists,
  } = useConversations(
    listsChanged,
    status?.running.map((each) => each.thread) ?? []
  )
  // The address names a conversation by its first run, or by any of its runs (an older link).
  const [opened, open] = useOpenRun()
  const project = useOpenProject() // whose home is open: a new conversation begins in it
  // The open conversation's runs come on their own: the lists hold a page of each, which it may be beyond.
  const {
    thread: openedThread,
    runs: threadRuns,
    turns: threadTurns,
    logs: threadLogs,
    listed,
  } = useThreadRuns(opened, listsChanged)
  const thread = openedThread ?? opened
  // From the lists, or from its own runs when it is beyond the pages they hold (one opened from search).
  const conversation =
    conversations?.find((each) => each.id === thread) ??
    conversationOf(threadTurns ?? []) ??
    undefined
  // A run that carries on the one before it with the same goal (「從這裡繼續」) does not repeat that goal.
  const continued = useMemo(
    () =>
      new Set(
        threadRuns
          ?.filter(
            (run, index, all) => index > 0 && run.goal === all[index - 1].goal
          )
          .map((run) => run.id)
      ),
    [threadRuns]
  )
  // Each conversation keeps its own draft, which its composer reads and writes.
  const draftKey = thread ?? NEW_TASK
  // Desktop panel and mobile sheet start closed; takeover opens the active view.
  const [panelOpen, setPanelOpen] = useState(false)
  const [sheetOpen, setSheetOpen] = useState(false)
  const isMobile = useIsMobile()
  // Both side panels can be dragged wider or narrower; this browser remembers the widths.
  const [sidebarWidth, setSidebarWidth] = useStoredWidth("sidebar-width", 256)
  const [liveWidth, setLiveWidth] = useStoredWidth("live-view-width", 520)
  // The panel never takes more than the page can spare beside the conversation, even after the window shrinks.
  const area = useRef<HTMLDivElement>(null)
  const [areaWidth, setAreaWidth] = useState(0)
  useEffect(() => {
    const element = area.current
    if (!element) return
    const observer = new ResizeObserver(([entry]) =>
      setAreaWidth(entry.contentRect.width)
    )
    observer.observe(element)
    return () => observer.disconnect()
  }, [])
  const liveMax = areaWidth
    ? Math.max(LIVE_MIN, Math.min(LIVE_MAX, areaWidth - MAIN_MIN))
    : LIVE_MAX
  // A width stored before the minimum rose is shown at the minimum.
  const liveShown = Math.max(LIVE_MIN, Math.min(liveWidth, liveMax))
  // Expanded, the live view fills the page's middle, over the conversation. Where the page can't spare the
  // conversation its width beside the narrowest panel, the panel covers it so, and closes as the sheet on a phone does.
  const [expanded, setExpanded] = useState(false)
  const cramped = areaWidth > 0 && areaWidth < MAIN_MIN + LIVE_MIN
  const covering = expanded || cramped
  const liveOpen = isMobile ? sheetOpen : panelOpen
  const setLiveOpen = isMobile ? setSheetOpen : setPanelOpen
  // Taking over from the composer or a notice opens the live view with the keyboard on the desktop; the live view says
  // once it is (or it closes first).
  const [focusScreen, setFocusScreen] = useState(false)
  if (focusScreen && !liveOpen) setFocusScreen(false)

  const {
    input,
    current,
    takesMessages,
    approval,
    steering,
    queued,
    handover,
    asking,
    started,
    start,
    stop,
    withdraw,
    remove,
    rename,
    move,
    createProject,
    renameProject,
    deleteProject,
    setControl,
    takeOver,
    skip,
    answer,
  } = useConversationActions({
    thread,
    project,
    status,
    isMobile,
    liveOpen,
    open,
    showLive: (focus = false) => {
      setLiveOpen(true)
      if (focus) setFocusScreen(true)
    },
    refreshStatus,
    confirmControl,
    refreshConversations,
  })
  // A conversation just started may not be read yet: its first run is all there is; a run started here comes in at once,
  // before the list has it. Kept while the conversation is the same, as is all the conversation is handed below: a new
  // copy on every keystroke or poll would draw each of its turns again.
  // The session in progress comes in as soon as the status lists it, as one the runtime started with a message queued
  // for it: before the list has it, and with the message it began with.
  const session = thread === null ? null : runningOf(status, { thread })
  const sessionRun = session?.run ?? null
  const sessionGoal = session?.goal ?? null
  const turns = useMemo(() => {
    const runs = threadRuns?.map((run) => run.id) ?? (opened ? [opened] : [])
    const late = [
      ...(started?.thread === thread ? [started.run] : []),
      ...(sessionRun ? [sessionRun] : []),
    ]
    const missing = late.filter(
      (run, index) => !runs.includes(run) && late.indexOf(run) === index
    )
    return missing.length ? [...runs, ...missing] : runs
  }, [threadRuns, opened, started, thread, sessionRun])
  // What the user sent each run, drawn before its log comes.
  const goals = useMemo(
    () =>
      new Map([
        ...(sessionRun && sessionGoal
          ? [[sessionRun, sessionGoal] as const]
          : []),
        ...(threadRuns ?? []).map((run) => [run.id, run.goal] as const),
        ...(started ? [[started.run, started.goal] as const] : []),
      ]),
    [threadRuns, started, sessionRun, sessionGoal]
  )
  // The sessions the list says are still going, which may come before the status lists them.
  const going = useMemo(
    () =>
      new Set(
        (threadRuns ?? [])
          .filter((run) => run.ended === null)
          .map((run) => run.id)
      ),
    [threadRuns]
  )
  // The run started here counts as just started until the list has it and it is no longer in progress; opened again
  // after, it waits for its log.
  const fresh =
    started &&
    (runningOf(status, { run: started.run }) !== null ||
      !threadRuns?.some((run) => run.id === started.run))
      ? started.run
      : null
  const running = current !== null
  const projectName = (id: string) =>
    projects?.find((each) => each.id === id)?.name
  const userHasControl = status?.control.owner === "user"
  const connection = connectionOf(status, offline)

  // The live view button lights up in the takeover color while the user has the desktop, which they are to hand back.
  // The agent having it is the usual state, so it is the plain icon; and nobody has a desktop that can't be reached.
  const yours = !!connection?.connected && userHasControl
  // Other conversations go on while one uses the desktop; only a service that can't be reached stops a message.
  const blocked = offline ? say.home.blockedOffline : null
  // Use the conversation title; a dot marks any run waiting for user input.
  const title = conversation && nameOf(conversation)
  const waiting = waitingOf(status)
  const someoneWaits = waiting !== null
  useEffect(() => {
    const name = title || "Computer Use"
    document.title = someoneWaits ? `● ${name}` : name
  }, [title, someoneWaits])

  // The open conversation is seen as far as its latest run has gone while the page is in view: as it opens, as that
  // run ends, and as the page comes back to the front. The sidebar marks the others' replies and failures till then.
  const { isNew, markSeen } = useSeen(conversations)
  const seenUntil = conversation
    ? (conversation.latest.ended ?? conversation.latest.started)
    : null
  useEffect(() => {
    if (!thread || seenUntil === null) return
    const mark = () => {
      if (document.visibilityState === "visible") markSeen(thread, seenUntil)
    }
    mark()
    document.addEventListener("visibilitychange", mark)
    return () => document.removeEventListener("visibilitychange", mark)
  }, [thread, seenUntil, markSeen])

  // Notify once for waits in other conversations. Dismiss on opening or when the wait ends.
  const waitingId = waiting?.id ?? null
  const waitingThread = waiting
    ? (runningOf(status, { run: waiting.run })?.thread ?? null)
    : null
  const waitingFor = !waiting
    ? null
    : waiting.for === "approval"
      ? say.home.waitingApproval
      : say.run.agentAsks
  const waitingTakeover = waiting?.for === "takeover"
  // A notice names the conversation it is about, its icon saying what happened there; the words say it only while the
  // list doesn't have that conversation yet, and to a screen reader.
  const nameIn = useCallback(
    (thread: string) => {
      const found = conversations?.find((each) => each.id === thread)
      return found ? nameOf(found) : null
    },
    [conversations]
  )
  const announced = useRef<string | null>(null)
  useEffect(() => {
    if (!waitingId || !waitingThread || !waitingFor) {
      toast.dismiss(WAITING_NOTICE)
      return
    }
    if (waitingThread === thread) {
      announced.current = waitingId
      toast.dismiss(WAITING_NOTICE)
      return
    }
    if (announced.current === waitingId) return
    announced.current = waitingId
    // A takeover is done on the desktop, so its button opens that too, as the composer's 「接管」 would; a step to
    // approve is asked in the conversation, or over a live view that covers it.
    notify(
      {
        icon: (
          <HandIcon
            role="img"
            aria-hidden={false}
            aria-label={waitingFor}
            className="size-5 shrink-0 text-warning"
          />
        ),
        text: nameIn(waitingThread) ?? waitingFor,
        action: waitingTakeover
          ? say.liveView.takeOver
          : say.home.openConversation,
        onAction: () => {
          open(waitingThread)
          if (waitingTakeover) {
            if (isMobile) setSheetOpen(true)
            else setPanelOpen(true)
            setFocusScreen(true)
          }
        },
      },
      { id: WAITING_NOTICE }
    )
  }, [
    waitingId,
    waitingThread,
    waitingFor,
    waitingTakeover,
    isMobile,
    thread,
    say,
    open,
    nameIn,
  ])

  // Notify once when another conversation ends; ignore runs completed before page load.
  const inProgress = status?.running
  const ran = useRef<Map<string, string> | null>(null)
  useEffect(() => {
    if (!inProgress) return
    const now = new Map(inProgress.map((each) => [each.run, each.thread]))
    const before = ran.current
    ran.current = now
    if (!before) return
    for (const [run, ended] of before) {
      if (now.has(run) || ended === thread) continue
      notify(
        {
          // The dot the sidebar marks a new reply with.
          icon: (
            <span className="flex size-5 shrink-0 items-center justify-center">
              <span
                role="img"
                aria-label={say.home.replied}
                className="size-2 rounded-full bg-unread"
              />
            </span>
          ),
          text: nameIn(ended) ?? say.home.replied,
          action: say.home.openConversation,
          onAction: () => {
            open(ended)
            // On a phone the live view covers the conversation, where the reply is.
            setSheetOpen(false)
          },
        },
        { id: `replied-${run}` }
      )
    }
  }, [inProgress, thread, say, open, nameIn])

  // Delay permanent deletion until the undo notice closes. Undo reopens the active conversation.
  // Project deletion includes conversations not yet loaded in the sidebar. Resolves true on success.
  const deleteConversations = (ids: string[], projectId: string | null) =>
    new Promise<boolean>((resolve) => {
      const previouslyOpen =
        thread !== null &&
        (ids.includes(thread) ||
          (projectId !== null && conversation?.project === projectId))
          ? thread
          : null
      if (previouslyOpen !== null) open(null)
      let undone = false
      let settled = false
      const settle = async () => {
        if (settled) return
        settled = true
        if (undone) return resolve(false)
        if (projectId !== null)
          return resolve((await deleteProject(projectId)) !== null)
        const deleted = await Promise.all(ids.map((each) => remove(each)))
        resolve(deleted.every(Boolean))
      }
      toast.custom(
        (id) => (
          <Notice
            icon={<TrashIcon aria-hidden className="size-5 shrink-0" />}
            text={
              projectId === null
                ? say.sidebar.deleted
                : say.sidebar.deletedProject(projectName(projectId) ?? "")
            }
            action={say.sidebar.restore}
            // The close button settles immediately; Sonner also reports swipes through onDismiss.
            onDismiss={() => {
              toast.dismiss(id)
              settle()
            }}
            onAction={() => {
              undone = true
              toast.dismiss(id)
              if (previouslyOpen !== null) open(previouslyOpen)
              settle()
            }}
          />
        ),
        {
          id:
            projectId === null
              ? `deleted-${ids[0]}`
              : `deleted-project-${projectId}`,
          className: "w-full",
          duration: UNDO_MS,
          onAutoClose: settle,
          onDismiss: settle,
        }
      )
    })

  // The question the main agent asked, while it is open.
  const [asked, setAsked] = useState<AskedQuestion | null>(null)
  // A touch screen's options are tapped; a narrow window on a computer still has Enter.
  const hasKeyboard = window.matchMedia("(pointer: fine)").matches
  const recommended = hasKeyboard ? (asked?.recommended ?? null) : null
  const many = hasKeyboard && asked?.multiple === true

  const takeover = asking && {
    text: say.composer.takeover.ask(asking.reason),
    onTakeOver: takeOver,
    onSkip: skip,
  }

  const composer = (
    <Composer
      draftKey={draftKey}
      onSubmit={(goal, queue) => {
        void preloadMarkdown()
        return start(goal, queue)
      }}
      // Unread messages continue in the next run.
      onStop={stop}
      running={running}
      takesMessages={takesMessages}
      blocked={blocked}
      handover={handover}
      approval={approval}
      onAnswer={answer}
      takeover={takeover}
      choice={
        (recommended !== null || many) && !approval
          ? {
              accept: async () => {
                if (recommended !== null) return start(recommended)
                document
                  .querySelector<HTMLElement>("[data-question-send]")
                  ?.click()
                return true
              },
              browse: () =>
                [
                  ...document.querySelectorAll<HTMLElement>(
                    "[data-question-option]"
                  ),
                ]
                  .at(-1)
                  ?.focus(),
            }
          : null
      }
      queued={queued}
      onWithdraw={withdraw}
      // A project's home is headed by its name already, and the home by the greeting's question.
      placeholder={
        approval
          ? say.composer.approval.placeholder
          : many
            ? say.run.question.pressEnterMany(ENTER_KEY)
            : recommended !== null
              ? say.run.question.pressEnter(ENTER_KEY)
              : asked !== null
                ? asked.placeholder || say.run.question.placeholder
                : thread
                  ? say.home.placeholderNext
                  : say.home.placeholderNew
      }
      autoFocus={!thread}
      ref={input}
    />
  )

  const liveView = (
    <LiveView
      status={status}
      offline={offline}
      onTakeover={() => setControl("user")}
      onReturn={() => setControl("agent")}
      focusScreen={focusScreen}
      onScreenFocused={() => setFocusScreen(false)}
      approval={approval}
      onAnswer={answer}
      {...(isMobile || cramped
        ? { onClose: () => setLiveOpen(false) }
        : { expanded, onExpand: () => setExpanded((value) => !value) })}
      className="size-full"
    />
  )
  // The conversation's plan, as its view reports it: shown beside the conversation unless hidden, or opened over it.
  const [plan, setPlan] = useState({ has: false, docked: true })
  const [planHidden, setPlanHidden] = useState(false)
  const [planOpen, setPlanOpen] = useState(false)
  // Another conversation has a plan of its own, or none: until its view says, none, and none opened over it.
  const [planOf, setPlanOf] = useState(thread)
  if (planOf !== thread) {
    setPlanOf(thread)
    setAsked(null)
    setPlan({ has: false, docked: plan.docked })
    setPlanOpen(false)
  }
  // Opened over the conversation, it closes once the run being read has none: scrolling back does not open it again.
  if (planOpen && !plan.has) setPlanOpen(false)
  const planShown = plan.docked ? !planHidden : planOpen
  const closePlan = useCallback(() => setPlanOpen(false), [])
  // Always the latest `start`, under a name that stays the same: a new one would draw every turn again.
  const starting = useRef(start)
  useEffect(() => {
    starting.current = start
  })
  const reply = useCallback((text: string) => starting.current(text), [])
  // A question asked brings the cursor to the composer, unless the user is typing somewhere else. A phone's keyboard
  // would cover the question.
  const questioned = asked !== null
  useEffect(() => {
    if (questioned && hasKeyboard && document.activeElement === document.body)
      input.current?.focus()
  }, [questioned, hasKeyboard, input])
  // The status says at once the run is no longer running, which changes the lists (listsChanged). Replaying an ended
  // run, as opening one does, ends its stream too, and asks the lists for nothing.
  const onRunEnded = refreshStatus
  // What was sent to steer the session in progress, which its turn shows where it goes.
  const steered = useMemo(
    () => (current === null ? null : { run: current, messages: steering }),
    [current, steering]
  )
  const openLive = useCallback(() => setLiveOpen(true), [setLiveOpen])
  const showPanel = !isMobile && panelOpen
  // The panel slides in from the window's edge and back out, as the sidebar does. Closed, it stays mounted until it
  // is out of sight, then goes; opened again on its way out, it turns back from where it is.
  const panel = useRef<HTMLDivElement>(null)
  const [panelMounted, setPanelMounted] = useState(false)
  if (showPanel && !panelMounted) setPanelMounted(true)
  const panelClosing = panelMounted && !showPanel
  useEffect(() => {
    if (!panelClosing) return
    let closing = true
    const sliding = panel.current?.getAnimations() ?? []
    Promise.all(sliding.map((animation) => animation.finished)).then(
      () => closing && setPanelMounted(false),
      () => {}
    )
    return () => {
      closing = false
    }
  }, [panelClosing])

  return (
    <SidebarProvider
      style={{ "--sidebar-width": `${sidebarWidth}px` } as CSSProperties}
    >
      <AppSidebar
        width={sidebarWidth}
        onWidth={setSidebarWidth}
        conversations={conversations}
        conversationsFailed={conversationsFailed}
        lists={lists}
        status={status}
        offline={offline}
        openConversation={thread}
        selectedProject={project}
        isNew={isNew}
        onDelete={deleteConversations}
        onRename={rename}
        onMove={move}
        projects={projects}
        onCreateProject={createProject}
        onRenameProject={renameProject}
        onDeleteProject={deleteProject}
        composer={input}
      />
      <SidebarInset className="h-svh min-w-0 overflow-hidden">
        <div ref={area} className="relative flex min-h-0 flex-1">
          {/* On a phone, the sidebar is a sheet with no rail to open it from, so its toggle is here, where the header
            would hold it. Elsewhere it is at the top of the sidebar. */}
          {isMobile && (
            <SidebarTrigger className="absolute top-1.5 left-2.5 z-20" />
          )}
          {/* Beside the panel, which covers it when expanded or cramped: it keeps its width then, so nothing reflows. It
            draws the divider while covered, so the panel sweeps over the line when it expands rather than carrying it
            along. */}
          <div
            data-slot="live-gap"
            className={cn(
              "flex min-w-0 flex-1 flex-col transition-[margin-right] duration-300 ease-(--ease-drawer) motion-reduce:transition-none",
              panelMounted && covering && "border-r"
            )}
            style={{ marginRight: showPanel ? liveShown : 0 }}
            inert={showPanel && covering}
          >
            <header className="flex h-12 shrink-0 items-center gap-2 px-2.5">
              {/* Over the panel, so it fades out there as the panel covers it rather than being cut by its edge, and
                back in near the end as the panel shrinks away. Only while the panel is shown: closed, a narrow window
                still needs the toggle to open it. */}
              <div
                className={cn(
                  "relative z-20 ml-auto flex items-center gap-2 transition-[opacity,filter,scale] ease-(--ease-out)",
                  showPanel && covering
                    ? "pointer-events-none scale-95 opacity-0 blur-[2px] duration-150 motion-reduce:scale-100 motion-reduce:blur-none"
                    : "delay-150 duration-200"
                )}
              >
                {/* The plan, once the main agent has written one: shown beside the conversation until hidden here, or
                  opened over it from here where there is no room. */}
                {thread && plan.has && (
                  <Tooltip>
                    <TooltipTrigger
                      render={
                        <Button
                          data-plan-toggle=""
                          variant={planShown ? "secondary" : "ghost"}
                          size="icon"
                          aria-label={say.run.plan}
                          aria-pressed={planShown}
                          className="transition-[opacity,scale,background-color] duration-200 ease-(--ease-out) starting:scale-90 starting:opacity-0"
                          onClick={() =>
                            plan.docked
                              ? setPlanHidden(!planHidden)
                              : setPlanOpen(!planOpen)
                          }
                        />
                      }
                    >
                      <PlanIcon className="size-5" />
                    </TooltipTrigger>
                    <TooltipContent>
                      {planShown ? say.home.hidePlan : say.home.showPlan}
                    </TooltipContent>
                  </Tooltip>
                )}
                <Tooltip>
                  <TooltipTrigger
                    render={
                      <Button
                        variant={liveOpen ? "secondary" : "ghost"}
                        size="icon"
                        aria-label={
                          connection
                            ? say.home.liveViewWith(connection.label)
                            : say.home.liveView
                        }
                        aria-pressed={liveOpen}
                        onClick={() => {
                          if (liveOpen) setExpanded(false)
                          setLiveOpen(!liveOpen)
                        }}
                      />
                    }
                  >
                    <span className="relative size-5 shrink-0">
                      <MonitorIcon
                        className={cn(
                          "size-5",
                          // Its screen lit in the same color, so it shows at a glance; the stand's lines have no inside.
                          yours &&
                            "text-takeover-glow [fill-opacity:0.22] dark:[fill-opacity:0.3]",
                          // Cut out the lines around the dot so the button's own background shows through.
                          connection &&
                            "[mask-image:radial-gradient(circle_at_80%_20%,transparent_6px,black_6.5px)]"
                        )}
                        style={yours ? { fill: "currentColor" } : undefined}
                      />
                      {connection && (
                        <span
                          aria-hidden
                          className={cn(
                            "absolute top-0 right-0 size-2 rounded-full",
                            connection.connected
                              ? "bg-success"
                              : "bg-destructive"
                          )}
                        />
                      )}
                    </span>
                  </TooltipTrigger>
                  <TooltipContent>
                    {liveOpen ? say.home.hideLiveView : say.home.showLiveView}
                  </TooltipContent>
                </Tooltip>
              </div>
            </header>

            {thread ? (
              <RunView
                key={thread}
                thread={thread}
                runs={turns}
                logs={threadLogs}
                goals={goals}
                going={going}
                started={fresh}
                continued={continued}
                listed={listed}
                status={status}
                asking={asking?.run ?? null}
                steering={steered}
                offline={offline}
                composer={composer}
                onEnded={onRunEnded}
                onOpenLive={openLive}
                onReply={reply}
                onAsked={setAsked}
                planShown={planShown}
                onPlan={setPlan}
                onClosePlan={closePlan}
              />
            ) : (
              <div className="flex min-h-0 flex-1 flex-col items-center justify-center overflow-y-auto px-4 pb-[10vh]">
                {/* A project's home is headed by its name, with no suggestions: what is begun here
                    is the project's own. */}
                {project ? (
                  <h2 className="mb-7 text-center text-2xl tracking-tight">
                    {projectName(project)}
                  </h2>
                ) : (
                  <Greeting />
                )}
                <div className="w-full max-w-3xl">{composer}</div>
                <div className="mt-5 flex max-w-3xl flex-wrap justify-center gap-2">
                  {!project &&
                    say.home.suggestions.map((suggestion) => (
                      <Button
                        key={suggestion.label}
                        variant="outline"
                        className="rounded-full text-muted-foreground"
                        onClick={() => {
                          setDraft(draftKey, suggestion.goal)
                          input.current?.focus()
                        }}
                      >
                        {suggestion.label}
                      </Button>
                    ))}
                </div>
              </div>
            )}
          </div>

          {/* Mounted only while open (and sliding out): a closed live view stops the stream, so nothing is captured for
            no one. With motion reduced it fades instead of sliding. Beside the column it draws the divider itself, so
            the line slides in with it: the column's edge follows on the main thread and can fall behind, under it. */}
          {panelMounted && (
            <div
              ref={panel}
              data-slot="live-panel"
              inert={panelClosing}
              className={cn(
                "absolute inset-y-0 right-0 z-10 bg-background transition-[width,translate,opacity] duration-300 ease-(--ease-drawer) motion-safe:starting:translate-x-full motion-reduce:starting:opacity-0",
                !covering && "border-l",
                panelClosing &&
                  "motion-safe:translate-x-full motion-reduce:opacity-0"
              )}
              style={{ width: covering ? "100%" : liveShown }}
            >
              {!covering && (
                <ResizeHandle
                  from="right"
                  width={liveShown}
                  min={LIVE_MIN}
                  max={liveMax}
                  onWidth={setLiveWidth}
                  label={say.home.resizeLiveView}
                  className="-left-1.5"
                />
              )}
              {liveView}
            </div>
          )}
        </div>
      </SidebarInset>

      {isMobile && (
        <Sheet open={sheetOpen} onOpenChange={setSheetOpen}>
          <SheetContent
            side="right"
            className="p-0 data-[side=right]:w-full data-[side=right]:sm:max-w-none"
            showCloseButton={false}
          >
            <SheetHeader className="sr-only">
              <SheetTitle>{say.home.liveView}</SheetTitle>
              <SheetDescription>
                {say.home.liveViewDescription}
              </SheetDescription>
            </SheetHeader>
            {liveView}
          </SheetContent>
        </Sheet>
      )}
      {/* Mounted once, centered in the viewport independently of the sidebar and live view. */}
      <Toaster
        position="bottom-center"
        offset={{ top: 24 }}
        mobileOffset={{ top: 64 }}
      />
    </SidebarProvider>
  )
}
