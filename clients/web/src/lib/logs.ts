import type { AgentUsage, Cost, EndEvent, RunEvent, Tokens } from "@/lib/api"

/**
 * One log of a session (agent/session.py): a turn of the main agent or a task it handed over, as its stream has it so
 * far, with the places of its replies the page saw being written.
 */
export type SessionLog = {
  id: string
  events: readonly RunEvent[]
  streamed?: ReadonlySet<number>
}

type Start = Extract<RunEvent, { type: "start" }>

/** The cost of all of these, or null when one is not known. */
function costOf(costs: (Cost | null)[]): Cost | null {
  if (costs.some((cost) => cost == null)) return null
  const total: Cost = { input: 0, cached: 0, cache_write: 0, output: 0 }
  for (const cost of costs as Cost[])
    for (const kind of Object.keys(total) as (keyof Cost)[])
      total[kind] += cost[kind]
  return total
}

function usageOf(all: Tokens[]): Tokens {
  const total: Tokens = {
    input: 0,
    cached: 0,
    cache_write: 0,
    output: 0,
    reasoning: 0,
  }
  for (const tokens of all)
    for (const kind of Object.keys(total) as (keyof Tokens)[])
      total[kind] += tokens[kind] ?? 0
  return total
}

/** Each agent's tokens with each model across the logs, in the order first used. */
function agentsOf(ends: EndEvent[]): AgentUsage[] {
  const by = new Map<string, AgentUsage[]>()
  for (const end of ends)
    for (const each of end.agents ?? []) {
      const key = `${each.agent} ${each.model}`
      by.set(key, [...(by.get(key) ?? []), each])
    }
  return [...by.values()].map((same) => ({
    agent: same[0].agent,
    model: same[0].model,
    usage: usageOf(same.map((each) => each.usage)),
    cost: costOf(same.map((each) => each.cost)),
  }))
}

/**
 * A session's logs as the one list of events the conversation shows (lib/thread.ts), in the order they were written:
 * its first turn's start, the main agent's turns, and each task's work tagged with the task's id (`task`), between
 * the task starting and ending. A screenshot another log wrote is named "<log>/<file>" (api.screenshotUrl). The
 * session ends once it is `quiet` and every log has ended: then its last turn's end, at its last log's end, with what
 * every log used.
 * `streamed` are the places, in the list, of the replies the page saw being written.
 */
export function mergeSession(
  logs: readonly SessionLog[],
  quiet: boolean
): { events: RunEvent[]; streamed: Set<number> } {
  const starts = new Map<string, Start>()
  for (const log of logs)
    if (log.events[0]?.type === "start") starts.set(log.id, log.events[0])
  const first = logs.find(
    (log) => (starts.get(log.id)?.kind ?? "turn") === "turn"
  )?.id
  // The tasks the turns say started, with their logs. A task log whose turn is read along with it waits for that turn
  // to hand it over, which places it; one read without its turn (the live view's) announces itself.
  const turns = new Set(
    logs.flatMap((log) =>
      (starts.get(log.id)?.kind ?? "turn") === "turn" ? [log.id] : []
    )
  )
  const announced = new Set(
    logs.flatMap((log) =>
      log.events.flatMap((event) =>
        event.type === "task" && event.record ? [event.record] : []
      )
    )
  )
  const order = new Map(logs.map((log, at) => [log.id, at]))
  const written = logs
    .flatMap((log) =>
      log.events.map((event, at) => ({ log: log.id, at, event }))
    )
    .sort(
      (a, b) =>
        a.event.time - b.event.time ||
        order.get(a.log)! - order.get(b.log)! ||
        a.at - b.at
    )
  const events: RunEvent[] = []
  const streamed = new Set<number>()
  const ends: EndEvent[] = []
  let lastTurnEnd: EndEvent | null = null
  let open = 0 // logs started and not ended
  for (const { log, at, event } of written) {
    const start = starts.get(log)
    const task = start?.kind === "task" ? start : null
    if (task && turns.has(task.parent ?? "") && !announced.has(log)) continue
    if (event.type === "start") {
      open++
      if (task && !announced.has(log))
        events.push({
          type: "task",
          state: "started",
          id: task.id ?? "",
          agent: task.agent ?? "",
          brief: task.goal,
          title: task.title ?? "",
          record: log,
          time: event.time,
        })
      else if (!task && log === first) events.push(event)
      continue
    }
    if (event.type === "end") {
      open--
      ends.push(event)
      if (task)
        events.push({
          type: "task",
          state:
            event.stop_reason === "stopped"
              ? "stopped"
              : event.stop_reason === "error"
                ? "failed"
                : "ended",
          id: task.id ?? "",
          agent: task.agent ?? "",
          brief: task.goal,
          title: task.title ?? "",
          record: log,
          time: event.time,
        })
      else lastTurnEnd = event
      continue
    }
    let shown: RunEvent = task ? { ...event, task: task.id } : event
    if (
      log !== first &&
      "screenshot" in shown &&
      typeof shown.screenshot === "string"
    )
      shown = { ...shown, screenshot: `${log}/${shown.screenshot}` }
    if (logs[order.get(log)!].streamed?.has(at)) streamed.add(events.length)
    events.push(shown)
  }
  const arrived = logs.every((log) => starts.has(log.id))
  if (quiet && arrived && open === 0 && lastTurnEnd !== null)
    events.push({
      ...lastTurnEnd,
      // When its last log ended: a task the user stopped can end after the turn that handed it over.
      time: Math.max(...ends.map((end) => end.time)),
      usage: usageOf(ends.map((end) => end.usage).filter(Boolean)),
      cost: costOf(ends.map((end) => end.cost)),
      agents: agentsOf(ends),
    })
  return { events, streamed }
}
