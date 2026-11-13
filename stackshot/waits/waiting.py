"""waiting.py: what an item that waits stands on, and whose move it is.

An open item always has a MOVER: the one party whose move it is now. A mover is a session (the owner of the item, or the first session its
needs names), the owner of the board (needs decision), an outside party (needs external, or the fleet tool for a pane recycle), or, for an item
that waits `after` another, that item's mover (the `via` says which item). This module holds the readers of an item's wait fields (wake, due
date, hold, `after`, needs, the real-world date a long wait stands on, a recorded failed wait) and `mover_for`, the one place that works the mover
out. It computes no date: an item is never given an "expected by" time and is never marked late for it. A parked item (on hold, or after an open
item) is held until its own wake or its blocker closes, with no stale mark; the passes that catch a wait that went wrong (the wake pass and the
watchers at a wake, the dates pass past a wake with no write, the failed-check notice, the wait-end audit) read the item's own fields.

The wake cap ([waiting] cap_days, cap_needs_owner: a wake a session sets may lie at most cap_days after the item's last move unless the owner's
words are recorded for that wake, metadata.cap_ok, or a real-world date stands behind it, metadata.wait_basis) is a gate on the write, kept here
(cap_days, cap_words, basis_of, basis_problem); a stored date is read as it is.

Pure functions of an item, the clock and one callback (`load`: an item by id). It reads only [waiting], [instance] and [fleet] tool_name from the
config."""
from __future__ import annotations

import datetime as dt
import re
from typing import Any, Callable

from stackshot.core import config as _cfg
from stackshot.fleet import sessions_registry as _sr


def _same(a: str, b: str) -> bool:
    """One session in two stored forms (a name, a transcript id, its permanent id) is one: compared as permanent ids when both resolve, else as written."""
    t = _sr.same(a, b)
    return (a == b) if t is None else t


OWNER_KIND = _cfg.OWNER_KIND      # the mover kind of an item that is the owner's move, inside the code (the items API words it by [items_api] owner_mover_kind: server._wait_fields)
DEFAULTS = {"cap_days": 7.0, "cap_needs_owner": True, "basis_weekday": 0.0, "dated_wait_min_hours": 1.0}
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


_WAIT_KINDS = ("time", "anchor", "item", "relay", "event", "list")      # the stored wait kinds (the same six as model.WAIT_KINDS; this module is read by model.py, so it cannot import them)


def stored_until(m: dict[str, Any]) -> str:
    """The `until` an item stores (the one date its wait ends on: YYYY-MM-DD, or YYYY-MM-DDTHH:MM, read as a wake is), on one line; "" when it stores none. An open item with one is waiting."""
    return " ".join(str(m.get("until") or "").split())


def wake_value(m: dict[str, Any]) -> Any:
    """The date a wake-side record (wait_basis, cap_ok) stands for: the stored `until`, else the stored `wake` as it is. The records are read only for the very date they were given for."""
    return stored_until(m) or m.get("wake")


def list_holds(m: dict[str, Any]) -> bool:
    """Does the item store a list of waits that holds (waits/wait_list.py)? The one check lives there; this module is imported by it, so it is read at the call (an import at the top would be a cycle)."""
    from stackshot.waits import wait_list as _wl
    return _wl.valid(m)


def kind_of(m: dict[str, Any]) -> str:
    """The kind of wait an item stores: its wait_kind when it is one of the six (a stored `list` only while the list holds: one that does not is ignored, as the model ignores it, and the
    item reads as the date alone); with none, "time" when it stores an `until` (a wait on the date alone); else ""."""
    k = " ".join(str(m.get("wait_kind") or "").split()).lower()
    if k in _WAIT_KINDS and not (k == "list" and not list_holds(m)):
        return k
    return "time" if stored_until(m) else ""


def until_of(m: dict[str, Any]) -> str:
    """The date an item's wait ends on, as stored text: its `until`; with none, what the legacy fields give for its kind (a time wait's wake; a relay's ask_by; the earlier of ask_by and
    wake for an anchor, item or event wait, whose date is the backstop; a wake, else an ask_by, when the item stores no kind); "" when it has no date."""
    su = stored_until(m)
    if su:
        return su
    k = " ".join(str(m.get("wait_kind") or "").split()).lower()
    wake, ask = " ".join(str(m.get("wake") or "").split()), " ".join(str(m.get("ask_by") or "").split())
    if k == "time":
        return wake
    if k == "relay":
        return ask
    if k in _WAIT_KINDS:
        dated = [(ep, v) for v in (ask, wake) if (ep := wake_epoch(v)) is not None]
        return min(dated)[1] if dated else ""
    return wake or ask


def due_epoch(value: Any) -> float | None:
    """A due date (YYYY-MM-DD) as the end of that day in the instance zone, None when it is not one."""
    try:
        d = dt.date.fromisoformat(str(value or "").strip()[:10])
        ts = dt.datetime.combine(d + dt.timedelta(days=1), dt.time(), _cfg.tz()).timestamp()
    except (ValueError, OverflowError, OSError):     # 9999-12-31 + 1 day overflows; a date this far out is no date
        return None
    return ts if 0 < ts < MAX_EPOCH else None


def doing_agent(item: dict[str, Any]) -> bool:
    """Agent work in progress: an open item in the stored state doing whose mover is a session. Its own run time says how long it has been at it (the state clock); a wait on a date is parked
    (a hold with a wake and its basis). The retire pass leaves such an item whole."""
    m = item.get("metadata") or {}
    return item.get("status") == "open" and m.get("state") == "doing" and mover_of(m)["kind"] == "session"


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


def is_held(item: dict[str, Any]) -> bool:
    """On hold, as the server and the renderer read it: an open item with metadata.hold whose needs do not hold decision."""
    m = item.get("metadata") or {}
    return item.get("status") == "open" and bool(m.get("hold")) and not any(x.lower() == "decision" for x in needs_of(m))


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
    then the first session needs names, else the stored post_wake_mover (the old name of a waiting item's mover, which wins while it is stored) or the stored mover, else the project's builder, else its -main agent (never the item's creator)."""
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
    wv = wake_value(m)
    if not isinstance(v, dict) or not wv or v.get("wake") != wv:
        return ""
    return " ".join(str(v.get("text") or "").split())


def cap_words(m: dict[str, Any], wait: str = "wake") -> bool:
    """Is the cap lifted for this item's wake or due date? Two things lift it, each for one date only: the owner's words recorded for it
    (metadata.cap_ok = {"wake", "by", "quote"?, "source"?, "due", "due_by"}, written when a date past the cap was accepted on his words), and,
    for a wake only, a real-world date the session gave as its basis (metadata.wait_basis, basis_of). A changed date reads without either."""
    v = m.get("cap_ok")
    key = "due" if wait == "due" else "wake"
    cur = wake_value(m) if key == "wake" else m.get(key)
    if isinstance(v, dict) and bool(cur) and v.get(key) == cur:
        return True
    return key == "wake" and bool(basis_of(m))


def words_of(m: dict[str, Any]) -> dict[str, str]:
    """The owner's recorded words behind this item's wake, {"quote", "source", "by"}, when cap_ok holds a quote for the very wake; else {}."""
    v = m.get("cap_ok")
    wv = wake_value(m)
    if isinstance(v, dict) and wv and v.get("wake") == wv and str(v.get("quote") or "").strip():
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
            if str(wake_value(v.get("metadata") or {}) or "") == wake:
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


# ---------------------------------------------------------------- whose move it is
def mover_for(item: dict[str, Any], load: Callable[[str], dict[str, Any] | None] | None = None, _path: tuple[str, ...] = ()) -> dict[str, str]:
    """Whose move it is now: {"kind", "who", "via"?}. mover_of(the item's needs), except that an item that waits `after` an open item is
    that item's mover with `via` naming it (`load(gid)` reads another item; with none every item stands on its own needs), and a held pane-recycle wait with no wake
    is the fleet tool's. A recorded failed wait keeps the item's own mover. Of several open blockers the first in the item's `after` list names the mover. Computes no date."""
    m = item.get("metadata") or {}
    gid = str(item.get("gid") or "")
    mv = mover_of(m)
    if failed_of(m):
        return mv
    if load is not None and len(_path) < 8:
        for g in after_of(m):
            if g == gid or g in _path:
                continue
            b = load(g)
            if not b or b.get("status") != "open":
                continue
            return {**mover_for({**b, "gid": g}, load, (*_path, gid)), "via": g}
    if is_held(item) and m.get("recycle") and not (wake_value(m) and wake_epoch(wake_value(m)) is not None):
        return {"kind": "outside", "who": f"{_cfg.fleet_tool() or 'the fleet tool'} (pane recycle)"}
    return mv


def when_words(ts: float) -> str:
    """"Thu Mar 12th 18:30" in the instance zone, the rulebook's form."""
    try:
        t = dt.datetime.fromtimestamp(float(ts), _cfg.tz())
    except (ValueError, OverflowError, OSError):
        return "an unreadable date"
    d = t.day
    return f"{t:%a %b} {d}{'th' if 11 <= d % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(d % 10, 'th')} {t:%H:%M}"
