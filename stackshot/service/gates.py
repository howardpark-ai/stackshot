"""gates.py: the write gates of the create, update and complete tools, and the checks that come before the item lock: the rules that refuse a write, with the text of each refusal.

Every gate raises `ToolError` itself, with the sentence the writer reads, and returns nothing (a few return what they normalized: the stored form of a list, the replacing item's id of a close). A gate judges the item a
write leaves, or the arguments it passes, against a rule of the model (model/, waits/, anchors/) and never writes. `service/create.py` and `service/update.py` call them in the order those modules keep; the order is part
of what a write means. The checks that come before the lock (`fix_front_mover`, `until_in`, `ask_pre`, `gate_self_wait`) are called by the tool wrappers on the surface, which are in web/tools/ and only parse input.

What stays on server.py, and is reached through `Hooks` (which web/wiring.py fills once with `install` (web/server.py calls it at its import); this module cannot import server.py, the surface sits above it): the per-write thread-local flags (`question`,
`terminal_row`, `reformat`, `session_next`, read through accessors until the telling and the routes that set them move), the helpers of the areas that still sit there (the hand-off machinery, the roster and the contact
lookups, the effective state, the wake parser, the anchors scoped to an item) and what the renderer answers (the answers and times). A function hook is looked up on its owner module (by web/wiring.py) when a gate
runs, so a suite that replaces one there still reaches the gate; a suite that replaces a gate patches it here, on its owner.

The rules of an item's fields and of an ask's options are model/'s (`field_gates.py`, `decision_gates.py`), called on those modules. The metadata gate looks a project's page up in the registry and may rebuild it, so it
is here (`gate_metadata`) with the registry readers it uses (`registry_hits`, `registry_hit`, `registry_text`) and the scope prefix a project's record gives a subject (`project_subject_prefix`).

Imports point down only: this module imports the domain and core and the store's readers beside it (service/store.py), never web/ and never audit/."""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable

from fastmcp.exceptions import ToolError

from stackshot.anchors import anchors as _anc
from stackshot.core import agentbox as _ab
from stackshot.core import call_log as _calls
from stackshot.core import config as _cfg
from stackshot.core import store as _store
from stackshot.core.instance import OWNER
from stackshot.fleet import clients as _clients
from stackshot.fleet import sessions_registry as _sr
from stackshot.fleet.sessions_registry import _session_label
from stackshot.github import ghsync as _gh
from stackshot.model import ask_leaves as _askl
from stackshot.model.bullet_text import _clip_line
from stackshot.model import contact as _contact
from stackshot.model import draft as _draft
from stackshot.model import faults as _faults
from stackshot.model import field_gates as _fg
from stackshot.model.ids import _norm_id
from stackshot.model import holders as _holders
from stackshot.model import member_gates as _mgates
from stackshot.model import model as _model
from stackshot.model import migration as _mig
from stackshot.model import model_guards as _mg
from stackshot.model.needs import _after_of, _canon_needs, _needs_kinds, _NEEDS_KINDS, _needs_list, _needs_sessions, _waits_decision
from stackshot.model import nextlines as _nl
from stackshot.model import note_read as _noteread
from stackshot.model import said as _said
from stackshot.model import states as _states
from stackshot.model import step_commands as _sc
from stackshot.model import step_proof as _sp
from stackshot.model import steps as _steps
from stackshot.model import work as _work
from stackshot.projects import brains as _brains
from stackshot.projects import pages as _pages
from stackshot.projects import projects as _prj
from stackshot.projects.project_registry import _registry, _roles_sync_safe
from stackshot.router import router_live as _router_live
from stackshot.service import handoff as _handoff
from stackshot.service import item_read as _item_read
from stackshot.service import telling as _telling
from stackshot.service import wakes as _wakes
from stackshot.service import watching as _watching
from stackshot.service import writes as _writes
from stackshot.service.store import _load, _path
from stackshot.waits import builderless as _bl
from stackshot.waits import event_waits as _ew
from stackshot.waits import handoff as _ho
from stackshot.waits import handover as _hv
from stackshot.waits import self_wait as _selfwait
from stackshot.waits import server_fixes as _sf
from stackshot.waits import until_write as _uw
from stackshot.waits import wait_list as _wl
from stackshot.waits import wait_list_write as _wlw
from stackshot.waits import waiting as _wt
from stackshot.waits import watchers as _watch


@dataclass(frozen=True)
class Hooks:
    after_open: Callable[..., Any]
    after_reaches: Callable[..., Any]
    answers_of: Callable[..., Any]            # web/render.answers_of: the answers an item carries
    ask_none: Any            # the closed list of words that clear an ask (server._ASK_NONE)
    ask_stands: Callable[..., Any]
    basis_words: Any
    close_refusal: Any            # the full close rule (server._CLOSE_REFUSAL); a refused close no longer appends it: it shows the accepted call, the tool text carries the rule
    contact_alive: Callable[..., Any]
    contact_fronts: Callable[..., Any]
    contact_same: Callable[..., Any]
    eff_state: Callable[..., Any]
    follow_superseded: Callable[..., Any]
    front_held: Callable[..., Any]            # audit/front_step.held: the front agent a step opens with when the write check refuses it (service/ imports no audit/)
    front_handover_ok: Callable[..., Any]
    handoffs_in: Callable[..., Any]
    handover_kind: Callable[..., Any]
    hub_sessions: Callable[..., Any]
    item_mover: Callable[..., Any]
    contact_main: Callable[..., Any]
    model_guards_on: Callable[..., Any]
    model_page: Any            # the gbrain page of the item model (server._MODEL_PAGE)
    open_item_named: Callable[..., Any]
    outcomes: Any            # how an item may end (owner_words.OUTCOMES)
    own_repo: Callable[..., Any]
    owner_quote_on: Callable[..., Any]
    owner_words_on: Callable[..., Any]
    parse_wake: Callable[..., Any]
    relaunch: Any            # the sentence a refused close ends with (owner_words._RELAUNCH)
    role_of: Callable[..., Any]
    same_sess: Callable[..., Any]            # fleet/sessions_registry._same_sess
    scoped_anchors: Callable[..., Any]
    session_id: Callable[..., Any]            # page_debts._session_id (web/)
    session_roster: Callable[..., Any]
    shown_ref: Callable[..., Any]            # page_debts._shown_ref (web/)
    store_ref: Callable[..., Any]            # fleet/sessions_registry._store_ref
    wake_at: Callable[..., Any]
    when_words: Callable[..., Any]            # web/render.when_words: a time in words
    zone: Callable[..., Any]            # the board's time zone as server.py holds it (ZONE, read when a refusal says a time)


_hooks_: Hooks | None = None


def install(hooks: Hooks) -> None:
    """Give the gates what is still server.py's (once, at its import)."""
    global _hooks_
    _hooks_ = hooks


def _hooks() -> Hooks:
    if _hooks_ is None:
        raise RuntimeError("the gates have no hooks installed (web/wiring.py installs them, called from web/server.py at its import)")
    return _hooks_


def lazy_said(said: Any, sender: str) -> Callable[[], list[dict[str, Any]]]:
    """The entries of a write's `said` as `gate_said` reads them (checked against the transcript), read once and only when asked, for the checks that come before the item lock: a `said` the gate refuses is
    no words here ([]); the write's own gate under the lock then refuses the write with its text."""
    memo: list[list[dict[str, Any]]] = []
    def get() -> list[dict[str, Any]]:
        if not memo:
            try:
                memo.append(gate_said(said, str(sender or "").strip(), "", dry=True))
            except Exception:  # noqa: BLE001  — refused words are no words; the write's own check says why
                memo.append([])
        return memo[0]
    return get


def _front_sibling(sender: str, key: str, project: str) -> bool:
    """Is `sender` a live front agent of the item's project, and `key` another live front agent of it (`key` as the roles list it)? False for the sender itself, for a background agent, another project's session, a
    session no page lists, a retired one, and on a failing roles read."""
    try:
        h = _hooks()
        s = str(sender or "").strip()
        if not s or not project:
            return False
        nm = _anc.names()
        roles, skey = h.role_of(s, nm)
        return bool(skey) and skey != key and _bl.front_siblings(roles.get(skey), roles.get(key), project)
    except Exception:  # noqa: BLE001  — the rule is an extra: a failed read leaves today's path
        return False


def sibling_quote(said_l: list[dict[str, Any]]) -> str:
    """The owner's words in a write's checked `said` entries, read the way the wake cap reads them (owner_words._owner_quote_on: an Acked-by checked against a transcript, a message no older than [waiting] cap_days; a board answer is none of this
    write's `said`): his sentence, or "" when there are none."""
    if not said_l:
        return ""
    return _hooks().owner_quote_on({}, said_l, _wt.cap_days())[1]


def _sibling_pointer(key: str, verb: str = "update") -> str:
    """The one clause a front agent that names a sibling front agent without the owner's words is given: what to send to hand it over on his order (`verb`: the call it is, update or create)."""
    return f"to hand it to {key} on {OWNER}'s order, send the {verb} again with said=[Acked-by …] quoting his words with the time"


def _front_mover_case(field: str, value: str, sender: str, project: str, current: str = "") -> "tuple[str, str, list[str], str] | None":
    """The case the front-mover rule judges: (the front agent's key, its project, the project's builder list, the project's hub) when a create or update sets mover, then (which becomes the mover after
    the owner's answer) to a front agent, sent by another session; None otherwise. A front agent gets no hand-off notice, so the item would sit handed
    and not taken until the owner noticed. Not a case: a front agent naming itself, the owner, a background agent, a session no page lists, a value that clears the field, and the value the item
    already stores in `current` (nothing changes hands). A failing roles read is no case, with one stderr line, as front_sender does."""
    h = _hooks()
    v = _model.clean(value)
    if not v or v.lower() in h.ask_none or _model.is_owner(v):
        return None
    try:
        nm = _anc.names()
        same = lambda a, b: bool(a) and bool(b) and (a == b or h.session_id(a) == h.session_id(b) or _anc.canonical(a, nm) == _anc.canonical(b, nm))
        cur = str(current or "").strip()
        if same(cur, v):
            return None
        roles, key = h.role_of(v, nm)
        if not key or roles[key].get("role") != "front":      # a one-session project's single name-line session is not front here either, as in the needs gate and front_sender
            return None
        s = str(sender or "").strip()
        if s:
            _r, skey = h.role_of(s, nm)
            if (skey and skey == key) or same(s, v):
                return None
        proj = roles[key]["project"]
        hub = h.hub_sessions(project)[0] if project else ""
        builder = _handoff.handoff_builder(project) if project else []      # the one predicate: no builder = front-only (anchors.front_only)
    except Exception as e:  # noqa: BLE001  — the gate is an extra: a failure in it lets the write through
        print(f"front-mover gate: roles read for {field}={v} failed ({e.__class__.__name__}: {e}); the write passes", file=sys.stderr, flush=True)
        return None
    return key, proj, list(builder), hub


def _for_peer(key: str, page: str) -> str:
    """How to ask the front agent `key`, listed on `page`, for a check or an answer only it can give: a message to the top-level page with `For <key>,` on its first line, the one a plain message to a front agent is
    refused for. The router reads that line against the agents of the top-level page (router.for_agent_rule, router_live.agent_root), so it is named only when that page lists `key`; "" when it does not (a peer
    listed only on a sub-page) or the read fails."""
    try:
        reg = _anc.registry()
        top = _anc.pilot_root(page) or page
        if any(str(k).lower() == key.lower() for k in ((reg.get(_router_live.agent_root(top, reg)) or {}).get("agents") or {})):
            return f"message(to={top!r}) with the first line \"For {key}, ...\""
    except Exception:  # noqa: BLE001  — the wording only
        pass
    return ""


def _front_only_why(key: str, project: str, sender: str) -> str:
    """Why a hand-over to the front agent `key` of a front-only project was refused, as the clause that follows "this call was refused because": the half that failed (front_handover_ok), the sender
    (retired, or no session a page lists) and / or the target (not a live front agent of the item's project). A failed read names both halves."""
    try:
        h = _hooks()
        nm = _anc.names()
        s = str(sender or "").strip()
        roles, skey = h.role_of(s, nm) if s else ({}, "")
        why = []
        if not skey:
            why.append(f"{s} is not a session any project page lists" if s else "the call names no sender")
        elif roles[skey].get("retired"):
            why.append(f"{s} is retired")
        troles, tkey = h.role_of(key, nm)
        if not _bl.front_of(troles.get(tkey) if tkey else None, project):
            why.append(f"{key} is not a live front agent of {project or 'the project'}")
        if why:
            return " and ".join(why)
    except Exception:  # noqa: BLE001  — the wording only: a failed read gives both halves
        pass
    return f"the sender is not a live session some project page lists, or {key} is not a live front agent of {project or 'the project'}"


def _front_mover_refusal(field: str, case: "tuple[str, str, list[str], str]", project: str = "", sender: str = "") -> ToolError:
    """The refusal of a front-mover case. A project that has a builder says the front agent gets no hand-off notice (the explanation is still true there). A front-only project (no builder: anchors.front_only)
    states only the rule that applies, a live session some project page lists may name a live front agent of the item's project in `mover` (told by a hand-off notice) or `then` (told
    by the answer or the wake), which half of that this call failed (_front_only_why), and the path to the peer for a check: the page key with `For <peer>,` first."""
    key, proj, builder, hub = case
    via = _for_peer(key, proj)
    if not builder:
        what = project or "the project"
        return ToolError(f"Refused: {field}={key} names {key}, a front agent of {proj}, for an item of {what}, and {hub or 'The project'} has no builder to hand it to, so the item stays with its current mover. "
                         f"A live session some project page lists may name a live front agent of {what} in mover= (told by a hand-off notice) or then= (told by the owner's answer or the wake); "
                         f"this call was refused because {_front_only_why(key, project, sender)}." + (f" To ask {key} for a check or an answer, {via}." if via else ""))
    return ToolError(f"Refused: {key} is a user-facing agent of {proj}, and {field}={key} from another session hands it an item it gets no notice of "
                     f"(the server sends a front agent no hand-off notice, so the item would sit handed and not taken). Hand build work to the project's builder, {builder[0]} ({field}={builder[0]})"
                     + (f"; for a check or an answer only {key} can give, {via}." if via else "."))


def step_marks(meta: "dict[str, Any] | None", done: Any = None, dropped: Any = None, reword: Any = None, work: Any = None, sender: str = "") -> "frozenset[int] | None":
    """The checklist positions (0-based) a write settles or rewords in the item as it stands (`meta`): the refs of `done` and `dropped` and the keys of `reword` read as the update tool reads them (`steps.resolve`,
    `steps.resolve_reword`: a position as a number or text, a comma list, a JSON string, or the exact text of an open step), and the first open step of the one a `work` status done finishes (the sender's, or the
    `agent` it names). None when a ref cannot be read the way the tool reads it (the write is refused for it, or the call is not one this reads): a hand-back then reads it as marking the holder's step and is the swap."""
    try:
        steps = _steps.view(meta)
        ix = {*_steps.resolve(steps, done, "done"), *_steps.resolve(steps, dropped, "dropped")}
        if _steps.reword_given(reword):
            ix |= set(_steps.resolve_reword(steps, reword))
        ix_named = _fg._marks_given(done)      # a call that names the steps done ticks only those: a work status done adds none
        if work is not None and str(work).strip() and not ix_named:
            spec = _work.parse(work)
            if spec.get("state") == "done" and not spec.get("remove"):
                nm = _anc.names()
                same = lambda x, y: bool(x) and bool(y) and (x == y or _anc.canonical(x, nm) == _anc.canonical(y, nm))
                at = _work.step_of(steps, spec.get("agent") or sender, same)
                if at >= 0:
                    ix.add(at)
        return frozenset(ix)
    except Exception:  # noqa: BLE001  — a ref the tool would refuse or this cannot read: the holder's step is taken as marked
        return None


def handed_back(value: str, sender: str, builder: list[str], meta: "dict[str, Any] | None", item: "dict[str, Any] | None", project: str = "", marked: "frozenset[int] | None" = frozenset(), ends: bool = False) -> bool:
    """Is a session's `mover` or `then` = the front agent `value` a hand-back: the item goes back to the front agent that holds its first open named step (past the owner's own lines), as the item
    STANDS before this write (`meta`, never a step line the write itself adds). All must hold: the front agent holds that step (telling.step_holder_at, in any letter case, as own_step reads it) and is a front agent of the
    item's `project` (telling.front_name, as the owner's answer reads its holder); the write leaves that step open (`marked`: the positions it ticks, drops or rewords, `step_marks`, None when its refs cannot be read; `ends`: it closes the item or clears next), so the
    notice has a step to read; the sender is the project's builder, or the item's current mover (`item`, read as the board reads it) when that mover is no front agent (a front agent that moves the item hands it to a
    sibling only on the owner's words, `fix_front_mover`'s own case); the front agent is a live session (live or cloud: a mover nobody can wake is the swap's); the item is a stored one (a create has none). A front
    agent that holds the step is the one the work comes back to, and `handoff_notify` tells it as a turn; a mover set by any other session, or one whose step comes after another's, is the builder's as before. A failing
    read is no hand-back."""
    try:
        if not meta or not item or not project:
            return False
        holder, at = _telling.step_holder_at(meta, past_his=True)
        if not holder or not _anc.same_session(holder, value) or ends or marked is None or at in marked:
            return False
        if not _telling.front_name(value, project):
            return False
        mover_now = str(_hooks().item_mover(item) or "")
        by_builder = any(_anc.same_session(sender, b) for b in builder)
        by_mover = _anc.same_session(sender, mover_now) and _telling.front_role(sender) is False      # a failed roles read is not "no front agent"
        if not (by_builder or by_mover):
            return False
        return _mg.Ctx().session_state(value) in ("live", "cloud")
    except Exception as e:  # noqa: BLE001  — an extra: a failed read leaves the swap
        print(f"front-mover gate: hand-back read for {value} failed ({e.__class__.__name__}: {e}); the swap stands", file=sys.stderr, flush=True)
        return False


def fix_front_mover(field: str, value: str, sender: str, project: str, current: str, meta: "dict[str, Any] | None", said_l: "Callable[[], list[dict[str, Any]]] | None" = None, verb: str = "update", item: "dict[str, Any] | None" = None, marked: "frozenset[int] | None" = frozenset(), ends: bool = False) -> "tuple[str, str, list[tuple[str, str, str]]]":
    """The front-mover rule as a fix (server_fixes.FRONT_MOVER): a mover or then that another session sets to a front agent becomes the project's builder, since the front agent gets
    no hand-off notice. → (the value to use, the note for the reply, the fixes to record on the item: (fix, token, History line), a line of "" = take the mark off). The value is the one sent when it is
    no case (_front_mover_case), or when the server already substituted this very value on this item for this very sender less than a day ago and the sender sends it again: the mover's no, kept as sent with a note, and the server leaves that
    field alone (another session, or the same one after a day, is substituted as a new case). With no builder to substitute (front-only), a `mover` or `then` goes through when
    `front_handover_ok` says so (the target is a live front agent of the item's project, the sender a live session some project page lists, of any project); a `mover` target is told by a hand-off
    notice, a `then` target by the owner's answer or the wake (no write tells it, as before).
    One case goes before all of that: the sender is a live front agent of the item's project and the value another live front agent of it (a sibling), and `said_l` (`lazy_said`: the write's `said`, checked) carries the
    owner's words (`sibling_quote`, the wake cap's reading). The value is then kept as sent, builder or none, with a note; the hand-off record carries his quoted words and its notice (handoff_notify) tells the sibling. With no
    such words a sibling's swap note says how to send them (`verb`: the call, update or create, the note names)."""
    h = _hooks()
    case = _front_mover_case(field, value, sender, project, current)
    if case is None:
        return value, "", []
    key, proj, builder, _hub = case
    told_now = field == "mover" and not (meta and _model.waits_stored(meta))      # a mover write on an item that waits names who picks it up when the wait ends: the owner's answer or the wake tells it, no write does
    if handed_back(value, sender, builder, meta, item, project, marked, ends):      # the front agent holds the item's open step and the sender is its builder or its mover (no front agent): the item goes back to it as sent, and it is told (handoff_notify, for this write's hand-back only; a then, by the answer or the wake)
        if field == "mover":
            hb = getattr(_telling.HO_STATE, "handback", None)
            if hb is None:
                hb = _telling.HO_STATE.handback = set()
            hb.add(key)
        return value, (f"\n(note: {field}={key} is kept as you sent it: {key} holds the item's open step, so the item goes back to it" + (", and it is told it is handed back)" if field == "mover" else "; the owner's answer or the wake hands it the item and tells it)")), []
    sib = _front_sibling(sender, key, project)
    if sib and sibling_quote(said_l() if said_l else []):
        return value, (f"\n(note: {field}={key} is kept as you sent it, on {OWNER}'s words in said; {key} is a front agent of {proj}, and "
                       + (f"is told it is handed the item)" if told_now else "if the item keeps it, the owner's answer or the wake hands it the item and tells it)")), []
    token = f"{field}={key}"
    by, now = h.session_id(sender) or sender, time.time()
    hit = _sf.marked_by(meta, _sf.FRONT_MOVER, token, by, now)       # the substitution was this session's, within a day: its second send is the mover's no
    if hit:
        return value, (f"\n(note: {field}={key} is kept as you sent it: {key} is a user-facing agent of {proj} and gets no hand-off notice, so the item sits with it until it looks; "
                       f"the server substituted the builder for this value before, and now leaves the field alone)"), [(_sf.FRONT_MOVER, hit, "")]
    if not builder:
        if h.front_handover_ok(sender, key, project):      # a front-only project (anchors.front_only): any session a project page lists may name one of its front agents; a mover is told by a notice (handoff_notify), a then by the answer or the wake
            return value, (f"\n(note: {project} has no builder, so mover={key} stays as sent; {key} is a front agent of the project and is told it is handed the item)" if told_now else
                           f"\n(note: {project} has no builder, so {field}={key} is not replaced by one; {key} is a front agent of the project, and if the item keeps it, the owner's answer or the wake hands it the item and tells it)"), []
        raise _front_mover_refusal(field, case, project, sender)
    via = _for_peer(key, proj)
    return builder[0], (f"\n(fixed: {field}={key} is a user-facing agent of {proj} and gets no hand-off notice from another session, so {field}={builder[0]}, the project's builder, was used instead. "
                        f"If {key} really is who should take it, send {field}={key} again: the server then keeps it as sent"
                        + (f"; {_sibling_pointer(key, verb)}, and {key} is told" if sib else "")      # a sibling's second send passes as before, but only the owner's words get it told
                        + (f"; for a check or an answer only {key} can give, {via}" if via else "") + ")"), \
        [(_sf.FRONT_MOVER, _sf.bind(token, by, now), f"{field} {key} → {builder[0]}: {key} is a user-facing agent and gets no hand-off notice from another session; sending {field}={key} again keeps it as sent")]


def gate_front_step(gid: str, item: dict[str, Any], before: list[dict[str, Any]], after: list[dict[str, Any]], sender: str) -> None:
    """A session's create or update may not put a NEW or reworded open step that opens with a front agent on an item another session moves: a front agent gets no work notice and its own wakes are
    refused, so nothing could wake it for the step and it would sit until the owner noticed (the mover check of fix_front_mover, applied to a step line). `before` and `after` = the checklist as it stood and
    as this write leaves it (`item` = the item as the write leaves it); only an open step whose text is not among the open steps before is judged, so a step already held by a front agent stays whatever else the
    write changes. Passes: the item's own mover (its own item), a background agent or the owner as opener, an item with no mover or a retired one (front_step.held reads the rest), and, in a front-only project, a live front agent of the item's own project (a peer: the step hand-over
    moves the item to it, handover.peer_opener) when an open step comes before its step (handover.open_before: with none, nothing would move the item, so it is refused). A failing read lets the write through,
    except that a failing front_only read leaves a front agent's step refused."""
    h = _hooks()
    if item.get("status") != "open":
        return
    old = {_steps.key(x["text"]) for x in before if x["status"] == _steps.OPEN}
    new = [x["text"] for x in after if x["status"] == _steps.OPEN and _steps.key(x["text"]) not in old and _steps.opener(x["text"])]
    if not new:
        return
    try:
        proj = str((item.get("metadata") or {}).get("project") or "")
        mover = h.item_mover({**item, "gid": gid})
        mroles, mkey = h.role_of(mover)
        if mkey and mroles[mkey].get("retired"):      # a retired mover is not running: the step cannot be given to it
            return
        for text in new:
            roles, key = h.role_of(_steps.opener(text))
            live = bool(key) and roles[key].get("role") == "front" and not roles[key].get("retired")
            # a live front agent of the item's own project, in a project with no builder, is a peer (handover.peer_opener; front_only is read for that case alone, and a read that fails leaves it
            # refused, as before peers). The step hand-over moves the item to a peer when the step before it is done, so its step passes only with an open step in front of it: as the first open step nothing
            # would ever move the item. Every other front agent, and every front agent of a project that has a builder, is refused as before.
            try:
                peer = live and _hv.peer_opener(roles[key], proj, _anc.front_only)
            except Exception:  # noqa: BLE001
                peer = False
            i = next((n for n, x in enumerate(after) if _steps.key(x["text"]) == _steps.key(text)), 0)
            first = peer and not _hv.open_before(after, i)
            front = h.front_held(text, mover, lambda _n: live and not (peer and not first), _handoff.ho_same)
            if not front:
                continue
            mv = _session_label(mover) or mover
            # the tail names what works: a plain message to a front agent starts no turn there (it goes to the project's background agent or is held), so it is the hand-over (`mover=`, between front agents of one front-only project) and the `For <agent>,` first line to the agent's page
            ask = f"ask {key} with a message to {roles[key]['project']} whose first line starts \"For {key},\""
            tail = (f"Put an open step before it (the step hand-over moves the item to {key} when that one is done), hand {key} the item with mover={key}, or {ask}." if first
                    else f"Keep the step with {mv}, hand {key} the item with mover={key} (only between front agents of one project that has no builder), or {ask}." if _handoff.ho_same(sender, mover)
                    else f"Give the step to {mv} (open it with \"{mv}:\"), or {ask}.")
            raise ToolError(f"Refused: the step \"{_clip_line(_steps.first_line(text), 90)}\" opens with {key}, a user-facing agent of {roles[key]['project']}: it gets no work notice and its own wakes are refused, "
                            f"so nothing would wake it for the step, and {mv} moves {_gh.shown(gid) if gid else 'the item'}. {tail}")
    except ToolError:
        raise
    except Exception as e:  # noqa: BLE001  — the gate is an extra: a failure in it lets the write through
        print(f"front-step gate: {gid or 'a new item'} not judged ({e.__class__.__name__}: {e}); the write passes", file=sys.stderr, flush=True)


def gate_needs_session(name: str, project: str, owner: str, also: str = "", by: str = "", said_l: "Callable[[], list[dict[str, Any]]] | None" = None, verb: str = "update") -> str:
    """A session name for an item's needs → the name stored. Allowed: the item's mover itself; a background agent (or the name-line
    session of a one-session page, which no agents map retires) of any project (anchors.session_roles, which roles.json builds on); the keeper of
    the item's own page (a sub-page's `agent:`). Refused: another user-facing agent (its part is its own item, linked with after=), a retired
    name-line session (of a page that lists user-facing agents), and a session no page names. One exception to the user-facing refusal: `by`, the writer of `agent=`, a live front agent of the item's project, naming another one (a sibling)
    with the owner's words in `said_l` (`lazy_said`, read as `sibling_quote` reads them): the sibling is stored; without them the refusal ends with how to send them."""
    h = _hooks()
    name = name.strip()
    nm = _anc.names()
    me = _anc.canonical(name, nm)
    same = lambda x: bool(x) and (x == name or _anc.canonical(x, nm) == me)
    if (owner and same(owner)) or (also and same(also)):      # `also`: the item's own `then` (a hand-back to the agent that handed it over)
        return h.store_ref(nm.get(me, "") or name)        # the mover by its permanent id when the registry knows the session, else by its name when the fleet knows one, else as given
    roles, key = h.role_of(name, nm)
    hub, stew, back, front, keeper = h.hub_sessions(project)
    if key and roles[key]["role"] == "front":
        sib = _front_sibling(by, key, project)
        if sib and sibling_quote(said_l() if said_l else []):      # a front agent hands the item to a sibling on the owner's words: stored as sent, the hand-off notice tells it
            return h.store_ref(key)
        ptr = _sibling_pointer(key, verb) if sib else ""
        if _anc.front_only(project) and _bl.front_of(roles[key], project):      # no builder: the peer's part is a hand-over (mover=) or its own item
            raise ToolError(f"Refused: {key} is a front agent of {roles[key]['project']}, and needs names a background agent or this project's keeper" + (f" ({keeper})" if keeper else f", which {hub or 'the project'} lacks") + ". "
                            f"To hand {key} the item set mover={key} (it is told); for its part of a plan open its own item and link it with after=[{key}'s item]." + (f" {ptr[:1].upper()}{ptr[1:]}." if ptr else ""))
        raise ToolError(f"Refused: {key} is a user-facing agent of {roles[key]['project']}, and needs names a background agent "
                        f"of any project, or this project's keeper; a user-facing agent's part is its own item, linked with after=[{key}'s item]. "
                        f"For {hub}: {', '.join(x for x in dict.fromkeys([stew, *back]) if x) or 'no background agent named'}" + (f"; {ptr}" if ptr else ""))
    if key and roles[key].get("retired"):           # the name-line session of a page that lists user-facing agents: its pane is gone, nothing may be sent to it
        raise ToolError(f"Refused: {key} is the retired name-line session of {roles[key]['project']} (its notices go to the project's keeper), and needs names a session that can act. "
                        f"For {hub}: {', '.join(x for x in dict.fromkeys([keeper, *back]) if x) or 'no background agent named'}")
    if key:
        return h.store_ref(key)
    if keeper and same(keeper):
        return h.store_ref(keeper)
    choices = ", ".join(x for x in dict.fromkeys([stew, keeper, *back]) if x) or "none named"
    raise ToolError(f"Refused: {name} is not a background agent of any project, nor this project's keeper; needs names one of "
                    f"those (for {hub}: {choices}), decision, or external")


def gate_needs(needs: Any, project: str, owner: str, also: str = "") -> list[str]:
    """needs as given (a list, or a string with commas) → the list stored, in its canonical order. Refuses a word that is neither
    a kind from [metadata.needs] enum nor an allowed session."""
    if isinstance(needs, str):
        needs = [x for x in re.split(r"[,\n]", needs) if x.strip()]
    if not isinstance(needs, list):
        raise ToolError("Refused: needs is a list of decision, external and session names (or one comma-separated string)")
    kinds = [str(x).lower() for x in (((_cfg.CFG.get("metadata") or {}).get("needs") or {}).get("enum") or _NEEDS_KINDS)]
    out = []
    for x in needs:
        x = str(x).strip()
        if not x:
            continue
        if x.lower() in kinds:
            out.append(x.lower())
        elif x.lower() in _NEEDS_KINDS:
            raise ToolError(f"Refused: needs {x!r} is not allowed here; the kinds are {kinds}")
        else:
            out.append(gate_needs_session(x, project, owner, also))
    return _canon_needs(out, _anc.names())


def gate_observers(observers: Any) -> list[str]:
    """observers as given (a list, or a comma-separated string) → the names stored: sessions the fleet, a page or a cloud id names."""
    h = _hooks()
    if isinstance(observers, str):
        observers = [x for x in re.split(r"[,\n]", observers) if x.strip()]
    if not isinstance(observers, list):
        raise ToolError("Refused: observers is a list of session names (or one comma-separated string)")
    nm = _anc.names(); roles = _anc.session_roles(); out = []
    for x in observers:
        x = str(x).strip()
        if not x:
            continue
        me = _anc.canonical(x, nm)
        known = _anc.is_id(x) or x in roles or nm.get(me, "") or any(n == x for n in nm.values())
        if not known:
            raise ToolError(f"Refused: observer {x!r} names no session: a pane's name, a transcript id, a cse_… id, or a session a project page lists")
        name = h.store_ref(nm.get(me, "") or x)
        if name not in out:
            out.append(name)
    return out


def gate_tell_him(names: Any, said_l: list[dict[str, Any]]) -> list[str]:
    """tell_him: the front agents he asked to tell him about an item → the names stored, when this very write carries his own words (a checked Acked-by said entry, never a kind acted one); refused otherwise.
    Only his request starts a front agent's turn while he is away (service/front_turn.py), so a session cannot record it for him."""
    if not any(e.get("checked") and e.get("tag") == "Acked-by" and e.get("kind") != _said.ACTED for e in said_l or []):
        raise ToolError(f"Refused: tell_him records that {OWNER} asked a front agent to tell him about this item, so the write carries his own words: said=[{{tag: Acked-by, quote: his sentence verbatim, msg: the uuid of his message}}], "
                        "checked against the transcript (an unchecked one is not enough). Without it nothing is recorded; tell_him=\"none\" takes an ask back without it.")
    return gate_observers(names)


def gate_work_writer(gid: str, writer: str, owner: str, meta: dict[str, Any], finishing: bool = False) -> None:
    """a step's status (work) is written by the item's mover (`owner` here) or a session named in its needs; anyone else is refused with the way in.
    A name or an id on either side; the needs list is read as the call leaves it. `finishing`: the writer finishes its own step
    (_finishes_own_line), which needs no naming in needs, so it passes without it."""
    h = _hooks()
    nm = _anc.names()
    me = _anc.canonical(writer, nm)
    same = lambda x: bool(x) and (x == writer or _anc.canonical(x, nm) == me)
    if finishing or same(owner) or any(same(s) for s in _needs_sessions(meta)):
        return
    named = ", ".join(h.shown_ref(x) for x in _needs_sessions(meta)) or "none named"
    raise ToolError(f"Refused: the status of a step on {_gh.shown(gid)} is written by its mover ({_session_label(owner) or 'none'}) or a session named in its needs ({named}); "
                    f"{writer} is neither. Have its mover name you in needs (needs=[…, {writer!r}]), or pass the step to it.")


def gate_draft_args(draft: Any, clear: bool) -> tuple[str, bool]:
    """create/update(draft=..., clear_draft=...): the draft text as it is to be stored, and whether the write clears it → (text, clear). The text is kept as written (many lines, any language;
    only its line breaks are made \\n and its blank lines before and after dropped); at most draft.MAX characters. draft="none" (or clear, or -) clears like clear_draft=true; "" is the default,
    not passed. A clear does not go with a new text."""
    if draft is not None and not isinstance(draft, str):
        raise ToolError(f"Refused: draft is a string, the text exactly as {OWNER} is to paste it")
    raw = draft or ""
    if _draft.is_clear(raw):
        clear, raw = True, ""
    text = _draft.normalize(raw)
    faults: list[str] = []
    if clear and text.strip():
        faults.append("Refused: clear_draft drops the draft; it does not go with a new one")
    if len(text) > _draft.MAX:
        faults.append(f"Refused: draft is at most {_draft.MAX} characters (got {len(text)}); a longer text goes in a document, and the step links it")
    if faults:
        raise _faults.refusals(faults)
    return (text if text.strip() else ""), bool(clear)


def gate_draft(item: dict[str, Any], gid: str = "") -> None:
    """The draft guard (draft.py): an item this write leaves in state your-step with the owner as the mover, whose step names text to post, send or paste, carries the text as a draft or
    links the document that holds it. Refused with one line naming the draft field and the link alternative. The caller runs it only for a write that sets the step, the state, the mover
    or the draft, so an unrelated write to an old item is never held up by it. [model] guards = false skips it, as it does the other write guards."""
    h = _hooks()
    if not h.model_guards_on() or item.get("status") != "open":
        return
    why = _draft.problem(item)
    if why:
        raise ToolError(f"Refused: {_gh.shown(gid) + ': ' if gid else ''}{why}.")


def gate_step(item: dict[str, Any], gid: str = "", prior_description: Any = None, step_set: bool = False) -> None:
    """The step guards (step_commands.py): an item this write leaves his to move (the owner is its mover, it is in your-step or your-call, or its needs hold his decision) has no numbered step and no `! ` line in its description, the
    Background; an item in state your-step with the owner as the mover carries every shell command he runs in a "<owner>:" line of next, not in its description or its step (the step is a one-line summary):
    a step a write sets (`step_set`) that carries a command is refused, and a step stored with one before keeps the old judgement (the command says where it runs, bash for the host has the ssh form) on a write that leaves it alone; the step does not point
    elsewhere ("see the description"). Refused with one line naming the field and the fix. The caller runs it only for a write that sets the state, step, mover, description or draft. A write that sets the description
    (`prior_description`, the one it replaces) is judged only on the commands it adds or changes. [model] guards = false skips it."""
    h = _hooks()
    if not h.model_guards_on() or item.get("status") != "open":
        return
    why = _sc.problem(item, prior_description, step_set)
    if why:
        raise ToolError(f"Refused: {_gh.shown(gid) + ': ' if gid else ''}{why}.")


def gate_state_args(carry: dict[str, str], split_note: str = "") -> tuple[str, dict[str, str], bool]:
    """update(step=...) and update(supplies=...): the two fields that still go with a stored state, as the call passes them (whitespace collapsed; a step is checked for its form) → (the state they
    set, the fields passed, whether the step is withdrawn). A step is the your-step state's and supplies the blocked state's, which no call names any more: passing the field sets the state it stood on, "" when the call passes neither.
    step="none" (or clear, -, like needs="none") withdraws the step: the your-step state and his open step line go in that write (the only way out of his step besides his Done, a close or a hold).
    `split_note` (the update's own: why a long step was not split into lines, step_split.skipped) goes beside the refusal of a step that is too long.
    The other inputs of the old states (state, clear_state, party, chase, end, proof, chase_note) are refused before the tool runs (retired_inputs.py, web/middleware.py _RetiredInputs)."""
    h = _hooks()
    faults: list[str] = []
    withdraw = str(carry.get("step") or "").strip().lower() in h.ask_none and bool(str(carry.get("step") or "").strip())
    if withdraw:
        if str(carry.get("supplies") or "").strip():
            faults.append('Refused: step="none" withdraws the step and supplies sets a wait on another item: pass one of them')
        carry = {**carry, "step": ""}
    given = {k: _states.carry_text(k, v) for k, v in carry.items() if k not in _states.RETIRED_FIELDS and _states.carry_text(k, v)}      # expected_by and expected_reason are accepted and not kept (RETIRED_NOTE, in service/update.py)
    for k, v in given.items():
        if k == "step":
            if _states.step_problem(v):
                faults.append(f"Refused: {_states.step_problem(v)}" + (f" (the server did not split it into lines of next: {split_note})" if split_note else ""))
        elif len(v) > _states.LINE_MAX:
            faults.append(f"Refused: {k} is one line of at most {_states.LINE_MAX} characters — got {len(v)}")
    if "step" in given and "supplies" in given:
        faults.append("Refused: step is a step for the person it names and supplies says what another item gives this one (a wait on that item): pass one of them")
    if faults:
        raise _faults.refusals(faults)
    return ("your-step" if "step" in given else "blocked" if "supplies" in given else ""), given, withdraw


_NOT_PASSED = ("until", "waits", "wait_mode", "until_server")      # in the wait group, but not arguments of this call


def gate_model_args(vals: dict[str, str], clears: dict[str, bool], stored: dict[str, Any] | None = None) -> tuple[dict[str, str], set[str]]:
    """The model fields a write passes (model.py): goal, mover, then, wait_kind, wait_anchor, wait_event, ask_by → (the fields to set, whitespace
    collapsed and the owner's name and wait_kind normalised, the fields to drop). A value of none, clear or - drops that field; clear_goal, clear_mover, clear_then drop theirs
    and clear_wait the wait's four (wait_kind, wait_anchor, wait_event, ask_by; the wake and after keep their own flags). A clear does not go with a new value
    for what it drops.     Only the form is judged here (model.check_fields): whether an alive item names a mover or a wait its mover is for the write guards.
    `stored`: the item's metadata as it stands (an update's): the refusal of clear_wait beside a new wait_kind names the stored wait_anchor and wait_event the call to send would keep."""
    h = _hooks()
    faults: list[str] = []
    setv: dict[str, str] = {}
    drop: set[str] = set()
    for k in _model.MODEL_FIELDS:
        v = _model.clean(vals.get(k))
        if v.lower() in h.ask_none:
            drop.add(k)
        elif v:
            setv[k] = v
    for flag, fields in (("goal", ("goal",)), ("mover", ("mover",)), ("then", ("then",)), ("wait", _model.WAIT_GROUP)):
        if clears.get(flag):
            clash = [k for k in fields if k in setv]
            if clash:
                instead = ""
                if "wait_kind" in clash:      # only the kind takes a new value's place: a stored anchor and event stay beside it, so the call to send names them
                    stays = [k for k in ("wait_anchor", "wait_event") if _model.clean((stored or {}).get(k)) and k not in setv and k not in drop]
                    instead = ". The new wait_kind takes the place of the stored kind: send this call again without clear_wait"
                    if stays:
                        instead += (f", and for {' and '.join(stays)}, which the item stores and would keep beside the new kind, send the new wait's own value or "
                                    + " and ".join(f'{k}="none"' for k in stays) + " to drop " + ("them" if len(stays) > 1 else "it"))
                faults.append(f"Refused: clear_{flag} drops {', '.join(k for k in fields if k not in _NOT_PASSED)}; it does not go with a new {', '.join(clash)}{instead}")      # `until`, `waits` and `wait_mode` are no write field of this call: the refusal names the five a caller can pass
            else:
                drop.update(fields)
    if "wait_kind" in setv:
        setv["wait_kind"] = setv["wait_kind"].lower()
    for k in ("mover", "then"):
        if k in setv:
            setv[k] = _sr.named(_model.norm_who(setv[k]))      # a short session id (`sala sessions`) is stored as the session's name: a mover that is an id would not be told from its name
    probs = _model.check_fields(setv)
    if probs:
        faults.append("Refused: " + "; ".join(probs))
    if faults:
        raise _faults.refusals(faults)
    return setv, drop


@dataclass
class WaitsPlan:
    """What the `waits` argument of a write comes to (`gate_waits`): kind `list` (2 to 8 lines, stored as a list), `one` (a list that is left with one line: stored as the single wait that line is), or `clear` (the
    list is cleared, or the one line left has arrived: the wait ends as clear_wait ends it); `lines` are the lines to store (item ids as stored, an arrival carried from the stored list), `mode` all or any,
    `note` the reply's lines."""
    kind: str
    lines: list[dict[str, Any]]
    mode: str = ""
    note: str = ""


def waits_clash(names: list[str]) -> ToolError:
    """The refusal of a list passed beside single-wait parameters (one way to say a wait): the names passed, and what to do instead."""
    return ToolError(f"Refused: waits is a wait on a list and does not go with {', '.join(names)}: put each thing waited on in a line of waits and the backstop day in until ({_wlw.FORM}); "
                     "clear_wait=true ends a wait on its own")


def _line_refusal(i: int, e: ToolError) -> ToolError:
    return ToolError(f"Refused: waits[{i}]: " + str(e).removeprefix("Refused: "))


def _no_repeat(lines: list[dict[str, Any]], held: "Counter[tuple[str, ...]]") -> None:
    """Refuse a wait given twice in one list, naming both lines; a line the stored list holds that many times is not a repeat when the list is sent again."""
    dup = _wlw.duplicate(lines, held)
    if dup:
        raise ToolError(f"Refused: waits[{dup[1]}] repeats waits[{dup[0]}] (the same {lines[dup[1] - 1]['kind']} line twice); give each wait once")


def gate_time_lines(dated: list[tuple[int, str]], backstop: str) -> None:
    """Refuse a time line (its 1-based position in the list, its date) that falls later than the backstop day: it could never arrive before the item comes back."""
    for i, until in dated:
        if _wlw.time_before(backstop, until):
            raise ToolError(f"Refused: waits[{i}] is a date ({until}) later than the backstop day {backstop}, so it could never arrive before the item comes back: give an earlier date or a later until")


def gate_waits(waits: Any, wait_mode: Any, *, gid: str, project: str, creating: bool, stored: dict[str, Any], backstop: str, others: dict[str, Any],
               anchor_gate: Callable[[dict[str, Any]], Any], event_gate: Callable[[dict[str, Any]], str]) -> "WaitsPlan | None":
    """The `waits` and `wait_mode` arguments of a create or update (a wait on a list of waits: waits/wait_list_write.py) → what they come to, or None when the call passes neither (or clears a list that is not
    there). Everything the single waits are judged by is reused, line by line, on the lines that are new or changed (a line the stored list already holds is not judged again, and keeps what has arrived):
    the item of an item line by `gate_after`, the anchor of an anchor line and the event of an event line by the gates of the single waits (`anchor_gate`, `event_gate`: callables that take the metadata of that one
    wait), the date of a time line against now. Refused, naming the line (waits[2]) and the way out: a list passed beside single-wait parameters (`others`: name → value), a line that is no line (kind, fields,
    an anchor or an item id over 300 characters, an `arrived`), a repeated line, fewer than 2 or more than 8 lines (one line is allowed only as what an edit leaves of a stored list), a list with no backstop day
    (`backstop`: the day the call or the item gives), a time line later than the backstop day, a wait_mode that is not all or any. `stored` = the item's metadata as it stands (empty for a create)."""
    h = _hooks()
    mode_given = bool(_model.clean(wait_mode)) and _model.clean(wait_mode).lower() not in h.ask_none
    if not _wlw.passed(waits):
        if mode_given:
            raise ToolError("Refused: wait_mode is the mode of a list and goes with waits; to change the mode of a list the item stores, send its lines again with the new wait_mode (what has arrived is kept)")
        return None
    clash = [k for k, v in others.items() if v]
    if clash:
        raise waits_clash(clash)
    try:
        lines = _wlw.parse(waits)
    except ValueError as e:
        raise ToolError(f"Refused: {e}")
    holds = _wl.valid(stored)
    if not lines:
        if mode_given:
            raise ToolError("Refused: wait_mode does not go with a clear of the list (waits=[])")
        return WaitsPlan("clear", []) if holds else None
    try:
        mode = _wlw.mode_of(wait_mode, stored)
    except ValueError as e:
        raise ToolError(f"Refused: {e}")
    for ln in lines:
        if ln["kind"] == "event":      # an event phrase in its canonical form first (`Recycle`, `FLEET_OP   any`), so the stored line it names is found, keeps its arrival and is not judged again; one that is no event is left for the gate below to refuse
            try:
                ln["event"] = _ew.text(_watching.event_spec(ln["event"]))
            except _ew.EventWaitError:
                pass
    held = Counter(_wl.line_key(ln) for ln in _wl.lines(stored))
    have = set(held)
    for i, ln in enumerate(lines, 1):
        if ln["kind"] == "item":
            try:
                nid = _norm_id(str(ln["after"]))
            except Exception:  # noqa: BLE001  — an id that no form reads is refused below, by gate_after, with its own words
                nid = ""
            if nid and ("item", nid) in have:
                ln["after"] = nid        # a line the stored list holds already: kept as it is (its item may have closed since, which the watchers end the line for)
            else:
                try:
                    ln["after"] = gate_after([ln["after"]], gid, i)[0]
                except ToolError as e:
                    raise _line_refusal(i, e)
        elif ln["kind"] == "time":
            try:
                ln["until"] = str(h.parse_wake(ln["until"]))
            except ToolError:
                raise ToolError(f"Refused: waits[{i}]: a time line's until is YYYY-MM-DD or YYYY-MM-DDTHH:MM ({_cfg.tz_abbr()}), a real date (got {ln['until']!r})")
            if _wl.line_key(ln) not in have and h.wake_at(ln["until"]) <= _pages.zone_now():
                raise ToolError(f"Refused: waits[{i}]: a time line's until must be in the future ({_cfg.tz_abbr()})")
    _no_repeat(lines, held)
    lines = _wlw.carry_arrived(lines, stored)
    kind, why = _wlw.shape(lines, holds)
    if not kind:
        raise ToolError(f"Refused: {why}")
    if kind == "none":
        return WaitsPlan("clear", [], note="\n(the one line left had already arrived, so the wait is over and is cleared)")
    if kind == "list":
        if not backstop and not _faults.current().marked(_faults.UNTIL):
            raise ToolError("Refused: a list needs its backstop day, the day the item comes back at the latest whatever has arrived: pass until=YYYY-MM-DD (or YYYY-MM-DDTHH:MM) beside waits")
        gate_time_lines([(i, ln["until"]) for i, ln in enumerate(lines, 1) if ln["kind"] == "time"], backstop)      # a backstop day the call gave but the gate refused is "" here, which holds no time line (time_before is False for no date)
    note = ""
    for i, ln in enumerate(lines, 1):
        if ln.get("arrived") or _wl.line_key(ln) in have:
            continue
        try:
            if ln["kind"] == "anchor":
                anchor_gate({"wait_kind": "anchor", "wait_anchor": ln["anchor"], "wait_event": ln["event"], "project": project})
            elif ln["kind"] == "event":
                tmp = {"wait_kind": "event", "wait_event": ln["event"], "wake": backstop}
                note += event_gate(tmp)
                ln["event"] = _model.clean(tmp.get("wait_event")) or ln["event"]
        except ToolError as e:
            raise _line_refusal(i, e)
    _no_repeat(lines, held)      # …and again now that an event line is in its canonical form (`Recycle` and `recycle` are one wait)
    return WaitsPlan(kind, lines, mode, note)


def gate_ask_on_wait(gid: str, item: dict[str, Any], meta: dict[str, Any], was_needs: list[str], closing: bool) -> None:
    """An update that asks the owner for a decision (needs gains decision) on an item that stores a wait (wait_kind) leaves a wait and an ask side by side, and the wait
    wins in the model (get lists it as a model conflict). It is refused with one line saying how to resolve it, instead of being left for get to show: clear_wait=true in the same update drops
    the wait; a wait kept means the owner is not asked. The wait is read after the write's own wait fields (_model_apply), so a clear_wait passed here has dropped it already. [model] guards = false skips it."""
    h = _hooks()
    if closing or item.get("status") != "open" or not h.model_guards_on():
        return
    kind = str(meta.get("wait_kind") or "").strip().lower()
    if kind not in _model.WAIT_KINDS:
        return
    asks = _waits_decision(meta) and not _waits_decision({"needs": was_needs})
    if not asks:
        return
    on = {"anchor": "an anchor event", "item": "another item's close", "relay": f"news only {OWNER} relays", "time": "a time", "event": "a fleet event", "list": "several things"}[kind]
    detail = str(meta.get("wait_event") or meta.get("wait_anchor") or "").strip()
    raise ToolError(f"Refused: {_gh.shown(gid)} still waits on {on}" + (f" ({detail})" if detail else "") + f"; pass clear_wait=true with this update to drop the wait and ask {OWNER}, "
                    f"or keep the wait and do not ask {OWNER}.")


def _description_guard_mode() -> str:
    """[model] description_guard (default note): what a thick description (model_guards.description_problem) gets. note: the write goes through and the reply carries the
    guidance; refuse: the write is refused with it (the release after this one). Anything else reads as note."""
    return "refuse" if str(_cfg.get("model", "description_guard", default="note") or "note").strip().lower() == "refuse" else "note"


def _option_labels(opts: list[Any]) -> list[str]:
    return [" ".join(str((o.get("label") if isinstance(o, dict) else o) or "").split()) for o in opts]


def his_step(text: Any) -> bool:
    """Is a step line the owner's: it opens with his name or an alias (steps.is_his, a line that names nobody is no one's), or with `you:` or "<owner> to …" (states.next_names_owner)?"""
    return _steps.is_his(text, unnamed_is_his=False) or bool(_states.next_names_owner(text))


def owner_waiting(meta: Any) -> bool:
    """Does the item wait on the owner, in any form: decision in needs, a stored ask, options no decision answer of his has settled (his pick takes them off the item; an answer in his own
    words keeps the options he was shown on its record, and settles them only while the item's options are still those: a comment, or an answer to another set, is no answer), a stored
    your-call or your-step, a mover or waiting picker that is a member, a member named in needs, or an open step line of his (his_step). The one test every default of the server reads (a
    close's outcome, a wait's end day), on the item as it stood and as the write leaves it: while it holds, none applies and the call is judged as before those defaults existed. An item
    that cannot be read counts as waiting on him."""
    m = meta if isinstance(meta, dict) else {}
    try:
        if _waits_decision(m) or _model.clean(m.get("state")).lower() in _model.OWNER_STATES or _model.clean(m.get("ask")):
            return True
        if any(_model.is_owner(x) for x in (m.get("mover"), *_needs_list(m.get("needs"))) if _model.clean(x)):
            return True
        opts = m.get("options")
        if isinstance(opts, list) and opts:
            shown = _option_labels(opts)
            if not any(isinstance(a, dict) and a.get("kind") == "decision" and isinstance(a.get("options"), list) and _option_labels(a["options"]) == shown
                       for a in (m.get("answers") if isinstance(m.get("answers"), list) else [])):
                return True
        return any(s["status"] == _steps.OPEN and his_step(s["text"]) for s in _steps.view(m))
    except Exception as e:  # noqa: BLE001  — a reading that fails leaves every default off
        print(f"owner wait: not read: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return True


def holds_end(meta: Any) -> bool:
    """Does the item hold an end in any field (until, the working fields wake and ask_by, the old ask_by with no wait_kind included, and the date fields older writes left, states.DATE_FIELDS):
    any value there, a date past or ahead or one that is no date. While it does, the server makes no default end: it never replaces or pushes out an end the item holds (update.py reads
    it on the item as it stood, _wait_end_fill on the item as the write leaves it)."""
    m = meta if isinstance(meta, dict) else {}
    return any(_model.clean(m.get(k)) for k in ("until", "wake", "ask_by", *_states.DATE_FIELDS))


def _default_wait_end(item: dict[str, Any], gid: str, creating: bool, before: dict[str, Any] | None = None) -> str:
    """Called only where the write would be refused for a wait with no end (the model guards' no_end, or a time wait with no date; update.py's park with nothing to end it): a wait on
    another item's close, an anchor, a relay or an event with no end, or a time wait with no date. Store the default backstop day (model/migration.DEFAULT_END_DAYS from today) as its
    end, mark it as the server's (model.SERVER_END_KEY), and tell the caller (fix kind wait-end-defaulted). The day is stored as `until` (the one date a wait stores) for a time wait and for a
    create; an update's other kinds carry it in their working field (until_write.slot_of) until update.py folds it. An end the item holds in any field (holds_end: a date past or
    ahead, the old ask_by with no wait_kind included, or a value that is no date) is never replaced: the write is judged as before. The caller's own date, a call that clears or drops
    a wait or its end, and an item that held an end before the write never reach here (gate_model's end_default, update.py's end_ok). Never while the item waits on the owner
    (owner_waiting), as the write leaves it or as it stood before (`before`: an update's metadata before the write). A failure here leaves the item as the write made it, and the guards
    judge it so. → the line told ("" when no day was stored)."""
    meta = item.get("metadata")
    if not isinstance(meta, dict) or owner_waiting(meta) or (before is not None and owner_waiting(before)):
        return ""
    kept = dict(meta)
    try:
        return _wait_end_fill(item, meta, gid, creating)
    except Exception as e:  # noqa: BLE001  — the default is an extra: on a failure the item is left as the write made it, and the guards refuse a wait with no end as they did before it
        meta.clear(); meta.update(kept)
        print(f"wait end: {gid or 'a new item'} not defaulted: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return ""


def _wait_end_fill(item: dict[str, Any], meta: dict[str, Any], gid: str, creating: bool) -> str:
    """_default_wait_end's work on the item's metadata, once its checks have passed."""
    h = _hooks()
    project = str(meta.get("project") or "")
    try:
        w = _model.derive(item, time.time(), lambda i_: h.after_open(i_.get("metadata") or {}), lambda i_: bool(gid and h.scoped_anchors(project, gid))).wait
    except Exception:  # noqa: BLE001
        return ""
    synthetic = False
    if w is None and meta.get("hold") and not (_wt.wake_value(meta) or _wt.stored_until(meta)):
        w = _model.Wait(kind="time", kind_explicit=False); synthetic = True                     # a hold with no date stands as a park whatever state the item still stores: a wait on a time with none
    if w is None or w.kind not in ("time", "anchor", "item", "relay", "event"):
        return ""
    if w.kind == "time" and meta.get("recycle"):
        return ""
    if w.until or (w.backstop if w.kind != "time" else "") or holds_end(meta):
        return ""                                        # the item holds an end in some field (a date, past or ahead, or a value that is none): the server never replaces it, and the write is judged as before
    anchor_hold = w.kind == "time" and bool(meta.get("hold")) and not creating and bool(gid and h.scoped_anchors(project, gid))      # a hold with no date on an item an anchor is scoped to waits on that anchor's notice (wakes.anchor_release reads the hold flag): it stays a hold, the day beside it its backstop, never a plain time wait the notice could no longer wake
    slot = "until" if (creating or w.kind == "time") else _uw.slot_of(w.kind)
    day = (_pages.zone_now().date() + dt.timedelta(days=_mig.DEFAULT_END_DAYS)).isoformat()      # one rule for every kind: the expected time an awaited item once carried is retired (states.RETIRED_FIELDS), so it is not read
    meta[slot] = day      # the field this kind reads (slot_of): an update judges the old working fields (update.py folds this one into `until` before it saves); a time wait's until stands on its own
    if not _uw.kind_of(meta) and not synthetic and not anchor_hold and not (w.kind == "anchor" and not meta.get("wait_anchor") and not meta.get("hold")):
        meta["wait_kind"] = w.kind                       # a date with no kind would read as a wait on a time: the wait keeps the kind the item's fields gave it. Not a bare hold (synthetic: it stays a park on the day), nor an anchor wait read from a scoped anchor alone on an item that holds no flag: stamped, it would wait for a notice on a wait_anchor it does not have, and the anchor's notice (which releases a hold or a date with no kind) would pass it by; a held one keeps the stamp, as its release reads the flag
    meta[_model.SERVER_END_KEY] = day
    if w.kind == "time" and not anchor_hold:
        for k_ in ("hold", "hold_set", "wake"):
            meta.pop(k_, None)                           # the day is the wait's one date, stored as until: no hold flag or working wake beside it
    why = f"{_mig.DEFAULT_END_DAYS} days from today"
    if anchor_hold:
        why += "; the hold stays, so the notice of the anchor scoped to the item still releases it first"
    line = (f"the wait had no {'date' if w.kind == 'time' else 'end'}, so the server stored {day} as its end ({why}); it is a backstop day set by the server, not a promise: the day it comes back to someone when nothing has arrived. "
            f"Its mover replaces it with the real day (until=YYYY-MM-DD); a day you give yourself for an item or anchor wait is capped at {_wt.cap_days():g} days from the item's last move "
            "(a later one needs the owner's word), so sending this day back as your own can be refused")
    _calls.fixed("wait-end-defaulted", line)
    return line


def gate_model(item: dict[str, Any], touched: "frozenset[str] | set[str] | None", gid: str = "", needs: list[str] | None = None, hold: bool | None = None, desc_set: bool = True, strict: bool = False, next_text: str | None = None, windows_text: str | None = None, creating: bool = False, defers_text: str | None = None, until_wait: bool = False, date_given: bool = False, hold_given: bool = False, basis_kept: bool = False, old_end_ok: bool = False, date_ends: bool = False, before: dict[str, Any] | None = None, end_default: bool = True) -> str:
    """The item model's write guards (model_guards.py) on the item as a create or update leaves it: refuse, with what is wrong and the fix, a write that
    leaves an alive item with no valid mover, a wait without its input, post-wake mover, reason or end, a second mover in needs, a decision with a hold, a placeholder, a next line with
    no name or one that reads as a wait, or an alarming word. `touched` = the fields the write sets (None: a create or a reopen, every field is judged): a guard on a field runs
    when the write sets it, the state invariants when it sets a field that defines the state or the wait, so an old item's other fields never block an unrelated write. A close is never judged
    (the caller passes open items). [model] guards = false skips all of it.
    A failure of the check itself writes as before, with a stderr line. → the notes for the reply ("" when none): a thick description in [model] description_guard = note mode
    (the write goes through; the guidance rides on the reply), refused with the rest in refuse mode. `desc_set` = the write sets the description: a
    reopen judges every field (touched None) but the description only when it sets one, so an old thick text never refuses a reopen that did not write it.
    With `strict` (the migration pass) a failure of the check itself refuses instead: a write nothing could judge is not made.
    `next_text`: the lines of next this write set (the sender's own), when other sessions' lines stand beside them: the text guards on next judge these only.
    `windows_text`: the lines of next the shell-place guard on his lines judges: an update passes the lines it sets, or "" when it leaves next alone (a whole-item judgement, the switchover's or a reopen's, never rejudges a stored line); None (a create) judges all of next.
    `defers_text`: the same for the next_defers guard (a line that defers on another open item in words while `after` does not name it): the lines the write sets, "" when it leaves next alone, None on a create.
    `old_end_ok`, `date_ends`: what an ask_by stored with no wait_kind counts for (model_guards.check).
    `before`: an update's metadata as the item stood before the write, for the default end's test of a wait on the owner (_default_wait_end). `end_default` = False: the call gave a date of its
    own or "none" for one, cleared or dropped a wait or its end, or the item held an end or waited on the owner before it, so a wait it leaves with no end is refused as before and no
    default end is made."""
    h = _hooks()
    if not h.model_guards_on() or item.get("status") != "open":
        return ""
    meta = item.get("metadata") or {}
    project = str(meta.get("project") or "")
    def _run() -> "list[Any]":
        return _mg.check(item, _mg.Ctx(label=_session_label, shown=_gh.shown), touched=touched, gid=gid,
                         after_open=lambda i_: h.after_open(i_.get("metadata") or {}),
                         anchored=lambda i_: bool(gid and h.scoped_anchors(project, gid)),
                         needs=needs, hold=hold, one_mover=bool(_cfg.get("model", "one_mover", default=True)), next_text=next_text, windows_text=windows_text, creating=creating,
                         defers_text=defers_text, named_open=h.open_item_named, canon=_gh.resolve, until_wait=until_wait, date_given=date_given, hold_given=hold_given, basis_kept=basis_kept, old_end_ok=old_end_ok, date_ends=date_ends)[0]
    try:
        probs = _run()
        if not strict and end_default and any(p.key in ("no_end", "wait_input") for p in probs) and _default_wait_end(item, gid, creating, before):      # where the check would refuse a wait with no end (a time wait: no date), the default backstop day is stored (the line goes to the reply through call_log.fixed) and the item is judged again with it; a wait whose input is missing for another reason stays refused for that
            probs = _run()
    except Exception as e:  # noqa: BLE001  — the guard is an extra: a failure in it writes as before
        print(f"model guards: {gid or 'a new item'} not judged: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        if strict:
            raise ToolError(f"Refused: the guards could not judge this write ({e.__class__.__name__}); the migration makes none that they have not judged")
        return ""
    if not desc_set:
        probs = [p for p in probs if p.key != "description"]
    if _writes.question():
        probs = [p for p in probs if p.key not in ("alarm", "description", "next_defers")]
    if _writes.terminal_row():
        probs = [p for p in probs if p.key != "next_defers"]      # a script's own row is never stranded on the words of its line
    if _writes.reformat() or _writes.terminal_row():
        probs = [p for p in probs if p.key != "owner_mover"]      # a re-bullet writes no mover and no state: an item already in the owner-as-mover shape is not refused for the form of its description; the terminal-prompt route creates its row with the owner as mover and sets state your-step with its step in the write that follows (a create sets no state), and that second write is judged
    notes = [p for p in probs if p.key == "description"] if _description_guard_mode() == "note" else []
    probs = [p for p in probs if p not in notes]
    if any(f.startswith("Refused: a line of next names no one") for f in _faults.current().found):
        probs = [p for p in probs if p.key != "next_unnamed" and not (p.key == "filler" and p.field == "next")]      # the same unnamed line, already refused by next's own rule (N1): the guard does not say it a second time, nor that the line is a placeholder (a placeholder names no one)
    if _faults.current().marked(_faults.EVENT):
        probs = [p for p in probs if p.key != "wait_input" and not (p.key == "filler" and p.field == "wait_event")]        # an event wait whose phrase the wait's own gate refused: its input is missing, and the phrase is no event, for that reason alone, which that fault already says
    if any(p.key == "next_unnamed" for p in probs):
        _faults.current().mark(_faults.NEXT)                       # the check that an open step is left reads the same line, which the guard refuses here
    if any(p.key in ("mover", "post_wake", "mover_state") for p in probs):
        _faults.current().mark(_faults.MOVER)                      # the hand-off and front-agent-step checks read the same mover (the item's, or the one a wait hands it to): they keep no fault of their own beside this one
    if probs:
        raise _faults.refusals(["Refused: " + p.text for p in probs], _mg.refusal(probs))
    if touched is None or "next" in touched:
        meta.pop("model_flags", None)      # an older write stored the broad-words flag here; those words are read from next itself now (_ac.wait_words), so a write drops the stored copy
    return "".join(f"\n(note: {p.text})" for p in notes)


# The server's state checks. They note, and refuse only where the design says so:
#   3  next opens with the owner while the state (stored or derived) is an agent's: a note in get and on the write's reply
#   4  a third re-park in a row (a move of a parked or verifying item's wake or end with nothing else changed) is refused; a verifying item's end date is its wait (the watchers end the wait that day)
#   5  next may be stale: another session changed needs, state, hold, wake or after and not next (metadata.next_stale), or next names a date that has passed
#   6  needs decision put back within an hour of the owner's last answer on the item with the ask line unchanged is refused; a question of his is no answer once the description has answered it
#   7  (gone: an owner's item with no stored state was once told what storing it took; no call stores a state now)
_REPARK_FIELDS = ("needs", "after", "state", "mover", "then", "wait_kind", "wait_anchor", "wait_event", "ask_by", "waits", "wait_mode")     # the structured fields a re-park may not change (status and hold beside them)


def _list_shape(v: Any) -> Any:
    """A list's lines as a comparable value: the lines without the server's record of what arrived, in no particular order (a line arriving or a reorder is no new shape; a line added, removed or changed is)."""
    if not isinstance(v, list):
        return v
    return sorted(json.dumps({k: x for k, x in w.items() if k != "arrived"}, sort_keys=True, default=str) if isinstance(w, dict) else str(w) for w in v)


_REPARK_QUIET = (_sf.MARK, _sf.DECLINED, "wake", "end", "hold", "hold_set", "cap_ok", "said", "idle", "waiting", "wait_failed", "undelivered", "repark", "next_stale", "refiled", "recycle", "recycle_at", "stall", "front_quiet", "hourly_audit", "stuck_since", "stuck_moved", "stuck_landed")     # [model] guards = false: today's test


_DECISION_AGAIN_S = 3600.0        # a decision is not asked again within this long after the owner's last answer on the item unless the ask line changed


def _substance(item: dict[str, Any]) -> str:
    """What an item stands on apart from when it waits, by its structured fields only (design section 6: "the re-park test compares the structured fields only"): its
    status, hold, needs, after, state, mover and then, and the wait's kind, anchor, event, ask-by and post-wake mover. A write that leaves these as they were and only moves the wake
    or the end is a re-park, whatever it did to next, the description or any other text: an edit of those changes nothing, so it neither resets the count nor stands for a change.
    With [model] guards = false the test is today's: the subject, the description and every metadata field but the wait's own (_REPARK_QUIET), the basis text included."""
    h = _hooks()
    m = item.get("metadata") or {}
    if not h.model_guards_on():
        mq = {k: v for k, v in m.items() if k not in _REPARK_QUIET}
        if isinstance(mq.get("wait_basis"), dict):
            mq["wait_basis"] = " ".join(str(mq["wait_basis"].get("text") or "").split())
        return json.dumps({"s": item.get("subject"), "d": item.get("description"), "t": item.get("status"), "m": mq}, sort_keys=True, default=str)
    return json.dumps({"t": item.get("status"), "h": bool(m.get("hold")), **{k: (_list_shape(m.get(k)) if k == "waits" else m.get(k)) for k in _REPARK_FIELDS}}, sort_keys=True, default=str)


class HisStepRefusal(ToolError):
    """gate_owner_step's refusal of an update, with the line (`line`) that is his step, the id of the item it is about (`gid`, as the update normalized it) and the said entries the write stores (`said`, set by
    the update): service/step_settle.py reads them to settle that step when the write itself says what became of it."""
    line = ""
    gid = ""
    said: tuple[Any, ...] = ()


def gate_owner_step(item: dict[str, Any], gid: str = "", create: bool = False, sender: str = "", keeper: str = "") -> None:
    """The owner's step hidden under an agent's state: refuse a create or update whose resulting item (open) has a first line of `next` that opens with a who-takes-it
    opener for him (states.next_names_owner: `<owner>:`, `<alias>:`, `you:`, "the owner to …") while its state, stored or derived, is doing, queued, blocked or verifying. The caller runs it only for a
    write that touches next, the state, needs or the step, so a mover can fix an item step by step; any other write to an item already in that shape keeps the note (_state_check_notes). Writes nothing."""
    h = _hooks()
    if item.get("status") != "open":
        return
    m = item.get("metadata") or {}
    who = _states.next_names_owner(m.get("next"), OWNER)
    if not who:
        return
    s = h.eff_state(item)
    if s not in _states.AGENT_STATES:
        return
    first = next((ln.strip() for ln in str(m.get("next") or "").splitlines() if ln.strip()), "")
    head = f"Refused: the first line of next is {who}'s step ({first[:100]!r}) but the item's state is {s}, an agent's, so his step would sit hidden under it" + (f" ({_gh.shown(gid)})" if gid else "")
    tail = f" Nothing was written. The item model: {h.model_page}."
    if create:      # a create has no state or step parameter
        raise ToolError(head + ". Set needs=decision with an ask (a create stores no state or step), or open next with the agent who takes the step." + tail)
    writer = (_nl.writers_of(m, keeper) or [""])[0]
    if sender and writer and not _handoff.ho_same(writer, sender):      # the first line is another session's, kept at its place by nextlines.write: opening next with an agent cannot move it
        err = HisStepRefusal(head + f". That line was written by {writer}, not by this write's sender. Drop the step (dropped=[its number], or step='none'), or pass clear_next=true, or pass step=<his step in one line> if it is truly his step. Mark it done only when {who}'s own words for it are recorded on the item." + tail)
    else:
        err = HisStepRefusal(head + ". Pass step=<his step in one line>, or needs=decision with an ask; or open next with the agent who takes the step." + tail)
    err.line, err.gid = first, gid
    raise err


def gate_decision_again(item: dict[str, Any], meta: dict[str, Any], was_needs: list[str], ask_was: Any, gid: str, description: str | None = None) -> None:
    """One ask per decision: refuse a write that puts `decision` back into needs within an hour of the owner's last answer on the item
    (a board answer or a comment of his: metadata.answers), unless the ask line changes in the same write. A decision already in needs is not put back. With several members the answer that counts is
    the one of the member this write asks (member_gates.asked_member): another member's comment keeps no ask from being put.
    A record the server marked as a question (model/note_read.py) is no call of his. Answered on the item (the description as this write leaves it, `description`, is another one than he asked under), it
    does not count. Not answered, and newer than anything he decided or commented, it refuses the put-back in words that say to answer it there. A question that stores no ask (a comment) was asked about the
    one the item holds, else the latest ask an earlier record of his stores, answered question or not."""
    h = _hooks()
    was_on_call = any(str(x).lower() == "decision" for x in was_needs) or h.eff_state(item) == "your-call"      # already on his call before this write: nothing is put back
    back = not was_on_call and "decision" in _needs_kinds(meta)
    if not back:
        return
    asked = _mgates.asked_member(meta) if _mgates.many() else OWNER      # whom this write asks: only their answer is one to the decision
    written = item.get("description") if description is None else description
    last, prev = 0.0, str(ask_was or "")
    asked_at, asked_prev = 0.0, ""      # his newest question that the item has not answered
    said: list[tuple[float, dict[str, Any]]] = []
    for a in h.answers_of(item):
        try:
            if _mgates.said_by(a, asked) and (a.get("text") or a.get("choice")):
                said.append((float(a.get("ts") or 0), a))
        except (TypeError, ValueError):
            continue
    stored = ""      # the latest ask a record of his stores, in the order he wrote them (a GitHub comment is read later than it was written)
    for ts, a in sorted(said, key=lambda x: x[0]):
        stored = str(a.get("ask") or "") or stored
        ask = str(a.get("ask") or ask_was or "")      # a board decision keeps the ask it answered (its answer drops the ask from the item)
        if not a.get("question"):
            if ts >= last:
                last, prev = ts, ask
        elif ts >= asked_at and not _noteread.answered_on_item(a, written):
            asked_at, asked_prev = ts, ask or stored      # a comment holds no ask, and the item may hold none any more: the one he was last asked still stands
    unanswered = asked_at > last
    if unanswered:
        last, prev = asked_at, asked_prev or prev
    age = time.time() - last
    if last <= 0 or not 0 <= age < _DECISION_AGAIN_S:
        return
    new = str(meta.get("ask") or "")
    if new and " ".join(new.split()) != " ".join(prev.split()):
        return
    his, he = ("their", "they are") if _mgates.many() else ("his", "he is")      # beside a member's name, never "his"
    ago = f"{max(int(age // 60), 0)} min ago ({h.when_words(dt.datetime.fromtimestamp(last, h.zone()))})"
    if unanswered:
        raise ToolError(f"Refused: {asked} asked a question on {_gh.shown(gid)} {ago} that the item does not answer yet (its description is the one the question was asked under), and this write puts the decision "
                        "back with the same ask line. Answer the question there first: rewrite the description with the answer, saying it answers the question (description=…), in this write or an earlier one. "
                        "The same ask line is then accepted at once")
    raise ToolError(f"Refused: {asked} answered {_gh.shown(gid)} {ago}, and this write puts it back on {his} call "
                    f"with the same ask line: one ask per decision, and {he} not asked again within {int(_DECISION_AGAIN_S // 60)} minutes of {his} answer. Act on {his} answer (write the next step), or, "
                    "if a new question is open, pass the new ask line in this same write (ask=…): a question that has changed is a new ask")


def gate_repark(item_was: dict[str, Any], item: dict[str, Any], meta: dict[str, Any], gid: str, said_l: list[dict[str, Any]]) -> None:
    """Re-parking forever: count the re-parks of an item that is parked or verifying (a write that moves its wake, or a verifying end, to a new date with nothing
    else changed but the wake, the end and the hold) in metadata.repark; a change to a structured field (_substance: needs, after, state, mover, the wait's fields) resets it, an edit of next
    or the description does not (the test compares the structured fields only). The third in a row is refused, unless the owner's words stand behind it (a checked
    said entry, or his answer on the item since it last moved), which resets it too."""
    h = _hooks()
    m0 = item_was.get("metadata") or {}
    was_s, now_s = h.eff_state(item_was), h.eff_state(item)
    same = _substance(item_was) == _substance(item)
    if not same:
        meta.pop("repark", None)                           # something else changed: the count starts again
        return
    if not (was_s in ("parked", "verifying") and now_s == was_s):
        return
    k = "end" if now_s == "verifying" else "wake"
    old_d, new_d = str(m0.get(k) or "")[:10], str(meta.get(k) or "")[:10]
    if not (old_d and new_d > old_d):                      # only a move to a later day is a re-park: a pull-in, a time of day on the same day, or no move at all neither counts nor resets
        return
    n = (int(m0.get("repark") or 0) if isinstance(m0.get("repark"), int) else 0) + 1
    if n >= _states.REPARK_MAX:
        if h.owner_words_on(item_was, said_l, _wt.cap_days()):
            meta.pop("repark", None)
            return
        what = "end date" if now_s == "verifying" else "wake"
        old = m0.get("end") if now_s == "verifying" else m0.get("wake")
        raise ToolError(f"Refused: {_gh.shown(gid)} was re-parked {n - 1} times in a row with nothing else changed, and this is the third move of its {what} ({old} → "
                        f"{meta.get('end') if now_s == 'verifying' else meta.get('wake')}). A wait that keeps moving is not a wait: bring it to {OWNER} instead with needs=decision and an ask "
                        "(keep it parked, drop it, or change the plan), or change something real on the item first ("
                        + ("only a change to hold, wake, needs, after or the wait resets the count: an edit of next, the description or the basis text does not). " if h.model_guards_on() else "next, state, what it waits on). ")
                        + f"When {OWNER} has just said to park it again, his words lift this: pass said=[…] with them, or ask him to answer on the item")
    meta["repark"] = n


_WAIT_STRUCTURE = ("wait_kind", "wait_event", "wait_anchor", "after", "waits", "wait_mode")      # what a wait stands on (the clock fields apart; the mover is who takes the item after, and the holder rules cover hand-offs; a changed list of waits is a new shape)


_STRUCT_KEEP = 5      # earlier signatures of the wait's structure kept in metadata.clock_struct


_STRUCT_PASSES = 3    # clock pushes in a row that a new wait shape alone lets through: the third is refused (metadata.clock_struct_n counts them)


def _struct_sig(m: dict[str, Any]) -> str:
    """The wait's structure as one comparable string: wait_kind, wait_event, wait_anchor and after, each normalised (an empty value is none; after is a sorted list). A wait_event of
    recycle or fleet_op is compared by its verb alone (`recycle <machine>` is `recycle`, `fleet_op <verb> <machine>` is `fleet_op <verb>`): the machine argument is free text to a session, so
    a made-up one would be a new shape each time; a pr_* event keeps its full target."""
    def norm(k: str, v: Any) -> Any:
        if k == "waits":
            return _list_shape(v) if isinstance(v, list) else ""
        if isinstance(v, (list, tuple)):
            return sorted(str(x).strip() for x in v if str(x).strip())
        s = " ".join(str(v or "").split())
        if k == "wait_event":
            w = s.split(" ")
            s = w[0] if w[0] == "recycle" else " ".join(w[:2]) if w[0] == "fleet_op" else s
        return s
    return json.dumps([norm(k, m.get(k)) for k in _WAIT_STRUCTURE if m.get(k) or k not in ("waits", "wait_mode")], sort_keys=True)      # a single wait's signature is what it always was: the list's two fields count only when stored


def _struct_progress(m0: dict[str, Any], meta: dict[str, Any]) -> bool:
    """Record the wait's structure on this write and say whether it is progress: the structure differs from what the item had AND is one it has never held (metadata.clock_struct keeps
    the last few; a flip A, B, A is no change on the return) AND is not a removal of after or wait_event. Writes meta["clock_struct"] when the structure changes (the write is saved or refused whole)."""
    old, new = _struct_sig(m0), _struct_sig(meta)
    if old == new:
        return False
    hist = [h for h in (m0.get("clock_struct") or []) if isinstance(h, str)]
    never_held = new not in hist
    if old not in hist:
        hist.append(old)
    if new not in hist:
        hist.append(new)
    meta["clock_struct"] = hist[-_STRUCT_KEEP:]
    removal = any(m0.get(k) and not meta.get(k) for k in ("after", "wait_event"))
    return never_held and not removal


_CLOCK_FIELDS = ("wake", "ask_by")    # the dates a mover can push out to buy time: a wake (a park's or a hand-off backstop's) and a relay or event wait's ask-by


def _clock_epoch(field: str, value: Any) -> float | None:
    """A clock field's value as an epoch for comparing two values of the SAME field, None when it reads as no date. A wake or an ask_by reads as the wake does (a bare date falls due at 00:00 of its day)."""
    h = _hooks()
    v = str(value or "").strip()
    if not v:
        return None
    try:
        return h.wake_at(v).timestamp()
    except Exception:  # noqa: BLE001  — a value that reads as no date is no renewal of one
        return None


def _open_step_keys(steps: list[dict[str, Any]]) -> list[str]:
    return [_steps.key(s["text"]) for s in steps if s.get("status") == _steps.OPEN]


def gate_clock_renewal(item_was: dict[str, Any], meta: dict[str, Any], gid: str, steps_old: list[dict[str, Any]], steps_new: list[dict[str, Any]] | None,
                        description: str, said_l: list[dict[str, Any]], sender: str = "", list_end_words: str = "") -> None:
    """No clock renewal without progress: refuse a session's write that pushes a wake or an ask_by to a LATER time than the item already holds while the item's reason and its
    open steps are as they were. A reason changed is a new description or wait_basis text, or the owner's words in the write (a NEW said entry that
    _owner_words_on accepts: Acked-by, checked against a transcript, recent; a message (msg) the item already holds does not count again, whatever the quote, nor does a board answer already on it), or a change to what the wait stands on (wait_kind, wait_event,
    wait_anchor, after) to a shape the item has never held (metadata.clock_struct keeps the last few; a flip back is no change, and removing after or wait_event is none), which lets a clock push through only twice in a row (metadata.clock_struct_n; the third is refused, and a step, a reason, a new owner message or a hand-off resets the count); a step changed is a
    step marked done or dropped, or a new line (the open lines differ; a line reworded in next alone reads as a new one). `reword=` is no progress: it restates a step that stays the same step, so a reword-only write does not renew a clock. A wait_reason is no reason here: it is not stored, so it cannot be compared and any text would pass.
    Setting a clock for the first time, pulling one in, leaving it as it is, clearing it and a real hand-off are not renewals: a hand-off is a write after which the item's effective holder
    (the stored mover, else the first session in needs), resolved through the registry, is another session than before AND is not the sender (a holder who sets its own clock is the same
    session by another name, or a flip back and forth). `list_end_words`: the refusal's own words for a write that ends a stored list (`waits=[]`) beside a later day; the refusal is then these, and a write with progress is let through as any other. Writes nothing."""
    h = _hooks()
    m0 = item_was.get("metadata") or {}
    struct_progress = _struct_progress(m0, meta)      # first: it records the structure of every write, whether or not a clock moves
    try:
        struct_n = int(m0.get("clock_struct_n") or 0)
    except (TypeError, ValueError):
        struct_n = 0
    spent = {str(e.get("msg") or "").strip() for e in (m0.get("said") or []) if isinstance(e, dict) and str(e.get("msg") or "").strip()}
    fresh = [e for e in said_l if str(e.get("msg") or "").strip() not in spent]      # a message is spent once it is stored, whatever quote is cut from it
    nm = _anc.names()

    def holder(m: dict[str, Any]) -> str:
        who = str(m.get("mover") or "").strip() or (str(_needs_sessions(m)[0]).strip() if _needs_sessions(m) else "")
        return _anc.canonical(who, nm) if who else ""
    was_h, now_h = holder(m0), holder(meta)

    def basis(m: dict[str, Any]) -> str:
        b = m.get("wait_basis")
        return " ".join(str(b.get("text") if isinstance(b, dict) else b or "").split())
    progress = (
        (steps_new is not None and _open_step_keys(steps_new) != _open_step_keys(steps_old))      # a step was done, dropped or added: the item moved
        or bool(h.owner_words_on({}, fresh, _wt.cap_days()))                                       # his words, checked, in this very write (a board answer already on the item is not new)
        or bool(now_h and now_h != was_h and not (sender.strip() and _anc.canonical(sender.strip(), nm) == now_h))      # a real hand-off to another session than the sender: the clock is the new holder's own
        or bool(description.strip() and " ".join(description.split()) != " ".join(str(item_was.get("description") or "").split()))
        or basis(meta) != basis(m0))
    if progress:
        meta.pop("clock_struct_n", None)                                    # a real change resets the count of clock pushes let through on a new wait shape alone
    moved = []
    for f in _CLOCK_FIELDS:
        old, new = _clock_epoch(f, m0.get(f)), _clock_epoch(f, meta.get(f))
        if old is not None and new is not None and new > old:
            moved.append(f"{f} {m0.get(f)} → {meta.get(f)}")
    if not moved or progress:
        return
    real ="mark a step done or dropped (done=[…], dropped=[…]), write the next step, or state the new reason (a new description)"
    if struct_progress:                                                     # the wait changed to a shape the item never held, with nothing else changed: at most twice in a row
        if struct_n + 1 >= _STRUCT_PASSES:
            raise ToolError(f"Refused: {_gh.shown(gid)} has had its clock pushed out {struct_n} times in a row on a change of what its wait stands on alone ({'; '.join(moved)}), and this would be the "
                            f"{_STRUCT_PASSES}rd: a wait that keeps taking a new shape is a wait that keeps moving, not progress. Change something real in the same write: {real}. "
                            f"Only a step, the reason, {OWNER}'s own new words or a hand-off to another session resets the count. The item model: {h.model_page}")
        meta["clock_struct_n"] = struct_n + 1
        return
    if list_end_words:
        raise ToolError(f"{list_end_words}, or change something real in the same write: {real}.")
    event = ("the event-wait form (wait_kind=\"event\", wait_event=<the event>, until=<the backstop day>, mover=<who takes it when it happens>)")
    if _waits_decision(meta):
        ways = f"Change something real in the same write: {real}. An item on {OWNER}'s decision cannot be held, so the date stays as it is until a step or the reason changes."
    elif str(m0.get("wait_kind") or "").lower() == "event":
        ways = (f"Change something real in the same write: {real}, or change what the wait stands on (a different wait_event or wait_anchor, or after=[…] naming another item). "
                "The event-wait form is already in use, so a later until alone is only a later date.")
    elif m0.get("hold") or h.eff_state(item_was) == "parked":
        ways = ("Change something real in the same write: a new wait_basis (what the wait now rests on, with its date), or " + real
                + f". If it waits on something that happens in the fleet, use {event} instead.")
    else:
        ways = (f"Change something real in the same write: {real}. If the item now waits, say what on: park it "
                f"(until=YYYY-MM-DD with wait_kind=\"time\" and wait_basis=<what the date is, with its date>), or, for something that happens in the fleet, use {event}.")
    raise ToolError(f"Refused: {_gh.shown(gid)} would have its clock pushed out ({'; '.join(moved)}) with its reason and its open steps exactly as they were: moving a date forward is not progress, "
                    f"and an item that keeps being re-dated is how work sits unseen. {ways} A wait_reason does not count (it is not stored). The item model: {h.model_page}")


def gate_after(after: Any, gid: str = "", line: int = 0) -> list[str]:
    """after as given (a list of item ids, or a comma-separated string) → the ids stored. Each names an open item of any project
    (a superseded one is followed to its replacement); the item itself, a closed one, a missing one and a loop are refused. `line`: the position of the item line of a list this is for (the loop's refusal then has no
    `(after)` in it: the written wait is no after link)."""
    h = _hooks()
    if isinstance(after, str):
        after = [x for x in re.split(r"[,\s]+", after) if x.strip()]
    if not isinstance(after, list):
        raise ToolError("Refused: after is a list of item ids (or one comma-separated string)")
    out = []
    for x in after:
        g = _norm_id(str(x), bare=True)
        if not _path(g).exists():
            raise ToolError(f"Refused: after names {g}, which does not exist")
        g = h.follow_superseded(g)
        if g == gid:
            raise ToolError(f"Refused: {gid} cannot wait on itself")
        it = _load(g)
        if it.get("status") != "open":
            raise ToolError(f"Refused: {g} is already {it.get('status')}" + (f" ({(it.get('metadata') or {}).get('outcome')})" if (it.get("metadata") or {}).get("outcome") else "")
                            + "; after names open items that must close first")
        if gid and h.after_reaches([g], gid):
            raise ToolError(f"Refused: a loop: {g} itself waits on {gid}{'' if line else ' (after)'}, so {gid} cannot wait on {g}" + (f"; take {g} out of waits[{line}] or end its wait on {gid} first" if line else ""))
        if g not in out:
            out.append(g)
    return out


# A front agent does not watch handed-off work itself: stackshot
# refuses a sender's wake or check on a handed-off item, and its text stops teaching it. The result lands through stackshot when the mover closes the
# item or hands it back to the front agent (tell_owner_close, tell_handback); a front agent that sets its own wake or until date on an alive item another
# session moves is polling work it handed away. Narrowed in review: only a date with no hold on an ALIVE item is refused. A hold with a
# wake on a waiting or parked item is the park's own timer, fired by the server, and a done `check` is the server-run push the rule itself names,
# so neither is gated; ask_by stays anyone's too. Only a front agent is refused (a background agent, the owner and a sender the roles do
# not know pass), the mover's own wake passes, re-sending the wake an item already carries is no setting, and a watch_reason naming why no push
# exists lets a real exception through. A wake already stored survives a hand-off made later: deliberate (it fires once, as a notice to the keeper).
_WATCH_REASON_MIN = 15


_WATCH_RULE = ("a front agent does not watch handed-off work itself (no wake or poll it sets): the result lands through stackshot when the mover closes the item or hands it back to you")


def _watch_others(item: dict[str, Any], sender: str, handed: list[str]) -> list[str]:
    """The sessions other than `sender` that move an ALIVE item as a write leaves it (its mover, and the sessions its next hands the work to); [] for a waiting
    item (a park's timer is the server's), for an item the owner moves, and when the model names none."""
    hk = _hooks()
    mod = _model.derive(item, after_open=lambda i_: hk.after_open(i_.get("metadata") or {}), anchored=lambda i_: False)
    if mod.state != _model.ALIVE:
        return []
    others = [h for h in handed if h and not (hk.same_sess(h, sender) or hk.session_id(h) == hk.session_id(sender))]
    mover = mod.mover
    if mover and not _model.is_owner(mover) and not (hk.same_sess(mover, sender) or hk.session_id(mover) == hk.session_id(sender)):
        others.append(mover)
    return others


def gate_sender_watch(gid: str, item_now: dict[str, Any], sender: str, *, handed: list[str] | None = None, watch_reason: str = "") -> str:
    """Refuse a front agent's own wake or until date (no hold) on an alive item another session moves (see the block above). Called only when the call sets a wake that
    differs from the one the item carried. `item_now` = the item as this call leaves it (so a hand-off made in the same call counts: the old mover is no
    longer the mover); `handed` = the sessions its next hands the work to. → the reason to record on the item ("" when none was needed); raises ToolError
    otherwise. A failure of the check itself passes the write (one stderr line)."""
    if not _telling.front_sender(sender):
        return ""
    try:
        others = _watch_others(item_now, sender, list(handed or []))
        who = (_session_label(others[0]) or others[0]) if others else ""
    except Exception as e:  # noqa: BLE001  — the rule is an extra: a failure in it lets the write through, never a 500
        print(f"watch rule: {gid or 'a new item'} not judged: {e.__class__.__name__}: {e}; the write passes", file=sys.stderr, flush=True)
        return ""
    if not others:
        return ""
    why = _model.clean(watch_reason)
    if why:
        if len(why) < _WATCH_REASON_MIN:
            raise ToolError(f"Refused: watch_reason {why!r} is too short to name why no push exists (at least {_WATCH_REASON_MIN} characters)")
        return why
    raise ToolError(f"Refused: {_WATCH_RULE}. {_gh.shown(gid)} is moved by {who}, so your date is refused: "
                    f"{who}'s close or hand-back reaches you through stackshot (a done `check` is allowed, and so is a park: until with wait_kind=\"time\" and wait_basis; within the wait cap's days it needs his recorded words). The date you may set is until on a wait, which the server watches. "
                    "If no push exists, pass watch_reason=<why no push reaches you> with the same call: it is recorded on the item and the call goes through.")


# A wait a session sets on its own item. An agent that moves an item can park its work with a wake or by dating its own step ("apply it at Monday's run") although nothing stops the
# step now: the ready work then sits idle until the date. self_wait.py holds the rule and the model call: such a write carries wait_reason (what the step waits on), and a model is
# asked once whether the step could be done now given that reason; yes refuses. The call is slow, so this gate runs BEFORE the item lock is taken (a read of the item as stored,
# never a write), and it fails open: any failure, a missing model, a call past the hourly cap, passes the write. Out of scope, because the wait already names its blocker: a wait on
# another item (after), on the owner or an outside party (needs decision or external), a stored wait (wait_kind), a park (hold, or a wait_basis the update tool keeps: one it drops, for a wake within the cap, is judged as if unsent), a hand-off to another session, an item
# that does not stay alive, and a mover other than the sender.
_SELF_WAIT_STATES_OUT = ("parked", "outside", "blocked", "verifying", "completed", "your-call", "your-step")


def reads_time_wait(item: dict[str, Any]) -> bool:
    """The model reads the open item as a wait on a time with no hold flag: a verifying item (its end date is its wait), or any item the model reads as a time wait (wait_kind=time). The snooze guard
    (model_guards) asks such a wait for its reason like a hold's, so update takes a wait_basis for its wake at any length, as it does for a held item; a wake an alive item
    carries as a hand-off's backstop (no until) is not a wait and reads False."""
    if item.get("status") != "open":
        return False
    try:
        mod = _item_read._model_of(item)    # the reader the hooks carry (wiring.py: model_of)
    except Exception:  # noqa: BLE001
        return False
    return mod.state == _model.WAITING and mod.wait is not None and mod.wait.kind == "time"


def basis_held(item: dict[str, Any], *, hold: bool = False, verifying: bool = False) -> bool:
    """Whether a wait_basis is judged for a time wait held: a hold, a held or verifying item. The one reading for the update tool (`_basis_frame`) and the self-wait check, so the two cannot differ;
    `item` is the item as the tool reads it, with a stored until stood in as the old working fields (`until_write.unfold_item`)."""
    hk = _hooks()
    return hk.model_guards_on() and bool(hold or _holders._is_held(item) or reads_time_wait(item) or verifying)


def gate_self_wait(gid: str, sender: str, *, next_text: str = "", wake: str = "", mover: str = "", needs: Any = "", after: Any = "", wait_kind: str = "", hold: bool = False,
                    wait_basis: str = "", state: str = "", status: str = "", wait_reason: str = "", clear_next: bool = False, clear_wake: bool = False, clear_needs: bool = False,
                    clear_after: bool = False, clear_wait: bool = False, clear_hold: bool = False, creating: dict[str, Any] | None = None) -> None:
    """Refuse (ToolError) a wait the sender sets on an item it moves when it names no blocker, or when the model says the step can be done now (see the block above).
    `gid` = the stored item ("" when `creating` is given: the item a create makes, as `{subject, project}`); the other arguments are the call's own. A failure of the check itself passes the write."""
    hk = _hooks()
    try:
        if not _cfg.wait_guard_on() or not sender.strip() or _model.is_owner(sender) or str(status or "").strip().lower() in ("completed", "closed"):
            return
        basis_given = bool(str(wait_basis or "").strip()) and " ".join(str(wait_basis).split()).lower() not in hk.ask_none      # a word that clears (none, clear, -) is no basis: the wake is judged as sent without one
        if wait_kind.strip().lower() in hk.ask_none:
            wait_kind, clear_wait = "", True                # a wait_kind of none, clear or - is a clear of the wait (the update tool reads it so), never a kind
        if hold or str(state or "").strip().lower() in _SELF_WAIT_STATES_OUT or wait_kind.strip():
            return
        if basis_given and (clear_wake or clear_hold):
            return                                          # a basis beside a wake or a hold this call drops: the update tool refuses the call whatever the gate says, so no model call is spent on it
        if _needs_list(needs) and any(x.lower() in _NEEDS_KINDS for x in _needs_list(needs)):
            return
        if _after_of({"after": after if isinstance(after, list) else _needs_list(after)}):
            return
        today = dt.datetime.now(_cfg.tz())
        mine = lambda n: _handoff.ho_same(n, sender)       # noqa: E731
        wake_given = ""
        if wake.strip() and not clear_wake:
            try:
                wake_given = hk.parse_wake(wake)                      # the stored form: "2099-01-04 10:00" and "2099-01-04T10:00" are one wake
            except ToolError:
                return                                              # a wake in no valid form: the write's own wake check refuses it, with its real message, and no model is asked
            if hk.wake_at(wake_given) <= _pages.zone_now():
                return                                              # a wake not in the future is refused there too
        if creating is None:
            item = _load(gid)
            if item.get("status") != "open":
                return
            meta = dict(item.get("metadata") or {})
            subject = str(item.get("subject") or "")
            if mover.strip():
                meta["mover"] = mover.strip()
            if clear_needs:
                meta.pop("needs", None)
            if _needs_list(needs):
                meta["needs"] = _needs_list(needs)
            if clear_after:
                meta.pop("after", None)
            if clear_wait:
                for k in ("wait_kind", "wait_anchor", "wait_event", "until"):
                    meta.pop(k, None)
            if clear_hold:
                meta.pop("hold", None)
            if wake.strip() and not clear_wake:
                meta["wake"] = wake.strip()
            if clear_wake:
                meta.pop("wake", None); meta.pop("until", None)
            if state.strip():
                meta["state"] = state.strip()
            mod = _model.derive({**item, "metadata": meta}, after_open=lambda i_: hk.after_open(i_.get("metadata") or {}), anchored=lambda i_: False)
            if mod.state != _model.ALIVE or not mod.mover or _model.is_owner(mod.mover) or not _handoff.ho_same(mod.mover, sender):
                return
            stored_wake = str(_wt.wake_value(item.get("metadata") or {}) or "")
            if basis_given:
                tool_item = json.loads(json.dumps(item))
                _uw.unfold_item(tool_item)                  # the item as the update tool reads it: a stored until stands as the old working fields, so the two read the same held
                if basis_unneeded(item, wake_given or stored_wake.strip(), basis_held(tool_item)) is None:
                    return                                      # a park that carries its basis (a wake past the cap, or a time wait's window) names its own reason; a basis the update tool drops (a wake within the cap) is no reason, so the wake is judged as if it were not sent
            wake_new = bool(wake_given) and wake_given != stored_wake.strip()      # re-sending the stored wake sets nothing
            stored_next = str((item.get("metadata") or {}).get("next") or "")
        else:
            subject = str(creating.get("subject") or "")
            if not mover.strip() or not mine(mover):
                return                                  # a create with no mover= is moved by the builder or the -main agent, never its creator: only mover=<the sender> sets a wait of its own
            wake_new, stored_next = False, ""
        if next_text.strip() and not clear_next:
            if [h for h in hk.handoffs_in(next_text, hk.session_roster()) if not mine(h)]:
                return                                  # a hand-off to another session: the work moves, nothing waits on the sender
            dated = _selfwait.dated_steps(next_text, stored_next, mine, today.date())
        else:
            dated = []
        if not wake_new and not dated:
            return
        waits = ([f"an until date {wake_given}"] if wake_new else []) + [f"a step dated {found}" for _, found in dated]
        own = _selfwait.own_lines(next_text, mine) if next_text.strip() and not clear_next else _selfwait.own_lines(stored_next, mine)
        step = " ".join(own) or subject
    except Exception as e:  # noqa: BLE001  — the rule is an extra: a failure in it lets the write through, never a 500
        print(f"wait guard: {gid or 'a new item'} not judged: {e.__class__.__name__}: {e}; the write passes", file=sys.stderr, flush=True)
        return
    call = ", ".join(([f'until="{wake_given}"'] if wake_new else []) + (['next="<your next, as you sent it>"'] if dated else []))
    why = _selfwait.gate(subject=subject, waits=waits, step=step, reason=wait_reason, now=today, call=call)
    if why:
        raise ToolError(f"Refused: {why}")


BUSY_HOLD_REFUSAL = ("Refused: this item is being moved now: {live} is running on it, so it is not paused. Keep it in hand and write where its step stands (work=<one line>, state in progress) "
                     "instead of a park. Park it only once nothing of yours is running on it.")


BUSY_RELEASE_PREFIX = "a release of PR #"      # what the words of a running release begin with (audit/busy_hold.py `live_release`): the refusal that names one is BUSY_RELEASE_REFUSAL
BUSY_RELEASE_REFUSAL = ("Refused: this item is being moved now: {live}, so it is not paused. Keep it in hand and write where its step stands (work=<one line>, state in progress), "
                        "or wait on it by name: update(wait_kind=\"event\", wait_event=\"pr_released <n>\" or \"pr_merged <n>\", until=<the day it comes back anyway; left out, the server takes tomorrow or the day the item's words give, and says so; it is not the 14-day backstop>, mover=<who takes it then>). "
                        "Park it only once nothing is running on it.")


def _given(v: Any) -> bool:
    """Does a parameter carry a value (a non-empty string, a non-empty list, a true flag)?"""
    return bool(v.strip()) if isinstance(v, str) else bool(v)


def _busy_mover(gid: str, *, mover: str = "", next_text: str = "", clear_needs: bool = False, clear_after: bool = False, clear_next: bool = False) -> "tuple[dict[str, Any], Any, str]":
    """The open item `gid` as a write that passes these leaves its mover → (the item, the model's reading of it, who moves it): "" for who when nobody the board can name, the owner, or a hand-off to another session
    (a next line that hands it on is the work moving: nothing of the mover's is paused; a `mover=` is the one who moves it from this write on, compared to the sender by the caller). An item already waiting has no mover while it waits: the one who picks it up is
    whose item it is. Raises what `_load` raises; a caller treats any failure as unknown."""
    hk = _hooks()
    item = _load(gid)
    if item.get("status") != "open":
        return item, None, ""
    meta = dict(item.get("metadata") or {})
    if _given(mover):
        meta["mover"] = _model.norm_who(mover)
    if clear_needs:
        meta.pop("needs", None)
    if clear_after:
        meta.pop("after", None)
    mod = _model.derive({**item, "metadata": meta}, after_open=lambda i_: hk.after_open(i_.get("metadata") or {}), anchored=lambda i_: False)
    who = mod.mover or mod.picker
    if not who or _model.is_owner(who):
        return item, mod, ""
    if next_text.strip() and not clear_next and [h for h in hk.handoffs_in(next_text, hk.session_roster()) if not _handoff.ho_same(h, who)]:
        return item, mod, ""                                          # a hand-off to another session: the work moves, nothing of the mover's is paused
    return item, mod, who


def gate_busy_hold(gid: str, sender: str, *, hold: bool = False, wake: str = "", ask_by: str = "", wait_kind: str = "", needs: Any = "", after: Any = "", mover: str = "",
                   next_text: str = "", status: str = "", done: Any = None, clear_hold: bool = False, clear_wake: bool = False, clear_wait: bool = False, clear_needs: bool = False,
                   clear_after: bool = False, clear_next: bool = False, live: Callable[[str, str], str] | None = None) -> None:
    """Refuse (ToolError) a hold the item's mover sets on an item it is moving at this moment: an item an agent is working on is kept in hand, never paused. An item already on hold counts (its mover is the one who
    picks it up). `live(item, mover)` is the server's proof (audit/busy_hold.py): the words for what of the mover's own is running on the item (`your subagent "<description>"`, or `a release of PR #<n> tied to this item is running (<what was read>)`
    for a release of a pull request tied to the item that is running, which gets its own refusal text), "" when nothing is or nothing can be told; None passes every write. A write that parks is a hold, or a date alone (a wake or an until: the write turns it into a hold), with no named blocker: neither in this write (a wait_kind other than time,
    an after link, a needs, a relay's ask_by) nor already stored on the item (an anchor, relay, item or event wait, an open `after`, a `needs` that names someone outside: any wait the model reads as other than a
    plain wait on a time), and no clear_* of the park. Never refused: the guard off (`[model] busy_hold_guard`), an owner's write, a write by anyone but the item's mover, a closed item or a write that closes it or
    ticks a step (done=), a hand-off to another session, and anything that cannot be read: a failure of the check itself passes the write, as `gate_self_wait` does. `gid` = the stored item."""
    try:
        hk = _hooks()
        if live is None or not _cfg.model_busy_hold_guard() or not sender.strip() or _model.is_owner(sender) or str(status or "").strip().lower() in ("completed", "closed"):
            return
        wake_set = _given(wake) and wake.strip().lower() not in hk.ask_none
        if not (hold or wake_set) or clear_hold or clear_wake or clear_wait or _given(done):
            return
        if wait_kind.strip().lower() not in ("", "time") or _given(ask_by) or _given(after) or _given(needs):
            return                                                    # a wait on something else, named: someone's step, another item, an event, an outside party
        item, mod, who = _busy_mover(gid, mover=mover, next_text=next_text, clear_needs=clear_needs, clear_after=clear_after, clear_next=clear_next)
        if not who or not _handoff.ho_same(who, sender):
            return
        if mod.wait is not None and mod.wait.kind != "time":
            return                                                    # the item already stores its blocker (an anchor, a relay, an item, an event, a list): a write that parks it again names it already
        stored = _telling.holder(item)
        what = live(gid, stored if stored and _handoff.ho_same(stored, who) else sender.strip())      # who is the sender's own session (ho_same, any spelling): the proof asks for it by the spelling the item stores, else the sender's
    except Exception as e:  # noqa: BLE001  — the rule is an extra: a failure in it (or an unreadable subagent) lets the write through, never a 500
        print(f"busy hold guard: {gid} not judged: {e.__class__.__name__}: {e}; the write passes", file=sys.stderr, flush=True)
        return
    if what:
        raise ToolError((BUSY_RELEASE_REFUSAL if what.startswith(BUSY_RELEASE_PREFIX) else BUSY_HOLD_REFUSAL).format(live=what))


def busy_note_answer(gid: str, *, hold: bool = False, next_text: str = "", reword: Any = None, mover: str = "", live: Callable[[str, str], str] | None = None) -> "str | None":
    """What of the holder's own runs on item `gid` (the words, "" for nothing), asked BEFORE the item lock, for the reply note that tells the holder of a doing item whose next reads as a wait to park it
    (service/update.py `_doing_wait_note`): while a running subagent of the holder, or a running release of a pull request tied to the item, is tied to the item the wait wording is about its own run, work in hand. None when the note cannot be made (the guard off, no proof, a
    hold, an item that is not open and doing, no line of this call that reads as a wait) and when anything cannot be read: the note then stays as it is. The proof is asked only when the note could be made, and the
    holder is looked up only then."""
    try:
        if live is None or hold or not _cfg.model_busy_hold_guard():
            return None
        if not (_mg.reads_as_wait(next_text) or (reword and _mg.reads_as_wait(json.dumps(reword, ensure_ascii=False, default=str)))):
            return None
        item = _load(gid)
        meta = item.get("metadata") or {}
        if item.get("status") != "open" or meta.get("hold") or meta.get("state") != "doing":
            return None
        stored = _telling.holder(item)
        who = _model.norm_who(mover) if _given(mover) and not (stored and _handoff.ho_same(mover, stored)) else stored      # the holder by the spelling the registry holds: mover= naming the one who holds it already adds nothing
        if not who:
            return None
        return live(gid, who) or ""
    except Exception as e:  # noqa: BLE001  — unknown: the note stays
        print(f"busy hold note: {gid} not judged: {e.__class__.__name__}: {e}; the note stays", file=sys.stderr, flush=True)
        return None


_ASK_HELD_TEXT_KEYS = ("steps", "work", "wait_basis")      # records of lines: only the `text` of each is held, never its status, state, name or time ("open", "done", "dropped" are not the item's text)


_ASK_HELD_KEYS = ("next", "step", "wait_reason", "watch_reason", "goal", "draft", "check", "supplies", "expected_reason", "reason", "outcome_text", "wait_event", "work", "owner_name", "owner", "agent", "observers")      # the options are left out: their labels are short words (Wait, Keep) that a hedge could equal whole


def ask_pre(item_id: str) -> "dict[str, Any]":
    """What an update needs to know of the ask before the write: the item, the ask that stood and its record, where the owner's notes are looked for from, and the text the item held (every text it
    keeps, one line each), so that only a line new in the write is read as its author's word. {} when the item cannot be read."""
    try:
        gid = _norm_id(item_id, bare=True)
        item = _load(gid)
    except ToolError:
        return {}
    try:
        return _ask_pre_read(gid, item)
    except Exception as e:  # noqa: BLE001  — a damaged stamp or record (a time that is no number) never fails the write: the ask's lines are skipped
        print(f"ask: {gid} not read before the write: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return {}


def _ask_pre_read(gid: str, item: dict[str, Any]) -> "dict[str, Any]":
    h = _hooks()
    meta = item.get("metadata") or {}
    held = [item.get("subject"), item.get("description")] + [meta.get(k) for k in _ASK_HELD_KEYS]      # every text the item keeps, one line each below: a line the item holds whole is not new
    for k in _ASK_HELD_TEXT_KEYS:
        v = meta.get(k)
        held += [e.get("text") if isinstance(e, dict) else e for e in (v if isinstance(v, list) else [v])]
    return {"gid": gid, "ask": h.ask_stands(item), "rec": dict(_askl.rec_of(meta)), "look": _askl.look_back(meta), "old": "\n".join(x for v in held for x in _askl.text_leaves(v) if x.strip())}


def gate_contact(name: str, project: str, keep: tuple[str, ...] = ()) -> str:
    """A contact named by a create or an update → the form stored (the session's permanent id where the registry resolves it, else its name). Allowed: a front agent
    (user-facing agent) of the item's project, named by its name, an old name or its id; and any session in `keep` (the item's creator and its current contact) that is a front
    agent of some project: the front agent that made the item from talking with the person stays its contact wherever the item is filed, and can be set back to. Refused with the
    project's front agents and their mandates: a background agent, a session no page lists, the person himself, a front agent of another project that is neither. A project that lists no front agent of its own
    also takes the configured one front (anchors.sole_front)."""
    h = _hooks()
    v = str(name or "").strip()
    choices = h.contact_fronts(project)
    if v and v.lower() not in _contact.NONE_WORDS and not _model.is_owner(v):
        for f in choices:
            if h.contact_same(f, v):
                return h.store_ref(f)
        for k in keep:
            if str(k or "").strip() and h.contact_same(k, v) and h.contact_alive(k):
                return h.store_ref(k)
        if not choices and h.contact_same(_anc.sole_front(), v):
            return h.store_ref(v)
    raise ToolError(_contact.refusal(v or "(empty)", project, choices, h.contact_main(project)))


def gate_handoff(gid: str, before: dict[str, Any] | None, after: dict[str, Any], writer: str) -> None:
    """The send-time guard (design section 3): a hand-off made by a write (needs, mover or then set to a session) is refused when that session has no live pane, with the
    project's background agent named: the message tool's rule since an earlier change. A failure of the check itself lets the write through."""
    if not _handoff.handoff_on() or after.get("status") != "open" or not writer or _ho.is_script(writer):
        return
    try:
        derive = lambda it: _handoff.ho_derive({**it, "gid": gid})
        to = _ho.detect(before, {**after, "gid": gid}, _session_label(writer) or writer, writer if _anc.is_id(writer) else "", derive, _handoff.ho_same)
        if not to or _model.is_owner(to):
            return
        am = after.get("metadata") or {}
        dflt = _telling.fallback_mover(str(am.get("project") or ""))      # D9: a `then` the server defaulted to the project's builder is no hand-off the writer made
        named = [x for x in (_model.norm_who(am.get("mover")), _model.norm_who(am.get("then")), *_needs_sessions(am)) if x and not (dflt and _handoff.ho_same(x, dflt) and x == _model.norm_who(am.get("then")) and x != _model.norm_who(am.get("mover")))]
        if not any(_handoff.ho_same(to, x) for x in named):      # a session the write did not name (the project's builder or -main agent, which an item with no mover falls to) is no hand-off the writer made
            return
        why = _handoff.handoff_pane(to)
        if not why:
            return
        project = str((after.get("metadata") or {}).get("project") or "")
        live = [n for n in _handoff.handoff_background(project) if not _handoff.ho_same(n, to) and not _handoff.handoff_pane(n)]
    except Exception as e:  # noqa: BLE001
        print(f"handoff: {gid} send-time check failed, writing as before: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return
    raise ToolError(f"Refused: {_gh.shown(gid) if gid else 'this item'} cannot be handed to {_session_label(to)}: {why}, so the hand-off would never be read. "
                    + (f"The project's background agent {live[0]} has a pane: hand it to {live[0]} (needs=[\"{live[0]}\"]) and it takes it from there." if live
                       else f"The project has no background agent with a pane either: hand it to a session that has one, or put the call to {OWNER} (needs=decision with its ask)."))


_RX_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
_RX_TIMED_DAY = re.compile(r"(\d{4}-\d{2}-\d{2})[T ]\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?\s*(?:Z|[+-]\d{2}(?::?\d{2})?)?")


def ask_by_day(value: Any, param: str = "ask_by") -> str:
    """A relay or event wait waits on news, so its date is a day, not a time of day: the caller reads this only for a date it gives to that kind of wait. The date a call gave as `param` (ask_by, until, or the old name
    wake) with a time on it (YYYY-MM-DDTHH:MM, seconds, a zone or a space for the T allowed, on a real day) keeps its day and loses the time, and the reply says so (call_log.fixed); a time with an offset or Z is first
    read in the instance timezone, and its day there is the day kept. Anything else comes back as it was, for the checks that judge it. A day falls due at 00:00 of that day, so a day that is not after now, given alone or
    with a time later today, is no day that can be kept: the write is refused, with tomorrow as the earliest."""
    v = _model.clean(value)
    m = _RX_TIMED_DAY.fullmatch(v)
    if not m:
        day = v if _RX_DAY.fullmatch(v) else ""
        keep = ""
    else:
        day = m.group(1)
        keep = (_wakes._wake_iso(v) or day)[:10]
    if not day:
        return value
    try:
        dt.date.fromisoformat(day)
    except ValueError:
        return value
    final = keep or day
    if _hooks().wake_at(final) <= _pages.zone_now():
        raise ToolError(f"Refused: on a relay or event wait {param} is its ask-by day, YYYY-MM-DD with no time of day, and a day falls due at 00:00 of that day: {final} is already past (got {v!r}); "
                        f"give tomorrow at the earliest, {param}={(_pages.zone_now().date() + dt.timedelta(days=1)).isoformat()}")
    if not m:
        return value
    _calls.fixed("ask-by-day", f"{param} {v} had a time of day and a relay or event wait's ask-by is a day: {final} was kept and the time dropped", fields=[param], stored=final, sent=v)
    return final


def until_in(item_id: str, status: str, until: str, wake: str, ask_by: str, hold: bool, wait_kind: str) -> tuple[str, str, bool, list[str], str]:
    """The update tool's date parameters → (wake, ask_by, until_wait, the old parameters used, the date they gave). `until` goes through the write as the wake it is read as (the same gates:
    the future, the cap, the renewal guard), or as the relay's ask_by when the wait is a relay's; the old wake, ask_by and hold(+wake) are read the same way and listed so that the reply names
    `until`. `until_wait`: the date was given as until (a wait on the date alone: the snooze guard, which judges a hold's wake, does not apply). until=none drops the date."""
    h = _hooks()
    none = lambda v: not v.strip() or v.strip().lower() in h.ask_none      # noqa: E731
    used = [n for n, v in (("wake", wake), ("ask_by", ask_by)) if v.strip() and not none(v)]
    given = wake.strip() if used and "wake" in used else ask_by.strip() if used else ""
    u = _model.clean(until)
    if hold and (u or used):
        used.append("hold")
    kind = _model.clean(wait_kind).lower()
    if not kind or kind in h.ask_none:
        try:
            kind = _watch.stored_kind((_load(_norm_id(item_id, bare=True)).get("metadata") or {})) if not kind else ""
        except Exception:  # noqa: BLE001  — an unknown item is _update's to refuse
            kind = ""
    slot = _uw.slot_of(kind)                                                  # the one working field the date of this kind stands in ("ask_by" for a relay or event wait, else "wake")
    if not u and slot != "ask_by" and ask_by.strip() and not wake.strip() and not none(ask_by) and kind not in ("anchor", "item") and _RX_TIMED_DAY.fullmatch(_model.clean(ask_by)):
        u = _model.clean(ask_by)                                              # ask_by is the old name of until: beside no relay or event wait it keeps its time of day, as until does
    if not u:
        if kind and not (wake.strip() and ask_by.strip()):                    # an old parameter on a kind of wait names the date for that kind: it goes where the stored date stands, so it replaces it
            if slot == "ask_by" and wake.strip() and not none(wake):
                day = ask_by_day(wake.strip(), "wake")
                return "", day, False, used, day if given == wake.strip() else given            # the note names the day stored, not the time the fix cut
            if slot == "wake" and ask_by.strip() and not none(ask_by) and kind in ("anchor", "item"):
                return ask_by, "", False, used, given
        day = ask_by_day(ask_by) if slot == "ask_by" and not none(ask_by) else ask_by
        return wake, day, False, used, day if used == ["ask_by"] and day != ask_by else given       # the note names the day stored, not the time the fix cut
    if slot == "ask_by" and u.lower() not in h.ask_none:                      # a relay or event wait: its date is a day, judged as one first (a time is cut to its day in the instance zone, a day not ahead is refused naming tomorrow); the read below would log a wake fix for an offset time beside it
        u = str(ask_by_day(u, "until"))
    if u.lower() not in h.ask_none:
        try:
            at = h.wake_at(h.parse_wake(u))
        except ToolError:
            raise ToolError(f"Refused: until is YYYY-MM-DD or YYYY-MM-DDTHH:MM ({_cfg.tz_abbr()}), a real date (got {u!r})")
        if at <= _pages.zone_now():
            raise ToolError(f"Refused: until must be in the future ({_cfg.tz_abbr()})")
    if slot == "ask_by":
        return "", u, True, used, given
    return u, "", True, used, given


def gate_close(gid: str, item: dict[str, Any], outcome: str, reason: str, superseded_by: str, outcome_text: str, no_default: str = "") -> str:
    """Refuse a close that does not say how the item ended → the replacing item's id, normalised, or "". Every fault of the close is kept and refused together (model/faults.py)."""
    h = _hooks()
    faults: list[str] = []
    missing = [n for n, v in (("outcome", outcome), ("reason", reason), ("outcome_text", outcome_text)) if not v.strip()]
    if outcome == "superseded" and not superseded_by.strip():
        missing.append("superseded_by")
    if missing:
        form = (f"accepted form: complete(item_id=\"{gid}\", sender=\"my-x\", outcome=\"done\", reason=\"<one line: the end state and why it closes>\", outcome_text=\"- <how it ended>\"); "
                "outcome is done | dropped | superseded, and superseded takes superseded_by=\"board#M\" too")
        faults.append(f"Refused: closing {gid} needs {', '.join(missing)}; {form}." + (f" {no_default}." if no_default else "") + (h.relaunch if {"outcome", "reason", "outcome_text"} <= set(missing) else ""))
    if outcome == "unrecorded":
        faults.append("Refused: outcome unrecorded means the item closed before the model with no outcome in its record; only the migration writes it. A close says how it ended: "
                      f"{' | '.join(h.outcomes)}")
    elif outcome and outcome not in h.outcomes:
        faults.append(f"Refused: outcome must be one of {' | '.join(h.outcomes)} — got {outcome!r}")
    if reason.strip():
        if len([ln for ln in reason.splitlines() if ln.strip()]) > 1:
            faults.append("Refused: reason is one line: the end state reached and why the item closed")
        rmax = _fg._close_reason_max()
        if rmax and len(reason) > rmax:
            faults.append(f"Refused: the reason is {len(reason)} characters and the limit is {rmax}. Shorten it to the end state reached and why the item closed; "
                          "the detail goes in the outcome_text bullets (and the project page's timeline).")
    if outcome_text.strip():
        faults.extend(_fg.description_faults(outcome_text, "outcome_text"))
    rep = ""
    if superseded_by.strip():
        if outcome != "superseded":
            faults.append(f"Refused: superseded_by goes with outcome=superseded, not {outcome}")
        else:
            try:
                rep = _norm_id(superseded_by, bare=True)
            except ToolError as e:
                faults.append(str(e))
            if not rep:
                pass
            elif rep == gid:
                faults.append(f"Refused: {gid} cannot be superseded by itself")
            elif not _path(rep).exists():
                faults.append(f"Refused: superseded_by names {rep}, which does not exist; name the item that replaces {gid}")
    if faults:
        raise _faults.refusals(faults)
    return rep


def gate_close_steps(gid: str, steps: list[dict[str, Any]], others: list[int]) -> None:
    """Refuse a session's close while another session's step is still open on the item (`others`: the positions steps.others_open found). A close ticks only the closer's own steps (the ones it wrote or that open with its name); it never settles a step
    that another session still owes, and a closed item holds no open step, so the close waits until that session's step is marked or the closer marks it in the same call. The refusal opens with the way forward."""
    if not others:
        return

    lines = "; ".join(f"{i + 1}. {_clip_line(_steps.first_line(steps[i]['text']), 90)} (owed by {_steps.opener(steps[i]['text'])})" for i in others[:5])
    more = f" and {len(others) - 5} more" if len(others) > 5 else ""
    n = [i + 1 for i in others]
    many = len(others) > 1
    raise ToolError(f"Refused: {_gh.shown(gid)} is not closed and nothing is ticked. To close it now, mark {'those steps' if many else 'that step'} in the closing call itself: "
                    f"update(item_id=..., status=\"completed\", outcome=..., reason=..., outcome_text=..., sender=..., dropped={n}) "
                    f"(done={n} when {'their' if many else 'its'} work was done; the complete tool takes no marks). Otherwise leave the item open: ask the session that owes {'them' if many else 'it'} to finish, or mark your own steps with update (done=[n]). "
                    f"A close ticks only the steps you wrote or that open with your name, and a step another session still owes stays open. Still open and not yours: {lines}{more}.")


def _said_roots() -> tuple[str, ...]:
    """[said] transcripts: where this box keeps Claude Code's transcripts (<root>/*/<session uuid>.jsonl), one path or a list;
    the default is ~/.claude/projects (a second Claude config dir keeps its own)."""
    return _said.roots_of(_cfg.get("said", "transcripts"))


def _box_refusal(who: str, sess: str, e: Exception) -> ToolError:
    """The refusal of a `said` entry whose transcript is on the box the agents run on ([agents_box] ssh) and that box did not answer. A session with no transcript there is stored unchecked, as before; a box that
    could not be asked is not "no transcript": the write is refused, with the reason, rather than stored unchecked without a word. The reason is logged by core/agentbox.py as well."""
    return ToolError(f"Refused: {who}: the transcript of {_session_label(sess) or sess or 'the sender'} could not be read from the box the sessions run on ({e}); the entry is not stored unchecked in its place. "
                     f"Send the same call again in a minute; if it keeps failing, {OWNER} needs to know that box is not reachable.")


def _said_verify(sess: str, spec: dict[str, str], root: Any, prefixes: Any, phrases: Any, marker: str = "") -> tuple[str, dict[str, Any]]:
    """Check one said entry against the transcript of the session it names → (the transcript id to store, said.verify's result). A permanent id
    (what _session_id gives once the registry knows the session) has no transcript of its own, so the candidates are: the session as given
    when it is a transcript id, then the registry's transcripts of that session, newest first, then what _session_id makes of it. The first
    candidate whose transcript is on this box is the one verified against and stored; none → the newest candidate, unchecked. An entry of kind
    acted is checked by said.verify_acted (a queued_command attachment entry of human origin), every other by said.verify (his typed message)."""
    fn = _said.verify_acted if spec.get("kind") == _said.ACTED else _said.verify
    sid, cands = _said_candidates(sess)
    for c in cands:
        if _said.locate(c, root) is not None:
            return c, fn(c, spec["msg"], spec["quote"], root, prefixes, phrases, marker)
    _clients.require_links_copy(answering=True)       # [agents_box] ssh set and no transcript found: only a box that answers now makes that "no transcript"; a silent box (a copy that may lack the session) is a refusal, not an unchecked entry
    keep = next((c for c in cands if not _sr.is_perm_id(c)), sid)       # nothing readable on this box: stored unchecked under a transcript id, not the permanent id
    return keep, fn(keep, spec["msg"], spec["quote"], root, prefixes, phrases, marker)


def _said_candidates(sess: str) -> tuple[str, list[str]]:
    """The session's id and the transcript ids its `said` is looked for under, in order (see _said_verify)."""
    _clients.require_links_copy()                     # [agents_box] ssh set: a name is resolved from the box's registry, and a copy that is missing or a day old is no ground for storing a quote unchecked: BoxError, the caller refuses
    h = _hooks()
    sid = h.session_id(sess)                          # a pane name → its transcript uuid (old rule) or its permanent id (registry); ids pass through
    given = str(sess or "").strip().lower()
    return sid, [c for c in dict.fromkeys([given if _said.is_uuid(given) else "", *reversed(_sr.transcripts(sid)), sid]) if c]


def _said_plain(quote: str, sess: str, root: Any, prefixes: Any, phrases: Any, marker: str, dry: bool = False) -> list[dict[str, str]]:
    """A `said` sent as plain text → the one entry it stands for, an Acked-by with that quote, and his message found in the sender's transcript by its words (the latest of his own typed messages that holds
    them; the same transcript lookup as the structured form, then the same check). A transcript this box cannot read leaves the entry unchecked, as the structured form does. A readable transcript with no
    message of his that holds the text is refused: the words are not his."""
    try:
        sid, cands = _said_candidates(sess)
    except _ab.BoxError as e:
        raise _box_refusal("said", sess, e) from e
    msg = ""
    seen = False
    for c in cands:
        try:
            path = _said.locate(c, root)
        except _ab.BoxError as e:
            raise _box_refusal("said", sess, e) from e
        if path is not None:
            seen = True
            try:
                msg = _said.find_by_quote(path, quote, prefixes, phrases, marker)
            except _ab.BoxError as e:
                raise _box_refusal("said", sess, e) from e
            except OSError:
                msg = ""
                break               # a transcript that cannot be read: unchecked, like any other
            if not msg:
                raise ToolError(f"Refused: said: no message of {OWNER}'s own in the transcript of {_session_label(c) or sess or 'the sender'} holds that text (whitespace aside); "
                                f"cut his sentences verbatim, or pass said as a list of objects, {_said.FORM}")
            break
    if not seen:
        try:
            _clients.require_links_copy(answering=True)       # no transcript found: unchecked only when the box answers now (see _said_verify)
        except _ab.BoxError as e:
            raise _box_refusal("said", sess, e) from e
    if not dry:
        _calls.fixed("said-text", f"said was sent as text, so it is recorded as {OWNER}'s Acked-by with that quote"
                     + (f", found in his message {msg[:8]} of the sender's session" if msg else " (no transcript of the sender's session can be read here, so it is stored unchecked)")
                     + "; to record another tag or a message that is not the latest holding those words, pass said as a list of objects")
    return [{"tag": "Acked-by", "quote": quote, "msg": msg, "session": "", "kind": _said.WORDS}]


def gate_said(said: Any, default_session: str, by: str, dry: bool = False) -> list[dict[str, Any]]:
    """The `said` argument of a create, update or complete → the entries to append to metadata.said, each checked against the
    transcript of the session it names (said.verify): {tag, quote, session (resolved to its transcript uuid the way an owner is),
    msg, ts (the message's clock), checked, prompt_source (for the record only), by (the sender)}. A readable transcript that
    fails the check refuses the whole write, naming the entry and the test; an unreadable one (a cloud session, another
    machine, a name no live pane carries) stores the entry unchecked. [] when nothing was passed. An entry of kind acted (proof he did his steps:
    a queued_command attachment entry of human origin) is stored with tag Done-by and kind acted; it never counts as his words or his decision.
    `dry`: only the lookups (the registry copy, the transcripts on the agents' box) are made, for `update.said_preread` to run before the item lock; the fixes are not noted and the result is thrown away."""
    if said is None or said == [] or (isinstance(said, str) and not said.strip()):
        return []
    faults: list[str] = []
    root = _said_roots()
    prefixes, phrases = _said.prefixes_of(_cfg.get("said", "injected_prefixes")), _said.phrases_of(_cfg.get("said", "injected_phrases"))   # stopgaps for messages before the marker
    marker = str(_cfg.get("said", "injected_marker") or "")                   # what the fleet tool puts at the start of text it types; "" = none
    if quote := _said.plain_quote(said):      # text, not the structured form: his words as an Acked-by, his message found by them (the server takes the fix and says so)
        specs = _said_plain(quote, default_session, root, prefixes, phrases, marker, dry)
    else:
        specs, shape = _said.parse_all(said)      # every entry that is not well formed is a fault of its own; the well formed ones are still checked against the transcript
        faults.extend(f"Refused: {e}" for e in shape)
    out: list[dict[str, Any]] = []
    for i, s in enumerate(specs):
        sess = s["session"] or default_session
        try:
            sid, r = _said_verify(sess, s, root, prefixes, phrases, marker)   # the transcript it was checked against (never the permanent session id: that has no jsonl)
        except _ab.BoxError as e:
            raise _box_refusal(f"said[{i}] ({s['tag']})", sess, e) from e
        who = f"said[{i}] ({s['tag']})"
        label = _session_label(sid) or sess or "the sender"
        if r["code"] == "missing":
            faults.append(f"Refused: {who}: no message {s['msg']} in the transcript of {label}; msg is the `uuid` field of his message's transcript entry, "
                          f"and session is the session he said it in (the front session when his words reached you relayed)")
            continue
        if s.get("kind") == _said.ACTED and r["code"] in ("not_queued", "not_human"):
            faults.append(f"Refused: {who}: attachment entry {s['msg']} in the transcript of {label} is not a message {OWNER} sent: {r['detail']}")
            continue
        if r["code"] in ("not_user", "tool_result", "not_human", "meta"):
            faults.append(f"Refused: {who}: message {s['msg']} in the transcript of {label} is not {OWNER}'s own: {r['detail']}")
            continue
        if r["code"] == "injected":
            faults.append(f"Refused: {who}: message {s['msg']} in the transcript of {label} is text a tool typed into the pane, not {OWNER}'s own: {r['detail']}")
            continue
        if r["code"] == "not_attachment":
            faults.append(f"Refused: {who}: entry {s['msg']} in the transcript of {label} cannot prove {OWNER} did a step: {r['detail']}")
            continue
        if r["code"] == "quote":
            faults.append(f"Refused: {who}: {r['detail']} ({'entry' if s.get('kind') == _said.ACTED else 'message'} {s['msg']} in the transcript of {label})")
            continue
        e: dict[str, Any] = {"tag": s["tag"], "quote": s["quote"], "session": sid, "msg": s["msg"], "ts": float(r["ts"] or 0), "checked": bool(r["checked"]),
                             "prompt_source": r["prompt_source"], "by": by}
        if not r["checked"]:
            e["why"] = str(r["detail"] or "")     # why it is unchecked, for the page and the reply
        if s.get("kind") == _said.ACTED:
            e["kind"] = _said.ACTED               # proof he did a step, never his words: no check of his words or decision reads it
        out.append(e)
    if faults:
        raise _faults.refusals(faults)         # one refusal for every entry that failed, each named by its place in the list
    return out


def gate_cap(item: dict[str, Any], said_l: list[dict[str, Any]], what: str, shown: str, when: float, basis: str = "") -> str:
    """The owner's rule for a wake a session sets: more than [waiting] cap_days after the item's last move (this write is one), it is refused
    unless his words are behind it (_owner_words_on). A due date is not gated: it is a deadline, not a wait.
    [waiting] cap_needs_owner = false lifts the gate. It judges the date a write stores as a wake. The date of a relay or an event wait is stored as its ask_by and is not judged, on a create or an update, unless
    the same update puts a hold on that wait; an anchored thread's wait has no exemption of its own. Only a write is gated: a date
    stored earlier is read as it is. → the words that allowed a wake past the cap ("a checked said entry" | "a board answer"), else ""."""
    h = _hooks()
    if not _wt.cap_needs_owner():
        return ""
    cap = _wt.cap_days()
    days = (when - time.time()) / 86400.0
    if days <= cap:
        return ""
    why = h.owner_words_on(item, said_l, cap)
    if why:
        return why
    if basis:                                         # a real-world date the wait stands on (wait_basis, checked by the caller): it lifts the cap for this wake
        return h.basis_words
    raise ToolError(f"Refused: a wait runs at most {cap:g} days from the item's last move ([waiting] cap_days), and this {what} ({shown}) is {days:.0f} days out. "
                    f"A longer one needs {OWNER}'s words behind it: ask {OWNER} to answer on the item (his answer there counts until the item moves again); "
                    f"or, when his words are in your own transcript on this box, pass said=[{{tag: Acked-by, quote: his sentence verbatim, msg: the uuid of his message}}] "
                    f"(checked against the transcript, a message from the last {cap:g} days); or, when the item waits for a date outside the board (a vendor's reply date, a release freeze), "
                    f"pass wait_basis=\"<what happens> YYYY-MM-DD\" with it; or set a {what} within {cap:g} days and set it again then.")


def basis_unneeded(item: dict[str, Any], wake: str, held: bool = False) -> float | None:
    """The days to `wake` when a wait_basis sent with it is not needed (the gate below would refuse it as such): an open item, a wake, no time wait held (`held` as for the gate) and the wake within
    [waiting] cap_days (or the cap off). None when the basis is needed, or when another refusal of the gate comes first (a closed item, no wake). The update tool drops such a basis and says so
    (call_log.fixed "wait-basis-dropped") instead of refusing it."""
    if item.get("status") == "completed" or not wake or held:
        return None
    cap = _wt.cap_days()
    days = (_hooks().wake_at(wake).timestamp() - time.time()) / 86400.0
    return max(days, 0.0) if (not _wt.cap_needs_owner() or days <= cap) else None


def gate_wait_basis(item: dict[str, Any], text: str, wake: str, held: bool = False) -> str:
    """The wait_basis a session gives for the wake of a time wait (a hold's window, or a verifying item's wake: `held` is true for both; the basis is the end of a wait-and-see window the work itself needs, "<what the window collects> ends
    YYYY-MM-DD", at any length) or for a wake past the cap (the owner's rule that an agent-set park needs a
    real-world date): "<what happens> YYYY-MM-DD", for the item's wake `wake` (the one this call sets, else the stored one) → the text, cleaned. Refused
    (the reasons keep it from becoming a way around the rule): a closed item, no wake date (a hold with no date is refused anyway), a date alone (no hold, on an item that is no time wait)
    within [waiting] cap_days of now (not needed: the ordinary wake does it) or more than 365 days out, a text that is too short or too long, one with a
    date that is not on the calendar, or one with no date from the wake day to 30 days after it (waiting.basis_problem). It lifts the cap for that wake only (waiting.cap_words reads it bound to the wake); a later wake drops it; the board's head lists
    these waits once a week (render.Board)."""
    h = _hooks()
    t = " ".join(str(text or "").split())
    if item.get("status") == "completed":
        raise ToolError("Refused: a completed item waits for nothing; wait_basis goes with an open item's wake")
    if not wake:
        raise ToolError("Refused: wait_basis explains the wake of a time wait (a park's or a verifying item's), or a wake past the cap, by the real-world date it waits for, and this item has no wake date. A park with no date is refused too: "
                        f"give the date (until=YYYY-MM-DD with wait_kind=\"time\", the date the outside event or {OWNER}'s words give) and the basis with it")
    cap = _wt.cap_days()
    days = (h.wake_at(wake).timestamp() - time.time()) / 86400.0
    if not held and (not _wt.cap_needs_owner() or days <= cap):
        raise ToolError(f"Refused: wait_basis is not needed: this wake ({wake}) is {max(days, 0):.0f} days out, within the {cap:g} days a wait may run "
                        "([waiting] cap_days). It is for the wake of a time wait (a park, or a verifying item), which carries a reason at any length, and for a wake past the cap; a date alone within the cap is a wait on its own and needs none")
    if days > _wt.BASIS_MAX_WAKE_DAYS:
        raise ToolError(f"Refused: wait_basis stands for a wake at most {_wt.BASIS_MAX_WAKE_DAYS} days from now, and this wake ({wake}) is {days:.0f} days out. "
                        "A wait that long is not a basis for the cap but a date to set again nearer the time")
    if not 12 <= len(t) <= 300:
        raise ToolError(f"Refused: wait_basis is one line of 12 to 300 characters, what the wait stands on and its date (\"The API token expires 2099-09-19\") — got {len(t)}")
    wake_day = h.wake_at(wake).date()
    why = _wt.basis_problem(t, wake_day)
    if why:
        day = wake_day.isoformat()
        base = t if why.startswith("it names no date") and len(t) + 11 <= 300 else "<what the wait stands on>"
        raise ToolError(f"Refused: wait_basis must name the real-world date the wait stands on as a real YYYY-MM-DD, from the wake or ask-by day ({day}) to "
                        f"{_wt.BASIS_WINDOW_DAYS} days after it: {why}. \"The vendor visits Tue 2099-03-10 14:00\" on a wake of 2099-03-10 is a basis; "
                        "a date years off, or one that is not on the calendar, is a way around the rule. "
                        f"The forms it takes are \"<what happens> YYYY-MM-DD\" and, for a window the work itself needs, \"<what the window collects> ends YYYY-MM-DD\". "
                        f"Send the same call again with wait_basis={json.dumps(f'{base} {day}', ensure_ascii=False)}, the date being the day the wait ends")
    return t


def gate_step_gap(meta: dict[str, Any], steps_new: list[dict[str, Any]], steps_old: list[dict[str, Any]]) -> None:
    """The write check of the hand-over (a session's create or update only): a step this write adds that delivers a pull request (`release PR #n`, `merge #n`, a URL) and has another session's step after it is refused
    unless it carries a proof (step_proof, or words that are all the release or merge phrase), because without one its event ticks nothing and the next session is never handed the item. A proof needs a pull
    request, which exists only once it is opened, so a step that names none is not judged. The refusal says in one line what to pass. `steps_new` is the checklist as the write leaves it, `steps_old` as it was."""
    h = _hooks()
    if not _writes.session_next():
        return
    had = {_steps.key(x["text"]) for x in steps_old if x["status"] == _steps.OPEN}
    proofs = meta.get("step_proof") if isinstance(meta.get("step_proof"), dict) else {}
    gaps = [g for g in _sp.proof_gaps(steps_new, proofs, _steps.opener, _handoff.ho_same, _steps.key, skip=lambda nm: _model.is_owner(nm) or h.handover_kind(nm) == _hv.OTHER, own=h.own_repo(),
                           released={a for r in _cfg.released_repos() for a in _cfg.repo_aliases(r)})
            if _steps.key(steps_new[g[0] - 1]["text"]) not in had]
    if gaps:
        n, ref, proof = gaps[0]
        kind = proof.split(" ", 1)[0]
        phrase = f"{_sp.VERB[kind]} {'PR ' if ref.startswith('#') else ''}{ref}"
        raise ToolError(f"Refused: step {n} ({_clip_line(_steps.first_line(steps_new[n - 1]['text']), 60)}) delivers {ref} and another session's step follows: split it so `{phrase}` is a step of its own (it ticks itself), "
                        f"or, if the PR landing finishes the step, add step_proof=[{{\"step\": {n}, \"proof\": \"{proof}\"}}]" + (" (another repository's PR: pr_merged <owner>/<repo>#<n>)" if ref.startswith("#") else "")
                        + (f" (and {len(gaps) - 1} more step{'s' if len(gaps) > 2 else ''})" if len(gaps) > 1 else ""))


# ----------------------------------------------------------------------------- registries
def registry_text() -> str:
    """The page registry file's text for the client API (`/client/registry`), with the project record's entries laid over the pages when there are any: a hook on another machine reads
    the same registry as the server does. The file's own text when no entry changes a page."""
    text = (_store.STORE / "projects.json").read_text(encoding="utf-8")
    try:
        doc = json.loads(text)
        pages = doc.get("pages") if isinstance(doc, dict) else None
        laid = _prj.with_record(pages) if isinstance(pages, dict) else pages
        return text if laid is pages else _prj.registry_json({**doc, "pages": laid})
    except Exception:  # noqa: BLE001
        return text         # a file that does not parse is served as it always was; only an unreadable one is "no registry yet"


def registry_hits(name: str, value: str) -> list[str]:
    """Every registry key the value can name, in match order (a bare slug may name projects/<slug> and infra/<slug>)."""
    reg = _registry(name)
    if name == "projects" and _prj.is_id(value):                 # a project's permanent id names its page (phase A: stored data still carries the key)
        k = _prj.id_to_key(value, reg)
        return [k] if k and k in reg else []
    return [k for k in dict.fromkeys(pat.format(value=value) for pat in _cfg.CFG["registries"][name].get("match", ["{value}"])) if k in reg]


def registry_hit(name: str, value: str) -> tuple[str | None, dict[str, Any]]:
    hits = registry_hits(name, value)
    return (hits[0], _registry(name)[hits[0]]) if hits else (None, {})



def project_subject_prefix(project: str) -> str:
    """The scope prefix a subject for `project` takes: "[<scope>] " of the project's scope when the instance has that prefix, else [subject] fallback_prefix when it is one of the prefixes;
    "" when the project does not name one record, the record has no scope, or neither applies (the subject is then refused for its missing prefix, as before)."""
    try:
        recs = _prj.refs(project, _registry("projects"))
    except Exception:  # noqa: BLE001 — a project record that cannot be read: the gate refuses the subject as it always did
        return ""
    if len(recs) != 1:
        return ""
    prefixes = list(_cfg.CFG["subject"]["prefixes"])
    fallback = str(_cfg.get("subject", "fallback_prefix") or "")
    scope = str(recs[0].get("scope") or "")
    return next((p for p in (f"[{scope}] " if scope else "", fallback) if p and p in prefixes), "")


def gate_metadata(meta: dict[str, Any], *, creating: bool) -> None:
    rules = _cfg.CFG["metadata"]
    for key, rule in rules.items():
        val = meta.get(key)
        if rule.get("required") and creating and val in (None, ""):
            raise ToolError(f"Refused: metadata.{key} is required")
        if val in (None, "", []):
            continue
        if key == "needs":                   # a list of the enum's kinds and session names, gated by gates.gate_needs
            if not isinstance(val, list):
                raise ToolError("Refused: metadata.needs is a list")
            continue
        if "enum" in rule and val not in rule["enum"]:
            raise ToolError(f"Refused: metadata.{key} must be one of {rule['enum']} — got {val!r}")
        if rule.get("format") == "YYYY-MM-DD":
            try:
                dt.date.fromisoformat(str(val))
            except ValueError:
                raise ToolError(f"Refused: metadata.{key} must be YYYY-MM-DD ({_cfg.tz_abbr()}) — got {val!r}")
        if rule.get("type") == "list" and not isinstance(val, list):
            raise ToolError(f"Refused: metadata.{key} must be a list")
        if rule.get("type") == "string" and not isinstance(val, str):
            raise ToolError(f"Refused: metadata.{key} must be a string")
        if "registry" in rule:
            hit, _ = registry_hit(rule["registry"], str(val))
            if not hit and rule["registry"] == "projects":
                # The registry is rebuilt on publish, i.e. after a successful write — so a page created minutes ago is
                # missing exactly when the first item for it arrives (a first item for a new page can arrive before
                # the pages checkout has it). Rebuild once, then re-check.
                try:
                    _pages.cmd_registry(quiet=True)
                except Exception:
                    pass
                _roles_sync_safe()                  # a new project's agents are front at once, not at the next publish
                hit, _ = registry_hit(rule["registry"], str(val))
            if not hit and rule["registry"] == "projects":
                # Fail open for a second brain ([[brains]]): a key it holds whose copy is missing or stale cannot be looked up, so it is
                # taken as written (the full key) and a warning naming the brain is logged; the board never blocks on that brain.
                want = _pages.norm(str(val))
                if _brains.skip(want, "create's page check accepts its keys unchecked") and not _prj.is_id(str(val)):
                    print(f"create: metadata.{key} = {want} is in second brain {_brains.for_key(want).name!r}, whose copy cannot be read: accepted unchecked",
                          file=sys.stderr, flush=True)
                    meta[key] = want
                    continue
            if not hit and rule["registry"] == "projects":
                # The record says the project has no page: there is no page to name, so the refusal below (which is for a page that does not exist) does not apply. The item stores
                # the project's permanent id. A project whose record points at a page that does not resolve is not this case: it is still refused.
                nopage = _prj.pageless(str(val))
                if nopage:
                    meta[key] = nopage["id"]
                    continue
            if not hit:
                reg = _registry(rule["registry"])
                known = sorted(k.split("/", 1)[1] for k in reg if k.startswith(_cfg.page_dirs()[0] + "/"))
                infra = sorted(k for k in reg if any(k.startswith(d + "/") for d in _cfg.page_dirs()[1:]))
                raise ToolError(
                    f"Refused: metadata.{key} = {val!r} names no page. Every board item belongs to a project page "
                    f"(gbrain projects/<slug>, or infra/<slug> for a machine/service item, written as the bare slug or the full key); "
                    f"create the page first, then the item. Existing project slugs: {', '.join(known)}. Infra pages: {', '.join(infra)}"
                    + (f". Where it looked: {where}." if (where := _brains.looked_in(_pages.norm(str(val)))) else "")
                )
            if rule["registry"] == "projects":
                hits = registry_hits(rule["registry"], str(val))
                if len(hits) > 1:
                    raise ToolError(f"Refused: metadata.{key} = {val!r} is ambiguous — it names {' and '.join(hits)}; write the full key")
                meta[key] = hit          # the item stores the page's full key (projects/<slug> or infra/<slug>) — the board and the hooks never guess
