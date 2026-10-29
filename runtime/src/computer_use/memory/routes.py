"""The page's routes for memory: list the user's, change one, forget one and put it back, or forget all."""

from collections.abc import Callable
from dataclasses import asdict, replace

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from computer_use.memory import EDITABLE, KINDS, MAX_TEXT, Memory, MemoryStore, Source


async def body(request: Request) -> dict:
    try:
        data = await request.json()
    except ValueError:
        data = None
    if not isinstance(data, dict):
        raise HTTPException(400, "expected a JSON object")
    return data


def edits(data: dict) -> dict[str, str]:
    """The EDITABLE fields `data` changes, each a nonempty text; the rule cut as remember cuts it."""
    changes = {name: data[name] for name in EDITABLE if name in data}
    if any(not isinstance(value, str) or not value.strip() for value in changes.values()):
        raise HTTPException(400, f"{', '.join(EDITABLE)} are nonempty texts")
    return {name: " ".join(value.split())[:MAX_TEXT] for name, value in changes.items()}


def memory_routes(store: MemoryStore, me: Callable[[Request], str]) -> list[Route]:
    """Each of them for the user `me` says is asking: another user's memory is as missing as one never written."""

    async def listed(request: Request) -> JSONResponse:
        return JSONResponse([asdict(memory) for memory in await store.list(me(request))])

    async def change(request: Request) -> JSONResponse:
        changes = edits(await body(request))
        if not changes:
            raise HTTPException(400, f"one of {', '.join(EDITABLE)} is required")
        changed = await store.update(me(request), request.path_params["id"], **changes)
        if changed is None:
            raise HTTPException(404, "no such memory")
        return JSONResponse(asdict(changed))

    async def put_back(request: Request) -> JSONResponse:
        """A memory forgotten a moment ago, as the page had it, back under its id: the page's 復原."""
        data = await body(request)
        try:
            source = Source(**data["source"])
            memory = Memory(**{**data, "source": source, "id": request.path_params["id"], "user": me(request)})
        except (KeyError, TypeError) as error:
            raise HTTPException(400, f"not a memory: {error}") from error
        if source.kind not in KINDS or not (memory.project is None or isinstance(memory.project, str)):
            raise HTTPException(400, "not a memory")
        try:
            await store.save(replace(memory, **edits(asdict(memory))))
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        return JSONResponse(asdict(memory), 201)

    async def forget(request: Request) -> JSONResponse:
        if not await store.delete(me(request), request.path_params["id"]):
            raise HTTPException(404, "no such memory")
        return JSONResponse({"deleted": request.path_params["id"]})

    async def forget_all(request: Request) -> JSONResponse:
        return JSONResponse({"deleted": await store.reset(me(request))})

    return [
        Route("/api/memory", listed),
        Route("/api/memory", forget_all, methods=["DELETE"]),
        Route("/api/memory/{id}", change, methods=["PATCH"]),
        Route("/api/memory/{id}", put_back, methods=["PUT"]),
        Route("/api/memory/{id}", forget, methods=["DELETE"]),
    ]
