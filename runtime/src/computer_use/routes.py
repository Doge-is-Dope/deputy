"""What the API's routes read of a request alike."""

from starlette.exceptions import HTTPException
from starlette.requests import Request


async def body(request: Request) -> dict:
    try:
        data = await request.json()
    except ValueError:
        data = None
    if not isinstance(data, dict):
        raise HTTPException(400, "expected a JSON object")
    return data
