import type { ComponentType, SVGProps } from "react"

import type { Cost, ErrorCode, Status } from "@/lib/api"
import { EFFORTS } from "@/lib/efforts"
import { locale, t } from "@/lib/i18n"
import {
  ClickIcon,
  ClockIcon,
  CursorPositionIcon,
  DragIcon,
  HandIcon,
  KeyboardIcon,
  PencilIcon,
  PointerIcon,
  ScreenshotIcon,
  ScrollIcon,
  TerminalIcon,
  ToolIcon,
  ZoomInIcon,
} from "@/components/icons"

type Icon = ComponentType<SVGProps<SVGSVGElement>>
type Args = Record<string, unknown>

const point = (value: unknown) =>
  Array.isArray(value) ? `(${value.join(", ")})` : ""
const held = (args: Args) =>
  typeof args.text === "string" && args.text ? `${args.text} + ` : ""
const clip = (text: string, length = 80) =>
  text.length > length ? `${text.slice(0, length)}…` : text
// Keys as a keyboard labels them: "ctrl+shift+s" as Ctrl+Shift+S, "esc" as Esc.
const KEY_NAMES: Record<string, string> = {
  ctrl: "Ctrl",
  alt: "Alt",
  shift: "Shift",
  win: "Win",
  cmd: "Cmd",
  esc: "Esc",
  pgup: "PgUp",
  pgdn: "PgDn",
}
const keys = (text: unknown) =>
  String(text ?? "")
    .split("+")
    .map(
      (key) =>
        KEY_NAMES[key.toLowerCase()] ??
        key.charAt(0).toUpperCase() + key.slice(1)
    )
    .join("+")

/** What a tool call did, in a few words, and an icon for it. */
export function describeAction(
  tool: string,
  args: Args
): { icon: Icon; label: string } {
  const say = t().actions
  if (tool in say.clicks) {
    return {
      icon: ClickIcon,
      label: `${held(args)}${say.clicks[tool]} ${point(args.coordinate) || say.atCursor}`,
    }
  }
  switch (tool) {
    case "screenshot":
      return { icon: ScreenshotIcon, label: say.screenshot }
    case "zoom":
      return { icon: ZoomInIcon, label: say.zoom(point(args.region)) }
    case "left_click_drag":
      return {
        icon: DragIcon,
        label: say.drag(point(args.start_coordinate), point(args.coordinate)),
      }
    case "mouse_move":
      return { icon: PointerIcon, label: say.move(point(args.coordinate)) }
    case "left_mouse_down":
      return { icon: ClickIcon, label: say.mouseDown }
    case "left_mouse_up":
      return { icon: ClickIcon, label: say.mouseUp }
    case "cursor_position":
      return { icon: CursorPositionIcon, label: say.cursorPosition }
    case "scroll":
      return {
        icon: ScrollIcon,
        label: `${held(args)}${say.scroll(String(args.scroll_direction), args.scroll_amount ?? 3)}`,
      }
    case "type":
      return {
        icon: PencilIcon,
        label: say.type(clip(String(args.text ?? "")).replaceAll("\n", "⏎")),
      }
    case "key": {
      const repeat = Number(args.repeat ?? 1) > 1 ? ` ×${args.repeat}` : ""
      return { icon: KeyboardIcon, label: say.key(keys(args.text), repeat) }
    }
    case "hold_key":
      return {
        icon: KeyboardIcon,
        label: say.holdKey(keys(args.text), args.duration),
      }
    case "wait":
      return { icon: ClockIcon, label: say.wait(args.duration ?? 2) }
    case "computer_batch": {
      // Several actions from one screenshot: each in its own words, in order.
      const steps = Array.isArray(args.actions) ? (args.actions as Args[]) : []
      return {
        icon: steps.length
          ? describeAction(String(steps[0].action), steps[0]).icon
          : ToolIcon,
        label:
          steps
            .map((step) => describeAction(String(step.action), step).label)
            .join(" → ") || tool,
      }
    }
    case "request_takeover":
      return {
        icon: HandIcon,
        label: say.requestTakeover(String(args.reason ?? "")),
      }
    // The coding agent's (agent/coding_agent.py): a command, by its first line, and a file it writes.
    case "bash": {
      const first = String(args.script ?? "")
        .trim()
        .split("\n")[0]
      return { icon: TerminalIcon, label: first || say.code.run }
    }
    case "write_file":
      return {
        icon: PencilIcon,
        label: say.code.write(String(args.path ?? "")),
      }
    default:
      return { icon: ToolIcon, label: tool }
  }
}

// What kind of thing each tool does, for what a group of steps did.
const KINDS: Record<string, keyof ReturnType<typeof t>["actions"]["kinds"]> = {
  left_click: "click",
  right_click: "click",
  middle_click: "click",
  double_click: "click",
  triple_click: "click",
  left_click_drag: "drag",
  left_mouse_down: "drag",
  left_mouse_up: "drag",
  mouse_move: "move",
  screenshot: "look",
  zoom: "look",
  cursor_position: "look",
  type: "type",
  key: "key",
  hold_key: "key",
  scroll: "scroll",
  wait: "wait",
  request_takeover: "takeover",
  bash: "run",
  write_file: "write",
}

/**
 * What a group of steps did, by kind, each once in the order it first came, as Codex sums its tool calls up ("Edited a
 * file, ran commands"): "點擊、輸入文字、按鍵". A batch's actions count each.
 */
export function describeActions(calls: { tool: string; args: Args }[]) {
  const say = t().actions
  const kinds = new Set(
    calls.flatMap(({ tool, args }) =>
      (tool === "computer_batch" && Array.isArray(args.actions)
        ? (args.actions as Args[]).map((action) => String(action.action))
        : [tool]
      ).map((name) => (name in KINDS ? say.kinds[KINDS[name]] : name))
    )
  )
  return say.kindList([...kinds])
}

/** Command output or written file for coding steps. Omit exit code 0;
 * keep nonzero codes at the start. Other steps have no code details. */
export function stepCode(
  tool: string,
  args: Args,
  output?: string
): { code: string; output: string } | null {
  switch (tool) {
    case "bash":
      return {
        code: String(args.script ?? ""),
        output: (output ?? "").replace(/^Exit code 0\.\n/, "").trimEnd(),
      }
    case "write_file":
      return { code: String(args.content ?? ""), output: "" }
    default:
      return null
  }
}

// The units a time ago is said in, largest first, each with its length in seconds: a year of 365 days, a twelfth of
// it a month, so 364 days is 11 months ago and not 12.
const AGO: [Intl.RelativeTimeFormatUnit, number][] = [
  ["year", 365 * 86400],
  ["month", (365 / 12) * 86400],
  ["week", 7 * 86400],
  ["day", 86400],
  ["hour", 3600],
  ["minute", 60],
]

// Intl's formatters are slow to make, and the page formats times and amounts on every redraw: each kind is made once
// for each language.
const made = new Map<string, unknown>()
function formatter<T>(kind: string, make: (language: string) => T): T {
  const key = `${kind} ${locale()}`
  if (!made.has(key)) made.set(key, make(locale()))
  return made.get(key) as T
}

/** How long ago something happened, in its largest whole unit: just now, 5 minutes ago, yesterday, 2 weeks ago. */
export function timeAgo(seconds: number, now = Date.now() / 1000): string {
  const elapsed = now - seconds
  const unit = AGO.find(([, length]) => elapsed >= length)
  if (!unit) return t().dates.justNow
  return formatter(
    "ago",
    (language) => new Intl.RelativeTimeFormat(language, { numeric: "auto" })
  ).format(-Math.floor(elapsed / unit[1]), unit[0])
}

/** The home page's heading for the time of day: night until 5, then morning, afternoon from 12, evening from 18. */
export function greeting(now = new Date()): string {
  const hour = now.getHours()
  const greetings = t().home.greeting
  if (hour < 5) return greetings.night
  if (hour < 12) return greetings.morning
  if (hour < 18) return greetings.afternoon
  return greetings.evening
}

/** When something happened, in full: the date and the time. */
export const formatDateTime = (seconds: number) =>
  formatter(
    "date and time",
    (language) =>
      new Intl.DateTimeFormat(language, {
        dateStyle: "medium",
        timeStyle: "short",
      })
  ).format(seconds * 1000)

/** A count, grouped as the language groups digits. */
export const formatNumber = (count: number) =>
  formatter("number", (language) => new Intl.NumberFormat(language)).format(
    count
  )

export function formatDuration(seconds: number): string {
  const total = Math.max(0, Math.round(seconds))
  const minutes = Math.floor(total / 60)
  if (minutes >= 60)
    return t().durationHours(Math.floor(minutes / 60), minutes % 60)
  return t().duration(minutes, total % 60)
}

// Each model the runtime offers (agent/models.py's PRICES) as its maker names it.
const MODEL_NAMES: Record<string, string> = {
  "openai:gpt-6-luna": "GPT-6 Luna",
  "openai:gpt-6.1-sol": "GPT-6.1 Sol",
  "openai:gpt-6.1-terra": "GPT-6.1 Terra",
  "anthropic:claude-haiku-5-5": "Claude Haiku 5.5",
  "anthropic:claude-sonnet-5-5": "Claude Sonnet 5.5",
  "anthropic:claude-opus-5-5": "Claude Opus 5.5",
}

/** A model's name from "provider:model"; one not listed above goes by its id, without the provider. */
export const modelName = (spec: string) =>
  MODEL_NAMES[spec] ?? spec.split(":").pop() ?? spec

/** A reasoning effort's name; one not in EFFORTS goes by its id. */
export const effortName = (effort: string) =>
  EFFORTS.find(({ id }) => id === effort)?.name ?? effort

/** US dollars: to the cent, or to a hundredth of one under a dollar. */
export function formatDollars(dollars: number): string {
  const digits = dollars < 1 ? 4 : 2
  return formatter(
    `dollars ${digits}`,
    (language) =>
      new Intl.NumberFormat(language, {
        style: "currency",
        currency: "USD",
        currencyDisplay: "narrowSymbol",
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      })
  ).format(dollars)
}

/** What a run cost, every kind of token together. */
export const formatCost = (cost: Cost) =>
  formatDollars(cost.input + cost.cached + cost.cache_write + cost.output)

/** Whether the desktop can be reached, in a few words, and the detail; null until the first status arrives. */
export function connectionOf(
  status: Status | null,
  offline: boolean
): { connected: boolean; label: string; detail: string } | null {
  const say = t().connection
  if (offline)
    return { connected: false, label: say.offline, detail: say.offlineDetail }
  if (!status) return null
  const { connected, detail } = status.computer
  return {
    connected,
    label: connected ? say.connected : say.disconnected,
    detail,
  }
}

/** Build copyable failure codes: E-SERVICE for API access, E-DESKTOP for desktop
 * connection, or the run's ErrorCode and ID. */
export type Problem = {
  code: "E-SERVICE" | ErrorCode
  detail: string
  run?: string
}

export function problemOf(
  status: Status | null,
  offline: boolean
): Problem | null {
  if (offline) return { code: "E-SERVICE", detail: "" }
  if (status && !status.computer.connected)
    return { code: "E-DESKTOP", detail: status.computer.detail }
  return null
}

/** What the user copies to report a problem: in English whatever the interface's language, for whoever fixes it. */
export function problemReport(problem: Problem, since: Date): string {
  return [
    `Error: ${problem.code}`,
    problem.detail && `Detail: ${problem.detail}`,
    problem.run && `Run: ${problem.run}`,
    `Since: ${since.toISOString()}`,
    `Copied: ${new Date().toISOString()}`,
    `Page: ${location.href}`,
    `Browser: ${navigator.userAgent}`,
  ]
    .filter(Boolean)
    .join("\n")
}
