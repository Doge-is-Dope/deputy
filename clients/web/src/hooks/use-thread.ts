import { useMemo } from "react"

import type { RunEvent } from "@/lib/api"
import { useLanguage } from "@/lib/i18n"
import { buildThread, type Thread } from "@/lib/thread"

// Each list of events built once for every part of the page that shows it (a run's conversation and the live view
// read the same stream's list), in the language it was built in.
const built = new WeakMap<RunEvent[], { locale: string; thread: Thread }>()

function threadOf(events: RunEvent[], locale: string) {
  let entry = built.get(events)
  if (entry?.locale !== locale)
    built.set(events, (entry = { locale, thread: buildThread(events) }))
  return entry.thread
}

/** A run's events as the conversation shows them: built in the interface's language, so built again when that changes. */
export function useThread(events: RunEvent[]) {
  const { locale } = useLanguage()
  return useMemo(() => threadOf(events, locale), [events, locale])
}
