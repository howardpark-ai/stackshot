"""frontdoor_files.py: the files the front door and a board behind it read: a secret file and the members file.

    read_secret(path, ...)   -> the one value in a secret file, or FileError naming the path and the reason (never the content)
    read_members(path)       -> {member: [backend names]} from the members file, read at each call

A secret file is read through one opened descriptor, as a brain's `secret_file` is (`projects/brains.py: secret`): it must be a regular file, private
to its owner (a file group or others can read is refused, the one wording of `core/config.py: secret_mode_text`), at most MAX_BYTES, text whose first
non-empty line is the value, with no control character and at least `min_len` characters. Nothing it holds is ever put in a message or a log.

The readers are in core/ because both ends use them: the front door (`stackshot/frontdoor/config.py` re-exports them) and a board behind it
(`core/behind_door.py`: the board's copy of the signing secret, and its members read from the front door's members file).
"""
from __future__ import annotations

import errno
import json
import os
import stat

from stackshot.core import config as _cfg

MAX_BYTES = 64 * 1024            # a secret or a members file larger than this is refused unread (a secret is a few dozen bytes; a stray big file is no secret)
MIN_SECRET = 16                  # a signing secret, a bearer token or an OAuth client secret shorter than this is not used


class FileError(Exception):
    """A secret or members file cannot be used: the message names the path and the reason, never a value."""


def _read_text(path: str, what: str) -> str:
    p = os.path.expanduser(path)
    try:
        fd = os.open(p, os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0))      # O_NONBLOCK: a FIFO opens without waiting for a writer
    except OSError as e:
        raise FileError(f"{what} {p} cannot be read: {e.strerror or type(e).__name__}") from None
    try:
        st = os.fstat(fd)
        if stat.S_ISDIR(st.st_mode):
            raise FileError(f"{what} {p} cannot be read: {os.strerror(errno.EISDIR)}")
        if not stat.S_ISREG(st.st_mode):
            raise FileError(f"{what} {p} cannot be read: not a regular file")
        if what != "members_file":
            bad = _cfg.secret_mode_text(st.st_mode)
            if bad:
                raise FileError(f"{what} {p} {bad}")
        if st.st_size > MAX_BYTES:
            raise FileError(f"{what} {p} is larger than {MAX_BYTES} bytes, so it is not used")
        data = b""
        while len(data) <= MAX_BYTES:
            chunk = os.read(fd, MAX_BYTES + 1 - len(data))
            if not chunk:
                break
            data += chunk
    except OSError as e:
        raise FileError(f"{what} {p} cannot be read: {e.strerror or type(e).__name__}") from None
    finally:
        os.close(fd)
    if len(data) > MAX_BYTES:
        raise FileError(f"{what} {p} is larger than {MAX_BYTES} bytes, so it is not used")
    try:
        return data.decode("utf-8")
    except ValueError:
        raise FileError(f"{what} {p} cannot be read: not text") from None


def read_secret(path: str, what: str = "secret_file", min_len: int = MIN_SECRET) -> str:
    """The value in the secret file `path`; `what` names the key in a message. FileError when the file cannot be used."""
    raw = _read_text(path, what)
    v = next((ln.strip() for ln in raw.splitlines() if ln.strip()), "")
    if not v:
        raise FileError(f"{what} {os.path.expanduser(path)} is empty")
    if not v.isprintable():
        raise FileError(f"{what} {os.path.expanduser(path)} has an unusable value (a control or other non-printable character)")
    if len(v) < min_len:
        raise FileError(f"{what} {os.path.expanduser(path)} has an unusable value (shorter than {min_len} characters)")
    return v


def read_members(path: str) -> dict[str, list[str]]:
    """{member: [backend names]}: a JSON object whose keys are the members' identities (as the proxy sets the identity header) and whose values are lists of backend names
    (`{"alice": ["a"], "bob": ["a", "b", "brain"]}`). Read at each call, so a change applies to the next request. A member whose value is no list of names is a
    member of nothing. FileError (the error of the file readers here) when the file is missing, too large or not a JSON object: the caller treats that as no one being a member."""
    raw = _read_text(path, "members_file")
    try:
        d = json.loads(raw)
    except ValueError:
        raise FileError(f"members_file {os.path.expanduser(path)} is not valid JSON") from None
    if not isinstance(d, dict):
        raise FileError(f"members_file {os.path.expanduser(path)} is not a JSON object of member -> [boards]")
    return {str(k).strip(): [x.strip() for x in v if isinstance(x, str) and x.strip()] if isinstance(v, list) else [] for k, v in d.items() if str(k).strip()}
