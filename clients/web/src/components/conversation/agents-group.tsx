import { type CSSProperties, type ReactNode } from "react"
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
import { useNow } from "@/hooks/use-now"
import { formatDuration } from "@/lib/format"
import { useT } from "@/lib/i18n"
import { type Task } from "@/lib/thread"
import { AgentIcon } from "@/components/icons"
import { Thumbnail } from "@/components/conversation/steps"

// The most agents drawn side by side in the line for them all.
const STACKED = 4

/** A run's agents at work, as one line: their robots side by side, a new one growing in beside the others as it is
 * handed work (index.css grow-in), how many work and for how long; opened, a line per agent, each opened on its own. */
export function AgentsGroup({
  tasks,
  run,
  active,
  last,
  full,
  onFull,
  opened,
  onOpen,
  onOpenLive,
  task: group,
}: {
  tasks: Task[]
  run: string
  active: boolean
  last: number | null
  full: boolean
  onFull: (full: boolean) => void
  opened: (key: string) => boolean
  onOpen: (key: string, open: boolean) => void
  onOpenLive: () => void
  task: (
    task: Task,
    full: boolean,
    onFull: (full: boolean) => void
  ) => ReactNode
}) {
  const t = useT()
  const running = tasks.filter((task) => task.outcome === "running").length
  const working = active && running > 0
  const done = tasks.length - running
  const now = useNow(working)
  const started = Math.min(...tasks.map((task) => task.started))
  const until = working
    ? now
    : Math.max(...tasks.map((task) => task.ended ?? last ?? task.started))
  // On the computer now: its latest screen, as a task alone shows it; while folded only, since opened, the agent's own
  // line shows it.
  const computer =
    working && !full
      ? tasks.find(
          (task) => task.outcome === "running" && task.tool === "computer_use"
        )
      : undefined
  const liveShot = computer?.entries.findLast(
    (entry) => entry.kind === "step" && entry.step.action?.screenshot
  )
  // Working, the agents still at it (the ones done are counted after it); done, all of them.
  const count = working ? running : tasks.length
  const title = working
    ? t.run.agents.working(count)
    : t.run.agents.worked(count)
  // The words around the count, which pops in on its own.
  const [before, after] = title.split(String(count))
  return (
    <Trace className="arrive-line gap-0">
      <TraceCollapsible open={full} onOpenChange={onFull}>
        <div className="flex min-w-0 items-center gap-3">
          <TraceCollapsibleTrigger>
            <TraceLine className="min-h-7">
              <TraceIcon className="size-auto">
                <span className="flex items-center">
                  {tasks.slice(0, STACKED).map((task, index) => (
                    <span
                      key={task.key}
                      className={cn(
                        "flex size-5 shrink-0 items-center justify-center rounded-full bg-background ring-1 ring-border",
                        index > 0 && "grow-in -ml-1.5"
                      )}
                    >
                      <AgentIcon className="size-3.5" />
                    </span>
                  ))}
                </span>
              </TraceIcon>
              <TraceTitle>
                {/* The words rise into place as they change; the count, keyed by itself, pops its digits in. */}
                <span
                  key={String(working)}
                  className={cn("reveal", working && "shimmer")}
                >
                  {before}
                  <span key={count} className="inline-flex">
                    {String(count)
                      .split("")
                      .map((digit, n) => (
                        <span
                          key={n}
                          className="pop-in"
                          style={{ "--digit": n } as CSSProperties}
                        >
                          {digit}
                        </span>
                      ))}
                  </span>
                  {after}
                </span>
              </TraceTitle>
              <TraceDescription>
                {working && done > 0 && `${t.run.agents.done(done)} · `}
                {formatDuration(Math.max(0, until - started))}
              </TraceDescription>
            </TraceLine>
          </TraceCollapsibleTrigger>
          {liveShot?.kind === "step" && liveShot.step.action?.screenshot && (
            <Thumbnail
              key="live"
              run={run}
              name={liveShot.step.action.screenshot}
              label={t.run.work.live}
              live
              onOpen={onOpenLive}
            />
          )}
        </div>
        <TraceCollapsibleContent className="space-y-1 pl-2">
          {tasks.map((task, line) => (
            <div
              key={task.key}
              className="reveal"
              style={{ "--line": line } as CSSProperties}
            >
              {group(task, opened(task.key), (open) => onOpen(task.key, open))}
            </div>
          ))}
        </TraceCollapsibleContent>
      </TraceCollapsible>
    </Trace>
  )
}
