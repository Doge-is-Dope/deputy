import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type RefObject,
} from "react"
import { cn } from "cn"

import { AnswerPair } from "@/components/composer/answers"
import { RemoteScreen } from "@/components/desktop/remote-screen"
import {
  CheckIcon,
  CloseIcon,
  CopyIcon,
  ExpandIcon,
  ShrinkIcon,
  CursorEnterIcon,
  HandIcon,
  OfflineIcon,
  PointingHandIcon,
  SpinnerIcon,
} from "@/components/icons"
import { Button } from "@/components/ui/button"
import { Spinner } from "@/components/ui/spinner"
import { useRunLog } from "@/hooks/use-api"
import { useCopy } from "@/hooks/use-copy"
import { NUDGE_MS, useFlash } from "@/hooks/use-flash"
import { useLive } from "@/hooks/use-live"
import { useTaskClock } from "@/hooks/use-task-clock"
import { useThread } from "@/hooks/use-thread"
import {
  userSince,
  type Approval,
  type Decision,
  type Owner,
  type Status,
} from "@/lib/api"
import {
  formatDuration,
  problemOf,
  problemReport,
  type Problem,
} from "@/lib/format"
import {
  canDrawLiquid,
  createLiquidTakeover,
  type LiquidTakeover,
} from "@/lib/liquid-takeover"
import { useT } from "@/lib/i18n"
import { reducedMotion } from "@/lib/motion"
import { doingNow, runningTask, stepUnderWay, type Task } from "@/lib/thread"

// How long a takeover or return may go unconfirmed before the pill shows the real state again. The runtime answers once
// the agent's action in flight is sent, which a held key makes up to about 10 s; a request that fails says so at once.
const PENDING_MS = 15_000
// After the pill switches, its button ignores clicks this long: the return button appears where the takeover
// button was, so a double click would otherwise take over and hand control straight back.
const SWITCH_LOCK_MS = 1000
// Holding the expand button this long shows the live view full screen.
const HOLD_MS = 500
// How long the desktop stays unavailable before the user is asked to report it: most problems clear up on their own
// within seconds (a restart, a dropped connection), and a report of one of those is noise.
const REPORT_AFTER_MS = 30_000

// The takeover frame is drawn as one thick stroke along its centerline (index.css: stroke-width): BAND wide, with
// RADIUS outer corners. Its box is the screen's plus 10px on each side (and 1px more below, under the pill), so the
// band reaches 1px over the screen. The screen is square, so the outer corners' radius is those 10px: inside and out
// the band's edges stay the same distance apart all round, as a monitor's bezel round its screen.
const BAND = 11
const RADIUS = 10

// When control changes hands the pill changes in one continuous motion rather than in steps: the label's prefix and
// the button morph to their new widths at once, on index.css's --ease-in-out (WAAPI can't read the variable), slow at
// both ends so the words they share never jolt (RESIZE). What leaves fades up out of the way (ROLL_OUT) while what
// comes in already rises into place on --ease-out (ROLL_IN), so the two cross and the place is never empty; for a
// prefix that grows, a little later, once there is about room for it (ROLL_IN_LATE_MS), since a label has no edge to
// clip it at.
const EASE_OUT = "cubic-bezier(0.23, 1, 0.32, 1)"
const EASE_IN_OUT = "cubic-bezier(0.77, 0, 0.175, 1)"
const ROLL_RISE = 4
const ROLL_BLUR = "blur(2px)"
const ROLL_OUT: KeyframeAnimationOptions = {
  duration: 160,
  easing: "ease-in",
}
const ROLL_IN: KeyframeAnimationOptions = {
  duration: 260,
  delay: 40,
  easing: EASE_OUT,
  fill: "backwards",
}
const ROLL_IN_LATE_MS = 90
const RESIZE: KeyframeAnimationOptions = {
  duration: 300,
  easing: EASE_IN_OUT,
}

/** The frame's box, and where the tab's two ends meet its bottom edge (the lines start there). */
type Outline = { width: number; height: number; left: number; right: number }

/** Half of the frame's centerline, from one end of the tab round one side to the middle of the top. */
function framePath(
  { width, height, left, right }: Outline,
  side: "left" | "right"
) {
  const c = BAND / 2
  const r = RADIUS - c
  const bottom = height - c
  if (side === "left")
    return `M${left} ${bottom}H${c + r}A${r} ${r} 0 0 1 ${c} ${bottom - r}V${c + r}A${r} ${r} 0 0 1 ${c + r} ${c}H${width / 2}`
  return `M${right} ${bottom}H${width - c - r}A${r} ${r} 0 0 0 ${width - c} ${bottom - r}V${c + r}A${r} ${r} 0 0 0 ${width - c - r} ${c}H${width / 2}`
}

/**
 * Classes for one of two texts that take turns in one place (data-text, rolled over by LiveView): the shown one is
 * laid out and sets the size, the other lies over it, hidden; centered in the button, and in the label's prefix at
 * its end, against the words both labels share.
 */
function slot(shown: boolean, place: "center" | "end") {
  return cn(
    "flex shrink-0 items-center gap-2",
    !shown && "pointer-events-none absolute opacity-0",
    !shown && (place === "center" ? "inset-0 justify-center" : "top-0 right-0")
  )
}

/**
 * That the desktop can't be used, in words for whoever uses it, who can't fix it; and once that has lasted, what to
 * send to someone who can: details to copy, with the code that says what is wrong. Mounted while one problem lasts
 * (keyed by its code), so it knows when that began.
 */
function Unavailable({ problem }: { problem: Problem }) {
  const t = useT()
  const began = useRef<Date | null>(null)
  const [lasting, setLasting] = useState(false)
  useEffect(() => {
    began.current = new Date()
    const timer = window.setTimeout(() => setLasting(true), REPORT_AFTER_MS)
    return () => window.clearTimeout(timer)
  }, [])
  const { copied, manual, copy } = useCopy()

  return (
    <>
      <OfflineIcon className="size-5 shrink-0 @max-sm:hidden" />
      <p className="font-medium text-neutral-100">{t.liveView.unavailable}</p>
      <p className="text-xs text-neutral-400">
        {t.liveView.recovering}
        <span aria-hidden className="loading-dots">
          <span>.</span>
          <span>.</span>
          <span>.</span>
        </span>
      </p>
      {import.meta.env.DEV && problem.code === "E-SERVICE" && (
        <p className="absolute top-2 right-3 text-xs text-neutral-500">
          local dev mode
        </p>
      )}
      {lasting && (
        <>
          <p className="mt-2 text-xs text-neutral-300">
            {t.liveView.stillDown}
          </p>
          <Button
            variant="ghost"
            size="xs"
            className="bg-white/10 text-neutral-100 hover:bg-white/20 hover:text-white"
            onClick={() =>
              copy(problemReport(problem, began.current ?? new Date()))
            }
          >
            {copied ? (
              <CheckIcon data-icon="inline-start" className="size-4" />
            ) : (
              <CopyIcon data-icon="inline-start" className="size-4" />
            )}
            <span aria-live="polite">
              {copied ? t.common.copied : t.common.copyDetails}
            </span>
          </Button>
          {manual && (
            <pre className="max-w-full shrink-0 overflow-x-auto rounded-md bg-black/40 px-3 py-2 text-left font-mono text-xs leading-4 text-neutral-300 select-all">
              {manual}
            </pre>
          )}
        </>
      )}
    </>
  )
}

/**
 * What the agent using the desktop is doing, over the screen's top edge: its step under way, or that it is thinking
 * about the next one, and how long it has worked, as the conversation's work group shows it. The live view can cover
 * the conversation (on a phone, or expanded), so it says it too. From the run's own events, whichever conversation it
 * is in; nothing while no work is under way. It goes as the takeover's blue comes and comes back as the blue drains
 * (`shown`: the agent has the desktop, and no step of it waits for the user's approval), the frame's place and its own
 * meeting at the top. Back, its timer stays stopped till the run's log says how long the user had the desktop.
 */
function WorkNow({
  task,
  shown,
  userSince,
}: {
  task: Task | null // the run's task under way
  shown: boolean
  userSince: number | null // the user has had the desktop since then, by the status
}) {
  const { worked } = useTaskClock(task, userSince, task !== null)
  if (!task) return null
  return (
    <p
      aria-hidden={!shown}
      data-hidden={shown ? undefined : ""}
      className="absolute inset-x-0 bottom-full mb-2.5 flex items-center gap-2 text-sm text-muted-foreground transition-[opacity,filter,translate] duration-250 ease-(--ease-out) data-hidden:translate-y-1 data-hidden:opacity-0 data-hidden:blur-[2px] data-hidden:duration-200 motion-reduce:transition-opacity"
    >
      <SpinnerIcon className="size-4" />
      <span className="shimmer min-w-0 truncate">{doingNow(task)}</span>
      <span className="ml-auto shrink-0 tabular-nums opacity-70">
        {formatDuration(worked)}
      </span>
    </p>
  )
}

/**
 * The desktop as it is now, streamed over WebRTC. While the agent has control it is only to watch; once the
 * user takes over, their mouse and keyboard reach the desktop, until they return it.
 *
 * Covering the conversation (expanded, full screen, or on a phone), it also asks the step the conversation waits for
 * the user to approve (`approval`), which the composer can't be seen asking, with what the composer would say above it
 * (`notice`), such as why an answer did not go through.
 */
export function LiveView({
  status,
  offline,
  onTakeover,
  onReturn,
  focusScreen = false,
  onScreenFocused,
  approval: asked = null,
  notice = null,
  onAnswer,
  onClose,
  expanded = false,
  onExpand,
  className,
}: {
  status: Status | null
  offline: boolean
  /** Ask for control or give it back; true once the runtime has done it. */
  onTakeover: () => Promise<boolean>
  onReturn: () => Promise<boolean>
  /** The user took over outside the live view (the composer, a notice): the keyboard goes to the desktop. */
  focusScreen?: boolean
  onScreenFocused?: () => void
  approval?: Approval | null
  notice?: string | null
  onAnswer?: (decision: Decision, note: string) => Promise<boolean> // true once answered
  onClose?: () => void
  /** On a side panel: whether it fills the page, and how to switch. */
  expanded?: boolean
  onExpand?: () => void
  className?: string
}) {
  const t = useT()
  const root = useRef<HTMLElement>(null)
  const fullscreen = useFullscreen(root)
  // Beside the conversation, the composer asks for an approval; covering it, the live view does.
  const approval = !onExpand || expanded || fullscreen ? asked : null
  const owner = status?.control.owner ?? "agent"
  const userHasControl = owner === "user"
  const { stream, state, send, pointer } = useLive(status?.ice_servers ?? null)
  // The run at work, from its own events: the line over the screen says what it does, and while the agent on the
  // desktop works out its next step (none under way), its pointer swings.
  const events = useRunLog(status?.active ?? null)
  const task = runningTask(useThread(events))
  const thinking = task?.tool === "computer_use" && !stepUnderWay(task)
  // The control the user just asked for, until the runtime's status shows it. Taking over waits for it (the
  // agent has to stop first); returning shows the agent's pill at once.
  const [pending, setPending] = useFlash<Owner>(PENDING_MS)
  if (pending && pending === owner) setPending(null)
  const shown = pending === "agent" ? "agent" : owner
  const lockedUntil = useRef(0)
  const lastShown = useRef(shown)
  useEffect(() => {
    if (lastShown.current === shown) return
    lastShown.current = shown
    lockedUntil.current = performance.now() + SWITCH_LOCK_MS
  }, [shown])
  // A takeover or return that didn't happen, said over the screen for a moment; and a takeover that did, after which
  // the keyboard goes to the desktop.
  const [failed, setFailed] = useFlash<Owner>(NUDGE_MS)
  const [tookOver, setTookOver] = useState(false)
  /** Ask for control, unless the pill has only just switched. `at` is the click's time (performance.now's clock). */
  const request = async (
    next: Owner,
    ask: () => Promise<boolean>,
    at: number
  ) => {
    if (at < lockedUntil.current) return
    lockedUntil.current = at + SWITCH_LOCK_MS
    aim()
    setFailed(null)
    setPending(next)
    if (await ask()) {
      if (next === "user") setTookOver(true)
      return
    }
    // The pill goes back to who has control after all, at once, rather than when the wait runs out.
    setPending(null)
    setFailed(next)
  }
  const waiting = pending === "user"
  const user = shown === "user"

  const problem = problemOf(status, offline)

  // Choose canvas or the CSS fallback before first paint; reduced motion uses CSS.
  const [liquid] = useState(() => !reducedMotion() && canDrawLiquid())
  const stage = useRef<HTMLDivElement>(null)
  const pill = useRef<HTMLDivElement>(null)
  const screenBox = useRef<HTMLDivElement>(null)
  const canvas = useRef<HTMLCanvasElement>(null)
  const surface = useRef<LiquidTakeover | null>(null)
  useLayoutEffect(() => {
    if (!liquid || !canvas.current) return
    const drawn = createLiquidTakeover(canvas.current, () => {
      const button = pill.current?.querySelector("button")
      return screenBox.current && pill.current && button
        ? { screen: screenBox.current, pill: pill.current, button }
        : null
    })
    surface.current = drawn
    return () => {
      drawn?.dispose()
      surface.current = null
    }
  }, [liquid])
  // Nobody operates a desktop that can't be reached, so no frame then.
  const framed = !problem && user
  useLayoutEffect(() => surface.current?.setTarget(framed), [framed])

  // Measure the takeover origin on load, resize and clicks, not every render,
  // so transitions retain their starting point.
  const frame = useRef<SVGSVGElement>(null)
  const [outline, setOutline] = useState<Outline | null>(null)
  const fill = useRef<HTMLSpanElement>(null)
  const aim = useCallback(() => {
    const button = pill.current?.querySelector("button")
    if (!button || !stage.current || !frame.current || !pill.current) return
    if (!fill.current) return
    // At rest the fill is clipped to the button's own shape (--fill-from, its insets within the fill's box), so the
    // blue widens out of the button and narrows back into it exactly.
    const b = button.getBoundingClientRect()
    const box = fill.current.getBoundingClientRect()
    stage.current.style.setProperty(
      "--fill-from",
      `${b.top - box.top}px ${box.right - b.right}px ${box.bottom - b.bottom}px ${b.left - box.left}px`
    )
    const p = pill.current.getBoundingClientRect()
    const f = frame.current.getBoundingClientRect()
    const along = (x: number) =>
      Math.round(Math.min(Math.max(x - f.left, RADIUS), f.width - RADIUS))
    const next: Outline = {
      width: Math.round(f.width * 2) / 2,
      height: Math.round(f.height * 2) / 2,
      left: along(p.left),
      right: along(p.right),
    }
    setOutline((current) =>
      current &&
      current.width === next.width &&
      current.height === next.height &&
      current.left === next.left &&
      current.right === next.right
        ? current
        : next
    )
  }, [])
  // Measured again once the status has loaded: before that the pill reads 「連線中…」 and its button sits elsewhere.
  const loaded = status !== null
  useLayoutEffect(() => {
    aim()
    // The panel can be resized on its own, so watch it rather than the window.
    const observer = new ResizeObserver(() => aim())
    if (stage.current) observer.observe(stage.current)
    return () => observer.disconnect()
  }, [aim, loaded])
  // And right after the pill switches, at its new size: taking over ends with the tab and the frame around
  // 「交還控制權」, and returning narrows the blue into 「接管」.
  useLayoutEffect(aim, [aim, shown])

  // Roll label and button text on ownership changes. Keep text colors fixed while
  // the background changes to preserve contrast. Measure widths before the switch;
  // interrupted animations resume from their current text positions and widths.
  const prefix = useRef<HTMLSpanElement>(null)
  const widths = useRef<number[]>([])
  const resizes = useRef<Animation[]>([])
  const sizedFor = useRef(shown)
  useLayoutEffect(() => {
    const parts = [prefix.current, pill.current?.querySelector("button")]
    const measure = () =>
      parts.map((part) => part?.getBoundingClientRect().width ?? 0)
    const resizing = resizes.current.some(
      (animation) => animation.playState === "running"
    )
    if (sizedFor.current === shown) {
      if (!resizing) widths.current = measure()
      return
    }
    sizedFor.current = shown
    // Switched again mid-resize: from the widths it has got to.
    const before = resizing ? measure() : widths.current
    for (const animation of resizes.current) animation.cancel()
    resizes.current = []
    widths.current = measure()
    // With motion reduced the texts only fade, and the widths change at once.
    const reduced = reducedMotion()
    parts.forEach((part, i) => {
      const [from, to] = [before[i], widths.current[i]]
      if (reduced || !part || !from || !to || from === to) return
      resizes.current.push(
        part.animate({ width: [`${from}px`, `${to}px`] }, RESIZE)
      )
    })
    const up = shown === "user" ? 1 : -1
    const prefixGrows = widths.current[0] > before[0]
    const texts = pill.current?.querySelectorAll<HTMLElement>("[data-text]")
    for (const text of texts ?? []) {
      const rise = reduced ? 0 : ROLL_RISE * up
      const blur = reduced ? "none" : ROLL_BLUR
      const rolling = text.getAnimations()
      const style = getComputedStyle(text)
      const from = rolling.length
        ? {
            opacity: style.opacity,
            transform: style.transform,
            filter: style.filter,
          }
        : null
      for (const animation of rolling) animation.cancel()
      if (text.dataset.text !== shown) {
        text.animate(
          [
            from ?? { opacity: 1, transform: "none", filter: "none" },
            {
              opacity: 0,
              transform: `translateY(${-rise}px)`,
              filter: blur,
            },
          ],
          ROLL_OUT
        )
        continue
      }
      const late = prefixGrows && text.closest("[data-prefix]")
      text.animate(
        [
          from ?? {
            opacity: 0,
            transform: `translateY(${rise}px)`,
            filter: blur,
          },
          { opacity: 1, transform: "none", filter: "none" },
        ],
        { ...ROLL_IN, delay: from ? 0 : late ? ROLL_IN_LATE_MS : ROLL_IN.delay }
      )
    }
  })

  // One button in the corner: to expand or shrink it where it can be, else to close it; full screen, to leave it.
  const corner = fullscreen
    ? {
        label: t.liveView.exitFullscreen,
        Icon: ShrinkIcon,
        onClick: () => void document.exitFullscreen(),
        pressed: true,
      }
    : onExpand
      ? {
          label: expanded ? t.liveView.shrink : t.liveView.expand,
          Icon: expanded ? ShrinkIcon : ExpandIcon,
          onClick: onExpand,
          pressed: expanded,
        }
      : onClose && {
          label: t.liveView.close,
          Icon: CloseIcon,
          onClick: onClose,
          pressed: undefined,
        }
  // Held, the expand button shows it full screen instead, where the page can be (not on an iPhone).
  const hold = useHoldForFullscreen(
    root,
    !!onExpand && !fullscreen && document.fullscreenEnabled
  )

  return (
    <aside
      ref={root}
      className={cn("relative flex min-h-0 flex-col bg-background", className)}
      aria-label={t.liveView.label}
    >
      {corner && (
        <Button
          variant="ghost"
          size="icon"
          aria-label={corner.label}
          aria-pressed={corner.pressed}
          className="absolute top-1.5 right-2.5 z-10"
          {...hold.handlers}
          onClick={() => {
            if (!hold.held()) corner.onClick()
          }}
        >
          <corner.Icon className="size-5" />
        </Button>
      )}

      {/* data-control drives the takeover frame and pill styles in index.css; unset while the desktop can't be
        reached, since then nobody is operating it. */}
      <div
        ref={stage}
        data-control={problem ? undefined : shown}
        data-liquid={liquid || undefined}
        className={cn(
          "flex min-h-0 flex-1 flex-col items-center justify-center overflow-y-auto px-5",
          fullscreen ? "py-4" : "py-12"
        )}
      >
        {/* The screen, as wide as the panel allows while it still fits its height, less the stage's padding, the
          line over it and the pill (12rem; 8rem full screen, where the stage pads less), and a step to approve
          (5rem). Isolated, so the takeover's layers stack within it: screen, pill background, blue, pill text. */}
        <div
          className="@container relative isolate mt-7.5 flex shrink-0 flex-col items-center"
          style={{
            width: `min(100%, calc((100svh - ${(fullscreen ? 8 : 12) + (approval ? 5 : 0)}rem) * 1.6))`,
          }}
        >
          {liquid && (
            <canvas ref={canvas} aria-hidden className="takeover-canvas" />
          )}
          {status?.active && (
            <WorkNow
              key={status.active}
              task={task}
              shown={
                !user && !problem && status.approval?.run !== status.active
              }
              userSince={userSince(status)}
            />
          )}
          <div className="relative w-full">
            {!liquid && (
              <svg ref={frame} aria-hidden className="takeover-frame">
                {outline && (
                  <>
                    <path
                      className="takeover-line"
                      pathLength={1}
                      d={framePath(outline, "left")}
                    />
                    <path
                      className="takeover-line"
                      pathLength={1}
                      d={framePath(outline, "right")}
                    />
                  </>
                )}
              </svg>
            )}
            {/* Square, as the desktop it shows is: none of it is cut off at the corners, and the frame round it (RADIUS,
              and SCREEN_RADIUS in liquid-takeover.ts) has no curve of the screen's to follow. */}
            <div
              ref={screenBox}
              className="takeover-screen relative aspect-[16/10] overflow-hidden bg-neutral-950"
            >
              <RemoteScreen
                stream={stream}
                // Not while the desktop can't be reached: the screen says so, and nothing typed there would arrive.
                interactive={userHasControl && state === "live" && !problem}
                send={send}
                pointer={pointer}
                thinking={thinking}
                notice={
                  failed === "user"
                    ? t.liveView.takeoverFailed
                    : failed === "agent"
                      ? t.liveView.returnFailed
                      : null
                }
                focus={focusScreen || tookOver}
                onFocused={() => {
                  setTookOver(false)
                  onScreenFocused?.()
                }}
              />
              {(problem || state !== "live") && (
                <div className="absolute inset-0 flex flex-col items-center justify-center-safe gap-2 overflow-y-auto bg-neutral-950/85 p-6 text-center text-sm text-neutral-200 @max-sm:p-4">
                  {problem ? (
                    <Unavailable key={problem.code} problem={problem} />
                  ) : (
                    <>
                      <Spinner className="size-5" />
                      {state === "retrying"
                        ? t.connection.reconnecting
                        : t.liveView.connecting}
                    </>
                  )}
                </div>
              )}
            </div>
          </div>

          {/* Hidden, not removed, while the desktop can't be reached, and while its video isn't in yet: the screen above
            says why, nobody takes over a desktop they can't see, and keeping its space stops the screen from shifting
            when the video comes in. The user's own control stays, though: handing back needs no sight of the screen,
            and the agent waits on it. */}
          <div
            ref={pill}
            className={cn(
              "takeover-pill",
              (problem || (state !== "live" && !user)) && "invisible"
            )}
          >
            <span aria-hidden className="takeover-pill-bg" />
            {!liquid && (
              <span ref={fill} aria-hidden className="takeover-fill" />
            )}
            {/* One label and one button for both owners, each holding both texts (slot), so a switch rolls and resizes
              them in place (the effect above) instead of swapping elements. */}
            <span className="relative z-[3] flex items-center gap-3">
              {/* Below 20rem the tab and its concave corners would outgrow the frame's straight bottom edge, so the pill
                keeps only its button. */}
              <span className="flex items-center text-sm whitespace-nowrap @max-xs:hidden">
                {status ? (
                  <>
                    <span
                      ref={prefix}
                      data-prefix
                      className="relative flex justify-end"
                    >
                      <span
                        data-text="agent"
                        aria-hidden={user}
                        className={slot(!user, "end")}
                      >
                        {t.liveView.agent}
                      </span>
                      <span
                        data-text="user"
                        aria-hidden={!user}
                        className={slot(user, "end")}
                      >
                        {t.liveView.you}
                      </span>
                    </span>
                    {t.liveView.control}
                  </>
                ) : (
                  t.liveView.connecting
                )}
              </span>
              <Button
                size="lg"
                className={cn(
                  "relative overflow-hidden rounded-full px-4",
                  user && "bg-black/15 hover:bg-black/25"
                )}
                aria-busy={user ? undefined : waiting}
                onClick={(event) =>
                  user
                    ? request("agent", onReturn, event.timeStamp)
                    : !waiting && request("user", onTakeover, event.timeStamp)
                }
                disabled={!user && !status}
              >
                <span
                  data-text="agent"
                  aria-hidden={user}
                  className={cn(
                    slot(!user, "center"),
                    "text-primary-foreground"
                  )}
                >
                  {/* Waiting on the runtime: after a moment, so a quick takeover shows none, the hand turns into
                    a spinner of its size, and nothing else in the pill moves. */}
                  <span className="relative flex size-5 shrink-0">
                    <PointingHandIcon
                      className={cn(
                        "size-5",
                        waiting &&
                          "animate-out delay-300 duration-150 fill-mode-forwards fade-out"
                      )}
                    />
                    {waiting && (
                      <span className="absolute inset-0 animate-in delay-300 duration-150 fill-mode-both fade-in">
                        <Spinner aria-hidden className="size-5" />
                      </span>
                    )}
                  </span>
                  {t.liveView.takeOver}
                </span>
                <span
                  data-text="user"
                  aria-hidden={!user}
                  className={cn(slot(user, "center"), "text-white")}
                >
                  <CursorEnterIcon />
                  {t.liveView.returnControl}
                </span>
              </Button>
            </span>
          </div>
        </div>
        {approval && onAnswer && (
          <ApprovalBar
            key={approval.id}
            approval={approval}
            notice={notice}
            onAnswer={onAnswer}
          />
        )}
      </div>
    </aside>
  )
}

/** Whether `root` is shown full screen; the browser's own Esc or a swipe can end it, so it is read from the page. */
function useFullscreen(root: RefObject<HTMLElement | null>) {
  const [fullscreen, setFullscreen] = useState(false)
  useEffect(() => {
    const changed = () =>
      setFullscreen(document.fullscreenElement === root.current)
    document.addEventListener("fullscreenchange", changed)
    return () => document.removeEventListener("fullscreenchange", changed)
  }, [root])
  return fullscreen
}

/** Press handlers for the expand button that show `root` full screen once it is held, and whether the press was a
 * hold, whose click then does nothing. The browser counts a mouse press as the user's own act, so full screen comes
 * while it is held; a touch counts only once lifted, so a held touch asks again then. */
function useHoldForFullscreen(
  root: RefObject<HTMLElement | null>,
  enabled: boolean
) {
  const timer = useRef(0)
  const held = useRef(false)
  const cancel = () => clearTimeout(timer.current)
  return {
    held: () => held.current,
    handlers: {
      onPointerDown: () => {
        if (!enabled) return
        timer.current = window.setTimeout(() => {
          held.current = true
          showFullscreen(root.current)
        }, HOLD_MS)
      },
      onPointerUp: () => {
        cancel()
        if (held.current && !document.fullscreenElement)
          showFullscreen(root.current)
        // After the click this release brings, if any.
        setTimeout(() => (held.current = false))
      },
      onPointerLeave: cancel,
      onPointerCancel: cancel,
    },
  }
}

/** Show `root` full screen. There, Esc goes to the desktop like any other key, where the browser allows (Chrome and
 * Edge): holding it leaves full screen. */
function showFullscreen(root: HTMLElement | null) {
  const keyboard = (
    navigator as { keyboard?: { lock(keys: string[]): Promise<void> } }
  ).keyboard
  root
    ?.requestFullscreen()
    .then(() => keyboard?.lock(["Escape"]))
    .catch(() => {})
}

/** Mirror approval controls when the live view covers the composer.
 * Keep failed answers retryable; keyboard shortcuts and rejection notes stay in the composer. */
function ApprovalBar({
  approval,
  notice,
  onAnswer,
}: {
  approval: Approval
  notice: string | null
  onAnswer: (decision: Decision, note: string) => Promise<boolean>
}) {
  const t = useT()
  const [answering, setAnswering] = useState(false)
  async function answer(decision: Decision) {
    setAnswering(true)
    if (!(await onAnswer(decision, ""))) setAnswering(false)
  }
  return (
    <div className="mt-6 w-full max-w-3xl shrink-0">
      {notice && (
        <p
          role="alert"
          className="mb-2 rounded-lg bg-destructive/10 px-3 py-2 text-sm text-destructive"
        >
          {notice}
        </p>
      )}
      <div className="flex w-full animate-in flex-wrap items-center justify-end gap-x-3 gap-y-2 rounded-[1.75rem] border bg-background p-2 pl-3 shadow-[0_2px_8px_rgb(0_0_0/0.04)] duration-200 ease-(--ease-out) fade-in slide-in-from-bottom-1 motion-reduce:animate-none dark:bg-[color-mix(in_oklch,var(--muted)_40%,var(--background))]">
        <div className="flex min-h-10 min-w-0 flex-[1_1_14rem] items-center gap-2.5 pr-2 pl-1">
          <HandIcon className="size-5 shrink-0 text-warning" />
          <p role="status" className="min-w-0 text-sm text-pretty">
            {t.composer.approval.ask(approval.consequence)}
          </p>
        </div>
        <AnswerPair
          decline={{
            label: t.composer.approval.decline,
            onClick: () => answer("reject"),
            disabled: answering,
          }}
          accept={{
            label: t.composer.approval.approve,
            onClick: () => answer("approve"),
            disabled: answering,
          }}
        />
      </div>
    </div>
  )
}
