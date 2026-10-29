import { beforeAll, describe, expect, it, vi } from "vitest"

import type * as Module from "@/lib/choices"

// The page keeps these in localStorage and hears other tabs' changes: stand-ins for both in Node.
let choices: typeof Module
beforeAll(async () => {
  const stored = new Map<string, string>()
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => stored.get(key) ?? null,
    setItem: (key: string, value: string) => stored.set(key, value),
    removeItem: (key: string) => stored.delete(key),
  })
  vi.stubGlobal("addEventListener", () => {})
  choices = await import("@/lib/choices")
})

const SOL = "openai:gpt-6.1-sol"
const LUNA = "openai:gpt-6-luna"
const status = {
  defaults: {
    main: { model: SOL, effort: "low" },
    computer: { model: LUNA, effort: "high" },
    coding: { model: "follow", effort: "follow" },
  },
  models: [
    { id: SOL, efforts: ["low", "medium", "high", "xhigh", "max"] },
    { id: LUNA, efforts: ["none", "low", "medium", "high", "xhigh"] },
  ],
}

describe("choices", () => {
  it("works out each agent's as the runtime does: following the main agent unless changed", () => {
    const { resolve } = choices
    expect(resolve(status, "coding", {})).toEqual({ model: SOL, effort: "low" })
    const chosen = {
      main: { model: SOL, effort: "medium" },
      computer: { model: "openai:gpt-5-gone", effort: "none" },
      coding: { model: LUNA, effort: "follow" },
    }
    // The main agent's model, at the lowest effort it takes: GPT-6.1 Sol has no "none".
    expect(resolve(status, "computer", chosen)).toEqual({
      model: SOL,
      effort: "low",
    })
    expect(resolve(status, "coding", chosen)).toEqual({
      model: LUNA,
      effort: "medium",
    })
  })

  it("keeps a subagent's choice of the main agent's value as following it, and forgets all on reset", () => {
    const { chooseModel, currentChoices, resetModels, setApprovals } = choices
    chooseModel(status, "coding", { model: SOL })
    chooseModel(status, "computer", { effort: "medium" })
    chooseModel(status, "main", { model: LUNA })
    setApprovals("auto")

    expect(currentChoices()).toEqual({
      agents: {
        coding: { model: "follow" },
        computer: { effort: "medium" },
        main: { model: LUNA },
      },
      approvals: "auto",
      memory: { learn: true, use: true },
    })
    expect(localStorage.getItem("approvals")).toBe("auto")
    resetModels()
    expect(currentChoices()).toMatchObject({ agents: {}, approvals: "auto" })
    expect(localStorage.getItem("agents")).toBeNull()
  })

  it("keeps memory on unless turned off, and stores only what is off", () => {
    const { currentChoices, setMemory } = choices
    setMemory({ learn: false })
    expect(currentChoices().memory).toEqual({ learn: false, use: true })
    expect(localStorage.getItem("memory-learn")).toBe("off")
    expect(localStorage.getItem("memory-use")).toBeNull()
    setMemory({ learn: true })
    expect(localStorage.getItem("memory-learn")).toBeNull()
  })
})
