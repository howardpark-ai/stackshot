"""board_home.py: the kept home of the board's root, as the state the server and the publisher share (its cache and its renders are routes/board_pages.py's): the dict, the lock that numbers its generations, and the drop a publish and a write from a page make.

The root page is drawn per request and kept for a moment; a write (or a publish) drops the kept copy, so the next read draws it again. English has one slot (`_BOARD_HOME`), every other language its own (`_BOARD_HOME_OTHER`,
made on first use by `_board_home_slot`). A slot is {at, html, gen, drawn, failed}: `gen` is bumped under `_BOARD_GEN_LOCK` by every drop, so a render that started before the drop is not kept."""
from __future__ import annotations

import threading
from typing import Any

_BOARD_HOME: dict[str, Any] = {"at": 0.0, "html": None, "gen": 0, "drawn": 0, "failed": 0.0}
_BOARD_GEN_LOCK = threading.Lock()
_BOARD_HOME_OTHER: dict[str, dict[str, Any]] = {}      # a language other than English: its own kept home, the same keys as _BOARD_HOME (the English draw is the one above)


def _board_home_slot(lang: str = "en") -> dict[str, Any]:
    """The kept home of `lang`: _BOARD_HOME for English, else the language's own (made on first use)."""
    if lang == "en":
        return _BOARD_HOME
    with _BOARD_GEN_LOCK:
        return _BOARD_HOME_OTHER.setdefault(lang, {"at": 0.0, "html": None, "gen": 0, "drawn": 0, "failed": 0.0})


def _board_home_drop() -> None:
    """The root home is drawn again on its next read (a write happened). A render that started before the drop is not kept. A recent failed draw still holds its back-off: a write
    does not make every request draw again."""
    with _BOARD_GEN_LOCK:
        for slot in (_BOARD_HOME, *_BOARD_HOME_OTHER.values()):
            slot["gen"] += 1
            slot["at"] = 0.0
