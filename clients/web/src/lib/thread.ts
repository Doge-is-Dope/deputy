// Build chat items from run events, grouping each delegated task with its steps and result.

import type {
  ActionEvent,
  EndEvent,
  ModelEvent,
  NoteEvent,
  Outcome,
  RunEvent,
} from "@/lib/api"
import { describeAction, formatDuration } from "@/lib/format"
import { t } from "@/lib/i18n"
import type { Remembered } from "@/lib/memory"

export type Step = {
  key: string
  thought: string
  call?: ModelEvent["tool_calls"][number] // what the model asked for, before its result arrives
  action?: ActionEvent
  // It needed approval first (the composer asks: agent/confirm.py): whether auto review looks at it first, as the
  // user had it when the step came up, and whether it has yet; how it was answered, by whom ("auto": auto review,
  // with its reason as the note), once it was.
  approval?: {
    id: string
    autoReview?: boolean
    reviewed?: boolean
    outcome?: Outcome
    by?: string
    note?: string
  }
}

/** What happened in a task: its steps, and the runtime's notes and the user's turns at the desktop among them. */
export type TaskEntry =
  | { kind: "step"; key: string; step: Step }
  | { kind: "note"; key: string; text: string }
  // The user had the desktop and the agent waited for it: one line, from the runtime's note that it waits until its
  // note that the desktop is back, with how long they had it by its count (null while it waits, or if the task ended
  // meanwhile). Keyed by its place among them, which the page knows before the log does (`waitingFor`).
  | { kind: "control"; key: string; seconds: number | null }
  // The desktop was gone and the agent waited for it: one line, from the runtime's note that it went to its note that it
  // is back, with how long it was gone (null while it is); or to its note that it gave up waiting, which ends the task.
  | { kind: "offline"; key: string; seconds: number | null; gaveUp?: true }
  // A rule the user taught that the task was handed over with (the runtime's memoryUsed note): one line each.
  | { kind: "memory"; key: string; id: string; text: string }

/** Work handed over to an agent: to the computer agent, or to the coding agent. */
export type Task = {
  key: string
  tool: string // the main agent's tool that handed it over: computer_use or write_code
  brief: string // what the main agent asked
  title: string // a few words for the user, the main agent's name for it
  started: number
  ended: number | null // null while it runs
  outcome: "running" | "done" | "stopped" | "failed"
  entries: TaskEntry[]
  result: string // what the agent doing it said last, once it ended
  // The time it waited for the user rather than worked: for a step's answer, for the desktop back. Since when it waits now, by the log, if it does.
  waited: number
  waitingSince: number | null
}

export type Item =
  // Work handed over, shown where it was handed over, under what the main agent said with it.
  | { kind: "task"; key: string; task: Task }
  // Tasks handed over together, in one turn of the main agent, as agents at work: where they were handed over. Keyed
  // by the first, which it grows out of.
  | { kind: "agents"; key: string; tasks: Task[] }
  // Work the runtime turned away before it started, with its structured reason and human-readable result.
  | {
      kind: "held"
      key: string
      tool: string
      brief: string
      reason: NonNullable<ActionEvent["reason"]>
      result: string
    }
  // What the main agent said along with a call (handing work over, telling a task something, writing its plan): it
  // goes on after it, so these are words on the way, not its answer. They stay where it said them: a sentence may be
  // about several agents, or ask the user something. `at`: its model event's place.
  | {
      kind: "commentary"
      key: string
      text: string
      time: number
      at: number
    }
  // The runtime's notes outside any task.
  | { kind: "note"; key: string; text: string }
  // A message the user sent while the run worked, where an agent first read it.
  | { kind: "message"; key: string; id: string; text: string; time: number }
  // What the main agent said, where it said it: in a run that works in the background, it talks as it goes.
  | { kind: "reply"; key: string; text: string; time: number; at: number }
  // What the main agent remembered, where it called remember, before what it said after: one chip for the rules one
  // reply of its saved, as Claude marks a memory written. `updated`: one of them replaced a rule it had.
  | { kind: "memory"; key: string; memories: Remembered[]; updated: boolean }

/** A step of the main agent's plan for the work (its write_todos calls: langchain's TodoListMiddleware). */
export type PlanStep = {
  content: string
  status: "pending" | "in_progress" | "completed"
}

/** The plan as the main agent last wrote it, and where: the place of the model event that wrote it. */
export type Plan = { steps: PlanStep[]; at: number }

/** Whether two plans are the same writing: a thread built again, as it is on every word of a reply, makes a new one. */
export const samePlan = (a: Plan | null, b: Plan | null) =>
  a === b ||
  (a !== null &&
    b !== null &&
    a.at === b.at &&
    a.steps.length === b.steps.length &&
    a.steps.every(
      (step, index) =>
        step.content === b.steps[index].content &&
        step.status === b.steps[index].status
    ))

export type Shot = { name: string; label: string }

export type Thread = {
  goal: string | null
  // In the order to show them: each where it happened, a task where it was handed over, done or not.
  items: Item[]
  end: EndEvent | null
  started: number | null
  last: number | null
  screenshots: Shot[]
  // The main agent is working out what to say: since the user's latest message or a task's end, it has not answered.
  thinking: boolean
  // Whether the computer agent has the run: from its task's start until its end.
  usingComputer: boolean
  // The steps the main agent listed for the work, if it listed any: each call writes the whole list again.
  plan: Plan | null
  // Each task the run handed over, by its key, shown alone or among its agents.
  tasks: Map<string, Task>
}

// The main agent's tools that steer a task under way (agent/main_agent.py); every other tool of its hands work over
// to an agent, one tool per agent.
const STEERING = ["tell_task", "stop_task"]
const TELL_TASK = "tell_task"
const WRITE_TODOS = "write_todos"
const REMEMBER = "remember"
// What remember says it saved (runtime memory/tools.py): the id is the last word of a result that saved one.
const REMEMBERED = /^Remembered as (\S+?)\.?$/
// The main agent's tools that neither steer nor hand over: its plan, its search of the other conversations, and its
// memory (runtime memory/tools.py).
const NO_HANDOVER = [WRITE_TODOS, "search_conversations", REMEMBER, "forget"]
const STATUSES: readonly string[] = ["pending", "in_progress", "completed"]
const handsOver = (tool: string) =>
  !STEERING.includes(tool) && !NO_HANDOVER.includes(tool)

// The runtime's notes, as the conversation tells them in the interface's language.
function note(event: NoteEvent): string {
  const { code, data, text } = event
  const notes = t().notes
  switch (code) {
    case "userControl":
      return notes.userControl
    case "controlReturned":
      return data?.seconds === undefined
        ? text
        : notes.controlReturned(formatDuration(data.seconds))
    case "interrupted":
      return data?.tool === undefined ? text : notes.interrupted(data.tool)
    case "stuck":
      return data?.count === undefined ? text : notes.stuck(String(data.count))
    case "declined":
      return data?.count === undefined
        ? text
        : notes.declined(String(data.count))
    case "gone":
      return data?.seconds === undefined
        ? text
        : notes.gone(formatDuration(data.seconds))
    case "unusable":
      return notes.unusable
    case "runnerUnusable":
      return notes.runnerUnusable
    default:
      return text
  }
}

export function buildThread(events: RunEvent[]): Thread {
  const thread: Thread = {
    goal: null,
    items: [],
    end: null,
    started: events[0]?.time ?? null,
    last: events.at(-1)?.time ?? null,
    screenshots: [],
    thinking: false,
    usingComputer: false,
    plan: null,
    tasks: new Map(),
  }
  // Where each item goes: the index of the event it came from; a task's, just under the words it was handed over with.
  const order = new Map<string, number>()
  const add = (item: Item, at: number) => {
    thread.items.push(item)
    order.set(item.key, at)
  }
  // The tasks under way, by the runtime's id, which the events of their work carry.
  const running = new Map<string, Task>()
  // Handed over, their starts not confirmed yet, oldest first.
  const handing: Extract<Item, { kind: "task" }>[] = []
  // Each task's latest step still waiting for its action.
  const open = new Map<Task, Step | null>()
  // It waits for the user from `time` (a step asked of them, the desktop they have) until it goes on: after
  // `seconds`, by the runtime's count from when they took the desktop, or since it began waiting.
  const wait = (work: Task, time: number) => {
    work.waitingSince ??= time
  }
  const resume = (work: Task, time: number, seconds?: number) => {
    const since = work.waitingSince
    work.waitingSince = null
    if (seconds !== undefined)
      work.waited += Math.min(seconds, Math.max(0, time - work.started))
    else if (since !== null) work.waited += Math.max(0, time - since)
  }
  // The line for the user's turn at the desktop, open while it lasts.
  const control = (work: Task, seconds: number | null) => {
    const lines = work.entries.filter((entry) => entry.kind === "control")
    const last = lines.at(-1)
    if (last?.kind === "control" && last.seconds === null)
      last.seconds = seconds
    else
      work.entries.push({
        kind: "control",
        key: `control-${lines.length}`,
        seconds,
      })
  }
  // The line for the desktop gone, open while it is; closed as it came back, or as the agent gave up on it.
  const offline = (
    work: Task,
    key: string,
    seconds: number | null,
    gaveUp = false
  ) => {
    const last = work.entries.findLast((entry) => entry.kind === "offline")
    const ended = gaveUp ? { gaveUp: true as const } : {}
    if (seconds !== null && last?.kind === "offline" && last.seconds === null)
      Object.assign(last, { seconds, ...ended })
    else work.entries.push({ kind: "offline", key, seconds, ...ended })
  }
  const end = (work: Task | null, outcome: Task["outcome"], time: number) => {
    if (!work || work.outcome !== "running") return
    // What it still waited for the user for ends with it.
    resume(work, time)
    work.outcome = outcome
    work.ended = time
    open.delete(work)
    for (const [id, each] of running) if (each === work) running.delete(id)
  }
  // Where the main agent handed each task over: a task turned away before it started stays there.
  const handedAt = new Map<string, number>()
  // Every task in the order it was handed over, which its agent keeps among the others.
  const made: Task[] = []
  const task = (
    key: string,
    time: number,
    tool: string,
    brief: string,
    title: string
  ): Task => {
    const created: Task = {
      key,
      tool,
      brief,
      title,
      started: time,
      ended: null,
      outcome: "running",
      entries: [],
      result: "",
      waited: 0,
      waitingSince: null,
    }
    made.push(created)
    return created
  }
  // The chip for the rules the main agent's latest reply remembered, which its next remember call joins; a reply of
  // its starts the next.
  let remembered: Extract<Item, { kind: "memory" }> | null = null
  // The work an event belongs to: the task under way its id names.
  const workOf = (event: RunEvent): Task | undefined =>
    event.task === undefined ? undefined : running.get(event.task)

  events.forEach((event, index) => {
    const key = String(index)
    switch (event.type) {
      case "start":
        thread.goal = event.goal
        thread.thinking = true
        break
      case "task": {
        if (event.state === "started") {
          // Handed over just before: its start is when it started.
          const at = handing.findIndex(
            (each) =>
              each.task.tool === event.tool && each.task.brief === event.brief
          )
          if (at < 0) {
            // Handed over by the runtime, as a message for the desktop the main agent's reply did not hand over
            // (agent/main_agent.py DESKTOP_HANDED): its own line, where it started.
            const handed = task(
              `task-${index}`,
              event.time,
              event.tool,
              event.brief,
              event.title
            )
            add({ kind: "task", key: handed.key, task: handed }, index)
            handedAt.set(handed.key, index)
            running.set(event.id, handed)
            break
          }
          const [started] = handing.splice(at, 1)
          started.task.started = event.time
          running.set(event.id, started.task)
        } else {
          end(
            running.get(event.id) ?? null,
            event.state === "stopped" ? "stopped" : "done",
            event.time
          )
          thread.thinking = true // the runtime tells the main agent how it ended
        }
        break
      }
      case "note": {
        const work = workOf(event)
        if (
          event.code === "goal" ||
          event.code === "runFinished" ||
          event.code === "runStopped" ||
          event.code === "runFailed" ||
          event.code === "takeoverRequested"
        ) {
          // The goal, run outcome and takeover request already have dedicated UI.
        } else if (work && event.code === "userControl") {
          wait(work, event.time)
          control(work, null)
        } else if (work && event.code === "controlReturned") {
          control(work, event.data?.seconds ?? null)
          resume(work, event.time, event.data?.seconds)
        } else if (work && event.code === "disconnected") {
          offline(work, key, null)
        } else if (work && event.code === "reconnected") {
          offline(work, key, event.data?.seconds ?? 0)
        } else if (work && event.code === "gone") {
          offline(work, key, event.data?.seconds ?? 0, true)
        } else if (work && event.code === "memoryUsed") {
          for (const [n, rule] of (event.data?.rules ?? []).entries())
            work.entries.push({
              kind: "memory",
              key: `${key}-${n}`,
              id: rule.id,
              text: rule.text,
            })
        } else if (work) {
          work.entries.push({ kind: "note", key, text: note(event) })
        } else {
          add({ kind: "note", key, text: note(event) }, index)
        }
        break
      }
      case "message":
        add(
          {
            kind: "message",
            key,
            id: event.id,
            text: event.text,
            time: event.time,
          },
          index
        )
        // Read by the main agent, which answers it.
        thread.thinking = true
        break
      case "model": {
        if (event.agent === "main") {
          remembered = null
          // As written, but for the end: a paragraph indented with full-width spaces keeps them, as it did while being
          // written (trim() takes those too).
          const text = event.text.trimEnd()
          const listed = event.tool_calls.findLast(
            (call) => call.name === WRITE_TODOS
          )
          if (listed && Array.isArray(listed.args.todos))
            thread.plan = {
              steps: (listed.args.todos as PlanStep[]).filter(
                (step) =>
                  typeof step?.content === "string" &&
                  STATUSES.includes(step.status)
              ),
              at: index,
            }
          // Each task it hands over at once, keyed by its call's place too.
          event.tool_calls
            .filter((call) => handsOver(call.name))
            .forEach((call, n) => {
              const started = task(
                n === 0 ? `task-${index}` : `task-${index}-${n}`,
                event.time,
                call.name,
                String(call.args.task ?? ""),
                String(call.args.title ?? "")
              )
              const item = {
                kind: "task" as const,
                key: started.key,
                task: started,
              }
              handing.push(item)
              // Under the words it was handed over with, in the same reply (as a hand-over turned away is, below).
              add(item, index + 0.5)
              handedAt.set(started.key, index)
            })
          // Its words: said with a call, words on the way; otherwise its reply.
          if (text && event.tool_calls.length > 0) {
            add(
              {
                kind: "commentary",
                key: `${key}-said`,
                text,
                time: event.time,
                at: index,
              },
              index
            )
          } else if (text) {
            add(
              {
                kind: "reply",
                key: `${key}-reply`,
                text,
                time: event.time,
                at: index,
              },
              index
            )
          }
          // A turn that calls tools goes on after their results; one that calls none has answered.
          thread.thinking = event.tool_calls.length > 0
          break
        }
        const work = workOf(event)
        if (!work) break
        // A turn that calls no tool is the end of the work: what it says is the result.
        if (event.tool_calls.length === 0) {
          if (event.text.trim()) work.result = event.text.trim()
          open.set(work, null)
          break
        }
        const step: Step = {
          key,
          thought: event.text.trim(),
          call: event.tool_calls[0],
        }
        work.entries.push({ kind: "step", key, step })
        open.set(work, step)
        break
      }
      case "action": {
        if (event.agent === "main") {
          // Telling a task something ends the main agent's turn too (agent.main_agent): it waits on the task.
          if (event.tool === TELL_TASK && event.status === "success")
            thread.thinking = false
          const saved =
            event.tool === REMEMBER && event.status === "success"
              ? REMEMBERED.exec(event.result.trim())?.[1]
              : undefined
          // The rule as given; none for one turned away (no project, nothing to replace).
          if (saved) {
            const memory = { id: saved, text: String(event.args.rule ?? "") }
            const updated = Boolean(event.args.replaces)
            if (remembered) {
              remembered.memories.push(memory)
              remembered.updated ||= updated
            } else {
              remembered = {
                kind: "memory",
                key: `memory-${index}`,
                memories: [memory],
                updated,
              }
              add(remembered, index)
            }
          }
          if (!handsOver(event.tool)) break
          if (event.reason) {
            // Turned away before it started (e.g. another task had the computer): never ran.
            // The hand-over it answers, by its tool and brief.
            const at = handing.findIndex(
              (each) =>
                each.task.tool === event.tool &&
                each.task.brief === String(event.args.task ?? "")
            )
            if (at >= 0) {
              const [turned] = handing.splice(at, 1)
              const held: Item = {
                kind: "held",
                key: turned.key,
                tool: turned.task.tool,
                brief: turned.task.brief,
                reason: event.reason,
                result: event.result,
              }
              thread.items[thread.items.indexOf(turned)] = held
              // Under what the main agent said with it, in the same reply.
              order.set(
                held.key,
                (handedAt.get(turned.key) ?? Number(key)) + 0.5
              )
            }
          } else {
            // A turn that has handed work over ends there (agent.main_agent): nothing asks the main agent for more until the
            // task ends or the user writes.
            thread.thinking = false
          }
          break
        }
        const work = workOf(event)
        if (!work) break
        const step = open.get(work)
        if (step && !step.action && step.call?.name === event.tool) {
          step.action = event
        } else {
          work.entries.push({
            kind: "step",
            key,
            step: { key, thought: "", action: event },
          })
        }
        open.set(work, null)
        if (event.screenshot) {
          thread.screenshots.push({
            name: event.screenshot,
            label: `#${event.n} ${describeAction(event.tool, event.args).label}`,
          })
        }
        break
      }
      case "confirm": {
        const work = workOf(event)
        if (!work) break
        const step = open.get(work)
        if (step) {
          step.approval = { id: event.id, autoReview: event.auto_review }
          wait(work, event.time)
        }
        break
      }
      case "review": {
        const work = workOf(event)
        if (!work) break
        const step = open.get(work)
        if (step?.approval?.id === event.id) {
          step.approval.reviewed = true
          // Auto review has looked: what it lets through waited for nobody, the rest is asked of the user from now.
          work.waitingSince = event.allow ? null : event.time
        }
        break
      }
      case "decision": {
        const work = workOf(event)
        if (!work) break
        const step = open.get(work)
        if (step?.approval?.id === event.id) {
          Object.assign(step.approval, {
            outcome: event.outcome,
            by: event.by,
            note: event.note,
          })
          resume(work, event.time)
        }
        break
      }
      case "end": {
        thread.end = event
        const outcome =
          event.stop_reason === "cancelled"
            ? "stopped"
            : event.stop_reason === "error"
              ? "failed"
              : "done"
        for (const work of [...running.values()]) end(work, outcome, event.time)
        thread.thinking = false
        break
      }
      case "input":
        // A message the runtime gave the main agent (a task's result, its status): it is the main agent's turn.
        if (event.agent === "main") thread.thinking = true
        break
    }
  })
  // The computer agent has the run from its task's start till its end.
  thread.usingComputer = [...running.values()].some(
    (each) => each.tool === "computer_use"
  )

  thread.items = thread.items
    .map((item, index) => ({ item, index }))
    .sort(
      (a, b) =>
        (order.get(a.item.key) ?? a.index) -
          (order.get(b.item.key) ?? b.index) || a.index - b.index
    )
    .map(({ item }) => item)
  groupAgents(thread, made, handedAt)
  return thread
}

/** Tasks handed over together, in one turn of the main agent, show as one line of agents, where they were handed over.
 * One handed over in a later turn is a line of its own, however the others are doing: the conversation keeps the order
 * things happened in, with what the main agent said between them between them. Each agent its own work, opened on its
 * own, in the order they were handed over, so none moves as one ends. */
function groupAgents(
  thread: Thread,
  made: Task[],
  handedAt: ReadonlyMap<string, number>
) {
  const items = thread.items.filter(
    (item): item is Extract<Item, { kind: "task" }> => item.kind === "task"
  )
  thread.tasks = new Map(items.map((item) => [item.key, item.task]))
  const tasks = items
    .map((item) => item.task)
    .sort((a, b) => made.indexOf(a) - made.indexOf(b))
  const batches: Task[][] = []
  for (const task of tasks) {
    const batch = batches.at(-1)
    const together =
      batch && handedAt.get(batch[0].key) === handedAt.get(task.key)
    if (together) batch.push(task)
    else batches.push([task])
  }
  for (const batch of batches) {
    if (batch.length < 2) continue
    const mine = items.filter((item) => batch.includes(item.task))
    // Keyed by the first handed over, which stays first: as tasks end, the item stays the same one, open or not.
    const one: Item = { kind: "agents", key: batch[0].key, tasks: batch }
    thread.items[thread.items.indexOf(mine.at(-1)!)] = one
    thread.items = thread.items.filter(
      (item) => item.kind !== "task" || !batch.includes(item.task)
    )
  }
}

/**
 * Steps in a row: what the agent said as it took the first, if it said anything, and
 * the steps, notes and turns at the desktop till it says something again.
 */
export type Phase = {
  kind: "phase"
  key: string
  said: string
  entries: TaskEntry[]
}

/**
 * A task's entries in groups of steps, a new one wherever the agent says something; notes before any step stay as
 * they are.
 */
export function phasesOf(entries: TaskEntry[]): (TaskEntry | Phase)[] {
  const out: (TaskEntry | Phase)[] = []
  let phase: Phase | null = null
  for (const entry of entries) {
    if (entry.kind === "step" && (entry.step.thought || !phase)) {
      phase = {
        kind: "phase",
        key: entry.key,
        said: entry.step.thought,
        entries: [],
      }
      out.push(phase)
    }
    if (phase) phase.entries.push(entry)
    else out.push(entry)
  }
  return out
}

/** What a step does: the tool it ran, or was asked to, with its arguments. */
export const stepTool = (step: Step) => ({
  tool: step.action?.tool ?? step.call?.name ?? "",
  args: step.action?.args ?? step.call?.args ?? {},
})

/** A step that failed: an error, not an action held back on purpose (which has its reason). */
export const stepFailed = (step: Step) =>
  step.action?.status === "error" && !step.action.reason

/** The step the agent has asked for and has no result of yet. */
export function stepUnderWay(task: Task): Step | null {
  const last = task.entries.findLast((entry) => entry.kind === "step")
  return last?.kind === "step" && !last.step.action && last.step.call
    ? last.step
    : null
}

/** What the agent working on a task does now: the step under way, or that it thinks about its next. */
export function doingNow(task: Task): string {
  const call = stepUnderWay(task)?.call
  return call ? describeAction(call.name, call.args).label : t().run.busy.model
}

/** Whether the log has the agent waiting for the desktop the user has: its last line for their turn still open. */
export function awaitingDesktop(task: Task): boolean {
  const turn = task.entries.findLast((entry) => entry.kind === "control")
  return turn?.kind === "control" && turn.seconds === null
}

/** Current user-wait start: approval or takeover from the log, or the fresher runtime status. */
export function waitingFor(
  task: Task,
  took: number | null = null
): number | null {
  const last = task.entries.findLast((entry) => entry.kind === "step")
  const approval = last?.kind === "step" ? last.step.approval : undefined
  const reviewing =
    approval?.autoReview && !approval.reviewed && !approval.outcome
  const logged = reviewing ? null : task.waitingSince
  return logged === null || took === null
    ? (logged ?? took)
    : Math.min(logged, took)
}

/** How long a task has worked by `until`: since it started, less the time it waited for the user (`since`, now). */
export function workedFor(
  task: Task,
  until: number,
  since: number | null = null
): number {
  const waiting =
    since === null ? 0 : Math.max(0, until - Math.max(since, task.started))
  return Math.max(0, until - task.started - task.waited - waiting)
}

/** The task under way on the computer, or else any under way, if one is. */
export const runningTask = (thread: Thread): Task | null => {
  const tasks = [...thread.tasks.values()].filter(
    (task) => task.outcome === "running"
  )
  return tasks.find((task) => task.tool === "computer_use") ?? tasks[0] ?? null
}

/** The rules the run's tasks were handed over with (their memoryUsed notes), each once, in the order first cited. */
export function citedMemories(thread: Thread): Remembered[] {
  const cited = new Map<string, Remembered>()
  for (const task of thread.tasks.values())
    for (const entry of task.entries)
      if (entry.kind === "memory" && !cited.has(entry.id))
        cited.set(entry.id, { id: entry.id, text: entry.text })
  return [...cited.values()]
}
