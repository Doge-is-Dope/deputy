"""HTTP API for conversations and SSE events, plus the routes of the desktop, memory and sign-in.

Every client reaches the runs through it; only this server runs agents. A client sends its model, locale and
approval choices with each message."""

import asyncio
import contextlib
import io
import json
import re
import traceback
from dataclasses import asdict
from functools import partial
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from urllib.parse import quote

from PIL import Image
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from computer_use.agent.main_agent import SUBAGENTS, run_turn
from computer_use.auth import Authenticate, build_authenticator
from computer_use.agent.models import MAIN_AGENT, efforts, offered, starting
from computer_use.agent.title import MAX_CHARS, Titles, title_model
from computer_use.adapters import build_code_runner, build_computer, build_control, build_screen_judge, build_stores
from computer_use.computers import Computer
from computer_use.config import APPROVALS, FOLLOW, RunChoices, Settings
from computer_use.desktop.control import ApprovalFile, ControlSyncError, DesktopBusy, RunLock
from computer_use.desktop.routes import desktop_routes
from computer_use.desktop.webrtc import ScreenShare
from computer_use.agent.history import can_continue, thread_of
from computer_use.routes import body
from computer_use.runner import ConversationBusy, Runner
from computer_use.sandbox import CodeRunnerError
from computer_use.memory.routes import memory_routes
from computer_use.storage import (
    ALL, MAX_PAGE, PAGE, TURN, Runs, RunSummary, supported,
)

RUN_ID = re.compile(r"[\w-]+")
SCREENSHOT = re.compile(r"[\w-]+\.png")
LANGUAGE_TAG = re.compile(r"[A-Za-z]{2,8}(-[A-Za-z0-9]{1,8})*")
# Fixed so each thumbnail is made once and cached.
THUMBNAIL_WIDTHS = (160, 192, 400)
# A screenshot never changes once written, so the browser keeps what it got.
IMMUTABLE = {"Cache-Control": "max-age=31536000, immutable"}
KEEPALIVE_SECONDS = 15
NOT_CONTINUABLE = "this conversation cannot be continued: no supported record"


def thumbnail(png: bytes, width: int) -> bytes:
    with Image.open(io.BytesIO(png)) as image:
        height = max(1, round(image.height * width / image.width))
        small = image.convert("RGB").resize((width, height), Image.LANCZOS)
    out = io.BytesIO()
    small.save(out, "WEBP", quality=80)
    return out.getvalue()


def known_zone(name: str) -> bool:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True


AGENTS = (MAIN_AGENT, *(each.agent for each in SUBAGENTS))


def create_app(settings: Settings, max_steps: int, computer: Computer | None = None) -> Starlette:
    store, projects, memory = build_stores(settings)
    authenticator = build_authenticator(settings)
    control = build_control(settings)
    computer = computer if computer is not None else build_computer(settings)
    code_runner = build_code_runner(settings)
    start_turn = partial(
        run_turn, settings, computer=computer, control=control, code_runner=code_runner, memory=memory,
        judge=build_screen_judge(settings),
    )
    runner = Runner(store, start_turn, Titles(settings))
    run_lock = RunLock(settings.run_lock_path)
    asked = ApprovalFile(settings.approval_path)
    share = ScreenShare(computer, control)
    ice_servers = []
    # Without its password a TURN server is no use, and a browser refuses one with an empty credential outright.
    if settings.turn_url and settings.turn_password:
        credential = settings.turn_password.get_secret_value()
        ice_servers.append({"urls": settings.turn_url, "username": "live", "credential": credential})
    def active() -> str | None:
        """The run that has the desktop, which may be another server's, such as the eval's."""
        holder = run_lock.holder()
        return holder.get("run") if holder else None

    def me(request: Request) -> str:
        return request.state.identity.id

    def mine(request: Request) -> Runs:
        return store.of(me(request))

    def running(user: str) -> list[dict]:
        """The sessions in progress, each by its first turn and its conversation, until quiet: also while a task
        has ended and the main agent has yet to begin the turn it wakes for."""
        return [
            {
                "run": run,
                "thread": thread,
                "goal": session.goal,
                "turn": session.turn,
                "tasks": list(session.tasks),
                "pending": [{"id": m.id, "text": m.text} for m in session.inbox.pending()],
                "queued": [{"id": m.id, "text": m.text} for m in session.inbox.queued()],
                "read": [m.id for m in session.inbox.delivered()],
            }
            for thread, run in runner.running(user).items()
            if (session := runner.session(run)) is not None
        ]

    def busy(reason: str, run: str | None) -> JSONResponse:
        text = {"desktop": "another run is using the desktop", "conversation": "this conversation has a run in progress"}
        return JSONResponse({"error": text[reason], "reason": reason, "run": run}, 409)

    # (user, run) pairs in the current format, so a run's record is read once.
    supported_runs: set[tuple[str, str]] = set()

    async def owned(runs: Runs, run: str) -> bool:
        key = (runs.user, run)
        if key not in supported_runs and RUN_ID.fullmatch(run) and supported(await runs.events(run, messages=False)):
            supported_runs.add(key)
        return key in supported_runs

    async def run_of(request: Request) -> str:
        run = request.path_params["run"]
        if not await owned(mine(request), run):
            raise HTTPException(404, "no such run")
        return run

    async def erase(thread: str, user: str) -> list[str]:
        deleted = await runner.delete(thread, user)
        supported_runs.difference_update((user, run) for run in deleted)
        return deleted

    async def runs_of(request: Request) -> list[RunSummary]:
        thread = request.path_params["thread"]
        listed = await mine(request).runs(thread) if RUN_ID.fullmatch(thread) else []
        if not listed:
            raise HTTPException(404, "no such conversation")
        return listed

    async def name_in(request: Request) -> str:
        name = (await body(request)).get("name")
        if not isinstance(name, str) or not name.strip():
            raise HTTPException(400, "name is required")
        return name

    async def project_of(request: Request, data: dict) -> str | None:
        """The asker's project `data` names by "project" (id) or "project_name" (made if missing); None for none."""
        if (name := data.get("project_name")) is not None:
            if not isinstance(name, str) or not name.strip():
                raise HTTPException(400, "project_name is a name")
            return (await projects.create(me(request), name)).id
        id = data.get("project")
        if id is not None and not (isinstance(id, str) and await projects.get(me(request), id)):
            raise HTTPException(404, "no such project")
        return id

    async def awaiting(request: Request):
        pending = asked.pending(run := active())
        return pending if pending is not None and await owned(mine(request), run) else None

    def choices_of(data: dict) -> RunChoices:
        """The user's choices sent with a message. A model or effort no longer offered, or an agent the runtime no
        longer has, is not refused: `models.chosen` falls back, so what a page kept from before still sends."""
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
        timezone = data.get("timezone")
        if timezone is not None and not (isinstance(timezone, str) and known_zone(timezone)):
            raise HTTPException(400, 'timezone must be an IANA time zone, such as "Asia/Taipei"')
        memory = data.get("memory", {})
        if not (isinstance(memory, dict) and set(memory) <= {"learn", "use"}
                and all(isinstance(value, bool) for value in memory.values())):
            raise HTTPException(400, "memory must say learn and use, each true or false")
        return RunChoices(
            {
                agent: {key: value for key, value in chosen.items() if agent != MAIN_AGENT or value != FOLLOW}
                for agent, chosen in agents.items()
                if agent in AGENTS
            },
            approvals,
            locale,
            timezone,
            memory.get("learn", False),
            memory.get("use", False),
        )

    def steps_of(data: dict) -> int:
        steps = data.get("max_steps", max_steps)
        if not isinstance(steps, int) or not 1 <= steps <= 200:
            raise HTTPException(400, "max_steps must be a whole number from 1 to 200")
        return steps

    async def status(request: Request) -> JSONResponse:
        try:
            computer_status = await computer.status()
            connected, detail = computer_status.connected, computer_status.detail
        except Exception as error:  # e.g. no display: the server runs, the desktop is unreachable
            connected, detail = False, f"{type(error).__name__}: {error}"
        return JSONResponse({
            # The runtime keeps no user's choices: the page works out what each agent will use from these and sends it.
            "defaults": starting(settings, AGENTS),
            "title_model": asdict(title_model(settings)),  # shown read-only in settings
            "models": [{"id": spec, "efforts": list(efforts(spec))} for spec in offered(settings)],
            "max_steps": max_steps,
            "active": active(),
            "running": running(me(request)),
            # Changes when a conversation is named, so the page lists them again.
            "titles_revision": await mine(request).revision(),
            "error": (
                {"run": runner.error["run"], "message": runner.error["message"]}
                if runner.error and runner.error["user"] == me(request) else None
            ),
            "control": asdict(control.read()),
            "approval": asdict(pending) if (pending := await awaiting(request)) else None,
            "computer": {"connected": connected, "detail": detail},
            # None when there is no coding agent.
            "code_runner": asdict(await code_runner.status()) if code_runner else None,
            "ice_servers": ice_servers,
        })

    async def session(request: Request) -> JSONResponse:
        """Who the page is signed in as, and how it signed in; a request that proves nobody never gets here (401)."""
        return JSONResponse({**asdict(request.state.identity), "login": authenticator.login})

    async def list_conversations(request: Request) -> JSONResponse:
        """A page of the asker's conversations, most recent first. `?project=` an id, empty for none, absent for all;
        `?before=` a page's `next`; `?limit=` up to 100."""
        params = request.query_params
        project = params.get("project", ALL) or None
        limit = params.get("limit", str(PAGE))
        if not limit.isdigit() or int(limit) < 1:
            raise HTTPException(400, "limit must be a whole number from 1")
        try:
            page = await mine(request).conversations(project, params.get("before"), int(limit))
        except ValueError:
            raise HTTPException(400, "before must be a page's next") from None
        return JSONResponse({"items": [asdict(each) for each in page.items], "next": page.next})

    async def conversation_runs(request: Request) -> JSONResponse:
        """A conversation's runs, oldest first, by its id or any run's id; 404 if not the asker's."""
        runs, id = mine(request), request.path_params["thread"]
        thread = await thread_of(runs, id) if RUN_ID.fullmatch(id) else None
        listed = await runs.runs(thread) if thread else []
        if not listed:
            raise HTTPException(404, "no such conversation")
        return JSONResponse([asdict(each) for each in listed])

    async def search(request: Request) -> JSONResponse:
        # Conversations by what was said in them; the page matches their names itself, from the list.
        query = request.query_params.get("q", "").strip()
        return JSONResponse([asdict(hit) for hit in await mine(request).search(query)] if query else [])

    async def download(request: Request) -> Response:
        thread, path = request.path_params["thread"], request.path_params["path"]
        await runs_of(request)
        if code_runner is None:
            raise HTTPException(503, "code runner is unavailable")
        try:
            data = await code_runner.read(thread, path)
        except FileNotFoundError:
            raise HTTPException(404, "no such file") from None
        except ValueError as error:
            raise HTTPException(400, str(error)) from None
        except CodeRunnerError:
            raise HTTPException(503, "code runner is unavailable") from None
        return Response(data, media_type="application/octet-stream", headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(path.rsplit('/', 1)[-1], safe='')}",
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        })

    async def new_run(request: Request) -> JSONResponse:
        data = await body(request)
        goal = data.get("goal")
        if not isinstance(goal, str) or not goal.strip():
            raise HTTPException(400, "goal is required")
        thread = data.get("thread")
        if thread is not None and not (
            isinstance(thread, str) and RUN_ID.fullmatch(thread) and await can_continue(mine(request), thread)
        ):
            raise HTTPException(404, NOT_CONTINUABLE)
        goal = goal.strip()
        choices = choices_of(data)
        desktop = data.get("computer", False)  # for the desktop, as a message that mentions @Computer is
        if not isinstance(desktop, bool):
            raise HTTPException(400, "computer must be true or false")
        queued = data.get("queue", False)  # to wait for the run in progress to end, rather than steer it
        if not isinstance(queued, bool):
            raise HTTPException(400, "queue must be true or false")
        if thread is not None:  # sent while the conversation's run works: it goes to that run
            try:
                sent = runner.send(thread, goal, choices, queued)
            except ConversationBusy as error:
                return busy("conversation", error.run)
            if sent is not None:
                run, message = sent
                return JSONResponse({"id": run, "thread": thread, "message": message.id}, 202)
        # The user agreed to hand the desktop over: the run gives it to the agent once it has it.
        take_control = data.get("take_control") is True
        # A message that continues a conversation stays in the conversation's own project.
        project = None if thread is not None else await project_of(request, data)
        steps = steps_of(data)
        try:
            run = await runner.start(
                goal, steps, thread=thread, force_computer=desktop, take_control=take_control,
                choices=choices, project=project, user=me(request),
            )
        except ConversationBusy as error:
            return busy("conversation", error.run)
        except DesktopBusy as error:
            return busy("desktop", error.run)
        except ControlSyncError as error:  # the run's return of control, as /api/control answers it
            return JSONResponse({"error": str(error)}, 503)
        except Exception as error:
            if thread is not None and not await can_continue(mine(request), thread):  # deleted since it was checked
                raise HTTPException(404, NOT_CONTINUABLE) from error
            traceback.print_exception(error)
            return JSONResponse({"error": f"{type(error).__name__}: {error}"}, 500)
        return JSONResponse({"id": run, "thread": thread or run}, 201)

    async def delete_conversation(request: Request) -> JSONResponse:
        """Erases a conversation's runs, records and screenshots for good."""
        thread = request.path_params["thread"]
        await runs_of(request)
        try:
            deleted = await erase(thread, me(request))
        except ConversationBusy as error:
            return busy("conversation", error.run)
        return JSONResponse({"deleted": deleted})

    async def update_conversation(request: Request) -> JSONResponse:
        """Rename or move a conversation; `"project": null` moves it to recents.

        User titles go in the latest turn and override generated titles. Project changes
        go in the first turn. Both append events without interrupting an active run.
        """
        thread = request.path_params["thread"]
        runs = [each.id for each in await runs_of(request) if each.kind == TURN]
        data = await body(request)
        changes = {}
        if "title" in data:
            title = data["title"]
            if not isinstance(title, str) or not title.strip():
                raise HTTPException(400, "title is required")
            changes["title"] = " ".join(title.split())[:MAX_CHARS].rstrip()
            await write(request, runs[-1], {"type": "title", "text": changes["title"], "by": "user"})
        if "project" in data or "project_name" in data:
            changes["project"] = await project_of(request, data)
            await write(request, runs[0], {"type": "project", "project": changes["project"], "by": "user"})
        if not changes:
            raise HTTPException(400, "title or project is required")
        return JSONResponse({"thread": thread, **changes})

    async def write(request: Request, run: str, event: dict) -> None:
        runs = mine(request)
        runner.live.publish(run, runs.append(run, event))
        await runs.flush(run)

    async def list_projects(request: Request) -> JSONResponse:
        return JSONResponse([asdict(each) for each in await projects.list(me(request))])

    async def new_project(request: Request) -> JSONResponse:
        """A new project, or the asker's own if they have one by that name already."""
        return JSONResponse(asdict(await projects.create(me(request), await name_in(request))), 201)

    async def rename_project(request: Request) -> JSONResponse:
        name = await name_in(request)
        try:
            renamed = await projects.rename(me(request), request.path_params["project"], name)
        except ValueError as error:
            return JSONResponse({"error": str(error)}, 409)
        if renamed is None:
            raise HTTPException(404, "no such project")
        return JSONResponse(asdict(renamed))

    async def delete_project(request: Request) -> JSONResponse:
        """Delete a project and its conversations sequentially.

        An active conversation returns 409. Earlier deletions remain; the project and
        remaining conversations are kept.
        """
        user = me(request)
        project = request.path_params["project"]
        runs = mine(request)
        if await projects.get(user, project) is None:
            raise HTTPException(404, "no such project")
        threads: list[str] = []
        before = None
        while True:
            page = await runs.conversations(project, before, MAX_PAGE)
            threads.extend(conversation.id for conversation in page.items)
            before = page.next
            if before is None:
                break
        for thread in threads:
            try:
                await erase(thread, user)
            except ConversationBusy as error:
                return busy("conversation", error.run)
        await projects.delete(user, project)
        return JSONResponse({"deleted": project, "conversations": threads})

    async def stop_run(request: Request) -> JSONResponse:
        """Stops one log: a turn (its tasks go on) or a task (the others go on)."""
        run = await run_of(request)
        if not await runner.stop_one(run):
            return JSONResponse({"error": "this run is not in progress"}, 409)
        return JSONResponse({"stopped": True})

    async def stop_conversation(request: Request) -> JSONResponse:
        session = runner.running(me(request)).get(request.path_params["thread"])
        if session is None:
            return JSONResponse({"error": "this conversation is not in progress"}, 409)
        await runner.stop(session)
        return JSONResponse({"stopped": True})

    async def withdraw_message(request: Request) -> JSONResponse:
        """Takes back a message no agent has read yet, or one queued for the next run; 409 once read."""
        run = await run_of(request)
        inbox = runner.inbox(run)
        if inbox is None or not inbox.withdraw(request.path_params["message"]):
            return JSONResponse({"error": "this message has been read"}, 409)
        return JSONResponse({"withdrawn": True})

    async def events(request: Request) -> StreamingResponse:
        """Server-sent events: each log line numbered, so a reconnecting page gets only what it missed, then "done"
        once the run has ended (at once for a run another server runs). While the main agent writes a reply,
        unnumbered events follow: "draft" with all of it so far and whether it is the final reply, then "delta" with
        what came since. Lines leave out the model messages, most of a log; `?full=1` keeps them for an export."""
        run, runs = await run_of(request), mine(request)
        seen = request.headers.get("last-event-id", "")
        after = int(seen) if seen.isdigit() else -1
        full = request.query_params.get("full") == "1"

        def said(kind: str, data: dict) -> str:
            return f"event: {kind}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

        def line(index: int, event: dict) -> str:
            shown = event if full else {key: value for key, value in event.items() if key != "message"}
            return f"id: {index}\ndata: {json.dumps(shown, ensure_ascii=False)}\n\n"

        async def stream():
            # Watch without awaiting, so no event falls in between: the view's seen events come from the store.
            with runner.live.watch(run) as view:
                if view is None:  # an ended run, or another server's
                    for index, event in enumerate(await runs.events(run, after, messages=full), after + 1):
                        yield line(index, event)
                    yield said("done", {})
                    return
                boundary = view.seen
                ended = False
                sent = after
                # Only what the page has not got is read: a page that reconnects has most of a long log already.
                missed = (await runs.events(run, after, messages=full))[:max(0, boundary - after - 1)]
                for sent, event in enumerate(missed, after + 1):
                    yield line(sent, event)
                    ended = ended or event["type"] == "end"
                if ended:
                    yield said("done", {})
                    return
                if view.draft or view.final:
                    yield said("draft", {"text": view.draft, "final": view.final})
                while True:
                    try:
                        item = await asyncio.wait_for(view.updates.get(), KEEPALIVE_SECONDS)
                    except TimeoutError:
                        yield ": keepalive\n\n"
                        continue
                    if item.kind == "resync":
                        return
                    if item.kind == "line":
                        if item.index > sent:
                            yield line(item.index, item.data)
                            sent = item.index
                        if item.data["type"] == "end":
                            yield said("done", {})
                            return
                    else:
                        yield said(item.kind, item.data)
                        if item.kind == "done":
                            return

        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    async def screenshot(request: Request) -> Response:
        """A screenshot of a run, or with `?w=` a thumbnail that wide."""
        run, name, runs = await run_of(request), request.path_params["name"], mine(request)
        if not SCREENSHOT.fullmatch(name):
            raise HTTPException(404, "no such screenshot")
        width = request.query_params.get("w")
        if width is not None and (not width.isdigit() or int(width) not in THUMBNAIL_WIDTHS):
            raise HTTPException(400, f"w must be one of {', '.join(map(str, THUMBNAIL_WIDTHS))}")
        # Made on first request and kept as a file of the run; many are never asked for.
        wanted = name if width is None else f"thumbs/{width}/{name}.webp"
        try:
            data = await runs.get_file(run, wanted)
        except FileNotFoundError:
            try:
                png = await runs.get_file(run, name)
            except FileNotFoundError:
                raise HTTPException(404, "no such screenshot") from None
            data = await asyncio.to_thread(thumbnail, png, int(width))
            await runs.put_file(run, wanted, data)
        return Response(data, media_type="image/png" if width is None else "image/webp", headers=IMMUTABLE)

    async def choose_approvals(request: Request) -> JSONResponse:
        """Sets at once how the run in progress answers steps that need approval; models apply from the next run."""
        run = await run_of(request)
        approvals = (await body(request)).get("approvals")
        if approvals not in APPROVALS:
            raise HTTPException(400, 'approvals must be "ask" or "auto"')
        if not runner.choose(run, approvals):
            return JSONResponse({"error": "this run is not in progress here"}, 409)
        return JSONResponse({"run": run, "approvals": approvals})

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette):
        async with contextlib.AsyncExitStack() as cleanup:
            for each in (store, projects, memory):
                cleanup.push_async_callback(each.close)
            cleanup.push_async_callback(computer.close)
            cleanup.push_async_callback(share.close)
            if code_runner is not None:
                cleanup.push_async_callback(code_runner.close)
            cleanup.push_async_callback(runner.close)
            yield

    async def http_error(request: Request, error: HTTPException) -> JSONResponse:
        return JSONResponse({"error": error.detail}, error.status_code)

    return Starlette(
        routes=[
            *authenticator.routes,
            *memory_routes(memory, me),
            *desktop_routes(computer, control, share, asked, awaiting),
            Route("/api/session", session),
            Route("/api/status", status),
            Route("/api/conversations", list_conversations),
            Route("/api/conversations/{thread}/runs", conversation_runs),
            Route("/api/conversations/{thread}/files/{path:path}", download),
            Route("/api/runs", new_run, methods=["POST"]),
            Route("/api/search", search),
            Route("/api/runs/{run}/events", events),
            Route("/api/runs/{run}/files/{name}", screenshot),
            Route("/api/runs/{run}/stop", stop_run, methods=["POST"]),
            Route("/api/runs/{run}/messages/{message}", withdraw_message, methods=["DELETE"]),
            Route("/api/runs/{run}/approvals", choose_approvals, methods=["POST"]),
            Route("/api/conversations/{thread}/stop", stop_conversation, methods=["POST"]),
            Route("/api/conversations/{thread}", delete_conversation, methods=["DELETE"]),
            Route("/api/conversations/{thread}", update_conversation, methods=["PATCH"]),
            Route("/api/projects", list_projects),
            Route("/api/projects", new_project, methods=["POST"]),
            Route("/api/projects/{project}", rename_project, methods=["PATCH"]),
            Route("/api/projects/{project}", delete_project, methods=["DELETE"]),
        ],
        middleware=[Middleware(Authenticate, authenticator=authenticator)],
        exception_handlers={HTTPException: http_error},
        lifespan=lifespan,
    )
