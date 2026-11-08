"""inbox.py — the server-side inbox: where a notice or a message waits until the session's own machine fetches it (the design doc).

The server box reaches into no other machine (since an earlier change this is the one path there; the ssh delivery is gone): push.py puts
the line here, and the machine's puller (puller.py) asks for what is waiting for the sessions live on it, hands each line to
the CLI's own inbox, and confirms. One file per item, <state>/inbox/<source>/<id>.json:
    {id, ts, src: hub|msg, to: <as addressed: a transcript uuid or a pane name>, uuid, name, pid, text}
`pid` is the PERMANENT session id the line is for (sessions_registry.py), resolved when the line is put (code finds a
session by its permanent id, names are for people): from a name, an alias, a transcript id or the permanent id itself, of a live registry session. A poll offers
the line to whichever live transcript carries that id (`_carriers`), so a relaunch with a new transcript, a rename or the CLI's placeholder name cannot strand it;
`name` keeps the session's name for display. A line with no `pid` (a name the registry does not know, a registry that was down, a line stored before an earlier change)
is matched as before: by the id and the name it carried when it was put (`uuid`, `name`). `uuid` and `name` are what `to` meant when the line was put,
so a line addressed to a pane that was since retired and spawned again under the same name finds the new pane instead of stranding under the old id.

A line handed to a puller is leased, not removed: it goes when the puller confirms it (ack), and is offered again when
the lease runs out. The pause flags and held lists of the reboot hooks apply here too: a paused source hands nothing out,
except to the keys a resume released. Cloud sessions are not served from here: the server box delivers to them itself.
Stdlib only: push.py, the server and the reboot hooks import it.
"""
from __future__ import annotations

import fcntl
import json
import logging
import os
import re
import secrets
import time
from pathlib import Path
from typing import Any

from stackshot.core import config as _cfg
from stackshot.fleet import liveness as _lv
from stackshot.fleet import sessions_registry as _sr

DIR: Path = _cfg.state("inbox")
FLAGS: Path = _cfg.state("anchor-hub")           # paused-<src>.json · held-<src>.txt · release-<src>.txt, shared with the push path
LEASE = 120.0                                    # s a handed-out line stays reserved for the puller that took it
RETRY = 10.0                                     # s before a line whose delivery failed is offered again
SOURCES = ("hub", "msg")
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
HEAD = {"hub": "[anchor]", "msg": "[stackshot]"}
log = logging.getLogger("stackshot.inbox")
STALE_LOG = 3600.0                               # s: one log line per stale hold entry per this long
_stale_logged: dict[str, float] = {}             # "<source>:<entry>" → when its line was last logged


def label(sender: str, text: str) -> str:
    """A drop opens with a short
    `from: <sender>` line, so a script's notice never reads as the owner's own prompt. A line stored before an earlier change has no sender
    and goes out as it was."""
    return f"from: {sender}\n{text}" if sender else text


class _locked:
    def __enter__(self):
        DIR.mkdir(parents=True, exist_ok=True)
        self.f = open(DIR / "lock", "w")
        fcntl.flock(self.f, fcntl.LOCK_EX)
        return self

    def __exit__(self, *a):
        fcntl.flock(self.f, fcntl.LOCK_UN); self.f.close()
        return False


def _leases() -> dict[str, float]:
    try:
        d = json.load(open(DIR / "leases.json", encoding="utf-8"))
        return {str(k): float(v) for k, v in d.items()}
    except Exception:
        return {}


def _save_leases(d: dict[str, float]) -> None:
    tmp = DIR / ".leases.json.tmp"
    json.dump(d, open(tmp, "w", encoding="utf-8")); os.replace(tmp, DIR / "leases.json")


def _items(src: str | None = None) -> list[dict[str, Any]]:
    out = []
    for s in ([src] if src else SOURCES):
        d = DIR / s
        if not d.is_dir():
            continue
        for p in d.glob("*.json"):
            try:
                it = json.load(open(p, encoding="utf-8"))
            except Exception:
                continue
            if isinstance(it, dict) and it.get("id"):
                out.append(it)
    return sorted(out, key=lambda it: (float(it.get("ts", 0)), str(it["id"])))


def _index() -> dict[str, dict[str, Any]]:
    """transcript uuid → {name, machine[, gone]} of every session the server knows (the same view every reader uses),
    identity records of gone sessions included."""
    try:
        from stackshot.fleet import fleet
        return {k: v for L in fleet.letters() for k, v in fleet.read(L, "sessions").items() if isinstance(v, dict)}
    except Exception:
        return {}


def _by_name(idx: dict[str, dict[str, Any]]) -> dict[str, str]:
    """name → uuid among the present sessions (fleet.by_name): a retired namesake never takes a line's id."""
    try:
        from stackshot.fleet import fleet
        return fleet.by_name(idx, present_only=True)
    except Exception:
        return {}


def _present(idx: dict[str, dict[str, Any]]) -> set[str]:
    """The sessions a line can still wait for: running, or gone for less than the grace (fleet.present). A session gone
    longer exists nowhere any more as far as delivery goes, so a line addressed to it by id follows its name (_target)."""
    try:
        return {u for u, r in idx.items() if _lv.present(r)}
    except Exception:
        return set(idx)


def _live_pid(ref: str) -> str:
    """The permanent id of the LIVE registry session `ref` (a permanent id, a transcript id, a name or an alias) names; '' when it names none, more than one, or a
    retired one (a retired session's name may be a pane's new name that the registry does not list yet: such a line keeps the name match)."""
    r = _sr.row(ref) if ref else None
    return str(r["id"]) if r and r.get("state") == "live" else ""


def put(to: str, text: str, src: str = "hub", now: float | None = None, sender: str = "") -> str:
    """One line for a session → its id. `to` = a transcript uuid, a pane name or a permanent session id, as the caller addressed it; `sender` goes out
    as the line's `from:`. The permanent id the reference resolves to is stored on the line (`pid`) and is what a poll matches by."""
    src = "msg" if src == "msg" else "hub"
    ref = str(to).strip()
    pid = _live_pid(ref)                  # from what the caller wrote, before it is turned into an address: a permanent id, a transcript id or a name all end here
    to = _sr.delivery(ref); idx = _index()       # a permanent session id is addressed by the session's name now (a pane has a name and a transcript id, never the id that outlives both)
    if UUID.match(to):
        uuid, name = to, str((idx.get(to) or {}).get("name") or "")
    else:                       # the running session of that name, else the one gone most recently (fleet.by_name): a line
        uuid, name = _by_name(idx).get(to, ""), to      # to a pane mid-relaunch records its id; a retired namesake never takes it
    if pid:
        name = _sr.display_name(pid) or name            # the name is for people: the session's name now
    iid = f"{int((time.time() if now is None else now) * 1000):013d}-{secrets.token_hex(3)}"
    it = {"id": iid, "ts": time.time() if now is None else now, "src": src, "to": to, "uuid": uuid, "name": name, "pid": pid, "text": text, "from": sender}
    with _locked():
        d = DIR / src; d.mkdir(parents=True, exist_ok=True)
        tmp = d / f".{iid}.tmp"
        json.dump(it, open(tmp, "w", encoding="utf-8"), ensure_ascii=False); os.replace(tmp, d / f"{iid}.json")
    return iid


def peek(ids: list[str]) -> list[dict[str, Any]]:
    """The waiting lines with these ids, as stored (read before an ack removes them); [] for ids that are gone."""
    out: list[dict[str, Any]] = []
    for iid in ids or []:
        if "/" in iid or iid.startswith("."):
            continue
        for s in SOURCES:
            try:
                out.append(json.loads((DIR / s / f"{iid}.json").read_text(encoding="utf-8")))
                break
            except (OSError, ValueError):
                continue
    return out


def exists(iid: str) -> bool:
    return any((DIR / s / f"{iid}.json").exists() for s in SOURCES)


def _lines(p: Path) -> set[str]:
    try:
        return {ln.strip() for ln in open(p, encoding="utf-8") if ln.strip()}
    except Exception:
        return set()


def blocked(src: str) -> tuple[bool, set[str], set[str]]:
    """(the source is paused, the keys a resume released while it is, the keys a resume held back)."""
    return (FLAGS / f"paused-{src}.json").exists(), _lines(FLAGS / f"release-{src}.txt"), _lines(FLAGS / f"held-{src}.txt")


def _keys(it: dict[str, Any]) -> set[str]:
    """What a hold or a release may name this line by: the address, the transcript uuid, the pane name, and the permanent id of the session
    any of them resolves to (a flag file may list a session in either form)."""
    return _sr.expand([x for x in (it.get("to"), it.get("uuid"), it.get("name"), it.get("pid")) if x])


def _stale_hold(entry: str) -> str:
    """Why a held entry no longer names a live session as it is now, '' when it does (or when there is no registry to tell by)."""
    if not _sr.available():
        return ""
    r = _sr.row(entry)
    if r is None:
        return "no session carries it"
    if r.get("state") != "live":
        return "its session is retired"
    if entry.lower() != r["id"] and not UUID.match(entry.lower()) and str(r.get("name") or "") != entry:
        return f"an old name of {r.get('name')}"
    return ""


def _log_held(src: str, it: dict[str, Any], held_raw: set[str], now: float) -> None:
    """A line skipped by a hold whose entry is stale (retired session, an old name, no session): say so in the server's journal, once per entry per
    hour. A hold that names a live session as it is now is the normal case and logs nothing."""
    keys = _keys(it)
    for e in sorted(held_raw):
        if e not in keys and not (_sr.expand_flag([e]) & keys):
            continue
        why = _stale_hold(e)
        k = f"{src}:{e}"
        if why and now - _stale_logged.get(k, -1e12) >= STALE_LOG:
            _stale_logged[k] = now
            log.warning("inbox: line %s for %s is held by '%s' in held-%s.txt, an entry that %s", it.get("id"), it.get("to"), e, src, why)


def _newest(cands: list[str], rank: dict[str, float] | None) -> list[str]:
    """Several live sessions carry one name (a stale namesake beside the real pane). The one registered last holds the name for delivery (fleet.by_name, which binds ids and items, still resolves two running namesakes to nobody). Without a registration time for each of them,
    or with the two newest tied, nobody does: the line waits, and the overdue flag (`new_overdue`) says so."""
    if len(cands) < 2 or not rank:
        return cands
    ordered = sorted(cands, key=lambda u: rank.get(u, 0.0), reverse=True)
    if rank.get(ordered[0], 0.0) > rank.get(ordered[1], 0.0):
        return ordered[:1]
    return cands


def _carriers(live: dict[str, str], rank: dict[str, float] | None = None) -> dict[str, str]:
    """permanent id → the live transcript that carries it. A live transcript carries the id the registry lists it under; one the registry does not list
    yet (a relaunch, a /clear: the tool has not recorded the new transcript) carries the id its name resolves to, the name being the server's kept one, never the CLI's
    placeholder. Several carriers of one id: the one registered last (`rank`), else the one the registry lists last; with neither settling it, nobody (no guess)."""
    pools: dict[str, list[str]] = {}
    for u, n in live.items():
        p = _sr.resolve(u) or (_sr.resolve(n) if n and UUID.match(str(u).lower()) else None)
        if p:
            pools.setdefault(p, []).append(u)
    out: dict[str, str] = {}
    for p, cands in pools.items():
        win = _newest(cands, rank)
        if len(win) > 1:
            order = {t: float(i) for i, t in enumerate(_sr.transcripts(p))}
            win = _newest(win, {u: order.get(str(u).lower(), -1.0) for u in win})
        if len(win) == 1:
            out[p] = win[0]
    return out


def _by_id(pid: str) -> bool:
    """Is this line matched by its permanent id: the registry, as read now, holds a LIVE row with that id. If it does not (the line has no id; the registry file of the
    session's machine is missing or stale; the session was retired, and a pane may have been spawned again under its name since the line was put), the line is matched
    by its name as before."""
    if not pid:
        return False
    r = _sr.row(pid)
    return bool(r and r.get("state") == "live")


def _target(it: dict[str, Any], live: dict[str, str], known: set[str], rank: dict[str, float] | None = None, carriers: dict[str, str] | None = None) -> str:
    """Which of these live sessions (uuid → name) the line is for, '' when none. A line with a permanent id goes to the live transcript that carries it (`_carriers`),
    whatever its transcript id, name or the name its puller reports. A line without one (a name the registry did not know when it was put, a line from before permanent ids existed), or whose id the registry no longer holds as a live session (its machine's registry file is missing or stale, or the session was retired and respawned
    under its name), is matched as before: by id first, then by the name it was addressed to (the newest of several namesakes, `_newest`); a line
    whose own session is gone everywhere follows the name it carried when it was put."""
    pid = str(it.get("pid") or "")
    if _by_id(pid):
        return (_carriers(live, rank) if carriers is None else carriers).get(pid, "")
    to, uuid, name = str(it.get("to") or ""), str(it.get("uuid") or ""), str(it.get("name") or "")
    if to in live:
        return to
    if uuid in live:
        return uuid
    by_name = _newest([u for u, n in live.items() if n and n in (to, name)], rank)
    if len(by_name) != 1:
        return ""
    if to == live[by_name[0]]:
        return by_name[0]                                   # addressed by name: whoever carries it now
    return by_name[0] if uuid not in known else ""          # addressed by id: only when that session exists nowhere any more


def take(live: dict[str, str], known: set[str] | None = None, only_src: str | None = None, now: float | None = None,
         rank: dict[str, float] | None = None) -> list[dict[str, Any]]:
    """What a puller is handed for the sessions live on its machine (uuid → name): one delivery per (session, source),
    several waiting lines folded into one turn, each line leased until it is confirmed. `live` carries the server's own name for
    each session (the poll passes what the server kept, never the CLI's placeholder a relaunched pane reports); `rank` (uuid →
    when the session was registered) settles several live namesakes or several live carriers of one permanent id (`_newest`).
    → [{session, name, src, ids: [...], text}]"""
    now = time.time() if now is None else now
    known = _present(_index()) if known is None else known
    carriers = _carriers(live, rank)
    out: dict[tuple[str, str], list[dict[str, Any]]] = {}
    with _locked():
        leases = {k: v for k, v in _leases().items() if v > now}
        flags = {s: blocked(s) for s in SOURCES}
        for it in _items(only_src):
            if it["id"] in leases:
                continue
            paused, released, held = flags[it["src"]]
            held_raw = held
            released, held = _sr.expand_flag(released), _sr.expand_flag(held)     # a name the session no longer carries names nothing but itself
            keys = _keys(it)
            if keys & held:
                _log_held(it["src"], it, held_raw, now)
                continue
            if paused and not keys & released:
                continue
            u = _target(it, live, known, rank, carriers)
            if u:
                out.setdefault((u, it["src"]), []).append(it)
        for (u, src), its in out.items():
            for it in its:
                leases[it["id"]] = now + LEASE
        _save_leases(leases)
    res = []
    for (u, src), its in out.items():
        lines = [label(str(i.get("from") or ""), i["text"]) for i in its]
        text = lines[0] if len(its) == 1 else f"{HEAD[src]} {len(its)} queued while you were away:\n" + "\n".join(lines)
        res.append({"session": u, "name": live.get(u, ""), "src": src, "ids": [i["id"] for i in its], "text": text})
    return res


def ack(delivered: list[str], failed: list[str] | None = None, now: float | None = None) -> int:
    """A puller's confirmation: delivered lines go, failed ones are offered again shortly. → how many were removed."""
    now = time.time() if now is None else now
    n = 0
    with _locked():
        leases = _leases()
        for iid in delivered or []:
            for s in SOURCES:
                p = DIR / s / f"{iid}.json"
                if p.exists():
                    p.unlink(); n += 1
            leases.pop(iid, None)
        for iid in failed or []:
            if iid in leases:
                leases[iid] = now + RETRY
        _save_leases({k: v for k, v in leases.items() if v > now})
    return n


def waiting(src: str | None = None) -> dict[str, int]:
    """key (as addressed) → how many lines wait for it."""
    out: dict[str, int] = {}
    for it in _items(src):
        out[str(it["to"])] = out.get(str(it["to"]), 0) + 1
    return out


# ----------------------------------------------------------------------------- a line that waits too long
# A message can wait in this inbox while the pane runs, e.g. when a line addressed by name finds no live namesake it can pick
# (two running sessions carrying the name, or the poll passing the CLI's placeholder name), and nothing would say so. Whatever the cause, a line that waits
# for a session that shows signs of life is reported, once, after [client] inbox_flag_minutes (server.py's tick).


def _carrier_rows(pid: str, idx: dict[str, dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    """The sessions in the heartbeat that carry this permanent id, as `_carriers` reads it: the transcript the registry lists under it, else the name it resolves to."""
    out = []
    for u, r in idx.items():
        n = str(r.get("name") or "")
        if (_sr.resolve(u) or (_sr.resolve(n) if n and UUID.match(str(u).lower()) else None)) == pid:
            out.append((u, r))
    return out


def shown(it: dict[str, Any]) -> str:
    """The name a line's session goes by now, for people: the registry's current name for its permanent id, else the name stored on the line, else the address."""
    pid = str(it.get("pid") or "")
    return (_sr.display_name(pid) if pid else None) or str(it.get("name") or it.get("to") or "")


def _rows_for(it: dict[str, Any], idx: dict[str, dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    """The sessions in the heartbeat this line is for: the one it was addressed to or recorded by id, every one that carries its permanent id, and every one
    that carries the name it was addressed to (or its current name)."""
    to, uuid, name = str(it.get("to") or ""), str(it.get("uuid") or ""), str(it.get("name") or "")
    pid = str(it.get("pid") or "")
    cur = (_sr.display_name(pid) if pid else None) or ""
    out = [(k, idx[k]) for k in dict.fromkeys((to, uuid)) if k and k in idx]
    if pid:
        out += [(u, r) for u, r in _carrier_rows(pid, idx) if u not in {k for k, _r in out}]
    return out + [(u, r) for u, r in idx.items() if r.get("name") and r.get("name") in (to, name, cur) and u not in {k for k, _r in out}]


def alive(it: dict[str, Any], idx: dict[str, dict[str, Any]] | None = None) -> bool:
    """Does the session this line waits for show a sign of life that a puller should have acted on: a row not marked gone (reported by its machine's puller at its
    last check-in), on a machine whose puller is checking in. A session on a machine with no puller takes its lines at its next prompt, whenever that is: not flagged.
    (The row's `seen` is no sign: the view writes it only when a fact changes, so it is hours old on a quiet session.)"""
    idx = _index() if idx is None else idx
    try:
        from stackshot.fleet import fleet
    except Exception:
        return False
    return any(_lv.running(r) and _lv.machine_online_ok(fleet.read(str(r.get("machine") or ""), "machine")) for _u, r in _rows_for(it, idx))


def deliberate(it: dict[str, Any]) -> str:
    """Why this line waits on purpose, '' when it does not: a hold on its session (sala's relaunch hold, a reboot's resume) in held-<src>.txt, or its source paused
    (paused-<src>.json) without a release for it. These are known waits, sala's own watch frees a hold a dead relaunch left after 10 minutes: the flag leaves them alone."""
    src = str(it.get("src") or "msg")
    paused, released, held = blocked(src)
    keys = _keys(it)
    if keys & _sr.expand_flag(held):
        return f"a hold on it in held-{src}.txt has not been lifted"
    if paused and not keys & _sr.expand_flag(released):
        return f"deliveries of its kind are paused (paused-{src}.json)"
    return ""


def why(it: dict[str, Any], idx: dict[str, dict[str, Any]] | None = None, now: float | None = None) -> str:
    """The likeliest reason this line still waits, in words, for the flag: a lease no puller confirmed, several running sessions carrying the name, else that no
    puller has asked for it (a deliberate hold or pause is no case for the flag, `deliberate`; named here for a caller that asks)."""
    now = time.time() if now is None else now
    idx = _index() if idx is None else idx
    if deliberate(it):
        return deliberate(it)
    if _leases().get(str(it.get("id")), 0.0) > now:
        return "it was handed to a puller that has not confirmed it yet"
    rows = [(u, r) for u, r in _rows_for(it, idx) if _lv.running(r)]
    pid = str(it.get("pid") or "")
    if _by_id(pid):
        carrying =[(u, r) for u, r in _carrier_rows(pid, idx) if _lv.running(r)]
        if len(carrying) > 1:
            return f"{len(carrying)} running sessions carry the permanent id {pid[:8]} ({', '.join(u[:8] for u, _r in carrying)}) and nothing says which is the newer"
        if not carrying:
            return (f"no running session is tied to its permanent id {pid[:8]} by the session registry"
                    + (f", though {', '.join(u[:8] for u, _r in rows)} runs under its name (a relaunch the registry has not recorded yet)" if rows else ""))
        return "no puller has asked for it: its session's puller may be down or behind"
    if len(rows) > 1:
        return f"{len(rows)} running sessions carry the name {rows[0][1].get('name')} ({', '.join(u[:8] for u, _r in rows)}), so the name does not say which one it is for"
    return "no puller has asked for it: the session's name here may differ from the one its puller reports"


def new_overdue(older_than: float, now: float | None = None, idx: dict[str, dict[str, Any]] | None = None, skip_from: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    """The lines that have waited at least `older_than` seconds for a session that shows a sign of life (`alive`), and were not reported before: each is reported
    once (its id goes to <inbox>/flagged.json, which keeps only ids still waiting). Oldest first, each with its age (`age`, s) and the reason (`why`).
    Left alone: a line sent by one of `skip_from` (the flag's own lines are sent by the server, so a stuck recipient is not flagged again for the flag), and a line that
    waits on purpose (`deliberate`: a hold or a pause); a held line is looked at again on the next pass and flagged if the hold is gone and it still waits."""
    now = time.time() if now is None else now
    idx = _index() if idx is None else idx
    out: list[dict[str, Any]] = []
    with _locked():
        try:
            done = {str(k): float(v) for k, v in json.load(open(DIR / "flagged.json", encoding="utf-8")).items()}
        except Exception:
            done = {}
        items = _items()
        keep = {k: v for k, v in done.items() if k in {str(it["id"]) for it in items}}
        for it in items:
            iid = str(it["id"])
            age = now - float(it.get("ts", 0))
            if iid in keep or age < older_than or str(it.get("from") or "") in skip_from or deliberate(it) or not alive(it, idx):
                continue
            keep[iid] = now
            out.append({**it, "name": shown(it), "age": age, "why": why(it, idx, now)})
        if keep != done:
            tmp = DIR / ".flagged.json.tmp"
            json.dump(keep, open(tmp, "w", encoding="utf-8")); os.replace(tmp, DIR / "flagged.json")
    return out
