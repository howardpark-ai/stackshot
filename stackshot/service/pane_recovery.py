"""pane_recovery.py: pane liveness and the park fallback. A pane stopped on an error is not a pane that can move an item: the one record of it is the pane's own transcript on this box, where Claude Code writes the failed turn
as an assistant entry with isApiErrorMessage (the usage limits, the workspace limit, the credit balance; said.py reads the same files). It holds why a pane looks stopped (`_pane_stuck`), whether a machine or a session is
down (`_machine_unreachable`, `_session_down`, `_idle_live`), the last rung of the ladders, the request that asks the project's -main agent or the fleet's builder to recover a quiet mover's item
(`_recovery_target`, `_recovery_note`, `_recovery_log`, `_recovery_tell`) and the wake a stored "Park until" answer sets (`_idle_park_at`). A raise to the owner's call stored before the last rung existed can still carry a "Park until"
button, which the answer route still applies (the hold and its wake), since the hold is his.

A service module: it reads the transcripts, the registry, the store and the config, writes the History line of a recovery request through the write path, and sends the one message of a recovery through the telling.
`_STARTED`, when this server started, is the one variable of its owner here: the tests that move it set it on this module, and `_machine_unreachable` and `_session_down` read it when they run.

Two things are still the server's, reached through `service/passes_hooks.py` (the table of the passes that read them): the session id of a name (`session_id`)."""
from __future__ import annotations

import datetime as dt
import re
import sys
import time
from pathlib import Path
from typing import Any

from fastmcp.exceptions import ToolError

from stackshot.anchors import anchors as _anc
from stackshot.core import config as _cfg
from stackshot.core.instance import OWNER
from stackshot.fleet import liveness as _lv
from stackshot.fleet import sessions_registry as _sr
from stackshot.github import ghsync as _gh
from stackshot.model import said as _said
from stackshot.model.bullet_text import _clip_line
from stackshot.projects import pages as _pages
from stackshot.service import fleet_events as _fleetev
from stackshot.service import handoff as _handoff
from stackshot.service import passes_hooks as _passes_hooks
from stackshot.service import store as _svcstore
from stackshot.service import telling as _telling
from stackshot.service import wakes as _wakes
from stackshot.service import writes as _writes
from stackshot.service import agents as _agents
from stackshot.waits import stall as _stall

_FOR_OWNER = f"[for {OWNER}]"      # the mark a message to a front agent carries on its first line ("[for <owner>]" on the owner's instance), as server.py holds it


def _session_id(value: str) -> str:
    """The session id of a name, as the server reads it (service/passes_hooks.py's `session_id` hook)."""
    return _passes_hooks.hooks().session_id(value)


_IDLE_PARK_DAYS = 3         # [idle] park_days when unset: only for a raise stored with a "Park until" button (no new raise offers one)


_STUCK_TAIL = 512 * 1024    # bytes read from the end of a transcript to find its last turn


_STUCK_CACHE: dict[str, tuple[tuple[str, int, int], str]] = {}   # transcript uuid → (the file's signature, why it looks stopped)


def _idle_park_days() -> int:
    """[idle] park_days: how many days out the raise's recommended park wakes (3 when unset; at least 1)."""
    try:
        v = _cfg.get("idle", "park_days")
        return max(1, int(_IDLE_PARK_DAYS if v is None or v == "" else v))
    except (TypeError, ValueError):
        return _IDLE_PARK_DAYS


def _transcript_error(path: Path) -> str:
    """The error the last turn in this transcript ended in ("" when it ended well): said.transcript_error, which the puller
    reads the same way on its own machine."""
    return _said.transcript_error(path, _STUCK_TAIL, 160)


def _pane_stuck(who: str, nm: dict[str, str] | None = None, idx: dict[str, dict[str, Any]] | None = None) -> str:
    """Why this pane looks stopped: the last turn in its transcript on this box ended in an API error (_transcript_error), the
    one record of a pane stopped on a usage or credit limit while its puller still reports it. "" when it did not, or when the
    box has no transcript for it (a cloud session, a name no live pane carries): then nothing is known and the clock runs as
    before. A transcript is read again only when the file changed. A pane on another machine has no transcript here: its
    puller (version 7) reads it there and reports `stopped` on the session's record, which `idx` (the sessions index) carries;
    an older puller reports none, so nothing is known of those."""
    sid = _anc.canonical(who, nm)
    try:
        roots = _said.roots_of(_cfg.get("said", "transcripts"))
        # a permanent id has no transcript of its own: the session's latest transcript on this box (step B), else the id as given
        path = next((x for x in (_said.find_transcript(t, roots) for t in [*reversed(_sr.transcripts(sid)), sid]) if x is not None), None)
        if path is None:
            rec = (idx or {}).get(sid.lower()) or (idx or {}).get(sid) or {}
            return str(rec.get("stopped") or "") if _lv.running(rec) else ""
        st = path.stat()
    except OSError:
        return ""
    sig = (str(path), st.st_size, st.st_mtime_ns)
    hit = _STUCK_CACHE.get(sid)
    if hit is None or hit[0] != sig:
        hit = (sig, _transcript_error(path)); _STUCK_CACHE[sid] = hit
    return hit[1]


_RECOVERY_ROLE = {"main": "the project's -main agent", "fleet": "the fleet's builder"}      # who a recovery request was asked of, in words, by `_recovery_target`'s kind


def _recovery_target(project: str, quiet: str) -> tuple[str, str, bool]:
    """(who is asked to recover a quiet mover's item, which kind of recipient it is: "main" | "fleet", whether the project has no builder: it is front-only, so the ladder had none to try). The caller computes
    it ONCE per request, on the raw session (a name or an id, never its label), and hands it to `_recovery_tell` and to the wording of what was tried, so the text and the real recipient cannot disagree.
    A front-only project (anchors.front_only: its `agents:` map lists no background agent, so there is no
    builder for the ladder to try) ends at its -main agent (`_main_agent`), the session its owner talks to. Every other project ends at the fleet's builder (`fleet_builder` in service/fleet_events.py), as before, and so does a front-only
    project with no -main agent to name, and one whose quiet mover is its -main agent itself (nobody is above it in the project): those are still builderless, so the third value is True for them. A front-only test
    that fails keeps the fleet's builder and says the project has one (False: nothing is claimed about a builder that was not read)."""
    builderless = False
    try:
        proj = str(project or "").strip()
        if proj and _anc.front_only(proj):
            builderless = True
            main = _agents._main_agent(proj)
            if main and not (_handoff.ho_same(main, quiet) or _session_id(main) == (_session_id(quiet) or quiet)):
                return main, "main", True
    except Exception as e:  # noqa: BLE001  — the choice is an extra: a failed read keeps the fleet's builder
        print(f"recovery: front-only test of {project} failed ({e.__class__.__name__}: {e}); the fleet's builder is asked", file=sys.stderr, flush=True)
        builderless = False
    return _fleetev.fleet_builder(), "fleet", builderless


def _recovery_note(item: dict[str, Any], now: float, quiet: str, why: str, tried: str, outcome: str, to: str = "") -> str:
    """The History line of a recovery request (metadata.stall.log, shown on the item as a line said by the server): which session is quiet, what happened to the request
    (`outcome`, as _recovery_tell reports it: asked, held, self, nobody, failed) and what the ladder tried. The line names the session asked by its own name, so it
    says the same whether that is the fleet's builder or a front-only project's -main agent. Written onto `item` in place; the caller saves it. → the text."""
    label = _sr._session_label(to) or to
    said = {"asked": f"{label} was asked to recover it",
            "held": f"not sent: the message to {label} was held back, not delivered",
            "self": f"not sent: {label} is the fleet's builder itself, so nobody else could be asked",      # only a fleet request can be its own quiet session: the -main agent is never chosen for itself (_recovery_target)
            "failed": f"not sent: the send to {label} failed",
            "nobody": "not sent: no fleet builder resolves (operator_session unset, retired or without a keeper)"}.get(outcome, outcome)
    text = f"{quiet} is quiet and nobody could take the item: {said} (why: {_clip_line(why, 90)}; tried: {tried})"
    _stall.note(item.setdefault("metadata", {}), now, text)
    return text


def _recovery_log(gid: str, quiet: str, why: str, tried: str, outcome: str, to: str, now: float | None = None, kind: str = "fleet") -> None:
    """Write the History line of a recovery request once its outcome is known: on a fresh read of the item under the lock (the send's thread may have recorded a failure on it meanwhile). Never raises."""
    try:
        with _writes.ITEM_LOCK:
            item = _svcstore._load(gid)
            if item.get("status") != "open":
                return
            _recovery_note(item, time.time() if now is None else now, quiet, why, tried, outcome, to)
            role = _RECOVERY_ROLE.get(kind, _RECOVERY_ROLE["fleet"])
            _writes.save(gid, item, note="nobody could take it: " + (f"{role} was asked" if outcome == "asked" else f"{role} could not be asked"))      # the server's own act: the state clock stays, and no page is owed
    except Exception as e:  # noqa: BLE001
        print(f"recovery: {gid} History line not written: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)


def _recovery_tell(gid: str, item: dict[str, Any], quiet: str, why: str, tried: str, tag: str = "stall", now: float | None = None, target: "tuple[str, str, bool] | None" = None) -> str:
    """The last rung of the ladders: ONE message to the fleet's builder naming the item and the quiet session and asking it to take the fix through its usual path (the callers send it once
    per episode: a hand-off record, a stall record; they mark the episode BEFORE this send, on purpose: a failed send is not retried every pass, `metadata.undelivered`
    records it and the audit's unmoved digest is the backstop). The item stays with its mover; the message is not for the owner and owes no reply. The History line is written here, after the
    outcome is known, so it says what happened. A front-only project's request goes to its -main agent instead (`_recovery_target`), marked for the owner as every message to a front agent is, and asks it to decide
    (bring the session back, message it, or hand the item on); the others go to the fleet's builder. → the outcome: "asked" (the send was started; a delivery that fails later lands in metadata.undelivered), "held" (the front gate held it), "self" (the quiet
    session is the builder itself), "nobody" (no builder resolves), "failed" (the send raised). `target` is the caller's `_recovery_target` (computed once on the raw session, as the caller's wording of `tried` used it);
    without it the target is read here on `quiet`. Never raises."""
    to, outcome, kind = "", "failed", "fleet"
    try:
        to, kind, _bl_less = target if target is not None else _recovery_target(str((item.get("metadata") or {}).get("project") or ""), quiet)
        to_id = (_session_id(to) or to) if to else ""
        if not to:
            outcome = "nobody"
            print(f"recovery: {gid} {quiet} is quiet and nobody could take it; no fleet builder resolves (operator_session unset, retired or without a keeper)", file=sys.stderr, flush=True)
        elif to_id == (_session_id(quiet) or quiet):
            outcome = "self"
            print(f"recovery: {gid} {quiet} is quiet and is the fleet's builder itself; nobody else to ask", file=sys.stderr, flush=True)
        else:
            meta = item.get("metadata") or {}
            if kind == "main":
                text = (f"{_FOR_OWNER}\n[stackshot] {_gh.shown(gid)} \"{item.get('subject') or ''}\" ({meta.get('project') or ''}) has gone quiet: {quiet} is its mover and is not working it, and the project lists no builder to take it. "
                        f"Why: {_clip_line(why, 300)}. What the ladder tried: {tried}. Please decide what it needs: bring the session back, message {quiet}, or hand the item on (update mover=<session>). "
                        f"The item stays with {quiet} meanwhile, and no reply is owed (put the result on the item). → {_telling.notice_link(gid)}")
            else:
                text = (f"[stackshot] fleet recovery: {_gh.shown(gid)} \"{item.get('subject') or ''}\" ({meta.get('project') or ''}) has gone quiet: {quiet} is its mover and is not working it. "
                        f"Why: {_clip_line(why, 300)}. What the ladder tried: {tried}. Please take the fix through your usual path: bring the session back, or hand the item to a session that runs. "
                        f"The item stays with {quiet} meanwhile; nothing here is for {OWNER}, and no reply is owed (put the result on the item). → {_telling.notice_link(gid)}")
            th = _telling.tell_woken(gid, to_id, text, tag=tag)
            outcome = "asked" if th is not None else "held"
            print(f"recovery: {gid} {quiet} is quiet; " + (f"{to} asked to recover it" if th is not None else f"the message to {to} was held back"), file=sys.stderr, flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"recovery: {gid} not sent: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    _recovery_log(gid, quiet, why, tried, outcome, to, now, kind)
    return outcome


def _idle_park_at(day: str, text: str) -> str:
    """The wake a "Park until …" answer sets, for a raise stored before the park option was dropped and still
    on an item's page: the first future date written in his note (YYYY-MM-DD, or with THH:MM), else `day`, the one the option
    named, else [idle] park_days from now (that day has passed). No new raise carries such an option."""
    now = _pages.zone_now()
    for cand in [*re.findall(r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2})?", str(text or "")), str(day or "")]:
        if not cand:
            continue
        try:
            stored = _wakes.parse_wake(cand)
            if _wakes.wake_at(stored) > now:
                return stored
        except ToolError:
            continue
    return (now + dt.timedelta(days=_idle_park_days())).strftime("%Y-%m-%d")


def _idle_live(who: str, nm: dict[str, str], idx: dict[str, dict[str, Any]]) -> bool:
    """Is that session running now (its puller or hooks report it, not marked gone)? A cse_ session's state is unknown to the
    server and does not count: its time is never live time."""
    sid = _anc.canonical(who, nm)
    return _lv.idle_live(idx.get(sid.lower()) or idx.get(sid))


_STARTED = time.time()      # when this server started: a machine is not called unreachable for downtime that was the server's own


def _machine_unreachable(letter: Any, now: float | None = None) -> str:
    """Why a machine cannot be reached now: its puller has not checked in (machine.json online.ok false) for [client] online_minutes,
    counted from its last check-in or this server's start, whichever is later (after the server's own downtime every puller reads
    as late until it has had its chance to check in), else ""."""
    return _lv.machine_unreachable(letter, now, _STARTED)       # _STARTED is read here, at the call: the tests move it


def _session_down(who: str, nm: dict[str, str], idx: dict[str, dict[str, Any]], stuck: Any = None, now: float | None = None) -> str:
    """Why this session cannot move an item now, "" when it can or when nothing is known (a cloud session, a name the fleet does not
    know: never down). A running pane is down when its last turn ended in an API error (`stuck`, else _pane_stuck: its transcript on
    this box, or the `stopped` its puller reports from another machine) or its machine's puller is not checking in; a pane that is
    not running is down once it has been gone past the grace (a relaunch under way is not)."""
    sid = _anc.canonical(who, nm)
    rec = idx.get(sid.lower()) or idx.get(sid)
    return _lv.session_down(rec, lambda: stuck(sid) if stuck is not None else _pane_stuck(sid, nm, idx), _STARTED, now)
