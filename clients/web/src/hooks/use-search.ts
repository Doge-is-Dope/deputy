import { useEffect, useState } from "react"

import { api, type SearchHit } from "@/lib/api"
import { nameOf } from "@/lib/conversations"

// Asked once typing pauses this long.
const PAUSE = 150

/** Searches all of the user's conversations by title and content. While waiting, keeps previous hits
 * that still match to avoid flicker; returns null if none remain. Empty queries and failures return []. */
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
  const kept = answer.hits.filter(
    (hit) =>
      hit.snippet?.toLocaleLowerCase().includes(lower) ||
      nameOf(hit.conversation).toLocaleLowerCase().includes(lower)
  )
  return kept.length > 0 ? kept : null
}
