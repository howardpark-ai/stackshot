"""queued.py: a mover busy on another item reads waiting, queued behind that item, not on agent.

A session that moves several open items works on one at a time. The board used to show every one of them on an agent, so the quiet ones were chased (the 45-minute news ask, the hourly audit line, the stall
ladder) as if nobody had them. This module is the one rule that tells which of a mover's on-agent items it is working on and which wait in line behind it. It is DERIVED, never stored: nothing is written to an
item, nothing is migrated, and a reader that stops asking sees the item as it always did. `[model] queued_behind` (default false, read at use) switches it on.

The rule, for each mover separately:

  1. the candidates are the mover's open items the board shows on an agent (not waiting, not the owner's move). A mover with ONE candidate changes nothing.
  2. the item it is working on is the one with the newest visible activity (`metadata.last_activity`, model/last_activity.py: a step, a state change, a commit, a review, CI or a merge on a tied pull request);
     a tie goes to the lower item number. That item must itself have had activity within `WINDOW_S` (an hour): a mover whose newest item is idle too is working on none of them, and nothing is queued.
  3. each OTHER candidate with no activity for more than `WINDOW_S` is queued behind that item. One with activity in the last hour stays on agent.
  4. a front agent (the owner talks to it) keeps today's reading: its items are never queued.

It ends by itself, because the same rule is read again every time: the mover moves a queued item (it has the newest activity and becomes the item in hand), the item it waits behind closes, goes idle for an hour or is
handed to another mover, or the mover's other items thin out to one.

A queued item reads as a wait of the `item` kind (`model.Wait.queued`, `after` = the item it is behind), so the board lists it under Waiting with the reason `queued behind <item>`, and the passes that leave a waiting
item alone (audit/hourly.py, audit/hand_idle.py, the stall pass) leave it alone too. Pure: no server import, no clock read, no file; the callers supply the candidates and `now`."""
from __future__ import annotations

import re
from typing import Any, Callable, Iterable

from stackshot.core import config as _cfg
from stackshot.model import last_activity as _la
from stackshot.model import model as _model

WINDOW_S = 3600.0       # an item has "no activity" past this many seconds; the item in hand must have had some within it
_HOOKS: dict[str, Any] = {"is_front": None}      # the server's answer to who is a front agent (server._front_keeper), for the readers that have no pass environment (the board's own rendering)


def enabled() -> bool:
    """`[model] queued_behind` (default false): only a TOML true switches the rule on. Read at use, so a reload turns it on or off."""
    return _cfg.model_queued_behind()


def configure(is_front: Callable[[str, str], bool] | None = None) -> None:
    """The server installs its own front-agent test for the board's rendering (the passes are handed theirs by their environment)."""
    if is_front is not None:
        _HOOKS["is_front"] = is_front


def front_hook() -> Callable[[str, str], bool] | None:
    """The front-agent test the server installed (`configure`), None before it did; the board's rendering (web/home.py `front_test`) falls back to the role map when there is none."""
    return _HOOKS["is_front"]


def _num(gid: str) -> int:
    return int(re.sub(r"\D", "", str(gid)) or 0)


def candidate(gid: str, item: dict[str, Any], mover: str, now: float) -> tuple[str, str, str, float]:
    """(gid, mover, project, activity time) of an on-agent item. The time is its `last_activity` record (0 when it has none), never later than `now`."""
    meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    return gid, str(mover or ""), str(meta.get("project") or ""), min(_la.at(item, now), now)


def queue(cands: Iterable[tuple[str, str, str, float]], now: float, is_front: Callable[[str, str], bool] | None = None, window: float = WINDOW_S) -> dict[str, str]:
    """{queued item: the item it is queued behind} over the on-agent candidates (`candidate`); {} when nothing is queued. See the module doc for the rule. `is_front(mover, project)` → True for a front agent.
    `window` is the span of "no activity" and of "had activity" (default `WINDOW_S`, the board's reading); the balancer (audit/hand_idle.py) reads the same rule over its own, shorter window."""
    by_mover: dict[str, list[tuple[str, str, float]]] = {}
    for gid, mover, project, at in cands:
        who = str(mover or "").strip().casefold()
        if not who or _model.is_owner(mover):
            continue
        try:
            if is_front is not None and is_front(mover, project):
                continue
        except Exception:  # noqa: BLE001  (a front test that cannot answer leaves the item as it was)
            continue
        by_mover.setdefault(who, []).append((gid, mover, at))
    out: dict[str, str] = {}
    for rows in by_mover.values():
        if len(rows) < 2:
            continue
        hand = max(rows, key=lambda r: (r[2], -_num(r[0])))
        if hand[2] <= 0 or now - hand[2] > window:
            continue      # the newest item is idle too: the mover is working on none of them, so every one stays on agent
        for gid, _mover, at in rows:
            if gid != hand[0] and now - at > window:
                out[gid] = hand[0]
    return out


def overlay(mod: "_model.Model", behind: str) -> "_model.Model":
    """The reading of an on-agent item that is queued behind `behind`: waiting, of the item kind, `after` the item it is behind, `queued` set so a page says it as a queue, and the same mover (it picks the item up when
    the queue clears). The reading of any other kind of item is returned as it was."""
    if not behind or mod.state != _model.ALIVE:
        return mod
    wait = _model.Wait(kind="item", kind_explicit=False, after=(behind,), mover=mod.mover, mover_explicit=mod.mover_explicit, due=False, queued=True)
    return _model.Model(_model.WAITING, mod.today, mod.today_derived, "", False, "", False, "", wait, mod.conflicts)


def reason(behind: str, shown: Callable[[str], str] = str) -> str:
    """The reason a queued item gives: `queued behind <item>`, the item as `shown` writes it."""
    return f"queued behind {shown(behind)}"


def board_queue(rows: Iterable[dict[str, Any]], base: Callable[[dict[str, Any]], "_model.Model"], now: float, is_front: Callable[[str, str], bool] | None = None) -> dict[str, str]:
    """The queue over the board's open rows (each a dict with `gid`, `metadata`, `last_activity` in its metadata) as the page reads them: `base(row)` is the reading before this rule. {} when the rule is off.
    The candidates are the rows `base` reads alive with a session as the mover, the very rows the home page puts under On agent. `is_front(mover, project)` says who is a front agent (the caller's: the model reads no role map)."""
    if not enabled():
        return {}
    cands = []
    for r in rows:
        if r.get("status") == "completed":
            continue
        try:
            mod = base(r)
        except Exception:  # noqa: BLE001  (an item that cannot be read is no candidate)
            continue
        if mod.state == _model.ALIVE and mod.mover and not _model.is_owner(mod.mover):
            cands.append(candidate(str(r.get("gid") or ""), r, mod.mover, now))
    return queue(cands, now, is_front)
