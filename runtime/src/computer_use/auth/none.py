"""No sign-in: anyone who reaches the runtime by this machine's own name is its local user. serve.py serves this way
only on the loopback address, unless CU_AUTH=none is set explicitly."""

import ipaddress
from urllib.parse import urlsplit

from starlette.requests import HTTPConnection

from computer_use.auth.base import LOCAL, Identity


class NoAuthenticator:
    login = None
    routes = ()

    def identify(self, request: HTTPConnection) -> Identity:
        return LOCAL


def loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


def named_here(host: str) -> bool:
    """Whether a request's Host header names this machine. A page elsewhere whose name was pointed at this machine
    (DNS rebinding) sends its own name, and with no sign-in nothing else tells it apart."""
    try:
        return loopback(urlsplit(f"//{host}").hostname or "")
    except ValueError:  # e.g. "[::1" with no "]"
        return False
