"""A test driver for router.py's judging: the shadow tick that router.py itself carried until (Mon Oct 26th 2026).

The production router no longer has a shadow mode (router_live.py acts on every project, `tick` there judges AND delivers). The judging
code (code_rule, call_project, Context, call_line, the attempts file, the call log) is router.py's and stays; tests/router_scenario.py
still wants to read what that code would rule for a notice WITHOUT acting, so this module is the old tick, kept here as a harness: it
judges every notice the shadow log does not hold yet and writes the ruling to <state>/router/shadow.jsonl, never to the routing log, and
never delivers. Nothing in the server imports it."""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Callable

from stackshot.anchors import anchors as _anc
from stackshot.router import router
from stackshot.router import routing as _routing

_LOCK = threading.Lock()


def shadow_path() -> Path:
    return router._dir() / "shadow.jsonl"


def read_shadow() -> dict[str, dict[str, Any]]:
    """The shadow log by notice id (the last line of an id wins)."""
    return {str(d.get("id")): d for d in router._read(shadow_path()) if d.get("id")}


def tick(now: float | None = None, runner: Callable[[str], dict[str, Any]] | None = None) -> dict[str, int]:
    """One pass: every notice younger than [router] max_age_hours that the shadow log does not hold yet is judged, by a rule in code or,
    the rest of a project together, by one thin call (at most [router] max_notices a call, oldest first). → {"coded", "called", "calls",
    "fallback", "retry"}. As router.tick was before, without the [router] shadow switch."""
    now = time.time() if now is None else now
    with _LOCK:
        done = set(read_shadow())
        since = now - 3600.0 * router._num("max_age_hours", 24.0, 0.1)
        groups: dict[str, list[tuple[str, dict[str, Any]]]] = {}
        for key in _routing.projects():
            root = _anc.pilot_root(key)
            if not root:
                continue
            for n in _routing.read(key, since=since):
                if n.get("pilot") and n.get("kind") in router.KINDS and n["id"] not in done:
                    groups.setdefault(root, []).append((key, n))
        out = {"coded": 0, "called": 0, "calls": 0, "fallback": 0, "retry": 0}
        if not groups:
            return out
        cx = router.Context()
        cap = int(router._num("max_notices", 25, 1))
        attempts = router._load_attempts()
        for root, rows in sorted(groups.items()):
            rows.sort(key=lambda r: float(r[1].get("ts", 0)))
            peers: dict[str, list[dict[str, Any]]] = {}
            todo = []
            for key, n in rows:
                if key not in peers:
                    peers[key] = _routing.read(key, since=since - router.REPEAT_WINDOW)
                ln = router.code_rule(key, n, root, cx, peers[key])
                if ln is None:
                    todo.append((key, n))
                else:
                    router._append(shadow_path(), ln)
                    out["coded"] += 1
            if not todo:
                continue
            batch = todo[:cap]
            before = dict(attempts)
            lines, rec = router.call_project(root, batch, cx, runner, attempts)
            for ln in lines:
                router._append(shadow_path(), ln)
            router._append(router.calls_path(), rec)
            if attempts != before:
                router._save_attempts(attempts)
            out["called"] += len(batch)
            out["calls"] += 1
            out["fallback"] += rec["fallback"]
            out["retry"] += rec["retry"]
        return out
