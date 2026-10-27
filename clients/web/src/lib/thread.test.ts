import { describe, expect, it, vi } from "vitest"

import type { RunEvent } from "@/lib/api"
import events from "../../../../runtime/tests/fixtures/events-v4.json"
import {
  awaitingDesktop,
  buildThread,
  doingNow,
  stepFailed,
  waitingFor,
  workedFor,
  type Step,
  type Task,
  type TaskEntry,
} from "@/lib/thread"

vi.mock("@/lib/i18n", async () => {
  const { en } = await import("@/locales/en")
  return { t: () => en, locale: () => "en" }
})

const fixture = events as RunEvent[]

// Both runtimes consume this contract fixture. All behavior comes from codes, not these display strings.
describe("v4 event projection", () => {
  it("groups background work, subtracts user control time and shows the main reply once", () => {
    const thread = buildThread(fixture)
    expect(thread.goal).toBe("Open the report")
    expect(thread.items.map((item) => item.kind)).toEqual([
      "commentary",
      "task",
      "reply",
    ])
    const item = thread.items[1]
    expect(item.kind).toBe("task")
    if (item.kind !== "task") throw new Error("Expected task")
    expect(item.task).toMatchObject({
      started: 102,
      ended: 110,
      waited: 4,
      outcome: "done",
    })
    expect(workedFor(item.task, item.task.ended!)).toBe(4)
    expect(item.task.entries.at(-1)).toMatchObject({
      kind: "control",
      seconds: 4,
    })
    expect(item.task.entries[0]).toMatchObject({
      kind: "step",
      step: {
        action: {
          reason: "screenChanged",
          result: "The screen moved; decide again.",
        },
      },
    })
    expect(thread.screenshots).toEqual([
      { name: "001-left_click.png", label: "#1 Click (50, 60)" },
    ])
    expect(thread.thinking).toBe(false)
    expect(thread.usingComputer).toBe(false)
  })

  it("does not infer behavior from the runtime's prose", () => {
    const changed = fixture.map((event): RunEvent => {
      if (event.type === "note")
        return { ...event, text: "Completely revised wording" }
      if (event.type === "action")
        return { ...event, result: "Completely revised wording" }
      return event
    })
    const before = buildThread(fixture)
    const after = buildThread(changed)
    expect(after.items.map((item) => item.kind)).toEqual(
      before.items.map((item) => item.kind)
    )
    const work = after.items.find((item) => item.kind === "task")
    expect(work?.kind === "task" && work.task.waited).toBe(4)
  })

  it("localizes note parameters from structured data and keeps uncoded prose visible", () => {
    const thread = buildThread([
      fixture[0],
      {
        type: "note",
        code: "controlReturned",
        data: { seconds: 7 },
        text: "Changed wording",
        time: 101,
      },
      {
        type: "note",
        code: "stuck",
        data: { count: 5 },
        text: "Changed wording",
        time: 102,
      },
      {
        type: "note",
        code: "interrupted",
        data: { tool: "left_click" },
        text: "Changed wording",
        time: 103,
      },
      {
        type: "note",
        text: "Finished after this sentence, but only as free text.",
        time: 104,
      },
    ])
    expect(
      thread.items.map((item) => item.kind === "note" && item.text)
    ).toEqual([
      "Control is back (you had it for 7s); the agent looks at the screen again and carries on.",
      "Stopped: the last 5 actions didn't change the screen.",
      "The last run stopped during left_click; whether that action happened is unknown.",
      "Finished after this sentence, but only as free text.",
    ])
  })

  it("writes a note's seconds as every other duration is written", () => {
    const thread = buildThread([
      fixture[0],
      {
        type: "note",
        code: "controlReturned",
        data: { seconds: 75 },
        text: "Desktop resumed.",
        time: 101,
      },
      {
        type: "note",
        code: "gone",
        data: { seconds: 90 },
        text: "Desktop gone.",
        time: 102,
      },
    ])
    expect(
      thread.items.map((item) => item.kind === "note" && item.text)
    ).toEqual([
      "Control is back (you had it for 1m 15s); the agent looks at the screen again and carries on.",
      "Stopped: the desktop didn't reconnect within 1m 30s.",
    ])
  })

  it("rounds elapsed seconds for note text without losing wait accounting precision", () => {
    const seconds = 4.6789
    const returned: RunEvent = {
      type: "note",
      code: "controlReturned",
      data: { seconds },
      text: "Desktop resumed.",
      task: "t1",
      time: 109.6789,
    }
    const standalone = buildThread([fixture[0], returned])
    expect(standalone.items[0]).toMatchObject({
      kind: "note",
      text: "Control is back (you had it for 5s); the agent looks at the screen again and carries on.",
    })

    const thread = buildThread([
      ...fixture.slice(0, 8),
      returned,
      {
        type: "note",
        code: "reconnected",
        data: { seconds: 7.6789 },
        text: "Desktop reconnected.",
        task: "t1",
        time: 109.9,
      },
    ])
    const item = thread.items.at(-1)
    if (item?.kind !== "task") throw new Error("Expected task")
    expect(item.task.waited).toBe(seconds)
    expect(
      item.task.entries.find((entry) => entry.kind === "control")
    ).toMatchObject({ seconds })
    expect(item.task.entries.at(-1)).toMatchObject({
      kind: "offline",
      seconds: 7.6789,
    })
  })

  it("folds the desktop going and coming back into one line", () => {
    const gone = buildThread([
      ...fixture.slice(0, 8),
      {
        type: "note",
        code: "disconnected",
        text: "Desktop disconnected.",
        task: "t1",
        time: 109,
      },
    ])
    const back = buildThread([
      ...fixture.slice(0, 8),
      {
        type: "note",
        code: "disconnected",
        text: "Desktop disconnected.",
        task: "t1",
        time: 109,
      },
      {
        type: "note",
        code: "reconnected",
        data: { seconds: 75 },
        text: "Desktop reconnected.",
        task: "t1",
        time: 184,
      },
    ])
    const entries = (thread: ReturnType<typeof buildThread>) => {
      const item = thread.items.at(-1)
      if (item?.kind !== "task") throw new Error("Expected task")
      return item.task.entries.filter((entry) => entry.kind === "offline")
    }
    expect(entries(gone)).toEqual([
      { kind: "offline", key: "8", seconds: null },
    ])
    expect(entries(back)).toEqual([{ kind: "offline", key: "8", seconds: 75 }])
  })

  it("closes the desktop's line as given up when it does not come back in time", () => {
    const thread = buildThread([
      ...fixture.slice(0, 8),
      {
        type: "note",
        code: "disconnected",
        text: "Desktop disconnected.",
        task: "t1",
        time: 109,
      },
      {
        type: "note",
        code: "gone",
        data: { seconds: 60 },
        text: "Stopped: the desktop did not reconnect within 60 seconds.",
        task: "t1",
        time: 169,
      },
    ])
    const item = thread.items.at(-1)
    if (item?.kind !== "task") throw new Error("Expected task")
    // One line, closed, and no note beside it saying the same.
    expect(
      item.task.entries.filter(
        (entry) => entry.kind === "offline" || entry.kind === "note"
      )
    ).toEqual([{ kind: "offline", key: "8", seconds: 60, gaveUp: true }])
  })

  it("tracks open desktop waits and preserves an uncoded note verbatim", () => {
    const thread = buildThread([
      ...fixture.slice(0, 8),
      {
        type: "note",
        text: "The user has control. This is only free text.",
        task: "t1",
        time: 106,
      },
    ])
    const item = thread.items.at(-1)
    if (item?.kind !== "task") throw new Error("Expected running task")
    expect(awaitingDesktop(item.task)).toBe(true)
    expect(waitingFor(item.task)).toBe(105)
    expect(item.task.entries.at(-1)).toMatchObject({
      kind: "note",
      text: "The user has control. This is only free text.",
    })
    expect(workedFor(item.task, 109, waitingFor(item.task))).toBe(3)
  })

  it("marks an unstarted handoff as held from its reason, regardless of result text", () => {
    const thread = buildThread([
      ...fixture.slice(0, 3),
      {
        type: "action",
        agent: "main",
        n: 1,
        id: "held",
        tool: "computer_use",
        args: { task: "Open the report" },
        status: "error",
        result: "Busy elsewhere",
        reason: "desktopBusy",
        screenshot: null,
        time: 102,
      },
    ])
    expect(thread.items.find((item) => item.kind === "held")).toMatchObject({
      kind: "held",
      reason: "desktopBusy",
      result: "Busy elsewhere",
    })
    // Under what the main agent said as it handed it over.
    expect(thread.items.map((item) => item.kind)).toEqual([
      "commentary",
      "held",
    ])
    expect(thread.usingComputer).toBe(false)
  })

  it("shows a task the runtime handed over itself where it started", () => {
    const thread = buildThread([
      fixture[0],
      {
        type: "model",
        agent: "main",
        text: "Sure.",
        tool_calls: [],
        time: 101,
      },
      {
        type: "task",
        state: "started",
        id: "t1",
        tool: "computer_use",
        brief: "@Computer open notepad",
        title: "open notepad",
        time: 102,
      },
      {
        type: "model",
        text: "",
        tool_calls: [{ name: "key", args: { text: "win" } }],
        task: "t1",
        time: 103,
      },
    ])
    const item = thread.items.find((each) => each.kind === "task")
    if (item?.kind !== "task") throw new Error("Expected task")
    expect(item.task).toMatchObject({
      tool: "computer_use",
      title: "open notepad",
      outcome: "running",
    })
    expect(item.task.entries).toHaveLength(1)
    expect(thread.usingComputer).toBe(true)
    expect(thread.items.at(-1)).toBe(item)
  })

  it("shows a coding task as the coding agent's, which does not use the computer", () => {
    const thread = buildThread([
      fixture[0],
      {
        type: "model",
        agent: "main",
        text: "I will add them.",
        tool_calls: [{ name: "write_code", args: { task: "Add 2 and 2" } }],
        time: 101,
      },
      {
        type: "task",
        state: "started",
        id: "t1",
        tool: "write_code",
        brief: "Add 2 and 2",
        title: "",
        time: 102,
      },
      {
        type: "model",
        text: "",
        tool_calls: [
          { name: "bash", args: { script: "python3 add.py\necho done" } },
        ],
        task: "t1",
        time: 103,
      },
    ])
    const item = thread.items.find((each) => each.kind === "task")
    if (item?.kind !== "task") throw new Error("Expected task")
    expect(item.task).toMatchObject({
      tool: "write_code",
      brief: "Add 2 and 2",
      outcome: "running",
    })
    expect(item.task.entries).toHaveLength(1)
    // What the main agent said with it stays in the conversation, where it said it.
    expect(thread.items.map((each) => each.kind)).toEqual([
      "commentary",
      "task",
    ])
    expect(thread.usingComputer).toBe(false)
  })

  it("does not treat an execution error as an intentionally held task", () => {
    const thread = buildThread([
      ...fixture.slice(0, 3),
      {
        type: "action",
        agent: "main",
        n: 1,
        id: "failure",
        tool: "computer_use",
        args: {},
        status: "error",
        result: "Not executed: unexpected exception",
        screenshot: null,
        time: 102,
      },
    ])
    expect(thread.items.at(-1)?.kind).toBe("task")
  })

  it("waits for the user while a step is asked of them, and not while auto review looks at it first", () => {
    const asked = (
      id: string,
      autoReview: boolean,
      time: number
    ): RunEvent => ({
      type: "confirm",
      id,
      tool: "left_click",
      args: {},
      consequence: "Open report",
      screenshot: null,
      auto_review: autoReview,
      task: "t1",
      time,
    })
    const task = (events: RunEvent[]) => {
      const item = buildThread([...fixture.slice(0, 6), ...events]).items.at(-1)
      if (item?.kind !== "task") throw new Error("Expected task")
      return item.task
    }

    // Auto review was on as the step came up: nobody is asked until it has looked.
    const reviewing = task([asked("approval", true, 104)])
    expect(reviewing.entries[0]).toMatchObject({
      step: { approval: { autoReview: true } },
    })
    expect(waitingFor(reviewing)).toBeNull()
    // The user turned it off while the run worked: the next step is theirs to answer at once.
    expect(waitingFor(task([asked("approval", false, 104)]))).toBe(104)
  })

  it("accounts for rejected auto review only from when it asks the user", () => {
    const thread = buildThread([
      ...fixture.slice(0, 6),
      {
        type: "confirm",
        id: "approval",
        tool: "left_click",
        args: {},
        consequence: "Open report",
        screenshot: null,
        auto_review: true,
        task: "t1",
        time: 104,
      },
      {
        type: "review",
        id: "approval",
        allow: false,
        reason: "Ask the user",
        task: "t1",
        time: 105,
      },
      {
        type: "decision",
        id: "approval",
        outcome: "declined",
        by: "web",
        note: "Leave it",
        task: "t1",
        time: 108,
      },
    ])
    const item = thread.items.at(-1)
    if (item?.kind !== "task") throw new Error("Expected task")
    expect(item.task.waited).toBe(3)
    expect(waitingFor(item.task)).toBeNull()
    expect(item.task.entries[0]).toMatchObject({
      kind: "step",
      step: { approval: { outcome: "declined", reviewed: true } },
    })
  })

  describe("a plan and the work done on it", () => {
    const step = (content: string, status: string) => ({ content, status })
    // The main agent handing a task over with its plan beside it, the task's one step, and the task's end.
    const handing = (
      at: number,
      task: string,
      todos: unknown[],
      said: string,
      result = "Done.",
      words = ""
    ): RunEvent[] => [
      {
        type: "model",
        agent: "main",
        text: said,
        tool_calls: [
          { name: "write_todos", args: { todos } },
          { name: "computer_use", args: { task } },
        ],
        time: at,
      },
      {
        type: "action",
        agent: "main",
        n: 1,
        id: `p${at}`,
        tool: "write_todos",
        args: { todos },
        status: "success",
        result: "Updated todo list",
        screenshot: null,
        time: at,
      },
      {
        type: "action",
        agent: "main",
        n: 2,
        id: `m${at}`,
        tool: "computer_use",
        args: { task },
        status: "success",
        result: "Started in the background.",
        screenshot: null,
        time: at,
      },
      {
        type: "task",
        state: "started",
        id: `t${at}`,
        tool: "computer_use",
        brief: task,
        title: "",
        time: at,
      },
      {
        type: "model",
        text: words,
        tool_calls: [{ name: "key", args: { text: "win" } }],
        task: `t${at}`,
        time: at + 1,
      },
      {
        type: "action",
        n: 1,
        task: `t${at}`,
        id: `k${at}`,
        tool: "key",
        args: { text: "win" },
        status: "success",
        result: "Pressed win.",
        screenshot: null,
        time: at + 2,
      },
      {
        type: "model",
        text: result,
        tool_calls: [],
        task: `t${at}`,
        time: at + 3,
      },
      {
        type: "task",
        state: "ended",
        id: `t${at}`,
        tool: "computer_use",
        brief: task,
        title: "",
        time: at + 4,
      },
    ]

    it("does not take the main agent's search of the other conversations for work handed over", () => {
      const thread = buildThread([
        fixture[0],
        {
          type: "model",
          agent: "main",
          text: "Let me look.",
          tool_calls: [
            { name: "search_conversations", args: { query: "notepad" } },
          ],
          time: 101,
        },
        {
          type: "action",
          agent: "main",
          n: 1,
          id: "c1",
          tool: "search_conversations",
          args: { query: "notepad" },
          status: "success",
          result: "No other conversation matches.",
          reason: null,
          screenshot: null,
          time: 102,
        },
        {
          type: "model",
          agent: "main",
          text: "None mention Notepad.",
          tool_calls: [],
          time: 103,
        },
      ] as RunEvent[])
      expect(thread.items.map((item) => item.kind)).toEqual([
        "commentary",
        "reply",
      ])
    })

    it("reads the plan from the main agent's latest write_todos, not as work handed over", () => {
      const thread = buildThread([
        fixture[0],
        ...handing(
          100,
          "Find A",
          [
            step("A", "in_progress"),
            step("B", "pending"),
            { content: 3, status: "x" },
          ],
          "First A."
        ),
      ])
      expect(thread.plan?.steps).toEqual([
        step("A", "in_progress"),
        step("B", "pending"),
      ])
      expect(thread.items.filter((item) => item.kind === "task")).toHaveLength(
        1
      )
    })

    it("keeps tasks one after another apart, each where it was handed over, what was said between them between them", () => {
      const thread = buildThread([
        fixture[0],
        ...handing(
          100,
          "Find A",
          [step("A", "in_progress"), step("B", "pending")],
          "First A.",
          "A is 1."
        ),
        ...handing(
          120,
          "Find B",
          [step("A", "completed"), step("B", "in_progress")],
          "Now B.",
          "B is 2."
        ),
      ])
      expect(thread.plan?.steps).toEqual([
        step("A", "completed"),
        step("B", "in_progress"),
      ])
      expect(thread.items.some((item) => item.kind === "agents")).toBe(false)
      expect(
        thread.items.flatMap((item) =>
          item.kind === "task"
            ? [`task ${item.task.brief}`]
            : item.kind === "commentary"
              ? [`said ${item.text}`]
              : []
        )
      ).toEqual(["said First A.", "task Find A", "said Now B.", "task Find B"])
      expect(thread.tasks.size).toBe(2)
    })

    it("is not thinking once the main agent has told a task something, which ends its turn", () => {
      const told = (status: "success" | "error"): RunEvent[] => [
        ...handing(100, "Find A", [], "First A.").slice(0, 4),
        {
          type: "model",
          agent: "main",
          text: "",
          tool_calls: [{ name: "tell_task", args: { task_id: "t100" } }],
          time: 103,
        },
        {
          type: "action",
          agent: "main",
          n: 3,
          id: "tell",
          tool: "tell_task",
          args: { task_id: "t100" },
          status,
          result: "Told it.",
          screenshot: null,
          time: 103,
        },
      ]
      expect(buildThread([fixture[0], ...told("success")]).thinking).toBe(false)
      expect(buildThread([fixture[0], ...told("error")]).thinking).toBe(true)
    })

    it("follows agents at work at once by their ids, each with its own steps", () => {
      const at = (time: number, task: string, text: string): RunEvent => ({
        type: "model",
        text: "",
        tool_calls: [{ name: "key", args: { text } }],
        task,
        time,
      })
      const thread = buildThread([
        fixture[0],
        {
          type: "model",
          agent: "main",
          text: "Both at once.",
          tool_calls: [
            { name: "computer_use", args: { title: "A", task: "Open A" } },
            { name: "write_code", args: { title: "B", task: "Add B" } },
          ],
          time: 101,
        },
        {
          type: "task",
          state: "started",
          id: "t1",
          tool: "computer_use",
          brief: "Open A",
          title: "",
          time: 102,
        },
        {
          type: "task",
          state: "started",
          id: "t2",
          tool: "write_code",
          brief: "Add B",
          title: "",
          time: 102,
        },
        at(103, "t2", "b1"),
        at(104, "t1", "a1"),
        at(105, "t2", "b2"),
        {
          type: "task",
          state: "ended",
          id: "t2",
          tool: "write_code",
          brief: "Add B",
          title: "",
          time: 106,
        },
      ])
      const item = thread.items.at(-1)
      if (item?.kind !== "agents") throw new Error("Expected agents")
      const keys = (task: Task) =>
        task.entries.map((entry) =>
          entry.kind === "step" ? entry.step.call?.args.text : entry.kind
        )
      expect(
        item.tasks.map((task) => [task.tool, task.outcome, keys(task)])
      ).toEqual([
        ["computer_use", "running", ["a1"]],
        ["write_code", "done", ["b1", "b2"]],
      ])
      expect(item.tasks.map((task) => task.title)).toEqual(["A", "B"])
      expect(thread.usingComputer).toBe(true)
      expect(
        thread.items.filter((each) => each.kind === "commentary")
      ).toHaveLength(1)
    })

    it("keeps a task handed over in a later turn on a line of its own, after what was said meanwhile", () => {
      const started = (
        id: string,
        tool: string,
        brief: string,
        time: number
      ): RunEvent => ({
        type: "task",
        state: "started",
        id,
        tool,
        brief,
        title: "",
        time,
      })
      const thread = buildThread([
        fixture[0],
        {
          type: "model",
          agent: "main",
          text: "First A.",
          tool_calls: [
            { name: "computer_use", args: { title: "A", task: "Open A" } },
          ],
          time: 101,
        },
        started("t1", "computer_use", "Open A", 102),
        {
          type: "model",
          agent: "main",
          text: "Meanwhile B.",
          tool_calls: [
            { name: "write_code", args: { title: "B", task: "Add B" } },
          ],
          time: 103,
        },
        started("t2", "write_code", "Add B", 104),
      ])
      expect(
        thread.items.map((item) =>
          item.kind === "task" ? `task ${item.task.title}` : item.kind
        )
      ).toEqual(["commentary", "task A", "commentary", "task B"])
    })
  })
})

describe("a task's groups of steps and the step under way", () => {
  const task = (entries: TaskEntry[]) => ({ entries }) as Task
  const step = (key: string, part: Partial<Step>): TaskEntry => ({
    kind: "step",
    key,
    step: { key, thought: "", ...part },
  })
  const call = { name: "key", args: { text: "ctrl+s" } } as Step["call"]

  it("says the step asked for and not done yet, or that the agent thinks", () => {
    expect(doingNow(task([step("1", { call })]))).toBe("Press Ctrl+S")
    const done = { tool: "key", status: "success" } as Step["action"]
    expect(doingNow(task([step("1", { call, action: done })]))).toBe(
      "Thinking about the next step"
    )
    expect(doingNow(task([]))).toBe("Thinking about the next step")
  })

  it("counts an error as a failure, not an action held back on purpose", () => {
    const action = (part: object) =>
      ({ tool: "key", status: "error", ...part }) as Step["action"]
    expect(stepFailed({ key: "1", thought: "", action: action({}) })).toBe(true)
    expect(
      stepFailed({
        key: "1",
        thought: "",
        action: action({ reason: "userControl" }),
      })
    ).toBe(false)
  })
})
