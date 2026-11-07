"""The API's routes for the desktop: screen, live view, control, and the answer to a step awaiting approval."""

from collections.abc import Awaitable, Callable
from dataclasses import asdict

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from computer_use.computers import Computer
from computer_use.desktop.control import Approval, ApprovalFile, Control, ControlSyncError, hand_over
from computer_use.desktop.webrtc import ScreenShare
from computer_use.routes import body

MAX_NOTE = 1000
ANSWERED_FROM = ("web", "cli")


def desktop_routes(
    computer: Computer, control: Control, share: ScreenShare, asked: ApprovalFile,
    awaiting: Callable[[Request], Awaitable[Approval | None]],
) -> list[Route]:
    """`awaiting` says which step the asker may answer, if the run with the desktop is theirs."""

    async def screen(request: Request) -> Response:
        try:
            frame = await computer.screenshot()
        except Exception as error:  # e.g. no display: the desktop is unreachable
            return JSONResponse({"error": f"{type(error).__name__}: {error}"}, 503)
        return Response(frame.png, media_type="image/png", headers={"Cache-Control": "no-store"})

    async def live(request: Request) -> JSONResponse:
        """WebRTC signalling: the page's offer in, the answer out, each with all its candidates."""
        offer = (await body(request)).get("sdp")
        if not isinstance(offer, str):
            raise HTTPException(400, "expected an SDP offer")
        return JSONResponse({"type": "answer", "sdp": await share.answer(offer)})

    async def approve(request: Request) -> JSONResponse:
        """Approves or rejects the step awaiting approval, with an optional note.
        A takeover (/api/control) answers it too."""
        data = await body(request)
        id, decision, note = data.get("id"), data.get("decision"), data.get("message", "")
        by = data.get("by", "web")
        if not isinstance(id, str) or decision not in ("approve", "reject"):
            raise HTTPException(400, 'expected {"id": …, "decision": "approve" or "reject"}')
        if not isinstance(note, str) or len(note) > MAX_NOTE:
            raise HTTPException(400, f"message must be text of at most {MAX_NOTE} characters")
        if by not in ANSWERED_FROM:
            raise HTTPException(400, f"by must be one of {', '.join(ANSWERED_FROM)}")
        pending = await awaiting(request)
        if pending is None or pending.id != id or not asked.decide(id, decision, note.strip(), by):
            return JSONResponse({"error": "this step is not awaiting approval"}, 409)
        return JSONResponse({"id": id, "decision": decision})

    async def set_control(request: Request) -> JSONResponse:
        data = await body(request)
        owner, by = data.get("owner"), data.get("by", "web")
        if owner not in ("agent", "user"):
            raise HTTPException(400, 'owner must be "agent" or "user"')
        reason = f"taken over from {by}" if owner == "user" else f"returned from {by}"
        # Answers once the agent's action in flight is sent, so a page that has taken over is not raced by it.
        try:
            return JSONResponse(asdict(await hand_over(control, computer, owner, reason)))
        except ControlSyncError as error:
            return JSONResponse({"error": str(error)}, 503)

    return [
        Route("/api/screen", screen),
        Route("/api/control", set_control, methods=["POST"]),
        Route("/api/approval", approve, methods=["POST"]),
        Route("/api/live", live, methods=["POST"]),
    ]
