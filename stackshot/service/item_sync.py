"""item_sync.py: `client.py post item-sync <marker> open|refresh|close`, an item a script keeps in step with a condition it checks, with the person as its mover.

A timer's script that finds a condition only the person can fix (a plugin sync that fell behind, say) opens one board item for him with his step, keeps its description current on every run
that still finds the condition, and closes it when a later run finds the condition gone. The item is marked with the caller's marker (`metadata.item_sync`): that mark is the whole of what the
route may touch, so it cannot refresh or close an item it did not open. `open` files an item whose mover is the person and whose `then` is an agent of the project (the agent takes it when he has
done his step), with his step as the one step on the checklist; while an item with the marker is open a repeat `open` is a `refresh` that may also set the step (_itemsync_step_write; never once he has finished or answered on the item), and once it is closed an `open` files a new item (the condition recurs).
`refresh` rewrites the description of the open item and nothing else; `close` completes it as done, through the update tool's own close. With no open item `refresh` and `close` do nothing and say so.
`_ITEMSYNC_LOCK` makes the look for an open item and the write one step against another call of this route (two opens of one marker file one item). A refresh, a close and a repeat open also hold the board's item lock
(`ITEM_LOCK`) from the look to the write, so a session's close cannot land between them; a new item is created without the board's lock, because the create reaches GitHub for the item number and no other writer of the board waits for that. The markers, the sender and the description rules are item_open.py's; the helpers the row is filed with are service/terminal_prompt.py's.

A service module: it reads the project record, the anchors' registry and the store and writes through `create_item` and the update tool's code. The route that calls it (`_client_post`) is the surface's.

Imports point down only: this module imports the domain, core and the services beside it, never web/ and never audit/."""
from __future__ import annotations

import contextlib
import threading
from typing import Any

from fastmcp.exceptions import ToolError

from stackshot.core import config as _cfg
from stackshot.core.instance import OWNER
from stackshot.core.store import _item_files
from stackshot.fleet import sessions_registry as _sr
from stackshot.github import ghsync as _gh
from stackshot.model import model as _model
from stackshot.model import owner_steps as _hs
from stackshot.model import states as _states
from stackshot.model import steps as _steps
from stackshot.model.field_gates import _close_reason_max, _fit, next_faults
from stackshot.projects import projects as _prj
from stackshot.projects.project_registry import _registry
from stackshot.service import create as _create_svc
from stackshot.service import item_open as _item_open
from stackshot.service import item_read as _item_read
from stackshot.service import owner_words as _owner_words
from stackshot.service import store as _svcstore
from stackshot.service import terminal_prompt as _terminal
from stackshot.service import update as _update_svc
from stackshot.service import writes as _writes


# ----------------------------------------------------------------------------- an item a script keeps in step with a condition (client.py post item-sync)
_ITEMSYNC_LOCK = threading.Lock()
_ITEMSYNC_ACTIONS = ("open", "refresh", "close")
_ITEMSYNC_KEYS = ("action", "marker", "project", "subject", "description", "step", "mover", "then", "reason", "sender")
_ITEMSYNC_OPEN_MAX = 10      # open items this route may hold per project: a marker that changes every run cannot pile up items


def _itemsync_open_items() -> list[tuple[str, str, str]]:
    """(id, marker, project) of every open item this route filed, read from the store (the mark is looked for as text first, so a store of thousands is cheap to scan). The marker is the item's whole key:
    a call for a marker never sees an item another route filed, whatever its text."""
    out = []
    for gid, p in _item_files():
        try:
            if '"item_sync"' not in p.read_text(encoding="utf-8"):
                continue
            it = _svcstore._load(gid)
        except (OSError, ValueError, ToolError):
            continue
        meta = it.get("metadata") or {}
        if it.get("status") == "open" and str(meta.get("item_sync") or ""):
            out.append((gid, str(meta["item_sync"]), str(meta.get("project") or "")))
    return out


def _itemsync_text(body: dict[str, Any], key: str) -> tuple[str, str]:
    """A text field of the call on one line -> (the text, "") or ("", why it is refused)."""
    raw = body.get(key)
    if raw is None:
        return "", ""
    if not isinstance(raw, str):
        return "", f"{key} is text"
    if any(ord(c) < 32 or ord(c) == 127 for c in raw):
        return "", f"{key} is one line, with no control character"
    return " ".join(raw.split()), ""


def _itemsync_post(machine: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """`client.py post item-sync <marker> open --project P --subject S --mover <the person> --then <agent> --step "<what he does>" --line "<fact>" [--line ...] [--sender L]`,
    `… <marker> refresh --line "<fact>" [--line ...] [--sender L]` and `… <marker> close [--reason "<why>"] [--sender L]`: a script keeps ONE board item in step with a condition it checks.
    body: action (open | refresh | close), marker (`<kind>:<what>`, the item's mark: item-open's form), sender (the script's own label, one word; default client.py), and for open project (an id, a page key or a bare slug),
    subject (the action and its object, no prefix: the server puts the project scope's prefix before it), description (the bullets: a list of lines or one text of lines, as item-open takes them), mover (the person the instance names: nobody
    else), then (an agent the project's page lists, front or background: it takes the item after his step) and step (one line, what he does; his name is put before it, and one the caller wrote is not doubled); for refresh the description; for close an optional
    reason (one line, cut to [close] reason_max; default says the script saw the condition gone). Any other key is refused.
    open: the item is filed through create_item (service/create.py), the create tool's own code, so the create tool's subject and next gates, the project page and the GitHub mirror all apply and a refusal is the tool's text (400); the description's line count and line length are item-open's own pre-checks; the caller picks no
    field the route does not take (no needs, ask, priority or date). The mover is the person, the item's `then` the agent, its creator the project's front agent (its -main first), its only step his; the state is your-step, as the terminal prompt's row.
    Marked metadata.item_sync = <marker>. While an item with the marker is open (the marker is global: refresh and close carry no project), a repeat open rewrites that item's description as refresh does and may set the sent step (_itemsync_step_write). The step the route last sent (metadata.item_sync_sent) is never asked again, also after a session replaced, reworded or withdrew it or a wait dropped it: only a different step is. Nor is the step he marked done last, nor anything for none, clear or -, while the item reads as waiting, or while a decision ask to him is pending. While an open line of his that is not the route's own (metadata.item_sync_step) stands, the route sets nothing, unless one of his open lines reads as the sent step: then the item is made to ask that line if it asks him nothing, and a session's current step is not written over. A step not set for one of those reasons is not recorded, so a later open with it sets it once the reason is gone. The route drops no open line but its own. Setting a step makes the person the mover (a stored `then` stays; with none stored an agent that moved the item becomes it, the project's builder in a front agent's place when one does the work); a repeat's mover and then are checked and never written themselves. An item filed before these records is read from its first step (_itemsync_record). Description and step go in one write, so a refused step leaves the item as it was; an open on another project than the
    open item's is a 400. A first open refuses a step of none, clear or -. After the item is closed an open files a new one. A project holds at most 10 open items of this route (a repeat never counts). The row owes no page and tells no session, as every script route's.
    refresh: rewrites the description of the marker's open item (the caller's bullets, then who opened it) and nothing else: not his step, not the mover, not the subject; no open item is a 200 that does nothing. A script's write is not judged by the Goal-first rule a session's
    description is (the board's way with script rows): the checks are item-open's (the line count and the length of a line), so the first bullet need not state a goal.
    close: the update tool's close of the marker's open item, outcome done, a reason within [close] reason_max, the end state in outcome_text, the description unchanged; his open steps are ticked by it and the history says the script saw the condition gone. While another writer's step is
    open on the item (an agent's follow-up) nothing is closed or ticked: the item is left open and the answer says so (action left-open). No open item is a 200 that does nothing.
    404 no such project, 409 no front agent to file under, 503 the project record cannot be read. -> (status, {item, marker, action: opened | refreshed | closed | left-open | none, project, mover, then, owner, repeat}); a `none` answer carries no item, and a left-open one a `note`."""
    extra_keys = sorted(k for k in body if k not in _ITEMSYNC_KEYS)
    if extra_keys:
        return 400, {"error": f"not taken: {', '.join(str(k) for k in extra_keys)}; item-sync takes {', '.join(_ITEMSYNC_KEYS)} and nothing else"}
    action = str(body.get("action") or "").strip()
    if action not in _ITEMSYNC_ACTIONS:
        return 400, {"error": "action = open | refresh | close"}
    texts = {}
    for k in ("marker", "project", "subject", "step", "mover", "then", "reason", "sender"):
        texts[k], why = _itemsync_text(body, k)
        if why:
            return 400, {"error": why}
    marker, sender = texts["marker"], texts["sender"] or "client.py"
    if not marker:
        return 400, {"error": "marker is required: the item's mark, <kind>:<what> (for example plugin_sync:stackshot), the same every time the same condition is reported"}
    if not _item_open._ITEMOPEN_MARKER.fullmatch(marker):
        return 400, {"error": "marker = <kind>:<what>: a lower-case kind (at most 40 characters of letters, digits, _ . -), a colon, then at most 80 characters of letters, digits and _ . - / (no spaces)"}
    if not _item_open._ITEMOPEN_SENDER.fullmatch(sender):
        return 400, {"error": "sender = the script's own label: one word of letters, digits and _ . - (at most 60 characters), no spaces or markup"}
    try:
        _owner_words._sender_not_owner(sender)
    except ToolError as e:
        return 400, {"error": str(e)}
    allowed = {"open": {"project", "subject", "description", "step", "mover", "then"}, "refresh": {"description"}, "close": {"reason"}}[action]
    stray = sorted(k for k in body if k in ("project", "subject", "description", "step", "mover", "then", "reason") and k not in allowed and body.get(k) not in (None, "", []))
    if stray:
        return 400, {"error": f"{action} does not take {', '.join(stray)}; item-sync {action} takes {', '.join(sorted(allowed)) or 'no field'} and the marker"}
    lines: list[str] = []
    if action in ("open", "refresh"):
        lines, why = _item_open._itemopen_lines(body.get("description"))
        if why:
            return 400, {"error": why}
    by = f"{sender} (a script on a client machine)"
    desc = _terminal._terminal_bullets(*lines, _item_open._ITEMOPEN_ATTRIBUTION.format(sender=sender)) if lines else ""
    plan: dict[str, Any] = {}
    if action == "open":
        plan, bad = _itemsync_plan(texts)
        if bad:
            return bad
    try:
        with _ITEMSYNC_LOCK, contextlib.ExitStack() as held:      # one call of the route at a time: the look for an open item and the create that follows are one step, so two opens of one marker file one item
            held.enter_context(_writes.ITEM_LOCK)      # the board's item lock too, from the look to the write, for the calls that change an item that exists (a session's close cannot land between them)
            _writes.TERMINAL_ROW.on = True      # a script's row: it owes no page and tells no session (create_item, _update, the tell_* notices)
            try:
                open_here = _itemsync_open_items()
                found = [(g, p_) for g, m_, p_ in open_here if m_ == marker]
                if action == "open":
                    if not found:
                        held.close()      # a new item: the create reaches GitHub for the item number (up to half a minute on a slow day), and no other writer of the board waits for it
                    return _itemsync_open(found, [p_ for _g, _m, p_ in open_here], marker, desc, plan, by, sender)
                if not found:
                    return 200, {"item": "", "marker": marker, "action": "none", "note": f"no open item for {marker}; nothing was {'refreshed' if action == 'refresh' else 'closed'}"}
                gid = found[0][0]
                if action == "refresh":
                    _update_svc._update(gid, description=desc, sender=by)
                    return 200, _itemsync_answer(gid, marker, "refreshed", True)
                return _itemsync_close(gid, marker, texts["reason"], sender, by)
            finally:
                _writes.TERMINAL_ROW.on = False
    except ToolError as e:
        return 400, {"error": str(e)}


def _itemsync_plan(texts: dict[str, str]) -> tuple[dict[str, Any], tuple[int, dict[str, Any]] | None]:
    """The open call's project, agents and wording, checked before anything is written -> (the plan, None) or ({}, the refusal)."""
    project, subject, step, mover, then = (texts[k] for k in ("project", "subject", "step", "mover", "then"))
    for k, v in (("project", project), ("subject", subject), ("step", step), ("mover", mover), ("then", then)):
        if not v:
            return {}, (400, {"error": f"{k} is required to open"})
    if not _model.is_owner(mover):
        return {}, (400, {"error": f"mover is {OWNER}: this route opens items that wait on him, so his step is the one step; got {mover!r}"})
    step = _steps.without_owner(_svcstore._shown_ids(step))      # item ids written as the create writes them into next, so the line, the step and the route's record of it are one text
    if not step:
        return {}, (400, {"error": "step is empty once his name is taken off it: say what he does"})
    if too_long := next_faults(f"{OWNER}: {step}"):      # one limit for a first and a repeat open: the line of next the create makes of the step, judged by the create tool's own gate, before anything is written
        return {}, (400, {"error": too_long[0]})
    if len(step) > _states.LINE_MAX:      # …and the step field's own limit, which a line with a long link can pass the gate above and still break
        return {}, (400, {"error": f"step is one line of at most {_states.LINE_MAX} characters — got {len(step)}; say what he does in one line"})
    try:
        recs = _prj.refs(project, _registry("projects"))
    except ValueError as e:
        return {}, (503, {"error": f"the project record cannot be read right now, nothing was filed: {e}"})
    if not recs:
        return {}, (404, {"error": f"no project {project!r}: an id, a page key or a bare slug of a page in the registry"})
    if len(recs) > 1:
        return {}, (400, {"error": f"{project!r} is ambiguous: it names {' and '.join(r['key'] for r in recs)}; write the full key or the id"})
    rec = recs[0]
    key = rec["key"]
    _hub, _nm, back, front, _keeper = _item_read._hub_sessions(key)
    if not front:
        return {}, (409, {"error": f"{key} lists no front agent (a user-facing agent under `agents:` on its page, or its hub's), so there is nobody to keep the item; a front agent lists itself first (client.py post project-agent)"})
    if then not in front and then not in back:
        return {}, (400, {"error": f"then {then!r} is not an agent listed on {key}'s page (its agents map): " + ", ".join(sorted([*front, *back]))})
    prefixes = [p.strip() for p in _cfg.CFG["subject"]["prefixes"] if p.strip()]
    subject = _svcstore._shown_ids(subject)
    while (hit := next((b for b in prefixes if subject.startswith(b) and (len(subject) == len(b) or subject[len(b)].isspace() or any(subject[len(b):].startswith(o) for o in prefixes))), "")):
        subject = subject[len(hit):].lstrip()      # a prefix the caller wrote comes off: the scope's prefix is the server's to choose, and goes on once
    if not subject:
        return {}, (400, {"error": "subject is only an instance prefix: write the action and its object after it (the server puts the project's prefix on)"})
    subject = _terminal._terminal_subject_prefix(str(rec.get("scope") or "")) + subject
    return {"key": key, "subject": subject, "step": step, "then": then, "owner": sorted(front, key=lambda n: (not n.endswith("-main"), n))[0]}, None


def _itemsync_close(gid: str, marker: str, reason: str, sender: str, by: str) -> tuple[int, dict[str, Any]]:
    """close, under the locks: the item is completed when nothing of anyone else is open on it, and his step is ticked by that close. Another writer's open step (an agent's follow-up, a second agent's step) is never settled by a script: the item is left
    open and the answer says so. His step is not ticked on its own: the board lets only his answer tick it (a session's tick is refused), and a close settles it. The completing write is a session's close (the update's own refusal of a close over
    another session's step stands behind this check)."""
    meta = _svcstore._load(gid).get("metadata") or {}
    steps = _steps.view(meta, keeper=str(meta.get("owner") or ""))
    if _steps.others_open(steps, lambda _w: False):       # the same count the update's close makes, with no writer excused: a step opening with another name stays that session's, the item keeper's included
        return 200, {**_itemsync_answer(gid, marker, "left-open", False), "note": "left open: open steps of others remain"}
    reason = _fit(reason or f"the script saw the condition ({marker}) is gone", _close_reason_max())
    outcome = _terminal._terminal_bullets(f"{marker}: the condition is gone", f"Closed by {sender} (a script on a client machine): it saw the condition gone, so his step is done")
    with _writes.close_write():
        _update_svc._update(gid, outcome_text=outcome, status="completed", outcome="done", reason=reason, sender=by)
    return 200, _itemsync_answer(gid, marker, "closed", False)


def _itemsync_answer(gid: str, marker: str, action: str, repeat: bool) -> dict[str, Any]:
    meta = _svcstore._load(gid).get("metadata") or {}
    return {"item": _gh.shown(gid), "marker": marker, "action": action, "project": str(meta.get("project") or ""), "mover": _model.owner_display(),
            "then": _sr._session_label(str(meta.get("then") or "")), "owner": _sr._session_label(str(meta.get("owner") or "")), "repeat": repeat}


def _itemsync_record(meta: dict[str, Any], checklist: list[dict[str, Any]]) -> tuple[str, str]:
    """(the route's own step, the step it last sent) of an item, "" for what is not known: metadata.item_sync_step and item_sync_sent. An item filed before those records holds neither, and its first
    checklist step, the one line its create wrote, is read instead. Open, his, written under the item's creator and reading as metadata.step: the route asked it, so it is its own step and the last
    sent. Open, his, written under the creator, the only step there ever was, and the item has no step (a filing cut short before its state): its own step, not yet sent. No longer open: the step last sent. Any
    other open first line cannot be told from a session's, so nothing is read from it. A stored empty item_sync_sent is read as it stands: a wait dropped the route's line before he answered
    (owner_steps.route_wait_dropped)."""
    own, sent = _states.clean(meta.get(_hs.ROUTE_KEY)), _states.clean(meta.get(_hs.SENT_KEY))
    if _hs.ROUTE_KEY in meta or _hs.SENT_KEY in meta or not checklist:      # SENT_KEY stored empty: a wait dropped the route's line, and no step counts as sent
        return own, sent
    first = checklist[0]
    text = _steps.without_owner(_steps.first_line(first["text"]))
    if first["status"] != _steps.OPEN:
        return "", text
    if not _steps.is_his(first["text"], unnamed_is_his=False) or first.get("writer") != str(meta.get("owner") or ""):
        return "", ""
    current = _states.clean(meta.get("step"))
    if current and _hs.same_line(_hs.line_of(current, meta), first["text"]):
        return text, text
    if not current and len(checklist) == 1:
        return text, ""
    return "", ""


def _itemsync_step_write(item: dict[str, Any], step: str) -> dict[str, Any]:
    """What a repeat open's write adds to the description for its step, {} when nothing is added.

    Nothing is added once he has finished or answered on the item: a step of his that he marked done himself (a session's tick does not count), or his answer to the item's step (owner_steps.route_answered).
    A script that repeats while its condition lasts, with a version or a count in its step, would otherwise put the item back on his list after every answer; the close, and a new item when the condition
    recurs, ask him again. Nothing is added either for none, clear or -; for the step the route last sent (_itemsync_record), whatever became of its line since; while the item reads as waiting, or a
    decision ask to him is pending; and while an open line of his that is not the route's own stands and none of his open lines reads as the sent step. A step that none of these stops is recorded as the last sent.

    The step is then written (the update's step=) when no open line reads as it, when the item does not ask him now (its state is not your-step with a step), or when the step it asks is the route's own
    older one. A session's current step is never written over: the line that reads as the sent step is on his list beside it. The route's own older line is dropped, and no other line. The route's own step
    is the one it added to the list; a line that stood already without being its own stays the writer's. Steps are compared as the board stores them, his name off."""
    meta = item.get("metadata") or {}
    if step.lower() in _update_svc._hooks().ask_none:
        return {}
    checklist = _steps.view(meta)
    if meta.get(_hs.ANSWERED_KEY) or any(s["status"] == _steps.DONE and _steps.is_his(s["text"], unnamed_is_his=False) and _model.is_owner(s["by"]) for s in checklist):
        return {}      # finished or answered by him: this item is not put on his list again
    own, sent = _itemsync_record(meta, checklist)
    line = _hs.line_of(step, meta)
    want = _steps.owner_key(line)
    if sent and _steps.owner_key(_hs.line_of(sent, meta)) == want:
        return {}      # sent once: only a different step asks again
    if _model.shown_waiting(item, None, lambda i_: _item_read._after_open(i_.get("metadata") or {})):
        return {}      # a step written onto a parked or held item asks him nothing: not recorded, so the next open after the wait sets it
    if meta.get("state") == "your-call" or "decision" in _states.kinds_of(meta):
        return {}      # a step set over a pending ask would take its Decide line off the list
    lines = [(n, _steps.owner_key(s["text"])) for n, s in enumerate(checklist, 1) if s["status"] == _steps.OPEN and _steps.is_his(s["text"], unnamed_is_his=False)]      # positions as dropped= takes them
    own_key = _steps.owner_key(_hs.line_of(own, meta)) if own and not meta.get("step_lines") else ""      # while a long step is split into lines it is a session's current step, whatever its summary reads
    own_at = next((n for n, k in lines if k == own_key), 0)
    stands = any(k == want for _n, k in lines)
    if not stands and any(n != own_at for n, _k in lines):
        return {}      # another line of his stands: not recorded, so a later open sets the step once that line is gone
    replaced = [own_at] if own_at and own_key != want else []
    current = _states.clean(meta.get("step"))
    current_key = _steps.owner_key(_hs.line_of(current, meta)) if current else ""
    asks = meta.get("state") == "your-step" and bool(current)
    out: dict[str, Any] = {"route_record": {"own": step if not stands or want == own_key else "", "sent": step}}
    if not stands or not asks or (replaced and current_key == own_key):
        out["step"] = step
    if replaced:
        out["dropped"] = replaced
    return out


def _itemsync_open(found: list[tuple[str, str]], projects: list[str], marker: str, desc: str, plan: dict[str, Any], by: str, sender: str) -> tuple[int, dict[str, Any]]:
    """open, under the lock: a repeat of an open marker is a refresh (its description rewritten) that sets its step too, so it is his move, when _itemsync_step_write says so; else a new item with the person as mover, the agent as then and his step."""
    key = plan["key"]
    if found:
        gid, was = found[0]
        if was != key:
            return 400, {"error": f"{marker} is already open on {was}: a marker belongs to one item at a time; close it there first, or use another marker for {key}"}
        step = plan["step"]
        _update_svc._update(gid, description=desc, sender=by, **_itemsync_step_write(_svcstore._load(gid), step))      # one write: a step the board's gates refuse leaves the description, the list and the record as they were
        return 200, _itemsync_answer(gid, marker, "refreshed", True)
    step = plan["step"]
    if step.lower() in _update_svc._hooks().ask_none:
        return 400, {"error": f"step {step!r} is no step: a first open files the item with what he does (on a repeat open, none, clear and - set nothing)"}
    if projects.count(key) >= _ITEMSYNC_OPEN_MAX:
        return 400, {"error": f"{key} already has {projects.count(key)} open items filed by this route and the cap is {_ITEMSYNC_OPEN_MAX}: an open item must close before another is filed "
                              "(a repeat of an open marker is always answered; a marker that changes on every run is the usual cause)"}
    gid, _reply = _create_svc.create_item(subject=plan["subject"], description=desc, project=key, owner=plan["owner"], next=f"{OWNER}: {step}", mover=OWNER, then=plan["then"], by=by,
                                          extra={"item_sync": marker, _hs.ROUTE_KEY: step})      # the line the create writes is the route's own, from the first write
    try:       # a create sets no step: the state is a second write, and an item the state fails for is closed again, never left half made (as the terminal prompt's row)
        _update_svc._update(gid, step=step, sender=by, route_record={"own": step, "sent": step})
    except Exception:  # noqa: BLE001  — re-raised below
        try:
            _update_svc._update(gid, outcome_text=_terminal._terminal_bullets(f"{marker}: the item could not be made", f"Closed by {sender} (a script on a client machine)"), status="completed", outcome="dropped",
                                reason="the item could not be made whole", sender=by)
        except Exception as e2:  # noqa: BLE001
            import sys
            print(f"item sync: {_gh.shown(gid)} left open half made, not closed: {e2}", file=sys.stderr, flush=True)
        raise
    return 200, _itemsync_answer(gid, marker, "opened", False)
