import { describe, expect, it, vi } from "vitest"

import {
  describeAction,
  describeActions,
  formatDollars,
  formatDuration,
  greeting,
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

describe("describeAction", () => {
  it("leaves screen coordinates out", () => {
    expect(
      [
        describeAction("left_click", { coordinate: [850, 250] }),
        describeAction("double_click", {}),
        describeAction("zoom", { region: [152, 236, 1096, 612] }),
        describeAction("left_click_drag", {
          start_coordinate: [1, 2],
          coordinate: [3, 4],
        }),
        describeAction("mouse_move", { coordinate: [5, 6] }),
      ].map((action) => action.label)
    ).toEqual(["Click", "Double-click", "Zoom in", "Drag", "Move the pointer"])
  })

  it("marks where typed text goes on to a new line", () => {
    expect(describeAction("type", { text: "a\nb\r\nc" }).label).toBe(
      "Type “a ↵ b ↵ c”"
    )
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

describe("formatDollars", () => {
  it("shows an amount too small to round to a hundredth of a cent as under one, and nothing as zero", () => {
    expect(formatDollars(0.00003)).toBe("<$0.0001")
    expect(formatDollars(0.00007)).toBe("$0.0001")
    expect(formatDollars(0)).toBe("$0.0000")
    expect(formatDollars(12.345)).toBe("$12.35")
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
