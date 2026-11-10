import { useEffect, useState, type ReactNode } from "react"
import { RememberedChip } from "@/components/memory/lines"
import { cn } from "cn"

import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { useCopy } from "@/hooks/use-copy"
import { type Pending } from "@/lib/api"
import { useNow } from "@/hooks/use-now"
import { formatDuration, problemReport, type Problem } from "@/lib/format"
import { useT } from "@/lib/i18n"
import {
  citedMemories,
  openQuestion,
  unlogged,
  type Item,
  type Task,
  type Thread,
} from "@/lib/thread"
import {
  CheckIcon,
  ChevronRightIcon,
  CopyIcon,
  NoSignIcon,
} from "@/components/icons"
import {
  Commentary,
  Reply,
  ThinkingRow,
  UserMessage,
} from "@/components/conversation/messages"
import { TaskGroup } from "@/components/conversation/task-group"
import { AgentsGroup } from "@/components/conversation/agents-group"
import { QuestionCard } from "@/components/conversation/question-card"
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

// A letter, digit or symbol: what a reply being written needs before it draws anything.
const WORD = /[\p{L}\p{N}\p{So}]/u

// No replies seen being written, for a conversation drawn from its log alone.
const NONE: ReadonlySet<number> = new Set()
// Nothing sent to steer it.
const NO_MESSAGES: Pending[] = []

// How wide each line of a reply still loading is drawn: in paragraphs, as a reply's are, each one's last short. A turn
// draws the first three; a conversation opening repeats them down the view, cut off at its end.
const REPLY_LINES = [
  ["w-full", "w-11/12", "w-full", "w-3/4"],
  ["w-full", "w-5/6", "w-2/5"],
  ["w-11/12", "w-1/2"],
  ["w-full", "w-11/12", "w-full", "w-5/6", "w-1/3"],
  ["w-full", "w-11/12", "w-full", "w-1/2"],
  ["w-5/6", "w-full", "w-full", "w-2/3"],
]

/** Delay the loading placeholder to avoid flashing. Match the final turn layout,
 * and mount it separately so the real turn starts its own entrance animation. */
export function TurnSkeleton({ long = false }: { long?: boolean }) {
  const t = useT()
  // A paragraph averages 98px with its gap; the message above them makes up for a run of short ones.
  const paragraphs = long ? Math.ceil(window.innerHeight / 98) : 3
  return (
    // A turn still to come, marked where it starts as the turn is (run-view.tsx places it). Opening a conversation,
    // it takes the height left in the view and no more, so nothing scrolls, down over the content's pb-10 to reach the
    // composer as a reply does.
    <div
      role="status"
      data-turn
      className={cn(
        "animate-in delay-300 duration-200 ease-(--ease-out) fill-mode-both fade-in",
        long && "-mb-10 h-0 grow overflow-hidden"
      )}
    >
      <span className="sr-only">{t.common.loading}</span>
      <div className="space-y-6 motion-safe:animate-pulse">
        <div className="flex flex-col items-end gap-1">
          <Skeleton className="h-11 w-2/5 rounded-3xl" />
          <div className="h-7" />
        </div>
        {/* Paragraphs spaced as Markdown spaces a reply's. */}
        <div className="space-y-2.5">
          {Array.from({ length: paragraphs }, (_, paragraph) => (
            <div key={paragraph}>
              {REPLY_LINES[paragraph % REPLY_LINES.length].map(
                (width, line) => (
                  <div key={line} className="flex h-6 items-center">
                    <Skeleton className={cn("h-3.5", width)} />
                  </div>
                )
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

/** How long a session has worked, over its work once there is some: counting from the start while it works, and once
 * its final reply has come, the line the work before that reply folds under (`fold`), a rule under it throughout. The
 * same line throughout, so nothing moves as it turns from one to the other. It opens its room as it comes, its gap to
 * the row under it inside. Drawn apart from the rows, so its clock draws only itself again. */
function WorkedLine({
  started,
  until,
  fold,
  open,
  onOpen,
}: {
  started: number
  until: number | null // when the session ended; counting until then
  fold: boolean
  open: boolean
  onOpen: (open: boolean) => void
}) {
  const t = useT()
  const now = useNow(until === null)
  return (
    <div className="mb-0 grid grid-rows-[1fr] transition-[grid-template-rows,opacity] duration-300 ease-(--ease-out) motion-reduce:transition-none in-data-settled:starting:grid-rows-[0fr] in-data-settled:starting:opacity-0">
      <div className="min-h-0 overflow-hidden">
        <div className="pb-6">
          <button
            type="button"
            disabled={!fold}
            aria-expanded={fold ? open : undefined}
            onClick={() => onOpen(!open)}
            className={cn(
              "flex w-full items-center gap-1 border-b border-border pb-2 text-left text-sm leading-6 text-muted-foreground tabular-nums transition-colors duration-300 ease-(--ease-out) outline-none",
              fold && "hover:text-foreground focus-visible:text-foreground"
            )}
          >
            {t.run.workedFor(formatDuration((until ?? now) - started))}
            {fold && (
              <ChevronRightIcon
                aria-hidden
                className={cn(
                  "size-3.5 shrink-0 transition-[rotate,opacity] duration-250 ease-(--ease-out) motion-reduce:transition-none in-data-settled:starting:opacity-0",
                  open && "rotate-90"
                )}
              />
            )}
          </button>
        </div>
      </div>
    </div>
  )
}

/** The work before a session's final reply, under its worked line: shut, or open as it was. In a settled conversation
 * it shuts as the reply comes: the rows, drawn again here, are simply there for the first frame (index.css
 * data-refolded), where they were. Its gap under the line is its own, inside the fold, so shut it takes no room. One
 * opened later is shut already. */
function WorkFold({ open, children }: { open: boolean; children: ReactNode }) {
  const [fresh, setFresh] = useState(true)
  useEffect(() => {
    const frame = requestAnimationFrame(() => setFresh(false))
    return () => cancelAnimationFrame(frame)
  }, [])
  return (
    <div
      inert={!open}
      data-open={open || undefined}
      className="-mt-6 grid grid-rows-[0fr] opacity-0 transition-[grid-template-rows,opacity] duration-300 ease-(--ease-out) motion-reduce:transition-none in-data-settled:starting:grid-rows-[1fr] in-data-settled:starting:opacity-100 data-open:grid-rows-[1fr] data-open:opacity-100"
    >
      {/* Room each side for a focus ring: the fold clips what it holds. */}
      <div className="-mx-1 min-h-0 overflow-hidden px-1">
        <div data-refolded={fresh || undefined} className="space-y-6 pt-6">
          {children}
        </div>
      </div>
    </div>
  )
}

/** The task of a work item that is on the computer and under way, if any. */
function computerTask(item: Extract<Item, { kind: "task" | "agents" }>) {
  const tasks = item.kind === "task" ? [item.task] : item.tasks
  return (
    tasks.find(
      (task) => task.outcome === "running" && task.agent === "computer"
    ) ?? null
  )
}

/** Render messages and replies in order, with delegated work grouped at its end.
 * Keep active work last, below commentary and steering messages. */
export function RunThread({
  run,
  thread,
  sent = null,
  dropped = false,
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
  draft = "",
  answering = false,
  steering = NO_MESSAGES,
  streamed = NONE,
  onOpenShot,
  onOpenLive,
  onReply,
  nextAnswer = null,
  answersQuestion = false,
}: {
  run: string
  thread: Thread
  sent?: string | null // what the user sent, drawn with the agent thinking under it until the log comes
  dropped?: boolean // its log stopped coming and waits to connect again
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
  draft?: string // the reply the main agent is writing, not logged yet
  steering?: Pending[] // sent to steer the session, drawn at once, until its log has them
  answering?: boolean // that reply is its final one, as its model said from its start
  streamed?: ReadonlySet<number> // its logged replies this page saw being written, by their model event's place
  onOpenShot: (name: string) => void
  onOpenLive: () => void
  onReply: (text: string) => Promise<boolean> // sends the user's choice as their next message
  nextAnswer?: string | null // the next run began with this, the answer to the question this one left open
  answersQuestion?: boolean // what began this run answers the question the last one left open, which draws it
}) {
  const t = useT()
  // The work groups the user opened, by key: kept here, since a group under way is drawn apart from those done, and
  // drawn again among them once it is done.
  const [opened, setOpened] = useState<ReadonlySet<string>>(new Set())
  // The work before the final reply, opened again by the user.
  const [workOpen, setWorkOpen] = useState(false)
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
  const goal = thread.goal ?? sent
  const shown = goal !== null
  const [settled, setSettled] = useState(false)
  useEffect(() => {
    if (!shown || !visible || settled) return
    const timer = window.setTimeout(() => setSettled(true), 400)
    return () => window.clearTimeout(timer)
  }, [shown, visible, settled])
  // The words as they come, once there is one: markup alone (a heading's ##, a list's -) draws nothing, and the thinking
  // row would fold shut over a blank.
  const words = WORD.test(draft) ? draft : ""
  // The reply its model said from its start is the final one, by its place among those this page saw written: what
  // led to it folds away as it starts, and stays folded once it is logged, until the session ends.
  const [answered, setAnswered] = useState<number | null>(null)
  if (answering && words && answered !== streamed.size)
    setAnswered(streamed.size)
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
  const sending = unlogged(thread, steering)
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
  const writing = !!words
  const rows = items.map((item) => {
    switch (item.kind) {
      case "message":
        return <UserMessage key={item.id} text={item.text} time={item.time} />
      case "reply":
        return (
          <Reply
            key={
              streamed.has(item.at)
                ? `written-${written.indexOf(item.at)}`
                : item.key
            }
            text={item.text}
            time={item.time}
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
      case "question":
        return (
          <QuestionCard
            key={item.key}
            question={item.question}
            options={item.options}
            multiple={item.multiple}
            // A later run began with their answer; a message sent counts before the log has it.
            answered={item.answered || !latest || sending.length > 0}
            answer={
              item.answer?.text ??
              (item.answered ? null : (nextAnswer ?? sending[0]?.text ?? null))
            }
            onReply={onReply}
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
      default:
        return item satisfies never // a new kind of row does not compile until it is drawn
    }
  })
  // The final reply's place: the session's last, once it ended replied; while no task works, the one its model said
  // was final from its start, as it is written (after every row) and once it is logged, while nothing came after it.
  const answer =
    answered === null
      ? -1
      : items.findIndex(
          (item) =>
            item.kind === "reply" &&
            streamed.has(item.at) &&
            written.indexOf(item.at) === answered
        )
  // A question still waiting stays in view: nothing folds it away.
  const final =
    latest && openQuestion(thread)
      ? -1
      : end?.stop_reason === "replied" && lastReply
        ? items.indexOf(lastReply)
        : working.length > 0
          ? -1
          : answering && words
            ? items.length
            : answer >= 0 && answer === items.length - 1
              ? answer
              : -1
  // The session's work: what it did and said before its final reply, or so far (a turn of work, words on the way, a
  // message meanwhile, a reply with more after it); not a reply alone, or what it recalled. Once the final reply has
  // come, or starts, the work folds under the worked line.
  const work = items.filter(
    (item, index) =>
      item.kind !== "memory" &&
      item.kind !== "question" &&
      (final < 0
        ? item !== lastReply || index < items.length - 1
        : index < final)
  )
  const fold = final > 0 && work.length > 0
  // Words said with a question are no work to account for.
  const onlyAsked =
    !fold &&
    items.some((item) => item.kind === "question") &&
    work.every((item) => item.kind === "commentary")
  // In one list with the rows, so a reply keeps its key from draft to logged.
  const all = [
    thread.started !== null && work.length > 0 && !onlyAsked ? (
      <WorkedLine
        key="worked"
        started={thread.started}
        until={end?.time ?? (active ? null : (thread.last ?? thread.started))}
        fold={fold}
        open={workOpen}
        onOpen={setWorkOpen}
      />
    ) : null,
    ...(fold
      ? [
          <WorkFold key="work" open={workOpen}>
            {rows.slice(0, final)}
          </WorkFold>,
          ...rows.slice(final),
        ]
      : rows),
    // What the main agent is writing, where it will stay once written. Without the line break a model ends its words with, which its logged reply drops
    // (lib/thread.ts) and which would be a blank line until then.
    words ? (
      <Reply
        key={`written-${written.length}`}
        text={words.trimEnd()}
        writing
        actions={false}
      />
    ) : null,
    // What the user sent to steer it, where it goes: after what the main agent is writing, which it reads next. Under
    // the same key as once its log has it, there in the conversation.
    ...sending
      .filter((_, index) => !(index === 0 && openQuestion(thread)))
      .map((message) => <UserMessage key={message.id} text={message.text} />),
    // The main agent working out what to say, until the first of its words comes. Last of all, under the work under way,
    // and
    // folding open and shut in its place rather than coming and going, so nothing above it moves.
    // Kept for what was just sent too, whose run the status may not list as working yet: gone and back, it would blink.
    active || sent !== null ? (
      <ThinkingRow
        key="thinking"
        replaced={!!words}
        shown={thread.goal === null ? !dropped : thread.thinking && !words}
      />
    ) : null,
  ]

  return (
    // Marked where the turn starts, with what the user sent: the conversation places it at the top of its view.
    <div
      data-turn
      data-run={run}
      // A run that answers the last one's question reads as more of it: the gap within a turn, not between turns.
      className={cn("space-y-6", answersQuestion && "-mt-4")}
      data-settled={settled || undefined}
    >
      {continued ? (
        <p className="flex dashed-rule items-center gap-3 text-xs text-muted-foreground">
          {t.run.continued}
        </p>
      ) : answersQuestion ? null : (
        <UserMessage text={goal!} time={thread.started ?? undefined} />
      )}

      {all}

      {failure && <Failure problem={failure} at={thread.last} />}
    </div>
  )
}
