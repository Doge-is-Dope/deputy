// The themes to choose from, as the ChatGPT desktop app lists them (its 29, read from its app.asar on 2026-10-23), each
// as the three colors it takes from its editor theme: the background (surface), the text (ink) and the accent, for
// the modes it has. Every other color is worked out from these three (index.css). The default is ChatGPT's own;
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
  {
    id: "default",
    name: null,
    light: seed("#ffffff", "#0d0d0d", "#0169cc"),
    dark: seed("#111111", "#fcfcfc", "#0169cc"),
  },
  {
    id: "absolutely",
    name: "Absolutely",
    light: seed("#f9f9f7", "#2d2d2b", "#cc7d5e"),
    dark: seed("#2d2d2b", "#f9f9f7", "#cc7d5e"),
  },
  { id: "ayu", name: "Ayu", dark: seed("#10141c", "#bfbdb6", "#e6b450") },
  {
    id: "catppuccin",
    name: "Catppuccin",
    light: seed("#eff1f5", "#4c4f69", "#8839ef"),
    dark: seed("#1e1e2e", "#cdd6f4", "#cba6f7"),
  },
  {
    id: "dracula",
    name: "Dracula",
    dark: seed("#282a36", "#f8f8f2", "#ff79c6"),
  },
  {
    id: "everforest",
    name: "Everforest",
    light: seed("#fdf6e3", "#5c6a72", "#93b259"),
    dark: seed("#2d353b", "#d3c6aa", "#a7c080"),
  },
  {
    id: "github",
    name: "GitHub",
    light: seed("#ffffff", "#1f2328", "#0969da"),
    dark: seed("#0d1117", "#e6edf3", "#1f6feb"),
  },
  {
    id: "gruvbox",
    name: "Gruvbox",
    light: seed("#fbf1c7", "#3c3836", "#458588"),
    dark: seed("#282828", "#ebdbb2", "#458588"),
  },
  {
    id: "linear",
    name: "Linear",
    light: seed("#fcfcfd", "#1b1b1b", "#5e6ad2"),
    dark: seed("#0f0f11", "#e3e4e6", "#606acc"),
  },
  {
    id: "lobster",
    name: "Lobster",
    dark: seed("#111827", "#e4e4e7", "#ff5c5c"),
  },
  {
    id: "material",
    name: "Material",
    dark: seed("#212121", "#eeffff", "#80cbc4"),
  },
  { id: "matrix", name: "Matrix", dark: seed("#040805", "#b8ffca", "#1eff5a") },
  {
    id: "monokai",
    name: "Monokai",
    dark: seed("#272822", "#f8f8f2", "#99947c"),
  },
  {
    id: "night-owl",
    name: "Night Owl",
    dark: seed("#011627", "#d6deeb", "#44596b"),
  },
  { id: "nord", name: "Nord", dark: seed("#2e3440", "#d8dee9", "#88c0d0") },
  {
    id: "notion",
    name: "Notion",
    light: seed("#ffffff", "#37352f", "#3183d8"),
    dark: seed("#191919", "#d9d9d8", "#3183d8"),
  },
  { id: "og", name: "OG", dark: seed("#343541", "#d1d5db", "#10a37f") },
  {
    id: "one",
    name: "One",
    light: seed("#fafafa", "#383a42", "#526fff"),
    dark: seed("#282c34", "#abb2bf", "#4d78cc"),
  },
  {
    id: "oscurange",
    name: "Oscurange",
    dark: seed("#0b0b0f", "#e6e6e6", "#f9b98c"),
  },
  { id: "proof", name: "Proof", light: seed("#f5f3ed", "#2f312d", "#3d755d") },
  {
    id: "raycast",
    name: "Raycast",
    light: seed("#ffffff", "#030303", "#ff6363"),
    dark: seed("#101010", "#fefefe", "#ff6363"),
  },
  {
    id: "rose-pine",
    name: "Rose Pine",
    light: seed("#faf4ed", "#575279", "#d7827e"),
    dark: seed("#232136", "#e0def4", "#ea9a97"),
  },
  { id: "sentry", name: "Sentry", dark: seed("#2d2935", "#e6dff9", "#7055f6") },
  {
    id: "solarized",
    name: "Solarized",
    light: seed("#fdf6e3", "#657b83", "#b58900"),
    dark: seed("#002b36", "#839496", "#d30102"),
  },
  { id: "temple", name: "Temple", dark: seed("#02120c", "#c7e6da", "#e4f222") },
  {
    id: "tokyo-night",
    name: "Tokyo Night",
    dark: seed("#1a1b26", "#a9b1d6", "#3d59a1"),
  },
  {
    id: "vercel",
    name: "Vercel",
    light: seed("#ffffff", "#171717", "#006aff"),
    dark: seed("#000000", "#ededed", "#006efe"),
  },
  {
    id: "vscode-plus",
    name: "VS Code Plus",
    light: seed("#ffffff", "#000000", "#007acc"),
    dark: seed("#1e1e1e", "#d4d4d4", "#007acc"),
  },
  {
    id: "xcode",
    name: "Xcode",
    light: seed("#ffffff", "#000000", "#0e0eff"),
    dark: seed("#1f1f24", "#ffffff", "#5482ff"),
  },
]

export const DEFAULT_THEME = PRESETS[0]
