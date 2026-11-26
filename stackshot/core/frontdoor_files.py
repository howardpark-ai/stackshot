"""frontdoor_files.py: the files the front door and a board behind it read: a secret file and the members file.

    read_secret(path, ...)   -> the one value in a secret file, or FileError naming the path and the reason (never the content)
    read_members(path)       -> {member: [backend names]} from the members file, read at each call
    read_member_records(path) -> {member: Member} the same file with each member's aliases and sign-in addresses, no name or address in two members

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
from dataclasses import dataclass

from stackshot.core import config as _cfg
from stackshot.core import members as _members

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


@dataclass(frozen=True)
class Member:
    """One member of the members file: the backends the member is on, the other names a line of a board's `next` may open with, and the sign-in addresses that are this member."""
    boards: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    emails: tuple[str, ...] = ()


def _names(v: object) -> tuple[str, ...]:
    """The strings of a JSON list, white space trimmed, none empty, no repeat; () for anything that is no list."""
    out: list[str] = []
    for x in v if isinstance(v, list) else ():
        if isinstance(x, str) and x.strip() and x.strip() not in out:
            out.append(x.strip())
    return tuple(out)


def _listed(v: object, what: str, said: list[str]) -> tuple[str, ...]:
    """`_names(v)`, with a line in `said` for each entry of the list that is dropped as blank or no text; `what` names such an entry in the line."""
    for x in v if isinstance(v, list) else ():
        if not isinstance(x, str) or not x.strip():
            said.append(f"members_file: {what} is {'blank' if isinstance(x, str) else 'not text'}, so it is not read")
    return _names(v)


def _fold(x: str) -> str:
    """What two names or addresses of the members file are compared by. A name: as a board looks a name up (`members._clean`: white space collapsed, casefolded), so two spellings the lookup reads as one
    name never belong to two members. Text with an `@` is an address: stripped and lower-cased only (casefold would make two distinct addresses one)."""
    return x.strip().lower() if "@" in x else _members._clean(x)


def read_member_records(path: str, notes: list[str] | None = None) -> dict[str, Member]:
    """The members file, `{member: value}`, as records. The key is the member's identity (the name the proxy sets the identity header to, and the name a board stores the person under). The value is
    either a list of backend names (the older form: `"alice@x": ["main", "side"]`, where the key is also the one sign-in address, as written) or an object
    `{"boards": ["main"], "aliases": ["PJ"], "emails": ["pat@x", "pat@y"]}` for a person who signs in with several addresses or is known by another name. The `emails` of an object are kept in lower case
    and each needs an `@`; an object with none and a key written like an address has the key as its address. A value that is neither a list nor an object is a member of nothing.

    No name or address belongs to two members (compared as `_fold` says). A key comes first: of two keys that fold to one only the first is a member. Then, in the file's order, an alias or address that
    another member's key or an earlier member already has is dropped from the later one. An entry on no board (empty `boards`) comes after every member who is on one: it takes no alias or address from
    them, by its key or by its lists. Each thing dropped, a blank alias or address or one that is no text included, is a line appended to `notes`, when one is given; so is a key with a character outside
    printable ASCII (U+0020 to U+007E), which the front door's headers cannot carry (the member cannot sign in through it; the entry is read like any other).
    Read at each call. FileError when the file is missing, too large or not a JSON object: the caller treats that as no one being a member."""
    said = notes if notes is not None else []
    parsed: list[tuple[str, Member]] = []
    keys: dict[str, str] = {}                           # folded key -> the key as written, of the member that has it
    for key, v in _members_object(path):
        if _fold(key) in keys:
            said.append(f"members_file lists {key!r} and {keys[_fold(key)]!r}: they are one name (case and spacing aside), so only the first is a member")
            continue
        keys[_fold(key)] = key
        if any(not " " <= c <= "~" for c in key):
            said.append(f"members_file: the key {key!r} is not printable ASCII, which the front door's headers cannot carry, so that member cannot sign in through it: "
                        f"use an ASCII key and put the other spelling in aliases")
        if isinstance(v, dict):
            emails: list[str] = []
            for e in _listed(v.get("emails"), f"an entry of the emails of {key!r}", said):
                if "@" in e:
                    emails.append(e.lower())
                else:
                    said.append(f"members_file: an entry of the emails of {key!r} has no @, so it is not read")
            if not emails and "@" in key:
                emails = [key]
            aliases = _listed(v.get("aliases"), f"an alias of {key!r}", said)
            parsed.append((key, Member(_names(v.get("boards")), aliases, tuple(dict.fromkeys(emails)))))
        else:
            parsed.append((key, Member(_names(v), (), (key,))))
    owner: dict[str, str] = {}                          # folded name or address -> the key of the member that has it

    def own(key: str, values: tuple[str, ...], what: str) -> tuple[str, ...]:
        kept = []
        for x in values:
            if owner.setdefault(_fold(x), key) == key:
                kept.append(x)
            else:
                said.append(f"members_file: {what} of {key!r} is already {owner[_fold(x)]!r}'s, so it is not read for {key!r}")
        return tuple(kept)

    done: dict[str, Member] = {}
    on_a_board = [(k, m) for k, m in parsed if m.boards]
    on_none = [(k, m) for k, m in parsed if not m.boards]
    for group in (on_a_board, on_none):                 # members on a board claim first, so an entry on no board takes nothing from them
        for key, _m in group:
            owner.setdefault(_fold(key), key)           # the keys of a group before any alias or address of it
        for key, m in group:
            done[key] = Member(m.boards, own(key, m.aliases, "an alias"), own(key, m.emails, "an address"))
    return {key: done[key] for key, _m in parsed}       # in the file's order


def _members_object(path: str) -> list[tuple[str, object]]:
    """The (key, value) pairs of the members file in its order, a key trimmed and none empty. FileError as `read_member_records` says."""
    raw = _read_text(path, "members_file")
    try:
        d = json.loads(raw)
    except ValueError:
        raise FileError(f"members_file {os.path.expanduser(path)} is not valid JSON") from None
    if not isinstance(d, dict):
        raise FileError(f"members_file {os.path.expanduser(path)} is not a JSON object of member -> [boards]")
    return [(str(k).strip(), v) for k, v in d.items() if str(k).strip()]


def read_members(path: str) -> dict[str, list[str]]:
    """{member: [backend names]}: a JSON object whose keys are the members' identities (as the proxy sets the identity header) and whose values are lists of backend names
    (`{"alice": ["a"], "bob": ["a", "b", "brain"]}`), or objects with a `boards` list (`read_member_records`). Read at each call, so a change applies to the next request. A member whose value is no list of
    names is a member of nothing. Every key as the file has it (the front door looks an identity up exactly). FileError when the file is missing, too large or not a JSON object: the caller treats that as no one being a member."""
    return {k: list(_names(v.get("boards") if isinstance(v, dict) else v)) for k, v in _members_object(path)}


def member_of_address(records: dict[str, Member], address: str) -> str:
    """The member (the key of `records`) whose sign-in address is `address` (compared without regard to case), or "" when none has it or `address` is no address."""
    a = str(address or "").strip().lower()
    if "@" not in a:
        return ""
    for k, m in records.items():
        if a in (e.lower() for e in m.emails):
            return k
    return ""
