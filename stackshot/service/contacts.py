"""contacts.py: an item's contact (model/contact.py has the rules): the front agent the person the board is for talks to about the item, stored in `metadata.contact`, a filing field. The readers of it (`_contact_of`,
`_contact_label`, `_contact_default`), the write of one (`_contact_set`), what follows a retired or renamed agent (`_contact_fall_retired`, `_contact_follow_rename`, `_contact_after_agent`), the backfill and its dry run
(`_contact_backfill`) and the project's -main agent as the pages will list it once an agent is off the map (`_main_agent_without`).

A service module: it reads the store and the registry, writes a contact through the write path (`service/writes.py`), and tells nobody."""
from __future__ import annotations

import sys
from typing import Any

from stackshot.anchors import anchors as _anc
from stackshot.core.store import _item_files
from stackshot.fleet import sessions_registry as _sr
from stackshot.fleet.sessions_registry import _same_sess
from stackshot.fleet.sessions_registry import _store_ref
from stackshot.github import ghsync as _gh
from stackshot.model import contact as _contact
from stackshot.model import migration as _mig
from stackshot.service import store as _svcstore
from stackshot.service import telling as _telling
from stackshot.service import writes as _writes
from stackshot.service import agents as _agents


def _contact_fronts(project: str) -> dict[str, str]:
    """The project's front agents with their mandate lines ({} when it lists none, or the registry cannot be read)."""
    try:
        return _contact.fronts(project)
    except Exception as e:  # noqa: BLE001  — a registry that cannot be read names nobody
        print(f"contact: front agents of {project} not read ({e.__class__.__name__}: {e})", file=sys.stderr, flush=True)
        return {}


def _contact_same(a: str, b: str) -> bool:
    """Do two references name one session: as permanent ids when both resolve, else as the names stand (case-folded), or as the fleet's canonical ids."""
    a, b = str(a or "").strip(), str(b or "").strip()
    if not a or not b:
        return False
    if a.casefold() == b.casefold() or _same_sess(a, b):
        return True
    try:
        nm = _anc.names()
        return _anc.canonical(a, nm) == _anc.canonical(b, nm)
    except Exception:  # noqa: BLE001
        return False


def _contact_alive(contact: str) -> bool:
    """Is a stored contact still a front agent (of any project: a front agent that created an item of another project stays its contact)?"""
    return _telling.front_sender(contact)


def _contact_default(creator: str, project: str) -> str:
    """The contact of an item nobody named one for: its creator when that is a front agent, else the project's -main agent; "" when the project names neither."""
    if creator and _telling.front_sender(creator):
        return _store_ref(creator)
    main = _agents._main_agent(project)
    return _store_ref(main) if main else ""


def _contact_of(meta: dict[str, Any]) -> str:
    """The item's contact as it stands now: the stored one while it is still a front agent, else the project's -main agent ("" when none)."""
    c = str(meta.get("contact") or "").strip()
    if c and _contact_alive(c):
        return c
    return _agents._main_agent(str(meta.get("project") or ""))


def _contact_label(item: dict[str, Any]) -> str:
    """The contact as people read it (the session's current name): an open item's live contact, a closed item's stored one; "" when none."""
    m = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    c = _contact_of(m) if item.get("status") == "open" else str(m.get("contact") or "").strip()
    return _sr._session_label(c) if c else ""


def _main_agent_without(project: str, name: str) -> str:
    """The project's -main agent as the pages will list it once `name` is off the agents map (the registry follows a retire minutes late)."""
    try:
        reg = _anc.registry()
        gone = name.casefold()
        out = {}
        for k, e in reg.items():
            if isinstance(e, dict) and gone in {str(n).casefold() for n in (e.get("agents") or {})}:
                e = {**e, "agents": {n: m for n, m in (e.get("agents") or {}).items() if str(n).casefold() != gone},
                     "back_agents": {n: m for n, m in (e.get("back_agents") or {}).items() if str(n).casefold() != gone}}
            out[k] = e
        return _anc.fallback_main(project, out)
    except Exception:  # noqa: BLE001
        return ""


def _contact_set(gid: str, new: str, was: str, why: str) -> bool:
    """Store a contact on an open item as a filing write by the server (the migration author): no state, clock, hand-off or page moves. → True when written."""
    with _writes.ITEM_LOCK:
        it = _svcstore._load(gid)
        meta = it.get("metadata") if isinstance(it.get("metadata"), dict) else {}
        if it.get("status") != "open" or str(meta.get("contact") or "") != was:
            return False                                        # the item moved on since it was read
        if new:
            meta["contact"] = new
        else:
            meta.pop("contact", None)
        it["metadata"] = meta
        _writes.save(gid, it, note=why, author=(_mig.AUTHOR, _mig.AUTHOR), mirror=False)
    return True


def _contact_fall_retired(name: str) -> list[str]:
    """`name` left its project (retired): every open item whose stored contact is that session falls to its project's -main agent (the one the pages will list without it).
    → the ids of the items changed. Never raises: a retire is not failed over it."""
    moved: list[str] = []
    try:
        for gid, _p in _item_files():
            try:
                it = _svcstore._load(gid)
            except Exception:  # noqa: BLE001
                continue
            meta = it.get("metadata") if isinstance(it.get("metadata"), dict) else {}
            c = str(meta.get("contact") or "").strip()
            if it.get("status") != "open" or not c or not _contact_same(c, name):
                continue
            main = _main_agent_without(str(meta.get("project") or ""), name)
            new = _store_ref(main) if main and not _contact_same(main, name) else ""
            if _contact_set(gid, new, str(meta.get("contact") or ""), f"contact {_sr._session_label(c)} retired: now {_sr._session_label(new) if new else 'none'}"):
                moved.append(_gh.shown(gid))
    except Exception as e:  # noqa: BLE001
        print(f"contact: retire pass for {name} stopped: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    return moved


def _contact_follow_rename(old: str, new: str) -> list[str]:
    """An agent's page entry was renamed `old` → `new`: a contact stored as the plain name `old` (the registry resolved no permanent id for it) becomes `new` on the open items; one
    stored as a permanent id needs no change (the name shown follows the session). → the ids of the items changed. Never raises."""
    moved: list[str] = []
    try:
        for gid, _p in _item_files():
            try:
                it = _svcstore._load(gid)
            except Exception:  # noqa: BLE001
                continue
            c = str((it.get("metadata") if isinstance(it.get("metadata"), dict) else {}).get("contact") or "").strip()
            if it.get("status") == "open" and c and c.casefold() == old.casefold() and _contact_set(gid, _store_ref(new), c, f"contact {old} is now {new}"):
                moved.append(_gh.shown(gid))
    except Exception as e:  # noqa: BLE001
        print(f"contact: rename pass for {old} stopped: {e.__class__.__name__}: {e}", file=sys.stderr, flush=True)
    return moved


def _contact_after_agent(out: tuple[int, dict[str, Any]], kind: str, *names: str) -> tuple[int, dict[str, Any]]:
    """The contacts follow a page's agent entry that was retired (`kind` "retire", names = (the agent,)) or renamed ("rename", names = (old, new)): run after the page write answered 200,
    and name the items changed in the answer as `contact_moved` (left out when none). Any other answer passes through untouched."""
    status, body = out
    if status != 200 or not isinstance(body, dict):
        return out
    moved = _contact_fall_retired(names[0]) if kind == "retire" else _contact_follow_rename(names[0], names[1])
    return (status, {**body, "contact_moved": moved}) if moved else out


def _contact_backfill(dry: bool = True) -> dict[str, Any]:
    """The backfill and its dry run (`client.py backfill-contact [--dry-run]`, tools/backfill_contact.py on a copy of the store): every open item without a live contact gets one,
    the creator when that was a front agent, else the project's -main agent (contact.plan has the rules). Closed items are left. → {"counts": {rule: n}, "items": [{item, project, rule,
    was, to}], "written": n, "dry_run": bool}. A dry run writes nothing; a second run writes nothing (the items have a contact then)."""
    mains: dict[str, str] = {}
    fronts: dict[str, bool] = {}
    rows: list[dict[str, Any]] = []
    counts = {r: 0 for r in _contact.RULES}
    written = 0
    for gid, _p in _item_files():
        try:
            it = _svcstore._load(gid)
        except Exception:  # noqa: BLE001
            continue
        meta = it.get("metadata") if isinstance(it.get("metadata"), dict) else {}
        project = str(meta.get("project") or "")
        creator = str(meta.get("owner") or "").strip()
        if project not in mains:
            mains[project] = _agents._main_agent(project) if project else ""
        if creator not in fronts:
            fronts[creator] = bool(creator) and _telling.front_sender(creator)
        new, rule = _contact.plan(it, creator_front=fronts[creator], main=(_store_ref(mains[project]) if mains[project] else ""), alive=_contact_alive)
        counts[rule] += 1
        if rule in (_contact.RULE_CLOSED, _contact.RULE_HAS):
            continue
        row = {"item": _gh.shown(gid), "project": project, "rule": rule, "was": _sr._session_label(str(meta.get("contact") or "")), "to": _sr._session_label(new)}
        if new and not dry:
            ok = _contact_set(gid, _store_ref(new), str(meta.get("contact") or ""), f"contact filled in: {_sr._session_label(new)} ({rule})")
            row["written"] = ok
            written += int(ok)
        rows.append(row)
    return {"dry_run": bool(dry), "counts": counts, "items": rows, "written": written}
