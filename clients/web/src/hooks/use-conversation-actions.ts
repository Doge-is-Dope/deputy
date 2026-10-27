import { useEffect, useMemo, useRef, useState } from "react"

import type { Handover } from "@/components/composer/composer"
import {
  ApiError,
  api,
  approvalFor,
  forComputer,
  runningOf,
  waitingOf,
  type Decision,
  type Owner,
  type Pending,
  type Status,
} from "@/lib/api"
import { t, useT } from "@/lib/i18n"

// What a 404 means depends on the action: one that continues a conversation, unless it says otherwise.
function explain(error: unknown, missing = t().home.cantContinue): string {
  if (error instanceof ApiError && error.status === 409)
    return error.reason === "conversation"
      ? t().home.conversationBusy
      : t().home.busy
  if (error instanceof ApiError && error.status === 404) return missing
  if (error instanceof ApiError) return error.message
  return t().home.offline
}

/** Conversation operations and their transient state; page layout and other conversations' notifications stay outside. */
export function useConversationActions({
  thread,
  project,
  status,
  isMobile,
  liveOpen,
  open,
  showLive,
  refreshStatus,
  refreshRuns,
}: {
  thread: string | null
  project: string | null // the project whose home is open: a new conversation begins in it
  status: Status | null
  isMobile: boolean
  liveOpen: boolean
  open: (thread: string | null) => void
  showLive: (focus?: boolean) => void
  refreshStatus: () => void
  refreshRuns: () => void
}) {
  const say = useT()
  const input = useRef<HTMLTextAreaElement>(null)
  const active = status?.active ?? null
  const working = thread === null ? null : runningOf(status, { thread })
  const current = working?.run ?? null
  // Command-line runs have no inbox, so they cannot take messages while working.
  const takesMessages = working?.pending !== undefined
  const userHasControl = status?.control.owner === "user"
  const approval = approvalFor(status, current)

  // Operation errors belong to the conversation in which the operation was taken.
  const [notice, setNotice] = useState<{
    thread: string | null
    text: string
  } | null>(null)
  const [noticeThread, setNoticeThread] = useState(thread)
  if (noticeThread !== thread) {
    setNoticeThread(thread)
    setNotice(null)
  }
  const report = (text: string) => setNotice({ thread, text })

  // Messages appear immediately, until status lists them or their run ends. RunView replaces read messages from its log.
  const [justSent, setJustSent] = useState<{ run: string; message: Pending }[]>(
    []
  )
  const listed = new Set(
    status?.running.flatMap((each) => each.pending ?? []).map((each) => each.id)
  )
  const stillShown = (each: { run: string; message: Pending }) =>
    !listed.has(each.message.id) &&
    runningOf(status, { run: each.run }) !== null
  if (status && !justSent.every(stillShown))
    setJustSent(justSent.filter(stillShown))
  // Kept while the same, so the turn it is shown in is not drawn again on every keystroke.
  const shownPending = working?.pending
  const pending = useMemo(
    () => [
      ...(shownPending ?? []),
      ...justSent
        .filter((each) => each.run === current)
        .map((each) => each.message),
    ],
    [shownPending, justSent, current]
  )

  /**
   * Does what the user asked of the runtime, null if it failed: the conversation says why, unless `ignore` says the
   * failure is no news (`missing`, what a 404 means), and the status and, if `runs` may have changed, the list of
   * conversations are read again either way.
   */
  async function act<T>(
    action: () => Promise<T>,
    {
      missing,
      ignore,
      runs = true,
    }: {
      missing?: string
      ignore?: (error: unknown) => boolean
      runs?: boolean
    } = {}
  ): Promise<T | null> {
    setNotice(null)
    try {
      return await action()
    } catch (error) {
      if (!ignore?.(error)) report(explain(error, missing))
      return null
    } finally {
      refreshStatus()
      if (runs) refreshRuns()
    }
  }

  // Sending @Computer asks before handing the user's desktop back, except on a phone where sending is the answer.
  const [handover, setHandover] = useState<
    (Handover & { thread: string | null }) | null
  >(null)
  function handOver(): Promise<boolean> {
    if (!userHasControl || isMobile) return Promise.resolve(true)
    handover?.answer(false)
    return new Promise((resolve) =>
      setHandover({
        thread,
        answer: (yes) => {
          setHandover(null)
          resolve(yes)
          if (!yes) input.current?.focus()
        },
      })
    )
  }
  // A different conversation, or control returned through the live view, cancels the pending question.
  const owner = status?.control.owner
  useEffect(() => {
    if (handover && (owner === "agent" || handover.thread !== thread))
      handover.answer(false)
  }, [handover, owner, thread])

  // A new conversation opens with a composer of its own in place of the one its first message was sent from: it takes
  // the focus over, as ChatGPT's stays in the composer after sending.
  const refocus = useRef<string | null>(null)
  useEffect(() => {
    if (refocus.current === null || refocus.current !== thread) return
    refocus.current = null
    input.current?.focus()
  }, [thread])

  async function start(goal: string) {
    if (current !== null && takesMessages) {
      const sent = await act(() => api.start(goal, thread ?? undefined))
      const message = sent?.message
      if (sent && message)
        setJustSent((list) => [
          ...list,
          { run: sent.id, message: { id: message, text: goal } },
        ])
      return sent !== null
    }
    // Another run owns the desktop until it finishes. Messages to this run must never return that run's control.
    const elsewhere = active !== null && active !== current
    const takeControl = forComputer(goal) && !elsewhere && userHasControl
    if (takeControl && !(await handOver())) return false
    const created = await act(() =>
      api.start(goal, thread ?? undefined, takeControl, project ?? undefined)
    )
    if (created) {
      if (created.thread !== thread) refocus.current = created.thread
      open(created.thread)
    }
    return created !== null
  }

  function stop() {
    if (current) return act(() => api.stop(current))
  }

  // True once deleted, for the sidebar to bring its row back if not.
  async function remove(conversation: string) {
    const deleted = await act(() => api.deleteConversation(conversation), {
      missing: say.home.deleted,
    })
    if (deleted && conversation === thread) open(null)
    return deleted !== null
  }

  // Deleted conversations back from the runtime's trash: true once all are.
  async function restore(conversations: string[]) {
    const restored = await Promise.all(
      conversations.map((each) => act(() => api.restoreConversation(each)))
    )
    return restored.every((each) => each !== null)
  }

  function rename(conversation: string, title: string) {
    return act(() => api.renameConversation(conversation, title), {
      missing: say.home.deleted,
    })
  }

  function move(conversation: string, project: string | null) {
    return act(() => api.moveConversation(conversation, project), {
      missing: say.home.deleted,
    })
  }

  // The live view presents control failures itself; only skipping a takeover reports one in the conversation.
  async function setControl(owner: Owner) {
    if (owner === "user") showLive()
    const done = await act(() => api.control(owner).then(() => true), {
      ignore: () => true,
      runs: false,
    })
    return done !== null
  }

  const waiting = waitingOf(status)
  const asked =
    waiting?.for === "takeover" && waiting.run === current ? waiting : null
  const [taken, setTaken] = useState<string | null>(null)
  if (asked && liveOpen && taken !== asked.id) setTaken(asked.id)
  const asking = asked !== null && taken !== asked.id ? asked : null
  function takeOver() {
    showLive(true)
  }
  async function skip() {
    if (!(await setControl("agent"))) report(say.composer.takeover.skipFailed)
  }

  // A step answered elsewhere disappears on refresh without reporting a conflict as an error.
  async function answer(decision: Decision, note: string) {
    if (!approval) return false
    const { id } = approval
    const done = await act(
      () => api.approval(id, decision, note).then(() => true),
      {
        ignore: (error) => error instanceof ApiError && error.status === 409,
        runs: false,
      }
    )
    return done !== null
  }

  return {
    input,
    notice: notice?.thread === thread ? notice.text : null,
    current,
    takesMessages,
    approval,
    pending,
    handover,
    asking,
    start,
    stop,
    remove,
    restore,
    rename,
    move,
    setControl,
    takeOver,
    skip,
    answer,
  }
}
