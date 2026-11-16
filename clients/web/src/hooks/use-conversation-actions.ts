import { useEffect, useMemo, useRef, useState } from "react"
import { flushSync } from "react-dom"

import { showError } from "@/components/notice"
import {
  ApiError,
  api,
  approvalFor,
  runningOf,
  waitingOf,
  waitingSession,
  type Decision,
  type Owner,
  type Pending,
  type Started,
  type Status,
} from "@/lib/api"
import { sentWith, type Attachment } from "@/lib/attachments"
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
  liveOpen: boolean
  open: (thread: string | null) => void
  showLive: (focus?: boolean) => void
  refreshStatus: () => void
  confirmControl: (control: Status["control"]) => void
  refreshConversations: () => Promise<void>
}) {
  const say = useT()
  const input = useRef<HTMLTextAreaElement>(null)
  const working = thread === null ? null : runningOf(status, { thread })
  const current = working?.run ?? null
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

  // A new conversation opens with a composer of its own in place of the one its first message was sent from: it takes
  // the focus over, so the focus stays in the composer after sending.
  const refocus = useRef<string | null>(null)
  useEffect(() => {
    if (refocus.current === null || refocus.current !== thread) return
    refocus.current = null
    input.current?.focus()
  }, [thread])

  // `queue`: while the session works, the message waits for it to end rather than steering it.
  async function start(
    goal: string,
    queue = false,
    onAccepted?: (sent: Started) => void,
    attachments: Attachment[] = []
  ) {
    const queued = current !== null && queue
    const sent = await act(() =>
      api.start(
        goal,
        thread ?? undefined,
        project ?? undefined,
        queued,
        attachments.flatMap((each) => (each.id ? [each.id] : []))
      )
    )
    if (!sent) return false
    const message = sent.message
    // Files go with a run's opening message only: shown with it at once, as its words are.
    if (!message) sentWith(sent.id, attachments)
    // The draft clearing and the new bubble show in the same paint.
    flushSync(() => {
      onAccepted?.(sent)
      if (message) {
        setJustSent((list) => [
          ...list,
          { run: sent.id, message: { id: message, text: goal }, queued },
        ])
      } else {
        setStarted({ run: sent.id, thread: sent.thread, goal })
        if (sent.thread !== thread) refocus.current = sent.thread
        open(sent.thread)
      }
    })
    return true
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

  // The project once made (or the viewer's by that name already), renamed, or deleted; null if not.
  async function createProject(name: string) {
    const project = await act(() => api.createProject(name))
    await refreshConversations() // listed before a conversation goes into it
    return project
  }

  function renameProject(project: string, name: string) {
    return act(() => api.renameProject(project, name), {
      conversations: true,
    })
  }

  function deleteProject(project: string) {
    return act(() => api.deleteProject(project), { conversations: true })
  }

  // The live view presents control failures itself; only skipping a takeover reports one, in a notice.
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
  // A task asks from its own log, so the wait is matched to this conversation's session by any of its logs.
  const asked =
    waiting?.for === "takeover" && waitingSession(status)?.run === current
      ? waiting
      : null
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
    approval,
    steering,
    queued,
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
