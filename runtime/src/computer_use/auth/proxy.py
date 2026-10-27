"""A sign-in proxy in front of the runtime, as Grafana's auth proxy and Open WebUI's trusted header: the proxy signs
the user in (Google, a company's SSO, Tailscale) and names them in a header; the runtime believes that header only
from the proxy's own addresses, since anyone else could set it. The address is the connection's own: serve.py does not
let a forwarded one stand in for it."""

import ipaddress

from starlette.requests import HTTPConnection

from computer_use.auth.base import Identity, identity


class ProxyAuthenticator:
    login = "proxy"
    routes = ()  # the proxy signs in and out

    def __init__(self, header: str, proxies: str):
        self.header = header
        self.proxies = [ipaddress.ip_network(each.strip()) for each in proxies.split(",") if each.strip()]

    def identify(self, request: HTTPConnection) -> Identity | None:
        if request.client is None:
            return None
        try:
            address = ipaddress.ip_address(request.client.host)
        except ValueError:
            return None
        user = request.headers.get(self.header, "").strip()
        return identity("proxy", user) if user and any(address in proxy for proxy in self.proxies) else None
