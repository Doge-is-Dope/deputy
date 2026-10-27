// Shortcuts as the keyboard has them: ⌘ on a Mac, Ctrl elsewhere.
export const MAC = /Mac|iPhone|iPad/.test(navigator.platform)

/** A shortcut with ⌘ (Ctrl off a Mac): its key, and whether ⇧ goes with it. */
export type Shortcut = { key: string; shift?: boolean }

/** As its keys read, a space between them, in the order a Mac's menus show them: "⌘ B", "⇧ ⌘ O", "Ctrl Shift O". */
export function shortcutLabel({ key, shift }: Shortcut) {
  const name = key.toUpperCase()
  if (MAC) return shift ? `⇧ ⌘ ${name}` : `⌘ ${name}`
  return shift ? `Ctrl Shift ${name}` : `Ctrl ${name}`
}

/** As aria-keyshortcuts names it: "Meta+Shift+O". */
export const shortcutAria = ({ key, shift }: Shortcut) =>
  [MAC ? "Meta" : "Control", shift && "Shift", key.toUpperCase()]
    .filter(Boolean)
    .join("+")

/** Whether a key press is the shortcut, and no other: ⌘ (Ctrl off a Mac), ⇧ only if it goes with it, no ⌥. */
export const isShortcut = (
  event: KeyboardEvent,
  { key, shift = false }: Shortcut
) =>
  (MAC ? event.metaKey : event.ctrlKey) &&
  !event.altKey &&
  event.shiftKey === shift &&
  event.key.toLowerCase() === key.toLowerCase()

/** A key that works an input method's composition (Chinese input), left to it. Safari reports the Enter that confirms
 * one with isComposing already false, but keyCode 229. */
export const isComposing = (event: KeyboardEvent) =>
  event.isComposing || event.keyCode === 229
