"""agent_state.py: `POST /client/agent-state`, the fleet's session manager telling the server which registered agents are busy and which are idle.

The hourly audit and the busy-hold guard need to know whether an agent is at work: a pane in a turn, or a subagent running. Most agents run on another machine than the server, so the server cannot read
that from a registry or a transcript of its own box. The machine that runs the panes knows it, and tells: about every five minutes it pushes the whole fleet in one body, which REPLACES the previous snapshot.

    {"schema": 1, "written": <epoch s>,
     "agents": {"<registered agent name>": {"state": "busy" | "idle" | "unknown", "since": <epoch s>, "why": "<one line>", "pane": "turn" | "idle" | "shell" | "sleeping", "read": true | false,
                                            "subagents": [{"id", "description", "brief" (its first 2048 characters), "at": <epoch s>, "quiet"?: true, "unreadable"?: true}]}}}

The sender decides the state (busy: the pane is in a turn or any subagent is running; idle: the pane is idle, showing a shell or sleeping and no subagent runs; unknown: it could not tell, `read` false); the server
stores what it was told and reads nothing of the agents' box. Answers 200 `{"ok": true, "agents": N}`, 400 with one line for a wrong schema, a body that is no object, a malformed agent entry or a body over `MAX_BYTES`
(the previous snapshot stays), 503 on a read-only standby copy or when the file cannot be written. The authorization is the machine token of every `/client` write, checked by the route before this module is called.

The snapshot is ONE file, `<paths.state>/agent-state.json`, written whole to a temporary file and renamed over the old one, so a reader sees the old snapshot or the new one, never half of one. It lives in the state
folder beside the other server-written files, outside the store and the fleet folders whose file times the board's views and republish stand on, so a push every few minutes republishes nothing. The file carries what
was pushed (clipped and normalised) and `received`, the server's own clock at the push. Reading it, and deciding what a missing, stale or unreadable snapshot means, is audit/agent_state.py.

A service module: it imports core and the standard library only. The route that calls it (`_client_post`) is the surface's."""
from __future__ import annotations

import json
import math
import os
import threading
import time
from pathlib import Path
from typing import Any

from stackshot.core import config as _cfg
from stackshot.core import readonly as _ro

VERB = "agent-state"        # the /client/<verb> the sender calls
FILE = "agent-state.json"   # in <paths.state>
SCHEMA = 1
MAX_BYTES = 1_000_000       # a body over this is refused before it is parsed
STATES = ("busy", "idle", "unknown")
NAME_MAX, WHY_MAX, PANE_MAX, DESC_MAX, ID_MAX = 200, 300, 20, 300, 120
BRIEF_MAX = 2048            # characters of a subagent's brief that are kept
SUBAGENTS_MAX = 200         # subagents kept per agent


def path() -> Path:
    return _cfg.state(FILE)


def too_large(length: Any) -> str:
    """The refusal (one line) for a body of `length` bytes (an int, or a Content-Length header's text), "" when it is within `MAX_BYTES` or cannot be read as a length."""
    try:
        n = int(length)
    except (TypeError, ValueError):
        return ""
    return f"the body is {n} bytes, over the {MAX_BYTES}-byte limit" if n > MAX_BYTES else ""


def _num(v: Any) -> float | None:
    """A finite number that is no bool, else None."""
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def _text(v: Any, cap: int) -> str | None:
    """The string clipped to `cap` characters, None when it is no string."""
    return v[:cap] if isinstance(v, str) else None


def _subagent(name: str, i: int, s: Any) -> tuple[dict[str, Any] | None, str]:
    """(one subagent entry normalised, "") or (None, why it is refused)."""
    where = f"agent {name!r} subagent {i}"
    if not isinstance(s, dict):
        return None, f"{where} is no object"
    out: dict[str, Any] = {}
    for key, cap in (("id", ID_MAX), ("description", DESC_MAX), ("brief", BRIEF_MAX)):
        v = s.get(key, "")
        t = _text(v, cap)
        if t is None:
            return None, f"{where}: {key} is no string"
        out[key] = t
    at = _num(s.get("at", 0))
    if at is None:
        return None, f"{where}: at is no number"
    out["at"] = at
    for flag in ("quiet", "unreadable"):
        if flag in s:
            if not isinstance(s[flag], bool):
                return None, f"{where}: {flag} is no true or false"
            if s[flag]:
                out[flag] = True
    return out, ""


def _agent(name: str, a: Any) -> tuple[dict[str, Any] | None, str]:
    """(one agent entry normalised, "") or (None, why the body is refused)."""
    where = f"agent {name!r}"
    if not isinstance(a, dict):
        return None, f"{where} is no object"
    if a.get("state") not in STATES:
        return None, f"{where}: state = " + " | ".join(STATES)
    if not isinstance(a.get("read"), bool):
        return None, f"{where}: read = true or false"
    since = _num(a.get("since", 0))
    why, pane = _text(a.get("why", ""), WHY_MAX), _text(a.get("pane", ""), PANE_MAX)
    if since is None or why is None or pane is None:
        return None, f"{where}: since is a number, why and pane are strings"
    subs = a.get("subagents", [])
    if not isinstance(subs, list):
        return None, f"{where}: subagents is a list"
    out_subs = []
    for i, s in enumerate(subs[:SUBAGENTS_MAX]):
        ns, bad = _subagent(name, i, s)
        if ns is None:
            return None, bad
        out_subs.append(ns)
    return {"state": a["state"], "since": since, "why": why, "pane": pane, "read": a["read"], "subagents": out_subs}, ""


def validate(body: Any) -> tuple[dict[str, Any] | None, str]:
    """(the snapshot to store, "") or (None, the one-line reason the body is refused)."""
    if not isinstance(body, dict):
        return None, "the body is a JSON object"
    if body.get("schema") != SCHEMA or isinstance(body.get("schema"), bool):
        return None, f"schema = {SCHEMA}"
    written = _num(body.get("written"))
    if written is None or written <= 0:
        return None, "written = the epoch second the snapshot was made"
    agents = body.get("agents")
    if not isinstance(agents, dict):
        return None, "agents = an object of registered agent names"
    out: dict[str, Any] = {}
    for name, a in agents.items():
        if not isinstance(name, str) or not name.strip() or len(name) > NAME_MAX:
            return None, f"an agent name is a string of 1 to {NAME_MAX} characters"
        norm, why = _agent(name, a)
        if norm is None:
            return None, why
        out[name] = norm
    return {"schema": SCHEMA, "written": written, "received": time.time(), "agents": out}, ""


def _write(snap: dict[str, Any]) -> None:
    """The snapshot whole to a temporary file beside the file, then renamed over it (never half of one), the temporary file removed on a failure."""
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        tmp.write_text(json.dumps(snap, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        os.replace(tmp, p)
    finally:
        tmp.unlink(missing_ok=True)


def post(machine: str, body: Any) -> tuple[int, dict[str, Any]]:
    """`POST /client/agent-state` -> (status, JSON): 200 `{ok, agents}` when the snapshot replaced the last one, 400 `{error}` for a body it refuses (the last snapshot stays), 503 on a standby copy or a file that cannot be written."""
    if _ro.is_read_only():
        return 503, {"error": _ro.REFUSAL}
    snap, why = validate(body)
    if snap is None:
        return 400, {"error": why}
    try:
        _write(snap)
    except OSError as e:
        return 503, {"error": f"the snapshot could not be written ({e.__class__.__name__}); the last one stays"}
    return 200, {"ok": True, "agents": len(snap["agents"])}


def load() -> dict[str, Any] | None:
    """The stored snapshot, None when there is none or it cannot be read as one (absent, torn, not an object, another schema). The caller decides what that means; it is never an empty fleet."""
    try:
        d = json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return None
    return d if isinstance(d, dict) and d.get("schema") == SCHEMA and isinstance(d.get("agents"), dict) else None
