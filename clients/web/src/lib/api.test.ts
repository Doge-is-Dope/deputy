import { describe, expect, it, vi } from "vitest"

import {
  approvalFor,
  runningOf,
  userSince,
  waitingOf,
  waitingSession,
  type Status,
} from "@/lib/api"

// The API's requests carry the browser's choices and language, which these selectors don't touch.
vi.mock("@/lib/choices", () => ({ currentChoices: () => ({}) }))
vi.mock("@/lib/i18n", () => ({ locale: () => "en" }))

const status = (part: Partial<Status>) =>
  ({
    running: [],
    control: { owner: "agent", since: 100, reason: "" },
    approval: null,
    ...part,
  }) as Status

describe("status selectors", () => {
  const running = status({
    running: [
      { run: "r1", thread: "t1" },
      { run: "r2", thread: "t2" },
    ] as Status["running"],
  })

  it("finds a run in progress by its id or its conversation", () => {
    expect(runningOf(running, { run: "r2" })?.thread).toBe("t2")
    expect(runningOf(running, { thread: "t1" })?.run).toBe("r1")
    expect(runningOf(running, { thread: "t3" })).toBeNull()
    expect(runningOf(null, { run: "r1" })).toBeNull()
  })

  it("finds the session waiting for the user by any of its logs", () => {
    const asking = {
      run: "r1",
      thread: "t1",
      turn: null,
      tasks: ["task-1"],
    } as Status["running"][number]
    const other = {
      run: "r2",
      thread: "t2",
      turn: "r2",
      tasks: [],
    } as Status["running"][number]
    const approval = { id: "a", run: "task-1" } as Status["approval"]
    expect(waitingSession(status({ running: [other, asking], approval }))).toBe(
      asking
    )
    expect(waitingSession(status({ running: [other], approval }))).toBeNull()
    expect(waitingSession(status({ running: [asking] }))).toBeNull()
    expect(waitingSession(null)).toBeNull()
  })

  it("says since when the user has had the desktop", () => {
    expect(userSince(status({}))).toBeNull()
    expect(
      userSince(status({ control: { owner: "user", since: 42, reason: "" } }))
    ).toBe(42)
    expect(userSince(null)).toBeNull()
  })

  it("gives the step one of a session's logs waits to have approved", () => {
    const approval = { id: "a", run: "task-1" } as Status["approval"]
    const waiting = status({ approval })
    expect(approvalFor(waiting, ["turn-1", "task-1"])).toBe(approval)
    expect(approvalFor(waiting, ["turn-2"])).toBeNull()
    expect(approvalFor(waiting, [])).toBeNull()
  })
})

describe("waitingOf", () => {
  const taken = (reason: string) =>
    waitingOf(
      status({
        active: "r1",
        control: { owner: "user", since: 100, reason, ready: true },
      } as Partial<Status>)
    )

  it("waits for the user only when the agent asked them to take over", () => {
    expect(taken("Please sign in.")).toMatchObject({ for: "takeover", reason: "Please sign in." })
    expect(taken("taken over from web")).toBeNull()
    expect(taken("taken over from cli")).toBeNull()
  })
})
