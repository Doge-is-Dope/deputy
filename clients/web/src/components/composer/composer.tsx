import {
  useEffect,
  useId,
  useImperativeHandle,
  useLayoutEffect,
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
import { AttachmentTiles, DropOverlay } from "@/components/attachments"
import { AttachMenu } from "@/components/composer/attach-menu"
import { ArrowUpIcon, PlusIcon, StopIcon } from "@/components/icons"
import { preloadMarkdown } from "@/components/markdown/markdown"
import { ScreenshotViewer } from "@/components/screenshot-viewer"
import { useAttachments, useFileDrop } from "@/hooks/use-attachments"
import { setDraft, useDraft } from "@/hooks/use-drafts"
import { NUDGE_MS } from "@/hooks/use-flash"
import { type Approval, type Decision, type Pending } from "@/lib/api"
import { type Attachment } from "@/lib/attachments"
import { useT } from "@/lib/i18n"
import { isComposing, shortcutLabel } from "@/lib/keys"
import { reducedMotion } from "@/lib/motion"
import { Kbd } from "@/components/ui/kbd"
import { QuestionRow } from "@/components/composer/question-row"
import { Queue } from "@/components/composer/queue"
import {
  AnswerPair,
  type Ask,
  useAnswerKeys,
} from "@/components/composer/answers"

/**
 * The agent asking the user to take the desktop over, and why: answered by taking it (which opens the desktop) or by
 * skipping it (which hands it straight back, for the agent to carry on without).
 */
type Takeover = {
  text: string
  onTakeOver: () => void
  onSkip: () => void
}

// What comes into the composer's corner fades in, and what it takes the place of goes at once: the answers, as the
// question's row opens, and the stop and send buttons, which also grow a little into place. Those two are 32px,
// with 4px round them, so their middle stays where a 40px one's was, in line with the text and the corner. They are
// filled with the theme's accent, the icon in the surface's color as on the default black.
const ANSWERS =
  "transition-opacity duration-300 ease-(--ease-drawer) motion-reduce:transition-none starting:opacity-0"

const CORNER_BUTTON =
  "m-1 touch-target rounded-full bg-(--theme-accent) text-background duration-200 ease-(--ease-out) hover:bg-(--theme-accent)/80 motion-reduce:transition-none starting:scale-90 starting:opacity-0"

// The text box's box and type: 24 a line, 8 above and below, and room for a scrollbar, which takes room on some systems.
const TEXT =
  "block max-h-52 min-h-10 px-1 py-2 text-sm leading-6 whitespace-pre-wrap [scrollbar-gutter:stable]"

/** The @ typed before the caret, with what follows it up to the caret, when that could start one of `words`: where it
 * starts and ends. An @ inside a word, as in an email address, starts none. */
function typedAt(text: string, caret: number, words: string[]) {
  const found = /(?<![A-Za-z0-9_])@([^\s@]*)$/.exec(text.slice(0, caret))
  if (!found) return null
  const query = found[1].toLowerCase()
  // A word of a row's words starts with it, or holds it where words have no spaces between them (Chinese).
  const fits = words.some((each) =>
    each
      .toLowerCase()
      .split(/\s+/)
      .some((word) =>
        /^\w*$/.test(word) ? word.startsWith(query) : word.includes(query)
      )
  )
  return fits ? { start: found.index, end: caret } : null
}

// The text box's height with one line in it, and with a second line begun.
const ONE_LINE = 40
const SECOND_LINE = ONE_LINE + 12

/** Compose goals and steering messages, or answer approval and takeover requests.
 * Typed text during approval becomes the rejection reason. Takeover replaces the input.
 * While a run works, send nonempty text and stop when empty.
 * Questions provide their own decline or skip action. */
export function Composer({
  draftKey,
  onSubmit,
  onStop,
  running,
  blocked,
  approval = null,
  onAnswer,
  takeover = null,
  choice = null,
  queued = [],
  onWithdraw,
  placeholder,
  suggestion = "",
  autoFocus,
  ref,
  className,
}: {
  draftKey: string // whose draft it shows (use-drafts)
  // `clear` empties the draft, called once the message shows, so the two happen in one paint.
  // `attachments` are what was uploaded with it.
  onSubmit: (
    goal: string,
    queue: boolean,
    clear: () => void,
    attachments: Attachment[]
  ) => Promise<unknown>
  onStop?: () => void
  running: boolean
  blocked: string | null // why a new task cannot start now, if it cannot
  approval?: Approval | null // the step the open run waits for the user to approve
  onAnswer?: (decision: Decision, note: string) => Promise<boolean> // true once answered
  takeover?: Takeover | null
  choice?: { accept: () => Promise<boolean>; browse: () => void } | null // the open question's options, with nothing written
  queued?: Pending[] // sent to the run in progress, not read by its agents yet
  onWithdraw?: (message: Pending) => void
  placeholder: string
  suggestion?: string // the answer the open question expects typed, shown as the placeholder: Tab or → writes it in
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
  const attachments = useAttachments(draftKey)
  const canSend =
    goal.trim() !== "" && !blocked && !sending && attachments.ready
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
  const asking = !approval ? takeover : null
  // What the composer asks, as one pair of answers that its buttons and its keys both give.
  const ask: Ask | null = approval
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
  // Files go with a message that starts a run, an answer to the main agent's question too (its turn has ended), not
  // with one steering a run at work or answering a step or a takeover.
  const attachable = !running && !approval && !asking
  // The plus button's list, open until a row is picked, the text changes or loses the focus, Esc, or plus again; and
  // while an @ is typed that could start its words ("@", "@檔"), until Esc closes it for that @. With as many
  // files as a message takes it opens all the same: picking more says so (use-attachments).
  const menuId = useId()
  const [menu, setMenu] = useState(false)
  const [caret, setCaret] = useState<number | null>(null) // while the text has the focus and nothing is selected
  const [dismissed, setDismissed] = useState<number | null>(null)
  const typed =
    attachable && caret !== null
      ? typedAt(goal, caret, [t.composer.attachments.add])
      : null
  if (dismissed !== null && dismissed !== typed?.start) setDismissed(null)
  const listed =
    attachable && (menu || (typed !== null && dismissed !== typed.start))
  // What was typed for it goes first, an edit of the text box's own that undo brings back.
  function pickFiles() {
    const text = textarea.current
    if (!menu && typed && text) {
      text.setSelectionRange(typed.start, typed.end)
      document.execCommand("delete")
    }
    setMenu(false)
    picker.current?.click()
  }
  const dragging = useFileDrop(attachable, attachments.add)
  const picker = useRef<HTMLInputElement>(null)
  // What the composer asks, in the row over its text: a step to approve, or the takeover the agent asks.
  const question = approval
    ? t.composer.approval.ask(approval.consequence)
    : asking
      ? asking.text
      : null
  // The screen the step was decided from, its target marked (middleware/approvals.py), to see what it will act on.
  const shot = approval?.screenshot
    ? { run: approval.run, name: approval.screenshot }
    : null
  // Kept while its row folds away, so it does not go blank as it closes.
  const [asked, setAsked] = useState({ question, shot })
  if (question !== null && question !== asked.question)
    setAsked({ question, shot })
  const [viewing, setViewing] = useState(false)
  // The row is opening or closing, which the conversation follows a frame at a time (index.css).
  const [opened, setOpened] = useState(question !== null)
  const [moving, setMoving] = useState(false)
  if (opened !== (question !== null)) {
    setOpened(question !== null)
    setMoving(true)
  }
  // Past one line, or under a question, the text takes the composer's width and its buttons a row of their own below
  // it; one line on its own sits between them. Files leave it as it is: their row opens and closes over it, so adding
  // or taking off the last one moves nothing else. Once past a line it stays so until emptied, so it does not flip back
  // as the wider text box fits that line again.
  const [grown, setGrown] = useState(false)
  if (grown && !goal) setGrown(false)
  useLayoutEffect(() => {
    if (!grown && (textarea.current?.scrollHeight ?? 0) > SECOND_LINE)
      setGrown(true)
  }, [goal, grown])
  const stacked = grown || question !== null
  // As the text, plus and send switch between one row and two, they move from where they were rather than jump, and
  // the grid's height eases along: each part slides from its old place in the grid to its new one while the grid grows
  // or shrinks, cut to that height (FLIP). Places are taken from the grid's top, which the height moves with. With
  // motion reduced it switches at once.
  const grid = useRef<HTMLDivElement>(null)
  const placed = useRef<{
    stacked: boolean
    height: number
    parts: Map<Element, { x: number; y: number }>
  } | null>(null)
  useLayoutEffect(() => {
    const box = grid.current
    if (!box) return
    // Where everything ends up, taken before anything moves, by offsets, which a part's slide and the grid's eased
    // height leave out: a switch in the middle of another starts from these. The grid is as tall as its lowest part
    // and its padding.
    const parts = [...box.children].filter(
      (each): each is HTMLElement =>
        each instanceof HTMLElement && each.getClientRects().length > 0
    )
    const now = {
      stacked,
      height:
        Math.max(...parts.map((each) => each.offsetTop + each.offsetHeight)) -
        box.offsetTop +
        parseFloat(getComputedStyle(box).paddingBottom),
      parts: new Map(
        parts.map((each) => [
          each as Element,
          {
            x: each.offsetLeft - box.offsetLeft,
            y: each.offsetTop - box.offsetTop,
          },
        ])
      ),
    }
    const was = placed.current
    placed.current = now
    if (!was || was.stacked === stacked || reducedMotion()) return
    const timing = { duration: 300, easing: "cubic-bezier(0.32, 0.72, 0, 1)" }
    box.animate(
      [
        { height: `${was.height}px`, overflow: "clip" },
        { height: `${now.height}px`, overflow: "clip" },
      ],
      timing
    )
    for (const [part, to] of now.parts) {
      const from = was.parts.get(part)
      if (!from || (from.x === to.x && from.y === to.y)) continue
      part.animate(
        [
          { translate: `${from.x - to.x}px ${from.y - to.y}px` },
          { translate: "0 0" },
        ],
        timing
      )
    }
  })
  const [hint, setHint] = useState(false)
  const [stopTip, setStopTip] = useState(false)
  const hintTimer = useRef<number>(undefined)
  useEffect(() => () => window.clearTimeout(hintTimer.current), [])
  useImperativeHandle(ref, () => textarea.current!, [])

  function follow(text: HTMLTextAreaElement) {
    setCaret(
      text.selectionStart === text.selectionEnd ? text.selectionStart : null
    )
  }

  function showHint() {
    setHint(true)
    window.clearTimeout(hintTimer.current)
    hintTimer.current = window.setTimeout(() => setHint(false), NUDGE_MS)
  }

  // `queue`: while the run works, the message waits for it to end rather than steering it.
  async function submit(event?: FormEvent, queue = false) {
    event?.preventDefault()
    if (!canSend) return
    setSending(true)
    const sent = attachments.list
    const clear = () => {
      setDraft(draftKey, "", goal)
      attachments.clear(sent)
    }
    if (approval && onAnswer) {
      if (await answer("reject", goal.trim())) clear()
    } else {
      await onSubmit(goal.trim(), queue, clear, sent)
    }
    setSending(false)
  }

  async function takeRecommended() {
    setSending(true)
    await choice?.accept()
    setSending(false)
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (isComposing(event.nativeEvent)) return
    // While the plus button's list is open, Enter or Tab picks its row and Esc closes it; the arrows have nowhere to go.
    if (listed && !event.shiftKey) {
      if (
        ["Enter", "Tab", "Escape", "ArrowUp", "ArrowDown"].includes(event.key)
      )
        event.preventDefault()
      if (event.key === "Enter" || event.key === "Tab") return pickFiles()
      if (event.key === "Escape")
        return menu ? setMenu(false) : setDismissed(typed?.start ?? null)
      if (event.key === "ArrowUp" || event.key === "ArrowDown") return
    }
    // Enter sends, Shift+Enter adds a line, ⌘/Ctrl+Enter queues the message for when the run in progress ends. With
    // nothing written, a step waiting for approval takes it, to approve.
    const key = event.shiftKey ? "" : event.key
    if (
      suggestion &&
      !goal &&
      (key === "Tab" || key === "ArrowRight") &&
      !event.altKey &&
      !event.ctrlKey &&
      !event.metaKey
    ) {
      event.preventDefault()
      onGoalChange(suggestion)
      return
    }
    if (choice && !goal.trim() && key === "ArrowUp") {
      event.preventDefault()
      choice.browse()
      return
    }
    if (key !== "Enter" || (approval && !declining)) return
    event.preventDefault()
    // A held Enter sends nothing: its repeats may come from a press meant for something else, as a picture's markup.
    if (event.repeat) return
    // With nothing written, Enter takes the recommended answer, unless files wait to go with an answer of one's own.
    if (choice && !goal.trim() && attachments.list.length === 0) {
      if (blocked) showHint()
      else if (!sending) void takeRecommended()
      return
    }
    if (goal.trim() && blocked) showHint()
    else submit(undefined, event.metaKey || event.ctrlKey)
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
      <TooltipContent>{hint ? blocked : t.composer.stop}</TooltipContent>
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
      {dragging && <DropOverlay />}
      <Queue
        messages={queued}
        hidden={question !== null || !!asking}
        onWithdraw={onWithdraw}
      />
      {/* Opaque, in dark mode too: the muted tint is mixed in, not see-through. */}
      <form
        onSubmit={submit}
        className="relative rounded-4xl border bg-background shadow-[0_2px_8px_rgb(0_0_0/0.04)] dark:bg-[color-mix(in_oklch,var(--muted)_40%,var(--background))]"
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
        {listed && <AttachMenu id={menuId} onChoose={pickFiles} />}
        <AttachmentTiles
          draft={draftKey}
          list={attachments.list}
          onRemove={attachments.remove}
          onRetry={attachments.retry}
        />
        {/* One grid, so the text box stays the same element (and keeps the focus) as the buttons move under it. Its
          rows keep to their content while its height eases past it, rather than stretching to fill it. */}
        <div
          ref={grid}
          className="grid grid-cols-[auto_minmax(0,1fr)_auto] content-start items-end gap-x-2 p-2"
          style={{
            gridTemplateAreas: stacked
              ? '"text text text" "plus . corner"'
              : '"plus text corner"',
          }}
        >
          {/* In the corner opposite send, the same size and as far from the edges: it opens its list, as a typed @ does,
            and turns to a cross while it is open, keeping the focus in the text, where the list's keys work. There only
            while files can go. */}
          {attachable && (
            <Tooltip>
              <TooltipTrigger
                render={
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    className="touch-target m-1 rounded-full [grid-area:plus]"
                    aria-label={t.composer.attachments.add}
                    aria-haspopup="listbox"
                    aria-expanded={listed}
                    aria-controls={listed ? menuId : undefined}
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={() => {
                      textarea.current?.focus()
                      setMenu(!listed)
                      if (listed) setDismissed(typed?.start ?? null)
                    }}
                  />
                }
              >
                <PlusIcon
                  className={cn(
                    "transition-transform duration-200 ease-(--ease-out) motion-reduce:transition-none",
                    listed && "rotate-45"
                  )}
                />
              </TooltipTrigger>
              <TooltipContent>
                {t.composer.attachments.add}
                <Kbd>@</Kbd>
              </TooltipContent>
            </Tooltip>
          )}
          <input
            ref={picker}
            type="file"
            multiple
            hidden
            onChange={(event) => {
              attachments.add([...(event.target.files ?? [])])
              event.target.value = ""
            }}
          />
          {/* Hidden rather than gone while the takeover is asked, so what was written stays. On a row of its own, its
            words start where the icons under and over it do. */}
          <div
            className={cn(
              "relative min-w-0 [grid-area:text]",
              stacked && "pl-1.5",
              asking && "hidden"
            )}
          >
            <textarea
              ref={textarea}
              id="goal"
              value={goal}
              onChange={(event) => {
                setMenu(false)
                onGoalChange(event.target.value)
                follow(event.currentTarget)
              }}
              onSelect={(event) => follow(event.currentTarget)}
              onFocus={(event) => follow(event.currentTarget)}
              onBlur={() => {
                setMenu(false)
                setCaret(null)
              }}
              aria-activedescendant={listed ? `${menuId}-0` : undefined}
              onKeyDown={onKeyDown}
              // A pasted screenshot or file is attached; pasted text goes in as text.
              onPaste={(event) => {
                const pasted = [...event.clipboardData.files]
                if (!attachable || pasted.length === 0) return
                event.preventDefault()
                attachments.add(pasted)
              }}
              placeholder={placeholder}
              autoFocus={autoFocus}
              rows={1}
              className={cn(
                TEXT,
                "field-sizing-content w-full resize-none bg-transparent outline-none placeholder:text-muted-foreground placeholder:opacity-(--send-placeholder-opacity)"
              )}
            />
          </div>
          <div className="flex shrink-0 [grid-area:corner]">
            {/* Keyed apart: the stop and send buttons each have their own tooltip, held open by the hint in turn, which
            one passed from either to the other would confuse. */}
            {ask ? (
              <AnswerPair
                key={ask.key}
                decline={ask.decline}
                accept={ask.accept}
                className={ANSWERS}
              />
            ) : running && !goal.trim() ? (
              stop
            ) : (
              // A disabled button gets no pointer events, so the tooltip hangs on a wrapper around it.
              // It says it sends; while the run works, what Enter and ⌘/Ctrl+Enter do; when the message cannot go, why
              // not.
              <Tooltip
                key="send"
                {...(blocked && { open: hint, onOpenChange: setHint })}
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
                <TooltipContent>
                  {blocked || (
                    <>
                      {t.composer.send}
                      <Kbd>⏎</Kbd>
                      {running && (
                        <>
                          <span className="ml-1.5">{t.composer.queue}</span>
                          <Kbd>{shortcutLabel({ key: "⏎" })}</Kbd>
                        </>
                      )}
                    </>
                  )}
                </TooltipContent>
              </Tooltip>
            )}
          </div>
        </div>
      </form>
    </div>
  )
}
