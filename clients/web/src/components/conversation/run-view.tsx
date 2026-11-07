import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
  type RefObject,
} from "react"
import { cn } from "cn"

import { PlanSteps } from "@/components/conversation/plan-steps"
import { RunThread, TurnSkeleton } from "@/components/conversation/run-thread"
import { useMarkdownReady } from "@/components/markdown/markdown"
import { ScreenshotViewer } from "@/components/screenshot-viewer"
import { buttonVariants } from "@/components/ui/button"
import { Spinner } from "@/components/ui/spinner"
import { HISTORY_PAGE, historyStart } from "@/lib/history"
import { useSessionEvents, type StreamPhase } from "@/hooks/use-run-events"
import { useLiquidGlass } from "@/hooks/use-liquid-glass"
import { useThread } from "@/hooks/use-thread"
import {
  approvalFor,
  runningOf,
  userSince,
  type Pending,
  type Status,
} from "@/lib/api"
import { useT } from "@/lib/i18n"
import { SIZE as GLASS } from "@/lib/liquid-glass"
import { reducedMotion } from "@/lib/motion"
import { samePlan, type Plan } from "@/lib/thread"
import { ArrowDownIcon } from "@/components/icons"

// The plan's card beside the conversation: its width (w-72), its gap to the window's edge (right-3) and to the
// conversation; and how wide the conversation must stay to have it there rather than over it, opened from the header.
const PLAN_SPACE = 288 + 12 + 12
const PLAN_DOCKED = PLAN_SPACE + 600

/** Whether something shown is still on screen: from when it shows until its way out (`ms`) is over. */
function usePresence(open: boolean, ms: number) {
  const [mounted, setMounted] = useState(open)
  if (open && !mounted) setMounted(true)
  useEffect(() => {
    if (open || !mounted) return
    const timer = window.setTimeout(() => setMounted(false), ms)
    return () => window.clearTimeout(timer)
  }, [open, mounted, ms])
  return [mounted, mounted && !open] as const
}

// Within this many pixels of the end, the conversation counts as read to the end and follows new events.
const STICK_PX = 80
// The run being read is the one across this line, as a share of the view's height down from its top; it is found
// again once scrolling has paused this long, so passing over a run does not flash its plan.
const READING_LINE = 0.3
const READ_AFTER_MS = 150
// A message the user sends sits this far below the top of the view, as the conversation's first one does (pt-4).
const PLACED_PX = 16
// Where each conversation was left, so it opens there again: the first turn read, and the turn at the top of the view
// and how far into it (null for one left at the end, which opens there). Kept while the page is, for the last few dozen.
const LEFT_AT = new Map<
  string,
  { first: string; at: { run: string; into: number } | null }
>()
const LEFT_AT_MAX = 50

const below = (element: HTMLElement) =>
  element.scrollHeight - element.scrollTop - element.clientHeight
const atEnd = (element: HTMLElement) => below(element) < STICK_PX
// The room still empty under a placed message: the end of the view there is not the end of what has come.
const roomLeft = (
  placed: RefObject<HTMLElement | null>,
  room: RefObject<HTMLElement | null>
) => (placed.current ? (room.current?.offsetHeight ?? 0) : 0)

/** Whether scrollbars float over the content and take no room, as they do on macOS with a trackpad. */
function overlayScrollbars() {
  const probe = document.createElement("div")
  probe.style.cssText =
    "position:absolute;visibility:hidden;width:50px;height:50px;overflow:scroll"
  document.body.append(probe)
  const overlay = probe.offsetWidth === probe.clientWidth
  probe.remove()
  return overlay
}

type TurnActions = {
  onEnded: () => void
  onOpenLive: () => void // the live view, from the screen of the step under way
}

const NO_LOGS: readonly string[] = []
// One empty list for every turn with nothing sent to steer it: a new one each time would draw every turn again.
const NO_MESSAGES: Pending[] = []

/** Where a run's stream stands, and whether any of it has arrived to show. */
type TurnStream = { phase: StreamPhase; shown: boolean }

/** One run of a conversation: its goal, its steps and its answer, streamed while it runs. */
function RunTurn({
  run,
  logs,
  goal,
  going,
  started,
  status,
  continued,
  latest,
  visible,
  takingOver,
  steering,
  wake,
  onStream,
  onPlan,
  ...actions
}: TurnActions & {
  run: string // the session's first turn, which names it
  logs: readonly string[] // the logs of its turns and tasks the conversation's list has
  goal: string | null // what the user sent it, from the conversation's list or as it was sent from here
  going: boolean // the conversation's list says it has not ended
  started: boolean // started from this page just now
  status: Status | null
  continued: boolean
  latest: boolean // the conversation's last run
  visible: boolean // the conversation is shown
  takingOver: boolean // the composer asks the user to take over the desktop for this run
  steering: Pending[] // sent to steer this session, until its log has them
  wake: number // changes when the runtime can be reached again, so a stream waiting to reconnect tries at once
  onStream: (run: string, stream: TurnStream) => void
  onPlan: (run: string, plan: Plan | null, active: boolean) => void
}) {
  const session = runningOf(status, { run })
  const active = session !== null
  // Its logs: those listed, those the status says are at work, and the tasks its turns name before either has them.
  const [named, setNamed] = useState<readonly string[]>(NO_LOGS)
  const known = [
    ...new Set([
      run,
      ...logs,
      ...(session?.turn ? [session.turn] : []),
      ...(session?.tasks ?? []),
      ...named,
    ]),
  ].sort()
  const { events, phase, done, draft, final, streamed } = useSessionEvents(
    known,
    !active,
    actions.onEnded,
    wake
  )
  const recorded = events.flatMap((event) =>
    event.type === "task" && event.record && !known.includes(event.record)
      ? [event.record]
      : []
  )
  // Read alongside from the next draw: once known, none of them is named again.
  if (recorded.length) setNamed([...new Set([...named, ...recorded])])
  // What the user sent, drawn before the log comes for a run under way (by the status, or by the list until the log
  // has anything), just started here, or whose log can't be read now. A finished run's log comes at once: it waits for
  // that.
  const early =
    goal !== null &&
    (active ||
      started ||
      phase === "retrying" ||
      (going && events.length === 0))
      ? goal
      : null
  const shown = events.length > 0 || early !== null
  useEffect(
    () => onStream(run, { phase, shown }),
    [run, phase, shown, onStream]
  )
  const thread = useThread(events)
  useEffect(
    () => onPlan(run, thread.plan, active),
    [run, thread.plan, active, onPlan]
  )
  const [shot, setShot] = useState<number | null>(null)

  // An earlier turn read on the way up shows once it has some; one whose read fails keeps its skeleton.
  if (visible && !latest && !shown && phase !== "retrying") return null

  return (
    <>
      <RunThread
        run={run}
        thread={thread}
        sent={early}
        dropped={phase === "retrying"}
        continued={continued}
        latest={latest}
        visible={visible}
        // A run the runtime doesn't have has nothing more to come either.
        loaded={done || phase === "missing"}
        active={active}
        error={status?.error?.run === run ? status.error.message : null}
        userSince={userSince(status)}
        disconnected={status?.computer.connected === false}
        approving={approvalFor(status, known)?.consequence ?? null}
        takingOver={takingOver}
        steering={steering}
        draft={draft}
        answering={final}
        streamed={streamed}
        onOpenShot={(name) =>
          setShot(thread.screenshots.findIndex((each) => each.name === name))
        }
        onOpenLive={actions.onOpenLive}
      />
      <ScreenshotViewer
        run={run}
        shots={thread.screenshots}
        index={shot}
        onIndexChange={setShot}
      />
    </>
  )
}

/** Stream the conversation's runs in order; follow new events only while at the bottom. */
export function RunView({
  thread,
  runs,
  logs,
  goals,
  going,
  started,
  continued,
  listed,
  status,
  asking = null,
  steering = null,
  offline,
  composer,
  planShown,
  onPlan,
  onClosePlan,
  onEnded,
  onOpenLive,
}: TurnActions & {
  thread: string
  runs: string[] // oldest first: each session's first turn
  logs: ReadonlyMap<string, readonly string[]> // each session's logs, by its first turn
  goals: ReadonlyMap<string, string> // what the user sent each run, as far as it is known yet
  going: ReadonlySet<string> // the runs the conversation's list says have not ended
  started: string | null // the run started from this page last
  continued: ReadonlySet<string> // runs that carry on the one before with the same goal
  listed: boolean // the list of runs has come (or failed to), so `runs` holds all the conversation's runs it knows of
  status: Status | null
  asking?: string | null // the run the composer asks the user to take over the desktop for
  steering?: { run: string; messages: Pending[] } | null // what was sent to steer the session in progress
  offline: boolean // the runtime can't be reached
  composer: ReactNode
  planShown: boolean // the header shows the plan: beside the conversation, or opened over it
  onPlan: (plan: { has: boolean; docked: boolean }) => void // whether the run being read has a plan, and room for it beside
  onClosePlan: () => void // the plan opened over the conversation, closed from elsewhere
}) {
  const t = useT()
  const [first, setFirst] = useState<string | null>(
    () => LEFT_AT.get(thread)?.first ?? null
  )
  const start = historyStart(runs, first)
  if (listed && runs.length > 0 && !runs.includes(first ?? ""))
    setFirst(runs[start])
  // Before the list comes, the run opened (one just started, mostly) reads its events alongside it.
  const shownRuns = listed ? runs.slice(start) : runs
  const anchor = useRef<{ element: Element; top: number } | null>(null)
  const earlier = useRef<HTMLDivElement>(null)
  // Each run's stream, as its turn reports it. The conversation is gone when none read is there; it can't be shown yet
  // while none of it has arrived and a stream waits to reconnect; and once some has, a stream that dropped says so
  // above the composer, everything shown staying where it is.
  const [streams, setStreams] = useState<Record<string, TurnStream>>({})
  const onStream = useCallback(
    (run: string, stream: TurnStream) =>
      setStreams((current) =>
        current[run]?.phase === stream.phase &&
        current[run]?.shown === stream.shown
          ? current
          : { ...current, [run]: stream }
      ),
    []
  )
  const states = shownRuns.map((run) => streams[run])
  // A historical run's first event is not the end of its replay; keep the anchor until it is complete.
  const loadingEarlier = states
    .slice(0, -1)
    .some(
      (stream) =>
        !stream || stream.phase === "connecting" || stream.phase === "open"
    )
  // Only the turns read so far are known: the conversation is gone when none of them is there.
  const missing =
    states.length > 0 && states.every((stream) => stream?.phase === "missing")
  const shown = states.some((stream) => stream?.shown)
  const retrying = states.some((stream) => stream?.phase === "retrying")
  const placeholder = missing ? "missing" : retrying && !shown ? "failed" : null
  // Reveal once all runs have loaded to avoid showing an earlier turn alone at the bottom.
  // Once revealed, keep the conversation visible during reconnects.
  // A conversation just started from here has nothing to read: what the user sent shows at once.
  const [ready, setReady] = useState(
    () => runs.length === 1 && runs[0] === started
  )
  const markdownReady = useMarkdownReady()
  if (
    !ready &&
    markdownReady &&
    listed &&
    states.every(
      (stream) =>
        stream &&
        stream.phase !== "connecting" &&
        (stream.phase !== "open" || stream.shown)
    )
  )
    setReady(true)
  // Once the runtime is back, streams waiting to reconnect try at once rather than after their wait.
  const [wake, setWake] = useState(0)
  const [wasOffline, setWasOffline] = useState(offline)
  if (wasOffline !== offline) {
    setWasOffline(offline)
    if (!offline) setWake((count) => count + 1)
  }
  const [plans, setPlans] = useState<
    Record<string, { plan: Plan | null; active: boolean }>
  >({})
  const [reading, setReading] = useState<string | null>(null)
  // Kept as it was while the same: a new copy every frame of a reply would draw the whole conversation again.
  const onRunPlan = useCallback(
    (run: string, plan: Plan | null, active: boolean) =>
      setPlans((current) =>
        current[run] &&
        samePlan(current[run].plan, plan) &&
        current[run].active === active
          ? current
          : { ...current, [run]: { plan, active } }
      ),
    []
  )
  // The plan of the run being read: each run's own, none for a run that wrote none (or wrote it empty).
  const current = reading ? plans[reading] : undefined
  const hasPlan = (current?.plan?.steps.length ?? 0) > 0
  // Any run's plan keeps the room beside the conversation, so the words do not reflow as the plan comes and goes.
  const written = shownRuns.some(
    (run) => (plans[run]?.plan?.steps.length ?? 0) > 0
  )
  // The plan the card shows, kept on its way out once the run being read has none.
  const [kept, setKept] = useState<{
    run: string
    plan: Plan
    active: boolean
  } | null>(null)
  if (
    hasPlan &&
    (kept?.run !== reading ||
      kept.plan !== current!.plan ||
      kept.active !== current!.active)
  )
    setKept({ run: reading!, plan: current!.plan!, active: current!.active })
  // Beside the conversation while it keeps room enough to read; otherwise opened over it from the header.
  const frame = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(0)
  useLayoutEffect(() => {
    const element = frame.current
    if (!element) return
    const observer = new ResizeObserver(([entry]) =>
      setWidth(entry.contentRect.width)
    )
    observer.observe(element)
    return () => observer.disconnect()
  }, [])
  const docked = width >= PLAN_DOCKED
  useEffect(() => onPlan({ has: hasPlan, docked }), [hasPlan, docked, onPlan])
  const showPlan = hasPlan && planShown && width > 0
  const [planMounted, planClosing] = usePresence(showPlan, 250)
  const card = useRef<HTMLElement>(null)
  // Opened over the conversation, it closes as a menu does: a press elsewhere, or Escape.
  useEffect(() => {
    if (!showPlan || docked) return
    const press = (event: PointerEvent) => {
      const target = event.target as Element
      if (
        card.current?.contains(target) ||
        target.closest("[data-plan-toggle]")
      )
        return
      onClosePlan()
    }
    const key = (event: KeyboardEvent) =>
      event.key === "Escape" && onClosePlan()
    document.addEventListener("pointerdown", press)
    document.addEventListener("keydown", key)
    return () => {
      document.removeEventListener("pointerdown", press)
      document.removeEventListener("keydown", key)
    }
  }, [showPlan, docked, onClosePlan])
  const scroller = useRef<HTMLDivElement>(null)
  const content = useRef<HTMLDivElement>(null)
  const turns = useRef<HTMLDivElement>(null)
  const room = useRef<HTMLDivElement>(null)
  const dock = useRef<HTMLDivElement>(null)
  const following = useRef(true)
  const lastTop = useRef(0)
  const readLater = useRef<number | undefined>(undefined)
  // The run across the reading line; at the end of the conversation, the last one, however little of it shows.
  const read = useCallback(() => {
    const element = scroller.current
    const list = turns.current
    if (!element || !list) return
    const all = [...list.children].filter((child): child is HTMLElement =>
      child.hasAttribute("data-run")
    )
    const line =
      element.getBoundingClientRect().top + element.clientHeight * READING_LINE
    const turn = atEnd(element)
      ? all.at(-1)
      : (all.findLast((each) => each.getBoundingClientRect().top <= line) ??
        all[0])
    setReading(turn?.dataset.run ?? null)
  }, [])
  useEffect(() => {
    read()
    return () => window.clearTimeout(readLater.current)
  }, [read, ready, runs, start])
  const lastHeight = useRef(0)
  const [behind, setBehind] = useState(false)
  const lens = useLiquidGlass()
  // The turn the user started last, its message held at the top of the view while the answer comes in under it;
  // where the view is on its way to for it, if it is; the turns already seen, so only a new one is
  // placed; and whether the conversation has shown yet.
  const placed = useRef<HTMLElement | null>(null)
  const placing = useRef<number | null>(null)
  const seen = useRef(new WeakSet<Element>())
  const opened = useRef(false)
  // Whether the conversation, and its last run, are still under way, by the status; the observer below reads them as
  // they were last drawn.
  const working = runs.some((run) => runningOf(status, { run }) !== null)
  const latestWorking =
    runs.length > 0 && runningOf(status, { run: runs.at(-1)! }) !== null
  const now = useRef({ shown: false, latestWorking: false, first: "" })
  useLayoutEffect(() => {
    now.current = {
      shown: ready && placeholder === null,
      latestWorking,
      first: shownRuns[0] ?? "",
    }
  })

  const loadEarlier = useCallback(() => {
    const top = scroller.current!.getBoundingClientRect().top
    const element = [...turns.current!.children].find(
      (child) =>
        child.hasAttribute("data-run") &&
        child.getBoundingClientRect().bottom > top
    )
    anchor.current = element
      ? { element, top: element.getBoundingClientRect().top }
      : null
    following.current = false
    placed.current = null
    placing.current = null
    setFirst(runs[Math.max(0, start - HISTORY_PAGE)])
  }, [runs, start])

  useEffect(() => {
    const target = earlier.current
    if (!target || !ready || loadingEarlier) return
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) loadEarlier()
      },
      { root: scroller.current }
    )
    observer.observe(target)
    return () => observer.disconnect()
  }, [ready, loadingEarlier, loadEarlier])

  // New events, screenshots loading and steps folding all change the height, and so does the window: stay at the
  // end while the user is, and notice when shorter content leaves nothing below, which scrolls nothing.
  useLayoutEffect(() => {
    const element = scroller.current
    const inner = content.current
    const list = turns.current
    if (!element || !inner || !list || !dock.current) return
    // Overlay scrollbars flash whenever the content resizes, as it does on every frame of steps folding away; they
    // take no room, so index.css hides them while that happens.
    element.toggleAttribute("data-overlay-scrollbars", overlayScrollbars())
    // Where the view's top goes for a turn to start at the top of it.
    const topFor = (turn: HTMLElement) =>
      turn.getBoundingClientRect().top -
      inner.getBoundingClientRect().top -
      PLACED_PX
    // The content stays tall enough for the placed turn to reach the top of the view, however little has come under
    // it yet; a turn gone (its skeleton, once the turn came) is placed no more.
    // Written only when it changes, so the frames of a reply streaming in lay out once.
    const fit = () => {
      if (placed.current && !placed.current.isConnected) placed.current = null
      const height = placed.current
        ? `${topFor(placed.current) + element.clientHeight - dock.current!.offsetHeight}px`
        : ""
      if (inner.style.minHeight !== height) inner.style.minHeight = height
    }
    // The last turn, the first time it shows: a message the user sent, their goal carried on, or the skeleton
    // standing in for either. Not a message sent into a run at work, which comes under what it is writing. Each turn
    // draws itself as a child of the list (its screenshots open in a portal), so only the children are read, however
    // long the replies in them grow.
    const fresh = () => {
      if (!now.current.shown) return null
      const all = list.children
      const last = all[all.length - 1] as HTMLElement | undefined
      const unseen = last?.hasAttribute("data-turn") && !seen.current.has(last)
      for (let index = 0; index < all.length; index++)
        seen.current.add(all[index])
      return unseen ? last! : null
    }
    const observer = new ResizeObserver(() => {
      // Historical replies can keep growing after their event stream ends (markdown and images).
      // Keep the old turn in place until the user moves again, even without native scroll anchoring.
      const held = anchor.current
      if (held?.element.isConnected)
        element.scrollTop += held.element.getBoundingClientRect().top - held.top
      // It goes to the top of the view if the view was at the end, the answer coming in under it and the view
      // holding still; and in place of the skeleton that stood in for it. A conversation opened lands at its end,
      // unless its last run is still under way, or where it was left. Where the view was is where it last scrolled
      // to: content that got shorter as this came may have pulled it up since.
      const sent = fresh()
      if (sent) {
        const opening = !opened.current
        opened.current = true
        const at = opening ? LEFT_AT.get(thread)?.at : null
        const back =
          at &&
          [...list.children].find(
            (child) => (child as HTMLElement).dataset.run === at.run
          )
        if (at && back) {
          // The browser keeps it there as what is above it loads (overflow-anchor).
          following.current = false
          element.scrollTop +=
            back.getBoundingClientRect().top -
            element.getBoundingClientRect().top +
            at.into
        } else if (
          opening
            ? now.current.latestWorking
            : lastHeight.current - lastTop.current - element.clientHeight <
                STICK_PX || placed.current?.isConnected === false
        ) {
          placed.current = sent
          following.current = false
          fit()
          // A view already there scrolls nothing, and hears of no scroll.
          const top = topFor(sent)
          const smooth = !opening && !reducedMotion()
          placing.current =
            smooth && Math.abs(element.scrollTop - top) > 1 ? top : null
          element.scrollTo({ top, behavior: smooth ? "smooth" : "instant" })
        }
      }
      if (placed.current) fit()
      const shrank = element.scrollHeight < lastHeight.current
      lastHeight.current = element.scrollHeight
      if (following.current) element.scrollTop = element.scrollHeight
      // Content that got shorter can leave nothing below, which scrolls nothing. Only nothing at all: a view merely
      // near the end would be pulled down to it mid-fold. Nothing else resumes following: steps the user unfolds
      // still sit near the end in their first frames.
      else if (shrank && below(element) <= 1 && !roomLeft(placed, room))
        following.current = true
      setBehind(
        !following.current &&
          placing.current === null &&
          below(element) - roomLeft(placed, room) >= STICK_PX
      )
    })
    observer.observe(inner)
    // What has come, too: inside the room under a placed message it grows with the content staying as tall.
    observer.observe(list)
    observer.observe(element)
    // The composer is part of what scrolls: a goal growing to more lines is content growing too.
    observer.observe(dock.current)
    return () => {
      observer.disconnect()
      // Where it is left, read while it is still laid out: the turn at the top of the view, unless it is at the end.
      // One never opened (or set up again at once, as in development) leaves what was kept.
      if (!opened.current) return
      LEFT_AT.delete(thread)
      const top = element.getBoundingClientRect().top
      const all = [...list.children].filter((child) =>
        child.hasAttribute("data-run")
      )
      const turn = all.findIndex(
        (child) => child.getBoundingClientRect().bottom > top
      )
      const end =
        following.current ||
        placing.current !== null ||
        below(element) - roomLeft(placed, room) < STICK_PX ||
        turn < 0
      LEFT_AT.set(thread, {
        first: now.current.first,
        at: end
          ? null
          : {
              run: (all[turn] as HTMLElement).dataset.run!,
              into: top - all[turn].getBoundingClientRect().top,
            },
      })
      if (LEFT_AT.size > LEFT_AT_MAX)
        LEFT_AT.delete(LEFT_AT.keys().next().value!)
    }
  }, [thread])

  // The user moving the view lets go of the turn held in place while earlier ones load.
  const release = () => {
    anchor.current = null
  }

  function onScroll() {
    const element = scroller.current!
    const end = atEnd(element)
    const left = roomLeft(placed, room)
    // Only scrolling up leaves the end. A scroll to the end that the content outgrew before it landed (steps
    // unfolding) does not, so following carries on. The end of the room under a placed message is not the end:
    // following starts again only once what came has outgrown it, and the room is nothing to scroll down to.
    if (end && !left) following.current = true
    else if (element.scrollTop < lastTop.current) following.current = false
    // On its way to a placed message the view passes what it is going to, which is not left behind; it is there
    // once it arrives or reaches the end, or the user has scrolled the other way.
    if (
      placing.current !== null &&
      (end ||
        element.scrollTop < lastTop.current ||
        Math.abs(element.scrollTop - placing.current) <= 1)
    )
      placing.current = null
    lastTop.current = element.scrollTop
    window.clearTimeout(readLater.current)
    readLater.current = window.setTimeout(read, READ_AFTER_MS)
    setBehind(
      !following.current &&
        placing.current === null &&
        below(element) - left >= STICK_PX
    )
  }

  return (
    <div ref={frame} className="relative flex min-h-0 flex-1 flex-col">
      <div
        ref={scroller}
        onScroll={onScroll}
        onPointerDownCapture={release}
        onKeyDownCapture={release}
        onWheelCapture={release}
        onTouchMoveCapture={release}
        // Beside the plan, the conversation keeps to the room left of it, moving over as the plan is shown or hidden.
        style={{
          paddingRight: docked && planShown && written ? PLAN_SPACE : 0,
        }}
        className="flex min-h-0 flex-1 flex-col overflow-y-auto transition-[padding-right] duration-300 ease-(--ease-drawer) motion-reduce:transition-none"
      >
        <div
          ref={content}
          // Work or a step the user unfolds opens downward where it is: the view stops following the end until the
          // user is back there.
          onClickCapture={(event) => {
            if ((event.target as Element).closest("[aria-expanded]"))
              following.current = false
          }}
          // Growing to fill the view and never shrinking below what it holds: the least height a placed message sets
          // is a floor under what has come, not a box it overflows. Its px-4 is inside the width, so the words are as
          // wide as the home's composer, whose px-4 is outside it.
          className="mx-auto flex w-full max-w-[calc(var(--container-3xl)+2rem)] shrink-0 grow flex-col px-4 pt-4 pb-10"
        >
          {placeholder && (
            <div className="flex flex-1 flex-col items-center justify-center gap-2 pb-[10vh] text-center">
              <p className="text-lg tracking-tight">
                {placeholder === "missing" ? t.run.notFound : t.run.loadFailed}
              </p>
              {placeholder === "missing" ? (
                <a
                  href="#"
                  className={cn(
                    buttonVariants({ variant: "outline" }),
                    "mt-3 rounded-full"
                  )}
                >
                  {t.sidebar.new}
                </a>
              ) : (
                <p className="text-sm text-muted-foreground">
                  {t.connection.offlineDetail}
                </p>
              )}
            </div>
          )}
          {!ready && placeholder === null && <TurnSkeleton long />}
          {/* Mounted while a placeholder shows, so their streams keep trying, and while the conversation loads. Laid
          out only once it is shown, which resizes it, so the view lands at the end in the frame it appears. */}
          <div
            ref={turns}
            hidden={placeholder !== null || !ready}
            className="space-y-10"
          >
            {start > 0 && (
              <div
                ref={earlier}
                className="flex h-8 items-center justify-center"
              >
                <Spinner />
              </div>
            )}
            {shownRuns.map((run) => (
              <RunTurn
                key={run}
                run={run}
                logs={logs.get(run) ?? NO_LOGS}
                goal={goals.get(run) ?? null}
                going={going.has(run)}
                started={run === started}
                status={status}
                // Not the first one read: what it carries on from is not shown above it.
                continued={continued.has(run) && run !== shownRuns[0]}
                latest={run === runs.at(-1)}
                visible={ready}
                takingOver={asking === run}
                steering={
                  steering?.run === run ? steering.messages : NO_MESSAGES
                }
                wake={wake}
                onStream={onStream}
                onPlan={onRunPlan}
                onEnded={onEnded}
                onOpenLive={onOpenLive}
              />
            ))}
          </div>
          {/* The room under a placed message, as tall as the content's least height leaves it. */}
          {placeholder === null && (
            <div ref={room} aria-hidden className="flex-1" />
          )}
        </div>
        {/* The composer stays at the bottom while the conversation scrolls on under it, as content runs under Apple's
        bars: nothing covers the words above it, they go on beneath it, dissolving toward the bottom edge (Apple's
        scroll edge effect) so the edge cuts no line in half. It is part of what scrolls, so the end of the
        conversation still clears it, and a conversation shorter than the view grows to keep it at the bottom. */}
        <div
          ref={dock}
          className="sticky bottom-0 mx-auto w-full max-w-[calc(var(--container-3xl)+2rem)] px-4 pb-4 before:pointer-events-none before:absolute before:inset-0 before:bg-linear-to-t before:from-background before:to-transparent"
        >
          {/* Down to the latest while it is out of view, glass over the words it floats on, fading in and out as
          ChatGPT's does on the even curve (the sharp ones here drop it in a frame or two), shrinking and blurring a
          little on its way as the plan does. While the agent works down there, the thinking lights pass on it in place of
          the arrow, which comes back under the pointer. A plain button: the glass is its whole surface, with no
          variant's to undo. Once the lens is drawn, the glass softens what is under it a touch and bends it with the
          lens's map, through this filter, and wears the lens's light. */}
          {lens && (
            <svg aria-hidden width={0} height={0} className="absolute">
              <filter
                id="liquid-glass"
                x={0}
                y={0}
                width={GLASS}
                height={GLASS}
                filterUnits="userSpaceOnUse"
                primitiveUnits="userSpaceOnUse"
                colorInterpolationFilters="sRGB"
              >
                <feGaussianBlur
                  in="SourceGraphic"
                  stdDeviation={0.5}
                  edgeMode="duplicate"
                  result="soft"
                />
                <feImage
                  href={lens.map}
                  x={0}
                  y={0}
                  width={GLASS}
                  height={GLASS}
                  preserveAspectRatio="none"
                  result="map"
                />
                <feDisplacementMap
                  in="soft"
                  in2="map"
                  scale={lens.scale}
                  xChannelSelector="R"
                  yChannelSelector="G"
                />
              </filter>
            </svg>
          )}
          <button
            type="button"
            aria-label={t.run.scrollToLatest}
            aria-hidden={!behind}
            tabIndex={behind ? undefined : -1}
            data-lens={lens ? "" : undefined}
            style={
              lens
                ? ({
                    "--glass-glint": `url("${lens.glint}")`,
                    "--glass-glint-dark": `url("${lens.glintDark}")`,
                  } as CSSProperties)
                : undefined
            }
            className={cn(
              "group/latest absolute bottom-full left-1/2 mb-6 flex size-8 -translate-x-1/2 items-center justify-center rounded-full glass transition-[opacity,scale,filter,visibility] duration-200 ease-[cubic-bezier(0.4,0,0.2,1)] outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
              !behind &&
                "invisible scale-90 opacity-0 blur-[2px] motion-reduce:scale-100 motion-reduce:blur-none"
            )}
            onClick={() =>
              scroller.current?.scrollTo({
                top: scroller.current.scrollHeight,
                behavior: "smooth",
              })
            }
          >
            {/* What it shows, the orbs or the arrow under the pointer, is kept through the fade out: it turns invisible,
            and stops taking the pointer, only once faded. The orbs are still while hidden. */}
            {working && (
              <span
                aria-hidden
                className={cn(
                  "thinking-orbs group-hover/latest:hidden group-focus-visible/latest:hidden",
                  !behind && "[&>span]:[animation-play-state:paused]"
                )}
              >
                <span />
                <span />
                <span />
              </span>
            )}
            <ArrowDownIcon
              className={cn(
                working &&
                  "hidden group-hover/latest:block group-focus-visible/latest:block"
              )}
            />
          </button>
          {/* Shown only once it has been down a second, so a stream that comes straight back never flashes it. On its
          own ground, since the words run on under the composer. */}
          {retrying && shown && (
            <p
              role="status"
              className="mx-auto mb-2 w-fit animate-in rounded-full border bg-background px-3 py-1 text-center text-sm text-muted-foreground delay-1000 duration-200 fill-mode-both fade-in"
            >
              {t.connection.reconnecting}
            </p>
          )}
          {!missing && composer}
        </div>
      </div>
      {/* The plan, at the top right where the work never moves it: beside the conversation,
        or over it like a menu when there is no room. It grows out of that corner and back into it, coming a moment after
        the conversation starts to make room for it, so it does not cover what is still moving out of its way. */}
      {planMounted && kept && (
        <aside
          ref={card}
          aria-label={t.run.plan}
          data-closing={planClosing || undefined}
          className={cn(
            "absolute top-2 right-3 z-10 flex max-h-[calc(100%-7rem)] w-72 origin-top-right flex-col overflow-y-auto rounded-2xl px-4 pt-3 pb-2.5 transition-[opacity,scale,filter] delay-100 duration-250 ease-(--ease-out) data-closing:scale-95 data-closing:opacity-0 data-closing:blur-[2px] data-closing:delay-0 motion-reduce:transition-opacity motion-reduce:data-closing:scale-100 motion-reduce:data-closing:blur-none starting:scale-95 starting:opacity-0 starting:blur-[2px] motion-reduce:starting:scale-100 motion-reduce:starting:blur-none",
            docked
              ? "border bg-background shadow-xs"
              : "bg-popover text-popover-foreground shadow-md ring-1 ring-foreground/10"
          )}
        >
          <p className="pb-1 text-sm text-muted-foreground">{t.run.plan}</p>
          {/* Another run's plan comes in whole, fading in, rather than as its steps changing one by one. */}
          <div
            key={kept.run}
            className="transition-opacity duration-150 ease-(--ease-out) motion-reduce:transition-none starting:opacity-0"
          >
            <PlanSteps plan={kept.plan} active={kept.active} />
          </div>
        </aside>
      )}
    </div>
  )
}
