"""frontdoor_identity.py: the caller's identity, signed by the front door for a backend and checked by the backend (a board).

The front door learns who is calling from a header its reverse proxy sets after the sign-in check. It then calls a backend with its own credential,
which says nothing about the caller, so it adds the caller's identity as a second header the backend can check: the identity and the time it was
signed, under a keyed hash (HMAC-SHA256) of a secret the front door and the backend share.

    value = sign(secret, "alice")           "v1.<identity, base64url>.<seconds since the epoch>.<hex of the hash>"
    verify(secret, value)                   "alice", or None when the value is missing, malformed, altered, signed with another secret, older than
                                            `max_age` seconds, or dated more than MAX_FUTURE seconds ahead of the verifier's clock

Pure functions of their arguments: no file, no clock but the optional `now`, no import outside the standard library. The secret is bytes the
caller has read from its file (`core/frontdoor_files.py: read_secret`); a value that fails to verify is never explained, so a caller learns nothing
about which part was wrong.

This module is in core/ because both ends use it: the front door signs with it (`stackshot/frontdoor/identity.py` re-exports it under its old name) and a
board verifies with it (`core/behind_door.py`); the board server imports nothing of `stackshot/frontdoor/`.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import time

VERSION = "v1"
HEADER = "x-stackshot-identity"      # the header a backend reads the signed identity from
MAX_AGE = 300.0                      # seconds a signed identity is accepted after it was signed
MAX_FUTURE = 30.0                    # seconds a signed time may be ahead of the verifier's clock (clocks of two processes on one box differ by far less)
NOT_MEMBER_CODE = -32003             # the JSON-RPC error code a board refuses a list or a read with when the caller is no member; the front door tells it from a board that is down


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _mac(secret: bytes, body: str) -> str:
    return hmac.new(secret, body.encode("ascii"), hashlib.sha256).hexdigest()


def sign(secret: bytes, identity: str, now: float | None = None) -> str:
    """The signed form of `identity`, dated `now` (the clock's time when None). An empty secret or identity signs nothing: ValueError."""
    if not secret:
        raise ValueError("an empty secret signs nothing")
    if not identity or not identity.strip():
        raise ValueError("an empty identity is not signed")
    body = f"{VERSION}.{_b64(identity.encode('utf-8'))}.{int(time.time() if now is None else now)}"
    return f"{body}.{_mac(secret, body)}"


def verify(secret: bytes, value: str | None, now: float | None = None, max_age: float = MAX_AGE) -> str | None:
    """The identity `value` was signed for, or None. The hash is compared in constant time, before anything else of the value is read."""
    if not secret or not value or not isinstance(value, str):
        return None
    parts = value.split(".")
    if len(parts) != 4 or parts[0] != VERSION:
        return None
    body = ".".join(parts[:3])
    try:
        if not hmac.compare_digest(parts[3].encode("ascii"), _mac(secret, body).encode("ascii")):
            return None
        if not parts[2].isascii() or not parts[2].isdigit():
            return None
        signed = int(parts[2])
        who = _unb64(parts[1]).decode("utf-8")
    except (UnicodeError, ValueError, binascii.Error):
        return None
    t = time.time() if now is None else now
    if t - signed > max_age or signed - t > MAX_FUTURE:
        return None
    return who or None
