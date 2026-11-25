"""backend.py: the backends as the front door calls them.

A call to a board or a brain leaves the front door through a transport built here, and nothing of the caller's request goes with it:

  * the backend's headers are set by this transport and no other: the front door's own credential (`Authorization: Bearer <token_file>`, or an OAuth
    access token the SDK's client-credentials provider asks for with the two client files and the scopes) under the lower-case key `authorization`,
    and the caller's identity, signed (`identity.sign`), under `identity.HEADER`;
  * `forward_incoming_headers=False`: the transport options FastMCP passes to a proxy's transport say not to copy the inbound request's headers, so the
    caller's own Authorization, X-Api-Key, Cookie and the rest stay at the front door.

`Backends` also holds the health of each backend: an open GET of its health URL, cached for `health_cache_seconds`.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import ssl
import urllib.parse
from dataclasses import replace
from typing import Any

from fastmcp.client.auth import ClientCredentialsOAuthProvider
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.client.transports.base import TransportOptions
from fastmcp.server.providers.proxy import ProxyClient

from stackshot.core.frontdoor_config import Backend, Settings
from stackshot.frontdoor import config as _config, identity as _identity

log = logging.getLogger("stackshot.frontdoor")
HEALTH_TIMEOUT = 5.0         # most seconds a health check waits for a backend (never longer than the backend_timeout_seconds of the config)


async def _status_of(url: str, timeout: float = HEALTH_TIMEOUT) -> int:
    """The HTTP status of a GET of `url`, read from the status line (an error status is a status; a refused connection or no answer in `timeout`
    seconds raises OSError). `timeout` is a total deadline for the connection, the request and the status line together, kept with
    `asyncio.wait_for` on a plain socket, so a backend that drips its answer one byte at a time is given up on at the deadline and nothing waits on
    after it (no worker thread is held). The backend is reached directly, never through an HTTP_PROXY of the environment, and a redirect is not
    followed: its status is the answer."""
    async def get() -> int:
        u = urllib.parse.urlsplit(url)
        tls = u.scheme == "https"
        host = u.hostname or ""
        reader, writer = await asyncio.open_connection(
            host, u.port or (443 if tls else 80), ssl=ssl.create_default_context() if tls else None, server_hostname=host if tls else None)
        try:
            path = urllib.parse.quote(u.path or "/", safe="/%:@!$&'()*+,;=~-._") + (("?" + urllib.parse.quote(u.query, safe="/%:@!$&'()*+,;=~-._?")) if u.query else "")
            who = f"[{host}]" if ":" in host else host
            writer.write(f"GET {path} HTTP/1.1\r\nHost: {who}{':' + str(u.port) if u.port else ''}\r\nAccept: */*\r\nConnection: close\r\n\r\n".encode("ascii"))
            await writer.drain()
            line = await reader.readline()
        finally:
            writer.close()
        parts = line.split(None, 2)
        if len(parts) < 2 or not parts[0].startswith(b"HTTP/") or not parts[1].isdigit():
            raise OSError("not an HTTP answer")
        return int(parts[1])
    return await asyncio.wait_for(get(), timeout)


class BackendTransport(StreamableHttpTransport):
    """The transport of one connection to a backend: a new inner transport, with this backend's headers only."""

    def __init__(self, backend: Backend, headers: dict[str, str], auth: Any = None):
        super().__init__(backend.url)
        self._backend_url = backend.url
        self._headers = headers
        self._auth = auth

    @contextlib.asynccontextmanager
    async def connect_session(self, *, transport_options: TransportOptions | None = None, **kw: Any):
        inner = StreamableHttpTransport(self._backend_url, headers=self._headers, auth=self._auth)
        opts = replace(transport_options or TransportOptions(), forward_incoming_headers=False)
        async with inner.connect_session(transport_options=opts, **kw) as session:
            yield session


class Backends:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.by_name: dict[str, Backend] = {b.name: b for b in settings.backends}
        self._oauth: dict[str, tuple[tuple[str, str, str], ClientCredentialsOAuthProvider]] = {}
        self._health: dict[str, tuple[float, dict[str, Any]]] = {}

    # ------------------------------------------------------------------ calling a backend

    def _headers(self, b: Backend, caller: str) -> tuple[dict[str, str], Any]:
        """(the backend's headers, its OAuth provider or None) for a call made for `caller`; the files are read now, so a rotated secret applies at once."""
        hdr: dict[str, str] = {}
        auth = None
        cred = _config.credentials(b)
        if b.oauth:
            key = (cred["client_id"], cred["client_secret"], cred["scopes"])
            have = self._oauth.get(b.name)
            if have is None or have[0] != key:
                have = (key, ClientCredentialsOAuthProvider(client_id=key[0], client_secret=key[1], scopes=key[2] or None))
                self._oauth[b.name] = have
            auth = have[1]
        else:
            hdr["authorization"] = "Bearer " + cred["token"]
        if self.settings.identity_secret_file:
            secret = _config.read_secret(self.settings.identity_secret_file, "identity_secret_file")
            hdr[_identity.HEADER] = _identity.sign(secret.encode("utf-8"), caller)
        return hdr, auth

    def client(self, name: str, caller: str, bound_handshake: bool = False) -> ProxyClient:
        """A client of the backend `name`, whose connection carries the front door's credential and `caller`'s signed identity.

        `bound_handshake`: the connection and the initialize handshake give up after backend_timeout_seconds (a call of a tool is given no total limit, since
        a tool may run long and report progress; a caller that lists or reads instructions bounds the whole use with `asyncio.wait_for` instead)."""
        b = self.by_name[name]
        hdr, auth = self._headers(b, caller)
        kw = {"init_timeout": self.settings.backend_timeout_seconds} if bound_handshake else {}
        return ProxyClient(BackendTransport(b, hdr, auth), mode="legacy", **kw)

    # ------------------------------------------------------------------ health

    async def health(self, name: str, force: bool = False) -> dict[str, Any]:
        """{"ok", "status" or "error", "ms", "kind"} of the backend `name`: a cached answer younger than health_cache_seconds, else a new GET of its health URL
        (`force`: always a new one, for the check that follows a failed call)."""
        have = self._health.get(name)
        if have and not force and time.monotonic() - have[0] < self.settings.health_cache_seconds:
            return have[1]
        b = self.by_name[name]
        t0 = time.monotonic()
        try:
            status = await _status_of(b.health_url, min(HEALTH_TIMEOUT, self.settings.backend_timeout_seconds))
            res: dict[str, Any] = {"ok": status == 200, "status": status}
        except Exception as e:      # noqa: BLE001  (any failure of the check is the backend not answering)
            res = {"ok": False, "error": type(e).__name__}
        res["ms"] = int((time.monotonic() - t0) * 1000)
        res["kind"] = b.kind
        self._health[name] = (time.monotonic(), res)
        return res

    async def health_all(self) -> dict[str, dict[str, Any]]:
        res = await asyncio.gather(*(self.health(n) for n in self.by_name))
        return dict(zip(self.by_name, res))
