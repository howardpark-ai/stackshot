"""repoint.py: hand what open items hold under one session's name to another, before that session is retired (`client.py repoint FROM TO [--apply]`). A dry run unless asked to apply.

What moves on an open item: `mover`, `then` and a post-wake mover; the session's place in `needs` and `observers`; the open steps whose `next` line opens with its name (the line is then TO's, as is its
checklist step); `contact` (TO when it is a front agent, else the project's -main agent as the pages list it without FROM, else none); `tell_him` (only to a front agent, else left and reported). The
item's creator, its history and closed items are not changed. The instance's settings and the project record's marks that name FROM are listed, never edited.

A service module: it reads the store, the registry and the config, writes through the write path (`service/writes.py`) as filing writes of the server's own, and sends one notice to a new holder that
is not a front agent."""
from __future__ import annotations

import copy
import re
from typing import Any

from fastmcp.exceptions import ToolError

from stackshot.anchors import anchors as _anc
from stackshot.core import config as _cfg
from stackshot.core.store import _item_files
from stackshot.fleet import sessions_registry as _sr
from stackshot.github import ghsync as _gh
from stackshot.model import migration as _mig
from stackshot.model import model as _model
from stackshot.model import needs as _nd
from stackshot.model import nextlines as _nl
from stackshot.model import steps as _st
from stackshot.projects import keeper as _kp
from stackshot.projects import project_registry as _pr
from stackshot.service import contacts as _contacts
from stackshot.service import store as _svcstore
from stackshot.service import telling as _telling
from stackshot.service import writes as _writes

ONE_NAME = ("mover", "then", _model.LEGACY_PICKER_KEY)      # the fields that hold one session
HOLDS = {*ONE_NAME, "needs", "next"}                        # a change of one of these gives the new session something to do
NOTICE_IDS = 40                                             # the most items one notice names


def _listed(meta: dict[str, Any], key: str, is_old, new: str) -> list[str] | None:
    """The list `metadata[key]` with the old session replaced by `new`, each session once; None when the list does not name the old one."""
    read = {"needs": _nd._needs_of, "observers": _nd._observers_of, "tell_him": _nd._tell_him_of}[key]
    was = read(meta)
    if not any(is_old(x) for x in was):
        return None
    out: list[str] = []
    for x in (new if is_old(x) else x for x in was):
        if not any(x.casefold() == y.casefold() or _contacts._contact_same(x, y) for y in out):
            out.append(x)
    return out


def _move(meta: dict[str, Any], frm: str, ref: str, label: str, front: bool) -> tuple[list[str], list[str]]:
    """Change `meta` in place → (the fields changed, why a field that names the old session was left)."""
    def is_old(x: Any) -> bool:
        return str(x).casefold() not in _nd._NEEDS_KINDS and _contacts._contact_same(str(x), frm)
    changed: list[str] = []
    left: list[str] = []
    for k in ONE_NAME:
        if meta.get(k) and is_old(meta[k]):
            meta[k] = ref
            changed.append(k)
    needs = _listed(meta, "needs", is_old, ref)
    if needs is not None:
        _nd._needs_store(meta, _nd._canon_needs(needs))
        changed.append("needs")
    observers = _listed(meta, "observers", is_old, ref)
    if observers is not None:
        meta["observers"] = observers
        changed.append("observers")
    told = _listed(meta, "tell_him", is_old, ref)
    if told is not None:
        if front:
            meta["tell_him"] = told
            changed.append("tell_him")
        else:
            left.append(f"tell_him: {label} is not a front agent")
    rows = _nl.resolve(meta, str(meta.get("owner") or ""))
    reworded: dict[str, str] = {}
    for i, (line, writer) in enumerate(rows):
        name = _st.opener(line)
        if name and is_old(name):
            new = line.replace(name, label, 1)
            reworded[_nl.norm(line)] = new
            rows[i] = (new, ref if is_old(writer) else writer)
    if reworded:
        _nl.set_rows(meta, rows)
        if isinstance(meta.get("steps"), list):      # the stored open step follows its line, so its tag stays with it
            meta["steps"] = [{**s, "text": reworded[_nl.norm(s.get("text"))]} if isinstance(s, dict) and s.get("status") == _st.OPEN and _nl.norm(s.get("text")) in reworded else s for s in meta["steps"]]
        changed.append("next")
    contact = str(meta.get("contact") or "").strip()
    if contact and is_old(contact):
        new = ref
        if not front:
            main = _contacts._main_agent_without(str(meta.get("project") or ""), frm)
            new = _sr._store_ref(main) if main and not is_old(main) else ""
        if new:
            meta["contact"] = new
        else:
            meta.pop("contact", None)
        changed.append("contact")
    return changed, left


def _settings(name: str) -> list[str]:
    """Where the instance's settings and the project record's marks name `name`: key paths only, never a setting's value."""
    rx = re.compile(rf"(?<![\w-]){re.escape(name)}(?![\w-])", re.IGNORECASE)
    found: set[str] = set()

    def walk(v: Any, path: str) -> None:
        if isinstance(v, dict):
            for k, x in v.items():
                p = f"{path}.{k}" if path else str(k)
                if rx.search(str(k)):
                    found.add(f"setting {p}")
                walk(x, p)
        elif isinstance(v, (list, tuple)):
            for x in v:
                walk(x, path)
        elif isinstance(v, str) and rx.search(v):
            found.add(f"setting {path}")
    walk(_cfg.CFG, "")
    fold = name.casefold()
    for pid, e in _pr.entries().items():
        where = _pr.page_key(e) or pid
        agents = e.get("agents") or {}
        for n in agents:
            if n.casefold() == fold:
                found.add(f"project {where}: on the agents map" + (", with the keeper mark" if _kp.record_mark(agents)[0] == n else ""))
        for sub, n in (e.get(_kp.PAGES) or {}).items():
            if str(n).casefold() == fold:
                found.add(f"project {where}: keeper mark of the sub-page {sub}")
    return sorted(found)


def repoint(frm: str, to: str, apply: bool = False) -> dict[str, Any]:
    """→ {dry_run, from, to, to_front, items: [{item, project, changed, left, written?}], written, created: n open items `frm` created, settings: [str], told: [item ids the notice names]}.
    Refused (ToolError): a name missing, the person the board is for on either side, both names one session, or a TO no project page lists (or lists as retired). A second run finds nothing left to move."""
    frm, to = str(frm or "").strip(), str(to or "").strip()
    if not frm or not to:
        raise ToolError("from and to = two session names")
    for n in (frm, to):
        if _model.is_owner(n) or n.casefold() in _nd._NEEDS_KINDS:
            raise ToolError(f"{n} is not a session name")
    if _contacts._contact_same(frm, to):
        raise ToolError(f"{frm} and {to} are one session")
    roles = _anc.session_roles()
    listed = _sr._role_name(roles, to)
    if not listed or roles[listed].get("retired"):
        raise ToolError(f"no project page lists {to} as an agent in use: name one that is listed")
    ref, label = _sr._store_ref(to), _sr._session_label(to)
    front = _telling.front_sender(to)
    rows: list[dict[str, Any]] = []
    holds: list[str] = []
    written = created = 0
    for gid, _p in _item_files():
        with _writes.ITEM_LOCK:
            try:
                it = _svcstore._load(gid)
            except Exception:  # noqa: BLE001
                continue
            if it.get("status") != "open":
                continue
            meta = copy.deepcopy(it.get("metadata")) if isinstance(it.get("metadata"), dict) else {}
            creator = str(meta.get("owner") or "")
            created += bool(creator) and _contacts._contact_same(creator, frm)
            changed, left = _move(meta, frm, ref, label, front)
            if not changed and not left:
                continue
            row = {"item": _gh.shown(gid), "project": str(meta.get("project") or ""), "changed": changed, "left": left}
            if apply and changed:
                it["metadata"] = meta
                _writes.save(gid, it, note=f"{_sr._session_label(frm)} is leaving: {', '.join(changed)} moved to {label}", author=(_mig.AUTHOR, _mig.AUTHOR), mirror=False)
                row["written"] = True
                written += 1
                if HOLDS.intersection(changed):
                    holds.append(row["item"])
        rows.append(row)
    told = holds if holds and not front else []
    if told:
        more = f" and {len(told) - NOTICE_IDS} more" if len(told) > NOTICE_IDS else ""
        _telling.tell_woken(",".join(told), ref, f"[stackshot] {_sr._session_label(frm)} is leaving, and these open items name you in its place: {', '.join(told[:NOTICE_IDS])}{more}. "
                            "Read each with get and take its next step.", tag="repoint")
    return {"dry_run": not apply, "from": _sr._session_label(frm), "to": label, "to_front": front, "items": rows, "written": written, "created": created, "settings": _settings(_sr._session_label(frm)), "told": told}
