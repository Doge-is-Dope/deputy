import { useEffect, useState } from "react"

import { api, type Conversation, type SearchHit } from "@/lib/api"
import { sureHits } from "@/lib/search"

// Asked once typing pauses this long.
const PAUSE = 150

/** The runtime's answer to a query, as far as its pages have been read. */
type Answer = {
  words: string
  hits: SearchHit[]
  next: string | null // the next page's cursor; null on the last
  added: number // how many of the hits came with the latest page after the first
}
const NONE: Answer = { words: "", hits: [], next: null, added: 0 }

/** Searches all of the user's conversations by title and content, a page at a time.
 * `hits`: until the answer is in, those sure to be in it (sureHits), or the last answer while the query only grows,
 * so the list neither empties nor loses rows it gets back; null if there are none. Empty queries and failures give [].
 * `more` reads the next page, where there is one; `reading` while it does. `added` is how many of the last hits
 * came with that page, for their entrance. */
export function useSearch(
  query: string,
  conversations: Conversation[] // those loaded, matched by name meanwhile
) {
  const words = query.trim()
  const [answer, setAnswer] = useState(NONE)
  const [reading, setReading] = useState(false)

  useEffect(() => {
    if (!words) return
    const abort = new AbortController()
    const timer = setTimeout(() => {
      api
        .search(words, null, abort.signal)
        .catch(() => (abort.signal.aborted ? null : { items: [], next: null }))
        .then(
          (page) =>
            page &&
            setAnswer({ words, hits: page.items, next: page.next, added: 0 })
        )
    }, PAUSE)
    return () => {
      clearTimeout(timer)
      abort.abort()
    }
  }, [words])

  const answered = answer.words === words
  const more =
    answered && answer.next !== null && !reading
      ? () => {
          setReading(true)
          void api
            .search(words, answer.next)
            .catch(() => ({ items: [], next: null })) // a page that fails ends the list
            .then((page) => {
              setReading(false)
              // Not if the query moved on meanwhile.
              setAnswer((now) =>
                now === answer
                  ? {
                      words,
                      hits: [...answer.hits, ...page.items],
                      next: page.next,
                      added: page.items.length,
                    }
                  : now
              )
            })
        }
      : null

  if (!words) return { hits: [], more: null, reading: false, added: 0 }
  if (answered) return { hits: answer.hits, more, reading, added: answer.added }
  // Typed further: the last answer holds all the next one can, so it stays until that one is in, rather than losing
  // rows it cannot tell still match (a snippet shows one match only) and getting them back.
  const further =
    answer.words !== "" &&
    words.toLocaleLowerCase().startsWith(answer.words.toLocaleLowerCase())
  const sure = further
    ? answer.hits
    : sureHits(words, conversations, answer.hits)
  return {
    hits: sure.length > 0 ? sure : null,
    more: null,
    reading: false,
    added: 0,
  }
}
