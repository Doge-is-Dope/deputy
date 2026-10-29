import { useEffect, useState } from "react"
import { RememberedChip } from "@/components/memory/lines"
import { cn } from "cn"

import { Button } from "@/components/ui/button"
import { useCopy } from "@/hooks/use-copy"
import { type Pending } from "@/lib/api"
import { problemReport, type Problem } from "@/lib/format"
import { useT } from "@/lib/i18n"
import { citedMemories, type Item, type Task, type Thread } from "@/lib/thread"
import { CheckIcon, CopyIcon, NoSignIcon } from "@/components/icons"
import {
  Commentary,
  Reply,
  ThinkingRow,
  UserMessage,
} from "@/components/conversation/messages"
import { TaskGroup } from "@/components/conversation/task-group"
import { AgentsGroup } from "@/components/conversation/agents-group"
import { PlainLine, skippedReason } from "@/components/conversation/steps"

/** Show a readable failure; keep the code and exception in the copyable report. */
function Failure({ problem, at }: { problem: Problem; at: number | null }) {
  const t = useT()
  const { copied, manual, copy } = useCopy()
  const errors: Record<string, string> = t.run.errors
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-x-1 text-sm leading-6">
        <p className="text-destructive">
          {errors[problem.code] ?? errors["E-UNKNOWN"]}
        </p>
        <Button
          variant="ghost"
          size="xs"
          className="font-normal text-muted-foreground"
          onClick={() =>
            copy(
              problemReport(
                problem,
                at === null ? new Date() : new Date(at * 1000)
              )
            )
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
      </div>
      {manual && (
        <pre className="max-w-full overflow-x-auto rounded-md bg-muted px-3 py-2 font-mono text-xs leading-4 select-all">
          {manual}
        </pre>
      )}
    </div>
  )
}

// How long the main agent's words may stop coming before it shows as thinking under them.
const DRAFT_PAUSE_MS = 1200

// No replies seen being written, for a conversation drawn from its log alone.
const NONE: ReadonlySet<number> = new Set()

// How wide each line of a reply still loading is drawn: in paragraphs, as a reply's are, each one's last short.
const REPLY_LINES = [
  ["w-full", "w-11/12", "w-full", "w-3/4"],
  ["w-full", "w-5/6", "w-2/5"],
  ["w-11/12", "w-1/2"],
]

/** Delay the loading placeholder to avoid flashing. Match the final turn layout,
 * and mount it separately so the real turn starts its own entrance animation. */
export function TurnSkeleton() {
  const t = useT()
  return (
    // A turn still to come, marked where it starts as the turn is (run-view.tsx places it).
    <div
      role="status"
      data-turn
      className="@container animate-in space-y-6 delay-300 duration-200 ease-(--ease-out) fill-mode-both fade-in"
    >
      <span className="sr-only">{t.common.loading}</span>
      <div className="flex flex-col items-end gap-1">
        <div className="skeleton-shape h-11 w-2/5 rounded-3xl [--at:60cqw]" />
        <div className="h-7" />
      </div>
      {/* Paragraphs spaced as Markdown spaces a reply's. */}
      <div className="space-y-2.5">
        {REPLY_LINES.map((lines, paragraph) => (
          <div key={paragraph}>
            {lines.map((width, line) => (
              <div key={line} className="flex h-6 items-center">
                <div className={cn("skeleton-shape h-3.5 rounded-md", width)} />
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  )
}

/** The task of a work item that is on the computer and under way, if any. */
function computerTask(item: Extract<Item, { kind: "task" | "agents" }>) {
  const tasks = item.kind === "task" ? [item.task] : item.tasks
  return (
    tasks.find(
      (task) => task.outcome === "running" && task.tool === "computer_use"
    ) ?? null
  )
}

/**
 * Whether the agent has answered the message at `index` of the items shown, read at `time`: it said something after
 * it, or took up work after it (a task that started after; one running since before goes on under it).
 */
function answeredAfter(items: Item[], index: number, time: number): boolean {
  return items
    .slice(index + 1)
    .some(
      (item) =>
        item.kind === "reply" ||
        item.kind === "commentary" ||
        item.kind === "held" ||
        (item.kind === "task" && item.task.started > time) ||
        (item.kind === "agents" &&
          item.tasks.some((task) => task.started > time))
    )
}

/** Render messages and replies in order, with delegated work grouped at its end.
 * Keep active work last, below commentary and steering messages. */
export function RunThread({
  run,
  thread,
  continued = false,
  latest = false,
  visible = true,
  loaded,
  active,
  error,
  userSince = null,
  disconnected = false,
  approving,
  takingOver = false,
  pending = [],
  draft = "",
  streamed = NONE,
  onOpenShot,
  onOpenLive,
}: {
  run: string
  thread: Thread
  continued?: boolean // carries on the run before with the same goal, so the goal is not shown again
  latest?: boolean // the conversation's last run, whose last reply keeps its buttons showing
  visible?: boolean // the conversation is shown: it stays hidden until all its runs have come
  loaded: boolean
  active: boolean
  error: string | null
  userSince?: number | null // the user has had the desktop since then, by the runtime's status
  disconnected?: boolean // the desktop can't be reached
  approving: string | null // the step the run waits for the user to approve, which the composer asks: what it will do
  takingOver?: boolean // the run waits for the user to take over the desktop, which the composer asks
  pending?: Pending[] // sent while the run works, and not read by its agents yet
  draft?: string // the reply the main agent is writing, not logged yet
  streamed?: ReadonlySet<number> // its logged replies this page saw being written, by their model event's place
  onOpenShot: (name: string) => void
  onOpenLive: () => void
}) {
  const t = useT()
  // Messages this page saw waiting for the agent: each says 「已讀」 once it is read. A conversation opened later, or
  // reloaded, has none waiting, and marks nothing.
  const [waited, setWaited] = useState<ReadonlySet<string>>(new Set())
  if (pending.some((message) => !waited.has(message.id)))
    setWaited(new Set([...waited, ...pending.map((message) => message.id)]))
  // The work groups the user opened, by key: kept here, since a group under way is drawn apart from those done, and
  // drawn again among them once it is done.
  const [opened, setOpened] = useState<ReadonlySet<string>>(new Set())
  const open = (key: string, open: boolean) =>
    setOpened((was) => {
      const now = new Set(was)
      if (open) now.add(key)
      else now.delete(key)
      return now
    })
  // The work under way, each where it was handed over, among what is said meanwhile.
  const working = active
    ? thread.items.filter(
        (item): item is Extract<Item, { kind: "task" | "agents" }> =>
          (item.kind === "task" && item.task.outcome === "running") ||
          (item.kind === "agents" &&
            item.tasks.some((task) => task.outcome === "running"))
      )
    : []
  // The task on the computer now, which the user's turns at the desktop and the steps they approve are about.
  const onComputer = working.map(computerTask).find((task) => task) ?? null
  // Opened while it worked, a work group folds once it is done.
  const [under, setUnder] = useState(working.map((item) => item.key))
  if (
    working.length !== under.length ||
    working.some((item, i) => item.key !== under[i])
  ) {
    setUnder(working.map((item) => item.key))
    for (const key of under)
      if (!working.some((item) => item.key === key)) open(key, false)
  }
  // Settled a moment after the conversation is first drawn: from then on, what arrives rises into place (index.css).
  // Drawn only once shown: what came while the conversation was hidden was there when it opened.
  const shown = thread.goal !== null
  const [settled, setSettled] = useState(false)
  useEffect(() => {
    if (!shown || !visible || settled) return
    const timer = window.setTimeout(() => setSettled(true), 400)
    return () => window.clearTimeout(timer)
  }, [shown, visible, settled])
  // The main agent's words, once they stop coming while its call goes on: it is writing a call now (work to hand over,
  // its plan), which takes a while, so it shows as thinking again under them.
  const [stalled, setStalled] = useState<string | null>(null)
  useEffect(() => {
    if (!draft) return
    const timer = window.setTimeout(() => setStalled(draft), DRAFT_PAUSE_MS)
    return () => window.clearTimeout(timer)
  }, [draft])
  const writingCall = !!draft && stalled === draft
  const end = thread.end
  const interrupted = loaded && !active && !end
  // A run with no reply to show because the main agent itself failed says why, in words (a desktop that cannot be used
  // is the main agent's to explain, in its reply). Why: logged with its end, as a code; for a run the runtime died under,
  // only while the runtime remembers it.
  const failure: Problem | null =
    end?.stop_reason === "error" || (interrupted && error)
      ? {
          code: end?.error_code ?? "E-UNKNOWN",
          detail: end?.error ?? error ?? "",
          run,
        }
      : null

  // Nothing to show for a run with nothing more to come; the shape of what will come, for one still loading.
  if (!shown) return loaded ? null : <TurnSkeleton />

  const items = thread.items
  const lastReply = items.findLast((item) => item.kind === "reply")
  const taskGroup = (
    task: Task,
    full: boolean,
    onFull: (full: boolean) => void,
    agent = false
  ) => (
    <TaskGroup
      key={task.key}
      task={task}
      run={run}
      active={active}
      last={thread.last}
      approving={task === onComputer ? approving : null}
      takingOver={task === onComputer && takingOver}
      userSince={task === onComputer ? userSince : null}
      disconnected={task === onComputer && disconnected}
      full={full}
      onFull={onFull}
      onOpenShot={onOpenShot}
      onOpenLive={onOpenLive}
      agent={agent}
    />
  )
  const group = (item: Extract<Item, { kind: "task" | "agents" }>) =>
    item.kind === "task" ? (
      // One agent alone is a line of its own, as each of several is: which agent, and what it was given.
      taskGroup(
        item.task,
        opened.has(item.key),
        (full) => open(item.key, full),
        true
      )
    ) : (
      <AgentsGroup
        key={item.key}
        tasks={item.tasks}
        run={run}
        active={active}
        last={thread.last}
        full={opened.has(item.key)}
        onFull={(full) => open(item.key, full)}
        opened={(key) => opened.has(`agent-${key}`)}
        onOpen={(key, full) => open(`agent-${key}`, full)}
        onOpenLive={onOpenLive}
        task={(task, full, onFull) => taskGroup(task, full, onFull, true)}
      />
    )

  // Keep drafts and their logged replies under the same key so reveal state survives.
  // Give each subsequent reply its own key and animation.
  const written = [...streamed].sort((a, b) => a - b)
  // Whether a reply is being written, not what: the rows above it are drawn again only when that changes, not on each
  // frame of the reply.
  const writing = !!draft
  const rows = items.map((item, index) => {
    switch (item.kind) {
      case "message":
        return (
          <UserMessage
            key={item.id}
            text={item.text}
            time={item.time}
            read={waited.has(item.id)}
            answered={writing || answeredAfter(items, index, item.time)}
          />
        )
      case "reply":
        return (
          <Reply
            key={
              streamed.has(item.at)
                ? `written-${written.indexOf(item.at)}`
                : item.key
            }
            text={item.text}
            time={end && item === lastReply ? end.time : undefined}
            // What the run used, every agent, logged as it ends.
            about={
              end && item === lastReply
                ? {
                    cost: end.cost,
                    agents: end.agents,
                    took:
                      thread.started === null
                        ? undefined
                        : end.time - thread.started,
                    cited: citedMemories(thread),
                  }
                : undefined
            }
            pinned={latest && !writing && item === lastReply}
            rise={!streamed.has(item.at)}
            // Words before the run's last reply were said on the way: no actions, as under commentary.
            actions={item === lastReply}
          />
        )
      case "commentary":
        return streamed.has(item.at) ? (
          <Reply
            key={`written-${written.indexOf(item.at)}`}
            text={item.text}
            rise={false}
            actions={false}
          />
        ) : (
          <Commentary key={item.key} text={item.text} />
        )
      case "task":
      case "agents":
        return group(item)
      case "held":
        return (
          <PlainLine
            key={item.key}
            icon={<NoSignIcon />}
            className="text-muted-foreground"
          >
            {skippedReason(item.reason, item.result, t)}
          </PlainLine>
        )
      case "memory":
        return (
          <RememberedChip
            key={item.key}
            memories={item.memories}
            updated={item.updated}
          />
        )
      case "note":
        return (
          <p
            key={item.key}
            className="arrive text-sm leading-6 whitespace-pre-wrap text-muted-foreground"
          >
            {item.text}
          </p>
        )
    }
  })
  // In one list with the rows, so a reply keeps its key from draft to logged.
  const all = [
    ...rows,
    // What the main agent is writing, where it will stay once written. Without the line break a model ends its words with, which its logged reply drops
    // (lib/thread.ts) and which would be a blank line until then.
    draft ? (
      <Reply
        key={`written-${written.length}`}
        text={draft.trimEnd()}
        writing
        actions={false}
      />
    ) : null,
    // The main agent working out what to say, until the first of its words comes; and again once they have stopped
    // while it still writes. Last of all, under the work under way as ChatGPT's indicator is, and
    // folding open and shut in its place rather than coming and going, so nothing above it moves.
    active ? (
      <ThinkingRow
        key="thinking"
        shown={thread.thinking && (!draft || writingCall)}
      />
    ) : null,
  ]

  return (
    // Marked where the turn starts, with what the user sent: the conversation places it at the top of its view.
    <div data-turn className="space-y-6" data-settled={settled || undefined}>
      {continued ? (
        <p className="flex dashed-rule items-center gap-3 text-xs text-muted-foreground">
          {t.run.continued}
        </p>
      ) : (
        <UserMessage text={thread.goal!} time={thread.started ?? undefined} />
      )}

      {all}

      {failure && <Failure problem={failure} at={thread.last} />}
    </div>
  )
}
