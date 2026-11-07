// Marking a search's matches; the finding is the runtime's (GET /api/search), by name and by what was said.

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
