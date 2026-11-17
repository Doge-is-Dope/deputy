import { useMemo } from "react"

import type { RunEvent } from "@/lib/api"
import { useLanguage } from "@/lib/i18n"
import { buildThread } from "@/lib/thread"

/** A run's events as the conversation shows them: built in the interface's language, so built again when that changes. */
export function useThread(events: RunEvent[]) {
  const { locale } = useLanguage()
  // The locale is read by the build through its strings, not passed in.
  return useMemo(() => buildThread(events), [events, locale])
}
