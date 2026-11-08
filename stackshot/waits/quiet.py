"""quiet.py — what a front agent hears about an item, and the board record that always goes with it.

The pure half: no server import, no clock read, no file. server._front_gate decides and acts; this module writes the line the board keeps.

The board always reaches the owner, and a front agent's turn is only ever extra. So whenever a notice about an item is, or is not, passed to a front agent, the same news is
written onto the item in the same pass, never instead of it: an ordinary progress notice is a History line (`metadata.front_quiet.log`, one line each, "stackshot: …"); a close is the item's own close in
the History; a stuck mark is the item's own record (metadata.wait_failed), which the notice only follows."""
from __future__ import annotations

from typing import Any

KEEP = 8            # the lines an item keeps (the History keeps every one it has shown: it reads the item's revisions)
CLIP = 220          # one line's text


def log_of(meta: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The lines written on an item (metadata.front_quiet.log), oldest first."""
    s = (meta or {}).get("front_quiet")
    return [x for x in ((s or {}).get("log") or []) if isinstance(x, dict)] if isinstance(s, dict) else []


def line(label: str, told: bool, why: str, news: str) -> str:
    """The History line: who was (or was not) told, why, and the news itself (the notice's own words, clipped)."""
    news = " ".join(str(news or "").replace("[stackshot]", " ").split())
    head = f"{label} hears of it on his next turn" if told else f"{label} was not told" + (f" ({why})" if why else "")
    return head + ": " + news


def note(meta: dict[str, Any], now: float, text: str, keep: int = KEEP) -> bool:
    """Write a line onto the item's metadata. → False when the newest line already says it (a notice sent twice is one line)."""
    log = log_of(meta)
    text = " ".join(str(text).split())[:CLIP]
    if log and log[-1].get("text") == text:
        return False
    log.append({"at": now, "text": text})
    meta["front_quiet"] = {"log": log[-keep:]}
    return True


def new_entries(before: dict[str, Any] | None, after: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The lines `after` has that `before` did not (History: one line each)."""
    seen = {(x.get("at"), x.get("text")) for x in log_of(before)}
    return [x for x in log_of(after) if (x.get("at"), x.get("text")) not in seen]
