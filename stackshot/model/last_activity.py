"""last_activity.py: the item's one "last activity" record, `metadata.last_activity = {"at": epoch seconds, "what": "short words"}`.

The pure half: no server import, no clock read, no file. Part A of the rule that no item an agent moves goes more than an hour without visible activity: this records the
last visible activity and nothing reads it yet (no flag, no notice, no board text); a later part reads it.

The one definition of activity. Something visible happened to the item when:

  a save moved the item's progress (model/progress.py `moved`, the same test, so this adds no second opinion): a step marked done or dropped, a state change (status, phase, the kind
  of a wait, mover, state, needs), a pull request recorded as merged, the item created. A save that is no one's write about the work (progress.moved with real=False) is the server's
  own bookkeeping and counts only by a status or phase change, as it does for progress; or
  a pull request tied to the item had an event: a CI result (failed, or passing again), a comment by a person, a review, a merge (anchors/event_log.py, tied by merge_tie).

What is not activity: a status line (`work`), a reply or a "no change" answer, a note, a message, a bare confirm, a new or reworded step, a description edit; and the server's own
writes about the item, which are not in progress either: a History line (the ladder's, the silence pass's, a merge pass's reason), the ask itself, the step a session or the server
makes for the owner. Those move the `activity` clock (activity.py), which this does not touch, and not this record.

Signals have named kinds, and the record keeps the kind of the newest: `step_done`, `step_dropped`, `state_change`, `pr_merged`, `ci_result`, `review`, `comment` (stamped today: the
progress signals of a save and the events of a tied pull request), and two that are defined and tested here but not stamped by anything yet: `update` (a mover's status write whose text differs
from the previous status text, `update_signal`) and `audit` (a line the audit writes saying what it verified: a pane in a turn, a subagent running, a commit, a review or CI on the pull
request). For those two the `what` is the short text itself. A later part stamps them; this one only knows them, so the record is extended by adding a signal, not by changing the record.
A reply that says nothing changed is no `update` (same text as before), and the ladder's and the server's own lines are none of these kinds.

Newest wins: a candidate replaces the stored record only when it is strictly later; a record never goes back. A candidate that is torn (no time, no words, a time that is not a number, a kind that is none of KINDS)
is skipped. The caller passes `now`; a candidate time after it is read as `now`.

Not seen here: a commit or push to a tied pull request. The hub emits no push event, so no signal for it can be built; a later part adds that source."""
from __future__ import annotations

import math
import re
import unicodedata
from typing import Any, Iterable

from stackshot.model import progress as _progress

FIELD = "last_activity"
MAX_WHAT = 80         # characters of the words kept
MAX_STEPS_NAMED = 3   # steps named in one save's words

# The named kinds of signal. STAMPED ones are what the server stamps today; the last two are defined here for the parts that come later.
STEP_DONE, STEP_DROPPED, STATE_CHANGE, PR_MERGED, CI_RESULT, REVIEW, COMMENT = "step_done", "step_dropped", "state_change", "pr_merged", "ci_result", "review", "comment"
UPDATE, AUDIT = "update", "audit"
STAMPED = (STEP_DONE, STEP_DROPPED, STATE_CHANGE, PR_MERGED, CI_RESULT, REVIEW, COMMENT)
KINDS = frozenset(STAMPED) | {UPDATE, AUDIT}

# The kinds of a tied pull request's events as anchors/event_log.py files them, the signal each is, and the words each is given.
PR_SIGNAL = {"ci_failed": CI_RESULT, "ci_passed": CI_RESULT, "comment": COMMENT, "review": REVIEW, "merged": PR_MERGED}
PR_WORDS = {"ci_failed": "CI failed on PR {n}", "ci_passed": "CI passing again on PR {n}", "comment": "comment on #{n}", "review": "review on PR {n}", "merged": "PR {n} merged"}

_PR_NUMBER = re.compile(r"#(\d+)\s*$")


def _meta(item: dict[str, Any] | None) -> dict[str, Any]:
    m = (item or {}).get("metadata")
    return m if isinstance(m, dict) else {}


def _words(v: Any) -> str:
    """One line of at most MAX_WHAT characters: control and format characters (a newline, an escape, a zero-width mark) become spaces, runs of spaces one."""
    text = "".join(" " if unicodedata.category(ch)[0] == "C" else ch for ch in str(v or ""))
    return " ".join(text.split())[:MAX_WHAT]


def clean(c: Any, now: float | None = None) -> dict[str, Any] | None:
    """A signal as {"at": float, "kind": str, "what": str}, None for one that is torn: not a dict, a kind that is none of KINDS, no finite positive time, no words. A time after `now` (when given) is read as `now`."""
    if not isinstance(c, dict):
        return None
    try:
        at = float(c.get("at"))
    except (TypeError, ValueError, OverflowError):
        return None
    what = _words(c.get("what"))
    kind = c.get("kind")
    if not what or not isinstance(kind, str) or kind not in KINDS or not math.isfinite(at) or at <= 0:      # a kind that is a list or a dict is torn, not a crash (it cannot be looked up in a set)
        return None
    return {"at": min(at, now) if now is not None else at, "kind": kind, "what": what}


def read(item: dict[str, Any] | None) -> dict[str, Any] | None:
    """The stored record of an item, None when it has none or it is torn."""
    return clean(_meta(item).get(FIELD))


def at(item: dict[str, Any] | None) -> float:
    """When the item last had visible activity, 0 when no record is stored (an item from before the record, or one with none yet)."""
    r = read(item)
    return r["at"] if r else 0.0


def signal(kind: str, at: Any, what: Any = "") -> dict[str, Any] | None:
    """A signal of a named kind at a time, None when it is torn (an unknown kind, a bad time, no words). `what` is the words; for `update` and `audit` it is the short text itself."""
    return clean({"at": at, "kind": kind, "what": what})


def pr_what(kind: str, n: int) -> str:
    """The words for an event of kind `kind` (event_log's kinds) on pull request `n`, "" for a kind that is no activity."""
    w = PR_WORDS.get(kind)
    return w.format(n=int(n)) if w and int(n) > 0 else ""


def pr_candidate(kind: str, n: int, ts: Any, now: float) -> dict[str, Any] | None:
    """The signal for one event of a tied pull request, as the event log holds it (its kind, number and the time the hub saw it); None for a kind that is no activity or a torn time."""
    sig = PR_SIGNAL.get(kind)
    return clean({"at": ts, "kind": sig, "what": pr_what(kind, n)}, now) if sig else None


def update_signal(previous: Any, text: Any, at: Any) -> dict[str, Any] | None:
    """The `update` signal for a mover's status write: its text is the words, but only when it differs from the previous status text (compared as words, case and spacing aside). The same text again
    ("no change" said twice), a blank one and a torn time give None: that is no update. Nothing stamps it yet."""
    now_t, was = " ".join(str(text or "").split()), " ".join(str(previous or "").split())
    if not now_t or now_t.casefold() == was.casefold():
        return None
    return signal(UPDATE, at, now_t)


def audit_signal(verified: Any, at: Any) -> dict[str, Any] | None:
    """The `audit` signal for a line the audit wrote saying what it verified (a pane in a turn, a subagent running, a commit, a review or CI on the pull request); the words are that short text. Nothing
    stamps it yet. A line that verified nothing is no signal."""
    return signal(AUDIT, at, verified)


def _pr_of(key: str) -> str:
    m = _PR_NUMBER.search(str(key))
    return m.group(1) if m else ""


def _step_signal(after: dict[str, Any], added: Iterable[tuple[str, str]], now: float) -> dict[str, Any] | None:
    """One signal for the steps just marked: "step 3 done", or several in one phrase ("step 1 done, step 3 dropped", the first three named); its kind is that of the last step named."""
    want = set(added)
    out: list[tuple[int, str]] = []
    for i, s in enumerate(_meta(after).get("steps") or [], 1):
        if isinstance(s, dict) and (_progress._norm(s.get("text")), str(s.get("status"))) in want:
            out.append((i, str(s.get("status"))))
    if not out:
        return None
    words = ", ".join(f"step {i} {st}" for i, st in out[:MAX_STEPS_NAMED]) + (f" (+{len(out) - MAX_STEPS_NAMED})" if len(out) > MAX_STEPS_NAMED else "")
    return clean({"at": now, "kind": STEP_DROPPED if out[-1][1] == _progress.DROPPED else STEP_DONE, "what": words})


def _state_words(before: dict[str, Any], after: dict[str, Any], real: bool) -> str:
    """"state: waiting" for what changed in progress.state_of, the first that differs in this order: the phase (alive or waiting), the state, the status, the mover, the needs."""
    stored = "phase" in _meta(before)
    b, a = _progress.state_of(before, stored, real), _progress.state_of(after, stored, real)
    # state_of order: status, phase, waits_on, mover, state, needs
    if b[1] != a[1] or b[2] != a[2]:
        return f"state: {a[1] or 'alive'}" + (f" ({a[2]})" if a[2] else "")
    if b[4] != a[4]:
        return f"state: {a[4] or 'none'}"
    if b[0] != a[0]:
        return f"state: {a[0] or 'none'}"
    if b[3] != a[3]:
        return "mover changed"
    if b[5] != a[5]:
        return "needs changed"
    return "state changed"


def _merge_words(before: dict[str, Any], after: dict[str, Any]) -> str:
    keys = sorted(_progress.merges(after) - _progress.merges(before))
    nums = [n for n in (_pr_of(k) for k in keys) if n]
    return ", ".join(f"PR {n} merged" for n in nums[:MAX_STEPS_NAMED]) if nums else "PR merged"


def save_signals(before: dict[str, Any] | None, after: dict[str, Any], now: float, real: bool = True) -> list[dict[str, Any]]:
    """The signals of what one save did that is visible activity, [] when it did none. It asks progress.moved, so the definition of a step, a state change and a merge is progress's own. A save
    that creates the item is a `state_change` ("created")."""
    flags = _progress.moved(before, after, real)
    if not flags:
        return []
    if before is None:
        return [s for s in (clean({"at": now, "kind": STATE_CHANGE, "what": "created"}),) if s]
    out: list[dict[str, Any] | None] = []
    if "step" in flags:
        out.append(_step_signal(after, _progress.marks(after) - _progress.marks(before), now))
    if "state" in flags:
        out.append(clean({"at": now, "kind": STATE_CHANGE, "what": _state_words(before, after, real)}))
    if "merged" in flags:
        out.append(clean({"at": now, "kind": PR_MERGED, "what": _merge_words(before, after)}))
    return [s for s in out if s]


def record(item: dict[str, Any] | None, events: Iterable[Any] = (), now: float | None = None) -> dict[str, Any] | None:
    """The item's last activity: the newest of the stored record and the signals `events` ({"at", "kind", "what"}: a save's visible activity, a tied pull request's event, and in later parts an update or an audit line), None when there is nothing.
    A candidate replaces the stored record only when strictly later; of candidates at the same time the last given wins. A torn candidate is skipped."""
    best = read(item)
    top: dict[str, Any] | None = None
    for e in events or ():
        c = clean(e, now)
        if c is not None and (top is None or c["at"] >= top["at"]):
            top = c
    if top is not None and (best is None or top["at"] > best["at"]):
        best = top
    return best


def apply(item: dict[str, Any], events: Iterable[Any] = (), now: float | None = None) -> bool:
    """Store the newest of the stored record and `events` in `metadata.last_activity`. → True when the item's field changed (a candidate that is not later changes nothing, so a repeat is no write)."""
    meta = item.get("metadata")
    if not isinstance(meta, dict):
        return False
    new = record(item, events, now)
    if new is None or meta.get(FIELD) == new:
        return False
    meta[FIELD] = new
    return True


def stamp(item: dict[str, Any], before: dict[str, Any] | None, now: float, real: bool = True) -> bool:
    """Apply one save: the signals it made (save_signals) become the record when later. Only an open item has one (as the progress clock). → True when the field changed."""
    if item.get("status") != "open":
        return False
    sigs = save_signals(before, item, now, real)
    return bool(sigs) and apply(item, sigs, now)
