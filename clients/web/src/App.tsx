import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react"
import { cn } from "cn"
import { toast } from "sonner"

import {
  AppSidebar,
  type ConversationEdits,
} from "@/components/sidebar/app-sidebar"
import { TitleMenu } from "@/components/title-menu"
import { Composer } from "@/components/composer/composer"
import {
  messageOrigin,
  tileOrigins,
  type SentMessage,
} from "@/components/conversation/message-send"
import { LiveView } from "@/components/desktop/live-view"
import { SidePanel } from "@/components/side-panel/side-panel"
import {
  RunView,
  type AskedQuestion,
  type PlanReport,
} from "@/components/conversation/run-view"
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
import { Notice, notify, showError } from "@/components/notice"
import { useAttachments } from "@/hooks/use-attachments"
import { NEW_TASK, setDraft } from "@/hooks/use-drafts"
import { useConversationActions } from "@/hooks/use-conversation-actions"
import { useSeen } from "@/hooks/use-seen"
import { useIsMobile } from "@/hooks/use-mobile"
import { usePresence } from "@/hooks/use-presence"
import { useStoredWidth } from "@/hooks/use-stored-width"
import { ResizeHandle } from "@/components/resize-handle"
import { runningOf, waitingOf, waitingSession } from "@/lib/api"
import { conversationOf, nameOf } from "@/lib/conversations"
import { connectionOf, greeting } from "@/lib/format"
import { useT } from "@/lib/i18n"
import { reducedMotion } from "@/lib/motion"
import { HandIcon, PlanIcon, SidebarIcon, TrashIcon } from "@/components/icons"
import {
  COMPUTER,
  markedTile,
  selectTab,
  setPanelOpen,
  showComputer,
  shownFiles,
  shownTab,
  usePanel,
  usePanelDraft,
} from "@/lib/side-panel"

// The line between the conversation and the live view, on the side of the element drawing it: 8 short of the card's
// top and bottom, under the resize handle's light.
const DIVIDER =
  "after:pointer-events-none after:absolute after:inset-y-2 after:z-10 after:w-px after:bg-border"

// A precise pointer, so a keyboard, read once: a touch screen's options are tapped; a narrow window on a computer still
// has Enter.
const HAS_KEYBOARD = window.matchMedia("(pointer: fine)").matches

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
  const [sentMessage, setSentMessage] = useState<SentMessage | null>(null)
  if (sentMessage && sentMessage.thread !== thread) setSentMessage(null)
  // From the lists, or from its own runs when it is beyond the pages they hold (one opened from search).
  const conversation =
    conversations?.find((each) => each.id === thread) ??
    conversationOf(threadTurns ?? []) ??
    undefined
  // Each conversation keeps its own draft, which its composer reads and writes.
  const draftKey = thread ?? NEW_TASK
  usePanelDraft(draftKey)
  // The panel beside the conversation (a sheet over it on a phone): closed at first; a takeover opens its computer.
  const panel = usePanel()
  const isMobile = useIsMobile()
  // The live view can be dragged wider or narrower; this browser remembers its width (the sidebar's, AppSidebar).
  const [liveWidth, setLiveWidth] = useStoredWidth("live-view-width", 520)
  // The panel never takes more than the page can spare beside the conversation, even after the window shrinks. Where
  // the page can't spare the conversation its width beside the narrowest panel, it is cramped. Only these are kept,
  // not the page's width: a sidebar drag then renders the page only when they change.
  const area = useRef<HTMLDivElement>(null)
  const [liveMax, setLiveMax] = useState(LIVE_MAX)
  const [cramped, setCramped] = useState(false)
  useEffect(() => {
    const element = area.current
    if (!element) return
    const observer = new ResizeObserver(([entry]) => {
      const width = entry.contentRect.width
      setLiveMax(Math.max(LIVE_MIN, Math.min(LIVE_MAX, width - MAIN_MIN)))
      setCramped(width < MAIN_MIN + LIVE_MIN)
    })
    observer.observe(element)
    return () => observer.disconnect()
  }, [])
  // A width stored before the minimum rose is shown at the minimum.
  const liveShown = Math.max(LIVE_MIN, Math.min(liveWidth, liveMax))
  // Expanded, the live view fills the page's middle, over the conversation; cramped, the panel covers it so, and
  // closes as the sheet on a phone does.
  const [expanded, setExpanded] = useState(false)
  const covering = expanded || cramped
  // The session in progress comes in as soon as the status lists it, as one the runtime started with a message queued
  // for it: before the list has it, and with the message it began with.
  const session = thread === null ? null : runningOf(status, { thread })
  const sessionRun = session?.run ?? null
  const sessionGoal = session?.goal ?? null
  // The panel shows this conversation's attachments; the computer is in view while its tab is chosen.
  const panelRuns = useMemo(
    () => [
      ...(threadRuns?.map((run) => run.id) ?? (opened ? [opened] : [])),
      ...(sessionRun ? [sessionRun] : []),
    ],
    [threadRuns, opened, sessionRun]
  )
  const panelTab = shownTab(
    panel,
    shownFiles(panel, panelRuns, draftKey),
    draftKey
  )
  const computerShown = panel.open && panelTab === COMPUTER
  // An attachment's tab over the conversation: what it asks is out of sight there, so a notice says so.
  const conversationHidden =
    panel.open && (isMobile || covering) && panelTab !== COMPUTER
  // Taking over from the composer or a notice opens the live view with the keyboard on the desktop; the live view says
  // once it is (or it closes first).
  const [focusScreen, setFocusScreen] = useState(false)
  if (focusScreen && !computerShown) setFocusScreen(false)

  const {
    input,
    current,
    approval,
    steering,
    queued,
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
    liveOpen: computerShown,
    open,
    showLive: (focus = false) => {
      showComputer()
      if (focus) setFocusScreen(true)
    },
    refreshStatus,
    confirmControl,
    refreshConversations,
  })
  // ⌘⏎ on a marked-up picture: its draft's message goes once the composer holds the copy, uploaded, and its comments.
  // Not if a file failed to go up, nor once another conversation is open.
  const sendDraft = useRef<string | null>(null)
  const [sendsAsked, setSendsAsked] = useState(0)
  const files = useAttachments(draftKey)
  useEffect(() => {
    if (sendDraft.current === null) return
    if (
      sendDraft.current !== draftKey ||
      files.list.some(
        (each) => each.state !== "uploading" && each.state !== "ready"
      )
    )
      sendDraft.current = null
    else if (files.ready) {
      sendDraft.current = null
      input.current?.form?.requestSubmit()
    }
  }, [input, draftKey, sendsAsked, files.list, files.ready])
  const focusComposerOnClose = useRef(false)
  useLayoutEffect(() => {
    if (panel.open || !focusComposerOnClose.current) return
    focusComposerOnClose.current = false
    input.current?.focus()
  }, [input, panel.open])
  // A conversation just started may not be read yet: its first run is all there is; a run started here comes in at once,
  // before the list has it. Kept while the conversation is the same, as is all the conversation is handed below: a new
  // copy on every keystroke or poll would draw each of its turns again.
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
  // The sidebar's edits to a conversation, for the header's menu.
  const edits = useRef<ConversationEdits>(null)
  const projectName = (id: string) =>
    projects?.find((each) => each.id === id)?.name
  const userHasControl = status?.control.owner === "user"
  const connection = connectionOf(status, offline)

  // The computer's tab lights up in the takeover color while the user has the desktop, which they are to hand back.
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
  const waitingThread = waitingSession(status)?.thread ?? null
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
      // Nothing to take down before a wait was ever announced. A dismissal lands on the next frame, so one made as the
      // page opens would take down the notice the first status brings, which has the same id.
      if (announced.current !== null) toast.dismiss(WAITING_NOTICE)
      return
    }
    if (waitingThread === thread && !conversationHidden) {
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
          // Asked in this conversation under an attachment's tab, it is asked over the computer's.
          const here = waitingThread === thread
          open(waitingThread)
          if (waitingTakeover || here) showComputer(waitingThread)
          if (waitingTakeover) setFocusScreen(true)
        },
      },
      { id: WAITING_NOTICE }
    )
  }, [
    waitingId,
    waitingThread,
    waitingFor,
    waitingTakeover,
    conversationHidden,
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
            // On a phone the panel covers the conversation, where the reply is.
            if (isMobile) setPanelOpen(false)
          },
        },
        { id: `replied-${run}` }
      )
    }
  }, [inProgress, thread, say, open, nameIn, isMobile])

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
  const recommended = HAS_KEYBOARD ? (asked?.recommended ?? null) : null
  const many = HAS_KEYBOARD && asked?.multiple === true
  // The answer the agent expects typed, when Enter takes no option: the empty composer shows it to take or change.
  const suggestion =
    !approval && !many && recommended === null ? (asked?.suggestion ?? "") : ""

  const takeover = asking && {
    text: say.composer.takeover.ask(asking.reason),
    onTakeOver: takeOver,
    onSkip: skip,
  }

  const composer = (
    <Composer
      draftKey={draftKey}
      onSubmit={async (goal, queue, clear, attachments) => {
        // A picture marked up and not put back (完成) would go as it was: its tab is shown, to finish or drop the marks.
        const marked = markedTile(attachments.map((each) => each.key))
        if (marked) {
          selectTab(marked)
          setPanelOpen(true)
          showError(say.markup.finishFirst)
          return false
        }
        void preloadMarkdown()
        const draft = input.current
        const typed = draft?.value
        const address = window.location.hash
        return start(
          goal,
          queue,
          (sent) => {
            // It moves from the draft into the conversation only while that draft and conversation are still the ones
            // it was sent from, and not to wait in the composer. Otherwise it arrives as any message does.
            const origin =
              draft &&
              draft.value === typed &&
              window.location.hash === address &&
              !(queue && sent.message) &&
              !reducedMotion()
                ? messageOrigin(draft)
                : null
            if (origin)
              setSentMessage({
                thread: sent.thread,
                run: sent.id,
                message: sent.message ?? null,
                origin,
                tiles: tileOrigins(draft!),
              })
            clear()
          },
          attachments
        )
      }}
      // Unread messages continue in the next run.
      onStop={stop}
      running={running}
      blocked={blocked}
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
            ? say.run.question.pressEnterMany
            : recommended !== null
              ? say.run.question.pressEnter
              : asked !== null
                ? suggestion || say.run.question.placeholder
                : thread
                  ? say.home.placeholderNext
                  : say.home.placeholderNew
      }
      suggestion={suggestion}
      autoFocus={!thread}
      ref={input}
    />
  )

  // The panel's own corner button, on every tab: expanding it over the conversation, or shrinking it back. Where the
  // page has no room beside it, it covers the conversation already, so it is shown expanded and shrinks away. On a
  // phone the panel is a sheet over the page, and the button closes it.
  const corner = isMobile
    ? { onClose: () => setPanelOpen(false) }
    : cramped
      ? { expanded: true, onExpand: () => setPanelOpen(false) }
      : { expanded, onExpand: () => setExpanded((value) => !value) }
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
      {...corner}
      className="size-full"
    />
  )
  const sidePanel = (
    <SidePanel
      computer={liveView}
      runs={panelRuns}
      draft={draftKey}
      connection={connection}
      yours={yours}
      place={{
        phone: isMobile,
        corner,
        expanded: !isMobile && expanded,
        // As the composer takes files (composer.tsx): with a new message or an answer, not while the agent works or
        // waits on a step or a takeover.
        blocked:
          approval || asking
            ? say.markup.answerFirst
            : running
              ? say.markup.busy
              : null,
        // Once a copy is added the cursor is back in the composer; where the panel covers the conversation, it closes.
        onAdded: (send) => {
          if (send) {
            sendDraft.current = draftKey
            setSendsAsked((count) => count + 1)
          }
          if (isMobile || covering) setPanelOpen(false)
          // On desktop the composer is inert until React applies the close.
          if (!isMobile && covering) focusComposerOnClose.current = true
          else input.current?.focus()
        },
      }}
    />
  )
  // The conversation's plan, as its view reports it: shown beside the conversation unless hidden, or opened over it.
  const [plan, setPlan] = useState<PlanReport>({
    has: false,
    docked: true,
    written: 0,
  })
  const [planHidden, setPlanHidden] = useState(false)
  const [planOpen, setPlanOpen] = useState(false)
  // How many of the view's new plans have been shown: each once, beside the conversation if hidden, or over it.
  const [popped, setPopped] = useState(0)
  // Another conversation: none opened over it, and its view counts new plans afresh.
  const [planOf, setPlanOf] = useState(thread)
  if (planOf !== thread) {
    setPlanOf(thread)
    setAsked(null)
    setPlan({ ...plan, written: 0 })
    setPlanOpen(false)
    setPopped(0)
  } else if (plan.written !== popped) {
    setPopped(plan.written)
    if (plan.written) {
      if (plan.docked) setPlanHidden(false)
      else setPlanOpen(true)
    }
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
    if (questioned && HAS_KEYBOARD && document.activeElement === document.body)
      input.current?.focus()
  }, [questioned, input])
  // The status says at once the run is no longer running, which changes the lists (listsChanged). Replaying an ended
  // run, as opening one does, ends its stream too, and asks the lists for nothing.
  const onRunEnded = refreshStatus
  // What was sent to steer the session in progress, which its turn shows where it goes.
  const steered = useMemo(
    () => (current === null ? null : { run: current, messages: steering }),
    [current, steering]
  )
  const showPanel = !isMobile && panel.open
  // The panel slides in from the window's edge and back out. Closed, it stays mounted until it is out of sight (its
  // duration-300), then goes; opened again on its way out, it turns back from where it is.
  const [panelMounted, panelClosing] = usePresence(showPanel, 300)
  // Closed while expanded, it goes as it is and opens beside the conversation the next time.
  if (!panelMounted && expanded) setExpanded(false)

  return (
    <SidebarProvider>
      <AppSidebar
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
        edits={edits}
      />
      <SidebarInset className="h-svh min-w-0 overflow-hidden">
        <div ref={area} className="relative flex min-h-0 flex-1">
          {/* On a phone, the sidebar is a sheet with no rail to open it from, so its toggle is here, where the header
            would hold it. Elsewhere it is at the top of the sidebar. */}
          {isMobile && (
            <SidebarTrigger className="touch-target absolute top-1.5 left-2.5 z-20" />
          )}
          {/* Beside the panel, which covers it when expanded or cramped: it keeps its width then, so nothing reflows. It
            draws the divider while covered, so the panel sweeps over the line when it expands rather than carrying it
            along. The divider stops 8 short of the card's top and bottom, apart from its edge. */}
          <div
            data-slot="live-gap"
            className={cn(
              "relative flex min-w-0 flex-1 flex-col transition-[margin-right] duration-300 ease-(--ease-panel) motion-reduce:transition-none",
              panelMounted && covering && [DIVIDER, "after:right-0"]
            )}
            style={{ marginRight: showPanel ? liveShown : 0 }}
            inert={showPanel && covering}
          >
            {/* Room at its end for the live view's toggle while that lies over this column. */}
            <header
              className={cn(
                // After the sidebar's toggle on a phone.
                "flex h-12 shrink-0 items-center gap-2 pl-11.5 transition-[padding] duration-300 ease-(--ease-panel) motion-reduce:transition-none md:h-13 md:pl-2",
                showPanel ? "pr-2.5 md:pr-2" : "pr-13.5 md:pr-13"
              )}
            >
              {/* The open conversation's name, its words on the column of the header buttons' icons. */}
              {conversation && (
                <TitleMenu
                  key={conversation.id}
                  conversation={conversation}
                  running={running}
                  edits={edits}
                  onRename={rename}
                />
              )}
              {/* Over the panel, so it fades out there as the panel covers it rather than being cut by its edge, and
                back in near the end as the panel shrinks away. */}
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
                          // It grows in for a plan just written here; switching to a conversation, it is simply there.
                          className={cn(
                            "touch-target transition-[opacity,scale,background-color] duration-200 ease-(--ease-out)",
                            plan.written > 0 &&
                              "starting:scale-90 starting:opacity-0"
                          )}
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
                sentMessage={sentMessage}
                listed={listed}
                status={status}
                asking={asking ? current : null}
                steering={steered}
                offline={offline}
                composer={composer}
                onEnded={onRunEnded}
                onOpenLive={() => showComputer()}
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
            no one. It slides by --slide (index.css), which its tabs and corner button also follow; with motion reduced it
            fades instead. Closing, what is on it goes at once and the empty panel slides away. Beside the column it draws
            the divider itself, so the line slides in with it: the column's edge follows on the main thread and can fall
            behind, under it. */}
          {panelMounted && (
            <div
              data-slot="live-panel"
              inert={panelClosing}
              className={cn(
                "@container absolute inset-y-0 right-0 z-10 translate-x-[calc(var(--slide)*100%)] bg-background transition-[width,--slide,opacity] duration-300 ease-(--ease-panel) motion-safe:animate-[reveal-panel-corner_150ms_step-end] motion-reduce:transition-opacity motion-safe:starting:[--slide:1] motion-reduce:starting:opacity-0",
                !covering && [
                  DIVIDER,
                  "after:left-0",
                  // Its part in the top row goes while less of the panel shows than the corner buttons' room
                  // (side-panel.tsx's 92px), so it never passes behind them: from 8 down to the row's end at 52.
                  "after:top-[calc(8px_+_clamp(0px,(92px_-_(1_-_var(--slide))_*_100cqw)_*_1000,44px))]",
                ],
                panelClosing &&
                  "*:opacity-0 motion-safe:[--slide:1] motion-reduce:opacity-0"
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
                  label={say.tabs.resize}
                  className="-left-1.5"
                />
              )}
              {sidePanel}
            </div>
          )}
          {/* The panel's toggle, at the window's corner whether it is open or not, over the panel: pressed twice in one
            place it opens and closes it. The left sidebar's toggle, mirrored. The panel's own corner button sits
            beside it. */}
          <Tooltip>
            <TooltipTrigger
              render={
                <Button
                  variant="ghost"
                  size="icon"
                  className="touch-target absolute top-1.5 right-2.5 z-20 md:top-2 md:right-2"
                  aria-label={say.tabs.title}
                  aria-pressed={panel.open}
                  onClick={() => setPanelOpen(!panel.open)}
                />
              }
            >
              <SidebarIcon open={panel.open} className="size-5 -scale-x-100" />
            </TooltipTrigger>
            <TooltipContent>
              {panel.open ? say.tabs.hide : say.tabs.show}
            </TooltipContent>
          </Tooltip>
        </div>
      </SidebarInset>

      {isMobile && (
        <Sheet
          open={panel.open}
          onOpenChange={(open, details) => {
            // Esc on a picture being marked up is the markup's own, as beside the conversation: the sheet stays and
            // lets the key on to it.
            const marking = panel.files.find((each) => each.key === panelTab)
            if (details.reason === "escape-key" && marking?.markup) {
              details.cancel()
              details.allowPropagation()
              return
            }
            setPanelOpen(open)
          }}
        >
          <SheetContent
            side="right"
            className="p-0 data-[side=right]:w-full data-[side=right]:sm:max-w-none"
          >
            <SheetHeader className="sr-only">
              <SheetTitle>{say.tabs.title}</SheetTitle>
              <SheetDescription>{say.tabs.description}</SheetDescription>
            </SheetHeader>
            {sidePanel}
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
