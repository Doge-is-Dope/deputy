import { useEffect, useState } from "react"

import { api, type SearchHit } from "@/lib/api"

// Asked once typing pauses this long: between Codex's 100 ms and Claude's 500 ms.
const PAUSE = 150

/** The conversations whose words hold the query, from the runtime; none for no query or when it cannot answer. Until
 * its answer for this query comes, the last answer's hits whose snippets hold this query too, so the list narrows as
 * the user types on rather than emptying at each key and filling again; null when none do. */
export function useSearch(query: string): SearchHit[] | null {
  const words = query.trim()
  const [answer, setAnswer] = useState<{ words: string; hits: SearchHit[] }>({
    words: "",
    hits: [],
  })

  useEffect(() => {
    if (!words) return
    const abort = new AbortController()
    const timer = setTimeout(() => {
      api
        .search(words, abort.signal)
        .catch(() => (abort.signal.aborted ? null : []))
        .then((hits) => hits && setAnswer({ words, hits }))
    }, PAUSE)
    return () => {
      clearTimeout(timer)
      abort.abort()
    }
  }, [words])

  if (!words) return []
  if (answer.words === words) return answer.hits
  const lower = words.toLocaleLowerCase()
  const kept = answer.hits.filter((hit) =>
    hit.snippet.toLocaleLowerCase().includes(lower)
  )
  return kept.length > 0 ? kept : null
}
