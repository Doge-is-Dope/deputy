import { useSyncExternalStore, type CSSProperties } from "react"

import {
  DEFAULT_THEME,
  PRESETS,
  type Preset,
  type Seed,
  type Variant,
} from "@/lib/themes"

// How the app looks: light or dark, the system's unless one was chosen, and a theme for each of the two, as the
// ChatGPT desktop app keeps them. A theme is three colors (lib/themes.ts) and the one it started from; the colors can
// be changed one by one, and the theme stays named as it was. All of it is kept in this browser. It ends up on <html>:
// the mode as data-mode, the mode's three colors as --theme-surface, --theme-ink and --theme-accent, which index.css
// works every other color out from. index.html sets them once before the first paint, so the page never flashes other
// colors; from then on they are kept here.

export type Mode = "system" | "light" | "dark"

export type { Seed, Variant }

/** A mode's theme: the colors it has now, and the theme they started from. */
export type ThemeChoice = Seed & { id: string }

export type ColorRole = keyof Seed

const HEX = /^#[0-9a-f]{6}$/

const systemDark = matchMedia("(prefers-color-scheme: dark)")
const listeners = new Set<() => void>()

const defaultChoice = (variant: Variant): ThemeChoice => ({
  id: DEFAULT_THEME.id,
  ...DEFAULT_THEME[variant]!,
})

const isChoice = (value: unknown): value is ThemeChoice => {
  const choice = value as ThemeChoice | null
  return (
    typeof choice?.id === "string" &&
    [choice.surface, choice.ink, choice.accent].every(
      (color) => typeof color === "string" && HEX.test(color)
    )
  )
}

function read(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

function write(key: string, value: string | null) {
  try {
    if (value === null) localStorage.removeItem(key)
    else localStorage.setItem(key, value)
  } catch {
    // Not stored; the choice still holds until the page reloads.
  }
}

function storedTheme(variant: Variant): ThemeChoice {
  try {
    const value = JSON.parse(read(`theme-${variant}`) ?? "null")
    if (isChoice(value)) return value
  } catch {
    // Not a theme: the default stands.
  }
  return defaultChoice(variant)
}

/** The choices, and the mode they come to: the system's while the mode is "system". */
let state: {
  mode: Mode
  resolved: Variant
  themes: Record<Variant, ThemeChoice>
}

function load() {
  const mode = read("mode")
  apply(mode === "light" || mode === "dark" ? mode : "system", {
    light: storedTheme("light"),
    dark: storedTheme("dark"),
  })
}

function apply(mode: Mode, themes: Record<Variant, ThemeChoice>) {
  const resolved =
    mode === "system" ? (systemDark.matches ? "dark" : "light") : mode
  state = { mode, resolved, themes }
  const root = document.documentElement
  root.dataset.mode = resolved
  for (const [name, value] of Object.entries(seedStyle(themes[resolved])))
    root.style.setProperty(name, value)
  for (const listener of listeners) listener()
}

load()
// The system can switch while the page is open (at sunset, say); it matters only while it is the choice.
systemDark.addEventListener("change", () => apply(state.mode, state.themes))
// A choice made in another tab applies here too.
addEventListener("storage", (event) => {
  if (
    event.key === null ||
    event.key === "mode" ||
    event.key.startsWith("theme-")
  )
    load()
})

/** A theme's three colors as the properties index.css reads, for <html> or a subtree drawn in another theme. */
export function seedStyle(seed: Seed) {
  return {
    "--theme-surface": seed.surface,
    "--theme-ink": seed.ink,
    "--theme-accent": seed.accent,
  } as CSSProperties & Record<string, string>
}

export function setMode(mode: Mode) {
  write("mode", mode === "system" ? null : mode)
  apply(mode, state.themes)
}

function setChoice(variant: Variant, choice: ThemeChoice) {
  const atDefault = isDefault(choice, variant)
  write(`theme-${variant}`, atDefault ? null : JSON.stringify(choice))
  apply(state.mode, { ...state.themes, [variant]: choice })
}

/** Start a mode's theme over from one of the list, which has that mode. */
export function setTheme(variant: Variant, preset: Preset) {
  setChoice(variant, { id: preset.id, ...preset[variant]! })
}

/** Change one of a mode's three colors; the theme keeps its name. */
export function setColor(variant: Variant, role: ColorRole, color: string) {
  const value = color.toLowerCase()
  if (!HEX.test(value)) return
  setChoice(variant, { ...state.themes[variant], [role]: value })
}

function isDefault(choice: ThemeChoice, variant: Variant) {
  const start = defaultChoice(variant)
  return (
    choice.id === start.id &&
    choice.surface === start.surface &&
    choice.ink === start.ink &&
    choice.accent === start.accent
  )
}

/** The themes there are for a mode. */
export const presetsFor = (variant: Variant) =>
  PRESETS.filter((preset) => preset[variant])

// A theme passed around as one line of text, in the ChatGPT desktop app's own format, so one copied there opens here
// and the other way round. It holds more than this app keeps: the rest is filled with that app's defaults for the
// mode, and read back as nothing. Its theme ids are ChatGPT's, the default one's "codex"; it turns down one it doesn't
// list, so a theme here goes out under its own id, or the default's.
const SHARE_PREFIX = "codex-theme-v1:"

const CHATGPT_DEFAULTS = {
  light: {
    contrast: 45,
    semanticColors: {
      diffAdded: "#00a240",
      diffRemoved: "#ba2623",
      skill: "#924ff7",
    },
  },
  dark: {
    contrast: 60,
    semanticColors: {
      diffAdded: "#40c977",
      diffRemoved: "#fa423e",
      skill: "#ad7bf9",
    },
  },
}

export function shareTheme(variant: Variant, choice: ThemeChoice) {
  const { id, surface, ink, accent } = choice
  return (
    SHARE_PREFIX +
    JSON.stringify({
      codeThemeId: id === DEFAULT_THEME.id ? "codex" : id,
      theme: {
        accent,
        accentSource: "custom",
        contrast: CHATGPT_DEFAULTS[variant].contrast,
        fonts: { code: null, ui: null },
        ink,
        opaqueWindows: false,
        semanticColors: CHATGPT_DEFAULTS[variant].semanticColors,
        surface,
      },
      variant,
    })
  )
}

/** The theme a line of text holds, and the mode it is for; null if it holds none. */
export function readTheme(
  text: string
): { variant: Variant; choice: ThemeChoice } | null {
  const line = text.trim()
  if (!line.startsWith(SHARE_PREFIX)) return null
  try {
    const rest = line.slice(SHARE_PREFIX.length)
    const shared = JSON.parse(
      rest.startsWith("{") ? rest : decodeURIComponent(rest)
    )
    const variant = shared?.variant
    if (variant !== "light" && variant !== "dark") return null
    const id =
      PRESETS.find(
        (preset) =>
          preset.id ===
          (shared.codeThemeId === "codex"
            ? DEFAULT_THEME.id
            : shared.codeThemeId)
      )?.id ?? DEFAULT_THEME.id
    const choice = {
      id,
      surface: String(shared.theme?.surface).toLowerCase(),
      ink: String(shared.theme?.ink).toLowerCase(),
      accent: String(shared.theme?.accent).toLowerCase(),
    }
    return isChoice(choice) ? { variant, choice } : null
  } catch {
    return null
  }
}

/** Take a theme from a line of text into the mode it is for. */
export function importTheme(text: string) {
  const shared = readTheme(text)
  if (shared) setChoice(shared.variant, shared.choice)
  return shared
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

export function useAppearance() {
  return useSyncExternalStore(subscribe, () => state)
}
