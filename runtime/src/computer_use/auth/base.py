"""What every way of signing in shares: who a request comes from, and the Authenticator that says so from what the
request carries. Each way is a module of its own (auth.none, auth.token, auth.proxy); another plugs in the same."""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from starlette.requests import HTTPConnection
from starlette.routing import Route

from computer_use.storage import LOCAL_USER

# How the page signs in, as a runtime that turns it away says: with the token's link, or at the proxy in front.
Login = Literal["token", "proxy"]


@dataclass(frozen=True)
class Identity:
    # What the runtime will know them by, e.g. to keep each user's conversations apart: letters and digits only, so
    # it is safe in a path or a key whatever the name, and the same each time they come.
    id: str
    name: str  # as the page shows it


def identity(kind: str, name: str) -> Identity:
    """Someone a way of signing in names: their id is a hash of the way and the name it gave, so two ways naming the
    same string are still two people, and a name with "/" or ".." in it never reaches a path."""
    return Identity(hashlib.sha256(f"{kind}:{name}".encode()).hexdigest()[:32], name)


# Whoever reaches a runtime with no sign-in, or has its one token: neither names anybody, so they are one local user,
# the same whichever of the two the runtime runs with.
LOCAL = Identity(LOCAL_USER, "Local user")


class Authenticator(Protocol):
    login: Login | None  # None: there is nothing to sign in to
    routes: Sequence[Route]  # its own signing in and out, which anyone may call: the gate lets their paths through

    def identify(self, request: HTTPConnection) -> Identity | None:
        """Who sent the request, from what it carries; None when it proves nobody, and the runtime answers 401."""
