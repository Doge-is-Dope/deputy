"""What every way of signing in shares: who a request comes from, and the Authenticator that says so."""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from starlette.requests import HTTPConnection
from starlette.routing import Route

from computer_use.storage import LOCAL_USER

Login = Literal["token", "proxy"]


@dataclass(frozen=True)
class Identity:
    # Letters and digits only, so it is safe in a path or a key whatever the name.
    id: str
    name: str


def identity(kind: str, name: str) -> Identity:
    """The id hashes the way and the name, so two ways naming the same string are two people, and a name with "/" or
    ".." in it never reaches a path."""
    return Identity(hashlib.sha256(f"{kind}:{name}".encode()).hexdigest()[:32], name)


# Neither no sign-in nor the one token names anybody, so both are one local user.
LOCAL = Identity(LOCAL_USER, "Local user")


class Authenticator(Protocol):
    login: Login | None  # None: there is nothing to sign in to
    routes: Sequence[Route]  # anyone may call these: the gate lets their paths through

    def identify(self, request: HTTPConnection) -> Identity | None:
        """Who sent the request, from what it carries; None when it proves nobody, and the runtime answers 401."""
