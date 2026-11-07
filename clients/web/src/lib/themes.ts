// The themes to choose from, each
// as the three colors it takes from its editor theme: the background (surface), the text (ink) and the accent, for
// the modes it has. Every other color is worked out from these three (index.css). The default is the first;
// index.css and index.html start from its colors too.

export type Variant = "light" | "dark"

export type Seed = { surface: string; ink: string; accent: string }

export type Preset = { id: string; name: string | null } & Partial<
  Record<Variant, Seed>
>

const seed = (surface: string, ink: string, accent: string): Seed => ({
  surface,
  ink,
  accent,
})

export const PRESETS: Preset[] = [
  // The text's color for the accent too: the send button, the user's message and the focus all in ink and its greys.
  // An off-white page in light, so what floats on it (menus, the composer) is the whiter.
  {
    id: "default",
    name: null,
    light: seed("#fcfcfc", "#0d0d0d", "#0d0d0d"),
    dark: seed("#111111", "#fcfcfc", "#fcfcfc"),
  },
  {
    id: "absolutely",
    name: "Absolutely",
    light: seed("#f9f9f7", "#2d2d2b", "#cc7d5e"),
    dark: seed("#2d2d2b", "#f9f9f7", "#cc7d5e"),
  },
  {
    id: "chatgpt",
    name: "ChatGPT",
    light: seed("#ffffff", "#0d0d0d", "#0169cc"),
    dark: seed("#111111", "#fcfcfc", "#0169cc"),
  },
  {
    id: "linear",
    name: "Linear",
    light: seed("#fcfcfd", "#1b1b1b", "#5e6ad2"),
    dark: seed("#0f0f11", "#e3e4e6", "#606acc"),
  },
  { id: "nord", name: "Nord", dark: seed("#2e3440", "#d8dee9", "#88c0d0") },
  // Our own, for long reading: graphite ink on barely warm paper, softer than black on white (about 12:1 either way).
  {
    id: "paper",
    name: "Paper",
    light: seed("#f8f7f3", "#2d2b28", "#7a6a5c"),
    dark: seed("#1d1d1c", "#dad8d3", "#b8a894"),
  },
]

export const DEFAULT_THEME = PRESETS[0]
