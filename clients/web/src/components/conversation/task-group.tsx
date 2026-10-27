import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ComponentType,
  type SVGProps,
} from "react"
import { cn } from "cn"

import {
  Trace,
  TraceCollapsible,
  TraceCollapsibleContent,
  TraceCollapsibleTrigger,
  TraceDescription,
  TraceIcon,
  TraceLine,
  TraceTitle,
} from "@/components/ui/trace"
import { useTaskClock } from "@/hooks/use-task-clock"
import { describeAction, formatDuration } from "@/lib/format"
import { useT } from "@/lib/i18n"
import {
  awaitingDesktop,
  doingNow,
  phasesOf,
  stepTool,
  stepUnderWay,
  type Task,
  type TaskEntry,
} from "@/lib/thread"
import {
  AgentIcon,
  CodeIcon,
  InfoIcon,
  MonitorIcon,
  OfflineIcon,
  PauseCircleIcon,
  SpinnerIcon,
  ToolIcon,
} from "@/components/icons"
import { Markdown } from "@/components/markdown/markdown"
import {
  PhaseLine,
  PlainLine,
  StepLine,
  Thumbnail,
} from "@/components/conversation/steps"

// Each agent the main agent hands work to, in its own icon, by the tool that hands it over (agent/subagent.py).
const AGENT_ICONS: Record<string, ComponentType<SVGProps<SVGSVGElement>>> = {
  computer_use: MonitorIcon,
  write_code: CodeIcon,
}

// What an agent reported: in markdown as a reply is, without a mark.
const REPORT = "arrive-line space-y-1.5 pt-1 text-sm leading-6"

/** Collapsible delegated work with steps and results. Duration excludes user waits;
 * steps stay folded until the user opens them. */
export function TaskGroup({
  task,
  run,
  active,
  last,
  approving,
  takingOver,
  userSince,
  disconnected,
  full,
  onFull,
  onOpenShot,
  onOpenLive,
  agent = false,
}: {
  task: Task
  run: string
  active: boolean // the run is in progress
  last: number | null // the run's last event, for a task that never ended
  approving: string | null // the step under way waits for the user's approval: what it will do
  takingOver: boolean // it asked the user to take the desktop over, which the composer asks
  userSince: number | null // the user has had the desktop it uses since then, by the runtime's status
  disconnected: boolean // it waits for the desktop to reconnect
  full: boolean // opened by the user: every step with its screen; folded until then, while it works too
  onFull: (full: boolean) => void
  onOpenShot: (name: string) => void
  onOpenLive: () => void
  agent?: boolean // one of the run's agents: its title, what it does now, for how long
}) {
  const t = useT()
  const running = task.outcome === "running" && active
  // The desktop is the user's: since when, by the status, which knows at once; or by the log.
  // The user's turns at the desktop in the task under way: of a run's tasks shown as one, the last one's, whose keys
  // alone are by their place (thread.ts mergeTasks).
  const controls = task.entries.filter(
    (entry) => entry.kind === "control" && entry.key.startsWith("control-")
  )
  const logged = awaitingDesktop(task)
  const { took, worked: elapsed } = useTaskClock(task, userSince, running, last)
  const paused = running && (took !== null || logged)
  // Waiting for the user (a step to approve, the desktop to take or hand back) or for the desktop: not moving.
  const moving =
    running && !paused && !takingOver && !disconnected && approving === null
  // What it waits for, which the summary says in place of working, folded or not; the last of it stays, so its words
  // can leave as the others come.
  const held =
    !running || moving
      ? null
      : disconnected
        ? t.run.work.waiting.desktop
        : paused
          ? t.run.work.waiting.control
          : takingOver
            ? t.run.work.waiting.takeover
            : t.run.work.waiting.approval
  const [lastHeld, setLastHeld] = useState(held)
  if (held !== null && held !== lastHeld) setLastHeld(held)
  const stopped =
    task.outcome === "stopped" || (!running && task.outcome === "running")
  const failed = task.outcome === "failed"
  const Kind = AGENT_ICONS[task.tool] ?? ToolIcon
  const shots = task.entries.flatMap((entry) =>
    entry.kind === "step" && entry.step.action?.screenshot
      ? [entry.step.action.screenshot]
      : []
  )
  const liveShot = shots.at(-1) ?? null
  const underWay = running ? stepUnderWay(task) : null
  const ended = !active
  const doing = moving ? doingNow(task) : t.run.work.working
  // What an agent's line says after its title: what it does or waits for, while folded (opened, its steps say it);
  // once it ended, nothing, unless it fell short.
  const now = full
    ? ""
    : running
      ? (held ?? doing)
      : failed
        ? t.run.work.failed
        : stopped
          ? t.run.work.stopped
          : ""
  const parts = phasesOf(task.entries)
  // The part under way, open while it is; the others say only what they did, till the user opens one.
  const current = running
    ? parts.findLast((part) => part.kind === "phase")
    : undefined

  // The desktop gone, while it comes back: in words, with the passing dots the live view has for it.
  const reconnecting = (
    <>
      {t.run.work.reconnecting}
      <span aria-hidden className="loading-dots">
        <span>.</span>
        <span>.</span>
        <span>.</span>
      </span>
    </>
  )

  const line = (entry: TaskEntry) => {
    switch (entry.kind) {
      case "step": {
        // Under way, unless the user has the desktop: whatever it was about to do waits for them.
        const under = entry.step === underWay && !paused
        const { tool, args } = stepTool(entry.step)
        // Its request to take the desktop over, which the user hasn't answered yet: said as a step to approve is.
        const asking =
          takingOver && entry.step === underWay && tool === "request_takeover"
        // Waiting for approval, it is the composer's to ask, right under it: once answered, it is a step as any other.
        if (under && approving) return null
        return (
          <StepLine
            key={entry.key}
            step={entry.step}
            run={run}
            running={under && !asking}
            waiting={asking ? describeAction(tool, args).label : null}
            full={full}
            ended={ended}
            onOpenShot={onOpenShot}
          />
        )
      }
      case "note":
        return (
          <PlainLine key={entry.key} icon={<InfoIcon />}>
            {entry.text}
          </PlainLine>
        )
      case "control":
        return turnLine(entry.key, entry.seconds)
      case "offline": {
        // While the desktop reconnects, and once it is back, how long it was gone, in its place as the user's turn is;
        // or, the agent having given up on it, that it did not come back in time.
        const { key, seconds, gaveUp } = entry
        const back = seconds !== null
        const time = back ? formatDuration(seconds) : ""
        return (
          <PlainLine key={key} icon={<OfflineIcon />}>
            <span className="swap">
              <span data-hidden={back ? "before" : undefined}>
                {reconnecting}
              </span>
              <span data-hidden={back ? undefined : ""}>
                {back &&
                  (gaveUp
                    ? t.run.work.gaveUp(time)
                    : t.run.work.wasOffline(time))}
              </span>
            </span>
          </PlainLine>
        )
      }
    }
  }

  // The user's turn at the desktop: while they have it, and once it is back, how long they had it, in its place.
  // Asked for and not taken yet, it is the request's to say. While the desktop can't be reached, that is what the line
  // says, as the summary does: nobody is in control of a desktop that is gone, and the line swaps back once it is not.
  const turnLine = (key: string, seconds: number | null) => {
    if (seconds === null && running && takingOver) return null
    const back = seconds !== null
    const gone = !back && running && disconnected
    return (
      <PlainLine
        key={key}
        icon={
          <span className="swap">
            <PauseCircleIcon data-hidden={gone ? "" : undefined} />
            <OfflineIcon data-hidden={gone ? undefined : ""} />
          </span>
        }
      >
        <span className="swap">
          <span data-hidden={back || gone ? "before" : undefined}>
            {running ? t.run.work.paused : t.run.work.tookOver}
          </span>
          <span data-hidden={gone ? undefined : ""}>{reconnecting}</span>
          <span data-hidden={back ? undefined : ""}>
            {back && t.run.work.operated(formatDuration(seconds))}
          </span>
        </span>
      </PlainLine>
    )
  }
  // One list, so the line the status opens is the one the log has next, under the same key (thread.ts): in the last
  // part, where the log would have it.
  const opened =
    paused && !logged ? turnLine(`control-${controls.length}`, null) : null
  const lines = parts.map((part, index) =>
    part.kind !== "phase" ? (
      line(part)
    ) : (
      <PhaseLine
        key={part.key}
        phase={part}
        icon={Kind}
        current={part === current}
        lines={[
          ...part.entries.map(line),
          index === parts.length - 1 && opened,
        ]}
      />
    )
  )
  if (opened && parts.at(-1)?.kind !== "phase") lines.push(opened)

  return (
    <Trace className="arrive-line gap-0">
      <TraceCollapsible open={full} onOpenChange={onFull}>
        <div className="flex min-w-0 items-center gap-3">
          <TraceCollapsibleTrigger>
            <TraceLine
              status={failed ? "error" : undefined}
              className="min-h-7"
            >
              {agent ? (
                <>
                  <TraceIcon>
                    <AgentIcon
                      className={cn(
                        "size-4",
                        !running && "text-muted-foreground"
                      )}
                    />
                  </TraceIcon>
                  <TraceTitle
                    className={cn(
                      "max-w-80 shrink-0",
                      !running && "text-muted-foreground"
                    )}
                  >
                    {task.title}
                  </TraceTitle>
                  {/* What it does now, or what came of it, its words swapping in place; then for how long. */}
                  {/* Its own space before it, in place of the line's gap, so the box closes up once nothing is left. */}
                  <span className="-ml-2 min-w-0 truncate text-muted-foreground">
                    <SwapText
                      text={now && `\u2002${now}`}
                      className={cn(moving && "shimmer")}
                    />
                  </span>
                  <TraceDescription>{formatDuration(elapsed)}</TraceDescription>
                </>
              ) : (
                <>
                  {/* Spinning while it works, what it works with while it waits; done, the words alone, as Codex's
                  "Worked for". */}
                  {running && (
                    <TraceIcon>
                      <span className="swap">
                        <SpinnerIcon
                          className="size-4"
                          data-hidden={moving ? undefined : ""}
                        />
                        <Kind
                          className="size-4"
                          data-hidden={moving ? "" : undefined}
                        />
                      </span>
                    </TraceIcon>
                  )}
                  <TraceTitle className="swap">
                    {/* Shimmering on its own: a shimmer on both would show the hidden words through it. */}
                    <span
                      data-hidden={running && !held ? undefined : "before"}
                      className="truncate"
                    >
                      <SwapText
                        text={doing}
                        className={cn(moving && "shimmer")}
                      />
                    </span>
                    <span
                      data-hidden={held ? undefined : running ? "" : "before"}
                    >
                      {held ?? lastHeld}
                    </span>
                    <span data-hidden={running ? "" : undefined}>
                      {failed
                        ? t.run.work.failed
                        : stopped
                          ? t.run.work.stopped
                          : t.run.work.worked}
                    </span>
                  </TraceTitle>
                  <TraceDescription>{formatDuration(elapsed)}</TraceDescription>
                </>
              )}
            </TraceLine>
          </TraceCollapsibleTrigger>
          {running && !disconnected && liveShot && (
            <Thumbnail
              key="live"
              run={run}
              name={liveShot}
              label={t.run.work.live}
              live
              onOpen={onOpenLive}
            />
          )}
        </div>
        <TraceCollapsibleContent className="space-y-0.5">
          {lines}
          {/* What the agent reported, in markdown as a reply is, without a mark: it is what an agent said, not a
              step. */}
          {!running && task.outcome === "done" && task.result && (
            <Markdown text={task.result} className={REPORT} />
          )}
        </TraceCollapsibleContent>
      </TraceCollapsible>
    </Trace>
  )
}

// How long the old words take to leave (index.css swap-text), after which they are gone.
const SWAP_MS = 200

/** Words that change in place: the old ones leave upward as the new come up from below, the box easing to the new
 * width (index.css swap-text). The page's first words are simply there. */
function SwapText({ text, className }: { text: string; className?: string }) {
  type Line = { key: number; text: string; leaving: boolean }
  const [lines, setLines] = useState<Line[]>(() => [
    { key: 0, text, leaving: false },
  ])
  const current = lines.findLast((line) => !line.leaving)!
  if (current.text !== text)
    setLines([
      ...lines.map((line) => ({ ...line, leaving: true })),
      { key: current.key + 1, text, leaving: false },
    ])
  const leaving = lines.some((line) => line.leaving)
  useEffect(() => {
    if (!leaving) return
    const timer = window.setTimeout(
      () => setLines((all) => all.filter((line) => !line.leaving)),
      SWAP_MS
    )
    return () => window.clearTimeout(timer)
  }, [leaving, current.key])
  // The box eases from the old words' width to the new ones', measured off-screen as they change and as the line
  // comes into view: words measured while hidden (in a folded group) measure nothing, and the box is then left to fit
  // them.
  const sizer = useRef<HTMLSpanElement>(null)
  const [width, setWidth] = useState<number | null>(null)
  useLayoutEffect(() => {
    const words = sizer.current
    if (!words) return
    const measure = () => {
      // Rounded up: a width cut short by a fraction of a pixel would end the words in an ellipsis. No words measure
      // nothing too, and the box closes up.
      const measured = Math.ceil(words.getBoundingClientRect().width)
      setWidth(measured > 0 || !words.textContent ? measured : null)
    }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(words)
    return () => observer.disconnect()
  }, [])
  return (
    <span className="swap-text" style={width === null ? undefined : { width }}>
      <span ref={sizer} data-sizer aria-hidden>
        {text}
      </span>
      {lines.map((line) => (
        <span
          key={line.key}
          data-line={line.leaving ? "leave" : "enter"}
          aria-hidden={line.leaving || undefined}
          className={className}
        >
          {line.text}
        </span>
      ))}
    </span>
  )
}
