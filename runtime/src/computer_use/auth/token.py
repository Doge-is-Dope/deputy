"""One shared token, as Jupyter's and code-server's defaults: whoever has it is the local user.

The command line sends it as a bearer token. The page cannot send a header with every request (an EventSource or an
<img> sends none), so signing in puts the token itself in a cookie, which the browser sends instead; the runtime
keeps no session for it, and changing the token signs everyone out."""

import hashlib
import hmac

from starlette.requests import HTTPConnection, Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from computer_use.auth.base import LOCAL, Identity

COOKIE = "cu_token"
# As long as browsers keep a cookie.
COOKIE_SECONDS = 400 * 24 * 3600


class TokenAuthenticator:
    login = "token"

    def __init__(self, token: str):
        self._digest = hashlib.sha256(token.encode()).digest()
        self.routes = (
            Route("/api/login", self.sign_in, methods=["POST"]),
            Route("/api/logout", self.sign_out, methods=["POST"]),
        )

    def valid(self, token: str) -> bool:
        return hmac.compare_digest(hashlib.sha256(token.encode()).digest(), self._digest)

    def identify(self, request: HTTPConnection) -> Identity | None:
        scheme, _, bearer = request.headers.get("authorization", "").partition(" ")
        token = bearer if scheme.lower() == "bearer" else request.cookies.get(COOKIE, "")
        return LOCAL if token and self.valid(token) else None

    async def sign_in(self, request: Request) -> Response:
        """Checks the token, {"token": …}, and puts it in the cookie the browser sends from then on."""
        try:
            token = (await request.json()).get("token")
        except (ValueError, AttributeError):
            token = None
        if not isinstance(token, str) or not self.valid(token):
            return JSONResponse({"error": "wrong token"}, 401)
        response = Response(status_code=204)
        response.set_cookie(COOKIE, token, max_age=COOKIE_SECONDS, httponly=True, samesite="strict",
                            secure=request.url.scheme == "https")
        return response

    async def sign_out(self, request: Request) -> Response:
        response = Response(status_code=204)
        response.delete_cookie(COOKIE, httponly=True, samesite="strict")
        return response
