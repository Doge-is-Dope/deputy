// The panel beside the conversation: the computer's live view and a tab for each attachment opened from the
// conversation. Held outside React, as drafts are, so an attachment opens from wherever it is shown.

import { useLayoutEffect } from "react"

import type { Markup } from "@/lib/markup"
import { store } from "@/lib/store"

/** Where an opened attachment comes from: a message's, kept with its run; or a tile in a composer's draft, whose
 * upload may change (a marked-up copy in its place). */
export type Source =
  | { kind: "sent"; run: string; file: string; name: string }
  | { kind: "draft"; draft: string; key: string; name: string }

/** The small copy of a picture the conversation already shows, to stand in for it while the file comes. */
export type Thumb = { src: string; width: number; height: number }

/** An opened attachment: its markup while it is being marked up, null while it is only shown. */
export type FileTab = {
  key: string
  source: Source
  markup: Markup | null
  thumb: Thumb | null
  writing: boolean // a comment's words typed and not yet kept
}

export const COMPUTER = "computer"

export type Panel = {
  open: boolean
  tab: string // COMPUTER or a file tab's key
  draft: string | null // the conversation whose tab is selected
  otherTabs: Record<string, string>
  files: FileTab[] // in the order they were opened, as their tabs are
  // Asked before what was drawn is thrown away: closing its tab, or leaving its markup.
  confirm: { key: string; then: "close" | "leave" } | null
  // The composer tile each message's picture went into, marked up, by the picture's tab: marked up again, it is that
  // tile, with what was drawn and written on it, not another copy.
  copies: Record<string, string>
}

export const CLOSED: Panel = {
  open: false,
  tab: COMPUTER,
  draft: null,
  otherTabs: {},
  files: [],
  confirm: null,
  copies: {},
}

export const keyOf = (source: Source) =>
  source.kind === "sent"
    ? `sent:${source.run}/${source.file}`
    : `draft:${source.key}`

/** Whether a tab holds anything that would be lost by closing it: a change since its markup began (comments it
 * began with are in the draft already), or a comment's words still being typed. */
export const unsaved = (file: FileTab) =>
  (file.markup?.past.length ?? 0) > 0 || file.writing

/** Opened: a tab that is open already is only shown again; a new one goes at the end. */
export function opened(
  panel: Panel,
  source: Source,
  thumb: Thumb | null = null
): Panel {
  const key = keyOf(source)
  const files = panel.files.some((each) => each.key === key)
    ? panel.files
    : [...panel.files, { key, source, markup: null, thumb, writing: false }]
  return { ...panel, open: true, tab: key, files }
}

/** The tab to show once `key` is gone: the one to its right among those `shown`, else its left, else the computer. */
function neighbour(panel: Panel, key: string, shown: readonly string[]) {
  if (panel.tab !== key) return panel.tab
  const at = shown.indexOf(key)
  if (at < 0) return COMPUTER
  return shown[at + 1] ?? shown[at - 1] ?? COMPUTER
}

/** Its tab taken away at once, what was drawn on it too. */
export function removed(
  panel: Panel,
  key: string,
  shown: readonly string[]
): Panel {
  return {
    ...panel,
    tab: neighbour(panel, key, shown),
    files: panel.files.filter((each) => each.key !== key),
    confirm: panel.confirm?.key === key ? null : panel.confirm,
  }
}

/** Its tab closed by the user: asked first when it holds markup. `shown` are the file tabs in view, in order. */
export function closedFile(panel: Panel, key: string, shown: string[]): Panel {
  const file = panel.files.find((each) => each.key === key)
  if (!file) return panel
  if (unsaved(file)) return { ...panel, confirm: { key, then: "close" } }
  return removed(panel, key, shown)
}

/** Its markup changed, or begun (an empty one), or left (null). */
export function marked(panel: Panel, key: string, markup: Markup | null) {
  return {
    ...panel,
    files: panel.files.map((each) =>
      each.key === key ? { ...each, markup } : each
    ),
  }
}

/** Leaving its markup: asked first when something is drawn. */
export function left(panel: Panel, key: string): Panel {
  const file = panel.files.find((each) => each.key === key)
  if (!file) return panel
  if (unsaved(file)) return { ...panel, confirm: { key, then: "leave" } }
  return marked(panel, key, null)
}

/** The answer to `confirm`: thrown away, and the tab closed or its markup left; or kept as it was. */
export function answered(panel: Panel, discard: boolean, shown: string[]) {
  const asked = panel.confirm
  if (!asked) return panel
  const cleared = { ...panel, confirm: null }
  if (!discard) return cleared
  return asked.then === "close"
    ? removed(cleared, asked.key, shown)
    : marked(cleared, asked.key, null)
}

/** The tabs a conversation shows: its messages' attachments and its own draft's; another's stay, out of sight. */
export function shownFiles(
  panel: Panel,
  runs: readonly string[],
  draft: string
) {
  return panel.files.filter(({ source }) =>
    source.kind === "sent" ? runs.includes(source.run) : source.draft === draft
  )
}

/** The tab in view: the chosen one where it is shown, else the computer. */
export function shownTab(panel: Panel, shown: FileTab[], draft = panel.draft) {
  const tab =
    draft === null || draft === panel.draft ? panel.tab : panel.otherTabs[draft]
  return shown.some((each) => each.key === tab) ? tab : COMPUTER
}

/** Keep the selected tab with its conversation, just as its files and draft stay there. */
export function switched(panel: Panel, draft: string): Panel {
  if (panel.draft === draft) return panel
  const otherTabs = { ...panel.otherTabs }
  const tab = otherTabs[draft] ?? COMPUTER
  delete otherTabs[draft]
  if (panel.draft !== null) otherTabs[panel.draft] = panel.tab
  return { ...panel, draft, tab, otherTabs, confirm: null }
}

const panel = store<Panel>(CLOSED)

export const usePanel = panel.use
export const getPanel = panel.get

const change = (next: (panel: Panel) => Panel) => panel.set(next(panel.get()))

export function usePanelDraft(draft: string) {
  useLayoutEffect(() => {
    change((each) => switched(each, draft))
  }, [draft])
}

export const openFile = (source: Source, thumb?: Thumb) =>
  change((each) => opened(each, source, thumb))
export const setPanelOpen = (open: boolean) =>
  change((each) => ({ ...each, open }))
export const selectTab = (tab: string) => change((each) => ({ ...each, tab }))
/** The computer's tab, with the panel open: where the desktop is taken over and its steps approved. */
export const showComputer = (draft?: string) =>
  change((each) =>
    draft === undefined || draft === each.draft
      ? { ...each, open: true, tab: COMPUTER }
      : { ...each, open: true, otherTabs: { ...each.otherTabs, [draft]: COMPUTER } }
  )
export const closeFile = (key: string, shown: string[]) =>
  change((each) => closedFile(each, key, shown))
export const setMarkup = (key: string, markup: Markup | null) =>
  change((each) => marked(each, key, markup))
export const leaveMarkup = (key: string) => change((each) => left(each, key))
/** A tile's tab once its file is another (its marked-up copy): named as the tile now is, as its download is. */
export const renameTab = (key: string, name: string) =>
  change((each) => ({
    ...each,
    files: each.files.map((tab) =>
      tab.key === key ? { ...tab, source: { ...tab.source, name } } : tab
    ),
  }))
export const copyOf = (key: string) => panel.get().copies[key]
export const keepCopy = (key: string, tile: string) =>
  change((each) => ({ ...each, copies: { ...each.copies, [key]: tile } }))
export function setWriting(key: string, writing: boolean) {
  const file = panel.get().files.find((each) => each.key === key)
  if (file && file.writing !== writing)
    change((each) => ({
      ...each,
      files: each.files.map((tab) =>
        tab.key === key ? { ...tab, writing } : tab
      ),
    }))
}
export const answer = (discard: boolean, shown: string[]) =>
  change((each) => answered(each, discard, shown))

/** The tab of a tile among `keys` that holds marks not yet put on it (完成), for a message about to go with them. */
export function markedTile(keys: readonly string[]): string | null {
  const file = panel
    .get()
    .files.find(
      (each) =>
        each.source.kind === "draft" &&
        keys.includes(each.source.key) &&
        unsaved(each)
    )
  return file?.key ?? null
}

/** Tabs taken away together: the chosen one gives way to its nearest neighbour among those `shown` that stay. */
export function forgotten(
  panel: Panel,
  gone: ReadonlySet<string>,
  shown: readonly string[]
) {
  return [...gone].reduce(
    (each, key) =>
      removed(
        each,
        key,
        shown.filter((other) => other === key || !gone.has(other))
      ),
    panel
  )
}

// The file tabs the page shows now, in order (SidePanel keeps it): where a tab taken away from under it, as its tile is
// sent or removed from the composer, finds its neighbour. Not other conversations' tabs, which are out of sight.
let inView: readonly string[] = []
export const showing = (keys: readonly string[]) => {
  inView = keys
}

/** Tiles taken off a draft or sent with its message: their tabs go, without asking (the user acted on the file).
 * Sent, so do the tabs of the messages' pictures they were marked-up copies of; and sent from under the tab in view,
 * the panel closes, back to the conversation rather than on to another tab. */
export function tilesGone(
  panel: Panel,
  tiles: ReadonlySet<string>,
  sent: boolean,
  shown: readonly string[]
) {
  const gone = new Set([...tiles].map((key) => `draft:${key}`))
  if (sent)
    for (const [tab, tile] of Object.entries(panel.copies))
      if (tiles.has(tile)) gone.add(tab)
  if (!panel.files.some((each) => gone.has(each.key))) return panel
  const after = forgotten(panel, gone, shown)
  return sent && gone.has(panel.tab) ? { ...after, open: false } : after
}

export function forgetTiles(keys: Iterable<string>, sent = false) {
  const current = panel.get()
  const next = tilesGone(current, new Set(keys), sent, inView)
  if (next !== current) panel.set(next)
}
