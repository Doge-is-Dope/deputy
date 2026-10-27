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
import { RunView } from "@/components/conversation/run-view"
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
import {
  useChatsOpen,
  useOpenProject,
  useOpenRun,
  useRuns,
  useStatus,
} from "@/hooks/use-api"
import { ChatsPage } from "@/components/chats-page"
import { Notice } from "@/components/notice"
import { NEW_TASK, setDraft } from "@/hooks/use-drafts"
import { useConversationActions } from "@/hooks/use-conversation-actions"
import { useSeen } from "@/hooks/use-seen"
import { useIsMobile } from "@/hooks/use-mobile"
import { useStoredWidth } from "@/hooks/use-stored-width"
import { ResizeHandle } from "@/components/resize-handle"
import { runningOf, waitingOf } from "@/lib/api"
import { conversationsOf, nameOf } from "@/lib/conversations"
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

export default function App() {
  const say = useT()
  const { status, offline, refresh: refreshStatus } = useStatus()
  const { runs, failed: runsFailed, refresh: refreshRuns } = useRuns()
  // The address names a conversation by its first run, or by any of its runs (an older link).
  const [opened, open] = useOpenRun()
  const project = useOpenProject() // whose home is open: a new conversation begins in it
  const chatsOpen = useChatsOpen() // the page of every conversation
  const conversations = useMemo(() => runs && conversationsOf(runs), [runs])
  const conversation = conversations?.find(
    (each) => each.id === opened || each.runs.some((run) => run.id === opened)
  )
  const thread = conversation?.id ?? opened
  // A conversation just started may not be in the list yet: its first run is all there is.
  // Kept while the conversation is the same, as is all the conversation is handed below: a new copy on every keystroke
  // or poll would draw each of its turns again.
  const turns = useMemo(
    () => conversation?.runs.map((run) => run.id) ?? (opened ? [opened] : []),
    [conversation, opened]
  )
  // A run that carries on the one before it with the same goal (「從這裡繼續」) does not repeat that goal.
  const continued = useMemo(
    () =>
      new Set(
        conversation?.runs
          .filter(
            (run, index, all) => index > 0 && run.goal === all[index - 1].goal
          )
          .map((run) => run.id)
      ),
    [conversation]
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
    notice,
    current,
    takesMessages,
    approval,
    pending,
    handover,
    asking,
    start,
    stop,
    remove,
    restore,
    rename,
    move,
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
    refreshRuns,
  })
  const running = current !== null
  const userHasControl = status?.control.owner === "user"
  const connection = connectionOf(status, offline)

  // Changes whenever a run starts or ends anywhere, or names its conversation, which the list then shows by its name
  // in a second or two, not once the run ends; a new list from every poll would not do.
  const runningKey = `${status?.titles_revision ?? 0}:${status?.running.map((each) => each.run).join() ?? ""}`
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
  const { isNew, markSeen } = useSeen(runs)
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
    toast.custom(
      (id) => (
        <Notice
          icon={
            <HandIcon
              role="img"
              aria-hidden={false}
              aria-label={waitingFor}
              className="size-5 shrink-0 text-warning"
            />
          }
          text={nameIn(waitingThread) ?? waitingFor}
          action={
            waitingTakeover ? say.liveView.takeOver : say.home.openConversation
          }
          onDismiss={() => toast.dismiss(id)}
          onAction={() => {
            toast.dismiss(id)
            open(waitingThread)
            if (waitingTakeover) {
              if (isMobile) setSheetOpen(true)
              else setPanelOpen(true)
              setFocusScreen(true)
            }
          }}
        />
      ),
      { id: WAITING_NOTICE, className: "w-full" }
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
  const runningPairs =
    status?.running.map((each) => `${each.run} ${each.thread}`).join("\n") ??
    null
  const ran = useRef<Map<string, string> | null>(null)
  useEffect(() => {
    if (runningPairs === null) return
    const now = new Map(
      runningPairs
        .split("\n")
        .filter(Boolean)
        .map((pair) => pair.split(" ") as [string, string])
    )
    const before = ran.current
    ran.current = now
    if (!before) return
    for (const [run, ended] of before) {
      if (now.has(run) || ended === thread) continue
      toast.custom(
        (id) => (
          <Notice
            // The dot the sidebar marks a new reply with.
            icon={
              <span className="flex size-5 shrink-0 items-center justify-center">
                <span
                  role="img"
                  aria-label={say.home.replied}
                  className="size-2 rounded-full bg-unread"
                />
              </span>
            }
            text={nameIn(ended) ?? say.home.replied}
            action={say.home.openConversation}
            onDismiss={() => toast.dismiss(id)}
            onAction={() => {
              toast.dismiss(id)
              open(ended)
              // On a phone the live view covers the conversation, where the reply is.
              setSheetOpen(false)
            }}
          />
        ),
        { id: `replied-${run}`, className: "w-full" }
      )
    }
  }, [runningPairs, thread, say, open, nameIn])

  // Deleted at once, into the runtime's trash, and said so with 還原 to bring them back, as Gmail's Undo does: one
  // conversation, or a project's. Brought back, the conversation that was open opens again. True once every one is.
  const deleteConversations = async (ids: string[], from: string | null) => {
    const opened = thread !== null && ids.includes(thread) ? thread : null
    const done = await Promise.all(ids.map((each) => remove(each)))
    const deleted = ids.filter((_, index) => done[index])
    if (deleted.length > 0)
      toast.custom(
        (id) => (
          <Notice
            icon={<TrashIcon aria-hidden className="size-5 shrink-0" />}
            text={
              from === null
                ? say.sidebar.deleted
                : say.sidebar.deletedProject(from)
            }
            action={say.sidebar.restore}
            onDismiss={() => toast.dismiss(id)}
            onAction={async () => {
              toast.dismiss(id)
              if ((await restore(deleted)) && opened) open(opened)
            }}
          />
        ),
        { id: `deleted-${deleted[0]}`, className: "w-full" }
      )
    return deleted.length === ids.length
  }

  // A run that starts or ends anywhere (here, or from the command line), or names its conversation, changes the list;
  // and once the runtime can be reached again, a list it couldn't give meanwhile loads.
  useEffect(() => {
    if (!offline) refreshRuns()
  }, [runningKey, offline, refreshRuns])

  const takeover = asking && {
    text: say.composer.takeover.ask(asking.reason),
    onTakeOver: takeOver,
    onSkip: skip,
  }

  const composer = (
    <>
      {notice && (
        <p
          role="alert"
          className="mb-2 rounded-lg bg-destructive/10 px-3 py-2 text-sm text-destructive"
        >
          {notice}
        </p>
      )}
      <Composer
        draftKey={draftKey}
        onSubmit={(goal) => {
          void preloadMarkdown()
          return start(goal)
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
        // A project's home is headed by its name already, and the home by the greeting's question.
        placeholder={
          approval
            ? say.composer.approval.placeholder
            : thread
              ? say.home.placeholderNext
              : say.home.placeholderNew
        }
        autoFocus={!thread}
        ref={input}
      />
    </>
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
      notice={notice}
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
    setPlan({ has: false, docked: plan.docked })
    setPlanOpen(false)
  }
  const planShown = plan.docked ? !planHidden : planOpen
  const closePlan = useCallback(() => setPlanOpen(false), [])
  const pendingRun = useMemo(
    () => (current === null ? null : { run: current, messages: pending }),
    [current, pending]
  )
  const onRunEnded = useCallback(() => {
    refreshRuns()
    refreshStatus()
  }, [refreshRuns, refreshStatus])
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
        conversationsFailed={runsFailed}
        status={status}
        offline={offline}
        openConversation={thread}
        selectedProject={project}
        isNew={isNew}
        onDelete={deleteConversations}
        onRename={rename}
        onMove={move}
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
                runs={turns}
                continued={continued}
                listed={runs !== null || runsFailed}
                status={status}
                asking={asking?.run ?? null}
                pending={pendingRun}
                offline={offline}
                composer={composer}
                onEnded={onRunEnded}
                onTitled={refreshRuns}
                onOpenLive={openLive}
                planShown={planShown}
                onPlan={setPlan}
                onClosePlan={closePlan}
              />
            ) : chatsOpen ? (
              <ChatsPage conversations={conversations ?? []} isNew={isNew} />
            ) : (
              <div className="flex min-h-0 flex-1 flex-col items-center justify-center overflow-y-auto px-4 pb-[10vh]">
                {/* A project's home is headed by its name, as ChatGPT's is, with no suggestions: what is begun here
                    is the project's own. */}
                {project ? (
                  <h2 className="mb-7 text-center text-2xl tracking-tight">
                    {project}
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
