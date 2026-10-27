import { describe, expect, it, vi } from "vitest"

import {
  describeActions,
  effortName,
  formatDuration,
  greeting,
  modelName,
  stepCode,
} from "@/lib/format"

vi.mock("@/lib/i18n", async () => {
  const { en } = await import("@/locales/en")
  return { t: () => en, locale: () => "en" }
})

describe("formatDuration", () => {
  it("rounds to the second and leaves a whole minute's or hour's zero out", () => {
    expect([4.6, 60, 75, 3600, 3660].map(formatDuration)).toEqual([
      "5s",
      "1m",
      "1m 15s",
      "1h",
      "1h 1m",
    ])
  })
})

describe("describeActions", () => {
  it("says each kind once, in the order it first came, a batch's actions each", () => {
    expect(
      describeActions([
        { tool: "left_click", args: {} },
        {
          tool: "computer_batch",
          args: { actions: [{ action: "type" }, { action: "key" }] },
        },
        { tool: "double_click", args: {} },
        { tool: "key", args: {} },
      ])
    ).toBe("Clicked, typed text, pressed keys")
    expect(describeActions([{ tool: "bash", args: {} }])).toBe("Ran commands")
  })
})

describe("stepCode", () => {
  it("shows a command with what it printed, exit code 0 left out", () => {
    expect(
      stepCode(
        "bash",
        { script: "python3 a.py" },
        "Exit code 0.\n總和：76127\n"
      )
    ).toEqual({ code: "python3 a.py", output: "總和：76127" })
    expect(stepCode("bash", { script: "false" }, "Exit code 1.\n")).toEqual({
      code: "false",
      output: "Exit code 1.",
    })
  })

  it("shows a file written as its content", () => {
    expect(
      stepCode("write_file", { path: "a.py", content: "print(1)\n" }, "Wrote")
    ).toEqual({ code: "print(1)\n", output: "" })
  })

  it("shows nothing for other steps", () => {
    expect(stepCode("left_click", { x: 1, y: 2 }, "ok")).toBeNull()
  })
})

describe("names", () => {
  it("names a model as its maker does, or by its id", () => {
    expect(modelName("openai:gpt-6.1-sol")).toBe("GPT-6.1 Sol")
    expect(modelName("anthropic:claude-haiku-5-5")).toBe("Claude Haiku 5.5")
    expect(modelName("openai:gpt-7")).toBe("gpt-7")
  })

  it("names a reasoning effort, or by its id", () => {
    expect(effortName("xhigh")).toBe("Extra High")
    expect(effortName("ultra")).toBe("ultra")
  })
})

describe("greeting", () => {
  const at = (hour: number, minute = 0) => new Date(2026, 9, 19, hour, minute)

  it("greets by the time of day, each from its first minute", () => {
    expect(greeting(at(4, 59))).toBe("Up late? What can I help with?")
    expect(greeting(at(5))).toBe("Good morning. What can I help with?")
    expect(greeting(at(12))).toBe("Good afternoon. What can I help with?")
    expect(greeting(at(18))).toBe("Good evening. What can I help with?")
    expect(greeting(at(23, 59))).toBe("Good evening. What can I help with?")
    expect(greeting(at(0))).toBe("Up late? What can I help with?")
  })
})
