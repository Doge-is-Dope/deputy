import io
import json

import httpx
import pytest
from PIL import Image, ImageDraw
from pydantic import SecretStr

import computer_use.desktop.executor
import computer_use.desktop.screen

from computer_use.adapters import build_screen_judge
from computer_use.desktop.decisions import SAME_SCREEN, DecisionsJudge
from computer_use.tools.desktop import desktop_tools


def judge_answering(probability: float, asked: list[dict]) -> DecisionsJudge:
    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        asked.append(body)
        answers = [{"type": "predicate", "name": q["name"], "probability": probability} for q in body["questions"]]
        return httpx.Response(200, json={"answers": answers})

    return DecisionsJudge("test-key", transport=httpx.MockTransport(respond))


async def test_holds_asks_the_condition_of_one_screen():
    asked: list[dict] = []
    assert await judge_answering(0.9, asked).holds(b"screen", "A dialogue is shown")
    assert not await judge_answering(0.2, asked).holds(b"screen", "A dialogue is shown")
    images = [part for part in asked[0]["input"][0]["content"] if part["type"] == "input_image"]
    assert len(images) == 1 and asked[0]["questions"][0]["instructions"] == "A dialogue is shown"


async def test_same_screen_compares_two_screens():
    asked: list[dict] = []
    assert await judge_answering(0.9, asked).same_screen(b"before", b"after")
    images = [part for part in asked[0]["input"][0]["content"] if part["type"] == "input_image"]
    assert len(images) == 2 and asked[0]["questions"][0]["instructions"] == SAME_SCREEN


async def test_a_failed_request_holds_nothing():
    judge = DecisionsJudge("test-key", transport=httpx.MockTransport(lambda request: httpx.Response(500)))
    assert await judge.holds(b"screen", "A dialogue is shown") is False
    assert await judge.same_screen(b"before", b"after") is False


def test_the_judge_is_built_only_with_an_openai_key(settings):
    assert build_screen_judge(settings.model_copy(update={"openai_api_key": None})) is None
    assert isinstance(build_screen_judge(settings.model_copy(update={"openai_api_key": SecretStr("test-key")})), DecisionsJudge)


def test_press_while_is_offered_only_with_a_judge(executor):
    assert "press_while" not in {tool.name for tool in desktop_tools(executor)}
    executor.judge = DecisionsJudge("test-key", transport=httpx.MockTransport(lambda request: httpx.Response(500)))
    assert "press_while" in {tool.name for tool in desktop_tools(executor)}


class Pages:
    """A dialogue of `menu_at` pages then a menu: each hold of a key shows the next page, and the judge says the
    condition holds on the pages before the menu."""

    def __init__(self, computer, executor, menu_at: int, turns_page: bool = True):
        self.page, self.menu_at, self.same = 0, menu_at, False
        self.computer = computer
        computer.screen = lambda: self.drawn(self.page)
        recorded = computer.hold

        async def hold(combo, seconds):
            await recorded(combo, seconds)
            self.page += turns_page

        computer.hold = hold
        executor.judge = self

    @staticmethod
    def drawn(page: int) -> bytes:
        image = Image.new("RGB", (1280, 800), "white")
        ImageDraw.Draw(image).rectangle((0, 40 * page, 1280, 40 * page + 30), fill="black")
        out = io.BytesIO()
        image.save(out, "PNG")
        return out.getvalue()

    async def holds(self, png: bytes, condition: str) -> bool:
        return png == self.drawn(min(self.page, self.menu_at - 1)) and self.page < self.menu_at

    async def same_screen(self, before: bytes, after: bytes) -> bool:
        return self.same


@pytest.fixture
def quick(monkeypatch, fast_polls):
    monkeypatch.setattr(computer_use.desktop.executor, "SETTLE_SECONDS", 0.05)
    monkeypatch.setattr(computer_use.desktop.executor, "MOVING_WATCH_SECONDS", 0)
    monkeypatch.setattr(computer_use.desktop.screen, "SETTLE_QUIET_SECONDS", 0.02)


ARGS = {"text": "x", "condition": "A dialogue is shown"}


async def test_press_while_presses_until_the_condition_stops_holding(computer, executor, quick):
    Pages(computer, executor, menu_at=3)
    await executor.observe("start")
    result = await executor.run("press_while", ARGS)
    assert result.ok and "Pressed x 3 times; stopped because the condition no longer held" in result.text
    assert [call[0] for call in computer.calls] == ["hold"] * 3


async def test_press_while_sends_nothing_when_the_condition_does_not_hold(computer, executor, quick):
    Pages(computer, executor, menu_at=0)
    await executor.observe("start")
    result = await executor.run("press_while", ARGS)
    assert result.ok and "Pressed x 0 times" in result.text and computer.calls == []


async def test_press_while_stops_at_its_limit_and_on_an_unchanged_screen(computer, executor, quick):
    Pages(computer, executor, menu_at=9)
    await executor.observe("start")
    assert "Pressed x 2 times; stopped because it reached 2 presses" in (
        await executor.run("press_while", {**ARGS, "max_presses": 2})
    ).text
    computer.calls.clear()
    Pages(computer, executor, menu_at=9, turns_page=False)
    await executor.observe("again")
    assert "Pressed x 1 times; stopped because the last press left the screen unchanged" in (
        await executor.run("press_while", ARGS)
    ).text


async def test_press_while_keeps_its_presses_when_the_screen_keeps_moving(computer, executor, quick):
    Pages(computer, executor, menu_at=9)
    await executor.observe("start")
    pressed = 0

    async def moving(seen, now, points):
        nonlocal pressed
        pressed += 1
        return pressed > 1  # after the first press

    executor._stale = moving
    result = await executor.run("press_while", ARGS)
    assert result.ok and result.reason is None
    assert "Pressed x 1 times; stopped because the screen kept changing" in result.text
    assert len(computer.calls) == 1


@pytest.mark.parametrize("same, sent", [(True, True), (False, False)])
async def test_a_key_on_a_changed_screen_is_sent_only_if_the_judge_sees_the_same_screen(
    computer, executor, quick, same, sent,
):
    pages = Pages(computer, executor, menu_at=9)
    pages.same = same
    await executor.observe("start")
    computer.screen = lambda: Pages.drawn(15)
    result = await executor.run("hold_key", {"text": "x", "duration": 0.2})
    assert result.ok is sent and bool(computer.calls) is sent
