import { useSyncExternalStore } from "react"

import type { Approvals, Choice, Status } from "@/lib/api"
import { EFFORTS } from "@/lib/efforts"

// Browser-owned model, effort and approval choices, sent with each message.
// Reset restores status.defaults. Model changes apply next run; approval changes
// apply to the active run's next flagged step.

/** A subagent's model or effort that is the main agent's, whatever that is (the runtime's config.FOLLOW). */
export const FOLLOW = "follow"
const MAIN = "main"
const LEVELS = EFFORTS.map((effort) => effort.id)

/** By agent, the model and effort the user chose, a subagent's either FOLLOW; what is not here is as it starts. */
export type Chosen = Record<string, Partial<Choice>>
export type Choices = { agents: Chosen; approvals: Approvals }

const AGENTS_KEY = "agents"
const APPROVALS_KEY = "approvals"

function load(): Choices {
  let agents: Chosen = {}
  let approvals: Approvals = "ask"
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(AGENTS_KEY) ?? "{}")
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed))
      agents = parsed as Chosen
    if (localStorage.getItem(APPROVALS_KEY) === "auto") approvals = "auto"
  } catch {
    // Nothing stored, or nothing readable: everything as it starts.
  }
  return { agents, approvals }
}

let state = load()
const listeners = new Set<() => void>()

function save(next: Choices) {
  state = next
  try {
    if (Object.keys(next.agents).length)
      localStorage.setItem(AGENTS_KEY, JSON.stringify(next.agents))
    else localStorage.removeItem(AGENTS_KEY)
    if (next.approvals === "auto") localStorage.setItem(APPROVALS_KEY, "auto")
    else localStorage.removeItem(APPROVALS_KEY)
  } catch {
    // Not stored; the choice still holds until the page reloads.
  }
  for (const listener of listeners) listener()
}

// A choice made in another tab applies here too.
addEventListener("storage", (event) => {
  if (
    event.key === AGENTS_KEY ||
    event.key === APPROVALS_KEY ||
    event.key === null
  ) {
    state = load()
    for (const listener of listeners) listener()
  }
})

/** What is chosen now, as a message sends it. */
export function currentChoices(): Choices {
  return state
}

export function useChoices(): Choices {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener)
      return () => {
        listeners.delete(listener)
      }
    },
    () => state
  )
}

/** The highest of a model's efforts at or below this one; its lowest when none is (the runtime's models.clamp). */
function clamp(effort: string, levels: string[]): string {
  const rank = LEVELS.includes(effort) ? LEVELS.indexOf(effort) : LEVELS.length
  const below = levels.filter((level) => LEVELS.indexOf(level) <= rank)
  return below.at(-1) ?? levels[0] ?? effort
}

/** Resolve overrides and FOLLOW against runtime defaults, falling back to the main
 * model for unavailable models and clamping effort. Keep aligned with agent/models.py. */
export function resolve(
  status: Pick<Status, "defaults" | "models">,
  agent: string,
  agents: Chosen
): Choice {
  const offered = (model: string) =>
    status.models.some((each) => each.id === model)
  const of = (name: string) => ({
    ...(status.defaults[name] ?? { model: FOLLOW, effort: FOLLOW }),
    ...agents[name],
  })
  const main = of(MAIN)
  let model = offered(main.model) ? main.model : status.defaults[MAIN].model
  let effort = main.effort
  if (agent !== MAIN) {
    const own = of(agent)
    if (own.model !== FOLLOW && offered(own.model)) model = own.model
    if (own.effort !== FOLLOW) effort = own.effort
  }
  const efforts = status.models.find((each) => each.id === model)?.efforts
  return { model, effort: clamp(effort, efforts ?? []) }
}

/** Update model or effort; choosing the main agent's value restores FOLLOW. */
export function chooseModel(
  status: Pick<Status, "defaults" | "models">,
  agent: string,
  change: Partial<Choice>
) {
  const main = resolve(status, MAIN, state.agents)
  const own = { ...state.agents[agent] }
  for (const key of ["model", "effort"] as const) {
    const value = change[key]
    if (value === undefined) continue
    own[key] = agent !== MAIN && value === main[key] ? FOLLOW : value
  }
  save({ ...state, agents: { ...state.agents, [agent]: own } })
}

/** Every agent's model and effort as the runtime starts them. */
export function resetModels() {
  save({ ...state, agents: {} })
}

export function setApprovals(approvals: Approvals) {
  save({ ...state, approvals })
}
