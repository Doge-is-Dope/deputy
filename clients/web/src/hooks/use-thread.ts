import { useMemo } from "react"

import type { RunEvent } from "@/lib/api"
import { useT } from "@/lib/i18n"
import { buildThread } from "@/lib/thread"

/** A run's events as the conversation shows them: built in the interface's language, so built again when that changes. */
export function useThread(events: RunEvent[]) {
  const messages = useT()
  return useMemo(() => buildThread(events, messages), [events, messages])
}
