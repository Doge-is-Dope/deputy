"""HTTP API for conversations, SSE events, desktop control and approvals.

Every client, the web page and the command line alike, reaches the runs through it; only
this server runs agents. Each conversation has one run at a time; only one task across
all servers sharing the desktop may use it. Runs accept steering messages, with unread
messages carried into the next run.

Durable events come from the run store. Live drafts are this server's alone and are
never logged as text history. A client sends its model, locale and approval choices
with each message."""

import asyncio
import contextlib
import io
import json
import re
import traceback
from dataclasses import asdict

from PIL import Image
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from computer_use.agent.main_agent import SUBAGENTS, forced
from computer_use.auth import Authenticate, build_authenticator
from computer_use.agent.models import MAIN_AGENT, efforts, offered, starting
from computer_use.agent.title import MAX_CHARS, title_model
from computer_use.computers import Computer, build_computer
from computer_use.sandbox import build_code_runner
from computer_use.config import APPROVALS, FOLLOW, RunChoices, Settings
from computer_use.desktop.control import ApprovalFile, ControlFile, DesktopBusy, RunLock, hand_over
from computer_use.desktop.webrtc import ScreenShare
from computer_use.agent.history import can_continue
from computer_use.runner import ConversationBusy, Runner
from computer_use.storage import RunStore, build_run_store, project_name

RUN_ID = re.compile(r"[\w-]+")
SCREENSHOT = re.compile(r"[\w-]+\.png")
# A language tag as the page sends the interface's language, such as "zh-Hant" or "en".
LANGUAGE_TAG = re.compile(r"[A-Za-z]{2,8}(-[A-Za-z0-9]{1,8})*")
# The widths a screenshot can be asked for in, for the page's thumbnails: its steps show them a few dozen pixels wide.
THUMBNAIL_WIDTHS = range(64, 801)
# A screenshot never changes once written, so the browser keeps what it got.
IMMUTABLE = {"Cache-Control": "max-age=31536000, immutable"}
KEEPALIVE_SECONDS = 15
# The longest note a user can send with a rejection; the agent reads it.
MAX_NOTE = 1000
# Where a user can answer a step awaiting approval.
ANSWERED_FROM = ("web", "cli")


def thumbnail(png: bytes, width: int) -> bytes:
    """The screenshot `png` scaled to `width` pixels wide, as WebP."""
    with Image.open(io.BytesIO(png)) as image:
        height = max(1, round(image.height * width / image.width))
        small = image.convert("RGB").resize((width, height), Image.LANCZOS)
    out = io.BytesIO()
    small.save(out, "WEBP", quality=80)
    return out.getvalue()


def project_of(data: dict) -> str | None:
    """The project a new conversation is begun in on the page; None without one, or for a message that continues a
    conversation, which stays in its own."""
    return None if data.get("thread") is not None else project_name(data.get("project"))



# The agents whose model and effort the settings page offers to choose: the main agent and each it hands work to.
AGENTS = (MAIN_AGENT, *(each.agent for each in SUBAGENTS))


def create_app(
    settings: Settings, max_steps: int, computer: Computer | None = None, store: RunStore | None = None
) -> Starlette:
    store = store or build_run_store(settings)
    authenticator = build_authenticator(settings)
    runner = Runner(settings, computer or build_computer(settings), store, build_code_runner(settings))
    control = ControlFile(settings.control_path)
    run_lock = RunLock(settings.run_lock_path)
    approvals = ApprovalFile(settings.approval_path)
    share = ScreenShare(runner.computer, control)
    ice_servers = []
    if settings.turn_url:
        password = settings.turn_password.get_secret_value() if settings.turn_password else ""
        ice_servers.append({"urls": settings.turn_url, "username": "live", "credential": password})
    owners: dict[str, str] = {}  # whose each run is that has been asked for, which never changes

    def active() -> str | None:
        """The run that has the desktop, started here or by another server sharing it, such as the eval's."""
        holder = run_lock.holder()
        return holder.get("run") if holder else None

    def me(request: Request) -> str:
        """Who is asking (auth.Identity's id): they see their own conversations only."""
        return request.state.identity.id

    async def owner(run: str) -> str | None:
        """Whose a run is; None for one not in the list, or not in the current format."""
        if run not in owners:
            summary = next((each for each in await store.summaries() if each.id == run), None)
            if summary is None:
                return None
            owners[run] = summary.user
        return owners[run]

    def running(user: str) -> list[dict]:
        """The runs in progress, each with its conversation, until their logs end: not only while they have the
        desktop, which a run lets go of before its last reply. The messages its agents have not read yet are listed,
        for the page to show and take back."""
        return [
            {
                "run": run,
                "thread": thread,
                "pending": [{"id": m.id, "text": m.text} for m in inbox.pending()],
            }
            for thread, run in runner.running(user).items()
            if (inbox := runner.inbox(run)) is not None
        ]

    def busy(reason: str, run: str | None) -> JSONResponse:
        """A message turned away: another run has the desktop ("desktop"), or the conversation has a run in progress
        ("conversation")."""
        text = {"desktop": "another run is using the desktop", "conversation": "this conversation has a run in progress"}
        return JSONResponse({"error": text[reason], "reason": reason, "run": run}, 409)

    async def run_of(request: Request) -> str:
        """The run the path names, if it is the asker's: another user's is as missing as one that never was."""
        run = request.path_params["run"]
        if not RUN_ID.fullmatch(run) or await owner(run) != me(request):
            raise HTTPException(404, "no such run")
        return run

    async def awaiting(request: Request):
        """The step the run with the desktop waits for the user to approve, if the run is the asker's."""
        pending = approvals.pending(run := active())
        return pending if pending is not None and await owner(run) == me(request) else None

    async def body(request: Request) -> dict:
        try:
            data = await request.json()
        except ValueError:
            data = None
        if not isinstance(data, dict):
            raise HTTPException(400, "expected a JSON object")
        return data

    def choices_of(data: dict) -> RunChoices:
        """The user's choices sent with a message, which the page keeps: `approvals`, "ask" or "auto"; `agents`, by
        agent, its `model` and `effort`, a subagent's either "follow". A model or effort no longer offered is not
        refused, nor an agent the runtime no longer has: an agent works with the main agent's model, or the nearest
        effort its model takes (`models.chosen`), so what a page kept from before still sends. And `locale`, the
        interface's language tag, which the agents write to the user in; none from a page that does not send it."""
        approvals = data.get("approvals", "ask")
        if approvals not in APPROVALS:
            raise HTTPException(400, 'approvals must be "ask" or "auto"')
        agents = data.get("agents", {})
        if not isinstance(agents, dict) or not all(
            isinstance(chosen, dict) and set(chosen) <= {"model", "effort"}
            and all(isinstance(value, str) and value for value in chosen.values())
            for chosen in agents.values()
        ):
            raise HTTPException(400, "agents must map an agent to its model and effort")
        locale = data.get("locale")
        if locale is not None and not (isinstance(locale, str) and re.fullmatch(LANGUAGE_TAG, locale)):
            raise HTTPException(400, 'locale must be a language tag, such as "zh-Hant"')
        return RunChoices(
            {
                agent: {key: value for key, value in chosen.items() if agent != MAIN_AGENT or value != FOLLOW}
                for agent, chosen in agents.items()
                if agent in AGENTS
            },
            approvals,
            locale,
        )

    def steps_of(data: dict) -> int:
        steps = data.get("max_steps", max_steps)
        if not isinstance(steps, int) or not 1 <= steps <= 200:
            raise HTTPException(400, "max_steps must be a whole number from 1 to 200")
        return steps

    async def start(
        goal: str, steps: int, thread: str | None, force_computer: bool, take_control: bool, choices: RunChoices,
        project: str | None, user: str,
    ) -> JSONResponse:
        try:
            run = await runner.start(goal, steps, thread, force_computer, take_control, choices, project, user)
        except ConversationBusy as error:
            return busy("conversation", error.run)
        except DesktopBusy as error:
            return busy("desktop", error.run)
        except Exception as error:
            traceback.print_exception(error)
            return JSONResponse({"error": f"{type(error).__name__}: {error}"}, 500)
        return JSONResponse({"id": run, "thread": thread or run}, 201)

    async def status(request: Request) -> JSONResponse:
        try:
            computer_status = await runner.computer.status()
            connected, detail = computer_status.connected, computer_status.detail
        except Exception as error:  # e.g. no display: the server runs, the desktop is unreachable
            connected, detail = False, f"{type(error).__name__}: {error}"
        return JSONResponse({
            # Each agent's model and effort as the settings start them, a value or "follow" (the main agent's), and the
            # models the settings page offers with the efforts each takes: the page works out from them, with what the
            # user chose, what each agent will work with (`models.chosen`), and sends the user's choices with each
            # message. The runtime keeps no user's choices.
            "defaults": starting(settings, AGENTS),
            "title_model": asdict(title_model(settings)),  # runtime-managed, shown read-only in settings
            "models": [{"id": spec, "efforts": list(efforts(spec))} for spec in offered(settings)],
            "max_steps": max_steps,
            "active": active(),  # the run using the desktop
            "running": running(me(request)),  # every run of the asker's in progress, with its conversation
            # Changes as a conversation is named, by this server or the command line, during a run or after it: the
            # page lists the conversations again, by their names.
            "titles_revision": await store.revision(),
            "error": runner.error if runner.error and await owner(runner.error["run"]) == me(request) else None,
            "control": asdict(control.read()),
            # The step the running run waits for the user to approve (agent.confirm), if any.
            "approval": asdict(pending) if (pending := await awaiting(request)) else None,
            "computer": {"connected": connected, "detail": detail},
            # Where the coding agent's commands run; None when there is none, and then no coding agent either.
            "code_runner": asdict(await runner.code_runner.status()) if runner.code_runner else None,
            "ice_servers": ice_servers,
        })

    async def session(request: Request) -> JSONResponse:
        """Who the page is signed in as, and how it signed in; a request that proves nobody never gets here (401)."""
        return JSONResponse({**asdict(request.state.identity), "login": authenticator.login})

    async def list_runs(request: Request) -> JSONResponse:
        mine = me(request)
        return JSONResponse([asdict(summary) for summary in await store.summaries() if summary.user == mine])

    async def search(request: Request) -> JSONResponse:
        # Conversations by what was said in them; the page matches their names itself, from the list.
        query = request.query_params.get("q", "").strip()
        return JSONResponse([asdict(hit) for hit in await store.search(query, me(request))] if query else [])

    async def new_run(request: Request) -> JSONResponse:
        data = await body(request)
        goal = data.get("goal")
        if not isinstance(goal, str) or not goal.strip():
            raise HTTPException(400, "goal is required")
        thread = data.get("thread")  # an earlier run's conversation to continue
        if thread is not None and not (
            isinstance(thread, str) and RUN_ID.fullmatch(thread) and await can_continue(store, thread)
            and await store.conversation(thread, user=me(request))
        ):
            raise HTTPException(404, "this conversation cannot be continued: no supported record")
        goal = goal.strip()
        choices = choices_of(data)
        desktop = data.get("computer", False)  # for the desktop, as a message that mentions @Computer is
        if not isinstance(desktop, bool):
            raise HTTPException(400, "computer must be true or false")
        if thread is not None:  # sent while the conversation's run works: it goes to that run
            try:
                sent = runner.send(thread, goal, choices)
            except ConversationBusy as error:
                return busy("conversation", error.run)
            if sent is not None:
                run, message = sent
                return JSONResponse({"id": run, "thread": thread, "message": message.id}, 202)
        # The user agreed to hand the desktop over for a message for it: the run gives it to the agent once it has it.
        take_control = data.get("take_control") is True
        return await start(
            goal, steps_of(data), thread, desktop or forced(goal), take_control, choices, project_of(data), me(request)
        )

    async def delete_conversation(request: Request) -> JSONResponse:
        """Moves a conversation's runs out of the list, into data/trash. Nothing is erased: an eval's grading sheet
        links to a run's screenshots, and moving a folder back undoes a mistake."""
        thread = request.path_params["thread"]
        if not RUN_ID.fullmatch(thread) or not await store.conversation(thread, user=me(request)):
            raise HTTPException(404, "no such conversation")
        if thread in runner.runs:
            return busy("conversation", runner.runs[thread].run)
        deleted = await store.delete(thread)
        for run in deleted:
            owners.pop(run, None)
        return JSONResponse({"deleted": deleted})

    async def restore_conversation(request: Request) -> JSONResponse:
        """Moves a deleted conversation's runs back out of data/trash into the list: the page's 還原."""
        thread = request.path_params["thread"]
        mine = RUN_ID.fullmatch(thread) and await store.conversation(thread, deleted=True, user=me(request))
        restored = await store.restore(thread) if mine else []
        if not restored:
            raise HTTPException(404, "no such deleted conversation")
        return JSONResponse({"restored": restored})

    async def update_conversation(request: Request) -> JSONResponse:
        """Names a conversation as the user wants it listed, or moves it into a project or out of one (`"project":
        null`). A name is a title event "by" the user in its latest run's log, which stands over any the runtime made
        (title_of) and keeps it from making another (history.has_title). A move is a project event in its first run's,
        which the page lists a conversation by (project_in). The log is appended a whole line at a time, as the run
        writes it, so a run in progress is not disturbed."""
        thread = request.path_params["thread"]
        runs = await store.conversation(thread, user=me(request)) if RUN_ID.fullmatch(thread) else []
        if not runs:
            raise HTTPException(404, "no such conversation")
        data = await body(request)
        if "project" in data and data["project"] is not None and not isinstance(data["project"], str):
            raise HTTPException(400, "project is a name or null")
        changes = {}
        if "title" in data:
            title = data["title"]
            if not isinstance(title, str) or not title.strip():
                raise HTTPException(400, "title is required")
            changes["title"] = " ".join(title.split())[:MAX_CHARS].rstrip()
            write(runs[-1], {"type": "title", "text": changes["title"], "by": "user"})
        if "project" in data:
            changes["project"] = project_name(data["project"])
            write(runs[0], {"type": "project", "name": changes["project"], "by": "user"})
        if not changes:
            raise HTTPException(400, "title or project is required")
        return JSONResponse({"thread": thread, **changes})

    def write(run: str, event: dict) -> None:
        """Adds the user's event to a run's log, and to the stream of its viewers while it runs."""
        _, event = store.append(run, event)
        if (draft := runner.draft(run)) is not None:
            draft.stream.record(event)

    async def stop_run(request: Request) -> JSONResponse:
        run = await run_of(request)
        if not runner.started(run):
            return JSONResponse({"error": "this run is not in progress"}, 409)
        await runner.stop(run)
        return JSONResponse({"stopped": True})

    async def events(request: Request) -> StreamingResponse:
        """Server-sent events: each line of the run's log, numbered so a reconnecting page gets only what it
        missed, then a "done" event once the run has ended, or at once for a run this server does not run. While the main agent writes a
        reply, events without a number follow the lines: "draft", all it has written of it, when the page has none of
        it yet, and then "delta", what it wrote since. A page that reconnects gets the lines it missed, then the reply
        so far, and nothing twice."""
        run = await run_of(request)
        seen = request.headers.get("last-event-id", "")
        after = int(seen) if seen.isdigit() else -1

        def said(kind: str, data: dict) -> str:
            return f"event: {kind}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

        async def stream():
            draft = runner.draft(run)
            if draft is not None:
                # Subscribe and take the durable boundary and draft snapshot without awaiting: publication cannot fall
                # in a gap. Durable events up to the boundary are read now; later ones come through the subscription.
                # Hold this object, not a lookup in Runner, so completion cannot discard this reader's pending text.
                with draft.stream.subscribe() as subscriber:
                    boundary, snapshot = store.count(run), draft.text
                    ended = False
                    sent = after  # the last index sent
                    # Only what the page has not got is read: a page that reconnects has most of a long log already.
                    missed = (await store.events(run, after))[:max(0, boundary - after - 1)]
                    for sent, event in enumerate(missed, after + 1):
                        yield f"id: {sent}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                        ended = ended or event["type"] == "end"
                    if ended:
                        yield said("done", {})
                        return
                    if snapshot:
                        yield said("draft", {"text": snapshot})
                    while True:
                        try:
                            item = await asyncio.wait_for(subscriber.get(), KEEPALIVE_SECONDS)
                        except TimeoutError:
                            yield ": keepalive\n\n"
                            continue
                        if item.kind == "resync":
                            return
                        if item.kind == "line":
                            if item.index > sent:
                                yield f"id: {item.index}\ndata: {json.dumps(item.data, ensure_ascii=False)}\n\n"
                                sent = item.index
                            if item.data["type"] == "end":
                                yield said("done", {})
                                return
                        else:
                            yield said(item.kind, item.data)
                            if item.kind == "done":
                                return
                return

            for index, event in enumerate(await store.events(run, after), after + 1):  # an ended run, or another server's
                yield f"id: {index}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
            yield said("done", {})
            return

        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    async def screenshot(request: Request) -> Response:
        """A screenshot of a run, or with `?w=` a copy that wide for a thumbnail: a few kilobytes, where the full
        screenshot is a few hundred."""
        run, name = await run_of(request), request.path_params["name"]
        if not SCREENSHOT.fullmatch(name):
            raise HTTPException(404, "no such screenshot")
        try:
            png = await store.get_file(run, name)
        except (FileNotFoundError, NotADirectoryError):
            raise HTTPException(404, "no such screenshot") from None
        width = request.query_params.get("w")
        if width is None:
            return Response(png, media_type="image/png", headers=IMMUTABLE)
        if not width.isdigit() or int(width) not in THUMBNAIL_WIDTHS:
            raise HTTPException(400, f"w must be a width from {THUMBNAIL_WIDTHS.start} to {THUMBNAIL_WIDTHS.stop - 1}")
        return Response(await asyncio.to_thread(thumbnail, png, int(width)), media_type="image/webp", headers=IMMUTABLE)

    async def screen(request: Request) -> Response:
        """The desktop's screen now, as a PNG."""
        try:
            frame = await runner.computer.screenshot()
        except Exception as error:  # e.g. no display: the server runs, the desktop is unreachable
            return JSONResponse({"error": f"{type(error).__name__}: {error}"}, 503)
        return Response(frame.png, media_type="image/png", headers={"Cache-Control": "no-store"})

    async def live(request: Request) -> JSONResponse:
        """WebRTC signalling for the live view: the page's offer in, the answer out, each with all its candidates."""
        offer = (await body(request)).get("sdp")
        if not isinstance(offer, str):
            raise HTTPException(400, "expected an SDP offer")
        return JSONResponse({"type": "answer", "sdp": await share.answer(offer)})

    async def approve(request: Request) -> JSONResponse:
        """The user's answer to the step awaiting approval: approve, or reject with an optional note. Doing it
        themselves is a takeover (/api/control), which answers it too."""
        data = await body(request)
        id, decision, note = data.get("id"), data.get("decision"), data.get("message", "")
        by = data.get("by", "web")  # where the user answered, which the log keeps
        if not isinstance(id, str) or decision not in ("approve", "reject"):
            raise HTTPException(400, 'expected {"id": …, "decision": "approve" or "reject"}')
        if not isinstance(note, str) or len(note) > MAX_NOTE:
            raise HTTPException(400, f"message must be text of at most {MAX_NOTE} characters")
        if by not in ANSWERED_FROM:
            raise HTTPException(400, f"by must be one of {', '.join(ANSWERED_FROM)}")
        pending = await awaiting(request)
        if pending is None or pending.id != id or not approvals.decide(id, decision, note.strip(), by):
            return JSONResponse({"error": "this step is not awaiting approval"}, 409)
        return JSONResponse({"id": id, "decision": decision})

    async def choose_approvals(request: Request) -> JSONResponse:
        """How a run in progress answers its next step that needs approval, as the user just chose in the page's
        settings, as Claude Code's permission mode applies at once; the models chosen there apply from the next run."""
        run = await run_of(request)
        approvals = (await body(request)).get("approvals")
        if approvals not in APPROVALS:
            raise HTTPException(400, 'approvals must be "ask" or "auto"')
        if not runner.choose(run, approvals):
            return JSONResponse({"error": "this run is not in progress here"}, 409)
        return JSONResponse({"run": run, "approvals": approvals})

    async def set_control(request: Request) -> JSONResponse:
        owner = (await body(request)).get("owner")
        if owner not in ("agent", "user"):
            raise HTTPException(400, 'owner must be "agent" or "user"')
        reason = "taken over by user" if owner == "user" else "returned by user"
        # Answers once the agent's action in flight is sent, so a page that has taken over is not raced by it.
        return JSONResponse(asdict(await hand_over(control, runner.computer, owner, reason)))

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette):
        yield
        await runner.close()
        await share.close()

    async def http_error(request: Request, error: HTTPException) -> JSONResponse:
        return JSONResponse({"error": error.detail}, error.status_code)

    return Starlette(
        routes=[
            *authenticator.routes,  # its own signing in and out
            Route("/api/session", session),
            Route("/api/status", status),
            Route("/api/runs", list_runs),
            Route("/api/runs", new_run, methods=["POST"]),
            Route("/api/search", search),
            Route("/api/runs/{run}/events", events),
            Route("/api/runs/{run}/files/{name}", screenshot),
            Route("/api/runs/{run}/stop", stop_run, methods=["POST"]),
            Route("/api/runs/{run}/approvals", choose_approvals, methods=["POST"]),
            Route("/api/conversations/{thread}", delete_conversation, methods=["DELETE"]),
            Route("/api/conversations/{thread}", update_conversation, methods=["PATCH"]),
            Route("/api/conversations/{thread}/restore", restore_conversation, methods=["POST"]),
            Route("/api/screen", screen),
            Route("/api/control", set_control, methods=["POST"]),
            Route("/api/approval", approve, methods=["POST"]),
            Route("/api/live", live, methods=["POST"]),
        ],
        middleware=[Middleware(Authenticate, authenticator=authenticator)],
        exception_handlers={HTTPException: http_error},
        lifespan=lifespan,
    )
