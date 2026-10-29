import {
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
  type Ref,
} from "react"
import { cn } from "cn"

import { Button } from "@/components/ui/button"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { ArrowUpIcon, HandIcon, StopIcon } from "@/components/icons"
import { preloadMarkdown } from "@/components/markdown/markdown"
import { ScreenshotViewer } from "@/components/screenshot-viewer"
import { setDraft, useDraft } from "@/hooks/use-drafts"
import { NUDGE_MS } from "@/hooks/use-flash"
import { type Approval, type Decision, type Pending } from "@/lib/api"
import { useT } from "@/lib/i18n"
import { isComposing } from "@/lib/keys"
import { MentionList } from "@/components/composer/mention-list"
import { MentionLogos, TEXT } from "@/components/composer/mention-logos"
import { useMentionText } from "@/components/composer/mention-text"
import { QuestionRow } from "@/components/composer/question-row"
import { Queue } from "@/components/composer/queue"
import {
  AnswerPair,
  type Ask,
  useAnswerKeys,
} from "@/components/composer/answers"

/** A task about to take the desktop from the user, waiting for them to say yes or no. */
export type Handover = {
  answer: (yes: boolean) => void
}

/**
 * The agent asking the user to take the desktop over, and why: answered by taking it (which opens the desktop) or by
 * skipping it (which hands it straight back, for the agent to carry on without).
 */
export type Takeover = {
  text: string
  onTakeOver: () => void
  onSkip: () => void
}

// What comes into the composer's corner fades in, and what it takes the place of goes at once: the answers, as the
// question's row opens, and the stop and send buttons, which also grow a little into place. Those two are 32px, as
// ChatGPT's, with 4px round them, so their middle stays where a 40px one's was, in line with the text and the corner.
const ANSWERS =
  "transition-opacity duration-300 ease-(--ease-drawer) motion-reduce:transition-none starting:opacity-0"

const CORNER_BUTTON =
  "m-1 rounded-full duration-200 ease-(--ease-out) motion-reduce:transition-none starting:scale-90 starting:opacity-0"

/** Compose goals and steering messages, or answer approval and takeover requests.
 * Typed text during approval becomes the rejection reason. Takeover replaces the input.
 * For an active web run, send nonempty text and stop when empty; CLI runs accept no steering.
 * Questions provide their own decline or skip action. */
export function Composer({
  draftKey,
  onSubmit,
  onStop,
  running,
  takesMessages = false,
  blocked,
  handover,
  approval = null,
  onAnswer,
  takeover = null,
  queued = [],
  onWithdraw,
  placeholder,
  autoFocus,
  ref,
  className,
}: {
  draftKey: string // whose draft it shows (use-drafts)
  onSubmit: (goal: string) => Promise<boolean> // true once the run started, which clears the draft
  onStop?: () => void
  running: boolean
  takesMessages?: boolean // the run in progress takes what is sent meanwhile
  blocked: string | null // why a new task cannot start now, if it cannot
  handover: Handover | null
  approval?: Approval | null // the step the open run waits for the user to approve
  onAnswer?: (decision: Decision, note: string) => Promise<boolean> // true once answered
  takeover?: Takeover | null
  queued?: Pending[] // sent to the run in progress, not read by its agents yet
  onWithdraw?: (message: Pending) => void
  placeholder: string
  autoFocus?: boolean
  ref?: Ref<HTMLTextAreaElement>
  className?: string
}) {
  const t = useT()
  const goal = useDraft(draftKey)
  // Bound to the conversation open as it renders, so a message that finishes sending after another one was opened
  // clears its own conversation's draft. Something written loads what shows the reply meanwhile.
  const onGoalChange = (text: string) => {
    if (text.trim()) void preloadMarkdown()
    setDraft(draftKey, text)
  }
  const [sending, setSending] = useState(false)
  const canSend = goal.trim() !== "" && !blocked && !sending
  const declining = approval !== null && goal.trim() !== ""
  // A step is answered once: its buttons and keys rest until the run moves on.
  const [answered, setAnswered] = useState<string | null>(null)
  const waiting = approval !== null && answered !== approval.id
  async function answer(decision: Decision, note = "") {
    if (!approval || !onAnswer) return false
    setAnswered(approval.id)
    const done = await onAnswer(decision, note)
    if (!done) setAnswered(null)
    return done
  }
  const textarea = useRef<HTMLTextAreaElement>(null)
  // A step waits while the agent has the desktop and a takeover while the user has it, so the two never meet.
  const asking = !handover && !approval ? takeover : null
  // What the composer asks, as one pair of answers that its buttons and its keys both give.
  const ask: Ask | null = handover
    ? {
        key: "handover",
        decline: {
          label: t.composer.handover.keep,
          onClick: () => handover.answer(false),
        },
        accept: {
          label: t.composer.handover.start,
          onClick: () => handover.answer(true),
        },
      }
    : approval
      ? {
          // Something written goes as the reason to decline the step, which the primary answer then sends, and Enter
          // too, as it sends anything written; declining without it keeps it. One pair throughout, so writing changes
          // only that answer's words.
          key: "approval",
          decline: {
            label: t.composer.approval.decline,
            onClick: () => answer("reject"),
            disabled: !waiting,
          },
          accept: {
            label: (
              <span className="swap">
                <span
                  data-hidden={declining ? "before" : undefined}
                  aria-hidden={declining}
                >
                  {t.composer.approval.approve}
                </span>
                <span
                  data-hidden={declining ? undefined : ""}
                  aria-hidden={!declining}
                >
                  {t.composer.send}
                </span>
              </span>
            ),
            onClick: () => (declining ? submit() : answer("approve")),
            disabled: !waiting || (declining && sending),
            byEnter: !declining,
          },
        }
      : asking
        ? {
            key: "takeover",
            decline: {
              label: t.composer.takeover.skip,
              onClick: asking.onSkip,
            },
            accept: {
              label: t.liveView.takeOver,
              onClick: asking.onTakeOver,
            },
          }
        : null
  useAnswerKeys(
    ask && {
      ...(!ask.decline.disabled && { Escape: ask.decline.onClick }),
      ...(!ask.accept.disabled &&
        ask.accept.byEnter !== false && { Enter: ask.accept.onClick }),
    },
    textarea
  )
  const question = handover
    ? t.composer.handover.title
    : approval
      ? t.composer.approval.ask(approval.consequence)
      : null
  // The screen the step was decided from, its target marked (agent/confirm.py), to see what it will act on.
  const shot =
    !handover && approval?.screenshot
      ? { run: approval.run, name: approval.screenshot }
      : null
  // Kept while its row folds away, so it does not go blank as it closes.
  const [asked, setAsked] = useState({ handover: false, question, shot })
  if (question !== null && question !== asked.question)
    setAsked({ handover: !!handover, question, shot })
  const [viewing, setViewing] = useState(false)
  // The row is opening or closing, which the conversation follows a frame at a time (index.css).
  const [opened, setOpened] = useState(question !== null)
  const [moving, setMoving] = useState(false)
  if (opened !== (question !== null)) {
    setOpened(question !== null)
    setMoving(true)
  }
  const [hint, setHint] = useState(false)
  const [stopTip, setStopTip] = useState(false)
  const hintTimer = useRef<number>(undefined)
  useEffect(() => () => window.clearTimeout(hintTimer.current), [])
  useImperativeHandle(ref, () => textarea.current!, [])

  // The text as its text box holds it, and what a mention needs there.
  const {
    shown,
    logos,
    overlay,
    options,
    current,
    listId,
    setHighlighted,
    choose,
    onKeyDown: mentionKeys,
    field,
  } = useMentionText({ goal, onGoalChange, textarea, listening: !handover })

  function showHint() {
    setHint(true)
    window.clearTimeout(hintTimer.current)
    hintTimer.current = window.setTimeout(() => setHint(false), NUDGE_MS)
  }

  async function submit(event?: FormEvent) {
    event?.preventDefault()
    if (!canSend) return
    setSending(true)
    try {
      const sent =
        approval && onAnswer
          ? await answer("reject", goal.trim())
          : await onSubmit(goal.trim())
      if (sent) onGoalChange("")
    } finally {
      setSending(false)
    }
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    // While the handover is asked, Enter and Esc here answer it (useAnswerKeys).
    if (handover) return
    if (isComposing(event.nativeEvent)) return
    if (mentionKeys(event)) return
    // Enter sends, Shift+Enter adds a line. With nothing written, a step waiting for approval takes it, to approve.
    // While a run that takes no message works, nothing goes yet: what is written stays, and the stop button says
    // when it can.
    const key = event.shiftKey ? "" : event.key
    if (key !== "Enter" || (approval && !declining)) return
    event.preventDefault()
    const held = running && !takesMessages && !approval
    if (goal.trim() && (blocked || held)) showHint()
    else if (!held) submit()
  }

  const stop = (
    <Tooltip
      key="stop"
      open={stopTip || hint}
      onOpenChange={(open) => {
        setStopTip(open)
        if (!open) setHint(false)
      }}
    >
      <TooltipTrigger
        render={
          <Button
            type="button"
            size="icon-sm"
            className={CORNER_BUTTON}
            aria-label={t.composer.stop}
            onClick={onStop}
          />
        }
      >
        <StopIcon className="size-5" />
      </TooltipTrigger>
      <TooltipContent>
        {hint ? t.composer.afterTask : t.composer.stopTask}
      </TooltipContent>
    </Tooltip>
  )

  return (
    <div className={cn("relative", className)}>
      {asked.shot && (
        <ScreenshotViewer
          run={asked.shot.run}
          shots={[{ name: asked.shot.name, label: asked.question ?? "" }]}
          index={viewing ? 0 : null}
          onIndexChange={(index) => setViewing(index !== null)}
        />
      )}
      <Queue
        messages={queued}
        hidden={question !== null || !!asking}
        onWithdraw={onWithdraw}
      />
      {/* Opaque, in dark mode too: the muted tint is mixed in, not see-through. */}
      <form
        onSubmit={submit}
        className="relative rounded-[1.75rem] border bg-background shadow-[0_2px_8px_rgb(0_0_0/0.04)] transition-shadow focus-within:shadow-[0_4px_16px_rgb(0_0_0/0.08)] dark:bg-[color-mix(in_oklch,var(--muted)_40%,var(--background))]"
      >
        <QuestionRow
          question={question}
          asked={asked}
          moving={moving}
          onMoved={() => setMoving(false)}
          onView={() => setViewing(true)}
        />
        {/* The focus stays put, so a screen reader hears the question as it appears. */}
        <span className="sr-only" aria-live="polite">
          {question ?? ""}
        </span>
        <label htmlFor="goal" className="sr-only">
          {t.composer.goal}
        </label>
        {options.length > 0 && (
          <MentionList
            id={listId}
            options={options}
            current={current}
            onHighlight={setHighlighted}
            onChoose={choose}
          />
        )}
        {/* The buttons sit beside the text and stay in the bottom corner as it grows; answers too wide for that go
          on a row of their own. */}
        <div className="flex flex-wrap items-end gap-2 p-2 pl-3">
          {asking && (
            <p className="flex min-h-10 min-w-0 flex-[1_1_12rem] items-center gap-2.5 py-2 pl-1 text-sm text-pretty">
              <HandIcon className="size-5 shrink-0 text-warning" />
              {asking.text}
            </p>
          )}
          {/* Hidden rather than gone while the takeover is asked in its place, so what was written stays. */}
          <div
            className={cn(
              "relative min-w-0 flex-[1_1_12rem]",
              asking && "hidden"
            )}
          >
            <textarea
              ref={textarea}
              id="goal"
              {...field}
              onChange={(event) => {
                // The handover is asked about the goal as it was sent: changing it, even emptying it, takes the question
                // back, and sending again asks about the new one.
                handover?.answer(false)
                field.onChange(event)
              }}
              onKeyDown={onKeyDown}
              placeholder={placeholder}
              autoFocus={autoFocus}
              rows={1}
              className={cn(
                TEXT,
                "field-sizing-content w-full resize-none bg-transparent outline-none placeholder:text-muted-foreground"
              )}
            />
            {logos.length > 0 && (
              <MentionLogos ref={overlay} shown={shown} logos={logos} />
            )}
          </div>
          <div className="ml-auto flex shrink-0">
            {/* Keyed apart: the stop and send buttons each have their own tooltip, held open by the hint in turn, which
            one passed from either to the other would confuse. */}
            {ask ? (
              <AnswerPair
                key={ask.key}
                decline={ask.decline}
                accept={ask.accept}
                className={ANSWERS}
              />
            ) : running && !(takesMessages && goal.trim()) ? (
              stop
            ) : (
              // A disabled button gets no pointer events, so the tooltip hangs on a wrapper around it.
              <Tooltip
                key="send"
                disabled={!blocked}
                open={!!blocked && hint}
                onOpenChange={setHint}
              >
                <TooltipTrigger render={<span className="flex rounded-full" />}>
                  <Button
                    type="submit"
                    size="icon-sm"
                    className={CORNER_BUTTON}
                    aria-label={running ? t.composer.send : t.composer.start}
                    disabled={!canSend}
                  >
                    <ArrowUpIcon className="size-6" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>{blocked}</TooltipContent>
              </Tooltip>
            )}
          </div>
        </div>
      </form>
    </div>
  )
}
