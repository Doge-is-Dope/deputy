import { useSyncExternalStore, type CSSProperties } from "react"

import {
  DEFAULT_THEME,
  PRESETS,
  type Preset,
  type Seed,
  type Variant,
} from "@/lib/themes"

// How the app looks: light or dark, the system's unless one was chosen, and a theme for each of the
// two. A theme is three colors (lib/themes.ts) and the one it started from; the colors can
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

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

export function useAppearance() {
  return useSyncExternalStore(subscribe, () => state)
}
