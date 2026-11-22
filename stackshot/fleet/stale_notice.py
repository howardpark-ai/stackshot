"""stale_notice.py: the screen a queued notice passes before it is delivered.

A notice about an item (a stall reminder, a wake, "a wait ended", a hand-off that was not taken) is true when it is sent and may not be any more when it is
delivered: a session that was away, or a box that was moved, takes it hours or weeks later, and by then the item may be closed, parked again, or someone
else's. Two queues hold such notices until their session can take them, and both call `screen` right before they hand lines out:
the per-session push queue (`push.flush`, <hub state dir>/queue-msg/<session>.jsonl) and the server's inbox (`inbox.take`).

A line the screen recognizes as one of those automatic notices (`classify`: it opens with the server's own `[stackshot]` mark and has one of the known shapes,
so a message another session wrote is never touched) is dropped when
  * it is older than `[client] stale_notice_hours` (default 6; 0 turns the expiry off);
  * every item it names is closed;
  * every item it names has been parked again since (a stall, wake or hand-off notice says the item is the recipient's to move now);
  * every item it names has another session as its mover since (the recipient is neither the mover, nor its `then`, nor named in its needs);
  * a newer line of the same kind names the same items: the older ones collapse into it.
Whatever the screen cannot read (an item that is missing, a store that does not open, a recipient it cannot tell from the mover, an item the owner or no one moves, a time that is no number) is kept: a notice is delivered
unless the screen can say it is no longer true. Lines of no known shape pass through unchanged.

Standard library plus the package's own config; the item store and the registry are read lazily and a failure of either keeps the line."""
from __future__ import annotations

import json
import re
import time
from typing import Any, Callable, Iterable

from stackshot.core import config as _cfg

DEFAULT_HOURS = 6.0
_HEAD = re.compile(r"^(?:\[for [^\]\n]{1,60}\]\s*)?\[stackshot\] ")     # the server's own notices; a session's message opens "[stackshot message]"
KINDS: tuple[tuple[str, "re.Pattern[str]"], ...] = (
    ("handoff-sender", re.compile(r"hand-offs? of yours (?:was|were) not taken")),
    ("stall", re.compile(r"you have had no turn running for")),
    ("handoff", re.compile(r"\bit came to you:|\bitems came to you, the sessions")),
    ("wake", re.compile(r"\bis yours now: |\bitems are yours now, their waits ended|\bwoke \(wake |\b(?:reminder|backstop) \(wake |\bitems? (?:woke|came due) for you|\bbackstops came due for you")),
)
MOVE_KINDS = ("stall", "wake", "handoff")           # the notice says the item is the recipient's to move now: a parked or reassigned item makes it false
_ITEM = re.compile(r"(?<![\w#/-])(board(?:-tmp-[a-z0-9][a-z0-9-]*)?)#([1-9][0-9]*)\b")
_STILL_AFTER = re.compile(r"still after .*?out of the queue until it closes", re.S)      # a wake's own wording for the items an item is queued behind: those are not what it is about


def hours() -> float:
    """`[client] stale_notice_hours`: how long a queued notice stays worth delivering (default 6; 0 = no expiry; anything that is not a number is the default)."""
    try:
        v = float(_cfg.get("client", "stale_notice_hours", default=DEFAULT_HOURS))
    except (TypeError, ValueError):
        return DEFAULT_HOURS
    return v if v >= 0 else DEFAULT_HOURS


def classify(text: Any) -> tuple[str, list[str]]:
    """(kind, the items it names as shown, once each) of an automatic notice, ("", []) for anything else."""
    t = str(text or "")
    if not _HEAD.match(t):
        return "", []
    for kind, pat in KINDS:
        if pat.search(t):
            body = _STILL_AFTER.sub("", t.lower())
            return kind, list(dict.fromkeys(f"{m.group(1)}#{m.group(2)}" for m in _ITEM.finditer(body)))
    return "", []


def _item(shown: str) -> dict[str, Any] | None:
    """The stored item a shown id names, None when it cannot be read (an unknown id, a missing file, a store that is not there)."""
    try:
        from stackshot.core import store as _cstore
        from stackshot.github import ghsync as _gh
        g = _gh.norm(shown)
        if not g:
            return None
        g = _gh.resolve(g)
        d = json.loads((_cstore.STORE / g[0] / f"{g[1:]}.json").read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else None
    except Exception:  # noqa: BLE001  — a notice is kept when the screen cannot read the item
        return None


def _keys(who: Iterable[str]) -> set[str]:
    """Every way a session is written (its names, its transcript and permanent ids), lower-cased."""
    ks = {str(w).strip() for w in who if str(w or "").strip()}
    try:
        from stackshot.fleet import sessions_registry as _sr
        ks = _sr.expand(ks)
    except Exception:  # noqa: BLE001
        pass
    return {k.lower() for k in ks}


def _is_theirs(item: dict[str, Any], rec: set[str]) -> bool | None:
    """Is the recipient still a session the item is for: its mover, its `then`, or named in its needs. None when the item stores no mover, or the owner or none (the model's default and the project's builder decide who is told, which the screen does not read)."""
    meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    mover = str(meta.get("mover") or "").strip()
    if not mover or not rec:
        return None
    try:
        from stackshot.model import model as _model
        if _model.is_owner(mover) or mover.lower() == "none":      # the owner moves it: its notices go to the project's builder, who is neither mover, `then` nor in its needs, so it cannot be told from here
            return None
    except Exception:  # noqa: BLE001
        return None
    needs = meta.get("needs")
    named = [mover, str(meta.get("then") or "")] + ([str(n) for n in needs] if isinstance(needs, list) else [])
    return any(_keys([n]) & rec for n in named if n.strip())


def _why_stale(kind: str, text: str, items: list[dict[str, Any]], rec: set[str]) -> str:
    """Why every one of these items makes the notice untrue, "" when any does not."""
    reasons: list[str] = []
    for it in items:
        meta = it.get("metadata") if isinstance(it.get("metadata"), dict) else {}
        if it.get("status") != "open":
            reasons.append("its item is closed"); continue
        if kind in MOVE_KINDS:
            if (meta.get("phase") == "waiting" or meta.get("hold")) and "still after" not in text.lower():
                reasons.append("its item was parked again"); continue
            if _is_theirs(it, rec) is False:
                reasons.append("its item has another mover now"); continue
        return ""
    return reasons[0] if reasons else ""


def screen(rows: list[dict[str, Any]], recipient: Iterable[str] = (), now: float | None = None, hours_: float | None = None,
           load: Callable[[str], dict[str, Any] | None] | None = None) -> tuple[list[dict[str, Any]], list[tuple[dict[str, Any], str]]]:
    """Split queued lines (dicts with `text` and a time, `ts` or `t`) into what is still worth delivering and what is not, each dropped line with the reason.
    `recipient`: the names and ids of the session they are for. The order of the kept lines is the order they came in; of several lines that say the same
    thing the newest is kept. → (keep, [(row, why)])."""
    now = time.time() if now is None else now
    cutoff = (hours() if hours_ is None else hours_) * 3600
    read = load or _item
    rec = _keys(recipient)
    cache: dict[str, dict[str, Any] | None] = {}
    drop: dict[int, str] = {}
    live: list[tuple[int, tuple[Any, ...]]] = []
    for i, row in enumerate(rows):
        kind, shown = classify(row.get("text"))
        if not kind:
            continue
        ts = _ts(row, now)
        if cutoff and now - ts > cutoff:
            drop[i] = f"older than {cutoff / 3600:g} hours"; continue
        items = []
        for s in shown:
            if s not in cache:
                cache[s] = read(s)
            if cache[s] is not None:
                items.append(cache[s])
        why = _why_stale(kind, str(row.get("text") or ""), items, rec) if items else ""     # type: ignore[arg-type]
        if why:
            drop[i] = why; continue
        live.append((i, (kind, tuple(sorted(shown)) or " ".join(str(row.get("text") or "").split()))))
    newest: dict[tuple[Any, ...], int] = {}
    for i, key in live:
        if key in newest:
            drop[newest[key]] = "a newer notice says the same"
        newest[key] = i
    return [r for i, r in enumerate(rows) if i not in drop], [(rows[i], w) for i, w in sorted(drop.items())]


def _ts(row: dict[str, Any], now: float) -> float:
    """When a line was queued; `now` (its age is unreadable, so it is kept) when the time is missing or not a number."""
    try:
        return float(row.get("ts", row.get("t", now)) or now)
    except (TypeError, ValueError):
        return now


def expired(row: dict[str, Any], now: float | None = None, hours_: float | None = None) -> bool:
    """Is this line an automatic notice older than the cutoff (for a line that waits with no session to take it, where the state of its items is not read)."""
    cutoff = (hours() if hours_ is None else hours_) * 3600
    now = time.time() if now is None else now
    return bool(cutoff and classify(row.get("text"))[0] and now - _ts(row, now) > cutoff)
