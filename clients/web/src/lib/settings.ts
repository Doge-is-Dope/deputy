import { store } from "@/lib/store"

// Where the settings open, when a line in the conversation opens them: a page and the item on it to show. The
// settings dialog lives in the sidebar, the lines in the conversation: this store is between them.
type OpenedSettings = {
  open: boolean
  page: string | null
  item: string | null
}
const settings = store<OpenedSettings>({
  open: false,
  page: null,
  item: null,
})

/** Opens the settings at a page (the last one seen without), and at an item of it, from anywhere on the page. */
export function openSettings(
  page: string | null = null,
  item: string | null = null
) {
  settings.set({ open: true, page, item })
}

export function closeSettings() {
  settings.set({ ...settings.get(), open: false })
}

export const useOpenedSettings = settings.use
