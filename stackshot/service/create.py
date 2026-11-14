"""create.py: creating an item: every gate and every write of the create tool, in the order they ran in server.py.

`create_item` is the one place an item is created: the create tool (`stackshot_create`, which stays on the surface and only parses its input and shapes the reply) and the three scripts' routes of
the client API (a pane's question, the terminal prompt's row, a watcher's job-gap item) all come through it, so a script cannot file what the tool would refuse. It runs the gates, takes the item's
id (the issue's number when the GitHub id switch is on, else the next local one), saves the item through the write path (`writes.save`), remembers the request id, charges the page debt, tells the
sessions the item names, publishes, and builds the reply. The order of those steps is part of what a create means and is kept as it was in server.py.

The request map (`requests.json`: a request id and the item it filed) is this module's: a retry with the same request id returns the item the first call made (`_requests`, `_remember_request`).

The write gates a create runs are service/gates.py's (`_gates.gate_*`, in the order they ran in server.py), the field and decision rules model/'s (`field_gates.py`, `decision_gates.py`, the similar-items rule `similar.py`), each called on its
module. The notices a create runs and the helpers of the areas that still sit in server.py are reached through `Hooks`, which web/wiring.py fills once with `install` (web/server.py calls it at its import) (this module cannot import server.py: the surface sits above it), and each of them leaves
`Hooks` when its area moves under service/. A hook is looked up on its owner module (by web/wiring.py) when a create runs, so a suite that replaces one there still reaches the create; a suite that replaces a gate or a rule patches it on its owner. Three thread-local flags of server.py are read by a create and also by the gates, the update tool and the telling, so they
stay thread-locals there until those areas move and a create reads them through `Hooks`: `session_next` (the create or update tool's own call, set by `session_write`), `question` (a script's
question: set by the question, terminal-prompt and watcher routes around their create) and `terminal_row` (the terminal prompt's and the job-gap routes' row).

Imports point down only: this module imports the domain and core and the store's readers beside it (service/store.py), never web/."""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from fastmcp.exceptions import ToolError

from stackshot.anchors import anchors as _anc
from stackshot.core import call_log as _calls
from stackshot.core import config as _cfg
from stackshot.core import instance as _inst
from stackshot.core.store import _item_files, _next_id
from stackshot.fleet.sessions_registry import _session_label
from stackshot.github import ghsync as _gh
from stackshot.model import decision_gates as _dg
from stackshot.model import field_gates as _fg
from stackshot.model import model as _model
from stackshot.model import similar as _sim
from stackshot.model import nextlines as _nl
from stackshot.model import next_rules as _nr
from stackshot.model import steps as _steps
from stackshot.model.needs import _canon_needs, _needs_kinds, _needs_sessions
from stackshot.projects import pages as _pages
from stackshot.service import checks as _checks
from stackshot.service import gates as _gates
from stackshot.service import proofs as _proofs
from stackshot.service import telling as _telling
from stackshot.service import writes as _writes
from stackshot.service.store import _load, _path, _shown_ids
from stackshot.waits import until_write as _uw
from stackshot.waits import wait_list as _wl
from stackshot.waits import waiting as _wt

REQUESTS = _cfg.state("requests.json")      # the request map: a request id -> the item it filed (server.py makes its folder at start)
_REQ_LOCK = threading.RLock()      # the request map is read and rewritten whole: one thread at a time (the tool's creates and the client API's questions share it)


def _requests() -> dict[str, str]:
    with _REQ_LOCK:
        try:
            with open(REQUESTS, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}


def _remember_request(rid: str, gid: str) -> None:
    with _REQ_LOCK:
        d = _requests(); d[rid] = gid
        fd, tmp = tempfile.mkstemp(prefix=f".{REQUESTS.name}.", suffix=".tmp", dir=str(REQUESTS.parent))     # a name of its own, so no writer in another process shares one
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(d, f)
            os.replace(tmp, REQUESTS)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


def similar_note(gid: str, subject: str, project: str) -> str:
    """The create reply's similar-items note (`model/similar.py` makes it): the stored items, the anchors registry's parent of a project and the clock are read here. A note only: any failure gives "" and the create stands."""
    try:
        if not _sim._subject_words(subject):
            return ""

        def stored():
            for g, p in _item_files():
                try:
                    with open(p, encoding="utf-8") as f:
                        it = json.load(f)
                except Exception:
                    continue
                if isinstance(it, dict):
                    yield g, it

        try:
            reg = _anc.registry()
            parent_of = lambda p: _anc.hub_of(p, reg)
        except Exception:
            parent_of = lambda p: p
        return _sim._similar_note(gid, subject, project, stored(), parent_of, time.time())
    except Exception:
        return ""


@dataclass(frozen=True)
class Hooks:
    """What a create still reaches in server.py (the notices and helpers it shares with the update tool, the close and the telling, the thread-local flags, a constant), in the names
    they have there without the leading underscore; web/wiring.py builds one and gives it to `install`. A gate raises `ToolError` itself; a flag is a function that reads the thread-local."""
    after_open: Callable[..., Any]
    anchor_wait_gate: Callable[..., Any]
    ask_owed: Callable[..., Any]
    contact_default: Callable[..., Any]
    evwait_gate: Callable[..., Any]
    fallback_wait_date: Callable[..., Any]
    fmt: Callable[..., Any]
    form_notes: Callable[..., Any]
    gate_ask: Callable[..., Any]
    gate_options: Callable[..., Any]
    lift_ask: Callable[..., Any]
    machine_note: Callable[..., Any]
    model_guards_on: Callable[..., Any]
    nag: Callable[..., Any]
    next_put: Callable[..., Any]
    owed_mark: Callable[..., Any]
    owner_then_default: Callable[..., Any]
    parse_wake: Callable[..., Any]
    publish: Callable[..., Any]
    record_fixes: Callable[..., Any]
    refuse_if_owing: Callable[..., Any]
    said_note: Callable[..., Any]
    session_id: Callable[..., Any]
    wait_alias_gate: Callable[..., Any]
    wake_at: Callable[..., Any]
    writer_owes: Callable[..., Any]
    ask_none: tuple[str, ...]             # the words that mean no ask, no observers, no check (server._ASK_NONE)


_hooks_: Hooks | None = None


def install(hooks: Hooks) -> None:
    """Give the create the gates and notices that are still server.py's (once, at its import)."""
    global _hooks_
    _hooks_ = hooks


def _hooks() -> Hooks:
    if _hooks_ is None:
        raise RuntimeError("the create has no hooks installed (web/wiring.py installs them, called from web/server.py at its import)")
    return _hooks_


def create_item(
    subject: str,
    description: str,
    project: str,
    owner: str,
    next: str = "",
    needs: list[str] | str = "",
    priority: str = "",
    due: str = "",
    anchors: list[str] | None = None,
    request_id: str = "",
    owner_name: str = "",
    ask: str = "",
    options: list[dict[str, Any]] | str | None = None,
    agent: str = "",
    observers: list[str] | str = "",
    after: list[str] | str = "",
    said: list[dict[str, Any]] | str | None = None,
    check: str = "",
    by: str = "",
    goal: str = "",
    mover: str = "",
    then: str = "",
    wait_kind: str = "",
    wait_anchor: str = "",
    wait_event: str = "",
    ask_by: str = "",
    post_wake_mover: str = "",
    draft: str = "",
    step_proof: list[dict[str, Any]] | str | None = None,
    contact: str = "",
    extra: dict[str, Any] | None = None,
    fixes: "list[tuple[str, str, str]] | None" = None,
    until: str = "",
    waits: list[dict[str, Any]] | str | None = None,
    wait_mode: str = "",
) -> tuple[str, str]:
    """Every gate and every write of the create tool, without its identity check (_who: the tool checks it, the client API's
    question write is proved by its machine token instead) -> (the new item's id, the tool's reply). The one place an item is
    created: the tool and `client.py post question` both come through here, so a script cannot file what the tool would refuse.
    `by` = the writer when it is a script and not the creating session ("<label> (a script on <machine>)"): the item is saved and
    mirrored under that name and records it as `filed_by`. The script owes no page, and nobody else is made to answer for its write
    except the page's keeper: the page debt is charged to the keeper of a pilot project's page (the keeper, or a page's own agent that
    is not a front agent) and told to it through the pilot relay, and to no one when the project has none; never to the creator, so a
    burst of filings cannot get the creator's own board writes refused (_refuse_if_owing is skipped for the script, and the creator's existing debt does not
    refuse it either). The mover is told nothing (a front agent mover is never messaged about its item, and no session is named in needs here);
    each session the caller names in needs is told once, as for the tool."""
    h = _hooks()
    if request_id:
        prev = _gh.resolve(_requests().get(request_id) or "")   # an id the worker re-keyed since → the item's id now
        if prev and _path(prev).exists():      # an entry whose item is gone is no previous entry: file anew (the map is rewritten below)
            it = _load(prev); it["gid"] = prev
            return prev, f"already created as {_gh.shown(prev)} (same request_id).\n" + h.fmt(it) + h.nag()
    subject, description, next, ask = (_shown_ids(x) for x in (subject, description, next, ask))   # g7 →
    if subject.strip() and not by and not any(subject.startswith(pfx) for pfx in _cfg.CFG["subject"]["prefixes"]) and not _fg._SUBJECT_TAGGED.match(subject):
        pfx_ = _gates.project_subject_prefix(project)        # a subject with no scope prefix takes its project's (a pure fact; the reply says so)
        if pfx_:
            subject = pfx_ + subject.lstrip()
            _calls.fixed("subject-prefix", f"the scope prefix {pfx_.strip()} was put before the subject, as the project's scope names it")
    _fg._gate_subject(subject)
    _fg._gate_recycle_item(subject)
    _fg._gate_description(description)
    if _writes.session_next() and not by:      # the create tool's own call: a script's item (the question route, a watcher, the terminal prompt) is filed whatever its first bullet
        _fg._gate_goal(description)
    _fg._gate_next(next, has_ask=bool(ask.strip()) and ask.strip().lower() not in h.ask_none, session=_writes.session_next())
    ask = "" if ask.strip().lower() in h.ask_none else ask
    if ask:
        ask = h.gate_ask(ask)
    _fg._gate_bare_urls({"description": description, "next": next, "ask": ask}, session=_writes.session_next())
    opts = h.gate_options(options)
    needs_l = _gates.gate_needs(needs, project, owner) if (needs if isinstance(needs, list) else needs.strip()) and str(needs).strip().lower() not in h.ask_none else []
    if agent.strip() and agent.strip().lower() not in h.ask_none:    # the older form writes the session into needs
        needs_l = _canon_needs([*_needs_kinds({"needs": needs_l}), _gates.gate_needs_session(agent, project, owner)], _anc.names())
    obs = _gates.gate_observers(observers) if (observers if isinstance(observers, list) else observers.strip()) and str(observers).strip().lower() not in h.ask_none else []
    aft = _gates.gate_after(after) if (after if isinstance(after, list) else after.strip()) and str(after).strip().lower() not in h.ask_none else []
    owner = h.session_id(owner)                                 # a pane name becomes its transcript id when the heartbeat knows it
    said_l = _gates.gate_said(said, owner, owner)                    # the trailers: his words checked against the transcript; a failed check refuses the create
    chk = _checks.parse_check(check) if check.strip() and check.strip().lower() not in h.ask_none else ""   # the done check: gated on its form; a create is never refused for a hand-off
    meta: dict[str, Any] = {"owner": owner, "project": project, **(extra or {})}     # extra = a script route's own marks (the terminal prompt's), written with the item
    until_v = _model.clean(until)
    if until_v.lower() in h.ask_none:
        until_v = ""                   # a "none" on a create is nothing to clear
    alias_used = ["ask_by"] if _model.clean(ask_by) and _model.clean(ask_by).lower() not in h.ask_none else []
    alias_ends = h.wait_alias_gate(alias_used)
    if until_v:
        try:
            until_at = h.wake_at(h.parse_wake(until_v))
        except ToolError:
            raise ToolError(f"Refused: until is YYYY-MM-DD or YYYY-MM-DDTHH:MM ({_cfg.tz_abbr()}), a real date (got {until_v!r})")
        if until_at <= _pages.zone_now():
            raise ToolError(f"Refused: until must be in the future ({_cfg.tz_abbr()})")
        if _uw.slot_of(_model.clean(wait_kind).lower()) == "ask_by" and len(until_v) != 10:
            raise ToolError(f"Refused: on a relay or event wait until is its ask-by day, YYYY-MM-DD with no time of day (got {until_v!r}); pass the day alone, e.g. until={until_v[:10]}")
        if _uw.slot_of(_model.clean(wait_kind).lower()) != "ask_by":      # the cap judges a wait on a date as an update's wake is judged (a relay's or event's ask-by day is no wake)
            _gates.gate_cap({}, said_l, "until", h.parse_wake(until_v), until_at.timestamp())
    elif alias_used:
        until_v = _model.clean(ask_by)          # ask_by is the old name of the date (an until beside it wins)
    model_set, _ = _gates.gate_model_args({"goal": goal, "mover": mover, "then": then, "wait_kind": wait_kind, "wait_anchor": wait_anchor, "wait_event": wait_event,
                                     "until": until_v, "post_wake_mover": post_wake_mover}, {})   # a "none" on a create is nothing to clear
    list_plan = _gates.gate_waits(waits, wait_mode, gid="", project=project, creating=True, stored={}, backstop=str(h.parse_wake(until_v)) if until_v else "",
                                  others={"wait_kind": _model.clean(wait_kind), "wait_anchor": _model.clean(wait_anchor), "wait_event": _model.clean(wait_event), "ask_by": _model.clean(ask_by),
                                          "after": after if isinstance(after, list) and after or isinstance(after, str) and after.strip().lower() not in ("", *h.ask_none) else ""},
                                  anchor_gate=lambda tmp: h.anchor_wait_gate({}, tmp, "", creating=True), event_gate=lambda tmp: h.evwait_gate({}, tmp, creating=True))
    if list_plan is not None:           # a list is 2 to 8 lines (a clear of a list that is not there is None; one line on a create is refused by the gate)
        model_set["wait_kind"], model_set["wait_mode"] = "list", list_plan.mode
    if owner_name:
        meta["owner_name"] = owner_name
    contact_v = _gates.gate_contact(contact, project, (owner,)) if contact.strip() else h.contact_default(owner, project)     # a named contact is checked against the project's front agents; else the creator when it is one, else the project's -main
    if contact_v:
        meta["contact"] = contact_v
    for k, v in (("needs", needs_l), ("ask", ask), ("priority", priority), ("due", due), ("options", opts), ("observers", obs), ("after", aft), ("said", said_l), ("check", chk)):
        if v:
            meta[k] = v
    if next:
        h.next_put(meta, next, owner, owner)     # the writer of a create's lines is its creator (a script's filing included: its label is no session)
    proof_note = _proofs.step_proof_set(meta, _steps.view(meta, keeper=owner), step_proof) if step_proof is not None else ""     # a step's proof: the event that finishes it
    _gates.gate_step_gap(meta, _steps.view(meta, keeper=owner), [])      # a step that delivers a pull request, followed by another session's step, needs its proof
    meta.update(model_set)
    if list_plan is not None:
        meta["waits"] = [dict(ln) for ln in list_plan.lines]
    wait_note = _uw.alias_note(alias_used, model_set.get("until", ""), alias_ends) if alias_used else ""
    if list_plan is not None:
        wait_note += list_plan.note + "\n(wait list: " + _wl.summary(meta, _gh.shown) + ")"
    if _uw.needs_date(meta):                                     # a kind with no date is never refused: the item's own words, else a suggestion, else tomorrow
        fb_d, _fb_how, fb_note = h.fallback_wait_date(meta, next, description, due)
        meta["until"] = fb_d
        wait_note += fb_note
    if _wt.stored_until(meta) and not _uw.kind_of(meta) and _wt.after_of(meta):
        meta["wait_kind"] = "item"         # a date beside an after link is that wait's backstop (as ask_by was): the wait stays on the item
    evw_note = h.evwait_gate({}, meta, creating=True)            # an event wait: its phrase in the canonical form, and refused when the event already happened
    then_note = h.owner_then_default(None, meta, "open", _session_label(owner) or owner, "then" in model_set, mover.strip())      # D9: an item created for his call has the agent doing the work as its then (a builder that files its own decision item is its own then), not the front agent that relayed it
    draft_txt, _ = _gates.gate_draft_args(draft, False)             # the verbatim text the owner pastes elsewhere; a create has no state to guard it by (the guard runs when an update sets your-step)
    if draft_txt:
        meta["draft"] = draft_txt
    if anchors:
        raise ToolError("Refused: anchors belong to the project, not the item — create the item, then anchors(project=<its project>, add=[url…], items=[<its id>]) for a thread about this item, or without items for a project-wide one")
    _gates.gate_metadata(meta, creating=True)
    lifted = "" if ask else h.lift_ask(meta, writer=owner, keeper=owner)   # a client without the ask parameter: the ask's form as next's first line
    asked = lifted + h.ask_owed(meta)       # needs=decision without an ask: a nag line, or refused from [ask] refuse_after
    _dg._gate_one_decision(meta, description, bool(lifted))  # one decision per item, options in words: the ask is being written
    _dg._gate_alternatives(meta, description)  # alternatives named, none listed
    if not _writes.question():    # a script's question is never lost on its wording: its Decide is the question as written, and the board may take no options
        _dg._gate_open_question(meta)          # an open question with no options: the page would draw Yes / No under it
        _dg._gate_recommend_stance(meta)       # no options and a Recommend that is no yes or no: the same Yes / No under a question it cannot answer
    _dg._gate_mockup(meta, description)        # a mockup linked in the text rides on the ask too
    _dg._gate_own_action(meta, create=True)    # his own action asked as a decision: it is a your-step
    asked += _dg._options_note(meta) + _dg._actor_note(meta)
    desc_note = _gates.gate_model({"status": "open", "subject": subject, "description": description, "metadata": meta}, None, creating=True, date_given=bool(until_v))    # the write guards of the item model, every field judged on a create
    h.anchor_wait_gate({}, meta, creating=True)                  # an anchor wait: its anchor must be on the project's list already (after the model guards, whose refusals are more specific)
    if _writes.session_next() and not by and (not _nl.split(meta.get("next")) or str(meta.get("next")).strip().lower() in _nl.NONE_WORDS) \
            and not _model.stood_his({"status": "open", "metadata": meta}, lambda i_: h.after_open(i_.get("metadata") or {})):      # N6: a session's create leaves the item with an open step (his server-made step, from needs=decision with an ask or a your-step, counts)
        raise ToolError(f"Refused: the new item has no open step in next: {_nr.NO_STEP_FIX_HELD if meta.get('hold') else _nr.NO_STEP_FIX}")
    if not _writes.terminal_row():      # the terminal prompt's row files "<owner>: open … and answer" and sets its state your-step in the next call (service/terminal_prompt.py `_terminal_state`; a create sets no step): its own script, not a session hiding a step
        _gates.gate_owner_step({"status": "open", "subject": subject, "description": description, "metadata": meta}, create=True)     # The owner's step under an agent's state is refused, as on an update
    if _writes.session_next() and not by and h.model_guards_on():
        _gates.gate_front_step("", {"status": "open", "subject": subject, "metadata": meta}, [], _steps.view(meta, keeper=owner), owner)     # a step that opens with a front agent on an item another session moves: nothing could wake it for the step
    if meta.get("mover") or meta.get("then") or _needs_sessions(meta):     # step 2: a hand-off at creation to a session with no pane is refused: an item created with no mover is nobody's hand-off, the project's builder or -main agent takes it (D1)
        _gates.gate_handoff("", None, {"status": "open", "subject": subject, "metadata": meta}, by or owner)
    if not by:                             # a script owes no page; the creator's own debt is not its to be refused for
        h.refuse_if_owing(owner)
    h.record_fixes(meta, fixes)             # what the server fixed in this create (server_fixes.py): the mark and a History line
    item = {
        "id": "",
        "subject": subject,
        "description": description,
        "status": "open",
        "metadata": meta,
    }
    if by:
        item["filed_by"] = by              # the script that filed it (the creator is the session that answers for it)
    local, local_held = "", False          # phase 2 prep: why the item got a local id (GitHub down, or the write budget spent), "" when it got its issue number
    if _gh.issue_ids():                    # the id is the issue's number, so the issue comes first (the one write that waits for GitHub)
        try:
            n = _gh.allocate(item, {owner: _session_label(owner)}, max_wait=_gh.CREATE_WAIT)     # a create never waits out the hour's write budget: over a few seconds it takes a temporary id
            gid = f"{_gh.letter()}{n}"
        except _gh.GitHubDown as e:
            if not _gh.enabled():          # no queue to carry the create later: the refusal of phase 1
                raise ToolError(f"Refused: {e if isinstance(e, _gh.GitHubBudget) else f'GitHub did not answer ({e})'} — with [github] issue_ids on a new item's id is its issue number, so a create "
                                "waits for GitHub; try again in a minute (an update or a close never waits: those are queued)")
            gid, local = _gh.allocate_local(), str(e)   # the outage fallback (GitHub down, or the hour's write budget spent): a temporary id, the create queued ahead of the other jobs, re-keyed when the issue is made
            local_held = isinstance(e, _gh.GitHubBudget)
        except _gh.GitHubError as e:
            raise ToolError(f"Refused: GitHub refused the issue for this item ({e})")
    else:
        gid = _next_id()
    item["id"] = gid[1:]
    item["updated"] = time.time()          # the item's own clock (the renderer used to trust the file's mtime, which a migration rewrites)
    item["state_updated"] = item["updated"]  # state clock: only a state change moves it (the page-owed badge reads it)
    item["confirmed"] = item["updated"]      # last confirmed true: a create, a state change or the confirm tool
    writer = by or owner
    _writes.save(gid, item, writer=writer)
    if request_id:
        _remember_request(request_id, gid)
    stew, role = _telling.pilot_charge(meta.get("project", ""), writer)
    if _writes.terminal_row():
        stew, role = "", ""                # a terminal-prompt row owes the page nothing: no one is charged, the router and the keeper are told nothing
    if stew and role == "name" and h.writer_owes() and not by:   # the writer owes it; the keeper only past the grace (a script owes none)
        told = _telling.writer_charge(meta.get("project", ""), gid, owner, stew, "created", loose=False)
    else:
        if by and stew and h.session_id(stew) == h.session_id(owner):
            stew = ""                  # a script's filing is never charged to the creator, even when it is also the keeper
        charged = stew if by else (stew or owner)
        if charged:
            h.owed_mark(meta.get("project", ""), charged, gid)  # a new item is a state change; in the pilot the page's keeper accounts for another session's (a script's filing: the keeper's alone)
        told = _telling.pilot_relay(meta.get("project", ""), gid, item, "created", writer, stew, role) if stew else ""
    told += _telling.tell_needed(gid, item, _needs_sessions(meta), writer)   # a session named in needs gets one notice
    told += _telling.handoff_notify(gid, item)     # step 2: the hand-off at creation is told, unless the notice above did
    h.publish()
    item["gid"] = gid
    machine_note = h.machine_note(gid, item, owner)      # an open step names an offline machine and no machine anchor tells the mover when it is back: a note, never a refusal
    if local:
        why_ = f"GitHub is taking no new write right now ({local[:120]})" if local_held else f"GitHub did not answer ({local[:120]})"
        told += (f"\n({why_}, so {_gh.shown(gid)} is a temporary id: the item takes its issue number when {'GitHub has room' if local_held else 'GitHub is back'}, "
                 f"{_gh.shown(gid)} stays as an alias for it, and {_session_label(owner) or 'its mover'} is told the new id)")
    return gid, (f"created {_gh.shown(gid)} — it is being published to the board ({_inst.BOARD_URL}) now.\n" + h.fmt(item) + h.said_note(said_l) + proof_note + asked + h.form_notes(description, next, meta=meta, gid=gid, cmd=True, ext="external" in _needs_kinds(meta)) + desc_note + evw_note + wait_note + machine_note
                 + then_note + similar_note(gid, subject, str(meta.get("project") or "")) + told + h.nag("" if by else owner))

