"""router_live.py — the router that rules stackshot's notices (design: the design doc).

The router rules every project.
There is no list of projects and no switch: every page of the registry is the router's, and the way back is a revert of the code.

  [router] live_tick_seconds  how often the live tick looks (default 60)
  [router] general_<scope>  the general -main agent of each scope (a scope of [project_scopes] order) that a page with no agent of its own falls to (see STAND-IN); none by default
  [[router.watch]] / [[router.quiet]]  the standing rulings (an anchor to an agent; a project whose agent is held for the digest); none by default
Both are read at each use, so a reload applies them. The keys [router] live and live_projects of the earlier form are ignored if present.

HOLD. A notice for a project is not delivered to the session the page names (a name that no running session carries). The place that would have delivered it (anchor-hub's
send, the server's message to a project, the board relay, the wake pass) calls holds(project, recipient); when it says yes the
notice is recorded in the routing log as usual but with `"live": true` and no recipient (routing.record(live=True)), the text
the session would have read is kept in <state>/router/held/<id>.json (stash), and nothing is pushed.

ACT. tick() (a thread of the server, loop()) takes the unruled live-held notices of each live project and judges them with
router.py's own code: its rules in code (code_rule), then one thin call per project (call_project). A notice whose call failed
or was left out stays held, undelivered, for one more try at the next tick (router.py's attempts file); the second failure is a pass to the -main agent (fallback_line). Then it acts on each:
  passed   delivered to the target the way a pass is delivered (push.py, the pane inbox), then ruled with
           routing.rule(id, "passed", to=target, by="stackshot (router)"). The text opens with "[for <owner>]" whenever the target
           is a front agent, whatever for_owner says: a front pane takes a peer's message only with the mark. A delivery
           to a background agent is unmarked.
           A batch finding of the audit (router.py's rule `audit-owners`) carries a `split`: one message per owner, each with the lines of its own
           items, marked as a pass to that agent is marked (_act_split); `to` in the routing log lists every owner, one still holding lines from before an earlier change named
           "(held)". A finding is a task for its mover: a BACKGROUND owner is woken with its lines at once, whole, like any pass (they had been held for its
           next turn as "asked nothing of you", then as one line cut to 260 characters, which left the findings out).
  dropped / merged / held   routing.rule only; nothing is delivered (a held notice is the page pass's).
A notice that cannot be judged twice (or an exception) is passed to the -main agent, never dropped; with no -main agent anywhere (the
page, its hub and the scope's general agent list none) it is held, with the reason. A delivery that fails is retried at the next ticks, three times, then
goes to the -main agent. Every action is a line in <state>/router/live.jsonl.

STAND-IN. stand_in(project) is where delivery goes where a page's name-line session used to be written to: the project's builder, a background agent whose
mandate says build, maintain, merge or engineer, else its -main agent. A page with no user-facing agent of its own falls to (1) its hub
page's agents (`hub:` line: agent_root), else (2) the general -main agent of its scope (anchors.general_main): the scope's
[router] general_<scope> (an agent name, or a page key whose -main agent is used; a page that lists no front agent but has a `display-name:` line gives its name-line session), else the default scope's. Router.Context.agents gives such a page that one agent, nobody else of the general page.
A page's `display-name:` line is only its name now: it decides nothing.

DIGEST. The router holds what no agent should be interrupted for (the page pass, a page's quiet hours, what the call is unsure of,
an image it could not read), so a held notice reaches nobody at once. A held notice owes nothing, and what is for the owner lives in
stackshot's For you list, not in a front agent's turn. digest_tick() (the same thread as the live tick) therefore does not deliver a
digest of held notices: once a day per live project, from [router] digest_hour on (default 9, the instance timezone; a server down at
that hour does it when it is back the same day), it writes one entry listing every notice ruled `held` since the last digest, each as id,
label, sender, gist and reason, to live.jsonl as kind "digest_logged" (with its text), and the notices count as digested (none is listed
twice). Nothing is pushed to any agent. The page-pass holds (the code rule `page-pass`: the page sheets of the jobs [router] page_senders
names) are their own group, logged the same way under the head "held for the page pass". A notice the router could not rule (CAP below)
is stackshot's own problem, so a digest with one is delivered: to the project's builder, unmarked, listing every row of the group; a
project with no builder takes it to its -main agent with "[for <owner>]" on line 1, since someone must see it. The quiet-hour holds of
the instance's [[router.quiet]] rows (router.quiet_map) go in the same pass to that agent, unmarked when it is a background
agent. Each group has its own day mark and tries. <state>/router/digest.json records the day each group was done, the notices already
digested (so none is sent twice) and the time of each project's last delivered digest. The routing log keeps the held ruling as it is, and
each digest delivered is a line of live.jsonl (kind "digest", project, count, target, outcome). A push that fails is tried again at the
next ticks (three times a day); its notices then wait for the next day's digest.

NOTE. A ruling line from the call may carry `note` (one line, at most 300 characters): what the router learned that belongs on the
project's page. After the ruling is written, the note goes to the page's timeline with the gbrain CLI as page_debt.GbrainIO runs it
(`gbrain call add_timeline_entry '{"slug", "date", "summary", "source": "stackshot (router)", ...}'`; the date is today in the instance
timezone), once per notice (live.jsonl `noted`). A failure is logged on the line (`note_error`) and never blocks the ruling. A page in a brain marked
`shared` takes no note: it is skipped, with no `note_error` and no `noted`, and the ruling is as it was. [router] notes (default true) is the switch.

HOLD FOR A BACKGROUND AGENT. A pass to a BACKGROUND agent of a notice that asks nothing of it is not
delivered as a turn: _hold_kind is the one decision (held.decide), and the notice is held for the agent's next turn (held.py: stored server-side,
handed over by the UserPromptSubmit hook), ruled `held` in the routing log with the reason "held: asks nothing (kind)". The kinds the router sees:
a notice recorded with `hold` (routing.record: a page-owed notice, a message its sender marked fyi) and a batch finding of the audit (rule
audit-owners, kind audit). A notice that carries the owner's words ([for <owner>], needs: decision, a `words` or `handback` mark, for_owner on the
ruling), or goes to a front agent, is passed as before. [router] hold_notices = false turns the hold off.

CAP. A ruling that cannot be written to the routing log (routing.rule raised) is tried again at the next ticks, three times in all.
After that the notice is logged with status "stuck", never judged again, and listed in the next digest as "could not be ruled".

`stackshot router-live status` prints a line per project: the notices acted on in the last hour; the notices held
since the last digest and the time of that digest; the last error. Stdlib only; anchor-hub imports it for holds() and stash().
"""
from __future__ import annotations
import os as _os, sys as _sys
if not __package__:   # started as a script (python3 stackshot/<area>/<name>.py): the checkout must be importable
    _here = _os.path.dirname(_os.path.abspath(__file__))
    _sys.path[:] = [_os.path.dirname(_os.path.dirname(_here))] + [p for p in _sys.path if _os.path.abspath(p or ".") != _here]

import datetime as dt
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

from stackshot import paths as _paths
from stackshot.core import config as _cfg
from stackshot.core import interp as _interp   # a missing interpreter (its uv environment deleted) never stops a delivery
from stackshot.router import routing as _routing
from stackshot.anchors import anchors as _anc
from stackshot.router import router as _router
from stackshot.waits import held as _held       # a notice that asks nothing of a background agent is held for its next turn

BY = "stackshot (router)"           # the ruler's name in the routing log, and the sender of what the router delivers
KINDS = _router.KINDS
SINCE_DAYS = 7                      # a held notice older than this is not taken up
MAX_TRIES = 3                       # delivery attempts to the target; then the -main agent. Also the writes of a ruling to the routing log; then "stuck"
NOTE_MAX = 300                      # characters in a ruling's `note`
DIGEST_SHOWN = 25                   # a digest lists this many notices, one line each, and counts the rest
DIGEST_TRIES = 3                    # pushes of one digest in a day; then its notices wait for the next day's
_LOCK = threading.Lock()

# What the server wires in (configure): the front-agent test (telling.front_keeper), the push, and the call made after a ruling
# (the release of a hold that waited on the notice's anchor, the board's republish). The defaults stand alone, for the tests and the CLI.
_HOOKS: dict[str, Any] = {"is_front": None, "deliver": None, "after_rule": None}


def configure(**kw: Any) -> None:
    for k, v in kw.items():
        if k not in _HOOKS:
            raise TypeError(k)
        _HOOKS[k] = v


# ----------------------------------------------------------------------------- config (read at each use: a reload applies)
def _truthy(v: Any) -> bool:
    return v is True or str(v).strip().lower() in ("true", "1", "yes", "on")


def is_live(project: str) -> bool:
    """Does the router rule this page key's notices? Every page of the registry, and a page under it (anchors.pilot_root)."""
    return bool(_anc.pilot_root(project))


def tick_s() -> float:
    try:
        return max(5.0, float(_cfg.get("router", "live_tick_seconds", default=60)))
    except (TypeError, ValueError):
        return 60.0


def digest_hour() -> int:
    """[router] digest_hour: the hour (0 to 23, the instance timezone) from which the day's digest of held notices may go (default 9)."""
    try:
        return min(23, max(0, int(_cfg.get("router", "digest_hour", default=9))))
    except (TypeError, ValueError):
        return 9


def notes_enabled() -> bool:
    """[router] notes: a ruling's `note` is written to the project page's timeline (default true; false = notes are ignored)."""
    v = _cfg.get("router", "notes")
    return True if v is None else _truthy(v)


def agent_root(root: str, reg: dict[str, dict[str, Any]]) -> str:
    """The page whose agents serve a pilot root: the root itself, or, for a root that names no agent of its own (projects/example-portal and
    ops/hub keep their key but are part of projects/hub: their `hub:` line), its hub's page."""
    def has(r: str) -> bool:
        page = reg.get(r) or {}
        return bool(page.get("agents"))
    if has(root):
        return root
    hub = _anc.hub_of(root, reg)
    return hub if hub and hub != root and has(hub) else root


def holds(project: str, session: str, stand_in_too: bool = False) -> bool:
    """Is this notice, which would go to `session` for `project`, the router's to rule? True when `session` is the name the project's
    notices are addressed to (anchors.notice_name: the page's name line, else the session its notices fall to). With `stand_in_too` it is also true when `session` is the
    project's stand-in (stand_in): the board and page-debt relays resolve their keeper through `project_keeper`, which answers the stand-in
    for a live project, and must reach the router, not the builder. Every other recipient is delivered to as before (a wake for a
    builder named in an item's needs is its own work)."""
    try:
        if not session or not is_live(project):
            return False
        nm = _anc.names()
        want = [_anc.notice_name(project)] + ([stand_in(project)] if stand_in_too else [])
        return any(w and _anc.canonical(session, nm) == _anc.canonical(w, nm) for w in want)
    except Exception:  # noqa: BLE001
        return False


def _agents_of(project: str, reg: dict[str, dict[str, Any]]) -> tuple[dict[str, str], dict[str, str]]:
    """(front, back) agents of the page whose agents serve this project (agent_root), {name: mandate} each."""
    root = agent_root(_anc.pilot_root(project), reg)
    page = reg.get(root) or {}
    agents = {str(k): str(v) for k, v in (page.get("agents") or {}).items()}
    back = {k: agents[k] for k in (page.get("back_agents") or {}) if k in agents}
    return {k: v for k, v in agents.items() if k not in back}, back


def builder(project: str, reg: dict[str, dict[str, Any]] | None = None) -> str:
    """The builder of a live project: the first background agent whose mandate line says build (first choice), maintain, merge or
    engineer; "" for a project that is not live and when there is none. As router.Context.builder."""
    try:
        if not is_live(project):
            return ""
        _front, back = _agents_of(project, _anc.registry() if reg is None else reg)
        hits = [(0 if re.search(r"\bbuild", m, re.I) else 1, i, k) for i, (k, m) in enumerate(back.items()) if _router._BUILDER.search(m)]
        return min(hits)[2] if hits else ""
    except Exception:  # noqa: BLE001
        return ""


def stand_in(project: str, reg: dict[str, dict[str, Any]] | None = None) -> str:
    """The project's STAND-IN, the agent the router's passes go to for it: its builder (builder()), else its -main agent (its own page's, else
    its hub's, else the scope's general one: anchors.fallback_main). "" for a key that names no page, and when no session can be named. The
    page's name line decides nothing here; a one-session page's items keep their keeper (telling.project_keeper), not this agent."""
    try:
        reg = _anc.registry() if reg is None else reg
        if not is_live(project):
            return ""
        b = builder(project, reg)
        if b:
            return b
        return _anc.fallback_main(project, reg)      # the page's own -main, else its hub's, else the scope's general one: the same chain the router's call uses (a page with background agents only has no -main of its own)
    except Exception:  # noqa: BLE001
        return ""


# ----------------------------------------------------------------------------- the logs and the held text
def _dir() -> Path:
    return _router._dir()


def live_path() -> Path:
    return _dir() / "live.jsonl"


def held_dir() -> Path:
    return _dir() / "held"


def stash(nid: str, body: str) -> None:
    """Keep the full text of a held notice (the routing log keeps a 300-character gist) for the router to deliver. A failure to
    write is not an error: the gist is delivered instead."""
    try:
        held_dir().mkdir(parents=True, exist_ok=True)
        (held_dir() / f"{nid}.json").write_text(json.dumps({"body": str(body)}, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def stashed(nid: str) -> str:
    try:
        return str(json.loads((held_dir() / f"{nid}.json").read_text(encoding="utf-8")).get("body") or "")
    except (OSError, ValueError):
        return ""


def _log(line: dict[str, Any]) -> None:
    _router._append(live_path(), line)


def _owner_mark() -> str:
    return f"[for {_cfg.get('instance', 'owner') or 'the owner'}]"


# ----------------------------------------------------------------------------- delivery
def deliver_via(push: list[str], target: str, text: str, timeout: float = 110.0) -> str:
    """Push `text` to `target` the way the server's relays do (push.py, the message source's queue) → push.py's last line
    ("delivered …", "queued …", "inbox …") or an error word."""
    try:
        r = subprocess.run([*_interp.resilient(push), "--from", BY, target, text], capture_output=True, text=True, timeout=timeout,
                           env={**os.environ, "ANCHOR_PUSH_SOURCE": "msg"})
        return (r.stdout.strip().splitlines() or [r.stderr.strip().splitlines()[-1] if r.stderr.strip() else "no result"])[-1]
    except subprocess.TimeoutExpired:
        return "timed out"
    except Exception as e:  # noqa: BLE001
        return f"failed: {type(e).__name__}"


def _deliver(target: str, text: str) -> str:
    fn = _HOOKS["deliver"]
    return fn(target, text) if fn else deliver_via([sys.executable, _paths.program("fleet", "push")], target, text)


def _ok(outcome: str) -> bool:
    return str(outcome).startswith(("delivered", "queued", "inbox"))


def _is_front(who: str, root: str, cx: "_router.Context") -> bool:
    fn = _HOOKS["is_front"]
    if fn:
        try:
            return bool(fn(who, root))
        except Exception:  # noqa: BLE001
            return False
    return who in cx.agents(root)[0]


def _hold_kind(n: dict[str, Any], ln: dict[str, Any], target: str, cx: "_router.Context") -> str:
    """The one decision of the router's hold: is this pass to `target` held for its next turn? -> the held kind, "" to deliver as
    before. Only a background agent holds; a notice with the owner's words, a hand-back or a ruling marked for the owner is delivered; anything unsure is
    delivered. Never raises."""
    try:
        if ln.get("rule") == "audit-owners":          # a finding is a task for its mover, never "asked nothing of you": it wakes a builder
            return ""
        kind = str(n.get("hold") or "")
        if not kind or not target:
            return ""
        body = _body(n)
        to_owner = bool(_router.line_for_owner(ln) or n.get("words") or n.get("handback") or _router.strong_owner(body) or _router.strong_owner(n.get("text")))
        return _held.decide(kind, is_background=bool(cx.background(target)), text=body, owner_words=to_owner, target=target)
    except Exception:  # noqa: BLE001
        return ""


def _body(n: dict[str, Any]) -> str:
    b = stashed(n["id"])
    if b:
        return b
    return " · ".join(x for x in (str(n.get("label") or ""), str(n.get("who") or "")) if x) + f": {n.get('text') or ''}" + (f" → {n['url']}" if n.get("url") else "")


def compose(n: dict[str, Any], root: str, target: str, reason: str, mark: bool, body: str | None = None) -> str:
    """What a pass delivers: the router's line (notice id, project, why), then the notice as the keeper would have read it (`body`:
    the part of it that is this target's, for a split batch)."""
    if body is not None:
        head = f"[stackshot] router: notice {n['id']} on {root} is passed to you" + (f": {reason}" if reason else ".")
        return (f"{_owner_mark()} " if mark else "") + head + "\n" + body + "\nThe router ruled it: no ruling is owed. Act on it within your mandate."
    if n.get("handback"):       # an item handed back to its mover alone (router.py hand-back): the one line the server wrote, nothing around it. (A close with the owner's own words is no pass any more: it is a For you row.)
        return (f"{_owner_mark()} " if mark else "") + _body(n)
    head = f"[stackshot] router: notice {n['id']} on {root} is passed to you" + (f": {reason}" if reason else ".")
    return (f"{_owner_mark()} " if mark else "") + head + "\n" + _body(n) + "\nThe router ruled it: no ruling is owed. Act on it within your mandate."


# ----------------------------------------------------------------------------- the live log
def _last() -> dict[str, dict[str, Any]]:
    """The last live.jsonl line of each notice id, and (in `tries`) how many errors it has had, (in `rule_tries`) how many times writing
    its ruling to the routing log failed. A line with no id (a digest's) is no notice's."""
    out: dict[str, dict[str, Any]] = {}
    for d in _router._read(live_path()):
        i = str(d.get("id") or "")
        if not i:
            continue
        tries = int(out.get(i, {}).get("tries", 0)) + (1 if d.get("status") == "error" else 0)
        rule_tries = int(out.get(i, {}).get("rule_tries", 0)) + (1 if d.get("stage") == "rule" else 0)
        out[i] = {**d, "tries": tries, "rule_tries": rule_tries}
    return out


def trace(nid: str) -> dict[str, Any]:
    """What live.jsonl holds of one notice, for the get tool: {"ruled": the last line of the router's own ruling of it (status "ruled": rule,
    source, target, item, reason, for_owner), "last": its last line of any status (an error shows there), "stuck": that line when the
    router gave up writing its ruling}, each None when there is none, and {} when the file is not read. Only the lines that carry the id
    are parsed, so the cost is a substring search over the file."""
    nid = str(nid).strip().lower()
    needle = f'"id": "{nid}"'
    try:
        data = live_path().read_bytes()
    except OSError:
        return {}
    out: dict[str, Any] = {"ruled": None, "last": None, "stuck": None}
    for ln in _routing.lines_with(data, needle):
        try:
            d = json.loads(ln)
        except ValueError:
            continue
        if not isinstance(d, dict) or str(d.get("id") or "") != nid:
            continue
        out["last"] = d
        if d.get("status") == "ruled":
            out["ruled"] = d
        elif d.get("status") == "stuck":
            out["stuck"] = d
    return out


# ----------------------------------------------------------------------------- the tick
def _judge(root: str, rows: list[tuple[str, dict[str, Any]]], cx: "_router.Context", runner: Any, since: float) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """The router's own ruling for each notice of the project's batch (router.py's rules in code, then its thin call): → (lines as the
    judging returns them, {"called": notices sent to a call, "calls": 0 or 1, "retry": notices left for one more try}). A notice
    whose call failed or was left out has no line on its first try: it stays held, undelivered, and is judged again at the next tick
    (router.py's attempts file); the second failure is the fallback line, a pass to -main. An
    exception anywhere passes every notice that has no line to the -main agent with the reason (no retry)."""
    lines: list[dict[str, Any]] = []
    todo = []
    stats = {"called": 0, "calls": 0, "retry": 0}
    try:
        peers: dict[str, list[dict[str, Any]]] = {}
        for key, n in rows:
            if key not in peers:
                peers[key] = _routing.read(key, since=since - _router.REPEAT_WINDOW)
            ln = _router.code_rule(key, n, root, cx, peers[key])
            if ln is None:
                todo.append((key, n))
            else:
                lines.append(ln)
        if todo:
            attempts = _router._load_attempts()
            before = dict(attempts)
            got, rec = _router.call_project(agent_root(root, cx.reg), todo, cx, runner, attempts)
            _router._append(_router.calls_path(), rec)
            if attempts != before:       # merge into the file as it is now: another pass may have saved its own meanwhile
                cur = _router._load_attempts()
                for key, n in todo:
                    i = str(n["id"])
                    if i in attempts:
                        cur[i] = attempts[i]
                    else:
                        cur.pop(i, None)
                _router._save_attempts(cur)
            lines += got
            stats.update(called=len(todo), calls=1, retry=len(todo) - len(got))
    except Exception as e:  # noqa: BLE001
        have = {x["id"] for x in lines}
        lines += [_router.fallback_line(n, key, agent_root(root, cx.reg), cx, f"the router failed on it ({type(e).__name__}: {str(e)[:100]})")
                  for key, n in rows if n["id"] not in have]
    return lines, stats


def add_timeline(slug: str, date: str, summary: str, detail: str, request_id: str) -> str:
    """One dated line on a page's timeline, written as the router (source BY) through the instance's page store (page_debt.page_io: the gbrain CLI's
    `call add_timeline_entry`, or the page file under `[pages] flavor = "plain"`; the request id makes a retry of the same notice's line a no-op in
    gbrain) → "" when accepted, else why not. Never raises."""
    try:
        from stackshot.router import page_debt as _pd
        return _pd.page_io().add_timeline(slug, date, summary, detail, BY, request_id)
    except Exception as e:  # noqa: BLE001
        return f"{type(e).__name__}: {str(e)[:120]}"


def _note(base: dict[str, Any], root: str, nid: str) -> None:
    """After a ruling was written: a `note` on the ruling line goes to the project page's timeline, once (the line is the notice's last,
    `noted`), dated today in the instance timezone. A failure is kept on the line (`note_error`) and never blocks the ruling; it is not
    tried again. Never raises."""
    note = " ".join(str(base.get("note") or "").split())[:NOTE_MAX]
    if not note or not notes_enabled():
        return
    from stackshot.projects import brains as _brains
    if _brains.shared_refusal(root):
        return                      # a shared brain's page takes no line of this board: skipped without a `note_error` (status() counts that as a router fault); the ruling stands
    try:
        today = dt.datetime.now(_cfg.tz()).strftime("%Y-%m-%d")
        why = add_timeline(root, today, note, f"router notice {nid}, ruled {base.get('ruling')}", f"stackshot-router-note-{nid}")
    except Exception as e:  # noqa: BLE001
        why = f"{type(e).__name__}: {str(e)[:120]}"
    if why:
        base["note_error"] = f"timeline note not written: {why}"
    else:
        base["noted"] = True


def _act_split(n: dict[str, Any], root: str, aroot: str, ln: dict[str, Any], cx: "_router.Context", prior: dict[str, Any],
               base: dict[str, Any], main: str) -> dict[str, Any]:
    """A pass that has a `split` (router.audit_rule: one batch finding, several owners) → the live.jsonl line. One message per agent,
    each with the lines of its own items (the -main agent's also with the lines that are no finding), marked as a pass to that agent
    is marked. The agents already told (`sent`, kept on the line) are not told again at a retry; an agent whose delivery failed
    MAX_TRIES times gets its lines at the -main agent instead. The notice is ruled once all are delivered, `to` listing every agent. A background
    agent is woken with its lines like a front one (a finding is a task, not "asked nothing"); only an entry of `sent` an earlier try
    wrote as ": held" (before an earlier change) is not delivered again, and `to` names it "(held)" so it does not look dropped."""
    split: dict[str, list[str]] = ln["split"]
    reason = ln.get("reason", "")
    sent: dict[str, str] = dict(prior.get("sent") or {})               # agent → delivery outcome, from the earlier tries
    failed = int(prior.get("tries", 0)) >= MAX_TRIES
    body = _body(n)
    marks, errors = [], []
    for agent, ids in split.items():
        if agent in sent:
            continue
        dest = main if failed and main and agent != main else agent
        mark = _is_front(dest, aroot, cx)
        text = _router.audit_text(body, ids, with_rest=agent == main)
        why = f"the audit's batch is split by item mover: these are the lines for {', '.join(ids) or 'the other lines'}"
        why += f" (mover {agent}; delivery to it failed {MAX_TRIES} times)" if dest != agent else (f" (mover {agent})" if agent != main else "")
        out = _deliver(dest, compose(n, root, dest, why, mark, text))
        if _ok(out):
            sent[agent] = f"{dest}: {out}"
            marks.append(mark)
        else:
            errors.append(f"delivery to {dest} failed: {out}")
    base.update(sent=sent, marked=any(marks) or bool(prior.get("marked")), outcome="; ".join(sent.values()), split=split,
                target=", ".join(split), reason=reason)
    if errors:
        return {**base, "status": "error", "error": "; ".join(errors)}
    told = [a for a in split if not sent[a].endswith(": held")]
    try:
        if not told:        # every keeper's lines were held by an earlier try (before an earlier change)
            base.update(ruling="held", reason=_held.reason("audit"), target="", held_for=", ".join(split), hold="audit")      # held_for: the digest leaves it out (it is waiting for the agents, not for a digest)
            _project, ruled = _routing.rule(n["id"], "held", reason=_held.reason("audit"), by=BY)
        else:
            to = [sent[a].split(":", 1)[0] + (" (held)" if a not in told else "") for a in split]          # every recipient, one with held lines named too
            _project, ruled = _routing.rule(n["id"], "passed", to=", ".join(dict.fromkeys(to)), reason=reason, by=BY)
    except Exception as e:  # noqa: BLE001
        return {**base, "status": "delivered", "stage": "rule", "error": f"delivered, not yet ruled: {type(e).__name__}: {str(e)[:100]}"}
    return {**base, "status": "ruled", "_ruled": ruled}


def _act(n: dict[str, Any], key: str, root: str, ln: dict[str, Any], cx: "_router.Context", prior: dict[str, Any]) -> dict[str, Any]:
    """Carry out one ruling → its live.jsonl line. Never raises."""
    base = {"id": n["id"], "ts": time.time(), "project": root, "key": key, "kind": n.get("kind"), "source": ln.get("source"), "rule": ln.get("rule"),
            "ruling": ln["ruling"], "target": ln.get("target", ""), "reason": ln.get("reason", ""), "for_owner": _router.line_for_owner(ln),
            "marked": False, "item": ln.get("item", ""), "call": ln.get("call", ""), "label": ln.get("label", ""), "text": ln.get("text", ""),
            "note": _router._clean(ln.get("note"), NOTE_MAX)}          # `note`: PR-X's optional key of a ruling line, read with .get
    aroot = agent_root(root, cx.reg)                  # the page whose agents serve this project (its hub's, for a component with none of its own)
    main = cx.main_agent(aroot)
    try:
        ruling, target, reason = ln["ruling"], ln.get("target", ""), ln.get("reason", "")
        if ruling == "passed":
            if not target or (int(prior.get("tries", 0)) >= MAX_TRIES and main and target != main):
                why = f"delivery to {target} failed {MAX_TRIES} times" if target else "no target"
                target, reason = main, f"passed to {main}: {why} ({reason})"
                base["source"] = "fallback"
            if not target:                                    # no -main agent anywhere (the page, its hub and the scope's general agent list none): held, with the reason, never dropped and never handed to a session that is gone
                ruling, reason = "held", f"no agent can take it: the page and its hub list no user-facing agent and the scope's general -main agent ([router] general_*) is on no page ({reason})"
                base["source"] = "fallback"
            base.update(ruling=ruling, target=target, reason=reason)
            if ln.get("split") and target:
                res = _act_split(n, root, aroot, ln, cx, prior, base, main)
                ruled = res.pop("_ruled", None)
                if ruled is None:
                    return res
                done = _HOOKS["after_rule"]
                if done:
                    try:
                        done(key, ruled)
                    except Exception as e:  # noqa: BLE001
                        res["error"] = f"after-rule: {type(e).__name__}: {str(e)[:100]}"
                _note(res, root, n["id"])
                return res
        if ruling == "passed" and prior.get("status") != "delivered":      # a pass that asks nothing of a background agent is held for its next turn
            hk = _hold_kind(n, ln, target, cx)
            if hk and _held.add(_held.key_of(target), hk, _body(n), sender=str(n.get("who") or ""), gid=str(ln.get("item") or ""), nid=n["id"]):
                held_for = target
                ruling, target, reason = "held", "", _held.reason(hk)
                base.update(ruling=ruling, target="", reason=reason, marked=False, held_for=held_for, hold=hk)
        if ruling == "passed":
            mark = _is_front(target, aroot, cx)       # a front pane takes a peer's message only with the mark: every delivery to one carries it, whatever for_owner says
            base["marked"] = mark
            if prior.get("status") == "delivered":            # delivered earlier; only the ruling is missing
                out = str(prior.get("outcome") or "delivered")
            else:
                out = _deliver(target, compose(n, root, target, reason, mark))
                if not _ok(out):
                    return {**base, "status": "error", "outcome": out, "error": f"delivery to {target} failed: {out}"}
            base["outcome"] = out
            try:
                _project, ruled = _routing.rule(n["id"], "passed", to=target, reason=reason, by=BY)
            except Exception as e:  # noqa: BLE001
                return {**base, "status": "delivered", "stage": "rule", "error": f"delivered, not yet ruled: {type(e).__name__}: {str(e)[:100]}"}
        else:
            base["outcome"] = ""
            try:
                _project, ruled = _routing.rule(n["id"], ruling, reason=reason, by=BY)
            except Exception as e:  # noqa: BLE001
                return {**base, "status": "error", "stage": "rule", "error": f"not ruled: {type(e).__name__}: {str(e)[:100]}"}
        done = _HOOKS["after_rule"]
        if done:
            try:
                done(key, ruled)
            except Exception as e:  # noqa: BLE001
                base["error"] = f"after-rule: {type(e).__name__}: {str(e)[:100]}"
        _note(base, root, n["id"])
        return {**base, "status": "ruled"}
    except Exception as e:  # noqa: BLE001
        return {**base, "status": "error", "outcome": "", "error": f"{type(e).__name__}: {str(e)[:140]}"}


def tick(now: float | None = None, runner: Any = None) -> dict[str, int]:
    """One pass over every project's unruled held notices → {"coded", "called", "calls", "fallback", "passed", "ruled", "errors", "stuck", "notes"}."""
    now = time.time() if now is None else now
    with _LOCK:
        out = {"coded": 0, "called": 0, "calls": 0, "fallback": 0, "retry": 0, "passed": 0, "ruled": 0, "errors": 0, "stuck": 0, "notes": 0}
        since = now - SINCE_DAYS * 86400
        last = _last()
        groups: dict[str, list[tuple[str, dict[str, Any]]]] = {}
        for key in _routing.projects():
            root = _anc.pilot_root(key)
            if not root:
                continue
            for n in _routing.read(key, since=since):
                if n.get("live") and n.get("pilot") and n.get("kind") in KINDS and not n.get("ruling") and last.get(n["id"], {}).get("status") not in ("steward", "ruled", "stuck"):     # "steward": a status written by the earlier rollback (a notice handed to a project session); old routing lines still carry it
                    groups.setdefault(root, []).append((key, n))
        if not groups:
            return out
        cx = _router.Context()
        cap = int(_router._num("max_notices", 25, 1))
        for root, rows in sorted(groups.items()):
            rows.sort(key=lambda r: float(r[1].get("ts", 0)))
            ready = [(k, n) for k, n in rows if last.get(n["id"], {}).get("status") == "delivered"]       # delivered, ruling to finish
            fresh = [(k, n) for k, n in rows if last.get(n["id"], {}).get("status") != "delivered"]
            batch = fresh[:cap]
            got, st = _judge(root, batch, cx, runner, since) if batch else ([], {"called": 0, "calls": 0, "retry": 0})
            lines = {x["id"]: x for x in got}
            for k, n in ready:
                p = last[n["id"]]
                lines[n["id"]] = {**p, "id": n["id"], "ruling": p.get("ruling", "passed"), "for_owner": _router.line_for_owner(p)}
            for key, n in [*ready, *batch]:
                ln = lines.get(n["id"])
                if ln is None:
                    continue
                prior = last.get(n["id"], {})
                res = _act(n, key, root, ln, cx, prior)
                _log(res)
                if res.get("stage") == "rule" and int(prior.get("rule_tries", 0)) + 1 >= MAX_TRIES:     # the ruling could not be written three times: stuck, never judged again
                    _log({**{k: res[k] for k in ("id", "project", "key", "kind", "ruling", "target", "label", "text") if k in res}, "ts": time.time(),
                          "status": "stuck", "reason": f"could not be ruled: the ruling could not be written to the routing log {MAX_TRIES} times ({res.get('error', '')[:120]})",
                          "error": res.get("error", "")})
                    out["stuck"] += 1
                out["notes"] += bool(res.get("noted"))
                out["errors"] += res["status"] == "error"
                out["ruled"] += res["status"] == "ruled"
                out["passed"] += res["status"] == "ruled" and res["ruling"] == "passed"
                out["fallback"] += ln.get("source") == "fallback"
                out["coded"] += ln.get("source") == "code"
            out["called"] += st["called"]; out["calls"] += st["calls"]; out["retry"] += st["retry"]
        return out


def loop() -> None:
    """The server's thread: a tick every [router] live_tick_seconds (read each pass: a reload applies it), then the day's digest. Its own
    thread (a call takes minutes). Never dies."""
    last = 0.0
    while True:
        time.sleep(5)
        try:
            if time.time() - last >= tick_s():
                last = time.time()
                tick()
                digest_tick()
        except Exception as e:  # noqa: BLE001
            print(f"router live tick failed: {type(e).__name__}: {e}", file=sys.stderr, flush=True)


# ----------------------------------------------------------------------------- the daily digest of held notices
def digest_path() -> Path:
    return _dir() / "digest.json"


def _read_digest() -> dict[str, Any]:
    """{"days": {"<root>|main", "<root>|quiet" or "<root>|pagepass": the date it was done}, "tries": {group: "<date>:<pushes>"}, "sent": {notice id: when it was
    digested}, "last": {root: when its last digest went out}}."""
    try:
        d = json.loads(digest_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    d = d if isinstance(d, dict) else {}
    return {k: (d.get(k) if isinstance(d.get(k), dict) else {}) for k in ("days", "tries", "sent", "last")}


def _write_digest(st: dict[str, Any], now: float) -> None:
    st["sent"] = {i: t for i, t in st["sent"].items() if float(t) >= now - 30 * 86400}
    p = digest_path(); p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, sort_keys=True), encoding="utf-8")
    tmp.replace(p)


def _digest_items(root: str, now: float, last: dict[str, dict[str, Any]], st: dict[str, Any]) -> tuple[list[tuple[dict[str, Any], dict[str, Any]]], ...]:
    """What the next digest of this project lists → (the "main" group: held notices, logged only, and the ones the router could not rule,
    delivered; quiet-hour holds for the QUIET agent; page-pass holds, logged only), each a list of (the
    router's live.jsonl line, the notice as the routing log reads it), oldest first: the notices the router ruled `held` (and nobody has
    overruled since) and the ones it could not rule (status "stuck", still unruled), that no digest has listed, from the last SINCE_DAYS."""
    rows: list[tuple[dict[str, Any], dict[str, Any]]] = []
    notices: dict[str, dict[str, dict[str, Any]]] = {}
    for i, ln in last.items():
        status = ln.get("status")
        if ln.get("project") != root or i in st["sent"] or float(ln.get("ts", 0)) < now - SINCE_DAYS * 86400:
            continue
        if ln.get("held_for"):          # held for a background agent's next turn (held.py), which hands it over: the digest would send it twice
            continue
        if not ((status == "ruled" and ln.get("ruling") == "held") or status == "stuck"):
            continue
        key = str(ln.get("key") or root)
        if key not in notices:
            notices[key] = {x["id"]: x for x in _routing.read(key)}
        n = notices[key].get(i)
        if n is None or (status == "ruled" and not (n.get("ruling") == "held" and n.get("ruled_by") == BY)) or (status == "stuck" and n.get("ruling")):
            continue
        rows.append((ln, n))
    rows.sort(key=lambda r: float(r[0].get("ts", 0)))
    quiet = [r for r in rows if root in _router.quiet_map() and r[0].get("status") == "ruled" and r[0].get("rule") == "quiet"]
    pagepass = [r for r in rows if r[0].get("status") == "ruled" and r[0].get("rule") == "page-pass"]
    return [r for r in rows if r not in quiet and r not in pagepass], quiet, pagepass


def _when(ts: float) -> str:
    d = dt.datetime.fromtimestamp(float(ts), _cfg.tz())
    sfx = "th" if 11 <= d.day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(d.day % 10, "th")
    return f"{d:%a %b} {d.day}{sfx} {d:%H:%M}"


def digest_text(root: str, rows: list[tuple[dict[str, Any], dict[str, Any]]], group: str, mark: bool) -> str:
    """The digest message: a line per notice (id, label, sender, gist, reason), then what is owed (nothing; a notice that could not be ruled
    is the router's, listed so a person sees it)."""
    held = [r for r in rows if r[0].get("status") != "stuck"]
    stuck = [r for r in rows if r[0].get("status") == "stuck"]
    parts = []
    if held:
        parts.append(f"{len(held)} notice{'s were' if len(held) != 1 else ' was'} held " + {"quiet": "through the quiet hour", "pagepass": "for the page pass"}.get(group, "by the router and not passed to any agent"))
    if stuck:
        parts.append(f"{len(stuck)} could not be ruled")
    head = (f"{_owner_mark()} " if mark else "") + f"[stackshot] router digest for {root}: " + " and ".join(parts) + " since the last digest."
    lines = [head]
    for ln, n in rows[:DIGEST_SHOWN]:
        label = _router._clean(n.get("label") or ln.get("label"), 60) or "-"
        who = _router._clean(n.get("who"), 40) or "-"
        gist = _router._clean(n.get("text") or ln.get("text"), 140)
        why = _router._clean(ln.get("reason") or n.get("reason"), 140)
        tag = "COULD NOT BE RULED · " if ln.get("status") == "stuck" else ""
        lines.append(f"- {n['id']} · {tag}{label} · from {who} · {_when(n.get('ts', 0))} · \"{gist}\"" + (f" — {why}" if why else ""))
    if len(rows) > DIGEST_SHOWN:
        lines.append(f"- and {len(rows) - DIGEST_SHOWN} more (the project's routing page lists them)")
    lines.append("The router ruled these held; nothing is owed on a held one." if held and not stuck else
                 "A held notice is the router's ruling and owes nothing; one that could not be ruled is in the routing log with no ruling.")
    return "\n".join(lines)


def digest_tick(now: float | None = None) -> dict[str, int]:
    """The day's digest of each live project, from [router] digest_hour on (a server that was down then sends it when it is back the
    same day) → {"sent", "empty", "failed", "logged"}. A project is done once a day per group (main, pagepass, and for router.QUIET's project
    quiet). A "main" or "pagepass" group of held rows only is logged, not delivered; one with a notice that could not be ruled is delivered
    (main: to the builder unmarked, else to -main marked). An empty list sends nothing. The notices listed are marked digested only when the push went through; a push
    that failed is tried again at the next ticks, DIGEST_TRIES times in the day, and then waits for the next day. Never raises."""
    out = {"sent": 0, "empty": 0, "failed": 0, "logged": 0}
    try:
        now = time.time() if now is None else now
        local = dt.datetime.fromtimestamp(now, _cfg.tz())
        if local.hour < digest_hour():
            return out
        day = local.date().isoformat()
        with _LOCK:
            st = _read_digest(); before = json.dumps(st, sort_keys=True)
            last = _last()
            roots = sorted({r for k in _routing.projects() for r in [_anc.pilot_root(k)] if r})
            cx = None
            for root in roots:
                main_rows, quiet_rows, page_rows = _digest_items(root, now, last, st)
                for group, rows in (("main", main_rows), ("quiet", quiet_rows), ("pagepass", page_rows)):
                    gk = f"{root}|{group}"
                    if (group == "quiet" and root not in _router.quiet_map()) or st["days"].get(gk) == day:
                        continue
                    if not rows:
                        st["days"][gk] = day
                        out["empty"] += 1
                        continue
                    if group in ("main", "pagepass") and not any(l.get("status") == "stuck" for l, _n in rows):
                        # held notices are the router's own ruling and owe nothing (the owner's are in stackshot's For you list, not in a front
                        # agent's turn), so the digest wakes nobody: it goes to the log, and its notices count as digested (none is listed
                        # twice). A digest with a notice that could not be ruled is delivered (below).
                        _log({"kind": "digest_logged", "ts": time.time(), "project": root, "group": group, "count": len(rows), "status": "logged",
                              "ids": [n["id"] for _l, n in rows], "text": digest_text(root, rows, group, False)})
                        for _l, n in rows:
                            st["sent"][n["id"]] = now
                        if group == "main":
                            st["last"][root] = now           # the project's digest was done today (status shows its time)
                        st["days"][gk] = day
                        out["logged"] += 1
                        continue
                    cx = cx or _router.Context()
                    aroot = agent_root(root, cx.reg)
                    if group == "quiet":
                        target = cx.agent_of(_router.quiet_map()[root], aroot) or _router.quiet_map()[root]
                        mark = _is_front(target, aroot, cx)
                    elif group == "pagepass":
                        target = cx.builder(aroot) or cx.main_agent(aroot)       # page work: the builder, else -main; never marked, even for a front agent
                        mark = False
                    else:
                        # a notice the router could not rule is stackshot's own problem: to the project's builder, unmarked; a project with no
                        # builder takes it to its -main agent, marked, since someone must see it
                        target = cx.builder(aroot)
                        mark = False
                        if not target:
                            target = cx.main_agent(aroot)
                            mark = bool(target)
                    res = _deliver(target, digest_text(root, rows, group, mark)) if target else "no target"
                    ok = _ok(res)
                    _log({"kind": "digest", "ts": time.time(), "project": root, "group": group, "count": len(rows), "target": target, "marked": mark if ok else False,
                          "outcome": res, "status": "sent" if ok else "error", "ids": [n["id"] for _l, n in rows], **({} if ok else {"error": f"the digest to {target or 'nobody'} was not delivered: {res}"})})
                    if ok:
                        for _l, n in rows:
                            st["sent"][n["id"]] = now
                        st["last"][root] = now
                        st["days"][gk] = day
                        out["sent"] += 1
                    else:
                        d0, _, c0 = str(st["tries"].get(gk, "")).partition(":")
                        c = (int(c0) if d0 == day and c0.isdigit() else 0) + 1
                        st["tries"][gk] = f"{day}:{c}"
                        if c >= DIGEST_TRIES:
                            st["days"][gk] = day
                        out["failed"] += 1
            if json.dumps(st, sort_keys=True) != before:
                _write_digest(st, now)
    except Exception as e:  # noqa: BLE001
        print(f"router live digest failed: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
    return out


# ----------------------------------------------------------------------------- status
def status(now: float | None = None) -> list[dict[str, Any]]:
    """One row per top-level page: the notices acted on in the last hour, the notices held since the last digest and when
    that digest went out (0 = none yet), the last error (text, when)."""
    now = time.time() if now is None else now
    rows = []
    lines = _router._read(live_path())
    calls = _router._read(_router.calls_path())
    last, st = _last(), _read_digest()
    for root in _anc.pilot_roots():
        mine = [d for d in lines if d.get("project") == root]
        acted = sum(1 for d in mine if d.get("status") in ("ruled", "steward") and float(d.get("ts", 0)) >= now - 3600)
        errs = [(float(d.get("ts", 0)), str(d.get("error") or d.get("note_error") or "")) for d in mine if d.get("status") == "error" or d.get("error") or d.get("note_error")]
        errs += [(float(c.get("ts", 0)), f"call {c.get('status')}: {c.get('note')}") for c in calls if c.get("project") == root and c.get("status") not in ("ok", None)]
        err = max(errs) if errs else (0.0, "")
        held_rows = _digest_items(root, now, last, st)
        rows.append({"project": root, "acted_last_hour": acted, "held_since_digest": sum(len(g) for g in held_rows),
                     "last_digest_at": float(st["last"].get(root, 0)), "last_error": err[1], "last_error_at": err[0]})
    return rows


def render(rows: list[dict[str, Any]]) -> str:
    fmt = lambda ts: dt.datetime.fromtimestamp(ts, _cfg.tz()).strftime("%Y-%m-%d %H:%M")
    out = ["router: rules every project",
           f"{'project':34} {'1h':>4} {'held':>5}  {'last digest':16}  last error"]
    for r in rows:
        when = fmt(r["last_error_at"]) if r["last_error_at"] else ""
        out.append(f"{r['project'][:34]:34} {r['acted_last_hour']:>4} {r['held_since_digest']:>5}  {fmt(r['last_digest_at']) if r['last_digest_at'] else '-':16}  "
                   + (f"{when} {r['last_error'][:120]}" if r["last_error"] else "-"))
    return "\n".join(out)


if __name__ == "__main__":
    if sys.argv[1:2] != ["status"]:
        sys.exit("usage: router_live.py status [--json]   (set STACKSHOT_CONFIG to the instance's file)")
    res = status()
    print(json.dumps(res, ensure_ascii=False, indent=1) if "--json" in sys.argv else render(res))
