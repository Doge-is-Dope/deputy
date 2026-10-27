"""The viewer must not lose a short reply, completion, or another viewer's events."""

import asyncio

from computer_use.agent.draft import Draft
from computer_use.streaming import LiveStream


async def test_queued_text_survives_clear_and_run_completion_for_each_viewer():
    draft = Draft()
    with draft.stream.subscribe() as first, draft.stream.subscribe() as second:
        draft.add("call1", "Hello ")
        draft.add("call1", "world.")
        draft.stream.record({"type": "model", "text": draft.text})
        draft.clear()
        draft.stream.record({"type": "end"})
        draft.stream.close()
        assert draft.text == ""
        for reader in (first, second):
            items = [await reader.get() for _ in range(5)]
            assert [x.kind for x in items] == ["draft", "delta", "line", "line", "done"]
            assert "".join(x.data["text"] for x in items[:2]) == "Hello world."
            assert [x.index for x in items[2:4]] == [0, 1]
    assert not draft.stream.subscribers


async def test_slow_reader_resyncs_without_blocking_or_consuming_another_viewers_data():
    stream = LiveStream(limit=32)
    with stream.subscribe() as slow, stream.subscribe() as fast:
        for _ in range(4):
            stream.publish("delta", {"text": "12345678"})
            assert (await fast.get()).data["text"] == "12345678"
        assert (await slow.get()).kind == "resync"
        assert slow not in stream.subscribers and fast in stream.subscribers


async def test_disconnect_removes_subscription_and_late_subscriber_does_not_wait():
    stream = LiveStream()
    with stream.subscribe():
        assert len(stream.subscribers) == 1
    assert not stream.subscribers
    stream.close()
    with stream.subscribe() as reader:
        assert (await asyncio.wait_for(reader.get(), 0.1)).kind == "done"


async def test_new_call_starts_a_new_draft_without_discarding_previous_queued_events():
    draft = Draft()
    with draft.stream.subscribe() as reader:
        draft.add("one", "First.")
        draft.stream.record({"type": "model", "text": "First."})
        draft.clear()
        draft.add("two", "Second.")
        assert [((item := await reader.get()).kind, item.data["text"]) for _ in range(3)] == [
            ("draft", "First."), ("line", "First."), ("draft", "Second.")
        ]
