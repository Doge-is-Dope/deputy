"""No sign-in: anyone who reaches the runtime is its local user. serve.py serves this way only on the loopback address,
unless CU_AUTH=none is set in so many words, which says only this machine can reach the address all the same."""

import ipaddress

from starlette.requests import HTTPConnection

from computer_use.auth.base import LOCAL, Identity


class NoAuthenticator:
    login = None
    routes = ()

    def identify(self, request: HTTPConnection) -> Identity:
        return LOCAL


def loopback(host: str) -> bool:
    """Whether an address to serve on is reachable from this machine only."""
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"
