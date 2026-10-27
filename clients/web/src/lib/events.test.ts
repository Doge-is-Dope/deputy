import { describe, expect, it } from "vitest"

import type { RunEvent } from "@/lib/api"
import {
  applyEventBatch,
  readEvents,
  type EventBatchItem,
  type EventState,
} from "@/lib/events"

function body(text: string, size = 1): ReadableStream<Uint8Array> {
  const bytes = new TextEncoder().encode(text)
  return new ReadableStream({
    start(controller) {
      for (let offset = 0; offset < bytes.length; offset += size)
        controller.enqueue(bytes.slice(offset, offset + size))
      controller.close()
    },
  })
}

const start: RunEvent = { type: "start", v: 4, goal: "你好", time: 1 }
const reply: RunEvent = {
  type: "model",
  agent: "main",
  text: "Done",
  tool_calls: [],
  time: 2,
}
const end: RunEvent = {
  type: "end",
  stop_reason: "replied",
  summary: "Done",
  usage: { input: 0, cached: 0, cache_write: 0, output: 0, reasoning: 0 },
  cost: null,
  agents: [],
  time: 3,
}
const frame = (event: RunEvent, id: string) =>
  `id: ${id}\ndata: ${JSON.stringify(event)}\n\n`
const draft = (text: string, whole = false) =>
  `event: ${whole ? "draft" : "delta"}\ndata: ${JSON.stringify({ text })}\n\n`
const fresh = (): EventState => ({ events: [], draft: "", streamed: new Set() })

describe("run event stream", () => {
  it("reads complete events and unicode split across arbitrary byte boundaries", async () => {
    const events: { data: RunEvent; id: string }[] = []
    const drafts: { text: string; whole: boolean }[] = []
    const done = await readEvents(
      body(
        `: heartbeat\n\n${frame(start, "0")}${draft("早安", true)}${draft("！")}event: done\ndata: {}\n\n`
      ),
      (data, id) => events.push({ data: JSON.parse(data), id }),
      (text, whole) => drafts.push({ text, whole })
    )
    expect(done).toBe(true)
    expect(events).toEqual([{ data: start, id: "0" }])
    expect(drafts).toEqual([
      { text: "早安", whole: true },
      { text: "！", whole: false },
    ])
  })

  it("retains the last complete event cursor across a dropped stream and replaces its draft on reconnect", async () => {
    let state = fresh()
    let cursor = ""
    const receive = (data: string, id: string) => {
      if (id) cursor = id
      state = applyEventBatch(state, [{ event: JSON.parse(data) }])
    }
    const write = (text: string, whole: boolean) => {
      state = applyEventBatch(state, [{ draft: text, whole }])
    }
    expect(
      await readEvents(
        body(`${frame(start, "0")}${draft("old", true)}id: 1\ndata: {"type":`),
        receive,
        write
      )
    ).toBe(false)
    expect(cursor).toBe("0")
    expect(state.events).toEqual([start])
    // useRunEvents reconnects with Last-Event-ID: 0 and clears the transient draft before replaying its current value.
    write("", true)
    expect(
      await readEvents(
        body(
          `${draft("Done", true)}${frame(reply, "1")}${frame(end, "2")}event: done\n\n`,
          7
        ),
        receive,
        write
      )
    ).toBe(true)
    expect(cursor).toBe("2")
    expect(state.events).toEqual([start, reply, end])
    expect(state.draft).toBe("")
    expect([...state.streamed]).toEqual([1])
  })

  it("preserves event and draft order in a frame and lets a saved reply replace the draft", () => {
    const batch: EventBatchItem[] = [
      { event: start },
      { draft: "Do", whole: true },
      { draft: "ne", whole: false },
      { event: reply },
      { draft: "next", whole: false },
    ]
    const state = applyEventBatch(fresh(), batch)
    expect(state.events).toEqual([start, reply])
    expect(state.draft).toBe("next")
    expect([...state.streamed]).toEqual([1])
    expect(applyEventBatch(state, [{ event: end }]).draft).toBe("")
  })

  it("does not clear the main draft when a worker model event arrives", () => {
    const worker: RunEvent = {
      type: "model",
      text: "Worker thought",
      tool_calls: [],
      time: 2,
    }
    const state = applyEventBatch(fresh(), [
      { draft: "Main reply", whole: true },
      { event: worker },
    ])
    expect(state.draft).toBe("Main reply")
    expect(state.streamed.size).toBe(0)
  })
})
