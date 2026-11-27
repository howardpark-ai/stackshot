"""board_home.py: the kept home of the board's root, as the state the server and the publisher share (its cache and its renders are routes/board_pages.py's): the dict, the lock that numbers its generations, and the drop a publish and a write from a page make.

The root page is drawn per request and kept for a moment; a write (or a publish) drops the kept copy, so the next read draws it again. The cache is keyed by the language and the viewer, the signed-in
member of a board of several members ("" for the page every member shares: one member, nobody signed in, a sign-in that is no member). With no viewer, English has one slot (`_BOARD_HOME`) and every
other language its own (`_BOARD_HOME_OTHER`); a viewer's slots are `_BOARD_HOME_VIEWERS`, at most `_VIEWER_SLOTS_MAX` of them, the one used longest ago going first. All are made on first use by
`_board_home_slot`. A slot is {at, html, gen, drawn, failed}: `gen` is bumped under `_BOARD_GEN_LOCK` by every drop, so a render that started before the drop is not kept."""
from __future__ import annotations

import collections
import contextlib
import contextvars
import threading
from typing import Any, Iterator

_BOARD_HOME: dict[str, Any] = {"at": 0.0, "html": None, "gen": 0, "drawn": 0, "failed": 0.0}
_BOARD_GEN_LOCK = threading.Lock()
_BOARD_HOME_OTHER: dict[str, dict[str, Any]] = {}      # a language other than English: its own kept home, the same keys as _BOARD_HOME (the English draw is the one above)
_BOARD_HOME_VIEWERS: "collections.OrderedDict[tuple[str, str], dict[str, Any]]" = collections.OrderedDict()      # (language, viewer) -> that member's kept home, the one used longest ago first
_VIEWER_SLOTS_MAX = 32

_VIEWER: contextvars.ContextVar[str] = contextvars.ContextVar("stackshot_home_viewer", default="")


def viewer() -> str:
    """The member the request's home is drawn for, "" for the shared page."""
    return _VIEWER.get()


@contextlib.contextmanager
def use_viewer(name: str) -> Iterator[None]:
    """Draw and read the home of the member `name` for the code run inside (the server wraps a request in it)."""
    tok = _VIEWER.set(name or "")
    try:
        yield
    finally:
        _VIEWER.reset(tok)


def _new_slot() -> dict[str, Any]:
    return {"at": 0.0, "html": None, "gen": 0, "drawn": 0, "failed": 0.0}


def _board_home_slot(lang: str = "en", who: str = "") -> dict[str, Any]:
    """The kept home of `lang` for the viewer `who`: with no viewer _BOARD_HOME for English, else the language's own; a viewer's own slot otherwise (all made on first use)."""
    if not who and lang == "en":
        return _BOARD_HOME
    with _BOARD_GEN_LOCK:
        if not who:
            return _BOARD_HOME_OTHER.setdefault(lang, _new_slot())
        slot = _BOARD_HOME_VIEWERS.get((lang, who))
        if slot is None:
            while len(_BOARD_HOME_VIEWERS) >= _VIEWER_SLOTS_MAX:
                _BOARD_HOME_VIEWERS.popitem(last=False)
            slot = _BOARD_HOME_VIEWERS[(lang, who)] = _new_slot()
        else:
            _BOARD_HOME_VIEWERS.move_to_end((lang, who))
        return slot


def _board_home_drop() -> None:
    """The root home is drawn again on its next read (a write happened). A render that started before the drop is not kept. A recent failed draw still holds its back-off: a write
    does not make every request draw again."""
    with _BOARD_GEN_LOCK:
        for slot in (_BOARD_HOME, *_BOARD_HOME_OTHER.values(), *_BOARD_HOME_VIEWERS.values()):
            slot["gen"] += 1
            slot["at"] = 0.0
