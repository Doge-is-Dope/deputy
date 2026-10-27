// Finding conversations: by name here, from the list the page already has, and by what was said in them from the
// runtime (GET /api/search), merged as Claude's Code tab merges its two.

import type { SearchHit } from "@/lib/api"
import { nameOf, type Conversation } from "@/lib/conversations"

/** A conversation a search found: by its name, or by its words with the snippet around the match. */
export type Found = { conversation: Conversation; snippet?: string }

const pattern = (query: string) =>
  new RegExp(`(${query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "iu")

/** Those named by the query first, then those only their words hold, in the order the runtime found them. While the
 * runtime's answer is on its way (`hits` null) the named ones alone. */
export function found(
  conversations: Conversation[],
  query: string,
  hits: SearchHit[] | null
): Found[] {
  const words = query.trim()
  if (!words) return conversations.map((conversation) => ({ conversation }))
  // By name here; by what was said, the runtime.
  const inName = pattern(words)
  const byName = conversations.filter((conversation) =>
    inName.test(nameOf(conversation))
  )
  const named = new Set(byName)
  const byId = new Map(conversations.map((each) => [each.id, each]))
  const byWords = (hits ?? []).flatMap(({ thread, snippet }) => {
    const conversation = byId.get(thread)
    return conversation && !named.has(conversation)
      ? [{ conversation, snippet }]
      : []
  })
  return [...byName.map((conversation) => ({ conversation })), ...byWords]
}

/** The text in pieces, each match of the query marked, ignoring case. */
export function marked(text: string, query: string) {
  const words = query.trim()
  if (!words) return [{ text, match: false }]
  return text
    .split(pattern(words))
    .map((piece, n) => ({ text: piece, match: n % 2 === 1 }))
    .filter((piece) => piece.text)
}
