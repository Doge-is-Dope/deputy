"""Who a request comes from, as Jupyter Server's identity providers say it: the runtime asks, never remembers.

There are no sessions. Every request carries its own proof, a token or a header a sign-in proxy set, and is judged on
its own, so any number of runtimes can serve the same users. Which kind of proof a runtime takes is a setting
(CU_AUTH): none (auth.none), a shared token (auth.token), or a sign-in proxy in front of it (auth.proxy), such as
oauth2-proxy, Cloudflare Access or Tailscale. Authenticate is the gate in front of the API."""

from starlette.datastructures import Headers
from starlette.requests import HTTPConnection
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from computer_use.auth.base import Authenticator
from computer_use.auth.none import NoAuthenticator, loopback
from computer_use.auth.proxy import ProxyAuthenticator
from computer_use.auth.token import TokenAuthenticator
from computer_use.config import Settings

__all__ = ["Authenticate", "build_authenticator", "loopback"]

# What changes nothing. Anything else a browser sends only from the page's own origin: a page elsewhere on the same
# site (another app on localhost, a sibling subdomain) gets the cookie too, and a form or a text/plain post from it
# needs no CORS preflight.
SAFE = frozenset({"GET", "HEAD", "OPTIONS"})
OWN = frozenset({"same-origin", "none"})  # Sec-Fetch-Site: the page's own origin, or typed into the address bar


def build_authenticator(settings: Settings) -> Authenticator:
    if settings.auth == "token":
        if settings.auth_token is None or not settings.auth_token.get_secret_value():
            raise ValueError("CU_AUTH=token needs a token (serve.py makes one when CU_AUTH_TOKEN is not set)")
        return TokenAuthenticator(settings.auth_token.get_secret_value())
    if settings.auth == "proxy":
        return ProxyAuthenticator(settings.auth_header, settings.auth_proxies)
    return NoAuthenticator()


class Authenticate:
    """The gate in front of the API: a request it lets through names someone, except to the authenticator's own
    routes, which anyone may call; the rest it answers 401, saying how the page signs in. A browser's request that
    would change something it lets through only from the page's own origin. Plain ASGI, so a stream of events passes
    through untouched."""

    def __init__(self, app: ASGIApp, authenticator: Authenticator):
        self.app = app
        self.authenticator = authenticator
        self.open = frozenset(route.path for route in authenticator.routes)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith("/api/"):
            return await self.app(scope, receive, send)
        site = Headers(scope=scope).get("sec-fetch-site")  # sent by browsers, not by the command line
        if scope["method"] not in SAFE and site is not None and site not in OWN:
            return await JSONResponse({"error": "refused: sent from another site"}, 403)(scope, receive, send)
        if scope["path"] not in self.open:
            identity = self.authenticator.identify(HTTPConnection(scope))
            if identity is None:
                answer = {"error": "sign in first", "login": self.authenticator.login}
                return await JSONResponse(answer, 401)(scope, receive, send)
            scope.setdefault("state", {})["identity"] = identity
        await self.app(scope, receive, send)
