"""The runtime's entry point: serve the HTTP API that every client reaches it through, the web page, the command line
(clients/cli) and the eval alike."""

import argparse
import asyncio
import secrets
import sys

import uvicorn
from pydantic import SecretStr

from computer_use.auth import loopback
from computer_use.config import Settings, get_settings
from computer_use.server import create_app

# Default model-call budget per desktop task; a message's max_steps overrides it.
MAX_STEPS = 60


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="computer-use-runtime", description="Serve the runtime's HTTP API.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    return parser


def open_to_anyone(settings: Settings, host: str) -> str | None:
    """Why the runtime will not serve with no sign-in on an address other machines can reach, as Codex's app-server
    will not listen beyond the loopback address without auth; None when it will. Setting CU_AUTH=none in so many words
    says the address is reachable only from this machine all the same, as a container's port published on the
    host's loopback address is (compose.yaml)."""
    if settings.auth != "none" or loopback(host) or "auth" in settings.model_fields_set:
        return None
    return (f"Refusing to serve {host} with no sign-in: set CU_AUTH=token with CU_AUTH_TOKEN, or CU_AUTH=proxy behind a "
            "sign-in proxy; or CU_AUTH=none if only this machine can reach that address.")


def signed_in_link(settings: Settings) -> tuple[Settings, str]:
    """The settings with a token, a new one each start unless CU_AUTH_TOKEN keeps one, and the page's link that signs
    in with it, as Jupyter prints its own: the token after "#", which a browser never sends, so no server or proxy
    logs it; the page takes it from there (clients/web, lib/session.ts)."""
    if settings.auth_token is None or not settings.auth_token.get_secret_value():
        settings = settings.model_copy(update={"auth_token": SecretStr(secrets.token_urlsafe(32))})
    return settings, f"{settings.web_url.rstrip('/')}/#token={settings.auth_token.get_secret_value()}"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    if refused := open_to_anyone(settings, args.host):
        print(refused, file=sys.stderr)
        return 2
    if settings.auth == "token":
        settings, link = signed_in_link(settings)
        print(f"Sign in: {link}", flush=True)
    app = create_app(settings, MAX_STEPS)
    try:
        # proxy_headers off: uvicorn would otherwise take a proxy's X-Forwarded-For for the connection's address, and a
        # sign-in proxy's header is believed only from the proxy's own (auth.proxy).
        config = uvicorn.Config(app, host=args.host, port=args.port, access_log=False, proxy_headers=False)
        asyncio.run(uvicorn.Server(config).serve())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
