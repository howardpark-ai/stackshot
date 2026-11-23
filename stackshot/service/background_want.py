"""background_want.py: a project that has no background agent says so, and the fleet tool may create one.

A message to a project that lists a front agent and no background agent has nobody to take it but that front agent, which a message that asks nothing of the person must not wake. The message keeps its old route
(the router archives it or the front gate holds it, no turn starts); this module only RECORDS that the project could use a background agent, a "want". It starts nothing, writes nothing to the project record and runs no
command: the fleet tool reads the wants (`GET /client/background-wanted`, `client.py background-wanted`), decides when the box can take one more session, and lists the agent the way its New session form does.
Later messages reach that agent by the one lookup the router and the message tool share (anchors.background_agent).

`want_background(project, kind)` is called once for a message to such a project, before it is ruled and whatever becomes of it (router_live._act, through the router's hook, for every ruling; messaging._message, before the front gate, for a message to a front agent by name). It records a want when the project
is eligible and the switch is on, and answers whether it recorded a new one. Eligible: listed and not retired, a top-level project (no sub-page, no `hub:` line), at least one front agent that is a session of the fleet (so the
agent a project's first listing would make keeper is never the new one), no background agent on its hub, and `kind` a message (a board or anchor notice never wants one). It NEVER raises: a failure leaves the message as it was.

`wanted()` is what the endpoint serves: the wants still open, each computed as "want present AND eligible AND still no background agent", so an agent that got listed drops the project by itself (and the want is then
marked served). A project that got an agent and lost it again wants one again only after `cooldown_minutes` from the want or the agent's showing up, and only on a new message. At most `max_open` wants are open at once.

A want is looked up by the project's id, never by the key it was recorded under, so a page that is renamed keeps it (the stored key is refreshed by the next message).

State: <state>/background-wanted.json {"schema": 1, "wants": {<project id>: {"key", "at", "served"?}}}, written whole through a temp file under an exclusive flock on <state>/background-wanted.lock, so two
threads or two processes setting one project's want make one. A switch that is off writes nothing and `wanted()` answers empty.

A service module: imports point down only."""
from __future__ import annotations

import fcntl
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from stackshot.anchors import anchors as _anc
from stackshot.core import config as _cfg
from stackshot.core import readonly as _ro
from stackshot.projects import keeper as _kp
from stackshot.projects import project_verbs as _pv
from stackshot.projects import projects as _prj

KIND = "message"          # the one kind of notice that wants an agent: a message a session wrote, never a board or anchor notice
MAX_OPEN = 3              # [background_agent] max_open: wants open at once
COOLDOWN_MINUTES = 60     # [background_agent] cooldown_minutes: before a project whose want was served wants again
SCHEMA = 1


def enabled() -> bool:
    """[background_agent] enabled: off by default (an instance whose fleet tool creates no agents leaves it off); read at each use."""
    return _cfg.background_agent_enabled()


def _setting(key: str, default: int) -> int:
    try:
        v = int(_cfg.get("background_agent", key))
    except (TypeError, ValueError):
        return default
    return v if v >= 0 else default


def max_open() -> int:
    return _setting("max_open", MAX_OPEN)


def cooldown_seconds() -> float:
    return float(_setting("cooldown_minutes", COOLDOWN_MINUTES)) * 60.0


def state_path() -> Path:
    return _cfg.state("background-wanted.json")


class _locked:
    """An exclusive flock on a lock file beside the state file: the one lock for every thread and process that reads and writes the wants."""
    def __enter__(self) -> "_locked":
        p = state_path().with_suffix(".lock")
        p.parent.mkdir(parents=True, exist_ok=True)
        self.f = open(p, "w")
        try:
            fcntl.flock(self.f, fcntl.LOCK_EX)
        except BaseException:
            self.f.close()
            raise
        return self

    def __exit__(self, *a: Any) -> bool:
        try:
            fcntl.flock(self.f, fcntl.LOCK_UN)
        finally:
            self.f.close()
        return False


def _num(v: Any) -> float:
    """A time read from the file: a number, else 0 (an entry written by hand or damaged is tolerated, never raises)."""
    try:
        f = float(v)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return f if f == f and abs(f) != float("inf") else 0.0


def _read() -> dict[str, Any]:
    """The wants as written ({} for a missing, unreadable, foreign or too deeply nested file: a want lost is only asked for again by the next message, and the next write replaces the file). An entry that is no
    object is skipped; the times of one that carries a string or nothing read as 0, so one odd entry never hides the others."""
    try:
        d = json.loads(state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return {}
    w = d.get("wants") if isinstance(d, dict) else None
    if not isinstance(w, dict):
        return {}
    out: dict[str, Any] = {}
    for k, v in w.items():
        if isinstance(v, dict):
            out[str(k)] = {"key": str(v.get("key") or ""), "at": _num(v.get("at")), **({"served": _num(v.get("served"))} if "served" in v else {})}
    return out


def _write(wants: dict[str, Any]) -> None:
    p = state_path()
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps({"schema": SCHEMA, "wants": wants}, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, p)


def _look(project: str) -> dict[str, Any] | None:
    """What a project looks like to a want: {id, key, prefix, front, agent (its background agent, "" for none)}, or None when it can have none: not a page of the registry, hidden (not listed), retired or moved,
    a sub-page or a page with a `hub:` line, with no front agent that is a session of the fleet (a page with only a name line, a one-session project, lists none), or whose key, name prefix or front agent is no
    plain name (a line of the endpoint's answer is three words). `project` is a page key or the project's permanent id: a want is looked up by its id, so a renamed page keeps it."""
    x = str(project or "").strip().strip("/")
    if x.endswith(".md"):
        x = x[:-3]
    if not x:
        return None
    reg = _prj.with_made(_anc.registry())
    rec = next(iter(_prj.refs(x, reg)), None)
    key = str((rec or {}).get("key") or "")
    entry = reg.get(key)
    if not rec or not isinstance(entry, dict) or key.count("/") != 1 or (key != x and not _prj.is_id(x)):
        return None
    if not rec.get("listed") or rec.get("retired") or rec.get("sub_page") or not _prj.page_active(entry):
        return None
    fronts = {n: a for n, a in (rec.get("agents") or {}).items() if a.get("front") and not a.get("page_owed") and not _kp.off_sala(a)}
    if not fronts:
        return None
    prefix = str(_prj.agent_prefixes(key, entry, reg, rec.get("agents"))[0])      # the name line's, else the front agent's name without -main (the project verbs take it first), else the slug
    front = str(_prj.main_of(fronts) or sorted(fronts)[0])
    if not all(_pv.NAME_RE.fullmatch(w) for w in (*key.split("/"), prefix, front)):
        return None
    return {"id": rec["id"], "key": key, "prefix": prefix, "front": front, "agent": _anc.background_agent(key, reg)}


def _open(wants: dict[str, Any], looks: dict[str, Any] | None = None) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    """(id, want, look) of the wants not served whose project is eligible and has no background agent, oldest first. A want whose project has got an agent is marked served here (`looks` collects the ids)."""
    out = []
    for pid, w in sorted(wants.items(), key=lambda kv: (float(kv[1].get("at") or 0), kv[0])):
        if "served" in w:
            continue
        look = _look(pid)      # by the project's id: a page that was renamed since the want was recorded is still the same project
        if look is None:
            continue
        if look["agent"]:
            if looks is not None:
                looks[pid] = look
            continue
        out.append((pid, w, look))
    return out


def open_state(project: str) -> str:
    """Is there an open want for `project` right now, the way `wanted()` serves it? "open" when the switch is on, the project is eligible, has no background agent and its want is recorded and not served; else
    why not: "off" (the switch), "not_eligible" (see `_look`), "has_agent" (a background agent is listed), "none" (no want recorded) or "served" (its want was served). "error" when the file cannot be
    read as a whole. Reads only, never raises: the check `post project-agent` makes for a background call."""
    try:
        if not enabled():
            return "off"
        look = _look(project)
        if look is None:
            return "not_eligible"
        if look["agent"]:
            return "has_agent"
        w = _read().get(look["id"])
        if w is None:
            return "none"
        return "served" if "served" in w else "open"
    except Exception as e:  # noqa: BLE001
        print(f"background want: {project} not read: {e.__class__.__name__}: {str(e)[:120]}", file=sys.stderr, flush=True)
        return "error"


def want_background(project: str, kind: str, now: float | None = None) -> bool:
    """Record that `project` could use a background agent: a message (`kind`) reached it and it has none. -> True when a new want was recorded, False for anything else (switch off, another kind, not eligible, a want
    already open, the cooldown not over, the cap reached, a failure). Never raises."""
    try:
        if kind != KIND or not enabled() or _ro.is_read_only():
            return False
        look = _look(project)
        if look is None or look["agent"]:
            return False
        t = time.time() if now is None else float(now)
        with _locked():
            wants = _read()
            cur = wants.get(look["id"])
            if cur is not None:
                if "served" not in cur:
                    if cur.get("key") != look["key"]:        # the page was renamed (the id followed it): keep the stored key current
                        cur["key"] = look["key"]
                        _write(wants)
                    return False        # set-if-absent: it is already open
                if t - max(float(cur.get("at") or 0), float(cur.get("served") or 0)) < cooldown_seconds():
                    return False
            if sum(1 for w in wants.values() if "served" not in w) >= max_open() and len(_open(wants)) >= max_open():
                return False
            wants[look["id"]] = {"key": look["key"], "at": t}
            _write(wants)
            return True
    except Exception as e:  # noqa: BLE001  — an extra: a failure in it leaves the message as it was
        print(f"background want: {project} not recorded: {e.__class__.__name__}: {str(e)[:120]}", file=sys.stderr, flush=True)
        return False


def wanted(now: float | None = None) -> list[dict[str, str]]:
    """The projects the fleet tool may give a background agent now, oldest want first: [{key, prefix, front}], the project's page key, its name prefix (the agent is called <prefix>-<role>) and its front agent.
    [] with the switch off (nothing is read or written). A want whose project got an agent in the meantime is marked served, which starts its cooldown. Never raises."""
    try:
        if not enabled():
            return []
        looks: dict[str, Any] = {}
        rows = _open(_read(), looks)
        if looks and not _ro.is_read_only():      # a read-only standby copy marks nothing, and says nothing
            try:
                with _locked():
                    wants = _read()
                    t = time.time() if now is None else float(now)
                    for pid in looks:
                        if pid in wants and "served" not in wants[pid]:
                            wants[pid]["served"] = t
                    _write(wants)
            except Exception as e:  # noqa: BLE001  — read only for the caller; the mark is made at a later read
                print(f"background want: served wants not marked: {e.__class__.__name__}: {str(e)[:120]}", file=sys.stderr, flush=True)
        return [{"key": look["key"], "prefix": look["prefix"], "front": look["front"]} for _pid, _w, look in rows]
    except Exception as e:  # noqa: BLE001
        print(f"background want: not read: {e.__class__.__name__}: {str(e)[:120]}", file=sys.stderr, flush=True)
        return []


def wanted_lines() -> str:
    """What `GET /client/background-wanted` answers: one line per wanted project, `<project key> <name prefix> <front agent>`, empty when there are none."""
    return "".join(f"{r['key']} {r['prefix']} {r['front']}\n" for r in wanted())
