"""The current reply snapshot for reconnects, and ordered updates for connected viewers."""

from computer_use.streaming import LiveStream


class Draft:
    """What the main agent has written so far in the model call under way: the call (LangGraph's checkpoint namespace
    for it) and its text, both empty between calls."""

    def __init__(self):
        self.call = ""
        self.text = ""
        self.stream = LiveStream()

    def add(self, call: str, text: str) -> None:
        kind = "draft" if call != self.call else "delta"
        if call != self.call:
            self.call, self.text = call, ""
        self.text += text
        self.stream.publish(kind, {"text": text})

    def clear(self) -> None:
        self.call, self.text = "", ""
