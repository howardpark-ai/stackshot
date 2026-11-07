"""waiting.py — the one rule for an item that waits (the owner's adoption of the one-rule model).

stackshot has eight ways for an item to wait: a hold, a wake, `after` another item, a done check, needs, a pane recycle, an
anchor's notice and the idle clock. Each used to be a watch of its own, and an item that was waiting in one of them was left
out of the others: a held or `after` item was never stale, never idle-poked, never in the audit. This module replaces those
exemptions with one rule: every open item always has a MOVER (the one party whose move it is now) and, except agent work in progress (state
doing), an EXPECTED-BY time (when that move is due), and an item past its expected-by is surfaced, whatever kind of wait it is in.

  mover        a session (the owner, or the first session its needs names), the owner of the board (needs decision), an outside
               party (needs external, or the fleet tool for a pane recycle), or, for an item that waits `after` another, that item's
               mover (the `via` says which item)
  expected-by  never later than the item's last state change + [waiting] cap_days, unless the owner's words are recorded for its wake or due date
               (metadata.cap_ok, with his quote and its source when it was recorded from the store) or, for a wake, a real-world date the session gave
               as its basis (metadata.wait_basis): each read only for the very wake it was recorded for. A verifying item's end date (its stored state, at most 30 days out) stands as its wait like a wake, uncapped (end_epoch). A due date three weeks out still surfaces if nobody moves the item. Derived from what the item has: the item it waits after (that item's own expected-by), else its wake, else its
               due date, else (for a hold with none of those) the pane recycle it waits for or now + the cap, else its
               check or needs set-time + a default; never stored, computed from the item each time it is read. Agent work in progress is the exception: an item in the stored
               state doing (mover a session, no wake, hold or after) has no expected-by at all (kind `doing`, no date, never past due): an agent's own work shows how long it has run, and the
               board keeps dates only for a wait on an outside party, a date or a person. An item that waits `after` such a doing item is expected by AFTER_DOING_SECONDS (12 hours) after that item's last write, the later of its updated and state_updated. When the wait is on an
               agent session and the item is not stored as doing, the derived date is [waiting] agent_hours from when the wait was set, not default_days or the cap; a wait on
               the owner or an outside party keeps the day-based dates
  past its expected-by an item is surfaced (the board, get, the item page), whatever kind of wait it is in, except agent work in progress (state doing), which has no expected time and is never past due; nothing in this module escalates it
  a wait that can no longer end (a check whose pull request was closed unmerged) is recorded as failed (metadata.wait_failed) and is
  past due at once; an `after` item that closes releases the item instead. A mover that is stopped or unreachable counts (the `down`
  callback), once seen so for a few minutes over two passes, when the item needs its move now

Pure functions of an item, the clock and two callbacks (`load`: an item by id; `down`: why a session cannot move, "" when it
can), shared by the server (get, the client API) and the renderer (the item page, board.md, the brief). It reads
only [waiting], [instance] and [fleet] tool_name from the config."""
from __future__ import annotations

import datetime as dt
import re
import zlib
from typing import Any, Callable

import config as _cfg
import sessions_registry as _sr


def _same(a: str, b: str) -> bool:
    """One session in two stored forms (a name, a transcript id, its permanent id) is one: compared as permanent ids when both resolve, else as written."""
    t = _sr.same(a, b)
    return (a == b) if t is None else t


OWNER_KIND = _cfg.OWNER_KIND      # the mover kind of an item that is the owner's move, inside the code (the items API words it by [items_api] owner_mover_kind: server._wait_fields)
DEFAULTS = {"cap_days": 7.0, "cap_needs_owner": True, "default_days": 3.0, "basis_weekday": 0.0,
            "agent_hours": 3.0, "dated_wait_min_hours": 1.0}
DAY = 86400.0
AFTER_DOING_SECONDS = 12 * 3600.0   # an item waiting `after` agent work in progress (a doing item whose mover is a session) is expected by this long after that item's last write; the agent_hours clock (3 h) is a different wait and is not this one
MAX_EPOCH = 32503680000.0     # Jan 1st 3000: a date beyond it is not a date (the stored value is garbage), so it counts as no date at all
_WAKE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}:\d{2}))?$")
_KINDS = ("decision", "external")


# ---------------------------------------------------------------- settings ([waiting], read at use: a reload is live)
def _num(key: str) -> float:
    try:
        v = float(_cfg.get("waiting", key))
        return v if v >= 0 else DEFAULTS[key]
    except (TypeError, ValueError):
        return DEFAULTS[key]


def cap_days() -> float:
    """[waiting] cap_days: the longest a wake a session sets may run (7 when unset)."""
    v = _num("cap_days")
    return v if v > 0 else DEFAULTS["cap_days"]


def cap_needs_owner() -> bool:
    """[waiting] cap_needs_owner: a wake past cap_days is refused without the owner's words (true when unset; false = allowed)."""
    v = _cfg.get("waiting", "cap_needs_owner")
    if isinstance(v, str):
        return v.strip().lower() not in ("false", "no", "0", "off")
    return DEFAULTS["cap_needs_owner"] if v is None else bool(v)


def default_days() -> float:
    """[waiting] default_days: how long a needs wait with no date of its own is expected to take, from its set-time (3 when unset)."""
    v = _num("default_days")
    return v if v > 0 else DEFAULTS["default_days"]


def agent_hours() -> float:
    """[waiting] agent_hours: how long a wait on an agent session that is not stored as doing (a created item handed to a session, a done check on its work) is expected to take, from when the wait was set (3 hours when unset).
    An item stored as doing has no expected time (compute)."""
    v = _num("agent_hours")
    return v if v > 0 else DEFAULTS["agent_hours"]


def dated_wait_min_hours() -> float:
    """[waiting] dated_wait_min_hours: how far ahead a doing item's wake must lie, with every open step dated for that day or later, for the board to show it as waiting (1 hour when
    unset; dated_wait.py). Closer than that, the item is work in hand."""
    v = _num("dated_wait_min_hours")
    return v if v > 0 else DEFAULTS["dated_wait_min_hours"]


def basis_weekday() -> int:
    """[waiting] basis_weekday: the weekday (0 = Monday … 6 = Sunday, the instance zone) on which the board's head lists the waits that stand on a
    real-world date (metadata.wait_basis); -1 = every day. Monday when unset or not a whole number in -1..6."""
    try:
        v = int(float(_cfg.get("waiting", "basis_weekday")))
    except (TypeError, ValueError):
        return int(DEFAULTS["basis_weekday"])
    return v if -1 <= v <= 6 else int(DEFAULTS["basis_weekday"])


# ---------------------------------------------------------------- an item's fields
def _owner_name() -> str:
    return str(_cfg.get("instance", "owner") or "the owner")


def needs_of(m: dict[str, Any]) -> list[str]:
    v = m.get("needs")
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    v = str(v or "").strip()
    return [v] if v else []


def after_of(m: dict[str, Any]) -> list[str]:
    v = m.get("after")
    return [str(x).strip() for x in v if str(x).strip()] if isinstance(v, list) else []


def wake_epoch(value: Any) -> float | None:
    """A stored wake (YYYY-MM-DD: the start of that day; YYYY-MM-DDTHH:MM: that minute) as an epoch in the instance zone, None when unreadable."""
    m = _WAKE_RE.match(str(value or "").strip())
    if not m:
        return None
    try:
        at = dt.datetime.strptime(m[1] + "T" + (m[2] or "00:00"), "%Y-%m-%dT%H:%M")
        ts = at.replace(tzinfo=_cfg.tz()).timestamp()
    except (ValueError, OverflowError, OSError):
        return None
    return ts if 0 < ts < MAX_EPOCH else None


def due_epoch(value: Any) -> float | None:
    """A due date (YYYY-MM-DD) as the end of that day in the instance zone, None when it is not one."""
    try:
        d = dt.date.fromisoformat(str(value or "").strip()[:10])
        ts = dt.datetime.combine(d + dt.timedelta(days=1), dt.time(), _cfg.tz()).timestamp()
    except (ValueError, OverflowError, OSError):     # 9999-12-31 + 1 day overflows; a date this far out is no date
        return None
    return ts if 0 < ts < MAX_EPOCH else None


_EB_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}):(\d{2})(?::\d{2}(?:\.\d+)?)?)?\s*(Z|[+-]\d{2}:?\d{2})?$")


def expected_parse(value: Any) -> tuple[float, bool] | None:
    """An expected_by stored on a doing item before expected times were dropped, as (epoch, timed), None when it is not one (nothing reads it but the readers that tolerate an older item). `YYYY-MM-DD` is the end of that day in the instance zone (timed False, as a due date is); `YYYY-MM-DD HH:MM`
    or `YYYY-MM-DDTHH:MM` (seconds allowed) is that minute in the instance zone, or in the zone its trailing Z or +HH:MM names (timed True)."""
    m = _EB_RE.match(str(value or "").strip())
    if not m:
        return None
    try:
        if m[2] is None:
            if m[4]:
                return None                       # a zone with no time of day names nothing
            ts = due_epoch(m[1])
            return (ts, False) if ts is not None else None
        at = dt.datetime.strptime(f"{m[1]}T{m[2]}:{m[3]}", "%Y-%m-%dT%H:%M")
        if m[4]:
            zone = dt.timezone.utc if m[4] == "Z" else dt.timezone(dt.timedelta(hours=int(m[4][:3]), minutes=int(m[4][0] + m[4][-2:])))
            ts = at.replace(tzinfo=zone).timestamp()
        else:
            ts = at.replace(tzinfo=_cfg.tz()).timestamp()
    except (ValueError, OverflowError, OSError):
        return None
    return (ts, True) if 0 < ts < MAX_EPOCH else None


def doing_agent(item: dict[str, Any]) -> bool:
    """Agent work in progress: an open item in the stored state doing whose mover is a session. It has no expected time: its own run time says how long it has been at it (the state clock), a wait
    on a date is parked (a hold with a wake and its basis), and compute() reads it as kind `doing` with no date and never past due. A wake, a hold, an `after` link and a failed wait come before it in compute()."""
    m = item.get("metadata") or {}
    return item.get("status") == "open" and m.get("state") == "doing" and mover_of(m)["kind"] == "session"


def agent_clock(item: dict[str, Any], now: float) -> float:
    """Where the hours of a derived agent wait count from: the item's state clock, or the later `metadata.agent_from` (a moment a cleanup stamped, as the rank
    cleanup does at the server's start: the wait counts from then, so nothing became overdue at once)."""
    su = clock_of(item, now)
    try:
        af = float((item.get("metadata") or {}).get("agent_from") or 0)
    except (TypeError, ValueError):
        af = 0.0
    return max(su, af) if 0 < af < MAX_EPOCH else su


def clock_of(item: dict[str, Any], now: float) -> float:
    """The item's state clock (when its state last changed), else its own clock, else its confirm, else now."""
    for k in ("state_updated", "updated", "confirmed"):
        try:
            v = float(item.get(k) or 0)
            if v > 0:
                return v
        except (TypeError, ValueError):
            pass
    return now


def last_write(item: dict[str, Any], now: float) -> float:
    """When the item was last written: the later of its own `updated` and its `state_updated` (any write by its mover counts as a move), else its confirm, else now."""
    best = 0.0
    for k in ("updated", "state_updated"):
        try:
            v = float(item.get(k) or 0)
        except (TypeError, ValueError):
            v = 0.0
        if 0 < v < MAX_EPOCH:
            best = max(best, v)
    return best if best > 0 else clock_of(item, now)


def is_held(item: dict[str, Any]) -> bool:
    """On hold, as the server and the renderer read it: an open item with metadata.hold whose needs do not hold decision."""
    m = item.get("metadata") or {}
    return item.get("status") == "open" and bool(m.get("hold")) and not any(x.lower() == "decision" for x in needs_of(m))


def end_epoch(item: dict[str, Any]) -> float | None:
    """The wait of a verifying item: the end date of its stored state (metadata.end, YYYY-MM-DD, at most 30 days from the day it was set; states.py checks that when it is
    written) as the end of that day in the instance zone, None for an item that is closed, not in the verifying state or without a readable end. The end stands as the item's
    wait like a wake does, without a wake of its own and without the cap: no idle nudge and no stale mark before it."""
    m = item.get("metadata") or {}
    if item.get("status") != "open" or m.get("state") != "verifying":
        return None
    return due_epoch(m.get("end"))


# The project's fallback mover: the builder, else the -main agent. The server installs the lookup (it reads the project registry); with none
# installed an unnamed mover stays unnamed.
FALLBACK_MOVER: Any = None


def fallback_mover(project: str) -> str:
    """The session that moves an item of `project` when nothing names one: its builder, else its -main agent ("" when no lookup is installed or the project has none)."""
    if FALLBACK_MOVER is None or not str(project or "").strip():
        return ""
    try:
        return str(FALLBACK_MOVER(str(project).strip()) or "").strip()
    except Exception:  # noqa: BLE001  — a registry that cannot be read names nobody
        return ""


def mover_of(m: dict[str, Any]) -> dict[str, str]:
    """Whose move it is by the item's own needs: {"kind": "owner" | "outside" | "session", "who"} (the items API names the owner's kind by [items_api] owner_mover_kind: see server._wait_fields). Decision first, then external,
    then the first session needs names, else the stored post-wake mover or mover, else the project's builder, else its -main agent (never the item's creator)."""
    ns = needs_of(m)
    low = [x.lower() for x in ns]
    if "decision" in low:
        return {"kind": OWNER_KIND, "who": _owner_name()}
    if "external" in low:
        return {"kind": "outside", "who": "an outside party"}
    named = [s for s in ns if s.lower() not in _KINDS]
    stored = next((v for v in (str(m.get("post_wake_mover") or "").strip(), str(m.get("mover") or "").strip()) if v and v.lower() != _owner_name().strip().lower()), "")
    who = (named or [stored or fallback_mover(str(m.get("project") or ""))])[0]
    return {"kind": "session", "who": who}


def basis_of(m: dict[str, Any]) -> str:
    """The real-world date a long wait stands on (metadata.wait_basis = {"text", "wake", "by", "at"}, set by the session that parked the item
    to a vendor reply, a release date, a trial end) → its text, "" when there is none or it was written for another wake: like cap_ok, it is
    read only for the very wake it was recorded for, so a wake moved to another date reads without it."""
    v = m.get("wait_basis")
    if not isinstance(v, dict) or not m.get("wake") or v.get("wake") != m.get("wake"):
        return ""
    return " ".join(str(v.get("text") or "").split())


def cap_words(m: dict[str, Any], wait: str = "wake") -> bool:
    """Is the cap lifted for this item's wake or due date? Two things lift it, each for one date only: the owner's words recorded for it
    (metadata.cap_ok = {"wake", "by", "quote"?, "source"?, "due", "due_by"}, written when a date past the cap was accepted on his words), and,
    for a wake only, a real-world date the session gave as its basis (metadata.wait_basis, basis_of). A changed date reads without either."""
    v = m.get("cap_ok")
    key = "due" if wait == "due" else "wake"
    if isinstance(v, dict) and bool(m.get(key)) and v.get(key) == m.get(key):
        return True
    return key == "wake" and bool(basis_of(m))


def words_of(m: dict[str, Any]) -> dict[str, str]:
    """The owner's recorded words behind this item's wake, {"quote", "source", "by"}, when cap_ok holds a quote for the very wake; else {}."""
    v = m.get("cap_ok")
    if isinstance(v, dict) and m.get("wake") and v.get("wake") == m.get("wake") and str(v.get("quote") or "").strip():
        return {"quote": str(v["quote"]), "source": str(v.get("source") or ""), "by": str(v.get("by") or "")}
    return {}


BASIS_MAX_WAKE_DAYS = 365        # a wait_basis stands for a wake at most this far from now
BASIS_WINDOW_DAYS = 30           # …and names a date from the wake day to this many days after it (a wake may come before the outside event: a deliberate early check)
_ISO_RX = re.compile(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)")


def basis_problem(text: str, wake_day: dt.date) -> str:
    """Why this basis text cannot stand for a wake on `wake_day`, "" when it can. Every YYYY-MM-DD in it must be a real calendar date
    (2026-02-30 is not), and at least one must fall from the wake day to BASIS_WINDOW_DAYS after it: the real-world date the wait is for,
    not a date that merely sounds distant. Shared by the server's gate and tools/cap_words.py."""
    real, fake = [], []
    for x in _ISO_RX.findall(text):
        try:
            real.append(dt.date.fromisoformat(x))
        except ValueError:
            fake.append(x)
    if fake:
        return f"{', '.join(fake)} is not a real calendar date"
    if not real:
        return "it names no date as YYYY-MM-DD"
    last = wake_day + dt.timedelta(days=BASIS_WINDOW_DAYS)
    if not any(wake_day <= d <= last for d in real):
        return (f"none of its dates ({', '.join(d.isoformat() for d in real)}) falls from the wake day {wake_day.isoformat()} to {BASIS_WINDOW_DAYS} days after it "
                f"({last.isoformat()}): the basis is the outside date the wait is for; the wake may come up to {BASIS_WINDOW_DAYS} days before it (an early check), not more")
    return ""


UNREADABLE_WHY = f"history unreadable: ask {_cfg.owner()} to answer again on the item"
PAIR_LEAD_SECONDS = 24 * 3600     # with no history to show it, an answer pairs with a move at most this long before it


def entry_current(item: dict[str, Any], ts: Any, now: float) -> bool:
    """Was this answer or comment given at or after the item's state clock (the move that set its current wake or hold)? The test _owner_words_on
    makes."""
    try:
        return float(ts) >= clock_of(item, now) - 0.5
    except (TypeError, ValueError):
        return False


class _Unreadable:
    """What prior_state_ts returns when the store's history exists but could not be read (git missing or hung, a file that does not parse, more
    versions than the look-back): an answer cannot be paired from it, which is not the same as there being no history."""
    def __repr__(self) -> str:
        return "UNREADABLE"

    def __bool__(self) -> bool:
        return False


UNREADABLE = _Unreadable()


def prior_state_ts(gid: str, wake: str, limit: int = 200) -> "float | None | _Unreadable":
    """When the item's state last changed BEFORE the move that set its current wake `wake`, read from the store's history (git): walking the
    committed versions of the item's file from the newest back, the versions that carry this very wake are the run the current wake was set in
    (a wake set, cleared and set again to the same value is the newest run only: the clear ends the earlier one); the first version before that
    run (another wake, or none) gives the answer, its state_updated (a version that only added an answer or a note keeps the state_updated it
    had). None when the history shows nothing earlier: the store is not a git checkout, the file has no history, the wake stood since the file's
    first version, or that version carries no state_updated. UNREADABLE when the history exists but could not be read: git is missing or timed
    out, a version does not parse, git cannot show a version it listed, or `limit` versions were walked without leaving the run (the move may
    lie further back). The item holds no list of its moves (state_updated is the latest one only, hold_set the hold's own time), so the history
    of its file is the record. The store is committed in snapshots, so several moves inside one snapshot count as one. Shared by the server and
    tools/cap_words.py."""
    import json
    import os
    import subprocess
    store = _cfg.path("paths", "store")
    repo = _cfg.path("paths", "repo")
    try:
        rel = os.path.relpath(os.path.join(str(store), gid[0], gid[1:] + ".json"), str(repo))
        if rel.startswith(".."):
            return None
        log = subprocess.run(["git", "-C", str(repo), "log", f"-n{limit}", "--format=%H", "--", rel], capture_output=True, text=True, timeout=30)
        if log.returncode != 0:
            return None if "not a git repository" in (log.stderr or "").lower() else UNREADABLE
        hashes = log.stdout.split()
        for h in hashes:
            show = subprocess.run(["git", "-C", str(repo), "show", f"{h}:{rel}"], capture_output=True, text=True, timeout=30)
            if show.returncode != 0:
                return UNREADABLE
            v = json.loads(show.stdout)
            if str((v.get("metadata") or {}).get("wake") or "") == wake:
                continue
            u = v.get("state_updated")
            return None if u is None else float(u)
        return UNREADABLE if len(hashes) >= limit else None      # every version carried the wake: it stood since the first, unless the look-back ended first
    except (OSError, subprocess.SubprocessError, ValueError, AttributeError, TypeError):
        return UNREADABLE


def entry_pairs(item: dict[str, Any], ts: Any, now: float, prior: "float | None | _Unreadable" = None) -> tuple[bool, str]:
    """Do his words (an answer or comment given at `ts`) stand behind the item's current wake or hold? → (yes, how) | (no, why).
    the owner answers, then a session sets the wake from his answer, so the answer usually comes just BEFORE the state clock. It pairs when it is
      (1) at or after the state clock, or
      (2) earlier, but no state move (wake, hold or needs change, which move state_updated) lies between it and the move that set the current
          wake: the state change before that move, `prior` (prior_state_ts), is at or before the answer. His words are then the last thing
          that happened before this park (a hold flag or needs changed AFTER the wake was set does not matter: the wake is what his words cover). A park answer, then a wake set, then another change, then the current one fails this: `prior` is after it.
      (3) with no history to show `prior` (None: the store is not a git checkout, or has no history for the file): the answer comes at most PAIR_LEAD_SECONDS (24 h) before the state clock.
      A history that exists but could not be read (`prior` is UNREADABLE) pairs nothing earlier than the state clock: refused, and the owner answers again on the item."""
    try:
        t = float(ts)
    except (TypeError, ValueError):
        return False, "it has no time"
    cur = clock_of(item, now)
    if t >= cur - 0.5:
        return True, "given since the move that set the current wake or hold"
    if prior is UNREADABLE:
        return False, UNREADABLE_WHY
    if prior is not None:
        if prior <= t + 0.5:
            return True, "the last thing before the move that set the current wake or hold: no state move lies between"
        return False, f"a state move ({_whenwords(prior)}) came after it and before the move that set the current wake"
    if cur - t <= PAIR_LEAD_SECONDS:
        return True, "within 24 hours before the move that set the current wake or hold (no history shows an earlier move)"
    return False, f"older than the move that set the current wake or hold ({_whenwords(cur)}) by more than 24 hours, and no history shows that nothing moved between"


def _whenwords(ts: float) -> str:
    try:
        return when_words(ts)
    except Exception:
        return str(ts)


_PARK_EN = r"\bpark|postpone|defer|snooze|\bhold\b|put (?:it |this )?off|remind|until"


def _park_rx():
    """The park test: the English words, plus [keywords.waiting] park_words (compiled once per set of words, so a reload is seen)."""
    return _cfg.kw_rx("waiting.park", lambda a: _PARK_EN + _cfg.kw_pipe(a), (("waiting", "park_words"),), re.I)


def park_words(text: Any) -> bool:
    """Do these words, which the store attributes to the owner, park or postpone the item ("park until Friday", "postpone for now")? The test for recording an answer or a comment as the words behind a long wait: "Approve" or "sent" is his, but is no park."""
    return bool(_park_rx().search(str(text or "")))


_WAIT_RX = re.compile(r"\bwait\w*", re.I)
_NEG_WAIT_RX = re.compile(r"\b(?:no|not|never|without|nothing)\b[^.;:]{0,24}\bwait\w*|n't\s+(?:\w+\s+){0,3}wait\w*|\bwait\w*\s+(?:for\s+)?(?:no\s?one|nobody|nothing|none|no)\b", re.I)


def answer_words(a: Any) -> str:
    """His words in a stored answer entry: what he typed (`text`); for a button he pressed (a board decision with no text) the option and its line, "<choice>: <choice_line>" (or the one of them there is)."""
    if not isinstance(a, dict):
        return ""
    text = " ".join(str(a.get("text") or "").split())
    if text:
        return text
    pick, line = (" ".join(str(a.get(k) or "").split()) for k in ("choice", "choice_line"))
    return f"{pick}: {line}" if pick and line else pick or line


def answer_parks(a: Any) -> bool:
    """Do his words in this entry park the item? What he typed parks when it reads as a park (park_words), exactly as before buttons counted. A button he pressed (no text) parks when its option and
    line read as a park, or when the option's LABEL (`choice`, never the line under it) has a wait word that is not negated ("Wait for Mar 28th"; not "No need to wait", "Waiting for nobody"): a date alone,
    "Approve and ship on Mar 3rd" or "Go: start next week" is no park, as typed words with a date alone never were."""
    if not isinstance(a, dict):
        return False
    if " ".join(str(a.get("text") or "").split()):
        return park_words(a.get("text"))
    s = answer_words(a)
    if not s:
        return False
    label = " ".join(str(a.get("choice") or "").split())
    return park_words(s) or (bool(_WAIT_RX.search(label)) and not _NEG_WAIT_RX.search(label))


def failed_of(m: dict[str, Any]) -> dict[str, Any]:
    """metadata.wait_failed: {"what", "why", "at"} when a wait ended in a way that can never complete it, else {}."""
    v = m.get("wait_failed")
    if isinstance(v, dict):
        try:
            if float(v.get("at") or 0) > 0:
                return v
        except (TypeError, ValueError):
            pass
    return {}


# ---------------------------------------------------------------- the server's old record (<state>/waiting.json, out of the store)
# {"baseline": the epoch of the first pass of the retired waiting ladder, "seen": {gid: when an undated wait was first seen}}, both only read now: nothing
# writes them any more, and a file from an earlier version (a `reported` list, anything else) is read for these two keys and nothing more. The baseline
# gives every item stored before the rule a fresh runway: a date derived from its state clock is never earlier than
# baseline + default_days, so the dates the board shows do not move. `seen` keeps the date of a hold with
# no wake, after or recycle from sliding. An `agent_rejudge` key an older file still holds is ignored (the one-off pass it recorded is gone).
def state_path():
    return _cfg.state("waiting.json")


def load_state() -> dict[str, Any]:
    import json
    try:
        d = json.loads(state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    d = d if isinstance(d, dict) else {}
    return {"baseline": d.get("baseline") if isinstance(d.get("baseline"), (int, float)) else None,
            "seen": d.get("seen") if isinstance(d.get("seen"), dict) else {}}


def save_state(st: dict[str, Any]) -> None:
    import json
    import os
    p = state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.tmp")
    tmp.write_text(json.dumps(st, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, p)


def floor_of(st: dict[str, Any], now: float | None = None) -> float:
    """The earliest a derived expected-by may fall: the baseline + default_days. Before the server's first pass there is no baseline:
    with `now` (a reader: the renderer, get) the floor is now + default_days, so nothing derived reads as late before the rule has
    started; without it 0.0 (no floor). compute() adds a per-item jitter of up to default_days on top, so the items that were
    already late when the rule started do not all surface in the same minute."""
    b = st.get("baseline")
    if isinstance(b, (int, float)):
        return float(b) + default_days() * DAY
    return float(now) + default_days() * DAY if now is not None else 0.0


def jitter(gid: str) -> float:
    """A fixed fraction in [0, 1) for an item id (a hash, so the same every time and on every box)."""
    return (zlib.crc32(str(gid).encode("utf-8")) & 0xFFFFFFFF) / 4294967296.0


# ---------------------------------------------------------------- the rule
def fallback(item: dict[str, Any], now: float) -> dict[str, Any]:
    """What an item whose wait cannot be computed (a stored value that raises) reads as: not late, a date the cap away. One bad item
    must never break the board or a read."""
    try:
        mv = mover_of(item.get("metadata") or {})
    except Exception:  # noqa: BLE001
        mv = {"kind": "session", "who": ""}
    eb = now + cap_days() * DAY
    return {"mover": mv, "expected_by": eb, "raw_eb": eb, "wait": "idle", "basis": "its wait could not be read", "overdue": False, "why": "", "down": "", "nodate": False}


def compute(item: dict[str, Any], now: float, load: Callable[[str], dict[str, Any] | None] | None = None,
            down: Callable[[str], str] | None = None, seen: Callable[[str], float | None] | None = None,
            floor: float = 0.0, _path: tuple[str, ...] = ()) -> dict[str, Any]:
    """_compute, and the fallback for an item it cannot compute."""
    try:
        return _compute(item, now, load, down, seen, floor, _path)
    except Exception:  # noqa: BLE001
        return fallback(item, now)


def _compute(item: dict[str, Any], now: float, load: Callable[[str], dict[str, Any] | None] | None = None,
             down: Callable[[str], str] | None = None, seen: Callable[[str], float | None] | None = None,
             floor: float = 0.0, _path: tuple[str, ...] = ()) -> dict[str, Any]:
    """The item's mover and expected-by, and whether it is past due.

    → {"mover": {"kind", "who", "via"?}, "expected_by": epoch, "raw_eb": the date before the rollout floor lifted it, "wait": the kind of wait that gives the date (after | failed | hold |
    wake | end | recycle | doing | due | check | needs | idle), "basis": the date's words, "overdue": bool, "why": what makes it overdue when
    that is not the date (a failed wait, a stopped mover), "down": the reason when the mover cannot move, "nodate": True when the
    item has no date of its own and was given now + cap (a hold with no wake, after or recycle)}.

    `load(gid)` reads another item (an `after` blocker); `down(session)` says why a session cannot move now ("" = it can);
    `seen(gid)` is when the server first saw an undated wait (None = now), kept in its state so that the date does not slide;
    `floor` is the earliest a derived date (a needs or idle default, a check's cap) may fall: a rollout gives existing items a
    fresh runway instead of calling every old one past due at once. A date the item carries itself (a wake, a due date, a
    blocker's, a failure) is never floored."""
    m = item.get("metadata") or {}
    gid = str(item.get("gid") or "")
    mv = mover_of(m)
    su = clock_of(item, now)
    out: dict[str, Any] = {"mover": mv, "expected_by": 0.0, "raw_eb": 0.0, "wait": "", "basis": "", "overdue": False, "why": "", "down": "", "nodate": False, "agent": False}

    fl = floor + jitter(gid) * default_days() * DAY if floor else 0.0   # staggered: a rollout does not surface every old item in one minute
    gate = cap_needs_owner()                                   # no wait runs past the cap after the item's last move without his words recorded

    def clamped(wait: str) -> bool:
        return gate and not cap_words(m, wait)

    def finish(eb: float, wait: str, basis: str, derived: bool = False, agent: bool = False) -> dict[str, Any]:
        raw = eb
        if wait in ("wake", "hold", "due") and not out["nodate"] and clamped(wait) and eb > su + cap_days() * DAY:
            raw = su + cap_days() * DAY                           # a due date three weeks out still surfaces if nobody moves the item for the cap
            eb = min(eb, max(raw, fl))                            # (on a rollout, not before the floor)
            basis += " (capped: the cap after its last move)"
        if derived and fl and eb < fl:
            eb = fl
        if wait in ("wake", "hold") and gate and not out["nodate"] and basis_of(m) and (raw > su + cap_days() * DAY or wait == "hold"):
            basis += f" · real-world date: {basis_of(m)}"        # a long wait that stands on a date outside the board, and a held park's window, show it where the date is
        out.update(expected_by=eb, raw_eb=raw, wait=wait, basis=basis, agent=agent)
        if now > eb:
            out["overdue"] = True
            if mv["kind"] == "session" and down is not None:      # a stopped mover matters when the item needs its move now, not before
                why = down(mv["who"])
                if why:
                    out.update(down=why, why=f"{mv['who']} {why}")
        return out

    fail = failed_of(m)
    if fail:
        out.update(why=f"{fail.get('what') or 'a wait'} failed: {fail.get('why') or 'it can no longer end'}")
        return finish(float(fail["at"]), "failed", "the wait failed")
    if load is not None and len(_path) < 8:
        best: tuple[float, dict[str, Any], str] | None = None
        for g in after_of(m):
            if g == gid or g in _path:
                continue
            b = load(g)
            if not b or b.get("status") != "open":
                continue
            bw = compute({**b, "gid": g}, now, load, down, seen, floor, (*_path, gid))
            if bw["wait"] == "doing":                             # the item it waits after is agent work in progress: no date of its own, so this wait is due AFTER_DOING_SECONDS after that item's last write
                due_at = last_write(b, now) + AFTER_DOING_SECONDS
                bw = {**bw, "expected_by": due_at, "raw_eb": due_at}
            if best is None or bw["expected_by"] > best[0]:
                best = (bw["expected_by"], bw, g)
        if best is not None:
            bw, g = best[1], best[2]
            out["mover"] = {**bw["mover"], "via": g}
            eb, raw = bw["expected_by"], bw.get("raw_eb", bw["expected_by"])
            if clamped("wake") and eb > su + cap_days() * DAY:    # the item's own last move counts too: waiting on a far blocker is not a way past the cap
                raw = su + cap_days() * DAY
                eb = min(eb, max(raw, fl))
            out.update(down=bw["down"], why=bw["why"], overdue=bw["overdue"] or now > eb)
            mvr = out["mover"]
            if now > eb and not bw["overdue"] and mvr["kind"] == "session" and down is not None:   # overdue through its own clamp: the mover's down grace applies, as in finish()
                why = down(mvr["who"])
                if why:
                    out.update(down=why, why=f"{mvr['who']} {why}")
            out.update(expected_by=eb, raw_eb=raw, wait="after", basis=f"after {g}")
            return out
    wake = wake_epoch(m.get("wake")) if m.get("wake") else None
    held = is_held(item)
    if wake is not None:
        return finish(wake, "hold" if held else "wake", "wake")
    ee = end_epoch(item) if not held else None
    if ee is not None:                          # verifying: its end date is its wait (the re-park rule), a wake of its own aside
        return finish(ee, "end", "verifying: its end date")
    if held and m.get("recycle"):
        try:
            at = float(m.get("recycle_at") or su)
        except (TypeError, ValueError):
            at = su
        out["mover"] = {"kind": "outside", "who": f"{_cfg.fleet_tool() or 'the fleet tool'} (pane recycle)"}
        return finish(at + cap_days() * DAY, "recycle", "pane recycle + the cap", True)
    if held:
        hs = m.get("hold_set")                  # the server stamps who set a hold and when (metadata.hold_set {at, by}): that is the date it was first seen
        stamped = float(hs["at"]) if isinstance(hs, dict) and isinstance(hs.get("at"), (int, float)) and hs["at"] > 0 else None
        first = stamped or (seen(gid) if seen is not None and gid else None) or now
        out["nodate"] = True
        return finish(first + cap_days() * DAY, "hold", "no wake, after or recycle: when the hold was set + the cap")
    if doing_agent(item):                       # agent work in progress (state doing): no expected time, never past due; its run time is the state clock
        out.update(expected_by=0.0, raw_eb=0.0, wait="doing", basis="doing: work in hand, no expected time", agent=True)
        return out
    due = due_epoch((m.get("due") or ""))
    if due is not None:
        return finish(due, "due", "due date")
    on_agent = mv["kind"] == "session"      # a wait on an agent session is timed in hours; the owner's and an outside party's keep days
    if str(m.get("check") or "").strip():
        if on_agent and _lane_wait(m) == "needs":    # a check whose needs names any session is an agent wait; with empty needs it keeps the cap
            # the check still closes the item when it passes, but it no longer sets the due: agent_hours from when the wait was set
            return finish(agent_clock(item, now) + agent_hours() * 3600.0, "check", "check set + the agent hours", agent=True)
        return finish(su + cap_days() * DAY, "check", "check set + the cap", True)
    lane = _lane_wait(m)
    if lane == "idle":
        from_idle = _idle_hours()
        return finish(su + (from_idle * 3600.0 if from_idle > 0 else default_days() * DAY), "idle", "its state clock + the idle hours", True)
    if on_agent:
        return finish(agent_clock(item, now) + agent_hours() * 3600.0, "needs", "needs set + the agent hours", agent=True)
    return finish(su + default_days() * DAY, "needs", "needs set + the default", True)


def _idle_hours() -> float:
    try:
        v = _cfg.get("idle", "hours")
        return float(v if v is not None else 4)
    except (TypeError, ValueError):
        return 4.0


def _lane_wait(m: dict[str, Any]) -> str:
    """"needs" when the item's needs name decision, external or a session, else "idle" (no one is named: its mover by default moves it)."""
    return "needs" if needs_of(m) else "idle"


# ---------------------------------------------------------------- words
def who_words(w: dict[str, Any], label: Callable[[str], str] = str, shown: Callable[[str], str] = str) -> str:
    """The mover in words: "my-engineer", "the owner", "an outside party", "the fleet tool (pane recycle)", with "(via board#N)" for an `after` item."""
    mv = w["mover"]
    base = label(mv["who"]) if mv["kind"] == "session" else mv["who"]
    return base + (f" (via {shown(mv['via'])})" if mv.get("via") else "")


def why_words(w: dict[str, Any], label: Callable[[str], str] = str) -> str:
    """`why` with a session mover's id shown as its name (compute writes the raw id; an id that does not resolve stays as it is)."""
    why, mv = str(w.get("why") or ""), w.get("mover") or {}
    who = str(mv.get("who") or "")
    if why and who and mv.get("kind") == "session" and why.startswith(who):
        return label(who) + why[len(who):]
    return why


def when_words(ts: float) -> str:
    """"Thu Mar 12th 18:30" in the instance zone, the rulebook's form."""
    try:
        t = dt.datetime.fromtimestamp(float(ts), _cfg.tz())
    except (ValueError, OverflowError, OSError):
        return "an unreadable date"
    d = t.day
    return f"{t:%a %b} {d}{'th' if 11 <= d % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(d % 10, 'th')} {t:%H:%M}"


def line(w: dict[str, Any], now: float, label: Callable[[str], str] = str, shown: Callable[[str], str] = str, lead: bool = True) -> str:
    """One line for get, the md and the item page: "my-engineer · expected by Thu Mar 12th 18:30 (wake) · past due by 2 d". `lead` = False
    leaves the words "expected by" out, for a place that already says them (the item page's "Expected by" heading)."""
    if w.get("wait") == "doing":
        return f"{who_words(w, label, shown)} · doing (work in hand; no expected time)"
    basis = f"after {shown(w['mover']['via'])}" if w.get("wait") == "after" and w["mover"].get("via") else str(w.get("basis") or "")
    s = f"{who_words(w, label, shown)} · {'expected by ' if lead else ''}{when_words(w['expected_by'])} ({basis})"
    if w.get("nodate"):
        s += " · no date of its own: given the cap"
    if w.get("overdue"):
        late = max(0.0, now - float(w["expected_by"]))
        s += " · past due" + (f" by {age_words(late)}" if late >= 60 else "")
        if w.get("why"):
            s += f": {why_words(w, label)}"
    return s


def age_words(seconds: float) -> str:
    m = int(max(0.0, float(seconds)) // 60)
    return f"{m} min" if m < 90 else (f"{m // 60} h" if m < 60 * 36 else f"{m // 1440} d")
