"""machines_list.py: `POST /client/machines`, the machine list the fleet manager posts, and the last good one kept on disk.

The fleet manager knows which machines a fleet has (their names, hosts, addresses and roles); the server does not. It posts the list when the list changes and at least every few minutes, so `written` is the list's
age. The body is one JSON object:

    {"schema": 1, "written": <epoch s>,
     "machines": [{"name", "hostname", "letter", "ssh", "addresses": [ipv4 or ipv6 text, ...], "roles": ["sala-host" | "stackshot-host", ...], "retired": true | false, "sources": [text, ...]}, ...],
     "not_read": [file name, ...]}

Limits (a body that breaks one is refused whole with 400 and one line of reason; nothing is clipped): `schema` is the JSON number 1; `written` is a finite epoch in seconds, not before 2020 and not more than `AHEAD_S` ahead
of the server's clock; `machines` at most `MACHINES_MAX` objects, no two with the same `name` once cleaned and case-folded; `name` is required text of 1 to `NAME_MAX` characters once cleaned, and so is `hostname` when it is
not empty or null: each holds at least one letter, digit, punctuation mark or symbol (a name of combining marks or spaces alone would draw as nothing; a `hostname` that is blank (empty, white space or control and format characters only) is stored as "", as a retired machine has none); `letter` and `ssh` are text of at most `TEXT_MAX` characters or null (or left out);
`addresses` at most `ADDRESSES_MAX` texts of at most `ADDRESS_MAX` characters (they are kept as text and not parsed as addresses); `roles` at most `ROLES_MAX` entries, each one of `ROLES`; `retired` is required and
true or false; `sources` at most `SOURCES_MAX` texts of at most `TEXT_MAX` characters; `not_read` at most `NOT_READ_MAX` texts of at most `TEXT_MAX` characters. A text is cleaned before it is counted and kept:
every control and format character (and the characters that draw as nothing) is taken out and runs of white space become one space. A key this module does not know is ignored and never stored. A body is read to at most `MAX_BYTES` bytes; the route
refuses a larger one with 413 before it parses anything (`too_large`).

Only what was validated and cleaned is stored, as text and never escaped: a reader shows every field as text only and builds no link, command or markup from one. The file is `<paths.state>/machines-list.json` (mode 0600),
written whole to a temporary file beside it, flushed to disk, renamed over the old one and the folder flushed, so a reader sees the last list or the new one, never half of one, and a power loss keeps one of them. It carries `schema`, `written`, `received` (the server's clock at the post), `posted_by` (the machine the token proved) and the list. A post that is refused never touches it: the last
good list stays. The file also carries `high`, the highest `written` ever accepted (the high-water mark; a file without it, from an earlier version, counts its own `written`). A post whose `written` is more than `NEWER_S` older than the
mark is a late arrival of an older list: it is answered 200 `{"ok": true, "kept": "newer"}` and the stored list stays (within `NEWER_S` of the mark, as when the sender's clock stepped back, the new post replaces, and the mark
stays where it was, so a run of posts each a little older than the last cannot walk the list back: every one is compared with the newest ever accepted, never with the one before it). A mark further ahead of the server's clock than `AHEAD_S` (a hand-edited file, a clock set right since) counts as `AHEAD_S` ahead, so one wrong clock cannot hold out true posts, and the next accepted post writes the corrected mark. `last_machines()` reads the file back through a bounded read (a regular file of at most `READ_MAX` bytes, opened without blocking and without following a
link) and answers None for no file or one that cannot be read as a list; it never raises and never blocks. Deciding how old a list may be before it is shown is the reader's, from `written` and `received`.

A service module: it imports core and the standard library only. The route that calls it (`_client_post`) is the surface's."""
from __future__ import annotations

import errno
import json
import math
import os
import re
import stat
import threading
import time
import unicodedata
from pathlib import Path
from typing import Any

from stackshot.core import config as _cfg
from stackshot.core import readonly as _ro

VERB = "machines"           # the /client/<verb> the sender calls
FILE = "machines-list.json"     # in <paths.state>
SCHEMA = 1
MAX_BYTES = 1_000_000       # a body over this is refused (413) before it is parsed
ROLES = ("sala-host", "stackshot-host")
MACHINES_MAX, NAME_MAX, TEXT_MAX = 200, 80, 200
ADDRESSES_MAX, ADDRESS_MAX, ROLES_MAX, SOURCES_MAX, NOT_READ_MAX = 16, 64, 4, 20, 200
WRITTEN_MIN = 1577836800.0  # Jan 1st 2020: a list dated before it is no list of this fleet
AHEAD_S = 60.0              # `written` may be at most this far ahead of the server's clock (a sender's clock that runs a little fast)
NEWER_S = 300.0             # a post is kept out when the highest `written` ever stored (the high-water mark) is more than this newer than its own (an older list that arrived late); within it the post replaces (a clock that stepped back)
READ_MAX = MAX_BYTES + 65536    # `last_machines()` reads no more than this: the body cap and a margin for the fields the server adds
NUMBER_MAX = 1e12           # a time past this, or not finite, is no time; converting a huge integer raises OverflowError
STALE_TMP_S = 3600.0        # a leftover temporary file older than this is removed by the next write
_BLANK_LOOKING = frozenset(map(chr, (0x3164, 0x115F, 0x1160, 0x2800, 0xFFA0)))      # the Hangul fillers and the braille blank: they draw as nothing
_TMP = re.compile(r"^\.machines-list\.json\.\d+\.\d+\.tmp$")      # the name `_write` gives its temporary file, and no other
_LOCK = threading.Lock()      # per process: it makes the read of the mark and the replacement of the file one step among this process's threads; two server processes on one state folder would not share it


NOT_OBJECT = "the body is a JSON object, not a list, text, number, true, false or null"


def path() -> Path:
    return _cfg.state(FILE)


def too_large(length: Any) -> str:
    """The refusal (one line) for a body of `length` bytes (an int, or a Content-Length header's text), "" when it is within `MAX_BYTES` or cannot be read as a length."""
    try:
        n = int(length)
    except (TypeError, ValueError):
        return ""
    return f"the body is {n} bytes, over the {MAX_BYTES}-byte limit" if n > MAX_BYTES else ""


def _num(v: Any) -> float | None:
    """A finite number that is no bool and no larger than `NUMBER_MAX` in size, else None (a huge integer cannot be converted to a float: OverflowError, which would be a 500, is None here)."""
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except OverflowError:
        return None
    return f if math.isfinite(f) and abs(f) <= NUMBER_MAX else None


def _clean(v: Any) -> str | None:
    """The text as one plain line: every control and format character (C0 and C1 controls, bidi and zero-width marks) taken out, runs of white space made one space, the ends trimmed. None when `v` is no
    string or holds a lone surrogate (no text a file can keep)."""
    if not isinstance(v, str):
        return None
    try:
        v.encode("utf-8")
    except UnicodeEncodeError:
        return None
    return " ".join("".join(ch if ch.isspace() else ("" if unicodedata.category(ch)[0] == "C" or ch in _BLANK_LOOKING else ch) for ch in v).split())


def _draws(t: str) -> bool:
    """Does the text hold a character that draws something: a letter, digit, punctuation mark or symbol (Unicode categories L, N, P, S)? Combining marks and spaces alone draw nothing."""
    return any(unicodedata.category(ch)[0] in "LNPS" for ch in t)


def _is_blank(v: str) -> bool:
    """Is the raw text empty, white space or control and format characters only (what a sender means by "no value")? A filler that draws as nothing (`_BLANK_LOOKING`) is no blank: `_clean` takes it out, but it was sent as a value."""
    return all(ch.isspace() or unicodedata.category(ch)[0] == "C" for ch in v)


def _text(v: Any, cap: int, what: str, *, null: bool = False, need: bool = False, draws: bool = False) -> tuple[str | None, str]:
    """(the cleaned text, "") or (None, why it is refused). `null`: None (or a missing key, which the caller passes as None) is allowed and answers (None, ""). `need`: the text must not be empty once cleaned.
    `draws`: a text that is not blank (empty, white space, or control and format characters only: `_is_blank`) must hold a character that draws something (`_draws`); a blank one is allowed and stays "" (add `need` to refuse it)."""
    if v is None and null:
        return None, ""
    t = _clean(v)
    if t is None:
        return None, f"{what} is text" + (" or null" if null else "")
    if len(t) > cap:
        return None, f"{what} is at most {cap} characters"
    if need and not t:
        return None, f"{what} is text of 1 to {cap} characters"
    if draws and not _is_blank(v) and not _draws(t):
        return None, f"{what} needs a letter, digit, punctuation mark or symbol (combining marks and spaces alone draw as nothing)"
    return t, ""


def _texts(v: Any, count: int, cap: int, what: str) -> tuple[list[str] | None, str]:
    """(a list of cleaned texts, "") or (None, why it is refused). A missing list (None) is empty."""
    if v is None:
        return [], ""
    if not isinstance(v, list):
        return None, f"{what} is a list of text"
    if len(v) > count:
        return None, f"{what} holds at most {count} entries"
    out = []
    for i, x in enumerate(v):
        t, why = _text(x, cap, f"{what}[{i}]")
        if t is None:
            return None, why
        out.append(t)
    return out, ""


def _machine(i: int, m: Any) -> tuple[dict[str, Any] | None, str]:
    """(one machine entry, cleaned and with only the keys this module knows, "") or (None, why the body is refused)."""
    where = f"machines[{i}]"
    if not isinstance(m, dict):
        return None, f"{where} is no object"
    name, why = _text(m.get("name"), NAME_MAX, f"{where}.name", need=True, draws=True)
    if name is None:
        return None, why
    out: dict[str, Any] = {"name": name}
    for key in ("hostname", "letter", "ssh"):
        t, why = _text(m.get(key), TEXT_MAX, f"{where}.{key}", null=True, draws=key == "hostname")
        if why:
            return None, why
        out[key] = t
    addresses, why = _texts(m.get("addresses"), ADDRESSES_MAX, ADDRESS_MAX, f"{where}.addresses")
    if addresses is None:
        return None, why
    roles = m.get("roles")
    if roles is None:
        roles = []
    if not isinstance(roles, list) or len(roles) > ROLES_MAX or not all(isinstance(r, str) and r in ROLES for r in roles):
        return None, f"{where}.roles is a list of at most {ROLES_MAX} of: " + ", ".join(ROLES)
    if not isinstance(m.get("retired"), bool):
        return None, f"{where}.retired = true or false"
    sources, why = _texts(m.get("sources"), SOURCES_MAX, TEXT_MAX, f"{where}.sources")
    if sources is None:
        return None, why
    out.update(addresses=addresses, roles=list(dict.fromkeys(roles)), retired=m["retired"], sources=sources)
    return out, ""


def validate(body: Any, now: float | None = None) -> tuple[dict[str, Any] | None, str]:
    """(the list to store: {schema, written, machines, not_read}, "") or (None, the one-line reason the body is refused)."""
    if not isinstance(body, dict):
        return None, NOT_OBJECT
    schema = body.get("schema")
    if type(schema) is not int or schema != SCHEMA:     # the JSON number 1: not 1.0, not true
        return None, f"schema = {SCHEMA} (the JSON number {SCHEMA})"
    written = _num(body.get("written"))
    if written is None or written < WRITTEN_MIN or written > (time.time() if now is None else now) + AHEAD_S:
        return None, "written = the epoch second the list was made: a finite number, not before 2020 and not more than a minute ahead of the server's clock"
    machines = body.get("machines")
    if not isinstance(machines, list):
        return None, "machines = a list of machine objects"
    if len(machines) > MACHINES_MAX:
        return None, f"machines holds at most {MACHINES_MAX} machines"
    out = []
    names: dict[str, int] = {}
    for i, m in enumerate(machines):
        norm, why = _machine(i, m)
        if norm is None:
            return None, why
        key = norm["name"].casefold()
        if key in names:
            return None, f"machines[{i}].name repeats machines[{names[key]}].name (names are compared ignoring case)"
        names[key] = i
        out.append(norm)
    not_read, why = _texts(body.get("not_read"), NOT_READ_MAX, TEXT_MAX, "not_read")
    if not_read is None:
        return None, why
    return {"schema": SCHEMA, "written": written, "machines": out, "not_read": not_read}, ""


def _sweep(folder: Path) -> None:
    """Remove the leftover temporary files of earlier writes in `folder` that are older than `STALE_TMP_S`: a regular file only (a link is never followed, nor removed), named exactly as the writer names its temporary
    file. A failure on one file is no failure of the write."""
    try:
        entries = list(os.scandir(folder))
    except OSError:
        return
    cut = time.time() - STALE_TMP_S
    for e in entries:
        try:
            if _TMP.match(e.name) and e.is_file(follow_symlinks=False) and e.stat(follow_symlinks=False).st_mtime < cut:
                os.unlink(e.path)
        except OSError:
            continue


def _fsync_dir(folder: Path) -> None:
    """Flush the folder's entry for the renamed file to disk. The new list is already in place by now, so a folder that cannot be flushed (a filesystem that does not support it) is no failure of the write."""
    try:
        fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _write(rec: dict[str, Any]) -> None:
    """The record whole to a temporary file beside the file (mode 0600, created new and never through a link), flushed to disk, then renamed over it (never half of one) and the folder flushed, so the list survives a power
    loss as the last list or the new one; the temporary file is removed on a failure."""
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    _sweep(p.parent)
    tmp.unlink(missing_ok=True)      # a leftover of this very name (a reused pid and thread): removed, never written through
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            os.fchmod(f.fileno(), 0o600)      # whatever the umask says
            f.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
        _fsync_dir(p.parent)
    finally:
        tmp.unlink(missing_ok=True)


def post(machine: str, body: Any) -> tuple[int, dict[str, Any]]:
    """`POST /client/machines` -> (status, JSON): 200 `{ok, machines}` when the list replaced the last one, 200 `{ok, kept: "newer"}` when the high-water mark (the highest `written` ever accepted) is more than `NEWER_S` newer than this one's (the
    stored list stays; a post with a fresh `written` is always accepted, an unchanged re-post of an old list is kept out until its `written` is newer than the mark minus `NEWER_S`), 400 `{error}` for a body it refuses (the last list stays), 503 on a standby copy or a file that cannot be written. `machine` is the one the token proved; it is stored as `posted_by`."""
    if _ro.is_read_only():
        return 503, {"error": _ro.REFUSAL}
    lst, why = validate(body)
    if lst is None:
        return 400, {"error": why}
    now = time.time()
    rec = {"schema": SCHEMA, "written": lst["written"], "received": now, "posted_by": str(machine), "high": lst["written"], "machines": lst["machines"], "not_read": lst["not_read"]}
    with _LOCK:     # reading the stored mark and replacing the file are one step
        high = _high_water(now)
        if high is not None:
            if high - lst["written"] > NEWER_S:
                return 200, {"ok": True, "kept": "newer"}
            rec["high"] = max(high, lst["written"])
        try:
            _write(rec)
        except OSError as e:
            return 503, {"error": f"the list could not be written ({e.__class__.__name__}); the last one stays"}
    return 200, {"ok": True, "machines": len(rec["machines"])}


def _read_stored() -> bytes | None:
    """The stored file's bytes, or None when it is absent, no regular file (a pipe, a device, a folder, a link) or larger than `READ_MAX`. Opened without blocking and without following a link, and read no further than
    `READ_MAX` bytes whatever the file turns out to be."""
    try:
        fd = os.open(path(), os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_NOCTTY)
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > READ_MAX:
            return None
        chunks, size = [], 0
        while size <= READ_MAX:
            try:
                chunk = os.read(fd, min(65536, READ_MAX + 1 - size))
            except OSError as e:
                if e.errno == errno.EINTR:
                    continue
                return None
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        return b"".join(chunks) if size <= READ_MAX else None
    finally:
        os.close(fd)


def _high_water(now: float) -> float | None:
    """The highest `written` ever accepted, as the stored file records it (a file without `high` counts its own `written`), held to at most `AHEAD_S` ahead of `now`; None when there is no readable list."""
    cur = _load()
    if cur is None:
        return None
    rec, _ = cur
    return min(rec["high"], now + AHEAD_S)      # `_load` has already made it at least the list's own `written`


def last_machines() -> tuple[dict[str, Any], float] | None:
    """(the last good list, when the server received it as epoch seconds), or None when there is none or the file cannot be read as one (absent, torn, not an object, another schema, a field of the wrong kind, no regular file,
    larger than `READ_MAX`). The list is {schema, written, posted_by, machines, not_read}. Never raises and never blocks (a pipe at the path is None)."""
    cur = _load()
    if cur is None:
        return None
    rec, received = cur
    return {k: v for k, v in rec.items() if k != "high"}, received


def _load() -> tuple[dict[str, Any], float] | None:
    """`last_machines()`'s read, with the high-water mark in the record as `high` (a missing or unreadable one is the list's own `written`)."""
    try:
        raw = _read_stored()
        if raw is None:
            return None
        d = json.loads(raw.decode("utf-8"))
        if not isinstance(d, dict) or d.get("schema") != SCHEMA:
            return None
        received, written = _num(d.get("received")), _num(d.get("written"))
        machines, not_read, by = d.get("machines"), d.get("not_read"), d.get("posted_by")
        if received is None or written is None or not isinstance(by, str):
            return None
        if not isinstance(machines, list) or not all(isinstance(m, dict) for m in machines) or not isinstance(not_read, list):
            return None
        high = _num(d.get("high"))
        return {"schema": SCHEMA, "written": written, "posted_by": by, "machines": machines, "not_read": not_read, "high": written if high is None else max(high, written)}, received
    except Exception:       # a file that cannot be read, a torn one, a path the config cannot give: no list, never an error
        return None
