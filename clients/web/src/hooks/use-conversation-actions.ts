import { useEffect, useMemo, useRef, useState } from "react"

import type { Handover } from "@/components/composer/composer"
import { showError } from "@/components/notice"
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
  confirmControl,
  refreshConversations,
}: {
  thread: string | null
  project: string | null // the project whose home is open: a new conversation begins in it
  status: Status | null
  isMobile: boolean
  liveOpen: boolean
  open: (thread: string | null) => void
  showLive: (focus?: boolean) => void
  refreshStatus: () => void
  confirmControl: (control: Status["control"]) => void
  refreshConversations: () => void
}) {
  const say = useT()
  const input = useRef<HTMLTextAreaElement>(null)
  const active = status?.active ?? null
  const working = thread === null ? null : runningOf(status, { thread })
  const current = working?.run ?? null
  // Command-line runs have no inbox, so they cannot take messages while working.
  const takesMessages = working?.pending !== undefined
  const userHasControl = status?.control.owner === "user"
  // The step any log of the session in progress waits to have approved: its turn's or a task's.
  const approval = approvalFor(
    status,
    working
      ? [working.run, ...(working.turn ? [working.turn] : []), ...working.tasks]
      : []
  )

  // The run started last from here and what was sent to it, drawn at once, before its log or the conversation's list
  // has it.
  const [started, setStarted] = useState<{
    run: string
    thread: string
    goal: string
  } | null>(null)

  // Messages appear immediately. One queued, until status lists it queued, or its run ends. One that steers the
  // session, until its run ends: read, it is in the run's log a moment after the status says so, and the turn draws it
  // from the log once it has it (RunThread), so it never goes missing in between.
  const [justSent, setJustSent] = useState<
    { run: string; message: Pending; queued: boolean }[]
  >([])
  const listed = new Set(
    status?.running.flatMap((each) =>
      (each.queued ?? []).map((message) => message.id)
    )
  )
  const stillShown = (each: {
    run: string
    message: Pending
    queued: boolean
  }) =>
    !(each.queued && listed.has(each.message.id)) &&
    runningOf(status, { run: each.run }) !== null
  if (status && !justSent.every(stillShown))
    setJustSent(justSent.filter(stillShown))
  // What was sent to steer the session, which the conversation shows where it goes, and what waits for it to end,
  // which the composer shows. Kept while the same, so the turn they are shown in is not drawn again on every keystroke.
  const shownSteering = working?.pending
  const shownQueued = working?.queued
  const steering = useMemo(() => {
    const waiting = shownSteering ?? []
    const sent = justSent
      .filter((each) => each.run === current && !each.queued)
      .map((each) => each.message)
    return [
      ...waiting,
      ...sent.filter(
        (message) => !waiting.some((each) => each.id === message.id)
      ),
    ]
  }, [shownSteering, justSent, current])
  const queued = useMemo(
    () => [
      ...(shownQueued ?? []),
      ...justSent
        .filter((each) => each.run === current && each.queued)
        .map((each) => each.message),
    ],
    [shownQueued, justSent, current]
  )

  /**
   * Runs an API action and returns null on failure. Shows errors unless `ignore` matches;
   * `missing` supplies the 404 message. Always refreshes status, whose revision brings the lists along when runs
   * change; `conversations` refreshes them too, for project writes, which it does not count.
   */
  async function act<T>(
    action: () => Promise<T>,
    {
      missing,
      ignore,
      conversations = false,
    }: {
      missing?: string
      ignore?: (error: unknown) => boolean
      conversations?: boolean
    } = {}
  ): Promise<T | null> {
    let result: T | null = null
    try {
      result = await action()
    } catch (error) {
      if (!ignore?.(error)) showError(explain(error, missing))
    }
    refreshStatus()
    if (conversations) refreshConversations()
    return result
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
  // the focus over, so the focus stays in the composer after sending.
  const refocus = useRef<string | null>(null)
  useEffect(() => {
    if (refocus.current === null || refocus.current !== thread) return
    refocus.current = null
    input.current?.focus()
  }, [thread])

  // `queue`: while the session works, the message waits for it to end rather than steering it.
  async function start(goal: string, queue = false) {
    if (current !== null && takesMessages) {
      const sent = await act(() =>
        api.start(goal, thread ?? undefined, false, undefined, queue)
      )
      const message = sent?.message
      if (sent && message)
        setJustSent((list) => [
          ...list,
          { run: sent.id, message: { id: message, text: goal }, queued: queue },
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
      setStarted({ run: created.id, thread: created.thread, goal })
      if (created.thread !== thread) refocus.current = created.thread
      open(created.thread)
    }
    return created !== null
  }

  function stop() {
    if (current && thread) return act(() => api.stop(thread))
  }

  // A queued message the session started the next one with meanwhile is in the conversation already, which is no news.
  async function withdraw(message: Pending) {
    if (current === null) return
    await act(() => api.withdraw(current, message.id), {
      ignore: (error) => error instanceof ApiError && error.status === 409,
    })
    setJustSent((list) => list.filter((each) => each.message.id !== message.id))
  }

  // True once deleted, for the sidebar to bring its row back if not.
  async function remove(conversation: string) {
    const deleted = await act(() => api.deleteConversation(conversation), {
      missing: say.home.deleted,
    })
    if (deleted && conversation === thread) open(null)
    return deleted !== null
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

  // A project's id once made (or the viewer's by that name already), renamed, or deleted; null if not.
  function createProject(name: string) {
    return act(() => api.createProject(name), { conversations: true })
  }

  function renameProject(project: string, name: string) {
    return act(() => api.renameProject(project, name), {
      conversations: true,
    })
  }

  function deleteProject(project: string) {
    return act(() => api.deleteProject(project), { conversations: true })
  }

  // The live view presents control failures itself; only skipping a takeover reports one in the conversation.
  async function setControl(owner: Owner) {
    if (owner === "user") showLive()
    try {
      confirmControl(await api.control(owner))
      return true
    } catch {
      refreshStatus()
      return false
    }
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
    if (!(await setControl("agent")))
      showError(say.composer.takeover.skipFailed)
  }

  // A step answered elsewhere disappears on refresh without reporting a conflict as an error.
  async function answer(decision: Decision, note: string) {
    if (!approval) return false
    const { id } = approval
    const done = await act(
      () => api.approval(id, decision, note).then(() => true),
      {
        ignore: (error) => error instanceof ApiError && error.status === 409,
      }
    )
    return done !== null
  }

  return {
    input,
    current,
    takesMessages,
    approval,
    steering,
    queued,
    handover,
    asking,
    started,
    start,
    stop,
    withdraw,
    remove,
    rename,
    move,
    createProject,
    renameProject,
    deleteProject,
    setControl,
    takeOver,
    skip,
    answer,
  }
}
