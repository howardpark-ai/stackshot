"""colorcombos.py — the saved color combinations of the shared color tool (shared/colortool.js), kept on the server so the board's page and the fleet tool's web page show one list.

What is stored: one small JSON file in the state dir, written atomically (a temporary file, then os.replace) under a lock:

  {"combos": [{"id": "<8 hex>", "name": "...", "values": {<the 14 keys>: "#rrggbb"}, "saved": <epoch seconds>, "via": "board" | "sala-web"}, ...]}

One list for the whole instance (it is the owner's, whichever of their addresses signed in), oldest first; no address is stored. It is not part of ui-prefs.json on purpose:
uiprefs rewrites that file from the settings it knows, so a foreign top-level key would be dropped at the next panel-order save.

The 14 keys, all required in a saved combination (an app fills a field the person never set with the shipped value before it saves):
  bg page background · card cards · fg body text · mut muted text · line lines · ibd button outlines · link text and links · solid solid fills · onsolid text on solid fills ·
  labbg small label fill · labfg small label text · labbd small label outline · disbg disabled fill · disfg disabled text.
A value is "#rrggbb" in lowercase hex (it is lowercased when sent in capitals); no "#rgb", no alpha, no functional notation, no color names. The server runs no contrast check: the app that
applies a combination checks it and names the failing pair.

A name is Unicode NFC, stripped, 1 to 40 characters, with no control, format or line-separator character (Unicode categories Cc, Cf, Zl, Zp), and unique when case is ignored: a save under a name the list already has replaces that
combination (same id and place, new values, time and via). The list holds at most 50 (Full). `via` records who saved it: "board" (the board's own page) or "sala-web" (the fleet
tool's web server).

A file that does not parse (or is not a JSON object) is moved aside to color-combos.json.bad-<epoch> and the list starts empty; a list of saved colors is worth less than the next
save. When it cannot be moved aside either, it stays and the case is the next one. A file that cannot be read at all (any error but "no such file") raises OSError, which the routes answer 503: it is never read as empty and written over. An entry of a
file that parses but is not a whole combination is left out when the list is read. Single server process, as uiprefs (no flock). Stdlib only."""
from __future__ import annotations

import json
import os
import re
import secrets as _secrets
import sys
import tempfile
import threading
import time
import unicodedata
from pathlib import Path
from typing import Any

from stackshot.core import config as _cfg

KEYS: tuple[str, ...] = ("bg", "card", "fg", "mut", "line", "ibd", "link", "solid", "onsolid", "labbg", "labfg", "labbd", "disbg", "disfg")
WEB_LABEL = "sala-web"      # the `sender` label of the fleet tool's web server, which is also what `via` records for its saves
VIAS: tuple[str, ...] = ("board", WEB_LABEL)
MAX_COMBOS = 50
NAME_MAX = 40
BODY_MAX = 4096          # a request body, in bytes (a combination is about 0.5 KB)
_HEX = re.compile(r"#[0-9a-f]{6}")
_ID = re.compile(r"[0-9a-f]{8}")
_LOCK = threading.RLock()
_NAME_REFUSED = frozenset({"Cc", "Cf", "Zl", "Zp"})     # Unicode categories a name never holds: controls (C0, DEL, C1), format characters (zero-width, bidi marks and overrides), line and paragraph separators


class Invalid(ValueError):
    """A name or values that cannot be saved. `field` is the name of the failing key, or "name" / "values" / "id", for the answer to point at."""

    def __init__(self, message: str, field: str | None = None):
        super().__init__(message)
        self.field = field


class Full(Exception):
    """The list already holds MAX_COMBOS combinations and the save is for a new name."""


def path() -> Path:
    return _cfg.state("color-combos.json")


def clean_name(name: Any) -> str:
    """The name as it is kept: NFC, stripped. Invalid (field "name") unless a string of 1 to NAME_MAX characters without a control, format or line-separator character."""
    if not isinstance(name, str):
        raise Invalid("name = a text of 1 to 40 characters", "name")
    n = unicodedata.normalize("NFC", name).strip()
    if not n or len(n) > NAME_MAX:
        raise Invalid(f"name = a text of 1 to {NAME_MAX} characters", "name")
    if any(unicodedata.category(c) in _NAME_REFUSED for c in n):
        raise Invalid("name has a control or invisible formatting character (a tab, a line break, a zero-width space, say)", "name")
    return n


def clean_values(values: Any) -> dict[str, str]:
    """The values as they are kept: exactly the 14 keys, each lowercase "#rrggbb". Invalid (field = the failing key) otherwise."""
    if not isinstance(values, dict):
        raise Invalid("values = an object with the 14 color keys", "values")
    extra = sorted(str(k) for k in values if k not in KEYS)
    if extra:
        raise Invalid(f"{extra[0][:40]!r} is not a color key", extra[0][:40])
    for k in KEYS:
        if k not in values:
            raise Invalid(f"{k} is missing: all 14 colors are needed", k)
    out: dict[str, str] = {}
    for k in KEYS:
        v = values[k]
        if not isinstance(v, str) or not _HEX.fullmatch(v.lower()):
            raise Invalid(f"{k} = a color as six hex digits, like #1a2b3c", k)
        out[k] = v.lower()
    return out


def validate(name: Any, values: Any) -> tuple[str, dict[str, str]]:
    """(name, values) as they would be kept, or Invalid. The name is judged first."""
    return clean_name(name), clean_values(values)


def _whole(e: Any) -> dict[str, Any] | None:
    """An entry of the file as a whole combination, None when it is not one."""
    if not isinstance(e, dict):
        return None
    try:
        name, values = validate(e.get("name"), e.get("values"))
    except Invalid:
        return None
    eid, saved, via = e.get("id"), e.get("saved"), e.get("via")
    if not (isinstance(eid, str) and _ID.fullmatch(eid) and isinstance(saved, (int, float)) and not isinstance(saved, bool) and via in VIAS):
        return None
    return {"id": eid, "name": name, "values": values, "saved": int(saved), "via": via}


def _move_aside(p: Path, why: str) -> list[dict[str, Any]]:
    bad = p.with_name(f"{p.name}.bad-{int(time.time())}")
    n = 1
    while bad.exists():
        n += 1
        bad = p.with_name(f"{p.name}.bad-{int(time.time())}-{n}")
    try:
        os.replace(p, bad)
    except OSError as e:
        # the corrupt file stays where it is and the list is not read as empty: a save would write over it, so this is the unreadable case (the routes answer 503)
        print(f"color-combos: {p} {why}; could not be moved aside ({e.__class__.__name__}: {e}); left as it is", file=sys.stderr, flush=True)
        raise OSError(e.errno, f"{p.name} {why} and could not be moved aside: {e.strerror or e}") from e
    print(f"color-combos: {p} {why}; moved to {bad.name}; starting empty", file=sys.stderr, flush=True)
    return []


def _load() -> list[dict[str, Any]]:
    p = path()
    try:
        text = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except UnicodeDecodeError:
        return _move_aside(p, "is not UTF-8 text")
    # any other OSError (permission, I/O, a directory in the way) propagates: the file is there and may hold the list, so it is never read as empty and written over
    try:
        d = json.loads(text)
    except ValueError:
        return _move_aside(p, "does not parse")
    if not isinstance(d, dict):
        return _move_aside(p, "is not a JSON object")
    combos = d.get("combos")
    out: list[dict[str, Any]] = []
    for e in combos if isinstance(combos, list) else []:
        w = _whole(e)
        if w is not None and w["id"] not in {x["id"] for x in out} and w["name"].casefold() not in {x["name"].casefold() for x in out}:
            out.append(w)
    return out[:MAX_COMBOS]


def _save(combos: list[dict[str, Any]]) -> None:
    """Write the file whole: a temporary file beside it, flushed to disk (fsync) before os.replace, so a crash leaves the old file or the new one and never a half-written one;
    the temporary file is removed when anything fails."""
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=f".{p.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps({"combos": combos}, ensure_ascii=False, indent=1) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def listing() -> list[dict[str, Any]]:
    """The saved combinations, oldest first. OSError when the file cannot be read."""
    with _LOCK:
        return _load()


def payload(combos: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """What the routes answer: {"combos": [...], "max": 50}."""
    return {"combos": listing() if combos is None else combos, "max": MAX_COMBOS}


def save(name: Any, values: Any, via: str) -> list[dict[str, Any]]:
    """Keep a combination and answer the whole list. A name the list already has (case ignored) is replaced in its place with its id kept. Invalid for a bad name or values,
    Full for a new name when the list holds MAX_COMBOS, OSError when the file cannot be read or written (nothing is changed then). `via` is one of VIAS."""
    if via not in VIAS:
        raise ValueError(f"via = one of {VIAS}")
    name, values = validate(name, values)
    with _LOCK:
        combos = _load()
        now = int(time.time())
        hit = next((c for c in combos if c["name"].casefold() == name.casefold()), None)
        if hit is not None:
            hit.update(name=name, values=values, saved=now, via=via)
        else:
            if len(combos) >= MAX_COMBOS:
                raise Full("the list is full, delete one")
            ids = {c["id"] for c in combos}
            cid = _secrets.token_hex(4)
            while cid in ids:
                cid = _secrets.token_hex(4)
            combos.append({"id": cid, "name": name, "values": values, "saved": now, "via": via})
        _save(combos)
        return combos


def delete(cid: Any) -> list[dict[str, Any]]:
    """Drop the combination with this id and answer the whole list. An id the list does not have is no error (it is already gone): the list as it is, nothing written.
    Invalid (field "id") unless the id is a text of 1 to 64 characters. OSError when the file cannot be read or written."""
    if not isinstance(cid, str) or not 1 <= len(cid) <= 64:
        raise Invalid("id = a saved combination's id", "id")
    with _LOCK:
        combos = _load()
        keep = [c for c in combos if c["id"] != cid]
        if len(keep) != len(combos):
            _save(keep)
        return keep
