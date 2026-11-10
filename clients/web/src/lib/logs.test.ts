import { describe, expect, it, vi } from "vitest"

import type { RunEvent } from "@/lib/api"
import single from "../../../../runtime/tests/fixtures/events-v5.json"
import records from "../../../../runtime/tests/fixtures/events-v7.json"
import { mergeSession, type SessionLog } from "@/lib/logs"
import { buildThread, runningTask } from "@/lib/thread"

vi.mock("@/lib/i18n", async () => {
  const { en } = await import("@/locales/en")
  return { t: () => en, locale: () => "en" }
})

// The runtime's shared fixture: a turn that hands a task over, the task's own log, and the turn its end woke.
const [turn, task, next] = (records as { records: RunEvent[][] }).records
const logs: SessionLog[] = [
  { id: "turn-1", events: turn },
  { id: "task-1", events: task },
  { id: "turn-2", events: next },
]

/** What the page draws of a conversation's events: its items, with each task's span and outcome. */
function drawn(events: RunEvent[]) {
  const thread = buildThread(events)
  return {
    goal: thread.goal,
    items: thread.items.map((item) =>
      item.kind === "task"
        ? {
            kind: item.kind,
            started: item.task.started,
            ended: item.task.ended,
            outcome: item.task.outcome,
            title: item.task.title,
            entries: item.task.entries.map((entry) => entry.kind),
          }
        : { kind: item.kind }
    ),
    replied: thread.end?.summary,
  }
}

describe("a session's logs", () => {
  it("draw as the one log of a run did", () => {
    const { events } = mergeSession(logs, true)
    expect(drawn(events)).toEqual(drawn(single as RunEvent[]))
  })

  it("end when its last log ended, a task after the turn that handed it over", () => {
    const { events } = mergeSession(logs.slice(0, 2), true)
    const end = events.at(-1)
    const taskEnd = task.findLast((event) => event.type === "end")
    expect(end?.type).toBe("end")
    expect(end?.time).toBe(taskEnd?.time)
  })

  it("show a task whose log ended in an error as failed", () => {
    const failed = task.map((event) =>
      event.type === "end" ? { ...event, stop_reason: "error" } : event
    ) as RunEvent[]
    const { events } = mergeSession(
      [logs[0], { id: "task-1", events: failed }, logs[2]],
      true
    )
    const items = drawn(events).items
    expect(items.find((item) => item.kind === "task")).toMatchObject({
      outcome: "failed",
    })
  })

  it("name the screenshots of a task by its log", () => {
    const { events } = mergeSession(logs, true)
    const action = events.find(
      (event) => event.type === "action" && event.task === "t1"
    )
    expect(action && "screenshot" in action && action.screenshot).toBe(
      "task-1/001-left_click.png"
    )
  })

  it("end only once the session is quiet and every log has ended", () => {
    const ended = (events: RunEvent[]) =>
      events.filter((event) => event.type === "end")
    expect(ended(mergeSession(logs, false).events)).toEqual([])
    // While the task works, the session goes on: the task is under way, nothing has ended.
    const working = mergeSession(
      [
        { id: "turn-1", events: turn },
        { id: "task-1", events: task.slice(0, -1) },
      ],
      true
    )
    expect(ended(working.events)).toEqual([])
    expect(runningTask(buildThread(working.events))?.brief).toBe(
      "Open the report"
    )
  })

  it("add up what every log used", () => {
    const cost = { input: 0.01, cached: 0, cache_write: 0, output: 0.02 }
    const usage = {
      input: 10,
      cached: 0,
      cache_write: 0,
      output: 2,
      reasoning: 0,
    }
    const priced = (events: RunEvent[]) =>
      events.map((event) =>
        event.type === "end"
          ? {
              ...event,
              cost,
              usage,
              agents: [{ agent: "main", model: "m", usage, cost }],
            }
          : event
      )
    const { events } = mergeSession(
      logs.map((log) => ({ ...log, events: priced(log.events as RunEvent[]) })),
      true
    )
    const end = events.at(-1)
    expect(end?.type).toBe("end")
    if (end?.type !== "end") return
    expect(end.cost?.output).toBeCloseTo(0.06)
    expect(end.usage.input).toBe(30)
    expect(end.agents).toEqual([
      {
        agent: "main",
        model: "m",
        usage: { ...usage, input: 30, output: 6 },
        cost: expect.anything(),
      },
    ])
  })

  it("a task's log read alone says what the task is", () => {
    const { events } = mergeSession(
      [{ id: "task-1", events: task.slice(0, -1) }],
      false
    )
    expect(runningTask(buildThread(events))).toMatchObject({
      agent: "computer",
      brief: "Open the report",
    })
  })

  it("map the replies seen being written to their places", () => {
    const { streamed } = mergeSession(
      [
        { id: "turn-1", events: turn },
        { id: "task-1", events: task },
        { id: "turn-2", events: next, streamed: new Set([1]) },
      ],
      true
    )
    const { events } = mergeSession(logs, true)
    expect([...streamed].map((at) => events[at].type)).toEqual(["model"])
  })
})

describe("a task whose log comes before its turn hands it over", () => {
  it("waits for the hand-over, which places it after what the main agent said", () => {
    const handedAt = turn.findIndex((event) => event.type === "task")
    const early = mergeSession(
      [
        { id: "turn-1", events: turn.slice(0, handedAt) },
        { id: "task-1", events: task },
      ],
      false
    )
    expect(
      early.events.some((event) => event.type === "task" || event.task)
    ).toBe(false)
    const later = drawn(mergeSession(logs, true).events)
    expect(later.items.map((item) => item.kind)).toEqual([
      "commentary",
      "task",
      "reply",
    ])
  })
})
