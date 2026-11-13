"""held.py — notices held for a background agent until its next turn (notices that ask nothing of a builder cost a turn each and often end with nothing done).

A notice to a BACKGROUND agent (a `background:` entry of a page's agents map) that asks nothing of it is not delivered as a new turn. It is
held here and handed over with the agent's next turn, whatever caused that turn. Held kinds (KINDS):
  closed      an item the agent moves or observes was closed or completed by another session (telling.tell_owner, tell_observers, tell_owner_change)
  changed     another session changed an item the agent neither moves nor is named on: its next, needs, check or after (tell_owner_change)
  queue       a wake that leaves an item still after an open item: its place in the queue, nothing to do yet (wake_tell in service/wakes.py)
  page-owed   the keeper's "the page update is owed" notice (pilot_relay, pilot_relay_many; also what the router passes of such a notice)
  fyi         a message its sender marked fyi (the message tool's `fyi`)
Everything else wakes the agent as before: a notice that names it in needs, hands it an item (mover, hand-off), ends its wait, carries
the owner's words or asks something; so does the audit's finding for an item's mover (router.py audit-owners): it is a task. When the code is unsure it delivers (decide() answers "" for any kind it does not know).

THE ONE DECISION POINT is decide(): the senders (telling.hold_notice, router_live._hold_kind) pass what they know and take its answer. It
never raises. [router] hold_notices (default true) is the switch; false delivers everything as before.

WHERE THEY LIVE. <state>/held/<key>.jsonl, one file per session, a line per notice {id, ts, kind, text, from, gid, nid}; the key is the
session's permanent id when the registry resolves it, else its transcript id or name (key_of). It is server-side state, so a pane's
conversation cleared or recycled loses nothing, and a restart of the server reloads it from the files.

HOW THEY REACH THE TURN. Every machine's UserPromptSubmit hook (`pages.py nag`, wired by `bin/stackshot client install`) asks the server for
the session's held notices (POST /client/held, the machine's token, the session as the server registered it), prints the answer (the hook's
output is the turn's context), and then acknowledges the ids it printed (a second POST). At least once, never lost: lease() marks the lines it
shows as leased for LEASE seconds and returns their ids; ack() removes them; a line never acknowledged (the hook died before it printed, or
the answer never arrived) is offered again once the lease runs out. A duplicate is possible, a loss is not. Oldest first, one line each, at
most SHOWN_MAX; the rest stay for the next turn and the last line says "+N more". A notice older than KEEP_DAYS is dropped, and a session
keeps at most KEEP_MAX (the oldest go); each drop is a stderr line. take() = lease + ack at once (a caller that has no hook to wait for).

ROLLOUT GATE. A notice is held only for a session whose hook has fetched held lines (mark_client, recorded when the endpoint is called;
can_fetch). A machine whose checkout is behind, a cloud session and a session that has not had a turn since the update never fetch, so
they are delivered as today and no line is stranded.

Stdlib only (anchors and config are the repo's own)."""
from __future__ import annotations
import os as _os, sys as _sys
if not __package__:   # started as a script (python3 stackshot/<area>/<name>.py): the checkout must be importable
    _here = _os.path.dirname(_os.path.abspath(__file__))
    _sys.path[:] = [_os.path.dirname(_os.path.dirname(_here))] + [p for p in _sys.path if _os.path.abspath(p or ".") != _here]

import datetime as dt
import fcntl
import json
import os
import re
import secrets
import sys
import time
from pathlib import Path
from typing import Any

from stackshot.core import config as _cfg

KINDS = ("closed", "changed", "queue", "page-owed", "fyi")
SHOWN_MAX = 8               # lines handed over at one turn start; the rest wait for the next turn
KEEP_MAX = 100              # held lines kept per session; past it the oldest go
KEEP_DAYS = 7               # a held line older than this is dropped, never handed over
LINE_MAX = 260              # characters in one held line
LEASE = 60.0                # s a line handed to a hook stays reserved for it until it acknowledges (then it is offered again)
CLIENT_DAYS = 30            # a session counts as fetching held lines for this long after its hook last asked
_ORD = {1: "st", 2: "nd", 3: "rd"}


def enabled() -> bool:
    """[router] hold_notices: whether notices that ask nothing are held for a background agent (default true; false = every notice is delivered as before)."""
    v = _cfg.get("router", "hold_notices")
    return True if v is None else (v is True or str(v).strip().lower() in ("true", "1", "yes", "on"))


def dir_() -> Path:
    return _cfg.state("held")


def key_of(who: str) -> str:
    """The key a session's held notices are filed under: its permanent id when the registry resolves it, else its transcript id or name as given
    (anchors.canonical turns a name that exactly one live pane carries into that pane's transcript id)."""
    who = str(who or "").strip()
    if not who:
        return ""
    try:
        from stackshot.fleet import sessions_registry as _sr
        pid = _sr.resolve(who)
        if pid:
            return pid
    except Exception:  # noqa: BLE001
        pass
    try:
        from stackshot.anchors import anchors as _anc
        return str(_anc.canonical(who) or who)
    except Exception:  # noqa: BLE001
        return who


def keys_for(*refs: str) -> list[str]:
    """Every key the session may have been filed under, given the references a hook knows (its transcript id, its pane name)."""
    out: list[str] = []
    for r in refs:
        r = str(r or "").strip()
        if not r:
            continue
        for k in (key_of(r), r):
            if k and k not in out:
                out.append(k)
    return out


def _file(key: str) -> Path:
    return dir_() / (re.sub(r"[^A-Za-z0-9._-]", "_", key)[:120] + ".jsonl")


class _locked:
    """An exclusive lock on the store (one lock file for all sessions: the lines are few and the work is short)."""
    def __enter__(self):
        dir_().mkdir(parents=True, exist_ok=True)
        self.f = open(dir_() / "lock", "w")
        fcntl.flock(self.f, fcntl.LOCK_EX)
        return self

    def __exit__(self, *a):
        fcntl.flock(self.f, fcntl.LOCK_UN)
        self.f.close()
        return False


def _read(path: Path) -> list[dict[str, Any]]:
    out = []
    try:
        for ln in path.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(ln)
            except ValueError:
                continue
            if isinstance(d, dict) and d.get("text"):
                out.append(d)
    except OSError:
        pass
    return out


def _write(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        try:
            path.unlink()
        except OSError:
            pass
        return
    tmp = path.with_name("." + path.name + ".tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    os.replace(tmp, path)


def one_line(text: Any, n: int = LINE_MAX) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= n else s[:n - 1].rstrip() + "…"


# ----------------------------------------------------------------------------- the decision
def _owner_mark() -> "re.Pattern[str]":
    """The mark that makes a notice the owner's: "[for <owner>]" with the instance's [instance] owner, or "needs: decision"."""
    owner = str(_cfg.get("instance", "owner") or "the owner")
    return re.compile(r"\[for " + re.escape(owner) + r"\]|needs:\s*decision", re.I)


def clients_file() -> Path:
    return dir_() / "clients.json"


def mark_client(*refs: str, now: float | None = None) -> None:
    """A session's hook has asked for its held lines: record it under every key the session may be filed under (can_fetch reads it). Never raises."""
    now = time.time() if now is None else now
    try:
        with _locked():
            d = _clients_read()
            ks = keys_for(*refs)
            if ks and all(now - d.get(k, 0.0) < 3600 for k in ks):
                return          # asked within the hour: every prompt of every session comes here, and the file need not be rewritten each time
            for k in ks:
                d[k] = now
            d = {k: v for k, v in d.items() if now - float(v) <= 3 * CLIENT_DAYS * 86400}
            tmp = clients_file().with_name(".clients.json.tmp")
            tmp.write_text(json.dumps(d), encoding="utf-8")
            os.replace(tmp, clients_file())
    except Exception:  # noqa: BLE001
        pass


def _clients_read() -> dict[str, float]:
    try:
        d = json.loads(clients_file().read_text(encoding="utf-8"))
        return {str(k): float(v) for k, v in d.items()} if isinstance(d, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def can_fetch(target: str, now: float | None = None) -> bool:
    """Does this session's hook fetch held lines (the rollout gate)? False for a session never seen asking, for a cloud session and for one on a
    checkout without the fetch: its notices are delivered as before, never stranded. False on any doubt."""
    now = time.time() if now is None else now
    try:
        d = _clients_read()
        return any(now - d.get(k, 0.0) <= CLIENT_DAYS * 86400 for k in keys_for(target))
    except Exception:  # noqa: BLE001
        return False


def decide(kind: str, *, is_background: bool, text: str = "", owner_words: bool = False, asks: bool = False, sender_is_owner: bool = False, target: str = "") -> str:
    """THE decision: is a notice of this `kind` to this recipient held? → the kind when it is, "" when it is delivered as now.
    Delivered whatever the kind: the switch is off; the kind is none of KINDS; the recipient is not a background agent (a front agent is unchanged);
    the notice carries the owner's words (`owner_words`, or a [for <owner>] mark or "needs: decision" in the text) or its sender is the owner himself
    (`sender_is_owner`); or the caller found that it asks something (`asks`: the agent is named in needs, is the item's mover, a hand-off, a wait that ends);
    or `target` (when given) is not a session whose hook fetches held lines (can_fetch: the rollout gate)."""
    try:
        if kind not in KINDS or not enabled() or not is_background:
            return ""
        if owner_words or sender_is_owner or asks or _owner_mark().search(str(text or "")):
            return ""
        if target and not can_fetch(target):
            return ""
        return kind
    except Exception:  # noqa: BLE001
        return ""


def reason(kind: str) -> str:
    """The routing log's reason for a hold."""
    return f"held: asks nothing ({kind})"


# ----------------------------------------------------------------------------- the store
def _say(msg: str) -> None:
    print(f"held: {msg}", file=sys.stderr, flush=True)


def _fresh(rows: list[dict[str, Any]], now: float, key: str = "") -> list[dict[str, Any]]:
    """The rows younger than KEEP_DAYS; a drop is a stderr line (a notice that was never handed over must leave a trace)."""
    keep = [r for r in rows if float(r.get("ts", 0)) >= now - KEEP_DAYS * 86400]
    if len(keep) != len(rows):
        _say(f"{len(rows) - len(keep)} notice{'s' if len(rows) - len(keep) != 1 else ''} for {key or 'a session'} dropped unread: older than {KEEP_DAYS} days")
    return keep


def _sweep(now: float) -> None:
    """A session's file nothing has touched for KEEP_DAYS (a retired session, a pane renamed away) holds only expired lines: remove it. Caller holds the lock."""
    try:
        for p in dir_().glob("*.jsonl"):
            try:
                if p.stat().st_mtime < now - KEEP_DAYS * 86400:
                    n = len(_read(p))
                    p.unlink()
                    _say(f"{p.stem}: {n} notice{'s' if n != 1 else ''} dropped unread, the session has not had a turn for {KEEP_DAYS} days")
            except OSError:
                pass
    except OSError:
        pass


def add(key: str, kind: str, text: str, sender: str = "", gid: str = "", nid: str = "", now: float | None = None) -> bool:
    """Hold one notice for the session `key` (key_of). Idempotent on `nid` (a router notice retried after a write failed is held once).
    → True when stored. Never raises."""
    key = str(key or "").strip()
    line = one_line(text)
    if not key or not line:
        return False
    now = time.time() if now is None else now
    try:
        with _locked():
            _sweep(now)
            p = _file(key)
            rows = _fresh(_read(p), now, key)
            if nid and any(r.get("nid") == nid for r in rows):
                return True
            rows.append({"id": secrets.token_hex(3), "ts": now, "kind": kind, "text": line, "from": one_line(sender, 60), "gid": str(gid or "")[:60], "nid": nid})
            if len(rows) > KEEP_MAX:
                _say(f"{len(rows) - KEEP_MAX} notice{'s' if len(rows) - KEEP_MAX != 1 else ''} for {key} dropped unread: more than {KEEP_MAX} waiting")
            _write(p, rows[-KEEP_MAX:])
        return True
    except Exception:  # noqa: BLE001
        return False


def count(*refs: str) -> int:
    """How many lines wait for the session, leased ones included (no side effect)."""
    n = 0
    try:
        with _locked():
            for k in keys_for(*refs):
                n += len(_read(_file(k)))
    except Exception:  # noqa: BLE001
        pass
    return n


def _when(ts: float, now: float) -> str:
    z = _cfg.tz()
    t, n = dt.datetime.fromtimestamp(ts, z), dt.datetime.fromtimestamp(now, z)
    hm = t.strftime("%H:%M")
    if t.date() == n.date():
        return hm
    d = t.day
    return f"{t.strftime('%a %b')} {d}{'th' if 10 <= d % 100 <= 20 else _ORD.get(d % 10, 'th')} {hm}"


def lease(*refs: str, now: float | None = None, shown_max: int | None = None) -> tuple[str, list[str]]:
    """The text to hand the session at a turn start and the ids of the lines in it → ("", []) when nothing is due. The lines shown are LEASED, not removed:
    ack() removes them, and one never acknowledged is offered again after LEASE seconds (at least once; a duplicate is possible, a loss is not). Lines
    under another offer's lease are not offered. Oldest first, one line each, SHOWN_MAX at most, and a last line "+N more" for those that wait for the
    next turn. Never raises."""
    now = time.time() if now is None else now
    cap = SHOWN_MAX if shown_max is None else max(1, shown_max)
    try:
        with _locked():
            keys = keys_for(*refs)
            paths = list(dict.fromkeys(_file(k) for k in keys))
            allrows: dict[Path, list[dict[str, Any]]] = {p: _fresh(_read(p), now, keys[0] if keys else "") for p in paths}
            due: list[tuple[Path, dict[str, Any]]] = [(p, r) for p, rs in allrows.items() for r in rs if float(r.get("lease", 0)) <= now]
            due.sort(key=lambda x: float(x[1].get("ts", 0)))
            shown, rest = due[:cap], due[cap:]
            for _p, r in shown:
                r["lease"] = now + LEASE
            for p, rs in allrows.items():
                if p.exists() or rs:
                    _write(p, rs)
            if not shown:
                return "", []
        lines = [f"- {_when(float(r['ts']), now)} · {r.get('kind', '')} · {r['text']}" for _p, r in shown]
        if rest:
            lines.append(f"- +{len(rest)} more, handed over at your next turn")
        n = len(shown) + len(rest)
        head = (f"[stackshot] {n} notice{'s' if n != 1 else ''} held for you while you were busy; they asked nothing of you, "
                "and are handed over once, oldest first:")
        return head + "\n" + "\n".join(lines), [str(r["id"]) for _p, r in shown]
    except Exception:  # noqa: BLE001
        return "", []


def ack(*refs: str, ids: list[str] | None = None) -> int:
    """The hook printed these lines: remove them. → how many were removed. An id the session does not hold is ignored. Never raises."""
    want = {str(i) for i in (ids or []) if i}
    if not want:
        return 0
    n = 0
    try:
        with _locked():
            for p in dict.fromkeys(_file(k) for k in keys_for(*refs)):
                rows = _read(p)
                keep = [r for r in rows if str(r.get("id")) not in want]
                if len(keep) != len(rows):
                    n += len(rows) - len(keep)
                    _write(p, keep)
    except Exception:  # noqa: BLE001
        pass
    return n


def take(*refs: str, now: float | None = None, shown_max: int | None = None) -> str:
    """lease() and ack() in one step: the text, with the lines it shows removed at once (each handed over once). For a caller with no hook to wait for. Never raises."""
    text, ids = lease(*refs, now=now, shown_max=shown_max)
    ack(*refs, ids=ids)
    return text


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 2 and sys.argv[1] == "count":
        print(count(*sys.argv[2:]))
    else:
        print(__doc__)
