import asyncio

import pytest
from pyee.asyncio import AsyncIOEventEmitter

import computer_use.server as server
from computer_use.desktop.webrtc import ScreenShare


@pytest.mark.parametrize("failure", [None, "runner"])
async def test_server_disposes_backend_after_its_callers_even_on_failure(settings, computer, monkeypatch, failure):
    order = []
    stores = server.build_stores(settings)

    def observe_close(resource, name):
        original = resource.close

        async def close(*args):
            await original(*args)
            order.append(name)
            if failure == name:
                raise RuntimeError(name)

        monkeypatch.setattr(resource, "close", close)

    for resource, name in zip(stores, ("runs", "projects", "memory")):
        observe_close(resource, name)
    observe_close(computer, "computer")
    observe_close(server.Runner, "runner")
    observe_close(server.ScreenShare, "live")

    monkeypatch.setattr(server, "build_stores", lambda _: stores)
    monkeypatch.setattr(server, "build_code_runner", lambda _: None)
    monkeypatch.setattr(server, "build_computer", lambda _: computer)
    app = server.create_app(settings, max_steps=10)

    async def serve():
        async with app.router.lifespan_context(app):
            assert not computer.closed

    if failure:
        with pytest.raises(RuntimeError, match=failure):
            await serve()
    else:
        await serve()
    assert computer.closed
    assert sorted(order) == sorted(["runner", "live", "computer", "memory", "projects", "runs"])
    for caller in ("runner", "live"):
        assert order.index(caller) < order.index("computer")
    for store in ("runs", "projects", "memory"):
        assert order.index("computer") < order.index(store)


@pytest.mark.parametrize("channel_closed", [False, True])
async def test_live_input_finishes_releasing_keys_before_backend_close(computer, control, channel_closed):
    order = []
    entered = asyncio.Event()
    released = asyncio.Event()
    control.write("user")

    async def release():
        entered.set()
        await released.wait()
        assert not computer.closed
        order.append("released")

    computer.release_all = release
    channel = AsyncIOEventEmitter()
    channel.readyState = "open"
    channel.send = lambda _: None
    share = ScreenShare(computer, control)
    share._take_input(channel)
    share._report_pointer(channel)
    await asyncio.sleep(0)
    if channel_closed:
        channel.emit("close")
        await asyncio.wait_for(entered.wait(), 1)
    closing = asyncio.create_task(share.close())
    try:
        await asyncio.wait_for(entered.wait(), 1)
        assert not closing.done()
    finally:
        released.set()
        await asyncio.wait_for(closing, 1)
    await computer.close()
    assert computer.closed and order == ["released"]
