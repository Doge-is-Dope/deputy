import { Fragment, useEffect, useRef, useState } from "react"
import { cn } from "cn"

import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { useNow } from "@/hooks/use-now"
import { type AgentUsage, type Cost } from "@/lib/api"
import {
  formatCost,
  formatDateTime,
  formatDollars,
  formatDuration,
  formatNumber,
  modelName,
  timeAgo,
} from "@/lib/format"
import { useT } from "@/lib/i18n"
import type { Remembered } from "@/lib/memory"
import { reducedMotion } from "@/lib/motion"
import { cut, FADE_MS, Pace, STEP_MS } from "@/lib/reveal"
import {
  EllipsisIcon,
  InfoIcon,
  MemoryIcon,
  ProviderIcon,
} from "@/components/icons"
import { CopyButton } from "@/components/copy-button"
import { CitedMemoriesDialog } from "@/components/memory/lines"
import { Markdown } from "@/components/markdown/markdown"
import { MessageText } from "@/components/mentions"

// A message's actions show while the pointer is over it, the keyboard is in it or its menu is open, as the sidebar's
// delete button does. Where nothing can hover (a touch screen) they stay. Their tooltips open below them, off the
// message, unless there is no room there.
const ON_HOVER =
  "transition-opacity duration-150 motion-reduce:transition-none [@media(hover:hover)]:opacity-0 group-hover/message:opacity-100 group-has-[:focus-visible]/message:opacity-100 group-has-[[data-popup-open]]/message:opacity-100"

// 「已讀」 fades out over this long once the answer comes, before the copy button is back in its place.
const READ_OUT_MS = 300

/** Show a read receipt for steering messages until answered, then restore the copy button. */
export function UserMessage({
  text,
  time,
  read = false,
  answered = false,
}: {
  text: string
  time?: number // when it was sent; not yet known for one still waiting to be read
  read?: boolean
  answered?: boolean
}) {
  const t = useT()
  const saying = read && !answered
  // Kept a moment once it stops, fading out: saying as of the last render, and whether it has just stopped.
  const [said, setSaid] = useState(saying)
  const [fading, setFading] = useState(false)
  if (saying !== said) {
    setSaid(saying)
    setFading(!saying)
  }
  useEffect(() => {
    if (!fading) return
    const timer = window.setTimeout(() => setFading(false), READ_OUT_MS)
    return () => window.clearTimeout(timer)
  }, [fading])
  return (
    <div className="group/message flex arrive flex-col items-end gap-1">
      <div className="max-w-[85%] rounded-3xl bg-muted px-4 py-2.5 text-sm leading-6 whitespace-pre-wrap">
        <MessageText text={text} />
      </div>
      {/* Where nothing can hover (a phone), the row under it holds no copy button, as Messages has none: pressing the
        text selects it. It is closed there but for 「已讀」, opening round it and closing after, so nothing below jumps. */}
      <div
        className={cn(
          "grid grid-rows-[1fr] transition-[grid-template-rows] duration-300 ease-(--ease-out) motion-reduce:transition-none",
          !saying && "[@media(hover:none)]:grid-rows-[0fr]"
        )}
      >
        <div className="min-h-0 overflow-hidden">
          {saying || fading ? (
            <p
              role="status"
              className={cn(
                "flex h-6 animate-in items-center px-1 text-xs text-muted-foreground transition-opacity duration-300 ease-(--ease-out) fade-in motion-reduce:transition-none",
                !saying && "opacity-0"
              )}
            >
              {t.run.read}
            </p>
          ) : (
            <div
              className={cn(
                "flex items-center gap-x-1.5 text-xs text-muted-foreground [@media(hover:none)]:invisible",
                ON_HOVER
              )}
            >
              <CopyButton text={text} />
              {time !== undefined && <TimeAgo time={time} />}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

/** What a run's last reply's details menu tells: what the whole run used, how long it took, and the rules it cited. */
type About = {
  cost: Cost | null
  agents: AgentUsage[]
  took?: number // seconds, from the user's message to the end of the run
  cited: Remembered[] // the rules its tasks were handed over with (citedMemories)
}

/** Reply actions appear on hover; keep the latest reply's buttons visible. */
function ReplyActions({
  text,
  time,
  about,
  pinned = false,
}: {
  text?: string
  time?: number
  about?: About
  pinned?: boolean
}) {
  return (
    <div
      className={cn(
        "flex min-h-6 flex-wrap items-center gap-x-1.5 gap-y-2 text-xs text-muted-foreground",
        !pinned && ON_HOVER
      )}
    >
      {text && (
        // Fading in once the reply's words are all there, rather than popping up under them.
        <span className="flex items-center gap-x-1.5 transition-opacity duration-250 motion-reduce:transition-none in-data-settled:starting:opacity-0">
          <CopyButton text={text} />
          {about && <ReplyMore about={about} />}
        </span>
      )}
      {time !== undefined && (
        <span className={cn("flex", pinned && ON_HOVER)}>
          <TimeAgo time={time} />
        </span>
      )}
    </div>
  )
}

/** Run duration and cost; each agent's tokens and cost, and the rules the run cited, each in a dialog of its own. */
function ReplyMore({ about }: { about: About }) {
  const t = useT()
  const words = t.run.about
  // The dialog the menu opened: kept outside it, as the menu closes once one opens.
  const [opened, setOpened] = useState<"details" | "cited" | null>(null)
  const close = (open: boolean) => !open && setOpened(null)
  const lines: [string, string][] = []
  if (about.took !== undefined)
    lines.push([words.took, formatDuration(about.took)])
  lines.push([words.cost, about.cost ? formatCost(about.cost) : words.unknown])
  return (
    <>
      <DropdownMenu>
        <Tooltip>
          <TooltipTrigger
            render={
              <DropdownMenuTrigger
                render={
                  <Button
                    variant="ghost"
                    size="icon-xs"
                    aria-label={t.run.usage}
                    className="text-muted-foreground data-popup-open:bg-muted"
                  />
                }
              />
            }
          >
            <EllipsisIcon className="size-4" />
          </TooltipTrigger>
          <TooltipContent side="bottom">{t.run.usage}</TooltipContent>
        </Tooltip>
        <DropdownMenuContent align="start" className="min-w-44 text-xs">
          <div className="px-2 py-0.5">
            {lines.map(([label, value]) => (
              <div
                key={label}
                className="flex items-center justify-between gap-4 py-0.5"
              >
                <span className="text-muted-foreground">{label}</span>
                <span className="tabular-nums">{value}</span>
              </div>
            ))}
          </div>
          {(about.agents.length > 0 || about.cited.length > 0) && (
            <DropdownMenuSeparator />
          )}
          {about.agents.length > 0 && (
            <DropdownMenuItem
              onClick={() => setOpened("details")}
              className="py-1 pr-2 text-xs text-muted-foreground"
            >
              <InfoIcon className="size-3.5!" />
              {words.details}
            </DropdownMenuItem>
          )}
          {about.cited.length > 0 && (
            <DropdownMenuItem
              onClick={() => setOpened("cited")}
              className="py-1 pr-2 text-xs text-muted-foreground"
            >
              <MemoryIcon className="size-3.5!" />
              {t.run.memory.citations(about.cited.length)}
            </DropdownMenuItem>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
      <UsageDialog
        agents={about.agents}
        open={opened === "details"}
        onOpenChange={close}
      />
      <CitedMemoriesDialog
        memories={about.cited}
        open={opened === "cited"}
        onOpenChange={close}
      />
    </>
  )
}

/** Each agent by the model it used (the main agent's first, then those it handed work to), by kind of token as each is
 * priced: the input read from and written to the cache apart from the rest, kinds not used left out. */
function UsageDialog({
  agents,
  open,
  onOpenChange,
}: {
  agents: AgentUsage[]
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const t = useT()
  const words = t.run.about
  const groups = agents.map((each) => {
    const { usage, cost } = each
    const kinds: [string, number, number | undefined][] = [
      [
        words.input,
        usage.input - usage.cached - usage.cache_write,
        cost?.input,
      ],
      [words.cached, usage.cached, cost?.cached],
      [words.cacheWrite, usage.cache_write, cost?.cache_write],
      [words.output, usage.output, cost?.output],
    ]
    return {
      model: each.model,
      cost: cost ? formatCost(cost) : words.unknown,
      kinds: kinds.filter(([, tokens]) => tokens > 0),
    }
  })
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[min(36rem,calc(100dvh-2rem))] flex-col pt-3">
        <DialogTitle className="flex h-8 items-center pr-8">
          {words.details}
        </DialogTitle>
        <div className="-mx-4 min-h-0 overflow-y-auto px-4">
          <div className="grid grid-cols-[1fr_auto_auto] gap-x-4">
            {groups.map((group, index) => (
              <Fragment key={index}>
                <span
                  className={cn(
                    "col-span-2 flex items-center gap-2 py-1.5 font-medium",
                    index > 0 && "mt-3"
                  )}
                >
                  <ProviderIcon model={group.model} className="size-4" />
                  {modelName(group.model)}
                </span>
                <span
                  className={cn(
                    "py-1.5 text-right font-medium tabular-nums",
                    index > 0 && "mt-3"
                  )}
                >
                  {group.cost}
                </span>
                {group.kinds.map(([label, tokens, dollars]) => (
                  <Fragment key={label}>
                    <span className="py-1.5 pl-6 text-muted-foreground">
                      {label}
                    </span>
                    <span className="py-1.5 text-right tabular-nums">
                      {formatNumber(tokens)}
                    </span>
                    <span className="py-1.5 text-right text-muted-foreground tabular-nums">
                      {dollars === undefined ? "" : formatDollars(dollars)}
                    </span>
                  </Fragment>
                ))}
              </Fragment>
            ))}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}

/** Pace incoming characters with lib/reveal.ts. Keep streaming markup until the final
 * character finishes fading; show static, replaced or reduced-motion text in full. */
function useRevealed(text: string, writing: boolean): [string, boolean] {
  const [moving] = useState(() => !reducedMotion())
  const [shown, setShown] = useState(writing && moving ? "" : text)
  // The text whose last character has faded in.
  const [faded, setFaded] = useState(writing ? null : text)
  // The pace, and the text it paced so far.
  const pacing = useRef<{ pace: Pace; text: string } | null>(null)
  if (!text.startsWith(shown) || (!moving && shown !== text)) {
    setShown(text)
    setFaded(text)
  }
  useEffect(() => {
    if (!moving) return
    const was = pacing.current
    const pacer =
      was && text.startsWith(was.text.slice(0, was.pace.shown))
        ? was
        : { pace: new Pace(text.length), text }
    pacer.text = text
    pacing.current = pacer
    // A step now, as more has come, and one every STEP_MS while there is more to show; what it lets in is shown at
    // the next frame.
    let frame = 0
    let timer = 0
    const step = () => {
      const count = pacer.pace.step(text.length, performance.now(), !writing)
      frame ||= requestAnimationFrame(() => {
        frame = 0
        setShown(text.slice(0, cut(text, pacer.pace.shown)))
      })
      if (count < text.length) timer = window.setTimeout(step, STEP_MS)
    }
    step()
    return () => {
      clearTimeout(timer)
      cancelAnimationFrame(frame)
    }
  }, [text, moving, writing])
  const done = !writing && shown === text
  useEffect(() => {
    if (!done || faded === text) return
    const timer = setTimeout(() => setFaded(text), FADE_MS)
    return () => clearTimeout(timer)
  }, [done, faded, text])
  return [shown, !done || faded !== text]
}

/** Render replies in place. Reuse streamed replies without a second entrance animation. Words said on the way, seen
 * being written, are drawn here too, under the same key as while they were written, so the reveal goes on (as a reply's
 * does once logged) and the row keeps its height: no actions under them, as none under words still being written. */
export function Reply({
  text,
  time,
  about,
  pinned = false,
  writing = false,
  rise = true,
  actions = true,
}: {
  text: string
  time?: number
  about?: About
  pinned?: boolean // the conversation's last reply, whose buttons stay
  writing?: boolean
  rise?: boolean
  actions?: boolean // a reply's copy button, time and details; not under commentary
}) {
  const [shown, coming] = useRevealed(text, writing)
  const streaming = writing || shown !== text
  return (
    <div
      aria-busy={streaming || undefined}
      className={cn(
        "group/message space-y-1",
        writing ? "make-room" : rise && "arrive"
      )}
    >
      <Markdown text={shown} streaming={coming} className="text-sm leading-6" />
      {actions && !writing && (
        <ReplyActions
          text={streaming ? undefined : text}
          time={time}
          about={about}
          pinned={pinned}
        />
      )}
    </div>
  )
}

/** The main agent thinking: three lights and a word, in a row that folds open and shut (as a plan's steps do) and is
 * there the whole run, folded or not. Its gap from the row above is its own, inside the fold, so folded it takes no
 * room at all. It opens and shuts as what arrives does, easing out. Shutting, it gives up its gap first, the word kept
 * at its foot: words that take its place open their room on the same curve, so the word stays where it is, fading out
 * as they fade in, and what is under it holds still. */
export function ThinkingRow({ shown }: { shown: boolean }) {
  const t = useT()
  // Folding: overlay scrollbars flash at every resize (index.css), so they hide while it moves.
  const [moving, setMoving] = useState(false)
  const [was, setWas] = useState(shown)
  if (shown !== was) {
    setWas(shown)
    setMoving(true)
  }
  return (
    <div
      inert={!shown}
      data-gone={shown ? undefined : ""}
      data-moving={moving || undefined}
      onTransitionEnd={(event) => {
        if (event.target === event.currentTarget) setMoving(false)
      }}
      className="group/thinking -mt-6 grid grid-rows-[1fr] transition-[grid-template-rows,opacity,filter] duration-300 ease-(--ease-out) data-gone:grid-rows-[0fr] data-gone:opacity-0 data-gone:blur-[2px] motion-reduce:transition-none in-data-settled:starting:grid-rows-[0fr] in-data-settled:starting:opacity-0 in-data-settled:starting:blur-[2px]"
    >
      <div className="min-h-0 overflow-hidden group-data-gone/thinking:flex group-data-gone/thinking:flex-col group-data-gone/thinking:justify-end">
        <div className="flex items-center gap-2 pt-6 text-sm leading-6 text-muted-foreground">
          <span aria-hidden className="thinking-orbs">
            <span />
            <span />
            <span />
          </span>
          <span className="shimmer">{t.run.thinking}</span>
        </div>
      </div>
    </div>
  )
}

/** What the main agent said on the way, where it said it: its words, without a reply's actions. */
export function Commentary({
  text,
  rise = true,
}: {
  text: string
  rise?: boolean
}) {
  return (
    <Markdown
      text={text}
      className={cn("text-sm leading-6", rise && "arrive")}
    />
  )
}

/** When a message came, as time ago, kept current; the date and the time in full in its tooltip. */
function TimeAgo({ time }: { time: number }) {
  const now = useNow(true, 30_000)
  return (
    <Tooltip>
      <TooltipTrigger
        render={<time dateTime={new Date(time * 1000).toISOString()} />}
      >
        {timeAgo(time, now)}
      </TooltipTrigger>
      <TooltipContent side="bottom">{formatDateTime(time)}</TooltipContent>
    </Tooltip>
  )
}
