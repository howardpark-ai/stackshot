"""project_activity.py: when each project last heard from outside and when its owner last gave input (`GET /client/project-activity`, `client.py project-activity`).

A script that decides whether a project may sleep needs two times per project, both about people and the world, never about the fleet's own traffic:

  anchor   the newest ANCHOR NOTICE that came in from outside: a line of the project's routing log (router/routing.py, `<state>/routing/<project key>.jsonl`) of kind `anchor`, recorded by the hub for an event on a
           watched thing. Left out, because the instance or an agent made them: a routine event on the fleet's own repository (the hub files it `log_only` and rules it itself), a log-only direct anchor (target `direct`,
           no recipient, nothing delivered), and the hub's own warning that an anchor cannot be read (it names the hub as its sender). Board notices and messages are other kinds of line and never count. What the hub's receivers
           drop upstream never reaches the log: the owner's own posts (Slack, GitHub comments) and a bot's message on a Slack direct anchor. Everything else on a watched thing does, a bot's comment or a CI notice on a pull
           request included, and the log does not say who posted. So the anchor time can count a post that no person made: it over-counts activity, which is the safe direction for a script deciding whether a project is quiet.
  owner    the newest INPUT of the person the board is for, from two records:
             - a board action: an entry of an item's `metadata.answers` (service/answer.py, answer_handover.py, github_events.py): his answer, decision, Done, note or comment on the board or on the item's GitHub issue
               (`via` board or github). An entry the server made for him on a mail he sent (`via` mail) is the server's tick, not his action, and is left out.
             - a front-chat message: the stamp file `<state>/prompts/<session id>` (written by the prompt hook on each of his prompts, never for a notice, a relayed message or a typed-in line; read here as telling.presence_here reads it),
               counted for the project of the front agent the session is (anchors.file_roles: role `front`, which also makes the name-line session of a one-session project front: a project with no `agents:` map has that one
               session and the owner talks to it directly, so its stamp is his front chat; session_roles alone calls it `keeper`, a role for who gets a notice, not for who he types to). A stamp of a session that is no
               front agent (a background agent's pane) or that no page lists is left out. The stamps are read only from this server's own state folder: a front agent whose pane runs on another machine leaves none here,
               so its chat is not seen.
           An audit, a router ruling, a notice and a message between agents are none of these.

A project is the top-level project (a sub-page counts for the project that owns it). Times are whole epoch seconds; a time in the future (more than `SKEW_S` ahead of the clock) is not a time that happened and is left out. A project with
neither value has no row. Reads only: the store, the routing log, the stamp files and the roles; it writes nothing and tells nobody.

A failure is never an empty answer: where a record the answer needs cannot be read, `Unreadable` is raised and the endpoint answers 503 with the reason (the client exits 1). That is the page registry when any time was found
(the roles and the sub-page mapping read it: without it every stamp would be dropped and a sub-page would stand for itself) and the roles or the stamp folder when stamps exist. A stamp folder that does not exist is no stamps.

A service module: imports point down only."""
from __future__ import annotations

import json
import time
from typing import Any

from stackshot.anchors import anchors as _anc
from stackshot.core import config as _cfg
from stackshot.core.store import _item_files
from stackshot.fleet import sessions_registry as _sr
from stackshot.model import item_project as _ip
from stackshot.router import routing as _routing

SKEW_S = 300.0                  # a time further ahead of the clock than this did not happen (a torn clock, a hand-edited record)
HUB_SENDER = "anchor-hub"       # the sender the hub names on its own warning line (anchors/anchorhub/core.py warn_unreadable)
_ANCHOR = b'"kind": "anchor"'   # json.dumps' own form of the field, as routing.py's lookups search for the id


def _time(v: Any, now: float) -> float:
    """`v` as a time that happened: a positive number (never a bool) not further ahead of `now` than SKEW_S; 0 for anything else."""
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        return 0.0
    try:
        t = float(v)
    except ValueError:
        return 0.0
    return t if 0 < t <= now + SKEW_S else 0.0


def external(n: dict[str, Any]) -> bool:
    """Is this routing line an anchor notice from outside (the module text lists what is not)?"""
    return (n.get("kind") == "anchor" and not n.get("log_only") and n.get("who") != HUB_SENDER
            and not (n.get("target") == "direct" and not n.get("to")))


def anchor_times(now: float) -> dict[str, float]:
    """{project key: the time of its newest external anchor notice}, from every project's routing file (only the lines that name the kind are parsed; the newest time wins, not the last line written). A file or a line that cannot be read is skipped."""
    out: dict[str, float] = {}
    for key in _routing.projects():
        try:
            data = _routing._file(key).read_bytes()
        except OSError:
            continue
        for raw in data.split(b"\n"):
            if _ANCHOR not in raw:
                continue
            try:
                n = json.loads(raw)
            except ValueError:
                continue
            t = _time(n.get("ts"), now) if isinstance(n, dict) and external(n) else 0.0
            if t:
                top = _ip.top_of(key)
                out[top] = max(out.get(top, 0.0), t)
    return out


def answer_times(now: float) -> dict[str, float]:
    """{project key: the time of his newest board action}, from the `answers` of every item, closed ones too. An item file that does not mention `answers` is not parsed."""
    out: dict[str, float] = {}
    for gid, p in _item_files():
        try:
            text = p.read_text(encoding="utf-8")
            if '"answers"' not in text:
                continue
            it = json.loads(text)
        except (OSError, ValueError):
            continue
        if not isinstance(it, dict) or not isinstance(it.get("metadata"), dict):
            continue
        ans = it["metadata"].get("answers")
        t = max((_time(a.get("ts"), now) for a in ans if isinstance(a, dict) and a.get("via") != "mail"), default=0.0) if isinstance(ans, list) else 0.0
        if t:
            top = _ip.project_of(it["metadata"])
            if top:
                out[top] = max(out.get(top, 0.0), t)
    return out


class Unreadable(RuntimeError):
    """A record the answer needs cannot be read: the answer is an error with this reason, never a smaller answer."""


def _need_registry() -> None:
    """Raise Unreadable when the page registry the roles and the sub-page mapping read is empty or cannot be read (both read it as {} without saying so)."""
    if not _anc.registry() or not _ip._pages():
        raise Unreadable("the project page registry cannot be read")


def prompt_times(now: float) -> dict[str, float]:
    """{project key: the time of his newest front-chat message}, from the stamp files of the sessions that are front agents. No stamp folder is no stamps; a folder that cannot be read, or stamps with no roles to place them by,
    raise Unreadable. One stamp file that cannot be read leaves that session out."""
    out: dict[str, float] = {}
    try:
        stamps = [f for f in _cfg.state("prompts").iterdir() if f.is_file() and not f.name.startswith(".")]
    except FileNotFoundError:
        return out
    except OSError as e:
        raise Unreadable(f"the front-chat stamp folder cannot be read ({e.__class__.__name__})") from e
    if not stamps:
        return out
    # file_roles, not session_roles: the only session of a one-session project is the session he talks to, which file_roles calls front (a name-line session of an active page with no `agents:` map, not retired, no cloud id)
    # and session_roles `keeper`. The roles file the sessions' own scripts read says the same.
    try:
        roles = _anc.file_roles()
    except Exception as e:  # noqa: BLE001
        raise Unreadable(f"the session roles cannot be read ({e.__class__.__name__}: {e})") from e
    if not roles:
        raise Unreadable("the session roles are empty although front-chat stamps exist, so no stamp can be placed")
    for f in stamps:
        try:
            t = _time(f.read_text(encoding="utf-8").strip().split()[0], now)
            name = _sr._role_name(roles, f.name) if t else ""
            r = roles.get(name) if name else None
            if not r or r.get("role") != "front" or not r.get("project"):
                continue
            top = _ip.top_of(r["project"])
            out[top] = max(out.get(top, 0.0), t)
        except Exception:  # noqa: BLE001  — one unreadable stamp leaves that session out
            continue
    return out


def activity(now: float | None = None) -> dict[str, dict[str, int | None]]:
    """{project key: {"anchor": epoch | None, "owner": epoch | None}}, only the projects that have either, by key. Raises Unreadable (module text) where a record it needs cannot be read."""
    now = time.time() if now is None else now
    anchor = anchor_times(now)
    answers = answer_times(now)
    prompts = prompt_times(now)
    if anchor or answers or prompts:
        _need_registry()
    owner: dict[str, float] = {}
    for src in (answers, prompts):
        for k, t in src.items():
            owner[k] = max(owner.get(k, 0.0), t)
    return {k: {"anchor": int(anchor[k]) if k in anchor else None, "owner": int(owner[k]) if k in owner else None} for k in sorted({*anchor, *owner})}


def payload(now: float | None = None) -> dict[str, Any]:
    """What the endpoint serves: {"projects": activity()}."""
    return {"projects": activity(now)}
