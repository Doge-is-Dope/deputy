import {
  useState,
  type ComponentType,
  type ReactNode,
  type SVGProps,
} from "react"
import { cn } from "cn"

import { Collapsible } from "@/components/ui/collapsible"
import {
  TraceCollapsible,
  TraceCollapsibleContent,
  TraceCollapsibleTrigger,
  TraceIcon,
  TraceLine,
  TraceLineContent,
  TraceTitle,
} from "@/components/ui/trace"
import { screenshotUrl, type ActionReason } from "@/lib/api"
import { describeAction, describeActions, stepCode } from "@/lib/format"
import { useT } from "@/lib/i18n"
import type { Messages } from "@/locales/zh-Hant"
import { stepFailed, stepTool, type Phase, type Step } from "@/lib/thread"
import {
  ChevronRightIcon,
  HandIcon,
  NoSignIcon,
  SpinnerIcon,
  XCircleIcon,
} from "@/components/icons"
import { Markdown } from "@/components/markdown/markdown"
import { ScreenshotPeek } from "@/components/screenshot-viewer"

/** The structured reason an action was held back, or null for one that ran or failed. */
export function skippedReason(
  reason: ActionReason | null | undefined,
  result: string,
  t: Messages
): string | null {
  if (!reason) return null
  return reason in t.run.skipped
    ? t.run.skipped[reason as keyof Messages["run"]["skipped"]]
    : result.split("\n", 1)[0]
}

// How wide the thumbnails are asked for: twice what they show, for sharp screens.
const THUMBNAIL_WIDTH = 160

/**
 * A step's screen, small, at the end of its line: the screen it left, opening the run's screenshots there; or for the
 * step under way, the screen as it is now (a green dot), opening the live view.
 */
export function Thumbnail({
  run,
  name,
  label,
  live = false,
  onOpen,
}: {
  run: string
  name: string
  label: string
  live?: boolean
  onOpen: () => void
}) {
  return (
    <ScreenshotPeek run={run} name={name}>
      <button
        type="button"
        onClick={onOpen}
        aria-label={label}
        className="relative ml-auto flex shrink-0 arrive-line cursor-zoom-in rounded-[5px] outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
      >
        <img
          src={screenshotUrl(run, name, THUMBNAIL_WIDTH)}
          alt=""
          width={44}
          height={28}
          loading="lazy"
          decoding="async"
          className="aspect-[16/10] w-11 rounded-[5px] border bg-muted object-cover transition-opacity hover:opacity-85"
        />
        {live && (
          <span className="absolute -top-0.5 -right-0.5 size-2 rounded-full bg-success ring-2 ring-background" />
        )}
      </button>
    </ScreenshotPeek>
  )
}

/** Expandable action row with progress, result, approval details and screenshot; a failed one opens on its error. */
export function StepLine({
  step,
  run,
  running,
  waiting,
  full,
  ended,
  onOpenShot,
}: {
  step: Step
  run: string
  running: boolean // under way
  waiting: string | null // the step waits for the user: what it says instead of its action
  full: boolean // every step shows its screen
  ended: boolean // the run is over: a step still waiting for the user's approval never ran
  onOpenShot: (name: string) => void
}) {
  const t = useT()
  // Until the user opens or closes it: open if it failed, so its error shows once, under it.
  const [chosen, setChosen] = useState<boolean | null>(null)
  const { tool, args } = stepTool(step)
  const errored = step.action?.status === "error"
  const { icon: Icon, label } = describeAction(tool, args)
  // A failed command's output is its error, shown below already.
  const code = stepCode(tool, args, errored ? "" : step.action?.result)
  // An action held back on purpose (the user had control, the screen moved on, the user declined it) did not fail: it
  // is struck out, with the reason, and not shown in red.
  const skipped = step.action
    ? skippedReason(step.action.reason, step.action.result, t)
    : null
  const failed = stepFailed(step)
  const error = failed ? step.action!.result.split("\n", 1)[0] : null
  const approval = step.approval
  const asked = !approval
    ? null
    : approval.outcome === "approved"
      ? approval.by === "auto"
        ? t.run.confirm.autoApproved(approval.note ?? "")
        : t.run.confirm.approved
      : approval.outcome
        ? null
        : ended
          ? t.run.confirm.unanswered
          : approval.autoReview && !approval.reviewed
            ? t.run.confirm.reviewing
            : null
  const shot = step.action?.screenshot ?? null
  const Mark = skipped
    ? NoSignIcon
    : failed
      ? XCircleIcon
      : waiting
        ? HandIcon
        : Icon
  const details = [asked, skipped, error].filter(Boolean)
  // A step with nothing more to show does not open.
  const opens =
    details.length > 0 || (shot !== null && !full) || Boolean(code?.code)
  const open = chosen ?? failed

  return (
    <Collapsible open={open && opens} className="arrive-line">
      <div className="flex min-w-0 items-center gap-3">
        <button
          type="button"
          onClick={() => setChosen(!open)}
          disabled={!opens}
          aria-expanded={opens ? open : undefined}
          className="group/step flex min-w-0 rounded-md text-left outline-none focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-default"
        >
          <TraceLine
            status={
              running && !waiting ? "running" : failed ? "error" : undefined
            }
            className={cn("min-h-7", waiting && "text-foreground")}
          >
            <TraceIcon>
              {/* The spinner while it runs, then its own icon, crossing over in one place. */}
              <span className="swap">
                <SpinnerIcon
                  className="size-4"
                  data-hidden={!running || waiting ? "" : undefined}
                />
                <Mark
                  className={cn("size-4", waiting && "text-warning")}
                  data-hidden={running && !waiting ? "" : undefined}
                />
              </span>
            </TraceIcon>
            {/* Struck through under ⊘, so it says it didn't run without the words; opened, the reason says why. */}
            <TraceTitle className={cn(skipped && "line-through")}>
              {waiting ?? label}
            </TraceTitle>
            {opens && (
              <ChevronRightIcon
                aria-hidden
                className={cn(
                  "size-3.5 shrink-0 opacity-0 transition-[opacity,rotate] duration-250 ease-(--ease-out) group-hover/step:opacity-60 group-focus-visible/step:opacity-60 motion-reduce:transition-none",
                  open && "rotate-90 opacity-60"
                )}
              />
            )}
          </TraceLine>
        </button>
        {full && shot && (
          <Thumbnail
            run={run}
            name={shot}
            label={t.run.enlarge(label)}
            onOpen={() => onOpenShot(shot)}
          />
        )}
      </div>
      <TraceLineContent className="mt-1 mb-2 ml-6 space-y-2 text-sm leading-5 text-muted-foreground">
        {details.map((text) => (
          <p key={text} className="whitespace-pre-wrap">
            {text}
          </p>
        ))}
        {code?.code && (
          <div className="max-h-80 overflow-auto rounded-lg bg-muted font-mono text-xs leading-5">
            <pre className="px-3 py-2 text-foreground">{code.code}</pre>
            {code.output && (
              <pre className="border-t border-border px-3 py-2">
                {code.output}
              </pre>
            )}
          </div>
        )}
        {shot && !full && (
          <button
            type="button"
            onClick={() => onOpenShot(shot)}
            aria-label={t.run.enlarge(label)}
            className="block cursor-zoom-in rounded-lg outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            <img
              src={screenshotUrl(run, shot, 400)}
              alt=""
              width={200}
              height={125}
              loading="lazy"
              decoding="async"
              className="aspect-[16/10] w-50 rounded-lg border bg-muted object-cover transition-opacity hover:opacity-85"
            />
          </button>
        )}
      </TraceLineContent>
    </Collapsible>
  )
}

/** A line with an icon that only says something: a note of the runtime's, a wait, the work's result. */
export function PlainLine({
  icon,
  children,
  running = false,
  after,
  className,
}: {
  icon: ReactNode
  children: ReactNode
  running?: boolean
  after?: ReactNode // at the end of the line: the screen now, while the agent thinks about its next step
  className?: string
}) {
  return (
    <div className="flex min-w-0 arrive-line items-center gap-3">
      <TraceLine
        status={running ? "running" : undefined}
        className={cn("min-h-7", className)}
      >
        <TraceIcon>{icon}</TraceIcon>
        <TraceTitle className="whitespace-normal">{children}</TraceTitle>
      </TraceLine>
      {after}
    </div>
  )
}

/**
 * Steps in a row, as Codex shows its tool calls: what the agent said as it took the first, in full, then the steps one
 * by one while they are under way; once done, they fold into one line of what they did by kind, which opens them again.
 */
export function PhaseLine({
  phase,
  icon: Icon,
  current,
  lines,
}: {
  phase: Phase
  icon: ComponentType<SVGProps<SVGSVGElement>> // what the agent works with: the computer, or code
  current: boolean // the group under way
  lines: ReactNode[]
}) {
  const [chosen, setChosen] = useState<boolean | null>(null)
  const calls = phase.entries.flatMap((entry) =>
    entry.kind === "step" ? [stepTool(entry.step)] : []
  )
  return (
    <>
      {phase.said && (
        <Markdown
          text={phase.said}
          className="arrive-line pt-2 pb-1 text-sm leading-6 first:pt-0"
        />
      )}
      <TraceCollapsible
        open={chosen ?? current}
        onOpenChange={setChosen}
        className="arrive-line"
      >
        {!current && (
          <TraceCollapsibleTrigger className="arrive-line">
            <TraceLine className="min-h-7">
              <TraceIcon>
                <Icon />
              </TraceIcon>
              <TraceTitle>{describeActions(calls)}</TraceTitle>
            </TraceLine>
          </TraceCollapsibleTrigger>
        )}
        {/* Under way, the steps are lines of the work as any other; folding, they go under their line. */}
        <TraceCollapsibleContent
          className={cn("space-y-0.5", current && "my-0 ml-0 border-l-0 pl-0")}
        >
          {lines}
        </TraceCollapsibleContent>
      </TraceCollapsible>
    </>
  )
}
