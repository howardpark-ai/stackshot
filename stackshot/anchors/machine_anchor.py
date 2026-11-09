"""machine_anchor.py: a machine of the fleet as an anchor.

An item whose open step needs a machine that is offline used to sit on a date check-back long after the machine was back; only a `box_online <machine>` event wait turned
an item, one machine per item, and only when its mover had set it by hand. A machine anchor is the standing form: the anchors tool takes `machine:<name>` beside the URLs
(`anchors(project, add=["machine:box-a"], items=["board#N"])`), and every item the anchor counts for has its mover told, once, each time that machine checks in again
(offline to online). An item may name several machines; each notice says which one came back. The item is not turned and not saved: a machine anchor is a notice, never a wait.

Why a store of its own and not anchors.json. An anchor in anchors.json is a thing anchor-hub reads, the board pages draw on an item, the model guards read as a hold and a completion
asks its page's keeper about. None of that fits a machine, so a machine anchor lives in `machine-anchors.json` beside it: {"<project key>": [{"machine": fleet name, "items": [ids] | null,
"added": ts, "by": who}, …]}, the same shape of entry and the same scope rule as an anchor (items = the item ids it is about, null = project-wide), and nothing else reads it.

What counts for an item: an entry of any project's page that lists the item, and a project-wide entry of the item's own project. A project-wide machine anchor tells the mover of each
open item of its project whose open step names the machine (whole word, `names_in`); an item-scoped one tells for the item whether or not a step names it, since the scope says it.

The check-in is the machine's own record in the clients state: `online_since` is stamped by clients.checkin exactly when a puller that was offline checks in. `seen` below keeps, per machine,
the `online_since` the last notice answered (state/machine-anchor.json); a record newer than that is a check-in not yet told, and one notice answers every check-in up to it. The
mark is set when an anchor is added (`seed`), so a machine that is online when the anchor is added, or that checked in before, tells nothing.

Stdlib and the config only (imported by server.py, which supplies the machine records and sends the notices)."""
from __future__ import annotations

import json
import os
import re
import threading
import time
from typing import Any

from stackshot.core import config as _cfg  # noqa: E402
from stackshot.core import readonly as _ro  # noqa: E402  (a warm standby copy writes nothing)

PREFIX = "machine:"
LOCK = threading.RLock()      # a read-modify-write of the store (the anchors tool on a request thread, the pass on the runner's) holds it


def _file():
    return _cfg.path("paths", "store") / "machine-anchors.json"


def _seen_file():
    return _cfg.state("machine-anchor.json")


# ---------------------------------------------------------------- the spelling
def is_machine(s: Any) -> bool:
    """`machine:<name>` (the prefix in any case), the form the anchors tool's add and remove take for a machine."""
    return isinstance(s, str) and s.strip().lower().startswith(PREFIX)


def name_of(s: str) -> str:
    """The machine name of a `machine:<name>` entry, as written (stripped)."""
    return s.strip()[len(PREFIX):].strip()


def shown(machine: str) -> str:
    return PREFIX + machine


# ---------------------------------------------------------------- the store
def load() -> dict[str, list[dict[str, Any]]]:
    """{project key: [entry, …]}; a missing or unreadable file, a page that is no list and an entry that names no machine hold nothing."""
    try:
        d = json.load(open(_file(), encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    out: dict[str, list[dict[str, Any]]] = {}
    for page, es in (d.items() if isinstance(d, dict) else ()):
        rows = [{**e, "machine": e["machine"].strip(), "items": [str(g) for g in e["items"]] if isinstance(e.get("items"), list) and e["items"] else None}
                for e in (es if isinstance(es, list) else []) if isinstance(e, dict) and isinstance(e.get("machine"), str) and e["machine"].strip()]
        if rows:
            out[str(page)] = rows
    return out


def save(d: dict[str, list[dict[str, Any]]]) -> None:
    _ro.guard("machine anchors write")
    f = _file()
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f".machine-anchors.json.{os.getpid()}.{threading.get_ident()}.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({k: v for k, v in sorted(d.items()) if v}, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, f)


def add(store: dict, project: str, machines: list[str], scope: list[str] | None, by: str) -> list[dict[str, Any]]:
    """Add machines (fleet names) to a project: a machine already there takes the new items into its scope (project-wide when none are given), as anchors.add does for a URL."""
    lst = store.setdefault(project, [])
    now = time.time()
    for m in machines:
        cur = next((e for e in lst if e.get("machine", "").lower() == m.lower()), None)
        if cur is None:
            lst.append({"machine": m, "items": sorted(set(scope)) if scope else None, "added": now, "by": by})
        elif scope and cur.get("items") is not None:
            cur["items"] = sorted(set(cur["items"]) | set(scope))
        elif not scope:
            cur["items"] = None
    return lst


def remove(store: dict, project: str, machines: list[str]) -> list[dict[str, Any]]:
    gone = {m.lower() for m in machines}
    lst = [e for e in store.get(project, []) if e.get("machine", "").lower() not in gone]
    if lst:
        store[project] = lst
    else:
        store.pop(project, None)
    return lst


def fmt(entries: list[dict[str, Any]], online: dict[str, bool] | None = None) -> str:
    """A project's machine anchors, one per line, with whether the machine is online now when the caller knows."""
    def now_(e: dict[str, Any]) -> str:
        st = (online or {}).get(e["machine"].lower())
        return "" if st is None else (" — online now" if st else " — offline now")
    return "\n".join(f"- {shown(e['machine'])}  [{'project-wide' if not e.get('items') else 'items: ' + ', '.join(e['items'])}]{now_(e)}" for e in entries)


def prune(store: dict, is_open: Any) -> bool:
    """Drop the closed and the gone items from the scoped entries (`is_open(gid)`), and an entry left with no item: a machine anchor that was about items nothing is open for is over. → True when the store changed."""
    changed = False
    for page in list(store):
        keep = []
        for e in store[page]:
            if e.get("items"):
                live = [g for g in e["items"] if is_open(g)]
                if len(live) != len(e["items"]):
                    changed = True
                if not live:
                    continue
                e = {**e, "items": live}
            keep.append(e)
        if keep:
            store[page] = keep
        else:
            store.pop(page)
    return changed


def counts(store: dict, gid: str, project: str) -> dict[str, tuple[str, bool]]:
    """The machine anchors that count for item `gid` of `project`: {lower-cased machine: (name as stored, scoped)}, from the entries of any page that list the item (scoped True) and the
    project-wide ones of the item's own page (scoped False, unless an entry lists the item too). Each machine once."""
    out: dict[str, tuple[str, bool]] = {}
    for page, es in store.items():
        for e in es:
            named = gid in (e.get("items") or [])
            if named or (not e.get("items") and page == project):
                k = e["machine"].lower()
                out[k] = (out[k][0] if k in out else e["machine"], named or (k in out and out[k][1]))
    return out


# ---------------------------------------------------------------- the check-ins
def seen_load() -> dict[str, float]:
    try:
        d = json.load(open(_seen_file(), encoding="utf-8"))
        return {str(k).lower(): float(v) for k, v in d.items()} if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def seen_save(d: dict[str, float]) -> None:
    _ro.guard("machine anchor state write")
    f = _seen_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f".machine-anchor.json.{os.getpid()}.{threading.get_ident()}.tmp")      # a name of its own per writer: two writers never share a temp file
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(d, fh, indent=1, sort_keys=True)
    os.replace(tmp, f)


def seed(machine: str, since: float) -> None:
    """Mark the machine's latest check-in (`online_since`, 0 when it never checked in) as already answered: what an anchor added now must never tell about. Only ever raises the mark."""
    d = seen_load()
    k = machine.lower()
    if k not in d or since > d[k]:
        d[k] = max(since, d.get(k, 0.0))
        seen_save(d)


def names_in(text: str, names: list[str]) -> list[str]:
    """Which of `names` (host or fleet names) `text` names as a whole word: not inside a longer name (`box-b` is not found in `box-b2` or `my-box-b`). Case ignored; in the order the names are given."""
    low = str(text or "").lower()
    return [n for n in names if n and re.search(r"(?<![\w-])" + re.escape(n.lower()) + r"(?![\w-])", low)]


# ---------------------------------------------------------------- the words
def notice(machine: str, at: str, rows: list[tuple[str, str, str]]) -> str:
    """The one message to a mover about a machine's check-in: rows are (item ref, subject, link)."""
    head = f"[stackshot] {machine} checked in{(' at ' + at) if at else ''}: it is online again."
    body = "".join(f"\n- {ref}: {subj} → {link}" for ref, subj, link in rows)
    return head + body + f"\nA machine anchor told you: the step that needs {machine} can go ahead. The anchor stays (anchors(project=…, remove=[\"{shown(machine)}\"]) drops it)."


def missing_note(gid_ref: str, project: str, machines: list[str], info: dict[str, str]) -> str:
    """The reply line of a write whose open step names offline machines that no machine anchor of the item covers. `info`: machine → "last checked in <when>" or "has not checked in yet"."""
    if not machines:
        return ""
    names = ", ".join(f"{m} ({info.get(m, 'offline')})" for m in machines)
    add_ = ", ".join(f'"{shown(m)}"' for m in machines)
    return (f"\n(note: an open step of {gid_ref} names {names}, offline now, and the item has no machine anchor for it, so nothing tells its mover when it is back. "
            f"Add one: anchors(project=\"{project}\", add=[{add_}], items=[\"{gid_ref}\"]); the mover is told at each check-in, and the item keeps its state.)")
