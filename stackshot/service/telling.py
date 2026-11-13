"""telling.py: who is told of a write, and how the notice goes: the senders, the gate in front of a front agent, the holds, the owner's, the observers' and the keeper's notices.

A write that changes an item is told to the sessions it concerns: the mover (`tell_owner`, `tell_owner_change`, `tell_owner_close`), the observers (`tell_observers`), the sessions the item now waits on
(`tell_needed`, `tell_decided`), the front agent a hand-back or a close reaches (`tell_handback`, `tell_close_owner`), the sessions that named a closed item (`tell_close_mentions`) and the keeper of the page when a
page update is owed (`pilot_relay`, `pilot_relay_many`, `writer_charge`). Every one of them ends in `tell_woken`, the one sender: it runs the front gate (`front_gate`: a front agent hears a notice only when the owner is there
for its pane and it touched the item), holds a notice that asks nothing of a background agent (`hold_notice`, waits/held.py), pushes the rest through the delivery script (`PUSH`) and records what came back undelivered.
They moved out of server.py as they were: the same texts, the same sessions told, the same order of events. A name that service/create.py, service/update.py, service/gates.py or server.py calls on this module has lost
its leading underscore (`_tell_woken` is `tell_woken`); the helpers beside it keep theirs.

The per-write state the telling keeps on a thread (`CLOSE_WAS`, the item as it stood before the close being saved; `FRONT_HINT`, the kind the sender gives the gate; `MENTIONED`, what the last close told;
`HO_STATE`, the hand-offs the write has just recorded) lives here, and a suite that sets one sets it on this module. The thread-locals that belong to the gates (`QUESTION`, `REFORMAT`, `TERMINAL_ROW`,
`SESSION_NEXT`) live in service/writes.py.

What stays in server.py is what needs the web layer or the live pane list: the hand-off record's own functions (the pane a hand-off went to, what it said), the page keeper lookups of a project's agents, the For you
list's row keys and flags, the page debt's marks, and the time zone. They are reached through `Hooks`, which server.py fills once with `install` (this module cannot import server.py: the surface sits above it);
a hook is looked up on server.py when a notice is told, so a suite that replaces one there still reaches the telling. A suite that replaces a function of the telling patches it on this module.

Imports point down only: this module imports the domain, core and the write path (service/writes.py, service/store.py), never web/ or audit/."""
from __future__ import annotations

from dataclasses import dataclass
import datetime as dt
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from typing import Any, Callable

from fastmcp.exceptions import ToolError

from stackshot import paths as _paths
from stackshot.anchors import anchors as _anc
from stackshot.core import config as _cfg, interp as _interp, store as _store
from stackshot.core.instance import NAME, OWNER
from stackshot.core.store import _item_files
from stackshot.fleet.sessions_registry import _session_label, _sessions_index
from stackshot.github import ghsync as _gh
from stackshot.model import model as _model, nextlines as _nl
from stackshot.model.bullet_text import _clip_line
from stackshot.model.ids import _GID, _item_url
from stackshot.model.needs import _needs_kinds, _NEEDS_KINDS, _needs_list, _needs_of, _needs_sessions, _observers_of
from stackshot.model.said import _owner_words
from stackshot.router import router_live as _router_live, routing as _routing
from stackshot.service import writes as _writes
from stackshot.service.store import _load, _path
from stackshot.waits import handoff as _ho, held as _held, quiet as _frontq



@dataclass(frozen=True)
class Hooks:
    """What the telling still reaches in server.py (the hand-off record's functions, the page keepers of a project's agents, the For you list, the page debt's marks and the time zone), in the names they have
    there without the leading underscore. server.py builds one and gives it to `install`. A hook that reads a value is a function with no argument."""
    back_agent: Callable[..., Any]  # server._back_agent
    builder_for: Callable[..., Any]  # server._builder_for
    check_changed: Callable[..., Any]  # server._check_changed
    check_lane_shown: Callable[..., Any]  # server._check_lane_shown
    debt_mover: Callable[..., Any]  # server._debt_mover
    foryou_failed: Callable[[], Any]  # server._FORYOU_FAILED
    foryou_key: Callable[..., Any]  # server._foryou_key
    front_handed_by_peer: Callable[..., Any]  # server._front_handed_by_peer
    fy_flag: Callable[..., Any]  # server._fy.flag
    fy_has_key: Callable[..., Any]  # server._fy.has_key
    grace_min: Callable[..., Any]  # server._grace_min
    handoff_builder: Callable[..., Any]  # server._handoff_builder
    handoff_on: Callable[..., Any]  # server._handoff_on
    handoff_pane_row: Callable[..., Any]  # server._handoff_pane_row
    handoff_pushed: Callable[..., Any]  # server._handoff_pushed
    handoff_text: Callable[..., Any]  # server._handoff_text
    handoff_told_text: Callable[..., Any]  # server._handoff_told_text
    ho_same: Callable[..., Any]  # server._ho_same
    main_agent: Callable[..., Any]  # server._main_agent
    model_of: Callable[..., Any]  # server._model_of
    owed_mark: Callable[..., Any]  # server._owed_mark
    rmod_outcome_word: Callable[..., Any]  # server._rmod.outcome_word
    role_name: Callable[..., Any]  # server._role_name
    same_sess: Callable[..., Any]  # server._same_sess
    session_id: Callable[..., Any]  # server._session_id
    shown_needs: Callable[..., Any]  # server._shown_needs
    zone: Callable[[], Any]  # server.ZONE


_hooks_: Hooks | None = None


def install(hooks: Hooks) -> None:
    """Server.py gives the telling what it still reaches there (once, at its import)."""
    global _hooks_
    _hooks_ = hooks


def _hooks() -> Hooks:
    if _hooks_ is None:
        raise RuntimeError("the telling has no hooks installed (server.py installs them at its import)")
    return _hooks_


_FOR_OWNER = f"[for {OWNER}]"      # the mark a message to a front agent carries on its first line ("[for <owner>]" on the owner's instance), as server.py holds it


# The same ruling on the item's notices: a front agent mover (the mover, or its `then`, or the project's -main agent, never the creator) hears the owner's own answer or comment and nothing else.
# not a move to needs=decision either, since the board's "Waiting on you" (now Need your call (agents)) view is where he reads it. The reply
# line a writer gets when its write would have told the mover.
_FRONT_QUIET = "\n(its {word} {owner} is a front agent: not told; the board shows it)"


def tell_comment(gid: str, item: dict[str, Any], text: str) -> list[str]:
    """the owner's comment on GitHub, one line to the item's mover (_holder) and to every session named in its needs, each
    once. A front agent mover hears it marked for the owner (_FOR_OWNER): the mark is what reaches its Claude. The text is clipped
    to one line; the whole comment is on the item and its issue. → the session ids told."""
    h = _hooks()
    meta = item.get("metadata") or {}
    owner, project = holder(item), str(meta.get("project") or "")
    note = f"[stackshot] {OWNER} commented on {_gh.shown(gid)} on GitHub: {_clip_line(text)} → {notice_link(gid)}"
    told: list[str] = []
    oid = h.session_id(owner) if owner else ""
    if oid:
        tell_woken(gid, oid, f"{_FOR_OWNER} {note}" if front_keeper(owner, project)[0] else note, tag="comment")
        told.append(oid)
    for s in _needs_sessions(meta):
        sid = h.session_id(s)
        if sid and sid not in told:
            tell_woken(gid, sid, note, tag="comment"); told.append(sid)
    if not told:
        print(f"comment: {gid} has nobody to tell", file=sys.stderr, flush=True)
    return told


def pilot_keeper(project: str) -> tuple[str, str]:
    """Who accounts for a board change on a pilot project: the agent that keeps the item's page when the item sits on a
    sub-page with an `agent:` line (the keeper is neither charged nor told for a page an agent keeps),
    else the project's keeper. → (session name, "agent" | "name"); ("", "") outside the pilot or with nobody named."""
    try:
        if not _anc.pilot_root(project):
            return "", ""
        e = _anc.registry().get(project) or {}
        if e.get("role") == "agent" and e.get("session"):
            return str(e["session"]), "agent"
        stew = _anc.notice_name(project)
        return (stew, "name") if stew else ("", "")
    except Exception:
        return "", ""


def pilot_charge(project: str, writer: str) -> tuple[str, str]:
    """The pilot (stackshot.toml [pilot]): a state-changing board write on a pilot project
    is the page keeper's to account for. → (the keeper's session id, its role) when `writer` is not the keeper, else ("", ""). A script's
    filing (create_item with `by`) charges the keeper this returns and nobody else: no one when it returns none, and no one when the keeper
    is the owner itself (the owner is never charged for what a script filed)."""
    h = _hooks()
    who, role = pilot_keeper(project)
    if who and front_keeper(who, project)[0] and not _router_live.holds(project, who):    # a front agent keeper (a sub-page's `agent:`) is passed by: the writer owes it, the keeper past the grace; the general -main agent a nameless page's notices are addressed to is the router's, not passed by
        who, role = _anc.notice_name(project), "name"
    sid = h.session_id(who) if who else ""
    return (sid, role) if sid and sid != h.session_id(writer) else ("", "")


# Vocabulary of this file (the router rules every project, and the role the project sessions once had is
# gone): the KEEPER of a project is the session its notices fall to (_stand_in_keeper: its builder, else its -main agent; for a page with
# no agent of its own its hub's, else the scope's general -main agent), and a notice that would have gone to the page's `display-name:`
# session is held for the router (router_live.holds). Text a session or the owner reads says keeper, builder or router.
def stand_in_keeper(project: str, reg: dict[str, Any] | None = None) -> str:
    """The keeper of a project, where the page's `display-name:` session used to be written to: its builder (a background agent whose mandate says build, maintain,
    merge or engineer), else its -main agent; for a page with no user-facing agent of its own, its hub's -main agent, else the general
    -main agent of its scope (router_live.stand_in, anchors.general_main). "" for a key that names no page."""
    return _router_live.stand_in(project, reg)


def page_keeper(project: str, reg: dict[str, Any] | None = None) -> str:
    """The keeper an item's project answers to. A project whose page or hub lists a user-facing agent: its stand-in (builder, else -main).
    A one-session page (a name-line session, no agents map; none on its hub either): that session, as before, not the general -main agent,
    which is for the router's passes alone (the owner); else the name line of its hub or top-level page. "" when the project has
    none (its mover then hears what a keeper would)."""
    try:
        reg = _anc.registry() if reg is None else reg
        if _anc.has_front(project, reg):
            return stand_in_keeper(project, reg)
        root = _anc.pilot_root(project)
        return (_anc.name_line(root, reg) if root else "") or _anc.name_line(_anc.hub_of(project, reg), reg) or _anc.name_line("/".join(str(project).split("/")[:2]), reg) or ""
    except Exception:
        return ""


def project_keeper(project: str, owner: str = "") -> str:
    """Who hears an item's notices when its needs names no session and nothing else names one (the whole board): the keeper of its page (a
    sub-page's `agent:`, unless that is a front agent), else the keeper of its pilot root or of its hub, else the project's builder, else its
    -main agent, else, for a mover that is a front agent, that mover's keeper, else the mover itself (`owner` here is the item's mover, never its creator). → a session name or id, "" when none is named."""
    try:
        reg = _anc.registry()
        e = reg.get(str(project or "").strip().strip("/")) or {}
        if e.get("role") == "agent" and e.get("session") and not front_keeper(str(e["session"]), project)[0]:
            return str(e["session"])
    except Exception:
        reg = None
    return page_keeper(project, reg) or fallback_mover(project) or (front_keeper(owner, project)[1] if owner else "") or owner


FALLBACK_CACHE: dict[str, tuple[int, float, str]] = {}


CLOSE_WAS = threading.local()      # the item as it stood before the close being saved on this thread: a close drops mover and then, and the close is told to the mover


def fallback_mover(project: str) -> str:
    """the session that moves, and hears the notices of, an item nothing else names: the project's builder (the background agent whose mandate builds; for a page
    [handoff.builder_by_page] maps, the mapped builder when the project lists it: _builder_for), else its -main agent, never the item's creator. "" when the project names neither. Cached for a few seconds per project and registry version: the board derives every item's mover."""
    h = _hooks()
    key = str(project or "").strip()
    if not key:
        return ""
    try:
        ver = os.stat(_anc.REGISTRY).st_mtime_ns
    except OSError:
        ver = 0
    now = time.monotonic()
    hit = FALLBACK_CACHE.get(key)
    if hit and hit[0] == ver and now - hit[1] < 20.0:
        return hit[2]
    who = h.builder_for(key) or h.main_agent(key)
    if not who:
        try:
            who = page_keeper(key)        # a page that lists no -main agent but names its keeper (`session:`, the -main agent of a page not yet converted)
        except Exception:  # noqa: BLE001
            who = ""
    FALLBACK_CACHE[key] = (ver, now, who)
    return who


def held_by(item: dict[str, Any], was: dict[str, Any] | None = None) -> tuple[str, str]:
    """the one session an item's notices go to, and the word for why → (session, "mover" | "then"): the item's mover; when its mover is the owner, its `then`; when it has neither,
    the project's builder, else its -main agent (which the model already names as the default mover). A closed item has no mover left (a close drops it), so `was`, the item as it stood
    before the close, is read instead. The creator (metadata.owner) is a fact of the History and holds no part here. ("", "mover") when no session can be named."""
    h = _hooks()
    if was is None and item.get("status") != "open":
        w0 = getattr(CLOSE_WAS, "item", None)
        if isinstance(w0, dict) and str(w0.get("id") or "") == str(item.get("id") or "x"):
            was = w0
    src = was if (was is not None and item.get("status") != "open") else item
    meta = src.get("metadata") or {}
    cands: list[tuple[str, str]] = []
    try:
        if src.get("status") == "open":
            mod = h.model_of({**src, "gid": src.get("gid") or src.get("id") or ""})
            if mod.state == _model.ALIVE:
                cands = [(mod.mover, "mover"), (mod.then, "then")]
            elif mod.wait:      # a waiting item: the post-wake mover when the writer named one, else the stored mover / `then` (it relays), else the model's default for who takes it after the wait.
                # The order is the one the hand-over writers (_hand_stored_then, _decision_hand_over, _release_after) still use: they hand to the stored `then`, so the reader must find the same session.
                cands = [(_model.norm_who(meta.get("post_wake_mover")), "then"), (_model.norm_who(meta.get("mover")), "mover"), (_model.norm_who(meta.get("then")), "then"), (mod.wait.mover, "then")]
    except Exception:  # noqa: BLE001  — a notice's addressee is never worth failing a write over
        cands = []
    cands += [(_model.norm_who(meta.get("mover")), "mover"), (_model.norm_who(meta.get("then")), "then")]      # a stored mover or `then` still holds an item that waits on someone outside (it relays; it is told when the wait ends)
    for who, word in cands:
        if who and not _model.is_owner(who):
            return who, word
    return fallback_mover(str(meta.get("project") or "")), "mover"


def holder(item: dict[str, Any], was: dict[str, Any] | None = None) -> str:
    """The session an item's notices go to (_held_by): "" when none can be named."""
    return held_by(item, was)[0]


def quiet_line(item: dict[str, Any], owner: str = "") -> str:
    """The reply line that says a front agent holding the item (its mover, else its `then`) is not told: the board shows it. `owner` = the session when the caller has it."""
    who, word = held_by(item)
    return _FRONT_QUIET.format(word=word, owner=_session_label(owner or who))


_HELD_LINE = re.compile(r"\n\(its (?:mover|then) ")


def then_label(item: dict[str, Any]) -> str:
    """The item's `then` (stored, else the model's) as a session label; "" when it has none or it is the owner."""
    h = _hooks()
    try:
        mod = h.model_of({**item, "gid": item.get("gid") or item.get("id") or ""})
        who = mod.then if mod.state == _model.ALIVE else ((mod.then if _model.is_owner(mod.wait.mover) else mod.wait.mover) if mod.wait else "")
    except Exception:  # noqa: BLE001
        who = _model.norm_who((item.get("metadata") or {}).get("then"))
    return "" if (not who or _model.is_owner(who)) else (_session_label(who) or who)


def then_part(item: dict[str, Any]) -> str:
    """", then <session>" for a notice that names who takes the item after the owner; "" when it has no `then` (the notice names no creator)."""
    t = then_label(item)
    return f", then {t}" if t else ""


def keeper_words(project: str, keeper: str) -> str:
    """How a notice names the keeper's standing: "the keeper of projects/alpha" when it keeps the item's project, else
    "the keeper of its page (projects/alpha/sub)"."""
    try:
        nm = _anc.names()
        if _anc.canonical(keeper, nm) == _anc.canonical(page_keeper(project), nm):
            return f"the keeper of {project}"
        roles = _anc.session_roles()
        r = roles.get(keeper) or roles.get(_session_label(keeper)) or roles.get(_anc.canonical(keeper, nm)) or {}
    except Exception:
        r = {}
    return f"the keeper of {r.get('project') or project}" if r.get("role") == _anc.NAME_ROLE else f"the keeper of its page ({project})"


def notice_to(meta: dict[str, Any]) -> list[tuple[str, str]]:
    """The sessions an item's notices go to → [(session id, why)]: the sessions named in its needs, else its mover or its `then` or, with neither, the project's builder, else its
    -main agent (_holder: never the creator). `why` is the words for the notice: "as a session named in its needs" | "as its mover" | "as its then"."""
    h = _hooks()
    out: list[tuple[str, str]] = []
    for s in _needs_sessions(meta):
        sid = h.session_id(s)
        if sid and sid not in [x for x, _w in out]:
            out.append((sid, "as a session named in its needs"))
    if out:
        return out
    who, word = held_by({"status": "open", "metadata": meta})
    kid = h.session_id(who) if who else ""
    return [(kid, f"as its {word}")] if kid else []


def front_keeper(who: str, project: str = "", strict: bool = False, unread_front: bool = False) -> tuple[bool, str]:
    """is `who` (a name or a transcript id) a front agent, by anchors.session_roles() (which roles.json builds on)? → (True, the
    keeper of `project`, else of the project it is front in: notice_name or keeper, as _gate_front finds it; "" when none),
    or (False, "") for a back agent, a keeper or a session with no role, and for the keeper of `project` itself even when
    session_roles ranks it front for another page. `strict` (the queue rule's: model/queued.py) answers (True, "") for any session whose role is front, the keeper of `project` included, and when the roles cannot be read, where the default answers False.
    `unread_front` (the hourly audit's: audit/hourly.py) keeps the default's answers for a role map that was read, and answers (True, "") when it was not (an error, or no role at all: the registry reads {} when its file cannot be read), so an unreadable registry is no proof that the session is a builder."""
    h = _hooks()
    try:
        roles = _anc.session_roles()
        if unread_front and not roles:
            return True, ""
        name = h.role_name(roles, who)
        if not name or roles[name]["role"] != "front":
            return False, ""
        if strict:
            return True, ""        # the queue rule asks only whether the session is a front agent: the keeper of the project is one too
        root = _anc.pilot_root(project) if project else ""
        own = (_anc.name_line(root) if root else _anc.name_line(project)) if project else ""      # the page's name line only (a sub-page's own `session:` is its agent: keeper, never the project's keeper): the fallback -main agent a nameless page's notices go to is no keeper, and it is front
        if own and h.session_id(own) == h.session_id(who):     # the keeper of this item's project is its keeper here, front elsewhere or not
            return False, ""
        for p in (project, roles[name]["project"]):
            stew = (page_keeper(p) or _anc.name_line(p)) if p else ""     # the page's keeper (_page_keeper: the stand-in of a page that lists agents, a one-session page's own session), not the retired name-line session
            if stew and h.session_id(stew) == h.session_id(who):
                return True, ""        # the stand-in is this front agent itself: it tells nobody about its own
            if stew:
                return True, stew
        return True, ""
    except Exception:
        return (True, "") if (strict or unread_front) else (False, "")


def front_sender(who: str) -> bool:
    """Is `who` (a name or a transcript id) a front agent by anchors.session_roles(), the test the message tool's front gate uses (_gate_front)? A session
    no page lists, a background agent and the owner are not: the watch rule fails open (one stderr line when the check itself fails)."""
    h = _hooks()
    who = str(who or "").strip()
    if not who or _model.is_owner(who):
        return False
    try:
        roles = _anc.session_roles()
        name = h.role_name(roles, who)
        return bool(name) and roles[name]["role"] == "front"
    except Exception as e:  # noqa: BLE001  — the rule is an extra: a failure in it lets the write through
        print(f"watch rule: front test of {who} failed ({e.__class__.__name__}: {e}); the write passes", file=sys.stderr, flush=True)
        return False


# ---- a front agent is no channel to the owner for an item's moves
# Two rules. (1) A return or fallback that stackshot makes itself (the hand-off ladder's return to the sender, the cold call's pick, the fallback mover a stepped answer or an
# ended wait lands on) never goes to a front agent: the item goes to the project's builder; a project without one keeps the item with its current mover. What
# The owner or a session sets explicitly (a mover, a `then`) is left as written. (2) A notice about an item reaches a front agent only when the owner is there for that pane (he typed in
# it within [presence] minutes: a stamp file the prompt hook writes) AND the agent touched the item in its current conversation; a progress notice then rides his next turn (fyi),
# a close or a stuck item is told as a turn (the [for <owner>] mark on one stackshot sends itself exempts nothing), everything else is held and logged. Messages a session sends on
# purpose through the message tool are not touched.
PRESENCE_MINUTES = 30.0


FRONT_TAG_KIND = {"answer": "exempt", "handoff": "exempt", "migration": "exempt", "recycle": "exempt", "needs": "exempt",
                   "wake": "exempt", "watch": "exempt", "idle": "exempt", "wait": "exempt", "comment": "exempt", "stall": "exempt", "release": "exempt", "ask": "exempt", "balance": "exempt",      # these ask the mover to act (its own timer fired, a wait ended, the owner commented): held, the item would sit unmoved
                   "close": "close", "check": "close",      # a notice's tag names its kind unless the sender passes one
                   "owner": "progress", "observer": "progress"}      # news about the item: progress (named here so a new, unmapped tag is a decision the tag-coverage test catches)


FRONT_HINT = threading.local()      # the kind the sender gives the gate for the one notice it is telling (see _tell_kind)


def tell_kind(kind: str, *args: Any, **kw: Any) -> "threading.Thread | None":
    """_tell_woken for a sender that knows what kind of notice it tells a front agent (progress | close | stuck | exempt); the hint lasts for this call only, so
    _tell_woken keeps its signature (the tests replace it)."""
    old = getattr(FRONT_HINT, "kind", "")
    FRONT_HINT.kind = kind
    FRONT_HINT.result = ("", "")
    try:
        return tell_woken(*args, **kw)
    finally:
        FRONT_HINT.kind = old


def gate_result() -> tuple[str, str]:
    """what the gate did with the last notice _tell_kind told on this thread: ("", "") sent as ever (or a recipient that is no front agent), ("fyi", "") filed to ride his next
    turn, ("held", why) nobody is told. A sender words its reply line from it, so a line never says "told" of a notice the gate held. (_tell_woken returns None for a held notice, but a
    test's stand-in returns None too, so the verdict is read here.)"""
    return getattr(FRONT_HINT, "result", ("", ""))


def no_front(who: str, project: str) -> str:
    """`who` unless it is a front agent, then the project's builder (_handoff_builder: a list of one, or none), "" when the project has none."""
    h = _hooks()
    if not who or not front_sender(who):
        return who
    b = h.handoff_builder(project)
    return b[0] if b else ""


def auto_mover(who: str, project: str) -> str:
    """a mover stackshot picks by itself (a fallback, never one a session or the owner wrote): `who`, moved to the project's builder when `who` is a front agent. A project
    with no builder keeps `who`: the item (his answer, an ended wait) has no other holder to stay with, and it is the item model's own default."""
    return no_front(who, project) or who


def presence_minutes() -> float:
    try:
        raw = _cfg.get("presence", "minutes", default=PRESENCE_MINUTES)
        v = float(raw)
        return v if v > 0 and not isinstance(raw, bool) else PRESENCE_MINUTES      # a value that is no number above 0 reads as 30; config.notes() says so (start, reload)
    except (TypeError, ValueError):
        return PRESENCE_MINUTES


def presence_here(who: str, now: float | None = None, idx: dict[str, Any] | None = None) -> bool:
    """is the owner there for this pane: the stamp file <state>/prompts/<session id> (written by the prompt hook of the config repo; stackshot only reads it) holds epoch seconds
    within [presence] minutes. The pane's session id comes from the CLI registry (_handoff_pane_row: ~/.claude/sessions/<pid>.json). A pane this box does not run, a missing, empty or
    unreadable file, a stamp from the future or an old one: not there."""
    h = _hooks()
    try:
        row = h.handoff_pane_row(who, idx)
        sid = str((row[1] if row else {}).get("sessionId") or "")
        if not sid or "/" in sid or sid.startswith("."):
            return False
        ts = float(_cfg.state("prompts", sid).read_text(encoding="utf-8").strip().split()[0])
        now = time.time() if now is None else now
        return 0 <= now - ts <= presence_minutes() * 60.0
    except Exception:  # noqa: BLE001  — no stamp, no presence
        return False


def _stamped_at(v: dict[str, Any]) -> float:
    """When a revision's writer stamp (`written_by`, `written_by_id`) was written: `written_at`, which only a write by a session or the owner sets (`writes.record_writer`); a revision from before
    that field has `updated`. A server save with no writer moves `updated` and leaves the stamp (and `written_at`) as the last real writer left them, so it is never a touch."""
    try:
        return float(v.get("written_at") or v.get("updated") or 0)
    except (TypeError, ValueError):
        return 0.0


def writers_since(gid: str, since: float) -> list[tuple[str, str]]:
    """The (name, id) every revision of the item whose writer stamp (`written_by`, `written_by_id`) was written at or after `since` (_stamped_at; a git revision committed after `since` that
    only carries an older stamp, a server save, does not count): the file on disk, then the store's git revisions (one `git log` and one `git cat-file --batch`, as render.item_versions
    reads them; a store outside git adds none)."""
    out: list[tuple[str, str]] = []
    try:
        it = _load(gid)
        if _stamped_at(it) >= since:
            out.append((str(it.get("written_by") or ""), str(it.get("written_by_id") or "")))
    except Exception:  # noqa: BLE001
        pass
    try:
        p = _path(gid)
        lg = subprocess.run(["git", "-C", str(_store.STORE), "log", f"--since={int(since)}", "--name-only", "--format=%x01%H", "--", str(p)], capture_output=True, timeout=10)
        if lg.returncode:
            return out
        want = []
        for chunk in lg.stdout.decode("utf-8", "replace").split("\x01")[1:]:
            head, _, rest = chunk.partition("\n")
            path = next((x.strip() for x in rest.splitlines() if x.strip()), "")
            if head.strip() and path:
                want.append(f"{head.strip()}:{path}\n")
        if not want:
            return out
        buf = subprocess.run(["git", "-C", str(_store.STORE), "cat-file", "--batch"], input="".join(want[:60]).encode(), capture_output=True, timeout=10).stdout
        i = 0
        while i < len(buf):
            nl = buf.find(b"\n", i)
            if nl < 0:
                break
            hdr = buf[i:nl].split()
            i = nl + 1
            if len(hdr) < 3 or hdr[1] != b"blob":
                continue
            n = int(hdr[2])
            try:
                v = json.loads(buf[i:i + n].decode("utf-8", "replace"))
                if _stamped_at(v) >= since:
                    out.append((str(v.get("written_by") or ""), str(v.get("written_by_id") or "")))
            except Exception:  # noqa: BLE001
                pass
            i += n + 1
    except Exception:  # noqa: BLE001
        pass
    return out


def touched(gid: str, who: str, since: float) -> bool:
    """did this session write the item in its current conversation: one of the item's revisions since the pane's process started (the CLI registry's startedAt, which a
    relaunch, a resume or a recycle moves) names it as the writer, as the item's History shows it. `gid` may name several items (a batched notice): any one counts. No start time
    (`since` of 0 or less) is never a touch: every write since the epoch would count, so it fails closed, as presence does."""
    h = _hooks()
    if not since or since <= 0:
        return False
    for g in [x for x in re.split(r"[,\s]+", str(gid or "")) if _GID.match(x)]:
        for name, wid in writers_since(g, since):
            if (wid and h.same_sess(wid, who)) or (name and h.same_sess(name, who)):
                return True
    return False


def front_verdict(gid: str, owner: str, kind: str) -> tuple[str, str]:
    """what a notice about an item does when it is for a front agent: ("send", "") as ever, ("fyi", "") rides its next turn, ("hold", why) nobody is told (logged)."""
    h = _hooks()
    idx = _sessions_index()
    row = h.handoff_pane_row(owner, idx)
    if not row:
        return "hold", "its pane is not on this box"
    if not presence_here(owner, idx=idx):
        return "hold", f"{OWNER} is not there for its pane ({presence_minutes():g} min)"
    try:
        since = float(row[1].get("startedAt") or 0) / 1000.0
    except (TypeError, ValueError):
        since = 0.0
    if since <= 0:
        return "hold", "its start time is not on record, so what it touched cannot be told"      # fails closed, like presence
    if not touched(gid, owner, since):
        return "hold", "it did not touch the item in this conversation"
    return ("send", "") if kind in ("close", "stuck") else ("fyi", "")


def _front_board_line(gid: str, owner: str, told: bool, why: str, note: str) -> list[str]:
    """The news of a progress notice for a front agent goes onto the
    item in the same pass, whether the notice is passed on or held: one History line (`metadata.front_quiet.log`, quiet.py), written by the server (no writer, no clock moves, nothing
    posted to the issue). A close and a stuck mark need none: the close is the item's own revision, and a stuck mark (metadata.wait_failed, a wait that can no longer end) is
    written before its notice is told. A closed item gets none (its close is the record). → the ids written. Never raises."""
    out: list[str] = []
    try:
        label = _session_label(owner) or str(owner)
        text = _frontq.line(label, told, why, note)
        for g in [x for x in re.split(r"[,\s]+", str(gid or "")) if _GID.match(x)][:5]:
            with _writes.ITEM_LOCK:
                it = _load(g)
                if it.get("status") != "open":
                    continue
                meta = dict(it.get("metadata") or {})
                if _frontq.note(meta, time.time(), text):
                    it["metadata"] = meta
                    _writes.save(g, it, note="a front agent's notice: " + ("told on his next turn" if told else "not told"))
                    out.append(g)
    except Exception as e:  # noqa: BLE001  — the line is a record; the gate's verdict stands without it
        print(f"front gate: {gid} board line not written: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    return out


def _front_held_log(gid: str, owner: str, kind: str, reason: str, note: str) -> None:
    """the routing-log line (ruled `held` by stackshot (auto)) for a notice a front agent was not told. Never raises."""
    try:
        proj = _hold_project(owner, gid)
        if proj:
            _routing.record_auto(proj, "held", reason, kind="board", label=f"{kind} {gid}".strip(), who=NAME, text=note,
                                 target="for " + (_session_label(owner) or str(owner)), pilot=bool(_anc.pilot_root(proj)))
    except Exception as e:  # noqa: BLE001  — the log line is a record
        print(f"front gate: {gid} not logged: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)


def front_gate(gid: str, owner: str, note: str, tag: str, kind: str) -> bool:
    """the one gate every item notice passes in _tell_woken. → True when the notice was handled here (held, or filed as an fyi line) and must not be pushed. False: send it as ever.
    Not gated: a recipient that is no front agent, a kind of "exempt" (his board answer relayed, a hand-off, a migration, a recycle, a notice that asks the mover to act). The [for <owner>]
    mark does not exempt a notice: a close or a stuck notice stackshot itself sends carries it, and takes a turn of its own only under presence plus touched. A message a session sends
    on purpose goes through the message tool, which does not pass here.
    A tag the map does not know is a progress notice (held when he is away); tests/front_quiet_scenario.py fails on a tag passed to the gate that the map lacks."""
    kind = kind or FRONT_TAG_KIND.get(tag, "progress")
    FRONT_HINT.result = ("", "")
    if kind == "exempt" or not front_sender(owner):
        return False
    try:
        verdict, why = front_verdict(gid, owner, kind)
        if verdict == "send":
            return False
        fyi_ok = verdict == "fyi" and _held.enabled() and _held.can_fetch(owner)
        if fyi_ok:
            fyi_ok = _held.add(_held.key_of(owner), "fyi", note, sender=NAME, gid=gid)
        if verdict == "fyi" and not fyi_ok:
            why = "its hook cannot fetch held lines, and a new turn is not worth it"
        reason = f"held: front agent, rides {OWNER}'s next turn (fyi, {kind})" if fyi_ok else f"held: front agent, {why} ({kind})"
        FRONT_HINT.result = ("fyi", "") if fyi_ok else ("held", why)
        if kind == "progress":
            _front_board_line(gid, owner, fyi_ok, why, note)      # the board keeps the news whether or not the pane hears it
        _front_held_log(gid, owner, kind, reason, note)
        return True
    except Exception as e:  # noqa: BLE001  — the gate is an extra: a failure in it sends the notice as before
        print(f"front gate: {gid} notice to {owner} sent as before: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return False


def notice_link(gid: str) -> str:
    """the link a notice pushed to a session (and its routing-log line) carries to its item: the item's page, as the item
    is shown (board#N → <board_url>/items/<n>, a temporary id → /items/board-tmp-<machine>-<n>, ghsync.href_id through
    _item_url), never the board card's anchor (#task-g-7), which spells the store id. The id the notice names is
    ghsync.shown(gid)."""
    return _item_url(gid) or f"/items/{_gh.href_id(gid)}"


def tell_close_owner(gid: str, item: dict[str, Any], owner: str, project: str, writer: str, by: str = "") -> str:
    """A close with his own words on the item (_owner_words) was the one close a front agent mover was told,
    in one line. It is a row on his For you list now, instead of a message to a front
    agent, which cost that agent a turn and him a place in a chat. The row is made when the close is saved (_foryou_on_save, which
    also holds the muted and unwatched rules), so nothing is delivered here; this only says whether the row exists, for the writer's
    reply line. The front agent mover is told of any close by another session all the same, in its own
    message (_tell_owner_close), so it need not set a far wake and wait; the row for his words is unchanged. The router's `close-words` rule stays for a notice recorded before this change (it rules it merged). → what shows his
    words ("" = no row: no words on the item, or the item is muted)."""
    h = _hooks()
    signal = _owner_words(item)
    if not signal:
        return ""
    key = h.foryou_key(gid, "closed", item)
    if h.fy_has_key(key):
        return signal
    if key in h.foryou_failed():           # the row could not be written (the list's file, the disk): the close must still reach someone
        h.foryou_failed().discard(key)
        if close_owner_notice(gid, item, owner, project, writer, by, signal):
            _FORYOU_FELL.add(key)
            if len(_FORYOU_FELL) > 500:
                _FORYOU_FELL.clear()
            return signal
    return ""


_FORYOU_FELL: set[str] = set()          # keys of closes told to the mover the old way because their row could not be written


def close_owner_notice(gid: str, item: dict[str, Any], owner: str, project: str, writer: str, by: str, signal: str) -> bool:
    """The way a close with his words was told to a front agent mover before the For you list, kept as the fallback for a row that could
    not be written. It is delivered at once with the mark (_FOR_OWNER), router live or not: the router's close-words rule now rules a
    recorded close merged, so a notice left to the router would reach nobody. → True when it was sent."""
    h = _hooks()
    meta = item.get("metadata") or {}
    who, olabel, subject = by or _session_label(writer) or "a session", _session_label(owner), str(item.get("subject") or "")
    outcome, sup, reason = str(meta.get("outcome") or "done"), str(meta.get("superseded_by") or ""), _clip_line(meta.get("reason"), 240)
    line = (f"[stackshot] {_gh.shown(gid)} closed by {who} ({outcome}{' by ' + _gh.shown(sup) if sup else ''}): {subject}"
            + (f" — {reason}" if reason else "") + f" → {notice_link(gid)}")
    try:
        tell_kind("close", gid, h.session_id(owner), f"{_FOR_OWNER} {line}", tag="owner")      # a close takes a turn only under presence plus touched; held, its news is the close revision
        return True
    except Exception as e:  # noqa: BLE001
        print(f"for-you: {gid} fallback notice to {olabel} failed: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return False


def tell_owner(gid: str, item: dict[str, Any], what: str, writer: str, decision: bool = False, heard: list[str] | None = None, close: bool = False, to: str = "") -> str:
    """on a pilot project, the item's mover (its mover, else its `then`, else the project's builder, else its -main agent; never the creator; `to` names it when the caller knows who it was before the write) hears what another session did to its item that it must know: a move to
    needs=decision (with the ask and its options), a completion, a reopen. a mover that is a front agent hears none of
    these itself; a completion or a reopen goes unmarked to the project's keeper instead, which passes it on only if it needs
    the owner. One the keeper made itself is told to nobody (an earlier rule used to tell
    the mover plainly, which woke its pane for nothing he had to do); the board shows it. A move to
    decision (`decision`) is told to nobody either, neither the front agent mover (it used to hear it marked with _FOR_OWNER)
    nor its keeper: the board's "Waiting on you" (now Need your call (agents)) view is where he reads it. `heard`, when given, gets the mover's id appended
    when the mover itself was told (not its keeper instead), and when a front agent mover is passed by on a move to decision,
    so a "now needs you" or quiet line in the same write does not double it. → the writer's reply line, or "" (no mover, or the
    mover wrote it). A close (`close`) with his own words on the item (_owner_words) was the one thing
    a front agent mover was told; it is a row on his For you list instead (_tell_close_owner says so in the
    reply line); its keeper is told as before. This function still tells a front agent mover nothing itself;
    the mover's own line for a close by another session (with his words or not) is _tell_owner_close's."""
    h = _hooks()
    if getattr(_writes.TERMINAL_ROW, "on", False):      # a terminal-prompt row (a script's notification of its own) tells no session
        return ""
    meta = item.get("metadata") or {}
    owner, project = to or holder(item), str(meta.get("project") or "")
    word = held_by(item)[1]
    if not owner or not _anc.pilot_root(project) or h.session_id(owner) == h.session_id(writer):
        return ""
    who = _session_label(writer) or "a session"
    note = f"[stackshot] {_gh.shown(gid)} {what} by {who}: {item.get('subject') or ''} → {notice_link(gid)}"
    front, stew = front_keeper(owner, project)
    if front and decision:                 # the board shows it; nobody is told
        if heard is not None:
            heard.append(h.session_id(owner))   # its quiet line is this one: _tell_needed leaves the mover out of the same write
        return quiet_line(item, owner)
    if front:
        words = tell_close_owner(gid, item, owner, project, writer) if close else ""       # a close with his words on it is the one thing a front agent mover hears
        row_note = f"{OWNER}'s words are on it ({words}), so it is a row on his For you list"     # no "not told;" in it: the mover's part is settled (_owner_reached); the mover itself is told by _tell_owner_close
        if words and h.foryou_key(gid, "closed", item) in _FORYOU_FELL:
            row_note = f"{OWNER}'s words are on it ({words}), but the For you list could not be written, so the old notice marked {_FOR_OWNER} was sent to {_session_label(owner)} instead"
        if not stew or h.session_id(stew) == h.session_id(writer):
            return f"\n(its {word} {_session_label(owner)} is a front agent: {row_note})" if words else quiet_line(item, owner)
        tell_kind("close" if close else "progress", gid, h.session_id(stew), f"[stackshot] {_gh.shown(gid)} ({word} {_session_label(owner)}, a front agent) {what} by {who}: {item.get('subject') or ''} → {notice_link(gid)}", tag="owner")
        res, why = gate_result()      # the gate may have held it, or filed it for his next turn there: the reply says what became of it
        klabel = _session_label(stew)
        tail = (f"its keeper {klabel} was not told ({why}); the board carries it" if res == "held" else f"its keeper {klabel} hears of it on his next turn" if res == "fyi"
                else f"its keeper {klabel} has been told {'too' if words else 'instead'}")
        return f"\n(its {word} {_session_label(owner)} is a front agent: " + (f"{row_note}; " if words else "") + tail + ")"
    else:
        tell_or_hold(gid, h.session_id(owner), note, "closed" if _done_close(what) and not _owner_words(item) else "", tag="owner")      # a plain completion asks a background mover nothing; a dropped or superseded one tells it to stop
    if heard is not None:
        heard.append(h.session_id(owner))
    return f"\n(its {word} {_session_label(owner)} has been told)"


def tell_observers(gid: str, item: dict[str, Any], what: str, writer: str) -> str:
    """an item's observers hear a close or a reopen, one line each, unmarked; a front agent observer hears it through its
    project's keeper. Neither the writer nor the item's mover (told by _tell_owner) is told here. → the writer's reply line, or ""."""
    h = _hooks()
    if getattr(_writes.TERMINAL_ROW, "on", False):      # a terminal-prompt row (a script's notification of its own) tells no session
        return ""
    meta = item.get("metadata") or {}
    owner, project = holder(item), str(meta.get("project") or "")
    wid, oid = h.session_id(writer), h.session_id(owner) if owner else ""
    who = _session_label(writer) or "a session"
    told, sent = [], set()
    try:
        roles = _anc.session_roles()
    except Exception:
        roles = {}
    for ob in _observers_of(meta):
        sid = h.session_id(ob)
        if not sid or sid in (wid, oid) or sid in sent:
            continue
        r = roles.get(h.role_name(roles, ob)) or {}
        front = r.get("role") == "front"
        stew = page_keeper(str(r.get("project") or project)) if front else ""   # its own project's keeper (the spec's words), not the item's
        if front:
            if not stew or h.session_id(stew) in (wid, sent):
                continue
            sent.add(h.session_id(stew))
            tell_kind("close" if str(what).startswith("was completed") else "progress", gid, h.session_id(stew), f"[stackshot] {_gh.shown(gid)} (observer {_session_label(ob)}, a front agent) {what} by {who}: {item.get('subject') or ''} "
                                                f"→ {notice_link(gid)} — pass it on only if it needs {_session_label(ob)}", tag="observer")
            if gate_result()[0] != "held":      # held by the gate: not told
                told.append(f"{_session_label(stew)} for {_session_label(ob)}")
        else:
            sent.add(sid)
            tell_or_hold(gid, sid, f"[stackshot] {_gh.shown(gid)} {what} by {who}: {item.get('subject') or ''} → {notice_link(gid)} (you observe it)",
                          "closed" if _done_close(what) and not _owner_words(item) else "", tag="observer")
            told.append(_session_label(ob))
    return f"\n(observers told: {', '.join(told)})" if told else ""


# The mover hears what another session changed (a defect fix: a builder set `next` on an item another session moved,
# and a session other than its mover closed one, and the mover learned of it only at the audit). One short notice per item per mover per window; the
# window is kept in memory (a restart forgets it, at worst one extra notice), and a close is never held back by it.
OWNER_HEARD: dict[tuple[str, str], float] = {}


_OWNER_HEARD_WINDOW = 600.0


def tell_owner_on() -> bool:
    """[board] tell_owner: whether the mover is told of another session's change (true when unset). Read where used (live)."""
    v = _cfg.get("board", "tell_owner")
    return v if isinstance(v, bool) else True


def _owner_is_session(owner: str) -> bool:
    """Is the item's mover a session that can be told: an id (cse_… or a transcript uuid), or a name the fleet or a page's roles know.
    the owner (the instance owner, as _sender_not_owner reads the name), an outside party's name and an empty mover are not."""
    o = str(owner or "").strip()
    if not o:
        return False
    norm = lambda x: re.sub(r"[^0-9a-z]+", " ", str(x or "").lower()).strip()
    if norm(o) in {norm(OWNER), norm(OWNER) + " board"}:
        return False
    if _anc.is_id(o):
        return True
    try:
        return o in set(_anc.names().values()) or o in _anc.session_roles()
    except Exception:
        return False


def owner_reached(text: str, relayed: bool) -> bool:
    """Did a reply line of _tell_owner (or of _auto_name, which carries it) say the mover was reached this write? Its "not told; the board
    shows it" line for a front agent mover counts only when the write also went to the project's keeper or router (`relayed`: _pilot_relay),
    where the mover's part is ruled; otherwise nobody got it and _tell_owner_change hands it to the page key."""
    return bool(_HELD_LINE.search(text)) and ("not told;" not in text or relayed)


def tell_owner_change(gid: str, item: dict[str, Any], before: dict[str, Any], writer: str, closing: bool, handled: bool, relayed: bool = False, reopening: bool = False) -> str:
    """The mover hears one short line when another session closes its item or changes its next, needs, check or after (a filing edit
    sends nothing). A session mover is pushed to through _tell_woken like the other board notices. A front agent mover
    is not messaged itself (the mark is for what the owner has to do) and the router rules a project's notices, so the line goes to the item's project
    page key as a message, where the router rules it like any inbound (the stand-in), saying the mover may need to act. One event makes one inbound there: nothing goes to the page key when the
    write already reached the project's keeper or router (`relayed`, _pilot_relay), when the writer is itself the project's keeper,
    keeper or stand-in, when the project has none of them (quietly), or when the routing record cannot be written (logged); the page
    key's delivery is built here, not through _message, which would name the stand-in builder in the item's needs. Not when the mover
    is the owner or not a session, when the writer is the mover, or when `handled` (_tell_owner, the server's naming of the writer, or a
    needs notice already told it this write, or _tell_owner_close, which tells a front agent mover of a close by another session, the owner).
    Otherwise a front agent is never pushed to by this notice: when the page key's target is a front agent (the
    stand-in of a project is its -main agent) or the mover itself, and when the write moves a front agent
    mover's item to needs=decision (the board shows it), nothing is pushed and the reply says so. At most one
    per item per mover per _OWNER_HEARD_WINDOW: a later change inside it is dropped (the item holds the newest state); a close and a
    reopen are always sent. → the writer's reply line, or "" (nobody told)."""
    h = _hooks()
    if getattr(_writes.TERMINAL_ROW, "on", False):      # a terminal-prompt row (a script's notification of its own) tells no session
        return ""
    if handled or not tell_owner_on():
        return ""
    meta = item.get("metadata") or {}
    owner, word = held_by(item)
    if not _owner_is_session(owner):
        return ""
    oid, wid = h.session_id(owner), h.session_id(writer)
    if not wid or wid == oid:
        return ""
    parts: list[str] = []
    if reopening:
        parts.append("reopened it")
    if closing:
        reason = _clip_line(meta.get("reason"), 120)
        parts.append(f"closed it: {meta.get('outcome') or 'done'}" + (f" ({reason})" if reason else ""))
    else:
        if (meta.get("next") or "") != (before.get("next") or ""):
            was_ln = [ln.strip() for ln in str(before.get("next") or "").splitlines() if ln.strip()]      # the line this write set, never the head of lines other sessions wrote
            now_ln = [ln.strip() for ln in str(meta.get("next") or "").splitlines() if ln.strip()]
            added = [ln for ln in now_ln if ln not in set(was_ln)]      # a line identical to one already there (another session's) is not a line this write set
            gone = [ln for ln in was_ln if ln not in set(now_ln)]
            if added:
                parts.append("set next: " + _clip_line(added[0], 120))
            elif gone:
                parts.append("removed their next lines")
        if set(_needs_of(meta)) != set(_needs_list(before.get("needs"))):
            parts.append("changed needs: " + (", ".join(h.shown_needs(_needs_of(meta))) or "cleared"))
        if h.check_changed(meta.get("check"), before.get("check")):
            parts.append("changed check: " + (_clip_line(h.check_lane_shown(meta.get("check") or ""), 120) or "cleared"))
        if meta.get("after") != before.get("after"):
            parts.append("changed after: " + (", ".join(_gh.shown(x) for x in meta["after"]) if isinstance(meta.get("after"), list) and meta["after"] else "cleared"))
    if not parts:
        return ""
    now = time.time()
    for k in [k for k, t in OWNER_HEARD.items() if now - t >= _OWNER_HEARD_WINDOW]:
        OWNER_HEARD.pop(k, None)
    if not (closing or reopening) and (gid, oid) in OWNER_HEARD:
        return ""
    project, who, olabel = str(meta.get("project") or ""), _session_label(writer) or "a session", _session_label(owner)
    front = front_keeper(owner, project)[0]
    subject = str(item.get("subject") or "")
    line = f"[board] {_gh.shown(gid)} {subject}: {who} {'; '.join(parts)}" + (f" ({word} {olabel} may need to act)" if front else "") + f" → {notice_link(gid)}"
    if not front:
        OWNER_HEARD[(gid, oid)] = now
        hk = "" if reopening else (("" if _owner_words(item) or (meta.get("outcome") or "done") != "done" else "closed") if closing else ("" if _asks_of(gid, item, oid) else "changed"))     # a close, or a change to an item it neither moves nor is asked on, asks a background mover nothing
        tell_or_hold(gid, oid, line, hk, tag="owner")
        return f"\n(its {word} {olabel} has been told)"
    quiet = quiet_line(item, owner)
    if "decision" in _needs_kinds(meta) and "decision" not in [str(x).lower() for x in _needs_list(before.get("needs"))]:
        return quiet                   # a move to decision is told to nobody, a front agent mover's item in or out of the pilot: the board shows it
    if relayed:
        return ""                      # the keeper or the router already has this write (_pilot_relay) and rules it: one event, one inbound
    key = project.strip().rstrip("/")
    try:
        reg = _anc.registry()
        stew = (_anc.notice_name(key, reg) or _anc.name_line(key, reg)) if key in reg else ""
        kept = stand_in_keeper(key, reg) if key in reg else ""
        keepers = {h.session_id(x) for x in (stew, kept, page_keeper(key, reg), front_keeper(owner, key)[1], project_keeper(key)) if x}
    except Exception:  # noqa: BLE001
        return ""
    if not (stew or kept) or wid in keepers:
        return ""                      # no page key with someone behind it, or the writer is that someone: the board shows it
    pilot = bool(_anc.pilot_root(key))
    live = pilot                       # the router rules it (a page of the registry always has a pilot root)
    to = h.session_id(kept or stew)
    if not live and (to == oid or front_keeper(kept or stew, key)[0]):
        return quiet                   # a front agent is never pushed to unmarked: the board shows it
    try:
        nid = _routing.record(key, kind="message", to="" if live else to, label=f"message to {key}", who=NAME, text=line, target="project-wide", pilot=pilot, live=live)
    except Exception as e:  # noqa: BLE001
        print(f"owner: {gid} notice to {key} not recorded, so not sent: {e}", file=sys.stderr, flush=True)
        return ""
    OWNER_HEARD[(gid, oid)] = now
    stamp = dt.datetime.now(h.zone()).strftime("%Y-%m-%d %H:%M %Z")
    if live and nid:
        _router_live.stash(nid, f"[stackshot message] from {NAME} · {stamp} · to {key}\n{line}")
    else:
        tell_kind("progress", gid, kept or stew, f"[stackshot message] from {NAME} · {stamp} · to {key}\n{line}", tag="owner")      # the notice could not be recorded for the router: told at once, never lost
    return f"\n(its {word} {olabel} is a front agent: the notice went to {key}, where the router rules it)"


def next_head(meta: dict[str, Any], writer: str = "") -> str:
    """The line of next a notice quotes: the first line the writer wrote when it wrote one (next is kept by writer, so the head of the list may be another session's line), else the head."""
    h = _hooks()
    own = _nl.text_of(meta, h.session_id(writer), str(meta.get("owner") or ""), h.ho_same) if str(writer or "").strip() else ""      # a line stored with no writer belongs to the creator: a fact of the History
    return ((own or str(meta.get("next") or "")).strip().splitlines() or [""])[0]


def tell_needed(gid: str, item: dict[str, Any], added: list[str], writer: str, heard: list[str] | None = None) -> str:
    """a session newly named in an item's needs gets one notice, never the writer. The item's mover (_holder) named by another session is told
    like any other, unless `heard` shows this same write already told it as mover (a move to decision, a reopen) or passed a front agent mover by on a move
    to decision, so it hears the write once and the reply says so once. → the reply line, or ""."""
    h = _hooks()
    meta = item.get("metadata") or {}
    owner, project = holder(item), str(meta.get("project") or "")
    wid = h.session_id(writer)
    skip = {wid, *(h.session_id(h) for h in (heard or []))}
    who = _session_label(writer) or "a session"
    told, quiet = [], ""
    for s in added:
        sid = h.session_id(s)
        if not sid or sid in skip:
            continue
        skip.add(sid)
        if owner and sid == h.session_id(owner) and front_keeper(owner, project)[0]:   # no item notice wakes a front agent mover
            quiet = quiet_line(item, owner); continue
        nxt = next_head(meta, writer)[:160]
        thn = then_part(item)
        tell_woken(gid, sid, f"[stackshot] {_gh.shown(gid)} now needs you (named in its needs by {who}): {item.get('subject') or ''} ({project}){thn}"
                              + (f"; next: {nxt}" if nxt else "") + f". Do your part and close it or hand it back (sender={_session_label(s)!r}); "
                              f"Your turn-end board check asks about it until then. → {notice_link(gid)}", tag="needs")
        told.append(_session_label(s))
        if heard is not None and owner and sid == h.session_id(owner):
            heard.append(sid)     # the mover has heard this write: a later notice in it (_tell_decided) leaves it out
    return (f"\n({', '.join(told)} {'has' if len(told) == 1 else 'have'} been told the item needs {'it' if len(told) == 1 else 'them'})" if told else "") + quiet


def tell_decided(gid: str, item: dict[str, Any], sessions: list[str], writer: str, heard: list[str] | None = None) -> str:
    """(if something can be done without the owner, he is pinged after it is done, and the other
    way round): when `decision` leaves an item's needs, the sessions still named in it are told at once that the move is theirs,
    never the writer. The item's mover named by another session is told like any other (a mover that wrote it is the writer), unless
    `heard` shows this same write already reached it as mover, so it hears the write once. → the reply line, or ""."""
    h = _hooks()
    meta = item.get("metadata") or {}
    owner, project = holder(item), str(meta.get("project") or "")
    skip = {h.session_id(writer), *(h.session_id(h) for h in (heard or []))}
    thn = then_part(item)
    nxt = next_head(meta, writer)[:160]
    told, quiet = [], ""
    for s in sessions:
        sid = h.session_id(s)
        if not sid or sid in skip or sid in [h.session_id(x) for x in told]:
            continue
        if owner and sid == h.session_id(owner) and front_keeper(owner, project)[0]:   # no item notice wakes a front agent mover
            quiet = quiet_line(item, owner); continue
        tell_woken(gid, sid, f"[stackshot] {_gh.shown(gid)}: {OWNER} has decided (decision left its needs, by {_session_label(writer) or 'a session'}), so the move is yours "
                              f"as named in its needs: {item.get('subject') or ''} ({project}){thn}" + (f"; next: {nxt}" if nxt else "")
                              + f". Read its next for his call, do your part and close it or hand it back (sender={_session_label(s)!r}). → {notice_link(gid)}", tag="needs")
        told.append(s)
        if heard is not None and owner and sid == h.session_id(owner):
            heard.append(sid)     # the mover has heard this write, as _tell_needed records it: _tell_owner_change leaves it out
    return (f"\n({', '.join(_session_label(s) for s in told)} {'has' if len(told) == 1 else 'have'} been told the move is {'its' if len(told) == 1 else 'theirs'} now that the decision is in)" if told else "") + quiet


def tell_handback(gid: str, item: dict[str, Any], was_needs: list[str], writer: str, heard: list[str] | None = None) -> str:
    """A front agent mover is not woken by most item notices, so an item a builder hands back
    sat with it until its next turn. This is the first exception (a close by another session, _tell_owner_close,
    skips a mover this function told; this is the one line a front agent
    mover hears of an open item's needs, only when back with it): a write by a session other than the mover that leaves the
    item's needs naming the mover alone (the sessions in it; `decision` still in it is his, not a hand-back, and `external` is ignored),
    when before the write they named someone else or others beside it (`was_needs`: nothing named before is no hand-back, the older
    silence), tells that front agent mover one short line, with the first line of `next`. Not on a close or a reopen, not when the mover
    wrote it, not when [board] tell_owner is off. A project the router is live for records it for the router, whose hand-back rule
    passes it straight to the mover (router.py), marked as every delivery to a front agent is; any other project delivers it at once with
    the mark (_FOR_OWNER), as _tell_close_owner does. The mover is added to `heard` and to _OWNER_HEARD, so the write's other notices
    (_tell_needed, _tell_decided, _tell_owner_change) leave it out: it hears the write once. There is no pilot gate, on purpose: a project outside the pilot gets the marked push. → the writer's reply line, or ""."""
    h = _hooks()
    meta = item.get("metadata") or {}
    owner, project = holder(item), str(meta.get("project") or "")
    if item.get("status") != "open" or not owner or not tell_owner_on():
        return ""
    oid, wid = h.session_id(owner), h.session_id(writer)
    if not oid or not wid or wid == oid or "decision" in _needs_kinds(meta):
        return ""
    after = {h.session_id(x) for x in _needs_sessions(meta)}
    before = {h.session_id(x) for x in _needs_list(was_needs) if x.lower() not in _NEEDS_KINDS}
    if after != {oid} or not before or before == {oid} or not front_keeper(owner, project)[0]:
        return ""
    who, olabel, subject = _session_label(writer) or "a session", _session_label(owner), str(item.get("subject") or "")
    nxt = _clip_line((str(meta.get("next") or "").strip().splitlines() or [""])[0], 160)
    line = f"[stackshot] {_gh.shown(gid)} is back with you alone (handed back by {who}): {subject}" + (f"; next: {nxt}" if nxt else "") + f" → {notice_link(gid)}"
    rec = {"gid": gid, "oid": oid, "olabel": olabel, "project": project, "who": who, "wid": wid, "subject": subject, "line": line}
    hold = handback_hold_s()
    dest = no_front(oid, project) if front_sender(oid) else oid      # a front agent mover is not handed the item by stackshot: its builder is told, else nobody
    if dest and dest != oid and h.session_id(dest) == wid:              # ... and the builder that wrote the hand-back itself needs no line about its own write
        told = "nobody is told: a front agent is not handed an item on stackshot's own motion, so the board shows it (your own write; the project's builder is you)"
        dest = ""
    elif dest and dest != oid:
        if _held.can_fetch(dest):      # the builder's hook fetches held lines: the line rides its next turn (_tell_or_hold); else it is pushed as a message
            told = f"its builder {_session_label(dest)} is passed a note that it is back with them alone, not them (a note for its next turn, not a wake-up): a front agent is not handed an item on stackshot's own motion"
        else:
            told = f"its builder {_session_label(dest)} is told it is back with them alone, not them: a front agent is not handed an item on stackshot's own motion"
    elif dest:
        told = "told it is back with them alone"
    else:
        told = "nobody is told: a front agent is not handed an item on stackshot's own motion, so it stays with them and the board shows it"
    if hold > 0 and dest:
        if _handback_hold(rec, hold):     # held for a few minutes; a close of the item inside the window sends the keeper only the close line
            tail = f"{told}, in {_handback_minutes(hold)} unless you close {_gh.shown(gid)} first (then it is told only that it was closed)"
        else:                             # the held line could not be written: sent at once, never lost
            if not handback_send(rec):
                told = "nobody is told: the board shows it"
            tail = told
    else:
        if dest and not handback_send(rec):
            told = "nobody is told: a front agent is not handed an item on stackshot's own motion, so the board shows it"
        elif not dest:
            handback_send(rec)      # nobody to tell: records the board line and the routing log line
        tail = told
    if heard is not None:
        heard.append(oid)
    OWNER_HEARD[(gid, oid)] = time.time()
    return f"\n(its {held_by(item)[1]} {olabel} is a front agent: {tail})"


# A builder that hands an item back to its front agent keeper and then closes the same
# item soon after woke the keeper twice. The hand-back line is now held for [board] handback_hold_seconds (default 180; 0 = sent at once, as before). A close of the item
# inside the window (any close: `writes.save` sees it) drops the held line, so the keeper hears only "closed by …" (_tell_owner_close); a second hand-back
# of the same item inside the window replaces the first (one line, the latest `next`, the original due time). When the window ends the line is sent
# if the item is still open and its needs still name the keeper alone; if the item moved on, it is dropped. The held lines are kept in
# <state>/handback-held.json, so a restart loses none: the runner's fleet tick (every 60 s) sends what is due.
HANDBACK_HOLD_S = 180.0


_HANDBACK_LOCK = threading.Lock()


def handback_hold_s() -> float:
    """[board] handback_hold_seconds: how long a hand-back line to a front agent keeper is held for a close to cancel it (default 180; 0 = no hold). Read where used (live)."""
    v = _cfg.get("board", "handback_hold_seconds")
    try:
        return max(0.0, float(v)) if v is not None and not isinstance(v, bool) else HANDBACK_HOLD_S
    except (TypeError, ValueError):
        return HANDBACK_HOLD_S


def _handback_minutes(seconds: float) -> str:
    m = max(1, int(round(seconds / 60.0)))
    return f"{m} minute" + ("" if m == 1 else "s")


def _handback_file() -> Path:
    return _cfg.state("handback-held.json")


def handback_read() -> dict[str, dict[str, Any]]:
    try:
        d = json.loads(_handback_file().read_text(encoding="utf-8"))
        return {str(k): v for k, v in d.items() if isinstance(v, dict)} if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def handback_write(d: dict[str, dict[str, Any]]) -> bool:
    """Write the held lines whole (an empty set removes the file) → True when written."""
    p = _handback_file()
    try:
        if not d:
            p.unlink(missing_ok=True)
            return True
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(f".{p.name}.tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, p)
        return True
    except OSError as e:
        print(f"hand-back: held lines not written: {e}", file=sys.stderr, flush=True)
        return False


def _handback_hold(rec: dict[str, Any], hold: float, now: float | None = None) -> bool:
    """Hold the hand-back line `rec` (gid, oid, olabel, project, who, subject, line) for `hold` seconds. One per item and keeper: a second one inside the window replaces the line and keeps the first due time. → False when the line could not be kept (the caller sends it at once)."""
    now = time.time() if now is None else now
    key = f"{rec['gid']}|{rec['oid']}"
    with _HANDBACK_LOCK:
        d = handback_read()
        d[key] = {**rec, "due": float((d.get(key) or {}).get("due") or (now + hold))}
        return handback_write(d)


def handback_drop(gid: str, why: str = "") -> int:
    """The item closed (or is no longer handed back): its held hand-back lines are dropped → how many."""
    with _HANDBACK_LOCK:
        d = handback_read()
        gone = [k for k, v in d.items() if v.get("gid") == gid]
        if gone:
            for k in gone:
                d.pop(k, None)
            handback_write(d)
    if gone:
        print(f"hand-back: {gid}: {len(gone)} held line(s) dropped{(' (' + why + ')') if why else ''}", file=sys.stderr, flush=True)
    return len(gone)


def handback_send(rec: dict[str, Any]) -> bool:
    """Deliver one hand-back line: recorded for the router when the project's is live (its hand-back rule passes it, marked), else pushed at once with the mark; a record that cannot be written is pushed (never lost).
    for a front agent mover the line goes to the project's builder instead (_tell_or_hold: it asks the builder nothing, so it rides the builder's next turn), or to nobody. → True when
    a line was passed to someone, False when nobody was told (the board and the routing log hold it)."""
    h = _hooks()
    gid, oid, project, who, olabel = rec["gid"], rec["oid"], rec["project"], rec["who"], rec["olabel"]
    if front_sender(oid):      # "back with you alone" is stackshot handing an item to a front agent by itself: it goes to the project's builder, or nowhere (the item stays with its mover)
        dest = no_front(oid, project)
        wid = str(rec.get("wid") or "")      # a record held before this release has no writer on file: unknown, so the builder may be the writer, and is not told about its own write
        if dest and wid and h.session_id(dest) != wid:
            tell_or_hold(gid, dest, str(rec["line"]).replace("is back with you alone", f"is back with {olabel}, a front agent, alone", 1)
                          + f" — told to you, not to {olabel}: an item is not handed to a front agent on stackshot's own motion", "changed", tag="owner")
            return True
        # no builder to tell, or the builder wrote the hand-back itself (or may have): the board holds it (the item's needs and History), the routing log says it was held
        why = "the project lists no builder to tell instead" if not dest else "the builder wrote the hand-back itself" if wid else "who wrote the hand-back is not on record, so the builder may have"
        _front_board_line(gid, oid, False, f"{why}, and an item is not handed to a front agent on stackshot's own motion", str(rec["line"]))
        _front_held_log(gid, oid, "progress", f"held: front agent, {why} (hand-back)", str(rec["line"]))
        return False
    delivered = False
    if _router_live.is_live(project):
        try:
            nid = _routing.record(project, kind="board", to="", label=f"hand-back {_gh.shown(gid)}", who=who, text=f"handed back by {who}: {rec['subject']}",
                                  url=notice_link(gid), target="for " + olabel, pilot=True, live=True, handback=True)
            _router_live.stash(nid, rec["line"])
            delivered = True
        except Exception:
            pass       # not recorded: told at once below, never lost
    if not delivered:
        tell_woken(gid, oid, f"{_FOR_OWNER} {rec['line']}", tag="owner")
    return True


def handback_tick(now: float | None = None) -> list[str]:
    """The fleet tick: send every held hand-back line whose window ended, if the item is still open and its needs still name the keeper alone; drop
    the rest. **At least once:** a line is sent first and removed from the file after, so a crash between the two (or a failed write of the file)
    sends it again at the next tick rather than never; a line whose send raises is tried at the next ticks and given up after 3 tries. → the gids sent."""
    h = _hooks()
    now = time.time() if now is None else now
    with _HANDBACK_LOCK:
        due = {k: v for k, v in handback_read().items() if float(v.get("due") or 0) <= now}
    sent: list[str] = []
    for key, rec in due.items():
        done = True
        try:
            item = _load(rec["gid"])
            meta = item.get("metadata") or {}
            if item.get("status") != "open" or {h.session_id(x) for x in _needs_sessions(meta)} != {rec["oid"]} or "decision" in _needs_kinds(meta):
                print(f"hand-back: {rec['gid']} moved on while held, not sent", file=sys.stderr, flush=True)
            else:
                handback_send(rec)
                sent.append(rec["gid"])
        except Exception as e:  # noqa: BLE001
            print(f"hand-back: {rec.get('gid')} not sent: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
            tries = int(rec.get("tries") or 0) + 1
            done = tries >= 3
            if not done:
                with _HANDBACK_LOCK:
                    d = handback_read()
                    if key in d:
                        d[key]["tries"] = tries
                        handback_write(d)
        if done:
            with _HANDBACK_LOCK:
                d = handback_read()
                if d.pop(key, None) is not None:
                    handback_write(d)
    return sent


def _closed_by(item: dict[str, Any], who: str) -> str:
    """The words of a close in the mover's line: "closed by <who>: done (<reason>)", with "by <id>" after a superseded outcome."""
    meta = item.get("metadata") or {}
    sup, reason = str(meta.get("superseded_by") or ""), _clip_line(meta.get("reason"), 120)
    return f"closed by {who}: {meta.get('outcome') or 'done'}{' by ' + _gh.shown(sup) if sup else ''}" + (f" ({reason})" if reason else "")


def tell_owner_check_closed(gid: str, item: dict[str, Any], told: list[str]) -> bool:
    """The server's own close on a done check (a merged pull request) tells
    a front agent mover at once too, in the line _tell_owner_close sends for a close by a session, with "stackshot's done check" as the
    closer. The same rules: not when [board] tell_owner is off, the mover is not a session or not a front agent, the item is muted on his
    For you list, the mover is already among `told` (it keeps the page, so the keeper's line reached it), or its For you row failed and
    the old notice went to it (_FORYOU_FELL). → True when sent."""
    h = _hooks()
    meta = item.get("metadata") or {}
    owner, project = holder(item), str(meta.get("project") or "")
    if not tell_owner_on() or not _owner_is_session(owner):
        return False
    oid = h.session_id(owner)
    if not oid or oid in {h.session_id(t) for t in told} or h.fy_flag(gid) == "mute" or not front_keeper(owner, project)[0] \
            or h.foryou_key(gid, "closed", item) in _FORYOU_FELL:
        return False
    by = "stackshot's done check"
    tell_kind("close", gid, oid, f"{_FOR_OWNER} [stackshot] {_gh.shown(gid)} {item.get('subject') or ''}: {_closed_by(item, by)} \u2192 {notice_link(gid)}", tag="owner")      
    OWNER_HEARD[(gid, oid)] = time.time()
    return gate_result()[0] != "held"      # False when the gate held it: the caller does not count the mover as told


def tell_owner_close(gid: str, item: dict[str, Any], writer: str, closing: bool, heard: list[str]) -> str:
    """A session other than the mover closes the item, and the front agent that
    moves it is told at once, by one marked line (any close, not only one with his words on it: that close is also a row on his For you
    list, which stays as it is, _foryou_on_save). It is delivered at once with the mark (_FOR_OWNER), router live or not, as
    _close_owner_notice does: the server's own delivery to the mover is what reaches a front agent (the message tool refuses an unmarked
    message to one, and a marked one that says nothing is needed from him). There is no pilot gate, as for _tell_handback. Not when the
    mover wrote it or is the owner or not a session, not when [board] tell_owner is off, not when the item is muted on his For you list, not
    when the mover is not a front agent (it already hears a close through _tell_owner), not when this write already told the mover
    (`heard`), not when the close's For you row failed and was told the old way (_FORYOU_FELL). This function once also told the mover of a builder's step, when a session the
    item's needs named took itself out of needs or finished its last step by a status done. That line is gone: a front agent mover hears of an
    item only when it is closed (here) or back with it alone (_tell_handback); a builder's step stays on the item's History (one line a change)
    and, for a state-changing write, the page debt it leaves (_owed_mark). The mover is added to `heard` and to _OWNER_HEARD so the write's other notices leave it out.
    → the writer's reply line, or "" (nobody told)."""
    h = _hooks()
    if getattr(_writes.TERMINAL_ROW, "on", False):      # a terminal-prompt row (a script's notification of its own) tells no session
        return ""
    if not closing:
        return ""
    meta = item.get("metadata") or {}
    owner, project = holder(item), str(meta.get("project") or "")
    if not tell_owner_on() or not _owner_is_session(owner):
        return ""
    oid, wid = h.session_id(owner), h.session_id(writer)
    if not oid or not wid or wid == oid or oid in {h.session_id(h) for h in heard} or h.fy_flag(gid) == "mute":
        return ""
    if not front_keeper(owner, project)[0] or h.foryou_key(gid, "closed", item) in _FORYOU_FELL:
        return ""
    who, olabel, subject = _session_label(writer) or "a session", _session_label(owner), str(item.get("subject") or "")
    tell_kind("close", gid, oid, f"{_FOR_OWNER} [stackshot] {_gh.shown(gid)} {subject}: {_closed_by(item, who)} \u2192 {notice_link(gid)}", tag="owner")      
    res, why = gate_result()      # the gate may have held it: the reply says what became of it
    heard.append(oid)
    OWNER_HEARD[(gid, oid)] = time.time()
    return f"\n(its {held_by(item)[1]} {olabel} is a front agent: " + (f"not told that it was closed ({why}); the close is on the board)" if res == "held" else "told at once that it was closed)")


def live_pass(project: str, nid: str, to: str) -> None:
    """A notice delivered at once to an agent of a project the router is live for (not the keeper): ruled passed by the router's name,
    so it does not sit unruled (there is no keeper to chase it, and the board flags the unruled ones)."""
    if nid and _router_live.is_live(project):
        try:
            _routing.rule(nid, "passed", to=to, reason="delivered at once to the agent it is for", by=_router_live.BY)
        except Exception:
            pass


def pilot_relay(project: str, gid: str, item: dict[str, Any], what: str, writer: str, keeper: str, role: str = "name", tail: str = "") -> str:
    """Tell the page's keeper what another session changed on the board (one routing-log line, one notice). → a line for the writer's reply.
    tail replaces "the page update is yours" (the fallback after the writer left it undone, or a close told for its anchors)."""
    if front_keeper(keeper, project)[0] and not _router_live.holds(project, keeper):      # a front agent gets no page-owed notice; the charge already passed it by (_pilot_charge); one that is only the address of a nameless page's notices is the router's
        return ""
    who = _session_label(writer) or "a session"
    subject = str(item.get("subject") or "")
    tail = tail or f"the page update is yours as {'its agent' if role == 'agent' else 'its keeper'}"
    live = _router_live.holds(project, keeper, stand_in_too=(role != "agent"))      # a live project: the router rules this notice, the keeper (or the stand-in standing in for it) is not told; a page's own agent is told directly
    ask = "yours as" in tail          # "…so it is yours as its keeper" (the fallback after the writer left it undone) and "the page update is yours as its keeper" hand the debt to the keeper: an ask, delivered
    if not live and not ask and hold_notice(keeper, f"[board] {_gh.shown(gid)} {what} by {who} — {subject} ({project}) → {notice_link(gid)} — {tail}", "page-owed", gid=gid, project=project, sender=who):
        return f"\n(pilot project: this change is charged to the {'agent' if role == 'agent' else 'keeper'} {_session_label(keeper)}, who keeps the page; it reads this at its next turn, it was not woken for it)"      
    try:
        nid = _routing.record(project, kind="board", to="" if live else keeper, label=f"board {_gh.shown(gid)}", who=who, text=f"{what}: {subject}",
                              url=notice_link(gid), target="for " + who, pilot=True, live=live, hold="page-owed" if live and not ask else "")
    except Exception:
        nid = ""
    if live and nid:
        _router_live.stash(nid, f"[board] {_gh.shown(gid)} {what} by {who} — {subject} ({project}) → {notice_link(gid)} — "
                                + tail.replace("so it is yours as its keeper", "so the page update is owed").replace("the page update is yours as its keeper", "the page update is owed"))
        return ("\n(pilot project: this change is charged to the router, which passes the page update to the agent that keeps the page)")
    live_pass(project, nid, keeper)
    note = (f"[board] {_gh.shown(gid)} {what} by {who} — {subject} ({project}) → {notice_link(gid)}"
            + (f" — {tail} · notice {nid}" if nid else ""))
    _ho_told(gid, keeper)          # step 2: a hand-off to the keeper in this same write is not told a second time
    threading.Thread(target=_relay_push, args=(gid, keeper, note), daemon=True).start()
    return f"\n(pilot project: this change is charged to the {'agent' if role == 'agent' else 'keeper'} {_session_label(keeper)}, who keeps the page and has been told; write your own page or the hub's timeline as usual)"


def _ho_told(gid: str, who: str) -> None:
    """This write has told `who` about `gid` (a notice, a relay, a charge): its hand-off notice leaves it out, so nobody hears one write twice."""
    h = _hooks()
    try:
        told = getattr(HO_STATE, "told", None)
        if told is not None and who:
            told.add((gid, h.session_id(who)))
    except Exception:  # noqa: BLE001
        pass


def push_noted(to: str, note: str) -> None:
    """One notice to a session through push.py, on a thread of its own, for a notice path that names items in its text (the keeper's page-owed batch, the anchors prompt): the outcome is
    recorded on the open hand-off of any item the text names to that session (_handoff_told_text). A failure is a stderr line, as these senders always had it. Never raises."""
    h = _hooks()
    try:
        r = subprocess.run([*_interp.resilient(PUSH), "--from", NAME, to, note], capture_output=True, text=True, timeout=110, env={**os.environ, "ANCHOR_PUSH_SOURCE": "msg"})
        h.handoff_told_text(to, note, (r.stdout.strip().splitlines() or [""])[-1], link_only=True)
    except Exception as e:  # noqa: BLE001
        print(f"push: notice to {to} failed: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)


def _relay_push(gid: str, keeper: str, note: str) -> None:
    """The keeper's page-owed notice, pushed on a thread of its own; a hand-off to the keeper that this push stands for is delivered (or not) by its outcome."""
    h = _hooks()
    try:
        r = subprocess.run([*_interp.resilient(PUSH), "--from", NAME, keeper, note], capture_output=True, text=True, timeout=110, env={**os.environ, "ANCHOR_PUSH_SOURCE": "msg"})
        out = (r.stdout.strip().splitlines() or [""])[-1]
        h.handoff_pushed(gid, keeper, out or "failed", (r.stderr.strip().splitlines() or [""])[-1])
    except Exception as e:  # noqa: BLE001
        h.handoff_pushed(gid, keeper, "failed", str(e))


def writer_charge(project: str, gid: str, writer: str, keeper: str, what: str, loose: bool) -> str:
    """charge a pilot board write to its writer, with the keeper as the fallback (_pilot_fallback_tick). → the writer's reply line."""
    h = _hooks()
    _ho_told(gid, writer)         # step 2: the writer hears this write in the reply
    h.owed_mark(project, writer, gid, settle="any" if loose else "ct", moves=keeper, what=what)
    which = ("any page write, a timeline line included, since only next or the hold changed" if loose
             else "its Current state, since the item's state changed")
    return (f"\n(pilot project: the page update is yours in this turn: {project}, {which}. If it is still missing after "
            f"{h.grace_min()} min, it moves to {h.debt_mover(project, keeper)}.)")


def pilot_relay_many(keeper: str, rows: list[tuple[str, str, dict[str, Any], str, str]], head: str = "") -> list[str]:
    """Several debts moved to one keeper in one tick (the turn rule's fourth build: each relay cost the
    keeper a turn): one message listing them, rows = [(project, gid, item, what, writer)]. Each debt still gets its own
    routing-log line, as _pilot_relay writes it, the lines sharing one `batch` id so a count of the turns notices cost counts
    the message once. `head` = another first line (the page-debt call's fallback to the -main agent, _page_debt_fallback)."""
    h = _hooks()
    batch = os.urandom(3).hex(); nids: list[str] = []
    held = [] if head else [r for r in rows if _router_live.holds(r[0], keeper, stand_in_too=True)]       # a live project: the router rules these, the keeper (or its stand-in) is not told; a caller that names its recipient (head: the page-debt fallback to the page's agent or -main) is delivered to
    if held:
        for project, gid, item, what, writer in held:
            who = _session_label(writer) or "a session"; subject = str(item.get("subject") or "")
            try:
                nid = _routing.record(project, kind="board", to="", label=f"board {_gh.shown(gid)}", who=who, text=f"{what}: {subject}",
                                      url=notice_link(gid), target="for " + who, pilot=True, live=True)
            except Exception:
                continue          # not recorded: it stays in `rows` below and goes out as before, never lost
            _router_live.stash(nid, f"[board] {_gh.shown(gid)} {what} by {who} — {subject} ({project}) → {notice_link(gid)} — {who} left its page update undone past {h.grace_min()} min, so the page update is owed")
            nids.append(nid)
            rows = [r for r in rows if not (r[0] == project and r[1] == gid and r[3] == what and r[4] == writer)]
        if not rows:
            return nids
    lines = [head or f"[board] {len(rows)} page updates are yours as its keeper: their writers left them undone past {h.grace_min()} min."]
    for project, gid, item, what, writer in rows:
        who = _session_label(writer) or "a session"
        subject = str(item.get("subject") or "")
        try:
            nid = _routing.record(project, kind="board", to=keeper, label=f"board {_gh.shown(gid)}", who=who, text=f"{what}: {subject}",
                                  url=notice_link(gid), target="for " + who, pilot=True, batch=batch)
        except Exception:
            nid = ""
        if nid:
            nids.append(nid); live_pass(project, nid, keeper)
        lines.append(f"- {_gh.shown(gid)} {what} by {who} — {subject} ({project}) → {notice_link(gid)}" + (f" · notice {nid}" if nid else ""))
    note = "\n".join(lines)
    threading.Thread(target=push_noted, args=(keeper, note), daemon=True).start()
    return nids


PUSH = [sys.executable, _paths.program("fleet", "push")]   # the delivery script (push.py since an earlier change); each call runs it through _interp.resilient


def _mentions_ref(gid: str) -> "re.Pattern[str]":
    """`board#N` of a store id as a whole id in a text: not board#N0 (a longer number), not glued to a word or a `#` before it."""
    n = _gh.shown(gid)
    return re.compile(r"(?<![\w#/&-])" + re.escape(n) + r"(?!\d)", re.I)


_MENTION_LINES_MAX = 8          # the items a close notice lists (the rest as a count): a very long list once overran MSG_MAX


MENTIONED = threading.local()      # what the last close of this thread told (_tell_close_mentions): ([item ids that named it], [the movers told]); the close's reply says it once


def mentions_reply(gid: str) -> str:
    """The reply line of a close for the notice to the movers of the items that name it, and forget it. "" when none named it."""
    got = getattr(MENTIONED, "got", None)
    MENTIONED.got = None
    if not got or got[0] != gid or not got[1]:
        return ""
    items, movers = got[1], got[2]
    return (f"\n({len(items)} other open item{'s' if len(items) != 1 else ''} name{'' if len(items) != 1 else 's'} {_gh.shown(gid)} in next or description ({', '.join(_gh.shown(x) for x in items[:6])}"
            f"{', …' if len(items) > 6 else ''}); {', '.join(movers) if movers else 'nobody'} {'has' if len(movers) == 1 else 'have'} been told)")


def tell_close_mentions(gid: str, outcome: str, reason: str, writer: str, skip: "set[str] | None" = None) -> list[str]:
    """(a next that says "after Sam's review" with no `after` can be left asleep after the item it named closed):
    a close tells the mover of every other open item whose next or description names the closed item, one batched notice per mover, naming the closed item, how it ended and why, and the
    items that named it. Left out: the closer itself (the session that wrote the close), the closed item, and the items in `skip` (the ones with the closed item in `after`: the wake they get
    is their notice). The mover is the item's mover as the model reads it; when that is the owner, or no session, the sessions its notices go to (_notice_to) hear it instead. A superseded
    item names its replacement. → the session ids told."""
    h = _hooks()
    try:
        closed = _load(gid)
    except ToolError:
        return []
    cm = closed.get("metadata") or {}
    rx = _mentions_ref(gid)
    wid = h.session_id(writer) if writer else ""
    by_sid: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for g, _p in _item_files():
        if g == gid or g in (skip or set()):
            continue
        try:
            it = _load(g)
        except Exception:  # noqa: BLE001
            continue
        m = it.get("metadata") or {}
        if it.get("status") != "open" or not (rx.search(str(m.get("next") or "")) or rx.search(str(it.get("description") or ""))):
            continue
        try:
            mover = h.model_of({**it, "gid": g}).mover
        except Exception:  # noqa: BLE001
            mover = ""
        sids = [h.session_id(mover)] if mover and not _model.is_owner(mover) else [s for s, _w in notice_to(m)]
        for sid in dict.fromkeys(x for x in sids if x):
            if sid != wid:
                by_sid.setdefault(sid, []).append((g, it))
    sup = str(cm.get("superseded_by") or "")
    how = f"{h.rmod_outcome_word(cm.get('outcome') or outcome or 'done')}" + (f" by {_gh.shown(sup)}" if sup else "")
    why = _clip_line(cm.get("reason") or reason, 160)
    told = []
    me = _gh.shown(gid)
    cause = f"{me} {_clip_line(closed.get('subject') or '', 100)} closed ({how}" + (f": {why}" if why else "") + f"){' by ' + _session_label(writer) if writer else ''}"
    for sid, rows in by_sid.items():
        keep: list[tuple[str, dict[str, Any]]] = []
        for g, it in rows:         # the path of _wake_tell: a recipient the router holds the project for gets the notice through the routing log, the router passes it on
            m_ = it.get("metadata") or {}
            project, owner = str(m_.get("project") or ""), holder(it)
            if not _router_live.holds(project, sid):      # the recipient is the item's mover, so there is no "its own item" to tell directly
                keep.append((g, it)); continue
            thn = then_part(it)
            try:
                nid = _routing.record(project, kind="board", to="", label=f"close {me}", who="stackshot", text=f"{cause}; {_gh.shown(g)} names it{thn}: {it.get('subject') or ''}",
                                      url=notice_link(g), target="for " + _session_label(sid), pilot=True, live=True)
            except Exception:
                keep.append((g, it)); continue      # not recorded: told as before, never lost
            _router_live.stash(nid, f"[stackshot] {cause}. {_gh.shown(g)} {it.get('subject') or ''} ({project}){thn}, names it → {notice_link(g)}")
        if keep != rows or not keep:
            told.append(sid)
        if not keep:
            continue
        batch = os.urandom(3).hex() if len(keep) > 1 else ""
        lines = []
        for g, it in keep[:_MENTION_LINES_MAX]:
            m_ = it.get("metadata") or {}
            project, owner = str(m_.get("project") or ""), holder(it)
            thn = then_part(it)
            nid = ""
            if _anc.pilot_root(project) and sid != (h.session_id(owner) if owner else ""):
                try:
                    nid = _routing.record(project, kind="board", to=sid, label=f"close {me}", who="stackshot", text=f"{cause}; {_gh.shown(g)} names it{thn}: {it.get('subject') or ''}",
                                          url=notice_link(g), target="for " + _session_label(sid), pilot=True, batch=batch)
                except Exception:
                    nid = ""
                live_pass(project, nid, sid)
            lines.append(f"- {_gh.shown(g)} {_clip_line(it.get('subject') or '', 100)} (its {'next' if rx.search(str(m_.get('next') or '')) else 'description'} names {me}) → {notice_link(g)}" + (f" · notice {nid}" if nid else ""))
        if len(keep) > _MENTION_LINES_MAX:
            lines.append(f"- … and {len(keep) - _MENTION_LINES_MAX} more")
        body = f"[stackshot] {cause}." + (" An open item you move names it:\n" if len(keep) == 1 else f" {len(keep)} open items you move name it:\n") + "\n".join(lines) \
            + f"\nIf one of them waited on {me}, it can go on now: refresh its next and set after= for any wait that is left."
        project = str((keep[0][1].get("metadata") or {}).get("project") or "")
        tell_kind("close", ",".join(g for g, _i in keep), sid, (_FOR_OWNER + " " if front_keeper(sid, project)[0] else "") + body, tag="close")      # a front keeper hears a close only under presence plus touched
        if sid not in told and gate_result()[0] != "held":      # a front keeper the gate held was not told: the reply line must not say it was
            told.append(sid)
    MENTIONED.got = (gid, list(dict.fromkeys(g for rows in by_sid.values() for g, _i in rows)), [_session_label(x) or x for x in told])
    return told


def tell_wait_failed(gid: str, item: dict[str, Any], what: str, why: str, skip: list[str] | None = None) -> str:
    """A wait that can no longer end (a check whose pull request was closed unmerged) is told at once to the keeper of the item's
    page (_keeper: its builder or -main agent): the item stays open, and the keeper
    decides what it waits on now. (An `after` item that is dropped or closed undone is not one: the item is released with the wake
    notice, which says so.) `skip` = session ids already
    told of the same event. → the session id told, "" when nobody."""
    h = _hooks()
    meta = item.get("metadata") or {}
    project = str(meta.get("project") or "")
    k = project_keeper(project)
    kid = h.session_id(k) if k else ""
    if not kid or kid in (skip or []):
        if not kid:
            print(f"waiting: {gid} wait failed ({why}); no keeper to tell", file=sys.stderr, flush=True)
        return ""
    tell_kind("stuck", gid, kid, f"[stackshot] {_gh.shown(gid)} \"{item.get('subject') or ''}\" ({project}){then_part(item)}: its wait ({what}) can no longer end: {why}. "
                          f"The item stays open. As {keeper_words(project, k)}: see that its mover or the session doing the work "
                          f"gives it what it waits on now (a new check, a wake, an item to wait after) or closes it. → {notice_link(gid)}", tag="wait")
    return kid


_UNDELIVERED_KEEP = 5       # the last this many failed deliveries stay on an item (metadata.undelivered); a state change drops them


def record_undelivered(gids: str, to: str, tag: str, why: str) -> list[str]:
    """A notice that could not be delivered is recorded on the item it was about (the owner's one rule: a failed delivery was a log
    line nobody read), as `metadata.undelivered` = [{to, tag, at, why}], the last _UNDELIVERED_KEEP. A filing record: no clock
    moves; the server's note goes to the History (nothing is posted to the issue). The item shows it in `get`, and the brief and
    board.md count the open items that carry one. `gids` = one store id or several, comma-separated (a batched
    notice). A state change by a session drops the record: the item has moved since. → the gids recorded."""
    out = []
    for g in [x for x in re.split(r"[,\s]+", str(gids or "")) if _GID.match(x)]:
        with _writes.ITEM_LOCK:                       # re-read under the lock: an update that landed meanwhile is kept
            try:
                it = _load(g)
                meta = dict(it.get("metadata") or {})
                rows = [x for x in (meta.get("undelivered") if isinstance(meta.get("undelivered"), list) else []) if isinstance(x, dict)]
                rows.append({"to": _session_label(to) or str(to), "tag": tag, "at": time.time(), "why": _clip_line(why, 200)})
                meta["undelivered"] = rows[-_UNDELIVERED_KEEP:]
                it["metadata"] = meta
                _writes.save(g, it, note=f"a notice ({tag}) to {_session_label(to) or to} was not delivered: {_clip_line(why, 160)}")
                out.append(g)
            except Exception as e:  # noqa: BLE001  — the record never fails the pass that told
                print(f"{tag}: {g} undelivered notice not recorded: {e}", file=sys.stderr, flush=True)
    return out


def _hold_project(target: str, gid: str = "") -> str:
    """The project page a held notice is logged under: the item's (the first of `gid`), else the page that lists the target."""
    h = _hooks()
    for g in [x for x in re.split(r"[,\s]+", str(gid or "")) if _GID.match(x)][:1]:
        try:
            pr = str((_load(g).get("metadata") or {}).get("project") or "")
            if pr:
                return pr
        except Exception:  # noqa: BLE001
            pass
    try:
        roles = _anc.session_roles()
        return str((roles.get(h.role_name(roles, target)) or {}).get("project") or "")
    except Exception:  # noqa: BLE001
        return ""


def hold_notice(target: str, text: str, kind: str, *, gid: str = "", project: str = "", sender: str = "", asks: bool = False, owner_words: bool = False) -> bool:
    """THE decision point for a notice this server delivers itself. A notice to a BACKGROUND agent that asks nothing of it
    is not pushed as a new turn: it is held (held.py, server-side) and handed over with the agent's next turn, and the routing log says so with the reason
    "held: asks nothing (kind)". The sender names the kind (held.KINDS) and what it knows: `asks` (the agent is named in needs, moves the item, is handed it, its wait
    ends), `owner_words` (the notice carries his words); held.decide answers, and anything unsure is delivered. A front agent, a kind the code does not know, a
    notice marked for the owner and a failure here all deliver as before. → True when the notice was held (the caller sends nothing). Never raises."""
    h = _hooks()
    try:
        if not kind or not target or not _held.decide(kind, is_background=bool(h.back_agent(target)), text=text, owner_words=owner_words, asks=asks, target=target):
            return False
        if not _held.add(_held.key_of(target), kind, text, sender=sender or NAME, gid=gid):
            return False
        try:
            proj = project or _hold_project(target, gid)
            if proj:
                _routing.record_auto(proj, "held", _held.reason(kind), kind="board", label=f"{kind} {gid}".strip(), who=sender or NAME, text=text,
                                     target="for " + (_session_label(target) or str(target)), pilot=bool(_anc.pilot_root(proj)))
        except Exception as e:  # noqa: BLE001  — the log line is a record; the hold stands without it
            print(f"held: {kind} notice for {target} not logged: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return True
    except Exception as e:  # noqa: BLE001
        print(f"held: {kind} notice for {target} not held, delivered as before: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return False


def _done_close(what: str) -> bool:
    """Is this notice's `what` a close with the outcome done (`was completed (done…`)? Only that asks a background agent nothing: a dropped or superseded item tells a builder to stop. False when unsure."""
    return str(what or "").startswith("was completed (done")


def _asks_of(gid: str, item: dict[str, Any], sid: str) -> bool:
    """Does the item put something to this session: it is named in its needs, or it is the item's mover as the model reads it (a change to it may be an instruction)? True when unsure."""
    h = _hooks()
    try:
        meta = item.get("metadata") or {}
        if any(h.session_id(x) == sid for x in _needs_sessions(meta)):
            return True
        mover = h.model_of({**item, "gid": gid}).mover
        return bool(mover) and h.session_id(mover) == sid
    except Exception:  # noqa: BLE001
        return True


def tell_or_hold(gid: str, owner: str, note: str, hold: str, tag: str = "wake") -> "threading.Thread | None":
    """The notice senders' one entry for a notice of a kind that asks nothing (`hold` is a held.KINDS kind): held for a background agent's next turn
    when _hold_notice says so (before anything is recorded as told, so a hand-off notice is not suppressed by it), else _tell_woken as ever. → the sending thread, None when held."""
    if hold and hold_notice(owner, note, hold, gid=gid):
        return None
    return tell_woken(gid, owner, note, tag=tag)


def tell_woken(gid: str, owner: str, note: str, tag: str = "wake", result: "dict[str, Any] | None" = None) -> "threading.Thread | None":
    """The wake pass's one line to the item's mover, through push.py in the background (as the keeper relay sends). A
    failure is a stderr line and, since the owner's one rule, a record on the item (_record_undelivered), never an exception: the
    pass has already saved the item. `gid` may name several items (a batched notice, comma-separated). `tag` names the sender in
    those lines (the recycle pass sends through here too). `result`, when given, is filled in by the thread: {"ok": bool, "why": str} (the migration's send_wake waits for it).
    a notice for a front agent first passes _front_gate (its kind: progress | close | stuck | exempt, from _tell_kind's hint, else from the tag); a held one returns None like "no owner".
    A notice that asks nothing of a background agent goes through _tell_or_hold instead. → the sending thread (a test joins it), None with no owner."""
    h = _hooks()
    if not owner:
        print(f"{tag}: {gid} has no owner to tell", file=sys.stderr, flush=True)
        return None
    if front_gate(gid, owner, note, tag, getattr(FRONT_HINT, "kind", "")):
        return None
    try:
        told = getattr(HO_STATE, "told", None)      # step 2: what this write has told, so its hand-off notice does not double it
        if told is not None:
            told.update((g, h.session_id(owner)) for g in re.split(r"[,\s]+", str(gid)) if g)
    except Exception:  # noqa: BLE001
        pass
    def run() -> None:
        try:
            r = subprocess.run([*_interp.resilient(PUSH), "--from", NAME, owner, note], capture_output=True, text=True, timeout=110,
                               env={**os.environ, "ANCHOR_PUSH_SOURCE": "msg"})
            out = (r.stdout.strip().splitlines() or [""])[-1]
            err = (r.stderr.strip().splitlines() or [""])[-1]
            if result is not None:
                result.update(ok=out.startswith(("delivered", "queued", "inbox")), why="" if out.startswith(("delivered", "queued", "inbox")) else f"{out or 'no result'}{(' — ' + err) if err else ''}")
            if not out.startswith(("delivered", "queued", "inbox")):
                why = f"{out or 'no result'}{(' — ' + err) if err else ''}"
                print(f"{tag}: {gid} notice to {owner} not delivered: {why}", file=sys.stderr, flush=True)
                record_undelivered(gid, owner, tag, why)
            h.handoff_pushed(gid, owner, out or "failed", err)     # step 2: a hand-off to this session is delivered, waiting or failed by this push
        except Exception as e:  # noqa: BLE001
            if result is not None:
                result.update(ok=False, why=f"failed: {e}")
            print(f"{tag}: {gid} notice to {owner} failed: {e}", file=sys.stderr, flush=True)
            record_undelivered(gid, owner, tag, f"failed: {e}")
            h.handoff_pushed(gid, owner, "failed", str(e))
    th = threading.Thread(target=run, daemon=True)
    th.start()
    return th


def tell_check_closed(gid: str, item: dict[str, Any], label: str) -> list[str]:
    """The server closed `gid` itself on its done check: its mover is told in one line (_holder, the mover as it stood before the close; a close is told to the mover alone,
    never to its `then` or its creator). A front agent mover hears it as a close by another session does, marked (_tell_owner_check_closed). A close with the owner's own words on the item
    is also a row on his For you list, made when the close is saved (_foryou_on_save). → the session ids told."""
    h = _hooks()
    meta = item.get("metadata") or {}
    project = str(meta.get("project") or "")
    owner = holder(item)
    told: list[str] = []
    oid = h.session_id(owner) if owner else ""
    front = bool(owner) and front_keeper(owner, project)[0]
    if oid and not front:
        tell_woken(gid, oid, f"[stackshot] {_gh.shown(gid)} closed itself: its done check passed ({label}): {item.get('subject') or ''} ({project}){then_part(item)} → {notice_link(gid)}", tag="check")
        told.append(oid)
    elif not oid:
        print(f"check: {gid} closed, and nobody moves it to tell", file=sys.stderr, flush=True)
    if front and h.foryou_key(gid, "closed", item) in h.foryou_failed():       # the row could not be written: the old notice, so the close still reaches someone
        if tell_close_owner(gid, item, owner, project, "", by=f"stackshot's done check ({label})"):
            told.append(oid)
    try:
        if tell_owner_check_closed(gid, item, told):
            told.append(oid)
    except Exception as e:  # noqa: BLE001  — the close is saved; a notice that fails is a stderr line
        print(f"check: {gid} closed but its mover was not told: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    return told


HO_STATE = threading.local()      # per write: the hand-offs it has just recorded ({gid: to}), and the (gid, session) pairs it has already told


def handoff_notify(gid: str, item: dict[str, Any]) -> str:
    """At the tail of a create or update: the hand-off this write just recorded is told to its new mover when no notice of the write has told it already (a change of `mover` or
    `then` names no one in needs, so _tell_needed said nothing). Not the owner, not a front agent (an item notice wakes none of them). → the reply line, or ""."""
    h = _hooks()
    try:
        to, at = (getattr(HO_STATE, "fresh", None) or {}).pop(gid, ("", None))
        r = _ho.record_of(item)
        if not to or not r or r.get("at") != at or not h.handoff_on() or _model.is_owner(to):
            return ""
        told = getattr(HO_STATE, "told", set())
        tid = h.session_id(to)
        if any(g == gid and (s == tid or h.ho_same(s, to)) for g, s in told):
            return ""
        proj = str((item.get("metadata") or {}).get("project") or "")
        if front_keeper(to, proj)[0] and not h.front_handed_by_peer(r, to, proj):      # a front agent is told only of a hand-off from a front agent of its own project when that project is front-only
            return ""
        tell_woken(gid, tid or to, h.handoff_text(gid, item, r), tag="handoff")
        return f"\n({_session_label(to)} has been told it is handed {_gh.shown(gid)})"
    except Exception as e:  # noqa: BLE001
        print(f"handoff: {gid} not told: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return ""
