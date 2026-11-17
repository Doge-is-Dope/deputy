import { useState } from "react"

import type { Conversation } from "@/lib/api"
import { nameOf } from "@/lib/conversations"

/** A conversation's name edited in place, in its sidebar row or the header: `draft` is the field's text while it is
 * open; Enter or blur saves a changed, nonempty name, Escape cancels. */
export function useRename(
  conversation: Conversation,
  onRename: (id: string, title: string) => Promise<{ title: string } | null>
) {
  const [draft, setDraft] = useState<string | null>(null)
  // The new name shows until the list has it, or the rename fails.
  const [given, setGiven] = useState<string | null>(null)
  if (given !== null && conversation.title === given) setGiven(null)
  // Null while the conversation has no name yet.
  const title = given ?? conversation.title
  // Each one remounts the name, skipping its roll-in (ConversationName).
  const [renames, setRenames] = useState(0)
  const commit = () => {
    if (draft === null) return
    const next = draft.trim()
    setDraft(null)
    if (!next || next === (title ?? nameOf(conversation))) return
    setGiven(next)
    setRenames((count) => count + 1)
    // As the runtime saved it: spaces collapsed, length capped.
    void onRename(conversation.id, next).then((renamed) =>
      setGiven(renamed?.title ?? null)
    )
  }
  return {
    draft,
    setDraft,
    title,
    renames,
    start: () => setDraft(title ?? nameOf(conversation)),
    cancel: () => setDraft(null),
    commit,
  }
}
