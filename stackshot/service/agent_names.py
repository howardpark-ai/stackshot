"""agent_names.py: the server names the working background agent in an item's needs.

The server links a background agent to the item it works on, in code and at the moments it already sees: a handover message names the agent on the open items the text names (`_name_on_handover`, also for a
SendMessage a box's hook reports), and a write by a background agent not yet named in the item's needs names it first (`_name_on_write`, which hands the caller the function that stores the naming, run just before
the write's own save). `_auto_name` is the one save both use, `_never_named` the [pilot] never_named list, `_one_mover_clash` the test that a naming never leaves an item with a second mover, `_back_agent` the test
that a session is a background agent, `_item_refs` the reader of the items a text names as plain words, and `_router_delivered` the router's push told to the hand-off record.

A service module: it reads the store and the registry and writes an item only through `writes.save`, under the caller's lock. The debounced publish of the board is still the surface's, reached through
service/save_hooks.py. A suite that replaces one of these sets it on this module.

Imports point down only: this module imports the domain, core and the services beside it, never web/ and never audit/."""
from __future__ import annotations

import sys
from typing import Any, Callable

from fastmcp.exceptions import ToolError

from stackshot.anchors import anchors as _anc
from stackshot.core import config as _cfg
from stackshot.fleet import sessions_registry as _sr
from stackshot.github import ghsync as _gh
from stackshot.model import model as _model
from stackshot.model import model_guards as _mg
from stackshot.model.ids import _ITEM_REF, _norm_id, _plain_text, _without_mq_groups
from stackshot.model.needs import _NEEDS_KINDS, _canon_needs, _needs_of, _needs_sessions, _needs_store
from stackshot.service import handoff as _handoff
from stackshot.service import item_read as _item_read
from stackshot.service import store as _svcstore
from stackshot.service import telling as _telling
from stackshot.service import writes as _writes
from stackshot.service.save_hooks import hooks as _hooks
from stackshot.service.store import _path


# The server links a background agent to the item it works on, in code and at
# the moments it already sees, so the item page shows what is in motion without a survey. (1) A handover: a message through the
# message tool, or a SendMessage a box's PostToolUse hook reports (pages.py touch → POST /client/handover), that goes to a background
# agent and names an open item names that agent in the item's needs. (2) Work on the item: an update or a close by a background agent
# not named in its needs names it first, so the record shows the agent, then its change. Only background agents (a hub page's
# `background:` entries, anchors.session_roles "back") are named: a front agent, a keeper or a session no page names never. The
# needs rules hold: decision and external stay first (_canon_needs), so a needs=decision item keeps its lane; the named session's
# lane and turn-end check follow as for a name written by hand. Nothing is ever removed: a session already named stays, and the
# mover is told once that the agent now works on it too (a plain first naming tells the owner in one line, unless the mover handed
# it over itself). An agent is never named twice, and a closed item is never touched. Every naming is the server's own save with a
# note (the History line; nothing is posted to the issue since an earlier change), the item's clocks unmoved.
# A background agent whose mandate never works items (the maintainer that merges and deploys, the daily audit) is listed in
# stackshot.toml [pilot] never_named and is never named at either moment, so a release request that cites an item in passing
# leaves that item alone; such an agent can still be named by hand (needs=). Read at each naming, so a reload applies it.
# A message (moment 1) never leaves the item with a second mover: when the needs that would result are refused by the guards' one-mover test
# (model_guards.second_mover_in), or the item stores another session as its mover, the agent is not named, the item is untouched and the reply says who moves it
# and that update(mover=) hands it over (_one_mover_clash). A background agent of the item's project is always named. Moment 2 is the agent's own work and is not judged.
# _ID_FORM, _ID_END and _ITEM_REF (an id written as a plain word) and _QUOTED and _plain_text (the text with its code and quotes blanked) are model/ids.py's.


def _item_refs(text: str) -> list[str]:
    """The items a message names as plain words → their gids, each once, in order: any id form _norm_id accepts (board#N,
    board-tmp-<machine>#3, an older letter-and-number id …) and an item page link (/items/<n>, /items/<letter><n>), never a bare #N (in prose it names a PR or
    an issue as often as an item), never an id in code or quotes or with a suffix glued on (above), never a merge-queue group number ("group g7", "split from g7", "[g7]").
    An id that names no item is skipped."""
    out: list[str] = []
    for m in _ITEM_REF.finditer(_without_mq_groups(_plain_text(text))):
        ref = m.group(1) or m.group(2) or ""
        if m.group(2) and ref.isdigit():
            ref = f"board#{ref}"
        try:
            g = _norm_id(ref)
        except ToolError:
            continue
        if g not in out and _path(g).exists():
            out.append(g)
    return out




def _back_agent(who: str, idx: dict[str, dict[str, Any]] | None = None) -> str:
    """A session (its name, or a pane id whose name the fleet knows) that a hub page lists under `background:` → its name as the
    roles know it (anchors.session_roles "back"); "" for a front agent, a keeper, a project page or a session no page names."""
    who = str(who or "").strip()
    if not who:
        return ""
    try:
        roles = _anc.session_roles()
    except Exception:
        return ""
    idx = _sr._sessions_index() if idx is None else idx
    name = _sr._role_name(roles, who, str((idx.get(who) or {}).get("name") or ""))
    return name if name and roles[name]["role"] == "back" else ""


def _never_named(agent: str, nm: dict[str, str] | None = None) -> bool:
    """A background agent listed in stackshot.toml [pilot] never_named: the server never names it in an item's needs on its own."""
    listed = [str(x).strip() for x in (_cfg.get("pilot", "never_named") or []) if str(x).strip()]
    if not listed or not agent:
        return False
    nm = _anc.names() if nm is None else nm
    me = _anc.canonical(agent, nm)
    return any(x == agent or _anc.canonical(x, nm) == me for x in listed)


def _one_mover_clash(item: dict[str, Any], agent: str) -> str:
    """Why naming `agent` in the item's needs would leave it with a second mover, in words ("<session> already moves it", or that it waits on the decision); "" when it would not. The test is
    the model guards' own (model_guards.second_mover_in) on the needs as they would stand, so a naming this lets through is never refused on the mover's next write, and it also reads a mover the
    item stores (metadata.mover) when needs does not name it. A background agent of the item's project is never counted by the guards, so it is always named, whatever the item holds.
    Off with [model] one_mover = false or guards = false."""
    meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    if not bool(_cfg.get("model", "one_mover", default=True)) or not _item_read._model_guards_on():
        return ""
    try:
        project, ctx = str(meta.get("project") or ""), _mg.Ctx(label=_sr._session_label, shown=_gh.shown)
        if ctx.background_of(agent, project):
            return ""
        needs_now = _needs_of(meta)
        if _mg.second_mover_in([*needs_now, _sr._store_ref(agent)], project, ctx):
            others = _mg.counted_movers(needs_now, project, ctx)
            return f"{', '.join(_sr._session_label(x) for x in others)} already moves it" if others else f"it waits on {_model.owner_display()}'s call (needs decision)"
        stored = _model.pick_who(meta.get("mover"))      # the legacy literal `none` names nobody
        # The stored mover is the agent being named: naming it keeps one mover, so it is no clash (and the reply would say the agent "already moves it" and tell it to hand the item to itself).
        if (stored and not _model.is_owner(stored) and not ctx.background_of(stored, project) and _anc.canonical(stored) != _anc.canonical(agent)
                and not any(_anc.canonical(stored) == _anc.canonical(x) for x in needs_now)):
            return f"{_sr._session_label(stored)} already moves it"
        return ""
    except Exception as e:  # noqa: BLE001  — a registry that cannot be read names the agent as before
        print(f"naming: one-mover check failed for {agent}: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
        return ""


def _auto_name(gid: str, item: dict[str, Any], agent: str, writer: str, why: str, tail: str = "", nm: dict[str, str] | None = None, one_mover: bool = False) -> str:
    """Name a background agent in an open item's needs as the server's own act: `why` is the record's line ("handover message from
    my-board", "update by my-engineer"), `tail` the mover's notice's words ("handed over", "after its
    update"; "" tells the mover nothing: a close's own notice names the closer), `writer` the session whose act it was (a mover
    that handed over itself is not told). Nothing on a closed item or for an agent already named; a session already named stays,
    and the mover hears once that the agent now works on it too. Nothing for an agent listed in [pilot] never_named. → the reply
    line, or ""."""
    if item.get("status") != "open" or not agent:
        return ""
    nm = _anc.names() if nm is None else nm
    if _never_named(agent, nm):
        return ""
    meta = item.get("metadata")
    if not isinstance(meta, dict):
        meta = item["metadata"] = {}
    me = _anc.canonical(agent, nm)
    if any(_anc.canonical(s, nm) == me for s in _needs_sessions(meta)):
        return ""
    if one_mover:         # a handover message never leaves the item with a second mover: the next write of its mover would be refused
        clash = _one_mover_clash(item, agent)
        if clash:
            return f"\n(did not name {agent} in {_gh.shown(gid)}'s needs: {clash}, and an item has one mover. To hand it to {agent}, write the item: update(mover={agent}))"
    prev = _telling.holder(item)       # the session that held the item before the agent is named hears of it
    already = list(_needs_sessions(meta))
    _needs_store(meta, _canon_needs([*_needs_of(meta), _sr._store_ref(agent)], nm))
    _writes.save(gid, item, note=f"named {agent}: {why}")
    was = ", ".join(_sr._session_label(s) for s in already)
    told = ""
    if tail:
        told = _telling.tell_owner(gid, item, f"now names {agent} in its needs" + (f" too ({was} {'was' if len(already) == 1 else 'were'} already named)" if already else "") + f", {tail}", writer, to=prev)
    return f"\n(named {agent} in {_gh.shown(gid)}'s needs: {why}" + (f"; {was} {'stays' if len(already) == 1 else 'stay'} named" if already else "") + ")" + told


def _name_on_handover(to: str, text: str, sender: str, idx: dict[str, dict[str, Any]] | None = None, via: str = "") -> str:
    """Moment 1: a message to a background agent that names open items names the agent in their needs. `via` says the path when it
    is not the message tool ("SendMessage on the host"). → the reply lines, "" when nothing was named."""
    agent = _back_agent(to, idx)
    if not agent:
        return ""
    out, nm = "", _anc.names()
    for g in _item_refs(text):
        try:
            it = _svcstore._load(g)
        except ToolError:
            continue
        out += _auto_name(g, it, agent, sender, f"handover message from {_sr._session_label(sender)}" + (f" ({via})" if via else ""), "handed over", nm, one_mover=True)
    if out:
        _hooks().publish()
    return out


def _name_on_write(gid: str, item: dict[str, Any], meta: dict[str, Any], sender: str, was: str, was_needs: list[str], closing: bool, plain: bool = True) -> Callable[[], str]:
    """Moment 2: a write on an open item by a background agent not named in its needs names it first, as its own save, so the record
    shows the agent named, then its change (on a close: named, then closed; the close's own notice names the closer, so the mover
    hears nothing extra). `item` is the write in flight, `meta` its metadata: the naming is carried into `meta` at once, so the gates on who may
    write (a step status) read the agent as a named session. Nothing is stored here: the returned function stores the naming (the server's own
    save, and the mover's notice) and the caller runs it just before the write's own save, so a write a later gate refuses leaves the item exactly
    as it was, the needs list included. Nothing on a closed item (`was`), on a write that names the agent itself, or without a sender; nothing on a write
    that is not plain work (`plain` false: it sets needs itself, `none` included, parks the item with hold or wake, sets or
    clears a recycle, or is filing only, service/update.py's _FILING_ONLY: a page rename's update(project=<new key>) did no work on the item), since such a
    write says where the move is, or none was made, and naming the agent would undo it or invent it. → the function that stores the naming and returns the reply line, or ""."""
    nothing = lambda: ""
    sender = str(sender or "").strip()
    if was != "open" or not sender or not plain:
        return nothing
    agent = _back_agent(sender)
    if not agent:
        return nothing
    nm = _anc.names()
    me = _anc.canonical(agent, nm)
    if any(_anc.canonical(s, nm) == me for s in [*was_needs, *_needs_sessions(meta)] if s.lower() not in _NEEDS_KINDS):
        return nothing
    if _never_named(agent, nm):
        return nothing
    why = f"{'close' if closing else 'update'} by {_sr._session_label(sender)}"
    if not closing:
        _needs_store(meta, _canon_needs([*_needs_of(meta), _sr._store_ref(agent)], nm))
    return lambda: _auto_name(gid, _svcstore._load(gid), agent, sender, why, "" if closing else "after its update", nm)


def _router_delivered(target: str, text: str, outcome: str) -> str:
    """The router's push to `target` came back `outcome`: an open hand-off to it of an item the text names is delivered (_handoff.handoff_told_text). → the outcome, unchanged."""
    _handoff.handoff_told_text(target, text, outcome, link_only=True)
    return outcome
