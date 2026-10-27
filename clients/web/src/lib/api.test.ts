import { describe, expect, it, vi } from "vitest"

import { approvalFor, runningOf, userSince, type Status } from "@/lib/api"

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

  it("says since when the user has had the desktop", () => {
    expect(userSince(status({}))).toBeNull()
    expect(
      userSince(status({ control: { owner: "user", since: 42, reason: "" } }))
    ).toBe(42)
    expect(userSince(null)).toBeNull()
  })

  it("gives the step a run waits to have approved", () => {
    const approval = { id: "a", run: "r1" } as Status["approval"]
    const waiting = status({ approval })
    expect(approvalFor(waiting, "r1")).toBe(approval)
    expect(approvalFor(waiting, "r2")).toBeNull()
    expect(approvalFor(waiting, null)).toBeNull()
  })
})
