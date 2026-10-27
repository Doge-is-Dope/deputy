import {
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type ChangeEvent,
  type ClipboardEvent,
  type CompositionEvent,
  type KeyboardEvent,
  type RefObject,
  type SyntheticEvent,
} from "react"

import { ComputerLogo } from "@/components/icons"
import { MENTION_LENGTH, mentionsIn } from "@/components/mentions"
import { useT } from "@/lib/i18n"

/**
 * The mention being typed: an @ and what follows it up to the caret, with no space in it. An @ inside a word, as in
 * an email address, starts none, as the runtime reads mentions (agent/main_agent.py).
 */
export function typedMention(text: string, caret: number) {
  const match = /(?<![A-Za-z0-9_])@([^\s@]*)$/.exec(text.slice(0, caret))
  return match && { start: match.index, query: match[1].toLowerCase() }
}

/** Whether a word of the text starts with the query, or holds it in words with no spaces between them (Chinese). */
export function fits(query: string, text: string) {
  return text
    .toLowerCase()
    .split(/\s+/)
    .some((word) =>
      /^\w*$/.test(word) ? word.startsWith(query) : word.includes(query)
    )
}

// The keys the @ list takes while it is open; Shift with any of them is the text's.
export const LIST_KEYS = ["ArrowDown", "ArrowUp", "Enter", "Tab", "Escape"]

// Replace mention @ with a fixed-width private-use glyph and overlay the logo.
// Restore @ when sending or copying; character positions stay unchanged.
export const MARK = "\uE000"

export const toGoal = (shown: string) => shown.replaceAll(MARK, "@")

export function toShown(goal: string) {
  let shown = goal
  for (const start of mentionsIn(goal))
    shown = shown.slice(0, start) + MARK + shown.slice(start + 1)
  return shown
}
// Loaded before the first mark, which is then drawn at its width.
void document.fonts.load('16px "Composer Mention"', MARK)

/** A name an @ completes to: what a message can be sent to, said in the interface's language, and its logo. */
export type Target = {
  name: string
  description: string
  logo: typeof ComputerLogo
}

/**
 * The composer's text as its text box holds it, and what a mention needs there: the @ list while one is typed, the
 * logo over each mention's @, and a mention copied, cut or deleted as a whole. The goal is the same text with its @s.
 */
export function useMentionText({
  goal,
  onGoalChange,
  textarea,
  listening,
}: {
  goal: string
  onGoalChange: (goal: string) => void
  textarea: RefObject<HTMLTextAreaElement | null>
  listening: boolean // the @ list may open: not while the handover is asked
}) {
  const t = useT()
  // What a message can be sent to with @. A name is the same in every language: the runtime looks for it.
  const targets: Target[] = [
    {
      name: "Computer",
      description: t.composer.mention.computer,
      logo: ComputerLogo,
    },
  ]
  // The text as the text box holds it, with a MARK for each mention's @. Edits here change it and the goal together;
  // a goal changed from outside (sent, or a suggestion picked) replaces it.
  const [shown, setShown] = useState(() => toShown(goal))
  if (toGoal(shown) !== toGoal(goal)) setShown(toShown(goal))
  // What is selected in the text, the caret where nothing is, and whether the text has the focus.
  const [selection, setSelection] = useState({ start: 0, end: 0 })
  function select(start: number, end = start) {
    setSelection((now) =>
      now.start === start && now.end === end ? now : { start, end }
    )
  }
  const caret = selection.start === selection.end ? selection.start : null
  const [focused, setFocused] = useState(false)

  // The list is open while the user types an @ here, until Esc closes it for that @. A name typed out in full has
  // nothing left to complete.
  const listId = useId()
  const [highlighted, setHighlighted] = useState(0)
  const [dismissed, setDismissed] = useState<number | null>(null)
  const mention =
    focused && listening && caret !== null ? typedMention(shown, caret) : null
  if (dismissed !== null && dismissed !== mention?.start) setDismissed(null)
  const options =
    mention && dismissed !== mention.start
      ? targets.filter(
          (target) =>
            target.name.toLowerCase() !== mention.query &&
            (fits(mention.query, target.name) ||
              fits(mention.query, target.description))
        )
      : []
  const current = Math.min(highlighted, options.length - 1)

  // Each mention whose @ is a MARK shows the logo there: a layer over the text, scrolled with it, holds the same text
  // unseen and the logo over each such MARK. The text stays the textarea's own, so typing, Chinese input, selecting
  // and undo work as they do anywhere.
  const marks = mentionsIn(goal)
  const logos = marks.filter((start) => shown[start] === MARK)
  const overlay = useRef<HTMLDivElement>(null)
  function follow() {
    if (overlay.current && textarea.current)
      overlay.current.scrollTop = textarea.current.scrollTop
  }
  useLayoutEffect(follow)

  // A mention typed or pasted gets a MARK for its @, and a MARK whose name was broken turns back into an @. Both are
  // edits of the text box's own, which undo takes back; a mention undone that way stays text until the next edit.
  function tidy(text: HTMLTextAreaElement) {
    queueMicrotask(() => {
      const wanted = toShown(toGoal(text.value))
      if (wanted === text.value || document.activeElement !== text) return
      const { selectionStart, selectionEnd } = text
      for (let i = 0; i < wanted.length; i++) {
        if (text.value[i] === wanted[i]) continue
        text.setSelectionRange(i, i + 1)
        document.execCommand("insertText", false, wanted[i])
      }
      text.setSelectionRange(selectionStart, selectionEnd)
    })
  }

  // The chosen name, with a MARK for its @ and a space after it, takes the place of what was typed from the @ on, of
  // the rest of a word the caret is in and of a space that follows: an edit of the text box's own, which leaves the
  // caret after it.
  function choose(name: string) {
    const text = textarea.current
    if (!mention || caret === null || !text) return
    let end = caret + (shown.slice(caret).match(/^\w*/)?.[0].length ?? 0)
    if (shown[end] === " ") end += 1
    text.setSelectionRange(mention.start, end)
    document.execCommand("insertText", false, `${MARK}${name} `)
  }

  // What is copied or cut out of the text has its @s back.
  function copy(event: ClipboardEvent<HTMLTextAreaElement>) {
    const text = event.currentTarget
    const part = text.value.slice(text.selectionStart, text.selectionEnd)
    if (!part.includes(MARK)) return false
    event.preventDefault()
    event.clipboardData.setData("text/plain", toGoal(part))
    return true
  }

  // An edit of the text box's own: the goal follows it.
  function onChange(event: ChangeEvent<HTMLTextAreaElement>) {
    const text = event.target
    select(text.selectionStart, text.selectionEnd)
    setShown(text.value)
    onGoalChange(toGoal(text.value))
    // Not while Chinese input composes, nor after undo or redo, which would undo nothing then.
    const input = event.nativeEvent as InputEvent
    if (!input.isComposing && !input.inputType?.startsWith("history"))
      tidy(text)
  }

  /** The keys the @ list and the mentions take; true when the list took the key, which then does nothing else. */
  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    // In the @ list, the arrow keys move, Enter or Tab picks, and Esc closes it.
    const key = event.shiftKey ? "" : event.key
    if (mention && options.length > 0 && LIST_KEYS.includes(key)) {
      event.preventDefault()
      if (key === "Escape") setDismissed(mention.start)
      else if (key === "Enter" || key === "Tab") choose(options[current].name)
      else {
        const step = key === "ArrowDown" ? 1 : -1
        setHighlighted((current + step + options.length) % options.length)
      }
      return true
    }
    // A mention goes as a whole, as it shows. What Backspace or Delete would take out (the selection, or the
    // character before or after the caret) grows to the whole of each mention it touches; the key's own deleting
    // then takes that out, so undo brings it back.
    const text = event.currentTarget
    const deleting = event.key === "Backspace" || event.key === "Delete"
    if (deleting && !(event.altKey || event.ctrlKey || event.metaKey)) {
      let from = text.selectionStart
      let to = text.selectionEnd
      if (from === to) {
        if (event.key === "Backspace") from -= 1
        else to += 1
      }
      const touched = marks.filter(
        (start) => start < to && start + MENTION_LENGTH > from
      )
      if (touched.length > 0)
        text.setSelectionRange(
          Math.min(from, touched[0]),
          Math.max(to, touched[touched.length - 1] + MENTION_LENGTH)
        )
    }
    return false
  }

  return {
    shown,
    logos,
    overlay,
    options,
    current,
    listId,
    setHighlighted,
    choose,
    onKeyDown,
    // What the text box takes from it: its text, and what keeps the text, the selection and the list in step.
    field: {
      value: shown,
      onChange,
      onCompositionEnd: (event: CompositionEvent<HTMLTextAreaElement>) =>
        tidy(event.currentTarget),
      onCopy: copy,
      onCut: (event: ClipboardEvent<HTMLTextAreaElement>) => {
        if (copy(event)) document.execCommand("delete")
      },
      onSelect: (event: SyntheticEvent<HTMLTextAreaElement>) =>
        select(
          event.currentTarget.selectionStart,
          event.currentTarget.selectionEnd
        ),
      onFocus: () => setFocused(true),
      onBlur: () => setFocused(false),
      onScroll: follow,
      "aria-autocomplete": "list" as const,
      "aria-controls": options.length > 0 ? listId : undefined,
      "aria-activedescendant":
        options.length > 0 ? `${listId}-${current}` : undefined,
    },
  }
}
