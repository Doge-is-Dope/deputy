import { useSyncExternalStore } from "react"

import { store } from "@/lib/store"

const KEY = "drafts"
/** Whose draft a new task's is, before it has a conversation. */
export const NEW_TASK = "new"

/**
 * What was written in each conversation's composer and not sent yet, by conversation (NEW_TASK for a new task): kept
 * for this tab, so switching conversations or reloading the page leaves each where it was. Storage that fails (private
 * mode) keeps them for the visit. Held outside React, so a keystroke draws only the composer again, not the page.
 */
const drafts = store<Record<string, string>>(
  (() => {
    try {
      const stored = JSON.parse(sessionStorage.getItem(KEY) ?? "{}")
      return stored && typeof stored === "object" ? stored : {}
    } catch {
      return {}
    }
  })()
)

export function setDraft(
  conversation: string,
  text: string,
  expected?: string
) {
  const current = drafts.get()
  if (expected !== undefined && current[conversation] !== expected) return
  const next = { ...current }
  if (text) next[conversation] = text
  else delete next[conversation]
  try {
    sessionStorage.setItem(KEY, JSON.stringify(next))
  } catch {
    // Not stored; the drafts still hold until the page reloads.
  }
  drafts.set(next)
}

/** What is written in `conversation`'s composer now. */
export const draftOf = (conversation: string) =>
  drafts.get()[conversation] ?? ""

/** What is written in `conversation`'s composer, changed by `change`: a picture's comments added or relabelled. */
export function editDraft(
  conversation: string,
  change: (text: string) => string
) {
  const current = draftOf(conversation)
  const next = change(current)
  if (next !== current) setDraft(conversation, next)
}

export function useDraft(conversation: string) {
  return useSyncExternalStore(drafts.subscribe, () => draftOf(conversation))
}
