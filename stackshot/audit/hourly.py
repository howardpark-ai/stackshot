"""hourly.py: the hourly audit line: an item on an agent that has had no write for an hour gets one short line saying what the audit verified.

Part of the rule that no item an agent moves goes more than an hour without an update. The mover writes the update; when it has nothing new to add, the audit checks that the item is moving and
writes the line itself, so the owner never sees an item on an agent idle for over an hour. This is the audit side; handing an idle item on is audit/hand_idle.py. Off by default (`[audit] hourly_line`).

  enabled()                                    `[audit] hourly_line`, only a TOML true
  due(items, gid, now, env, pane, same)        the line an item is owed now, None when none: {"text", "verified", "kind"}
  pass_(items, now, env, pane, same)           [(gid, line)] of every open item that is owed one; reads only
  last_line(meta)                              the newest audit line on an item (its log entry), None when it has none

An item is owed a line when all of these hold, using the silence pass's own scope (`silence.reading`, `silence.clock`):

  - it is open and on an agent as the board shows it: a session is its mover, its state is not the owner's move, and the board does not show it waiting. A hold, a parked item and any stored
    wait (a dated wake, an item it waits after, a release, a CI run, a relay, an outside party) and an item queued behind its mover's other item (`[model] queued_behind`, model/queued.py) are left alone, exactly as the silence pass leaves them;
  - an untaken hand-off to a back agent is left alone (the hand-off audit clocks it); an untaken hand-off to a front agent is not, as in the silence pass. A front agent's item is otherwise
    treated like any other: the pass sends nobody anything, it writes a History line, so there is no notice to hold back from a front agent;
  - the item has had no real activity for an hour: `silence.clock`, the clock the silence pass reads (a step done or added, a state change, the owner's answer, a message, an event on an anchor,
    a write by the mover). A bare confirm ("no change") and the audit's own and the ladder's lines do not move it, so a "no change" reply is no update;
  - no audit line was written on it lately: one an hour for the first 24 hours of silence, then one every 6 hours (`SLOW_EVERY`), so a week of silence is about fifty lines, not 168. The newest line of
    `metadata.hourly_audit.log` is the clock, so a second pass in the same hour writes nothing and a clock that goes backwards only delays the next line.

What the pass verifies, from data the server already holds, and says in the line (`Audit hh:mm: verified …`):

  - the mover's pane is in a turn: the CLI's registry shows it `busy` (read by the server on its own box; a session this box does not run shows nothing). A background subagent keeps a pane busy;
  - a subagent is running: a step status in progress, last changed within `silence.SUBAGENT_S`, on a step that opens with the mover's name (`silence.subagent_running`);
  - a pull request tied to the item had a CI result, a review, a comment by a person or a merge in the last hour, as `metadata.last_activity` records it (model/last_activity.py).

The first two are live states; the third is a recorded event, one the activity record already counts. A line that rests on live states alone says so in its words
(`… (live state only, nothing recorded on the item)`). No line is stamped as the item's `last_activity`: a pane that is busy all day must not keep every silent item looking fresh, and an event
that is recorded is in the record already.

No pull request is read from GitHub here: the audit uses recorded data only. A commit or push to a tied pull request is not recorded by anything, so it is not a signal yet. When nothing is
verified the line reads `Audit hh:mm: idle, nothing verified` and its log entry carries kind `audit_idle`, which audit/hand_idle.py reads to hand the item on.

Pure: no server import, no file, no clock read but the zone for the hour and minute in the line. Stdlib plus the repo's modules."""
from __future__ import annotations

import datetime as dt
from typing import Any, Callable

from stackshot.audit import audit_checks as _ac
from stackshot.audit import hourly_log as _log
from stackshot.audit import silence as _silence
from stackshot.core import config as _cfg
from stackshot.model import last_activity as _la
from stackshot.waits import handoff as _ho
from stackshot.waits import waiting as _wt

EVERY = 3600.0           # an item on an agent is owed a line after this long without activity, and again this long after the last line
LONG_AFTER = 24 * 3600.0     # …until it has been silent this long; then the lines thin out to one every SLOW_EVERY
SLOW_EVERY = 6 * 3600.0
SLACK = 300.0            # the ten-minute tick reads its clock a few seconds later or earlier each time: a line is owed once this much less than the gap has passed, so an hour on the tick grid is never missed by seconds and pushed a whole tick on (half a tick)
PREFIX = "Audit "        # every line starts with it, then the time: `Audit 14:05: verified …`
KIND_OK, KIND_IDLE = _log.KIND_OK, _log.KIND_IDLE      # the `kind` of the log entry of a line that verified something, and of one that did not
LIVE_ONLY = " (live state only, nothing recorded on the item)"
PR_KINDS = frozenset({_la.CI_RESULT, _la.REVIEW, _la.COMMENT, _la.PR_MERGED})      # the recorded signals that are a tied pull request's events


def enabled() -> bool:
    """`[audit] hourly_line` (default false): only a TOML true switches the pass on. Read at use, so a reload turns it on or off."""
    return _cfg.audit_hourly_line()


def last_line(meta: dict[str, Any] | None, now: float | None = None) -> dict[str, Any] | None:
    """The newest audit line on an item, as its `metadata.hourly_audit.log` entry ({"at", "text", "kind"}); None when it has none or the entry is torn. With `now` given, an entry dated more than
    `EVERY` ahead of it is torn too (a clock set far ahead once, or a bad write): it would otherwise hide every line until real time caught up. A clock stepped back by less than that only delays the next line."""
    best = None
    for e in _log.log_of(meta):
        if e.get("kind") in (KIND_OK, KIND_IDLE) and isinstance(e.get("at"), (int, float)) and not isinstance(e.get("at"), bool) and (now is None or e["at"] <= now + EVERY) and (best is None or e["at"] >= best["at"]):
            best = e
    return best


def idle_marked(meta: dict[str, Any] | None, now: float | None = None) -> bool:
    """Is the newest audit line on the item one that verified nothing? What audit/hand_idle.py reads to find the items to hand on (given `now`, an entry dated far ahead of it is not read, as in `last_line`)."""
    e = last_line(meta, now)
    return bool(e) and e.get("kind") == KIND_IDLE


def verified(item: dict[str, Any], meta: dict[str, Any], mover: str, now: float, pane: Callable[[str], str] | None, same: Any = None) -> tuple[list[str], list[str]]:
    """What the audit can verify about the item now: (all the short phrases, the ones that rest on a recorded event). Both empty: nothing verified. `pane(mover)` → the registry status of the mover's
    pane ("busy", "idle", "shell", or "" when unknown); one that raises is read as unknown. A recorded event is one in the past: a record dated ahead of `now` is no event."""
    out: list[str] = []
    recorded: list[str] = []
    try:
        if pane is not None and pane(mover) == "busy":
            out.append("the mover's pane is in a turn")
    except Exception:  # noqa: BLE001  (a pane that cannot be read verifies nothing)
        pass
    if _silence.subagent_running(item, now, mover, same):
        out.append("a subagent is running on it")
    rec = _la.read(item)
    if rec and rec["kind"] in PR_KINDS and 0 <= now - rec["at"] <= EVERY:
        out.append(rec["what"])
        recorded.append(rec["what"])
    return out, recorded


def text(now: float, what: list[str], recorded: list[str] | None = None) -> str:
    """The line: `Audit hh:mm: verified a, b` or `Audit hh:mm: idle, nothing verified`, the time in the instance zone. A line that rests on live states alone (nothing in `recorded`) says so."""
    hm = dt.datetime.fromtimestamp(now, _cfg.tz()).strftime("%H:%M")
    if not what:
        return f"{PREFIX}{hm}: idle, nothing verified"
    return f"{PREFIX}{hm}: verified " + ", ".join(what) + ("" if recorded else LIVE_ONLY)


def due(items: dict[str, dict[str, Any]], gid: str, now: float, env: Any = None, pane: Callable[[str], str] | None = None, same: Any = None, queue: dict[str, str] | None = None) -> dict[str, Any] | None:
    """The line the open item `gid` is owed now (see the module doc), or None. → {"text", "verified" (the phrases), "recorded" (those that rest on a recorded event), "kind"}. `env.is_front(name, project)` says who is a front agent (None reads none as front)."""
    item = items.get(gid) or {}
    if item.get("status") != "open":
        return None
    it, meta, after_open, mover = _ac._item_view(items, gid)
    if queue is None:
        queue = _silence.queued(items, now, env)      # the mover's other items it is busy on (model/queued.py): `pass_` reads it once for every item
    if not _silence.reading(it, mover, after_open, now, queue.get(gid, "")) or _wt.is_held(it):
        return None      # not on an agent as the board shows it (a hold, a park, a stored wait, an item queued behind another of its mover's, the owner's or an outsider's move), or on hold
    front = (env.is_front if hasattr(env, "is_front") else None)
    if _ho.awaiting_session(it) and not (front is not None and front(mover, str(meta.get("project") or ""))):
        return None      # an untaken hand-off to a back agent is the hand-off audit's (a front agent's is checked, as the silence pass does)
    last = _silence.clock(it, mover)
    if not (last > 0 and now - last >= EVERY):
        return None
    prior = last_line(meta, now)
    if prior is not None and now - prior["at"] < (SLOW_EVERY if now - last >= LONG_AFTER else EVERY) - SLACK:
        return None      # a line was written lately, within the gap less the slack (a clock that went backwards lands here too: the next line is only delayed)
    what, recorded = verified(it, meta, mover, now, pane, same)
    return {"text": text(now, what, recorded), "verified": what, "recorded": recorded, "kind": KIND_OK if what else KIND_IDLE}


def pass_(items: dict[str, dict[str, Any]], now: float, env: Any = None, pane: Callable[[str], str] | None = None, same: Any = None) -> list[tuple[str, dict[str, Any]]]:
    """[(gid, line)] of every open item that is owed a line now, in id order; reads only. An item that cannot be read is left out (the server logs nothing for it: the board's other passes report it)."""
    out: list[tuple[str, dict[str, Any]]] = []
    queue = _silence.queued(items, now, env)
    for gid in sorted(items, key=_ac._num):
        if items[gid].get("status") != "open":
            continue
        try:
            line = due(items, gid, now, env, pane, same, queue)
        except Exception:  # noqa: BLE001
            continue
        if line is not None:
            out.append((gid, line))
    return out
