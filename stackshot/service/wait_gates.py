"""wait_gates.py: the write guards of a wait and of a decision's options, and what an update owes the watchers.

An event wait (wait_kind=event: a pull request merged or released, a machine online, a recycle, a fleet op) is gated at the write: the phrase is parsed and stored in its canonical form and a wait for something that has
already happened is refused (`_evwait_gate`, with the facts it reads before the item lock in `_evwait_preread` and the machine of a box_online wait in `_evw_box_spec`). An anchor wait is refused unless its anchor is on
the project's list (`_anchor_wait_gate`); `_watch_anchor_seen` says what the anchors receiver already recorded on it, and `_machine_note` says which offline machine an open step names that nothing watches. `_watch_on_write` is what an
update owes the watchers on the metadata it leaves, `_watch_answer` applies the owner's pick on a watcher's ask, and `_watch_close` is the server's own close of a wait he drops. The options of a decision are gated by
`_gate_options` (the shape of options=[...]; the other decision gates are model/decision_gates.py's). The front-step rule's two writes (`_front_step_mark`, the clock; `_front_step_move`, the reword) and the delivery
the ten-minute filing and dates passes send their messages through (`_filing_deliver`) are written here as the server's own bookkeeping; the passes that call them are still the surface's.

A service module: it reads the store and the registry and writes an item only through `writes.save`, under the item lock. The page's words for a time and its time zone, the ask words, the link-free form of an id and the
anchor texts are the surface's, reached through service/save_hooks.py, which also hands out the audit modules when a hook runs (audit/ sits outside the layers). A suite that replaces one of these sets it on this module
(and `time` here, since this module reads its own).

Imports point down only: this module imports the domain, core and the services beside it, never web/ and never audit/."""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import time
from typing import Any

from fastmcp.exceptions import ToolError

from stackshot.anchors import anchor_scope as _ascope
from stackshot.anchors import anchors as _anc
from stackshot.anchors import machine_anchor as _ma
from stackshot.core import config as _cfg
from stackshot.core import ghbudget as _gb
from stackshot.core.instance import NAME, OWNER
from stackshot.fleet import liveness as _lv
from stackshot.fleet import sessions_registry as _sr
from stackshot.github import ghsync as _gh
from stackshot.model import model as _model
from stackshot.model import nextlines as _nl
from stackshot.model import states as _states
from stackshot.model import steps as _steps
from stackshot.model.bullet_text import _clip_line
from stackshot.model.decision_gates import _MOCKUP_ASK, _OPT_FORM
from stackshot.model.field_gates import _close_reason_max, _fit
from stackshot.router import routing as _routing
from stackshot.service import checks as _checks
from stackshot.service import event_waits as _evwaits
from stackshot.service import messaging as _messaging
from stackshot.service import released as _relsvc
from stackshot.service import released_live as _rlive
from stackshot.service import store as _svcstore
from stackshot.service import telling as _telling
from stackshot.service import watching as _watching
from stackshot.service import writes as _writes
from stackshot.service.save_hooks import hooks as _hooks
from stackshot.waits import event_waits as _ew
from stackshot.waits import stall as _stall
from stackshot.waits import watchers as _watch


# ----------------------------------------------------------------------------- the options
# metadata.options: the alternatives a needs=decision item asks the owner to pick between, shown on the item page, under the ask in
# the queue's tooltip and board.md, and in the tool reply.
# The shape is render.options_of's. A yes/no decision lists two, Approve and Decline (the page draws
# Approve and Decline only when the owner lists them, so the owner gets one-click buttons); an open question (what, which, how, who, when, where, why) lists its answers as options, or is
# reworded as a yes/no, because the page's Yes and No fallback cannot answer it (_gate_open_question). An ask or
# description that names alternatives while the item lists none is refused (_gate_alternatives), with a matcher kept narrow so a go/no-go ask passes (keywords in either; in the
# Decide part also a list "x, y or z", "x vs y" and labeled choices, "A or B", "A (…) or B (…)", _lettered_alternatives). An ask whose Recommend part does not name the
# recommended option's label gets a note in the reply (_options_note), never a refusal: scripts file asks of their own wording.
# The decision gates live in model/decision_gates.py (the option form and the matchers); this module reads the option form and the mockup form for the options gate below.


# An option is drawn as a clickable card that selects or unselects, so a link inside its label or line would show as raw "[text](url)" text and could
# take the select click: a markdown link or a bare http(s) URL in an option is refused, and the mockup link goes in the ask.
_OPTION_LINK = re.compile(r"\[[^\]\n]*\]\([^)\n]*\)|https?://[^\s<>()\[\]]+", re.I)


def _gate_options(options: Any) -> list[dict[str, Any]] | None:
    """options as given → the stored list, [] to clear ("none", "clear", "-", or an empty list), None when not passed. Refuses
    a misshaped list. A JSON string of the list is read as the list (a client that sends every argument as a string)."""
    if options is None:
        return None
    if isinstance(options, str):
        t = options.strip()
        if t.lower() in _hooks().ask_none() or not t:
            return []
        try:
            options = json.loads(t)
        except ValueError:
            raise ToolError(f"Refused: options must be a list: {_OPT_FORM}")
    if not isinstance(options, list):
        raise ToolError(f"Refused: options must be a list: {_OPT_FORM}")
    if not options:
        return []
    if not _hooks().options_min() <= len(options) <= _hooks().options_max():
        raise ToolError(f"Refused: options takes {_hooks().options_min()} to {_hooks().options_max()} entries, got {len(options)}: {_OPT_FORM}")
    out, seen = [], set()
    for i, o in enumerate(options, 1):
        if not isinstance(o, dict):
            raise ToolError(f"Refused: option {i} is not an object: {_OPT_FORM}")
        label, line, rec = _svcstore._shown_ids(str(o.get("label") or "").strip()), _svcstore._shown_ids(_hooks().unlink_ids(str(o.get("line") or "").strip())), o.get("recommended", False)
        if isinstance(rec, str):
            rec = rec.strip().lower() in ("true", "yes", "1")
        if not label or not line:
            raise ToolError(f"Refused: option {i} needs a label and a line: {_OPT_FORM}")
        hit = _OPTION_LINK.search(label + " " + line)
        if hit:
            raise ToolError(f"Refused: option {i} ({label}) carries a link ({hit.group(0)[:80]}). An option is a clickable card that selects or unselects, so a link in it shows as raw text and can take the select click: "
                            f"take the link out of the option and put it in the ask's Decide part, where a mockup goes as {_MOCKUP_ASK}; the option's line says in words what it is.")
        if any(c in label + line for c in "\r\n\v\f\x85\u2028\u2029"):
            raise ToolError(f"Refused: option {i} ({label}): its label and line are one line each")
        if len(label) > _hooks().option_label_max():
            raise ToolError(f"Refused: option {i}'s label is longer than {_hooks().option_label_max()} characters; put the detail in its line")
        if len(line) > _hooks().option_line_max():
            raise ToolError(f"Refused: option {i} ({label}): its line is longer than {_hooks().option_line_max()} characters; one sentence")
        if label.lower() in seen:
            raise ToolError(f"Refused: two options are labelled {label}")
        seen.add(label.lower())
        out.append({"label": label, "line": line, "recommended": rec is True})
    n = sum(o["recommended"] for o in out)
    if n != 1:
        raise ToolError(f"Refused: exactly one option is recommended (recommended: true), got {n}")
    return out


# The other decision gates (an ask that names alternatives, an open question, a mockup link, one decision per item, the owner's own action, the two notes) are decision_gates.py's;
# their names are imported at `_OPT_FORM` above.


def _watch_anchor_seen(project: str, url: str, since: float) -> str:
    """At wait-set: what anchor-hub already delivered or logged on this anchor since the item's last move (the routing log keeps every notice it recorded for the project; an event
    it filtered or never bound is not kept), and whether it watches the anchor at all: any project's page that holds the anchor makes it watched, and the log of each such page is read
    (the item's own page too). → the reply's lines."""
    out = ""
    try:
        pages = _ascope.holders(_anc.load(), url, _watching.same_anchor)
    except Exception:  # noqa: BLE001
        pages = [project]
    if not pages:
        out += (f"\n(anchor wait: anchor-hub does not watch {url} for {project}, so no notice will arrive: add it with anchors(project=\"{project}\", add=[\"{url}\"]); "
                "until then the wait ends only at its backstop)")
    try:
        rows = sorted((n for pg in dict.fromkeys([project, *pages]) for n in _routing.read(pg, since=since) if n.get("kind") == "anchor" and _watching.same_anchor(str(n.get("anchor") or ""), url)),
                      key=lambda n: float(n.get("ts") or 0))
    except Exception as e:  # noqa: BLE001
        return out + f"\n(anchor wait: the routing log could not be read ({e.__class__.__name__}), so what anchor-hub saw on {url} since the item's last move is not reported)"
    if rows:
        out += (f"\n(anchor wait: anchor-hub already recorded {len(rows)} notice{'s' if len(rows) != 1 else ''} on {url} since the item's last move, "
                f"which this wait does not count; read {'them' if len(rows) != 1 else 'it'} before waiting for more:\n"
                + "\n".join(f"- {_hooks().when_words(dt.datetime.fromtimestamp(float(n.get('ts') or 0), _hooks().zone()))} {_clip_line(str(n.get('text') or ''), 160)} ({n.get('ruling') or 'unruled'})" for n in rows[-8:]) + ")")
    else:
        out += f"\n(anchor wait: anchor-hub recorded nothing on {url} since the item's last move)"
    return out


def _evw_box_spec(sp: "_ew.Spec") -> "_ew.Spec":
    """A box_online spec with the machine as the fleet names it; ToolError naming the known machines when it is none, and when it is online now (nothing to wait for: the precedent of a pr_merged wait
    on a pull request already merged)."""
    boxes = _evwaits.evw_boxes()
    hit = boxes.get(sp.machine.lower())
    if hit is None:
        known = sorted({f for f, _r in boxes.values()}, key=str.lower)
        raise ToolError(f"Refused: box_online names a machine of the fleet and {sp.machine!r} is not one" + (f"; the machines are {', '.join(known)}" if known else "; the server knows no machine yet"))
    fleet, rec = hit
    if rec and _lv.puller_online(rec):
        seen, mins = _lv.ts(rec["puller"]), _lv.online_window() / 60.0
        shown = lambda t: dt.datetime.fromtimestamp(t, _hooks().zone()).strftime("%Y-%m-%d %H:%M %Z")
        raise ToolError(f"Refused: {fleet} is online now (its puller last checked in at {shown(seen)}), so there is nothing to wait for. If it is really down, the same write is accepted once {mins:g} minutes have passed since that "
                        f"check-in, that is after {shown(seen + _lv.online_window())}; otherwise hand the item to the step that follows, or wait for something that has not happened")
    return _ew.Spec(sp.kind, "", fleet)


def _evwait_preread(kind: Any, phrase: Any) -> None:
    """Before the item lock: the facts an event wait's write gate reads (_evwait_gate), so the gate itself makes no GitHub call and no git log under the lock every other write waits on. A pr_merged
    wait reads its pull request on GitHub (paced like the done check: checks.pr_merged, kept in _evwaits.EVW_GH); a pr_released wait warms the git answers for the last-good commit. A failure is the gate's
    case of 'cannot be read': the wait is stored and the catch-up reads it later."""
    k = str(kind or "").strip().lower()
    if (k and k != "event") or not str(phrase or "").strip():
        return
    try:
        sp = _watching.event_spec(phrase)
        if sp.kind == _ew.PR_MERGED:
            with _gb.tag("event_wait"):
                _checks.pr_merged(sp.key, time.time(), _evwaits.EVW_GH)
        elif sp.kind == _ew.PR_RELEASED and sp.key.rpartition("#")[0] != _cfg.canon_repo(_relsvc._own_repo()):
            _rlive.foreign_prs(sp.key.rpartition("#")[0])      # a [released.repos] repository: warm the checkout's merges
        elif sp.kind == _ew.PR_RELEASED:
            good, head = _rlive.released_live_base()
            hit = _evwaits.evw_merge(good, _ew.pr_number(sp))
            if hit:
                _evwaits.evw_live_why(hit[0], good, head)
    except Exception:  # noqa: BLE001
        return


def _evwait_gate(old: dict[str, Any], meta: dict[str, Any], creating: bool = False) -> str:
    """The write guard of an event wait, on the metadata as the write leaves it: when wait_kind or wait_event changed (or on a create) the phrase is parsed and stored in its canonical form, and a wait for
    something that has already happened is refused, since nothing would ever report it (a PR already live or merged). pr_released is release.sh's (this repository's pull requests) or a [released.repos] repository's (live in its checkout). Where GitHub or the
    checkout cannot say, the wait is stored. → the reply's lines."""
    if _watch.stored_kind(meta) != "event":
        return ""
    same_wait = not creating and old.get("wait_kind") == meta.get("wait_kind") and old.get("wait_event") == meta.get("wait_event")
    for f in ("ask_by", "wake"):      # the backstop is a day (it falls due at 00:00 of that day in the instance timezone) or a time: one that is not after now would bring the item back at once
        v = str(meta.get(f) or "").strip()
        ep = _watch.day_epoch(v) if v else None
        if ep is not None and ep <= time.time() and (not same_wait or old.get(f) != meta.get(f)):
            raise ToolError(f"Refused: {f} {v} is not after now, so the event wait would end the moment it is stored. A day falls due at 00:00 of that day in the instance timezone, so today's date is already past: give a later day (tomorrow at the earliest) or a time later today")
    if same_wait:
        return ""
    try:
        sp = _watching.event_spec(meta.get("wait_event"))
    except _ew.EventWaitError as e:
        raise ToolError(f"Refused: {e}")
    if sp.kind == _ew.BOX_ONLINE:
        sp = _evw_box_spec(sp)
    meta["wait_event"] = _ew.text(sp)
    n = _ew.pr_number(sp)
    if sp.kind == _ew.PR_RELEASED:
        repo = sp.key.rpartition("#")[0]
        foreign = repo != _cfg.canon_repo(_relsvc._own_repo())
        if foreign and _rlive.released_foreign(repo) is None:
            raise ToolError(f"Refused: pr_released is release.sh's event and release.sh releases only {_relsvc._own_repo() or 'this repository'}'s pull requests and those of [released.repos] ({_rlive.released_foreign_why()}); wait for {repo}#{n} with pr_merged {repo}#{n}")
        try:
            if foreign:
                good, head = "", ""
                hit = _rlive.foreign_prs(repo)[1].get(n)       # a merge in the checkout's HEAD is live
            else:
                good, head = _rlive.released_live_base()
                hit = _evwaits.evw_merge(good, n)
        except ToolError:
            hit = None                                   # no last-good or HEAD to read: the wait is stored and the catch-up reads it later
        if hit and (foreign or not _evwaits.evw_live_why(hit[0], good, head)):
            raise ToolError(f"Refused: PR #{n} is already merged and live, so there is nothing to wait for. Hand the item to the step that follows it, or wait for something that has not happened")
    elif sp.kind == _ew.PR_MERGED:
        rec = _evwaits.EVW_GH.get(_checks.check_ref(sp.key)) or {}      # only what _evwait_preread read before the item lock: no GitHub call is made here
        if rec.get("merged"):
            raise ToolError(f"Refused: {sp.key} is already merged, so there is nothing to wait for. Hand the item to the step that follows it")
        if rec.get("dead"):
            raise ToolError(f"Refused: {sp.key} {rec['dead']}, so it will never merge")
    who = "the server reads it" if sp.kind in _ew.PR_KINDS else "the server reads the machine's puller check-ins" if sp.kind == _ew.BOX_ONLINE else "the fleet tool reports it at the end of a recycle (client.py recycled)" if sp.kind == _ew.RECYCLE else "the fleet tool reports the end of each op with client.py event" if sp.kind == _ew.FLEET_OP else "it is reported with client.py event"
    quiet = "" if _ew.live(sp) else (f" Nothing tells the server of this event yet (nothing posts `client.py event` for it); only the PR kinds, box_online, recycle and fleet_op are live today, so this wait turns on its backstop {meta.get('ask_by') or meta.get('wake')}, not on the event.")
    return f"\n(event wait: the server watches for {_ew.words(_ew.text(sp))}; {who}. The stall pass does not run for it while it is open; the item comes back to its post-wake mover when the event arrives, or on its backstop date if it never does.{quiet})"


def _machine_note(gid: str, item: dict[str, Any], keeper: str = "") -> str:
    """The reply line of a write that leaves an open step naming a machine of the fleet that is offline now, while the item has no machine anchor for it and no box_online wait on it: a note naming the anchors
    call, never a refusal. A machine is named when a step has its fleet name or a hostname as a whole word (machine_anchor.names_in); only the item's open steps are read; once per write, every machine in one line.
    "" for a closed item, when nothing is named and when the machines cannot be read (a stderr line)."""
    if item.get("status") != "open":
        return ""
    try:
        meta = item.get("metadata") or {}
        texts = [s["text"] for s in _steps.view(meta, keeper=keeper or str(meta.get("owner") or "")) if s["status"] == _steps.OPEN]
        if not texts:
            return ""
        project = str(meta.get("project") or "")
        have = set(_ma.counts(_ma.load(), gid, project))
        if _watch.stored_kind(meta) == "event":
            try:
                sp = _watching.event_spec(meta.get("wait_event"))
                if sp.kind == _ew.BOX_ONLINE:
                    have.add(_evwaits.machine_state(sp.machine)[0].lower() or sp.machine.lower())
            except _ew.EventWaitError:
                pass
        off: dict[str, str] = {}              # an offline machine named by an open step → when it last checked in
        boxes = _evwaits.evw_boxes()
        for fleet in sorted({f for f, _r in boxes.values()}, key=str.lower):
            _f, _since, online, aliases = _evwaits.machine_state(fleet, boxes)
            if online or fleet.lower() in have or not any(_ma.names_in(t, aliases) for t in texts):
                continue
            seen = _lv.ts((boxes[fleet.lower()][1] or {}).get("puller"))
            off[fleet] = f"last checked in {dt.datetime.fromtimestamp(seen, _hooks().zone()).strftime('%Y-%m-%d %H:%M %Z')}" if seen else "has not checked in yet"
        return _ma.missing_note(_gh.shown(gid), project, list(off), off)
    except Exception as e:  # noqa: BLE001  — the write is saved: a note that fails is a stderr line
        print(f"machine anchor: {gid} note not made: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return ""


def _anchor_wait_gate(old: dict[str, Any], meta: dict[str, Any], gid: str = "", creating: bool = False) -> None:
    """The write guard of an anchor wait, on the metadata as the write leaves it: a write that sets or changes wait_anchor on a wait_kind=anchor wait names an anchor that must be on the
    project's list (the anchors tool), else nothing watches it and the wait ends only at its backstop. Listed = scoped to this item (on any project's page) or project-wide on the item's
    own project page, the same URL by `_watching.same_anchor`. A stored wait re-saved unchanged is not judged, nor is any other wait kind. A create has no id yet, so only a project-wide anchor counts.
    The anchors file unreadable (present but not a JSON object; a missing file is an empty list): the wait is stored as before, with a stderr line. A wait_anchor that is no anchor shape the
    anchors tool accepts is refused with that said, not with an add that would be refused too. Raises ToolError naming the anchors call."""
    if _watch.stored_kind(meta) != "anchor":
        return
    url = _model.clean(meta.get("wait_anchor"))
    if not url:
        return
    if not creating and _watch.stored_kind(old) == "anchor" and _model.clean(old.get("wait_anchor")) == url:
        return
    project = str(meta.get("project") or "")
    try:
        if _anc.FILE.exists():      # anchors.load() turns a corrupt file into {}, which would refuse every anchor
            with open(_anc.FILE, encoding="utf-8") as f:
                if not isinstance(json.load(f), dict):
                    raise ValueError("the anchors file is not a JSON object")
        store = _anc.load()
        listed = [e["url"] for e in (_ascope.anchor_scope(store, gid, project) if gid else [])]
        listed += [e["url"] for e in _ascope.clean_entries(store.get(project)) if e["items"] is None]
    except Exception as e:  # noqa: BLE001  — the guard is an extra: a failure in it writes as before
        print(f"anchor wait: {gid or 'a new item'} not judged: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return
    if any(_watching.same_anchor(u, url) for u in listed):
        return
    if not _anc.anchor_id(_anc.split_fragment(url)[0]):
        raise ToolError(f"Refused: wait_anchor {url!r} is not an anchor shape the anchors tool accepts, so it can never be on the list ({_hooks().anchor_shapes()}). "
                        "Set wait_anchor to a link of one of those shapes, add it to the anchors list, then set the wait")
    if _anc.gmail_query_problem(url):
        raise ToolError(f"Refused: wait_anchor {url!r} is a Gmail query the matcher cannot evaluate ({_anc.gmail_query_problem(url)}), so it can never be on the list. {_hooks().gmail_terms()}")
    if creating:
        fix = (f"add it project-wide first: anchors(project=\"{project}\", add=[\"{url}\"]); or create the item without the wait, "
               f"then anchors(project=\"{project}\", add=[\"{url}\"], items=[<its id>]), then set the wait")
    else:
        fix = f"anchors(project=\"{project}\", add=[\"{url}\"], items=[\"{_gh.shown(gid)}\"]), then set the wait again"
    raise ToolError(f"Refused: wait_anchor {url} is not on {project or 'the project'}'s anchors list, so nothing watches it and the wait would end only at its backstop. Add the anchor first: {fix}")


def _old_key_changed(old: dict[str, Any], meta: dict[str, Any], model_set: dict[str, str], model_drop: set[str]) -> bool:
    """Did the write change the old picker key (`post_wake_mover`) on purpose? The save rule drops a stored old key beside a new `mover` and on `clear_mover`: that vanishing is the rule's own
    doing, not a change to the wait (the awaited date, anchor or picker as the writer meant it), so it neither restamps the wait's clock nor starts the chases over, as on main, where the key stayed."""
    k = _model.LEGACY_PICKER_KEY
    if meta.get(k) == old.get(k):
        return False
    if k not in meta and k not in model_set and k not in model_drop and ("mover" in model_set or "mover" in model_drop):
        return False
    return True


def _watch_on_write(gid: str, item_was: dict[str, Any], meta: dict[str, Any], model_set: dict[str, str], model_drop: set[str], writer: str, session_write: bool) -> str:
    """What an update owes the watchers, on the metadata as the write leaves it: a session's write ends the shown arrival (`woke`); a wait newly set, or whose awaited date or anchor moved,
    stamps its time (a notice older than that is not its arrival) and starts the chases over (they were about the old date); a wait cleared drops both. → the reply's lines."""
    note = ""
    old = item_was.get("metadata") or {}
    if session_write:
        meta.pop("woke", None)
    kind = _watch.stored_kind(meta)
    if kind == "event":
        note += _evwait_gate(old, meta)
    if not kind:
        meta.pop("chases", None)
        if isinstance(meta.get("watch"), dict):
            w = {k: v for k, v in meta["watch"].items() if k != "set_at"}
            meta["watch"] = w
            if not w:
                meta.pop("watch")
    elif any(meta.get(k) != old.get(k) for k in ("wait_kind", "wait_anchor", "wait_event", "ask_by", "wake", "until", "waits", "wait_mode")) or _old_key_changed(old, meta, model_set, model_drop):
        w = dict(meta.get("watch") or {}) if isinstance(meta.get("watch"), dict) else {}
        w["set_at"] = time.time()
        meta["watch"] = w
        meta.pop("chases", None)
        if kind == "anchor" and (meta.get("wait_anchor") != old.get("wait_anchor") or _watch.stored_kind(old) != "anchor") and meta.get("wait_anchor"):
            since = float(item_was.get("state_updated") or item_was.get("updated") or 0)
            note += _watch_anchor_seen(str(meta.get("project") or ""), str(meta["wait_anchor"]), since)
    return note


def _watch_close(item: dict[str, Any], reason: str, now: float) -> None:
    """Close the item as not planned on the owner's answer to a watcher ask ("drop"): the server's own act, as checks.check_close: outcome dropped, the live fields cleared as a session's close clears them."""
    meta = dict(item.get("metadata") or {})
    _steps.close_meta(meta, "dropped", NAME, now)       # a close marks the open steps, the server's own close included
    for k in ("next", "next_by", "owner_step", "ask", "needs", "options", "after", "hold", "hold_set", "wake", "recycle", "recycle_at", "idle", "check", "watch_reason", "waiting", "wait_failed", "wait_basis", "cap_ok", "undelivered",
              *_states.DROP_ON_CLOSE, *_states.CLOSE_EXTRA, *_model.DROP_ON_CLOSE, *_watch.DROP_ON_CLOSE):
        meta.pop(k, None)
    meta["outcome"], meta["reason"] = "dropped", _fit(reason, _close_reason_max())     # the server's own close keeps to the reason limit a session's close is held to
    item["status"] = "completed"; item["metadata"] = meta
    item["updated"] = item["state_updated"] = item["confirmed"] = now


def _watch_answer(item: dict[str, Any], meta: dict[str, Any], eff: dict[str, str], now: float) -> str:
    """The owner's pick on a watcher ask, applied on the metadata `_answer` is leaving (his decision is already out of needs and the ask and options off the item): arrived → the item goes to
    the session that takes it after the wait (`then`), alive; not yet / keep waiting → the wait is put back with the date he gave; drop → closed as not planned. → what happened, in words."""
    w = meta.get("watch") if isinstance(meta.get("watch"), dict) else {}
    asked = str(w.get("asked") or "")
    what = _watch.subject_of({**(w.get("was") or {}), **{k: v for k, v in meta.items() if k in ("party", "wait_event")}})
    do = eff["do"]
    if do == "arrived":
        was_post = _watch.was_picker(w.get("was"))
        post = str(meta.get("then") or ("" if _model.is_owner(was_post) else was_post) or _telling.auto_mover(_telling.fallback_mover(str(meta.get("project") or "")), str(meta.get("project") or "")))      # a fallback is never a front agent when the project has a builder; he is the one answering: a post-wake mover that is he falls back to the project's builder, else its -main agent
        _watch.turn_alive(meta, post, f"{OWNER} says {what} arrived", now)
        meta.pop("chases", None)
        return f"arrived → {_watching.watch_label(post)}"
    if do == "words":     # his words with no button: never an arrival or a drop; the post-wake mover has the item, the wait's record (watch.was) and his words, and judges
        was_post = _watch.was_picker(w.get("was"))
        post = str(meta.get("then") or ("" if _model.is_owner(was_post) else was_post) or _telling.auto_mover(_telling.fallback_mover(str(meta.get("project") or "")), str(meta.get("project") or "")))
        keep = w.get("was")
        _watch.turn_alive(meta, post, f'{OWNER} answered in words: "{_clip_line(eff.get("text") or "", 300)}"', now)
        meta.pop("options", None); meta.pop("ask", None)
        if keep:
            meta["watch"] = {**(meta.get("watch") if isinstance(meta.get("watch"), dict) else {}), "was": keep}
        return f"answered in words → {_watching.watch_label(post)}"
    if do == "wait":
        meta.pop("then", None); meta.pop("woke", None); meta.pop("mover", None)      # before the restore: the wait's own mover (who picks it up) comes back with it and stays
        _watch.restore_wait(meta, eff["date"], reset_chases=True, now=now)      # a moved date is a new round: the backstop and the chases start over
        return f"waits again until {eff['date']}"
    if do == "drop":
        item["metadata"] = meta
        _watch_close(item, f"dropped on {OWNER}'s answer on the board: {what} is not waited for any more", now)
        meta.clear(); meta.update(item["metadata"])
        return "dropped"
    return ""


def _front_step_mark(gid: str, h: "str | None", now: float, mover: str = "") -> bool:
    """The front-step rule's clock (front_step.py), written as the server's own bookkeeping (no writer: no activity, no confirm, no notice, no History line). With a step hash `h` and the item's mover:
    `metadata.stuck_since` = {step, mover, at: now} when the item is open, `h` is still its first open step, the finding still holds against that mover (read again under the lock) and no clock for that step
    under that mover is there already; with None: the clock is dropped. → whether the item was written."""
    _ac, _fs = _hooks().audit_mod("audit_checks"), _hooks().audit_mod("front_step")
    with _writes.ITEM_LOCK:
        item = _svcstore._load(gid)
        meta = item.get("metadata")
        if not isinstance(meta, dict):
            return False
        if h is None:
            if _fs.CLOCK not in meta:
                return False
            meta.pop(_fs.CLOCK, None)
        else:
            first = _ac.first_open_step(meta)
            if item.get("status") != "open" or not first or not mover or _fs.step_hash(first) != h or _fs.clock(meta, h, mover) is not None:
                return False
            if _fs.still_holds(gid, item, _svcstore._load, mover, now):
                return False
            meta[_fs.CLOCK] = {"step": h, "mover": mover, "at": now}
        _writes.save(gid, item)
        return True


def _front_step_move(gid: str, h: str, opener: str, mover: str, hours: float, now: float) -> "dict[str, Any]":
    """The front-step rule's move (front_step.py): the item's first open step, whose hash is `h`, opens with `opener` (a front agent or a retired session) and has had its clock for `hours` hours, is reworded
    to open with `mover`, the item's mover, through the same pieces an update's reword uses (nextlines.reword, steps.apply, the step's proof), the line now the mover's own. A History line (the stall
    log) names the original opener, so the step is put back by a reword. Read again under the lock: nothing moves when the item is closed, the step is another or reworded, or the clock is not due. The clock is
    dropped and the step's hash is kept in `metadata.stuck_moved`, so the step moves once. The server's own write (no writer). → {"moved": bool, "why": str, "line": the step's new first line}."""
    _ac, _fs = _hooks().audit_mod("audit_checks"), _hooks().audit_mod("front_step")
    with _writes.ITEM_LOCK:
        item = _svcstore._load(gid)
        meta = item.get("metadata")
        if not isinstance(meta, dict) or item.get("status") != "open":
            return {"moved": False, "why": "the item is not open"}
        first = _ac.first_open_step(meta)
        if not first or _fs.step_hash(first) != h or _steps.opener(first) != opener:
            return {"moved": False, "why": "the first open step is not the one the clock was kept for"}
        at = _fs.clock(meta, h, mover)
        if at is None or now - at < hours * 3600:
            return {"moved": False, "why": "its clock is not due"}
        if (why := _fs.still_holds(gid, item, _svcstore._load, mover, now)):
            return {"moved": False, "why": why}
        name = _sr._session_label(mover) or mover
        new_text = _fs.reopen(first, name)
        if not new_text:
            return {"moved": False, "why": "the step's first line cannot be reopened with the mover's name"}
        keeper = str(meta.get("owner") or "")
        steps_old = _steps.view(meta, keeper=keeper)
        i = next((k for k, st in enumerate(steps_old) if st["status"] == _steps.OPEN and st["text"] == first), None)
        if i is None:
            return {"moved": False, "why": "the step is not on the checklist"}
        if any(k != i and st["status"] == _steps.OPEN and _steps.key(st["text"]) == _steps.key(new_text) for k, st in enumerate(steps_old)):
            return {"moved": False, "why": "another open step already reads the same"}
        if not _nl.reword(meta, first, new_text, keeper, writer=steps_old[i].get("writer") or None, new_writer=_hooks().session_id(mover) or mover):
            return {"moved": False, "why": "the step's line is not in next"}
        proofs = dict(meta["step_proof"]) if isinstance(meta.get("step_proof"), dict) else {}
        if (pv := proofs.pop(_steps.key(first), None)) is not None:
            proofs[_steps.key(new_text)] = pv                       # an event that finishes the step still finishes it
            meta["step_proof"] = proofs
        steps_old[i] = {**steps_old[i], "text": new_text}
        meta["steps"] = _steps.stored(_steps.apply(steps_old, str(meta.get("next") or ""), [], [], NAME, now, strict=False, reworded={i: new_text}))
        meta.pop(_fs.CLOCK, None)
        meta[_fs.LANDED] = {"step": _fs.step_hash(new_text), "mover": mover, "at": now}       # the hourly audit line counts the mover's quiet time from here, wake or none
        meta[_fs.MOVED] = [*[x for x in (meta.get(_fs.MOVED) if isinstance(meta.get(_fs.MOVED), list) else []) if x != h], h][-_fs.MOVED_KEEP:]
        shown = f"{(now - at) / 3600:.1f}".rstrip("0").rstrip(".")
        _stall.note(meta, now, f"step moved from {_sr._session_label(opener) or opener} to {name} after {shown} hours open with the stuck-elsewhere finding unanswered (reword it back to undo): "
                    f"\"{_clip_line(_steps.strip_opener(_steps.first_line(first)), 70)}\"")
        _writes.save(gid, item, note="front step moved to the mover")
        return {"moved": True, "why": "", "line": _steps.first_line(new_text)}


def _filing_deliver(to: str, text: str, fyi: bool = False) -> "tuple[bool, str]":
    """The ten-minute passes' message (filing and dates), sent from inside the server as a script's message to a session (the same function the `message` route calls); a refusal is a failed delivery, as the route's 400 is."""
    _ar = _hooks().audit_mod("audit_run")
    try:
        return True, _messaging._message(to, text, _ar.SENDER, "server", os.uname().nodename, fyi)
    except ToolError as e:
        return False, str(e)
