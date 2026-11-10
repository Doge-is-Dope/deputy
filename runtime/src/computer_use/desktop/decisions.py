"""ScreenJudge over OpenAI's Decisions API: predicates on screenshots, about 0.4 s each."""

import base64

import httpx

DECISIONS_URL = "https://api.openai.com/v1/decisions"
MODEL = "gpt-6-luna"
# Measured 2026-11-07 on 80 logged game screens: a pure dialogue box scored 0.87-0.99, menus and maps 0.0-0.03.
HOLDS = 0.5
TIMEOUT_SECONDS = 10
# Measured 2026-11-08 on 39 labelled key refusals: all 25 animations and walkers scored 0.81 or more, all 14 new screens
# 0.25 or less.
SAME_SCREEN = (
    "The second screenshot shows the same screen as the first, differing only by animation or decoration, such as a "
    "different picture cycling on a title screen, more text printed into the same text box, a tooltip, or a character "
    "walking on the same map; not a new screen, page, menu, dialog, step or scene."
)


class DecisionsJudge:
    def __init__(self, key: str, transport: httpx.AsyncBaseTransport | None = None):
        self._http = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {key}"}, timeout=TIMEOUT_SECONDS, transport=transport,
        )

    async def holds(self, png: bytes, condition: str) -> bool:
        answers = await self._ask("A screenshot of the computer's screen.", [png], {"holds": condition})
        return answers.get("holds", False)

    async def same_screen(self, before: bytes, after: bytes) -> bool:
        text = "Two screenshots of the same computer: first earlier, then now."
        return (await self._ask(text, [before, after], {"same": SAME_SCREEN})).get("same", False)

    async def _ask(self, text: str, pngs: list[bytes], questions: dict[str, str]) -> dict[str, bool]:
        """Each question's answer by name; none on a failed request."""
        images = [
            {"type": "input_image", "image_url": "data:image/png;base64," + base64.b64encode(png).decode(),
             "detail": "original"}
            for png in pngs
        ]
        body = {
            "model": MODEL,
            "input": [{"role": "user", "content": [{"type": "input_text", "text": text}, *images]}],
            "questions": [
                {"type": "predicate", "name": name, "instructions": instructions}
                for name, instructions in questions.items()
            ],
        }
        try:
            response = await self._http.post(DECISIONS_URL, json=body)
            response.raise_for_status()
            return {answer["name"]: answer["probability"] >= HOLDS for answer in response.json()["answers"]}
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            return {}
