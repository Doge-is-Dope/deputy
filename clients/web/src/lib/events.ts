import type { RunEvent } from "@/lib/api"

export type EventBatchItem =
  { event: RunEvent } | { draft: string; whole: boolean; final?: boolean }
export type EventState = {
  events: RunEvent[]
  draft: string
  final: boolean // the draft is the main agent's final reply, as its model said from its start
  streamed: ReadonlySet<number>
}

/** Apply one frame of stream data; a persisted reply replaces the transient draft. */
export function applyEventBatch(
  current: EventState,
  batch: EventBatchItem[]
): EventState {
  // Copied only once an event comes: a frame of the reply alone keeps the same list, and the thread built from it.
  let { events, draft, final, streamed } = current
  for (const item of batch) {
    if ("draft" in item) {
      draft = item.whole ? item.draft : draft + item.draft
      if (item.whole) final = item.final ?? false
      continue
    }
    const { event } = item
    if (
      (event.type === "model" && event.agent === "main") ||
      event.type === "end"
    ) {
      if (draft && event.type === "model")
        streamed = new Set(streamed).add(events.length)
      draft = ""
      final = false
    }
    if (events === current.events) events = [...events]
    events.push(event)
  }
  return { events, draft, final, streamed }
}

/**
 * Reads the server-sent events of a response (server.py's: an id and a line of data each, a "done" event at the end and
 * comments that keep the connection open), handing on each event and its id. The reply the main agent is writing comes
 * between them, without an id: all of it so far, and whether it is the final reply ("draft"), then what it adds
 * ("delta"). True once "done" arrives;
 * false if the stream ends before it.
 */
export async function readEvents(
  body: ReadableStream<Uint8Array>,
  onEvent: (data: string, id: string) => void,
  onDraft: (text: string, whole: boolean, final: boolean) => void
): Promise<boolean> {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ""
  for (;;) {
    const { value, done } = await reader.read()
    if (done) return false
    buffer += decoder.decode(value, { stream: true })
    let end
    while ((end = buffer.indexOf("\n\n")) >= 0) {
      const fields: Record<string, string> = {}
      for (const line of buffer.slice(0, end).split("\n")) {
        const colon = line.indexOf(":")
        if (colon > 0)
          fields[line.slice(0, colon)] = line.slice(colon + 1).trimStart()
      }
      buffer = buffer.slice(end + 2)
      const data = fields.data ? JSON.parse(fields.data) : {}
      if (fields.event === "done") return true
      if (fields.event === "draft" || fields.event === "delta")
        onDraft(data.text, fields.event === "draft", data.final === true)
      else if (fields.data) onEvent(fields.data, fields.id ?? "")
    }
  }
}
