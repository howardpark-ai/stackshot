"""Scenario test for what becomes of a message or notice sent to a session name that is no live session (stackshot/fleet/retired_recipient.py, push.py's `retired`, the message relay in
service/messaging.py) — fixture data in a temporary directory, no live store, no network, no server process, no real pane (push.py's socket calls are replaced by recorders).

Such a line is not left in the per-session queue (<hub state dir>/queue-msg/<name>.jsonl): it goes to the name's project, where the router picks the receiver, or, when the name belongs to
no project (or the project's only agent is that name), back to its sender, or, when the sender is a script, only into a log; and the sender is told in one line that the receiver is retired and who got it.
Covers: which names are no live session (`gone_why`: a pane gone for two hours on an online machine, a retired registry row, an old name of a live session, a name no heartbeat has seen, against a pane
running, a pane only away, a name too young to be missed); the line push.py prints, per case; readdressed (a notice recorded for the project's router, the line stashed, the journal), returned to a live
session sender, a script sender only logged, the router's own deliveries and a hub-source line unchanged, a live or young name unchanged, an unreadable or partial view of the fleet unchanged; the message
tool (a script's refusal for a retired name no project takes is in the message log); and the one-shot sweep of the queue: the dry run (counts per name and action, nothing written), the real run (stale notices
dropped, the rest readdressed or returned, one journal line each, the queue file moved to the archive, a line of a live name kept, a second run does nothing twice), and the command line.

    tests/run-suite retired_recipient        → exit 0 / 1"""
import io, json, os, re, sys, time, pathlib, logging, contextlib
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="retiredrecipienttest-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = ""', f'session_links = "{tmp}/sala"', 1); assert f'session_links = "{tmp}/sala"' in toml   # the fixture registry, never the host's sala store
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet", PUSH_INBOX_WAIT="0.05", ANCHOR_PUSH_SOURCE="msg")
for k in ("STACKSHOT_URL", "CLAUDE_CODE_SESSION_ID", "ANCHOR_PUSH_FORCE"): os.environ.pop(k, None)
for d in ("store/a", "fleet/a", "brain/projects", "sala/a", "secrets", "touch"): (T / d).mkdir(parents=True)
B = "board" + "#"
NOW = time.time()
def uid(n): return f"00000000-0000-4000-8000-{n:012d}"
def gone_iso(sec): return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - sec))
RUN = {"main": uid(1), "x": uid(2), "beta": uid(3)}
HEART = {RUN["main"]: {"name": "work-osprey-main", "machine": "a", "url": "", "seen": "x"}, RUN["x"]: {"name": "work-osprey-x", "machine": "a", "url": "", "seen": "x"},
         RUN["beta"]: {"name": "home-beta", "machine": "a", "url": "", "seen": "x"},
         uid(10): {"name": "work-osprey-old", "machine": "a", "url": "", "seen": "x", "gone": gone_iso(7200)},       # a retired agent of the alpha project: its pane gone for two hours
         uid(11): {"name": "zz-lone-old", "machine": "a", "url": "", "seen": "x", "gone": gone_iso(7200)},           # a gone session no page lists and no page's name starts: no project
         uid(12): {"name": "work-solo-main", "machine": "a", "url": "", "seen": "x", "gone": gone_iso(7200)},       # the only agent of projects/solo, gone
         uid(13): {"name": "work-osprey-away", "machine": "a", "url": "", "seen": "x", "gone": gone_iso(300)}}      # away for five minutes: a pane, not a retired one
(T / "fleet/a/sessions.json").write_text(json.dumps(HEART))
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0", "online": {"ok": True, "since": gone_iso(48)}}))
def reg_row(sid, name, state="live", aliases=(), tr=()):
    return {"id": sid, "name": name, "aliases": list(aliases), "project": None, "project_key": None, "role": None, "lane": "max", "model": "opus", "effort": "medium", "pane": name, "cwd": "/work/example",
            "state": state, "created": "2026-10-21T21:00:00Z", "retired_at": None if state == "live" else "2026-10-22T01:00:00Z", "transcripts": [{"id": t, "machine": "a", "at": "2026-10-21T21:00:00Z", "why": "fresh"} for t in tr]}
REG = pathlib.Path(tmp) / "sala/a/session-registry.json"
REG.write_text(json.dumps({"schema": 1, "machine": "a", "written": "2026-10-22T07:00:00Z", "sessions": {
    uid(102): reg_row(uid(102), "work-osprey-x", aliases=["work-osprey-builder"], tr=[RUN["x"]]),            # renamed: the old name is an alias of a live session
    uid(110): reg_row(uid(110), "work-osprey-ret", state="retired", tr=[uid(210)])}}))                          # a retired session with no pane in any heartbeat
page = lambda name, sess, **kw: {"title": name, "name": name, "org": "home", "tags": [], "type": "project", "session": sess, "status": "active", "board": [], "board_row": False, "updated": 1, "mirror": f"https://example.invalid/{name}", **kw}
(T / "store/projects.json").write_text(json.dumps({"pages": {
    "projects/alpha": page("Alpha", "work-osprey", role="name", agents={"work-osprey-main": "the contact", "work-osprey-x": "builds, merges and releases the code"}, back_agents={"work-osprey-x": "builds, merges and releases the code"}),
    "projects/solo": page("Solo", "work-solo", role="name", agents={"work-solo-main": "the contact"}),
    "projects/beta": page("Beta", "home-beta")}}))
(T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))

from stackshot.core import config as _cfg
from stackshot.fleet import sessions_registry as _sr
from stackshot.fleet import push
from stackshot.fleet import retired_recipient as rr
from stackshot.router import routing, router_live
from stackshot.web import server          # installs the hooks the message relay reads
from stackshot.service import messaging as _messaging
from stackshot.service import telling
from stackshot.web import publish as _web_publish
from fastmcp.exceptions import ToolError
_web_publish._publish = lambda: None
(T / "fakepush.py").write_text("import sys\na = sys.argv[1:]\nif a[:1] == ['--from']: a = a[2:]\nprint('delivered → ' + a[0])\n")
telling.PUSH = [sys.executable, str(T / "fakepush.py")]          # the relay's own push is a recorder: no pane
_sr.TTL = 0                         # the directory is looked at on every call: the test rewrites files at once
HUB = pathlib.Path(push.A); HUB.mkdir(parents=True, exist_ok=True)
Q = HUB / "queue-msg"; LOG = HUB / rr.LOG_NAME
push.SRC, push.Q = "msg", str(Q)
sock_sent = []                       # what reached a live pane's socket (the recorder replaces push.py's socket calls)
push.resolve = lambda name: "/sock/" + name if name in ("home-beta", "work-osprey-main") else ""
push.send = lambda sock, text: sock_sent.append((sock, text)) or True
push.inbox_serves = lambda name: False         # every line takes the local path here: the inbox has its own suites
def deliver(name, text, sender):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf): rc = push.deliver(name, text, sender)
    return rc, buf.getvalue().strip()
def queued(name): return [json.loads(l) for l in (Q / f"{name}.jsonl").read_text().splitlines()] if (Q / f"{name}.jsonl").exists() else []
def journal(): return [json.loads(l) for l in LOG.read_text().splitlines()] if LOG.exists() else []
def routed(key): return [x for x in routing.read(key) if x.get("kind") == "message"]

# ---- 1. which names are no live session
view = rr._view()
check("view: the fleet is readable: the heartbeat index and the page roles", view is not None and len(view[0]) == 7, view and len(view[0]))
check("a pane running is no retired name", rr.gone_why("work-osprey-main", view=view) == "" and rr.gone_why(RUN["main"], view=view) == "")
check("a pane away for five minutes is no retired name (its machine is online, it may be back)", rr.gone_why("work-osprey-away", view=view) == "")
w = rr.gone_why("work-osprey-old", view=view)
check("a pane gone for two hours on a machine that is online is gone, with the message tool's reason", "gone for" in w and "while its machine is online" in w, w)
check("a retired session of the registry with no pane anywhere is gone", rr.gone_why("work-osprey-ret", view=view) == "a retired session, its pane gone", rr.gone_why("work-osprey-ret", view=view))
check("an old name of a live session (an alias) is gone: it names no pane", rr.gone_why("work-osprey-builder", view=view) == "an old name of work-osprey-x", rr.gone_why("work-osprey-builder", view=view))
check("a name no heartbeat has seen is not gone for a line that has just come: a pane started a minute ago is in no heartbeat yet", rr.gone_why("work-never-seen", age=5, view=view) == "")
check("…and is gone for a line that waited longer than [client] dead_after_minutes", rr.gone_why("work-never-seen", age=7200, view=view) == "no pane of that name is in any heartbeat")
check("a cloud session id and an empty name are never gone", rr.gone_why("cse_x", age=1e9, view=view) == "" and rr.gone_why("", age=1e9, view=view) == "")
class Partial(dict):
    unreadable = ["b"]
check("a partial view (one machine's heartbeat did not read) says nothing about any name", rr.gone_why("work-osprey-old", view=(Partial(view[0]), view[1])) == "")
_idx = _sr._sessions_index
_sr._sessions_index = lambda: Partial(view[0])
check("_view is None for a partial index", rr._view() is None)
def boom(): raise RuntimeError("heartbeat unreadable")
_sr._sessions_index = boom
check("…and gone_why answers nothing, never raises, when the view does not read", rr.gone_why("work-osprey-old") == "")
_sr._sessions_index = _idx

# ---- 2. a line for a retired agent goes to its project's router
n_a = len(routed("projects/alpha"))
rc, out = deliver("work-osprey-old", "[stackshot] work-osprey-old, a hand-off came to you", "stackshot")
rt = routed("projects/alpha")[n_a:]
check("rerouted: push.py answers one line that begins as a queued line does, says the receiver is retired and who got it", rc == 1 and out.startswith("queued (retired: work-osprey-old, ") and "sent to projects/alpha, where the router rules notice" in out and out.endswith("→ work-osprey-old"), (rc, out))
check("…the line is recorded for the project's router (live, pilot, not delivered to anyone) with its sender", len(rt) == 1 and rt[0]["live"] and rt[0]["pilot"] and rt[0]["to"] == "" and rt[0]["who"] == "stackshot" and rt[0]["target"] == "project-wide", rt)
nid = rt[0]["id"] if rt else ""
check("…the router's tick finds it as it finds any message to a project, and the text it will pass on is the line, with the retired name said", nid in out and "work-osprey-old" in router_live.stashed(nid) and "a hand-off came to you" in router_live.stashed(nid) and "came to projects/alpha instead" in router_live.stashed(nid), router_live.stashed(nid))
check("…nothing is left in the queue", queued("work-osprey-old") == [] and not (Q / "work-osprey-old.jsonl").exists())
j = journal()
check("…and the journal has it: id, name, reason, what was done", len(j) == 1 and j[0]["name"] == "work-osprey-old" and j[0]["action"] == "rerouted" and j[0]["project"] == "projects/alpha" and j[0]["notice"] == nid and "gone for" in j[0]["reason"] and j[0]["id"] and j[0]["via"] == "push", j)
rc, out = deliver("work-osprey-builder", "[stackshot message] from a script: hello", "some-script (a script on hp-x)")
check("an old name of a live session is readdressed the same way", rc == 1 and "sent to projects/alpha" in out and "an old name of work-osprey-x" in out, (rc, out))
check("a retired name reached by its transcript id is readdressed the same way", deliver(uid(10), "[stackshot] x", "stackshot")[1].startswith("queued (retired: ") and queued(uid(10)) == [], deliver(uid(10), "[stackshot] x", "stackshot"))

# ---- 3. no project: returned to a live session sender, only logged for a script
sock_sent.clear()
rc, out = deliver("zz-lone-old", "please look at the export page", "home-beta")
check("returned: a name no project takes goes back to its sender when that is a running session, and the answer says so", rc == 1 and out.startswith("queued (retired: zz-lone-old, ") and "no project takes its messages, so it was returned to home-beta" in out, (rc, out))
check("…the sender's pane was told: the receiver is retired, and the start of its text", len(sock_sent) == 1 and sock_sent[0][0] == "/sock/home-beta" and "zz-lone-old is retired" in sock_sent[0][1] and "please look at the export page" in sock_sent[0][1] and sock_sent[0][1].startswith("from: stackshot\n"), sock_sent)
check("…and it is not left in the queue", queued("zz-lone-old") == [] and journal()[-1]["action"] == "returned" and journal()[-1]["name"] == "zz-lone-old" and journal()[-1]["from"] == "home-beta")
sock_sent.clear()
rc, out = deliver("zz-lone-old", "a nightly report", "stackshot")
check("logged: when the sender is a script (the server's own name, a label that is no session) nothing is sent: the journal has it", rc == 1 and "its sender is a script: logged" in out and sock_sent == [] and queued("zz-lone-old") == [] and journal()[-1]["action"] == "logged", (rc, out, sock_sent))
rc, out = deliver("zz-lone-old", "a report", "librarian (a script on testbox)")
check("…a script's label (\"… (a script on <machine>)\") too", "its sender is a script: logged" in out and sock_sent == [] and journal()[-1]["action"] == "logged" and journal()[-1]["from"] == "librarian (a script on testbox)", (out, sock_sent))
rc, out = deliver("work-solo-main", "to the sole agent of a page", "home-beta")
check("the only agent of a project is no receiver for itself: a retired sole agent's line is returned, not ruled back onto it", "returned to home-beta" in out and routed("projects/solo") == [], (out, routed("projects/solo")))
rc, out = deliver("zz-lone-old", "from a retired sender", "work-osprey-old")
check("a sender that is itself no running session gets nothing back: logged", "its sender is a script: logged" in out and sock_sent[-1:] != [("/sock/work-osprey-old", "x")] and journal()[-1]["action"] == "logged", (out, sock_sent))

# ---- 4. what stays as it was
n_alpha = len(routed("projects/alpha")); n_j = len(journal())
rc, out = deliver("work-never-seen", "a line for a pane that has just started", "stackshot")
check("a name no heartbeat has seen yet is queued as before (the pane may be starting)", rc == 1 and out == "queued → work-never-seen" and len(queued("work-never-seen")) == 1 and len(routed("projects/alpha")) == n_alpha, (rc, out))
rc, out = deliver("work-osprey-away", "a line for a pane that is away", "stackshot")
check("a pane away for five minutes is queued as before", out == "queued → work-osprey-away" and len(queued("work-osprey-away")) == 1, (rc, out))
rc, out = deliver("work-osprey-main", "a live pane on this box", "stackshot")
check("a live pane is delivered as before", rc == 0 and out == "delivered → work-osprey-main" and sock_sent[-1][0] == "/sock/work-osprey-main", (rc, out))
rc, out = deliver("work-osprey-old", "the router passes a line to a retired agent", "stackshot (router)")
check("the router's own delivery to a retired agent is queued as before (readdressing it would be the router ruling its own pass again)", out == "queued → work-osprey-old" and len(queued("work-osprey-old")) == 1 and len(routed("projects/alpha")) == n_alpha, (out, routed("projects/alpha")[n_alpha:]))
(Q / "work-osprey-old.jsonl").unlink()
push.SRC = "hub"
rc, out = deliver("work-osprey-old", "[anchor] a hub line", "the hub")
check("a line of the hub's own queue (anchor changes) is queued as before", out == "queued → work-osprey-old" and len(routed("projects/alpha")) == n_alpha, out)
push.SRC = "msg"; (HUB / "queue/work-osprey-old.jsonl").unlink(missing_ok=True)
(Q / "work-osprey-old.jsonl").unlink(missing_ok=True)
_sr._sessions_index = lambda: Partial(view[0])
rc, out = deliver("work-osprey-old", "[stackshot] while the fleet's view is partial", "stackshot")
check("with a partial view of the fleet the line is queued as before, nothing readdressed or journalled", out == "queued → work-osprey-old" and len(routed("projects/alpha")) == n_alpha and len(journal()) == n_j, (out, len(journal()), n_j))
_sr._sessions_index = boom
(Q / "work-osprey-old.jsonl").unlink(missing_ok=True)
rc, out = deliver("work-osprey-old", "[stackshot] while the registry does not read", "stackshot")
check("…and when it does not read at all", out == "queued → work-osprey-old" and len(routed("projects/alpha")) == n_alpha and len(journal()) == n_j, out)
_sr._sessions_index = _idx
(Q / "work-osprey-old.jsonl").unlink(missing_ok=True)
(HUB / "paused-msg.json").write_text("{}")
rc, out = deliver("work-osprey-old", "[stackshot] during a reboot's pause", "stackshot")
check("a line held for a reboot's pause is queued as before", out.startswith("queued (paused for a reboot)") and len(routed("projects/alpha")) == n_alpha, out)
(HUB / "paused-msg.json").unlink(); (Q / "work-osprey-old.jsonl").unlink(missing_ok=True)
_rr_handle = rr.handle
rr.handle = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("the handler broke"))
rc, out = deliver("work-osprey-old", "[stackshot] when the handler itself fails", "stackshot")
check("a failure inside the handler never loses the line: it is queued as before", rc == 1 and out == "queued → work-osprey-old" and len(queued("work-osprey-old")) == 1, (rc, out))
rr.handle = _rr_handle; (Q / "work-osprey-old.jsonl").unlink(missing_ok=True)

# ---- 5. the message tool
a0 = len(routed("projects/alpha"))
res = _messaging._message("work-osprey-old", "a question for the retired agent", "home-beta")
check("the message tool sends a message to a retired name to its project and says so in front of the usual answer", res.startswith("'work-osprey-old' is retired (") and "so this went to its project 'projects/alpha' instead — held for the router — the router rules notice" in res and len(routed("projects/alpha")) == a0 + 1, res)
res = _messaging._message("work-osprey-builder", "to an old name of a live session", "home-beta")
check("…an old name of a live session the same (the heartbeat knows no pane of that name)", "so this went to its project 'projects/alpha' instead" in res, res)
try: _messaging._message("zz-lone-old", "nobody takes this", "home-beta"); e = ""
except ToolError as x: e = str(x)
check("a retired name no project takes is refused to a session, as before (the refusal is the return to the sender)", e.startswith("Refused: 'zz-lone-old' cannot receive this") and "no project page that reaches someone else" in e, e)
ml = _messaging.MSG_LOG
n_ml = len(ml.read_text().splitlines()) if ml.exists() else 0
try: _messaging._message("zz-lone-old", "nobody takes this", "a-nightly-script", origin="a"); e = ""
except ToolError as x: e = str(x)
rows = [json.loads(l) for l in ml.read_text().splitlines()][n_ml:] if ml.exists() else []
check("…and a script's is refused and logged, the message log saying it was returned to its sender", e.startswith("Refused:") and len(rows) == 1 and rows[0]["outcome"].startswith("returned to its sender") and rows[0]["to"] == "zz-lone-old", (e, rows))
try: _messaging._message("work-solo-main", "to a sole agent", "home-beta"); e = ""
except ToolError as x: e = str(x)
check("a retired sole agent of a page is refused to the sender, naming the page (nobody else there to give it to)", e.startswith("Refused: 'work-solo-main' cannot receive this") and "projects/solo" in e and routed("projects/solo") == [], e)
res = _messaging._message("work-osprey-x", "to a live agent", "home-beta")
check("a live name is sent to as before (nothing readdressed)", res.startswith("delivered") or res.startswith("inbox") or res.startswith("queued"), res)

# ---- 5a. a refusal of the relay names its kind, and the call log keeps it with the target and the text (service/messaging.py Refused, web/middleware.py _RefusalLog)
import asyncio, types
from stackshot.core import call_log as _CL
from stackshot.web import middleware as _wmw
def logged(to, text, sender="home-beta", **kw):
    """A message call as the tool makes it, through the server's refusal log → (the call log's new row, the ToolError it ended in)."""
    n_ = len(list(_CL.read(0, time.time() + 60)))
    async def nxt(ctx): return _messaging._message(to, text, sender, **kw)
    ctx = types.SimpleNamespace(message=types.SimpleNamespace(name="message", arguments={"to": to, "text": text, "sender": sender}))
    err = None
    with contextlib.redirect_stderr(io.StringIO()):
        try: asyncio.run(_wmw._RefusalLog().on_call_tool(ctx, nxt))
        except ToolError as x: err = x
    new = list(_CL.read(0, time.time() + 60))[n_:]
    return (new[-1] if new else None), err
for label, to, kind, said in (("a retired name no project takes", "zz-lone-old", "dead-recipient", "nobody takes this"), ("the retired sole agent of a page", "work-solo-main", "no-receiver", "to a sole agent"),
                              ("a name no heartbeat has seen", "work-osprey-fresh", "no-session", "a question for a pane that may be running")):
    row, err = logged(to, said)
    check(f"kind: {label} is refused as `{kind}` and the row keeps the target, the kind and the text", err is not None and err.kind == kind and row is not None and row["ok"] is False and row["kind"] == kind and row["to"] == to
          and row["text"] == said and row["sender"] == "home-beta", (err, row))
live_x = _sr._sessions_index()[RUN["x"]]
dead_x = dict(live_x, gone=gone_iso(7200))
try: _messaging._dead_recipient(uid(14), [dead_x], {uid(14): dead_x, RUN["x"]: live_x}); e = None
except ToolError as x: e = x
check("kind: a dead pane's id whose name has a pane running under another id is refused as `session-id-use-name`, naming the name", e is not None and e.kind == "session-id-use-name" and "address it by name, to='work-osprey-x'" in str(e), e)
row, err = logged("work-osprey-old", "a script's line", "a-nightly-script", origin="a")
check("kind: …a retired name that its project takes is no refusal: it goes to the page (the plain row of a call that went through, no error)", row is not None and row["ok"] is True and "kind" not in row and err is None, (row, err))

# ---- 5b. the message tool says nothing about a name it cannot see: an empty, partial or unreadable view of the fleet is no proof of a retired name, so the refusal stands as before
def refused_unseen(to, sender="home-beta", **kw):
    a, m = len(routed("projects/alpha")), len(sock_sent)
    try: res, e = _messaging._message(to, "a question for a pane that may be running", sender, **kw), ""
    except ToolError as x: res, e = "", str(x)
    return res, e, len(routed("projects/alpha")) == a and len(sock_sent) == m
class EmptyUnreadable(dict):
    unreadable = ["a"]
home_only = {k: v for k, v in view[0].items() if v["name"] == "home-beta"}
for label, fake in (("an empty heartbeat index", lambda: {}), ("a partial index (only another session in it)", lambda: dict(home_only)),
                    ("an unreadable view", lambda: EmptyUnreadable()), ("a partial, unreadable index", lambda: Partial(home_only))):
    _sr._sessions_index = fake
    for who in ("work-osprey-x", "work-osprey-fresh"):          # a pane that runs but is in no heartbeat the tool can read, and one that has just started
        res, e, quiet = refused_unseen(who)
        check(f"message tool, {label}: a message to {who} is refused as before, not rerouted to its project and not called retired", e.startswith(f"Refused: no session '{who}' in the heartbeat") and "is retired" not in e and not res and quiet, (res, e))
    for who in ("work-osprey-x", "work-osprey-fresh"):
        res, e, quiet = refused_unseen(who, sender="a-nightly-script", origin="a")
        check(f"…a script's message to {who} too ({label})", e.startswith("Refused: no session") and quiet, (res, e))
_sr._sessions_index = _idx
n_ml = len(ml.read_text().splitlines())
res, e, quiet = refused_unseen("zz-fresh-never", sender="a-nightly-script", origin="a")
check("a name no project takes that no heartbeat has seen (a readable view) is refused as before, and the message log does not call it retired", e.startswith("Refused: no session 'zz-fresh-never'") and quiet and len(ml.read_text().splitlines()) == n_ml, (e, ml.read_text().splitlines()[n_ml:]))
res, e, quiet = refused_unseen("work-osprey-fresh")
check("a name just started (in no heartbeat yet) on a readable view is refused as before too: only a name the view shows gone is rerouted", e.startswith("Refused: no session 'work-osprey-fresh' in the heartbeat") and quiet, (res, e))
a0 = len(routed("projects/alpha"))
res = _messaging._message("work-osprey-old", "positive control: a gone name on a readable view", "home-beta")
check("…while a gone name on a readable view is still rerouted (the positive case)", res.startswith("'work-osprey-old' is retired (") and len(routed("projects/alpha")) == a0 + 1, res)

# ---- 6. the sweep of the queue
SQ = T / "sweepstate/hub/queue-msg"; SQ.mkdir(parents=True)
def put(name, rows): (SQ / f"{name}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
H = 3600.0
wake = lambda i, ago, who="stackshot": {"t": NOW - ago, "from": who, "text": f"[stackshot] {B}{i} woke (wake 2026-11-20): it is yours to move now"}
stalled = lambda i, ago: {"t": NOW - ago, "from": "stackshot", "text": f"[stackshot] {B}{i} stalled: you have had no turn running for 30 min"}
put("work-osprey-old", [wake(1, 1 * H),                         # its item closed
                        stalled(2, 1 * H),                      # its item has another mover now
                        wake(3, 50 * H),                        # an over-age wake
                        {"t": NOW - 1 * H, "from": "home-beta", "text": "[stackshot message] from home-beta: a question that is still open"},      # a session's message: never screened
                        wake(4, 1 * H)])                        # its item is open and its mover: still true
put("zz-lone-old", [{"t": NOW - 5 * H, "from": "home-beta", "text": "[stackshot message] from home-beta: for nobody"}, {"t": NOW - 5 * H, "from": "stackshot", "text": "[stackshot] a report for nobody"}])
put("work-osprey-main", [{"t": NOW - 5 * H, "from": "stackshot", "text": "[stackshot] a line for a live pane"}])
put("work-never-seen", [{"t": NOW - 30, "from": "stackshot", "text": "[stackshot] young"}, {"t": NOW - 5 * H, "from": "stackshot", "text": "[stackshot message] from a script: old and unknown"}])
items = {f"{B}1": {"status": "closed", "metadata": {"mover": "work-osprey-old"}}, f"{B}2": {"status": "open", "metadata": {"mover": "work-osprey-x"}},
         f"{B}3": {"status": "open", "metadata": {"mover": "work-osprey-old"}}, f"{B}4": {"status": "open", "metadata": {"mover": "work-osprey-old"}}}
load = lambda shown: items.get(shown)
before = {p.name: p.read_text() for p in SQ.iterdir()}
n_alpha = len(routed("projects/alpha")); n_j = len(journal()); sock_sent.clear()
dry = rr.sweep(SQ, apply=False, now=NOW, deliver=push.deliver, view=rr._view(), load=load)
check("sweep dry run: counts per name and per action", dry["names"]["work-osprey-old"] == {"dropped": 3, "rerouted": 2}
      and dry["names"]["zz-lone-old"] == {"returned": 1, "logged": 1} and dry["names"]["work-osprey-main"] == {"kept": 1} and dry["names"]["work-never-seen"] == {"kept": 1, "logged": 1}
      and dry["actions"] == {"dropped": 3, "rerouted": 2, "returned": 1, "logged": 2, "kept": 2}, dry)
check("…and writes nothing: the queue files as they were, no archive, no journal line, no notice, nobody told", {p.name: p.read_text() for p in SQ.iterdir()} == before and not (SQ.parent / "archive").exists()
      and len(routed("projects/alpha")) == n_alpha and len(journal()) == n_j and sock_sent == [] and not (SQ.parent / rr.LOG_NAME).exists())
txt = rr.report(dry, False)
check("the report names the run a dry run and lists each name with its counts and the total", txt.startswith("dry run (nothing written)") and "work-osprey-old: dropped 3, rerouted 2 → projects/alpha" in txt and txt.splitlines()[-1].startswith("total: "), txt)
buf = io.StringIO()
with contextlib.redirect_stdout(buf): rc = rr.main(["sweep", "--queue", str(SQ)])
check("the command: `sweep --queue DIR` without --apply is the dry run (live items are read from the store, which this fixture does not hold: those lines are kept and counted by age)", rc == 0 and buf.getvalue().startswith("dry run (nothing written)") and {p.name: p.read_text() for p in SQ.iterdir()} == before, buf.getvalue()[:300])
run = rr.sweep(SQ, apply=True, now=NOW, deliver=push.deliver, view=rr._view(), load=load)
SJ = SQ.parent / rr.LOG_NAME
sj = [json.loads(l) for l in SJ.read_text().splitlines()]
by = lambda n, a: [x for x in sj if x["name"] == n and x["action"] == a]
check("sweep: the real run does what the dry run counted", run["names"] == dry["names"] and run["actions"] == dry["actions"], run)
check("…the journal has one line per dropped, readdressed or returned line: id, name, reason", len(sj) == 3 + 2 + 2 + 1 and all(x["id"] and x["name"] and x["reason"] and x["via"] == "sweep" for x in sj), sj)
reasons = sorted(x["reason"] for x in by("work-osprey-old", "dropped"))
check("…the stale notices were dropped with the screen's reasons: closed, another mover, over age", reasons == ["its item has another mover now", "its item is closed", "older than 6 hours"], reasons)
check("…the open question and the still-true wake were readdressed to the project (notices recorded, journalled with the notice id)", len(by("work-osprey-old", "rerouted")) == 2 and len(routed("projects/alpha")) == n_alpha + 2 and all(x["notice"] and x["project"] == "projects/alpha" for x in by("work-osprey-old", "rerouted")), by("work-osprey-old", "rerouted"))
check("…a name no project takes: the session's line returned to it, the script's logged", len(by("zz-lone-old", "returned")) == 1 and len(by("zz-lone-old", "logged")) == 1 and len(sock_sent) == 1 and sock_sent[0][0] == "/sock/home-beta", (by("zz-lone-old", "returned"), sock_sent))
arch = sorted((SQ.parent / "archive").glob("queue-msg-*.jsonl"))
check("…each queue file of a gone name was moved to the archive, whole, never deleted", sorted(p.name.rsplit("-", 2)[0] for p in arch) == ["queue-msg-work-never-seen", "queue-msg-work-osprey-old", "queue-msg-zz-lone-old"], [p.name for p in arch])
check("…the archived file holds the original lines", len((SQ.parent / "archive" / next(p.name for p in arch if "work-osprey-old" in p.name)).read_text().splitlines()) == 5)
check("…a live pane's file stays as it was, and a line of an unknown name too young to be missed stays in its own file", (SQ / "work-osprey-main.jsonl").read_text() == before["work-osprey-main.jsonl"]
      and [x["text"] for x in (json.loads(l) for l in (SQ / "work-never-seen.jsonl").read_text().splitlines())] == ["[stackshot] young"] and not (SQ / "work-osprey-old.jsonl").exists() and not (SQ / "zz-lone-old.jsonl").exists())
again = rr.sweep(SQ, apply=True, now=NOW, deliver=push.deliver, view=rr._view(), load=load)
check("a second run does nothing twice: the kept lines stay kept, no notice, no journal line", again["actions"] == {"kept": 2} and len(routed("projects/alpha")) == n_alpha + 2 and len(SJ.read_text().splitlines()) == len(sj), again)
# a run that stopped before the file was moved: its lines the journal already has are not done again
put("work-osprey-old", [wake(4, 1 * H)])
rr.log("sweep", rr.line_id("work-osprey-old", NOW - 1 * H, wake(4, 1 * H)["text"]), "work-osprey-old", "rerouted", "stackshot", "x", "a run that was cut off", dest=SJ)
stop = rr.sweep(SQ, apply=True, now=NOW, deliver=push.deliver, view=rr._view(), load=load)
check("…and a line the journal already has (a run cut off before it moved the file) is not readdressed again", stop["names"].get("work-osprey-old") == {"already-done": 1} and len(routed("projects/alpha")) == n_alpha + 2, stop)
check("…and the file of that cut-off run is archived, with nothing left to do in it", not (SQ / "work-osprey-old.jsonl").exists() and len(list((SQ.parent / "archive").glob("queue-msg-work-osprey-old-*.jsonl"))) >= 1)
_sr._sessions_index = lambda: Partial(view[0])
put("work-osprey-old", [wake(5, 1 * H)])
blind = rr.sweep(SQ, apply=True, now=NOW, deliver=push.deliver, load=load)
check("a sweep whose view of the fleet is partial calls no name gone: every line is kept, nothing moved or journalled", blind["actions"].get("rerouted", 0) == 0 and blind["unreadable_view"] and (SQ / "work-osprey-old.jsonl").exists(), blind)
_sr._sessions_index = _idx

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed" if not fails else f"{len(fails)} check(s) failed")
sys.exit(1 if fails else 0)
