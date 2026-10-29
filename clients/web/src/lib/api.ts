// The runtime's HTTP API (runtime/src/computer_use/server.py) and the events a run writes to its log.

import { currentChoices } from "@/lib/choices"
import { locale } from "@/lib/i18n"
import { answered } from "@/lib/session"

export type Owner = "agent" | "user"
// How a run ended: the main agent replied, or the run was stopped (from the page or with Ctrl-C) or failed.
export type StopReason = "replied" | "cancelled" | "error"
// Why a run failed, as the runtime codes it (agent/failures.py, which says what each covers). The page says each in
// words (run.errors) and puts the code only in the report the user copies.
export type ErrorCode =
  | "E-DESKTOP"
  | "E-MODEL-KEY"
  | "E-MODEL-LIMIT"
  | "E-MODEL-DOWN"
  | "E-MODEL-REQUEST"
  | "E-CALL-LIMIT"
  | "E-UNKNOWN"

/** An agent's model ("provider:model") and reasoning effort. */
export type Choice = { model: string; effort: string }

export type Status = {
  // Each agent's model and effort as the runtime starts it, by agent: "main", then those it hands work to; a value, or
  // "follow" (the main agent's). What the user chooses over them is kept in this browser (lib/choices.ts): the runtime
  // is shared by many users and keeps none of their choices.
  defaults: Record<string, Choice>
  title_model: Choice // runtime-managed, displayed read-only
  models: { id: string; efforts: string[] }[] // what the settings page offers, each with the efforts it takes
  active: string | null // the run using the desktop
  titles_revision: number // changes as a conversation is named, during a run or after it (agent/title.py)
  running: Running[] // every run in progress, one per conversation at most
  error: { run: string; message: string } | null
  control: { owner: Owner; since: number; reason: string }
  approval: Approval | null // the step the running run waits for the user to approve
  computer: { connected: boolean; detail: string }
  // Where the coding agent's commands run; null when the runtime has none, and then no coding agent either.
  code_runner: { connected: boolean; detail: string } | null
  ice_servers: RTCIceServer[] // for the live view; a TURN server when the runtime runs in Docker
}

/** Active run state. Only web runs accept steering messages and report unread inbox entries. */
export type Running = {
  run: string
  thread: string
  pending?: Pending[]
}
export type Pending = { id: string; text: string }

/** A step the computer-use agent asks the user to approve before it is sent (agent/confirm.py). */
export type Approval = {
  id: string // the tool call's: an answer approves only this step
  run: string
  tool: string
  consequence: string // what the step will do, in the agent's words
  screenshot: string | null // the screen it decided from, its target marked
  since: number
  decision: Decision | null
}
export type Decision = "approve" | "reject"
// The user is asked every flagged step, or auto review first lets through those it judges not high risk and covered by
// the user's words (agent/review.py).
export type Approvals = "ask" | "auto"
// How the user answered a step awaiting approval, as the run's log records it.
export type Outcome = "approved" | "declined" | "took_control"

export type RunSummary = {
  id: string
  thread: string // the conversation the run belongs to: its first run's id
  goal: string // the user's message
  title: string | null // the conversation's name, made from its first message (agent/title.py); null until it is
  started: number
  actions: number // on the desktop
  ended: number | null // when it ended; null while it runs, or if it never ended (the runtime stopped under it)
  failed: boolean // it ended in an error, not a reply or the user's stop
  project: string | null // the id of the project its conversation is in (Project); null for none
  user: string // whose it is (the signed-in user's id); the runtime lists only the asker's
}

/** A project of the viewer's, which conversations are listed under; its id stays when it is renamed. */
export type Project = {
  id: string
  name: string
  created: number
}

/** Stable runtime note codes; the display text is never used to infer behavior. */
export type NoteCode =
  | "userControl"
  | "controlReturned"
  | "disconnected"
  | "reconnected"
  | "interrupted"
  | "stuck"
  | "declined"
  | "gone"
  | "unusable"
  | "runnerUnusable"
  | "takeoverRequested"
  | "runFinished"
  | "runStopped"
  | "runFailed"
  | "goal"
  | "memoryUsed"

/** Why an action was held back; an error without a reason is an execution failure. */
export type ActionReason =
  | "userControl"
  | "userActed"
  | "screenChanged"
  | "disconnected"
  | "declined"
  | "tookControl"
  | "batched"
  | "unexplained"
  | "desktopBusy"
  | "taskLimit"
  | "computerInUse"
  | "tooManyTasks"
  | "noTask"

// An event an agent logged while it worked on a background task carries that task's id (agent/trajectory.py TASK).
export type RunEvent = { time: number; task?: string } & (
  | {
      type: "start"
      v: 4 // only the current log format is served
      run?: string
      thread?: string
      goal: string
      computer?: boolean // the message was for the desktop (@Computer, or the command line)
      approvals?: Approvals // how the user chose, when they sent it, to have its steps approved; each confirm says
      // how it was as that step came up
    }
  | {
      type: "note"
      text: string
      code?: NoteCode | null
      data?: {
        seconds?: number
        count?: number
        tool?: string
        rules?: { id: string; text: string }[] // memoryUsed: the rules the user taught that a task was given
      }
    }
  // A message the runtime gave an agent; what it said stays in the runtime, which restores the conversation from it.
  | { type: "input"; agent?: "main" }
  // A message the user sent while the run worked, logged once an agent read it (agent/inbox.py)
  | { type: "message"; id: string; text: string }
  // The conversation's name, made from its first message in the background (agent/title.py)
  | { type: "title"; text: string; seconds?: number }
  // Work the main agent handed over in the background starting or ending (agent/background.py)
  | {
      type: "task"
      state: "started" | "ended" | "stopped"
      id: string // the task's id, which the events of its work carry (`task`)
      tool: string
      brief: string
      title: string // what the user sees for it: a few words, beside the brief the agent reads
    }
  | {
      type: "model"
      agent?: "main" // the main agent's; the computer-use agent's carry no tag
      text: string
      tool_calls: { name: string; args: Record<string, unknown> }[]
    }
  | {
      type: "action"
      agent?: "main"
      n: number
      id: string
      tool: string
      args: Record<string, unknown>
      status: "success" | "error"
      result: string
      reason?: ActionReason | null
      screenshot: string | null
    }
  | {
      type: "confirm" // the agent asked the user to approve a step
      id: string
      tool: string
      args: Record<string, unknown>
      consequence: string
      screenshot: string | null
      auto_review: boolean // auto review looks at it first, as the user had it then
    }
  | {
      type: "review" // what auto review made of it, before the user was asked
      id: string
      allow: boolean
      reason?: string
      error?: string // the review failed or took too long, so the user was asked
    }
  | {
      type: "decision" // how it was answered
      id: string
      outcome: Outcome
      note: string // what the user said with a rejection, or auto review's reason
      by: string // "web" or "cli", or "auto": auto review; empty when the user took the desktop
    }
  | {
      type: "end"
      stop_reason: StopReason
      summary: string // the main agent's reply
      usage: Tokens // the whole run's, every agent's
      cost: Cost | null // null when a model's price is unknown, or a call a stop cut off left its usage unknown
      agents: AgentUsage[] // the same by agent and model, in the order first used
      error?: string // why a run that ended in "error" failed: the exception, for the report
      error_code?: ErrorCode // the same, as a code
    }
)

/** Tokens a run used. Cache reads and writes are part of input, reasoning part of output. */
export type Tokens = {
  input: number
  cached: number
  cache_write: number
  output: number
  reasoning: number
}

/** The tokens one agent used with one model, and what they cost (null when its price is unknown). */
export type AgentUsage = {
  agent: string // "main", or a subagent's name in the settings: "computer", "coding"
  model: string
  usage: Tokens
  cost: Cost | null
}

/** US dollars at list prices, by kind of token: `input` is the input neither read from nor written to the cache. */
export type Cost = {
  input: number
  cached: number
  cache_write: number
  output: number
}

export type NoteEvent = Extract<RunEvent, { type: "note" }>
export type ModelEvent = Extract<RunEvent, { type: "model" }>
export type ActionEvent = Extract<RunEvent, { type: "action" }>
export type EndEvent = Extract<RunEvent, { type: "end" }>

// Why a message was turned away (409): another run is using the desktop, or the conversation has a run in progress.
export type BusyReason = "desktop" | "conversation"

export class ApiError extends Error {
  status: number
  run?: string
  reason?: BusyReason

  constructor(
    status: number,
    message: string,
    run?: string,
    reason?: BusyReason
  ) {
    super(message)
    this.status = status
    this.run = run
    this.reason = reason
  }
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: init?.body ? { "Content-Type": "application/json" } : undefined,
  })
  answered(response)
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new ApiError(
      response.status,
      data.error ?? response.statusText,
      data.run,
      data.reason
    )
  }
  return data as T
}

const post = <T>(path: string, body: object = {}) =>
  request<T>(path, { method: "POST", body: JSON.stringify(body) })

export const api = {
  status: () => request<Status>("/api/status"),
  runs: () => request<RunSummary[]>("/api/runs"),
  projects: () => request<Project[]>("/api/projects"),
  // A project by this name: the viewer's own if they have one by it already.
  createProject: (name: string) => post<Project>("/api/projects", { name }),
  renameProject: (project: string, name: string) =>
    request<Project>(`/api/projects/${project}`, {
      method: "PATCH",
      body: JSON.stringify({ name }),
    }),
  // The project only: its conversations are deleted first (useSidebarLists).
  deleteProject: (project: string) =>
    request<{ deleted: string }>(`/api/projects/${project}`, {
      method: "DELETE",
    }),
  // A deleted project back, for its conversations brought back from the trash to list under.
  restoreProject: (project: string) =>
    post<Project>(`/api/projects/${project}/restore`),
  // The conversations whose words hold the query (storage.said), most recently active first, one hit each.
  search: (query: string, signal?: AbortSignal) =>
    request<SearchHit[]>(`/api/search?q=${encodeURIComponent(query)}`, {
      signal,
    }),
  // Start or continue a conversation; steer its active web run when one exists.
  // takeControl transfers ownership only after acquiring the desktop.
  // Send browser choices, locale and time zone with each message.
  // A new conversation begins in `project` when given; a message into a conversation stays in its own.
  start: (
    goal: string,
    thread?: string,
    takeControl = false,
    project?: string
  ) =>
    post<Started>("/api/runs", {
      goal,
      ...(thread && { thread }),
      ...(takeControl && { take_control: true }),
      ...(project && !thread && { project }),
      ...currentChoices(),
      locale: locale(),
      // Today's date, for the agents, as the user's clock says it.
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    }),
  stop: (run: string) => post(`/api/runs/${run}/stop`),
  // Takes back a message sent to a run in progress, while none of its agents has read it (409 once one has).
  withdraw: (run: string, message: string) =>
    request<{ withdrawn: boolean }>(`/api/runs/${run}/messages/${message}`, {
      method: "DELETE",
    }),
  // Moves every run of the conversation to the runtime's data/trash, out of the list.
  deleteConversation: (thread: string) =>
    request<{ deleted: string[] }>(`/api/conversations/${thread}`, {
      method: "DELETE",
    }),
  // Brings a deleted conversation back from the runtime's trash.
  restoreConversation: (thread: string) =>
    post<{ restored: string[] }>(`/api/conversations/${thread}/restore`),
  // Names the conversation as the user wants it listed, over the name the runtime made.
  renameConversation: (thread: string, title: string) =>
    request<{ thread: string; title: string }>(`/api/conversations/${thread}`, {
      method: "PATCH",
      body: JSON.stringify({ title }),
    }),
  // Moves the conversation into a project (its id), or out of the one it is in (null).
  moveConversation: (thread: string, project: string | null) =>
    request<{ thread: string; project: string | null }>(
      `/api/conversations/${thread}`,
      { method: "PATCH", body: JSON.stringify({ project }) }
    ),
  control: (owner: Owner) => post<Status["control"]>("/api/control", { owner }),
  // Answers the step awaiting approval; doing it oneself is a takeover (control("user")).
  approval: (id: string, decision: Decision, message = "") =>
    post<{ id: string; decision: Decision }>("/api/approval", {
      id,
      decision,
      message,
    }),
  // How a run in progress answers its next step that needs approval, as the user just chose (lib/choices.ts).
  setApprovals: (run: string, approvals: Approvals) =>
    post<{ run: string; approvals: Approvals }>(`/api/runs/${run}/approvals`, {
      approvals,
    }),
  live: (sdp: string) =>
    post<RTCSessionDescriptionInit>("/api/live", { type: "offer", sdp }),
}

// A conversation a search found, by the words around the first match in its latest run that has one, "…" where cut.
export type SearchHit = { thread: string; snippet: string }

// The run: a new one, or for a message sent while the conversation's run works, that run and the message's id.
export type Started = { id: string; thread: string; message?: string }

// Why the user has the desktop when they took it themselves (runtime server.py, for the page and the CLI alike).
// Any other reason is the agent's own, given when it asked them to take over (agent/tools.py).
const TAKEN_OVER = "taken over by user"

/** Pending approval or requested takeover for the desktop owner.
 * id distinguishes consecutive waits; null means no user action is pending. */
export function waitingOf(
  status: Status | null
):
  | { id: string; run: string; for: "approval"; consequence: string }
  | { id: string; run: string; for: "takeover"; reason: string }
  | null {
  if (!status) return null
  if (status.approval)
    return {
      id: status.approval.id,
      run: status.approval.run,
      for: "approval",
      consequence: status.approval.consequence,
    }
  const { owner, reason, since } = status.control
  if (owner === "user" && status.active && reason && reason !== TAKEN_OVER)
    return {
      id: `${status.active}-${since}`,
      run: status.active,
      for: "takeover",
      reason,
    }
  return null
}

/** The run in progress with this id, or in this conversation; null when there is none. */
export function runningOf(
  status: Status | null,
  which: { run: string } | { thread: string }
): Running | null {
  const matches = (each: Running) =>
    "run" in which ? each.run === which.run : each.thread === which.thread
  return status?.running.find(matches) ?? null
}

/** Since when the user has had the desktop; null while the agent has it. */
export const userSince = (status: Status | null) =>
  status?.control.owner === "user" ? status.control.since : null

/** The step this run waits for the user to approve; null when it waits for none. */
export const approvalFor = (status: Status | null, run: string | null) =>
  run !== null && status?.approval?.run === run ? status.approval : null

/** Whether a message is for the desktop: it mentions @Computer, as the runtime reads it (agent/main_agent.py). */
export const forComputer = (message: string) =>
  /(?<![A-Za-z0-9_])@computer(?![A-Za-z0-9_])/i.test(message)

export const eventsUrl = (run: string) => `/api/runs/${run}/events`
// A screenshot, or with a width, a small copy of it for a thumbnail (server.py): a few kilobytes, not a few hundred.
export const screenshotUrl = (run: string, name: string, width?: number) =>
  `/api/runs/${run}/files/${name}${width ? `?w=${width}` : ""}`
