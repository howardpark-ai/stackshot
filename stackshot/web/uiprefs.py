"""uiprefs.py — a signed-in person's settings for the board's pages at the root, kept on the server so every device they sign in on shows the same thing.

What is stored, in one small JSON file in the state dir (<state>/ui-prefs.json), written atomically (a temporary file, then os.replace), under a lock:

  {"users": {"<signed-in address>": {"panel_order": ["runners", "machines", ...], "panel_open": false}}}

  panel_order  the order of the side panel's sections, as the person last left it. Only a section the person moved is stored; a person who never
               moved one has no entry, and the panel is in its default order (PANEL_SECTIONS).
  panel_open   whether the side panel is open (pinned beside the page) on a wide screen, as the person last left it: the same on every page. The default is open and is
               stored as no key; only a person who closed it has `"panel_open": false`, and opening it again removes the key. A key of any other value reads as open, so a file
               written before this key existed needs no migration. Under 800 px the panel is a drawer that starts closed whatever this says, and the drawer is never stored.

A file that does not parse (or is not a JSON object) is moved aside to ui-prefs.json.bad-<epoch> and the settings start empty; nothing in it is worth
more than the person's next drag. A file that cannot be read at all (any error but "no such file") is a different matter: it may hold other people's orders, so a
save raises (OSError) rather than start empty and write over it, and a read answers the defaults (the default order, open) and writes nothing. Stdlib only; the server writes through
set_panel_order / reset_panel_order / set_panel_open and the page renderer (ui/render.py) reads through panel_order and panel_open (the server's page wrapper reads both in one go, panel_prefs).
Each setting leaves the other and the person's other keys as they are, and a person left with no setting has no entry.

Reading a saved order, `normalize`: names this version does not know and repeated names are dropped; a section the saved list leaves out (one added
since) goes back where it sits by default, right after the section that precedes it in the default order (at the front when none does). So a release that
adds or removes a panel section never needs this file migrated.

Saving, `merge`: the page sends the order of the sections it shows (one it does not draw, the Anchor hub before a receiver has reported, is not in it). Those names
take, in the order sent, the places the stored full order has them in; a section not sent keeps its stored place, so a hidden section's position is not lost."""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from stackshot.core import config as _cfg

# The side panel's sections, in their default order, by the ids the page gives them (Machines, Runners, Anchor hub, Audit, Projects).
PANEL_SECTIONS: tuple[str, ...] = ("machines", "runners", "anchorhub", "audit-panel", "projects-panel")
MAX_NAMES = 32          # a request carries at most this many names (the panel has five): more is refused as malformed
MAX_NAME_LEN = 40
_LOCK = threading.RLock()


def path() -> Path:
    return _cfg.state("ui-prefs.json")


def normalize(order: Any, known: tuple[str, ...] = PANEL_SECTIONS) -> list[str]:
    """A saved order made whole: only known names, each once, in the saved order; a known name the list leaves out is put back after the name that precedes it
    in `known` (first when none does). Anything that is not a list gives the default order."""
    out: list[str] = []
    for n in order if isinstance(order, (list, tuple)) else []:
        if isinstance(n, str) and n in known and n not in out:
            out.append(n)
    for i, n in enumerate(known):
        if n in out:
            continue
        prev = next((p for p in reversed(known[:i]) if p in out), None)
        out.insert(out.index(prev) + 1 if prev is not None else 0, n)
    return out


def merge(stored: Any, sent: Any, known: tuple[str, ...] = PANEL_SECTIONS) -> list[str]:
    """The person's full order after the page sent `sent`, the order of the sections it shows. `stored` is made whole first (normalize). The sent names (known ones, each
    once) take, in the order sent, the places those same names have in the stored order; a section not sent keeps its place. Nothing usable sent leaves it as it is."""
    full = normalize(stored, known)
    names: list[str] = []
    for n in sent if isinstance(sent, (list, tuple)) else []:
        if isinstance(n, str) and n in known and n not in names:
            names.append(n)
    for i, n in zip([i for i, x in enumerate(full) if x in names], names):
        full[i] = n
    return full


def is_default(order: list[str], known: tuple[str, ...] = PANEL_SECTIONS) -> bool:
    return list(order) == list(known)


def _move_aside(p: Path, why: str) -> dict[str, Any]:
    import sys
    bad = p.with_name(f"{p.name}.bad-{int(time.time())}")
    n = 1
    while bad.exists():
        n += 1
        bad = p.with_name(f"{p.name}.bad-{int(time.time())}-{n}")
    try:
        os.replace(p, bad)
        kept = f"moved to {bad.name}"
    except OSError as e:
        kept = f"could not be moved aside ({e.__class__.__name__}: {e})"
    print(f"ui-prefs: {p} {why}; {kept}; starting empty", file=sys.stderr, flush=True)
    return {"users": {}}


def _load() -> dict[str, Any]:
    p = path()
    try:
        text = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"users": {}}
    except UnicodeDecodeError:
        return _move_aside(p, "is not UTF-8 text")
    # any other OSError (permission, I/O, a directory in the way) propagates: the file is there and may hold other people's orders, so it is never read as empty
    try:
        d = json.loads(text)
    except ValueError:
        return _move_aside(p, "does not parse")
    if not isinstance(d, dict):
        return _move_aside(p, "is not a JSON object")
    users = d.get("users")
    return {"users": {str(k): v for k, v in users.items() if isinstance(v, dict)} if isinstance(users, dict) else {}}


def _save(d: dict[str, Any]) -> None:
    """Write the file whole: a temporary file beside it, flushed to disk (fsync) before os.replace, so a crash leaves the old file or the new one and never a half-written
    one; the temporary file is removed when anything fails."""
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=f".{p.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(d, ensure_ascii=False, indent=1) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _tidy(d: dict[str, Any], email: str) -> None:
    """A person left with no setting has no entry."""
    if isinstance(d["users"].get(email), dict) and not d["users"][email]:
        d["users"].pop(email, None)


def _put(d: dict[str, Any], email: str, order: list[str]) -> None:
    """Set the person's entry in the loaded settings; the default order is no entry."""
    if is_default(order):
        u = d["users"].get(email)
        if isinstance(u, dict):
            u.pop("panel_order", None)
            _tidy(d, email)
    else:
        d["users"].setdefault(email, {})["panel_order"] = order


def _put_open(d: dict[str, Any], email: str, is_open: bool) -> None:
    """Set the person's panel state in the loaded settings; open (the default) is no key, closed is `"panel_open": false`."""
    if is_open:
        u = d["users"].get(email)
        if isinstance(u, dict):
            u.pop("panel_open", None)
            _tidy(d, email)
    else:
        d["users"].setdefault(email, {})["panel_open"] = False


def _open_of(entry: Any) -> bool:
    """Open unless the entry says `false` (no key, or a value of any other kind, is the default)."""
    return not (isinstance(entry, dict) and entry.get("panel_open") is False)


def panel_order(email: str) -> list[str]:
    """The person's side-panel order, whole (see normalize); the default order for someone who never moved a section, for nobody signed in, and for a file that cannot be
    read (a read writes nothing, so the file is left as it is)."""
    if not email:
        return list(PANEL_SECTIONS)
    try:
        with _LOCK:
            saved = _load()["users"].get(email, {}).get("panel_order")
    except OSError:
        return list(PANEL_SECTIONS)
    return normalize(saved)


def set_panel_order(email: str, names: Any) -> list[str]:
    """Save the person's order and return the whole order. `names` is what the page sent, the order of the sections it shows; it is merged into the stored full order (see
    merge), so a section the page did not draw keeps its place. An order equal to the default is stored as no entry, so "differs from the default" is only ever a real
    choice. Raises OSError when the file cannot be read or written; nothing is changed then."""
    with _LOCK:
        d = _load()
        order = merge(d["users"].get(email, {}).get("panel_order"), names)
        _put(d, email, order)
        _save(d)
    return order


def reset_panel_order(email: str) -> list[str]:
    """Back to the default order for this person; returns it. Raises OSError like set_panel_order."""
    with _LOCK:
        d = _load()
        _put(d, email, list(PANEL_SECTIONS))
        _save(d)
    return list(PANEL_SECTIONS)


def panel_prefs(email: str) -> tuple[list[str], bool]:
    """The person's side-panel order (whole, see normalize) and whether the panel is open, from one read of the file. The defaults (default order, open) for nobody signed in and for
    a file that cannot be read (a read writes nothing, so the file is left as it is)."""
    if not email:
        return list(PANEL_SECTIONS), True
    try:
        with _LOCK:
            entry = _load()["users"].get(email, {})
    except OSError:
        return list(PANEL_SECTIONS), True
    return normalize(entry.get("panel_order")), _open_of(entry)


def panel_open(email: str) -> bool:
    """Whether the person's side panel is open on a wide screen: True for someone who never closed it, for nobody signed in, for a file with no such key (one written before the
    key existed) and for a file that cannot be read."""
    return panel_prefs(email)[1]


def set_panel_open(email: str, is_open: bool) -> bool:
    """Save whether the person's side panel is open and return it. Open is the default and is stored as no key, so only a real choice (closing it) is on file. Opening a panel that is not stored closed writes nothing. Raises OSError when
    the file cannot be read or written (a read is always needed); nothing is changed then."""
    is_open = bool(is_open)
    with _LOCK:
        d = _load()
        if is_open and _open_of(d["users"].get(email, {})):
            return is_open      # open is the default and nothing is stored: nothing to write (no fsync, and an unwritable file is no error for a no-op)
        _put_open(d, email, is_open)
        _save(d)
    return is_open
