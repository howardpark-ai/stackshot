"""proofs.py: a step's proof arrives, and the hand-over that follows.

A step of next that names the event which completes it (model/step_proof.py) is ticked by the server when the event happens, not when a session remembers to: `pr_released` is a release.sh call or the sweep finding the
merge in last-good and HEAD (service/released.py), `pr_merged` is GitHub saying the pull request is merged (the done check's own read, `checks.pr_merged`, plus git for this repository's merges the checkout already
holds). This module holds the write side of a step's explicit proof (`step_proof_set`, `step_proof_prune`), the settle of one item for one event (`proof_item`: a pure proof step is ticked, the mover told once what the next
open step is, the item closed when none is open), the hand-over to the session the next step names (`handover`), and the pass that finds the events that have happened (`sweep_proofs`, the clock `proof_tick`, and the
`client.py sweep-step-proof` call). A pull request closed without a merge never ticks anything. Reads (git, GitHub) come before the item lock, writes under it.

What it still reaches in server.py comes through `Hooks` in service/checks_hooks.py, looked up when it runs, so a suite that replaces one on server.py is the one called. A suite that replaces a function or a
clock of this module sets it here (and `time` here, since this module reads its own).

Imports point down only: this module imports the domain, core and the services beside it, never web/ and never audit/."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any

from fastmcp.exceptions import ToolError

from stackshot.anchors import anchors as _anc
from stackshot.core import config as _cfg
from stackshot.core import ghbudget as _gb
from stackshot.core.instance import NAME, OWNER
from stackshot.core.store import _item_files
from stackshot.fleet.sessions_registry import _session_label, _sessions_index
from stackshot.github import ghsync as _gh
from stackshot.github import pr_state as _prs
from stackshot.model import activity as _activity
from stackshot.model import field_gates as _fg
from stackshot.model import model as _model
from stackshot.model import nextlines as _nl
from stackshot.model import states as _states
from stackshot.model import step_proof as _sp
from stackshot.model import steps as _steps
from stackshot.model.bullet_text import _clip_line
from stackshot.model.needs import _NEEDS_KINDS, _canon_needs, _needs_of, _needs_store
from stackshot.service import checks as _checks
from stackshot.service import handoff as _handoff
from stackshot.service import released_live as _live
from stackshot.service import stall as _stallsvc
from stackshot.service import telling as _telling
from stackshot.service import wakes as _wakes
from stackshot.service import writes as _writes
from stackshot.service.checks_hooks import hooks as _hooks
from stackshot.service.store import _load
from stackshot.waits import wait_end as _we
from stackshot.waits import handover as _hv
from stackshot.waits import watchers as _watch


RELEASED_TOLD = "released_told"     # metadata: the PR keys ("owner/repo#n") this item's mover was told are live: a rerun tells nobody twice


def proof_ref(pr: str, own: str) -> str:
    """The pull request a step's proof names, as written ("#4", "4", "owner/repo#4", a PR URL) → "owner/repo#n" (repo through [github.moved]); refused with the forms otherwise."""
    s = str(pr or "").strip()
    m = re.fullmatch(r"#?(\d+)", s)
    if m:
        if not own:
            raise ToolError(f"Refused: step_proof {s!r} names no repository and this checkout has no GitHub origin remote: write <owner>/<repo>#<n> or the PR's URL")
        return f"{own}#{int(m.group(1))}"
    m = _checks.PR_RX.match(s)
    if not m or not m.group(1).strip(".") or not m.group(2).strip("."):
        raise ToolError(f"Refused: step_proof {s!r} is not a pull request: write #<n> (this repository's), <owner>/<repo>#<n>, or the PR's URL")
    return f"{_cfg.canon_repo(m.group(1) + '/' + m.group(2))}#{int(m.group(3))}"


def step_proof_set(meta: dict[str, Any], steps: list[dict[str, Any]], spec: Any) -> str:
    """The `step_proof` parameter of create and update, written onto `meta` for the open steps of `steps` (the checklist as the call leaves it) → the reply lines. Each entry names an open step (its 1-based
    position or the exact text of its first line) and its proof (step_proof.py); the proof is stored under the step's key and goes with the step. Refused, before anything is written: a step that is not
    open or not found, his step (it is ticked by his answer), a proof that is not `pr_merged|pr_released <PR>`, a release of the PR of a repository that is neither this one nor in [released.repos]."""
    try:
        entries = _sp.parse_spec(spec)
    except _sp.ProofError as e:
        raise ToolError(f"Refused: {e}")
    if entries is None:
        return ""
    own = _cfg.canon_repo(_hooks().own_repo())
    cur = dict(meta["step_proof"]) if isinstance(meta.get("step_proof"), dict) else {}
    if not entries:
        meta.pop("step_proof", None)
        return "\n(step_proof: cleared)" if cur else ""
    note = ""
    for ref, text in entries:
        try:
            ix = _steps.resolve(steps, [ref], "step_proof")
            kind, pr = _sp.split_proof(text)
        except (_steps.StepError, _sp.ProofError) as e:
            raise ToolError(f"Refused: {e}")
        for i in ix:
            k = _steps.key(steps[i]["text"])
            if kind == "none":
                if cur.pop(k, None) is not None:
                    note += f"\n(step {i + 1} proof: cleared)"
                    _hooks().wait_end_sent_back(meta, (_we.PR, _we.DELIVERY))      # a proof the server set from the line's words, sent back
                continue
            if _steps.is_his(steps[i]["text"], unnamed_is_his=False):
                raise ToolError(f"Refused: step {i + 1} is {OWNER}'s own step: it is ticked by his answer, never by an event, so it takes no proof")
            key = proof_ref(pr, own)
            if kind == _sp.PR_RELEASED and key.rsplit("#", 1)[0] != own and _live.released_foreign(key.rsplit("#", 1)[0]) is None:
                raise ToolError(f"Refused: step {i + 1}: pr_released is for this repository's pull requests ({own or 'no origin remote'}), which release.sh releases, and for a repository in [released.repos] ({_live.released_foreign_why()}); {key} is another repository's: use pr_merged")
            cur[k] = _sp.stored(kind, key)
            note += f"\n(step {i + 1} proof: {kind} {key}: the server ticks the step when it happens)"
    if cur:
        meta["step_proof"] = cur
    else:
        meta.pop("step_proof", None)
    return note


def step_proof_prune(meta: dict[str, Any], steps: list[dict[str, Any]]) -> str:
    """A proof goes with its step: the stored proofs of steps that are no longer open are dropped. → one reply line per proof dropped, saying why (its step is done, dropped, or no longer in the list: its text changed)."""
    if not isinstance(meta.get("step_proof"), dict):
        return ""
    state = {_steps.key(s["text"]): s["status"] for s in steps}
    kept = {k: v for k, v in meta["step_proof"].items() if state.get(k) == _steps.OPEN}
    note = "".join(f"\n(step proof dropped: {_clip_line(str(k), 70)} ← {v}: " + ("its step text changed, so it is a different step now; give the new step its proof again if it still waits on that event" if k not in state else f"its step is {state[k]}") + ")"
                   for k, v in meta["step_proof"].items() if k not in kept)
    if kept:
        meta["step_proof"] = kept
    else:
        meta.pop("step_proof", None)
    return note


def step_proofs(meta: dict[str, Any]) -> dict[str, tuple[str, str]]:
    """The explicit proofs stored on an item (`metadata.step_proof`) → {steps.key of the step: (kind, "owner/repo#n")}."""
    raw = meta.get("step_proof")
    return {str(k): _sp.read_stored(v) for k, v in raw.items()} if isinstance(raw, dict) else {}


def proof_stamp(kind: str, key: str) -> str:
    """What an item's `released_told` list holds for an event its mover was told of: the bare PR key for a release (as it always did), "merged <key>" for a merge."""
    return key if kind == _sp.PR_RELEASED else f"merged {key}"


def proof_hits(cl: list[dict[str, Any]], opened: list[int], meta: dict[str, Any], kind: str, n: int, key: str, anchored: set[str], named: bool) -> dict[int, bool]:
    """{index of an open step this event is the proof of: is the step a pure proof step (ticked on the event) or does it name more (the mover is told)?}
    An explicit proof (`step_proof`) always counts and always ticks. A step's words count when the item is anchored to the PR or names its URL (a bare "#n" may be another
    repository's), except a gate ("once #n is released ..."), which also counts on an item anchored to any pull request of that repository, since it says what the step waits on, not what it is."""
    explicit = step_proofs(meta)
    repos = {k.rsplit("#", 1)[0] for k in anchored}
    out: dict[int, bool] = {}
    for i in opened:
        if _steps.is_his(cl[i]["text"], unnamed_is_his=False):      # his own step is ticked by his answer, never by an event
            continue
        if explicit.get(_steps.key(cl[i]["text"])) == (kind, key):
            out[i] = True
            continue
        h = _sp.hits(_sp.text_proofs(cl[i]["text"]), kind, n, key, _hooks().pr_key)
        if not h or not (named or any(p.url for p in h) or (all(p.via == "gate" for p in h) and key.rsplit("#", 1)[0] in repos)):
            continue
        out[i] = all(p.pure for p in h)
    return out


def proof_other(text: str, meta: dict[str, Any], kind: str, n: int, key: str) -> bool:
    """Is this open step the pure proof step of some other pull request (explicit or in its words)? Then nothing is for the mover to do until that one's event."""
    ek, ekey = step_proofs(meta).get(_steps.key(text), ("", ""))
    if ek and ekey != key:
        return True
    return _sp.other_pure(_sp.text_proofs(text), kind, n, key, _hooks().pr_key)


PROOF_LOGGED: set[tuple[str, str, str]] = set()


def proof_log_once(gid: str, key: str, why: str, line: str = "") -> None:
    """The pass's "left alone" line, once per item, pull request and reason (a held item would otherwise log it every two minutes)."""
    if (gid, key, why) in PROOF_LOGGED:
        return
    if len(PROOF_LOGGED) > 4000:
        PROOF_LOGGED.clear()
    PROOF_LOGGED.add((gid, key, why))
    print(line or f"released: {gid} left alone for {_live.pr_shown(key)}: {why}", file=sys.stderr, flush=True)


PROOF_TOLD_SID: dict[str, tuple[str, float]] = {}      # gid → (the session id a step notice went to, when): for one notice per session when an event wait ends on the same release (the release path and the catch-up read it)
PROOF_TOLD_FOR = 300.0                  # a step notice is "the same event's" for this long


def told_recent(now: float | None = None) -> dict[str, str]:
    """{gid: session id} of the step notices sent in the last PROOF_TOLD_FOR seconds (proof_item); older ones are dropped."""
    now = time.time() if now is None else now
    for g in [g for g, (_sid, at) in PROOF_TOLD_SID.items() if now - at > PROOF_TOLD_FOR]:
        PROOF_TOLD_SID.pop(g, None)
    return {g: sid for g, (sid, _at) in PROOF_TOLD_SID.items()}


def handover_kind(name: str) -> str:
    """What a step's opener is, for handover.decide: the owner, a front agent or a retired session or a page's keeper (never moved to by this rule), a session of the fleet (a page lists it, or the fleet knows the name), else no session."""
    if _model.is_owner(name):
        return _hv.OWNER
    try:
        roles = _anc.session_roles()
        r = roles.get(_hooks().role_name(roles, name)) or {}
        if r:
            return _hv.FRONT if r.get("retired") or r.get("role") in ("front", _anc.NAME_ROLE) else _hv.SESSION
        return _hv.SESSION if name in _hooks().session_roster() or _session_label(name) in _hooks().session_roster() else _hv.OTHER
    except Exception:  # noqa: BLE001  — a role map that cannot be read names no session to move to
        return _hv.OTHER


def handover_down(name: str) -> str:
    """Why this session cannot take an item now ("" when it can): no pane, a retired one, no heartbeat, or a last turn that ended in an error."""
    try:
        return _handoff.handoff_pane(name) or _hooks().session_down(name, _anc.names(), _sessions_index())
    except Exception as e:  # noqa: BLE001
        return f"its pane could not be read ({e.__class__.__name__})"


def handover(gid: str, now: float, done: list[str], dry: bool = False) -> dict[str, Any] | None:
    """A step of the item is done (ticked by its proof, or marked by hand) and the item is still open: when the next open step opens with another session, the item's mover becomes that session and it is told, with the step's text
    (handover.py has the rules). That session down or unknown: the item stays with its mover, who is told the step and why. The owner, a front agent and a name that is no session: nothing moves. Idempotent by the record
    `metadata.handover` (the step's hash and what was done). `done` = the first lines of the steps just done. Takes the item lock itself. → the row {action: moved | fallback | left | none, to, step, why, told}, None when the item is closed."""
    with _writes.ITEM_LOCK:
        it = _load(gid)
        if it.get("status") != "open":
            return None
        meta = dict(it.get("metadata") or {})
        mover = _telling.holder(it)
        row: dict[str, Any] = {"item": gid, "shown": _gh.shown(gid), "action": "none", "to": "", "step": "", "why": "", "told": ""}
        if (why := _live.released_skip(it, meta, mover)):
            return {**row, "action": "left", "why": why}
        plan = _hv.decide(meta, str(meta.get("owner") or ""), mover, handover_kind, handover_down, _handoff.ho_same)
        step = _clip_line(_steps.first_line(plan["step"]), 140)
        row.update(to=plan["to"], step=step, why=plan["why"])
        if plan["action"] == "none" or dry:
            return {**row, "action": plan["action"] if dry else "none"}
        to, h = plan["to"], plan["hash"]
        frm, project, subject = mover, str(meta.get("project") or ""), str(it.get("subject") or "")
        did = "; ".join(_clip_line(x, 80) for x in done) or "a step"
        if plan["action"] == "fallback":
            _hv.mark(meta, h, _hv.FALLBACK, to, now, plan["why"])
            it["metadata"] = meta
            _writes.save(gid, it, note=f"step hand-over: the next step is {_session_label(to)}'s but it cannot take the item now ({_clip_line(plan['why'], 100)}), so the item stays with {_session_label(frm) or 'its mover'}: {step}")
            row.update(action="fallback")
            if frm and not _model.is_owner(frm) and not _telling.front_keeper(frm, project)[0]:
                _telling.tell_woken(gid, _hooks().session_id(frm), f"[stackshot] {_gh.shown(gid)}: the next step is {_session_label(to)}'s ({step}), but {_session_label(to)} cannot take the item now ({_clip_line(plan['why'], 100)}), "
                            f"so it stays with you. Do the step yourself, hand the item to another session, or reword the step. {subject} ({project}) → {_telling.notice_link(gid)}", tag="handoff")
                row["told"] = _session_label(frm)
            return row
        keep = [x for x in _needs_of(meta) if x.lower() in _NEEDS_KINDS or not (_handoff.ho_same(x, frm) or _handoff.ho_same(x, to))]
        _needs_store(meta, _canon_needs([to, *keep]))
        if meta.get("mover"):
            meta["mover"] = to
        _hv.mark(meta, h, _hv.MOVED, to, now)
        it["metadata"] = meta
        _writes.save(gid, it, note=f"step hand-over: {did} is done and the next step is {_session_label(to)}'s, so the item moved from {_session_label(frm) or 'its mover'} to {_session_label(to)}: {step}")
        text = (f"[stackshot] {_gh.shown(gid)} is yours: {did} is done, and the next step is yours: {step}. {subject} ({project}). Do your part and close it or hand it back"
                + (f" (sender={_session_label(frm)!r})" if frm else "") + f"; starting work on it (a step marked done, a step status in progress) counts as taking it; a note does not. → {_telling.notice_link(gid)}")
        _telling.tell_woken(gid, _hooks().session_id(to) or to, text, tag="handoff")
        PROOF_TOLD_SID[gid] = (_hooks().session_id(to), now)
        row.update(action="moved", told=_session_label(to))
        return row


def proof_item(gid: str, n: int, key: str, live: str, anchored: set[str], dry: bool, now: float, kind: str = _sp.PR_RELEASED, dead: str = "") -> dict[str, Any] | None:
    """Settle one open item for the event `kind` (pr_released: the pull request `key` (#`n`) is live; pr_merged: it is merged); `live` says when and at which commit. → the row for the reply,
    or None when the item is not one this event settles (closed, no open step that names the PR as its proof). The step is ticked by the server when it is the proof's pure step (or its explicit
    proof); when no open step is left the item closes; otherwise the mover gets one notice naming the next open step. Under the item lock (the caller's)."""
    it = _load(gid)
    meta = dict(it.get("metadata") or {})
    if it.get("status") != "open":
        return None
    keeper = str(meta.get("owner") or "")
    cl = _steps.view(meta, keeper=keeper)
    named = key in proof_named(it, cl, anchored)     # not anchored to the PR: it counts only when the item names the PR's URL
    opened = [i for i, s in enumerate(cl) if s["status"] == _steps.OPEN]
    hits = proof_hits(cl, opened, meta, kind, n, key, anchored, named)
    if not hits:
        return None
    word = _sp.WORD[kind]
    ref = _live.pr_shown(key)
    tests = " and main's tests passed" if kind == _sp.PR_RELEASED and key.rsplit("#", 1)[0] == _cfg.canon_repo(_hooks().own_repo()) else ""      # only this repository's release is gated on main's full run
    mover = _telling.holder(it)
    row: dict[str, Any] = {"item": gid, "shown": _gh.shown(gid), "subject": str(it.get("subject") or ""), "mover": _session_label(mover) if mover else "", "kind": kind, "ref": ref}
    why = _live.released_skip(it, meta, mover)
    if why:
        proof_log_once(gid, key, why)
        return {**row, "action": "left", "why": why}
    step = _steps.first_line(cl[min(hits)]["text"])[:120]
    told_before = [str(x) for x in (meta.get(RELEASED_TOLD) or [])]
    if dead:      # the proof can never arrive (its pull request was closed unmerged): nothing is ticked; the mover is told once, to fix the step
        dstamp = f"dead {key}"
        if dstamp in told_before:
            return {**row, "action": "left", "why": f"its mover was told already that {ref} was closed without a merge", "dead": dead}
        row.update(action="told", dead=dead, step=step)
        if dry:
            return row
        meta[RELEASED_TOLD] = [*told_before, dstamp][-20:]
        it["metadata"] = meta
        it["updated"] = now
        _writes.save(gid, it, note=f"{NAME}: {ref} was closed without being merged, so the step \"{step}\" cannot be ticked by it" + ("" if mover else " (no mover to tell)"), activity=_activity.EVENT)
        if mover:
            _telling.tell_woken(gid, _hooks().session_id(mover), f"[stackshot] {_gh.shown(gid)}: {ref} was closed without being merged, so its step \"{step}\" will never be ticked by it. "
                        f"Reword or drop the step, or give it another proof. {it.get('subject') or ''} → {_telling.notice_link(gid)}", tag="release")
            row["told"] = _session_label(mover)
        else:
            row["told"] = ""
            print(f"released: {gid} has no mover to tell that {ref} was closed without a merge", file=sys.stderr, flush=True)
        return row
    pure = [i for i, p in hits.items() if p]
    rest = [i for i in opened if i not in pure]
    if not rest:      # its only open steps are this event's proof: the item is done
        reason = _fg._fit(f"{ref} is live ({live}){tests}" if kind == _sp.PR_RELEASED else f"{ref} is merged ({live})", _fg._close_reason_max())
        row.update(action="closed", reason=reason, step=step)
        if dry:
            return row
        _telling.CLOSE_WAS.item = json.loads(json.dumps(it))
        try:
            _steps.close_meta(meta, "done", NAME, now)       # the proof's step (and only it) is marked done by the server
            for k in ("next", "next_by", "owner_step", "ask", "needs", "options", "after", "hold", "hold_set", "wake", "recycle", "recycle_at", "idle", "check", "watch_reason", "waiting", "wait_failed", "wait_basis", "step_proof", *_states.DROP_ON_CLOSE, *_states.CLOSE_EXTRA, *_model.DROP_ON_CLOSE, *_watch.DROP_ON_CLOSE):
                meta.pop(k, None)
            meta["outcome"], meta["reason"] = "done", reason
            it["status"] = "completed"; it["metadata"] = meta
            it["updated"] = it["state_updated"] = it["confirmed"] = now
            _writes.save(gid, it, note=(f"closed by {NAME}: {ref} is live{tests}, and its only open step was that release" if kind == _sp.PR_RELEASED
                                 else f"closed by {NAME}: {ref} is merged, and its only open step was waiting on that merge"), activity=_activity.EVENT)   # the server's act: no session turn, no page owed; the anchor's event is activity
        finally:
            _telling.CLOSE_WAS.item = None
        print(f"released: {gid} closed, {ref} is {word} — {it.get('subject')}", file=sys.stderr, flush=True)
        try:
            _wakes.release_after(gid, "done", "", "")
        except Exception as e:  # noqa: BLE001
            print(f"released: {gid} closed but its after releases failed: {e}", file=sys.stderr, flush=True)
        return row
    stamp = proof_stamp(kind, key)
    already = stamp in told_before
    quiet = bool(pure) and all(proof_other(cl[i]["text"], meta, kind, n, key) for i in rest)      # every other open step is itself the proof step of another PR: nothing for the mover to do yet
    if already and not pure:
        return {**row, "action": "left", "why": f"its mover was told already that {ref} is {word}"}
    nxt = next((_steps.first_line(cl[i]["text"])[:140] for i in rest if i not in hits), "") or next((_steps.first_line(cl[i]["text"])[:140] for i in rest), "")
    row.update(action="ticked" if pure else "told", quiet=quiet, step=step, ticked=[_steps.first_line(cl[i]["text"])[:120] for i in pure], next_step=nxt)
    if dry:
        return row
    if pure:
        for i in pure:
            cl[i] = {**cl[i], "status": _steps.DONE, "by": NAME, "at": now}
        _nl.prune(meta, [cl[i]["text"] for i in pure], keeper)
        meta["steps"] = _steps.stored(cl)
        step_proof_prune(meta, cl)      # a proof whose step is no longer open goes
    due = not already and not quiet      # a notice is owed; it is recorded as told even when the item has no holder to send it to, so a later pass does not owe it again
    tell = bool(mover) and due
    if due:
        meta[RELEASED_TOLD] = [*told_before, stamp][-20:]
    if pure or due:
        it["metadata"] = meta
        it["updated"] = now
        _writes.save(gid, it, note=(f"step done: {step} ({ref} is {word}{tests}; ticked by {NAME})" if pure
                             else f"{NAME}: told its mover {ref} is {word}{tests}"), activity=_activity.EVENT)
    note = (f"[stackshot] {_gh.shown(gid)}: {ref} is {word}; its step is " + ("ticked" if pure else "not ticked (it names a follow-up)") + "; the item's other open steps remain. "
            + (f"Next step: {nxt}. " if nxt else "") + f"{it.get('subject') or ''} → {_telling.notice_link(gid)}")
    if tell:
        _telling.tell_woken(gid, _hooks().session_id(mover), note, tag="release")      # a real notice, not the log-only result: the mover's next step waits on it
        row["told"] = _session_label(mover)
        PROOF_TOLD_SID[gid] = (_hooks().session_id(mover), now)
    else:
        row["told"] = ""
        print(f"released: {gid} " + (f"ticked without telling its mover: every other open step waits on another PR" if quiet else f"mover was told already that {ref} is {word}" if already else f"has no mover to tell that {ref} is {word}"), file=sys.stderr, flush=True)
    if pure and not quiet:      # the ticked step may leave another session's step next: that session is handed the item and told (handover.py)
        try:
            ho = handover(gid, now, row["ticked"])
        except Exception as e:  # noqa: BLE001  — the tick is saved: a hand-over that fails is a stderr line, and the audit finds the next session unreached
            ho = None
            print(f"released: {gid} hand-over not made: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        if ho and ho.get("action") in ("moved", "fallback"):
            row["handover"] = {k: ho[k] for k in ("action", "to", "step", "why", "told")}
    return row


# ----------------------------------------------------------------------------- a step's proof arrives (the first step of the hand-over overhaul)
# A step of next that names the event which completes it (step_proof.py) is ticked by the server when the event happens, not when a session remembers to: `pr_released` is a
# release.sh call or the sweep below finding the merge in last-good and HEAD (the rule above), `pr_merged` is GitHub saying the pull request is merged (the done check's own
# read, pr_merged, plus git for this repository's merges the checkout already holds). The pass (proof_tick, every [PROOF_EVERY] seconds) and `client.py sweep-step-proof`
# read the same facts and settle the same way (proof_item): a pure proof step is ticked, the mover told once what the next open step is, the item closed when none is open.
# A pull request closed without a merge never ticks anything. Reads (git, GitHub) come before the item lock, writes under it.
PROOF_EVERY = 120.0
PROOF_LAST = [0.0]
PROOF_GH_READS = 20            # new GitHub reads one pass makes at most; the rest wait for the next pass (a kept answer costs nothing)


def proof_state_path() -> Path:
    return _cfg.state("step-proof.json")


def proof_state() -> dict[str, Any]:
    try:
        d = json.load(open(proof_state_path(), encoding="utf-8"))
    except Exception:  # noqa: BLE001
        d = {}
    return d if isinstance(d, dict) else {}


def proof_gh_load() -> dict[str, Any]:
    d = proof_state()
    return d.get("github") if isinstance(d.get("github"), dict) else {}


def proof_state_save(**fields: Any) -> None:
    """Merge `fields` into the pass's state file (the kept GitHub answers, the mark that the first dry pass was logged)."""
    try:
        p = proof_state_path(); p.parent.mkdir(parents=True, exist_ok=True)
        d = {**proof_state(), **fields}
        tmp = p.with_suffix(".tmp"); tmp.write_text(json.dumps(d, indent=1) + "\n", encoding="utf-8"); os.replace(tmp, p)
    except Exception as e:  # noqa: BLE001
        print(f"step proof: state not saved: {e}", file=sys.stderr, flush=True)


def proof_gh_save(gh_st: dict[str, Any], seen: set[str]) -> None:
    proof_state_save(github={k: v for k, v in gh_st.items() if k in seen})


def proof_named(it: dict[str, Any], cl: list[dict[str, Any]], anchored: set[str]) -> set[str]:
    """The pull requests an item names for a step's words to count: those anchored to it, and those whose URL its description or steps carry (a bare "#n" on any other item may be another repository's)."""
    words = "\n".join([str(it.get("description") or ""), *(s["text"] for s in cl)])
    return set(anchored) | {k for m in _hooks().pr_url().finditer(words) if (k := _hooks().pr_key(m.group(0)))}


def proof_events(cl: list[dict[str, Any]], meta: dict[str, Any], own: str, named: set[str]) -> set[tuple[str, int, str]]:
    """The events the open steps of an item wait on: {(kind, n, "owner/repo#n")}, from the explicit proofs and from the steps' words as `proof_hits` will read them: a bare "#n" counts only for a pull
    request the item names (`named`), a URL always, a gate also for a pull request of a repository the item is anchored to. His own steps wait on his answer, not on an event."""
    out: set[tuple[str, int, str]] = set()
    explicit = step_proofs(meta)
    repos = {k.rsplit("#", 1)[0] for k in named}
    foreign = _cfg.released_repos()
    for s in cl:
        if s["status"] != _steps.OPEN or _steps.is_his(s["text"], unnamed_is_his=False):
            continue
        ek, ekey = explicit.get(_steps.key(s["text"]), ("", ""))
        if ek and "#" in ekey:
            out.add((ek, int(ekey.rsplit("#", 1)[1]), ekey))
        for p in _sp.text_proofs(s["text"]):
            ks = [f"{own}#{p.n}"] if p.n and own else [_hooks().pr_key(p.url)] if p.url else []
            if p.n and p.kind == _sp.PR_RELEASED:      # a bare #n on an item anchored to that number in a [released.repos] repository is that repository's (as `released` reads it)
                ks += [k for k in sorted(named) if k.endswith(f"#{p.n}") and k.rsplit("#", 1)[0] in foreign and k not in ks]
            for k in ks:
                if k and (p.url or k in named or (p.via == "gate" and k.rsplit("#", 1)[0] in repos)):
                    out.add((p.kind, int(k.rsplit("#", 1)[1]), k))
    return out


def proof_final(ref: str, *stores: dict[str, Any]) -> dict[str, Any]:
    """A kept GitHub answer that can no longer change (merged, or closed without a merge), from the pass's own file or from the done checks' (checks.json): {} when there is none."""
    for st in stores:
        rec = st.get(ref) if isinstance(st.get(ref), dict) else {}
        if rec.get("merged") or rec.get("dead"):
            return rec
    return {}


def sweep_proofs(dry: bool = False, only: set[str] | None = None, tick: bool = False, save: bool | None = None) -> dict[str, Any]:
    """The pass and `client.py sweep-step-proof [--dry-run]`: every open item whose open step names an event that has already happened is settled (proof_item). → {"head", "good", "items": [rows, each with
    "pr" and "kind"]}. `dry` writes and tells nothing (it still reads git and GitHub; `save` says whether the GitHub answers are kept, by default when not `dry`). A pull request released is one whose merge is in
    last-good and in HEAD (read now); one merged is in HEAD, or GitHub says so; one closed without a merge is told to the mover once and ticks nothing; one GitHub cannot read is left. The git facts are read
    only for the pull requests some open step waits on, and kept by commit; the pass of the clock (`tick`) with nothing to wait on reads no git at all."""
    own = _cfg.canon_repo(_hooks().own_repo())
    anchors = _live.released_anchors()
    todo: list[tuple[str, list[tuple[str, int, str]]]] = []
    for gid, _p in _item_files():      # first what the open steps wait on: files only
        if only is not None and gid not in only:
            continue
        try:
            it = _load(gid)
            if it.get("status") != "open":
                continue
            meta = it.get("metadata") or {}
            cl = _steps.view(meta, keeper=str(meta.get("owner") or ""))
            ev = sorted(proof_events(cl, meta, own, proof_named(it, cl, anchors.get(gid, set()))))
            if ev:
                todo.append((gid, ev))
        except Exception as e:  # noqa: BLE001
            print(f"step proof: {gid} not read: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    if tick and not todo:
        return {"head": "", "good": "", "items": []}
    try:
        good, head = _live.released_live_base()
    except ToolError:
        try:
            good, head = "", _live.git_commit("HEAD")
        except Exception:  # noqa: BLE001
            good = head = ""
    om = ""
    if head and any(kind == _sp.PR_MERGED and key.rsplit("#", 1)[0] == own for _g, ev in todo for kind, _n, key in ev):
        try:
            om = _live.git("rev-parse", "--verify", "--quiet", "refs/remotes/origin/main^{commit}").stdout.strip()      # merged: in the live checkout, or in origin/main as this checkout last fetched it
        except Exception:  # noqa: BLE001
            om = ""
    gh_st = proof_gh_load()
    checks_gh = _checks.checks_load()["github"]
    now = time.time()
    reads = [0]
    seen: set[str] = set()
    facts: dict[tuple[str, str], tuple[str, str]] = {}      # (kind, key) → ("yes", when) | ("dead", why) | ("no", "")

    def prs(sha: str) -> dict[int, tuple[str, float]]:
        return _live.proof_git(("prs", sha), lambda: _live.merged_prs(sha)) if sha else {}

    def fact(kind: str, n: int, key: str) -> tuple[str, str]:
        if (kind, key) in facts:
            return facts[(kind, key)]
        res = ("no", "")
        repo = key.rsplit("#", 1)[0]
        if kind == _sp.PR_RELEASED:
            if repo == own and good and head and n in prs(good):
                sha, ct = prs(good)[n]
                if not _live.proof_git(("live", good, head, sha), lambda: _live.released_is_live(sha, good, head)):
                    res = ("yes", f"merged at {sha[:7]} on {_stallsvc.stall_when(ct)}, in the last-good commit {good[:7]}")
            elif repo != own and _live.released_foreign(repo) is not None:      # a [released.repos] repository: a merge in its checkout's HEAD is live
                fhead, fprs = _live.foreign_prs(repo)
                if n in fprs:
                    res = ("yes", f"merged at {fprs[n][0][:7]} on {_stallsvc.stall_when(fprs[n][1])}, in the checkout at {fhead[:7]}")
        elif repo == own and (n in prs(head) or (om and n in prs(om))):
            sha, ct = prs(head).get(n) or prs(om)[n]
            res = ("yes", f"merged at {sha[:7]} on {_stallsvc.stall_when(ct)}")
        else:
            ref = _checks.check_ref(key)
            seen.add(ref)
            rec = proof_final(ref, gh_st, checks_gh)
            if rec:
                res = ("yes", "merged on GitHub") if rec.get("merged") else ("dead", str(rec.get("dead") or "its pull request was closed without being merged"))
            else:
                fresh = _prs.fresh(ref, gh_st, now)       # a record of the pass's own file or the one shared with the done check and the event wait, still inside its pace
                if fresh or reads[0] < PROOF_GH_READS:
                    reads[0] += 0 if fresh else 1
                    try:
                        with _gb.tag("step_proof"):
                            ok, err = _checks.pr_merged(key, now, gh_st)
                    except Exception as e:  # noqa: BLE001
                        ok, err = False, f"{type(e).__name__}: {e}"
                    dead = _checks.check_dead(f"pr_merged {key}", gh_st)
                    res = ("yes", "merged on GitHub") if ok and not err else ("dead", dead) if dead else ("no", err)
        facts[(kind, key)] = res
        return res

    for gid, ev in todo:      # the reads come first, outside the lock
        for kind, n, key in ev:
            fact(kind, n, key)
    if save if save is not None else not dry:
        proof_gh_save(gh_st, seen)
    rows: list[dict[str, Any]] = []
    with _writes.ITEM_LOCK:
        for gid, ev in todo:
            for kind, n, key in ev:
                state, why = facts.get((kind, key), ("no", ""))
                if state == "no":
                    continue
                try:
                    r = proof_item(gid, n, key, why if state == "yes" else "", anchors.get(gid, set()), dry, now, kind, dead=why if state == "dead" else "")
                except Exception as e:  # noqa: BLE001  — one item that cannot be read or written never stops the others
                    print(f"step proof: {gid} not settled for PR #{n}: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
                    continue
                if r:
                    rows.append({**r, "pr": n})
                    if r.get("action") == "closed":
                        break
    if not dry and any(r.get("action") in ("closed", "ticked", "told") for r in rows):
        _hooks().publish()
    return {"head": head, "good": good, "items": rows}


def proof_live() -> bool:
    """May the clock act? `[step_proof] live` says so outright (true or false); without it the pass acts once its first dry pass, which only logs what it would do, has been logged."""
    sec = _cfg.get("step_proof")
    if isinstance(sec, dict) and "live" in sec:
        return bool(sec["live"])
    return bool(proof_state().get("dry_logged"))


def proof_tick(now: float | None = None) -> list[str]:
    """The runner's clock for step proofs: at most every PROOF_EVERY seconds, settle the items whose open step waits on an event that has happened. → the ids settled. Until it may act
    (proof_live) a pass is dry: it writes and tells nothing, and logs what it would do (once per item and event) and keeps it in `<state>/step-proof-dry.json`, so the first pass after a deploy
    can be read before anything changes."""
    now = time.time() if now is None else now
    if now - PROOF_LAST[0] < PROOF_EVERY:
        return []
    PROOF_LAST[0] = now
    if proof_live():
        out = sweep_proofs(tick=True)
        return [r["item"] for r in out["items"] if r.get("action") in ("closed", "ticked", "told")]
    out = sweep_proofs(dry=True, tick=True, save=True)
    for r in out["items"]:
        what = f"would {r.get('action')} ({r.get('why') or r.get('reason') or r.get('step') or ''})"
        proof_log_once(r["item"], f"{r.get('kind')} {r.get('pr')}", what, f"step proof (dry pass): {r['item']} {r.get('ref') or ''}: {what}")
    try:
        p = _cfg.state("step-proof-dry.json"); p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"at": now, "head": out.get("head"), "good": out.get("good"), "items": out["items"]}, indent=1, default=str) + "\n", encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        print(f"step proof: dry pass not kept: {e}", file=sys.stderr, flush=True)
    sec = _cfg.get("step_proof")
    if not (isinstance(sec, dict) and "live" in sec):
        proof_state_save(dry_logged=now)      # no switch set: this was the first dry pass, the next one acts
    return []
