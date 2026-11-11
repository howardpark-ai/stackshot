"""home.py — the home page's three lists on the item model (the design: docs/design, section 8, and
its build plan, step 3).

Every open item is exactly one of alive or waiting (model.py), so it sits in exactly one of three lists:

  your-move   alive, and the owner is the mover: oldest first (the age is how long it has been his; the board paints it amber past two days and red past five)
  agents      alive, and a session or the project's background agent is the mover: oldest first by the age the row shows (the longest-running item leads); the mover's name is on the row and plays no part in the order
  waiting     waiting on a time, an anchor's event, another item's close or news only the owner relays: by end date

This module is the pure half: which list an item is in, the row's immediate next step (the first `next` line, its `<mover>: ` prefix stripped), when its state began, the
age's colour, who watches a wait, the sorts. The HTML is render.py's (Board.home_html). Pure functions of items, the model's reading and a clock: no server import, so the
board, the project pages and the tests share one copy."""
from __future__ import annotations

import re
from typing import Any, Callable

from stackshot.web import i18n as _i18n
from stackshot.waits import handoff as _ho
from stackshot.model import model as _model
from stackshot.model import model_guards as _mg
from stackshot.waits import waiting as _wt

YOUR_MOVE, AGENTS, WAITING = "your-move", "agents", "waiting"
LISTS = (YOUR_MOVE, AGENTS, WAITING)
AMBER_S = 2 * 86400.0          # Your move: the age turns amber past two days
RED_S = 5 * 86400.0
WATCHED_BY = {"time": "the scheduler", "relay": "the scheduler", "anchor": "the anchor module", "item": "the server", "event": "the server"}      # model section 4's table: who notices the wake event      # i18n: skip  (English keys of watcher_word, which routes them)
_FAR = float("inf")


def list_of(mod: "_model.Model") -> str:
    """Which list an open item is in, from the model's reading: waiting → Waiting; alive with the owner as the mover → Your move; any other alive item → Agents at work.
    A dead item is in none ("")."""
    if mod.state == _model.WAITING:
        return WAITING
    if mod.state == _model.ALIVE:
        return YOUR_MOVE if _model.is_owner(mod.mover) else AGENTS
    return ""


def wait_words(mod: "_model.Model") -> str:
    """The kind of a wait in words, as board.md and the brief say it ("a time", "an anchor event", "another item's close", "news only <owner> relays", "a fleet event"): the model's own KIND_WORDS. "" for an item that is not waiting."""
    if mod.state != _model.WAITING or mod.wait is None:
        return ""
    return _model.KIND_WORDS.get(mod.wait.kind, "").format(owner=_model.owner_display())


def is_mover_name(name: str, known: tuple = ()) -> bool:
    """Is the text before a next line's colon a mover (so the row drops it) and not part of the step ("Check the result: it works", "follow-up: call her", "Step 1: ...")? The owner,
    or a name the caller knows: the item's mover, owner and post-wake mover as stored and as the board names them, and the fleet's session names. No shape rule: a hyphenated
    word is not a session."""
    n = _model.clean(name)
    if not n:
        return False
    return _model.is_owner(n) or n.casefold() in {_model.clean(k).casefold() for k in known if k}


def first_next(text: Any, known: tuple = ()) -> tuple[str, str]:
    """(the mover named before the colon, the step) of the first `next` line: the line without its list marker and its bold marks, and with a fenced block and a parenthesised server
    note left out. The `<name>: ` opener is stripped only when it names the owner or a known mover (is_mover_name); any other prefix stays in the step and the name is "". ("", "") when the item has no
    next line."""
    lines = _mg.next_openers(text)
    if not lines:
        return "", ""
    line, name = lines[0]
    if name and is_mover_name(name, known):
        return name, _mg._line_content(line)
    return "", _mg._MARK_RX.sub("", line.strip().replace("**", "")).strip()


def watched_by(kind: str) -> str:
    """Who notices the end of a wait of this kind: the scheduler (a time, a relay's ask-by day), the anchor module, the server (another item's close)."""
    return WATCHED_BY.get(kind, "the scheduler")


_WATCHERS = {"the scheduler": "home.watcher.scheduler", "the anchor module": "home.watcher.anchor", "the server": "home.watcher.server"}      # WATCHED_BY's English words → the string table's keys


def watcher_word(english: str) -> str:
    """Who watches a wait, in the request's language (the string table; the English word when it has no key)."""
    return _i18n.t(_WATCHERS[english]) if english in _WATCHERS else english


def age_class(seconds: float) -> str:
    """"red" past five days, "amber" past two, "" before: the nag of the Your move list, a colour and nothing else."""
    return "red" if seconds > RED_S else "amber" if seconds > AMBER_S else ""


def _num(v: Any) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def since(item: dict[str, Any], mod: "_model.Model", same: Callable[[Any, Any], bool] = lambda a, b: _model.clean(a).lower() == _model.clean(b).lower()) -> float:
    """When the row's state began (epoch seconds): the item's state clock (state_updated, else its last update, else the render's own `_updated`); and, for an alive item, when it
    was handed to its mover or woke into the mover's hands, if that is later (a hand-off to the owner is when it became his). 0 when nothing is known."""
    ts = _num(item.get("state_updated")) or _num(item.get("updated"))
    if not ts and item.get("_updated") is not None:
        try:
            ts = item["_updated"].timestamp()
        except AttributeError:
            ts = _num(item.get("_updated"))
    if mod.state == _model.ALIVE and mod.mover:
        meta = item.get("metadata") or {}
        ho = _ho.record_of(item)
        if ho and same(ho.get("to"), mod.mover):
            ts = max(ts, _num(ho.get("at")))
        w = meta.get("woke")
        if isinstance(w, dict) and w.get("what") and same(w.get("to"), mod.mover):
            ts = max(ts, _num(w.get("at")))
    return ts


def end_of(mod: "_model.Model") -> str | None:
    """The stored date (YYYY-MM-DD, or with THH:MM) a wait ends on: a time wait's wake (or a verifying item's end date), a relay's ask-by day, an item or anchor wait's backstop; None when it has none
    or the stored text is no date. The one reader of a wait's end: the Waiting sort (end_epoch) and the end date a Waiting row shows (ui/render.py home_row) both read it, so they cannot disagree."""
    w = mod.wait
    if not w:
        return None
    v = w.until if w.kind in ("time", "relay") and w.until else w.backstop if w.backstop else None
    return v if v and _wt.wake_epoch(v) is not None else None


def end_epoch(mod: "_model.Model") -> float:
    """When a wait ends, for the sort (end_of as an epoch); far away when it has none."""
    v = end_of(mod)
    return _FAR if v is None else _wt.wake_epoch(v)


def classify(rows: list[dict[str, Any]], derive: Callable[[dict[str, Any]], "_model.Model"]) -> dict[str, list[tuple[dict[str, Any], "_model.Model"]]]:
    """The open rows split into the three lists, each row with its model reading: {your-move: [(row, model)], agents: […], waiting: […]}, in the rows' own order (the sorts are
    below). Every open row lands in exactly one list; a row whose reading fails is read as an alive item of the agents (never dropped: an item that cannot be read is still one)."""
    out: dict[str, list[tuple[dict[str, Any], _model.Model]]] = {k: [] for k in LISTS}
    for r in rows:
        if r.get("status") == "completed":
            continue
        try:
            mod = derive(r)
            which = list_of(mod)
        except Exception:  # noqa: BLE001
            mod, which = _model.Model(_model.ALIVE), ""
        if not which:
            mod, which = _model.Model(_model.ALIVE), AGENTS
        out[which].append((r, mod))
    return out


def sort_your_move(pairs: list[tuple[dict[str, Any], "_model.Model"]], tie: Callable[[dict[str, Any]], Any], same: Callable[[Any, Any], bool] | None = None) -> list[tuple[dict[str, Any], "_model.Model"]]:
    """Oldest first: the item that has been his longest leads. `tie` orders items of one age (the board's due-date order)."""
    kw = {"same": same} if same else {}
    return sorted(pairs, key=lambda p: (since(p[0], p[1], **kw), tie(p[0])))


def sort_agents(pairs: list[tuple[dict[str, Any], "_model.Model"]], tie: Callable[[dict[str, Any]], Any],
                same: Callable[[Any, Any], bool] | None = None) -> list[tuple[dict[str, Any], "_model.Model"]]:
    """Oldest first by the time the row shows (`since`, the same call the row's age is drawn from, so a bare confirm, which moves `confirmed` and leaves the state clock and a hand-off alone, never moves a row):
    the item that has been in its state longest leads. The mover is on the row and does not sort. `tie` orders items of one age (the board's due-date order, then machine and number)."""
    kw = {"same": same} if same else {}
    return sorted(pairs, key=lambda p: (since(p[0], p[1], **kw), tie(p[0])))


def sort_waiting(pairs: list[tuple[dict[str, Any], "_model.Model"]], tie: Callable[[dict[str, Any]], Any]) -> list[tuple[dict[str, Any], "_model.Model"]]:
    """By end date, the soonest first; a wait with no date last."""
    return sorted(pairs, key=lambda p: (end_epoch(p[1]), tie(p[0])))


def copyables(step: str) -> tuple[str, list[str]]:
    """(the step's text, the blocks to copy) for a step only the owner takes: each backticked command (a span with a space in it; a lone word stays inline) leaves the line for a block
    of its own, the text saying "the command below". With no command the text comes back whole and no block: a link stays in the line, drawn as a link like any other. The text is returned with its markdown as written."""
    cmds = [m.group(1) for m in re.finditer(r"`([^`\n]+)`", step) if " " in m.group(1).strip()]
    if cmds:
        n = iter(range(1, len(cmds) + 1))
        text = re.sub(r"`([^`\n]+)`", lambda m: (_i18n.t("home.cmd_below") if len(cmds) == 1 else _i18n.t("home.cmd_n_below", n=next(n))) if " " in m.group(1).strip() else m.group(0), step)
        return text, [c.strip() for c in cmds]
    return step, []
