"""client_reads.py: the reads of the client API and the item facts they carry.

What a machine's hooks read: the page registry, the brief, the rulebook, a page's freshness, the open items a session moves (`items?key=`) and what the end-of-turn check needs about the items a reply names
(`item-facts`), served to a machine that proves itself with its own token, so a client needs no checkout of the repository. `_client_get` is the one entry of the read calls (web/routes/client_api.py is the thin
surface that serves it); `_client_items` and `_client_item_facts` read the store once per call; `_wait_fields`, `_then_label_raw`, `_item_mover_model`, `_item_mover`, `_item_mover_label`, `_basis_wait_of` and
`_item_list` are the readers of an item's mover, its `then`, its wait and its list that those two (and the wake passes, the update's hand-over and the tools that probe an item) share.

A service module: it reads the store and writes nothing. What it still reaches in the surface (the rulebook text, the renderer's brief and words, the notice's ruling, the report of holds, the page's time, the board's
ids as shown, the home page's list rule, the queue map and the time zone) comes through `Hooks` in service/passes_hooks.py, which server.py fills at its import. A suite that replaces one of these functions sets it on this
module (and `time` here, since this module reads its own clock).

Imports point down only: this module imports the domain, core and the services beside it, never web/ and never audit/."""
from __future__ import annotations

import datetime as dt
import json
import re
import time
from typing import Any

from fastmcp.exceptions import ToolError

from stackshot.anchors import anchors as _anc
from stackshot.core import config as _cfg
from stackshot.core import store as _store
from stackshot.core.store import _item_files
from stackshot.fleet import sessions_registry as _sr
from stackshot.github import ghsync as _gh
from stackshot.model import item_project as _ip
from stackshot.model import model as _model
from stackshot.model import queued as _queued
from stackshot.model import states as _states
from stackshot.model.ids import _GID
from stackshot.model.needs import _needs_of, _needs_sessions
from stackshot.projects import projects as _prj
from stackshot.projects.project_registry import ROLES, _registry, _roles_sync_safe
from stackshot.service import agents as _agents
from stackshot.service import answer_handover as _handover
from stackshot.service import contacts as _contacts
from stackshot.service import foryou as _fy
from stackshot.service import gates as _gates
from stackshot.service import item_read as _item_read
from stackshot.service.passes_hooks import hooks as _hooks
from stackshot.service.projects import _projects_list
from stackshot.service.store import _legacy_hold, _legacy_needs, _path
from stackshot.waits import dated_wait as _dw
from stackshot.waits import waiting as _wt


def _client_get(what: str, params: dict[str, str]) -> tuple[int, str, str]:
    """One read of the client API → (status, content type, body)."""
    if what == "registry":
        try:
            return 200, "application/json", _gates.registry_text()
        except Exception:
            return 503, "text/plain", "no registry yet"
    if what == "roles":                 # roles.json as the server keeps it; written here first if it is not there yet
        if not ROLES.exists():
            _roles_sync_safe()
        try:
            return 200, "application/json", ROLES.read_text(encoding="utf-8")
        except Exception:
            return 503, "text/plain", "no roles yet"
    if what == "rules":
        return 200, "text/markdown; charset=utf-8", _hooks().rules_text("full")
    if what == "brief":
        return 200, "text/plain; charset=utf-8", _hooks().rmod_render(str(_store.STORE), "brief")
    if what == "project":               # phase A: one project's record by id, full key or bare slug: {id, key, keeper, agents}
        key = str(params.get("key") or "").strip()
        if not key or len(key) > 200:
            return 400, "text/plain", "key = a project: its id (prj_<8 hex>), its page key or its bare slug"
        try:
            recs = _prj.refs(key, _registry("projects"))
        except ValueError as e:         # the id file is damaged and the registry has no id for the page: nothing is minted, the reader tries again
            return 503, "text/plain", f"the project record cannot be read right now: {e}"
        if not recs:
            return 404, "text/plain", f"no project {key!r}: an id (prj_<8 hex>), a page key (projects/<slug>, infra/<slug>) or a bare slug of a page in the registry"
        if len(recs) > 1:
            return 400, "text/plain", f"{key!r} is ambiguous: it names {' and '.join(r['key'] for r in recs)}; write the full key or the id"
        return 200, "application/json", json.dumps(recs[0], ensure_ascii=False)
    if what == "projects":              # the fleet tool's New session form: the listed projects of a scope, hidden ones too when q matches (projects?scope=<s>&q=<text>)
        return _projects_list(params)
    if what == "page-ts":
        key = _prj.to_key(str(params.get("key") or "").strip("/"))
        if key.endswith(".md"):
            key = key[:-3]
        if not re.fullmatch(_cfg.page_dirs_re() + r"/[\w./-]+", key) or ".." in key:
            return 400, "text/plain", "key = a page key, " + " or ".join(f"{d}/<slug>" for d in _cfg.page_dirs())
        ts = int(_hooks().page_ts(key))
        return 200, "application/json", json.dumps({"key": key, "ts": ts or None})
    if what == "items":
        return _client_items(str(params.get("key") or ""))
    if what == "item-facts":
        return _client_item_facts(str(params.get("key") or ""), str(params.get("ids") or ""))
    if what == "answer":                # a script reads the owner's latest board answer on an item (client.py get answer board#N)
        return _handover._client_answer(str(params.get("key") or ""))
    if what == "notice":                # a script reads what the router did with a notice (client.py get notice <id>): the text get(item_id=<id>) shows
        nid = _hooks().notice_asked("notice " + str(params.get("key") or "").strip())
        if not nid:
            return 400, "text/plain", "key = a notice id: the six hex characters a message to a project returns (\"notice a1b2c3\")"
        try:
            return 200, "text/plain; charset=utf-8", _hooks().notice_report(nid)
        except ToolError as e:
            return 404, "text/plain", str(e)
    if what == "holds":                 # the open items on hold whose hold names no reason: read only, each mover releases its own
        return 200, "text/plain; charset=utf-8", _hooks().holds_report()
    if what == "for-you":               # the For you list: {"generated", "rows": newest first, "flags": {item: watch | mute}} (the fleet tool's items sheet reads it)
        return 200, "application/json", json.dumps(_fy.payload(_gh.shown), ensure_ascii=False)
    return 404, "text/plain", "no such read: registry | rules | brief | project?key=<id | page key | slug> | projects?scope=<" + "|".join([*_prj.scopes(), "all"]) + r">[&q=<text>] | page-ts?key=<page key or project id> | items?key=<session> | item-facts?key=<session>&ids=<id,…> | answer?key=<item id> | notice?key=<notice id> | holds | for-you | whoami | config | roles"


def _wait_fields(gid: str, it: dict[str, Any], ctx: "_agents._WaitCtx") -> dict[str, Any]:
    """The wait fields on an item as the items API carries them (the web board and the fleet tool read them): mover {kind, who, via?}. The fields that
    carried a computed expected-by time stay in the answer so that a reader written against them does not break, always empty (expected_by null, wait "",
    overdue null): they go in a later release."""
    try:
        mv = dict(ctx.mover(gid, it))
    except Exception:  # noqa: BLE001  — a reading that fails never fails the list
        return {}
    if mv.get("kind") == _wt.OWNER_KIND:
        mv["kind"] = _cfg.owner_mover_kind()      # [items_api] owner_mover_kind: the word a reader of the API matches for the owner's move ("legacy" by default, or "owner")
    elif mv.get("kind") == "session":
        mv["who"] = _sr._session_label(str(mv.get("who") or "")) or str(mv.get("who") or "")
    if mv.get("via"):
        mv["via"] = _gh.shown(str(mv["via"]))
    return {"mover": mv, "expected_by": None, "wait": "", "overdue": None}


_ROLE_MOVER, _ROLE_THEN, _ROLE_NEEDS = "mover", "then", "needs"     # the values of a client items row's `roles` (pages.py words them)


def _client_items(key: str) -> tuple[int, str, str]:
    """`items?key=<session>`: the open items a session moves, for the end-of-turn board check in
    pages.py. key = the asking session as its hook knows it: a transcript uuid, a cse_ id or a pane name. An item is its own when
    it moves (its needs, its stored mover, or the project's builder, else its -main agent when nothing names one) or takes after the owner's answer (`then`: the creator is no
    one's), or when it names the session in its needs, with role "agent" (the key the hooks have read since an earlier change). Every row carries `roles`: the asking session's live roles on the item, from "mover", "then" and "needs" (named in it); the alive item a session moves without keeping or being named is listed too. One pass over the store, one read of
    the fleet's names. Held items, items that wait on an open item (after) and doing items the board lists as waiting for a wake that states its reason (wait_basis) are listed with held: true (the hook skips them). Every row carries `list`: the home page's list the item is in, "your-move", "agents" or "waiting" (home.list_of), the key the fleet tool's items sheet groups by, so it shows the page's three groups; never empty (an item the page cannot place is in "agents", as there)."""
    k = str(key or "").strip()
    if not k or len(k) > 200 or any(c in k for c in "\r\n\t"):
        return 400, "text/plain", "key = the asking session: its transcript uuid, cse_ id or pane name"
    nm = _anc.names()
    me = {k, _anc.canonical(k, nm)}
    me |= {nm.get(x, "") for x in list(me)}
    me.discard("")
    out = []
    now = time.time()
    ctx = _agents._WaitCtx(now)                # every open item has a mover, listed whatever wait it is in
    for gid, p in _item_files():
        try:
            with open(p, encoding="utf-8") as f:
                it = json.load(f)
        except Exception:
            continue
        if not isinstance(it, dict):
            continue
        _legacy_hold(it); _legacy_needs(it); _ip.read_through(it)
        if it.get("status") != "open":
            continue
        m = it.get("metadata") or {}
        linked = any({ag, _anc.canonical(ag, nm)} & me for ag in _needs_sessions(m))   # named in its needs
        mv_, alive_ = _item_mover_model(dict(it, gid=gid))
        is_mover = bool(alive_ and mv_ and not _model.is_owner(mv_) and ({mv_, _anc.canonical(mv_, nm)} & me))      # the item's mover, by its needs, its stored mover or the project's default (builder, else -main agent)
        th_ = _then_label_raw(dict(it, gid=gid))
        is_then = bool(th_ and ({th_, _anc.canonical(th_, nm)} & me))
        theirs = me if (is_mover or is_then) else set()        # the rows' `mine`: this session moves the item or takes it after the owner
        if not (is_mover or is_then or linked):
            continue
        try:
            su = float(it.get("state_updated") or 0) or None
        except (TypeError, ValueError):
            su = None
        try:
            up = float(it.get("updated") or 0) or None    # any write, a filing edit too (an ask-only update moves only this)
        except (TypeError, ValueError):
            up = None
        st_, st_derived = _states.of(it, lambda i_: _item_read._after_open(i_.get("metadata") or {}))     # the item's stored state, or the one derived from its fields (not sent)
        # the asking session's live roles on the item, as the server holds them now (the end-of-turn text shows them): "mover" (it moves the alive item: by its needs, its
        # stored mover or the project's default), "then" (it takes the item after the owner's answer) and "needs" (named in its needs).
        roles = ([_ROLE_MOVER] if is_mover else []) + ([_ROLE_THEN] if is_then else []) + ([_ROLE_NEEDS] if linked else [])
        out.append({"gid": gid, "shown": _gh.shown(gid), "subject": str(it.get("subject") or ""), "needs": _hooks().shown_needs(_needs_of(m)),
                    **({"state": st_, "state_fields": _states.carry_of(it)} if not st_derived else {}),      # only an item that stores a state carries it: the word an item reads as is not sent
                    "contact": _contacts._contact_label(dict(it, gid=gid)),
                    "next": str(m.get("next") or ""), "state_updated": su, "confirmed": _hooks().rmod_confirmed_at(it, p),
                    "updated": up, "held": _item_read._is_parked(it) or bool(_item_read._after_open(m)) or _basis_wait_of(dict(it, gid=gid)), "list": _item_list(dict(it, gid=gid)), **_wait_fields(gid, it, ctx),
                    "roles": roles, **({"role": "agent"} if linked else {})})      # "agent": named in the item's needs (the session named in needs is its mover too, so the key no longer excludes it)
    return 200, "application/json", json.dumps({"items": out}, ensure_ascii=False)


def _then_label_raw(item: dict[str, Any]) -> str:
    """The session id or name an alive item's `then` (stored, else the model's) or a waiting item's post-wake mover names; "" for none or the owner."""
    try:
        mod = _item_read._model_of(dict(item, gid=str(item.get("gid") or item.get("id") or "")))
        who = mod.then if mod.state == _model.ALIVE else ((mod.then if _model.is_owner(mod.wait.mover) else mod.wait.mover) if mod.wait else "")      # a waiting item's picker takes the role `then` (or, when he picks it up, the `then` beside him)
    except Exception:  # noqa: BLE001
        who = ""
    return "" if (not who or _model.is_owner(who)) else who


def _item_mover_model(item: dict[str, Any]) -> tuple[str, bool]:
    """(who moves the item now as _item_mover reads it, whether the item is alive): "" and False when the reading fails or the item is closed."""
    try:
        mod = _item_read._model_of(dict(item, gid=str(item.get("gid") or item.get("id") or "")))
        alive = mod.state == _model.ALIVE
        return (mod.mover if alive else (mod.wait.mover if mod.wait else "")), alive
    except Exception:  # noqa: BLE001
        return "", False


def _basis_wait_of(item: dict[str, Any]) -> bool:
    """Is the open item a doing item the board lists as waiting for a wake that states its reason (dated_wait.basis_wait)? The end-of-turn board question skips it like a held one."""
    try:
        return _dw.basis_wait(item, time.time(), lambda i_: _item_read._after_open(i_.get("metadata") or {})) is not None
    except Exception:  # noqa: BLE001
        return False


def _item_list(item: dict[str, Any]) -> str:
    """Which of the home page's three lists an open item is in, as the wire word: "your-move", "agents" or "waiting" (home.list_of on the model's reading). The home page's own
    rule for an item it cannot place (a failed reading, or a dead one) is Agents at work (home.classify), so the field is never empty: the items sheet groups as the page does."""
    try:
        it = dict(item, gid=str(item.get("gid") or item.get("id") or ""))
        vw = _model.view(it, _item_read._model_of(it), after_open=lambda i_: _item_read._after_open(i_.get("metadata") or {}))
        which = _hooks().home_list_of(_queued.overlay(vw, _hooks().queue_map().get(it["gid"], "")))     # a doing item with a far wake and every step dated is listed as waiting, and one queued behind its mover's other item
    except Exception:  # noqa: BLE001
        which = ""
    return which or _hooks().home_agents()


def _item_mover(item: dict[str, Any]) -> str:
    """Who moves the item now, as stored or derived (the model's mover, else for a waiting item who takes it when the wait ends); "" for a closed item or when the reading fails."""
    return _item_mover_model(item)[0]


def _item_mover_label(item: dict[str, Any], names: dict[str, str], who: str | None = None) -> str:
    """The mover as a person reads it; "" for a closed item or when the reading fails. `who` = the mover when the caller has read it already (_item_mover)."""
    try:
        who = _item_mover(item) if who is None else who
        if not who or _model.is_owner(who):
            return who
        return names.get(_anc.canonical(who, names), "") or _sr._session_label(who)
    except Exception:  # noqa: BLE001
        return ""


def _client_item_facts(key: str, ids: str) -> tuple[int, str, str]:
    """`item-facts?key=<session>&ids=g7,g8`: what the end-of-turn check needs about the items a reply's Board lines
    name, so it can note a line about an item the session is neither the mover nor the `then` of nor the linked agent of, or one already closed (a
    session that kept reporting on a closed item). Per known id: status, mover (the mover's name), mover_me (the asking session
    is the mover), mine (the session is its `then`), agent (the item names the session in its needs), project (its metadata.project, for the pane's
    page gate when a portal write's reply did not say it), and for a closed item its close time in words and outcome. An
    unknown id is left out."""
    k = str(key or "").strip()
    if not k or len(k) > 200 or any(c in k for c in "\r\n\t"):
        return 400, "text/plain", "key = the asking session: its transcript uuid, cse_ id or pane name"
    want = [g.strip().lower().replace("#", "") for g in str(ids or "").split(",") if g.strip()][:20]
    if not want or not all(_GID.match(g) for g in want):
        return 400, "text/plain", "ids = item ids, comma-separated (at most 20)"
    nm = _anc.names()
    me = {k, _anc.canonical(k, nm)}
    me |= {nm.get(x, "") for x in list(me)}
    me.discard("")
    out = {}
    for g in dict.fromkeys(want):
        p = _path(g)
        try:
            with open(p, encoding="utf-8") as f:
                it = json.load(f)
        except Exception:
            continue
        if not isinstance(it, dict):
            continue
        _legacy_needs(it)
        m = it.get("metadata") or {}
        mover = _item_mover(it)
        th_ = _then_label_raw(dict(it, gid=g))
        row = {"status": str(it.get("status") or ""), "shown": _gh.shown(g),
               "mover": _item_mover_label(it, nm, mover), "mover_me": bool(mover and ({mover, _anc.canonical(mover, nm)} & me)),
               "mine": bool(th_ and ({th_, _anc.canonical(th_, nm)} & me)), "agent": any({ag, _anc.canonical(ag, nm)} & me for ag in _needs_sessions(m)),
               "project": str(m.get("project") or ""), "contact": _contacts._contact_label(it)}
        if row["status"] != "open":
            try:
                ts = float(it.get("state_updated") or it.get("updated") or 0)
            except (TypeError, ValueError):
                ts = 0.0
            if ts:
                row["closed"], row["closed_words"] = ts, _hooks().rmod_when_words(dt.datetime.fromtimestamp(ts, _hooks().zone()))
            if m.get("outcome"):
                row["outcome"] = str(m["outcome"])
        out[g] = row
    return 200, "application/json", json.dumps({"items": out}, ensure_ascii=False)
