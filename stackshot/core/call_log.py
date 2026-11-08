"""call_log.py — the count of board writes the server refused, and the small corrections it made instead of refusing.

The server writes one line per call of a counted write tool (create, update, complete, confirm, message) to `<paths.state>/calls/<YYYY-MM>.jsonl`:

    {"t": epoch seconds, "tool": "update", "ok": true}                                          the call went through
    {"t": …, "tool": "update", "ok": true, "fix": ["wake", "item-id"]}                           it went through after the server corrected a field itself (see `fixed`)
    {"t": …, "tool": "update", "ok": false, "item": "board#N", "sender": "my-x", "why": "…"}    the server refused it (the ToolError's text, whitespace folded, clipped)

`tools/refusal_report.py` reads these lines for its weekly report. The call's other arguments are never logged: a description, a draft or a said line stays out.

A correction (`fixed`) is a pure fact the server can put right without a judgment: a bare item number read as the board id, a wake with seconds or a UTC offset read as the
instance time, a subject with no scope prefix given the one its project's scope names. The server stores the corrected field, adds one line to the reply saying what it did
(`reply_note`), and counts it here. A mover who disagrees sends the field again as they want it and the server leaves it alone.

Stdlib only; the config is read through config.py at each use."""
from __future__ import annotations

import contextvars
import datetime as dt
import json
import re
import threading
import time
from pathlib import Path
from typing import Any, Iterator

from stackshot.core import config as _cfg

COUNTED = ("create", "update", "complete", "confirm", "message")      # the write tools whose calls are counted
WHY_MAX = 300                                                         # characters of a refusal's text kept

_FIXES: contextvars.ContextVar[list[tuple[str, str]] | None] = contextvars.ContextVar("call_log_fixes", default=None)
_LOCK = threading.Lock()


def begin() -> "contextvars.Token[list[tuple[str, str]] | None]":
    """Start collecting the corrections of one tool call (the middleware calls this before the tool runs)."""
    return _FIXES.set([])


def end(token: "contextvars.Token[list[tuple[str, str]] | None]") -> list[tuple[str, str]]:
    """Stop collecting → the corrections the call made, [(kind, the line that tells it)] in order, each kind once."""
    got = _FIXES.get() or []
    _FIXES.reset(token)
    seen: set[str] = set()
    return [(k, n) for k, n in got if not (k in seen or seen.add(k))]


def fixed(kind: str, note: str) -> None:
    """The server corrected a field of the call that is running (no call running: nothing is recorded, as for a stored value read at a start)."""
    got = _FIXES.get()
    if got is not None:
        got.append((kind, note))


def reply_note(fixes: list[tuple[str, str]]) -> str:
    """The text appended to a reply that carries corrections; "" for none."""
    if not fixes:
        return ""
    return "\n(fixed for you: " + "; ".join(n for _, n in fixes) + ". To keep a field as you wrote it, send it again as you want it.)"


def _file(now: float) -> Path:
    return _cfg.state("calls") / (dt.datetime.fromtimestamp(now, _cfg.tz()).strftime("%Y-%m") + ".jsonl")


def record(tool: str, ok: bool, *, item: str = "", sender: str = "", why: str = "", fixes: list[tuple[str, str]] | None = None, now: float | None = None) -> None:
    """Append the line of one call. Never raises: a log line is not worth a lost reply."""
    if tool not in COUNTED:
        return
    t = time.time() if now is None else now
    row: dict[str, Any] = {"t": int(t), "tool": tool, "ok": bool(ok)}
    if fixes:
        row["fix"] = [k for k, _ in fixes]
    if not ok:
        row["item"] = re.sub(r"\s+", " ", str(item or "")).strip()[:40]
        row["sender"] = re.sub(r"\s+", " ", str(sender or "")).strip()[:80]
        why = re.sub(r"\s+", " ", str(why or "")).strip()
        row["why"] = why if len(why) <= WHY_MAX else why[:WHY_MAX - 1].rstrip() + "…"
    try:
        p = _file(t)
        with _LOCK:
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    except Exception:  # noqa: BLE001 — a log line is never worth a lost reply
        pass


def read(since: float, until: float) -> Iterator[dict[str, Any]]:
    """The lines with since <= t < until, oldest file first. A line that does not parse is skipped."""
    z = _cfg.tz()
    a, b = dt.datetime.fromtimestamp(since, z), dt.datetime.fromtimestamp(max(until - 1, since), z)
    months, y, m = [], a.year, a.month
    while (y, m) <= (b.year, b.month):
        months.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    for name in months:
        p = _cfg.state("calls") / f"{name}.jsonl"
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for ln in lines:
            try:
                row = json.loads(ln)
            except ValueError:
                continue
            if isinstance(row, dict) and isinstance(row.get("t"), (int, float)) and since <= row["t"] < until:
                yield row


# ---------------------------------------------------------------------------------------------------------------- what a refusal says, as a kind
_KINDS: tuple[tuple[str, str], ...] = (
    (r"next no longer lists", "a step left out of next with no done or dropped"),
    (r"description bullet is \d+ characters", "a description bullet over its limit"),
    (r"description has \d+ lines", "a description over its line limit"),
    (r"the description must open with its goal", "a description that does not open with its goal"),
    (r"description contains '", "a changelog word in a description"),
    (r"a line of next is \d+ characters", "a line of next over its limit"),
    (r"the subject is \d+ characters", "a subject over its limit"),
    (r"subject must start with", "a subject without a scope prefix"),
    (r"ask must read|this ask has a Decide part|needs an ask line", "an ask in the wrong form"),
    (r"Refused: option \d+ ", "an option without its label and line"),
    (r"Refused: said[\[:]", "a said entry in the wrong form"),
    (r"wait on another item's close has no end|wait on news only .* relays has no end", "a wait on another item with no end date"),
    (r"wait_basis", "a wait_basis the rule does not take"),
    (r"metadata\.wake must be", "a wake in the wrong form"),
    (r"bad item id", "an item id in the wrong form"),
    (r"waits on a time .* with no reason|a wait on your own item needs its reason|clock pushed out", "a wait set without its reason"),
    (r"needs names more than one mover", "needs naming more than one mover"),
    (r"reword: step", "a reword of another session's step"),
    (r"leaves .* open with no open step|new item has no open step", "an open item left with no open step"),
    (r"user-facing agent|not a background agent|this update hands ", "a front agent named as mover"),
    (r"state is a retired input|ranks are retired", "a retired input"),
    (r"pass sender=", "no sender"),
)
_KIND_RX = tuple((re.compile(p, re.I), name) for p, name in _KINDS)


def kind_of(why: str) -> str:
    """A refusal's text → the kind it is counted under: a named kind of _KINDS, else the text with its ids and numbers folded to 'N' and cut at 70 characters."""
    t = str(why or "")
    for rx, name in _KIND_RX:
        if rx.search(t):
            return name
    t = re.sub(r"^Refused:\s*", "", t)
    t = re.sub(r"board(?:-tmp-[\w-]+)?#\d+", "ID", t)
    return re.sub(r"\d+", "N", t)[:70].rstrip()
