"""router_live.py — the router that rules stackshot's notices (design: the design doc).

The router rules every project.
There is no list of projects and no switch: every page of the registry is the router's, and the way back is a revert of the code.

  [router] live_tick_seconds  how often the live tick looks (default 60)
  [router] general_<scope>  the general -main agent of each scope (a scope of [project_scopes] order) that a page with no agent of its own falls to (see STAND-IN); none by default
  [[router.watch]] / [[router.quiet]]  the standing rulings (an anchor to an agent; a project whose agent is archived for the digest); none by default
Both are read at each use, so a reload applies them. The keys [router] live and live_projects of the earlier form are ignored if present.

HOLD. A notice for a project is not delivered to the session the page names (a name that no running session carries). The place that would have delivered it (anchor-hub's
send, the server's message to a project, the board relay, the wake pass) calls holds(project, recipient); when it says yes the
notice is recorded in the routing log as usual but with `"live": true` and no recipient (routing.record(live=True)), the text
the session would have read is kept in <state>/router/held/<id>.json (stash), and nothing is pushed.

ACT. tick() (a thread of the server, loop()) takes the unruled live-held notices of each live project and judges them with
router.py's own code: its rules in code (code_rule, among them the read-first gate: machine news archived by rule, a person's message passed where router.person_place says, a trivial
one read and recorded), then one thin call per project (call_project). One event on an anchor several pages hold is ruled once (_twin_plan: the page it is about is ruled, the others follow, rule one-ruling).
A notice whose call failed or was left out stays held, undelivered, for one more try at the next tick (router.py's attempts file); the second failure is a pass to the -main agent (fallback_line).
A person's message (router.person_notice) is never archived, dropped or merged, and is not tried twice: whatever the call or a rule would have done, it is held for the page's background agent
(router.person_hold_line, hold kind `person`) at once; a pass of one to a front agent is a held line for that agent's next turn (the front_fyi path, kind `person`: person_front in _act), never a turn, and is
delivered as before, marked, only when the held store cannot file it or the rule is a standing watch. Then it acts on each:
  passed   delivered to the target the way a pass is delivered (push.py, the pane inbox), then ruled with
           routing.rule(id, "passed", to=target, by="stackshot (router)"). The text opens with "[for <owner>]" only when the target
           is a front agent and the pass carries a real need of the person (_must_see: for a message a session wrote, only a named open item of his (one whose needs include a decision or whose step is his, or one he asked the agent to tell him about), written as a plain word; for any other notice the ruling's for_owner, his words, a hand-back, the mark or
           needs: decision in the text, a named item whose needs include a decision, an audit finding, the fallback pass): the mark means he must see it, and is never added to get a pass
           through. Any other pass to a front agent (_front_route) is an answer to the agent's own question (delivered unmarked while the person is in
           that conversation, else written onto the item it names or held), or goes to the project's background agent, unmarked, or, in a project with none, is held
           through the front gate for the agent's next turn. A gate that cannot file it leaves the pass delivered, marked. A delivery to a background agent is unmarked.
           A pass that would start the front agent's turn does so in two cases only (_front_turn_gate, service/front_turn.py): it needs him and he is talking with that agent now (telling.present_fronts), or he asked
           it, in his own words, to tell him about the notice's subject (the agent is in the `tell_him` of an open item the notice names). Otherwise it never reaches the front agent, not even held: it goes, unmarked, to the
           background agent that moves or works a named item, else it is ruled archived (a row of the digest). A pass to a background agent is not gated, nor is a configured watch (his standing ask); a hand-back, a fallback pass to -main and an
           audit batch finding to a front mover are gated like the rest (the finding never needs him: only his ask warrants it). A wake for a front mover of an item that waits on his decision needs him (case 1).
           A batch finding of the audit (router.py's rule `audit-owners`) carries a `split`: one message per owner, each with the lines of its own
           items, marked as a pass to that agent is marked (_act_split); `to` in the routing log lists every owner, one still holding lines from before an earlier change named
           "(held)". A finding is a task for its mover: a BACKGROUND owner is woken with its lines at once, whole, like any pass (they had been held for its
           next turn as "asked nothing of you", then as one line cut to 260 characters, which left the findings out).
  dropped / merged / archived   routing.rule only; nothing is delivered (an archived notice is the page pass's).
A notice that cannot be judged twice (or an exception) is passed to the -main agent, never dropped; with no -main agent anywhere (the
page, its hub and the scope's general agent list none) it is archived, with the reason. A delivery that fails is retried at the next ticks, three times, then
goes to the -main agent. Every action is a line in <state>/router/live.jsonl.

STAND-IN. stand_in(project) is where delivery goes where a page's name-line session used to be written to: the project's builder, a background agent whose
mandate says build, maintain, merge or engineer, else its -main agent. A page with no user-facing agent of its own falls to (1) its hub
page's agents (`hub:` line: agent_root), else (2) the general -main agent of its scope (anchors.general_main): the scope's
[router] general_<scope> (an agent name, or a page key whose -main agent is used; a page that lists no front agent but has a `display-name:` line gives its name-line session), else the default scope's. Router.Context.agents gives such a page that one agent, nobody else of the general page.
A page's `display-name:` line is only its name now: it decides nothing.

DIGEST. The router archives what no agent should be interrupted for (the page pass, a page's quiet hours, machine news, a bare laugh or ack, an image it could not read; never a
person's message the call is unsure of: that is held for the page's background agent), so an archived notice reaches nobody at once. An archived notice owes nothing, and what is for the owner lives in
stackshot's For you list, not in a front agent's turn. digest_tick() (the same thread as the live tick) therefore does not deliver a
digest of archived notices: once a day per live project, from [router] digest_hour on (default 9, the instance timezone; a server down at
that hour does it when it is back the same day), it writes one entry listing every notice ruled `archived` since the last digest, each as id,
label, sender, gist and reason, to live.jsonl as kind "digest_logged" (with its text), and the notices count as digested (none is listed
twice). Nothing is pushed to any agent. The page-pass holds (the code rule `page-pass`: the page sheets of the jobs [router] page_senders
names) are their own group, logged the same way under the head "archived for the page pass". A notice the router could not rule (CAP below)
is stackshot's own problem, so a digest with one is delivered: to the project's builder, unmarked, listing every row of the group; a
project with no builder takes it to its -main agent with "[for <owner>]" on line 1, since someone must see it. The quiet-hour holds of
the instance's [[router.quiet]] rows (router.quiet_map) go in the same pass to that agent, unmarked when it is a background
agent. Each group has its own day mark and tries. <state>/router/digest.json records the day each group was done, the notices already
digested (so none is sent twice) and the time of each project's last delivered digest. The routing log keeps the archived ruling as it is (a record
written before the rename says `held`: routing.ruling_of reads it as archived, the digest too), and
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
ruling; a message a session wrote counts only by naming an open item of his, and his own message is his words), or goes to a front agent, is passed as before, except an fyi and a page-owed notice for a front agent: they go through the front gate and are held for its next turn
(_front_fyi, _front_page_owed; the router rules them `held` too), and a pass to a front agent with no need of the person (_front_route, above). [router] hold_notices = false turns the hold off.

CAP. A ruling that cannot be written to the routing log (routing.rule raised) is tried again at the next ticks, three times in all.
After that the notice is logged with status "stuck", never judged again, and listed in the next digest as "could not be ruled".

`stackshot router-live status` prints a line per project: the notices acted on in the last hour; the notices archived
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
SINCE_DAYS = 7                      # an archived notice older than this is not taken up
MAX_TRIES = 3                       # delivery attempts to the target; then the -main agent. Also the writes of a ruling to the routing log; then "stuck"
NOTE_MAX = 300                      # characters in a ruling's `note`
DIGEST_SHOWN = 25                   # a digest lists this many notices, one line each, and counts the rest
DIGEST_TRIES = 3                    # pushes of one digest in a day; then its notices wait for the next day's
_LOCK = threading.Lock()

# What the server wires in (configure): the front-agent test (telling.front_keeper), the push, the call made after a ruling
# (the release of a hold that waited on the notice's anchor, the board's republish), and the front gate for an fyi or a page-owed notice (telling.front_fyi). The defaults stand alone, for the tests and the CLI.
_HOOKS: dict[str, Any] = {"is_front": None, "deliver": None, "after_rule": None, "front_fyi": None, "front_answer": None, "front_turn": None, "his_items": None, "want_background": None, "front_words": None}      # his_items: service/front_turn.his_items, which of the named items are open ones of his; front_answer: messaging.router_answer, what becomes of an answer to a front agent's own question; front_turn: service/front_turn.warranted, whether a notice may start a turn of a front agent; want_background: service/background_want.want_background, the record that a project with no background agent could use one; front_words: service/sibling_words.held_words, whether a sibling front agent's message quotes his words


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
    """[router] digest_hour: the hour (0 to 23, the instance timezone) from which the day's digest of archived notices may go (default 9)."""
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
        return any(w and _same_session(session, w, nm) for w in want)
    except Exception:  # noqa: BLE001
        return False


def _same_session(a: str, b: str, nm: dict[str, str]) -> bool:
    """Do two references (a route's session, a page's notice address) name one session? One canonical form each (anchors.canonical); and, when they differ, the name each stands for now (anchors.display).
    A route names its session by its permanent id, and the registry that resolves a name to it can read empty for a moment (the copy of it being replaced, a torn read): the page's name then falls
    to the old rule, a transcript id, and the id and the transcript id differ though they are one session. The registry keeps the name of every id it has read (sessions_registry.display_name), so the id still reads as its name."""
    if _anc.canonical(a, nm) == _anc.canonical(b, nm):
        return True
    da, db = _anc.display(a, nm), _anc.display(b, nm)
    return bool(da) and da == db


def _agents_of(project: str, reg: dict[str, dict[str, Any]], roots: list[str] | None = None) -> tuple[dict[str, str], dict[str, str]]:
    """(front, back) agents of the page whose agents serve this project (agent_root), {name: mandate} each. `roots`: anchors.pilot_root's argument (given, the registry file is not read)."""
    root = agent_root(_anc.pilot_root(project, roots) or "/".join(str(project or "").strip("/").split("/")[:2]), reg)     # a key the registry file does not hold yet reads from its top-level page
    page = reg.get(root) or {}
    agents = {str(k): str(v) for k, v in (page.get("agents") or {}).items()}
    back = {k: agents[k] for k in (page.get("back_agents") or {}) if k in agents}
    off = _anc.surface_agents(page)                                      # an agent that is not a sala session is no recipient of a notice: neither front nor back here
    return {k: v for k, v in agents.items() if k not in back and k not in off}, back


def builder(project: str, reg: dict[str, dict[str, Any]] | None = None) -> str:
    """The builder of a live project: the first background agent whose mandate line says build (first choice), maintain, merge or
    engineer; "" for a project that is not live and when there is none. As router.Context.builder."""
    try:
        if not is_live(project):
            return ""
        return _builder_in(project, _anc.registry() if reg is None else reg)
    except Exception:  # noqa: BLE001
        return ""


def _builder_in(project: str, reg: dict[str, dict[str, Any]], roots: list[str] | None = None) -> str:
    """builder(), read from `reg` alone: no live-page test, no registry file."""
    _front, back = _agents_of(project, reg, roots)
    hits = [(0 if re.search(r"\bbuild", m, re.I) else 1, i, k) for i, (k, m) in enumerate(back.items()) if _router._BUILDER.search(m)]
    return min(hits)[2] if hits else ""


def marked_in(project: str, reg: dict[str, dict[str, Any]], roots: list[str] | None = None) -> str:
    """The agent the project marks as its keeper ("" with no mark): the mark of the page whose agents serve the project (agent_root: its top-level page, or the hub that page falls to). A mark names an
    agent of its own page's map, so a project that has one lists agents."""
    root = _anc.pilot_root(project, roots) or "/".join(str(project or "").strip("/").split("/")[:2])
    return _anc.marked_for(root, reg)


def stand_in_of(project: str, reg: dict[str, dict[str, Any]]) -> str:
    """stand_in(), read from `reg` alone: the project's marked keeper, else its builder, else its -main agent (anchors.fallback_main). The same steps in the same order; only the live-page test and the registry file are left
    out, so a registry being built (pages.cmd_registry), or being read through the project record (project_registry.apply, which the registry file's own reader calls), can ask before the file
    holds the page. "" when no session can be named."""
    try:
        roots = ["/".join(str(project or "").strip("/").split("/")[:2])]
        return marked_in(project, reg, roots) or _builder_in(project, reg, roots) or _anc.fallback_main(project, reg, roots)
    except Exception:  # noqa: BLE001
        return ""


def stand_in(project: str, reg: dict[str, dict[str, Any]] | None = None) -> str:
    """The project's STAND-IN, the agent the router's passes go to for it: the agent its page marks as its keeper (keeper.py), else its builder (builder()), else its -main agent (its own page's, else
    its hub's, else the scope's general one: anchors.fallback_main). "" for a key that names no page, and when no session can be named. The
    page's name line decides nothing here; a one-session page's items keep their keeper (telling.project_keeper), not this agent."""
    try:
        reg = _anc.registry() if reg is None else reg
        if not is_live(project):
            return ""
        m = marked_in(project, reg)
        if m:
            return m
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


def _front_anywhere(who: str, root: str, cx: "_router.Context") -> bool:
    """Is `who` a front agent of this project or of any other (the message tool reads its sender's role the same way)?"""
    if _is_front(who, root, cx):
        return True
    try:
        return _anc.session_roles(cx.reg).get(who, {}).get("role") == "front"
    except Exception:  # noqa: BLE001
        return False


def _person_words(n: dict[str, Any], ln: dict[str, Any], body: str) -> bool:
    """Does this notice carry the person's words or mark: a ruling for him, his words, a hand-back, a strong mention in the text?"""
    return bool(_router.line_for_owner(ln) or n.get("words") or n.get("handback") or _router.strong_owner(body) or _router.strong_owner(n.get("text")))


def _front_fyi(n: dict[str, Any], ln: dict[str, Any], target: str, root: str, cx: "_router.Context") -> tuple[str, str]:
    """A pass of an fyi (the sender's word that it asks nothing) to a FRONT agent goes through the front gate, as a notice about an item does: -> ("fyi", "") held for the agent's next turn,
    ("held", why) held because its hook cannot fetch held lines (nobody is told), ("", "") delivered as before (not an fyi, a notice with the person's words or mark, a ruling for him, an audit finding,
    a recipient that is no front agent, the switch off). A pass to a background agent is _hold_kind's. Never raises."""
    try:
        fn = _HOOKS["front_fyi"]
        if not fn or str(n.get("hold") or "") != "fyi" or not target or ln.get("rule") == "audit-owners" or not _held.enabled():
            return "", ""
        body = _body(n)
        if _person_words(n, ln, body) or _held._owner_mark().search(body) or not _is_front(target, root, cx):
            return "", ""
        return fn(target, _held_text(n, body), str(ln.get("item") or ""), n["id"], False, whole=True) or ("", "")      # log=False: the router's own ruling is the routing-log line; whole: a session's message keeps its words and line breaks
    except Exception:  # noqa: BLE001
        return "", ""


def _page_owed_line(n: dict[str, Any], body: str, project: str) -> str:
    """The held line of a page-owed notice for a front agent: the page, the item, what changed and who changed it, then the notice's own closing words (what is owed, and by whom), which give way last:
    the long parts go first (the subject cut to fit, then the link, then the subject). The closing words are the last " — " part of its stashed text; with the stash gone, words that are true of the
    notice stand in: the writer owes the page update, and the notice is for the anchors scoped to the item."""
    parts = str(n.get("label") or "").split()
    ref, who = (parts[-1] if parts else ""), str(n.get("who") or "") or "a session"
    what, _, subject = " ".join(str(n.get("text") or "").split()).partition(": ")
    url = str(n.get("url") or "")
    tail = body.rsplit(" — ", 1)[1].strip() if body.startswith("[board]") and " — " in body else ""
    tail = _held.one_line(tail or f"the writer owes the page update; this notice is for the anchors scoped to {ref or 'the item'}", 140)

    def build(subj: str, link: str) -> str:
        return f"[board] {ref + ' ' if ref else ''}{what} by {who}" + (f" — {subj}" if subj else "") + f" ({project})" + (f" → {link}" if link else "") + f" — {tail}"

    def cut(link: str) -> str:
        room = _held.LINE_MAX - len(build("", link)) - 3
        return build(subject[:room - 1].rstrip() + "…", link) if subject and room >= 12 else ""
    for line in (build(subject, url), cut(url), build("", url), cut(""), build("", "")):
        if line and len(line) <= _held.LINE_MAX:
            return line
    return _held.one_line(build("", ""))


def _front_page_owed(n: dict[str, Any], ln: dict[str, Any], target: str, root: str, project: str, cx: "_router.Context") -> tuple[str, str]:
    """A pass of a page-owed notice (the code's `hold` kind `page-owed`: it asks nothing of the person) to a FRONT agent goes through the same front gate as an fyi does -> ("fyi", "") held for the agent's
    next turn (it starts none), ("", "") delivered as before: not a page-owed notice, a notice with the person's words or mark, a ruling for him, an audit finding, a hand-back, a recipient that is no front
    agent, the switch off, no gate wired, a gate that declined or failed, or a hook that cannot fetch held lines (an owed page is not dropped for want of a place to hold it). Never raises."""
    try:
        fn = _HOOKS["front_fyi"]
        if not fn or str(n.get("hold") or "") != "page-owed" or not target or ln.get("rule") == "audit-owners" or not _held.enabled():
            return "", ""
        body = _body(n)
        if _person_words(n, ln, body) or _held._owner_mark().search(body) or not _is_front(target, root, cx):
            return "", ""
        verdict, _why = fn(target, _page_owed_line(n, body, project), "", n["id"], False, kind="page-owed") or ("", "")      # no item is named: the owed list is the board's record of it; log=False: the router's own ruling is the routing-log line
        return ("fyi", "") if verdict == "fyi" else ("", "")
    except Exception:  # noqa: BLE001
        return "", ""


_ITEM_URL = re.compile(r"/items/(?:board-tmp-[\w-]+-)?([A-Za-z]?\d+)\b")
_ITEM_BARE = re.compile(r"(?<![\w#/&.:@-])#(\d+)\b")
_ITEM_OLD = re.compile(r"(?<![\w#/\\.:@-])([A-Za-z]\d+)(?![\w\-/\\]|\.\w)")


def _item_refs_loose(text: str) -> set[str]:
    """Every way a notice's text can name an item, as the board index spells it: the id forms the router reads (a board id, a letter id), an item page link, a bare #<number> and a capital-letter id.
    More than the tool's own reading on purpose: a name that is no item (a pull request's number) only keeps a pass marked, which is the safe side."""
    out = set(_router._TOKEN.findall(text))
    out.update(f"board#{d}" if d.isdigit() else d.lower() for d in _ITEM_URL.findall(text))
    out.update(f"board#{d}" for d in _ITEM_BARE.findall(text))
    out.update(x.lower() for x in _ITEM_OLD.findall(text))
    return out


def _item_refs_plain(text: str) -> set[str]:
    """The items a session's message names as the message tool reads them (`model/ids`: an id written as a plain word, never one in code or quotes, never a bare #<number>, never a merge queue's group number), as
    the board index spells them: the id as written and the store's id for it. No more forms than the tool's own reader (`service/agent_names._item_refs`), so a pull request's `#14` in prose names no item."""
    from stackshot.model import ids as _ids
    out: set[str] = set()
    for m in _ids._ITEM_REF.finditer(_ids._without_mq_groups(_ids._plain_text(text))):
        ref = m.group(1) or m.group(2) or ""
        if m.group(2) and ref.isdigit():
            ref = f"board#{ref}"
        out.add(ref.lower())
        try:
            out.add(_ids._norm_id(ref))
        except Exception:  # noqa: BLE001      # an id that names no item form: only the form as written is looked up
            pass
    return out


def _named_items(n: dict[str, Any], ln: dict[str, Any], body: str, cx: "_router.Context", plain: bool = False) -> list[dict[str, Any]]:
    """The board items a notice names (the ruling's `item`, the notice's label, an id, a link or a bare number in its text), each once. `plain`: only the forms the message tool reads (_item_refs_plain), for a message a
    session wrote. [] when it names none or the board cannot be read."""
    try:
        read = _item_refs_plain if plain else _item_refs_loose
        ruled = "" if plain else str(ln.get("item") or "").strip()      # the ruling's `item` reads an id in backticks and in quotes too (router.py _TOKEN): for a session's message only the plain reading counts, which names the same id
        refs = {ruled, *read(body), *read(str(n.get("label") or ""))} - {""}
        out: dict[str, dict[str, Any]] = {}
        for r in sorted(refs):
            t = cx.index.get(r)
            if t is not None:
                out.setdefault(str(t.get("gid") or r), t)
        return list(out.values())
    except Exception:  # noqa: BLE001
        return []


def _item_waits_decision(n: dict[str, Any], ln: dict[str, Any], body: str, cx: "_router.Context") -> bool:
    """Does an item the notice names (_named_items) wait on a decision of the person (its needs include `decision`)? False when it names none or the board cannot be read."""
    return any(_router.waits_decision(t) for t in _named_items(n, ln, body, cx))


def _item_is_his(n: dict[str, Any], ln: dict[str, Any], body: str, cx: "_router.Context", target: str = "") -> bool:
    """Does a message a session wrote name (as plain words, _item_refs_plain) an open item that is his to act on: its needs include `decision`, or the model reads its step as his (service/front_turn.his_items, the
    `his_items` hook)? Or, when `target` is the front agent it is passed to, an item he asked that agent to tell him about (its `tell_him`, the `front_turn` hook): the message tool's own test of what a marked message names.
    False when it names none, the board cannot be read or no reader is wired: nothing is his on a guess."""
    try:
        ids = [str(t.get("gid") or "") for t in _named_items(n, ln, body, cx, True)]
        fn = _HOOKS["his_items"]
        return bool((fn and fn(ids)) or (target and ids and _front_warranted(target, ids)))
    except Exception:  # noqa: BLE001
        return False


_NO_TURN = "he is not talking with it now and has not asked it to tell him about this"


def _front_warranted(agent: str, ids: list[str], needs: bool = False) -> bool:
    """Did he ask the front agent `agent` to tell him about one of the items `ids` (case 2; a finding never needs him, so case 1 does not apply), or, with `needs`, is he talking with it now (case 1)? False on any failure: nothing is delivered on a guess."""
    try:
        return bool(_HOOKS["front_turn"](agent, [str(i) for i in ids], needs))
    except Exception:  # noqa: BLE001
        return False


def _builder_of(items: list[dict[str, Any]], cx: "_router.Context", sender: str = "") -> str:
    """The background agent whose work a notice is about: the one that moves a named item, else the one its needs or its first next line name (router.item_worker); "" when no named item is a background agent's.
    Never the notice's own sender: a notice is not handed back to the session that wrote it (the message tool's `_builder_named` and `_front_route` leave the sender out the same way)."""
    def other(b: str) -> bool:
        return bool(b) and b.casefold() != str(sender or "").casefold()
    for t in items:
        b = cx.background(_anc.mover_of(t) or "")
        if other(b):
            return b
    return next((w for w in (_router.item_worker(t, cx) for t in items) if other(w)), "")


def _front_turn_gate(n: dict[str, Any], ln: dict[str, Any], target: str, root: str, cx: "_router.Context", needs: bool | None = None) -> tuple[str, str]:
    """A pass to a FRONT agent that would start a turn (marked, delivered) starts one only in the two cases the person's rule allows: it needs him and he is talking with that agent now, or he asked that agent to tell
    him about the notice's subject (an item it names; service/front_turn.py, the `front_turn` hook). Otherwise it never reaches the front agent, not even held. -> ("", "") deliver (a case holds, no gate wired, a recipient that is
    no front agent, a configured watch: his own standing ask, case 2 recorded in the config); ("background", name) the notice is about a named item that background agent moves or works: it takes the pass, unmarked;
    ("archived", why) nobody is told: the ruling is archived, a row of the digest. `needs` overrides the test of whether the notice needs him (an audit finding never does: only his ask warrants a turn for it). Never raises. A failure of the test itself
    (an unreadable presence, an exception in the hook, the item lookup or the need test) fails closed: no turn is warranted, so nothing is delivered."""
    fn = _HOOKS["front_turn"]
    if not fn or not target:
        return "", ""
    items: list[dict[str, Any]] = []
    try:
        if not _is_front(target, root, cx) or ln.get("rule") == "watch":
            return "", ""
        body = _body(n)
        items = _named_items(n, ln, body, cx)
        if fn(target, [str(t.get("gid") or "") for t in items], (ln.get("rule") != "audit-owners" and _must_see(n, ln, body, cx)) if needs is None else needs):
            return "", ""
        back = _builder_of(items, cx, _sender_name(n))
    except Exception:  # noqa: BLE001      # fails closed, like a presence that cannot be read: no turn, nothing held, a row in the digest
        return "archived", "the test of whether he is with it or asked it failed, so no turn is warranted"
    return ("background", back) if back else ("archived", _NO_TURN)


def _sender_name(n: dict[str, Any]) -> str:
    """The session a notice came from, from its label (`name (id...)`; a script `x (a script on m)` is no session): "" for none."""
    who = str(n.get("who") or "").strip()
    return "" if "(a script on" in who else re.split(r" \(", who, maxsplit=1)[0].strip()


def _held_where(n: dict[str, Any]) -> str:
    """Where the words a cut held message left out are: the notice, which keeps its whole text (the closing note of a cut names it and its sender)."""
    return f"notice {n['id']}, from {_sender_name(n) or str(n.get('who') or 'a sender')}"


def _held_text(n: dict[str, Any], body: str) -> str:
    """The words a held pass of a session's message carries to the front gate: all of them, with their line breaks, while they fit held.WHOLE_MAX (the message tool's limit and the room for the label); above it the text
    is cut at a line or word boundary and closed with a note that says how many characters were left out and names the notice and its sender (the notice keeps the whole text)."""
    return _held.cut_whole(_held.keep_whole(body), _held.WHOLE_MAX, _held_where(n))


def _is_session_message(n: dict[str, Any], body: str) -> bool:
    """Is this notice a message a session wrote: a message notice that carries neither his words nor a hand-back, is not the server's own line about an item, not the audit's and not his own (his message counts as his
    words, as at the message tool's gate)? Only such a message needs him by naming an item of his."""
    if str(n.get("kind") or "") != "message" or n.get("words") or n.get("handback") or str(body or "").lstrip().startswith("[board]") or _router._is_owner_name(_sender_name(n)):
        return False
    return not (_cfg.is_audit_sender(n.get("who")) or _cfg.is_audit_sender(str(n.get("who") or "").split(" (")[0].strip()))


def _must_see(n: dict[str, Any], ln: dict[str, Any], body: str, cx: "_router.Context", target: str = "") -> bool:
    """Does a pass to a front agent carry a real need of the person, so that it stays marked and starts a turn? A message a session wrote needs him only when it names, as plain words, an open item of his (_item_is_his: its needs
    include a decision, or its step is his; with `target`, one he asked that agent to tell him about too): the model call's for_owner guess and a mark or `needs: decision` in its text are no source. Every other notice keeps
    its signals: the ruling's for_owner, his own words, a hand-back, the mark or needs: decision in the text (_person_words, the held rule's own mark test), a named item whose needs include a decision, and an audit batch
    finding (rule audit-owners: a task for the agent, its own path). Where the router has no signal the answer is no: a pass with none is not marked."""
    if ln.get("rule") == "audit-owners":
        return True
    if _is_session_message(n, body):
        return _item_is_his(n, ln, body, cx, target)
    return bool(_person_words(n, ln, body) or _held._owner_mark().search(body) or _item_waits_decision(n, ln, body, cx))


def _want_background(n: dict[str, Any], root: str, ln: dict[str, Any], cx: "_router.Context") -> None:
    """A message to a project whose page lists a front agent and no background agent is recorded as a want for one (service/background_want.py; the fleet tool may create the agent), whatever the router rules it: the one
    call is made by `_act` before any ruling is carried out, so a model call's or a rule's archived, merged or dropped, a hold, a pass to a front agent that needs the person and a pass the front gate archives all record it
    (the call checks that the project has no background agent), and the message takes the route it takes without it. Only a message a session wrote counts: a board or anchor notice, the server's own line about an item, an audit
    finding, any other line the audit sends, a front agent's word (a peer's, or its own project's) and the person's own message want none. Never raises."""
    try:
        fn = _HOOKS["want_background"]
        if not fn or not _cfg.background_agent_enabled():      # the switch first: off (the default) does no further work
            return
        if str(n.get("kind") or "") != "message" or str(n.get("text") or "").lstrip().startswith("[board]") or ln.get("rule") == "audit-owners":
            return
        if _cfg.is_audit_sender(n.get("who")) or _cfg.is_audit_sender(cx.name_of(str(n.get("who") or ""))):      # the audit's own line (its findings, its held notes, the filing passes'), the same test the message tool makes, on the label and on the session a bare id names
            return
        sender = _sender_name(n)
        if sender and (_front_anywhere(sender, root, cx) or _router._is_owner_name(sender)):      # a front agent's word (a peer's, or its own project's) is the channel between front agents, and the person's own message is no session's: neither calls for a background agent
            return
        fn(root, "message")
    except Exception:  # noqa: BLE001
        return


def _front_route(n: dict[str, Any], ln: dict[str, Any], target: str, root: str, cx: "_router.Context") -> tuple[str, str]:
    """What a pass to a FRONT agent with no need of the person becomes (_must_see is false; an fyi and a page-owed notice have their own paths above). -> ("", "") as before: marked, delivered (a need, no gate
    wired, the switch off, a recipient that is no front agent); ("deliver", "") an answer to a question of the agent's while the person is in that conversation (a message notice from a session the agent itself wrote to: the
    answer hook): delivered to the agent, unmarked; ("items", reply) such an answer while he is not: written onto the item it names, nothing delivered; ("background", name) the project's background agent (its builder,
    else the first listed) takes it, unmarked; ("archived", why) a project with no background agent: nobody is told, the ruling is archived (a row of the digest), nothing is held; ("hold", why) held for the agent's next turn
    through the front gate: only what is one agent's word to another (an answer outside the conversation that names no item, a peer front agent's message, the background agent's own word, a sibling front agent's marked message that quotes his words while no turn is warranted: when one is, it is delivered as a turn, `_front_turn_gate`'s own test), which starts no turn. Never raises."""
    try:
        if not _HOOKS["front_fyi"] or not target or not _held.enabled() or not _is_front(target, root, cx):
            return "", ""
        if str(n.get("hold") or "") in ("fyi", "page-owed") or ln.get("rule") == "audit-owners":
            return "", ""
        body = _body(n)
        if _must_see(n, ln, body, cx, target):
            if (n.get("kind") == "message" and _HOOKS["front_words"] and _HOOKS["front_turn"] and (sib_ := _sender_name(n)) and sib_.casefold() != str(target).casefold()
                    and not _front_warranted(target, [str(t.get("gid") or "") for t in _named_items(n, ln, body, cx)], True) and _HOOKS["front_words"](target, sib_, body)):      # a sibling front agent's message that quotes his words (sibling_words), while no turn is warranted (he is not talking with the target, he did not ask it about the item: the test _front_turn_gate makes): held, not diverted; a warranted one is delivered as a turn, as before
                return "hold", f"{sib_} is a front agent of the project and quotes the owner's words, so its message to {target} rides {target}'s next turn"
            return "", ""
        fn = _HOOKS["front_answer"]
        if fn and n.get("kind") == "message":
            kind, arg = fn(target, str(n.get("who") or ""), body, n["id"]) or ("", "")
            if kind in ("deliver", "items", "hold"):
                return kind, arg
        sender = _sender_name(n)
        if sender and sender.casefold() != str(target).casefold() and _front_anywhere(sender, root, cx):      # a front agent's word to a peer front agent: the channel between them, held for that peer's next turn
            return "hold", f"{sender} is a front agent, so its message to {target} rides {target}'s next turn"
        back = _anc.background_agent(root, cx.reg)       # the one lookup the message tool uses too: the builder, else the first background agent, a hub's for a component page with none
        if back and sender and sender.casefold() == back.casefold():      # the background agent's own word to the front agent can never go back to it
            return "hold", f"{back} is the project's background agent, so it cannot go back to it"
        return ("background", back) if back else ("archived", "the project has no background agent")
    except Exception:  # noqa: BLE001
        return "", ""


def _hold_kind(n: dict[str, Any], ln: dict[str, Any], target: str, cx: "_router.Context") -> str:
    """The one decision of the router's hold: is this pass to `target` held for its next turn? -> the held kind, "" to deliver as
    before. Only a background agent holds; a notice with the owner's words, a hand-back or a ruling marked for the owner is delivered; anything unsure is
    delivered. Never raises."""
    try:
        if ln.get("rule") == "audit-owners":          # a finding is a task for its mover, never "asked nothing of you": it wakes a builder
            return ""
        kind = str(ln.get("hold") or n.get("hold") or "")      # the ruling's own (the read-first gate's `person`: a person's message nothing placed, held for the background agent) before the sender's
        if not kind or not target:
            return ""
        body = _body(n)
        to_owner = _person_words(n, ln, body)
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
def _aliased(d: dict[str, Any]) -> dict[str, Any]:
    """A live.jsonl line with its ruling as it reads now. An older line says `held` for a notice kept from everyone and for one told to no one too; only a line
    that names the agent it was filed for (`held_for`, which every filed hold carries) keeps `held`, and the reason text is not read."""
    if d.get("ruling") == "held" and not d.get("held_for"):
        d = {**d, "ruling": _routing.ARCHIVED}
    return d


def _last() -> dict[str, dict[str, Any]]:
    """The last live.jsonl line of each notice id, and (in `tries`) how many errors it has had, (in `rule_tries`) how many times writing
    its ruling to the routing log failed. A line with no id (a digest's) is no notice's."""
    out: dict[str, dict[str, Any]] = {}
    for d in _router._read(live_path()):
        i = str(d.get("id") or "")
        if not i:
            continue
        d = _aliased(d)
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
        d = _aliased(d)
        out["last"] = d
        if d.get("status") == "ruled":
            out["ruled"] = d
        elif d.get("status") == "stuck":
            out["stuck"] = d
    return out


# ----------------------------------------------------------------------------- the tick
def _fallback_or_hold(n: dict[str, Any], key: str, root: str, cx: "_router.Context", why: str) -> dict[str, Any] | None:
    """router.fallback_line for a notice the judging failed on, guarded: if the fallback itself raises (reading the notice failed again), a held line for the page's background agent built without reading the notice
    (hold kind `person`, never an archive); failing that None, and the notice is left unruled for the next tick. Never raises, so one notice can never stall the projects after it."""
    aroot = agent_root(root, cx.reg)
    try:
        return _router.fallback_line(n, key, aroot, cx, why)
    except Exception:  # noqa: BLE001
        pass
    try:
        back = cx.live_background(aroot)
        if back:
            return _router._line(n, key, aroot, source="fallback", rule="", ruling="passed", target=back, hold="person", person=True,
                                 reason=f"{why}: held for {back}, the page's background agent (the fallback itself failed)")
    except Exception:  # noqa: BLE001
        pass
    return None


def _nowhere(ln: dict[str, Any]) -> bool:
    """Is this the ruling of a person's message that has nobody to go to (a pass with no target: the page lists no live background agent and no front agent)? It is never made a line: `_act` would archive a pass with no target."""
    return bool(ln.get("person")) and ln.get("ruling") == "passed" and not str(ln.get("target") or "").strip()


def rehome_person(cx: "_router.Context") -> int:
    """A held `person` line of an agent that is gone now (retired after the line was held; a surface agent) is moved to the page's live background agent, else its contact front agent, so a person's message is
    never left on a session nobody reads. → how many lines moved. One page's agents at a time; never raises."""
    moved = 0
    try:
        for page in list(cx.reg):
            front, back = cx.agents(page)
            for nm in dict.fromkeys([*front, *back]):
                if not cx.gone(nm):
                    continue
                rows = [r for r in _held._read(_held._file(_held.key_of(nm))) if r.get("kind") == "person"]
                dest = cx.live_background(page) or cx.contact(page) if rows else ""
                if not dest or dest == nm:
                    continue
                for r in rows:
                    if _held.add(_held.key_of(dest), "person", str(r.get("text") or ""), sender=str(r.get("from") or ""), gid=str(r.get("gid") or ""), nid=str(r.get("nid") or ""), whole=True) and _held.ack(nm, ids=[str(r["id"])]):
                        moved += 1
    except Exception as e:  # noqa: BLE001
        print(f"router live: re-homing a gone agent's person lines failed: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
    return moved


def _judge(root: str, rows: list[tuple[str, dict[str, Any]]], cx: "_router.Context", runner: Any, since: float,
           offered: dict[str, list[str]] | None = None) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """The router's own ruling for each notice of the project's batch (router.py's rules in code, then its thin call): → (lines as the
    judging returns them, {"called": notices sent to a call, "calls": 0 or 1, "retry": notices left for one more try}). A notice
    whose call failed or was left out has no line on its first try: it stays held, undelivered, and is judged again at the next tick
    (router.py's attempts file); the second failure is the fallback line, a pass to -main. An
    exception anywhere passes every notice that has no line to the -main agent with the reason (no retry; a person's message is held for the page's background agent instead, router.fallback_line).
    `offered` = notice id → the other pages that hold its anchor (tick's twin plan), shown to the call."""
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
            got, rec = _router.call_project(agent_root(root, cx.reg), todo, cx, runner, attempts, offered)
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
        for key, n in rows:
            if n["id"] in have:
                continue
            ln = _fallback_or_hold(n, key, root, cx, f"the router failed on it ({type(e).__name__}: {str(e)[:100]})")
            if ln is None:
                stats["retry"] += 1      # not even a hold could be made: no line, so the notice stays unruled and the next tick judges it again
            else:
                lines.append(ln)
    placed = [x for x in lines if not _nowhere(x)]
    stats["retry"] += len(lines) - len(placed)      # a person's message with nobody to hold it for (no live background agent, no front agent): no line, so it stays unruled and the next tick judges it again, never archived
    return placed, stats


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
        if mark and _HOOKS["front_turn"] and not _front_warranted(dest, ids):      # a finding is a task, not a need of his: a front mover hears it only when he asked it to tell him about the item; else its lines are archived, never held
            sent[agent] = f"{dest}: archived"
            continue
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
    told = [a for a in split if not sent[a].endswith((": held", ": archived"))]
    try:
        if not told and any(v.endswith(": archived") for v in sent.values()):      # nobody was told: every recipient is a front agent he did not ask about these items
            why = f"archived: front mover{'s' if len(split) != 1 else ''} {', '.join(split)}, he has not asked it to tell him about these items (not delivered, not held)"
            base.update(ruling="archived", reason=why, target="", marked=False)
            _project, ruled = _routing.rule(n["id"], "archived", reason=why, by=BY)
        elif not told:        # every keeper's lines were held by an earlier try (before an earlier change)
            base.update(ruling="held", reason=_held.reason("audit"), target="", held_for=", ".join(split), hold="audit")      # held_for: the digest leaves it out (it is waiting for the agents, not for a digest)
            _project, ruled = _routing.rule(n["id"], "held", reason=_held.reason("audit"), by=BY, next_turn="audit")
        else:
            to = [sent[a].split(":", 1)[0] + (" (held)" if sent[a].endswith(": held") else " (archived)" if sent[a].endswith(": archived") else "") for a in split]          # every recipient, one with held lines named too
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
    _want_background(n, aroot, ln, cx)      # whatever the ruling: set-if-absent, so a retried notice records nothing new
    try:
        ruling, target, reason = ln["ruling"], ln.get("target", ""), ln.get("reason", "")
        if ruling == "passed":
            tried = str(prior.get("target") or "")        # where the failed tries went: a pass to the -main agent that was rerouted to the background agent logged that agent, not the ruling's target
            rerouted = bool(tried) and tried != main and not ln.get("split")
            if not target or (int(prior.get("tries", 0)) >= MAX_TRIES and main and (target != main or rerouted)):
                why = f"delivery to {tried if rerouted else target} failed {MAX_TRIES} times" if target else "no target"
                target, reason = main, f"passed to {main}: {why} ({reason})"
                base["source"] = "fallback"
            if not target and ln.get("person"):               # a person's message is never archived, not even for want of an agent: left unruled, tried again at the next tick (_judge makes no such line: this is the backstop)
                return {**base, "status": "error", "error": "a person's message with nobody to hold it for: the page lists no live background agent and no front agent; left unruled for the next tick"}
            if not target:                                    # no -main agent anywhere (the page, its hub and the scope's general agent list none): archived, with the reason, never dropped and never handed to a session that is gone
                ruling, reason = "archived", f"no agent can take it: the page and its hub list no user-facing agent and the scope's general -main agent ([router] general_*) is on no page ({reason})"
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
        unmarked_front = False         # a pass to a front agent that goes unmarked: an answer to the agent's own question, while the person is in that conversation
        person_front = False           # a person's message passed to a front agent (the read-first gate: a need of the owner, or a page with no background agent)
        if ruling == "passed" and ln.get("person") and ln.get("rule") != "watch" and prior.get("status") != "delivered" and target and _is_front(target, aroot, cx):
            person_front = True        # a person's message is never archived by a front gate: it is filed as a held line for the agent's next turn (the same front gate, which starts no turn), or delivered as before when it cannot be filed; a standing [[router.watch]] is his own explicit ask, so it keeps its delivery
            try:
                fn_p = _HOOKS["front_fyi"]
                verdict_p = (fn_p(target, _held_text(n, _body(n)), str(ln.get("item") or ""), n["id"], False, kind="person", whole=True) or ("", ""))[0] if fn_p and _held.enabled() else ""
            except Exception:  # noqa: BLE001
                verdict_p = ""
            if verdict_p == "fyi":
                held_for = target
                ruling, target, reason = "held", "", f"held: a person's message, {reason} (rides {held_for}'s next turn, starts none)"
                base.update(ruling=ruling, target="", reason=reason, marked=False, held_for=held_for, hold="person")
        if ruling == "passed" and prior.get("status") != "delivered" and base.get("source") != "fallback" and not person_front:      # a pass to a front agent with no need of the person: not marked, not a turn for him
            act_, arg_ = _front_route(n, ln, target, aroot, cx)
            nameless = "the message names no open item of his; " if _is_session_message(n, _body(n)) and act_ in ("background", "archived", "hold") and not _must_see(n, ln, _body(n), cx, target) else ""      # a session's message reaches here with no item of his named, except a sibling's quoted words (held with one named): the reason line says so only for the first
            if act_ == "deliver":
                unmarked_front = True
                base["reason"] = reason = f"{reason} (an answer to {target}'s own question, and the person is in that conversation)"
            elif act_ == "background":
                base.update(target=arg_, reason=f"{reason} (not for the person: {nameless}passed to the project's background agent {arg_}, not to {target})")
                target, reason = arg_, base["reason"]
            elif act_ == "archived":      # no background agent to take it, and nothing here needs him: logged, a row of the digest, not held for the front agent
                reason = f"archived: front agent {target}, {nameless}{arg_} (not delivered, not held)"
                ruling, target = "archived", ""
                base.update(ruling=ruling, target="", reason=reason, marked=False, front_gate=True)
            elif act_ in ("items", "hold"):
                verdict_ = "fyi"
                if act_ == "hold":
                    verdict_, _why = _HOOKS["front_fyi"](target, _held_text(n, _body(n)), str(ln.get("item") or ""), n["id"], False, whole=True) or ("", "")      # log=False: the router's own ruling is the routing-log line
                if verdict_ == "fyi":
                    held_for = target
                    ruling, target = "held", ""
                    reason = f"written onto the item it names, not delivered: an answer to {held_for}'s question, and the person is not in that conversation" if act_ == "items" else f"held: front agent, {nameless}{arg_} (rides its next turn, starts none)"
                    base.update(ruling=ruling, target="", reason=reason, marked=False, held_for=held_for, hold="fyi")
                # a gate that could not file it (the agent's hook cannot fetch held lines, or the gate failed): delivered as before, marked, never dropped for want of a place to hold it
        if ruling == "passed" and prior.get("status") != "delivered":      # a pass that asks nothing of a background agent is held for its next turn
            hk = _hold_kind(n, ln, target, cx)
            if hk and _held.add(_held.key_of(target), hk, _body(n), sender=str(n.get("who") or ""), gid=str(ln.get("item") or ""), nid=n["id"], whole=(hk in ("fyi", "person")), where=_held_where(n)):
                held_for = target
                ruling, target, reason = "held", "", _held.reason(hk)
                base.update(ruling=ruling, target="", reason=reason, marked=False, held_for=held_for, hold=hk)
            else:
                verdict, why = _front_fyi(n, ln, target, aroot, cx)      # an fyi for a front agent: the front gate files it for his next turn, or holds it
                hold_as = "fyi"
                if not verdict:
                    verdict, why = _front_page_owed(n, ln, target, aroot, key, cx)      # a page-owed notice for a front agent: the same gate
                    hold_as = "page-owed"
                if verdict:
                    held_for = target if verdict == "fyi" else ""
                    ruling, target = ("held" if held_for else "archived"), ""      # filed for the agent's next turn, or told to no one (its hook cannot fetch held lines): only the first is held
                    reason = _held.reason(hold_as) if verdict == "fyi" else f"archived: front agent, {why} ({hold_as})"
                    base.update(ruling=ruling, target="", reason=reason, marked=False, held_for=held_for, hold=hold_as)
        if ruling == "passed" and prior.get("status") != "delivered" and not unmarked_front and not person_front:      # a pass to a front agent starts a turn only when he is with it and it needs him, or he asked it to tell him about the subject
            verdict_t, arg_t = _front_turn_gate(n, ln, target, aroot, cx)
            if verdict_t == "background" and base.get("source") == "fallback" and arg_t == tried:      # the fallback after the background agent's own deliveries failed: back to it it never goes, so a pass that meets neither case is logged
                verdict_t, arg_t = "archived", f"the background agent {tried} could not be reached, and he is not talking with {target} and has not asked it to tell him about this"
            if verdict_t == "background":      # about the work of a background agent: it takes the pass, and holds it as it holds any
                base.update(target=arg_t, reason=f"{reason} (not for the person: passed to {arg_t}, whose work it is, not to {target}: he is not talking with {target} and has not asked it to tell him about this)")
                target, reason = arg_t, base["reason"]
                hk = _hold_kind(n, ln, target, cx)
                if hk and _held.add(_held.key_of(target), hk, _body(n), sender=str(n.get("who") or ""), gid=str(ln.get("item") or ""), nid=n["id"], whole=(hk in ("fyi", "person")), where=_held_where(n)):
                    held_for = target
                    ruling, target, reason = "held", "", _held.reason(hk)
                    base.update(ruling=ruling, target="", reason=reason, marked=False, held_for=held_for, hold=hk)
            elif verdict_t == "archived":      # nobody is told, and nothing waits for a front agent's next turn: a row of the digest, which he reads
                reason = f"archived: front agent {target}, {arg_t} (not delivered, not held)"
                ruling, target = "archived", ""
                base.update(ruling=ruling, target="", reason=reason, marked=False, front_gate=True)
        if ruling == "passed":
            mark = _is_front(target, aroot, cx) and not unmarked_front       # the mark means the person must see it: a pass to a front agent without a need of his is held, sent to the background agent, or (an answer in his conversation) unmarked, above; what reaches here marked had a need, or no place to be held
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
                _project, ruled = _routing.rule(n["id"], ruling, reason=reason, by=BY, next_turn=str(base.get("hold") or "") if ruling == "held" else "")
            except Exception as e:  # noqa: BLE001
                return {**base, "status": "error", "stage": "rule", "error": f"not ruled: {type(e).__name__}: {str(e)[:100]}"}
        done = _HOOKS["after_rule"]
        if done:
            try:
                after = {**ruled, "front_held": True} if isinstance(ruled, dict) and ruling == "held" and base.get("hold") == "fyi" and base.get("held_for") else {**ruled, "front_gate": True} if isinstance(ruled, dict) and ruling == "archived" and base.get("front_gate") else ruled      # front_held: the front agent has the line for its next turn, so a hold that waited on this anchor is released, as by a pass
                if isinstance(after, dict) and _router.person_wakes(n):
                    after = {**after, "person_wake": True}      # a person's message (not a bare laugh or ack) wakes an item that waits on its anchor, whatever the ruling was
                done(key, after)
            except Exception as e:  # noqa: BLE001
                base["error"] = f"after-rule: {type(e).__name__}: {str(e)[:100]}"
        _note(base, root, n["id"])
        return {**base, "status": "ruled"}
    except Exception as e:  # noqa: BLE001
        return {**base, "status": "error", "outcome": "", "error": f"{type(e).__name__}: {str(e)[:140]}"}


TWIN_WINDOW = 30.0      # seconds: the notices one event makes for the pages that hold its anchor are recorded within moments of one another


def _twin_sig(n: dict[str, Any]) -> tuple[str, str, str, str]:
    a = str(n.get("anchor") or "")
    return (_anc.anchor_id(a) or a, str(n.get("who") or "").strip().lower(), " ".join(str(n.get("text") or "").split()), str(n.get("url") or ""))


def _about(key: str, n: dict[str, Any], root: str, cx: "_router.Context") -> int:
    """How much a notice is about this page: the anchor is scoped to one open item of it (4), to several (3), plus one when the page's own name is in the notice's words."""
    items = _router._anchor_items(key, n, cx)
    low = " ".join(str(n.get(f) or "") for f in ("text", "label", "url")).lower()
    slug = root.rsplit("/", 1)[-1].lower()
    return (4 if len(items) == 1 else 3 if items else 0) + (1 if slug and slug in low else 0)


def _twin_plan(groups: dict[str, list[tuple[str, dict[str, Any]]]], last: dict[str, dict[str, Any]], cx: "_router.Context") -> tuple[dict[str, tuple[str, str, str]], dict[str, dict[str, list[str]]], dict[str, tuple[str, str, str]]]:
    """One event, one ruling. An anchor notice on an anchor several pages hold is recorded once for each of them (the anchor listener), with the same sender, text and link a moment apart, and used to be ruled once on each page. Now
    the notices of one event are found and one of them is ruled by the gate and the call: the one for the page it is about (_about; the first recorded on a tie), and the call is shown the other pages (`offered`) and may
    name their agents. The others follow it (router.twin_line), once it is ruled. A notice that comes in after its twin was ruled follows that ruling.
    → (twin id → (the ruled notice's id, its page, its key), page → {notice id → the other pages that hold its anchor}, twin id → the same for a twin already ruled earlier). Notices already delivered are never twins."""
    cands = [(root, key, n) for root, rows in groups.items() for key, n in rows
             if n.get("kind") == "anchor" and n.get("anchor") and last.get(n["id"], {}).get("status") != "delivered"]
    buckets: dict[tuple[str, str, str, str], list[tuple[str, str, dict[str, Any]]]] = {}
    for c in cands:
        buckets.setdefault(_twin_sig(c[2]), []).append(c)
    twins: dict[str, tuple[str, str, str]] = {}
    offered: dict[str, dict[str, list[str]]] = {}
    used: set[str] = set()
    for cs in buckets.values():
        cs.sort(key=lambda c: (float(c[2].get("ts", 0)), c[1]))
        for j, first in enumerate(cs):
            if first[2]["id"] in used:
                continue
            cluster, keys = [first], {first[1]}
            for other in cs[j + 1:]:
                if other[2]["id"] not in used and other[1] not in keys and float(other[2].get("ts", 0)) - float(first[2].get("ts", 0)) <= TWIN_WINDOW:
                    cluster.append(other)
                    keys.add(other[1])
            if len(cluster) < 2:
                continue
            used.update(c[2]["id"] for c in cluster)
            _i, best = max(enumerate(cluster), key=lambda t: (_about(t[1][1], t[1][2], t[1][0], cx), -t[0]))
            rest = [c for c in cluster if c is not best]
            others = sorted({c[0] for c in rest if c[0] != best[0]})
            if others:
                offered.setdefault(best[0], {})[str(best[2]["id"])] = others
            for c in rest:
                twins[str(c[2]["id"])] = (str(best[2]["id"]), best[0], best[1])
    ruled: dict[str, tuple[str, str, str]] = {}
    since = min((float(c[2].get("ts", 0)) for c in cands), default=0.0) - TWIN_WINDOW - 1
    by_sig: dict[str, dict[tuple[str, str, str, str], list[dict[str, Any]]]] = {}      # a holding page's ruled notices by signature: read and folded once per tick, however many notices ask

    def ruled_on(k2: str) -> dict[tuple[str, str, str, str], list[dict[str, Any]]]:
        if k2 not in by_sig:
            idx: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
            for m in _routing.read(k2, since=since):
                if m.get("kind") == "anchor" and m.get("ruling") in ("passed", "merged", "held", "archived", "dropped"):
                    idx.setdefault(_twin_sig(m), []).append(m)
            by_sig[k2] = idx
        return by_sig[k2]

    for root, key, n in cands:
        if str(n["id"]) in used:
            continue
        sig = _twin_sig(n)
        for k2 in _router.anchor_holders(n, cx):
            if k2 == key or str(n["id"]) in ruled:
                continue
            for m in ruled_on(k2).get(sig, ()):
                if (m.get("id") != n["id"] and abs(float(m.get("ts", 0)) - float(n.get("ts", 0))) <= TWIN_WINDOW
                        and not (_router.person_notice(n) and m["ruling"] in ("archived", "dropped"))):      # a person's message never follows an archive
                    ruled[str(n["id"])] = (str(m["id"]), _anc.pilot_root(k2) or k2, k2)
                    break
    return twins, offered, ruled


def tick(now: float | None = None, runner: Any = None) -> dict[str, int]:
    """One pass over every project's unruled held notices → {"coded", "called", "calls", "fallback", "passed", "ruled", "errors", "stuck", "notes"}. The notices of one event on an anchor several pages hold are ruled once (_twin_plan)."""
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
        rehome_person(cx)      # a held person line of an agent that retired since is moved to a live agent of its page
        cap = int(_router._num("max_notices", 25, 1))
        try:
            twins, offered, ruled_twins = _twin_plan(groups, last, cx)
        except Exception as e:  # noqa: BLE001  (an extra: a failure in it rules every notice on its own page, as before)
            print(f"router live: twin plan failed: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
            twins, offered, ruled_twins = {}, {}, {}
        followers = {**twins, **ruled_twins}       # notices that follow another's ruling: not judged here
        results: dict[str, dict[str, Any]] = {}
        later: list[tuple[str, str, dict[str, Any]]] = []
        for root, rows in sorted(groups.items()):
            rows.sort(key=lambda r: float(r[1].get("ts", 0)))
            ready = [(k, n) for k, n in rows if last.get(n["id"], {}).get("status") == "delivered"]       # delivered, ruling to finish
            fresh = [(k, n) for k, n in rows if last.get(n["id"], {}).get("status") != "delivered"]
            batch = fresh[:cap]
            later += [(root, k, n) for k, n in batch if str(n["id"]) in followers]
            batch = [(k, n) for k, n in batch if str(n["id"]) not in followers]
            got, st = _judge(root, batch, cx, runner, since, offered.get(root)) if batch else ([], {"called": 0, "calls": 0, "retry": 0})
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
                results[str(n["id"])] = res
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
        for root, key, n in later:      # the notices of one event that follow the ruling of the one for the page it is about (or of one ruled at an earlier tick)
            nid = str(n["id"])
            rid, rroot, rkey = followers[nid]
            if nid in ruled_twins:
                m = _routing.lookup(rid, rkey)
                ruling, how = (str(m[1].get("ruling") or "merged"), str(m[1].get("ruled_to") or m[1].get("ruling"))) if m else ("merged", "ruled earlier")
            else:
                r = results.get(rid)
                if not r or r.get("status") != "ruled":
                    continue      # the ruled one is not ruled yet (its call is tried again, or its delivery failed): this one waits for it
                ruling, how = str(r.get("ruling") or "merged"), f"{r.get('ruling')} {r.get('target') or r.get('held_for') or ''}".strip()
            ln = _router.twin_line(n, key, root, rid, rroot, ruling, how)
            res = _act(n, key, root, ln, cx, last.get(nid, {}))
            _log(res)
            out["errors"] += res["status"] == "error"
            out["ruled"] += res["status"] == "ruled"
            out["coded"] += 1
            out["notes"] += bool(res.get("noted"))
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


# ----------------------------------------------------------------------------- the daily digest of archived notices
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
    """What the next digest of this project lists → (the "main" group: archived notices, logged only, and the ones the router could not rule,
    delivered; quiet-hour holds for the QUIET agent; page-pass holds, logged only), each a list of (the
    router's live.jsonl line, the notice as the routing log reads it), oldest first: the notices the router ruled `archived` (and nobody has
    overruled since) and the ones it could not rule (status "stuck", still unruled), that no digest has listed, from the last SINCE_DAYS."""
    rows: list[tuple[dict[str, Any], dict[str, Any]]] = []
    notices: dict[str, dict[str, dict[str, Any]]] = {}
    for i, ln in last.items():
        status = ln.get("status")
        if ln.get("project") != root or i in st["sent"] or float(ln.get("ts", 0)) < now - SINCE_DAYS * 86400:
            continue
        if ln.get("held_for"):          # held for a background agent's next turn (held.py), which hands it over: the digest would send it twice
            continue
        if not ((status == "ruled" and ln.get("ruling") == _routing.ARCHIVED) or status == "stuck"):
            continue
        key = str(ln.get("key") or root)
        if key not in notices:
            notices[key] = {x["id"]: x for x in _routing.read(key)}
        n = notices[key].get(i)
        if n is None or (status == "ruled" and not (n.get("ruling") == _routing.ARCHIVED and n.get("ruled_by") == BY)) or (status == "stuck" and n.get("ruling")):
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
    archived = [r for r in rows if r[0].get("status") != "stuck"]
    stuck = [r for r in rows if r[0].get("status") == "stuck"]
    parts = []
    if archived:
        parts.append(f"{len(archived)} notice{'s were' if len(archived) != 1 else ' was'} archived " + {"quiet": "through the quiet hour", "pagepass": "for the page pass"}.get(group, "by the router and not passed to any agent"))
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
    lines.append("The router ruled these archived; nothing is owed on an archived one." if archived and not stuck else
                 "An archived notice is the router's ruling and owes nothing; one that could not be ruled is in the routing log with no ruling.")
    return "\n".join(lines)


def digest_tick(now: float | None = None) -> dict[str, int]:
    """The day's digest of each live project, from [router] digest_hour on (a server that was down then sends it when it is back the
    same day) → {"sent", "empty", "failed", "logged"}. A project is done once a day per group (main, pagepass, and for router.QUIET's project
    quiet). A "main" or "pagepass" group of archived rows only is logged, not delivered; one with a notice that could not be ruled is delivered
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
                        # archived notices are the router's own ruling and owe nothing (the owner's are in stackshot's For you list, not in a front
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
    """One row per top-level page: the notices acted on in the last hour, the notices archived since the last digest and when
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
        archived_rows = _digest_items(root, now, last, st)
        rows.append({"project": root, "acted_last_hour": acted, "archived_since_digest": sum(len(g) for g in archived_rows),
                     "last_digest_at": float(st["last"].get(root, 0)), "last_error": err[1], "last_error_at": err[0]})
    return rows


def render(rows: list[dict[str, Any]]) -> str:
    fmt = lambda ts: dt.datetime.fromtimestamp(ts, _cfg.tz()).strftime("%Y-%m-%d %H:%M")
    out = ["router: rules every project",
           f"{'project':34} {'1h':>4} {'archived':>8}  {'last digest':16}  last error"]
    for r in rows:
        when = fmt(r["last_error_at"]) if r["last_error_at"] else ""
        out.append(f"{r['project'][:34]:34} {r['acted_last_hour']:>4} {r['archived_since_digest']:>8}  {fmt(r['last_digest_at']) if r['last_digest_at'] else '-':16}  "
                   + (f"{when} {r['last_error'][:120]}" if r["last_error"] else "-"))
    return "\n".join(out)


if __name__ == "__main__":
    if sys.argv[1:2] != ["status"]:
        sys.exit("usage: router_live.py status [--json]   (set STACKSHOT_CONFIG to the instance's file)")
    res = status()
    print(json.dumps(res, ensure_ascii=False, indent=1) if "--json" in sys.argv else render(res))
