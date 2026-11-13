"""hourly.py: the hourly audit line: an item on an agent that has had no write for an hour gets one short line saying what the audit verified.

Part of the rule that no item an agent moves goes more than an hour without an update. The mover writes the update; when it has nothing new to add, the audit checks that the item is moving and
writes the line itself, so the owner never sees an item on an agent idle for over an hour. This is the audit side; handing an idle item on is audit/hand_idle.py. Off by default (`[audit] hourly_line`).

  enabled()                                    `[audit] hourly_line`, only a TOML true
  due(items, gid, now, env, pane, same, subagents, anchored)   the line an item is owed now, None when none: {"text", "verified", "kind"}
  pass_(items, now, env, pane, same, subagents, anchored)      [(gid, line)] of every open item that is owed one; reads only
  last_line(meta)                              the newest audit line on an item (its log entry), None when it has none
  stamp_signal(line, now)                      the `audit` signal a line that verified something stamps as the item's last_activity, None for one that did not

An item is owed a line when all of these hold, using the silence pass's own scope (`silence.reading`, `silence.clock`):

  - it is open and on an agent as the board shows it: a session is its mover, its state is not the owner's move, and the board does not show it waiting. A hold, a parked item and any stored
    wait (a dated wake, an item it waits after, a release, a CI run, a relay, an outside party) are left alone, exactly as the silence pass leaves them;
  - an untaken hand-off to a back agent is left alone (the hand-off audit clocks it); an untaken hand-off to a front agent is not, as in the silence pass. A front agent's item is otherwise
    treated like any other: the pass sends nobody anything, it writes a History line, so there is no notice to hold back from a front agent;
  - the item has had no real activity for an hour: `silence.clock`, the clock the silence pass reads (a step done or added, a state change, the owner's answer, a message, an event on an anchor,
    a write by the mover). A bare confirm ("no change") and the audit's own and the ladder's lines do not move it, so a "no change" reply is no update;
  - no audit line was written on it lately: the next line is owed 45 minutes after the last (`FAST_GAP`) for the first 24 hours of silence, then one every 6 hours (`SLOW_EVERY`), so a week of silence is about
    sixty lines, not 168. The ten-minute tick lands it on the first tick from then on, 50 minutes after the last line on an exact grid and at most about 56 minutes with a late round and jitter, so the row of a
    verified item, which reads red only strictly past an hour since its last activity (the line's time), never turns red between two lines. The newest line of `metadata.hourly_audit.log` is the clock, so a
    second pass in the same 45 minutes writes nothing and a clock that goes backwards only delays the next line.

What the pass verifies, from data the server already holds, and says in the line (`Audit hh:mm: verified …`):

  - the mover's pane is in a turn: the CLI's registry shows it `busy` (read by the server on its own box; a session this box does not run shows nothing). A busy pane says the mover works, not on which item, so it
    verifies an item only when it is the mover's one item on an agent (`alone`: no other open item of the mover is on an agent as the board shows it); a mover with several items has none verified by its pane;
  - a subagent is running ON THIS ITEM: one of the mover's running subagents, read from the transcript Claude Code keeps on this box, has a description or brief that names the item or a pull request anchored to it
    (audit/subagent_tie.py). A step status in progress is no proof (the mover wrote it, and one mover can carry it on several items while one subagent runs), and neither is a busy pane, which says the
    mover works, not on which item: with one subagent running, only the item it is tied to reads verified for it; the mover's other items read idle unless something else verifies them;
  - a pull request tied to the item had a CI result, a review, a comment by a person or a merge in the last hour, as `metadata.last_activity` records it (model/last_activity.py).

The first two are live states; the third is a recorded event, one the activity record already counts. A line that rests on live states alone says so in its words
(`… (live state only, nothing recorded on the item)`). A line that verified something is the hourly update the item promises, so it is stamped as the item's `last_activity` (kind `audit`, the words
`audit verified …`, `stamp_signal`; newest wins, so it never replaces a newer real event) and the On agent row reads its time and words. A line that verified nothing is no update and stamps nothing; a phrase that
rests on a recorded event alone stamps nothing, since that event is in the record already at its own time. The audit's write still moves no `activity` clock (model/activity.py): only `last_activity`.

No pull request is read from GitHub here: the audit uses recorded data only. A commit or push to a tied pull request is not recorded by anything, so it is not a signal yet. When nothing is
verified the line reads `Audit hh:mm: idle, nothing verified` and its log entry carries kind `audit_idle`, which audit/hand_idle.py reads to hand the item on.

Pure: no server import, no file, no clock read but the zone for the hour and minute in the line. Stdlib plus the repo's modules."""
from __future__ import annotations

import datetime as dt
from typing import Any, Callable

from stackshot.audit import audit_checks as _ac
from stackshot.audit import hourly_log as _log
from stackshot.audit import silence as _silence
from stackshot.audit import subagent_tie as _tie
from stackshot.core import config as _cfg
from stackshot.model import last_activity as _la
from stackshot.waits import handoff as _ho
from stackshot.waits import waiting as _wt

EVERY = 3600.0           # an item on an agent is owed a line after this long without activity
FAST_GAP = 45 * 60.0     # …and the next line this long after the last (not an hour): the ten-minute tick lands it 50 minutes on (at most about 56 with a late round and jitter), so the On agent row, which reads the line's time as the item's last activity and turns red strictly past an hour, never reads "idle over 1 h" between two lines
LONG_AFTER = 24 * 3600.0     # …until it has been silent this long; then the lines thin out to one every SLOW_EVERY
SLOW_EVERY = 6 * 3600.0
SLACK = 300.0            # in the slow stretch (a line every SLOW_EVERY): the ten-minute tick reads its clock a few seconds later or earlier each time, so the line is owed once this much less than the gap has passed and 6 hours on the tick grid is never missed by seconds and pushed a whole tick on
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


def verified(item: dict[str, Any], meta: dict[str, Any], mover: str, now: float, pane: Callable[[str], str] | None, same: Any = None, tied: Callable[[], bool] | None = None,
             alone: Callable[[], bool] | None = None) -> tuple[list[str], list[str]]:
    """What the audit can verify about the item now: (all the short phrases, the ones that rest on a recorded event). Both empty: nothing verified. `pane(mover)` → the registry status of the mover's
    pane ("busy", "idle", "shell", or "" when unknown); one that raises is read as unknown. A busy pane says the mover works, not on which item, so it counts for this item only when `alone()` says it is the
    mover's one item on an agent (None reads as alone: a caller that gives no view of the mover's other items). `tied()` → True when a subagent that is running is tied to THIS item (audit/subagent_tie.py: its description or
    brief names the item or a pull request anchored to it); None, or one that raises, verifies no subagent. A step status in progress is no proof of one (the mover wrote it, and it can sit on several items
    while one subagent runs). A recorded event is one in the past: a record dated ahead of `now` is no event."""
    out: list[str] = []
    recorded: list[str] = []
    try:
        if pane is not None and pane(mover) == "busy" and (alone is None or alone()):
            out.append("the mover's pane is in a turn")
    except Exception:  # noqa: BLE001  (a pane that cannot be read verifies nothing)
        pass
    try:
        if tied is not None and tied():
            out.append("a subagent is running on it")
    except Exception:  # noqa: BLE001  (a subagent that cannot be read verifies nothing)
        pass
    rec = _la.read(item)
    if rec and rec["kind"] in PR_KINDS and 0 <= now - rec["at"] <= EVERY:
        out.append(rec["what"])
        recorded.append(rec["what"])
    return out, recorded


def stamp_signal(line: dict[str, Any] | None, now: float) -> dict[str, Any] | None:
    """The `audit` signal a line stamps as the item's `last_activity` (model/last_activity.py), None when it stamps nothing. Only a line that VERIFIED something (kind `audit`) does: it is the hourly update the item
    promises, so the On agent row reads its time and words (`audit verified ` and the line's phrases). A line that verified nothing (`audit_idle`) is no update and stamps nothing. A line whose phrases all rest on a
    recorded event stamps nothing either: that event is in the record already, at its own time and kind, and a line stamped at `now` over it would only move it later. Newest wins when it is applied
    (`last_activity.apply`), so an older line never replaces a newer real event. The words are the live phrases, then the recorded ones that still fit in one short line."""
    if not line or line.get("kind") != KIND_OK:
        return None
    recorded = set(line.get("recorded") or [])
    live = [w for w in (line.get("verified") or []) if w and w not in recorded]
    if not live:
        return None
    words = "audit verified " + ", ".join(live)
    for w in (w for w in (line.get("verified") or []) if w in recorded):      # the recorded phrases follow, whole or not at all: the record keeps one short line (last_activity.MAX_WHAT), and a phrase cut in the middle says nothing
        if len(words) + 2 + len(w) <= _la.MAX_WHAT:
            words += ", " + w
    return _la.audit_signal(words, now)


def stamp(item: dict[str, Any], line: dict[str, Any] | None, now: float) -> bool:
    """Stamp the line as the item's `last_activity` (`stamp_signal`, then `last_activity.apply`: newest wins) → True when the record changed. The record never goes backwards for an audit line: a stored record dated
    ahead of `now` that still reads (within `last_activity.SKEW_S`: a clock stepped back a little, or an event the hub dated just ahead) stays, where `last_activity.record` alone would ignore a time past `now` and
    replace it with the earlier one. A record dated further ahead than that is no record (`last_activity.read`), and is replaced as everywhere."""
    sig = stamp_signal(line, now)
    if sig is None:
        return False
    cur = _la.read(item, now)
    if cur is not None and cur["at"] > sig["at"]:
        return False
    return _la.apply(item, [sig], now)


def text(now: float, what: list[str], recorded: list[str] | None = None) -> str:
    """The line: `Audit hh:mm: verified a, b` or `Audit hh:mm: idle, nothing verified`, the time in the instance zone. A line that rests on live states alone (nothing in `recorded`) says so."""
    hm = dt.datetime.fromtimestamp(now, _cfg.tz()).strftime("%H:%M")
    if not what:
        return f"{PREFIX}{hm}: idle, nothing verified"
    return f"{PREFIX}{hm}: verified " + ", ".join(what) + ("" if recorded else LIVE_ONLY)


def due(items: dict[str, dict[str, Any]], gid: str, now: float, env: Any = None, pane: Callable[[str], str] | None = None, same: Any = None,
        subagents: Callable[[str], list[dict[str, Any]]] | None = None, anchored: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """The line the open item `gid` is owed now (see the module doc), or None. → {"text", "verified" (the phrases), "recorded" (those that rest on a recorded event), "kind"}. `env.is_front(name, project)` says who is a front agent (None reads none as front).
    `subagents(mover)` → the mover's running subagents ([{"text": description and brief, ...}], subagent_tie.running; None reads none), `anchored` {item id: the pull requests ("owner/repo#n") anchored to it}: a subagent counts for the item only when it names
    the item or one of those pull requests."""
    item = items.get(gid) or {}
    if item.get("status") != "open":
        return None
    it, meta, after_open, mover = _ac._item_view(items, gid)
    if not _silence.reading(it, mover, after_open, now) or _wt.is_held(it):
        return None      # not on an agent as the board shows it (a hold, a park, a stored wait, the owner's or an outsider's move), or on hold
    front = (env.is_front if hasattr(env, "is_front") else None)
    if _ho.awaiting_session(it) and not (front is not None and front(mover, str(meta.get("project") or ""))):
        return None      # an untaken hand-off to a back agent is the hand-off audit's (a front agent's is checked, as the silence pass does)
    last = _silence.clock(it, mover)
    if not (last > 0 and now - last >= EVERY):
        return None
    prior = last_line(meta, now)
    if prior is not None and now - prior["at"] < (SLOW_EVERY - SLACK if now - last >= LONG_AFTER else FAST_GAP):
        return None      # a line was written lately, within the gap (a clock that went backwards lands here too: the next line is only delayed)
    def tied() -> bool:
        if subagents is None:
            return False
        from stackshot.tools import next_report as _nr  # noqa: PLC0415
        return _tie.tied(subagents(mover), _nr.shown(gid), (anchored or {}).get(gid, ()))
    def alone() -> bool:
        eq = same or (lambda a, b: str(a or "").casefold() == str(b or "").casefold())
        n = 0
        for g in items:
            if g == gid or items[g].get("status") != "open":
                continue
            try:
                it2, _m2, after2, mover2 = _ac._item_view(items, g)
                if mover2 and eq(mover2, mover) and _silence.reading(it2, mover2, after2, now) and not _wt.is_held(it2):
                    return False
            except Exception:  # noqa: BLE001  (an item that cannot be read is no other item of the mover's)
                continue
        return True
    what, recorded = verified(it, meta, mover, now, pane, same, tied, alone)
    return {"text": text(now, what, recorded), "verified": what, "recorded": recorded, "kind": KIND_OK if what else KIND_IDLE}


def pass_(items: dict[str, dict[str, Any]], now: float, env: Any = None, pane: Callable[[str], str] | None = None, same: Any = None,
          subagents: Callable[[str], list[dict[str, Any]]] | None = None, anchored: dict[str, Any] | None = None) -> list[tuple[str, dict[str, Any]]]:
    """[(gid, line)] of every open item that is owed a line now, in id order; reads only. An item that cannot be read is left out (the server logs nothing for it: the board's other passes report it)."""
    out: list[tuple[str, dict[str, Any]]] = []
    for gid in sorted(items, key=_ac._num):
        if items[gid].get("status") != "open":
            continue
        try:
            line = due(items, gid, now, env, pane, same, subagents, anchored)
        except Exception:  # noqa: BLE001
            continue
        if line is not None:
            out.append((gid, line))
    return out
