"""mover_steps.py: the steps of a save that keep whose move an item is and what it stands on: the stored state a step or supplies sets or a write unseats (`_state_apply`), the default `then` of an item that goes to the owner
(`_owner_then`, `_owner_then_default`), the mover settle (`_owner_state_mover` for an update, `_settle_mover_on_save` for every other save), the owner's step on the checklist (`_owner_steps_on_save`), the state as the brief shows it
(`_eff_state`) and the notes a read carries (`_state_check_notes`), the chain of an item that closed as superseded (`_follow_superseded`), the wait graph's loop test (`_after_reaches`) and the lookup of a project record
(`project_ref`). They run inside every save through the Steps table of the write path, so a change to one is a change to every write.

A service module: it reads the store (an item by id, the items an `after` names), the registry and the clock, and writes only the metadata dict it is handed. The pure rules those steps apply (the model fields a write stores, what
a settle decided, what the owner's step reads) are model/holders.py's. The session id of a name, the audit's broad wait words, the board's words for a time and its time zone are still the surface's or the audit's, reached
through service/save_hooks.py."""
from __future__ import annotations

import datetime as dt
import re
import sys
import time
from typing import Any

from fastmcp.exceptions import ToolError

from stackshot.core.instance import NAME, OWNER
from stackshot.fleet import sessions_registry as _sr
from stackshot.model import holders as _holders
from stackshot.model import model as _model
from stackshot.model import owner_steps as _hs
from stackshot.model import states as _states
from stackshot.model.needs import _after_of, _needs_sessions
from stackshot.projects import pages as _pages
from stackshot.projects import projects as _prj
from stackshot.projects.project_registry import _registry
from stackshot.service import agents as _agents
from stackshot.service import item_read as _item_read
from stackshot.service import store as _svcstore
from stackshot.service.save_hooks import hooks as _hooks
from stackshot.service.store import _path
from stackshot.waits import wait_list as _wl


def _session_id(value: str) -> str:
    """The session id of a name, as the server reads it (service/save_hooks.py's `session_id` hook)."""
    return _hooks().session_id(value)


def _follow_superseded(gid: str, seen: set[str] | None = None) -> str:
    """An item id → itself, or, when it closed as superseded, the item that replaced it (followed through a chain)."""
    seen = set() if seen is None else seen
    try:
        m = _svcstore._load(gid).get("metadata") or {}
    except ToolError:
        return gid
    rep = str(m.get("superseded_by") or "")
    if m.get("outcome") == "superseded" and rep and rep not in seen and _path(rep).exists():
        seen.add(gid)
        return _follow_superseded(rep, seen)
    return gid


def _after_reaches(start: list[str], target: str, seen: set[str] | None = None) -> bool:
    """Does `target` sit in the wait chain of any of `start` (open items only)? The loop test. An item waits on what its `after` names and on the item lines of its list of waits that have not arrived
    (wait_list.item_ids): the one place the wait graph is walked, so a list's item lines count as links in every write that asks."""
    seen = set() if seen is None else seen
    for g in start:
        if g == target:
            return True
        if g in seen:
            continue
        seen.add(g)
        try:
            it = _svcstore._load(g)
        except ToolError:
            continue
        if it.get("status") == "open" and _after_reaches(_after_of(it.get("metadata") or {}) + _wl.item_ids(it.get("metadata") or {}), target, seen):
            return True
    return False


def _state_apply(meta: dict[str, Any], status: str, st: str, given: dict[str, str], touched: frozenset[str] = frozenset(), withdraw: bool = False) -> str:
    """Keep the stored state `meta` holds true, or set the one a step or supplies stands on (the metadata as this write leaves it; the caller has run every other gate) → a note for the reply.
    No call names a state any more: an item stores alive or waiting directly, and a state word an older item still holds is only read (states.py). A step passed sets your-step and supplies blocked
    (`st`, from gates.gate_state_args), each needing what its state carries in the item as it is stored once this write is applied; the carry fields of the state it replaces go. A write that
    leaves a stored state alone and touches a field the state stands on (`touched`, against states.STANDS_ON) so that the item can no longer stand in it drops the state (the item reads from its
    fields, as a hold always did), never refuses: no call can move or clear it. The fields of the retired inputs (party, chase, end, proof) are left as they are: readers still take them.
    `withdraw` (step="none"): the item's stored step goes, and the your-step state with it; the mover he held goes back to `then` (_owner_state_mover) and his open step line leaves the checklist
    (_owner_steps_on_save), both on the same save. A closed item has no state."""
    was = meta.get("state") if isinstance(meta.get("state"), str) and meta.get("state") in _states.STATES else ""
    if status == "completed":
        if st or withdraw:
            raise ToolError("Refused: a completed item has no step or supplies (its outcome is its record); they go with an open item")
        for k in _states.DROP_ON_CLOSE:
            meta.pop(k, None)
        return ""
    if withdraw:
        if was != "your-step" and not meta.get("step"):
            raise ToolError("Refused: step=\"none\" withdraws a step, and this item stores none (its state is " + (was or "not stored") + "). Nothing was written")
        for k in ("step", *(["state"] if was == "your-step" else [])):
            meta.pop(k, None)
        return "\n(step withdrawn: the item is no longer in his step" + ("; its state your-step is gone" if was == "your-step" else "") + ")"
    today = _pages.zone_now().date()
    new = st or was
    if not new:
        for k in _states.CARRY_FIELDS:                    # a leftover field with no state to own it (the retired inputs' fields stay for the readers)
            if k not in _states.RETIRED_INPUT_FIELDS:
                meta.pop(k, None)
        return ""
    if not st and not given and not (set(touched) & set(_states.STANDS_ON[new])):
        return ""                                        # the state stays as stored; nothing this write touched can unseat it
    own = _states.CARRY[new]
    dropped = [k for k in _states.CARRY_FIELDS if k not in own and k not in _states.RETIRED_INPUT_FIELDS and meta.get(k) is not None] if new != was else []
    for k in _states.CARRY_FIELDS:
        if k not in _states.RETIRED_INPUT_FIELDS and (k not in own or new != was):
            meta.pop(k, None)
    for k, v in given.items():
        meta[k] = v
    meta["state"] = new
    probs = _states.problems(meta, new, today, check_dates=bool(st) and new != was)
    if probs:
        if st:
            raise ToolError(f"Refused: {'step' if st == 'your-step' else 'supplies'} needs {'; '.join(probs)}. Add {'it' if len(probs) == 1 else 'them'} to this write")
        for k in ("state", *[x for x in own if x not in _states.RETIRED_INPUT_FIELDS]):      # party, chase, end and proof stay for the readers
            meta.pop(k, None)
        return f"\n(stored state {new} dropped: the item no longer stands on {_holders._STATE_STANDS_ON[new] or 'what it was written for'}; it reads from its fields)"
    if new != was:
        return f"\n(state {was + ' → ' if was else ''}{new}" + (f"; dropped {', '.join(dropped)} of the old state" if dropped else "") + ")"
    return ""


def _owner_then(project: str, mover_before: str, sender: str, next_text: str, needs: list[str]) -> str:
    """Who takes an item after the owner's answer when nobody named it, as an item goes to him. Not the front agent that relayed the
    ask: the agent that does the work. In order: (1) the mover before his step when it is a background agent; (2) the project's builder when it moves the item (a session in needs) or when
    next names it as the one building (a line `<builder>: …`); (3) the sender when it is a background agent (a builder that files or edits its own decision item is its own then). "" when
    none (the model's own default then stands: the first session in needs, else nobody, and his answer hands the item to the project's builder, else its -main agent)."""
    if _holders._is_background(mover_before, project):
        return mover_before
    b = _agents._builder_for(project)
    if b:
        bid = _session_id(b)
        named = any(_session_id(x) == bid for x in needs)
        if not named and next_text:
            named = bool(re.search(r"(?mi)^\s*(?:[-*]\s+|\d+[.)]\s+)?" + re.escape(b) + r"\s*:", next_text))
        if named:
            return b
    if _holders._is_background(sender, project):
        return sender
    return ""


def _owner_then_default(item_was: dict[str, Any] | None, meta: dict[str, Any], status: str, sender: str, given: bool, mover_arg: str = "") -> str:
    """The write leaves an open item on the owner's move (needs decision, your-call, your-step) that was not his before, with no `then` stored or passed: store the default (_owner_then) as
    `then`. → the reply note ("" when nothing was stored). A stored `then`, a `then` or clear_then in this call, and an item already his before the write are left alone."""
    if given or status != "open" or _model.norm_who(meta.get("then")):
        return ""
    try:
        now_item = {"status": "open", "metadata": meta}
        mod = _item_read._model_of(now_item)
        if mod.state != _model.ALIVE or not _model.is_owner(mod.mover):
            return ""
        after = lambda i_: _item_read._after_open(i_.get("metadata") or {})
        if item_was and _model.stood_his(item_was, after):
            return ""
        before = ""
        if mover_arg and not _model.is_owner(mover_arg):
            before = mover_arg
        elif item_was and item_was.get("status") == "open":
            wm = _item_read._model_of({**item_was, "gid": ""})
            before = wm.mover if wm.state == _model.ALIVE else ""
        project = str(meta.get("project") or "")
        who = _owner_then(project, before, sender, str(meta.get("next") or ""), _needs_sessions(meta))
    except Exception as e:  # noqa: BLE001  — a default is never worth failing a write
        print(f"model: then default not read: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return ""
    if not who:
        return ""
    meta["then"] = who
    return f"\n(then {_sr._session_label(who) or who}: the agent doing the work takes it after {OWNER}'s answer or step; pass then=<session> to name another)"


def _owner_state_mover(item_now: dict[str, Any], meta: dict[str, Any], named: bool, item_was: dict[str, Any] | None = None) -> str:
    """A write that leaves an open item in his state (your-step, your-call, needs decision) and does not name a mover makes him the mover
    (an agent's update set a step and left itself as the stored mover, and the item read as both). `meta` is changed in place:
    mover = he; `then` stays if stored, else the stored agent mover becomes `then`, so his answer or Done hands the item back to whoever had it (the same `then` _answer and Done
    read). A mover the write names itself is not touched here: the guard (model_guards mover_state) refuses it with the fix, and the mirror (owner_mover: the owner as mover with the item in none of his states) refuses him as mover beside an agent's state. `named` is also true for a bookkeeping write (filing_only, the re-bullet): it flips nothing with nobody told.
    The way back: when the item stood in his state before this write (`item_was`) and no longer does (his decision out of needs, the state moved on), the mover he held goes back to `then` (the
    agent that had it), or to the model's default when none is stored; a wait that replaces his state drops it. → the note for the reply ("" when nothing moved).
    [model] guards = false, a filing write and a close are left alone."""
    if named or not _item_read._model_guards_on() or item_now.get("status") != "open":
        return ""
    after = lambda i_: _item_read._after_open(i_.get("metadata") or {})
    try:
        ch = _model.settle(item_now, _model.stood_his(item_was, after), after, waiting=True)      # the one caller that settles a waiting item: an update write that did not name a mover
    except Exception as e:  # noqa: BLE001  — a reading that fails changes nothing
        print(f"model: mover not read: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return ""
    if not ch:
        return ""
    mover_s, h = _model.norm_who(meta.get("mover")), _model.owner_display()
    if ch.get("mover") == h and not _model.norm_who(meta.get("then")) and ch.get("then") == mover_s and not _holders._is_background(mover_s, str(meta.get("project") or "")):
        better = _owner_then(str(meta.get("project") or ""), mover_s, "", str(meta.get("next") or ""), _needs_sessions(meta))      # D9: a front agent that relayed the ask is not its then when a builder does the work
        if better:
            ch = {**ch, "then": better}
    _holders._settle_apply(meta, ch)
    if ch["mover"] == h:
        keep = ch["then"]
        back = "" if keep == mover_s else f" (to have it come back to you instead, set then=<you>)"
        return f"\n(mover: {_sr._session_label(mover_s) or mover_s} → {h}: the item is in his state ({_eff_state(item_now)}), so he moves it; then {_sr._session_label(keep) or keep} takes it after his answer or Done){back}"
    to = ch["mover"]
    return (f"\n(mover: {h} → {_sr._session_label(to) or to}: the item is out of his hands, so {_sr._session_label(to) or to} moves it again)" if to
            else f"\n(mover: {h} dropped: the item is out of his hands, so its default mover moves it)")


def _settle_mover_on_save(item: dict[str, Any], before: dict[str, Any] | None) -> bool:
    """The backstop of the same rule for every save that is not an update's own: the server's moves (a wake, his answer on the board, a create). An open item
    whose stored mover disagrees with the side of his state it stands on is settled in place (model.settle): an agent mover on an item that waits on him becomes he, the agent in `then`; the mover he
    held goes back to `then` when the item leaves his state. Runs before the hand-off record, so a move to him is a hand-off to him and the way back needs none. A filing write and
    [model] guards = false leave it. Never fails a save. → True when it changed the item."""
    if not _item_read._model_guards_on() or item.get("status") != "open":
        return False
    try:
        after = lambda i_: _item_read._after_open(i_.get("metadata") or {})
        ch = _model.settle(item, _model.stood_his(before, after), after)
        if not ch:
            return False
        meta = item.get("metadata")
        if not isinstance(meta, dict):
            return False
        _holders._settle_apply(meta, ch)
        return True
    except Exception as e:  # noqa: BLE001
        print(f"model: mover not settled: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return False


def _owner_steps_on_save(item: dict[str, Any], before: dict[str, Any] | None, writer: str, author: tuple[str, str] | None) -> bool:
    """N5 for his part, on every save (the consistency step: the stored fields (needs, ask, state, step) stay what decides whether the item waits on him, and the checklist is made to agree with them):
      the item waits on him (alive, your-call or your-step or needs decision) → his open step is on the checklist: added at the end when none stands, adopted when a `<owner>:` line is there already, reworded
        (old dropped, new added) when the ask changed (owner_steps.ensure); a `<owner>:` line of a session about something else is left alone, and the server's step added beside it
      it stood on him before this write (or the server's step is still recorded open) and does not now, and the write is not his own answer → a session withdrew the ask or the step, or the item
        went on to wait for something else: the server's step is dropped, by the writer (owner_steps.drop_open); his own
        answer ticks the step itself (_answer), and a note on a step leaves it open for the session that judges it
    A closed item (its checklist is the record), a filing write and [model] guards = false leave it. Never fails a save. → True when it changed the checklist."""
    if not _item_read._model_guards_on() or item.get("status") != "open":
        return False
    try:
        meta = item.get("metadata")
        if not isinstance(meta, dict):
            return False
        after = lambda i_: _item_read._after_open(i_.get("metadata") or {})
        keeper, now, was = str(meta.get("owner") or ""), time.time(), (meta.get("steps"), meta.get("next"), _hs.recorded(meta))
        if _model.stood_his(item, after):
            _hs.ensure(meta, _holders._owner_want(meta), keeper, NAME, now, NAME)
        elif (_model.stood_his(before, after) or _hs.recorded(meta)) and not (author and author[1] == "board"):    # it stood on him before this write, or the server's step is still recorded open (the item stopped waiting on him by a wait earlier, and the step stayed): either way no ask or step of his stands now
            _hs.drop_open(meta, keeper, _sr._session_label(writer) or writer or NAME, now, also=_holders._owner_want((before or {}).get("metadata") or {}) if _model.stood_his(before, after) else "")
        else:
            _hs.forget_closed(meta, keeper)
        return was != (meta.get("steps"), meta.get("next"), _hs.recorded(meta))
    except Exception as e:  # noqa: BLE001
        print(f"owner-steps: {item.get('gid') or item.get('id')}: not settled: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return False


def _eff_state(item: dict[str, Any]) -> str:
    """The item's state, stored else derived, as the brief shows it."""
    return _states.of(item, lambda i_: _item_read._after_open(i_.get("metadata") or {}))[0]


def _state_check_notes(item: dict[str, Any]) -> list[str]:
    """The lines get, the brief and a write's reply carry for an open item (the owner-step and stale-next checks): next names the owner while the state is an agent's; next may be stale."""
    if item.get("status") != "open":
        return []
    m = item.get("metadata") or {}
    out = []
    who = _states.next_names_owner(m.get("next"), OWNER)
    if who:
        s = _eff_state(item)
        if s in _states.AGENT_STATES:
            out.append(f"note: next names {who} but the state is {s}: pass step=… (or needs=decision with an ask)")
    _hits, broad = _hooks().wait_words(item, lambda i_: _item_read._after_open(i_.get("metadata") or {}))
    if broad:
        out.append(f"(flag: next uses {', '.join(broad)}, words that can hide a wait: if it waits, set the wait; the auditor reads this)")
    ns = m.get("next_stale")
    if isinstance(ns, dict) and ns.get("fields"):
        try:
            when = " " + _hooks().when_words(dt.datetime.fromtimestamp(float(ns["at"]), _hooks().zone()))
        except (KeyError, TypeError, ValueError, OverflowError, OSError):
            when = ""
        out.append(f"(next may be stale: {ns.get('by') or 'another session'} changed {', '.join(str(x) for x in ns['fields'])}{when})")
    gone = _states.passed_dates(m.get("next"), _pages.zone_now().date())
    if gone:
        out.append(f"(next may be stale: it names {gone[0][0]}, which has passed)")
    return out


def project_ref(x: str) -> dict[str, Any] | None:
    """A project's record by id, full page key or bare slug (projects.ref, on the registry this server reads); None when it names none."""
    return _prj.ref(x, _registry("projects"))
