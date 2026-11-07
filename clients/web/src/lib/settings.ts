import { store } from "@/lib/store"

// Where the settings open, when a line in the conversation opens them: a page, the item on it to show, and whether
// to edit it. The settings dialog lives in the sidebar, the lines in the conversation: this store is between them.
export type OpenedSettings = {
  open: boolean
  page: string | null
  item: string | null
  editing: boolean
}
const settings = store<OpenedSettings>({
  open: false,
  page: null,
  item: null,
  editing: false,
})

/** Opens the settings at a page (the last one seen without), and at an item of it, from anywhere on the page. */
export function openSettings(
  page: string | null = null,
  item: string | null = null,
  editing = false
) {
  settings.set({ open: true, page, item, editing })
}

export function closeSettings() {
  settings.set({ ...settings.get(), open: false })
}

export const useOpenedSettings = settings.use
