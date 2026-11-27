"""Scenario test for the two switches that keep a front agent's work from waiting on an idle front agent - fixture data, no live store, no network, no server.

`[front] to_background_senders` (empty by default) lists front agents that send nothing to a front agent: their message to one goes to the target project's background agent (`messaging._gate_front` and the "For <front agent>" project message),
the router passes their messages there too (`router_live._front_reroute`, hook `front_reroute`), and a hand-off of theirs that names no open item gets one line at the end of its reply. `[front] idle_peers_to_background` (off by default) sends a
front agent's unmarked message to a peer front agent the person is not with to that project's background agent instead of holding it (the gate, and the router's peer hold, hook `front_idle`).

Covers:
  0. The two keys: defaults (nobody listed, off), a value of the wrong kind reads as the default and `config.notes` names it, only a TOML true turns the second on.
  1. Both switches off: the peer hold, the pass of a hand-off, the project message, the router's hold, no added line.
  2. A listed sender to a front agent: marked or not, fyi or not, a question, an answer, a note, its own project's front agent, the sender as a session id: the background agent takes it, never a refusal; an unlisted sender, a listed background agent and a script are untouched.
  3. No background agent, or one that cannot take it (a failed push, a retired session): held for the front agent's next turn, the reply saying why and to use a board item; refused only when nothing can carry it; no send comes back on itself.
  4. A project message that opens "For <front agent>": the same.
  5. The router: a listed sender's message passed to a front agent goes to the background agent, never held for the front agent; a project with none is ruled as before; a background agent that cannot be reached has it archived.
  6. The added line: present for a hand-off that names no open item (once, last), absent for a named open item, an fyi, a note, an unlisted sender, a script, a refusal.
  7. Idle peers, the message tool: to the background agent while the person is away; held while he is there, on a presence that cannot be read, for notes, answers, fyi, marked messages, no background agent, an agent that cannot take it.
  8. Idle peers, the router: the same for a pass to a peer front agent, and held for the peer after the background agent's deliveries failed.

    tests/run-suite front_reroute   -> exit 0 / 1"""
import datetime, json, logging, os, pathlib, re, sys, threading, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="frontreroute-"); T = pathlib.Path(tmp)
BOARD = "https://board.example.org"
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's own session store
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "UTC")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml = _instance.set_person(toml)
for pat, rep in ((r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]'), (r'(?m)^board_url = "[^"]*"', f'board_url = "{BOARD}"'),
                 (r'(?m)^base_url = "[^"]*"', f'base_url = "{BOARD}"'),
                 (r'(?m)^allowed_emails = \[[^\]]*\]', 'allowed_emails = ["oliver@example.org"]'), (r'(?m)^ui_open = true', 'ui_open = false')):
    toml, n = re.subn(pat, rep, toml); assert n == 1, pat
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/transcripts"]', toml); assert n == 1   # never the host's transcripts
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/site", "secrets", "touch", "repo", "brain/projects", "transcripts/-x"): (T / d).mkdir(parents=True)

# the sessions: alpha has two front agents and two background agents, beta one of each, solo and quiet a front agent alone
NAMES = ("my-front", "second-front", "my-builder", "my-docs", "other-front", "other-builder", "solo-front", "quiet-front", "outside-session")
ID = {name: f"{d}" * 8 + f"-{d * 4}-4{d * 3}-8{d * 3}-" + d * 12 for name, d in zip(NAMES, "123456789")}
(T / "state/site/favicon.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"/>')
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a", "url": "", "seen": "x"} for n, u in ID.items()}))
def page(title, agents, back):
    return {"title": title, "name": title, "org": "home", "tags": [], "type": "project", "session": title.lower(), "status": "active", "board": [], "board_row": False,
            "updated": 1, "mirror": f"https://example.invalid/{title.lower()}", "agents": agents, "back_agents": {k: agents[k] for k in back}}
DESK, BUILDS = "Oliver's point of contact", "builds, merges and releases the code"
(T / "store/projects.json").write_text(json.dumps({"pages": {
    "projects/alpha": page("Alpha", {"my-front": DESK, "second-front": DESK, "my-builder": BUILDS, "my-docs": "keeps the pages"}, ("my-builder", "my-docs")),
    "projects/beta": page("Beta", {"other-front": DESK, "other-builder": BUILDS}, ("other-builder",)),
    "projects/solo": page("Solo", {"solo-front": DESK}, ()),
    "projects/quiet": page("Quiet", {"quiet-front": DESK}, ())}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n# Alpha\n\n## Current state\n\nALPHA-STATE.\n\n<!-- timeline -->\n- 2026-10-01 | old\n")
now0 = time.time()
def item(i, owner="my-builder", status="open", project="projects/beta", **meta):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": "- A thing\n- It lives here\n- Finished when it works", "status": status,
                                                       "updated": now0 - 3600, "state_updated": now0 - 3600, "confirmed": now0 - 3600,
                                                       "metadata": {"owner": owner, "project": project, "next": "the next step", **({} if "needs" in meta else {"mover": owner}), **meta}}))
item(1); item(2, status="completed"); item(3, owner="other-front", needs=["decision"])
(T / "store/next-id").write_text("100")
push_log = T / "push.log"
(T / "fakepush.py").write_text("import sys, json, os, pathlib\na = sys.argv[1:]\nif a[:1] == ['--from']: a = a[2:]\n"
                               f"if (pathlib.Path({tmp!r}) / ('fail-' + a[0])).exists(): print('boom'); sys.exit(0)\n"
                               f"open({str(push_log)!r}, 'a').write(json.dumps(a) + '\\n')\nprint('delivered → ' + a[0])\n")
def pushes(): return [json.loads(l) for l in push_log.read_text().splitlines()] if push_log.exists() else []
def settle(until=30):
    end = time.time() + until
    while time.time() < end and any(t is not threading.main_thread() and t.is_alive() for t in threading.enumerate()):
        time.sleep(0.02)
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))

from stackshot.core import config as _cfg; from stackshot.router import routing; from stackshot.waits import held
from stackshot.router import router as _router; from stackshot.router import router_live as _live
from stackshot.web import server
from stackshot.service import messaging as _messaging
from stackshot.service import front_turn as _front_turn
from stackshot.fleet import clients as _clients
from fastmcp.exceptions import ToolError
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
from stackshot.web.tools import anchors as _wt_anchors
from stackshot.web.tools import route as _wt_route
from stackshot.service import telling
from stackshot.service import handoff as handoff_svc
handoff_svc.CLI_SESSIONS = T / "cli"; (T / "cli").mkdir()
def pane(who):
    """The CLI's own registry row of a pane on this box, which the presence test reads the session id from."""
    (T / f"cli/{os.getpid()}-{who}.json").write_text(json.dumps({"pid": os.getpid(), "kind": "interactive", "sessionId": ID[who], "name": who, "status": "idle", "startedAt": int((time.time() - 7200) * 1000),
                                                                  "statusUpdatedAt": int(time.time() * 1000), "updatedAt": int(time.time() * 1000)}))
def stamp_file(who): return T / "state/prompts" / ID[who]
def stamp(who, minutes_ago):
    p = stamp_file(who); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(f"{time.time() - minutes_ago * 60:.0f}\n")
def unstamp(who): stamp_file(who).unlink(missing_ok=True)
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None; telling.PUSH = [sys.executable, str(T / "fakepush.py")]
_web_page_debts._owing_note = lambda debtor: ""
_cfg.CFG["router"] = {"command": [sys.executable, "-c", "pass"], "timeout_seconds": 20, "live": True}
OWNER = _cfg.owner()
for name in NAMES:
    _clients.register("home-test", {"uuid": ID[name], "name": name})
    pane(name)
    if name != "quiet-front": held.mark_client(ID[name], name)      # quiet-front's hook never fetched held lines: nothing can be held for it

def switches(listed=None, idle=None):
    """Set the `[front]` table to these two keys alone (None leaves the key out)."""
    _cfg.CFG["front"] = {**({} if listed is None else {"to_background_senders": listed}), **({} if idle is None else {"idle_peers_to_background": idle})}
def fresh():
    """Empty the held store, the push log, the message log, the failures and the stamps between checks, once the sends before are over."""
    settle()
    for p in held.dir_().glob("*.jsonl"): p.unlink()
    for p in T.glob("fail-*"): p.unlink()
    push_log.unlink(missing_ok=True); _messaging.MSG_LOG.unlink(missing_ok=True)
    for name in NAMES: unstamp(name)
def msg(to, text, sender, **kw):
    try: return _messaging._message(to, text, sender, **kw)
    except ToolError as e: return str(e)
def got(who): return [x for x in pushes() if x[0] in (who, ID[who])]
def waiting(who): return held.count(ID[who])
def failing(who):
    for ref in (who, ID[who]): (T / f"fail-{ref}").write_text("x")
def mlog(): return [json.loads(l) for l in _messaging.MSG_LOG.read_text().splitlines()] if _messaging.MSG_LOG.exists() else []
def asked(front, other):
    """A row of the message log: `front` put a question to `other` a minute ago."""
    _messaging.MSG_LOG.parent.mkdir(parents=True, exist_ok=True)
    t = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=1)).isoformat(timespec="seconds")
    with open(_messaging.MSG_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps({"t": t, "from": front, "auth": "", "to": other, "outcome": "delivered", "error": "", "text": "which one?", "question": True}) + "\n")
def mark(): return _messaging._FOR_OWNER
LINE = _messaging._NO_ITEM_LINE
def rerouted(out, sender="my-front", back="other-builder", front="other-front", project="projects/beta"):
    """The reply and the effect of a reroute: the background agent's pane got the message, the front agent's neither a turn nor a held line."""
    return (out.startswith(f"Rerouted: {sender} sends nothing to front agents, so it went to {back}, the background agent of {project}, instead of {front}: ") and "Not for " not in out
            and got(front) == [] and waiting(front) == 0)
def idle_sent(out, back="other-builder", front="other-front"):
    return (out.startswith(f"Rerouted: {front} is idle ({OWNER} is not talking with it), so this went to {back}, the background agent of projects/beta: delivered")
            and len(got(back)) == 1 and got(front) == [] and waiting(front) == 0)
def peer_held(out, sender="second-front", front="other-front"):
    return out.startswith(f"held for {front}'s next turn ({sender} is a front agent, so its message to {front} rides {front}'s next turn") and got(front) == [] and waiting(front) == 1
def retired(*who):
    """Make these sessions read as retired to the address check; returns the call that undoes it."""
    real = _messaging._dead_recipient
    def check_(to, recs, idx):
        name = next((n for n in who if to in (n, ID[n])), "")
        if name:
            project = "projects/solo" if name == "solo-front" else "projects/beta"
            raise _messaging._Retired(f"Refused: {name} is retired", name, project, "retired in the test")
        return real(to, recs, idx)
    _messaging._dead_recipient = check_
    return lambda: setattr(_messaging, "_dead_recipient", real)
@__import__("contextlib").contextmanager
def hold_off():
    had = _cfg.CFG["router"].get("hold_notices")
    _cfg.CFG["router"]["hold_notices"] = False
    try: yield
    finally:
        if had is None: _cfg.CFG["router"].pop("hold_notices", None)
        else: _cfg.CFG["router"]["hold_notices"] = had

ASK = "please build the export for the weekly page"

# ---- 0. the keys
_cfg.CFG.pop("front", None)
check("0 with no [front] table nobody is listed and the idle switch is off", _front_turn.to_background_senders() == [] and _front_turn.idle_peers_to_background() is False)
switches(["My-Front", "other-front"], True)
check("0 the listed names are read case-folded and true turns the idle switch on", _front_turn.to_background_senders() == ["my-front", "other-front"] and _front_turn.idle_peers_to_background() is True)
for bad in ("true", "on", 1, "false"):
    switches(None, bad)
    check(f"0 idle_peers_to_background = {bad!r} is no TOML true: off, and the config notes name it", _front_turn.idle_peers_to_background() is False and any(x.startswith("[front] idle_peers_to_background") for x in _cfg.notes()), _cfg.notes())
for bad in ("my-front", True, 3):
    switches(bad)
    check(f"0 to_background_senders = {bad!r} is no list: nobody is listed, and the config notes name it", _front_turn.to_background_senders() == [] and any(x.startswith("[front] to_background_senders = ") for x in _cfg.notes()), _cfg.notes())
switches(["my-front", 4, " "])
check("0 entries that are no names are ignored and named, the valid name stays listed", _front_turn.to_background_senders() == ["my-front"] and any(x.startswith("[front] to_background_senders has 2 entries") for x in _cfg.notes()), _cfg.notes())
switches(["my-front"], False)
check("0 a good table leaves no note about either key", not any("to_background_senders" in x or "idle_peers_to_background" in x for x in _cfg.notes()), _cfg.notes())

# ---- 1. both switches off
for label, table in (("no table", (None, None)), ("empty and false", ([], False))):
    switches(*table); fresh()
    out = msg("other-front", ASK, "my-front"); settle()
    check(f"1 {label}: a front agent's message to a peer front agent is held as before, with no added line", peer_held(out, "my-front") and got("other-builder") == [] and LINE not in out, out)
    fresh(); out = msg("other-builder", ASK, "my-front"); settle()
    check(f"1 {label}: a hand-off to a background agent is delivered with no added line", out.startswith("delivered") and len(got("other-builder")) == 1 and LINE not in out, out)
    fresh(); out = msg("projects/beta", f"For other-front, {ASK}", "my-front"); settle()
    check(f"1 {label}: a project message that opens For <front agent> goes to the router, with no added line", out.startswith("held for the router") and got("other-builder") == [] and LINE not in out, out)

# ---- 2. a listed sender to a front agent
switches(["MY-FRONT"])
fresh(); out = msg("other-front", ASK, "my-front"); settle()
check("2 an unmarked message goes to the target project's background agent", rerouted(out) and len(got("other-builder")) == 1 and ASK in got("other-builder")[0][1], out)
for label, text in (("marked, naming his item while he is there", f"{mark()}\na3: decide whether the export ships on Friday"),
                    ("marked, naming no item", f"{mark()}\ndecide whether the export ships on Friday"),
                    ("the mark away from the first line", f"hello\n{mark()} decide whether the export ships"),
                    ("a done note", "the build is done, no action needed."),
                    ("a marked note", f"{mark()}\nthe build is done, no action needed.")):
    fresh(); stamp("other-front", 1); out = msg("other-front", text, "my-front"); settle()
    check(f"2 {label}: rerouted, never refused", rerouted(out) and len(got("other-builder")) == 1, out)
fresh(); asked("other-front", "my-front"); stamp("other-front", 1); out = msg("other-front", "the second one", "my-front"); settle()
check("2 an answer to the front agent's own question is rerouted too", rerouted(out) and len(got("other-builder")) == 1, out)
fresh(); out = msg("other-front", ASK, "my-front", fyi=True); settle()
check("2 an fyi is held for the background agent, as an fyi", rerouted(out) and "held for other-builder's next turn (fyi" in out and waiting("other-builder") == 1 and got("other-builder") == [], out)
fresh(); out = msg("other-front", "which export do you need?", "my-front", question=True); settle()
check("2 a question keeps its mark on the way to the background agent", rerouted(out) and any(r.get("to") == "other-builder" and r.get("question") is True for r in mlog()), (out, mlog()))
fresh(); out = msg("second-front", ASK, "my-front"); settle()
check("2 the sender's own project's front agent: that project's background agent takes it", rerouted(out, back="my-builder", front="second-front", project="projects/alpha") and len(got("my-builder")) == 1, out)
fresh(); out = msg(ID["other-front"], ASK, ID["my-front"]); settle()
check("2 the sender and the target as session ids resolve as the gate resolves them", rerouted(out) and len(got("other-builder")) == 1, out)
fresh(); out = msg("other-front", ASK, "second-front"); settle()
check("2 a front agent the key does not list is held as before", peer_held(out) and got("other-builder") == [], out)
fresh(); out = msg("other-front", ASK, "my-front", origin="home-test"); settle()
check("2 a script that names itself like a listed agent is no session: not rerouted, no added line", not out.startswith("Rerouted:") and LINE not in out, out)
switches(["my-builder"]); fresh(); out = msg("other-front", ASK, "my-builder"); settle()
check("2 a listed name whose role is not front counts for nothing", out.startswith("Not for ") and "Rerouted" not in out and LINE not in out, out)
switches(["my-front"]); fresh(); out = msg("other-builder", ASK, "my-front"); settle()
check("2 a listed sender's message to a background agent is delivered as before", out.startswith("delivered") and len(got("other-builder")) == 1, out)

# ---- 3. no background agent, or one that cannot take it
def held_back(out, front="solo-front", why="projects/solo has no background agent"):
    return (out.startswith(f"held for {front}'s next turn (it could not be rerouted: {why}") and "Put the work on a board item" in out and "Refused" not in out.split(":")[0]
            and got(front) == [] and waiting(front) == 1)
for label, text, kw in (("unmarked", ASK, {}), ("marked", f"{mark()}\ndecide the export", {}), ("an fyi", ASK, {"fyi": True}), ("a question", "which one?", {"question": True})):
    fresh(); out = msg("solo-front", text, "my-front", **kw); settle()
    check(f"3 no background agent, {label}: held for the front agent, the reply saying why and what to do", held_back(out), out)
fresh(); failing("other-builder"); out = msg("other-front", ASK, "my-front"); settle()
check("3 a background agent the push cannot reach: held for the front agent, the reply saying why", held_back(out, "other-front", "other-builder, the background agent of projects/beta, could not take it (Delivery failed: boom"), out)
undo = retired("other-builder")
try:
    for label, kw in (("a message", {}), ("an fyi", {"fyi": True})):
        fresh(); out = msg("other-front", ASK, "my-front", **kw); settle()
        check(f"3 a retired background agent, {label}: held for the front agent, not sent to the project", held_back(out, "other-front", "other-builder, the background agent of projects/beta, could not take it") and not any(r.get("to") == "projects/beta" for r in mlog()), out)
finally: undo()
undo = retired("other-builder", "other-front")
try:
    fresh(); out = msg("other-front", f"For other-front, {ASK}", "my-front"); settle()
    check("3 the front agent and its background agent both retired: the message goes to the project once and no send comes back on itself", out.startswith("'other-front' is retired") and "held for the router" in out and out.count(LINE) == 1, out)
finally: undo()
undo = retired("solo-front")
try:
    fresh(); out = msg("solo-front", f"For solo-front, {ASK}", "my-front"); settle()
    check("3 a retired front agent with no background agent: to the project, once", out.startswith("'solo-front' is retired") and "held for the router" in out, out)
finally: undo()
fresh(); out = msg("quiet-front", ASK, "my-front"); settle()
check("3 a front agent whose hook cannot fetch held lines: not passed on and said so, no refusal", out.startswith("not passed on — it could not be rerouted: projects/quiet has no background agent") and "Put the work on a board item" in out and got("quiet-front") == [], out)
with hold_off():
    fresh(); out = msg("solo-front", ASK, "my-front"); settle()
    check("3 the hold off and no background agent: nothing can carry it, so it is refused", out.startswith("Refused: my-front sends nothing to front agents, projects/solo has no background agent") and LINE not in out and got("solo-front") == [], out)
    fresh(); out = msg("other-front", ASK, "my-front"); settle()
    check("3 the hold off and a background agent: rerouted all the same", rerouted(out) and len(got("other-builder")) == 1, out)
    fresh(); failing("other-builder"); out = msg("other-front", ASK, "my-front"); settle()
    check("3 the hold off and a background agent that cannot take it: refused", out.startswith("Refused: my-front sends nothing to front agents, other-builder") and got("other-front") == [] and waiting("other-front") == 0, out)

# ---- 4. a project message that opens For <front agent>
fresh(); n0 = len(routing.read("projects/beta")); out = msg("projects/beta", f"For other-front, {ASK}", "my-front"); settle()
check("4 it goes to that project's background agent, and no notice is left for the router", rerouted(out) and len(got("other-builder")) == 1 and len(routing.read("projects/beta")) == n0, out)
fresh(); out = msg("projects/solo", f"for solo-front, {ASK}", "my-front"); settle()
check("4 a project with no background agent: held for the front agent, the reply saying why", held_back(out), out)
fresh(); failing("other-builder"); out = msg("projects/beta", f"For other-front, {ASK}", "my-front"); settle()
check("4 a background agent that cannot take it: held for the front agent", held_back(out, "other-front", "other-builder, the background agent of projects/beta, could not take it"), out)
fresh(); out = msg("projects/beta", f"For other-front, {ASK}", "second-front"); settle()
check("4 an unlisted sender's goes to the router as before", out.startswith("held for the router") and got("other-builder") == [], out)
with hold_off():
    fresh(); out = msg("projects/solo", f"For solo-front, {ASK}", "my-front"); settle()
    check("4 the hold off and no background agent: the project takes it as before, no refusal", out.startswith("held for the router"), out)
    fresh(); failing("other-builder"); out = msg("projects/beta", f"For other-front, {ASK}", "my-front"); settle()
    check("4 the hold off and a background agent that cannot take it: the project takes it as before", out.startswith("held for the router"), out)

# ---- 5. the router
def sent(key, text, sender, **kw):
    """A real message to a project page with the switches off, so it is recorded and stashed as the relay does it -> the notice."""
    keep = _cfg.CFG.get("front"); switches()
    try:
        out = msg(key, text, sender, **kw); settle()
    finally: _cfg.CFG["front"] = keep
    nid = re.search(r"router rules notice (\w+)", out).group(1)
    return next(n for n in routing.read(key) if n["id"] == nid)
def act(n, target, key="projects/beta", prior=None, **ln):
    line = {"id": n["id"], "ruling": "passed", "target": target, "reason": "it fits", "for_owner": False, "source": "code", "rule": "for-agent", "item": "", **ln}
    return _live._act(n, key, key, line, _router.Context(), prior or {})
def to_back(res, back="other-builder", front="other-front"):
    return (res.get("status") == "ruled" and res.get("ruling") == "passed" and res.get("target") == back and res.get("marked") is False and len(got(back)) == 1 and got(front) == [] and waiting(front) == 0
            and not got(back)[0][1].startswith(mark()))
switches(["my-front"])
fresh(); n = sent("projects/beta", f"For other-front, {ASK}", "my-front"); res = act(n, "other-front"); settle()
check("5 a pass of a listed sender's message to a front agent goes to the background agent, unmarked", to_back(res) and "my-front sends nothing to front agents" in res.get("reason", ""), res)
fresh(); n = sent("projects/beta", ASK, "my-front"); res = act(n, "other-front", rule="anchor-item"); settle()
check("5 a project message without the For line, whatever rule picked the front agent", to_back(res), res)
fresh(); stamp("other-front", 1); n = sent("projects/beta", f"{mark()}\na3: decide whether the export ships", "my-front"); res = act(n, "other-front", rule="watch"); settle()
check("5 a message that names his item, while he is there, under a watch: still the background agent", to_back(res), res)
fresh(); n = sent("projects/beta", f"For other-front, {ASK}", "my-front", fyi=True); res = act(n, "other-front"); settle()
check("5 an fyi is held for the background agent, never for the front agent", res.get("ruling") == "held" and res.get("held_for") == "other-builder" and waiting("other-builder") == 1 and waiting("other-front") == 0 and got("other-front") == [], res)
fresh(); n = sent("projects/beta", f"For other-front, {ASK}", "second-front"); res = act(n, "other-front"); settle()
check("5 an unlisted front sender's pass is held for the front agent as before", res.get("ruling") == "held" and res.get("held_for") == "other-front" and got("other-builder") == [], res)
fresh(); n = sent("projects/solo", f"For solo-front, {ASK}", "my-front"); res = act(n, "solo-front", key="projects/solo"); settle()
check("5 a project with no background agent is ruled as before", res.get("ruling") == "held" and res.get("held_for") == "solo-front", res)
fresh(); n = sent("projects/beta", f"[board] item a1 moved: {ASK}", "my-front"); res = act(n, "other-front"); settle()
check("5 a server's [board] line is no message of the sender's: ruled as before", res.get("target") != "other-builder" and got("other-builder") == [], res)
fresh(); failing("other-builder"); n = sent("projects/beta", f"For other-front, {ASK}", "my-front"); res = act(n, "other-front")
check("5 a failed delivery to the background agent is an error to try again", res.get("status") == "error" and res.get("target") == "other-builder", res)
res = act(n, "other-front", prior={**res, "tries": _live.MAX_TRIES}); settle()
check("5 …and after the last try it is archived: the front agent gets neither a turn nor a held line", res.get("ruling") == "archived" and "could not be reached" in res.get("reason", "") and got("other-front") == [] and waiting("other-front") == 0, res)
fresh()
for key_ in routing.projects():          # the notices the checks above left unruled: the tick below judges the one that follows, alone
    for old in routing.read(key_):
        if not old.get("ruling"): routing.rule(old["id"], "archived", reason="left by an earlier check", by="test")
n = sent("projects/beta", f"For other-front, {ASK}", "my-front"); _live.tick(); settle()
row = routing.lookup(n["id"], "projects/beta")[1]
check("5 end to end: the tick's own for-agent rule passes it to the background agent", row.get("ruled_to") == "other-builder" and len(got("other-builder")) == 1 and got("other-front") == [] and waiting("other-front") == 0, (row, pushes()))

# ---- 6. the added line
switches(["my-front"])
def once(out): return out.count(LINE) == 1 and out.endswith("\n" + LINE)
for label, to, text in (("to a background agent", "other-builder", ASK), ("to a front agent, rerouted", "other-front", ASK), ("held, no background agent", "solo-front", ASK),
                        ("to a project", "projects/beta", ASK), ("to a project, For <front agent>", "projects/beta", f"For other-front, {ASK}"),
                        ("naming a closed item only", "other-builder", "a2: please take this up again"), ("naming an id in backticks only", "other-builder", f"`a1` is the context: {ASK}")):
    fresh(); out = msg(to, text, "my-front"); settle()
    check(f"6 {label}: the line ends the reply, once", once(out), out)
for label, to, text, kw, sender in (("naming an open item, to a background agent", "other-builder", "a1: please build the export", {}, "my-front"),
                                    ("naming an open item, to a front agent", "other-front", "a1: please build the export", {}, "my-front"),
                                    ("naming an open item, to a project", "projects/beta", "a1: please build the export", {}, "my-front"),
                                    ("an fyi", "other-builder", ASK, {"fyi": True}, "my-front"), ("an fyi to a front agent", "other-front", ASK, {"fyi": True}, "my-front"),
                                    ("a no-action note", "other-builder", "the build is done, no action needed.", {}, "my-front"), ("a status report", "other-builder", "the PR is merged, the suites pass.", {}, "my-front"),
                                    ("an unlisted sender", "other-builder", ASK, {}, "second-front"), ("a script", "other-builder", ASK, {"origin": "home-test"}, "my-front")):
    fresh(); out = msg(to, text, sender, **kw); settle()
    check(f"6 {label}: no line", LINE not in out and "Refused" not in out, out)
fresh(); out = msg("no-such-session", ASK, "my-front"); settle()
check("6 a refusal carries no line", out.startswith("Refused") and LINE not in out, out)

# ---- 7. idle peers, the message tool
switches(None, True)
fresh(); out = msg("other-front", ASK, "second-front"); settle()
check("7 the person away: a front agent's message to a peer goes to the peer's background agent, the reply saying the peer is idle", idle_sent(out) and LINE not in out, out)
fresh(); stamp("other-front", 600); out = msg("other-front", ASK, "second-front"); settle()
check("7 an old stamp is away", idle_sent(out), out)
fresh(); stamp("other-front", 1); out = msg("other-front", ASK, "second-front"); settle()
check("7 the person there: held as before", peer_held(out) and got("other-builder") == [], out)
fresh(); stamp_file("other-front").mkdir(parents=True)
try:
    out = msg("other-front", ASK, "second-front"); settle()
    check("7 a presence that cannot be read counts as there: held", peer_held(out) and got("other-builder") == [], out)
finally: stamp_file("other-front").rmdir()
fresh(); real_here = telling.presence_here
def boom(*a, **k): raise RuntimeError("no presence")
telling.presence_here = boom
try:
    out = msg("other-front", ASK, "second-front"); settle()
    check("7 a presence test that fails: held", peer_held(out) and got("other-builder") == [], out)
finally: telling.presence_here = real_here
for label, text in (("a no-action note", "the build is done, no action needed."), ("a status report", "the PR is merged, the suites pass.")):
    fresh(); out = msg("other-front", text, "second-front"); settle()
    check(f"7 {label} is held as before", out.startswith("held for other-front's next turn (it is a done, taken or no-action note") and got("other-builder") == [], out)
fresh(); asked("other-front", "second-front"); out = msg("other-front", "the second one", "second-front"); settle()
check("7 an answer to the peer's own question takes the answer rule, not the switch", not out.startswith("Rerouted") and got("other-builder") == [] and waiting("other-front") == 1, out)
fresh(); out = msg("other-front", ASK, "second-front", fyi=True); settle()
check("7 an fyi is held for the peer", out.startswith("held for other-front's next turn (fyi") and got("other-builder") == [], out)
fresh(); out = msg("other-front", f"{mark()}\ndecide the export", "second-front"); settle()
check("7 a marked message is judged as before", not out.startswith("Rerouted") and got("other-builder") == [] and waiting("other-front") == 1, out)
fresh(); out = msg("solo-front", ASK, "second-front"); settle()
check("7 a project with no background agent: held as before", peer_held(out, front="solo-front"), out)
fresh(); failing("other-builder"); out = msg("other-front", ASK, "second-front"); settle()
check("7 a background agent that cannot take it: held as before", peer_held(out), out)
undo = retired("other-builder")
try:
    fresh(); out = msg("other-front", ASK, "second-front"); settle()
    check("7 a retired background agent: held as before, not sent to the project", peer_held(out) and not any(r.get("to") == "projects/beta" for r in mlog()), out)
finally: undo()
fresh(); out = msg("other-front", ASK, "outside-session"); settle()
check("7 a sender that is no front agent is passed as before", out.startswith("Not for ") and "Rerouted" not in out, out)
with hold_off():
    fresh(); out = msg("other-front", ASK, "second-front"); settle()
    check("7 the hold off: the pass of before, not the switch's", out.startswith("Not for ") and len(got("other-builder")) == 1, out)
switches(None, "true"); fresh(); out = msg("other-front", ASK, "second-front"); settle()
check("7 a string \"true\" leaves it off: held", peer_held(out) and got("other-builder") == [], out)
switches(["second-front"], True); fresh(); out = msg("other-front", "the build is done, no action needed.", "second-front"); settle()
check("7 both switches, a listed sender: the first one rules, a note too", rerouted(out, sender="second-front") and len(got("other-builder")) == 1, out)

# ---- 8. idle peers, the router's peer hold
switches(None, True)
def routed(text, **kw):
    fresh(); return sent("projects/beta", f"For other-front, {text}", "second-front", **kw)
n = routed(ASK); res = act(n, "other-front"); settle()
check("8 the person away: the router passes a peer front agent's message to the background agent", to_back(res) and "is not talking with other-front" in res.get("reason", ""), res)
n = routed(ASK); stamp("other-front", 1); res = act(n, "other-front"); settle()
check("8 the person there: held for the peer", res.get("ruling") == "held" and res.get("held_for") == "other-front" and got("other-builder") == [], res)
n = routed("the PR is merged, the suites pass."); res = act(n, "other-front"); settle()
check("8 a status report is held for the peer", res.get("ruling") == "held" and res.get("held_for") == "other-front" and got("other-builder") == [], res)
n = routed("the build is done, no action needed."); res = act(n, "other-front"); settle()
check("8 a no-action note is held for the peer", res.get("ruling") == "held" and res.get("held_for") == "other-front" and got("other-builder") == [], res)
n = routed(f"{ASK}\n{mark()} for later"); res = act(n, "other-front"); settle()
check("8 a message that carries the mark is held for the peer", res.get("ruling") == "held" and res.get("held_for") == "other-front" and got("other-builder") == [], res)
n = routed(ASK, fyi=True); res = act(n, "other-front"); settle()
check("8 an fyi is held for the peer", res.get("ruling") == "held" and res.get("held_for") == "other-front" and got("other-builder") == [], res)
fresh(); n = sent("projects/solo", f"For solo-front, {ASK}", "second-front"); res = act(n, "solo-front", key="projects/solo"); settle()
check("8 a project with no background agent: held for the peer", res.get("ruling") == "held" and res.get("held_for") == "solo-front", res)
switches(None, False); n = routed(ASK); res = act(n, "other-front"); settle()
check("8 the switch off: held for the peer", res.get("ruling") == "held" and res.get("held_for") == "other-front" and got("other-builder") == [], res)
switches(None, True); n = routed(ASK); failing("other-builder"); res = act(n, "other-front")
check("8 a failed delivery to the background agent is an error to try again", res.get("status") == "error" and res.get("target") == "other-builder", res)
res = act(n, "other-front", prior={**res, "tries": _live.MAX_TRIES}); settle()
check("8 …and after the last try it is held for the peer, as without the switch", res.get("ruling") == "held" and res.get("held_for") == "other-front" and waiting("other-front") == 1 and got("other-front") == [], res)

settle()
print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
