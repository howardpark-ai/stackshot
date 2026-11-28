"""Scenario test for the two switches that keep a front agent's work from waiting on an idle front agent - fixture data, no live store, no network, no server.

`[front] to_background_senders` (empty by default) lists front agents that send nothing to a front agent: their message to one goes to the target project's background agent (`messaging._gate_front` and the "For <front agent>" project message),
the router passes their messages there too (`router_live._front_reroute`, hook `front_reroute`), and a hand-off of theirs that names no open item gets one line at the end of its reply. `[front] idle_peers_to_background` (off by default) sends a
front agent's unmarked message to a peer front agent the person is not with to that project's background agent instead of holding it (the gate, and the router's peer hold, hook `front_idle`).

Covers:
  0. The two keys: defaults (nobody listed, off), a value of the wrong kind reads as the default and `config.notes` names it, only a TOML true turns the second on.
  1. Both switches off: the peer hold, the pass of a hand-off, the project message, the router's hold, no added line.
  2. A listed sender to a front agent: marked or not, fyi or not, a question, an answer, a note, its own project's front agent, the sender as a session id: the background agent takes it, with no refusal for any of these (the one refusal is 18's); an unlisted sender, a listed background agent and a script are untouched.
  3. No background agent, or one that cannot take it (a failed push, a retired session): held for the front agent's next turn, the reply saying why and to use a board item; where nothing can be held for it, the same reply and effect as with
     both switches off (delivered, or that path's own refusal); no send comes back on itself.
  4. A project message that opens "For <front agent>": the same; a front agent whose pane is gone can be held nothing, so the project takes the message.
  5. The router: a listed sender's message passed to a front agent goes to the background agent, never held for the front agent; a project with none is ruled as before; a background agent that cannot be reached has it held for the front agent,
     and when it cannot be held, ruled as with both switches off (never archived because of a switch), its tries counted anew; a notice delivered already is only ruled.
  6. The added line: present for a hand-off that names no open item (once, last), absent for a named open item, an fyi, a note, an unlisted sender, a script, a refusal.
  7. Idle peers, the message tool: to the background agent while the person is away; held while he is there, on a presence that cannot be read, for notes, answers, fyi, marked messages, no background agent, an agent that cannot take it.
  8. Idle peers, the router: the same for a pass to a peer front agent, and held for the peer after the background agent's deliveries failed (not ruled held when it cannot be filed, nor after a delivery).
  9. A background agent the fleet's registry lists as retired is passed over for a live second one, by both switches, in the message tool and the router; with none left the message is held as with no background agent.
 10. A presence that cannot be told (no pane row, a row file or a registry that does not read, a stamp that does not read or is from the future, no stamps at all) counts as there.
 11. A rerouted message leaves on the item it names the History line that holding it leaves: nothing goes to the front agent, no need or mover changes.
 12. The idle switch leaves a message with verified quoted words of the person, or one naming an item that waits on a decision or that he asked to be told about, as without it, in the message tool and the router.
 13. Where the reroute can neither deliver nor hold, the message tool does what it does with both switches off: delivered, written onto the item, or refused.
 14. The router never archives, because of either switch, a notice that is delivered with both off.
 15. A background agent whose pane is gone is passed over for the next live one.
 16. A listed sender is matched under its spellings: letter case, an id label, a number suffix, an old name after a rename; a name another session has taken since is not its own.
 17. What a listed sender writes reaches the background agent with its marks, quoted words and flags as written; what that agent can then send on to the front agent is what any background agent can.

  18. A listed sender's decision or step for the person (the mark or needs: decision, no note that nothing is needed) that names no open item of his is refused: nothing sent or held, the whole text in the message log.

    tests/run-suite front_reroute   -> exit 0 / 1"""
import contextlib, datetime, json, logging, os, pathlib, re, sys, threading, time

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
item(1); item(2, status="completed"); item(3, owner="other-front", needs=["decision"]); item(4, owner="other-front")
item(5, owner="other-builder", tell_him=["my-front"]); item(6, owner="other-builder", status="completed", tell_him=["other-front"]); item(7, owner="other-builder", status="completed", needs=["decision"])
item(10, owner="quiet-front", project="projects/quiet", needs=["decision"]); item(11, owner="second-front", project="projects/alpha", needs=["decision"]); item(12, owner="solo-front", project="projects/solo", needs=["decision"])
UNTOUCHED = {i: (T / f"store/a/{i}.json").read_text() for i in (3, 10)}      # as created: no History line yet
(T / "store/next-id").write_text("100")
push_log = T / "push.log"
(T / "fakepush.py").write_text("import sys, json, os, pathlib\na = sys.argv[1:]\nif a[:1] == ['--from']: a = a[2:]\n"
                               f"if (pathlib.Path({tmp!r}) / ('fail-' + a[0])).exists(): print('boom'); sys.exit(0)\n"
                               f"g = pathlib.Path({tmp!r}) / ('gone-' + a[0])\n"
                               "if g.exists(): print('queued (retired: ' + a[0] + ', retired in the test; ' + ('sent to projects/beta, where the router rules notice n1' if g.read_text() == 'sent' else 'no project takes its messages, so it was returned to my-front') + ') → ' + a[0]); sys.exit(0)\n"
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
    for p in [*T.glob("fail-*"), *T.glob("gone-*")]: p.unlink()
    push_log.unlink(missing_ok=True); _messaging.MSG_LOG.unlink(missing_ok=True)
    for name in NAMES: unstamp(name)
    stamp("outside-session", 600)          # the prompt hook has stamped some pane: a pane with no stamp beside it is away
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
@contextlib.contextmanager
def hold_off():
    had = _cfg.CFG["router"].get("hold_notices")
    _cfg.CFG["router"]["hold_notices"] = False
    try: yield
    finally:
        if had is None: _cfg.CFG["router"].pop("hold_notices", None)
        else: _cfg.CFG["router"]["hold_notices"] = had

@contextlib.contextmanager
def cannot_fetch(who):
    """This session's hook cannot fetch held lines: nothing can be held for it."""
    real = held.can_fetch
    held.can_fetch = lambda x, *a, **k: False if x in (who, ID[who]) else real(x, *a, **k)
    try: yield
    finally: held.can_fetch = real
def waiting_all(): return {w: waiting(w) for w in NAMES if waiting(w)}
def reached(): return sorted(next((n for n in NAMES if x[0] in (n, ID[n])), x[0]) for x in pushes())
def like_off(to, text, sender, table, prep=lambda: None, **kw):
    """The same send with the switches `table` and with both off, each from the same fresh state -> [(the reply less the item line, who got a turn, what is held for whom)] twice."""
    results = []
    for t in (table, (None, None)):
        switches(*t); fresh(); prep(); out = msg(to, text, sender, **kw); settle()
        results.append((re.sub(r"notice \w+|item_id=\"\w+\"", "N", out.replace("\n" + LINE, "")), reached(), waiting_all()))
    switches(*table)
    return results

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
                    ("the mark away from the first line", f"hello\n{mark()} a3: decide whether the export ships"),
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
for label, text, kw in (("unmarked", ASK, {}), ("marked, naming his item", f"{mark()}\na12: decide the export", {}), ("an fyi", ASK, {"fyi": True}), ("a question", "which one?", {"question": True})):
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
    check("3 the front agent and its background agent both retired: the message goes to the project once and no send comes back on itself", out.startswith("'other-front' is retired") and "held for the router" in out and out.count(LINE) == 1 and len(mlog()) == 1, (out, mlog()))
finally: undo()
undo = retired("solo-front")
try:
    fresh(); out = msg("solo-front", f"For solo-front, {ASK}", "my-front"); settle()
    check("3 a retired front agent with no background agent: to the project, once", out.startswith("'solo-front' is retired") and "held for the router" in out and len(mlog()) == 1, (out, mlog()))
finally: undo()
on, off = like_off("quiet-front", ASK, "my-front", (["my-front"], None))
check("3 a front agent whose hook cannot fetch held lines, no background agent: as with the switches off", on == off and off[0].startswith("not passed on — quiet-front is a front agent") and off[1:] == ([], {}), (on, off))
with hold_off():
    on, off = like_off("solo-front", ASK, "my-front", (["my-front"], None))
    check("3 the hold off and no background agent: the refusal of the switches off", on == off and off[0].startswith("Refused") and "(to='projects/solo'" in off[0] and off[1:] == ([], {}), (on, off))
    fresh(); out = msg("other-front", ASK, "my-front"); settle()
    check("3 the hold off and a background agent: rerouted all the same", rerouted(out) and len(got("other-builder")) == 1, out)
    on, off = like_off("other-front", ASK, "my-front", (["my-front"], None), prep=lambda: failing("other-builder"))
    check("3 the hold off and a background agent that cannot take it: the refusal of the switches off", on == off and off[0].startswith("Refused") and "other-builder" in off[0] and "sends nothing to front agents" not in off[0] and off[1:] == ([], {}), (on, off))

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

sessions_file = T / "fleet/a/sessions.json"; machine_file = T / "fleet/a/machine.json"
@contextlib.contextmanager
def pane_gone(who):
    """The session's pane has been gone for two hours while its machine is online: the address check refuses a send to it."""
    rows, machine = sessions_file.read_text(), machine_file.read_text()
    changed = json.loads(rows)
    changed[ID[who]]["gone"] = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=2)).isoformat(timespec="seconds").replace("+00:00", "Z")
    sessions_file.write_text(json.dumps(changed)); machine_file.write_text(json.dumps({**json.loads(machine), "online": {"ok": True}}))
    try: yield
    finally: sessions_file.write_text(rows); machine_file.write_text(machine)
with pane_gone("solo-front"):
    fresh(); out = msg("solo-front", ASK, "second-front"); settle()
    check("4 the fixture's gone pane is one a send is refused for", out.startswith("Refused") and "pane has been gone" in out, out)
    fresh(); out = msg("projects/solo", f"For solo-front, {ASK}", "my-front"); settle()
    check("4 a front agent whose pane is gone, no background agent: the project takes it, with no refusal that says to send it there", out.startswith("held for the router") and out.count(LINE) == 1 and waiting("solo-front") == 0, out)
with pane_gone("other-front"):
    fresh(); failing("other-builder"); out = msg("projects/beta", f"For other-front, {ASK}", "my-front"); settle()
    check("4 a front agent whose pane is gone and a background agent that cannot take it: the project takes it", out.startswith("held for the router") and waiting("other-front") == 0, out)
    fresh(); out = msg("projects/beta", f"For other-front, {ASK}", "my-front"); settle()
    check("4 a front agent whose pane is gone and a live background agent: rerouted", rerouted(out) and len(got("other-builder")) == 1, out)
def found_retired(how, *who):
    for w in who or ("other-builder",):
        for ref in (w, ID[w]): (T / f"gone-{ref}").write_text(how)
fresh(); found_retired("sent"); out = msg("other-front", ASK, "my-front"); settle()
check("4 a push that answers queued (retired: ...; sent to a project): the reply does not say the background agent got it", "turned out retired and did not get it: queued (retired:" in out and "so it went to" not in out, out)
on, off = like_off("other-front", ASK, "my-front", (["my-front"], None), prep=lambda: found_retired("returned"))
check("4 a push that answers queued (retired: ...; returned): nobody has it, so as with the switches off: held for the front agent", on == off and off[2] == {"other-front": 1} and "turned out retired" not in on[0], (on, off))
fresh()

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
failed = {**res, "tries": _live.MAX_TRIES}
res = act(n, "other-front", prior=failed); settle()
check("5 …and after the last try it is held for the front agent, which gets no turn", res.get("ruling") == "held" and res.get("held_for") == "other-front" and "could not be reached" in res.get("reason", "") and pushes() == [] and waiting("other-front") == 1, res)
res = act(n, "other-front", prior={**res, "status": "error", "stage": "rule", "tries": _live.MAX_TRIES + 1}); settle()
check("5 …a ruling that failed to write holds it once and delivers nothing on the retry", res.get("ruling") == "held" and waiting("other-front") == 1 and pushes() == [], (res, pushes()))
@contextlib.contextmanager
def unfiled():
    """The front gate files nothing: the agent's hook cannot fetch held lines."""
    real = _live._HOOKS["front_fyi"]
    _live._HOOKS["front_fyi"] = lambda *a, **k: ("held", "its hook cannot fetch held lines")
    try: yield
    finally: _live._HOOKS["front_fyi"] = real
def route_like_off(text, table, sender="my-front", target="other-front", key="projects/beta", prior=None, off_prior=None, prep=lambda: None, around=contextlib.nullcontext, **ln):
    """The same notice ruled with the switches `table` and `prior`, and with both off and `off_prior`, each from the same fresh state -> [(status, ruling, target, held for, marked, who got a turn, what is held)] twice, and the first line."""
    results, first = [], None
    for t, p in ((table, prior), ((None, None), off_prior)):
        switches(); fresh(); n = sent(key, text, sender); fresh(); switches(*t); prep()
        with around(): res = act(n, target, key=key, prior=p, **ln); settle()
        first = first or res
        results.append((res.get("status"), res.get("ruling"), res.get("target") or "", res.get("held_for") or "", bool(res.get("marked")), reached(), waiting_all()))
    switches(*table)
    return results[0], results[1], first
HIS = f"{mark()}\na3: decide whether the export ships"
def he_is_there(): stamp("other-front", 1)
on, off, res = route_like_off(f"For other-front, {ASK}", (["my-front"], None), prior=failed, around=unfiled)
check("5 …and when it cannot be filed it is ruled as with the switches off, the tries before not counted", on == off and res.get("switches_off") == _live.MAX_TRIES and not res.get("reroute_from"), (on, off, res))
switches(["my-front"])
fresh(); failing("other-builder"); n = sent("projects/beta", ASK, "my-front"); res = act(n, "other-builder", rule="anchor-item")
check("5 the background agent as the ruling's own target, a failed delivery: tried again", res.get("status") == "error", res)
res = act(n, "other-builder", rule="anchor-item", prior={**res, "tries": _live.MAX_TRIES}); settle()
check("5 …after the last try the fallback to the front agent holds it, never a turn", res.get("ruling") == "held" and res.get("held_for") == "other-front" and pushes() == [] and waiting("other-front") == 1, res)
tried = {"status": "error", "target": "other-builder", "tries": _live.MAX_TRIES}
on, off, res = route_like_off(ASK, (["my-front"], None), target="other-builder", rule="anchor-item", prior=tried, off_prior=tried, around=unfiled)
check("5 …and when it cannot be filed the fallback goes on as with the switches off", on == off and res.get("switches_off") == 0, (on, off, res))
switches(["my-front"])
fresh(); n = sent("projects/beta", f"For other-front, {ASK}", "my-front")
res = act(n, "other-front", prior={"status": "delivered", "stage": "rule", "target": "other-front", "outcome": "delivered"}); settle()
check("5 a notice delivered already is only ruled: not rerouted afterwards", res.get("status") == "ruled" and res.get("target") == "other-front" and pushes() == [], res)
fresh(); n = sent("projects/beta", f"For other-front, {ASK}", "my-front")
res = act(n, "other-front", prior={"status": "delivered", "stage": "rule", "target": "other-builder", "reroute_from": "other-front", "outcome": "delivered", "tries": _live.MAX_TRIES}); settle()
check("5 …and not held for the front agent afterwards, whatever the count of failures", res.get("status") == "ruled" and res.get("ruling") == "passed" and waiting("other-front") == 0 and pushes() == [], res)
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
n = routed(ASK); last = {"status": "error", "target": "other-builder", "idle_from": "other-front", "tries": _live.MAX_TRIES}
with unfiled(): res = act(n, "other-front", prior=last); settle()
check("8 a line that cannot be filed is not ruled held", res.get("ruling") != "held" and not res.get("held_for") and waiting("other-front") == 0, res)
n = routed(ASK); res = act(n, "other-front", prior={**last, "status": "delivered", "stage": "rule", "outcome": "delivered"}); settle()
check("8 a notice delivered already is only ruled, not held afterwards", res.get("status") == "ruled" and res.get("ruling") == "passed" and waiting("other-front") == 0 and pushes() == [], res)

# ---- 9. a retired background agent, by the fleet's registry
from stackshot.fleet import sessions_registry as _sessreg
@contextlib.contextmanager
def registry_retired(*who):
    """The fleet's own registry lists these names on retired rows only; the pages still list them."""
    had = _cfg.CFG["client"].get("session_links")
    path = T / "links/a/session-registry.json"; path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema": 1, "machine": "a", "sessions": {ID[w]: {"id": ID[w], "name": w, "state": "retired", "transcripts": []} for w in who}}))
    _cfg.CFG["client"]["session_links"] = str(T / "links"); _sessreg._CACHE["at"] = -1e9
    try:
        assert all(_sessreg.retired(w) for w in who), who
        yield
    finally:
        _cfg.CFG["client"]["session_links"] = had; path.unlink(); _sessreg._CACHE["at"] = -1e9
with registry_retired("my-builder"):
    switches(["my-front"])
    fresh(); out = msg("second-front", ASK, "my-front"); settle()
    check("9 the message tool, a listed sender: the live second background agent takes it", rerouted(out, back="my-docs", front="second-front", project="projects/alpha") and len(got("my-docs")) == 1 and got("my-builder") == [], out)
    fresh(); out = msg("projects/alpha", f"For second-front, {ASK}", "my-front"); settle()
    check("9 …a project message that opens For <front agent> too", rerouted(out, back="my-docs", front="second-front", project="projects/alpha") and got("my-builder") == [], out)
    fresh(); n = sent("projects/alpha", f"For second-front, {ASK}", "my-front"); res = act(n, "second-front", key="projects/alpha"); settle()
    check("9 …the router too", to_back(res, back="my-docs", front="second-front") and got("my-builder") == [], res)
    switches(None, True)
    fresh(); out = msg("second-front", ASK, "my-front"); settle()
    check("9 the message tool, an idle peer: the live second background agent takes it", out.startswith("Rerouted: second-front is idle") and len(got("my-docs")) == 1 and got("my-builder") == [], out)
    fresh(); n = sent("projects/alpha", f"For second-front, {ASK}", "my-front"); res = act(n, "second-front", key="projects/alpha"); settle()
    check("9 …the router too", to_back(res, back="my-docs", front="second-front") and got("my-builder") == [], res)
with registry_retired("other-builder"):
    switches(["my-front"])
    fresh(); out = msg("other-front", ASK, "my-front"); settle()
    check("9 no live background agent, the message tool: held for the front agent, the reply saying so", held_back(out, "other-front", "projects/beta has no live background agent") and got("other-builder") == [], out)
    fresh(); n = sent("projects/beta", f"For other-front, {ASK}", "my-front"); res = act(n, "other-front"); settle()
    check("9 …the router: nothing is queued for the retired builder, the pass is ruled as before", res.get("ruling") == "held" and res.get("held_for") == "other-front" and got("other-builder") == [] and waiting("other-builder") == 0, res)
    switches(None, True)
    fresh(); out = msg("other-front", ASK, "second-front"); settle()
    check("9 no live background agent, an idle peer: held for the peer", peer_held(out) and got("other-builder") == [], out)
    n = routed(ASK); res = act(n, "other-front"); settle()
    check("9 …the router too", res.get("ruling") == "held" and res.get("held_for") == "other-front" and got("other-builder") == [] and waiting("other-builder") == 0, res)

# ---- 10. a presence that cannot be told counts as there
row_file = T / f"cli/{os.getpid()}-other-front.json"
def no_row():
    row_file.unlink()
    return lambda: pane("other-front")
def bad_row():
    row_file.write_text("{not json")
    return lambda: pane("other-front")
def no_registry():
    had = handoff_svc.CLI_SESSIONS; handoff_svc.CLI_SESSIONS = T / "no-such-folder"
    return lambda: setattr(handoff_svc, "CLI_SESSIONS", had)
def bad_stamp():
    stamp_file("other-front").mkdir(parents=True)
    return lambda: stamp_file("other-front").rmdir()
def future_stamp():
    stamp("other-front", -600)
    return lambda: unstamp("other-front")
def no_stamps():
    unstamp("outside-session")
    return lambda: None
for label, setup in (("no pane row", no_row), ("a row file that does not read", bad_row), ("a registry that is not there", no_registry), ("a stamp that does not read", bad_stamp),
                     ("a stamp from the future", future_stamp), ("no stamp of any pane", no_stamps)):
    switches(None, True); n = routed(ASK); undo = setup()
    try:
        res = act(n, "other-front"); settle()
        check(f"10 {label}, the router: held for the peer", res.get("ruling") == "held" and res.get("held_for") == "other-front" and got("other-builder") == [], res)
        for p in held.dir_().glob("*.jsonl"): p.unlink()
        out = msg("other-front", ASK, "second-front"); settle()
        check(f"10 {label}, the message tool: held for the peer", peer_held(out) and got("other-builder") == [], out)
    finally: undo()
fresh()
check("10 a pane with no stamp beside another pane's stamp is away; a caller that does not ask otherwise reads an untold presence as away, as before",
      telling.presence_here("other-front", unread=True) is False and telling.presence_here("no-such-pane") is False and telling.presence_here("no-such-pane", unread=True) is True)

# ---- 11. the History line on the item a rerouted message names
item_file = T / "store/a/4.json"
pristine = item_file.read_text()
def history(): return [x["text"] for x in ((json.loads(item_file.read_text())["metadata"].get("front_quiet") or {}).get("log") or [])]
def traced(back="other-builder"):
    meta = json.loads(item_file.read_text())["metadata"]; was = json.loads(pristine)["metadata"]
    return (len(history()) == 1 and history()[0].startswith(f"other-front was not told (it went to {back}, the project's background agent): ") and "weekly page" in history()[0]
            and all(meta.get(k) == was.get(k) for k in ("owner", "mover", "needs", "next")) and got("other-front") == [] and waiting("other-front") == 0)
def restart():
    fresh(); item_file.write_text(pristine)
NAMED = f"a4: {ASK}"
for label, table, to, text, sender, kw in (("a listed sender", (["my-front"], None), "other-front", NAMED, "my-front", {}), ("its fyi", (["my-front"], None), "other-front", NAMED, "my-front", {"fyi": True}),
                                           ("its project message", (["my-front"], None), "projects/beta", f"For other-front, {NAMED}", "my-front", {}),
                                           ("an idle peer", (None, True), "other-front", NAMED, "second-front", {})):
    switches(*table); restart(); out = msg(to, text, sender, **kw); settle()
    check(f"11 the message tool, {label}: one History line on the named item, nothing for the front agent, needs and mover as they were", out.startswith("Rerouted:") and traced(), (out, history()))
for label, table, sender, kw in (("a listed sender", (["my-front"], None), "my-front", {}), ("its fyi, held for the background agent", (["my-front"], None), "my-front", {"fyi": True}), ("an idle peer", (None, True), "second-front", {})):
    switches(*table); restart(); n = sent("projects/beta", f"For other-front, {NAMED}", sender, **kw); item_file.write_text(pristine); res = act(n, "other-front"); settle()
    check(f"11 the router, {label}: the same line", (res.get("target") == "other-builder" or res.get("held_for") == "other-builder") and traced(), (res, history()))
switches(["my-front"]); restart(); n = sent("projects/beta", f"For other-front, {NAMED}", "my-front"); item_file.write_text(pristine); failing("other-builder"); res = act(n, "other-front"); settle()
check("11 a delivery that failed leaves no line", res.get("status") == "error" and history() == [], (res, history()))
switches(); restart(); out = msg("other-builder", NAMED, "my-front"); settle()
check("11 a message that was moved off no front agent leaves no such line", out.startswith("delivered") and history() == [], (out, history()))
item_file.write_text(pristine)

# ---- 12. what the idle switch leaves as it is
QUOTE = "hand the export to the second desk"
said_now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
(T / f"transcripts/-x/{ID['second-front']}.jsonl").write_text(json.dumps({"type": "user", "uuid": "aaaaaaaa-aaaa-4aaa-8aaa-000000000001", "timestamp": said_now, "origin": {"kind": "human"},
                                                                          "message": {"role": "user", "content": f"Oliver here: {QUOTE}, please"}}) + "\n", encoding="utf-8")
ACKED = f'Acked-by: "{QUOTE}" (just now, session second-front)'
bad_item = T / "store/a/8.json"
KEPT = (("verified quoted words, the session named", f"{ASK}\n{ACKED}"),
        ("verified quoted words, no session named: the sender's own", f'{ASK}\nAcked-by: "{QUOTE}" (just now)'),
        ("verified quoted words on the second Acked-by line", f'{ASK}\nAcked-by: "words he never said at all" (just now)\n{ACKED}'),
        ("a tell-him item, another agent's ask", f"a5: {ASK}"),
        ("a closed tell-him item", f"a6: {ASK}"),
        ("an item that waits on a decision", f"a3: {ASK}"),
        ("an item that cannot be read", f"a8: {ASK}"))
MOVED_ON = (("words that are not in his message", f'{ASK}\nAcked-by: "words he never said at all" (just now)'),
            ("an open item that waits on nothing of his", f"a1: {ASK}"),
            ("a closed item that still carries the decision need", f"a7: {ASK}"))
bad_item.write_text("{not json")
try:
    for label, text in KEPT:
        on, off = like_off("other-front", text, "second-front", (None, True))
        check(f"12 the message tool, {label}: as with the switch off, nothing for the background agent", on == off and "other-builder" not in on[1] and "other-builder" not in on[2], (on, off))
        if label.startswith("an item that cannot"): continue          # the router's own reading of an item that does not read is not this switch's
        on, off, res = route_like_off(f"For other-front, {text}", (None, True), sender="second-front")
        check(f"12 the router, {label}: as with the switch off", on == off and not res.get("idle_from"), (on, off, res))
finally: bad_item.unlink()
for label, text in MOVED_ON:
    switches(None, True); fresh(); out = msg("other-front", text, "second-front"); settle()
    check(f"12 the message tool, {label}: the background agent takes it", idle_sent(out), out)
    n = routed(text); res = act(n, "other-front"); settle()
    check(f"12 the router, {label}: the background agent takes it", to_back(res), res)
switches(None, True)
n = routed(f"{ASK}\n{ACKED}")
check("12 the router's hook itself: False for quoted words, True without them", _messaging.router_idle_peer("other-front", str(n.get("who") or ""), _live._body(n)) is False
      and _messaging.router_idle_peer("other-front", str(n.get("who") or ""), _live._body(routed(ASK))) is True, n)

# ---- 13. nothing can be delivered by the reroute or held: the message tool does what it does with the switches off
def failing_there():
    failing("other-builder"); stamp("other-front", 1)
LISTED = (["my-front"], None)
with cannot_fetch("other-front"):
    on, off = like_off("other-front", HIS, "my-front", LISTED, prep=failing_there)
    check("13 a failed background agent and a front agent nothing can be held for, a turn due: delivered to it", on == off and off[1] == ["other-front"] and off[0].startswith("delivered"), (on, off))
    on, off = like_off("other-front", ASK, "my-front", LISTED, prep=lambda: failing("other-builder"))
    check("13 …no turn due: what the switches off say, nothing held", on == off and off[1:] == ([], {}) and "could not be rerouted" not in on[0], (on, off))
    on, off = like_off("projects/beta", f"For other-front, {ASK}", "my-front", LISTED, prep=lambda: failing("other-builder"))
    check("13 …a project message that opens For <front agent>: to the page", on == off and off[0].startswith("held for the router"), (on, off))
    switches(*LISTED); fresh(); failing("other-builder"); out = msg("projects/beta", f"For other-front, {ASK}", "my-front"); settle()
    check("13 …the item line ends that reply once", out.count(LINE) == 1 and out.endswith("\n" + LINE), out)
    on, off = like_off("other-front", ASK, "second-front", (None, True), prep=lambda: failing("other-builder"))
    check("13 …an idle peer too", on == off and off[1:] == ([], {}), (on, off))
def quiet_log(i): return ((json.loads((T / f"store/a/{i}.json").read_text())["metadata"].get("front_quiet") or {}).get("log") or [])
(T / "store/a/10.json").write_text(UNTOUCHED[10])
on, off = like_off("quiet-front", f"{mark()}\na10: decide whether the export ships", "my-front", LISTED, prep=lambda: stamp("quiet-front", 1))
check("13 no background agent and a front agent whose hook cannot fetch, a turn due: delivered to it", on == off and off[1] == ["quiet-front"], (on, off))
check("13 …and no History line is written for a hold that cannot be", quiet_log(10) == [], quiet_log(10))
with cannot_fetch("other-front"):
    switches(*LISTED); fresh(); failing("other-builder"); out = msg("projects/Beta", f"For other-front, {ASK}", "my-front"); settle()
    check("13 a call handled again says each thing about it once (a page key spelled another way)", out.startswith("held for the router") and out.count("sent there") == 1, out)
on, off = like_off("projects/quiet", f"For quiet-front, {ASK}", "my-front", LISTED)
check("13 …the project message too", on == off and off[0].startswith("held for the router"), (on, off))
real_add = held.add
held.add = lambda *a, **k: False
try:
    on, off = like_off("solo-front", ASK, "my-front", LISTED)
    check("13 a hold the store does not take: what the switches off say", on == off and off[1:] == ([], {}) and "could not be rerouted" not in on[0], (on, off))
    on, off = like_off("solo-front", f"{mark()}\na12: decide whether the export ships", "my-front", LISTED, prep=lambda: stamp("solo-front", 1))
    check("13 …a turn due: delivered", on == off and off[1] == ["solo-front"], (on, off))
finally: held.add = real_add
with pane_gone("solo-front"):
    on, off = like_off("solo-front", ASK, "my-front", LISTED)
    check("13 a front agent whose pane is gone, no background agent: the refusal of the switches off", on == off and off[0].startswith("Refused") and "pane has been gone" in off[0], (on, off))

# ---- 14. the router: neither switch archives a notice that is delivered with both off
for label, kw in (("the front agent's hook cannot fetch held lines", {"around": lambda: cannot_fetch("other-front")}), ("the hold off", {"around": hold_off}), ("the gate files nothing", {"around": unfiled})):
    (T / "store/a/3.json").write_text(UNTOUCHED[3])
    on, off, res = route_like_off(f"For other-front, {HIS}", LISTED, prior=failed, prep=he_is_there, **kw)
    check(f"14 …{label}: no History line for a hold that cannot be", quiet_log(3) == [], quiet_log(3))
    check(f"14 a listed sender, {label}, a turn due: delivered to the front agent, not archived", on == off and off[1] == "passed" and off[5] == ["other-front"] and res.get("switches_off") == _live.MAX_TRIES, (on, off, res))
    on, off, res = route_like_off(HIS, LISTED, target="other-builder", rule="anchor-item", prior=tried, off_prior=tried, prep=he_is_there, **kw)
    check(f"14 …after the fallback from the background agent itself, {label}: delivered", on == off and off[1] == "passed" and off[5] == ["other-front"] and res.get("switches_off") == 0, (on, off, res))
with pane_gone("other-front"):
    on, off, res = route_like_off(f"For other-front, {HIS}", LISTED, prior=failed, prep=he_is_there)
    check("14 …a front agent whose pane is gone: nothing is filed for it, ruled as with the switches off", on == off and not on[6] and res.get("switches_off") == _live.MAX_TRIES, (on, off, res))
idle_last = {"status": "error", "target": "other-builder", "idle_from": "other-front", "tries": _live.MAX_TRIES}
for label, text, prep in (("no turn due", ASK, lambda: None), ("a turn due", HIS, he_is_there)):
    on, off, res = route_like_off(f"For other-front, {text}", (None, True), sender="second-front", prior=idle_last, prep=prep, around=lambda: cannot_fetch("other-front"))
    check(f"14 an idle peer nothing can be held for, {label}: as with the switch off, not sent to the background agent again", on == off and "other-builder" not in on[5] and res.get("switches_off") == _live.MAX_TRIES and not res.get("idle_from"), (on, off, res))
# the tries of the path with the switches off are counted from where it began
switches(["other-front"]); fresh(); n = sent("projects/alpha", f"For second-front, {mark()}\na11: decide whether the export ships", "other-front"); fresh(); stamp("second-front", 1); failing("second-front")
first = {"status": "error", "target": "my-builder", "reroute_from": "second-front", "tries": _live.MAX_TRIES}
with cannot_fetch("second-front"):
    res = act(n, "second-front", key="projects/alpha", prior=first); settle()
    check("14 the first try with the switches off goes to the front agent", res.get("status") == "error" and res.get("target") == "second-front" and res.get("switches_off") == _live.MAX_TRIES and got("my-builder") == [], res)
    for more in (1, 2):
        res = act(n, "second-front", key="projects/alpha", prior={**res, "tries": _live.MAX_TRIES + more}); settle()
        check(f"14 after {more} failed of them it is tried again, not rerouted and not given up", res.get("status") == "error" and res.get("target") == "second-front" and res.get("switches_off") == _live.MAX_TRIES and pushes() == [], res)
    res = act(n, "second-front", key="projects/alpha", prior={**res, "tries": 2 * _live.MAX_TRIES}); settle()
    check("14 …and after three of them the ordinary fallback takes over", res.get("source") == "fallback" and res.get("switches_off") == _live.MAX_TRIES and got("second-front") == [], res)
    fresh(); res = act(n, "second-front", key="projects/alpha", prior={"status": "delivered", "stage": "rule", "target": "second-front", "outcome": "delivered", "switches_off": _live.MAX_TRIES, "tries": _live.MAX_TRIES + 1}); settle()
    check("14 a line delivered on that path and not yet ruled is only ruled", res.get("status") == "ruled" and res.get("target") == "second-front" and pushes() == [] and waiting("second-front") == 0, res)

# ---- 15. a background agent whose pane is gone
with pane_gone("my-builder"):
    switches(["my-front"])
    fresh(); out = msg("second-front", ASK, "my-front"); settle()
    check("15 the message tool, a listed sender: the next live background agent takes it", rerouted(out, back="my-docs", front="second-front", project="projects/alpha") and len(got("my-docs")) == 1 and got("my-builder") == [], out)
    fresh(); n = sent("projects/alpha", f"For second-front, {ASK}", "my-front"); res = act(n, "second-front", key="projects/alpha"); settle()
    check("15 …the router too", to_back(res, back="my-docs", front="second-front") and got("my-builder") == [], res)
    switches(None, True)
    fresh(); out = msg("second-front", ASK, "my-front"); settle()
    check("15 the message tool, an idle peer: the next live one", out.startswith("Rerouted: second-front is idle") and len(got("my-docs")) == 1 and got("my-builder") == [], out)
    fresh(); n = sent("projects/alpha", f"For second-front, {ASK}", "my-front"); res = act(n, "second-front", key="projects/alpha"); settle()
    check("15 …the router too", to_back(res, back="my-docs", front="second-front") and got("my-builder") == [], res)
with pane_gone("other-builder"):
    switches(["my-front"]); fresh(); out = msg("other-front", ASK, "my-front"); settle()
    check("15 every background agent's pane gone: held for the front agent", held_back(out, "other-front", "projects/beta has no live background agent") and got("other-builder") == [], out)

# ---- 16. the spellings of a listed sender
def sends(sender, listed=("my-front",)):
    switches(list(listed)); fresh(); out = msg("other-front", ASK, sender); settle()
    return out
for label, sender in (("another letter case", "My-Front"), ("an id label", f"my-front ({ID['my-front'][:8]}…)"), ("an id with a label", f"{ID['my-front']} (my-front)"),
                      ("a number suffix", "my-front-2"), ("a number suffix and a label", f"MY-FRONT-12 ({ID['my-front'][:8]}…)")):
    out = sends(sender)
    check(f"16 the message tool, {label}: matched", rerouted(out) and len(got("other-builder")) == 1, out)
    check(f"16 the router's hook, {label}: matched", _messaging.router_to_background(sender) == "my-front", _messaging.router_to_background(sender))
check("16 a longer name that only starts alike is not matched", _messaging.router_to_background("my-front-desk") == "" and _messaging.router_to_background("my-front2000") == "", "")
check("16 a script with a listed name is not matched", _messaging.router_to_background("my-front (a script on home-test)") == "", "")
FRONT_ROLE = {"role": "front", "project": "projects/alpha"}
switches(["my-front"])
check("16 a page that lists the name in other letters: matched", _messaging._to_background_sender("My-Front", {}, {"My-Front": FRONT_ROLE}) == "My-Front", "")
check("16 an agent a page lists under a numbered name is not its base", _messaging._to_background_sender("my-front-2", {}, {"my-front": FRONT_ROLE, "my-front-2": FRONT_ROLE}) == "", "")
switches(["my-front-2"])
check("16 a listed numbered name is itself, not its base", _messaging.router_to_background("my-front-2") != "" and _messaging.router_to_background("my-front") == "", "")
@contextlib.contextmanager
def registry(rows):
    """The fleet's own registry holds these rows: id -> (name, state, aliases)."""
    had = _cfg.CFG["client"].get("session_links")
    path = T / "links/a/session-registry.json"; path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema": 1, "machine": "a", "sessions": {i: {"id": i, "name": nm, "state": st, "aliases": al, "transcripts": []} for i, (nm, st, al) in rows.items()}}))
    _cfg.CFG["client"]["session_links"] = str(T / "links"); _sessreg._CACHE["at"] = -1e9
    try: yield
    finally:
        _cfg.CFG["client"]["session_links"] = had; path.unlink(); _sessreg._CACHE["at"] = -1e9
TWIN = "abababab-abab-4bab-8bab-abababababab"
with registry({ID["my-front"]: ("my-front", "live", ["desk-one"])}):
    switches(["my-front"])
    check("16 an old name after a rename sends: matched by the name the page lists", _messaging.router_to_background("desk-one") == "my-front", _messaging.router_to_background("desk-one"))
    out = sends("desk-one")
    check("16 …in the message tool too", rerouted(out), out)
    switches(["desk-one"])
    check("16 the key lists the old name: the renamed sender is matched", _messaging.router_to_background("my-front") == "my-front", _messaging.router_to_background("my-front"))
with registry({TWIN: ("my-front-2", "live", [])}):
    switches(["my-front"])
    check("16 a registry name with a number suffix, sent by its id: matched", _messaging.router_to_background(TWIN) == "my-front", _messaging.router_to_background(TWIN))
with registry({ID["my-front"]: ("my-front", "live", []), TWIN: ("my-front", "live", [])}):
    switches(["my-front"])
    check("16 a session id whose registry name two sessions carry: matched by that name", _messaging.router_to_background(TWIN) == "my-front", _messaging.router_to_background(TWIN))
with registry({ID["my-front"]: ("my-front", "live", ["desk-two"]), TWIN: ("desk-two", "live", [])}):
    switches(["desk-two"])
    check("16 an old name another session has taken since is not the sender's own", _messaging.router_to_background("my-front") == "", _messaging.router_to_background("my-front"))

# ---- 17. what reaches the background agent, and what it can send on
FULL = f"{mark()}\na3: decide whether the export ships\n{ACKED}\nneeds: decision"
switches(["second-front"]); fresh(); out = msg("other-front", FULL, "second-front"); settle()
check("17 the message tool: the background agent's line carries the text with its mark, quoted words and needs line as written", rerouted(out, sender="second-front") and FULL in got("other-builder")[0][1], (out, pushes()))
fresh(); out = msg("other-front", FULL, "second-front", fyi=True); settle()
check("17 …a marked fyi too", rerouted(out, sender="second-front") and FULL in got("other-builder")[0][1], (out, pushes()))
fresh(); out = msg("other-front", f"{ASK}\n{ACKED}", "second-front", fyi=True); settle()
taken = str(held.take(ID["other-builder"], "other-builder"))
check("17 …an unmarked fyi's held line keeps the quoted words", rerouted(out, sender="second-front") and ACKED in taken, (out, taken))
fresh(); n = sent("projects/beta", f"For other-front, {FULL}", "second-front"); fresh(); switches(["second-front"]); res = act(n, "other-front"); settle()
check("17 the router: the same", res.get("target") == "other-builder" and FULL in got("other-builder")[0][1], (res, pushes()))
switches(["my-front"])
fresh(); stamp("other-front", 1); out = msg("other-front", HIS, "other-builder"); settle()
check("17 the background agent can send a marked decision on while he is with the front agent: a turn", out.startswith("delivered") and len(got("other-front")) == 1, out)
fresh(); out = msg("other-front", HIS, "other-builder"); settle()
check("17 …while he is not, it is written onto the item it names, no turn", out.startswith("Not delivered: written onto a3") and got("other-front") == [], out)
fresh(); stamp("other-front", 1); out = msg("other-front", f"{ASK}\n{ACKED}", "other-builder"); settle()
check("17 quoted words it relays unmarked are held for the front agent's next turn, no turn", out.startswith("held for other-front's next turn") and got("other-front") == [] and waiting("other-front") == 1 and QUOTE in str(held.take(ID["other-front"], "other-front")), out)
fresh(); asked("other-front", "my-front"); stamp("other-front", 1); out = msg("other-front", "the second one", "other-builder"); settle()
check("17 an answer it relays to a question the front agent put to the listed sender is no answer of its own: held, no turn", out.startswith("held for other-front's next turn") and got("other-front") == [] and waiting("other-front") == 1, out)


# ---- 18. a listed sender's decision or step for the person that names no open item of his would reach him nowhere: refused
BARE = f"{mark()}\ndecide whether the export ships on Friday\n{ACKED}"
def off_board(out): return out.startswith(f"Refused: my-front sends nothing to front agents, so a decision or step for {OWNER} reaches him on the board") and pushes() == [] and waiting_all() == {}
def logged(): return [r for r in mlog() if r["outcome"].startswith("not delivered: it carries a decision or step")]
switches(["my-front"])
for label, text, kw in (("marked, naming no item", BARE, {}), ("the mark away from the first line", f"hello\n{mark()} decide whether the export ships", {}), ("needs: decision with no mark", f"{ASK}\nneeds: decision", {}),
                        ("naming an item that is not his", f"{mark()}\na4: decide whether the export ships", {}), ("naming a closed item", f"{mark()}\na7: decide whether the export ships", {}),
                        ("a marked fyi", BARE, {"fyi": True}), ("a marked question", BARE, {"question": True})):
    for how, to, sent_ in (("by name", "other-front", text), ("as For <front agent>", "projects/beta", f"For other-front, {text}")):
        fresh(); stamp("other-front", 1); n0 = len(routing.read("projects/beta")); out = msg(to, sent_, "my-front", **kw); settle()
        check(f"18 {label}, {how}: refused, nothing sent, held or left for the router, and logged", off_board(out) and len(routing.read("projects/beta")) == n0 and len(logged()) == 1 and len(mlog()) == 1, (out, mlog()))
fresh(); out = msg("other-front", BARE, "my-front"); settle()
check("18 the message log keeps the whole text, quoted words included, and the reply says what to do", [r["text"] for r in logged()] == [BARE] and "send it again naming that item" in out, (out, mlog()))
fresh()
try: _messaging._message("other-front", BARE, "my-front"); kind_ = ""
except _messaging.Refused as e: kind_ = e.kind
check("18 the refusal has a kind of its own", kind_ == "reroute-decision-off-board", kind_)
for label, to, prep in (("a project with no background agent", "solo-front", contextlib.nullcontext), ("the hold off", "other-front", hold_off), ("a front agent nothing can be held for", "quiet-front", contextlib.nullcontext)):
    with prep():
        fresh(); stamp(to, 1); out = msg(to, BARE, "my-front"); settle()
    check(f"18 {label}: refused all the same", off_board(out), out)
fresh(); out = msg("other-builder", BARE, "my-front"); settle()
check("18 to a background agent it is delivered as before", out.startswith("delivered") and len(got("other-builder")) == 1, out)
for label, table, sender, kw in (("a sender the key does not list", (["my-front"], None), "second-front", {}), ("both switches off", (None, None), "my-front", {}), ("a script", (["my-front"], None), "my-front", {"origin": "home-test"})):
    switches(*table); fresh(); out = msg("other-front", BARE, sender, **kw); settle()
    check(f"18 {label}: not this refusal", "sends nothing to front agents" not in out and logged() == [], out)

settle()
print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
