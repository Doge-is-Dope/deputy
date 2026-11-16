// Marking a search's matches; the finding is the runtime's (GET /api/search), by name and by what was said.

import type { Conversation, SearchHit } from "@/lib/api"
import { nameOf } from "@/lib/conversations"

const pattern = (query: string) =>
  new RegExp(`(${query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "iu")

/** The text in pieces, each match of the query marked, ignoring case. */
export function marked(text: string, query: string) {
  const words = query.trim()
  if (!words) return [{ text, match: false }]
  return text
    .split(pattern(words))
    .map((piece, n) => ({ text: piece, match: n % 2 === 1 }))
    .filter((piece) => piece.text)
}

/** What a search is sure to find, shown until the runtime's answer is in: the loaded conversations named so, and an
 * earlier answer's hits that still match, by name or in their snippet. Latest first, as the answer is, so its rows
 * stay where they are and the answer only adds to them. */
export function sureHits(
  query: string,
  conversations: Conversation[],
  earlier: SearchHit[]
): SearchHit[] {
  const words = query.trim().toLocaleLowerCase()
  const has = (text: string | null) =>
    text !== null && text.toLocaleLowerCase().includes(words)
  const sure = new Map<string, SearchHit>()
  for (const conversation of conversations)
    if (has(nameOf(conversation)))
      sure.set(conversation.id, { conversation, snippet: null })
  for (const hit of earlier)
    if (has(hit.snippet)) sure.set(hit.conversation.id, hit)
    else if (has(nameOf(hit.conversation)))
      sure.set(hit.conversation.id, { ...hit, snippet: null })
  return [...sure.values()].sort(
    (a, b) => b.conversation.last - a.conversation.last
  )
}
