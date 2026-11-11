"""Scenario test for the router's rule over every project page (board; stackshot.toml [pilot]) on fixture data -- no live
store, no network.

A project `projects/alpha` (agent work-osprey-main, a builder, a sub-page) next to a one-session project `projects/beta`. Covers: who
gets an anchor notice and what the notice says (anchors.routes, the hub's send); the routing log and its counts; the rulings; an
agent's board write charged and relayed to the keeper (server); a message addressed to a project (held for the router); the pane gate
letting a pilot agent off; the board cell and the page behind it; a green release.sh result logged and ruled automatically, a red one
held for the router; the fleet's own routine PR events (opened, merged, closed, new commits, CI passing) logged by type and ruled
automatically, still releasing the item held on their anchor, while comments, reviews, failing CI and other repositories' events are
delivered. The router's holding is switched off here (router_live.holds), so a notice is observable as delivered to the keeper;
router_live_scenario covers the holding itself.

    tests/run-suite pilot        → exit 0 / 1"""
import json, os, re, sys, time, pathlib, tempfile, logging, datetime, threading
BID_A = 9189
BID_B = 9190
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="pilottest-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml(), keywords=True)
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store (session links off)
toml = toml.replace('lanes_file = ""', f'lanes_file = "{tmp}/sala/lanes.tsv"', 1); assert f'lanes_file = "{tmp}/sala/lanes.tsv"' in toml   # a lane record in the temp dir (the example has none)
toml = toml.replace('limit_file = ""', f'limit_file = "{tmp}/sala/limit.json"', 1); assert f'limit_file = "{tmp}/sala/limit.json"' in toml   # and a limit watch
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"),
                 ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1   # the fixtures' subjects
toml, n = re.subn(r"(?m)^tell_owner = true", "tell_owner = false", toml); assert n == 1   # the owner's notice of another session's change has its own section at the end; the checks before it count pushes without it
toml, n = re.subn(r'(?m)^guards = true', 'guards = false', toml); assert n == 1   # [model] guards off: this suite is about the notices, its ~280 writes carry plain next lines and bare holds (the write guards have their own suite: model_guards)
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1   # this suite is about the notices, its writes replace next wholesale (a step that leaves next unmarked reads as dropped); the checklist has its own suite: checklist
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet")   # the session and machine state is a fixture under fleet/
S, A, B, X = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222", "33333333-3333-4333-8333-333333333333", "44444444-4444-4444-8444-444444444444"
for d in ("store/a", "fleet/a", "state/anchor-hub", "state/site", "secrets", "touch", "repo", "sala"): (T / d).mkdir(parents=True)
(T / "state/site/favicon.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"/>')   # the favicon render.py versions at import
(T / "fleet/a/sessions.json").write_text(json.dumps({S: {"name": "work-osprey", "machine": "a", "url": "", "seen": "x"}, A: {"name": "work-osprey-main", "machine": "a", "url": "", "seen": "x"},
                                                      B: {"name": "home-beta", "machine": "a", "url": "", "seen": "x"}, X: {"name": "work-osprey-x", "machine": "a", "url": "", "seen": "x"}}))
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
page = lambda name, sess: {"title": name, "name": name, "org": "home", "tags": [], "type": "project", "session": sess, "status": "active", "board": [], "board_row": False, "updated": 1, "mirror": f"https://example.invalid/{name}"}
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": page("Alpha", "work-osprey"), "projects/alpha/sub": page("Alpha sub", "work-osprey"), "projects/beta": page("Beta", "home-beta"),
                                                              "projects/alpha/kept": {**page("Alpha kept", "work-osprey-x"), "role": "agent"}}}))
def _mv(owner, needs=""): return {"then": owner} if needs == "decision" else {"mover": owner}      # the creator moves nothing; a decision is Oliver's, the agent is its `then`
def item(i, proj, owner): (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": "A thing. It lives here. Done when done.", "status": "open", "metadata": {"owner": owner, "mover": owner, "project": proj}, "updated": 1.0}))
item(1, "projects/alpha", A); item(2, "projects/alpha/sub", A); item(3, "projects/beta", B); item(4, "projects/alpha/kept", A)
(T / "store/next-id").write_text("10")
(T / "store/anchors.json").write_text(json.dumps({
    "projects/alpha": [{"url": "https://x.slack.com/archives/C0000000001", "items": None, "added": 1, "by": "t"}, {"url": "https://mail.google.com/mail/u/0/#all/1111111111111111", "items": ["a1"], "added": 1, "by": "t"}],
    "projects/alpha/sub": [{"url": "https://docs.google.com/document/d/AAAAAAAAAAAAAAAAAAAAAAAAA", "items": ["a2"], "added": 1, "by": "t"}],
    "projects/beta": [{"url": "https://x.slack.com/archives/C0000000002", "items": None, "added": 1, "by": "t"}]}))
REGJ = T / "store/projects.json"
def general(on):
    """The scope's general page (projects/example-general, whose -main agent home-commons-main takes the notices of a page with no agent of its own) is in the registry only while a
    check needs a recipient for a page with none: without it such a page keeps its own name line as the address, which is what most of this scenario is about."""
    d = json.loads(REGJ.read_text(encoding="utf-8"))
    if on: d["pages"]["projects/example-general"] = {**page("General", "home-commons"), "agents": {"home-commons-main": "Oliver's general contact"}}
    else: d["pages"].pop("projects/example-general", None)
    REGJ.write_text(json.dumps(d), encoding="utf-8")
push_log = T / "push.log"
from_log = T / "push-from.log"     # every drop names its sender (--from); the push log keeps <session> <text> as before
(T / "fakepush.py").write_text(f"import sys, json\na = sys.argv[1:]\nif a[:1] == ['--from']: open({str(from_log)!r}, 'a').write(json.dumps(a[1]) + '\\n'); a = a[2:]\n"
                               f"else: open({str(from_log)!r}, 'a').write(json.dumps(None) + '\\n')\n"
                               f"open({str(push_log)!r}, 'a').write(json.dumps(a) + '\\n')\nprint('delivered → ' + a[0])\n")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:400]}" if got is not None else ""))

# ---- 1. who gets a notice, and for whom it is
from stackshot.anchors import anchors as a; from stackshot.router import routing
from stackshot.router import router_live
# Since the router rules every project page, so a notice for a page's keeper is held for it (router_live.holds) and the
# keeper is told nothing: tests/router_live_scenario.py covers the holding, the router's rulings and what is delivered. This scenario is about the
# notice text, the routing log, the ledger and the rulings; to see them without the router, holds() is switched off here, which hands every
# recipient the notice as the hub's send, the board relay and the message tool always built it.
router_live.holds = lambda *a, **k: False
r = a.routes()
flat = {k: [(x["project"], x["session"], x["target"], x["pilot"]) for x in v] for k, v in r.items()}
check("pilot project-wide anchor → the keeper only", flat.get("slack:C0000000001") == [("projects/alpha", S, "project-wide", True)], flat)
check("pilot item-scoped anchor → the keeper, for the agent", flat.get("gmail:1111111111111111") == [("projects/alpha", S, "for work-osprey-main", True)], flat)
check("pilot sub-page anchor → the root's keeper", flat.get("drive:AAAAAAAAAAAAAAAAAAAAAAAAA") == [("projects/alpha/sub", S, "for work-osprey-main", True)], flat)
check("a page with one session and no agent (beta) is the router's too: its notice goes to the page's name, project-wide", flat.get("slack:C0000000002") == [("projects/beta", B, "project-wide", True)], flat)
b, _f = a.bindings(); check("the agent is bound to nothing in the pilot", all(A not in v for v in b.values()), b)
check("pilot_root", a.pilot_root("projects/alpha/sub") == "projects/alpha" and a.pilot_root("projects/alphabet") == "" and a.pilot_root("projects/beta") == "projects/beta" and a.pilot_root("projects/nope") == "")

# ---- 2. the hub: text and log
from stackshot.anchors.anchorhub import core
hub = core.Hub(); out = []
hub.deliver = lambda anchor, session, text: out.append((session, text)); hub.write_status = lambda: None
hub.bindings = core.load_bindings()
ev = lambda anc, who, text: hub.event(anc, {"title": f"L {anc[:6]}", "who": who, "text": text, "url": "https://u/x", "ts": "1"}, kind="slack" if anc.startswith("slack") else "gmail" if anc.startswith("gmail") else "drive")
ev("gmail:1111111111111111", "Dana", "hello there"); ev("slack:C0000000001", "Eve", "channel talk"); ev("slack:C0000000002", "Bob", "beta talk"); ev("drive:AAAAAAAAAAAAAAAAAAAAAAAAA", "Dana", 'changed "doc"')
check("four deliveries", len(out) == 4, out)
m = re.search(r" — for work-osprey-main · notice ([0-9a-f]{6})$", out[0][1]); check("pilot notice carries target and id", out[0][0] == S and bool(m), out[0])
check("project-wide target", out[1][0] == S and re.search(r" — project-wide · notice [0-9a-f]{6}$", out[1][1]), out[1])
check("beta's notice text carries its target and id like any project's", out[2][0] == B and re.fullmatch(r'\[anchor\] Slack L slack:: new message from Bob: "beta talk" → https://u/x — project-wide · notice [0-9a-f]{6}', out[2][1]), out[2])
nid = m.group(1) if m else ""
c = routing.counts(["projects/alpha", "projects/alpha/sub"]); check("pilot counts: 3 in, 3 pending", (c["in"], c["pending"], c["passed"]) == (3, 3, 0), c)
c = routing.counts(["projects/beta"]); check("beta counts: 1 in, 1 pending (a one-session page is the router's like the rest)", (c["in"], c["pending"]) == (1, 1), c)

# ---- 3. rulings
from stackshot.web import server
from stackshot.waits import waiting as _WT  # the wait is stored as one date, until: these read it as the old fields were read
hd_ = lambda m: bool(m.get("hold") or _WT.stored_until(m))
wk_ = lambda m: _WT.wake_value(m)
def setwk_(m, w):
    if "until" in m: m["until"] = w
    else: m["wake"] = w
ab_ = lambda m: _WT.stored_until(m) or m.get("ask_by")
server._publish = lambda: None; server._PUSH = [sys.executable, str(T / "fakepush.py")]
PRESENT = [True]    # a front agent Oliver is typing to now: the gate sends; the held case has its own check (front_quiet_scenario)
_real_verdict = server._front_verdict
server._front_verdict = lambda gid, owner, kind: ("send", "") if PRESENT[0] else _real_verdict(gid, owner, kind)
server._wt.cap_needs_owner = lambda: False     # this scenario sets waits far ahead; the cap on a session's wake has its own scenario (waiting)
from fastmcp.exceptions import ToolError
def refused(fn):
    try: fn(); return False
    except ToolError: return True
check("passed needs an agent", refused(lambda: server._route(nid, "passed")))
check("unknown ruling refused", refused(lambda: server._route(nid, "ignored")))
check("unknown notice refused", refused(lambda: server._route("zzzzzz", "dropped")))
res = server._route(nid, "passed", to="work-osprey-main", reason="their thread", sender="work-osprey"); check("ruling recorded", res.startswith(f"ruled {nid} (projects/alpha): passed to work-osprey-main — their thread"), res)
c = routing.counts(["projects/alpha", "projects/alpha/sub"]); check("after one ruling: 1 passed, 2 pending", (c["in"], c["passed"], c["pending"]) == (3, 1, 2), c)
server._route(nid, "dropped", reason="overruled: noise", sender="work-osprey")
n = next(x for x in routing.read("projects/alpha") if x["id"] == nid); check("a later ruling wins", (n["ruling"], n["reason"], n["ruled_by"]) == ("dropped", "overruled: noise", "work-osprey"), n)

# ---- 4. an agent's board write is the keeper's
def wait_push(n):
    """The push log once it holds n lines and every push started so far has landed (5 s at most). The server sends each notice
    from its own daemon thread (server._tell_woken, _pilot_relay), and one write can start two: a close by an agent sends the
    keeper the page-owed relay and the "was completed" line, a needs edit by the owner sends the relay and the "has decided"
    line. They land in either order, so a wait on the count alone returns between them under load and the late one shows up in
    the next step's slice. Those threads are the only ones beside the main thread in this process
    (_publish is a no-op here), so the log is complete when none is alive."""
    deadline = time.time() + 5
    while time.time() < deadline:
        lines = push_log.read_text().splitlines() if push_log.exists() else []
        if len(lines) >= n and threading.active_count() == 1: break
        time.sleep(0.05)
    return [json.loads(l) for l in push_log.read_text().splitlines()] if push_log.exists() else []
res = server._update("a1", next="call the vendor", sender="work-osprey-main")
check("agent told it was charged to the keeper", "charged to the keeper work-osprey" in res and "[nag]" not in res, res)
owed = server._owed_load(); check("ledger: the keeper owes projects/alpha", list(owed.get("projects/alpha", {})) == [S], owed)
p = wait_push(1); check("keeper notified of the board write", len(p) == 1 and p[0][0] == S and re.match(r"\[board\] a1 changed \(next\) by work-osprey-main — \[home\] item 1 \(projects/alpha\) → https://stackshot\.example\.com/items/a1 — the page update is yours as its keeper · notice [0-9a-f]{6}$", p[0][1])
      and "#task-" not in p[0][1], p)
check("board write in the routing log", any(x["kind"] == "board" and x["pilot"] for x in routing.read("projects/alpha")))
res = server._update("a1", next="keeper edits", sender="work-osprey"); check("the keeper's own write is not relayed", "charged to the keeper" not in res and len(wait_push(1)) == 1, res)
res = server._update("a3", next="beta step", sender="home-beta"); owed = server._owed_load()
check("ordinary project: the writer owes, nobody is told", list(owed.get("projects/beta", {})) == [B] and "charged" not in res and len(wait_push(1)) == 1, owed)
res = server._update("a2", priority="p1", sender="work-osprey-main"); check("a filing edit owes and relays nothing", "charged" not in res and "projects/alpha/sub" not in server._owed_load() and len(wait_push(1)) == 1, res)
res = server._update("a2", status="completed", sender="work-osprey-main", outcome="done", reason="the work landed", description="- Goal: The test item's work is in place"); p = wait_push(2)
check("completion on a sub-page: charged to the root's keeper", list(server._owed_load().get("projects/alpha/sub", {})) == [S] and len(p) == 2 and "a2 completed (done) by work-osprey-main" in p[1][1], p)

# ---- 5. a message addressed to a project: the router rules it (every project since), so it is recorded and held, and delivered to no session here
from stackshot.router import router_live as _rl
def msg(*a, **k):
    general(True)
    try: return server._message(*a, **k)
    finally: general(False)
res = msg("projects/alpha", "who owns the Gmail thread?", "home-beta"); p = wait_push(2)
nid_m = routing.read("projects/alpha")[-1]["id"]; n_m = routing.read("projects/alpha")[-1]
check("message to a project → recorded for the router with a notice id and held; the keeper is not messaged", res.startswith(f"held for the router — the router rules notice {nid_m}") and len(p) == 2 and n_m["live"] is True and n_m["kind"] == "message" and not n_m.get("ruling"), (res, p[2:], n_m))
check("…and the envelope the router will deliver is kept whole, with the page it was for", (_rl.stashed(nid_m) or "").startswith("[stackshot message] from ") and " · to projects/alpha\n" in (_rl.stashed(nid_m) or "") and "who owns the Gmail thread?" in (_rl.stashed(nid_m) or ""), _rl.stashed(nid_m))
res = msg("projects/alpha/sub", "about the sub-page", "home-beta"); p = wait_push(2)
check("message to a sub-page → held for the router too (the root's)", res.startswith("held for the router") and len(p) == 2 and routing.read("projects/alpha/sub")[-1]["live"] is True, (res, p[2:]))
res = msg("projects/beta", "hello beta", "work-osprey"); p = wait_push(2)
check("a message to a page whose scope has no general -main agent and that lists none is refused, not sent to its keeper", refused(lambda: server._message("projects/beta", "x", "work-osprey")) and len(wait_push(2)) == 2)
check("message to a page with a single session (beta) → held for the router too, not delivered to the page's session", res.startswith("held for the router") and len(p) == 2 and routing.read("projects/beta")[-1]["live"] is True and routing.read("projects/beta")[-1]["to"] == "", (res, p[2:]))
check("message to a page that does not exist is refused", refused(lambda: server._message("projects/nope", "x", "home-beta")))
check("message to an id no machine reports and no pane here ever had is refused, not queued", refused(lambda: server._message("99999999-9999-4999-8999-999999999999", "x", "home-beta")))
res = server._message("home-beta", "plain", "work-osprey"); p = wait_push(3); check("a message to a session is as before", p[2][0] == "home-beta" and " · to " not in p[2][1].split("\n")[0], p[2:])
res = server._message("home-beta", "from the car", "cse_voice_oliver"); p = wait_push(4); check("a sender that cannot be reached is named as such", "will not reach it" in p[3][1] and "Reply with the message tool" not in p[3][1], p[3:])
check("…and a reachable sender keeps the reply hint", "Reply with the message tool (to='work-osprey'" in p[2][1], p[2:])
res = server._message("home-beta", "from the car", "cse_voice"); p = wait_push(5); check("a sender label that only looks like a cloud id (cse_voice) is named as unreachable", "will not reach it" in p[4][1] and "Reply with the message tool" not in p[4][1], p[4][1][-300:])
check("…and a message to it is refused, not queued", refused(lambda: server._message("cse_voice", "hello", "home-beta")))

# ---- 5b. a message to a retired or stopped session is refused, naming where to send it instead; a live pane, a relaunching pane,
# a pane on a machine that is asleep, a cloud id and a page key are as before. The fixtures and the push log are put back after it.
def gone_iso(sec): return datetime.datetime.fromtimestamp(time.time() - sec, datetime.timezone.utc).isoformat().replace("+00:00", "Z")
FJ = T / "fleet/a/sessions.json"; MJ = T / "fleet/a/machine.json"; FJ0, MJ0, PL0 = FJ.read_text(), MJ.read_text(), push_log.read_text()
rows = json.loads(FJ0)
rows["55555555-5555-4555-8555-555555555555"] = {"name": "work-osprey-old", "machine": "a", "url": "", "seen": "x", "gone": gone_iso(7200)}     # a retired agent of alpha: its pane gone for two hours, its machine online
rows["66666666-6666-4666-8666-666666666666"] = {"name": "zz-stopped", "machine": "a", "url": "", "seen": "x", "gone": gone_iso(7200)}              # gone, and no project can be told
rows["77777777-7777-4777-8777-777777777777"] = {"name": "work-osprey-relaunch", "machine": "a", "url": "", "seen": "x", "gone": gone_iso(60)}      # gone a minute: a pane being relaunched
rows["88888888-8888-4888-8888-888888888888"] = {"name": "home-beta", "machine": "a", "url": "", "seen": "x", "gone": gone_iso(7200)}                  # an old namesake of the running home-beta
rows["aaaaaaaa-0059-4aaa-8aaa-aaaaaaaaaaaa"] = {"name": "work-osprey-w59", "machine": "a", "url": "", "seen": "x", "gone": gone_iso(59 * 60)}     # the window is 60 minutes: 59 is still a pane coming back
rows["aaaaaaaa-0061-4aaa-8aaa-aaaaaaaaaaaa"] = {"name": "work-osprey-w61", "machine": "a", "url": "", "seen": "x", "gone": gone_iso(61 * 60)}     # ...61 is gone
rows["aaaaaaaa-0000-4aaa-8aaa-aaaaaaaaaaaa"] = {"name": "work-osprey-garbage", "machine": "a", "url": "", "seen": "x", "gone": "garbage"}        # an unreadable stamp: gone, for a time not known
rows["aaaaaaaa-0001-4aaa-8aaa-aaaaaaaaaaaa"] = {"name": "zz-keeper", "machine": "a", "url": "", "seen": "x", "gone": gone_iso(7200)}             # the only session of projects/zz, gone
rows["aaaaaaaa-0002-4aaa-8aaa-aaaaaaaaaaaa"] = {"name": "home-beta-dead", "machine": "a", "url": "", "seen": "x", "gone": gone_iso(7200)}         # a retired agent of the pages sharing the name home-beta (below)
rows["aaaaaaaa-0003-4aaa-8aaa-aaaaaaaaaaaa"] = {"name": "home-beta-listed", "machine": "a", "url": "", "seen": "x", "gone": gone_iso(7200)}       # ...one that a single page lists by its exact name
rows["aaaaaaaa-0004-4aaa-8aaa-aaaaaaaaaaaa"] = {"name": "home-gamma", "machine": "a", "url": "", "seen": "x"}                                     # the running keeper of the pages sharing the name home-gamma
rows["aaaaaaaa-0005-4aaa-8aaa-aaaaaaaaaaaa"] = {"name": "home-gamma-dead", "machine": "a", "url": "", "seen": "x", "gone": gone_iso(7200)}
FJ.write_text(json.dumps(rows))
MJ.write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0", "online": {"ok": True, "since": gone_iso(48)}}))
PJ = T / "store/projects.json"; PJ0 = PJ.read_text(); _pj = json.loads(PJ0); _pj["pages"]["projects/alpha"]["role"] = "name"      # as pages.py writes it: the name line gives the project its name (alpha-*)
_pj["pages"]["projects/alpha"]["agents"] = {"work-osprey-main": "front"}      # alpha lists its -main agent here: the page key reaches it (the router rules every page)
_pj["pages"]["projects/zz"] = {**page("Zz", "zz-keeper"), "role": "name"}
# pages that share one display name (home-beta, home-gamma: the name line of each), as ops/example-hub, projects/example and others share ops-falcon
for _k, _s, _ag in (("projects/aaa-none", "home-beta", {}), ("projects/mmm-two", "home-beta", {"home-beta-one": "x", "home-beta-two": "y"}), ("projects/zzz-one", "home-beta", {"home-beta-listed": "z"}),
                    ("projects/aaa-g", "home-gamma", {}), ("projects/gamma", "home-gamma", {"home-gamma-eng": "x"}), ("projects/gamma/sub", "home-gamma", {"home-gamma-a": "x", "home-gamma-b": "y", "home-gamma-c": "z"})):
    _pj["pages"][_k] = {**page(_k, _s), "role": "name", **({"agents": _ag} if _ag else {})}
PJ.write_text(json.dumps(_pj))
(T / "fleet/b").mkdir()
(T / "fleet/b/machine.json").write_text(json.dumps({"letter": "b", "fleet": "laptop", "claude": "1.0.0", "online": {"ok": False, "since": gone_iso(99999)}}))      # asleep
(T / "fleet/b/sessions.json").write_text(json.dumps({"99999999-bbbb-4bbb-8bbb-999999999999": {"name": "laptop-gone", "machine": "b", "url": "", "seen": "x", "gone": gone_iso(86400)}}))
def refusal(to):
    try: server._message(to, "hello there", "home-beta"); return ""
    except ToolError as x: return str(x)
n_a = len(wait_push(0))
e = refusal("work-osprey-old")
check("retired-agent: a retired agent (its pane gone for two hours, its machine online) is refused, naming the project key to send to", e.startswith("Refused: 'work-osprey-old' cannot receive this") and "message(to='projects/alpha'" in e, e)
e = refusal("55555555-5555-4555-8555-555555555555")
check("retired-agent: …addressed by its transcript id, the same", "message(to='projects/alpha'" in e, e)
e = refusal("66666666-6666-4666-8666-666666666666")
check("retired-agent: a stopped session no page can be told for is refused with the live panes only", e.startswith("Refused: 'zz-stopped' cannot receive this") and "no project page that reaches someone else" in e and "home-beta" in e and "work-osprey-old" not in e and "zz-stopped" not in e.split("Panes right now:")[1], e)
e = refusal("zz-keeper")
check("retired-agent: a session that is the only keeper of its page is not sent to that page: the live panes are named instead", e.startswith("Refused: 'zz-keeper' cannot receive this") and "projects/zz" not in e and "Panes right now:" in e, e)
e = refusal("home-bata")
check("retired-agent: a misspelled name is refused, with the live name to use", e.startswith("Refused: no session 'home-bata'") and "did you mean home-beta" in e and "work-osprey-old" not in e, e)
e = refusal("work-osprey-oldd")
check("retired-agent: …a misspelling of an agent's name also names the project to send to, and the retired pane is not offered", "message(to='projects/alpha'" in e and "work-osprey-old" not in e.split("panes right now:")[1], e)
e = refusal("home-beta-dead")
check("retired-agent: pages sharing a display name: a dead name no page lists is pointed at the page with the most agents, not the first alphabetically (a page with none)", "message(to='projects/mmm-two'" in e and "aaa-none" not in e, e)
e = refusal("home-beta-nope")
check("retired-agent: …an unknown name the same, and the heartbeat-miss branch names that page as the one it is an agent of", "if it is an agent of projects/mmm-two" in e and "aaa-none" not in e, e)
e = refusal("home-beta-listed")
check("retired-agent: …a name that one page's agents map lists wins over the page with more agents (it is a front agent there: the gate names that page)", "projects/zzz-one" in e and "mmm-two" not in e, e)
check("retired-agent: …and with no roles to go by, the exact listing is found among the pages of the prefix (home-beta-listed → zzz-one, not mmm-two with more agents)", server._project_of_name("home-beta-listed", {}, server._sessions_index()) == "projects/zzz-one", server._project_of_name("home-beta-listed", {}, server._sessions_index()))
e = refusal("home-gamma-dead")
check("retired-agent: …a top-level page whose key slug is the name's last part (home-gamma → gamma) wins over a sub-page with more agents and a page with none", "message(to='projects/gamma'" in e and "gamma/sub" not in e and "aaa-g" not in e, e)
e = refusal("home-gamma-nope")
check("retired-agent: …unknown, the same page, named in the heartbeat-miss branch", "if it is an agent of projects/gamma," in e and "gamma/sub" not in e, e)
e = refusal("88888888-8888-4888-8888-888888888888")
check("retired-agent: a gone transcript id whose name runs under another id is told to use the name", "running under another id" in e and "to='home-beta'" in e, e)
e = refusal("work-osprey-w61")
check("retired-agent: the window is 60 minutes: a pane gone 61 is refused", e.startswith("Refused: 'work-osprey-w61' cannot receive this") and "61 min" in e, e)
e = refusal("work-osprey-garbage")
check("retired-agent: an unreadable gone stamp is refused as gone for a time not known, not a failed call", e.startswith("Refused: 'work-osprey-garbage' cannot receive this") and "a time not known" in e, e)
p = wait_push(0); check("retired-agent: none of those refusals queued anything", len(p) == n_a, p[n_a:])
res = server._message("home-beta", "still live", "work-osprey"); p = wait_push(n_a + 1)
check("retired-agent: a live pane is delivered as before (an old gone namesake does not block it)", res.startswith("delivered") and p[-1][0] == "home-beta", (res, p[n_a:]))
res = server._message("work-osprey-relaunch", "being relaunched", "home-beta"); p = wait_push(n_a + 2)
check("retired-agent: a pane gone for less than the grace (a relaunch) is still addressed", res.startswith("delivered") and p[-1][0] == "work-osprey-relaunch", (res, p[n_a:]))
res = server._message("work-osprey-w59", "coming back after a reboot", "home-beta"); p = wait_push(n_a + 3)
check("retired-agent: …and one gone 59 minutes (panes come back slowly after a reboot) is too", res.startswith("delivered") and p[-1][0] == "work-osprey-w59", (res, p[n_a:]))
res = server._message("laptop-gone", "to the laptop, long away", "home-beta"); p = wait_push(n_a + 4)
check("retired-agent: a pane marked gone on a machine that is asleep is still sent to: there a dead pane cannot be told from one that is away", res.startswith("delivered") and p[-1][0] == "laptop-gone", (res, p[n_a:]))
res = server._message("cse_example0000000000001", "to a cloud session", "home-beta"); p = wait_push(n_a + 5)
check("retired-agent: a cse_ id is accepted as before", res.startswith("delivered") and p[-1][0] == "cse_example0000000000001", (res, p[n_a:]))
general(True)
res = server._message("projects/zz", "to a page whose keeper's pane is gone", "home-beta"); p = wait_push(0)
general(False)
check("retired-agent: a page key is never refused for its keeper's pane: the router takes the message, held for its ruling and delivered to nobody here (release.sh sends to projects/example)", res.startswith("held for the router") and len(p) == n_a + 5, (res, p[n_a:]))
_pd = server._project_of_name; server._project_of_name = lambda *a, **k: 1 / 0
try: res = server._message("work-osprey-old", "the check itself fails", "home-beta"); p = wait_push(n_a + 6)
finally: server._project_of_name = _pd
check("retired-agent: a failure inside the check falls back to today's behaviour: the message is sent, the call does not fail", res.startswith("delivered") and p[-1][0] == "work-osprey-old", (res, p[n_a:]))
MJ.write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
res = server._message("work-osprey-old", "machine unknown", "home-beta"); p = wait_push(n_a + 7)
check("retired-agent: with no sign of the machine's puller (online unknown) a gone session is not refused: it cannot be told from one that is away", res.startswith("delivered") and p[-1][0] == "work-osprey-old", (res, p[n_a:]))
PJ.write_text(PJ0); FJ.write_text(FJ0); MJ.write_text(MJ0); push_log.write_text(PL0)            # the fixtures and the push log as they were: the checks below count pushes from the start
import shutil; shutil.rmtree(T / "fleet/b")

# ---- 6. the pane gate lets a pilot agent off
from stackshot.projects import pages
pl = lambda sid: {"session_id": sid, "tool_response": "updated."}
pages._touch_mcp_record(pl(A), {"project": "projects/alpha", "item_id": "a1"}, "update"); check("pilot agent: no pane debt", not pages.load_state(A).get("touches"), pages.load_state(A))
pages._touch_mcp_record(pl(S), {"project": "projects/alpha", "item_id": "a1"}, "update"); check("pilot keeper: pane debt as usual", "projects/alpha" in pages.load_state(S).get("touches", {}), pages.load_state(S))
pages._touch_mcp_record(pl(B), {"project": "projects/beta", "item_id": "a3"}, "update"); check("ordinary project: pane debt as usual", "projects/beta" in pages.load_state(B).get("touches", {}), pages.load_state(B))

# ---- a script's message (POST /client/message → _message with origin): the keeper gets it with a notice id, and it says what it is
n0 = len(wait_push(0)); res = msg("projects/alpha", "run 2026-02-21 finished cleanly", "nightly-job", auth="machine:testbox", origin="testbox")
p = wait_push(n0); last = routing.read("projects/alpha")[-1]; env = _rl.stashed(last["id"]) or ""
check("a script's message to a project is held for the router with a notice id; the keeper is not messaged", len(p) == n0 and last["live"] is True and env.split("\n")[0].startswith("[stackshot message] from nightly-job (a script on testbox) · ")
      and env.split("\n")[0].endswith("· to projects/alpha"), (env, p[n0:]))
check("…is recorded in the routing log as pending, under the script's label", last["kind"] == "message" and last["who"] == "nightly-job (a script on testbox)" and last["pilot"] and not last.get("ruling"), last)
check("…and the envelope says it is a script's, not a session's, and cannot be answered", "from a script that runs for" in env and "It cannot be replied to." in env and "Reply with the message tool" not in env and "another Claude session" not in env, env)
check("…and the sender is told it was held for the router, with no reply hint", res.startswith("held for the router") and "a reply, if any" in res, res)
try: server._message("projects/alpha", "x", "", origin="testbox"); ok = False
except Exception as e: ok = "sender is required" in str(e)
check("a script must still name itself", ok)

# ---- 7. the board cell and the page behind it
from stackshot.web import render
# ---- type and title are kept apart from the receiver on; only a notice puts them together
e = core.Event(anchor="notion:" + "a" * 32, kind="notion", title='"Notion tips"', who="Dana", text="hi", url="https://u/n")
check("an event carries its title; type and label derive from it", (e.type, e.title, e.label) == ("Notion", '"Notion tips"', 'Notion "Notion tips"'), (e.type, e.title, e.label))
h2 = core.Hub(); h2.write_status = lambda: None; h2.flush_queues = lambda: None
h2.resolvers["slack"] = lambda a: {"title": "Slack-talk #alpha", "url": "https://x.slack.com/archives/" + a[6:], "seen": None} if a.endswith("1") else {"url": ""}
h2.rescan(); sa = h2.status["anchors"]
check("a resolved anchor is stored as type + title + composed label", {k: sa["slack:C0000000001"].get(k) for k in ("type", "title", "label")} == {"type": "Slack", "title": "Slack-talk #alpha", "label": "Slack Slack-talk #alpha"}, sa.get("slack:C0000000001"))
check("an unresolved one keeps its id and no title, so it is tried again", sa["slack:C0000000002"].get("label") == "slack:C0000000002" and not sa["slack:C0000000002"].get("title"), sa.get("slack:C0000000002"))
(T / "state/anchor-hub/status.json").write_text(json.dumps({"started": "x", "anchors": sa}))
import importlib; from stackshot.web import render; importlib.reload(render)
import stackshot.web.ui.render as ui_render; importlib.reload(ui_render)   # after render's reload: it binds the icon versions at import
bd = ui_render.Board(f"{tmp}/store")
# the watch state of a row: one word per row, the overlay's lines one detail per line
w_, det = bd.watch("projects/alpha"); c = routing.counts(["projects/alpha", "projects/alpha/sub"])
check("pilot watch: ok while its notices are fresh; one detail per line (the anchors, the notices of the day)",
      w_ == "ok" and det[0] == "3 anchors watched" and re.fullmatch(r"\d+ notices? in the last 24 hours", det[1]) and len(det) == 2
      and c["pending"] > 0 and c["waiting"] == 0 and c["escalated"] == 0, (w_, det, c))
later = ui_render.Board(f"{tmp}/store", now=bd.now + datetime.timedelta(minutes=61)); w_, det = later.watch("projects/alpha"); c2 = later.routing_counts("projects/alpha")
check("…an hour later the notices still without a ruling turn it to waiting", c2["waiting"] == c["pending"] and w_ == "wait" and f'{c2["waiting"]} unruled past an hour' in det, (w_, det, c2))
check("…and the markdown board says it as a word", "| waiting |" in later.markdown() and "| watch |" in later.markdown())
w_, det = bd.watch("projects/beta"); check("a one-session page's watch: ok, one anchor in the detail", w_ == "ok" and det[0] == "1 anchor watched", (w_, det))
bd.anchors.pop("projects/beta", None); bd.anchors.pop("projects/gamma", None)
_q = [k for k in bd.proj if k not in bd.anchors and not routing.read(k) and not bd.group.get(k)]
check("a row with nothing watched and nothing in the log is none", not _q or bd.watch(_q[0])[0] == "none", _q[:1])
check("the no-project row has no watch state", bd.watch("") is None)
check("a one-session page waits like any other: its unruled notices past an hour are waiting", later.routing_counts("projects/beta")["waiting"] == later.routing_counts("projects/beta")["pending"] > 0, later.routing_counts("projects/beta"))
# ---- the page's agents: line, checked against the items and the live sessions
rs_a = bd.by_proj["projects/alpha"]; base = bd.lines("projects/alpha", rs_a)
check("no agents: line → lines as before, nothing flagged", [(x[0], x[5]) for x in base] == [("a/work-osprey", ""), ("a/work-osprey-main", "")], base)
bd.proj["projects/alpha"]["agents"] = {"work-osprey-main": "does the work", "work-osprey-gone": "left last week", "home-beta": "lends a hand"}
ln = {x[0]: x for x in bd.lines("projects/alpha", rs_a)}
check("a listed agent that owns items: no flag, its mandate as the tip", ln["a/work-osprey-main"][5] == "" and ln["a/work-osprey-main"][6] == "does the work" and ln["a/work-osprey-main"][2] == "", ln.get("a/work-osprey-main"))   # the keeper work-osprey owns nothing and is not listed: no line, so no "-main" built on it
check("a listed agent with no open item still has a line", "a/home-beta" in ln and ln["a/home-beta"][4] == [] and ln["a/home-beta"][5] == "" and ln["a/home-beta"][2] == "", ln.get("a/home-beta"))
check("a listed agent the fleet does not know is flagged", ln["a/work-osprey-gone"][5] == "no session" and ln["a/work-osprey-gone"][2] == "" and "a/work-osprey" not in ln, ln.get("a/work-osprey-gone"))
bd.proj["projects/alpha"]["agents"] = {"work-osprey-docs": "writes"}
ln = {x[0]: x for x in bd.lines("projects/alpha", rs_a)}
check("an item owner the page does not list is flagged", ln["a/work-osprey-main"][5] == "unlisted", ln.get("a/work-osprey-main"))
page_html = bd.routing_html("projects/alpha"); md = bd.markdown()
check("the project page shows the flags, with what they mean", 'class="aflag"' in page_html and ">unlisted</span>" in page_html and ">no session</span>" in page_html and "agents: line does not list it" in page_html, page_html.count("aflag"))
check("board.md says the same", "(unlisted)" in md and "(no session)" in md, [l for l in md.splitlines() if "alpha" in l][:4])
del bd.proj["projects/alpha"]["agents"]
html = bd.routing_html("projects/alpha")
check("the page prints the type once, bold, and the title whole as the link — a title that itself opens with the type word is not cut", '<b>Slack</b> <a href="https://x.slack.com/archives/C0000000001" target="_blank" rel="noopener">Slack-talk #alpha</a>' in html, html[html.find("alist"):][:400])
_anch = html[html.find("<h2>Anchors"):html.find("<h2>Notices")]
check("page: anchors of the row and its sub-page", _anch.count("<li>") == 3, _anch.count("<li>"))
check("page: pending, a ruling and its reason", 'class="r-pending"' in html and 'class="r-dropped"' in html and "overruled: noise" in html and "for work-osprey-main" in html)
try: bd.routing_html("projects/nope"); check("unknown project → KeyError", False)
except KeyError: pass
_home_pg = bd.html()
check("board renders", 'id="your-move"' in _home_pg and "routing/" not in _home_pg)
# the details page lives at /<page key>: the index's project name opens it in a new tab, the page links the
# project's gbrain mirror, and board.md (what sessions read) keeps linking the mirror
_ix = bd.projects_table(); _proj = re.findall(r'<td class="proj"[^>]*>(.*?)</td>', _ix)
check("Projects page: the project name links its details page /<key> in a new tab, not the gbrain mirror", '<a href="/projects/alpha" target="_blank" rel="noopener" title="work/Alpha">work/Alpha</a>' in _proj
      and not any("example.invalid" in x for x in _proj), _proj)
_dp = bd.routing_html("projects/alpha")
check("details page: a gbrain page link to the mirror under the title, in a new tab", '</h1><p class="sub"><a href="https://example.invalid/Alpha" target="_blank" rel="noopener">gbrain page ↗</a></p>' in _dp, _dp[_dp.find("<h1>"):][:300])
# the way back to the Projects page: a small link above the project's title, on a project page and a sub-page, not on the Projects page itself
_BACK = '<p class="pjback"><a href="/projects">\u2190 Projects</a></p>'
_ds = bd.routing_html("projects/alpha/sub"); _pl = bd.projects_html()
check("details page: a real link to the Projects page, above the title", _dp.count(_BACK) == 1 and 0 < _dp.find(_BACK) < _dp.find("<h1>") and _dp.find(_BACK) > _dp.find("</header>"), _dp.find(_BACK))
check("a sub-page has the same link above its title", _ds.count(_BACK) == 1 and _ds.find(_BACK) < _ds.find("<h1>work/Alpha sub</h1>"), _ds.find(_BACK))
check("the Projects page itself has no back link", 'class="pjback"' not in _pl and "\u2190 Projects" not in _pl and "<h1>Projects</h1>" in _pl, ['class="pjback"' in _pl, "\u2190 Projects" in _pl, "<h1>Projects</h1>" in _pl])
check("details page: every link and asset works from any depth (absolute or external)", not re.findall(r'(?:href|src)="(?!/|https?:|#)[^"]*"', _dp) and '<a href="/">' in _dp and 'href="/favicon.svg?v=' in _dp,
      re.findall(r'(?:href|src)="(?!/|https?:|#)[^"]*"', _dp))
check("board.md still links the project's gbrain mirror", "](https://example.invalid/Alpha)" in bd.markdown(), [l for l in bd.markdown().splitlines() if "Alpha" in l][:3])
# one theme switch on the board and on every routing page; the saved choice applies before the first paint, and the
# dark palette follows the system unless light is chosen, and is forced when dark is chosen
for nm, pg in (("board", bd.html()), ("routing page", bd.routing_html("projects/alpha"))):
    check(f"{nm}: the theme button, its script, and the saved choice read in <head> before the stylesheet",
          pg.count('id="theme"') == 1 and "localStorage.setItem('stackshot-theme'" in pg
          and pg.find("localStorage.getItem('stackshot-theme')") < pg.find("<style>") < pg.find("</head>"), nm)
    check(f"{nm}: dark follows the system unless light is chosen, and dark is forced when chosen",
          ":root:not([data-theme=light]){--bg:#161617" in pg and ":root[data-theme=dark]{--bg:#161617" in pg, nm)
# the reload button (first in the title bar of a project page and the item page, then floating on the board and on every page): the round reload button and Back to top, one shared pair of
# markup, on the board, the routing (project) page and the item page; the title bar keeps only the theme button
_fab = '<button type="button" class="fab" id="reload" aria-label="Reload" title="Reload page"><svg'
for nm, pg in (("routing page", bd.routing_html("projects/alpha")), ("item page", bd.item_html("a1"))):
    check(f"{nm}: one floating reload button (id=reload, class=fab, named Reload) and one Back to top link, the shared pair, after the page's main",
          pg.count('id="reload"') == 1 and pg.count(_fab) == 1 and pg.count('id="totop"') == 1 and ui_render._FAB_PAIR in pg
          and pg.find("</main>") < pg.find('id="reload"') < pg.find('id="totop"') and pg.find('id="totop"') - pg.find('id="reload"') < 1000, nm)
    check(f"{nm}: no title-bar reload button (no class rbtn in the markup or the stylesheet)", 'class="rbtn"' not in pg and ".rbtn" not in pg, nm)
    check(f"{nm}: Back to top has a target: exactly one element with id=top, the page's main, and its script scrolls to the top",
          pg.count('id="top"') == 1 and re.search(r'<main[^>]*id="top"', pg) and 'href="#top"' in pg
          and pg.count("document.getElementById('totop')") == 1 and "window.scrollTo(0,0)" in pg, nm)
    check(f"{nm}: the floating buttons share the board's one rule (same size, round, fixed, safe-area aware); the reload sits 10 px above Back to top",
          "#totop,.fab{position:fixed;right:calc(20px + env(safe-area-inset-right));bottom:calc(20px + env(safe-area-inset-bottom));width:44px;height:44px;border-radius:50%;" in pg
          and "#totop:hover,.fab:hover{" in pg and ".fab{bottom:calc(74px + env(safe-area-inset-bottom));" in pg, nm)
    i = pg.find('<header class="top">'); j = pg.find("</header>", i)
    check(f"{nm}: the title bar holds the theme and panel buttons, then the site title; the reload button is not in it", 0 < i < pg.find('id="theme"') < pg.find('id="panel-open"') < pg.find('<p class="site">') < j and 'id="reload"' not in pg[i:j], nm)
_bh = bd.html()
for nm, pg in (("board", _bh), ("routing page", bd.routing_html("projects/alpha")), ("item page", bd.item_html("a1"))):
    check(f"{nm}: the reload button's script reloads the page, delegated from the document", pg.count("e.target.closest('#reload'):null;if(b)location.reload()") == 1, nm)
_hd = _bh[_bh.find('<header class="top">'):_bh.find("</header>")]
check("board: the same shared pair, and one Back to top script that scrolls to the top (target: the main column, id=top)",
      ui_render._FAB_PAIR in _bh and _bh.count("document.getElementById('totop')") == 1 and re.search(r'<main[^>]*id="top"', _bh) and _bh.count('id="top"') == 1)
check("board: the title bar reads theme, panel; the reload button is not in it", 'id="reload"' not in _hd and 'class="rbtn"' not in _bh
      and 0 < _hd.find('id="theme"') < _hd.find('id="panel-open"') and "header.top .rbtn" not in _bh
      and "header.top h1,header.top p.site{font-size:17px;margin:0 0 6px}" in _bh and "padding-right:calc(24px + 2 * var(--ico))}" in _bh)
check("board: exactly one reload button, floating, right before the Back to top button (outside the header, the main column and the panel)",
      _bh.count('id="reload"') == 1 and _bh.count(_fab) == 1 and _bh.find("</aside>") < _bh.find(_fab) < _bh.find('id="totop"')
      and _bh.find('id="totop"') - _bh.find('id="reload"') < 1000 and _bh.find('id="reload"') > _bh.find("</header>"))
check("board: the floating buttons share one rule (same size, round, fixed, safe-area aware) and the reload sits 10 px above Back to top",
      "#totop,.fab{position:fixed;right:calc(20px + env(safe-area-inset-right));bottom:calc(20px + env(safe-area-inset-bottom));width:44px;height:44px;border-radius:50%;" in _bh
      and "#totop:hover,.fab:hover{" in _bh and ".fab{bottom:calc(74px + env(safe-area-inset-bottom));" in _bh)
# the board as an installed app: every page links the manifest with credentials (Cloudflare Access turns a cookieless fetch
# away) and carries the script that keeps a same-origin new-tab link inside the app window. The icon links carry ?v= with the
# first 12 hex of the SHA-256 of the file's bytes (render.py ICON_V), so a new icon is a new URL to the browser and the edge.
import hashlib
_v_touch = hashlib.sha256((pathlib.Path(STACK) / "icons/apple-touch-icon.png").read_bytes()).hexdigest()[:12]
_v_fav = hashlib.sha256((T / "state/site/favicon.svg").read_bytes()).hexdigest()[:12]
_d1, _d2 = T / "one.png", T / "two.png"; _d1.write_bytes(b"\x89PNG one"); _d2.write_bytes(b"\x89PNG two")
_va, _vb = render.asset_version(_d1), render.asset_version(_d2)
check("asset_version: 12 hex of the bytes' SHA-256, a different version for different bytes, the same for the same bytes",
      re.fullmatch(r"[0-9a-f]{12}", _va) and _va != _vb and _va == hashlib.sha256(b"\x89PNG one").hexdigest()[:12] and render.asset_version(_d1) == _va, (_va, _vb))
_d1.write_bytes(b"\x89PNG one, redrawn")
check("asset_version: rewriting the file's bytes changes its version", render.asset_version(_d1) not in ("", _va), (_va, render.asset_version(_d1)))
check("asset_version: a missing file has no version, and its link stays unversioned", render.asset_version(T / "nope.png") == "" and render.icon_href("nope.png") == "/nope.png")
check("ICON_V: every committed icon and the favicon, read at import", set(render.ICON_V) >= {"icon-192.png", "icon-512.png", "icon-maskable-512.png", "apple-touch-icon.png", "favicon.svg"}
      and render.ICON_V["apple-touch-icon.png"] == _v_touch and render.ICON_V["favicon.svg"] == _v_fav, render.ICON_V)
for nm, pg in (("board", bd.html()), ("routing page", bd.routing_html("projects/alpha")), ("item page", bd.item_html("a1"))):
    hd = pg[:pg.find("</head>")]
    check(f"{nm}: the manifest link in <head>, with use-credentials, once", hd.count('<link rel="manifest" href="/manifest.webmanifest" crossorigin="use-credentials">') == 1
          and pg.count('rel="manifest"') == 1, nm)
    check(f"{nm}: the apple-touch-icon link in <head>, once, versioned by its bytes", hd.count(f'<link rel="apple-touch-icon" href="/apple-touch-icon.png?v={_v_touch}">') == 1
          and pg.count('rel="apple-touch-icon"') == 1, (nm, re.findall(r'<link rel="apple-touch-icon"[^>]*>', hd)))
    check(f"{nm}: the favicon link in <head>, once, versioned by its bytes (an absolute address, whichever page)",
          hd.count(f'<link rel="icon" href="/favicon.svg?v={_v_fav}" type="image/svg+xml">') == 1 and pg.count('rel="icon"') == 1,
          (nm, re.findall(r'<link rel="icon"[^>]*>', hd)))
    check(f"{nm}: theme-color in <head> for each scheme, each theme's --bg", hd.count('<meta name="theme-color" content="#fafaf8" media="(prefers-color-scheme: light)">') == 1
          and hd.count('<meta name="theme-color" content="#161617" media="(prefers-color-scheme: dark)">') == 1 and pg.count('name="theme-color"') == 2
          and ":root{--bg:#fafaf8;" in pg and ":root[data-theme=dark]{--bg:#161617;" in pg, nm)
    check(f"{nm}: the standalone script in <head>: display-mode read at click time, same-origin _blank links only",
          hd.count("matchMedia('(display-mode: standalone)')") == 1 and "window.navigator.standalone===true" in hd and "document.addEventListener('click'" in hd
          and "u.origin!==location.origin)return" in hd and "location.assign(u.href)" in hd and hd.find("matchMedia('(display-mode") < hd.find("<style>"), nm)
# the search box's form opens in a new tab; in an app window (no tabs) the same script sends a same-origin GET form with target=_blank to the window itself. The head script is run
# in node against a stub document, window, location and FormData (no browser): a submit in an app window navigates and is cancelled, a submit in a tab, another origin, a form without
# target=_blank, a POST form and a submit already cancelled are left alone.
if shutil.which("node"):
    _pg = bd.html()
    _head_js = next(j for j in re.findall(r"<script>(.*?)</script>", _pg[:_pg.find("</head>")], re.S) if "display-mode: standalone" in j)
    _harness = r"""
const src = require('fs').readFileSync(0, 'utf8'); const out = [];
function run(app, form, defaultPrevented) {
  const subs = []; let moved = null, stopped = false;
  const ctx = {URL, URLSearchParams, String, Symbol, Array,
    FormData: class { constructor(f) { this.f = f } [Symbol.iterator]() { return this.f.fields[Symbol.iterator]() } },
    window: {matchMedia: () => ({matches: app}), navigator: {standalone: false}},
    location: {href: 'https://board.example.org/items/a1', origin: 'https://board.example.org', assign: u => { moved = u }},
    document: {addEventListener: (t, fn) => { if (t === 'submit') subs.push(fn) }}};
  ctx.matchMedia = ctx.window.matchMedia;
  require('vm').runInNewContext(src, ctx);
  const f = {getAttribute: k => form[k] ?? null, fields: form.fields || []};
  subs.forEach(fn => fn({target: f, defaultPrevented: !!defaultPrevented, preventDefault: () => { stopped = true }}));
  return {moved, stopped};
}
const box = {target: '_blank', method: 'get', action: '/search', fields: [['q', 'a b&c']]};
out.push(run(true, box));
out.push(run(false, box));
out.push(run(true, {...box, target: null}));
out.push(run(true, {...box, method: 'post'}));
out.push(run(true, {...box, action: 'https://elsewhere.example.net/search'}));
out.push(run(true, box, true));
console.log(JSON.stringify(out));
"""
    import subprocess as _sp
    _r = _sp.run(["node", "-e", _harness], input=_head_js, capture_output=True, text=True, timeout=30)
    _o = json.loads(_r.stdout) if _r.returncode == 0 and _r.stdout.strip() else []
    check("search box in an app window: a target=_blank GET form goes to the window itself with the typed query in the address, and the submit is cancelled",
          len(_o) == 6 and _o[0] == {"moved": "https://board.example.org/search?q=a+b%26c", "stopped": True}, (_o, _r.stderr[:300]))
    check("search box in a tab and the other cases: left to the browser (a tab, no target, a POST form, another origin, a submit already cancelled)",
          len(_o) == 6 and all(x == {"moved": None, "stopped": False} for x in _o[1:5]) and _o[5] == {"moved": None, "stopped": False}, (_o, _r.stderr[:300]))
# the code font: D2Coding, served by stackshot itself, ahead of the monospace stack on code (command blocks and inline code), the stack kept as the fallback
_d2v = hashlib.sha256((pathlib.Path(STACK) / "fonts/D2Coding-Regular.woff2").read_bytes()).hexdigest()[:12]
for nm, pg in (("board", bd.html()), ("routing page", bd.routing_html("projects/alpha")), ("item page", bd.item_html("a1"))):
    check(f"{nm}: the D2Coding @font-face, once, from our own /fonts/ (woff2, swap), versioned by the file's bytes",
          pg.count("@font-face{") == 1 and f'@font-face{{font-family:"D2Coding";src:url("/fonts/D2Coding-Regular.woff2?v={_d2v}") format("woff2");font-weight:400;font-style:normal;font-display:swap}}' in pg, nm)
    check(f"{nm}: code (so .cmd pre code, .md pre code, inline code) is D2Coding first, then the monospace stack as the fallback",
          'code{font:13px "D2Coding",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;' in pg and "__D2FACE__" not in pg, nm)
check("render.font_href: the versioned URL of the committed file", render.font_href() == f"/fonts/D2Coding-Regular.woff2?v={_d2v}" and re.fullmatch(r"[0-9a-f]{12}", _d2v), render.font_href())
# a phone (dark scheme): the root itself paints each theme's --bg (the overscroll and gesture-bar area), the page
# declares both schemes and runs edge to edge with the safe-area insets as padding. The width itself is measured in a
# browser by tests/phone_width_check.py (a manual check, CONTRIBUTING.md); here the markup and style it relies on.
for nm, pg in (("board", bd.html()), ("routing page", bd.routing_html("projects/alpha")), ("item page", bd.item_html("a1"))):
    hd = pg[:pg.find("</head>")]
    check(f"{nm}: viewport-fit=cover and color-scheme light dark in <head>, once each",
          hd.count('<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">') == 1 and pg.count('name="viewport"') == 1
          and hd.count('<meta name="color-scheme" content="light dark">') == 1 and pg.count('name="color-scheme"') == 1, nm)
    check(f"{nm}: html carries --bg, and the root's color-scheme follows the system and the switch in both themes",
          "html{background:var(--bg);scrollbar-gutter:stable}" in pg and ":root{color-scheme:light}" in pg
          and re.search(r"@media\(prefers-color-scheme:dark\)\{:root:not\(\[data-theme=light\]\)\{--bg:#161617;[^}]*color-scheme:dark\}\}", pg)
          and re.search(r":root\[data-theme=dark\]\{--bg:#161617;[^}]*color-scheme:dark\}", pg), nm)
    check(f"{nm}: the page end and sides keep clear of the gesture bar and the screen's edges (safe-area insets)",
          "calc(64px + env(safe-area-inset-bottom))" in pg and "max(16px,env(safe-area-inset-left))" in pg and "max(16px,env(safe-area-inset-right))" in pg, nm)
_bh = bd.html(); _bcss = bd._css()
_pt = bd.projects_table()
check("phone width: the Projects table sits in its box, which does not scroll sideways",
      _pt.startswith('<div class="pwrap"><table class="pidx">') and _pt.endswith("</tbody></table></div>")
      and ".pwrap{overflow-x" not in _bcss and "body.panel-pin .pwrap" not in _bcss, _pt[:200])
check("phone width: the Projects table is fixed-layout at the box's width; the agents column has no width of its own, so it takes the rest; names wrap in their cells; nothing sticks",
      "table.pidx{table-layout:fixed;width:100%;border-collapse:separate;border-spacing:0}" in _bcss
      and "table.pidx col.c-sess" not in _bcss and "table.pidx col.c-proj{width:36%}" in _bcss
      and "table.pidx td.sess{white-space:normal}" in _bcss
      and "table.pidx td.sess a,table.pidx td.sess code{display:inline;max-width:none;overflow:visible;text-overflow:clip;white-space:normal;overflow-wrap:anywhere}" in _bcss
      and "position:sticky;left:0" not in _bcss and "tr.scope th .sc{position:sticky" not in _bcss and 'th colspan="2"><span class="sc">' in _pt, _bcss.count("pidx"))
check("phone width: Machines is a card per machine (name inside) that wraps; Anchor hub cards two to a row on a phone",
      re.search(r'<section id="machines">.*?<div class="matrix"><div class="mcol"><div class="pc mach"><b class="lbl mh"', _bh, re.S) is not None
      and "#machines .matrix{grid-template-columns:repeat(auto-fit,minmax(128px,1fr))}" in _bcss
      and _bcss.rfind("#machines .matrix{grid-template-columns:repeat(auto-fill,minmax(250px,1fr))}") > _bcss.find("#machines .matrix{grid-template-columns:repeat(auto-fit,minmax(128px,1fr))}")   # the card's width, after the old column rule
      and "@media(max-width:600px){.matrix.rcvs{grid-template-columns:repeat(2,minmax(0,1fr))}}" in _bcss
      and "minmax(128px,1fr))\">" not in _bh)

# ---- the Projects page lists a hub's front agents (the -main agent first) and its running background agents, dimmed and tagged; the page's name line is an ordinary front agent, with no "steward" tag, group or tip
# anywhere (the keepers were retired); the project page lists every session; the lines of a row (lines, index_lines) carry the items
bs = ui_render.Board(f"{tmp}/store")
def idx(b): return b.projects_table()
def alpha_rows(b):
    i = idx(b); s0 = i.find(">" + b.proj_title("projects/alpha") + "</a>"); s1 = i.find('<td class="proj"', s0); return i[s0:s1 if s1 > 0 else len(i)]
def il(b, k="projects/alpha"): return b.index_lines(k, b.by_proj[k])
check("not a hub: the keeper's line stays on the Projects page", "<li>work-osprey</li>" in alpha_rows(bs) and "<li>home-beta</li>" in idx(bs), alpha_rows(bs))
bs.proj["projects/alpha"]["agents"] = {"work-osprey-main": "does the work", "work-osprey-x": "keeps the kept page"}
bs.proj["projects/alpha"]["back_agents"] = {"work-osprey-x": "keeps the kept page"}   # the registry's shape: agents = all, back_agents = the background subset
ar = alpha_rows(bs)
check("hub row: a keeper that owns nothing and is not listed has no line; the -main agent is the one front line, untagged", '<li title="does the work">work-osprey-main</li>' in ar and ">work-osprey</li>" not in ar and 'class="rtag"' not in ar.split("work-osprey-main")[0] and "steward" not in ar.lower(), ar)
check("hub row: the lead shows the full label, and no suffix is built on a keeper that does not lead", ">work-osprey-main</li>" in ar and ">-main</li>" not in ar, ar)
check("hub row: a running background agent follows the front agents, dimmed and tagged", 0 <= ar.find("work-osprey-main") < ar.find("work-osprey-x")
      and re.search(r'<li class=dimline title="keeps the kept page">work-osprey-x <span class="rtag"[^>]*>background</span></li>', ar) is not None, ar)
bm = ui_render.Board(f"{tmp}/store"); bm.proj["projects/alpha"]["agents"] = {"work-osprey-aaa": "helps", "work-osprey-main": "does the work"}
_am = alpha_rows(bm)
check("hub row: the -main agent leads, even when another agent sorts before it", 0 <= _am.find(">work-osprey-main</li>") < _am.find(">work-osprey-aaa</li>"), _am)
check("board.md lists the background agent, not the keeper that owns nothing and is not listed", "`a/work-osprey`" not in bs.markdown() and "-x`" in bs.markdown(), [l for l in bs.markdown().splitlines() if "alpha" in l][:4])
check("lines() carries a background agent's mandate", {x[0]: x[6] for x in bs.lines("projects/alpha", bs.by_proj["projects/alpha"])}.get("a/work-osprey-x") == "keeps the kept page")
_r0 = bs.by_proj["projects/alpha"][0]
def owned(i, sid): return {**_r0, "_mod": None, "id": str(i), "gid": f"a{i}", "owner": sid, "metadata": {**_r0["metadata"], "owner": sid, "mover": sid}}
bs.by_proj["projects/alpha"] = bs.by_proj["projects/alpha"] + [owned(97, S), owned(98, X)]
ar = alpha_rows(bs)
_il = {x[0]: x for x in il(bs)}; _labels = [x[0] for x in il(bs)]
check("hub row: a keeper that owns an open item is a plain line with its item, not tagged", "a/work-osprey" in _il and _il["a/work-osprey"][7] == "" and [r["gid"] for r in _il["a/work-osprey"][4]] == ["a97"] and "steward" not in str(_il).lower(), _il.get("a/work-osprey"))
check("hub row: a background agent that owns an open item is back, tagged, after the front agents", _il["a/work-osprey-x"][7] == "background" and [r["gid"] for r in _il["a/work-osprey-x"][4]] == ["a98"]
      and _labels.index("a/work-osprey-main") < _labels.index("a/work-osprey") < _labels.index("a/work-osprey-x"), _labels)
bs.by_proj["projects/alpha"] = [r for r in bs.by_proj["projects/alpha"] if r["owner"] != S]
ar = alpha_rows(bs)
_labels = [x[0] for x in il(bs)]
check("hub row: the keeper owning nothing again, the background agent with an item still shows", "a/work-osprey-main" in _labels and "a/work-osprey-x" in _labels and "a/work-osprey" not in _labels and "steward" not in str(il(bs)).lower(), _labels)
bs.proj["projects/alpha"]["back_agents"] = {"work-osprey-main": "the nightly sweep", "work-osprey-x": "keeps the kept page"}
ar = alpha_rows(bs)
_il = {x[0]: x for x in il(bs)}
check("back_agents: is honoured — a listed agent with items is tagged background, with its mandate; with no name line it leads with its full label", "a/work-osprey" not in _il and _il["a/work-osprey-main"][7] == "background" and _il["a/work-osprey-main"][6] == "the nightly sweep"
      and _il["a/work-osprey-main"][2] == "" and [x[0] for x in il(bs)][0] == "a/work-osprey-main" and "steward" not in str(_il).lower(), _il)
bs.by_proj["projects/alpha"] = [owned(97, S)]
ar = alpha_rows(bs)
check("hub row: the keeper that owns the only items is the one line, untagged", [(x[0], x[7]) for x in il(bs)] == [("a/work-osprey", "")] and "steward" not in str(il(bs)).lower(), il(bs))
_bn = ui_render.Board(f"{tmp}/store"); _bn.proj["projects/alpha"]["session"] = ""; _bn.proj["projects/alpha"]["agents"] = {"work-osprey-x": "keeps the kept page"}; _bn.proj["projects/alpha"]["back_agents"] = {"work-osprey-x": "keeps the kept page"}
check("hub row whose every session is hidden (no keeper, only an idle background agent) still renders one empty line", _bn.index_lines("projects/alpha", []) == [("", "", "", False, [], "", "", "")], _bn.index_lines("projects/alpha", []))
# the page's keeper is its -main agent, as on the real hub pages: one ordinary front line, the other agents' suffixes built on it
bsm = ui_render.Board(f"{tmp}/store"); bsm.proj["projects/alpha"]["session"] = A
bsm.proj["projects/alpha"]["agents"] = {"work-osprey-main": "does the work", "work-osprey-x": "keeps the kept page", "work-osprey-aaa": "helps"}
bsm.proj["projects/alpha"]["back_agents"] = {"work-osprey-x": "keeps the kept page"}
_r0 = bsm.by_proj["projects/alpha"][0]
bsm.by_proj["projects/alpha"] = bsm.by_proj["projects/alpha"] + [{**_r0, "_mod": None, "id": "99", "gid": "a99", "owner": X, "metadata": {**_r0["metadata"], "owner": X, "mover": X}}]
_sc = lambda b: re.findall(r'<td class="sess">(.*?)</td>', idx(b))
am = alpha_rows(bsm)
am = alpha_rows(bsm)
_ilm = il(bsm); _lm = [x[0] for x in _ilm]
check("hub row, keeper = -main: it appears once, as the plain lead line with its full label", _lm.count("a/work-osprey-main") == 1 and _lm[0] == "a/work-osprey-main" and _ilm[0][7] == "" and _ilm[0][6] == "does the work" and am.count("work-osprey-main") == 1 and 'rtag">keeper' not in am, (_lm, am))
check("…the other agents follow as lines of their own, the background one with an item tagged; the Projects page lists them with the front agent before the background one",
      "a/work-osprey-aaa" in _lm and {x[0]: x[7] for x in _ilm}.get("a/work-osprey-x") == "background" and 0 <= am.find(">work-osprey-main</li>") < am.find(">work-osprey-aaa</li>") < am.find("work-osprey-x"), (_lm, am))
check("…and nothing on the index says steward (a role no session has any more)", "steward" not in " ".join(_sc(bsm)).lower() and "steward" not in ui_render._ROLE_TIP and "steward" not in ui_render._ROLE_TIP.get("background", ""), _sc(bsm))
_pm = bsm.routing_html("projects/alpha"); _sm = _pm[_pm.find("<h2>Sessions"):_pm.find("<h2>Anchors")]
check("…the project page lists it once under Agents, with no Steward group", _sm.count("work-osprey-main</span>") == 1 and _sm.find(">Agents</h3>") < _sm.find("work-osprey-main</span>") < _sm.find(">Background agents</h3>") and "steward" not in _sm.lower(), re.sub(r"<[^>]*>", "|", _sm))
# ---- a hub page's keeper (its `display-name:` line) gets a line only while it owns an open item here or is a listed agent (retired name-line sessions stay off the index); a keeper with no live pane is flagged "no session"
def keeper_board(agents, keeper_gone=True, keeper_items=False, session=S):
    b = ui_render.Board(f"{tmp}/store"); b.proj["projects/alpha"]["agents"] = agents; b.proj["projects/alpha"]["session"] = session
    if keeper_gone and session in b.sess:      # a private copy of the fleet view: the keeper's pane is gone past the grace, under both of its keys
        b.sess = {**b.sess}; gone = {**b.sess[session], "gone": GONE0}; b.sess[session] = gone
        if "name:" + str(gone.get("name")) in b.sess: b.sess["name:" + str(gone["name"])] = gone
    r0 = b.by_proj["projects/alpha"][0]
    b.by_proj["projects/alpha"] = [r for r in b.by_proj["projects/alpha"] if r["owner"] != S] + ([{**r0, "id": "96", "gid": "a96", "owner": session, "metadata": {**r0["metadata"], "owner": session, "mover": session}}] if keeper_items else [])
    return b
GONE0 = "2026-01-01T00:00:00Z"
def klines(b):
    rs = b.by_proj["projects/alpha"]; return {"lines": b.lines("projects/alpha", rs), "index": b.index_lines("projects/alpha", rs)}
def knames(b): return {w: [x[0] for x in v] for w, v in klines(b).items()}
AG = {"work-osprey-main": "does the work", "work-osprey-aaa": "helps"}
b1 = keeper_board(AG)
check("keeper: retired (no pane), owns nothing, not listed → no line on lines() or index_lines(); the others keep their full labels",
      all("a/work-osprey" not in v for v in knames(b1).values()) and [x[0] for x in klines(b1)["lines"]] == ["a/work-osprey-aaa", "a/work-osprey-main"]
      and all(x[2] == "" for v in klines(b1).values() for x in v) and b1._lines("projects/alpha", b1.by_proj["projects/alpha"])[0] is False, klines(b1))
b1n = keeper_board(AG, session="work-home-commons")      # a keeper the fleet never knew, as the real retired ones
check("keeper: a name the fleet does not know, owning nothing → no line either", all(not any("home-commons" in n for n in v) for v in knames(b1n).values()), knames(b1n))
b2 = keeper_board(AG, keeper_items=True)
k2 = {w: [x for x in v if x[0] == "a/work-osprey"] for w, v in klines(b2).items()}
check("keeper: retired but owning an open item → its line is there once, flagged no session, with the item",
      all(len(v) == 1 and v[0][5] == "no session" and [r["gid"] for r in v[0][4]] == ["a96"] for v in k2.values()), k2)
check("…and the other agents' suffixes are built on it again, since its line is shown", [x[2] for x in klines(b2)["lines"] if x[0] == "a/work-osprey-main"] == ["-main"], klines(b2)["lines"])
b3 = keeper_board({**AG, "work-osprey": "the page's keeper"}, keeper_gone=False)
k3 = {w: [x for x in v if x[0] == "a/work-osprey"] for w, v in klines(b3).items()}
check("keeper: a listed live agent owning nothing → exactly one line, unflagged, with its mandate", all(len(v) == 1 and v[0][5] == "" and v[0][6] == "the page's keeper" for v in k3.values()), k3)
b3g = keeper_board({**AG, "work-osprey": "the page's keeper"})
k3g = {w: [x for x in v if x[0] == "a/work-osprey"] for w, v in klines(b3g).items()}
check("keeper: a listed agent with no pane → exactly one line, flagged no session", all(len(v) == 1 and v[0][5] == "no session" for v in k3g.values()), k3g)
b3b = keeper_board({**AG, "work-osprey": "nightly"}, keeper_gone=False); b3b.proj["projects/alpha"]["back_agents"] = {"work-osprey": "nightly"}
check("keeper: listed as a background agent with no item → one line on lines(), none on the index", [x[0] for x in klines(b3b)["lines"]].count("a/work-osprey") == 1 and "a/work-osprey" not in knames(b3b)["index"], knames(b3b))
b4 = keeper_board(AG); b4.proj["projects/beta"]["agents"] = {}; kb = klines_b = b4.lines("projects/beta", b4.by_proj["projects/beta"])
check("a row that is not a hub keeps its name line as before", [x[0] for x in kb][:1] == ["a/home-beta"], kb)
def invariant(b):      # every hub row, every line: a listed agent, an owner of an open item on the row, or flagged
    bad = []
    for k in b.proj:
        rs = b.by_proj.get(k, [])
        if not b.is_hub(k): continue
        front, back = b.agent_roles(k)
        for who, ls in (("lines", b.lines(k, rs)), ("index", b.index_lines(k, rs))):
            for x in ls:
                if x[0] and x[0].split("/", 1)[-1] not in {**front, **back} and not x[4] and not x[5]: bad.append((k, who, x[0]))
    return bad
check("every line of every hub row is a listed agent, an owner of an open item there, or flagged", all(not invariant(b) for b in (b1, b1n, b2, b3, b3g, b3b, bs, bsm)) and any(b.is_hub(k) for b in (b1, b2) for k in b.proj), [invariant(b) for b in (b1, b1n, b2, b3, b3g, b3b, bs, bsm)])

bs = ui_render.Board(f"{tmp}/store")
bs.proj["projects/alpha"]["agents"] = {"work-osprey": "the page's keeper", "work-osprey-main": "does the work", "work-osprey-x": "keeps the kept page", "work-osprey-docs": "writes", "work-osprey-bg": "the nightly sweep"}
bs.proj["projects/alpha"]["back_agents"] = {"work-osprey-bg": "the nightly sweep", "work-osprey-x": "keeps the kept page"}
# session names link to their view in the fleet tool's web UI while they have a live pane: [client]
# session_view and [fleet] tool_name as his instance sets them, sala (the example's "" = no links, "the fleet tool"); a session gone
# past the grace has no live pane and stays text
SALA_T = "https://sala.example.org/#s={name}"
def sala_on(on=True): render._cfg.CFG["client"]["session_view"] = SALA_T if on else ""
render._cfg.CFG.setdefault("fleet", {})["tool_name"] = "sala"
GONE = "2026-01-01T00:00:00Z"
_sl = lambda n, label=None, arrow="": f'<a href="https://sala.example.org/#s={n}" target="_blank" rel="noopener" title="open this session in sala">{label or n}{arrow}</a>'
sala_on(); bs.sess[S]["gone"] = GONE                  # the keeper's pane is gone; work-osprey-main's is live
ph = bs.routing_html("projects/alpha"); sec = ph[ph.find("<h2>Sessions"):ph.find("<h2>Anchors")]
check("project page: titled by the project, no '— routing'", "<title>work/Alpha</title>" in ph and "<h1>work/Alpha</h1>" in ph and "— routing" not in ph, ph[:900])
check("project page: Sessions comes before Anchors, with Agents / Background agents in that order and no Keeper group",
      0 < ph.find("<h2>Sessions") < ph.find("<h2>Anchors") and 0 < sec.find(">Agents</h3>") < sec.find(">Background agents</h3>") and "steward" not in sec.lower(), sec)
_g = lambda t: sec[sec.find(f">{t}</h3>"):][:sec[sec.find(f">{t}</h3>"):].find("</ul>")]
_gs = _g("Agents")[_g("Agents").find('<span class="sn">work-osprey</span>'):][:200]
check("…the page's name line is an ordinary line under Agents, the -main agent first, with its machine", ">work-osprey</span>" in _gs and "· testbox" in _gs and 0 < _g("Agents").find("work-osprey-main") < _g("Agents").find(">work-osprey</span>"), _g("Agents"))
check("…a session with no live pane is plain text on the project page", '<span class="sn">work-osprey</span>' in _g("Agents") and "sala.example.org" not in _gs, _gs)
check("…an agent with a live pane links to its view in sala in a new tab, and its open items link to their item pages", f'<span class="sn">{_sl("work-osprey-main")}</span>' in _g("Agents") and '<a href="/items/a1">a1</a>' in _g("Agents") and "/#task-" not in sec and "does the work" in _g("Agents"), _g("Agents"))
check("…a listed agent the fleet does not know is flagged", "work-osprey-docs" in _g("Agents") and ">no session</span>" in _g("Agents"), _g("Agents"))
check("…background agents from the registry's back_agents, with their mandates",
      "work-osprey-x" in _g("Background agents") and "work-osprey-bg" in _g("Background agents") and "keeps the kept page" in sec and "background:" not in sec.lower().replace(">background agents<", ""), _g("Background agents"))
_bp = ui_render.Board(f"{tmp}/store"); _bp.proj["projects/alpha"]["agents"] = {"work-osprey-main": "does the work", "work-osprey-y": "background: old style"}
check("the old background: mandate prefix no longer marks an agent", "work-osprey-y" in _bp.agent_roles("projects/alpha")[0], _bp.agent_roles("projects/alpha"))
bs.proj["projects/alpha"]["agents"] = {"work-osprey-docs": "writes"}; del bs.proj["projects/alpha"]["back_agents"]
ph = bs.routing_html("projects/alpha"); sec = ph[ph.find("<h2>Sessions"):ph.find("<h2>Anchors")]
check("…an unlisted item owner goes under Agents, flagged", "work-osprey-main" in _g("Agents") and ">unlisted</span>" in _g("Agents") and ">Background agents<" not in sec, sec)
ph = bs.routing_html("projects/beta"); sec = ph[ph.find("<h2>Sessions"):ph.find("<h2>Anchors")]
check("project page, not a hub: one group 'Session' with the session on the name line, no keeper label", ">Session</h3>" in sec and "steward" not in sec.lower() and f'<span class="sn">{_sl("home-beta")}</span>' in sec, sec)
check("Projects page: the agents column links a live session's name to sala, its name as the text",
      '<a class="sref" href="https://sala.example.org/#s=home-beta" target="_blank" rel="noopener" title="open this session in sala">home-beta</a>' in bs.projects_table(), re.findall(r'<td class="sess">.*?</td>', bs.projects_table()))
check("Projects page, not a hub: no keeper label, group or tip on any row", "steward" not in " ".join(re.findall(r'<td class="sess">(.*?)</td>', idx(bs))).lower() and 'class="rtag"' not in idx(bs), re.findall(r'<td class="sess">(.*?)</td>', idx(bs)))
sala_on(False)

# ---- the project page's Items section, first on the page, and every section a fold like the board's
import shutil
shutil.copytree(T / "store", T / "store-items")
def item_x(i, proj, owner, status="open", age_h=2, **md):
    (T / f"store-items/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": "A thing. Done when done.", "status": status,
        "metadata": {"owner": owner, **_mv(owner, md.get("needs")), "project": proj, **md}, "updated": time.time() - age_h * 3600}))
item_x(11, "projects/alpha", A, needs="decision"); item_x(12, "projects/alpha/sub", A, needs="external"); item_x(13, "projects/alpha", A, hold=True)
item_x(14, "projects/alpha/sub", A, status="completed", outcome="done"); item_x(15, "projects/alpha", A, status="completed", outcome="done", age_h=24 * 20)
item_x(16, "projects/beta", B, needs="decision")
bi = ui_render.Board(f"{tmp}/store-items"); ph = bi.routing_html("projects/alpha")
_secs = re.findall(r'<section id="([a-z]+)"><details class="fold" data-fold="project\.\1"( open)?>', ph)
check("project page: four sections, each a details.fold with its data-fold, in the order Items, Sessions, Anchors, Notices",
      [s for s, _o in _secs] == ["items", "sessions", "anchors", "notices"] and ph.split('<aside id="panel"')[0].count('<section id="') == 4, _secs)      # the summary panel's own sections are not the page's
check("…Items first on the page, right after the header", ph.find('<section id="items">') == ph.find("<section") and ph.find("</h1>") < ph.find('<section id="items">'), ph.find("<section"))
check("…Notices folded by default, the rest open", dict(_secs) == {"items": " open", "sessions": " open", "anchors": " open", "notices": ""}, _secs)
check("…the project page carries the sent-notes element the home page's script reads, right before the Items, and the script that shows it", ph.count('<div id="sent-notes" hidden data-hash="') == 1 and 0 < ph.find('<div id="sent-notes"') < ph.find('<section id="items">')
      and ph.find('</h1>') < ph.find('<div id="sent-notes"') and ph.find('<div id="sent-notes"') == ph.find('<section id="items">') - len(bi.sent_notes_html()) and "<script>" + ui_render._HOME_JS + "</script>" in ph and "getElementById('counts')||N" in ui_render._HOME_JS, ph.find('<div id="sent-notes"'))
check("…the board's fold script remembers each fold per viewer", "<script>" + ui_render._FOLD_JS + "</script>" in ph and "stackshot.fold." in ph)
def _fold_head_ok(h):   # the pre-paint script sits in the <head>, after the theme script, before any details.fold, once
    return (h.count(ui_render._FOLD_HEAD) == 1 and h.find("</head>") > h.find(ui_render._FOLD_HEAD) > h.find(ui_render._THEME_HEAD) > 0
            and h.find(ui_render._FOLD_HEAD) < h.find('<details class="fold"'))
check("…fold state applied before the first paint: the head script is in the <head>, before the first fold", _fold_head_ok(ph), ph.find(ui_render._FOLD_HEAD))
_items = ph[ph.find('<section id="items">'):ph.find('<section id="sessions">')]
_grp = re.findall(r'<details class="fold sfold" data-fold="project\.items\.([a-z-]+)"( open)?><summary><h3 class="iscope">([^<]+) <span class="count">(\d+)</span>', _items)
check("items in the home page's three lists, in its order and wording, then Completed, each list a fold",
      [(g, t, n) for g, _o, t, n in _grp] == [("your-move", "Your move", "1"), ("agents", "On agent", "2"), ("waiting", "Waiting", "2"), ("completed", "Completed", "2")], _grp)
def _gsl(g): s = _items.find(f'data-fold="project.items.{g}"'); e = _items.find("</details>", s); return _items[s:e]
_ids = lambda g: re.findall(r'<li class="irow hrow" id="task-a-(\d+)"', _gsl(g))
_cids = lambda: re.findall(r'<li class="irow" id="task-a-(\d+)"', _gsl("completed"))
check("…each item under the list the home page would put it in: the decision on Your move, the agent's items, the outside wait and the held one under Waiting, the recent completions",
      (_ids("your-move"), sorted(_ids("agents")), sorted(_ids("waiting")), sorted(_cids())) == (["11"], ["1", "4"], ["12", "13"], ["14", "2"]),
      [(_g, _ids(_g)) for _g in ("your-move", "agents", "waiting")])
_open_ids = _ids("your-move") + _ids("agents") + _ids("waiting")
_proj_open = sorted(r["gid"][1:] for r in bi.rows if r["status"] != "completed" and render.proj_key(r).startswith("projects/alpha"))
check("…every open item of the project is in exactly one list: none twice, none missing, and the home page's classification agrees",
      len(_open_ids) == len(set(_open_ids)) and sorted(_open_ids) == _proj_open
      and all(sorted(r["gid"][1:] for r, _m in bi.home_lists([x for x in bi.rows if x["status"] != "completed" and render.proj_key(x).startswith("projects/alpha")])[w]) == sorted(_ids(g))
              for w, g in ((ui_render._home.YOUR_MOVE, "your-move"), (ui_render._home.AGENTS, "agents"), (ui_render._home.WAITING, "waiting"))), (_open_ids, _proj_open))
check("…another project's item is not on the page, and a completion older than 14 days is not either", "task-a-16" not in _items and "task-a-3\"" not in _items and "task-a-15" not in _items)
check("completed folded by default, the three lists open", [(g, o) for g, o, _t, _n in _grp] == [("your-move", " open"), ("agents", " open"), ("waiting", " open"), ("completed", "")], _grp)
_r4 = next(r for r in bi.rows if r["gid"] == "a4"); _r1 = next(r for r in bi.rows if r["gid"] == "a1"); _r11 = next(r for r in bi.rows if r["gid"] == "a11"); _r13 = next(r for r in bi.rows if r["gid"] == "a13")
_row = lambda r, w: bi.home_row(r, bi.mod_of(r), w, flags=True)
check("…the rows are the home page's own, drawn by home_row: the same row as the function draws, in the list it belongs to",
      _row(_r11, ui_render._home.YOUR_MOVE) in _gsl("your-move") and _row(_r1, ui_render._home.AGENTS) in _gsl("agents") and _row(_r4, ui_render._home.AGENTS) in _gsl("agents")
      and _row(_r13, ui_render._home.WAITING) in _gsl("waiting"), _gsl("agents")[:900])
_l1 = _gsl("agents")[_gsl("agents").find('<li class="irow hrow" id="task-a-1"'):]; _l1 = _l1[:_l1.find("</li>")]
check("…a row is a top line (the item's number and goal linking its item page, then the age), the mover under it, then the next step on its own line",
      re.search(r'<li class="irow hrow" id="task-a-1" data-st="agent"><div class="ir-top"><span class="ir-title"><a class="ir-link" href="/items/a1"[^>]*><span class="ir-id">a1</span> <span class="hgoal">item 1</span></a></span><span class="tip ir-age"[^>]*>[^<]*</span></div><div class="ir-who"><span class="hwho">[^<]*</span></div><div class="ir-det"><span class="hnext">.+?</span></div>', _l1, re.S), _l1)
_l13 = _gsl("waiting")[_gsl("waiting").find('<li class="irow hrow" id="task-a-13"'):]; _l13 = _l13[:_l13.find("</li>")]
check("…a Waiting row carries the Waiting fields: the wait line says what it waits on, and above it who picks it up (and who watches, when something does: this one has no date)", '<span class="hwait">' in _l13
      and re.search(r'<div class="ir-who"><span class="hwho">[^<]*</span> picks it up</div><div class="ir-det"><span class="hwait">[^<]*</span></div>', _l13) and "watched by" not in _l13
      and 'class="hr"' not in _l13, _l13)
_ag = _gsl("agents"); _a4 = _ag[_ag.find('id="task-a-4"'):]; _a1 = _ag[_ag.find('id="task-a-1"'):_ag.find("</li>", _ag.find('id="task-a-1"'))]
check("…a row draws no project label, a sub-page's item included (the page says the project, and the row no longer links to the page it is on)",
      "hproj" not in _ag and "hwhom" not in _ag and "gbrain" not in _ag and 'class="ir-top"' in _a4, (_a1, _a4[:700]))
_r14 = next(r for r in bi.rows if r["gid"] == "a14")
check("…Completed keeps the compact lines, each with its sub-page's name where it has one", bi.done_row(_r14, "Alpha sub") in _gsl("completed")
      and _gsl("completed").count('<div class="ir-who">Alpha sub</div>') == 2 and 'class="irow hrow"' not in _gsl("completed"), _gsl("completed"))
check("…the page loads the home page's script that shows an answer form to the signed-in viewer, and the copy script, for the forms and command blocks its rows carry",
      "<script>" + ui_render._HOME_JS + "</script>" in ph and ui_render._COPY_JS in ph, ph[-900:])
check("…the Items heading counts the open items and names the completed ones", '<h2>Items <span class="count">5</span> <span class="count dim">· 2 completed</span></h2>' in ph, _items[:300])
_kp = bi.routing_html("projects/alpha/kept")
check("…a sub-page's own page lists its items, unlabelled", "task-a-4" in _kp and "subp" not in _kp and "task-a-1\"" not in _kp, _kp[_kp.find('<section id="items">'):][:600])
bi.proj["projects/empty"] = {**bi.proj["projects/beta"], "title": "Empty", "name": "Empty"}; _ep = bi.routing_html("projects/empty")
check("…a project with nothing open says so, and draws no group", '<p class="empty">no open items</p>' in _ep and "project.items." not in _ep, _ep[_ep.find('<section id="items">'):][:400])

# ---- anchors under a key whose page is gone (a rename by hand): listable and removable, nothing else
st0 = a.load(); st0["projects/gone"] = [{"url": "https://x.slack.com/archives/C0000000009", "items": None, "added": 1, "by": "t"}]; a.save(st0)
out = server._anchors("projects/gone", who="t")
check("anchors: a key with no page lists what it still holds and says so", "names no page any more" in out and "C0000000009" in out, out)
try: server._anchors("projects/gone", add=["https://x.slack.com/archives/C0000000008"], who="t"); ok = False
except Exception as e: ok = "names no page" in str(e) and "not added to" in str(e)
check("anchors: nothing can be added under it", ok)
out = server._anchors("gone", remove=["https://x.slack.com/archives/C0000000009"], who="t")
check("anchors: its anchors can be removed, and the key goes with the last one", "(none)" in out and "projects/gone" not in a.load(), (out, list(a.load())))
try: server._anchors("projects/never", who="t"); ok = False
except Exception as e: ok = "names no page" in str(e) and "still holds" not in str(e)
check("anchors: a key that names nothing at all is refused as before", ok)
general(True)
out = server._anchors("projects/beta", who="t")
check("anchors: a page with one session lists as ever, naming the router and the keeper (its own session)", out.startswith("projects/beta anchors (router: rules this project; keeper: home-beta):") and "C0000000002" in out, out)
out = server._anchors("projects/alpha/kept", who="t")
check("anchors: a kept sub-page names the router, the keeper, then the agent that keeps it", out.startswith("projects/alpha/kept anchors (router: rules this project; keeper: work-osprey; kept by work-osprey-x):"), out)
general(False)

# ---- 9. an item on a sub-page an agent keeps is that agent's, not the keeper's
n0 = len(wait_push(0)); res = server._update("a4", next="a step on the kept page", sender="work-osprey-main")
check("writer told the change is charged to the page's agent", "charged to the agent work-osprey-x" in res and "charged to the keeper" not in res, res)
owed = server._owed_load(); check("ledger: the agent owes the kept page, the keeper does not", list(owed.get("projects/alpha/kept", {})) == [X], owed)
p = wait_push(n0 + 1); check("the agent is told, the keeper is not", len(p) == n0 + 1 and p[-1][0] == X and "the page update is yours as its agent" in p[-1][1], p[-1:])
res = server._update("a4", next="the agent edits its own page's item", sender="work-osprey-x"); owed = server._owed_load()
check("the agent's own write is not relayed and is its own debt", "charged" not in res and len(wait_push(n0 + 1)) == n0 + 1 and list(owed.get("projects/alpha/kept", {})) == [X], res)
res = server._update("a2", next="a step on the keeper-less sub-page", sender="home-beta"); p = wait_push(n0 + 2)
check("a keeper-less sub-page still charges the keeper", "charged to the keeper work-osprey" in res and p[-1][0] == S, res)

# ---- 10. the reminders (the keeper reminded, the -main agent told at three hours, a held notice re-surfaced, the re-send every hour and its cap, the lane check,
# the batch of reminders) are gone with the keeper: the router rules every notice, a notice it cannot rule is passed to a front agent at once, and the
# board's waiting light shows an unruled one. What the later sections need from the old setup stays: the page lists its -main agent, and nothing is left unruled.
pj = json.load(open(T / "store/projects.json")); pj["pages"]["projects/alpha"]["agents"] = {"work-osprey-main": "does the work"}; (T / "store/projects.json").write_text(json.dumps(pj))
for pk in routing.projects():                                          # earlier sections leave unruled, backdated notices: close them first
    for n in routing.read(pk):
        if n.get("pilot") and not n.get("ruling"): routing.rule(n["id"], "dropped", reason="closed before the checks that follow", by="work-osprey")
check("reminders are gone: routing has no due() or remind(), the server no _remind_tick", not hasattr(routing, "due") and not hasattr(routing, "remind") and not hasattr(server, "_remind_tick"))

# ---- 11. the -main agent is picked among the front agents only; a background agent is never the escalation target
pj = json.load(open(T / "store/projects.json")); keep = dict(pj["pages"]["projects/alpha"])
def reg_agents(agents, back):
    pj["pages"]["projects/alpha"]["agents"] = agents; pj["pages"]["projects/alpha"]["back_agents"] = back; (T / "store/projects.json").write_text(json.dumps(pj))
reg_agents({"x-docs": "writes the docs", "x-main": "sweeps"}, {"x-main": "sweeps"})                 # agents {x-docs, background: {x-main}}
check("_main_agent: a background -main is never picked; the first front agent is", server._main_agent("projects/alpha") == "x-docs", server._main_agent("projects/alpha"))
reg_agents({"x-main": "talks", "x-docs": "writes", "x-ops": "runs"}, {"x-ops": "runs"})              # agents {x-main, x-docs, background: {x-ops}}
check("_main_agent: the front -main wins", server._main_agent("projects/alpha") == "x-main", server._main_agent("projects/alpha"))
reg_agents({"x-ops": "runs", "x-main": "sweeps"}, {"x-ops": "runs", "x-main": "sweeps"})             # only background agents
check("_main_agent: only background agents → nobody", server._main_agent("projects/alpha") == "", server._main_agent("projects/alpha"))
pj["pages"]["projects/alpha"] = keep; (T / "store/projects.json").write_text(json.dumps(pj))

# ---- 12. the "Need your call (agents)" queue at the top of the board: one ticket per session
Q = T / "qstore"; (Q / "a").mkdir(parents=True); (Q / "projects.json").write_text((T / "store/projects.json").read_text())
qnow = datetime.datetime(2026, 2, 22, 12, 0, tzinfo=bd.now.tzinfo)
def qitem(i, owner, proj, ago, needs="", due="", nxt=""):
    md = {"owner": owner, **_mv(owner, needs), "project": proj, **({"needs": needs} if needs else {}), **({"due": due} if due else {}), **({"next": nxt} if nxt else {})}
    (Q / f"a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] queue item {i}", "description": "x", "status": "open", "metadata": md, "updated": (qnow - ago).timestamp()}))
H_ = datetime.timedelta(hours=1)
qitem(61, B, "projects/beta", 3 * H_, needs="decision", due="2026-02-27", nxt="pick vendor A or B; then tell the keeper")   # dated, waited 3 h
qitem(62, A, "projects/alpha", 48 * H_, nxt="ship the draft")                     # on agent, quiet 2 d → stale, still not in
qitem(63, A, "projects/alpha", 1 * H_)                                            # on agent, 1 h → not in
qitem(64, X, "projects/alpha/kept", 120 * H_, needs="external")                   # on others → never in
qitem(65, A, "projects/alpha/sub", 5 * H_, needs="decision")                      # undated, waited 5 h: leads the dated
qitem(60, A, "projects/alpha", 2 * H_, needs="decision")                          # A's second call → same ticket
qitem(66, S, "projects/alpha", 96 * H_)                                           # on agent, stale 4 d → not in
bq = ui_render.Board(str(Q), now=qnow); sala_on(); bq.sess[A]["gone"] = GONE   # home-beta has a live pane, work-osprey-main none
qh = bq.html()
# the home page's lists replaced the "Need your call (agents)" queue and the four item sections (part 1; tests/home_scenario.py covers the lists themselves)
check("home: the old queue, the four item sections, the state tiles and the Tasks overview are gone from the page", all(x not in qh for x in (
      '<section id="waiting">', '<section id="needs-your-call">', '<section id="waiting-on-others">', '<section id="on-agent">', 'id="overview"', '<a class="stat', '<li class="q-row"', '<li class="iline"', "Need your call (agents)")), re.findall(r'<section id="([a-z-]+)"', qh))
_onag = qh[qh.find('id="agents-at-work"'):qh.find('id="queued-release"')]
check("home: the stale on-agent item keeps its row in the On agent list", '<li class="irow hrow" id="task-a-62"' in _onag and 'href="/items/a62"' in _onag, _onag[:400])

# ---- 13. the project page's item lines (the board's old sections are gone; the lines live on the project page)
_pg = lambda k: (lambda h: h[h.find('<section id="items">'):h.find('<section id="sessions">')])(bq.routing_html(k))
ns = _pg("projects/beta")
check("item rows: one home-page row per item, the anchor id kept, one top line (the number and the goal linking /items/<gid>, the age)",
      '<li class="irow hrow" id="task-a-61" data-st="you"><div class="ir-top"><span class="ir-title"><a class="ir-link" href="/items/a61" target="_blank" rel="noopener"><span class="ir-id">a61</span> <span class="hgoal">queue item 61</span></a></span>' in ns, ns[:900])
check("…the age at the right of the top line, no mover on a Your move row, the step alone on its own line, no project label",
      re.search(r'id="task-a-61" data-st="you"><div class="ir-top">.*?<span class="tip ir-age" data-ts="\d+"[^>]*>3h ago</span></div>.*?<div class="ir-det"><span class="hnext">pick vendor A or B; then tell the keeper</span></div>', ns)
      and "hwho" not in ns[ns.find('id="task-a-61"'):ns.find("</li>", ns.find('id="task-a-61"'))] and "hproj" not in ns and "iown" not in ns, ns)
check("…the due badge is kept on the project page's rows, alone on the line under the top line; the home page's rows carry none",
      re.search(r'3h ago</span></div><div class="ir-who"><span class="badge due">Due in 5 d \(\d\d-\d\d [A-Z][a-z]{2}\)</span></div><div class="ir-det">', ns[ns.find('id="task-a-61"'):]) and "badge due" not in bd.html(), ns[ns.find('id="task-a-61"'):][:700])
_ns_a = _pg("projects/alpha")
check("…an item with no next step says so on its row", '<li class="irow hrow" id="task-a-60" data-st="you">' in _ns_a and 'no next step on the item' in _ns_a[_ns_a.find('id="task-a-60"'):][:600], _ns_a[:900])
_bh = bd.html()
_l61 = ns[ns.find('<li class="irow hrow" id="task-a-61" data-st="you">'):ns.find("</li>", ns.find('<li class="irow hrow" id="task-a-61" data-st="you">'))]
check("item rows: the top line (number, goal, age), then the due badge line, then the next step, in one row element, no right-hand group, no mover",
      _l61.find('class="ir-top"') < _l61.find('class="ir-id"') < _l61.find('class="hgoal"') < _l61.find('ir-age') < _l61.find('badge due') < _l61.find('class="ir-det"') < _l61.find('class="hnext"') and 'class="hr"' not in _l61 and "hwho" not in _l61, _l61)
_cs = bd._css()
check("item lines (Completed): a two-column grid, the subject and the meta both in column 2 (the meta row indented under the subject), the meta small and muted",
      "li.iline{display:grid;grid-template-columns:minmax(2.8em,max-content) minmax(0,1fr);" in _cs
      and re.search(r"li\.iline \.isubj\{grid-column:2;[^}]*overflow-wrap:anywhere", _cs)
      and re.search(r"li\.iline \.imeta\{grid-column:2;[^}]*font-size:12px;[^}]*color:var\(--mut\)", _cs)
      and "margin-left:auto" not in _cs[_cs.find("li.iline .imeta{"):_cs.find("}", _cs.find("li.iline .imeta{"))], _cs[_cs.find("ul.ilines"):][:900])
check("item rows: nothing expands inline on the project page or the board: no description, no next box, no card", "It lives here" not in _bh and 'class="next"' not in _bh and "article class=\"task\"" not in _bh
      and "It lives here" not in _ns_a and '<li class="irow hrow" id="task-a-60" data-st="you">' in _ns_a)
# the home page's folds: only Your move open, every other fold closed, each with its own key (Oliver step 3, part 1; only Your move open, nothing remembered)
_top = re.findall(r'<section id="([a-z-]+)"><details class="fold" data-fold="([a-z-]+)"( open)?><summary><h2[ >]', qh)
check("top sections: Your move and Queued for release are open by default, Agents at work and Waiting closed, each keyed by its own id; Machines and the Anchor hub sit in the panel; For you is hidden (ui_render._SHOW_FOR_YOU)",
      all(a == b for a, b, _o in _top) and [(a, o) for a, _b, o in _top if a not in ("machines", "runners", "anchorhub", "audit-panel", "projects-panel")] == [("your-move", " open"), ("agents-at-work", ""), ("queued-release", " open"), ("waiting-list", "")]
      and "for-you" not in {a for a, _b, _o in _top} and len({b for _a, b, _o in _top}) == len(_top), _top)
check("top sections: the side panel's sections render open (Machines, Runners, Anchor hub when there are receivers, Audit, and Projects), each keyed by its own id; the main column's fold state is as in the board item",
      {a for a, _b, _o in _top if a in ("machines", "runners", "anchorhub", "audit-panel", "projects-panel")} >= {"machines", "runners", "audit-panel", "projects-panel"}
      and all(o == " open" for a, _b, o in _top if a in ("machines", "runners", "anchorhub", "audit-panel", "projects-panel")), _top)
check("top sections: the heading is the summary, the old plain h2 is gone, no fold in the title bar, and the page holds no Tasks overview",
      "<summary><h2>Your move <span" in qh and '<section id="by-project"><h2' not in qh and '<details' not in qh[qh.find('<header class="top">'):qh.find('</header>')] and 'id="overview"' not in qh, _top)
# the summary panel: Machines and Anchor hub in a panel on the right, out of the main column,
# closed on every load and remembered nowhere; the main column starts at the three counts (part 1)
_mn = qh[qh.find('<main id="top">'):qh.find("</main>")]; _pn = qh[qh.find('<aside id="panel"'):qh.find("</aside>")]
check("panel: one aside after the main column holds Machines, and none of it is in the main column",
      qh.count('<aside id="panel"') == 1 and qh.find("</main>") < qh.find('<aside id="panel"') and '<section id="machines">' in _pn and all(x not in _mn for x in ('id="machines"', 'id="runners"', 'id="anchorhub"')), _pn[:300])
check("panel: the main column starts at the counts, then the four lists (For you is hidden), right after the title bar, with no For you section or jump link left",
      re.findall(r'<(?:section|nav)\b[^>]*?\bid="([a-z-]+)"', _mn)[:6] == ["counts", "your-move", "agents-at-work", "queued-release", "waiting-list"] and "for-you" not in _mn and "For you" not in _mn and "#for-you" not in qh[qh.find("<body"):],
      re.findall(r'<(?:section|nav)\b[^>]*?\bid="([a-z-]+)"', _mn)[:8])
check("panel: pinned on load: the body is rendered with panel-pin, the title bar's button expanded with 'Hide summary panel', the panel, edge and scrim in the markup",
      '<button type="button" class="b ico pbtn" id="panel-open" aria-label="Summary panel" aria-controls="panel" aria-expanded="true" title="Hide summary panel"' in qh[qh.find('<header class="top">'):qh.find('</header>')]
      and ui_render._PANEL_BODY + '<div id="layout"><main id="top">' in qh and qh.count('<body') == 1 and '<div id="panel-edge" aria-hidden="true"></div>' in qh and '<div id="panel-scrim"></div>' in qh)
_css = bq._css(); _wide = _css[_css.find("@media(min-width:800px){"):]
check("panel: the pinned look is only in the wide media query, so a phone's first paint stays a closed drawer; the drawer's open state is outside it",
      "panel-pin" not in _css[:_css.find("@media(min-width:800px)")] and "body.panel-pin #panel{z-index:9;padding-bottom" in _wide and "body.panel-pin #layout{padding-right:288px}" in _wide and "body.panel-pin #panel-open{color:var(--acc)" in _wide
      and "#panel{position:fixed;z-index:30;top:0;right:0;" in _css and "transform:translateX(100%);visibility:hidden" in _css and "body.panel-open #panel{transform:none;visibility:visible" in _css)
check("panel: the script starts from the rendered class, pinned only when wide, corrects the button at once, and sets the page's same default when the width crosses 800 px; a swap never touches the body",
      "D=b.classList.contains('panel-pin'),s={peek:false,pin:D&&!M.matches,open:false,t:0}" in ui_render._PANEL_JS and "apply();reveal();" in ui_render._PANEL_JS
      and "s.pin=!M.matches&&D;apply()" in ui_render._PANEL_JS and "panel-pin" not in ui_render._LIVE_JS and "panel-open" not in ui_render._LIVE_JS and "classList" not in ui_render._LIVE_JS.replace("B.className", ""))
check("panel: nothing is stored in the browser (the state is the person's, kept on the server): no localStorage, sessionStorage, cookie, history or indexedDB call in the panel's script, no stored key, no pre-paint read in the page; a click on a wide screen pins or unpins and saves it (POST /prefs/panel-open), the drawer never saves",
      re.search(r"localStorage|sessionStorage|cookie|history|indexedDB|stored\(|save\(", ui_render._PANEL_JS) is None and "stackshot.panel" not in ui_render._PANEL_JS and "stackshot.fold" not in ui_render._PANEL_JS
      and not hasattr(render, "_PANEL_KEY") and not hasattr(render, "_PANEL_PRE") and "stackshot.panel" not in qh and "s.pin=!s.pin;s.peek=false;D=s.pin;apply();keep(s.pin)" in ui_render._PANEL_JS
      and "if(narrow()){if(s.open)shut();else{s.open=true;apply();if(X)X.focus({preventScroll:true})}return}\ns.pin=!s.pin" in ui_render._PANEL_JS and ui_render._PANEL_JS.count("keep(") == 2 and "'/prefs/panel-open'" in ui_render._PANEL_JS and "@ROOT@" not in ui_render._PANEL_JS
      and "panel-pin" not in ui_render._LIVE_JS and "panel-open" not in ui_render._LIVE_JS and ui_render._PANEL_JS in qh and "localStorage" not in qh[qh.find('<aside id="panel"'):qh.find("</aside>")])
check("panel: every page, the item page too, is drawn pinned (<body class=\"panel-pin\">, nothing before the layout) and the closed form is a bare <body> with the button offering to show the panel (apply_panel_open)",
      ui_render._PANEL_BODY == '<body class="panel-pin">' and ui_render._PANEL_BODY in qh and ui_render._PANEL_BODY_CLOSED == '<body>'
      and ui_render._PANEL_BTN_CLOSED.count('aria-expanded="false" title="Show summary panel"') == 1 and 'aria-expanded="true"' not in ui_render._PANEL_BTN_CLOSED
      and 'aria-expanded="true" title="Hide summary panel"' in ui_render._PANEL_BTN and '<header class="top">\n' + ui_render._THEME_BTN + ui_render._PANEL_BTN + "\n" in bq.page_header()
      and 'class="panel-pin"' in bd.item_html("a1") and ui_render._PANEL_BODY + '<div id="layout"><main class="itempage"' in bd.item_html("a1")
      and 'aria-expanded="true" title="Hide summary panel"' in bd.item_html("a1")
      and ui_render.apply_panel_open(qh, True) == qh and ui_render.apply_panel_open("<p>no panel</p>", False) == "<p>no panel</p>"
      and ui_render._PANEL_BODY_CLOSED + '<div id="layout"><main id="top">' in ui_render.apply_panel_open(qh, False) and 'class="panel-pin"' not in ui_render.apply_panel_open(qh, False)
      and '<header class="top">\n' + ui_render._THEME_BTN + ui_render._PANEL_BTN_CLOSED + "\n" in ui_render.apply_panel_open(qh, False)
      and ui_render.apply_panel_open(qh, False).count('aria-expanded="false" title="Show summary panel"') == 1)
check("theme button: the markup keeps a space between its attributes (id=\"theme\" aria-label=), on every page that carries it",
      'id="theme" aria-label=' in ui_render._THEME_BTN and 'id="theme"aria-label' not in ui_render._THEME_BTN and 'id="theme" aria-label=' in qh and 'id="theme"aria-label' not in qh and 'id="theme"aria-label' not in bd.item_html("a1"))
_BMQ = re.search(r'<meta name="stackshot-blocks" content="([^"]*)">', qh).group(1)
check("panel: the in-place update swaps only the blocks inside it; the frame (aside, edge, scrim, button) is no block, so a swap leaves it open or pinned",
      all(k in _BMQ for k in ("counts=", "your-move=", "machines=", "audit-panel=")) and all(f'id="{k}"' in qh for k in ("panel", "panel-edge", "panel-scrim", "panel-open")) and not any(k in {x.split("=")[0] for x in _BMQ.split()} for k in ("panel", "panel-edge", "panel-scrim", "overview", "tasks"))
      and "document.getElementById(k)" in ui_render._LIVE_JS, _BMQ)
check("panel: wide screens (800 px and up) peek on hover and pin on a click, narrower ones a drawer; a hash into it opens it",
      "(max-width: 799.98px)" in ui_render._PANEL_JS and ui_render._PANEL_DOCK_PX == 800 and "'mouseenter'" in ui_render._PANEL_JS and "s.pin=!s.pin" in ui_render._PANEL_JS and "hashchange" in ui_render._PANEL_JS and "setAttribute('aria-label'" not in ui_render._PANEL_JS and "if(was)B.focus(" in ui_render._PANEL_JS
      and "#panel .tip:hover::after{left:auto;right:0;width:max-content;max-width:min(200px,70vw);white-space:normal" in bq._css()
      and "@media(min-width:800px){" in bq._css() and "body.panel-pin #layout{padding-right:288px}" in bq._css(), ui_render._PANEL_JS[:200])
check("panel: a click on a link in the open drawer closes it only for a plain same-origin link without a target (a link that opens a tab or leaves the board keeps the drawer)",
      "||a.origin!==location.origin||a.target)return;" in ui_render._PANEL_JS and ui_render._PANEL_JS.index("a.origin!==location.origin") < ui_render._PANEL_JS.index("a.pathname===location.pathname"), ui_render._PANEL_JS[-900:-500])
# the board item: the buttons are fixed at the window's top right in every state, the panel starts right under them, 280 px wide, peeking or pinned alike
_wcss = bq._css(); _wi = _wcss.find("@media(min-width:800px){\nbody::before"); _w = _wcss[_wi:]; _w = _w[:_w.find(".phead{display:none}}")]; _nw = _wcss[:_wi]   # the panel's own wide block (the item page's has an earlier one)
check("panel placement: wide screens: the title bar's panel and theme buttons are position:fixed at the top right (the two buttons every page's title bar holds), above a 56 px band with the page background; no state class moves them",
      "body::before{content:\"\";position:fixed;top:0;right:0;width:104px;height:56px;background:var(--bg);z-index:8;pointer-events:none}" in _w
      and ui_render._THEME_BTN + ui_render._PANEL_BTN in bq.page_header()   # the title bar every page draws holds both buttons
      and "header.top .theme,header.top .pbtn{position:fixed;z-index:10}" in _w
      and "header.top .theme{position:absolute;top:12px;right:16px}header.top .pbtn{position:absolute;top:12px;right:calc(24px + var(--ico))}" in _nw
      and re.search(r"panel-(?:pin|peek|open)[^{}]*[.](?:tb|theme|pbtn)\b|[.](?:tb|theme|pbtn)\b[^{}]*panel-(?:pin|peek|open)", _w) is None, _w[:900])
check("panel placement: peeking and pinned, the panel is position:fixed at the window's right edge, 280 px wide, starting 56 px from the top (the band's bottom), and the hover strip starts there too; no --ptop or --hdr offset",
      "#panel{top:56px;height:calc(100dvh - 56px);width:280px;padding-top:14px}" in _w and "#panel-edge{display:block;position:fixed;z-index:29;top:56px;right:0;bottom:0;width:8px}" in _w
      and "body.panel-peek #panel{transform:none;visibility:visible" in _w and "body.panel-pin #panel{z-index:9;padding-bottom:" in _w and "position:sticky" not in _w and "--ptop" not in _wcss and "var(--hdr" not in _w
      and "top:0;right:0;height:100dvh;width:min(300px,88vw)" in _nw and "256px" not in _w and "--ptop" not in ui_render._PANEL_JS and "function top()" not in ui_render._PANEL_JS)
check("panel placement: pinned, #layout leaves room on its right for the panel (no grid: the panel is fixed), 288 px = 280 + 8 beside the body's 16 px padding; the item page's one-column strip edge is still 1088 px",
      "body.panel-pin #layout{padding-right:288px}" in _w and "display:grid" not in _w and ui_render._PANEL_PX == 280 and ui_render._PANEL_TOP_PX == 56 and ui_render._PANEL_RESERVE_PX == ui_render._PANEL_PX + 8 and ui_render._ITEM_PIN_STRIP_PX == 1088)
check("panel placement: under 800 px nothing of it is in the base rules: the drawer (#panel from the top, 100dvh, translated out), the buttons absolute in the page header, and no band",
      "body::before" not in _nw and "#panel{position:fixed;z-index:30;top:0;right:0;height:100dvh;" in _nw and "transform:translateX(100%);visibility:hidden" in _nw and "position:fixed;z-index:10" not in _nw and "body.panel-pin #panel" not in _nw and "body.panel-pin #layout" not in _nw)
_fav = render.icon_href("favicon.svg")
check("header: the board's title carries stackshot's icon, decorative, at the favicon's own versioned URL",
      re.search(r'<h1 class="site"><a href="/"><img class="logo" src="' + re.escape(_fav) + r'" alt="" aria-hidden="true">', qh) is not None and f'<link rel="icon" href="{_fav}"' in qh
      and "h1 .logo,.site .logo{width:1.2em;height:1.2em;" in bq._css(), _fav)
check("top sections: the home page keeps no stored fold state (its script reads and writes none, the swap carries only the live open state over and reads no storage)",
      "localStorage.getItem" not in ui_render._HOME_FOLD_JS and "localStorage.setItem" not in ui_render._HOME_FOLD_JS and "if(k in f)d.open=f[k]" in ui_render._LIVE_JS
      and "localStorage.getItem('stackshot.fold." not in ui_render._LIVE_JS and "<script>" + ui_render._HOME_FOLD_JS + "</script>" in qh and ui_render._FOLD_JS not in qh)
import _colors as _C1; _qh_full, qh = qh, _C1.without_colortool(qh)      # the color tool's library (shared/colortool.js) watches data-theme with a MutationObserver: the next check reads the page without its script blocks
check("board: no pre-paint fold script in the head (the markup is the state: Your move open, the rest closed); the pre-paint script stays on the item and project pages",
      ui_render._FOLD_HEAD not in qh and "MutationObserver" not in qh[:qh.find("</head>")] and "stackshot.fold." not in qh[:qh.find("</head>")], qh.find(ui_render._FOLD_HEAD))
qh = _qh_full
_js = qh[qh.find("<script>(function(){try{[\"for-you\""):][:1600]
check("sections: state kept nowhere: no read, no write, no toggle listener; the old section keys are removed once on load, guarded (storage that throws = nothing happens), and only those keys (the item and project folds keep theirs)",
      "try{[\"for-you\", \"your-move\", \"agents-at-work\", \"queued-release\", \"waiting-list\", \"by-project\", \"completed\", \"machines\", \"anchorhub\"].forEach(function(k){localStorage.removeItem('stackshot.fold.'+k)})}catch(e){}" in _js
      and "getItem" not in _js and "setItem" not in _js and "addEventListener('toggle'" not in _js and "item." not in _js.split("function go")[0] and "project." not in _js.split("function go")[0]
      and 0 < qh.find("</main>") < qh.find('<section id="machines">') < qh.find(_js[:40]), _js)   # the script runs after the panel, so its folds are reached too
_pj = qh[qh.find(ui_render._PANEL_JS):][:len(ui_render._PANEL_JS)]
_css = qh[qh.find("<style>"):qh.find("</style>")]
check("panel sections: one card spacing, the Anchor hub's: the cards sit 8px apart (no 14px gap rule left for Machines or Runners), a Machines or Runners card has the .pc padding and row gap (no row-gap of its own), its name has no padding or margin, and the Audit card is a .pc card (class pc audit) with the .pc padding, radius and gaps and no rule of its own for them",
      "gap:14px" not in _css and ".pc.mach{grid-template-columns:minmax(0,max-content) minmax(0,max-content) minmax(0,1fr);min-width:0}" in _css and "row-gap:3px" not in _css
      and ".pc.mach .mh{grid-column:1/-1;display:block;margin:0;padding:0;" in _css and ".matrix{display:grid;gap:8px;margin:0 0 6px}" in _css
      and ".pc{display:grid;grid-template-columns:max-content max-content;column-gap:8px;row-gap:2px;align-items:baseline;padding:6px 10px;border:1px solid var(--line);border-radius:10px;" in _css
      and "#panel #audit-panel .audit{" not in _css and ".audit{display:flex" not in _css and ".audit{margin:0;font-size:12px}" in _css, _css[_css.find("#audit-panel"):][:400])
check("panel sections: a machine row that is behind shows its new version in the text colour and is not wrapped in the panel, so its '→ <latest>' stays on one line (the words are in machines_scenario)",
      ".mr.update .st{color:var(--fg);font-weight:600}" in _css and "#panel #machines .mr.update .st{white-space:nowrap}" in _css, _css[_css.find(".mr.update"):][:200])
check("panel sections: the Machines cards share one set of three columns (the matrix owns them, each card takes them by subgrid), so the 'latest' values line up from card to card (the Runners cards are one line each since)",
      "#panel #machines .matrix{grid-template-columns:minmax(0,max-content) minmax(0,max-content) minmax(6em,1fr)}" in _css
      and "#panel #runners .matrix{grid-template-columns" not in _css and "#panel #runners .matrix" not in _css
      and "#panel #machines .mcol{grid-column:1/-1;grid-template-columns:subgrid}" in _css and "#panel #machines .pc.mach{grid-template-columns:subgrid}" in _css
      and "#panel #machines .mcol>.pc{grid-column:1/-1}" in _css and ".mr{grid-column:1/-1;display:grid;grid-template-columns:minmax(0,max-content) minmax(0,max-content) minmax(0,1fr);grid-template-columns:subgrid;" in _css, _css[_css.find(":is(#machines"):][:300])
check("panel sections: no fold-storage key is read or written for Machines, Runners, Anchor hub or Audit (neither script has a storage call), and the in-place swap keeps each fold as it is on screen",
      "stackshot.fold" not in ui_render._PANEL_JS and "sessionStorage" not in ui_render._PANEL_JS and "localStorage" not in ui_render._AUDIT_JS and "sessionStorage" not in ui_render._AUDIT_JS
      and "localStorage" not in ui_render._HOME_FOLD_JS.replace("localStorage.removeItem('stackshot.fold.'+k)", "") and _pj == ui_render._PANEL_JS
      and "o.querySelectorAll('details.fold').forEach(function(d){f[d.getAttribute('data-fold')]=d.open})" in ui_render._LIVE_JS and "if(k in f)d.open=f[k]" in ui_render._LIVE_JS
      and "stackshot.fold." not in ui_render._LIVE_JS and "audit-panel" not in ui_render._HOME_FOLD_JS, ui_render._PANEL_JS[:200])
check("sections: a hash to a section or to a line inside one opens it; the three counts' links do too", "el.closest('details.fold')" in _js.replace("el.closest&&el.closest", "el.closest") and "el.querySelector('details.fold')" in _js
      and "addEventListener('hashchange'" in _js and all(f'href="#{h}"' in qh[qh.find('id="counts"'):qh.find("</nav>", qh.find('id="counts"'))] for h in ("your-move", "agents-at-work", "waiting-list")), _js)
check("row ids open the item's page in a new tab", '<a class="ir-link" href="/items/a61" target="_blank" rel="noopener"><span class="ir-id">a61</span>' in qh and 'href="#task-a-61"' not in qh)
check("markdown keeps its expanded items", "- It lives here." in bd.markdown())

# ---- 14. the item page (/items/<gid>): fields, whose move in words, links
ip = bq.item_html("a61")
check("item page: titled by its id and subject, back link to the board, theme switch", '<h1><span class="hid">a61</span> queue item 61</h1>' in ip and '<p class="site"><a href="/"><img class="logo"' in ip and '<a href="/">← ' not in ip and ip.count('id="theme"') == 1 and "<title>a61 · queue item 61</title>" in ip, ip[:900])
_side = lambda h: h[h.find('<aside class="iside"'):h.find("</aside>")]       # the right-hand sidebar (GitHub's issue layout)
_istat = lambda h: h[h.find('<div class="istat">'):h.find("</div>", h.find('<div class="istat">'))]
check("item page: the state line (item model) — the state tag and since; the mover and who takes it next are the sidebar's Mover and Then rows, due and priority are in the sidebar too, not here (the id in the title)",
      _istat(ip).startswith('<div class="istat"><p class="istate"><span class="tag t-you">Your move</span> · since ') and " · then " not in _istat(ip) and "mover" not in _istat(ip) and "your call" not in _istat(ip) and "Due " not in _istat(ip)
      and "prio-" not in _istat(ip) and 'class="iid"' not in _istat(ip), _istat(ip))
check("item page: the sidebar opens with the mover, then holds project, then, priority, each a small heading over its value, and no Expected by; due sits in the closed More details fold, the mover does not",
      '<dl class="sgrp"><dt>Then</dt><dd>' in _side(ip) and 'Expected by' not in _side(ip)
      and _side(ip).startswith('<aside class="iside" aria-label="Details"><dl class="sgrp"><dt>Mover</dt><dd><a href="https://sala.example.org/#s=home-beta"') and _side(ip).count("<dt>Mover</dt>") == 1
      and _side(ip).find("<h3>More details</h3>") > _side(ip).find("<dt>Mover</dt>") and "<dt>Mover</dt>" not in _side(ip).split("<h3>More details</h3>")[1] and '<dt>Project</dt><dd><a href="/projects/beta">home/Beta</a>' in _side(ip)
      and '<dt>Priority</dt><dd>P2</dd></dl>' in _side(ip) and _side(ip).find("<h3>More details</h3>") < _side(ip).find('<dt>Due</dt><dd><span class="badge due">Due in 5 d')
      and '<details class="fold imore" data-fold="item.more"><summary><h3>More details</h3></summary>' in _side(ip) and "<dt>Whose move</dt>" not in _side(ip), _side(ip))
check("item page: two columns — the title over a wrapper holding the sidebar (first in the source, for the phone) and the main column",
      ip.index("</h1>") < ip.index('<div class="ilayout"><aside class="iside" aria-label="Details">') < ip.index("</aside><div class=\"imain\">"), ip[ip.find("</h1>"):][:300])
check("item page: the main column holds status, Next, Background and History in that order (the Ask and the answer box: answer_scenario), and no sidebar field",
      (lambda m: 0 <= m.find('<div class="istat">') < m.find("<h2>Next</h2>") < m.find("<h2>Background</h2>") < m.find("<h2>History")
       and "<dt>Mover</dt>" not in m and "<dt>Project</dt>" not in m)(ip[ip.find('<div class="imain">'):]), ip[ip.find('<div class="imain">'):][:400])
check("item page: Background is a fold, open; History and Comments are folds, closed by default; the fold head and script are in",
      '<details class="fold" data-fold="item.description" open id="description">' in ip and '<details class="fold" data-fold="item.history" id="history">' in ip
      and '<details class="fold" data-fold="item.comments" id="comments">' in ip and ui_render._FOLD_HEAD in ip and ui_render._FOLD_JS in ip and ui_render._THEME_HEAD in ip)
check("item page: the grid puts the sidebar on the right (256px), and under 768px folds to one column",
      ".ilayout{display:grid;grid-template-columns:minmax(0,1fr) 256px;" in ip and ".iside{grid-column:2;grid-row:1;" in ip
      and "@media(max-width:767px){.ilayout{grid-template-columns:minmax(0,1fr)}.imain,.iside{grid-column:1;grid-row:auto}" in ip, re.findall(r"\.ilayout\{[^}]*\}|@media\(max-width:767px\)\{[^@]*", ip)[:3])
check("item page: on a phone the Ask and the answer box come before the fields: the main column's boxes become grid items, status, Ask and answer first, the sidebar next, the rest after",
      ".imain{display:contents}.imain>*{order:2}.imain>.istat,.imain>.iask,.imain>.ianswer,.imain>.iwait,.imain>.ioutcome{order:0}.iside{order:1}" in ip[ip.find("@media(max-width:767px)"):], ip[ip.find("@media(max-width:767px)"):][:400])
check("item page: the id in the h1 is the title's first word, drawn as the title is, and the <title> starts with the id",
      ip.find("<title>a61 · ") > 0 and "main.itempage h1 .hid{font-family:inherit;font-weight:400;color:inherit}" in bq._css(), ip[:400])
check("item page: the model's state as a tag for an outside wait (Waiting) and an agent's item (On agent)", '<span class="tag t-wait">Waiting</span>' in bq.item_html("a64") and '<span class="tag t-agent">On agent</span> · since ' in bq.item_html("a63") and " · mover <b>" not in bq.item_html("a63") and "<dt>Mover</dt>" in bq.item_html("a63"), bq.item_html("a64")[bq.item_html("a64").find("istate"):][:300])
# every badge is a GitHub-style label: a pill with a tinted fill, text and border in the value's colour, 12px medium;
# one colour per value, from the theme tokens, so the board's rows and the item page draw the same label
_css = bq._css()
_lab = lambda cls: (re.search(rf"\.badge\.{re.escape(cls)}(?![-\w])[^{{}}]*\{{--bc:var\(--([a-z0-9]+)\)[;}}]", _css) or [None, None])[1]
_LABS = ("call", "agent", "relay", "prio-p1", "prio-p2", "prio-p3", "w-in-progress", "w-assigned", "w-defined", "w-done", "open", "hold", "done")
check("labels: one rule draws every badge as a pill, tinted fill, text and 1px border in its colour, 12px medium, no left margin",
      re.search(r"\.badge\{--bc:var\(--mut\);display:inline-block;font-size:12px;font-weight:500;[^}]*border-radius:2em;border:1px solid var\(--bc\);"
                r"color:color-mix\(in srgb,var\(--bc\) var\(--ink\),var\(--fg\)\);background:color-mix\(in srgb,var\(--bc\) 16%,transparent\);margin-right:4px;", _css)
      and not re.search(r"\.badge[.\w-]*\{(color|border-color):", _css), re.findall(r"[^}]*\.badge[.\w-]*\{(?:color|border-color):[^}]*\}", _css) or re.findall(r"\.badge\{[^}]*\}", _css))
# priority red-yellow-green and "on others" one purple everywhere
check("labels: whose move, priority, work line and status each take their colour",
      {c: _lab(c) for c in _LABS} == {"call": "call", "agent": "run", "relay": "relay", "prio-p1": "p1", "prio-p2": "yellow", "prio-p3": "ok", "w-in-progress": "ok",
                                      "w-assigned": "run", "w-defined": "mut", "w-done": "mut", "open": "ok", "hold": "warn", "done": "run"}, {c: _lab(c) for c in _LABS})
check("labels: --relay is the purple in both themes, so the on-others badge matches; the text mix is a token in both (light 65% for contrast, dark all of it)",
      "--relay:#8250df;" in _css and _css.count("--relay:#bc8cff;") == 2 and "--purple" not in _css and "--ink:65%;" in _css and _css.count("--ink:100%;") == 2
      and ".badge.relay,.badge.oc-superseded{--bc:var(--relay)}" in _css, re.findall(r"--relay:[^;]*|--ink:[^;}]*", _css))
check("labels: p2 is a true yellow in both themes, its text kept to 45% of it in light (5.5:1 on its tint) and all of it in dark",
      "--yellow:#d9b200;--ink:65%;--yellow-ink:45%}" in _css and _css.count("--yellow:#f0c929;--ink:100%;--yellow-ink:100%;") == 2
      and ".badge.prio-p2{--bc:var(--yellow);--ink:var(--yellow-ink)}" in _css, re.findall(r"--yellow[-\w]*:[^;}]*|\.badge\.prio-p2\{[^}]*\}", _css))
check("item page: the owner links to its view in sala in a new tab, with its machine", f'{_sl("home-beta", arrow=" ↗")} <span class="dim">· testbox</span>' in ip, ip[ip.find("iprops"):][:600])
_ia60 = bq.item_html("a60")
check("item page: an owner with no live pane is plain text", '<dt>Mover</dt><dd>work-osprey-main <span class="dim">· testbox</span></dd>' in _side(_ia60), _side(_ia60))
sala_on(False)
check("item page: the project links its details page in the same tab, and its gbrain page", '<dd><a href="/projects/beta">home/Beta</a> <span class="dim">·</span> <a href="https://example.invalid/Beta" target="_blank" rel="noopener">gbrain page ↗</a></dd>' in ip, ip[ip.find("iprops"):][:600])
check("item page: next as a list, a line whole with its mover named, description as on the board", '<h2>Next</h2></summary><ul class="inext" aria-label="Next steps"><li class="cl-open"><span class="cb" aria-hidden="true"></span><div class="cl-b"><span class="sr">To do: </span><span class="cl-t">the owner: pick vendor A or B; then tell the keeper</span></div></li></ul>' in ip and '<h2>Background</h2></summary><div class="desc md"><p>x</p>\n</div>' in ip, ip[ip.find("<h2>Next"):][:400])
check("item page: no anchors field when none is scoped to it", "<dt>Anchors" not in ip and 'class="alist"' not in ip)
# a command the owner runs: a backticked span is <code>,
# verbatim and never linked; in a Next line addressed to the owner, a span with a space leaves the line for its own block with a copy button
check("code span: <code>, verbatim, never linked, never split", render.linkify("run `curl https://x.invalid/a?b=1`") == "run <code>curl https://x.invalid/a?b=1</code>"
      and render.next_steps("Oliver: run `a; b -> c` then x; y") == [(0, "Oliver: run `a; b -> c` then x"), (0, "y")], render.linkify("run `curl https://x.invalid/a?b=1`"))
check("code span: a link whose label holds code stays one link; a stray backtick never stops a split",
      render.linkify("see [`server.py`](https://x.invalid/s?a=1&b=2) now") == 'see <a href="https://x.invalid/s?a=1&amp;b=2" target="_blank" rel="noopener"><code>server.py</code> ↗</a> now'
      and render.next_steps("it`s a; b") == [(0, "it`s a"), (0, "b")] and len(render.sentences("one ` here\ntwo")) == 2,
      (render.linkify("see [`server.py`](https://x.invalid/s?a=1&b=2) now"), render.next_steps("it`s a; b"), render.sentences("one ` here\ntwo")))
_o = ui_render._OWNER; ui_render._OWNER = "Oliver"
_c1 = bq.cmd_step("Oliver: in PowerShell run `ssh -t box-a '/x/tool check'` and type `yes` when asked")
_c2 = bq.cmd_step("Oliver: run `a b` then `c d`"); _c3 = bq.cmd_step("Then run `a b`")
_c4 = bq.cmd_step("Oliver: in PowerShell run `ssh -t box-a 'tool check --all'` and type yes when asked")   # the item's line
_c5 = bq.cmd_step("Oliver: read [`a b`](https://x.invalid/r) first")
ui_render._OWNER = _o
check("command: its own block with a copy button, the line pointing at it", _c1 == ("Oliver: in PowerShell run the command below and type <code>yes</code> when asked"
      '<div class="cplace"><span>Runs on box-a</span></div><div class="cmd"><pre><code>ssh -t box-a &#x27;/x/tool check&#x27;</code></pre><button type="button" class="b copy" aria-label="Copy the command">Copy</button></div>'), _c1)
check("command: several are numbered; a line not addressed to the owner keeps them inline", _c2.startswith("Oliver: run command 1 below then command 2 below<div class=\"cplace\"><span>In PowerShell</span></div><div class=\"cmd\">")
      and _c2.count('class="b copy"') == 2 and _c3 == "Then run <code>a b</code>", (_c2, _c3))
check("command: the item's line comes out as one block; code in a link's label is never a command",
      _c4.startswith("Oliver: in PowerShell run the command below and type yes when asked<div class=\"cplace\"><span>Runs on box-a</span></div><div class=\"cmd\">")
      and "<code>ssh -t box-a &#x27;tool check --all&#x27;</code>" in _c4 and _c4.count('class="b copy"') == 1
      and 'class="cmd"' not in _c5 and "<code>a b</code> ↗</a>" in _c5, (_c4, _c5))
check("command: the item page carries the copy script and the block style", "closest('button.copy')" in ip and "navigator.clipboard" in ip and ".cmd button.copy{" in bq._css())
check("item page: every link absolute or external", not re.findall(r'(?:href|src)="(?!/|https?:|#)[^"]*"', ip), re.findall(r'(?:href|src)="(?!/|https?:|#)[^"]*"', ip))
check("item page: dark tokens follow the system and the switch", ":root:not([data-theme=light]){--bg:#161617" in ip and ":root[data-theme=dark]{--bg:#161617" in ip)
try: bq.item_html("a47"); check("item page: unknown id → KeyError", False)
except KeyError: pass
check("item page: no git → an empty history, said plainly", "no history in the store's git" in ip)

# ---- 15. on hold (an open item with metadata.hold, optional metadata.wake): out of the queue; a kind of on agent —
# muted in the index's on-agent column, after the active lines in the On agent section, counted under on agent and open only; the item page says so.
# the item is a row with the retired status "on_hold" (a stale file the server's start-time migration has not rewritten): it reads as held all the same
qitem(67, B, "projects/beta", 30 * H_, needs="external", nxt="wait on Kim")
qitem(68, A, "projects/alpha", 120 * H_)
for i_, w_ in ((67, "2026-03-02"), (68, "")):
    d_ = json.loads((Q / f"a/{i_}.json").read_text())
    if i_ == 68: d_["status"] = "on_hold"
    else: d_["metadata"]["hold"] = True
    if w_: d_["metadata"]["wake"] = w_
    (Q / f"a/{i_}.json").write_text(json.dumps(d_))
bh = ui_render.Board(str(Q), now=qnow); hh = bh.html()
_hl = lambda h, g: sum(h[h.find(f'<section id="{sid}"'):h.find("</section>", h.find(f'<section id="{sid}"'))].count(f'id="task-a-{g}"') for sid in ("your-move", "agents-at-work", "waiting-list"))
check("held: on the home page in exactly one of the three lists, never in two, and never in the removed queue", _hl(hh, 67) == 1 and _hl(hh, 68) == 1 and "q-row" not in hh, (_hl(hh, 67), _hl(hh, 68)))
_na = len(bh.agent)
check("held: counted under on agent and open, never your call or on others", all(r["gid"] not in ("a67", "a68") for r in bh.n_call + bh.n_relay + bh.agent) and bh.n_open == 7
      and len(bh.held) == 2 and {r["gid"] for r in bh.held} == {"a67", "a68"}, (bh.n_open, _na, [r["gid"] for r in bh.n_call]))
_hc = {sid: re.search(rf'<section id="{sid}"><details class="fold" data-fold="{sid}"(?: open)?><summary><h2>[^<]*<span class="count">(\d+)</span>', hh) for sid in ("your-move", "agents-at-work", "waiting-list")}
_hn = {sid: int(m.group(1)) if m else None for sid, m in _hc.items()}
_hr = {sid: len(re.findall(r'<li class="irow hrow', hh[hh.find(f'<section id="{sid}"'):hh.find("</section>", hh.find(f'<section id="{sid}"'))])) for sid in _hn}
check("held: the three list headers' numbers are the rows in each list, and together the open items — the 7 not held and the 2 held", _hn == _hr and sum(_hn.values()) == bh.n_open + len(bh.held) == 9
      and re.findall(r'<a class="hcard[^"]*" href="#(your-move|agents-at-work|waiting-list)"[^>]*><b>(\d+)</b>', hh) == [(k, str(v)) for k, v in _hn.items()], (_hn, _hr, bh.n_open, len(bh.held)))
check("held: in by_proj, so their project keeps its row", {r["gid"] for rs in bh.by_proj.values() for r in rs} >= {"a67", "a68"})
_wl = hh[hh.find('<section id="waiting-list"'):hh.find("</section>", hh.find('<section id="waiting-list"'))]
check("held: its row is on the Waiting list, with who takes it then", 'id="task-a-67"' in _wl and 'id="task-a-68"' in _wl and _wl.count('<span class="hwait">') >= 2, _wl[:900])
check("held: no separate on-hold section", 'id="on-hold"' not in hh and 'class="onhold"' not in hh and 'id="on-agent"' not in hh)
hp_ = bh.item_html("a67")
check("held: the item page says it waits and until when, not whose move", '<span class="tag t-wait">Waiting</span>' in hp_ and "<dt>Watched by</dt><dd>the scheduler</dd><dt>Until</dt><dd>Mon Mar 2nd</dd>" in hp_ and "your call</span>" not in hp_, hp_[hp_.find('class="istate"'):][:400])
_md = bh.markdown(); _mdw = _md[_md.find("\n## Waiting\n"):_md.find("\n## On agents\n")]; _mda = _md[_md.find("\n## On agents\n"):_md.find("## Completed")]
check("held: board.md lists them in the list the model puts them in (a hold with a wake is a wait), marked, and drops the On hold section", "## On hold" not in _md
      and "**a67 · [home] queue item 67** (on hold, wake Mon Mar 2nd)" in _mdw and "**a68 · [home] queue item 68** (on hold, no wake date)" in _mdw + _mda
      and "waiting on needs your call" not in _md and "[a67](#task-a-67) (on hold)" in _md and "_9 open · " in _md and "on hold)" not in _md[:_md.find("## Machines")], (_mdw[-900:], _mda[-300:]))
check("held: the helper is the one place", render.is_held({"status": "open", "metadata": {"hold": True}}) and render.is_held({"status": "on_hold"})
      and not render.is_held({"status": "open"}) and not render.is_held({"status": "open", "metadata": {"hold": False}}) and not render.is_held({"status": "completed", "metadata": {"hold": True}})
      and not render.is_held({"status": "held"}) and render.wake_of({"metadata": {"wake": "2026-03-02"}}) == datetime.date(2026, 3, 2))
check("held: a legacy on_hold row is loaded as open + hold, so nothing downstream sees the retired status", bh.item("a68")["status"] == "open" and bh.item("a68")["metadata"].get("hold") is True)
# a wake with a time of day: drawn with its clock, sorted by the minute
qitem(69, B, "projects/beta", 10 * H_, needs="external")
d_ = json.loads((Q / "a/69.json").read_text()); d_["metadata"]["hold"] = True; d_["metadata"]["wake"] = "2026-03-02T09:30"
(Q / "a/69.json").write_text(json.dumps(d_))
bt = ui_render.Board(str(Q), now=qnow); ht = bt.html()
check("held, timed wake: parsed as a datetime in the instance timezone", render.wake_of({"metadata": {"wake": "2026-03-02T09:30"}}) == datetime.datetime(2026, 3, 2, 9, 30, tzinfo=render._cfg.tz())
      and render.wake_of({"metadata": {"wake": "2026-03-02 09:30"}}) == datetime.datetime(2026, 3, 2, 9, 30, tzinfo=render._cfg.tz()))
check("held, timed wake: the item page shows the clock", "<dt>Until</dt><dd>Mon Mar 2nd 09:30</dd>" in bt.item_html("a69"), bt.item_html("a69")[bt.item_html("a69").find('class="istate"'):][:300])
check("held, timed wake: sorted by the minute (a date-only wake is its midnight, so it goes first)", [r["gid"] for r in bt.held][:2] == ["a67", "a69"], [r["gid"] for r in bt.held])
check("held, timed wake: board.md shows the clock", "(on hold, wake Mon Mar 2nd 09:30)" in bt.markdown())
check("held, timed wake: a held relay stays out of the relays and the calls", all(r["gid"] not in ("a67", "a68", "a69") for r in bt.n_relay + bt.n_call) and len(bt.held) == 3, [r["gid"] for r in bt.n_relay])

# ---- 15b. the four item sections grouped by scope: the Task board's scopes in its order ([scopes] order here:
# work, home, ops), an item under its project row's scope (no project → the default), empty groups skipped, held after active within a
# scope, and the [home] / [work] tag hidden in the list line only, since the sub-heading says it
W = T / "wstore"; (W / "a").mkdir(parents=True)
(W / "projects.json").write_text(json.dumps({"pages": {"projects/wk": {**page("Wk", "home-beta"), "org": "work"}, "projects/hm": page("Hm", "home-beta")}}))
def witem(i, subj, proj, ago, status="open", **md):
    (W / f"a/{i}.json").write_text(json.dumps({"id": str(i), "subject": subj, "description": "x", "status": status,
                                               "metadata": {"owner": B, **({"project": proj} if proj else {}), **md}, "updated": (qnow - ago).timestamp()}))
witem(101, "[home] box call 101", "ops/box", 1 * H_, needs="decision"); witem(21, "[work] wk call 21", "projects/wk", 2 * H_, needs="decision")
witem(103, "[home] note on [home] tags 103", "projects/hm", 3 * H_, needs="decision"); witem(104, "[home] loose call 104", "", 4 * H_, needs="decision")
witem(105, "[home] box work 105", "ops/box", 1 * H_); witem(106, "[home] box parked 106", "ops/box", 2 * H_, hold=True)
witem(107, "[work] wk parked 107", "projects/wk", 3 * H_, hold=True); witem(108, "[work] wk work 108", "projects/wk", 4 * H_); witem(109, "[work] wk work 109", "projects/wk", 5 * H_)
witem(110, "[work] wk done 110", "projects/wk", 6 * H_, status="completed"); witem(111, "[home] box done 111", "ops/box", 7 * H_, status="completed")
witem(112, "[home] box relay 112", "ops/box", 8 * H_, needs="external")
bw = ui_render.Board(str(W), now=qnow); wh = bw.html()
check("scope groups: the stored subject and board.md keep the tag (a leading tag is dropped from a home row's goal and from the item page's title)", bw.item("a21")["subject"] == "[work] wk call 21"
      and "<title>a21 · wk call 21</title>" in bw.item_html("a21") and '<span class="hgoal">wk call 21</span>' in wh and "[work] wk call 21</span>" not in wh
      and "[work] wk call 21" in bw.markdown() and "[home] box parked 106" in bw.markdown(), bw.markdown()[:600])
check("scope groups: the sub-heading is a small bold line with a rule under it", "h3.iscope{font-size:12px;font-weight:600;color:var(--fg);" in bw._css()
      and "border-bottom:1px solid var(--mut)" in bw._css()[bw._css().find("h3.iscope{"):])
check("scope groups: the group heading is the fold's summary with the section folds' marker",
      "details.fold>summary h3::before{content:'▸ ';color:var(--mut)}details.fold[open]>summary h3::before{content:'▾ '}" in bw._css()
      and "details.fold>summary::-webkit-details-marker{display:none}" in bw._css(), bw._css()[bw._css().find("details.fold>summary"):][:400])
_fj = ui_render._FOLD_JS
check("scope groups: on load a fold rendered open closes on a stored '0'; a closed one (a section) still opens only on '1'",
      "var v=get(d.getAttribute('data-fold'));if(d.open){if(v==='0')d.open=false}else if(v==='1')d.open=true" in _fj and "get(d.getAttribute('data-fold'))==='1')d.open=true" not in _fj, _fj)
check("scope groups: the in-place swap carries each fold's live state both ways (a closed group stays closed, an open one open)",
      "o.querySelectorAll('details.fold').forEach(function(d){f[d.getAttribute('data-fold')]=d.open})" in ui_render._LIVE_JS
      and "if(k in f)d.open=f[k]" in ui_render._LIVE_JS and "localStorage" not in ui_render._LIVE_JS[ui_render._LIVE_JS.find("function swap"):ui_render._LIVE_JS.find("function apply")]
      and "if(f[d.getAttribute('data-fold')])d.open=true" not in ui_render._LIVE_JS, ui_render._LIVE_JS[ui_render._LIVE_JS.find("function swap"):][:400])
check("scope groups: a hash to a line opens every fold around it; to a section, just the section",
      "if(el.matches&&el.matches('section')){var s=el.querySelector('details.fold');if(s&&!s.open)s.open=true}" in _fj
      and "else for(var d=el.closest&&el.closest('details.fold');d;d=d.parentElement&&d.parentElement.closest('details.fold'))if(!d.open)d.open=true;" in _fj, _fj)

# ---- 16. history from the store's git (one item, a few commits) and the anchors scoped to it
import subprocess
G = T / "gstore"; (G / "a").mkdir(parents=True); (G / "projects.json").write_text((T / "store/projects.json").read_text())
(G / "anchors.json").write_text(json.dumps({"projects/beta": [{"url": "https://x.slack.com/archives/C0000000007", "items": ["a70"], "added": 1, "by": "t"},
                                                             {"url": "https://x.slack.com/archives/C0000000006", "items": None, "added": 1, "by": "t"},
                                                             {"url": "https://mail.google.com/mail/u/0/#all/2222222222222222", "items": ["a71"], "added": 1, "by": "t"}]}))
git = lambda *a: subprocess.run(["git", "-C", str(G), "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], check=True, capture_output=True)
git("init", "-q")
ZONE_TZ = bd.now.tzinfo; at = lambda d, h, mi=0: (datetime.datetime(2026, 2, 18, h, mi, tzinfo=ZONE_TZ) + datetime.timedelta(days=d)).timestamp()
v = {"id": "70", "subject": "[home] history item", "description": "A thing with a past.", "status": "open", "metadata": {"owner": B, "project": "projects/beta", "needs": "decision", "due": "2026-02-27", "next": "decide"}, "updated": at(1, 9)}
def commit(msg, **chg):
    for k_, v_ in chg.items():
        if k_.startswith("m_"):
            if v_ is None: v["metadata"].pop(k_[2:], None)
            else: v["metadata"][k_[2:]] = v_
        else: v[k_] = v_
    (G / "a/70.json").write_text(json.dumps(v)); git("add", "-A"); git("commit", "-q", "-m", msg)
commit("created")
commit("relayed", m_needs="external", updated=at(1, 10))
commit("due moved", m_due="2026-03-02", updated=at(2, 11, 30))
commit("on hold", status="on_hold", m_wake="2026-03-02", updated=at(3, 8))                 # the retired status, as the store's git holds it
commit("migrated", status="open", m_hold=True, updated=at(3, 8))                         # the start-time migration: no clock change, no event
commit("wake cleared", m_wake=None, updated=at(3, 20))
commit("unheld", m_hold=None, m_wake=None, updated=at(4, 9, 15))
commit("done", status="completed", updated=at(4, 18, 5))
v["subject"] = "[home] history item, renamed"; v["updated"] = at(4, 18, 30); (G / "a/70.json").write_text(json.dumps(v))   # on disk, not committed yet
bgs = ui_render.Board(str(G), now=datetime.datetime(2026, 2, 23, 12, 0, tzinfo=ZONE_TZ))
evs, more = bgs.item_events(bgs.item("a70")); txt = [(bgs.when(ts), k_, re.sub(r"<[^>]+>", "", h_)) for ts, k_, h_ in evs]
check("history: every event, newest first, in the instance timezone, with the uncommitted write on top", txt == [
    ("Sun Feb 22nd 18:30", "edit", "subject edited (was “[home] history item”)"),
    ("Sun Feb 22nd 18:05", "completed", "completed"),
    ("Sun Feb 22nd 09:15", "unhold", "back from hold · Waiting"),
    ("Sat Feb 21st 20:00", "hold", "wake cleared"),
    ("Sat Feb 21st 08:00", "hold", "put on hold · wake Mon Mar 2nd"),
    ("Fri Feb 20th 11:30", "due", "due moved: Fri Feb 27th → Mon Mar 2nd"),
    ("Thu Feb 19th 10:00", "needs", "moved to Waiting"),
    ("Thu Feb 19th 09:00", "created", "created as “[home] history item” · Your move · mover the owner · created by home-beta")] and more == 0, txt)
gp = bgs.item_html("a70")
check("history: on the page, with the time and the event", '<h2>History <span class="count">8</span></h2></summary><ul class="hist"><li class="ev ev-edit"><div class="eh"><span class="t">Sun Feb 22nd 18:30</span></div>' in gp
      and '<li class="ev ev-completed"><div class="eh"><span class="t">Sun Feb 22nd 18:05</span></div><div class="w"><div class="eb">completed</div></div></li>' in gp, gp[gp.find("<h2>History"):][:600])
check("item page: a closed item says so, with no whose-move or due badge; its priority stays in the sidebar", '<div class="istat"><p class="istate"><span class="tag t-closed">Closed</span> · ' in gp
      and "Due " not in gp and "<dt>Whose move</dt>" not in gp and '<dt>Priority</dt><dd>P2</dd>' in _side(gp), _side(gp))
_an = _side(gp)[_side(gp).find("<dt>Anchors"):]
check("item page: only the anchors scoped to this item, in the sidebar", _an.startswith('<dt>Anchors <span class="count">1</span></dt><dd><ul class="alist">') and "C0000000007" in _an and "C0000000006" not in _an and "2222222222222222" not in _an, _an)
_bgp = bgs.routing_html("projects/beta")
check("completed group on the project page: the compact line form", '<li class="irow" id="task-a-70"><div class="ir-top"><span class="ir-title"><span class="tag t-closed">Closed</span> <a class="ir-link" href="/items/a70" target="_blank" rel="noopener"><span class="ir-id">a70</span>' in _bgp
      and re.search(r'<span class="tip ir-age" data-ts="\d+"', _bgp))
for n_ in range(60): commit(f"edit {n_}", m_next=f"step {n_}", updated=at(5, 0, n_ % 60))
evs, more = ui_render.Board(str(G), now=bgs.now).item_events(bgs.item("a70"))
check("history: capped at 50, the rest counted", len(evs) == 50 and more > 0 and "older events not shown" in ui_render.Board(str(G), now=bgs.now).item_html("a70"), (len(evs), more))
# the board item: when the decision leaves the needs, the options leave the page's Ask and stay in History, on that line
G2 = T / "gstore2"; (G2 / "a").mkdir(parents=True); (G2 / "projects.json").write_text((T / "store/projects.json").read_text())
git2 = lambda *a: subprocess.run(["git", "-C", str(G2), "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], check=True, capture_output=True)
git2("init", "-q")
dec72 = {"id": "72", "subject": "[home] a choice", "description": "Pick a vendor.", "status": "open", "updated": at(1, 9),
      "metadata": {"owner": B, "project": "projects/beta", "needs": ["decision"], "next": "decide", "ask": "Decide: which of the two vendors · Recommend: Vendor A · Stakes: a month · By: no date",
                   "options": [{"label": "Vendor A", "line": "Cheaper.", "recommended": True}, {"label": "Vendor B", "line": "Slower.", "recommended": False}]}}
(G2 / "a/72.json").write_text(json.dumps(dec72)); git2("add", "-A"); git2("commit", "-q", "-m", "created")
bo2 = ui_render.Board(str(G2), now=datetime.datetime(2026, 2, 23, 12, 0, tzinfo=ZONE_TZ)); ip2 = bo2.item_html("a72")
check("options history: while the decision is open the page draws them under the ask", '<b class="osub">Options</b><ol class="iopts">' in ip2, ip2[ip2.find('class="iask"'):][:400])
dec72["metadata"]["needs"] = []; dec72["metadata"]["next"] = "act on Vendor A"; dec72["updated"] = at(2, 10)
(G2 / "a/72.json").write_text(json.dumps(dec72)); git2("add", "-A"); git2("commit", "-q", "-m", "decided")
bo2 = ui_render.Board(str(G2), now=datetime.datetime(2026, 2, 23, 12, 0, tzinfo=ZONE_TZ)); ip2 = bo2.item_html("a72")
evs2 = [(k_, re.sub(r"<[^>]+>", "", h_)) for _, k_, h_ in bo2.item_events(bo2.item("a72"))[0]]
check("options history: decided, the page draws no open options", 'class="iopts"' not in ip2 and '<b class="osub">' not in ip2, ip2[ip2.find('class="iask"'):][:400])
check("options history: …and History keeps them on the line where the decision left", ("needs", "moved to On agent") in evs2 and ("needs", "the ask was: which of the two vendors") in evs2 and ("needs", "the options were:") in evs2 and ("needs", "Vendor A (recommended): Cheaper.") in evs2 and ("needs", "Vendor B: Slower.") in evs2, evs2)
check("ask: decided, the page draws no ask either (its History keeps the whole ask in a closed fold); the stored line stays", 'class="iask"' not in ip2 and "Recommend" not in re.sub(r"<details.*?</details>", "", ip2, flags=re.S) and dec72["metadata"]["ask"], ip2[ip2.find('class="istat"'):][:400])
check("ask: …nor board.md, nor a row of the home page", "which of the two vendors" not in bo2.markdown() and "which of the two vendors" not in bo2.html(), bo2.markdown()[:300])

# ---- 13. on hold (a property of an open item): status stays open, metadata.hold (+ an optional metadata.wake); at its wake the item
# returns to the lane its needs give it (the point of wake)
import io, contextlib
def refusal(fn):
    try: fn(); return ""
    except ToolError as e: return str(e)
rd = lambda g: json.loads((T / f"store/{g[0]}/{g[1:]}.json").read_text())
held_ = lambda g: rd(g)["status"] == "open" and hd_(rd(g)["metadata"]) is True
today = server._pages.zone_now().date(); D = lambda n: (today + datetime.timedelta(days=n)).isoformat()
NEW_FORM = "Refused: status must be open | completed; on hold is a property of an open item: hold=true (with an optional wake); clear_hold=true releases it"
HINT = "\nstill on hold: pass clear_hold=true to release it"
for i in (5, 6, 7, 8): item(i, "projects/beta", B)
server._WAKE_EVENT.clear(); e = refusal(lambda: server._update("a3", hold=True, sender="home-beta"))
check("hold: hold=true with no wake, after, anchor or recycle is refused, naming the four conditions",
      e.startswith("Refused: a hold names what it waits for; an unconditional or indefinite park is refused.") and all(x in e for x in ("wake=", "after=[\"board#N\"]", "anchors(project, add=[url], items=[\"a3\"])", "recycle=true"))
      and not held_("a3") and not server._WAKE_EVENT.is_set(), e)
check("minute loop: no next wake while nothing is on hold", server._next_wake() is None, server._next_wake())
# an item waiting on the owner is never held. The refusal
# names the after form; a hold whose next says it waits on him is noted, never refused (a wake on an item he has answered is fine)
check("hold (owner wait): the refusal names the after form for a hold that waits on the owner's decision",
      f"An item waiting on {server.OWNER} is never parked: needs=decision with its ask, or after=[<the item that carries the ask>]" in e, e)
NOTE_OWNER = f"this hold's next says it waits on {server.OWNER}: an item waiting on {server.OWNER} is never parked. Give it needs=decision with its ask, or after=[<the item that carries the ask>]"
for i in (74, 75, 76): item(i, "projects/beta", B)
res = server._update("a74", hold=True, wake=D(2), next=f"waiting on {server.OWNER}'s call on the pricing", sender="home-beta")
check("hold (owner wait): a hold whose next says it waits on the owner gets the note and still applies", NOTE_OWNER in res and held_("a74") and wk_(rd("a74")["metadata"]) == D(2), res)
res = server._update("a75", hold=True, wake=D(2), next=f"- deploy once the CI run is green\n- until {server.OWNER} decides, keep the old flag", sender="home-beta")
check("hold (owner wait): 'until <owner> decides' is noted too", NOTE_OWNER in res and held_("a75"), res)
res = server._update("a76", hold=True, wake=D(2), next=f"per {server.OWNER}'s call of Mon Mar 2nd, deploy after the CI run; tell {server.OWNER} when it is live", sender="home-beta")
check("hold (owner wait): a hold that mentions the owner only in passing gets no note", "waits on " + server.OWNER not in res and held_("a76"), res)
check("hold (owner wait): the matcher stays narrow", [server._waits_on_owner(t) for t in (f"blocked on {server.OWNER}", f"pending his answer", f"needs {server.OWNER}'s go-ahead",
      f"for {server.OWNER} to pick A or B", f"held until {server.OWNER}'s trip ends, then ship", f"{server.OWNER}'s decision of Mon: ship it", f"ask {server.OWNER} about the logo on Thu",
      f"waiting on the CI run {server.OWNER} asked for")] == [True, True, True, True, False, False, False, False])
for i in (74, 75, 76): (T / f"store/a/{i}.json").unlink()   # out of the fixture again: the sections below count the held items
server._WAKE_EVENT.clear()
res = server._update("a3", hold=True, wake=D(2), sender="home-beta")
check("hold: hold=true with a wake parks an open item; status stays open", held_("a3") and wk_(rd("a3")["metadata"]) == D(2) and res.startswith("updated a3.\na3 [open · on hold] "), res)
check("hold: hold=true wakes the minute loop", server._WAKE_EVENT.is_set())
check("hold: the hold is a state change (the writer owes the page)", "a3" in json.dumps(server._owed_load().get("projects/beta", {})), server._owed_load())
res = server._update("a3", wake=D(3), sender="home-beta")
check("hold: a wake set on an item already waiting on a date, shown as the until", wk_(rd("a3")["metadata"]) == D(3) and f"until: {D(3)}" in res and held_("a3"), res)
res = server._update("a5", hold=True, wake=D(2), due=D(9), needs="external", sender="home-beta"); m5 = rd("a5")["metadata"]
check("hold: hold=true with a wake parks; needs and due stay", held_("a5") and wk_(m5) == D(2) and m5.get("due") == D(9) and m5.get("needs") == ["external"], rd("a5"))
b5 = ui_render.Board(str(T / "store"))
check("hold: a held item with needs external is drawn held, counted on agent, never on others",
      "a5" in [r["gid"] for r in b5.held] and "a5" not in [r["gid"] for r in b5.n_call + b5.n_relay + b5.agent] and "a5" in {r["gid"] for rs in b5.by_proj.values() for r in rs}, [r["gid"] for r in b5.n_relay])
e = refusal(lambda: server._update("a2", hold=True, sender="home-beta"))
check("hold: hold=true on a completed item refused", e == "Refused: a completed item does not go on hold; set it open first" and rd("a2")["status"] == "completed" and "hold" not in rd("a2")["metadata"], e)
e = refusal(lambda: server._update("a2", wake=D(3), sender="home-beta"))
check("hold: a wake on a completed item refused (a reminder on a closed item is nothing to check)", e == "Refused: a completed item takes no wake; set it open first" and "wake" not in rd("a2")["metadata"], e)
e = refusal(lambda: server._update("a6", status="on_hold", sender="home-beta"))
check("hold: status=on_hold refused, naming the property form", e == NEW_FORM and rd("a6")["status"] == "open" and "hold" not in rd("a6")["metadata"], e)
e = refusal(lambda: server._update("a6", status="on_hold", wake=D(3), sender="home-beta"))
check("hold: status=on_hold with a wake refused the same, nothing saved", e == NEW_FORM and "wake" not in rd("a6")["metadata"] and "hold" not in rd("a6")["metadata"], e)
e0 = refusal(lambda: server._update("a6", wake=D(0), sender="home-beta")); e1 = refusal(lambda: server._update("a6", wake=D(-1), sender="home-beta"))
check("hold: a wake today or in the past refused, nothing saved", e0 == e1 == "Refused: wake must be in the future (+04)" and not held_("a6") and "wake" not in rd("a6")["metadata"], (e0, e1))
e = refusal(lambda: server._update("a6", wake="2026/12/01", sender="home-beta"))
check("hold: a wake in another format refused", e.startswith("Refused: metadata.wake must be YYYY-MM-DD or YYYY-MM-DDTHH:MM (+04) — got ") and not held_("a6"), e)
check("hold: an unknown status still refused", refusal(lambda: server._update("a6", status="parked", sender="home-beta")) == "Refused: status must be open | completed")
_was6 = rd("a6")["status"]; e_old = [refusal(lambda v=v: server._update("a6", status=v, sender="home-beta")) for v in ("pending", "in_progress")]
check("status: the retired older values (pending, in_progress) are refused like any unknown status", e_old == ["Refused: status must be open | completed"] * 2 and rd("a6")["status"] == _was6, e_old)
e = refusal(lambda: server._update("a5", clear_hold=True, wake=D(3), sender="home-beta"))
check("hold: clear_hold with a wake refused, nothing saved", e == "Refused: clear_hold releases the item and drops its wake; it does not go with hold or wake" and held_("a5") and wk_(rd("a5")["metadata"]) == D(2), e)
res = server._update("a5", status="open", sender="home-beta")
check("hold: status=open on a held item keeps the hold and the wake, and the reply says how to release it",
      held_("a5") and wk_(rd("a5")["metadata"]) == D(2) and res.startswith("updated a5.\na5 [open · on hold] "), res)
res = server._update("a5", next="ask Kim for A or B", sender="home-beta")
check("hold: other edits on a waiting item carry no hint", HINT not in res and held_("a5"), res)
res = server._update("a5", clear_hold=True, sender="home-beta"); m5 = rd("a5")["metadata"]
check("hold: clear_hold=true releases now: the date goes, needs, due and next stay", rd("a5")["status"] == "open" and "hold" not in m5 and "wake" not in m5 and "until" not in m5
      and m5.get("due") == D(9) and m5.get("needs") == ["external"] and m5.get("next") == "ask Kim for A or B" and res.startswith("updated a5.\na5 [open] ") and HINT not in res, res)
check("hold: released with needs external → back on others at once", "a5" in [r["gid"] for r in ui_render.Board(str(T / "store")).n_relay])
server._update("a6", hold=True, wake=D(4), sender="home-beta"); res = server.stackshot_complete("a6", sender="home-beta", outcome="done", reason="the work landed", description="- Goal: The test item's work is in place")
check("hold: complete (the complete tool) drops the hold and the wake", rd("a6")["status"] == "completed" and "wake" not in rd("a6")["metadata"] and "hold" not in rd("a6")["metadata"], rd("a6"))
res = server._update("a3", wake="none", sender="home-beta")
check("hold: wake=\"none\" on a wait on a date alone ends the wait (the date was all it waited on; nothing is left parked)", not held_("a3") and not _WT.stored_until(rd("a3")["metadata"]), (res, rd("a3")["metadata"]))
server._update("a3", wake=D(3), sender="home-beta"); res = server._update("a3", clear_wake=True, sender="home-beta")
check("hold: clear_wake=true the same", not held_("a3") and not _WT.stored_until(rd("a3")["metadata"]), (res, rd("a3")["metadata"]))
server._update("a3", hold=True, recycle=True, sender="home-beta"); res = server._update("a3", wake=D(3), sender="home-beta"); res = server._update("a3", wake="none", sender="home-beta")
check("hold: with a recycle to wait for, wake=\"none\" drops the date and the hold stays", rd("a3")["metadata"].get("hold") is True and not _WT.stored_until(rd("a3")["metadata"]) and rd("a3")["metadata"].get("recycle") is True, rd("a3"))
e = refusal(lambda: server._update("a3", clear_recycle=True, sender="home-beta"))
check("hold: clear_recycle=true that would leave the hold waiting on nothing is refused", e.startswith("Refused: a hold names what it waits for") and rd("a3")["metadata"].get("recycle") is True, e)
server._update("a3", wake=D(1), sender="home-beta"); server._update("a3", clear_recycle=True, sender="home-beta")   # a wake on an item already on hold is that hold's
check("hold: …and passes once a wake holds it", held_("a3") and wk_(rd("a3")["metadata"]) == D(1) and "recycle" not in rd("a3")["metadata"], rd("a3"))
# the wake pass: items due (wakes in the past, written into the store files past the gate), one due today, one not yet.
# item 5 has needs external and comes back on others; item 3 and item 8 have none and come back on agent (the point of wake)
server._update("a5", hold=True, wake=D(5), sender="home-beta")
server._update("a7", hold=True, wake=D(5), sender="home-beta"); server._update("a8", hold=True, wake=D(5), sender="home-beta")
for g, w in (("a3", D(-2)), ("a5", D(-1)), ("a8", D(0))):
    it = rd(g); setwk_(it["metadata"], w); it["updated"] = it["state_updated"] = 1000.0
    (T / f"store/{g[0]}/{g[1:]}.json").write_text(json.dumps(it))
led0 = json.dumps(server._owed_load(), sort_keys=True); n0 = len(wait_push(0)); t0 = time.time()
woke = server._wake_pass()
a3, a5, a7, a8 = rd("a3"), rd("a5"), rd("a7"), rd("a8")
check("wake pass: the items due (yesterday's and today's wake) are released, the one not due stays on hold", sorted(woke) == ["a3", "a5", "a8"]
      and all(x["status"] == "open" and "hold" not in x["metadata"] for x in (a3, a5, a8)) and held_("a7") and wk_(a7["metadata"]) == D(5), (woke, a3, a7, a8))
check("wake pass: the wake goes and both clocks move to now, together", all("wake" not in x["metadata"] and x["updated"] == x["state_updated"] and t0 - 1 <= x["updated"] <= time.time() + 1 for x in (a3, a5, a8)), (a3, a8))
check("wake pass: needs, due and next untouched", a5["metadata"].get("needs") == ["external"] and a5["metadata"].get("due") == D(9) and a5["metadata"].get("next") == "ask Kim for A or B", a5)
bw = ui_render.Board(str(T / "store"))
check("wake pass: back in its lane: needs external → on others, no needs → on agent; none still held", "a5" in [r["gid"] for r in bw.n_relay]
      and {"a3", "a8"} <= {r["gid"] for r in bw.agent} and not {"a3", "a5", "a8"} & {r["gid"] for r in bw.held}, ([r["gid"] for r in bw.n_call], [r["gid"] for r in bw.held]))
p = wait_push(n0 + 1)
_w3 = sorted(p[n0][1].splitlines()[1:]) if len(p) == n0 + 1 else []
check("wake pass (the turn rule's fourth build): the owner is told once for the three, one line each, naming the wake as stored and the lane",
      len(p) == n0 + 1 and p[n0][0] == B and p[n0][1].startswith("[stackshot] 3 items are yours now, their waits ended:\n")
      and [x.split(" [home]")[0] for x in _w3 if x.startswith("- a")] == [f"- a3: its until {D(-2)} came.", f"- a5: its until {D(-1)} came.", f"- a8: its until {D(0)} came."], p[n0:])
check("wake pass: it owes no page", json.dumps(server._owed_load(), sort_keys=True) == led0)
check("wake pass: a second run finds nothing and tells nobody", server._wake_pass() == [] and len(wait_push(0)) == n0 + 1)
# the item (the item before it): an item whose needs names no session wakes the keeper of its page, whatever its needs (an agent prepares the ask):
# its keeper; on a sub-page that names an agent, that agent. The keeper's own item: the owner's line
for i, proj, owner, needs in ((41, "projects/alpha", A, ""), (42, "projects/alpha/sub", A, ""), (43, "projects/alpha", A, "external"),
                              (44, "projects/alpha/kept", A, ""), (45, "projects/alpha", S, ""), (46, "projects/alpha", A, "decision")):
    item(i, proj, owner); it = rd(f"a{i}"); it["metadata"].update(hold=True, wake=D(-1), **({"needs": needs} if needs else {})); (T / f"store/a/{i}.json").write_text(json.dumps(it))
n0 = len(wait_push(0))
woke = server._wake_pass(); p = wait_push(n0 + 2); new = p[n0:]
to = {ln.split()[1]: m[0] for m in new for ln in m[1].splitlines() if re.match(r"(\[stackshot\]|-) a4\d ", ln)}
check("wake to agent: every item woke; one message per session (the turn rule's fourth build): the -main agent that moves five of them gets one message, the keeper that moves a45 another (each item goes to its mover alone)",
      sorted(woke) == [f"a{i}" for i in range(41, 47)] and len(new) == 2 and sorted(m[0] for m in new) == sorted([A, S]), (woke, new))
check("wake to agent: each item goes to the session that moves it: a41-a44 and a46 to their mover, a45 to its own, whatever the page or the needs",
      to.get("a41") == A and to.get("a42") == A and to.get("a43") == A and to.get("a46") == A and to.get("a44") == A and to.get("a45") == S, to)
mS = next((m[1] for m in new if m[0] == A), ""); mX = next((m[1] for m in new if m[0] == S), "")
check("wake to agent: the mover's own items are the short lines, no owner named, none of the old 'keeper of record' words",
      mS.startswith("[stackshot] 5 items woke for you:\n") and f"- a41 woke (wake {D(-1)}): back in its lane (on agent, by its needs)" in mS.splitlines()
      and "keeper of record" not in mS and "keeper of record" not in mX, mS)
check("wake to agent: one item alone keeps its short line, with what to do",
      re.match(rf"\[stackshot\] a45 woke \(wake {D(-1)}\): back in its lane \(on agent, by its needs\); refresh its ask if things moved\.$", mX) is not None, mX)
check("wake to agent: the batch counts them, one line each, then what to do",
      "(your call, by its needs)" in next(ln for ln in mS.splitlines() if ln.startswith("- a46 ")) and mS.endswith("Refresh each one's ask if things moved."), mS)
rl = [n for k in ("projects/alpha", "projects/alpha/sub", "projects/alpha/kept") for n in routing.read(k) if str(n.get("label")).startswith("wake ")]
check("wake to agent: no pilot notice is recorded for the router to rule on: nothing is told to a keeper in the mover's place", rl == [], rl)
def _turns(ns):     # the turn audit's count: one turn per message, a batch counted once, a log-only line none
    return len({n.get("batch") or n["id"] for n in ns if n.get("to") and not n.get("log_only")})
check("wake to agent: the audit counts nothing for the pass, which logged no notice", _turns(rl) == 0, rl)
for i in range(41, 47): (T / f"store/a/{i}.json").unlink()      # out of the fixture again: later checks count the open items

# a delivery that fails is a stderr line, never an exception: the item is released all the same
(T / "failpush.py").write_text("import sys\nprint('boom', file=sys.stderr); sys.exit(4)\n")
_push = server._PUSH; server._PUSH = [sys.executable, str(T / "failpush.py")]
it = rd("a7"); setwk_(it["metadata"], D(-1)); (T / "store/a/7.json").write_text(json.dumps(it))
_err = io.StringIO()
with contextlib.redirect_stderr(_err):
    woke = server._wake_pass()
    for _ in range(300):    # a failed push is told on stderr first and recorded on the item after, and the hand-off's one resend is a second thread
                            # that records its own failure: wait for both records, or one lands after the hold update below (which drops them) and stays
        if "notice to" in _err.getvalue() and {x.get("tag") for x in rd("a7")["metadata"].get("undelivered") or []} >= {"watch", "handoff"}: break
        time.sleep(0.1)
server._PUSH = _push
check("wake pass: a failed owner notice is logged to stderr, the item released all the same", woke == ["a7"] and not held_("a7")
      and f"watch: a7 notice to {B} not delivered: no result — boom" in _err.getvalue(), _err.getvalue())
server._update("a7", hold=True, wake=D(5), sender="home-beta")
# a time of day (2099-01-09, "hold until noon"): stored with a T, due at that minute, fired by the minute loop
item(9, "projects/beta", B); now_ = server._pages.zone_now(); d2 = D(2); tz_ = now_.tzinfo; n9 = len(wait_push(0))
server._WAKE_EVENT.clear(); res = server._update("a9", hold=True, wake=f"{d2} 12:00", sender="home-beta")
check("timed wake: a time of day in the future is accepted (a space for the T) and stored with a T", held_("a9") and wk_(rd("a9")["metadata"]) == f"{d2}T12:00" and f"until: {d2}T12:00" in res, res)
check("timed wake: the update that set it wakes the minute loop", server._WAKE_EVENT.is_set())
server._WAKE_EVENT.clear(); server._update("a9", priority="p2", sender="home-beta")
check("timed wake: a filing edit does not wake the minute loop", not server._WAKE_EVENT.is_set())
res = server._update("a9", wake=f"{d2}T13:30", sender="home-beta")
check("timed wake: the T form is accepted as given", wk_(rd("a9")["metadata"]) == f"{d2}T13:30", res)
e0 = refusal(lambda: server._update("a9", wake=(now_ - datetime.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"), sender="home-beta"))
e1 = refusal(lambda: server._update("a9", wake=now_.strftime("%Y-%m-%d %H:%M"), sender="home-beta"))
check("timed wake: an hour ago and this minute refused, nothing saved", e0 == e1 == "Refused: wake must be in the future (+04)" and wk_(rd("a9")["metadata"]) == f"{d2}T13:30", (e0, e1))
bad = [refusal(lambda w=w: server._update("a9", wake=w, sender="home-beta")) for w in (f"{d2}T24:00", f"{d2}T12", f"{d2}T12:00+25:00", "2026/12/01")]
check("timed wake: 24:00, a bare hour, an impossible offset and a slashed date refused with the two forms named", all(x.startswith("Refused: metadata.wake must be YYYY-MM-DD or YYYY-MM-DDTHH:MM (+04) — got ") for x in bad)
      and f"'{d2}T24:00'" in bad[0] and wk_(rd("a9")["metadata"]) == f"{d2}T13:30", bad)
old_past = refusal(lambda: server._update("a9", wake="2026-02-24T12:00:30", sender="home-beta"))
check("timed wake: seconds are read as the minute they fall in, then the wake is judged as any other (a past one is refused as past)", old_past == "Refused: wake must be in the future (+04)" and wk_(rd("a9")["metadata"]) == f"{d2}T13:30", old_past)
for w_, want_ in ((f"{d2}T12:00:30", f"{d2}T12:00"), (f"{d2}T12:00+04:00", f"{d2}T12:00"), (f"{d2}T08:00:59Z", f"{d2}T12:00")):
    res = server._update("a9", wake=w_, sender="home-beta")
    check(f"timed wake: {w_} is stored as {want_} (the instance time) and the update says it", wk_(rd("a9")["metadata"]) == want_, (wk_(rd("a9")["metadata"]), res))
server._update("a9", wake=f"{d2}T13:30", sender="home-beta")
at9 = server._wake_at(f"{d2}T13:30")
check("timed wake: _wake_at reads both forms in the instance zone", at9 == datetime.datetime.fromisoformat(f"{d2}T13:30").replace(tzinfo=tz_)
      and server._wake_at(d2) == datetime.datetime.fromisoformat(f"{d2}T00:00").replace(tzinfo=tz_) and at9.utcoffset() == datetime.timedelta(hours=4), at9)
check("minute loop: the next wake is the timed item's minute, ahead of a date-only wake later", server._next_wake() == at9, (server._next_wake(), at9))
check("timed wake: a pass a minute before the instant leaves it on hold", server._wake_pass(now=at9 - datetime.timedelta(minutes=1)) == [] and held_("a9"))
woke = server._wake_pass(now=at9)
check("timed wake: a pass at the instant releases it and drops the wake; the date-only hold stays", woke == ["a9"] and rd("a9")["status"] == "open" and not held_("a9")
      and "wake" not in rd("a9")["metadata"] and held_("a7"), (woke, rd("a9"), rd("a7")))
res = server._update("a9", hold=True, wake=D(1), sender="home-beta")
check("date-only wake: still stored as YYYY-MM-DD", wk_(rd("a9")["metadata"]) == D(1), res)
check("date-only wake: a pass given a date takes the whole day, as before (not due today, due on its day)",
      server._wake_pass(now=today) == [] and server._wake_pass(now=today + datetime.timedelta(days=1)) == ["a9"] and not held_("a9"))
p = wait_push(n9 + 2)
check("timed and date-only wakes: the owner is told each time, the date as stored", sorted(x[1].split(" [home]")[0] for x in p[n9:]) == sorted([   # pushed from threads: either order
      f"[stackshot] a9 is yours now: its until {d2}T13:30 came.",
      f"[stackshot] a9 is yours now: its until {D(1)} came."]), p[n9:])
# brief: the held item has its own block, after the open ones and not among them
(T / "board.md").write_text(ui_render.Board(f"{tmp}/store").markdown(), encoding="utf-8")   # what the publish writes; the brief reads its head
b = server.stackshot_brief(); op, _, hd = b.partition("\n\nOn hold (")
check("brief: an item waiting on a date is listed (with its date) and no longer in an On hold block", "a7 [open" in b and f"until: {D(5)}" in b and "a3 [open]" in b, b[-1500:])
check("brief: the board's index links each item's page, never its card anchor #task-<letter>-<n>",
      "#task-" not in b and "](https://stackshot.example.com/items/a3)" in b and "#task-" in (T / "board.md").read_text(), b[:1500])
# the pilot relay names the hold
n0 = len(wait_push(0)); server._update("a1", hold=True, wake=D(2), sender="work-osprey-main"); p = wait_push(n0 + 1)
check("pilot relay: an agent putting an item on hold → the keeper is told 'put on hold'", len(p) == n0 + 1 and p[-1][0] == S and "a1 put on hold by work-osprey-main" in p[-1][1], p[-1:])
server._update("a1", wake=D(3), sender="work-osprey-main"); p = wait_push(n0 + 2)
check("pilot relay: a wake on an item already held is named among the changed fields", len(p) == n0 + 2 and "a1 changed (wake) by work-osprey-main" in p[-1][1], p[-1:])
server._update("a1", clear_hold=True, sender="work-osprey-main"); p = wait_push(n0 + 3)
check("pilot relay: …and 'released from hold' on clear_hold", len(p) == n0 + 3 and "a1 released from hold by work-osprey-main" in p[-1][1] and not held_("a1"), p[-1:])

# the session-start line (ui_render.Board.brief): held items are open and on agent, named inside on agent
bl = ui_render.Board(str(T / "store")).brief().splitlines()[0]
mb = re.fullmatch(r"Board: (\d+) open \((\d+) your move, (\d+) on agents, (\d+) waiting\), (\d+) completed in 14d\.", bl)
check("session-start line: held counted in open and in the list the model puts them in, and the line names no hold total", bool(mb) and int(mb[1]) == int(mb[2]) + int(mb[3]) + int(mb[4]) and "on hold" not in bl, bl)
check("session-start line: the same words when none is on hold, and nothing about holds", re.fullmatch(r"Board: \d+ open \(\d+ your move, \d+ on agents, \d+ waiting\), \d+ completed in 14d(?: · \d+ stale)?\.", bq.brief().splitlines()[0])
      and "on hold" not in bq.brief(), bq.brief())

# the start-time migration: legacy status on_hold files are read as held before it and rewritten as open + hold by it, clocks untouched
for i_, w_ in ((91, D(3)), (92, "")):
    d_ = {"id": str(i_), "subject": f"[home] legacy {i_}", "description": "Held the old way.", "status": "on_hold",
          "metadata": {"owner": B, "project": "projects/beta", "needs": "external", **({"wake": w_} if w_ else {})}, "updated": 1234.0, "state_updated": 1200.0}
    (T / f"store/a/{i_}.json").write_text(json.dumps(d_))
check("legacy: before the migration, _load reads it as open + hold", server._load("a91")["status"] == "open" and server._load("a91")["metadata"].get("hold") is True
      and json.loads((T / "store/a/91.json").read_text())["status"] == "on_hold")
check("legacy: before the migration, its wake is on the minute loop's list", "a91" in [g for g, *_ in server._wakes()])
bl_ = ui_render.Board(str(T / "store"))
check("legacy: before the migration, the board draws it held, never on others", {"a91", "a92"} <= {r["gid"] for r in bl_.held} and not {"a91", "a92"} & {r["gid"] for r in bl_.n_relay})
check("legacy: before the migration, the brief tool lists it on hold", "a91 [open · on hold]" in server.stackshot_brief().partition("\n\nOn hold (")[2])
_err = io.StringIO()
with contextlib.redirect_stderr(_err):
    mig = server._migrate_holds()
l91, l92 = rd("a91"), rd("a92")
check("migration: every legacy item rewritten as open + hold, its wake kept, its other fields as they were", mig == ["a91", "a92"]
      and l91["status"] == l92["status"] == "open" and hd_(l91["metadata"]) is True and hd_(l92["metadata"]) is True
      and wk_(l91["metadata"]) == D(3) and "wake" not in l92["metadata"] and l91["metadata"].get("needs") == "external", (mig, l91, l92))
check("migration: neither clock moves", (l91["updated"], l91["state_updated"], l92["updated"], l92["state_updated"]) == (1234.0, 1200.0, 1234.0, 1200.0), (l91, l92))
check("migration: one stderr line per item", _err.getvalue().count("migrate: ") == 2
      and f"migrate: a91 status on_hold → open + metadata.hold (wake {D(3)}), clocks unchanged — [home] legacy 91" in _err.getvalue()
      and "migrate: a92 status on_hold → open + metadata.hold (wake none), clocks unchanged" in _err.getvalue(), _err.getvalue())
check("migration: a second run finds nothing", server._migrate_holds() == [])

# ---- 16b. a wake alone is a reminder, never a hold (items kept showing while their work was live). hold=true parks, as before; a wake without it leaves the item in its lane,
# and at its moment the owner and the sessions in its needs are told once and the wake goes. An item that needs decision is never on hold.
for i in (30, 25, 34, 31, 35, 36, 37): item(i, "projects/beta", B)
server._WAKE_EVENT.clear()
res = server._update("a30", wake=D(2), next="home-beta: review the draft", sender="home-beta"); m_ = rd("a30")["metadata"]
check("reminder: a wake alone is stored as the wait on that date and is no hold; its own step passes; the reply shows the item waiting",
      wk_(m_) == D(2) and "hold" not in m_ and m_.get("next") == "home-beta: review the draft" and res.startswith("updated a30.\na30 [open · on hold] ") and f"until: {D(2)}" in res, res)
check("reminder: it wakes the minute loop and is on its list", server._WAKE_EVENT.is_set() and "a30" in [g for g, *_ in server._wakes()])
b_ = ui_render.Board(str(T / "store")); ip_ = b_.item_html("a30")
check("reminder: a wake alone is a wait on that date: parked out of the active lane", "a30" in [r["gid"] for r in b_.held] and "a30" not in [r["gid"] for r in b_.agent + b_.n_call + b_.n_relay], ([r["gid"] for r in b_.held], [r["gid"] for r in b_.agent]))
_wk30 = re.search(r"<dt>Wake</dt><dd>([^<]*)</dd>", ip_)
check("reminder: the item page shows the date in the sidebar's Wake row, and says waiting", bool(_wk30) and _wk30.group(1) == b_.when(render.wake_of(rd("a30"))) and "tag t-wait" in ip_, (_wk30.group(1) if _wk30 else None, ip_[ip_.find("istat"):][:300]))
_b30 = server.stackshot_brief().partition("\n\nOn hold (")
check("reminder: the brief lists it among the parked, not the active items", "a30 [open" in _b30[2] and "a30 [open" not in _b30[0], _b30[0][-300:])
check("reminder: the update description says a wake alone is a wait until that date, never that it implies a hold",
      "alone is a wait: the item waits until that date" in server._UPDATE_DESC and "a wake implies" not in server._UPDATE_DESC and "implies hold" not in server._UPDATE_DESC)
pj = json.load(open(T / "store/projects.json")); pj["pages"]["projects/zz"] = {**page("Zz", "work-zz"), "agents": {"work-zz-bg": "builds"}, "back_agents": {"work-zz-bg": "builds"}}; (T / "store/projects.json").write_text(json.dumps(pj))
# a session in needs: a background agent (a page's keeper is retired and refused); it has a pane in the heartbeat, or the hand-off's send-time guard (handoff suite) refuses it
ZZB = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
_sjz = json.loads((T / "fleet/a/sessions.json").read_text()); _sjz[ZZB] = {"name": "work-zz-bg", "machine": "a", "url": "", "seen": "x"}
(T / "fleet/a/sessions.json").write_text(json.dumps(_sjz))
server._update("a25", needs=["work-zz-bg"], next="build it", sender="home-beta"); server._update("a25", wake=D(3), sender="home-beta")
check("reminder: a wake on an item with a session in needs is no hold either", "hold" not in rd("a25")["metadata"] and wk_(rd("a25")["metadata"]) == D(3), rd("a25"))
for g in ("a30", "a25"):
    it = rd(g); setwk_(it["metadata"], D(-1)); (T / f"store/{g[0]}/{g[1:]}.json").write_text(json.dumps(it))
clk = {g: (rd(g)["state_updated"], rd(g).get("confirmed")) for g in ("a30", "a25")}; nd_b = rd("a25")["metadata"].get("needs")
led0 = json.dumps(server._owed_load(), sort_keys=True); n0 = len(wait_push(0))
woke = server._wake_pass(); r_wk1, r_wk2 = rd("a30"), rd("a25"); p = wait_push(n0 + 2)
check("reminder pass: both items are told their date came; the date and kind are gone, next and status as they were",
      sorted(woke) == ["a25", "a30"] and all(x["status"] == "open" and "until" not in x["metadata"] and "wait_kind" not in x["metadata"] and "hold" not in x["metadata"] for x in (r_wk1, r_wk2))
      and r_wk1["metadata"].get("next") == "home-beta: review the draft", (woke, r_wk1, r_wk2))
_rem_b = next((m for m in p[n0:] if m[0] == B), ["", ""]); _rem_s = [m for m in p[n0:] if m[0] == ZZB]
check("reminder pass: the mover of a30 is told its one line, and a25's mover (the session its needs name) its own once, nobody else",
      len(p) == n0 + 2 and _rem_b[1].startswith(f"[stackshot] a30 is yours now: its until {D(-1)} came.")
      and [m[1].split(" [home]")[0] for m in _rem_s] == [f"[stackshot] a25 is yours now: its until {D(-1)} came."], p[n0:])
pj = json.load(open(T / "store/projects.json")); pj["pages"].pop("projects/zz"); (T / "store/projects.json").write_text(json.dumps(pj))
check("reminder pass: it owes no page, and a second pass finds nothing and tells nobody",
      json.dumps(server._owed_load(), sort_keys=True) == led0 and server._wake_pass() == [] and len(wait_push(0)) == n0 + 2)
b_ = ui_render.Board(str(T / "store"))
check("reminder pass: the items stay in their lane, still active", {"a30", "a25"} <= {r["gid"] for r in b_.agent} and not {"a30", "a25"} & {r["gid"] for r in b_.held})
# hold=true with a wake parks and releases as before; an item stored held with a wake before the change still releases at its wake
server._update("a34", hold=True, wake=D(2), sender="home-beta")
_b34 = ui_render.Board(str(T / "store"))
check("park: hold=true with a wake is waiting on its date, parked out of the active lane", held_("a34") and "hold" not in rd("a34")["metadata"]
      and "a34" in [r["gid"] for r in _b34.held] and "a34" not in [r["gid"] for r in _b34.agent + _b34.n_call + _b34.n_relay], ([r["gid"] for r in _b34.held], [r["gid"] for r in _b34.agent]))
it = rd("a34"); setwk_(it["metadata"], D(-1)); (T / "store/a/34.json").write_text(json.dumps(it))
it = rd("a31"); it["metadata"].update(hold=True, wake=D(-1)); (T / "store/a/31.json").write_text(json.dumps(it))   # as a file written before the change holds it
n0 = len(wait_push(0)); woke = server._wake_pass(); p = wait_push(n0 + 1)
check("park: at the wake both are released, the date gone, both clocks moved, and the owner told for each (one message)",
      sorted(woke) == sorted(["a34", "a31"]) and not held_("a34") and not held_("a31") and all("wake" not in rd(g)["metadata"] and "until" not in rd(g)["metadata"] and rd(g)["updated"] == rd(g)["state_updated"] for g in ("a34", "a31"))
      and len(p) == n0 + 1 and p[n0][1].count("a31 woke (wake") == 1 and f"a34 is yours now: its until {D(-1)} came." in p[n0][1], (woke, p[n0:]))
# one pass with a parked item released and a reminder due, both for the same owner: still one message for the session, naming both
it = rd("a36"); it["metadata"].update(hold=True, wake=D(-1)); (T / "store/a/36.json").write_text(json.dumps(it))
it = rd("a37"); setwk_(it["metadata"], D(-1)); (T / "store/a/37.json").write_text(json.dumps(it))
n0 = len(wait_push(0)); woke = server._wake_pass(); p = wait_push(n0 + 1)
check("mixed pass: a released hold and a reminder for one owner come in one message, each line saying what it is",
      sorted(woke) == ["a36", "a37"] and len(p) == n0 + 1 and p[n0][0] == B and p[n0][1].splitlines()[0] == "[stackshot] 2 items came due for you (woken or reminded):"
      and sorted(p[n0][1].splitlines()[1:3]) == sorted([f"- a36 woke (wake {D(-1)}): back in its lane (on agent, by its needs)",
                                                        f"- a37 reminder (wake {D(-1)}): still active (on agent), check where it stands"])
      and not held_("a36") and "wake" not in rd("a36")["metadata"] and "wake" not in rd("a37")["metadata"], (woke, p[n0:]))
# an item that needs decision is never on hold: a stored flag is ignored by every view, and the next write drops it
ASK_D = "Decide: ship A or B · Recommend: A · Stakes: a week either way · By: no date"
it = rd("a35"); it["metadata"].update(needs=["decision"], ask=ASK_D, hold=True, wake=D(4)); (T / "store/a/35.json").write_text(json.dumps(it))
b_ = ui_render.Board(str(T / "store")); ip_ = b_.item_html("a35")
check("decision + hold flag: the board shows it in your call, never parked; the item page says open, not on hold",
      "a35" in [r["gid"] for r in b_.n_call] and "a35" not in [r["gid"] for r in b_.held]
      and '<span class="badge hold">on hold</span>' not in ip_ and "(on hold" not in b_.markdown().split("a35 · ")[1][:200] if "a35 · " in b_.markdown() else False,
      [r["gid"] for r in b_.held])
check("decision + hold flag: the server's views agree (get, the brief's lanes)", not server._is_held(rd("a35")) and "a35 [open]" in server.stackshot_brief().partition("\n\nOn hold (")[0]
      and "on hold" not in server._fmt({**rd("a35"), "gid": "a35"}).splitlines()[0])
res = server._update("a35", next="prepping the options", sender="home-beta"); m_ = rd("a35")["metadata"]
check("decision + hold flag: any write drops the hold, keeps its date, and says so",
      "hold" not in m_ and wk_(m_) == D(4) and m_.get("needs") == ["decision"] and "is never on hold: the hold is dropped; its date " + D(4) + " stays, and no date parks an item on his call" in res, res)
res = server._update("a35", hold=True, wake=D(5), sender="home-beta"); m_ = rd("a35")["metadata"]
check("decision: hold=true on it parks nothing (the hold is dropped, the wake a reminder), never refused", "hold" not in m_ and wk_(m_) == D(5) and "the hold is dropped" in res, res)
for i in (30, 25, 34, 31, 35, 36, 37): (T / f"store/a/{i}.json").unlink()   # out of the fixture again: later checks count the open items
wait_push(0)

# ---- 17. the ask line, last confirmed and staleness
CF = server._cfg.CFG; CF.setdefault("ask", {})["refuse_after"] = ""
ASK = "Decide: whether to take vendor A · Recommend: yes, it is cheaper · Stakes: B costs a month either way · By: Mon Mar 2nd"
SHAPE = 'Refused: ask must read "Decide: … · Recommend: … · Stakes: … · By: …" in one line of at most 240 characters'
NEED = 'Refused: a needs=decision item needs an ask line: ask="Decide: … · Recommend: … · Stakes: … · By: …" (≤ 240 chars). A client whose tool has no ask parameter writes the line as the first line of next instead.'
NAG = '[ask] a needs=decision item carries an ask line: ask="Decide: … · Recommend: … · Stakes: … · By: …" (≤ 240 chars)'
mk = lambda **kw: server.stackshot_create(subject="[home] ask test", description="- Goal: A decision\n- It lives here\n- Done when decided", project="beta", sender="home-beta", **{"next": "home-beta: carry on", **kw})
gid_of = lambda res: re.match(r"created (\w+) ", res).group(1)
nfiles = lambda: len(list((T / "store/a").glob("*.json")))
def setf(g, **kw):
    it = rd(g); it.update(kw); (T / f"store/{g[0]}/{g[1:]}.json").write_text(json.dumps(it))
res = mk(needs="decision", ask="  " + ASK + " "); g1 = gid_of(res); m1 = rd(g1)["metadata"]
check("ask: a valid ask is accepted, stored trimmed and printed right after needs, with no nag", m1.get("ask") == ASK and f"\nneeds: decision\nask: {ASK}\n" in res and "[ask]" not in res, res)
check("ask: the shape is the renderer's, importable", render.parse_ask(ASK) == {"decide": "whether to take vendor A", "recommend": "yes, it is cheaper", "stakes": "B costs a month either way", "by": "Mon Mar 2nd"}
      and render.ASK_RE.fullmatch(ASK) is not None and render.parse_ask("Decide: x · Recommend: y · Stakes: z · By: no date")["by"] == "no date")
bad = {"a part missing": "Decide: whether to take vendor A · Recommend: A · By: Mon Mar 2nd",
       "parts out of order": "Decide: whether to take vendor A · Stakes: a month · Recommend: A · By: Mon Mar 2nd",
       "longer than 240": "Decide: " + "x" * 200 + " · Recommend: A · Stakes: a month · By: Mon Mar 2nd",
       "a newline inside": "Decide: whether to take vendor A\n · Recommend: A · Stakes: a month · By: Mon Mar 2nd",
       "a trailing newline": ASK + "\n",
       "another separator": "Decide: whether to take vendor A - Recommend: A - Stakes: a month - By: Mon Mar 2nd",
       "an empty part": "Decide:  · Recommend: A · Stakes: a month · By: Mon Mar 2nd"}
for why, a_ in bad.items():
    n_ = nfiles(); e = refusal(lambda: mk(needs="decision", ask=a_))
    check(f"ask: misshaped ({why}) refused on create, nothing created", e == SHAPE and nfiles() == n_ and render.parse_ask(a_) is None, e)
    e = refusal(lambda: server._update(g1, ask=a_, sender="home-beta"))
    check(f"ask: misshaped ({why}) refused on update, the item unchanged", e == SHAPE and rd(g1)["metadata"]["ask"] == ASK, e)
check("ask: exactly 240 characters is accepted", render.parse_ask("Decide: " + "x" * (240 - len("Decide:  · Recommend: A · Stakes: a month · By: Mon Mar 2nd")) + " · Recommend: A · Stakes: a month · By: Mon Mar 2nd") is not None)
# stage one (no refuse_after, or a date to come): accepted, with the nag line
res = mk(needs="decision"); g2 = gid_of(res)
check("ask: needs=decision with no ask (a cached schema without the parameter) → created, the nag line without a date, and how such a client passes it", "[ask] A client whose tool has no ask parameter writes the line as the first line of next instead." in res.splitlines() and NAG in res.splitlines() and "ask" not in rd(g2)["metadata"], res)
res = mk(); g3 = gid_of(res); check("ask: no needs, no ask → no nag", "[ask]" not in res, res)
res = server._update(g3, needs="decision", sender="home-beta"); check("ask: an update that sets needs=decision without an ask → accepted, nag", NAG in res.splitlines() and rd(g3)["metadata"]["needs"] == ["decision"], res)
res = server._update(g3, priority="p2", sender="home-beta"); check("ask: any edit of a needs=decision item left without an ask → nag", NAG in res.splitlines(), res)
res = server._update(g3, ask=ASK, sender="home-beta"); check("ask: adding the ask ends the nag", "[ask]" not in res and rd(g3)["metadata"]["ask"] == ASK, res)
later_ = today + datetime.timedelta(days=7); CF["ask"]["refuse_after"] = later_.isoformat()
res = server._update(g2, priority="p3", sender="home-beta")
check("ask: before [ask] refuse_after the nag names the date in words", NAG[:-1] + f"; refused from {render.when_words(later_)})" in res.splitlines(), res)
CF["ask"]["refuse_after"] = "soon"; check("ask: a refuse_after that is not a date reads as none (nag)", server._cfg.ask_refuse_after() == "" and NAG in server._update(g2, priority="p2", sender="home-beta").splitlines())
# stage two (from refuse_after): refused, nothing saved
CF["ask"]["refuse_after"] = today.isoformat()
n_ = nfiles(); e = refusal(lambda: mk(needs="decision")); check("ask: from refuse_after, a needs=decision create without an ask is refused, nothing created", e == NEED and nfiles() == n_, e)
res = mk(needs="decision", ask=ASK); check("ask: …and with one it is created", "[ask]" not in res and rd(gid_of(res))["metadata"]["ask"] == ASK, res)
# a client whose cached schema has no ask (an old claude.ai chat or Cowork session) writes it as the first line of next
LIFT = "(note: this call passed no ask, so the first line of next, which has the ask's form, was taken as the ask line.)"
res = mk(needs="decision", next=ASK + "\nhome-beta: step two"); g6 = gid_of(res)
check("ask: from refuse_after, a create with the ask's form as next's first line is accepted, the line lifted into ask", rd(g6)["metadata"]["ask"] == ASK and rd(g6)["metadata"]["next"] == "home-beta: step two" and LIFT in res and "[ask]" not in res, res)
res = mk(); g7 = gid_of(res)
res = server._update(g7, needs="decision", next="\n" + ASK, sender="home-beta"); check("ask: …an update too; next left empty goes", rd(g7)["metadata"]["ask"] == ASK and "next" not in rd(g7)["metadata"] and LIFT in res, res)
n_ = nfiles(); e = refusal(lambda: mk(needs="decision", next="Decide: something without the rest")); check("ask: …a first line not in the ask's form is still refused", e == NEED and nfiles() == n_, e)
res = mk(needs="decision", ask=ASK, next=ASK.replace("Mon Mar 2nd", "no date") + "\nhome-beta: step two"); check("ask: …a call that passes an ask lifts nothing", rd(gid_of(res))["metadata"]["next"].startswith("Decide:") and LIFT not in res, res)
# a stale ask, refreshed the same way (the item's owner, a session without the ask parameter, could not refresh it)
RFR = "(note: this call passed no ask, so the first line of next, which has the ask's form, replaced the ask line.)"
ASK2 = ASK.replace("Mon Mar 2nd", "Wed Mar 4th")
gr = gid_of(mk(needs="decision", ask=ASK, next="home-beta: step one"))
res = server._update(gr, next=ASK2 + "\nstep two", sender="home-beta")
check("ask: an update whose next starts with a different ask-shaped line replaces the stored ask, the line leaves next, and the reply says so",
      rd(gr)["metadata"]["ask"] == ASK2 and rd(gr)["metadata"]["next"] == "step two" and RFR in res, res)
res = server._update(gr, next=ASK2 + "\nstep three", sender="home-beta")
check("ask: …the same line as the stored ask only leaves next", rd(gr)["metadata"]["ask"] == ASK2 and rd(gr)["metadata"]["next"] == "step three"
      and "repeated the ask line" in res and RFR not in res, res)
res = server._update(gr, next=ASK + "\nstep four", ask=ASK2.replace("Wed Mar 4th", "no date"), sender="home-beta")
check("ask: …a call that passes ask wins, next kept as given", rd(gr)["metadata"]["ask"] == ASK2.replace("Wed Mar 4th", "no date")
      and rd(gr)["metadata"]["next"].startswith(ASK) and RFR not in res, res)
res = server._update(gr, priority="p3", sender="home-beta")
check("ask: …an update that does not pass next leaves an ask-shaped line already in next alone", rd(gr)["metadata"]["ask"] == ASK2.replace("Wed Mar 4th", "no date")
      and rd(gr)["metadata"]["next"].startswith(ASK) and RFR not in res, res)
gq = gid_of(mk(ask=ASK))
res = server._update(gq, next=ASK2 + "\nstep", sender="home-beta")
check("ask: …on an item that needs no decision, next is kept as given", rd(gq)["metadata"]["ask"] == ASK and rd(gq)["metadata"]["next"].startswith(ASK2), res)
res = mk(); g4 = gid_of(res)
e = refusal(lambda: server._update(g4, needs="decision", sender="home-beta")); check("ask: from refuse_after, setting needs=decision without an ask is refused, nothing saved", e == NEED and "needs" not in rd(g4)["metadata"], e)
res = server._update(g4, needs="decision", ask=ASK, sender="home-beta"); check("ask: …with the ask in the same update it is accepted", rd(g4)["metadata"].get("needs") == ["decision"] and "[ask]" not in res, res)
e = refusal(lambda: server._update(g2, priority="p1", sender="home-beta")); check("ask: from refuse_after, an edit of an ask-less needs=decision item is refused", e == NEED and rd(g2)["metadata"].get("priority") == "p2", e)
e = refusal(lambda: server._update(g4, ask="none", sender="home-beta")); check("ask: from refuse_after, clearing the ask of a needs=decision item is refused", e == NEED and rd(g4)["metadata"]["ask"] == ASK, e)
res = server.stackshot_complete(g2, sender="home-beta", outcome="done", reason="the work landed", description="- Goal: The test item's work is in place"); check("ask: a completion never needs an ask", rd(g2)["status"] == "completed" and "[ask]" not in res, res)
CF["ask"]["refuse_after"] = ""
res = server._update(g4, clear_needs=True, sender="home-beta"); check("ask: an ask is kept when needs changes, but not shown once the decision left", "needs" not in rd(g4)["metadata"] and rd(g4)["metadata"]["ask"] == ASK and ASK not in res and "ask:" not in res, res)
res = server._update(g4, needs="decision", sender="home-beta"); check("ask: the decision put back brings the stored ask back into get", f"ask: {ASK}" in res and f"ask: {ASK}" in server.stackshot_get(g4), res)
res = server._update(g4, needs="decision", ask=ASK, sender="home-beta"); res = server._update(g4, needs="none", sender="home-beta")
check("needs: needs=\"none\" clears the badge, like clear_needs (an older tool list may lack it)", "needs" not in rd(g4)["metadata"], res)
res = server._update(g4, ask="none", sender="home-beta"); check("ask: ask=\"none\" clears it", "ask" not in rd(g4)["metadata"] and "ask:" not in res, res)
check("ask: the update and create tools take an ask, and both descriptions say its shape", all("ask" in __import__("inspect").signature(f).parameters for f in (server.stackshot_create, server.stackshot_update, server._update))
      and "ask=\"none\" clears it" in server._UPDATE_DESC and "Stakes: <what happens either way>" in server._UPDATE_DESC)

# ---- 17b. the options
OA = {"label": "Vendor A", "line": "Cheaper, and ships next week.", "recommended": True}
OB = {"label": "Vendor B", "line": "Costs a month more, but the team uses it already.", "recommended": False}
OPTS = [OA, OB]
ASKO = "Decide: which of the two vendors · Recommend: Vendor A, it is cheaper · Stakes: B costs a month either way · By: Mon Mar 2nd"
res = mk(needs="decision", ask=ASKO, options=OPTS); go = gid_of(res); mo = rd(go)["metadata"]
check("options: stored as given, recommended a bool", mo.get("options") == [OA, OB], mo.get("options"))
check("options: the reply lists them under the ask, one line each, the recommended one marked",
      f"ask: {ASKO}\noptions:\n- Vendor A (recommended): Cheaper, and ships next week.\n- Vendor B: Costs a month more" in res and "(note: the ask's Recommend" not in res, res)
res = mk(needs="decision", ask=ASKO, options=json.dumps(OPTS)); check("options: a JSON string of the list is read as the list", rd(gid_of(res))["metadata"]["options"] == OPTS, res)
badopts = {"one entry": [OA], "seven entries": [dict(OA, label=f"L{i}", recommended=i == 0) for i in range(7)],
           "none recommended": [dict(OA, recommended=False), OB], "two recommended": [OA, dict(OB, recommended=True)],
           "a missing line": [OA, {"label": "Vendor B", "recommended": False}], "a line over 160": [OA, dict(OB, line="x" * 161)],
           "a label over 40": [OA, dict(OB, label="y" * 41)], "a newline in a line": [OA, dict(OB, line="one\ntwo")],
           "two equal labels": [OA, dict(OB, label="vendor a")], "not a list": "Vendor A or B", "an entry not an object": [OA, "Vendor B"]}
for why, o_ in badopts.items():
    n_ = nfiles(); e = refusal(lambda: mk(needs="decision", ask=ASKO, options=o_))
    check(f"options: misshaped ({why}) refused, nothing created", e.startswith("Refused: ") and "option" in e and nfiles() == n_, e)
ALT = "Refused: this needs=decision item names alternatives (“"
for why, kw in {"`which of the two` in the ask": dict(ask=ASKO),
                "`pick one` in the ask": dict(ask="Decide: pick one vendor · Recommend: A · Stakes: a month · By: no date"),
                "`Option A` in the description": dict(ask=ASK, description="- Goal: Option A is cheap\n- Option B is fast\n- Done when picked"),
                "`(a) … (b)` in the description": dict(ask=ASK, description="- Goal: Either (a) wait or (b) ship now\n- Done when picked"),
                "`x, y or z` in the Decide part": dict(ask="Decide: merge, deploy or wait · Recommend: merge · Stakes: a day · By: no date"),
                "`x vs y` in the Decide part": dict(ask="Decide: Postgres vs SQLite · Recommend: SQLite · Stakes: a week · By: no date")}.items():
    n_ = nfiles(); kw.setdefault("description", "- Goal: A decision\n- It lives here\n- Done when decided")
    e = refusal(lambda: server.stackshot_create(subject="[home] alt test", project="beta", owner="home-beta", needs="decision", **kw))
    check(f"options: {why}, no options → refused, nothing created, the refusal says what to add and the portal route",
          e.startswith(ALT) and "lists no options" in e and '"recommended": true' in e and "codemode.stackshot_update" in e and nfiles() == n_, e)
for why, a_ in {"a yes/no ask": "Decide: whether to ship the release today · Recommend: yes · Stakes: a day either way · By: no date",
                "one vendor named, no pair (`whether to take vendor A`)": ASK, "the word `optional`": "Decide: make the field optional · Recommend: yes · Stakes: none · By: no date",
                "`options` as a plain noun": "Decide: keep our options open on the lease · Recommend: yes · Stakes: rent · By: no date"}.items():
    res = mk(needs="decision", ask=a_); check(f"options: {why} passes without options", "created" in res, res)
res = server.stackshot_create(subject="[home] alt test", project="beta", owner="home-beta", description="- Goal: Option A or Option B\n- Done when picked", next="home-beta: carry on")
check("options: alternatives on an item that needs no decision pass", "created" in res, res)
# a yes/no decision lists Approve (recommended) and Decline; the gates accept exactly that list and the item page draws its two buttons
YN_ASK = "Decide: whether to ship the release today · Recommend: Approve · Stakes: a day either way · By: no date"
YN_OPTS = [{"label": "Approve", "line": "Ship the release today as it is.", "recommended": True}, {"label": "Decline", "line": "Hold the release.", "recommended": False}]
res = mk(needs="decision", ask=YN_ASK, options=YN_OPTS); gyn = gid_of(res)
check("options: a yes/no ask with Approve (recommended) and Decline listed is accepted and stored as given, with no refusal and no Recommend note",
      "created" in res and rd(gyn)["metadata"]["options"] == YN_OPTS and "(note:" not in res, res)
res = server._update(gyn, ask="Decide: whether to ship the release tomorrow · Recommend: Approve · Stakes: a day either way · By: no date", options=YN_OPTS, sender="home-beta")
check("options: …and an update that writes the same list is accepted too", rd(gyn)["metadata"]["options"] == YN_OPTS and "Refused" not in res and "(note:" not in res, res)
ipn = ui_render.Board(str(T / "store")).item_html(gyn, answer={"action": f"/items/{gyn}/answer", "token": "T", "sent": ""})
check("options: …and the item page draws exactly two options, Approve (marked recommended) first, then Decline",
      re.findall(r'name="choice" value="([^"]*)"', ipn) == ["Approve", "Decline"] and '<span class="alab">Approve</span> <span class="badge rec">recommended</span>' in ipn, re.findall(r'name="choice" value="([^"]*)"', ipn))
e = refusal(lambda: mk(needs="decision", ask=ASKO))
check("options: the refusal for an ask that names alternatives tells a yes/no ask to list Approve and Decline, and an open question to list its answers or become a yes/no", "Approve" in e and "Decline" in e and "open question" in e and "needs no options" not in e and "or reword the ask so it names no alternatives" in e, e)
g8 = gid_of(mk(needs="decision", ask=ASK))
e = refusal(lambda: server._update(g8, ask=ASKO, sender="home-beta")); check("options: an update whose ask names alternatives, none listed → refused, unchanged", e.startswith(ALT) and rd(g8)["metadata"]["ask"] == ASK, e)
res = server._update(g8, ask=ASKO, options=OPTS, sender="home-beta"); check("options: …with the options in the same update it is accepted", rd(g8)["metadata"]["options"] == OPTS and "options:\n- Vendor A (recommended)" in res, res)
e = refusal(lambda: server._update(g8, options="none", sender="home-beta")); check("options: clearing them while the ask names alternatives is refused", e.startswith(ALT) and rd(g8)["metadata"]["options"] == OPTS, e)
res = server._update(g8, ask=ASK, options="none", sender="home-beta"); check("options: options=\"none\" clears them with an ask that names none", "options" not in rd(g8)["metadata"] and "options:" not in res, res)
setf(g8, metadata={**rd(g8)["metadata"], "ask": ASKO})     # an item written before alternatives named, no options
res = server._update(g8, priority="p3", sender="home-beta"); check("options: an edit that writes neither ask, description, needs nor options is not held", rd(g8)["metadata"]["priority"] == "p3", res)
res = server._update(g8, options=[dict(OA, label="Acme"), dict(OB, label="Bolt")], sender="home-beta")
check("options: a Recommend part that does not name the recommended label → a reply note, accepted", "(note: the ask's Recommend part does not name the recommended option, “Acme”" in res and rd(g8)["metadata"]["options"][0]["label"] == "Acme", res)
res = server._update(g8, options=[OA, OB], sender="home-beta"); check("options: …naming it ends the note", "(note: the ask's Recommend" not in res, res)
# option labels and the ask line name who acts; a bare you/I/me/my gets a reply note, never a refusal
YOU_OPTS = [{"label": "A: flag, you approve", "line": "Flag it; Oliver approves it.", "recommended": True}, {"label": "B: Oliver decides", "line": "Hold until Oliver answers.", "recommended": False}]
YOU_ASK = "Decide: flag or hold · Recommend: A: flag, you approve · Stakes: a day either way · By: no date"
NAMED_ASK = "Decide: flag or hold · Recommend: A: flag, Oliver approves · Stakes: a day either way · By: no date"
res = mk(needs="decision", ask=NAMED_ASK, options=YOU_OPTS); gy = gid_of(res)
check("actor: a create whose option label says \"you\" succeeds and the reply notes that label, once",
      "created" in res and rd(gy)["metadata"]["options"][0]["label"] == "A: flag, you approve" and res.count("name who acts") == 1
      and "(note: option “A: flag, you approve” says “you”: name who acts" in res, res)
res = mk(needs="decision", ask=YOU_ASK, options=[dict(YOU_OPTS[0], label="A: flag, Oliver approves"), YOU_OPTS[1]]); gy2 = gid_of(res)
check("actor: …and an ask line that says \"you\" is noted the same way, the item still created",
      "created" in res and rd(gy2)["metadata"]["ask"] == YOU_ASK and "(note: the ask line says “you”: name who acts" in res and "(note: option" not in res, res)
res = mk(needs="decision", ask=NAMED_ASK, options=[dict(YOU_OPTS[0], label="A: flag, Oliver approves"), YOU_OPTS[1]])
check("actor: labels and an ask that name who acts get no note", "created" in res and "name who acts" not in res, res)
res = mk(needs="decision", ask="Decide: reply “I agree” or not · Recommend: A, say `my call` · Stakes: none · By: no date", options=[dict(YOU_OPTS[0], label="A: say \"you\" back"), dict(YOU_OPTS[1], label="B: Oliver decides, i.e. now")])
check("actor: you/I inside quotes or backticks, and \"i.e.\", are not noted", "created" in res and "name who acts" not in res, res)
res = server._update(gy2, ask=NAMED_ASK, options=YOU_OPTS, sender="home-beta")
check("actor: an update that sets options with a \"you\" label notes it, and the write goes through",
      "Refused" not in res and rd(gy2)["metadata"]["options"][0]["label"] == "A: flag, you approve" and "(note: option “A: flag, you approve” says “you”" in res, res)
res = server._update(gy2, ask=YOU_ASK.replace("you approve", "I will approve"), sender="home-beta")
check("actor: an update that sets only the ask notes the ask line and not the stored labels", "(note: the ask line says “I”" in res and "(note: option" not in res, res)
res = server._update(gy2, ask=NAMED_ASK, options=[dict(YOU_OPTS[0], label="A: flag, Oliver approves"), YOU_OPTS[1]], sender="home-beta")
check("actor: …naming who acts ends the note", "name who acts" not in res and "Refused" not in res, res)
# option lines and the wider word list (we/our/us): the same reply note, never a refusal; quoted words, whole-word matching, the abbreviation
def opt_pair(label, line):
    return [{"label": label, "line": line, "recommended": True}, {"label": "B: Pat decides", "line": "Hold until Pat answers.", "recommended": False}]
def actor_hits(label, line):
    return server._actor_note({"options": opt_pair(label, line)}, ask=False)
res = actor_hits("I unpublish", "you click Unpublish")
check("actor: the real case (label \"I unpublish\", line \"you click Unpublish\") is noted once for that option, with an example",
      res.count("name who acts") == 1 and "option \u201cI unpublish\u201d says \u201cI\u201d" in res and f"\u201c{server.OWNER} unpublishes\u201d instead of \u201cI unpublish\u201d" in res, res)
res = actor_hits("Pat unpublishes", "you click Unpublish")
check("actor: a named label with a \"you\" line is noted as the option's line", "the line of option \u201cPat unpublishes\u201d says \u201cyou\u201d: name who acts" in res, res)
for word in ["I", "I'm", "I'll", "I've", "me", "my", "mine", "myself", "we", "we'll", "our", "ours", "us", "you", "your", "yours", "you'll", "yourself"]:
    lab = actor_hits("Pat ships", f"Ship it, {word} decide later")
    lab2 = actor_hits(f"{word} ship", "Pat ships it")
    check(f"actor: \"{word}\" is noted in a line and in a label", "name who acts" in lab and "name who acts" in lab2 and f"says \u201c{word}\u201d" in lab, (lab, lab2))
for line in ["The session redrafts it", "Pat usage report", "Run the mine-sweeper", "Deploy to US-EAST", "Deploy to the US market", "Mirrors the I/O path, i.e. now", "Because the user said so",
             'Pat replies "you can go ahead" to it', "Pat says \u201cwe agree\u201d", "Pat runs `my_script`", "Pat unpublishes it", "The ours-of-it-sweeper runs", "Focus on status"]:
    check(f"actor: \"{line}\" is no hit", actor_hits("Pat unpublishes", line) == "" and actor_hits(line, "Pat acts") == "", (line, actor_hits("Pat unpublishes", line)))
check("actor: a quote does not hide a bare word next to it", "says \u201cyou\u201d" in actor_hits("Pat unpublishes", 'Pat quotes "we win" and you click Unpublish'), actor_hits("Pat unpublishes", 'Pat quotes "we win" and you click Unpublish'))
check("actor: we/our/us are noted in an option only; the ask line keeps its own word list",
      server._actor_note({"ask": "Decide: do we ship it · Recommend: yes", "options": []}) == "" and "says \u201cwe\u201d" in actor_hits("Pat ships", "we ship it"), "")
res = server._actor_note({"options": opt_pair("I a", "you b") + [{"label": "C: me", "line": "x"}, {"label": "D: my", "line": "y"}]})
check("actor: the module re-exports the word-list names", all(hasattr(server, n) for n in ("_OPT_PRONOUN_RX", "_ACTOR_EXAMPLE", "_PRONOUN_HEAD", "_PRONOUN_TAIL")), "")
check("actor: at most three option notes, one per option", res.count("name who acts") == 3, res)
res = server._actor_note({"ask": "Decide: do you ship it", "options": opt_pair("I a", "you b") + [{"label": "C: me", "line": "x"}, {"label": "D: my", "line": "y"}]})
check("actor: three option notes fill the cap and the ask-line note still comes after them", res.count("name who acts") == 4 and res.rstrip().endswith("name who acts, e.g. " + f"\u201c{server.OWNER} unpublishes\u201d instead of \u201cI unpublish\u201d.)") and "the ask line says \u201cyou\u201d" in res.split("\n")[-1], res)
res = actor_hits("", "you click Unpublish")
check("actor: an option with an empty label is named by its place, not by empty quotes", "the line of option 1 says \u201cyou\u201d" in res and "\u201c\u201d" not in res, res)
res = mk(needs="decision", ask=NAMED_ASK, options=opt_pair("A: flag", "you approve it, we wait")); gl = gid_of(res)
check("actor: a create whose option line says \"you\" is created, with the note on that line and no refusal",
      "created" in res and "Refused" not in res and rd(gl)["metadata"]["options"][0]["line"] == "you approve it, we wait" and "(note: the line of option \u201cA: flag\u201d says \u201cyou\u201d: name who acts" in res, res)
res = server._update(gl, options=opt_pair("A: flag", "Pat approves it"), ask=NAMED_ASK, sender="home-beta")
check("actor: …and naming who acts in the line ends the note", "name who acts" not in res and "Refused" not in res, res)
res = server._update(gl, options=opt_pair("A: flag", "we approve it"), ask="Decide: flag or hold \u00b7 Recommend: the slim one \u00b7 Stakes: a day either way \u00b7 By: no date", sender="home-beta")
check("actor: the Recommend-part note still works beside the actor note",
      "(note: the ask's Recommend part does not name the recommended option" in res and "(note: the line of option" in res and "Refused" not in res, res)
check("actor: the shared item form (create and update descriptions) carries the sentence", "Name who acts in every option label and line" in server._ITEM_FORM and "the ask line likewise never says" in server._ITEM_FORM, "")
bo = ui_render.Board(str(T / "store")); ip = bo.item_html(go)
check("options: the item page lists them under the ask, the recommended one marked",
      '<b class="osub">Options</b><ol class="iopts"><li class=rec><b>Vendor A</b> <span class="badge rec">recommended</span><span class="oline">Cheaper, and ships next week.</span></li><li><b>Vendor B</b>' in ip, ip[ip.find('class="iask"'):ip.find('class="iask"') + 900])
md = bo.markdown(); j = md.find(f"**{go} · ")
check("options: board.md lists them under the ask line", "- options:\n  - **Vendor A** (recommended): Cheaper, and ships next week.\n  - **Vendor B**: " in md[j:j + 1200], md[j:j + 1200])
setf(go, metadata={**rd(go)["metadata"], "options": [OA, dict(OB, recommended=True)]})
check("options: a hand-edited list that broke the shape draws nothing", 'class="iopts"' not in ui_render.Board(str(T / "store")).item_html(go))
setf(go, metadata={**rd(go)["metadata"], "options": OPTS})
# the board item: once the decision has left the needs, the options are no open choice: neither the get/update reply
# nor the item page draws them under the ask (the page keeps them in History), nor the queue's tooltip; the stored list stays
res = server._update(go, needs="none", next="act on the decision", sender="home-beta"); ip = ui_render.Board(str(T / "store")).item_html(go)
check("options: decided (decision left the needs): the update reply lists no options", "decision" not in str(rd(go)["metadata"].get("needs") or "")
      and "options:" not in res and rd(go)["metadata"].get("options") == OPTS, res)
check("options: …nor the get reply", "options:" not in server._fmt(rd(go)), server._fmt(rd(go)))
check("options: …nor the item page as an open choice", 'class="iopts"' not in ip and '<b class="osub">' not in ip, ip[ip.find('class="iask"'):ip.find('class="iask"') + 600])
res = server._update(go, needs="decision", ask=ASKO, sender="home-beta")
check("options: back to needs=decision: they are an open choice again", "options:\n- Vendor A (recommended)" in res and 'class="iopts"' in ui_render.Board(str(T / "store")).item_html(go), res)
res = server.stackshot_complete(go, sender="home-beta", outcome="done", reason="Vendor A was picked", description="- Goal: The vendor is picked")
check("options: a close drops them with the ask", "options" not in rd(go)["metadata"] and "options:" not in res and 'class="iopts"' not in ui_render.Board(str(T / "store")).item_html(go), res)
check("options: create and update take options and both descriptions say the form and the refusal",
      all("options" in __import__("inspect").signature(f).parameters for f in (server.stackshot_create, server.stackshot_update, server._update, server._create))
      and "exactly one recommended" in server._UPDATE_DESC and "A yes/no decision lists two options" in server._UPDATE_DESC and "whose Decide part opens with what, which, how, who, when, where or why" in server._UPDATE_DESC and "options=\"none\" clears them" in server._UPDATE_DESC)

# One decision per item: an ask that packs several decisions, or points at its choices by a code the item
# does not spell out, is refused when it is written or changed; an existing item is not held for the ask it already has.
ODRE = "Refused: this ask"
mkd = lambda **kw: server.stackshot_create(**{"subject": "[home] od test", "project": "beta", "owner": "home-beta", "description": "- Goal: A decision\n- It lives here\n- Done when decided", "next": "home-beta: carry on", **kw})
ODHINT = ("One decision per item", "split it into one item per decision", "write each option out in words")   # several decisions
ODCODE = ("write each option out in words", "define each code in the ask or description", "A: ")   # a code the item does not define: no split advice
mkask = lambda decide, rec="yes", desc="- Goal: A decision\n- It lives here\n- Done when decided", **kw: dict(
    ask=f"Decide: {decide} · Recommend: {rec} · Stakes: a day either way · By: no date", description=desc, **kw)
PACKED_ASK = "Decide: tool and choices 2-3 · Recommend: tool on plan A, 2b plugins on plan A, 3a runner off plan A · Stakes: three lanes change · By: Mon Mar 2nd"
n_ = nfiles(); e = refusal(lambda: mk(needs="decision", ask=PACKED_ASK))
check("one decision: the three-decisions ask (choices 2-3, 2b, 3a) is refused on create with the hint, nothing created",
      e.startswith(ODRE) and all(h in e for h in ODHINT) and nfiles() == n_, e)
for why, (kw, frag) in {
        "several Decide: labels": (dict(ask="Decide: ship A · Decide: ship B · Recommend: both · Stakes: a day · By: no date"), "more than one Decide"),
        "a Decide joined by ·": (dict(ask="Decide: ship the fix · rename the repo · Recommend: yes · Stakes: a day · By: no date"), "split by"),
        "a Decide joined by ;": (dict(ask="Decide: ship the fix; rename the repo · Recommend: yes · Stakes: a day · By: no date"), "split by"),
        "`and choices 2-3`": (dict(ask="Decide: Widget and choices 2-3 · Recommend: Widget · Stakes: a day · By: no date"), "and choices 2"),
        "`and the options 1/2`": (dict(ask="Decide: Widget and the options 1/2 · Recommend: Widget · Stakes: a day · By: no date"), "and the options 1"),
        "a Recommend cut by ·": (dict(ask="Decide: what to ship · Recommend: Widget plan-A-only · plugins plan-A-only · Stakes: a day · By: no date"), "split by"),
        "`choice 2`": (mkask("ship choice 2 or wait"), "choice 2"),
        "`option 3`": (mkask("take option 3 or wait"), "option 3"),
        "`options 1/2`": (mkask("take options 1/2 or wait"), "options 1/2"),
        "`Option A`": (mkask("take Option A or wait"), "Option A"),
        "a bare `2b`": (mkask("ship 2b or wait"), "2b"),
        "a bare `3a` in Recommend": (mkask("what to ship", rec="3a"), "3a"),
        "`(a)/(b)`": (mkask("take (a)/(b) or wait"), "(a)")}.items():
    n_ = nfiles(); e = refusal(lambda: mkd(needs="decision", **kw))
    check(f"one decision: {why} → refused on create, the hint says split and word the options, nothing created",
          e.startswith(ODRE) and frag in e and all(h in e for h in (ODHINT if "decisions" in e else ODCODE)) and ("split it" in e) == ("decisions" in e) and nfiles() == n_, e)
for why, (decide, rec) in {
        "a date": ("ship it by Mar 12th or Fri Mar 13th, 2026-03-13", "ship it"), "a version": ("move to v3 or 1.2.3 or v3.1", "v3"),
        "a PR and a board id": (f"merge #19 or hold board#{BID_A} and PR #5", "merge #19"), "sizes": ("use 2GB, 16px, 4K or 7B models", "2GB"),
        "times and days": ("run at 5m, 10am or 3pm, 2d, 3d", "10am"), "a money size": ("budget $5b or 2x", "$5b"),
        "a single decision with `and` in its options": ("A and B together, or C", "A and B together"),
        "a worded single decision": ("whether the tool is plan-A-only or open to all lanes", "plan-A-only, since the cost is per seat")}.items():
    ask_ = mkask(decide, rec)["ask"]
    check(f"one decision: {why} is accepted (the matcher)", server._one_decision({"ask": ask_}, "") == "", server._one_decision({"ask": ask_}, ""))
res = mkd(needs="decision", **mkask(f"ship the 2GB build, v3 and 1.2.3 on Fri Mar 13th at 10am with PR #53 and board#{BID_A}", "yes, 16px, 4K, 7B, 5m, 2d, 3d, $5b"))
check("one decision: dates, versions, ids, sizes and times together pass on create", "created" in res, res)
res = mkd(needs="decision", **mkask("A and B together, or C", "yes, A and B together; C costs a day more"))
check("one decision: a single decision with `and` in its options passes on create", "created" in res, res)
res = mkd(needs="decision", **mkask("ship Widget plan-A-only or on every lane", "yes, plan-A-only, since the cost is per seat"))
check("one decision: a split single ask with its options worded is accepted", "created" in res, res)
for why, kw in {"2b = … in the description": mkask("ship 2b or 3a", "yes, 2b", desc="- Goal: 2b = plugins plan-A-only\n- 3a = the runner off plan A\n- Done when decided"),
                "codes defined by the options list": mkask("take option A or option B", "A", options=[dict(OA, label="A", line="plugins on plan A only", recommended=True), dict(OB, label="B", line="plugins on every lane")])}.items():
    res = mkd(needs="decision", **kw); check(f"one decision: codes defined in the item are accepted on create ({why})", "created" in res, res)
for why, ask_, desc_ in (("A: … B: … in the description", mkask("take Option A or Option B", "Option A")["ask"], "A: plugins on plan A only. B: plugins on every lane. Done when decided."),
                         ("choice codes defined in the ask itself", mkask("take choice 1: Widget plan-A-only or choice 2: Widget on every lane", "choice 1")["ask"], ""),
                         ("(a) … (b) in the ask", mkask("(a) Widget plan-A-only or (b) Widget on every lane", "(a)")["ask"], "")):
    r_ = server._one_decision({"ask": ask_}, desc_)
    check(f"one decision: codes defined in the item are accepted ({why}; the matcher)", r_ == "", r_)
check("one decision: defining the codes does not excuse an ask that packs several decisions", "several decisions" in server._one_decision({"ask": PACKED_ASK}, "2: plugins on plan A. 3: runner off plan A."), "")
e = server._one_decision({"ask": mkask("take Option A or Option B", "Option A")["ask"]}, "A: plugins on plan A only. Done when decided.")
check("one decision: a code with no definition is refused although another is defined (the matcher)", "Option B" in e or "B" in e, e)
od = lambda ask_, desc_="", opts_=None: server._one_decision({"ask": ask_, "options": opts_}, desc_)
# options spelled out in plain prose, in the description, in a list or in bold are defined; a code pointed at by a unit or a place is none
for why, (ask_, desc_) in {
        "`Option A (words)` in the ask": (mkask("take Option A (Widget plan-A-only) or Option B (all lanes)", "Option A")["ask"], ""),
        "`option A, words, or option B, words` in the ask": (mkask("option A, Widget plan-A-only, or option B, all lanes", "A")["ask"], ""),
        "`Option A is …` in the description": (mkask("take option A or option B", "A")["ask"], "Option A is plan-A-only. Option B is all lanes."),
        "`A means …` in the description": (mkask("take option A or option B", "A")["ask"], "A means plan-A-only. B means all lanes."),
        "`1. … / 2. …` in the description": (mkask("take option 1 or option 2", "option 1")["ask"], "1. plan-A-only / 2. all lanes"),
        "`A. …` list lines in the description": (mkask("take option A or option B", "A")["ask"], "A. plan-A-only\nB. all lanes"),
        "`- A: …` list lines in the description": (mkask("take option A or option B", "A")["ask"], "- A: plan-A-only\n- B: all lanes"),
        "markdown bold `**A**` in the description": (mkask("take option A or option B", "A")["ask"], "**A** plan-A-only. **B** all lanes."),
        "`A: … B: …` in the description": (mkask("take Option A or Option B", "Option A")["ask"], "A: plugins on plan A only. B: plugins on every lane."),
        "`choice 1: … choice 2: …` in the ask": (mkask("take choice 1: Widget plan-A-only or choice 2: Widget on every lane", "choice 1")["ask"], ""),
        "`(a) … (b) …` in the ask": (mkask("(a) Widget plan-A-only or (b) Widget on every lane", "(a)")["ask"], ""),
        "`2b = …` in the description": (mkask("ship 2b or 3a", "2b")["ask"], "2b = plugins plan-A-only. 3a = the runner off plan A.")}.items():
    check(f"one decision: {why} defines the code", od(ask_, desc_) == "", od(ask_, desc_))
check("one decision: codes defined by the options list pass", od(mkask("take option A or option B", "A")["ask"], "", [dict(OA, label="A", line="plugins on plan A only"), dict(OB, label="B", line="plugins on every lane")]) == "")
check("one decision: a numbered line `1. …` in the ask itself is not a definition (a sentence end)", od(mkask("take option 1. then wait", "option 1")["ask"]) != "")
for why, ask_ in {"`option 1 year`": mkask("pick option 1 year from now")["ask"], "`options 2x faster`": mkask("take options 2x faster")["ask"],
                  "`choice 3D printer`": mkask("the choice 3D printer")["ask"], "`7b model`": mkask("use the llama 7b model")["ask"],
                  "`Step 2b`": mkask("do Step 2b now")["ask"], "`section 3a`": mkask("see section 3a")["ask"], "`Fig. 2a`": mkask("redo Fig. 2a")["ask"],
                  "`rooms 1a and 2c`": mkask("rooms 1a and 2c")["ask"], "`at 2b`": mkask("at 2b")["ask"], "uppercase `2B`": mkask("ship 2B", "3D")["ask"],
                  "`and options` in prose": mkask("approve it and options stay as is")["ask"], "`and choices` in prose": mkask("whether this and choices of words stay")["ask"],
                  "a `;` in a URL": mkask("open https://x.y/a?b=1;c=2")["ask"], "a `;` in an entity": mkask("whether &lt; works")["ask"],
                  "a trailing `;`": mkask("ship it;")["ask"], "a `;` in a quotation": mkask('whether to use "a; b"')["ask"],
                  "a `;` in a Recommend": mkask("ship", "run it; the wake keeps it fresh")["ask"]}.items():
    check(f"one decision: {why} passes", od(ask_) == "", od(ask_))
for why, ask_ in {"`(a) or (b)`": mkask("take (a) or (b)", "(a)")["ask"], "`(a) vs (b)`": mkask("take (a) vs (b)", "(a)")["ask"],
                  "`(a) / (b)`": mkask("take (a)/(b)", "(a)")["ask"], "`(1) or (2)`": mkask("take (1) or (2)", "(1)")["ask"]}.items():
    check(f"one decision: {why} with no definition is refused", od(ask_) != "", od(ask_))
check("one decision: `(a) or (b)` defined in the description passes", od(mkask("take (a) or (b)", "(a)")["ask"], "(a) plan-A-only. (b) all lanes.") == "")
check("one decision: a `;` followed by a space in a Decide still splits", "split by" in od(mkask("ship the fix; rename the repo")["ask"]), od(mkask("ship the fix; rename the repo")["ask"]))
# the refusal's wording follows the rule that fired
k_ = refusal(lambda: server._gate_one_decision({"ask": mkask("ship 2b or wait")["ask"]}, ""))
check("one decision: only the code rule fired → word the options or define each code, no advice to split", "define each code" in k_ and "A: " in k_ and "split it" not in k_ and "One decision per item" not in k_, k_)
k_ = refusal(lambda: server._gate_one_decision({"ask": PACKED_ASK}, ""))
check("one decision: the several-decisions rule fired → split it into one item per decision", "split it into one item per decision" in k_ and "define each code" not in k_, k_)
k_ = refusal(lambda: server._gate_one_decision({"ask": mkask("ship 2b or wait")["ask"]}, "", True))
check("one decision: an ask lifted from next says so", k_.startswith("Refused: this ask (lifted from next's first line) "), k_)
# an update: refused only when the ask is written or changed; the item keeps its ask
g9 = gid_of(mk(needs="decision", ask=ASK))
e = refusal(lambda: server._update(g9, ask=PACKED_ASK, sender="home-beta")); check("one decision: an update whose ask packs three decisions is refused, the ask unchanged", e.startswith(ODRE) and rd(g9)["metadata"]["ask"] == ASK, e)
e = refusal(lambda: server._update(g9, next="Decide: ship 2b · Recommend: 2b · Stakes: a day · By: no date", sender="home-beta"))
check("one decision: …so is an ask lifted from the first line of next, and the refusal says it came from next", e.startswith(ODRE) and "(lifted from next's first line)" in e and rd(g9)["metadata"]["ask"] == ASK, e)
res = server._update(g9, ask="Decide: Widget on plan A only or all lanes · Recommend: yes, plan A only · Stakes: cost per seat · By: no date", sender="home-beta")
check("one decision: an update with one worded decision is accepted", "plan A only" in rd(g9)["metadata"]["ask"], res)
setf(g9, metadata={**rd(g9)["metadata"], "ask": PACKED_ASK})     # an item written before this rule: the ask it carries stays
res = server._update(g9, priority="p3", sender="home-beta"); check("one decision: an existing item's other-field update is not held", rd(g9)["metadata"]["priority"] == "p3", res)
res = server._update(g9, next="look at the plugins", sender="home-beta"); check("one decision: …nor an update of next", rd(g9)["metadata"]["next"] == "look at the plugins", res)
res = server._update(g9, description="- Goal: A decision\n- It lives here\n- Done when decided, in two lines", sender="home-beta"); check("one decision: …nor of the description", rd(g9)["description"].endswith("two lines"), res)
res = server._update(g9, needs="none", sender="home-beta"); check("one decision: …nor a needs clear", "decision" not in str(rd(g9)["metadata"].get("needs") or ""), res)
res = server._update(g9, clear_ask=True, sender="home-beta"); check("one decision: …nor clearing the ask", "ask" not in rd(g9)["metadata"], res)
check("one decision: create and update descriptions say one decision per item with the options in words",
      all(("One decision per item" in d and "write each option out in words" in d) for d in (server._UPDATE_DESC, server._ITEM_FORM)), server._ITEM_FORM[-700:])

# the item (the linked agent of before it): needs is a list of decision, external and session names. A background agent of the hub, the
# keeper, a sub-page's keeper, the keeper or a background agent of another project, or the item's owner may be named; a user-facing agent or
# an unknown session is refused; a background agent is refused as owner; agent= still writes it; the owner hears a decision, a close and a reopen
_reg0 = (T / "store/projects.json").read_text(); _rg = json.loads(_reg0)
_rg["pages"]["projects/alpha"].update(agents={"work-osprey-main": "front", "work-osprey-z": "front", "work-osprey-y": "back", "work-osprey-bld": "builds, merges and releases the code"}, back_agents={"work-osprey-y": "back", "work-osprey-bld": "builds, merges and releases the code"})   # the builder is the page's keeper (the stand-in)
(T / "store/projects.json").write_text(json.dumps(_rg))
_sjy = json.loads((T / "fleet/a/sessions.json").read_text())      # the background agents named below have panes in the heartbeat: a hand-off to one without is refused (handoff suite)
for _i, _n in enumerate(("work-osprey-y",)): _sjy[f"ffffffff-ffff-4fff-8fff-ffffffffff0{_i}"] = {"name": _n, "machine": "a", "url": "", "seen": "x"}
(T / "fleet/a/sessions.json").write_text(json.dumps(_sjy))
mka = lambda **kw: server.stackshot_create(**{"subject": "[home] linked test", "description": "- Goal: A thing\n- It lives here\n- Done when done", "project": "projects/alpha", "owner": "work-osprey-main", "next": "work-osprey-main: carry on", **kw})
ya = server._session_id("work-osprey-y")
n0 = len(wait_push(0)); res = mka(needs=["work-osprey-y"]); gl = gid_of(res); p = wait_push(n0 + 2)   # the keeper's board line and the named session's, from two threads
check("needs: a background agent of the hub is named, stored as a list, and get shows it", rd(gl)["metadata"].get("needs") == ["work-osprey-y"] and "agent" not in rd(gl)["metadata"]
      and "\nneeds: work-osprey-y\n" in res and "\nneeds: work-osprey-y\n" in server.stackshot_get(gl) and "keeper:" not in server.stackshot_get(gl), res)
check("needs: the session named gets one notice, and the reply says so", any(m[0] == ya and m[1].startswith(f"[stackshot] {gl} now needs you (named in its needs by work-osprey-main)") for m in p[n0:])
      and "work-osprey-y has been told the item needs it" in res, (p[n0:], res))
res = mka(); gd = gid_of(res)
check("needs: none set → nothing stored, and get shows no keeper line (the project's builder holds an item with no mover, and get does not say it)", "needs" not in rd(gd)["metadata"] and "\nkeeper:" not in res and "keeper of record" not in res, res)
check("needs: board.md lists the sessions named", "- needs: `work-osprey-y`" in ui_render.Board(str(T / "store")).markdown())
for why, a_, frag in (("another user-facing agent", "work-osprey-z", "is a user-facing agent of projects/alpha"), ("an unknown session", "nobody-here", "is not a background agent of any project, nor this project's keeper")):
    n_ = nfiles(); e = refusal(lambda: mka(needs=[a_]))
    check(f"needs: {why} is refused with the reason and the choices, nothing created", e.startswith("Refused: ") and frag in e and "work-osprey-y" in e and nfiles() == n_, e)
res = mka(agent="work-osprey-y"); ga = gid_of(res)
check("agent=: the older form still writes the session into needs, nothing under agent", rd(ga)["metadata"].get("needs") == ["work-osprey-y"] and "agent" not in rd(ga)["metadata"], res)
res = server.stackshot_create(subject="[home] linked test", description="- Goal: A thing\n- It lives here\n- Done when done", project="beta", owner="home-beta", needs=["home-beta"], next="home-beta: carry on"); gb = gid_of(res)
check("needs: outside the pilot too (the whole board): the owner itself may be named", rd(gb)["metadata"].get("needs") == ["home-beta"] and "\nneeds: home-beta\n" in res, res)
e = refusal(lambda: server.stackshot_create(subject="[home] linked test", description="- Goal: A thing\n- It lives here\n- Done when done", project="beta", owner="home-beta", needs=["nobody-here"]))
check("needs: …and a session with no role is refused there too", e.startswith("Refused: nobody-here is not a background agent of any project"), e)
e = refusal(lambda: server._update(gd, agent="work-osprey", sender="work-osprey")); check("needs: the retired name-line session is refused by update (agent=), nothing stored", "retired name-line session of projects/alpha" in e and "needs" not in rd(gd)["metadata"], e)
res = server._update(gd, agent="work-osprey-y", sender="work-osprey"); check("needs: a background agent may be named by update (agent=)", rd(gd)["metadata"].get("needs") == ["work-osprey-y"], res)
res = server._update(gd, agent="none", sender="work-osprey"); check("agent=\"none\" takes the sessions out; no keeper line is shown", "needs" not in rd(gd)["metadata"] and "\nkeeper:" not in res, res)
# a cross-project doer, the keeper or a background agent of another project; a user-facing agent anywhere stays refused
res = server._update(gd, needs=["home-beta"], sender="work-osprey"); check("needs: the keeper of another project may be named (a cross-project doer)", rd(gd)["metadata"].get("needs") == ["home-beta"], res)
_rg2 = json.loads((T / "store/projects.json").read_text()); _rg2["pages"]["projects/beta"].update(agents={"home-beta-main": "front", "home-beta-ops": "builds and releases the code"}, back_agents={"home-beta-ops": "builds and releases the code"})
(T / "store/projects.json").write_text(json.dumps(_rg2))
server._cfg.CFG.setdefault("model", {})["handoff"] = False      # home-beta-ops is the keeper of projects/beta, whose pushes these suites read by name: it has no heartbeat row here, so the hand-off guard (handoff suite) is off for the needs= lines below
res = server._update(gd, needs="home-beta-ops", sender="work-osprey"); check("needs: …or one of its background agents (a one-word string reads as a list)", rd(gd)["metadata"].get("needs") == ["home-beta-ops"], res)
e = refusal(lambda: server._update(gd, needs=["home-beta-main"], sender="work-osprey")); check("needs: …never a user-facing agent of another project", e.startswith("Refused: home-beta-main is a user-facing agent of projects/beta") and rd(gd)["metadata"].get("needs") == ["home-beta-ops"], e)
res = server._update(gd, needs=["external", "decision", "home-beta-ops", "home-beta-ops"], ask=ASK, sender="work-osprey")
check("needs: several at once, stored in canonical order (decision, external, then the sessions), deduped", rd(gd)["metadata"].get("needs") == ["decision", "external", "home-beta-ops"], rd(gd)["metadata"].get("needs"))
check("needs: the lane follows the first of decision, external, a session: decision → your call", gd in [r["gid"] for r in ui_render.Board(str(T / "store")).n_call])
server._update(gd, needs=["external", "home-beta-ops"], next="wait on Kim", sender="work-osprey")
check("needs: …external without decision → on others", gd in [r["gid"] for r in ui_render.Board(str(T / "store")).n_relay])
server._update(gd, needs=["home-beta-ops"], sender="work-osprey")
check("needs: …a session alone → on agent", gd in [r["gid"] for r in ui_render.Board(str(T / "store")).agent])
server._cfg.CFG.setdefault("model", {})["handoff"] = True
e = refusal(lambda: server._update(gd, needs=["decision", "nope"], ask=ASK, sender="work-osprey"))
check("needs: an unknown word among the entries is refused as a session name, nothing stored", "nope is not a background agent" in e and rd(gd)["metadata"].get("needs") == ["home-beta-ops"], e)
st_, _ct, body = server._client_items(server._session_id("home-beta")); st2, _ct2, body2 = server._client_items(S)
check("items: a session's list carries the items its needs names, marked role agent; the keeper's list does not", st_ == 200
      and not [x for x in json.loads(body)["items"] if x["gid"] == gd] and not [x for x in json.loads(body2)["items"] if x["gid"] == gd and x.get("role") == "agent"], (body, body2))
ok_ = [x for x in json.loads(server._client_items("home-beta-ops")[2])["items"] if x["gid"] == gd]
check("items: …the named session's list has it, with role agent and needs as a list", len(ok_) == 1 and ok_[0].get("role") == "agent" and ok_[0].get("needs") == ["home-beta-ops"], ok_)
server._update(gd, needs="none", sender="work-osprey")
check("needs: needs=\"none\" empties the list", "needs" not in rd(gd)["metadata"], rd(gd)["metadata"])
n_ = nfiles(); res = mka(owner="work-osprey-y"); gbg = gid_of(res)
check("create: a background agent may create an item: no refusal; the creator is a stored History fact and moves nothing (no mover stored from it)",
      res.startswith("created") and "Refused" not in res and "mover" not in rd(gbg)["metadata"] and "keeper of record" not in res, (sorted(rd(gbg)["metadata"]), nfiles(), n_, res[:80]))
(T / f"store/{gbg[0]}/{gbg[1:]}.json").unlink()
# notices: the wake goes to the session named in needs; a front agent owner hears no move to decision, and its keeper a close
# and a reopen by another session
it = rd(gl); it["metadata"].update(hold=True, wake=D(-1)); (T / f"store/{gl[0]}/{gl[1:]}.json").write_text(json.dumps(it))
time.sleep(0.5); n0 = len(wait_push(0)); server._wake_pass(); time.sleep(0.5); p = wait_push(n0 + 1)
wk = [m for m in p[n0:] if f" {gl} woke" in m[1]]
check("needs: the wake goes to the session named (its mover); the creator and the keeper hear nothing", len(wk) == 1 and wk[0][0] == ya and "keeper of record" not in wk[0][1]
      and not [m for m in p[n0:] if m[0] in (A, S)], p[n0:])
check("keeper: the page's builder, else the project's own keeper", server._keeper("projects/alpha", A) == "work-osprey-bld" and server._keeper("projects/beta", B) == "home-beta-ops")
# the board item D2: every notice about an item goes to its mover alone; the creator (here A, a front agent) is told nothing of a move to decision, a close or a reopen, and no reply names a keeper of record
n0 = len(wait_push(0))
res = server._update(gl, needs="decision", ask=ASKO, options=OPTS, sender="work-osprey-y"); time.sleep(0.7); p = wait_push(0)
check("D2: a move to needs=decision tells the creator nothing, and the reply names no keeper of record",
      not [m for m in p[n0:] if m[0] == A] and "keeper of record" not in res, (res[-500:], p[n0:]))
# a mover that is a keeper (here S, with an item of its own) still hears the move to decision, with the ask and the options, unmarked
item(74, "projects/alpha", S)
n0 = len(wait_push(0))
res = server._update("a74", needs="decision", ask=ASKO, options=OPTS, sender="work-osprey-y"); wait_push(n0 + 2); time.sleep(0.5); p = wait_push(0)
mo_ = [m for m in p[n0:] if m[0] == S and "a74 now needs" in m[1]]
check("D2: a move to needs=decision by another agent reaches the mover, with the ask and the options, unmarked", len(mo_) == 1
      and mo_[0][1].startswith(f"[stackshot] a74 now needs {server.OWNER}'s call") and ASKO in mo_[0][1] and "Vendor A (recommended): Cheaper" in mo_[0][1]
      and "set by work-osprey-y" in mo_[0][1] and server._FOR_OWNER not in mo_[0][1] and "keeper of record" not in res, (p[n0:], res))
server.stackshot_complete("a74", sender="work-osprey", outcome="dropped", reason="test item", description="- Goal: Dropped"); time.sleep(0.5)
n0 = len(wait_push(0)); res = server._update(gl, next="a next step", sender="work-osprey-y"); time.sleep(0.5)
check("D2: an ordinary edit by the agent tells the creator nothing", not [m for m in wait_push(0)[n0:] if m[0] == A], wait_push(0)[n0:])
n0 = len(wait_push(0)); res = server.stackshot_complete(gl, sender="work-osprey-y", outcome="done", reason="Vendor A was picked", description="- Goal: Picked"); time.sleep(0.7); p = wait_push(0)
check("D2: a close by another session is told to the item's mover alone, never to its creator, and the reply names no keeper of record",
      not [m for m in p[n0:] if m[0] == A] and "keeper of record" not in res and not any("keeper of record" in m[1] for m in p[n0:]), (p[n0:], res))
n0 = len(wait_push(0)); res = server._update(gl, status="open", next="look again", sender="work-osprey-y"); time.sleep(0.7); p = wait_push(0)
check("D2: a reopen by another session tells the creator nothing either", not [m for m in p[n0:] if m[0] == A] and "keeper of record" not in res, (p[n0:], res))
n0 = len(wait_push(0)); res = server.stackshot_complete(gl, sender="work-osprey-bld", outcome="done", reason="closed by the builder", description="- Goal: Closed"); time.sleep(0.7); p = wait_push(0)
check("D2: a close by the builder tells the creator nothing", not [m for m in p[n0:] if m[0] == A] and "keeper of record" not in res, (p[n0:], res))
n0 = len(wait_push(0)); res = server._update(gl, status="open", next="look once more", sender="work-osprey-bld"); time.sleep(0.7); p = wait_push(0)
check("D2: a reopen by the builder tells the creator nothing", not [m for m in p[n0:] if m[0] == A] and "keeper of record" not in res, (p[n0:], res))
server._update(gl, clear_needs=True, sender="work-osprey-y")
n0 = len(wait_push(0)); res = server._update(gl, needs=["decision", "work-osprey-y"], ask=ASK, sender="home-beta"); time.sleep(0.7); p = wait_push(0)
check("D2: a move to decision naming a session in needs tells the creator nothing", not [m for m in p[n0:] if m[0] == A] and "keeper of record" not in res, (p[n0:], res))
# the item: when decision leaves needs,
# the sessions still named are told at once; a session added beside it gets the "now needs you" line instead
n0 = len(wait_push(0)); server._update(gl, clear_needs=True, sender="work-osprey-y"); res = server._update(gl, needs=["decision", "work-osprey-y"], ask=ASK, sender="work-osprey-main"); p = wait_push(n0 + 2)   # the board line and the named session's
check("decided: adding a session beside decision tells it 'now needs you' (not 'decided')", any(m[0] == ya and m[1].startswith(f"[stackshot] {gl} now needs you") for m in p[n0:]) and not [m for m in p[n0:] if "has decided" in m[1]], p[n0:])
n0 = len(wait_push(0)); res = server._update(gl, needs=["work-osprey-y"], next="his call: vendor A; place the order", sender="work-osprey-main"); p = wait_push(n0 + 2)
dd = [m for m in p[n0:] if m[0] == ya]
check("decided: decision leaving needs tells the session still named at once, with the next line, and the reply says so", len(dd) == 1
      and dd[0][1].startswith(f"[stackshot] {gl}: {server.OWNER} has decided (decision left its needs, by work-osprey-main), so the move is yours as named in its needs:")
      and "next: his call: vendor A; place the order" in dd[0][1] and "work-osprey-y has been told the move is its now that the decision is in" in res, (p[n0:], res))
check("decided: the create and update descriptions carry the sequencing rule", all(x in server._NEEDS_FORM for x in ("needs names only who can move now", "the session goes first and adds decision when it is done", "when unsure, in sequence", "the sessions still named are told at once"))
      and server._NEEDS_FORM in server._UPDATE_DESC)
n0 = len(wait_push(0)); server._update(gl, clear_needs=True, sender="work-osprey-main"); wait_push(n0 + 1)   # its board line lands before the next count, or that count is stale
# the item rows 3-5: the page-owed notice never goes to a front agent keeper (the writer owes it, the keeper past the grace); an item a
# front agent owns wakes its keeper when no linked agent takes the wake; a back agent, a keeper or a session with no role is unchanged
_kr = server._pilot_charge("projects/alpha/kept", B)
check("a back or no-role keeper of a sub-page is charged as before", _kr == (server._session_id("work-osprey-x"), "agent"), _kr)
n0 = len(wait_push(0)); r_ = server._pilot_relay("projects/alpha/kept", "a4", rd("a4"), "changed (next)", B, "work-osprey-x", "agent"); pk = wait_push(n0 + 1)
check("…and told, unmarked", "charged to the agent work-osprey-x" in r_ and any(m[0] == "work-osprey-x" and m[1].startswith("[board] a4 ") for m in pk[n0:]), pk[n0:])
_rg3 = json.loads((T / "store/projects.json").read_text()); _rg3["pages"]["projects/alpha"]["agents"]["work-osprey-x"] = "front"
(T / "store/projects.json").write_text(json.dumps(_rg3))
_kr = server._pilot_charge("projects/alpha/kept", B)
check("a front agent keeper is passed by: the charge goes to the keeper's role, so the writer owes it and the keeper gets it past the grace", _kr == (S, "name"), _kr)
n0 = len(wait_push(0)); r_ = server._pilot_relay("projects/alpha/kept", "a4", rd("a4"), "changed (next)", B, "work-osprey-x", "agent"); time.sleep(0.5)
check("_pilot_relay sends a front agent no page-owed notice", r_ == "" and not [m for m in wait_push(0)[n0:] if m[0] == "work-osprey-x"], wait_push(0)[n0:])
_rg3["pages"]["projects/alpha"]["agents"].pop("work-osprey-x"); (T / "store/projects.json").write_text(json.dumps(_rg3))
for i, ow in ((47, "home-beta-main"), (48, "nobody-roleless")):
    item(i, "projects/beta", ow); it = rd(f"a{i}"); it["metadata"].update(hold=True, wake=D(-1)); (T / f"store/a/{i}.json").write_text(json.dumps(it))
n0 = len(wait_push(0)); woke = server._wake_pass(); pw = wait_push(n0 + 2)[n0:]
check("an item wakes its mover alone, whoever it is (a front agent or a session with no role): each hears its own, short, with no keeper of record named",
      sorted(m[0] for m in pw) == sorted([server._session_id("home-beta-main"), server._session_id("nobody-roleless")]) and all(m[1].startswith("[stackshot] a4") and "keeper of record" not in m[1] for m in pw), pw)
for i in (47, 48): (T / f"store/a/{i}.json").unlink()
# sala's recycle-done notice: an item a front agent owns goes to its project's keeper instead, unmarked, naming the owner;
# a no-role owner is told itself, and a pilot item's linked agent as before (the fleet test is stubbed, recycles.json restored after)
_rp = server._recycles_path(); _rp0 = _rp.read_text() if _rp.exists() else None; _om = server._on_machine
server._on_machine = lambda m: (server._anc.names(), lambda o: True)
for i, pr, ow in ((50, "projects/beta", "home-beta-main"), (51, "projects/beta", "nobody-roleless"), (52, "projects/alpha", A)):
    item(i, pr, ow); it = rd(f"a{i}"); it["metadata"].update(recycle=True, recycle_at=1.0); (T / f"store/a/{i}.json").write_text(json.dumps(it))
n0 = len(wait_push(0)); rr = server._recycled("testbox", "recycle", time.time(), "ok", []); pw = wait_push(n0 + 3)[n0:]
r50 = [m for m in pw if "a50" in m[1]]; r51 = [m for m in pw if "a51" in m[1]]; r52 = [m for m in pw if "a52" in m[1]]
_sid = server._session_id
check("a recycle done is told to the item's mover alone, whoever it is (a front agent, a session with no role, the page's -main agent), with no keeper of record named; the recycle flag goes",
      len(r50) == 1 and r50[0][0] == "home-beta-main" and r50[0][1].startswith("[stackshot] the recycle you waited for has run (testbox, ") and "re-read a50 and resume." in r50[0][1]
      and "keeper of record" not in r50[0][1] and "recycle" not in rd("a50")["metadata"], (rr, pw))
check("…a session with no role hears its own", len(r51) == 1 and r51[0][0] == "nobody-roleless" and "re-read a51 and resume." in r51[0][1], pw)
check("…and the -main agent that moves a52 hears it, nobody else", len(r52) == 1 and r52[0][0] == _sid("work-osprey-main") and "re-read a52 and resume." in r52[0][1] and server._FOR_OWNER not in r52[0][1], pw)
check("the recycle's report counts the three, told to the three movers", rr["cleared"] == ["a50", "a51", "a52"] and sorted(rr["told"]) == sorted([_sid("work-osprey-main"), "home-beta-main", "nobody-roleless"]), rr)
server._on_machine = _om
for i in (50, 51, 52): (T / f"store/a/{i}.json").unlink()
if _rp0 is None: _rp.unlink(missing_ok=True)
else: _rp.write_text(_rp0)
# a keeper that is a front agent on another page is still the keeper of its own project: charged, told and woken there
_rg4 = json.loads((T / "store/projects.json").read_text()); _rg4["pages"]["projects/beta"]["agents"]["work-osprey"] = "front"
(T / "store/projects.json").write_text(json.dumps(_rg4))
check("session_roles ranks alpha's keeper front (for beta), yet it is not front for an alpha item", server._anc.session_roles().get("work-osprey", {}).get("role") == "front"
      and server._front_keeper("work-osprey", "projects/alpha") == (False, "") and server._front_keeper("work-osprey", "projects/beta")[0], server._anc.session_roles().get("work-osprey"))
check("…so it is still charged as alpha's keeper", server._pilot_charge("projects/alpha", B) == (S, "name"), server._pilot_charge("projects/alpha", B))
n0 = len(wait_push(0)); r_ = server._pilot_relay("projects/alpha", "a1", rd("a1"), "changed (next)", B, S); pk = wait_push(n0 + 1)
check("…and gets alpha's page-owed notice, unmarked", "charged to the keeper" in r_ and any(m[0] == S and m[1].startswith("[board] a1 ") for m in pk[n0:]), (r_, pk[n0:]))
item(49, "projects/alpha", A); it = rd("a49"); it["metadata"].update(hold=True, wake=D(-1)); (T / "store/a/49.json").write_text(json.dumps(it))
n0 = len(wait_push(0)); server._wake_pass(); pw = [m for m in wait_push(n0 + 1)[n0:] if " a49 " in m[1]]
check("…and alpha's wake goes to the item's mover, unmarked", len(pw) == 1 and pw[0][0] == server._session_id("work-osprey-main") and pw[0][1].startswith("[stackshot] a49 woke") and server._FOR_OWNER not in pw[0][1], pw)
(T / "store/a/49.json").unlink(); _rg4["pages"]["projects/beta"]["agents"].pop("work-osprey"); (T / "store/projects.json").write_text(json.dumps(_rg4))
check("needs: the create, update and get descriptions say it; agent=, observers and after are parameters of both tools", server._NEEDS_FORM in server._UPDATE_DESC and "agent=\"none\" takes the sessions out" in server._NEEDS_FORM
      and all(k in __import__("inspect").signature(f).parameters for f in (server.stackshot_create, server.stackshot_update) for k in ("needs", "agent", "observers", "after")))
for g in (gl, gd): (T / f"store/{g[0]}/{g[1:]}.json").unlink()
(T / "store/projects.json").write_text(_reg0)

# a command the owner runs lives on the item: a note, never a refusal
CMDN = "this item waits on the owner running a command or a paste, but next carries neither the command"
ASKC = "Decide: run the setup paste on the laptop · Recommend: yes · Stakes: the box stays offline · By: no date"
res = mk(needs="decision", ask=ASKC, next="home-beta: run the 20-line paste in PowerShell"); gc = gid_of(res)
check("command: a decision item whose ask or next says run or paste, with no link or code span in next → the note, the item created", CMDN in res and server._path(gc).exists(), res)
res = mk(needs="decision", ask=ASKC, next="home-beta: run the paste on [the project page](https://example.com/p#setup)"); check("command: …quiet with a link in next", CMDN not in res, res)
res = mk(needs="decision", ask=ASKC, next="home-beta: run `sala provision home-z` in a shell"); check("command: …quiet with a code span in next", CMDN not in res, res)
res = mk(needs="external", next="Kim: paste the command on their side"); check("command: …quiet on needs=external", CMDN not in res, res)
res = mk(needs="decision", ask="Decide: ノートPCで設定コマンドを実行するか · Recommend: yes · Stakes: オフライン · By: no date", next="home-beta: スクリプト実行")
check("command: …the Japanese words too", CMDN in res, res)
res = server._update(gc, next="run the paste on [the project page](https://example.com/p#setup)", sender="home-beta"); check("command: an update that adds the link ends it", CMDN not in res, res)
res = server._update(gc, priority="p3", sender="home-beta"); check("command: an update that writes none of ask, next or needs says nothing", CMDN not in res, res)

# the item (the item phase 2): the board's form rules that left the rulebook speak as reply notes, only when broken, never as refusals
res = server._create(subject="[home] form test", description="- Lives at https://example.com/x\n- Done when decided", project="beta", owner="home-beta", next="home-beta: carry on"); g5 = gid_of(res)
check("form: a naked URL in a description written by a script (not through the tools) → a note naming it, the item created", "(note: a naked URL (https://example.com/x):" in res and rd(g5)["description"].startswith("- Lives at"), res)
res = server._update(g5, next="read [the doc](https://example.com/y)", sender="home-beta"); check("form: a link on words → no note", "(note:" not in res, res)
res = server._update(g5, next="see https://example.com/z and https://example.com/w", sender="home-beta"); check("form: a naked URL in next → a note, the item updated", "(note: a naked URL (https://example.com/z, …)" in res and rd(g5)["metadata"]["next"].startswith("see"), res)
# a bare URL in what a session writes through the create and update tools is refused (a script's write is not): description, next and ask, each by itself
BARE = "has a bare URL (https://example.com/q) and the page may not draw it as a link. Write it as `[words](url)`"
mkb = lambda **kw: server.stackshot_create(subject="[home] bare url test", description=kw.pop("description", "- Goal: A fact\n- Done when decided"), project="beta", sender="home-beta", **{"next": "home-beta: carry on", **kw})
n_items = len(list((T / "store/a").glob("*.json")))
e = refusal(lambda: mkb(description="- Goal: Lives at https://example.com/q\n- Done when decided")); check("bare url: a create with one in the description is refused, naming the field and the fix", e.startswith("Refused: description " + BARE), e)
e = refusal(lambda: mkb(next="home-beta: read https://example.com/q.")); check("bare url: …in next (the closing dot is not part of it)", e.startswith("Refused: next " + BARE), e)
e = refusal(lambda: mkb(needs="decision", ask="Decide: ship it (https://example.com/q)? · Recommend: yes · Stakes: none · By: no date")); check("bare url: …in the ask", e.startswith("Refused: ask " + BARE), e)
check("bare url: …and none of the three created an item", len(list((T / "store/a").glob("*.json"))) == n_items)
res = mkb(description="- Goal: Lives at [the doc](https://example.com/q)\n- Done when decided", next="home-beta: read [the doc](https://example.com/q) and `curl https://example.com/q`"); g6 = gid_of(res)
check("bare url: a URL inside [words](url) or a code span is accepted in description and next", rd(g6)["description"].startswith("- Goal: Lives at [the doc]"), res)
res = mkb(needs="decision", ask="Decide: ship it ([doc](https://example.com/q))? · Recommend: yes · Stakes: none · By: no date"); check("bare url: …and inside [words](url) in the ask", res.startswith("created "), res)
e = refusal(lambda: server.stackshot_update(g6, description="- Goal: Lives at https://example.com/q\n- Done when decided", sender="home-beta")); check("bare url: an update with one in the description is refused and writes nothing", e.startswith("Refused: description " + BARE) and "[the doc]" in rd(g6)["description"], e)
e = refusal(lambda: server.stackshot_update(g6, next="home-beta: read https://example.com/q", sender="home-beta")); check("bare url: …in next", e.startswith("Refused: next " + BARE) and "[the doc]" in rd(g6)["metadata"]["next"], e)
e = refusal(lambda: server.stackshot_update(g6, needs="decision", ask="Decide: ship it https://example.com/q? · Recommend: yes · Stakes: none · By: no date", sender="home-beta")); check("bare url: …in the ask", e.startswith("Refused: ask " + BARE), e)
res = server.stackshot_update(g6, description="- Goal: Lives at [the page](https://example.com/q)\n- Done when decided", next="home-beta: read [the page](https://example.com/q)", sender="home-beta"); check("bare url: an update with the URL in [words](url) is accepted", "[the page]" in rd(g6)["description"], res)
# old text with a bare URL stays: an update that does not set the field is not refused for it, and one that sets it with that same URL again is not either
it = rd(g6); it["description"] = "- Lives at https://example.com/q\n- Done when decided"; it["metadata"]["next"] = "home-beta: read https://example.com/q"; (T / f"store/{g6[0]}/{g6[1:]}.json").write_text(json.dumps(it))
res = server.stackshot_update(g6, priority="p2", sender="home-beta"); check("bare url: an update that sets none of the three fields is not refused for the stored URLs", rd(g6)["metadata"].get("priority") == "p2", res)
res = server.stackshot_update(g6, description="- Goal: Lives at https://example.com/q\n- Done when decided and posted", sender="home-beta"); check("bare url: …nor one that sets the description with the stored URL still in it", rd(g6)["description"].endswith("posted"), res)
e = refusal(lambda: server.stackshot_update(g6, description="- Goal: Lives at https://example.com/q\n- And at https://example.com/r", sender="home-beta")); check("bare url: …but a new bare URL beside it is refused", "(https://example.com/r)" in e, e)
check("bare url: the create and update descriptions say it", "a naked http(s) URL in description, next or ask is refused, write `[words](url)`" in server._ITEM_FORM and server._ITEM_FORM in server._UPDATE_DESC)
e = refusal(lambda: server._update(g5, hold=True, sender="home-beta")); check("form: an owner's hold without a wake is refused outright, no longer noted", e.startswith("Refused: a hold names what it waits for") and not hd_(rd(g5)["metadata"]), e)
wk = (today + datetime.timedelta(days=3)).isoformat()
res = server._update(g5, hold=True, wake=wk, sender="home-beta"); check("form: a hold with a wake → no note", "(note:" not in res, res)
res = server._update(g5, priority="p2", sender="home-beta"); check("form: a filing edit of a held item → no note", "(note:" not in res, res)
server._update(g5, clear_hold=True, sender="home-beta"); server._update(g5, needs="external", next="wait on Kim", sender="home-beta")
res = server._update(g5, hold=True, wake=wk, sender="home-beta"); check("form: parking an item that waits on someone outside → a note", "(note: on hold while it waits on someone outside" in res and "without a wake" not in res, res)
check("form: the update description carries the rules that moved", all(x in server._UPDATE_DESC for x in ("(needs=external) is not parked", "never a naked URL", "page first")), server._UPDATE_DESC[:200])

# an item put on someone outside with no anchor scoped to it draws one note to anchor the thread, never a refusal
EXTN = "this item now waits on someone outside, and no thread is anchored to it: anchor the thread it waits on in this same turn"
res = server.stackshot_create(subject="[home] ext anchor note", description="- Goal: Waits on Kim's email\n- Done when she answers", project="beta", owner="home-beta", needs="external", next="Kim: answer the email"); gx = gid_of(res)
check("ext anchor: create with needs=external and no anchor → the note naming the item, the item created", EXTN in res and f"items=[{gx}]" in res and server._path(gx).exists(), res)
res = server._update(gx, priority="p2", sender="home-beta"); check("ext anchor: an update that leaves external as it was → no note", EXTN not in res, res)
res = server.stackshot_create(subject="[home] ext anchor note decision", description="- Goal: Waits on Oliver\n- Done when decided", project="beta", owner="home-beta", needs="decision",
                              ask="Decide: whether to take A · Recommend: yes · Stakes: none · By: no date", next="Oliver: pick one"); gdx = gid_of(res)
check("ext anchor: create without external → no note", EXTN not in res, res)
res = server._update(gdx, needs="external", next="wait on Kim", sender="home-beta"); check("ext anchor: an update that adds external with no anchor → the note", EXTN in res and f"items=[{gdx}]" in res, res)
res = server._update(gdx, needs="external", next="still waiting on Kim", sender="home-beta"); check("ext anchor: an update when external was already in needs → no note", EXTN not in res, res)
server._update(gdx, needs="decision", ask="Decide: whether to take A · Recommend: yes · Stakes: none · By: no date", next="Oliver picks", sender="home-beta")
server._anchors("projects/beta", add=["https://github.com/example/repo/issues/91"], who="t")   # project-wide: no items
res = server._update(gdx, needs="external", next="wait on Kim", sender="home-beta"); check("ext anchor: a project-wide anchor alone does not count → the note", EXTN in res, res)
server._update(gdx, needs="decision", ask="Decide: whether to take A · Recommend: yes · Stakes: none · By: no date", next="Oliver picks", sender="home-beta")
server._anchors("projects/beta", add=["https://github.com/example/repo/issues/92"], items=[gdx], who="t")
res = server._update(gdx, needs="external", next="wait on Kim", sender="home-beta"); check("ext anchor: an anchor scoped to the item → no note", EXTN not in res, res)
server._anchors("projects/beta", remove=["https://github.com/example/repo/issues/92"], who="t")
server._update(gdx, clear_hold=True, needs="decision", ask="Decide: whether to take A · Recommend: yes · Stakes: none · By: no date", next="Oliver picks", sender="home-beta")
res = server._update(gdx, needs="external", next="wait on Kim", hold=True, wake=wk, sender="home-beta")
check("ext anchor: external added with a hold and no anchor → exactly one note, the hold's", "(note: on hold while it waits on someone outside" in res and EXTN not in res and res.count("(note:") == 1, res)
server._anchors("projects/beta", remove=["https://github.com/example/repo/issues/91"], who="t")
for g in (gx, gdx): (T / f"store/{g[0]}/{g[1:]}.json").unlink()

# next that reads like a report (a commit hash, a test count, a past-tense report) draws one note, never a refusal; a line over 200 characters is refused (tests/bullets_scenario.py)
RN = "(note: next reads like a report ("
def rnote(nx): return server._report_note(nx)
for name_, nx_, want_ in (
        ("a bare commit hash", "ops-x: fix landed in 0a0a0a0a0, check it", "a commit hash (0a0a0a0a0)"),
        ("a full 40-character hash", "see 0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a now", "a commit hash"),
        ("a hash in link text", "[0a0a0a0a0](https://github.com/o/r/commit/0a0a0a0a0) is in", "a commit hash (0a0a0a0a0)"),
        ("a hash in backticks", "landed as `5f5f5f5` on main", "a commit hash (5f5f5f5)"),
        ("N tests", "ops-x: 12 tests green", "a test count (12 tests)"),
        ("N checks", "the pilot ran 40 checks", "a test count (40 checks)"),
        ("N passed", "pilot: 231 passed", "a test count (231 passed)"),
        ("all suites green", "all suites green on main", "a test count (all suites green)"),
        ("tests passed", "contract tests passed", "a test count (tests passed)"),
        ("merged at the start", "merged and live", "a past-tense report (merged)"),
        ("done at", "- done at the Thu run", "a past-tense report (done at)"),
        ("live since", "live since Tue", "a past-tense report (live since)"),
        ("deployed after PR #N", "PR #12 deployed to prod", "a past-tense report (PR #12 deployed)"),
        ("released after a PR link", "[PR #12](https://github.com/o/r/pull/12) released", "a past-tense report (PR #12 released)"),
        ("released after an owner prefix", "ops-x: released v3.4", "a past-tense report (ops-x: released)")):
    check(f"report note: {name_} → the note", (r_ := rnote(nx_)).startswith("next reads like a report (") and want_ in r_ and "put results, hashes and test counts on the project page (Current state or a timeline line)" in r_, (nx_, r_))
for name_, nx_ in (
        ("merge PR #12 after green CI", "merge PR #12 after green CI"),
        ("a release by someone once tests pass", "ops-plover-engineer: release once tests pass"),
        ("check the deploy", "check the deploy"),
        ("deploy, then tell", "- deploy to prod\n- ops-x: tell the owner when it is live"),
        ("merge a PR link alone", "merge [PR #12](https://github.com/o/r/pull/12), then close [board#5](https://github.com/o/r/issues/5)"),
        ("a hash inside a link URL", "review [the commit](https://github.com/o/r/commit/0a0a0a0a0a0a0a0a)"),
        ("a naked URL with a hash path", "see https://github.com/o/r/commit/0a0a0a0a0a0a0a0a"),
        ("a word of hex letters only", "ops-x: check the defaced and decaded pages"),
        ("a date", "ops-x: review by 20261023"),
        ("add tests", "ops-x: add 3 tests for the parser"),
        ("a command Oliver runs, hash included", f"{server.OWNER}: `stackshot-rollback --rev 0a0a0a0a0`"),
        ("a long command Oliver runs", f"{server.OWNER}: `" + "x " * 150 + "`"),
        ("Oliver's line reporting", f"{server.OWNER}: merged and 12 tests passed"),
        ("a line of 150 characters", "ops-x: " + "word " * 28)):
    check(f"report note: {name_} → no note", rnote(nx_) == "", (nx_, rnote(nx_)))
r_ = rnote("merged 0a0a0a0a0, 12 tests passed\nPR #3 deployed")
check("report note: one note however many lines match, each kind named once", r_.count("next reads like a report") == 1 and "a commit hash" in r_ and "a test count" in r_ and "a past-tense report" in r_, r_)
res = server.stackshot_create(subject="[home] report note", description="- Goal: Waits on Kim\n- Done when she answers", project="beta", owner="home-beta", next="ops-x: merged 0a0a0a0a0, 12 tests passed"); gn = gid_of(res)
check("report note: create → one note, the item still written with that next", res.count(RN) == 1 and server._path(gn).exists() and rd(gn)["metadata"]["next"].startswith("ops-x: merged"), res)
res = server._update(gn, next="ops-x: merge PR #12 after green CI", sender="home-beta"); check("report note: an update to an action line → no note", RN not in res, res)
res = server._update(gn, next="ops-x: PR #12 deployed, all suites green", sender="home-beta"); check("report note: an update to a report → the note, next stored", res.count(RN) == 1 and rd(gn)["metadata"]["next"].startswith("ops-x: PR #12 deployed"), res)
res = server._update(gn, description="- Goal: Merged in 0a0a0a0a0\n- Done when decided", sender="home-beta"); check("report note: a hash in the description alone → no note (only next counts)", RN not in res, res)
res = server._update(gn, priority="p2", sender="home-beta"); check("report note: an update that leaves next as it was → no note", RN not in res, res)
(T / f"store/{gn[0]}/{gn[1:]}.json").unlink()
W_ = server._NEXT_WORDS        # the one wording of what next holds, shared by the create and update forms and the connector instructions
check("report note: the item form (create and update) and the server instructions say what next holds", W_ in server._ITEM_FORM and W_ in server._UPDATE_DESC and W_ in (server.mcp.instructions or ""), server._ITEM_FORM[:300])

# an item that waits on someone outside is parked when the thread it waits on is anchored to it and named in next
TH = "https://github.com/example/repo/issues/7"
server._update(g5, clear_hold=True, sender="home-beta")
server._anchors(rd(g5)["metadata"]["project"], add=[TH], items=[g5], who="t")
res = server._update(g5, hold=True, wake=wk, sender="home-beta"); check("anchored hold: anchored to the item, not named in next → the note says how", f"anchored to it (anchors(project, add=[url], items=[{g5}])) and named in next" in res, res)
server._update(g5, clear_hold=True, next=f"wait on Kim in [#7]({TH})", sender="home-beta")
res = server._update(g5, hold=True, wake=wk, sender="home-beta"); check("anchored hold: anchored to the item and named in next → no note", "(note:" not in res and hd_(rd(g5)["metadata"]), res)
res = server._update(g5, wake=(today + datetime.timedelta(days=45)).isoformat(), sender="home-beta")
check("anchored hold: a wake beyond the backstop (the 7-day cap) → a note", "(note: on hold on an anchored thread with a wake more than 7 days out" in res and "a longer one needs" in res, res)
res = server._update(g5, wake=(today + datetime.timedelta(days=7)).isoformat(), sender="home-beta"); check("anchored hold: a backstop of cap_days → no note", "(note:" not in res, res)
check("anchored hold: the update description carries the exception", "anchored to it (anchors(project, add=[url], items=[its id])) and named in next" in server._UPDATE_DESC
      and "backstop wake (at most [waiting] cap_days out unless his words are on the item)" in server._UPDATE_DESC, server._UPDATE_DESC[:200])
# the item: a notice from the anchor scoped to a held item
# releases the hold when the keeper passes or merges it, never when it drops it; the anchor alone is no condition (the backstop wake stays);
# a project with no keeper releases on the notice itself, by the minute loop's pass
e = refusal(lambda: server._update(g5, wake="none", sender="home-beta"))
check("anchor wait: dropping the backstop wake of a hold that waits on an anchor is refused, naming the backstop", e.startswith(f"Refused: a hold that waits on a notice from the anchor scoped to {g5} still carries a backstop wake, at most 7 days out unless the owner's words are on the item") and held_(g5), e)
t0 = time.time(); time.sleep(0.05)
n_d = routing.record("projects/beta", kind="anchor", to=B, label="GitHub #7", who="hub", text="a comment on #7", target="for home-beta", anchor=TH)
server._route(n_d, "dropped", reason="noise", sender="home-beta")
check("anchor wait: a notice the keeper drops releases nothing", held_(g5), rd(g5)["metadata"])
n_p = routing.record("projects/beta", kind="anchor", to=B, label="GitHub #7", who="hub", text="Kim answered on #7", target="for home-beta", anchor=TH)
n0 = len(wait_push(0)); res = server._route(n_p, "passed", to="home-beta", reason="Kim's answer", sender="home-beta"); p = wait_push(n0 + 1)
check("anchor wait: a notice the keeper passes releases the hold and its wake; the route reply says so", not held_(g5) and "wake" not in rd(g5)["metadata"] and rd(g5)["status"] == "open"
      and f"({g5} waited on this anchor and is released from hold)" in res, (res, rd(g5)["metadata"]))
check("anchor wait: the owner is told what released it", any(m[0] == B and m[1].startswith(f"[stackshot] {g5} woke: a notice from {TH}, the anchor it waited on, was passed by home-beta") for m in p[n0:]), p[n0:])
check("anchor wait: the release moves both clocks (so one notice never releases twice)", rd(g5)["state_updated"] >= t0 and rd(g5)["updated"] == rd(g5)["state_updated"], rd(g5))
server._update(g5, hold=True, wake=wk, sender="home-beta")
check("anchor wait: a notice older than the park releases nothing", server._anchor_release("projects/beta", next(n for n in routing.read("projects/beta") if n["id"] == n_p)) == [] and held_(g5))
n_m = routing.record("projects/beta", kind="anchor", to=B, label="GitHub #7", who="hub", text="merged", target="for home-beta", anchor=TH)
server._route(n_m, "merged", reason="in the digest", sender="home-beta")
check("anchor wait: merged releases too", not held_(g5), rd(g5)["metadata"])
n_o = routing.record("projects/beta", kind="anchor", to=B, label="Slack #ops", who="hub", text="elsewhere", target="for home-beta", anchor="https://example.slack.com/archives/C1")
server._update(g5, hold=True, wake=wk, sender="home-beta"); time.sleep(0.05); server._route(n_o, "passed", to="home-beta", reason="not this thread", sender="home-beta")
check("anchor wait: a notice from an anchor not scoped to the item releases nothing", held_(g5), rd(g5)["metadata"])
_pj = json.loads((T / "store/projects.json").read_text()); _keep_beta = _pj["pages"]["projects/beta"].get("session"); _pj["pages"]["projects/beta"]["session"] = ""; (T / "store/projects.json").write_text(json.dumps(_pj))
check("anchor wait: with no keeper, a pass before any notice releases nothing", server._anchor_pass() == [] and held_(g5))
routing.record("projects/beta", kind="anchor", to="", label="GitHub #7", who="hub", text="logged, not delivered", target="direct", anchor=TH, reason="direct: log only")
check("anchor wait: with no keeper, a log-only direct line (no recipient) releases nothing", server._anchor_pass() == [] and held_(g5))
_g5m = rd(g5); _g5m["metadata"]["mover"] = "home-beta"; (T / f"store/{g5[0]}/{g5[1:]}.json").write_text(json.dumps(_g5m))      # a project with no keeper, no builder and no -main agent has no default mover, so the item names its own
routing.record("projects/beta", kind="anchor", to=B, label="GitHub #7", who="hub", text="Kim wrote again", target="for home-beta", anchor=TH)
n0 = len(wait_push(0)); rel = server._anchor_pass(); p = wait_push(n0 + 1)
check("anchor wait: …and the notice itself does once it arrives, saying the project has no keeper", rel == [g5] and not held_(g5)
      and any(m[1].startswith(f"[stackshot] {g5} woke: a notice from {TH}, the anchor it waited on, arrived (nobody rules this project's notices)") for m in p[n0:]), (rel, p[n0:]))
check("anchor wait: the pass releases once", server._anchor_pass() == [])
_pj["pages"]["projects/beta"]["session"] = _keep_beta; (T / "store/projects.json").write_text(json.dumps(_pj))
check("anchor wait: the update description says how the hold is released", "releases the hold when the project's router (or the project's builder, else its -main agent) passes or merges a notice from that anchor" in server._UPDATE_DESC)

# last confirmed: set on create and on a state change, never on a filing edit
it5 = rd(g4); check("confirmed: set on create (with both clocks)", rd(g1)["confirmed"] == rd(g1)["updated"] == rd(g1)["state_updated"], rd(g1))
setf(g4, confirmed=1000.0, state_updated=1000.0)
server._update(g4, priority="p3", sender="home-beta"); check("confirmed: a filing edit leaves it (and the state clock) alone", rd(g4)["confirmed"] == 1000.0 and rd(g4)["state_updated"] == 1000.0, rd(g4))
server._update(g4, ask=ASK, sender="home-beta"); check("confirmed: an ask edit is filing: no confirm, no state clock", rd(g4)["confirmed"] == 1000.0 and rd(g4)["state_updated"] == 1000.0, rd(g4))
t0 = time.time(); server._update(g4, next="pick one", sender="home-beta"); check("confirmed: a state change sets it with the state clock", rd(g4)["confirmed"] == rd(g4)["state_updated"] >= t0, rd(g4))
# the confirm tool: confirmed only; no page, no relay; published
pubs = []; _pub_ = server._publish; server._publish = lambda: pubs.append(1)
setf("a1", confirmed=1000.0, updated=2000.0, state_updated=2000.0); before = rd("a1")
led0 = json.dumps(server._owed_load(), sort_keys=True); n0 = len(wait_push(0)); t0 = time.time()
res = server.stackshot_confirm("a1", sender="work-osprey-main"); after_ = rd("a1"); time.sleep(0.5)
server._publish = _pub_
check("confirm: sets confirmed only (updated, state_updated, metadata, status as they were); the writer stamp beside it (written_at: when the session last wrote the item) is the one other field that moves",
      after_["confirmed"] >= t0 and after_.get("written_at", 0) >= t0 and {k: v for k, v in after_.items() if k not in ("confirmed", "written_at")} == {k: v for k, v in before.items() if k not in ("confirmed", "written_at")}, (before, after_))
check("confirm: replies 'confirmed <gid> at <time>.' and the item", re.match(r"confirmed a1 at \w{3} \w{3} \d{1,2}(st|nd|rd|th) \d\d:\d\d\.\na1 \[open\] ", res) is not None
      and f"confirmed: {render.when_words(datetime.datetime.fromtimestamp(after_['confirmed'], server.ZONE))} (fresh)" in res, res)
check("confirm: owes no page and tells no keeper on a pilot project", json.dumps(server._owed_load(), sort_keys=True) == led0 and len(wait_push(0)) == n0 and "charged" not in res, (server._owed_load(), wait_push(0)[n0:]))
check("confirm: publishes", pubs == [1], pubs)
check("confirm: a bad id is refused", refusal(lambda: server.stackshot_confirm("zz9")).startswith("bad item id"))
# with the GitHub mirror off (the default here), a tool write without a sender is still the owner's, as before
_save_, saved = server._save, []
server._save = lambda gid, item, writer="", note="", **kw: (saved.append((gid, writer)), _save_(gid, item, writer=writer, note=note, **kw))[1]
res = mk(); g_ns = gid_of(res); own_ns = server._session_id(server._holder(rd(g_ns))); saved.clear()
server.stackshot_confirm(g_ns); server.stackshot_update(g_ns, next="home-beta: take the owner's step")
server.stackshot_complete(g_ns, outcome="done", reason="it is in", description="- Goal: The test item's work is in place")
server._save = _save_
check("mirror off: update, confirm and complete without a sender go through, written as the item's mover", rd(g_ns)["status"] == "completed"
      and rd(g_ns)["metadata"].get("outcome") == "done" and [server._session_id(w) for g, w in saved if g == g_ns] == [own_ns] * 3 and own_ns, (own_ns, saved))
# the wake pass leaves confirmed alone; an item without one keeps the reading it had
res = mk(); g6 = gid_of(res); res = mk(); g7 = gid_of(res)
setf(g6, confirmed=5000.0, state_updated=5000.0, metadata={**rd(g6)["metadata"], "hold": True, "wake": D(-1)})
it7 = rd(g7); it7.pop("confirmed"); it7.update(state_updated=4000.0, updated=4000.0, metadata={**it7["metadata"], "hold": True, "wake": D(-1)}); (T / f"store/{g7[0]}/{g7[1:]}.json").write_text(json.dumps(it7))
woke = server._wake_pass()
check("wake pass: confirmed is not moved, so a woken item reads stale until its owner refreshes it", g6 in woke and rd(g6)["confirmed"] == 5000.0 and rd(g6)["state_updated"] > 5000.0
      and render.freshness(rd(g6), time.time())[0] == "stale", rd(g6))
check("wake pass: an item with no confirmed is pinned at the clock it read as (its old state_updated)", g7 in woke and rd(g7)["confirmed"] == 4000.0 and render.freshness(rd(g7), time.time())[0] == "stale", rd(g7))

# freshness: each lane around its limit, held, completed, the fallbacks, the config
NOW = 2_000_000_000.0; DAY = 86400
fr = lambda needs="", ago=0.0, **kw: render.freshness({"status": "open", "metadata": {**({"needs": needs} if needs else {})}, "confirmed": NOW - ago, **kw}, NOW)
check("freshness: your call: fresh just under 1 d, stale at 1 d", fr("decision", DAY - 60) == ("fresh", DAY - 60) and fr("decision", DAY) == ("stale", DAY))
check("freshness: on agent: fresh just under 1 d, stale at 1 d", fr("", DAY - 60)[0] == "fresh" and fr("", DAY)[0] == "stale")
check("freshness: on others: fresh just under 3 d, stale at 3 d", fr("external", 3 * DAY - 60)[0] == "fresh" and fr("external", 3 * DAY)[0] == "stale" and fr("external", 2 * DAY)[0] == "fresh")
check("freshness: held is 'held', never stale", render.freshness({"status": "open", "metadata": {"hold": True, "needs": "external"}, "confirmed": NOW - 30 * DAY}, NOW) == ("held", 30 * DAY)
      and render.freshness({"status": "on_hold", "metadata": {}, "confirmed": NOW - 30 * DAY}, NOW)[0] == "held")
check("freshness: a hold flag on a decision item is ignored (never on hold, Thu Mar 5th 2026): stale by its lane", render.freshness({"status": "open", "metadata": {"hold": True, "needs": "decision"}, "confirmed": NOW - 30 * DAY}, NOW)[0] == "stale")
check("freshness: completed is never stale", render.freshness({"status": "completed", "metadata": {}, "confirmed": NOW - 30 * DAY}, NOW)[0] == "fresh")
check("freshness: no confirmed → state_updated, else updated", render.freshness({"status": "open", "metadata": {}, "state_updated": NOW - 2 * DAY, "updated": NOW}, NOW) == ("stale", 2 * DAY)
      and render.freshness({"status": "open", "metadata": {}, "updated": NOW - 3600}, NOW) == ("fresh", 3600))
fp_ = T / "fresh-mtime.json"; fp_.write_text("{}"); os.utime(fp_, (NOW - 5 * DAY, NOW - 5 * DAY))
check("freshness: no clock at all → the file's mtime", render.freshness({"status": "open", "metadata": {}, "_path": str(fp_)}, NOW) == ("stale", 5 * DAY)
      and render.confirmed_at({}, str(fp_)) == NOW - 5 * DAY and render.confirmed_at({}) == 0.0)
check("freshness: takes an aware datetime as well", render.freshness({"status": "open", "metadata": {}, "confirmed": NOW - 60}, datetime.datetime.fromtimestamp(NOW, server.ZONE)) == ("fresh", 60))
check("freshness: limits default to 1 / 1 / 3 days", server._cfg.freshness_days() == {"call_days": 1.0, "agent_days": 1.0, "external_days": 3.0})
CF["freshness"] = {"external_days": 5, "call_days": "x", "agent_days": 0.5}
check("freshness: [freshness] overrides a limit; a value that is not a positive number keeps its default", fr("external", 4 * DAY)[0] == "fresh" and fr("decision", DAY)[0] == "stale" and fr("", DAY / 2)[0] == "stale")
del CF["freshness"]
# _fmt's lines
fm = lambda **kw: server._fmt({"id": "99", "gid": "a99", "status": "open", "subject": "[home] fmt", "metadata": {"owner": B, "project": "projects/beta", "needs": "decision", "ask": ASK, "priority": "p1"}, **kw})
c_ = time.time() - 2 * DAY - 100; out_ = fm(confirmed=c_)
out_nw = out_
check("_fmt: ask after needs, before priority; confirmed in words with its staleness", f"needs: decision\nask: {ASK}\npriority: p1\nconfirmed: {render.when_words(datetime.datetime.fromtimestamp(c_, server.ZONE))} (stale 2 d)" in out_nw, out_)
check("_fmt: no waiting line (no expected time is computed): priority is followed by confirmed", "\npriority: p1\nconfirmed: " in out_ and "waiting:" not in out_ and "expected by" not in out_, out_)
cline = lambda out: out.split("\nconfirmed: ", 1)[1].split("\n", 1)[0]
check("_fmt: a fresh item says (fresh)", cline(fm(confirmed=time.time() - 600)).endswith(" (fresh)"), fm(confirmed=time.time() - 600))
check("_fmt: a held item says (held)", server._fmt({"id": "99", "gid": "a99", "status": "open", "subject": "[home] fmt", "metadata": {"hold": True}, "confirmed": c_}).split("\nconfirmed: ", 1)[1].endswith(" (held)"))
check("_fmt: an item without confirmed reads its state_updated", f"confirmed: {render.when_words(datetime.datetime.fromtimestamp(c_, server.ZONE))} (stale 2 d)" in fm(state_updated=c_))
# the renderer: every row carries its freshness; the session-start line counts the stale active items
Z = T / "zstore"; (Z / "a").mkdir(parents=True); (Z / "projects.json").write_text((T / "store/projects.json").read_text())
znow = datetime.datetime(2026, 2, 23, 18, 40, tzinfo=server.ZONE); zt = znow.timestamp()
def zitem(i, ago, status="open", **md):
    (Z / f"a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] z {i}", "description": "x", "status": status, "metadata": {"owner": B, "project": "projects/beta", **md}, "updated": zt - ago, "confirmed": zt - ago}))
zitem(1, 2 * DAY, needs="decision"); zitem(2, 3600); zitem(3, 2 * DAY, needs="external"); zitem(4, 9 * DAY, hold=True); zitem(5, 2 * DAY, status="completed"); zitem(6, 4 * DAY, needs="external")
bz = ui_render.Board(str(Z), now=znow); fz = {r["gid"]: (r["_fresh"], r["_age"]) for r in bz.rows}
check("renderer: each row carries _fresh and _age", fz == {"a1": ("stale", 2 * DAY), "a2": ("fresh", 3600), "a3": ("fresh", 2 * DAY), "a4": ("held", 9 * DAY), "a5": ("fresh", 2 * DAY), "a6": ("stale", 4 * DAY)}, fz)
check("session-start line: ' · <n> stale' before the period, active open items only", bz.brief().splitlines()[0].endswith("completed in 14d · 2 stale."), bz.brief())
zitem(1, 3600, needs="decision"); zitem(6, 3600, needs="external")
check("session-start line: nothing about staleness when nothing is stale", ui_render.Board(str(Z), now=znow).brief().splitlines()[0].endswith("completed in 14d."), ui_render.Board(str(Z), now=znow).brief())

# ---- 18. the ask line and staleness on the board (render.py over #9192's fields): the queue, the item page, the landing lines, board.md
K = T / "store_k"; (K / "a").mkdir(parents=True); (K / "projects.json").write_text((T / "store/projects.json").read_text())
know = datetime.datetime(2026, 2, 23, 18, 40, tzinfo=server.ZONE); kt = know.timestamp()
KASK = "Decide: whether to take vendor A · Recommend: yes, it is cheaper · Stakes: B costs a month either way · By: Mon Mar 2nd"
def kitem(i, owner, upd, conf, **md):
    (K / f"a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] k {i}", "description": "x", "status": "open",
        "metadata": {"owner": owner, "project": "projects/beta", **md}, "updated": kt - upd, "state_updated": kt - upd, "confirmed": kt - conf}))
kitem(81, A, 5 * DAY, 3600)                                  # on agent: updated long ago, confirmed an hour ago → NOT in the queue
kitem(82, A, 3600, 3 * DAY)                                  # on agent: touched an hour ago, confirmed 3 d ago → stale, still NOT in
kitem(83, B, 2 * DAY, 2 * DAY, needs="decision", ask=KASK)   # your call, stale ask
kitem(84, B, 600, 600, needs="decision", ask=KASK)           # your call, fresh ask, same owner
kitem(85, S, 600, 600, needs="decision", ask="please pick a vendor")   # a misshaped ask (a hand edit): shown raw
kitem(86, X, 4 * DAY, 4 * DAY, needs="external")             # on others, stale
bk = ui_render.Board(str(K), now=know)
kids = [r["gid"] for r in bk.n_call]
check("ask/stale home: calls only — on-agent items stay out of Your move, fresh or stale", "a81" not in kids and "a82" not in kids and bk.item("a82")["_fresh"] == "stale" and sorted(kids) == ["a83", "a84", "a85"], kids)
kh = bk.html(); ks = kh[kh.find('<section id="your-move">'):kh.find("</section>", kh.find('<section id="your-move">'))]
_ka = bk.routing_html("projects/beta"); _ka = _ka[_ka.find('<section id="items">'):_ka.find('<section id="sessions">')]
check("ask/stale home: the stale on-agent item keeps its ⚠ on its row of the project page (under the top line), and is no row of Your move", "a82" not in ks and "qdot" not in kh
      and '<span class="iwarn" title="no confirmation for 3 d — may be out of date">⚠</span>' in _ka[_ka.find('id="task-a-82"'):][:900], _ka[:900])
check("ask/stale home: the three calls are rows of Your move, the two a82 and a81 are not, and a misshaped ask is shown raw in its row",
      re.findall(r'<li class="irow hrow" id="task-a-(\d+)"', ks) and sorted(re.findall(r'id="task-a-(\d+)"', ks)) == ["83", "84", "85"] and "please pick a vendor" in ks, ks[:900])
kp = bk.item_html("a83")
_ask = kp[kp.find('<div class="iask">'):kp.find("</div>", kp.find('<div class="iask">'))]
check("ask/stale item page: the Ask block sits under the status line, above Next, four labelled lines",
      kp.find('<aside class="iside"') < kp.find('<div class="istat">') < kp.find('<div class="iask">') < kp.find("<h2>Next</h2>")
      and re.findall(r"<dt>(\w+)</dt>", _ask) == ["Decide", "Recommend", "Stakes", "By"]
      and "<dt>Decide</dt><dd>whether to take vendor A</dd>" in _ask and "<dt>By</dt><dd>Mon Mar 2nd</dd>" in _ask and "<b>Ask</b>" in _ask, _ask)
check("ask/stale item page: an unparseable ask is shown raw under Ask", '<div class="iask"><b>Ask</b><p>please pick a vendor</p></div>' in bk.item_html("a85"))
check("ask/stale item page: no ask, no block", '<div class="iask">' not in bk.item_html("a82"))
_st = lambda h: h[h.find('<div class="istat">'):h.find("</div>", h.find('<div class="istat">'))]
check("ask/stale item page: the sidebar says confirmed <when> · stale (warn) when stale",
      '<dt>Confirmed</dt><dd>Sat Feb 21st 18:40 <span class="iwarn stw" title="ask last confirmed 2 d ago — may be out of date">· stale</span></dd>' in _side(kp) and "confirmed" not in _st(kp), _side(kp))
check("ask/stale item page: …and confirmed <when> alone when fresh", '<dt>Confirmed</dt><dd>Mon Feb 23rd 18:30</dd>' in _side(bk.item_html("a84")) and "stale" not in _side(bk.item_html("a84")), _side(bk.item_html("a84")))
_kpb = bk.routing_html("projects/beta")
_kl = lambda gid: _kpb[_kpb.find(f'<li class="irow hrow" id="task-a-{gid}" data-st='):_kpb.find("</li>", _kpb.find(f'<li class="irow hrow" id="task-a-{gid}" data-st='))]
check("ask/stale project page: a stale your-call row gets the ⚠ with the ask tooltip, alone on the line under the top line",
      _kl(83).startswith('<li class="irow hrow" id="task-a-83" data-st="you"><div class="ir-top"><span class="ir-title"><a class="ir-link" href="/items/a83"') and '</span></div><div class="ir-who"><span class="iwarn" title="ask last confirmed 2 d ago — may be out of date">⚠</span></div><div class="ir-det">' in _kl(83), _kl(83))
check("ask/stale project page: a decision's row carries the ask and its answer form, shown by the home page's script for a signed-in viewer", 'form class="hanswer" data-cards method="post" action="/items/a83/answer"' in _kl(83) and 'data-gid="a83"' in _kl(83) and "<script>" + ui_render._HOME_JS + "</script>" in _kpb, _kl(83))
check("ask/stale project page: on others and on agent say no confirmation", '<span class="iwarn" title="no confirmation for 4 d — may be out of date">⚠</span>' in _kl(86)
      and '<span class="iwarn" title="no confirmation for 3 d — may be out of date">⚠</span>' in _kl(82), (_kl(86), _kl(82)))
check("ask/stale project page: a fresh row is unchanged: no ⚠, no flag beside its age", _kl(84).startswith('<li class="irow hrow" id="task-a-84" data-st="you"><div class="ir-top"><span class="ir-title"><a class="ir-link" href="/items/a84"') and "⚠" not in _kl(84) and "⚠" not in _kl(81) and "iwarn" not in _kl(84), _kl(84))
check("ask/stale project page: nothing else new in a stale row: the text is the number, the goal, the age, the ⚠, then the ask", re.sub(r"<[^>]+>", "", _kl(83)).startswith("a83") and re.search(r"^a83.*? ago⚠", re.sub(r"<[^>]+>", "", _kl(83))), re.sub(r"<[^>]+>", "", _kl(83)))
km = bk.markdown()
_mi = lambda gid: km[km.find(f"**a{gid} · "):].split("\n- mover:", 1)[0]
check("ask/stale board.md: a your-call item carries its ask, a stale one says stale (before the ask)", _mi(83).endswith(f"p2 · stale · ask: {KASK}")
      and _mi(84).endswith(f"p2 · ask: {KASK}"), (_mi(83), _mi(84)))
check("ask/stale board.md: a stale item that waits says stale after what it waits on; no ask outside your call", _mi(86).endswith("waiting on news only the owner relays · stale") and _mi(82).endswith("p2 · stale") and "ask:" not in _mi(81), (_mi(86), _mi(82)))
check("ask/stale: brief() is #9192's, untouched", bk.brief().splitlines()[0].endswith("· 3 stale."), bk.brief())
# history: a confirm alone shows as "confirmed" at its own time; an ask set or edited as "ask edited"
J = T / "jstore"; (J / "a").mkdir(parents=True); (J / "projects.json").write_text((T / "store/projects.json").read_text())
gj = lambda *a: subprocess.run(["git", "-C", str(J), "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], check=True, capture_output=True)
gj("init", "-q")
jv = {"id": "90", "subject": "[home] confirm item", "description": "x", "status": "open", "metadata": {"owner": B, "project": "projects/beta", "needs": "decision"},
      "updated": at(1, 9), "state_updated": at(1, 9), "confirmed": at(1, 9)}
def jcommit(**chg):
    for k_, v_ in chg.items():
        if k_.startswith("m_"): jv["metadata"][k_[2:]] = v_
        else: jv[k_] = v_
    (J / "a/90.json").write_text(json.dumps(jv)); gj("add", "-A"); gj("commit", "-q", "-m", "x")
jcommit(); jcommit(m_ask=KASK, updated=at(2, 10)); jcommit(confirmed=at(3, 11)); jcommit(m_ask=KASK.replace("Mon Mar 2nd", "no date"), updated=at(3, 12))
jcommit(m_next="decide", updated=at(4, 9), state_updated=at(4, 9), confirmed=at(4, 9))
bj = ui_render.Board(str(J), now=know); jev = [(bj.when(ts), k_, re.sub(r"<[^>]+>", "", h_)) for ts, k_, h_ in bj.item_events(bj.item("a90"))[0]]
check("ask/stale history: a confirm alone reads 'confirmed' at its time; an ask set or edited reads 'ask edited'; a state change is not a confirm event", jev == [
    ("Sun Feb 22nd 09:00", "edit", "next: decide"), ("Sat Feb 21st 12:00", "edit", "ask edited"), ("Sat Feb 21st 11:00", "confirm", "confirmed"),
    ("Fri Feb 20th 10:00", "edit", "ask edited"), ("Thu Feb 19th 09:00", "created", "created as “[home] confirm item” · Your move · mover the owner · created by home-beta")], jev)

# ---- error handling on the landing page
# stale / unreachable: the render stamp, the banner, the poll and its guards, the warn threshold
_now = datetime.datetime(2026, 2, 23, 12, 55, tzinfo=bd.now.tzinfo)
be = ui_render.Board(f"{tmp}/store", now=_now); he = be.html()
check("errors: the page carries its render stamp in the head", f'<meta name="stackshot-rendered" content="{int(_now.timestamp())}">' in he[:600], he[:600])
check("errors: the unreachable banner, hidden, with the render time in the board's zone",
      '<div id="conn" class="conn" role="status" aria-live="polite" hidden>' in he and "Can't reach stackshot — showing the board as of Mon Feb 23rd 12:55. Retrying…" in he, he[he.find('id="conn"'):][:400])
check("errors: the newer-board banner with its reload button", 'A newer board is available — <button type="button" id="conn-reload" class="b warn">Reload</button>' in he)
L = ui_render._LIVE_JS
check("errors: the poll script is on the page, polls /render-stamp uncached, every 60 s and on focus / visibility / online / bfcache",
      L in he and "fetch('/render-stamp',{cache:'no-store'" in L and "setTimeout(poll,down?15000:60000)" in L
      and all(f"addEventListener('{e}'" in L for e in ("focus", "online", "offline", "visibilitychange", "pageshow")), L[:300])
check("errors: a redirect (sign-in), a non-OK answer or a body that is not the stamp counts as unreachable; a 401 (signed out) is not a retry (the sign-in suite runs the script)",
      "if(!r.ok||r.redirected)throw 0" in L and "typeof d.ts!=='number')throw 0" in L and ".catch(function(){if(!out)down=true})" in L
      and "if(r.status===401){out=true;throw 0}" in L and "function poll(){if(out)return;" in L)
check("errors: a newer render updates the page in place unless a field has focus, text is selected or the panel's menu is open — then the banner",
      "if(busy()||tried===ts){newer=true;return}return update(ts)" in L and "if(busy())return 'busy'" in L and "else if(k==='busy')newer=true" in L
      and "#panel[data-pbusy],#panel-menu:not([hidden])" in L and "INPUT|TEXTAREA|SELECT" in L)
check("errors: no reload loop — a stamp already reloaded for only gets the banner; no stamp on the page never reloads",
      "function fallback(ts){if(ss(KF)!==String(ts)){ss(KF,String(ts));reload()}else newer=true}" in L and "if(!R||ts<=R)" in L)
# the in-place update (a board write used to republish the page and reload it)
check("in place: location.reload is reached only through reload(), and reload() only from the fallback (and the banner's own button)",
      L.count("location.reload") == 1 and "function reload(){ss(KY,String(window.scrollY||0));location.reload()}" in L
      and [m.start() for m in re.finditer(r"(?<![\w.])(?<!function )reload\(\)", L)] == [L.find("reload()}else newer=true")]
      and L.count("addEventListener('click',reload)") == 1 and L.count("fallback(") == 2 and "if(k==='fail')fallback(ts)" in L
      and "try{k=apply(t)}catch(e){k='fail'}" in L, L)
check("in place: the page itself is fetched uncached, same-origin; a redirect or a non-OK answer reads as unreachable",
      "fetch(location.pathname+location.search,{cache:'no-store',credentials:'same-origin'" in L and L.count("if(!r.ok||r.redirected)throw 0") == 2
      and "new DOMParser().parseFromString(t,'text/html')" in L)
check("in place: a different shell (a deploy's script or style), a different block set or a missing block falls back to the reload",
      "if(!SH||!sh||sh.content!==SH.content)throw 0" in L and "if(!K.length||K.join(' ')!==Object.keys(V).join(' '))throw 0" in L and "if(!o||!n)throw 0" in L)
check("in place: only a changed block is swapped; a block with a popover open waits; folds, the live audit line and the scroll are kept",
      "if(V[k]===W[k])return;" in L and "if(o.querySelector('details:not(.fold)[open]')){later=true;return}" in L
      and "if(k in f)d.open=f[k]" in L and "if(oa&&na)na.parentNode.replaceChild(oa,na)" in L and "if(window.scrollY!==y)window.scrollTo(0,y)" in L)
check("in place: the render stamp and the 'as of' move only when every block is in; the page scripts hear stackshot:swapped",
      "R=S;M.content=String(S)}" in L and "document.dispatchEvent(new Event('stackshot:swapped'))" in L
      and "document.addEventListener('stackshot:swapped',hdr)" in he and "document.addEventListener('stackshot:swapped',function(){tick();rcv()})" in he)
check("in place: the item and project pages' fold toggle stays delegated (a swapped-in fold keeps recording), the home page records nothing", "document.addEventListener('toggle',function(e){var d=e.target;if(d&&d.matches&&d.matches('details.fold')" not in he
      and "d.addEventListener('toggle'" not in ui_render._FOLD_JS and "document.addEventListener('toggle',function(e){var d=e.target;if(d&&d.matches&&d.matches('details.fold')" in ui_render._FOLD_JS)
_bm = lambda h: re.search(r'<meta name="stackshot-blocks" content="([^"]*)">', h).group(1)
_sh = lambda h: re.search(r'<meta name="stackshot-shell" content="([0-9a-f]{16})">', h).group(1)
he2 = ui_render.Board(f"{tmp}/store", now=_now + datetime.timedelta(minutes=7)).html()
check("in place: the head carries the shell and the block fingerprints, by id in page order",
      [p.split("=")[0] for p in _bm(he).split()] == ["counts", "status", "your-move", "agents-at-work", "queued-release", "waiting-list", "machines", "runners", "audit-panel", "projects-panel"]
      and he.find('<meta name="stackshot-rendered"') < he.find('<meta name="stackshot-shell"') < 600 and 'id="counts"' in he, _bm(he))
check("in place: a later render of the same board — ages and 'as of' moved on — keeps every fingerprint and the shell",
      _bm(he) == _bm(he2) and _sh(he) == _sh(he2) and he != he2, (_bm(he), _bm(he2)))
_it = json.loads((T / "store/a/1.json").read_text()); (T / "store/a/1.json").write_text(json.dumps({**_it, "subject": "[home] item 1 renamed"}))
he3 = ui_render.Board(f"{tmp}/store", now=_now).html(); (T / "store/a/1.json").write_text(json.dumps(_it))
_d = [a.split("=")[0] for a, b in zip(_bm(he).split(), _bm(he3).split()) if a != b]
check("in place: a changed item changes only the blocks it is drawn in", _d and "agents-at-work" in _d and "machines" not in _d and "counts" not in _d and _sh(he) == _sh(he3), _d)
_css0 = ui_render.Board._css
ui_render.Board._css = lambda self: _css0(self) + "/*deploy*/"
check("in place: a changed stylesheet changes the shell", _sh(ui_render.Board(f"{tmp}/store", now=_now).html()) != _sh(he))
ui_render.Board._css = _css0
check("errors: a reload keeps the scroll position", "ss(KY,String(window.scrollY||0));location.reload()" in L and "window.scrollTo(0,+y)" in L)
check("errors: stale threshold = 1.5 × the timer period (10 min → 15 min), drawn on the rendered stamp and kept by the page script",
      ui_render._stale_s() == 900 and '<span id="rendered" data-stale="900"' in he and "g.classList.toggle('old',n-(+gs.getAttribute('data-ts'))>+g.getAttribute('data-stale'))" in he
      and "#rendered.old{color:var(--warn)" in he, ui_render._stale_s())
# the daily audit's line under "Need your call (agents)": with the audit off ([audit] enabled false, the example's) hidden and empty
_ws = he[he.find('<div id="status">'):he.find('<section id="your-move">')]
_as = he[he.find('<section id="audit-panel">'):he.find("</aside>")]
check("audit: the line sits in the side panel's own Audit section (open), hidden and empty (a .pc card, the Anchor hub's), the board's zone on it, and the old place under the counts holds none",
      _as.startswith('<section id="audit-panel"><details class="fold" data-fold="audit-panel" open><summary><h2 class="hdr">Audit</h2></summary><div id="audit" class="pc audit" data-tz="Asia/Dubai" hidden><b class="lbl mh"><a class="nm" href="/audits">Audits ↗</a><button type="button" id="audit-now">Audit now</button></b><span class="a-txt"></span> <span class="a-msg" role="status" aria-live="polite"></span></div></details><button type="button" class="pgrip" id="pgrip-audit-panel"')
      and 'id="audit' not in _ws and he.count('id="audit"') == 1 and he.count('id="audit-now"') == 1 and he.find('<aside id="panel"') < he.find('id="audit"'), (_as[:500], _ws[:300]))
check("audit: with the audit off the whole Audit section is hidden with its line (nothing but an empty heading would show), unless it holds the GitHub calls card", "#audit-panel:has(#audit[hidden]):not(:has(#ghcalls)){display:none}" in he)
check("audit: hidden means hidden, whatever the grid display (the card is a .pc grid)", ".audit[hidden]{display:none}" in he)
check("audit: the rows are grid items out of a display:contents wrapper, so they carry the .pc>* rules themselves: a value wraps and may shrink",
      ".audit .a-txt{display:contents}.audit .lbl,.audit .val{min-width:0}.audit .val{white-space:normal;overflow-wrap:anywhere}" in he)
check("audit: Audit now is a text link, not a .b button: a real <button type=button> with id audit-now and no class, inside the card's name row after the name, the old .b rules not applying to it",
      re.search(r'<b class="lbl mh"><a class="nm" href="/audits">Audits ↗</a><button type="button" id="audit-now">Audit now</button></b>', he) is not None and 'id="audit-now" class=' not in he and re.search(r'<button[^>]*id="audit-now"[^>]*class="b', he) is None
      and he.count("Audit now</button>") == 1 and ".a-btn" not in he and ".b.pri" not in he and ".b.xs" not in he)
check("audit: the link look: the accent as text (--acc), no border, no background, no padding, the card text's own font and line height (the name row stays one line), underline on hover and keyboard focus with the focus ring",
      "#audit-now{position:relative;flex:none;margin:0;padding:0;border:0;border-radius:2px;background:none;font:inherit;font-weight:400;line-height:inherit;color:var(--acc);text-decoration:none;cursor:pointer}" in he
      and "@media(hover:hover){#audit-now:hover:not(:disabled){text-decoration:underline}}" in he
      and "#audit-now:focus-visible{outline:2px solid var(--acc);outline-offset:2px;text-decoration:underline}" in he)
check("audit: running, it greys (--mut), loses the underline and shows not-allowed; on a touch screen its tap area is 44 px tall (a hit area laid over the row, the row's height unchanged)",
      "#audit-now:disabled{color:var(--mut);text-decoration:none;cursor:not-allowed}" in he
      and "#audit-now::after{content:'';position:absolute;left:-8px;right:-8px;top:-6px;bottom:-6px}" in he and "@media(pointer:coarse){#audit-now::after{bottom:auto;height:44px}}" in he)
check("audit: the card's name row, 'Audits ↗' (a link to the Audits page), holds the Audit now link at its right end (flex, space between, centred)", "#panel :is(.audit,.ghc)>.mh{grid-column:1/-1;display:flex;justify-content:space-between;align-items:center" in he)
AJ = ui_render._AUDIT_JS
check("audit: the script is on the page, before the poll, and refreshes on every poll tick (load, 60 s, focus …)",
      AJ in he and he.find(AJ) < he.find(L) and "document.addEventListener('stackshot:poll',refresh)" in AJ
      and "last=t;clearTimeout(timer);document.dispatchEvent(new Event('stackshot:poll'));" in L)
check("audit: GET /audit/status uncached; a failure keeps what is drawn; a 404 or enabled false hides the line",
      "fetch('/audit/status',{cache:'no-store',credentials:'same-origin'" in AJ and ".catch(function(){})" in AJ
      and "if(r.status===404&&!r.redirected){E.hidden=true;return null}if(!r.ok||r.redirected)throw 0" in AJ
      and "typeof d.enabled!=='boolean')throw 0" in AJ and "function draw(d){if(!d.enabled){E.hidden=true;if(P)P.hidden=true;return}" in AJ)
check("audit: the button POSTs /audit/now once, same-origin, no retry, and fetches the status after",
      AJ.count("fetch('/audit/now'") == 1 and "fetch('/audit/now',{method:'POST',cache:'no-store',credentials:'same-origin'})" in AJ
      and "setInterval" not in AJ and AJ.count("setTimeout(") == 1 and ".then(function(){inflight=false;btn();refresh()})" in AJ)
check("audit: the button is disabled while a run is in progress, while the POST is in flight and while 'cued' shows",
      "function btn(){B.forEach(function(b){b.disabled=run||inflight||Date.now()<hold;if(inflight)b.setAttribute('aria-busy','true');else b.removeAttribute('aria-busy')})}" in AJ and "run=!!d.running" in AJ and "inflight=true;btn();" in AJ
      and "if(s===202){hold=Date.now()+10000;say(t||SST('panel.audit.cued'),false)}" in AJ)
check("audit: the server's answer shows 10 s — 409 / 503 warn, 404 hides the line",
      "else if(s===409||s===503)say(t||SST('panel.audit.http',{n:s}),true)" in AJ and "if(s===404){E.hidden=true;if(P)P.hidden=true;return}" in AJ and "},10000)" in AJ and ".audit .a-bad,.audit .a-msg.warn{color:var(--warn)" in he)
check("audit: the variants — running since, did not finish (warn), the shortlist (a group's name, its audits, its findings in 24 h, a dash where no log is kept) and the note under it",
      "num(d.running_since)?SST('panel.audit.running_since',{at:clock(d.running_since)}):SST('panel.audit.running')" in AJ and "sp('a-run a-bad',SST('panel.audit.unfinished'))" in AJ
      and "sp('val a-n'+(g.found?' hit':''),g.found===null?'–':String(g.found))" in AJ and "sp('a-h',SST('panel.audit.h_found'))" in AJ and "if(C.note)f.appendChild(sp('a-cn',NK[C.note]?SST('panel.audit.note.'+NK[C.note]):C.note))" in AJ
      and "row('findings'" not in AJ and "row('last audit'" not in AJ)
check("audit: the Audits page's button shares the script: it finds #audit-now-page and the message line #audit-page-msg, and both buttons cue through the one cue()",
      "document.getElementById('audit-page-msg')" in AJ and "B=[N,P].filter(Boolean)" in AJ and "B.forEach(function(b){b.addEventListener('click',function(){if(!b.disabled)cue()})})" in AJ and AJ.count("function cue()") == 1)
check("audit: times in the rulebook's form, in the board's zone", "Intl.DateTimeFormat('en-US',Object.assign({timeZone:Z},O))" in AJ
      and "function when(ts){var p=pt(ts);return SST('date.full',{wd:SST('date.wd.'+WD.indexOf(p.weekday))" in AJ and "hourCycle:'h23'" in AJ)
check("audit: the server's text is drawn as text, never as markup", "innerHTML" not in AJ and "g.textContent=t" in AJ)
check("audit: a redraw builds the new text first and swaps it in, and leaves an unchanged line alone",
      "f=document.createDocumentFragment()" in AJ and "if(sig(f)!==sig(T)){if(T.replaceChildren)T.replaceChildren(f);else{T.textContent='';T.appendChild(f)}}" in AJ
      and "T.textContent=''" not in AJ.replace("else{T.textContent='';T.appendChild(f)}", ""))
# with the audit on, the static page carries the card already drawn — the script's rows, classes and button
from stackshot.audit import audit_overview as _ov
_AD = T / "state/audit"; _AD.mkdir(parents=True, exist_ok=True)
_audit_was = render._cfg.CFG.setdefault("audit", {}).get("enabled"); render._cfg.CFG["audit"]["enabled"] = True
_audit_at_was = render._cfg.CFG["audit"].get("at"); render._cfg.CFG["audit"]["at"] = "05:00"      # the card is checked on the once-a-day schedule; the example ships two times
def _aw(h): w = h[h.find('<section id="audit-panel">'):]; return w[w.find('<div id="audit"'):w.find("</div>", w.find('<div id="audit"')) + 6]
_at = lambda d, hh, mm: (datetime.datetime(2026, 2, 18, hh, mm, tzinfo=_now.tzinfo) + datetime.timedelta(days=d)).timestamp()
_BTN = ' <span class="a-msg" role="status" aria-live="polite"></span></div>'      # the message line after the rows
_NM = lambda dis="": '<b class="lbl mh"><a class="nm" href="/audits">Audits ↗</a><button type="button" id="audit-now"' + dis + '>Audit now</button></b>'
_HD = '<div id="audit" class="pc audit" data-tz="Asia/Dubai">' + _NM() + '<span class="a-txt">'
_CH = '<span class="a-h"></span><span class="a-h">audits</span><span class="a-h">found, 24 h</span>'
def _CARD(found=None, note="\u2013 keeps no findings log"):
    """The shortlist the card draws: per group its name, audits and findings in 24 h (0 for a logged group without findings, a dash for the two that keep no log) and the note."""
    found = found or {}; o = _CH
    for g in _ov.GROUPS:
        n = found.get(g["key"], 0) if g["log"] else None
        o += f'<span class="lbl">{g["name"]}</span><span class="val a-n">{len(g["audits"])}</span><span class="val a-n{" hit" if n else ""}">{"\u2013" if n is None else n}</span>'
    return o + (f'<span class="a-cn">{note}</span>' if note else "")
_LOG = _AD / "findings-log.jsonl"
check("audit on, no run yet: visible, the shortlist of the eight groups (a zero for a group that keeps a log and found nothing, a dash for the two that keep none) and the note, no run line",
      _aw(ui_render.Board(f"{tmp}/store", now=_now).html()) == _HD + _CARD() + '</span>' + _BTN, _aw(ui_render.Board(f"{tmp}/store", now=_now).html()))
(_AD / "run-2026-02-23.json").write_text(json.dumps({"started": _at(5, 5, 0), "finished": _at(5, 5, 20), "items_read": 9,
    "findings": [{"id": "a1"}, {"id": "a2"}], "by_category": {"stale": 1, "no-ask": 1}, "by_session": {}}))
ha = ui_render.Board(f"{tmp}/store", now=_now).html()
check("audit on, last run finished: the same shortlist (the card no longer lists the last run), no run line",
      _aw(ha) == _HD + _CARD() + '</span>' + _BTN, _aw(ha))
check("audit on: the dash is an en dash and never a zero for Fleet and services and Text and rules; the others show a number", _aw(ha).count("\u2013</span>") == 2 and _aw(ha).count('<span class="val a-n">') == 16, _aw(ha))
check("audit on: the line does not move a block's fingerprint (its script keeps it current)", _bm(ha) == _bm(he), (_bm(ha), _bm(he)))
_av = ha[ha.find('<section id="audit-panel">'):]; _av = _av[:_av.find("</section>") + 10]
for _rx, _sub in ui_render._VOLATILE: _av = _rx.sub(_sub, _av)
check("audit on: _VOLATILE takes the whole card (rows, button, message) out of the Audit block's fingerprint, the fold around it stays",
      _av.startswith('<section id="audit-panel"><details class="fold" data-fold="audit-panel" open><summary><h2 class="hdr">Audit</h2></summary></details><button type="button" class="pgrip" id="pgrip-audit-panel"') and 'id="audit"' not in _av, _av)
check("audit on: the card keeps the ids the page script finds it by (#audit, #audit-now, .a-txt, .a-msg) and the live swap carries the live card over by #audit",
      all(x in ha for x in ('id="audit"', 'id="audit-now"', 'class="a-txt"', 'class="a-msg"')) and "o.querySelector('#audit')" in ui_render._LIVE_JS
      and "E=document.getElementById('audit')" in AJ and "N=document.getElementById('audit-now')" in AJ and "T=E.querySelector('.a-txt')" in AJ and "E.querySelector('.a-msg')" in AJ)
# findings in the log: counted by group over the last 24 hours, older ones left out, the group's number marked
_LOG.write_text("\n".join(json.dumps(r) for r in (
    {"at": _now.timestamp() - 3600, "source": "silence", "id": f"board#{1}", "kind": "stale", "agent": "a", "project": "projects/x", "detail": "d"},
    {"at": _now.timestamp() - 7200, "source": "filing", "id": f"board#{2}", "kind": "board checks:why-not-now", "agent": "a", "project": "projects/x", "detail": "d"},
    {"at": _now.timestamp() - 7300, "source": "filing", "id": f"board#{3}", "kind": "stuck-elsewhere", "agent": "a", "project": "projects/x", "detail": "d"},
    {"at": _now.timestamp() - 90000, "source": "filing", "id": f"board#{4}", "kind": "stuck-elsewhere", "agent": "a", "project": "projects/x", "detail": "older than a day"})) + "\n")
check("audit on, findings in the log: counted per group in the last 24 hours (the older one left out), a nonzero number marked 'hit', the groups with no log still a dash",
      _aw(ui_render.Board(f"{tmp}/store", now=_now).html()) == _HD + _CARD({"silence": 1, "filing": 2}) + '</span>' + _BTN, _aw(ui_render.Board(f"{tmp}/store", now=_now).html()))
_pr_was = render._cfg.CFG["audit"].get("pattern_review"); render._cfg.CFG["audit"]["pattern_review"] = "off"
check("audit on, the findings log off: every group a dash and the note says the log is off (a count of nothing is never a zero)",
      _aw(ui_render.Board(f"{tmp}/store", now=_now).html()) == _HD + _CH + "".join(f'<span class="lbl">{g["name"]}</span><span class="val a-n">{len(g["audits"])}</span><span class="val a-n">\u2013</span>' for g in _ov.GROUPS)
      + '<span class="a-cn">\u2013 the findings log is off</span></span>' + _BTN, _aw(ui_render.Board(f"{tmp}/store", now=_now).html()))
if _pr_was is None: render._cfg.CFG["audit"].pop("pattern_review", None)
else: render._cfg.CFG["audit"]["pattern_review"] = _pr_was
_LOG.unlink()
(_AD / "run-2026-02-23.json").write_text(json.dumps({"started": _at(5, 12, 40), "finished": None, "findings": []}))
check("audit on, a run in progress: 'Audit running since 12:40…' above the shortlist, the button disabled",
      _aw(ui_render.Board(f"{tmp}/store", now=_now).html()) == _HD.replace(_NM(), _NM(" disabled")) + '<span class="a-run">Audit running since 12:40…</span>' + _CARD() + '</span>'
      + _BTN, _aw(ui_render.Board(f"{tmp}/store", now=_now).html()))
(_AD / "run-2026-02-23.json").write_text(json.dumps({"started": _at(5, 5, 0), "finished": None, "findings": []}))
check("audit on, a crashed run: 'Last audit did not finish' in warn above the shortlist",
      _aw(ui_render.Board(f"{tmp}/store", now=_now).html()) == _HD + '<span class="a-run a-bad">Last audit did not finish</span>' + _CARD() + '</span>' + _BTN,
      _aw(ui_render.Board(f"{tmp}/store", now=_now).html()))
# the agent's real records hold ISO-8601 strings, not epoch numbers: the card shows the same words
(_AD / "run-2026-02-23.json").write_text(json.dumps({"started": "2026-02-23T05:00+04:00", "finished": "2026-02-23T05:20+04:00", "items_read": 9,
    "findings": [{"id": "a1"}, {"id": "a2"}], "by_category": {"stale": 1, "no-ask": 1}, "by_session": {}}))
check("audit on, last run with ISO-string times: the same card as with epoch numbers",
      _aw(ui_render.Board(f"{tmp}/store", now=_now).html()) == _aw(ha), _aw(ui_render.Board(f"{tmp}/store", now=_now).html()))
(_AD / "run-2026-02-23.json").write_text(json.dumps({"started": "2026-02-22T20:00:00Z", "finished": "2026-02-22T20:20:00Z", "findings": []}))
check("audit on, ISO times with a trailing Z: finished, so no run line",
      _aw(ui_render.Board(f"{tmp}/store", now=_now).html()) == _HD + _CARD() + '</span>' + _BTN, _aw(ui_render.Board(f"{tmp}/store", now=_now).html()))
(_AD / "run-2026-02-23.json").write_text(json.dumps({"started": "2026-02-23T12:40+04:00", "finished": None, "findings": []}))
check("audit on, a run in progress with an ISO start: 'Audit running since 12:40…', the button disabled",
      _aw(ui_render.Board(f"{tmp}/store", now=_now).html()) == _HD.replace(_NM(), _NM(" disabled")) + '<span class="a-run">Audit running since 12:40…</span>' + _CARD() + '</span>'
      + _BTN, _aw(ui_render.Board(f"{tmp}/store", now=_now).html()))
(_AD / "run-2026-02-23.json").write_text(json.dumps({"started": "2026-02-23T05:00+04:00", "finished": None, "findings": []}))
check("audit on, a crashed run with an ISO start: 'Last audit did not finish' in warn, as with an epoch",
      _aw(ui_render.Board(f"{tmp}/store", now=_now).html()) == _HD + '<span class="a-run a-bad">Last audit did not finish</span>' + _CARD() + '</span>' + _BTN,
      _aw(ui_render.Board(f"{tmp}/store", now=_now).html()))
render._cfg.CFG["audit"]["enabled"] = False
check("audit off with run records: hidden and empty", _aw(ui_render.Board(f"{tmp}/store", now=_now).html()) == '<div id="audit" class="pc audit" data-tz="Asia/Dubai" hidden>' + _NM() + '<span class="a-txt"></span>' + _BTN)
render._cfg.CFG["audit"]["enabled"] = _audit_was
render._cfg.CFG["audit"]["at"] = _audit_at_was
for _f in _AD.glob("run-*.json"): _f.unlink()
# receiver cards: a short state word, the raw error only in a tooltip, single-line cells
LONG = "drive user@example.com: [Errno -3] Temporary failure in name resolution (while refreshing the watch channel)"
(T / "state/anchor-hub/status.json").write_text(json.dumps({"started": "x", "anchors": {}, "receivers": {
    "slack": {"ok": True, "checked": "2026-02-23 12:50:00"}, "google": {"ok": False, "error": LONG, "checked": "2026-02-23 12:33:51"},
    "notion": {"ok": False, "error": "invalid_grant: the refresh token was revoked by its owner", "checked": "2026-02-23 12:33:51"},
    "github": {"ok": True, "checked": "2026-02-23 12:55:05"}}}))
hr = ui_render.Board(f"{tmp}/store", now=_now).html()
def rcard(k):
    i = hr.find(f'data-rcv="{k}"'); return hr[hr.rfind("<div", 0, i):hr.find("</div>", i)]
txt = lambda h: re.sub(r"<[^>]+>", "", h)
g = rcard("google"); n_ = rcard("notion"); gh = rcard("github")
check("errors: a network-shaped receiver error → 'unreachable ✗', warn, raw message in the tooltip only",
      'class="pc rcv warn"' in g and '<span class="lbl st warn" title="' + render.esc(LONG) + '">unreachable ✗</span>' in g and "Errno" not in txt(g), g)
check("errors: any other receiver error → 'error ✗', bad", 'class="pc rcv bad"' in n_ and ">error ✗</span>" in n_ and "invalid_grant" not in txt(n_) and "invalid_grant" in n_, n_)
check("errors: a healthy receiver unchanged in words", 'class="pc rcv ok"' in gh and '<span class="lbl st ok" title="healthy">healthy ✓</span>' in gh, gh)
_pr = hr[hr.find('<aside id="panel"'):hr.find("</aside>")]
check("panel: Anchor hub is the panel's second section, after Machines, and not in the main column",
      0 < _pr.find('<section id="machines">') < _pr.find('<section id="anchorhub">') and 'data-rcv="google"' in _pr and 'id="anchorhub"' not in hr[:hr.find('<aside id="panel"')], _pr[:200])
check("errors: every card cell is single-line and clipped with an ellipsis (the age keeps its tooltip unclipped)",
      ".pc{grid-template-columns:minmax(0,max-content) minmax(0,1fr);min-width:0}.pc>*{min-width:0;white-space:nowrap}.pc>:not(.tip){overflow:hidden;text-overflow:ellipsis}" in hr)
check("errors: receiver_state agrees with the cards", ui_render.receiver_state({"ok": False, "error": LONG}) == ("unreachable ✗", "warn")
      and ui_render.receiver_state({"ok": False, "error": "HTTP 401 unauthorized"}) == ("error ✗", "bad") and ui_render.receiver_state({"ok": False}) == ("error ✗", "bad")
      and ui_render.receiver_state({"ok": True, "error": "x"}) == ("healthy ✓", "ok"))
# the live update path (rcv()) draws the same: the same pattern, a short word, the raw text as a title, never as text
check("errors: rcv() uses the render's pattern and never writes the raw error as text",
      f"var NET=new RegExp({json.dumps(ui_render._NET_ERR)},'i');" in hr and "h.title=raw;h.textContent=SST(k==='ok'?'js.rcv.ok':k==='warn'?'js.rcv.warn':'js.rcv.bad')" in hr
      and "(v.error||'down')+' ✗'" not in hr and "['ok','warn','bad'].forEach(function(x){c.classList.toggle(x,x===k)})" in hr and "c.querySelector('.st')" in hr)
check("errors: the board.md receiver table is untouched by the card change", "| google | DOWN: " + LONG + " |" in ui_render.Board(f"{tmp}/store", now=_now).markdown())
# a healthy receiver whose last check is more than twice its beat old is stale, with the age (beats: GitHub and Slack 1 min, Google and Notion 30 min); exactly twice is still healthy
_status_before = (T / "state/anchor-hub/status.json").read_text()
(T / "state/anchor-hub/status.json").write_text(json.dumps({"started": "x", "anchors": {}, "receivers": {
    "github": {"ok": True, "checked": "2026-02-23 12:53:00"}, "slack": {"ok": True, "checked": "2026-02-23 12:52:59"},
    "google": {"ok": True, "checked": "2026-02-23 11:55:00"}, "notion": {"ok": True, "checked": "2026-02-23 11:54:59"},
    "hook-x": {"ok": True, "checked": "2026-02-22 12:55:00"}}}))
hs_ = ui_render.Board(f"{tmp}/store", now=_now).html()
def rcard_(k):
    i = hs_.find(f'data-rcv="{k}"'); return hs_[hs_.rfind("<div", 0, i):hs_.find("</div>", i)]
check("stale: exactly twice the beat old (GitHub 2 min, Google 60 min) is still healthy, drawn as before",
      all('class="pc rcv ok"' in rcard_(k) and '<span class="lbl st ok" title="healthy">healthy ✓</span>' in rcard_(k) for k in ("github", "google")), (rcard_("github"), rcard_("google")))
check("stale: one second past twice the beat (Slack 121 s, Notion 3601 s) is stale, in warn, with the age",
      'class="pc rcv warn"' in rcard_("slack") and ">stale 2m ✗</span>" in rcard_("slack") and 'class="pc rcv warn"' in rcard_("notion") and ">stale 1h ✗</span>" in rcard_("notion"), (rcard_("slack"), rcard_("notion")))
check("stale: the tooltip says how long and that the last check said healthy", "no check for 2m" in rcard_("slack") and "the last one said healthy" in rcard_("slack"), rcard_("slack"))
from stackshot.anchors import receiver_health as _rh_
check("stale: the card's tooltip is the one text (receiver_health.stale_note) the live update takes from the endpoint",
      f'title="{render.esc(_rh_.stale_note("slack", 121))} · checked 2026-02-23 12:52:59' in rcard_("slack")
      and "sn=String(v.stale_note||sw)" in hs_ and "c.title=SST('js.rcv.title',{raw:sn,checked:v.checked,tz:" in hs_ and "h.title=sn;h.textContent=sw" in hs_, rcard_("slack"))
check("stale: a receiver with no known beat is never stale", 'class="pc rcv ok"' in rcard_("hook-x"), rcard_("hook-x"))
check("stale: the live update (rcv()) draws the stale word from the endpoint's `stale` seconds and leaves the healthy lines as they were",
      "if(v.ok&&+v.stale>0){var sw=SST('js.rcv.stale',{age:dur(+v.stale)}),sn=" in hs_ and "h.textContent=SST(k==='ok'?'js.rcv.ok':k==='warn'?'js.rcv.warn':'js.rcv.bad')" in hs_, "")
# the receivers' live update is run, not only read: every function it calls is defined in the page, and (with node) rcv() draws a stale and an errored receiver as the render does
_scripts_ = re.findall(r"<script>(.*?)</script>", hs_, re.S)
_rcv_js_ = next((x for x in _scripts_ if "receivers.json" in x), "")
_i0_ = _rcv_js_.find("(function(){function dur(")
_blk_ = _rcv_js_[_i0_:_rcv_js_.find("tick();rcv()});})();", _i0_) + len("tick();rcv()});})();")] if _i0_ >= 0 else ""      # the receivers' IIFE alone
check("live update: the receivers script defines dur() and fa() before it calls them", "function dur(" in _blk_ and "function fa(" in _blk_ and _blk_.find("function dur(") < _blk_.find("dur(+v.stale)"), _rcv_js_[:200])
import shutil as _shutil_, subprocess as _sp_
if _shutil_.which("node"):
    _head_ = next((x for x in _scripts_ if x.startswith("window.SSD=")), "")
    _sim_ = r"""
const vm=require('vm'),fs=require('fs');const inp=JSON.parse(fs.readFileSync(0,'utf8'));
function mkCard(name){const cls=new Set(['pc','rcv','ok']);const st={className:'lbl st ok',title:'',textContent:''};
 return{name,title:'',classList:{add:c=>cls.add(c),remove:c=>cls.delete(c),toggle:(c,on)=>{on?cls.add(c):cls.delete(c)},has:c=>cls.has(c)},
  getAttribute:a=>a==='data-rcv'?name:null,querySelector:q=>q==='.st'?st:null,st,cls}}
const cards={slack:mkCard('slack'),github:mkCard('github')};let ticks=0;
const ctx={window:{},document:{getElementById:()=>null,addEventListener(){},querySelectorAll:q=>{if(q==='[data-rcv]')return Object.values(cards);if(q==='[data-ts]')ticks++;return[]}},
 fetch:()=>Promise.resolve({status:200,ok:true,json:()=>Promise.resolve(inp.data)}),setInterval(){},setTimeout,Promise,RegExp,Math,Date,String,JSON,console};
vm.createContext(ctx);vm.runInContext(inp.head,ctx);ctx.SST=ctx.window.SST;
vm.runInContext(inp.block,ctx);
setTimeout(()=>{const o={ticks};for(const k in cards){const c=cards[k];o[k]={cls:[...c.cls].filter(x=>['ok','warn','bad'].includes(x)),word:c.st.textContent,stcls:c.st.className,title:c.title}}
 process.stdout.write(JSON.stringify(o))},50);"""
    _data_ = {"slack": {"ok": True, "checked": "2026-02-23 11:00:00", "stale": 7200, "stale_note": "no check for 2h; the last one said healthy", "ts": 1}, "github": {"ok": False, "error": "HTTP 401 unauthorized", "checked": "2026-02-23 12:53:00", "ts": 1}}
    _r_ = _sp_.run(["node", "-e", _sim_], input=json.dumps({"head": _head_, "block": _blk_, "data": _data_}), capture_output=True, text=True, timeout=30)
    if _r_.returncode != 0 or not _r_.stdout: check("live update: rcv() runs in a simulated page (node)", False, _r_.stderr[-500:])
    else:
        _o_ = json.loads(_r_.stdout)
        check("live update: a stale receiver is drawn warn, 'stale 2h ✗', with the endpoint's note as its tooltip (the healthy line is not left standing)",
              _o_["slack"]["cls"] == ["warn"] and _o_["slack"]["word"] == "stale 2h ✗" and _o_["slack"]["stcls"] == "lbl st warn" and _o_["slack"]["title"].startswith("no check for 2h; the last one said healthy"), _o_)
        check("live update: an errored receiver is drawn bad, 'error ✗', and tick() runs (the later cards are still updated)", _o_["github"]["cls"] == ["bad"] and _o_["github"]["word"] == "error ✗" and _o_["ticks"] >= 2, _o_)
# a receiver that announced a wait (status.json hold:the first pass after a start, a wait after GitHub refuses calls) is not stale during it, and counts its age from the end of it
_t0_ = _now.timestamp()
(T / "state/anchor-hub/status.json").write_text(json.dumps({"started": "x", "anchors": {}, "hold": {"github": _t0_ + 300, "slack": _t0_ - 121},
    "receivers": {"github": {"ok": True, "checked": "2026-02-23 12:00:00"}, "slack": {"ok": True, "checked": "2026-02-23 12:00:00"}}}))
hh_ = ui_render.Board(f"{tmp}/store", now=_now).html()
def rcard2_(k):
    i = hh_.find(f'data-rcv="{k}"'); return hh_[hh_.rfind("<div", 0, i):hh_.find("</div>", i)]
check("stale: a hold that has not run out keeps a receiver healthy however old its check; one that ran out 121 s ago is stale, 2m old",
      'class="pc rcv ok"' in rcard2_("github") and 'class="pc rcv warn"' in rcard2_("slack") and ">stale 2m ✗</span>" in rcard2_("slack"), (rcard2_("github"), rcard2_("slack")))
(T / "state/anchor-hub/status.json").write_text(_status_before)

# ---- items that wait for a pane recycle (metadata.recycle): one plain status line under the Machines
# heading listing the open ones not on hold or held for the recycle alone (render.recycle_due, the test the server's recycle-wanted
# uses), oldest update first; the same line under the Machines table in board.md; a "waits for recycle"
# badge on their lines and pages. Sala runs a flagged recycle itself, so the line is out of "Need your call (agents)"
# and "Needs your call".
RS = T / "rstore"; (RS / "a").mkdir(parents=True); (RS / "projects.json").write_text((T / "store/projects.json").read_text())
def ritem(i, ago, rec=None, needs="", status="open", hold=False, wake="", after=None):
    md = {"owner": B, "project": "projects/beta", **({"needs": needs} if needs else {}), **({"hold": True} if hold else {}), **({"recycle": rec} if rec is not None else {}),
          **({"wake": wake} if wake else {}), **({"after": after} if after else {})}
    (RS / f"a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] recycle item {i}", "description": "x", "status": status, "metadata": md, "updated": (qnow - ago).timestamp()}))
for i_, ago_ in ((81, 5), (82, 9), (83, 2), (84, 7), (85, 3), (86, 4), (87, 1), (88, 6), (89, 8)): ritem(i_, ago_ * H_, needs="decision" if i_ == 81 else "")
_rb = lambda: ui_render.Board(str(RS), now=qnow)
r0 = _rb(); h0 = r0.html(); m0 = r0.markdown()
_ws = lambda h: h[h.find('<div id="status">'):h.find('<section id="your-move">')]
check("recycle: no item carries the field → no status line and no board.md line", r0.recycle == [] and '<p id="recycle"' not in h0 and "Pane recycle" not in h0
      and "Pane recycle" not in m0 and "waits for recycle" not in h0, r0.recycle)
ritem(81, 5 * H_, True, needs="decision"); ritem(82, 9 * H_, "yes"); ritem(83, 2 * H_, 1)                  # open: listed
ritem(88, 6 * H_, True, hold=True)                                                                      # held for the recycle alone: listed → the item
ritem(84, 7 * H_, "true", hold=True, wake="2099-01-02"); ritem(89, 8 * H_, True, hold=True, after=["a86"])  # held for a wake, or an open after, as well: not listed
ritem(85, 3 * H_, True, status="completed")                                                             # completed: never listed
ritem(86, 4 * H_, "no"); ritem(87, 1 * H_, 0)                                                           # falsy values: not set
r1 = _rb(); h1 = r1.html(); m1 = r1.markdown(); w1 = _ws(h1)
_ms = lambda h: h[h.find('<section id="machines">'):h.find("</section>", h.find('<section id="machines">'))]
x1 = _ms(h1)
_ra = lambda g: f'<a class="r-id" href="/items/{g}" target="_blank" rel="noopener" title="[home] recycle item {g[1:]}">{g}</a>'
check("recycle: the field is read as set for true, \"true\", 1, \"yes\" and not for false, 0, \"\", \"no\" or absent",
      all(render.waits_recycle({"metadata": {"recycle": v}}) for v in (True, "true", "TRUE", 1, "yes", "Yes", "1"))
      and not any(render.waits_recycle({"metadata": {"recycle": v}}) for v in (False, 0, "", "no", "false", None, 2)) and not render.waits_recycle({"metadata": {}}))
check("recycle: the status line lists exactly the open items not on hold or held for the recycle alone, oldest update first",
      [r["gid"] for r in r1.recycle] == ["a82", "a88", "a81", "a83"], [r["gid"] for r in r1.recycle])
check("recycle: one plain status line, linked ids (new tab, subject as tooltip), in order, saying sala runs it",
      h1.count('<p id="recycle"') == 1 and f'<p id="recycle" class="mnote" role="status">Pane recycle pending for {_ra("a82")}, {_ra("a88")}, {_ra("a81")}, {_ra("a83")} (sala runs it)</p>' in x1, x1[:900])
_rline = x1[x1.find('<p id="recycle"'):x1.find("</p>", x1.find('<p id="recycle"'))]
check("recycle: an item held for the recycle alone is on the line (sala's recycle-wanted counts it too)", '/items/a88"' in _rline, _rline)
check("recycle: an item held with a wake as well is not on the line, nor one held for an open after as well", '/items/a84"' not in _rline and '/items/a89"' not in _rline, _rline)
check("recycle: completed items and falsy values are not on the line", all(f"/items/{g}\"" not in _rline for g in ("a85", "a86", "a87")), _rline)
check("recycle: the board's test is the predicate the server's recycle-wanted calls",
      render.recycle_due(next(r for r in r1.rows if r["gid"] == "a88"), [])
      and not render.recycle_due(next(r for r in r1.rows if r["gid"] == "a84"), []) and not render.recycle_due(next(r for r in r1.rows if r["gid"] == "a89"), ["a86"])
      and "_rmod.recycle_due(" in open(os.path.join(STACK, "stackshot/web/server.py"), encoding="utf-8").read() and "_rmod.held_only_for_recycle(" in open(os.path.join(STACK, "stackshot/web/server.py"), encoding="utf-8").read())
check("recycle: the line is out of Need your call (agents) and sits under the Machines heading, above the machine matrix",
      '<p id="recycle"' not in w1 and "Pane recycle" not in w1 and 0 < x1.find("</h2>") < x1.find('<p id="recycle"') < x1.find('<div class="matrix"'), (w1[:600], x1[:600]))
check("recycle: no ask or call styling: no warning box, no icon, no call colour",
      'class="rnote"' not in x1[x1.find('<p id="recycle"'):x1.find("</p>", x1.find('<p id="recycle"'))] and "r-ico" not in x1[x1.find('<p id="recycle"'):x1.find("</p>", x1.find('<p id="recycle"'))]
      and ".mnote{" in h1 and "var(--mut)" in h1[h1.find(".mnote{"):h1.find("}", h1.find(".mnote{"))]
      and not any(t in h1[h1.find(".mnote{"):h1.find("}", h1.find(".mnote{"))] for t in ("var(--warn)", "var(--call)", "border")))
_mc = lambda m: m[m.find("## Your move"):m.find("## ", m.find("## Your move") + 3)]
check("recycle: board.md says it under the Machines table, with the items' anchors, and not under Your move",
      "\n\nPane recycle pending for [a82](#task-a-82), [a88](#task-a-88), [a81](#task-a-81), [a83](#task-a-83) (sala runs it)\n\n" in m1 and m1.count("Pane recycle") == 1
      and m1.find("## Machines") < m1.find("Pane recycle pending") < m1.find("Shared by every Claude session") and "Pane recycle" not in _mc(m1) and "Recycle needed" not in m1,
      m1[m1.find("## Machines"):][:600])
_rl = lambda r, g: (lambda h: (lambda i: h[i:h.find("</li>", i)])(max(h.find(f'<li class="irow hrow" id="task-a-{g}" data-st='), h.find(f'<li class="irow" id="task-a-{g}">'))))(r.routing_html("projects/beta"))      # the item rows (a completed one is a line) live on the project page
_RB = '<span class="badge recycle">waits for recycle</span>'
check("recycle: the badge on the items' lines on the project page, a held one's too; never on a completed one or one without the field",
      all(_RB in _rl(r1, g) for g in ("81", "82", "83", "84")) and not any(_RB in _rl(r1, g) for g in ("85", "86", "87")) and _rl(r1, "85"), [_rl(r1, g)[-260:] for g in ("84", "85")])
check("recycle: the badge on the item page", _RB in r1.item_html("a82") and _RB in r1.item_html("a84") and _RB not in r1.item_html("a85") and _RB not in r1.item_html("a86"))
check("recycle: the badge reads in both themes from the tokens", re.search(r"\.badge\.recycle[^{}]*\{--bc:var\(--warn\)\}", h1), re.findall(r"[^}]*badge\.recycle[^}]*\}", h1))
_fw = lambda h: dict(p.split("=") for p in _bm(h).split())["your-move"]
_fm = lambda h: dict(p.split("=") for p in _bm(h).split())["machines"]
check("recycle: the machines block's fingerprint covers the line, the Your move block's does not move, and the shell does not change, so it comes and goes in place",
      _fm(h0) != _fm(h1) and _fw(h0) == _fw(h1) and _sh(h0) == _sh(h1) and [p.split("=")[0] for p in _bm(h0).split()] == [p.split("=")[0] for p in _bm(h1).split()], (_bm(h0), _bm(h1)))
ritem(81, 5 * H_, None, needs="decision"); ritem(82, 9 * H_, None); ritem(83, 2 * H_, None); ritem(88, 6 * H_, None, hold=True, wake="2099-01-02")   # left with the field: items held for more
r2 = _rb(); h2 = r2.html()
check("recycle: only items held for a wake or an after as well (or completed) with the field → no status line, no board.md line; their lines keep the badge",
      '<p id="recycle"' not in h2 and "Pane recycle" not in r2.markdown() and _fm(h2) == _fm(h0) and _RB in _rl(r2, "84"), _ms(h2)[:600])
ritem(83, 2 * H_, True)
check("recycle: one item → 'Pane recycle pending for a83 (sala runs it)'", f'Pane recycle pending for {_ra("a83")} (sala runs it)</p>' in _rb().html()
      and "Pane recycle pending for [a83](#task-a-83) (sala runs it)\n" in _rb().markdown())
render._cfg.CFG["fleet"]["tool_name"] = ""
check("recycle: with no [fleet] tool_name the line names no tool", f'Pane recycle pending for {_ra("a83")} (the fleet tool runs it)</p>' in _rb().html()
      and "Pane recycle pending for [a83](#task-a-83) (the fleet tool runs it)\n" in _rb().markdown() and "sala" not in _rb().markdown().split("Pane recycle pending")[1].split("\n")[0])
render._cfg.CFG["fleet"]["tool_name"] = "sala"

# the provision line, from the boxes whose puller is behind; shown at once, "(offline)" after a box that is off
_pl = ui_render.provision_lag
try:
    ui_render.provision_lag = lambda now: [("box-c", True), ("box-e", False)]
    rp = _rb(); hp_ = rp.html(); wp = _ws(hp_); mp = rp.markdown()
    check("provision: one line in the status block, naming the boxes, (offline) after the one that is off; the audit line is not in that block (it is in the panel)",
          hp_.count('<p id="provision"') == 1 and '⟳</span> Provision needed for <b class="r-host">box-c</b>, <b class="r-host">box-e</b> <span class="r-off">(offline)</span></p>' in wp
          and 0 <= wp.find('<p id="provision"') and 'id="audit"' not in wp and 0 < hp_.find('<div id="audit"') and '<p id="recycle"' not in wp, wp[:900])
    check("provision: board.md says it at the top of Your move; the recycle line stays under Machines",
          "## Your move\n\nProvision needed for box-c, box-e (offline)\n\n" in mp and "Pane recycle" not in _mc(mp) and "Pane recycle pending for [a83](#task-a-83)" in mp,
          mp[mp.find("## Your move"):][:300])
    ui_render.provision_lag = lambda now: []
    rq = _rb(); check("provision: no box behind → no line, on the page or in board.md", '<p id="provision"' not in rq.html() and "Provision needed" not in rq.markdown())
finally:
    ui_render.provision_lag = _pl
check("provision: with no client state to read, the board draws no line and does not fail", isinstance(ui_render.provision_lag(datetime.datetime.now(render._cfg.tz())), list))

# inline mentions: a real item id and a session with a link become links in free text on the
# HTML pages; an id-shaped token that is no item, a session without a link, a machine, a link, code and markup stay as they are
(RS / "a/88.json").write_text(json.dumps({"id": "88", "subject": "[home] mentions a81 and a88", "status": "open", "updated": qnow.timestamp(),
    "description": "Blocked on a81, not a99 nor xa81 nor a81-b nor a81.5. work-osprey-main and work-osprey-x wait; work-osprey owns it on testbox. "
                   "Kept: `a82 and work-osprey`, [see a83](https://example.invalid/a83), https://example.invalid/work-osprey. Not markup: <b>a84</b>.",
    "metadata": {"owner": B, "project": "projects/beta", "next": "ask work-osprey about a85; then close a88", "ask": "is a86 still needed?", "needs": ["decision"]}}))
mb = _rb()
sala_on()                                                                               # the keeper has a live pane; work-osprey-main and -x have none
mb.sess["name:work-osprey-main"]["gone"] = mb.sess["name:work-osprey-x"]["gone"] = GONE
mb.sess["name:testbox"] = {"id": "z", "kind": "pane", "name": "testbox", "url": "", "machine": "a"}   # a live session named like the machine
_ia = lambda g: f'<a href="/items/{g}" target="_blank" rel="noopener" title="[home] recycle item {g[1:]}">{g}</a>'
_sa = _sl("work-osprey")
mp_ = mb.item_html("a88"); md_ = mp_[mp_.find('<div class="desc md">'):mp_.find("</div>", mp_.find('<div class="desc md">'))]
check("mentions: a real item id in a description links to its item page in a new tab, its subject as the tooltip", f"Blocked on {_ia('a81')}, not" in md_, md_)
check("mentions: an id-shaped token that is no item, or sits inside a longer word, stays text",
      "not a99 nor xa81 nor a81-b nor a81.5." in md_ and "/items/a99" not in mp_, md_)
check("mentions: a session with a live pane is linked to sala, one without stays text, a shorter name is not found inside a longer one",
      f"; {_sa} owns it" in md_ and "work-osprey-main and work-osprey-x wait" in md_ and md_.count('#s=work-osprey"') == 1, md_)
check("mentions: a machine name is never a session, even when a session carries it", "on testbox." in md_ and "#s=testbox" not in mp_, md_)
check("mentions: nothing inside backticks, an existing link or its href is touched",
      "<code>a82 and work-osprey</code>" in md_ and '<a href="https://example.invalid/a83" target="_blank" rel="noopener">see a83 ↗</a>' in md_
      and '<a href="https://example.invalid/work-osprey" target="_blank" rel="noopener">example.invalid ↗</a>' in md_, md_)
check("mentions: the text is still escaped (an injected tag stays text, the id beside it linked)", f"&lt;b&gt;{_ia('a84')}&lt;/b&gt;" in md_ and "<b>a84" not in md_, md_)
check("mentions: next and the ask link too; the item's own id stays plain on its page",
      f"ask {_sa} about {_ia('a85')}" in mp_ and "then close a88" in mp_ and f"is {_ia('a86')} still needed?" in mp_ and "/items/a88" not in mp_, mp_[mp_.find("<h2>Next"):mp_.find("<h2>Description")])
check("mentions: the subject in the page title links another item, never its own id", f'<span class="hid">a88</span> mentions {_ia("a81")} and a88</h1>' in mp_ and "<title>a88 · mentions a81 and a88</title>" in mp_, mp_[:900])
check("mentions: on raw HTML, code and existing links are left whole and an entity is no id",
      mb.mentions('<code>a81 work-osprey</code> <a href="/x">a81</a> it&#x27;s a81') == f'<code>a81 work-osprey</code> <a href="/x">a81</a> it&#x27;s {_ia("a81")}')
check("mentions: the regex is built once per Board", mb._mention_rx() is mb._mention_rx())
check("mentions: board.md is untouched (markdown keeps its own links)", "a81" in mb.markdown() and "/items/" not in mb.markdown() and "sala.example.org" not in mb.markdown())
# the helper itself (sess_html): a name is url-quoted in the link and escaped in the text; a cloud session, an unknown name and
# a gone one stay text; with session_view unset nothing links
mb.sess["name:we ird&<x>'\""] = {"id": "w", "kind": "pane", "name": "we ird&<x>'\"", "url": "", "machine": "a"}
check("sala link: a name needing quoting and escaping", mb.sess_href("we ird&<x>'\"") == "https://sala.example.org/#s=we%20ird%26%3Cx%3E%27%22"
      and mb.sess_html("we ird&<x>'\"") == '<a href="https://sala.example.org/#s=we%20ird%26%3Cx%3E%27%22" target="_blank" rel="noopener" title="open this session in sala">we ird&amp;&lt;x&gt;&#x27;&quot;</a>',
      mb.sess_html("we ird&<x>'\""))
mb.sess["name:cloudy"] = {"id": "cse_01Q", "kind": "cloud", "name": "cloudy", "url": "https://claude.ai/code/session_01Q", "machine": "c"}
check("sala link: a cloud session, an unknown name and a gone one stay plain (escaped) text, a class kept on a span",
      mb.sess_html("cloudy") == "cloudy" and mb.sess_html("no-such<s>") == "no-such&lt;s&gt;" and mb.sess_html("work-osprey-main", label="a/work-osprey-main", cls="iown") == '<span class="iown">a/work-osprey-main</span>')
render._cfg.CFG["fleet"]["tool_name"] = ""
check("sala link: with no [fleet] tool_name the link's title names no tool", "title=\"open this session's view\"" in mb.sess_html("we ird&<x>'\""), mb.sess_html("we ird&<x>'\""))
render._cfg.CFG["fleet"]["tool_name"] = "sala"
sala_on(False)
check("sala link: with [client] session_view unset no name links", mb.sess_href("work-osprey") == "" and mb.sess_html("work-osprey") == "work-osprey")

# ---- the writer owes the page update; the keeper gets it only past the grace ([pilot] writer_owes_page)
from stackshot.projects import pages as _pg
_ct0, _pts0 = _pg.ct_changed_since, server._pdebts._page_ts
server._pdebts._page_ts = lambda key: 0.0; _pg.ct_changed_since = lambda key, ts: False      # no page written yet
server._owed_save({}); server._cfg.CFG["pilot"]["writer_owes_page"] = True
(T / "store/a/40.json").write_text(json.dumps({"id": "40", "subject": "[home] item 40", "description": "A thing. It lives here. Done when done.", "status": "open", "metadata": {"owner": A, "project": "projects/alpha"}, "updated": 1.0}))
n0 = len(wait_push(0))
res = server._update("a1", next="call the vendor again", sender="work-osprey-main"); time.sleep(0.5)
e = server._owed_load().get("projects/alpha", {})
check("a next-only write is the writer's, any page write settles it", list(e) == [A] and e[A].get("settle") == "any" and e[A].get("moves") == S, e)
check("the keeper is not told at once", len(wait_push(0)) == n0, wait_push(0)[n0:])
check("the writer's reply says the update is its own, and the fallback",
      "the page update is yours in this turn: projects/alpha, any page write" in res and "after 30 min, it moves to the router, which passes the page update to the agent that keeps the page" in res and "charged to the keeper" not in res, res)
res = server._update("a1", description="- Goal: A thing, now with a vendor\n- It lives here\n- Done when done", sender="work-osprey-main")
e = server._owed_load()["projects/alpha"][A]; check("a state change asks for the Current state", e.get("settle") == "ct" and "its Current state" in res, (e, res))
server._update("a1", next="and then the next step", sender="work-osprey-main")
check("a later next-only write never loosens it", server._owed_load()["projects/alpha"][A].get("settle") == "ct", server._owed_load())
res = server._update("a1", next="a step by someone else", sender="work-osprey-x")
check("each writer owes its own", sorted(server._owed_load()["projects/alpha"]) == sorted([A, X]) and server._owed_load()["projects/alpha"][X]["settle"] == "any")
d = server._owed_load(); d["projects/alpha"][A]["ts"] -= 3600; server._owed_save(d)
try: server._refuse_if_owing(A); ok = True
except ToolError: ok = False
check("the writer is never refused for a pilot debt", ok)
check("the nag says it moves instead", "Still missing after 30 min, it moves to the router" in server._nag(A) and "refuses your next board write" not in server._nag(A), server._nag(A))
d = server._owed_load(); d["projects/alpha"][A]["ts"] += 3600; server._owed_save(d)
server._pdebts._page_ts = lambda key: time.time() + 5           # a timeline line: the page is newer, its Current state is not
o = server._owed_settle().get("projects/alpha", {})
check("a timeline line settles the next-only debt, not the state change", list(o) == [A], o)
_pg.ct_changed_since = lambda key, ts: True
check("a Current-state edit settles it", "projects/alpha" not in server._owed_settle(), server._owed_load())
server._pdebts._page_ts = lambda key: 0.0; _pg.ct_changed_since = lambda key, ts: False
# the fallback: still missing past the grace → the keeper's, with today's notice saying who left it
server._update("a1", next="one more step", sender="work-osprey-main")
check("inside the grace nothing moves", server._pilot_fallback_tick() == 0)
d = server._owed_load(); d["projects/alpha"][A]["ts"] -= 31 * 60; server._owed_save(d); n0 = len(wait_push(0))
check("past the grace it moves", server._pilot_fallback_tick() == 1)
e = server._owed_load().get("projects/alpha", {}); p = wait_push(n0 + 1)
check("re-marked to the keeper, dropped from the writer", list(e) == [S] and "moves" not in e[S] and e[S].get("settle") == "any", e)
check("the keeper gets the board notice, saying who left it undone",
      len(p) == n0 + 1 and p[-1][0] == S and re.match(r"\[board\] a1 changed \(next\) by work-osprey-main — \[home\] item 1 \(projects/alpha\) → https://stackshot\.example\.com/items/a1 — work-osprey-main left its page update undone past 30 min, so it is yours as its keeper · notice [0-9a-f]{6}$", p[-1][1]), p[-1:])
check("and the routing log has the line, linked to the item page, never the card's store-id anchor",
      sum(1 for x in routing.read("projects/alpha") if x["kind"] == "board" and x.get("label") == "board a1" and x.get("url") == "https://stackshot.example.com/items/a1") >= 2
      and not any("#task-" in str(x.get("url")) for x in routing.read("projects/alpha")))
check("nothing moves twice", server._pilot_fallback_tick() == 0)
# the turn rule: the debts that move to one keeper in the same tick go in one message, each with its
# own notice; a debt still moves at the first tick past the grace (the keeper's condition: a digest never holds one past 30 min)
server._owed_save({}); t5 = time.time()
server._owed_save({"projects/alpha": {A: {"ts": t5 - 31 * 60, "item": "a1", "settle": "any", "moves": S, "what": "changed (next)"},
                                      X: {"ts": t5 - 30 * 60 - 1, "item": "a40", "settle": "ct", "moves": S, "what": "changed (description)"}},
                   "projects/alpha/sub": {A: {"ts": t5 - 29 * 60, "item": "a2", "settle": "any", "moves": S, "what": "changed (next)"}},
                   "projects/beta": {X: {"ts": t5 - 40 * 60, "item": "a3", "settle": "any", "moves": B, "what": "changed (next)"}}})
n0 = len(wait_push(0))
k = server._pilot_fallback_tick(now=t5); p = wait_push(n0 + 2); new = p[n0:]
mS = [m[1] for m in new if m[0] == S]; mB = [m[1] for m in new if m[0] == B]
check("debt digest: three debts past the grace move in one tick; the keeper gets its two in one message, the other keeper its own",
      k == 3 and len(new) == 2 and len(mS) == 1 and len(mB) == 1, new)
check("debt digest: the message counts them and lists each with its item, writer, link and notice id",
      mS and mS[0].startswith("[board] 2 page updates are yours as its keeper: their writers left them undone past 30 min.\n")
      and re.search(r"^- a1 changed \(next\) by work-osprey-main — \[home\] item 1 \(projects/alpha\) → https://stackshot\.example\.com/items/a1 · notice [0-9a-f]{6}$", mS[0], re.M)
      and re.search(r"^- a40 changed \(description\) by work-osprey-x — \[home\] item 40 \(projects/alpha\) → https://stackshot\.example\.com/items/a40 · notice [0-9a-f]{6}$", mS[0], re.M), mS)
check("debt digest: the one at 30 min was not held for a later digest: moved in this tick, the writer's dropped, the keeper's marked",
      X not in server._owed_load().get("projects/alpha", {}) and S in server._owed_load().get("projects/alpha", {}), server._owed_load())
check("debt digest: one alone keeps its old text", mB and re.match(r"\[board\] a3 changed \(next\) by work-osprey-x — .* — work-osprey-x left its page update undone past 30 min, so it is yours as its keeper · notice [0-9a-f]{6}$", mB[0]), mB)
check("debt digest: the one inside the grace stays with its writer, and holds nothing back", A in server._owed_load().get("projects/alpha/sub", {}), server._owed_load())
rd5 = [n for n in routing.read("projects/alpha") if mS and n["id"] in re.findall(r"notice ([0-9a-f]{6})", mS[0])]
check("debt digest: each debt has its own routing-log line, the two sharing one batch id; the audit counts the message once",
      len(rd5) == 2 and rd5[0].get("batch") and rd5[0].get("batch") == rd5[1].get("batch") and _turns(rd5) == 1, rd5)
rb5 = [n for n in routing.read("projects/beta") if mB and n["id"] in re.findall(r"notice ([0-9a-f]{6})", mB[0])]
check("debt digest: the other keeper's notice, sent alone, carries no batch id", len(rb5) == 1 and "batch" not in rb5[0] and _turns(rd5 + rb5) == 2, rb5)
n0 = len(wait_push(0))
k = server._pilot_fallback_tick(now=t5 + 61); p = wait_push(n0 + 1)
check("debt digest: …and at its own first tick past 30 min it moves, alone, in its old text",
      k == 1 and len(p) == n0 + 1 and p[-1][0] == S and p[-1][1].startswith("[board] a2 changed (next) by work-osprey-main") and "so it is yours as its keeper · notice" in p[-1][1]
      and A not in server._owed_load().get("projects/alpha/sub", {}), p[n0:])
server._owed_save({})
# a close: the writer owes it; the keeper is told only when anchors are scoped to the item
server._owed_save({}); n0 = len(wait_push(0))
res = server._update("a1", status="completed", sender="work-osprey-main", outcome="done", reason="the vendor called back", description="- Goal: The vendor is signed and the thing is in use")
p = wait_push(n0 + 1); e = server._owed_load().get("projects/alpha", {})
check("closing an item with scoped anchors: the writer owes Current state", list(e) == [A] and e[A]["settle"] == "ct", e)
check("and the keeper is told for the anchors, owing nothing",
      len(p) == n0 + 1 and p[-1][0] == S and "a1 completed (done) by work-osprey-main" in p[-1][1] and "no page update is owed by you (work-osprey-main writes it); this notice is for the anchors scoped to a1" in p[-1][1], p[-1:])
n0 = len(wait_push(0))
server._update("a40", status="completed", sender="work-osprey-main", outcome="dropped", reason="no longer needed", description="- Goal: Nothing more is needed here"); time.sleep(0.5)
check("a close without anchors tells nobody", len(wait_push(0)) == n0, wait_push(0)[n0:])
res = server._update("a4", next="the kept page's item, switch on", sender="work-osprey-main")
check("a sub-page an agent keeps still charges that agent", "charged to the agent work-osprey-x" in res and X in server._owed_load().get("projects/alpha/kept", {}), res)
res = server._create(subject="[home] a new thing", description="- Goal: A new thing\n- It lives here\n- Done when done", project="projects/alpha", owner="work-osprey-main")
gid_new = re.search(r"created ([a-z]\d+)", res).group(1); time.sleep(0.3)
check("a create by an agent is its own debt, Current state", server._owed_load()["projects/alpha"][A].get("item") == gid_new and server._owed_load()["projects/alpha"][A]["settle"] == "ct" and "its Current state" in res, res)
res = server._update(gid_new, next="the keeper's own step", sender="work-osprey")
check("the keeper's own write is its own, as before", S in server._owed_load()["projects/alpha"] and "moves" not in server._owed_load()["projects/alpha"][S] and "page update is yours in this turn" not in res, res)
server._cfg.CFG["pilot"]["writer_owes_page"] = False; server._owed_save({}); n0 = len(wait_push(0))
res = server._update(gid_new, next="switch off again", sender="work-osprey-main"); p = wait_push(n0 + 1)
check("off: today's behaviour (the keeper charged and told at once)", "charged to the keeper work-osprey" in res and list(server._owed_load()["projects/alpha"]) == [S] and len(p) == n0 + 1 and p[-1][0] == S, res)
server._pdebts._page_ts, _pg.ct_changed_since = _pts0, _ct0
# ---- the pane gate follows [pilot] writer_owes_page, and settles as the server does
from stackshot.projects import pages as _pg2
_pg2._cfg.CFG["pilot"]["writer_owes_page"] = True
_pts, _ct = _pg2.page_ts, _pg2.ct_changed_since
for sid in (A, X): _pg2.save_state(sid, {})
up = lambda sid, inp, tool="update": _pg2.touch_mcp({"session_id": sid, "tool_name": "mcp__claude_ai_Stackshot__" + tool, "tool_input": inp, "tool_response": "updated a1.\nproject: projects/alpha"})
up(A, {"item_id": "a1", "next": "a step"})
t = _pg2.load_state(A).get("touches", {}).get("projects/alpha") or {}
check("pane: switch on, a pilot agent's next-only write is its own debt, any page write settles it", t.get("settle") == "any", _pg2.load_state(A))
up(A, {"item_id": "a1", "description": "- Goal: A changed thing\n- It lives here"})
check("pane: a state change asks for the Current state", _pg2.load_state(A)["touches"]["projects/alpha"].get("settle") == "ct", _pg2.load_state(A))
up(A, {"item_id": "a1", "next": "later"})
check("pane: a later next-only write never loosens it", _pg2.load_state(A)["touches"]["projects/alpha"].get("settle") == "ct")
up(X, {"item_id": "a1", "hold": True})
check("pane: a hold counts, settled by any page write", (_pg2.load_state(X).get("touches", {}).get("projects/alpha") or {}).get("settle") == "any", _pg2.load_state(X))
up(X, {"item_id": "a1", "priority": "p2"}); check("pane: a filing edit still owes nothing", _pg2.load_state(X)["touches"]["projects/alpha"].get("settle") == "any")
_pg2.page_ts = lambda key: int(time.time()) + 5; _pg2.ct_changed_since = lambda key, ts: False      # a timeline line
check("pane: a timeline line settles the next-only debt", _pg2.stale_touches(X, strict=True) == [] and "projects/alpha" not in _pg2.load_state(X).get("touches", {}))
check("pane: but not the state change, even for a session outside the currency", [k for k, _ in _pg2.stale_touches(A, strict=False)] == ["projects/alpha"])
check("pane: and says so", "has no Current-state edit since" in _pg2.describe("projects/alpha", _pg2.load_state(A)["touches"]["projects/alpha"], strict=False))
_pg2.ct_changed_since = lambda key, ts: True
check("pane: a Current-state edit settles it", _pg2.stale_touches(A, strict=False) == [])
_pg2.page_ts, _pg2.ct_changed_since = _pts, _ct
_pg2._cfg.CFG["pilot"]["writer_owes_page"] = False; _pg2.save_state(A, {})
up(A, {"item_id": "a1", "next": "switch off"}); check("pane: switch off, a pilot agent's pane owes nothing (today)", not _pg2.load_state(A).get("touches"), _pg2.load_state(A))
up(A, {"item_id": "a1", "hold": True}); check("pane: switch off, a hold alone is filing, as today", not _pg2.load_state(A).get("touches"))

# ---- every drop the server makes names its sender
# ---- a front agent takes a peer's message only with the mark on its first line; the keeper and a background agent as before
_reg_a = (T / "store/projects.json").read_text(); _rg = json.loads(_reg_a)
_rg["pages"]["projects/alpha"].update(agents={"work-osprey-main": "talks", "work-osprey-x": "sweeps"}, back_agents={"work-osprey-x": "sweeps"})
(T / "store/projects.json").write_text(json.dumps(_rg))
def why(fn):
    try: fn(); return ""
    except ToolError as e: return str(e)
n0 = len(wait_push(0)); MK = server._FOR_OWNER
r = why(lambda: server._message("work-osprey-main", "can you look at the vendor thread?", "home-beta"))
check("an unmarked message to a front agent is refused, naming the mark and the project, where the router rules it",
      r == f"Refused: work-osprey-main is a front agent of projects/alpha, a session {server.OWNER} talks to, and it takes a message only when the message's first line "
           f"carries {MK}. Put {MK} on the first line if this is for {server.OWNER}; anything else goes to the project, where the router rules it (to='projects/alpha') instead.", r)
check("…by its transcript id too, and nothing was delivered", why(lambda: server._message(A, "unmarked", "home-beta")).startswith("Refused: work-osprey-main is a front agent")
      and len(wait_push(0)) == n0)
check("…and the mark below the first line does not count", why(lambda: server._message("work-osprey-main", f"a status line\n{MK} decide this", "home-beta")).startswith("Refused:"))
check("…nor does a script's message get past it", why(lambda: server._message("work-osprey-main", "run finished", "nightly-job", origin="testbox")).startswith("Refused:"))
res = server._message("work-osprey-main", f"\n  \n{MK} vendor A or B? the keeper recommends A", "home-beta"); pp = wait_push(n0 + 1)
check("a marked message (first non-empty line) to a front agent is delivered", res.startswith("delivered") and pp[-1][0] == "work-osprey-main" and MK in pp[-1][1], pp[-1:])
res = server._message("work-osprey-x", "sweep the inbox", "home-beta"); pp = wait_push(n0 + 2)
check("a message to a background agent is unaffected", res.startswith("delivered") and pp[-1][0] == "work-osprey-x", pp[-1:])
res = server._message("work-osprey", "a plain line for the keeper", "home-beta"); pp = wait_push(n0 + 3)
check("a message to the keeper by name is unaffected", res.startswith("delivered") and pp[-1][0] == "work-osprey", pp[-1:])
res = server._message("projects/alpha", "a plain line for the project", "home-beta"); pp = wait_push(n0 + 3)
check("a message to the project page is held for the router, unaffected: nobody is messaged", res.startswith("held for the router") and len(pp) == n0 + 3, (res, pp[-1:]))
# a marked message that says nothing is needed from him is refused too, and sent to the keeper
n0 = len(wait_push(0)); NOT = server._NOT_FOR_OWNER
check("gate: the phrase list is short and fixed", NOT == (f"nothing needed from {server.OWNER}", f"nothing for {server.OWNER}", "no action needed", f"no action for {server.OWNER}",
                                                       "no decision needed", "nothing to decide", "FYI", "for your information", "for the record", "no reply needed"), NOT)
for ph in NOT:
    r = why(lambda: server._message("work-osprey-main", f"{MK} the build is live. {ph}, the rest is on the page.", "home-beta"))
    check(f"gate: a marked message to a front agent that says {ph!r} is refused, naming the phrase and the project",
          r.startswith(f"Refused: work-osprey-main is a front agent of projects/alpha, a session {server.OWNER} talks to, and {MK} marks only what {server.OWNER} has to do; "
                       f"this message says nothing is needed from him ({ph!r}). A hand-back, a result or an FYI goes to the project, where the router rules it (to='projects/alpha') instead"), r)
r = why(lambda: server._message(A, f"{MK} the release\nis live: NO ACTION NEEDED.", "home-beta"))
check("gate: …without regard to case, on a later line, and by its transcript id", r.startswith("Refused: work-osprey-main is a front agent") and "('NO ACTION NEEDED')" in r, r)
check("gate: nothing was delivered by the refusals", len(wait_push(0)) == n0)
res = server._message("work-osprey-main", f"{MK} Decide: is the satisfying option A or B? · Recommend: A · Stakes: a month · By: Fri", "home-beta"); pp = wait_push(n0 + 1)
check("gate: a marked message with something to decide is delivered (a phrase inside a word does not count)", res.startswith("delivered") and pp[-1][0] == "work-osprey-main", (res, pp[-1:]))
res = server._message("work-osprey-x", "the build is live, no action needed", "home-beta"); pp = wait_push(n0 + 2)
check("gate: the same words to a background agent are delivered", res.startswith("delivered") and pp[-1][0] == "work-osprey-x", pp[-1:])
res = server._message("work-osprey", f"{MK} FYI the build is live, nothing for {server.OWNER}", "home-beta"); pp = wait_push(n0 + 3)
check("gate: …and to the keeper, marked or not", res.startswith("delivered") and pp[-1][0] == "work-osprey", pp[-1:])
(T / "store/projects.json").write_text(_reg_a)

# ---- observers hear only a close or a reopen (a front agent through its keeper); after = the items that must close first; the migration
_reg_b = (T / "store/projects.json").read_text(); _rgo = json.loads(_reg_b)
_rgo["pages"]["projects/alpha"].update(agents={"work-osprey-main": "front", "work-osprey-x": "back", "work-osprey-bld": "builds and releases the code"}, back_agents={"work-osprey-x": "back", "work-osprey-bld": "builds and releases the code"})
(T / "store/projects.json").write_text(json.dumps(_rgo))
mk2 = lambda **kw: gid_of(server.stackshot_create(**{"subject": "[home] after test", "description": "- Goal: A thing\n- It lives here\n- Done when done", "project": "beta", "owner": "home-beta", "next": "home-beta: carry on", **kw}))
o1 = mk2(observers=["work-osprey-x", "work-osprey-main"]); xs = ("work-osprey-x", X)
check("observers: stored as given; get shows them", rd(o1)["metadata"].get("observers") == ["work-osprey-x", "work-osprey-main"] and "\nobservers: work-osprey-x, work-osprey-main\n" in server.stackshot_get(o1), server.stackshot_get(o1))
e = refusal(lambda: mk2(observers=["nobody-at-all"])); check("observers: an unknown session is refused", e.startswith("Refused: observer 'nobody-at-all' names no session"), e)
n0 = len(wait_push(0)); server._update(o1, next="a step", sender="home-beta"); time.sleep(0.4)
check("observers: an ordinary edit tells them nothing", not [m for m in wait_push(0)[n0:] if m[0] in xs or m[0] == S], wait_push(0)[n0:])
from stackshot.waits import held; held.mark_client(X, "work-osprey-x")      # the rollout gate: its hook fetches held lines
n0 = len(wait_push(0)); res = server.stackshot_complete(o1, sender="home-beta", outcome="done", reason="landed", description="- Goal: Done"); p = wait_push(n0 + 2)
ox = [m for m in p[n0:] if m[0] in xs]; os_ = [m for m in p[n0:] if m[0] == "work-osprey-bld"]
from stackshot.waits import held
hx = held.take(X, "work-osprey-x")
check("observers: a close is held for a background observer (it asks nothing, so it starts no turn) and reaches a front observer through its own project's keeper; the reply names them", len(ox) == 0 and f"{o1} was completed (done: landed) by home-beta" in hx and "(you observe it)" in hx and " · closed · " in hx
      and len(os_) == 1 and os_[0][1].startswith(f"[stackshot] {o1} (observer work-osprey-main, a front agent) was completed (done: landed) by home-beta") and not [m for m in p[n0:] if m[0] == A]
      and "(observers told: work-osprey-x, work-osprey-bld for work-osprey-main)" in res, (p[n0:], res))
n0 = len(wait_push(0)); server._update(o1, status="open", next="again", sender="home-beta"); p = wait_push(n0 + 2)
check("observers: a reopen too", any(m[0] in xs and "reopened" in m[1] for m in p[n0:]) and any(m[0] == "work-osprey-bld" and "reopened" in m[1] for m in p[n0:]), p[n0:])
server._update(o1, observers="none", sender="home-beta"); check("observers: observers=\"none\" clears", "observers" not in rd(o1)["metadata"])
# after
a1_, a2_, a3_, a4_ = mk2(), mk2(), mk2(), mk2()
res = server._update(a1_, after=[a2_, a3_], sender="home-beta")
check("after: stored; get shows each with its state", rd(a1_)["metadata"].get("after") == [a2_, a3_] and f"\nafter: {a2_} (open), {a3_} (open)\n" in res, res)
bA = ui_render.Board(str(T / "store")); rA = bA.item(a1_)
check("after: the item is parked (out of the queue, a wait on the item) without a hold; the tooltip and board.md say 'after …', and the brief counts it waiting", a1_ in [r["gid"] for r in bA.held] and a1_ not in [r["gid"] for r in bA.agent + bA.n_call]
      and not render.is_held(rA) and render.is_parked(rA) and bA.hold_tip(rA) == f"after {a2_}, {a3_} · until it closes" and f"**{a1_} · [home] after test** (after {a2_}, {a3_})" in bA.markdown()
      and f"- after: [{a2_}](#task-{a2_[0]}-{a2_[1:]}), [{a3_}](#task-{a3_[0]}-{a3_[1:]})" in bA.markdown() and a1_ in [r["gid"] for r, _m in bA.home_pairs()["waiting"]] and "after another item" not in bA.brief().splitlines()[0], (bA.hold_tip(rA), bA.brief().splitlines()[0]))
_ap = "".join(bA.routing_html(k) for k in bA.proj); _ar = _ap[_ap.find(f'<li class="irow hrow" id="task-{a1_[0]}-{a1_[1:]}" data-st="wait">'):][:1400]
check("after: the project page's Waiting row says what it waits for (after the two items), and the item page's prop",
      f'data-fold="project.items.waiting"' in _ap and f'<span class="hwait">After <a href="/items/{a2_}"' in _ar and f'/items/{a3_}"' in _ar and f'<dt>After</dt><dd><a href="/items/{a2_}">{a2_}</a> <span class="dim">(open)</span>' in _side(bA.item_html(a1_)), _side(bA.item_html(a1_)))
res = server._update(a1_, hold=True, sender="home-beta"); check("after: a hold with no wake passes while an after is open (the after is what it waits for); both show", held_(a1_) and bA.md_hold(ui_render.Board(str(T / "store")).item(a1_)) == f"on hold, no wake date; after {a2_}, {a3_}", res)
server._update(a1_, clear_hold=True, sender="home-beta")
e = refusal(lambda: server._update(a2_, after=[a1_], sender="home-beta")); check("after: a loop is refused", e.startswith("Refused: a loop:") and "after" not in rd(a2_)["metadata"], e)
e = refusal(lambda: server._update(a1_, after=[a1_], sender="home-beta")); check("after: itself is refused", "cannot wait on itself" in e, e)
e = refusal(lambda: server._update(a1_, after=["a2"], sender="home-beta")); check("after: a closed item is refused, naming its outcome", "is already completed" in e and "after names open items" in e, e)
e = refusal(lambda: server._update(a1_, after=["z999"], sender="home-beta")); check("after: an unknown id is refused", "does not exist" in e, e)
check("after: every idle pass skips it", server._after_open(rd(a1_)["metadata"]) == [a2_, a3_])
n0 = len(wait_push(0)); res = server.stackshot_complete(a2_, sender="home-beta", outcome="dropped", reason="not needed", description="- Goal: Dropped"); time.sleep(0.4)
msgs_ = [m for m in wait_push(0)[n0:] if a1_ in m[1]]
check("after: a dropped prerequisite leaves the list; the item still waits on the other and is not released, and its wait did not fail (one rule: another blocker is open): nothing recorded, nobody told",
      rd(a1_)["metadata"].get("after") == [a3_] and "released" not in res and "wait_failed" not in rd(a1_)["metadata"] and not msgs_, (res, rd(a1_)["metadata"], msgs_))
res = server.stackshot_complete(a3_, sender="home-beta", outcome="superseded", superseded_by=a4_, reason="folded into a4", description="- Goal: Superseded")
check("after: a superseded prerequisite is followed to its replacement", rd(a1_)["metadata"].get("after") == [a4_] and "released" not in res, (res, rd(a1_)["metadata"]))
server._update(a1_, hold=True, wake=D(9), sender="home-beta")
n0 = len(wait_push(0)); res = server.stackshot_complete(a4_, sender="home-beta", outcome="dropped", reason="not needed either", description="- Goal: Dropped"); p = wait_push(n0 + 1)
check("after: the last one closing releases the item, after, hold and wake together; the reply and the owner's line say it was dropped", "after" not in rd(a1_)["metadata"] and not held_(a1_) and "wake" not in rd(a1_)["metadata"]
      and f"({a1_} waited on {a4_} and is released" in res and any(m[0] == B and m[1].startswith(f"[stackshot] {a1_} is yours now: {a4_}, the last item it waited on, was dropped by home-beta") for m in p[n0:]), (res, p[n0:]))
check("after: back in the queue", a1_ in [r["gid"] for r in ui_render.Board(str(T / "store")).agent])
check("after: a done close releases with 'closed (done)'", True)
a5_, a6_ = mk2(), mk2(); n0 = len(wait_push(0)); server._update(a5_, after=[a6_], needs=["work-osprey-x"], sender="home-beta"); wait_push(n0 + 1)   # its "now needs you" line lands before the next count
n0 = len(wait_push(0)); server.stackshot_complete(a6_, sender="home-beta", outcome="done", reason="landed", description="- Goal: Done"); p = wait_push(n0 + 1)
w5 = [m for m in p[n0:] if f" {a5_} woke" in m[1]]
check("after: the release tells the session named in needs, not the owner", len(w5) == 1 and w5[0][0] in xs and f"{a6_}, the last item it waited on, closed (done) by home-beta" in w5[0][1]
      and not [m for m in p[n0:] if m[0] == B], p[n0:])
check("after: create takes it too", rd(mk2(after=[a5_]))["metadata"].get("after") == [a5_])
# the migration: an item stored before (needs a word, the linked agent under agent) reads as a list, and the start step rewrites the open ones once
(T / "store/a/90.json").write_text(json.dumps({"id": "90", "subject": "[home] old 90", "description": "x", "status": "open", "metadata": {"owner": "home-beta", "project": "projects/beta", "needs": "decision", "agent": "home-beta-ops", "ask": ASK}, "updated": 1.0, "state_updated": 1.0}))
(T / "store/a/91.json").write_text(json.dumps({"id": "91", "subject": "[home] old 91", "description": "x", "status": "completed", "metadata": {"owner": "home-beta", "project": "projects/beta", "needs": "external", "agent": "home-beta-ops", "outcome": "done"}, "updated": 1.0, "state_updated": 1.0}))
check("legacy: a one-word needs and an agent read as the list, in memory", server._load("a90")["metadata"].get("needs") == ["decision", "home-beta-ops"] and "agent" not in server._load("a90")["metadata"], server._load("a90")["metadata"])
check("legacy: a closed item's needs reads as a list too; its agent is not carried into it", server._load("a91")["metadata"].get("needs") == ["external"] and "agent" not in server._load("a91")["metadata"], server._load("a91")["metadata"])
check("legacy: render reads both shapes", render.needs_of({"metadata": {"needs": "external"}}) == ["external"] and render.needs_kind({"metadata": {"needs": "external"}}) == "relay"
      and render.needs_kind({"metadata": {"needs": ["home-beta-ops"]}}) == "" and render.needs_kind({"metadata": {"needs": ["home-beta-ops", "decision"]}}) == "call" and render.needs_sessions({"metadata": {"needs": ["decision", "home-beta-ops"]}}) == ["home-beta-ops"])
mig = server._migrate_needs()
check("migration: the start step rewrites the open item, clocks untouched, and leaves the closed one as a record", "a90" in mig and "a91" not in mig and rd("a90")["metadata"].get("needs") == ["decision", "home-beta-ops"] and "agent" not in rd("a90")["metadata"] and rd("a90")["updated"] == 1.0
      and rd("a91")["metadata"].get("needs") == "external" and rd("a91")["metadata"].get("agent") == "home-beta-ops", (mig, rd("a90"), rd("a91")))
check("migration: idempotent", server._migrate_needs() == [])
check("migration: get shows the migrated item's needs; the hub's name line not, since a session is named", "\nneeds: decision, home-beta-ops\n" in server.stackshot_get("a90") and "keeper:" not in server.stackshot_get("a90"), server.stackshot_get("a90"))
for i in (90, 91): (T / f"store/a/{i}.json").unlink()
(T / "store/projects.json").write_text(_reg_b)

# ---- the board item: step statuses, what is in motion on an item and what waits
from stackshot.model import work as W; from stackshot.model import steps as _stp; from stackshot.github import ghsync as _ghs
_regw = (T / "store/projects.json").read_text(); _rgw = json.loads(_regw)
_rgw["pages"]["projects/alpha"].update(agents={"work-osprey-main": "front", "work-osprey-x": "back"}, back_agents={"work-osprey-x": "back"})
(T / "store/projects.json").write_text(json.dumps(_rgw))
tags_of = lambda g: [(_stp.opener(x["text"]), x["status"], (x.get("tag") or {}).get("text"), (x.get("tag") or {}).get("state")) for x in rd(g)["metadata"].get("steps") or []]
w1 = mk2(); st0, cf0 = rd(w1)["state_updated"], rd(w1)["confirmed"]; next0 = rd(w1)["metadata"]["next"]
n0 = len(wait_push(0)); owed0 = server._owed_load().get("projects/beta", {}).get(B); time.sleep(0.02)   # the create's own debt, as it stands
res = server._update(w1, work={"text": "migrating the ids"}, sender="home-beta")
check("work: the owner sets the status of its open step: stored on the step (in progress), the step's words and the list unchanged; the reply shows the change",
      tags_of(w1) == [("home-beta", "open", "migrating the ids", "in progress")] and rd(w1)["metadata"]["next"] == next0 and "work" not in rd(w1)["metadata"]
      and "\nstep status: migrating the ids — in progress (home-beta)\n" in res and "\nstatus: migrating the ids \u00b7 in progress (home-beta)" in res, (tags_of(w1), res))
owed1 = server._owed_load().get("projects/beta", {}).get(B)
check("work: a filing edit: no page owed (the ledger's beta entry is the create's or gone), nobody told, the state clock and the confirm untouched, the item's own clock moved",
      (owed1 is None or owed1 == owed0) and "charged" not in res and len(wait_push(0)) == n0
      and rd(w1)["state_updated"] == st0 and rd(w1)["confirmed"] == cf0 and rd(w1)["updated"] > st0, (owed0, owed1, rd(w1)))
check("work: the pane hook counts it as filing only (no touch)", pages.touch_mcp({"tool_name": "mcp__Stackshot__update", "tool_input": {"item_id": w1, "work": {"text": "x"}}, "tool_response": "updated"}) == 0)
e = refusal(lambda: server._update(w1, work={"text": "migrating the ids", "state": "in progress"}, sender="work-osprey-main"))   # a front agent: a background agent's first write names it and passes (auto-name, below)
check("work: a session neither owner nor named in needs is refused, with the way in", e.startswith(f"Refused: the status of a step on {w1} is written by its mover (home-beta) or a session named in its needs (none named); work-osprey-main is neither.")
      and "name you in needs" in e and tags_of(w1)[0][3] == "in progress", e)
server._update(w1, needs=["work-osprey-x"], sender="home-beta"); time.sleep(0.3)
res = server._update(w1, work={"text": "PR 83 up", "state": "in progress"}, sender="work-osprey-x")
check("work: a session named in needs with no open step of its own gets one made from the text, with that status; needs unchanged; the owner's step keeps its status",
      tags_of(w1) == [("home-beta", "open", "migrating the ids", "in progress"), ("work-osprey-x", "open", "PR 83 up", "in progress")] and rd(w1)["metadata"]["needs"] == ["work-osprey-x"]
      and "(step added for work-osprey-x: work-osprey-x: PR 83 up)" in res, (tags_of(w1), res))
res = server._update(w1, work={"text": "review running", "state": "in progress"}, sender="work-osprey-x")
check("work: the next status of that session replaces the one on its step in place: still one step, one status",
      tags_of(w1)[1:] == [("work-osprey-x", "open", "review running", "in progress")] and len(tags_of(w1)) == 2 and "step added" not in res, (tags_of(w1), res))
e = refusal(lambda: server._update(w1, work={"text": "review running", "state": "done"}, sender="work-osprey-main"))
check("work: a stranger is still refused once a session is named", "work-osprey-main is neither" in e and "(work-osprey-x)" in e and tags_of(w1)[1][3] == "in progress", e)
res = server._update(w1, work={"text": "review running", "state": "in progress"}, sender="work-osprey-x")
check("work: a no-op says so, writes no change", "(work: \"review running\" unchanged, already so)" in res, res)
t_before = (rd(w1)["metadata"]["steps"][1].get("tag") or {}).get("ts")
time.sleep(0.05); server._update(w1, work={"text": "review running", "state": "in progress"}, sender="work-osprey-x")
check("work: a status sent again unchanged keeps its old time", (rd(w1)["metadata"]["steps"][1].get("tag") or {}).get("ts") == t_before, t_before)
_m1 = rd(w1)["metadata"]
check("work: the change reads as one line, in History, never a JSON dump", W.changes({**_m1, "steps": [{**x, "tag": None} if i == 1 else x for i, x in enumerate(_m1["steps"])]}, _m1) == ["status: review running \u00b7 in progress (work-osprey-x)"],
      W.changes({**_m1, "steps": [{**x, "tag": None} if i == 1 else x for i, x in enumerate(_m1["steps"])]}, _m1))
check("work: get and the brief carry the one line", "\nstep status: migrating the ids — in progress (home-beta) · review running — in progress (work-osprey-x)\n" in server.stackshot_get(w1)
      and "step status: migrating the ids — in progress (home-beta) · review running — in progress (work-osprey-x)" in server.stackshot_brief(), server.stackshot_get(w1))
# the forms: a plain string is the text, a JSON string too (a client whose cached schema sends text)
server._update(w1, work="tests running", sender="work-osprey-x"); server._update(w1, work='{"text": "docs", "state": "in progress"}', sender="work-osprey-x")
check("work: a plain string and a JSON string are the status text; each replaces the status in place", tags_of(w1)[1:] == [("work-osprey-x", "open", "docs", "in progress")], tags_of(w1))
res = server._update(w1, work={"remove": True}, sender="work-osprey-x")
check("work: remove clears the status of the sender's open step; the step stays", tags_of(w1)[1] == ("work-osprey-x", "open", None, None) and "status: docs cleared" in res, (tags_of(w1), res))
res = server._update(w1, work={"state": "done"}, sender="work-osprey-x")
check("work: state done ticks the sender's step as done=[n] does: the step is done, its status done, the owner's step stays open",
      [(a_, b_, d_) for a_, b_, c_, d_ in tags_of(w1)] == [("home-beta", "open", "in progress"), ("work-osprey-x", "done", "done")] and "(step 2 done: work-osprey-x: PR 83 up)" in res, (tags_of(w1), res))
for bad, want in (({"text": "x" * 41}, "at most 40 characters"), ({"foo": "bar"}, "unknown key foo"), ([{"text": "a"}], "one status line per call"),
                  ({"text": "a", "state": "soon"}, "is not one of defined, assigned, in progress, done")):
    e = refusal(lambda: server._update(w1, work=bad, sender="work-osprey-x")); check(f"work: refused: {want}", e.startswith("Refused: work: ") and want in e, e)
# no open step: a status done is recorded nowhere and says so; a clear says so; a status with text makes the step
w1b = mk2(next="work-osprey-main: someone else's step"); res = server._update(w1b, work={"state": "done"}, sender="home-beta")
check("work: state done with no open step of the sender's: nothing ticked, the reply says so", "(work: not recorded, home-beta has no open step on the item to finish" in res and all(x[1] == "open" for x in tags_of(w1b)), (tags_of(w1b), res))
res = server._update(w1b, work={"remove": True}, sender="home-beta")
check("work: remove with no open step of the sender's: the reply says so", "(work: not recorded, home-beta has no open step on the item, so there is no status to clear)" in res, res)
res = server._update(w1b, work={"text": "starting up"}, sender="home-beta")
check("work: a status with no open step of the sender's makes one open step from the text (smallest choice, not a refusal)",
      tags_of(w1b)[-1] == ("home-beta", "open", "starting up", "in progress") and rd(w1b)["metadata"]["next"].endswith("\nhome-beta: starting up"), (tags_of(w1b), rd(w1b)["metadata"]["next"]))
# a night of writes is one line on the step: 41 statuses in, 1 stored
w1c = mk2()
for i in range(41): server._update(w1c, work={"text": f"stage 11: round {i}"}, sender="home-beta")
check("work: 41 writes on one step leave one step with the last status (the list does not grow)", tags_of(w1c) == [("home-beta", "open", "stage 11: round 40", "in progress")] and rd(w1c)["metadata"]["next"] == "home-beta: carry on", (tags_of(w1c), rd(w1c)["metadata"]["next"]))
# the board: the row shows the statuses in progress with the agent's short name (the project keeper's prefix dropped), "+N" for the rest; the item page shows each on its step
wa = mk2(project="alpha", owner="work-osprey-main"); server._update(wa, needs=["work-osprey-x"], sender="work-osprey-main"); time.sleep(0.3)
server._update(wa, work={"text": "migrating the ids", "state": "in progress"}, sender="work-osprey-x")
bW = ui_render.Board(str(T / "store")); hW = "".join(bW.routing_html(k) for k in bW.proj)      # the item lines live on the project pages
check("work: the words of work in progress are no part of the home page's row, which the project page's lists share: the item has its row, without them",
      f'<li class="irow hrow" id="task-{wa[0]}-{wa[1:]}" data-st="agent">' in hW and '<span class="iwork"' not in hW, re.findall(r'<span class="iwork".*?</span>', hW))
check("work: short names", W.short_agent("ops-falcon-engineer", "ops-falcon") == "engineer" and W.short_agent("ops-plover-master", "ops-falcon") == "ops-plover-master" and W.short_agent("ops-falcon", "ops-falcon") == "ops-falcon")
server._update(wa, work={"text": "answer box", "state": "in progress"}, sender="work-osprey-x")
bW = ui_render.Board(str(T / "store")); hW, mdW, pW = "".join(bW.routing_html(k) for k in bW.proj), bW.markdown(), bW.item_html(wa)
check("work: board.md carries the one line", "- step status: answer box — in progress (work-osprey-x)\n" in mdW and "- step status: migrating the ids — in progress (work-osprey-x)" not in mdW, re.findall(r"- step status: .*", mdW))
check("work: the item page has no Work field in the sidebar; the status is on its step in Next", "<dt>Work" not in pW and '<span class="cl-tag">answer box' in pW, re.findall(r'<span class="cl-tag">.*?</span>', pW))
check("work: an item with no statuses shows no Work section and no row words", "<dt>Work" not in bW.item_html("a1") and 'class="iwork"' not in bW.item_html("a1") and "Agent at work" not in bW.item_html("a1") and 'class="cl-tag"' not in bW.item_html("a1"))
# read-compat: an item that still carries the old `work` list (before the migration) is read as it always was
wl_old = mk2(project="alpha", owner="work-osprey-main", next="work-osprey-main: carry on"); _it_old = rd(wl_old)
_it_old["metadata"]["work"] = [{"id": "migrating", "text": "migrating", "agent": "work-osprey-x", "state": "in progress", "ts": time.time() - 60}, {"id": "docs", "text": "docs", "agent": "", "state": "defined", "ts": time.time() - 30}]
(T / f"store/{wl_old[0]}/{wl_old[1:]}.json").write_text(json.dumps(_it_old))
bO = ui_render.Board(str(T / "store")); pO, mdO = bO.item_html(wl_old), bO.markdown()
check("work: an item that still carries the old list (until the migration has run) shows it in the sidebar and in get, and counts it in progress for the checks",
      '<dt>Work <span class="count">2</span></dt>' in _side(pO) and "\nstep status: migrating — in progress (work-osprey-x) · docs — defined\n" in server.stackshot_get(wl_old) and W.in_progress(rd(wl_old)["metadata"])[0]["agent"] == "work-osprey-x", _side(pO)[:300])
check("work: the update tool's description says it", "work: the status of your open step, one line per call" in server._UPDATE_DESC and "Written by the mover or a session named in needs" in server._UPDATE_DESC)
(T / "store/projects.json").write_text(_regw)
# ---- the board item: the server names the working background agent in needs, at the
# moments it sees: a handover by message, and a write on the item. Only a background agent; never twice; never on a closed item;
# decision stays first; a session already named stays and the owner hears it once, through the owner path
_reg46 = (T / "store/projects.json").read_text(); _rg46 = json.loads(_reg46)
_rg46["pages"]["projects/alpha"].update(agents={"work-osprey-main": "front", "work-osprey-x": "back", "work-osprey-bld": "builds and releases the code", "work-osprey-ops": "back"}, back_agents={"work-osprey-x": "back", "work-osprey-bld": "builds and releases the code", "work-osprey-ops": "back"})
(T / "store/projects.json").write_text(json.dumps(_rg46))
_sj46 = json.loads((T / "fleet/a/sessions.json").read_text()); _sj46["55555555-5555-4555-8555-555555555555"] = {"name": "work-osprey-ops", "machine": "a", "url": "", "seen": "x"}      # a session named in needs below has a pane in the heartbeat (the hand-off guard, handoff suite); the same row is written again further down
(T / "fleet/a/sessions.json").write_text(json.dumps(_sj46))
def mk46(**kw):                      # a create on the pilot project relays to the keeper in the background: let that push land before counting
    g = gid_of(server.stackshot_create(**{"subject": "[home] auto-name test", "description": "- Goal: A thing\n- It lives here\n- Done when done", "project": "projects/alpha", "owner": "work-osprey-main", "mover": kw.get("owner", "work-osprey-main"), "next": "work-osprey-main: carry on", **kw}))
    time.sleep(0.6); return g
needs46 = lambda g: rd(g)["metadata"].get("needs")
# moment 1: a handover by the message tool
h1 = mk46(); n0 = len(wait_push(0))
res = server._message("work-osprey-x", f"please take {h1}: build the thing", "work-osprey-main"); wait_push(n0 + 1); time.sleep(0.4); p = wait_push(0)
check("auto-name: a message to a background agent that names an item names the agent in its needs; the sender's reply says so",
      needs46(h1) == ["work-osprey-x"] and f"(named work-osprey-x in {h1}'s needs: handover message from work-osprey-main)" in res, (needs46(h1), res))
check("auto-name: …the owner handed it over itself, so only the message went out (no owner line, no 'now needs you')", [m[0] for m in p[n0:]] == ["work-osprey-x"] and "now needs you" not in p[n0][1], p[n0:])
res = server._message("work-osprey-x", f"again about {h1}", "work-osprey-main"); time.sleep(0.3)
check("auto-name: never twice", needs46(h1) == ["work-osprey-x"] and "(named" not in res, (needs46(h1), res))
h2, h3 = mk46(), mk46(); n0 = len(wait_push(0))
res = server._message("work-osprey-x", f"two of them: {server._shared.BOARD_URL}/items/{h2} and {h3.upper()}, plus p1 which is no item", "home-beta"); p = wait_push(n0 + 3)
check("auto-name: an item page link and an upper-case id count, an id that names no item is skipped, each item is named",
      needs46(h2) == ["work-osprey-x"] and needs46(h3) == ["work-osprey-x"] and res.count("(named work-osprey-x") == 2, (needs46(h2), needs46(h3), res))
ow = [m for m in p[n0:] if m[0] == "work-osprey-bld"]
check("auto-name: a handover by another session tells the owner once per item, through the owner path (a front owner: its keeper)",
      len(ow) == 2 and all(re.match(r"\[stackshot\] [a-z]\d+ \(mover work-osprey-main, a front agent\) now names work-osprey-x in its needs, handed over by home-beta: \[home\] auto-name test", m[1]) for m in ow)
      and "its keeper work-osprey-bld has been told instead" in res, (ow, res))
h4 = mk46(); n0 = len(wait_push(0))
server._message("work-osprey-main", f"{MK} {h4} needs your look", "home-beta"); server._message("work-osprey", f"{h4} for the keeper", "home-beta"); server._message("projects/alpha", f"{h4} for the project", "home-beta"); wait_push(n0 + 3)
server._message("work-osprey-x", f"{h4} failed its run", "cron", auth="machine:testbox", origin="testbox"); wait_push(n0 + 4); time.sleep(0.3)
check("auto-name: a message to a front agent, to the keeper or to the project page names nobody; nor does a script's message", "needs" not in rd(h4)["metadata"], rd(h4)["metadata"])
d1 = mk46(owner="home-beta"); n0 = len(wait_push(0))
_d1 = rd(d1); _d1["metadata"]["project"] = "projects/alpha"; server._save(d1, _d1)   # home-beta's create is refiled to projects/beta ("Refile itself"): an item filed before the rule
res = server._message("work-osprey-x", f"take {d1}", "work-osprey-main"); p = wait_push(n0 + 2)
ow = [m for m in p[n0:] if m[0] == B]
check("auto-name: a plain first naming tells the owner in one line (an owner that is not a front agent, directly)", needs46(d1) == ["work-osprey-x"] and len(ow) == 1
      and ow[0][1].startswith(f"[stackshot] {d1} now names work-osprey-x in its needs, handed over by work-osprey-main: [home] auto-name test") and "(its mover home-beta has been told)" in res, (ow, res))
# only an id written as a plain word names the receiver (misfires to avoid: a test name quoted in a brief,
# "a close by …"; a format example "1 g9191@1791800000"; a sala handover's context line): not in code, not in quotes, nothing glued on
q1, q2, q3 = mk46(), mk46(), mk46()
def _missed(forms, want):            # the forms whose ids _item_refs reads otherwise than `want`
    return [(t, got) for t in forms for got in [server._item_refs(t)] if got != want]
_m = _missed([f"`{q1}`", f"the test `{q1}_scenario` failed", f"run ``{q1}`` again", f"```\npytest -k {q1}\n```", f"~~~\n{q1}: x\n~~~"], [])
check("plain id: an id in backticks names nothing (inline code, a test name in code, a fenced block)", not _m, _m)
_m = _missed([f'3 checks: "{q1}: a close by another session…", "{q1}: a reopen…"', f"“{q1} done”", f"‘{q1} done’", f"the '{q1}' check"], [])
check("plain id: an id inside quotes names nothing (\" “ ” ‘ ’, a '…' pair), the quoted test name of the first misfire included", not _m, _m)
_m = _missed([f"e.g. 1 {q1}@1791800000 so", f'e.g. "1 {q1}@1791800000", so', f"{q1}/x", f"{q1}/{q2}", f"{q1}_scenario", f"{q1}x", f"{q1}0", f"x{q1}", f"~{q1}",
              f"{server._shared.BOARD_URL}/items/{q1}_x", f"{server._shared.BOARD_URL}/items/{q1}@1"], [])
check("plain id: an id with something glued on names nothing (@epoch, /, _, a letter or digit after it; anything but a space or ( [ before it)", not _m, _m)
_real = [f"hand-off of {q1}", f"{q1}: do X", f"({q1})", f"{q1}.", f"[{q1}]({server._shared.BOARD_URL}/items/{q1})", f"{q1}'s build is yours", f"{q1}, {q1}; {q1}!",
         f"**{q1}**", f"see {server._shared.BOARD_URL}/items/{q1} for it", f"line one\n{q1}\nline three", f"{q1.upper()} is yours", f"{q1}—the build"]
check("plain id: the real handover forms still name (hand-off of, id: do X, (id), id., a markdown link, a possessive, a page link)", not _missed(_real, [q1]), _missed(_real, [q1]))
n0 = len(wait_push(0))
res = server._message("work-osprey-x", f"the test `{q1}_scenario` failed; e.g. \"1 {q1}@1791800000\"; see {q1}/x and \"{q1}: a close by …\"", "work-osprey-main"); wait_push(n0 + 1); time.sleep(0.3)
check("plain id: a message to a background agent that cites an id only in code, quotes or glued names nobody", "needs" not in rd(q1)["metadata"] and "(named" not in res, (rd(q1)["metadata"], res))
n0 = len(wait_push(0))
res = server._message("work-osprey-x", f"Build job, {q2}, from Oliver's words (Wed Jun 10th 09:40 +00). Context: `{q3}` carried recycle=true, which only flags it.", "work-osprey-main")
wait_push(n0 + 1); time.sleep(0.3)
check("plain id: a sala-style handover names the job's item and not the item its context line cites in backticks",
      needs46(q2) == ["work-osprey-x"] and "needs" not in rd(q3)["metadata"] and res.count("(named work-osprey-x") == 1, (needs46(q2), rd(q3)["metadata"], res))
check("plain id: the message tool's description says how a handover writes the id, and that a context-only id goes in backticks",
      "names the item id, written as a plain word, not in backticks or quotes" in server._MESSAGE_DESC
      and "An item id cited only for context, not handed over, goes in backticks, since a plain-word id names the receiver on that item." in server._MESSAGE_DESC)
# moment 2: a write on the item by a background agent not named in its needs
w1 = mk46(); n0 = len(wait_push(0))
res = server._update(w1, next="building it", sender="work-osprey-x"); p = wait_push(n0 + 2)
check("auto-name: an update by a background agent not named in needs names it; the reply says so; the write lands", needs46(w1) == ["work-osprey-x"]
      and f"(named work-osprey-x in {w1}'s needs: update by work-osprey-x)" in res and rd(w1)["metadata"].get("next", "").endswith("\nbuilding it"), (needs46(w1), res))
check("auto-name: …and the owner is told through the owner path", any(m[0] == "work-osprey-bld" and f"[stackshot] {w1} (mover work-osprey-main, a front agent) now names work-osprey-x in its needs, after its update by work-osprey-x: " in m[1] for m in p[n0:]), p[n0:])
res = server._update(w1, next="still building", sender="work-osprey-x"); check("auto-name: a second write names nothing again", needs46(w1) == ["work-osprey-x"] and "(named" not in res, res)
w3 = mk46(owner="home-beta"); n0 = len(wait_push(0))
res = server._update(w3, work={"text": "migrating the ids"}, sender="work-osprey-x"); time.sleep(0.3)
check("auto-name: an unnamed background agent's first status passes the status-writer gate, since the naming runs before it, and leaves it named; the step is made from the text",
      needs46(w3) == ["work-osprey-x"] and [(_stp.opener(x["text"]), (x.get("tag") or {}).get("text")) for x in rd(w3)["metadata"].get("steps") or []][-1] == ("work-osprey-x", "migrating the ids")
      and f"(named work-osprey-x in {w3}'s needs: update by work-osprey-x)" in res, (needs46(w3), rd(w3)["metadata"].get("steps"), res))
e = refusal(lambda: server._update(w3, work={"text": "docs"}, sender="work-osprey-main"))
check("auto-name: …while a front agent's status is still refused by that gate (a front agent is never auto-named)", e.startswith(f"Refused: the status of a step on {w3} is written by")
      and "work-osprey-main is neither" in e and needs46(w3) == ["work-osprey-x"] and len(rd(w3)["metadata"]["steps"]) == 2, e)
w2 = mk46(); server._update(w2, next="x", sender="work-osprey"); server._update(w2, next="y", sender="work-osprey-main")
check("auto-name: a write by the keeper or a front agent names nobody", "needs" not in rd(w2)["metadata"], rd(w2)["metadata"])
c1 = mk46(needs=["work-osprey-ops"]); wait_push(len(wait_push(0))); n0 = len(wait_push(0))
res = server._update(c1, next="joining", sender="work-osprey-x"); p = wait_push(n0 + 2); time.sleep(0.3); p = wait_push(0)
check("auto-name: a conflict keeps the session already named, adds the agent after it, and tells the owner once", needs46(c1) == ["work-osprey-ops", "work-osprey-x"]
      and f"(named work-osprey-x in {c1}'s needs: update by work-osprey-x; work-osprey-ops stays named)" in res
      and len([m for m in p[n0:] if m[0] == "work-osprey-bld" and "now names work-osprey-x in its needs too (work-osprey-ops was already named), after its update by work-osprey-x" in m[1]]) == 1, (needs46(c1), res, p[n0:]))
k1 = mk46(); server._update(k1, needs=["decision"], ask=ASK, sender="work-osprey-main")
res = server._update(k1, next="prepping while he decides", sender="work-osprey-x")
check("auto-name: a needs=decision item keeps decision first and stays in his lane", needs46(k1) == ["decision", "work-osprey-x"] and k1 in [r["gid"] for r in ui_render.Board(str(T / "store")).n_call], (needs46(k1), res))
# only plain work names the agent: a write by it that sets needs itself (none included), parks the item (hold, wake) or sets a recycle
# leaves needs as the write says.
wk46 = (datetime.datetime.now(server.ZONE).date() + datetime.timedelta(days=3)).isoformat()
n1 = mk46(); server._update(n1, next="building it", sender="work-osprey-x"); res = server._update(n1, needs="none", sender="work-osprey-x")
check("auto-name: a background agent's needs=none clears needs and does not name it back", "needs" not in rd(n1)["metadata"] and "(named" not in res, (rd(n1)["metadata"], res))
res = server._update(n1, wake=wk46, recycle=True, sender="work-osprey-x")
check("auto-name: …and its next write of only wake and recycle=true does not name it either (the live case); the reminder and the recycle land, no hold",
      "needs" not in rd(n1)["metadata"] and "(named" not in res and "hold" not in rd(n1)["metadata"] and wk_(rd(n1)["metadata"]) == wk46 and rd(n1)["metadata"].get("recycle"), (rd(n1)["metadata"], res))
n2 = mk46(); res = server._update(n2, needs="none", sender="work-osprey-x")
check("auto-name: needs=none from an unnamed background agent names nobody", "needs" not in rd(n2)["metadata"] and "(named" not in res, (rd(n2)["metadata"], res))
n3 = mk46(); res = server._update(n3, needs=["work-osprey-ops"], sender="work-osprey-x")
check("auto-name: a background agent that sets needs to someone else is not added: needs is exactly what it gave", needs46(n3) == ["work-osprey-ops"] and "(named" not in res, (needs46(n3), res))
n4 = mk46(); res = server._update(n4, wake=wk46, sender="work-osprey-x")
check("auto-name: a background agent's wake alone (a reminder) names nobody; the wake lands, no hold", "needs" not in rd(n4)["metadata"] and "(named" not in res and "hold" not in rd(n4)["metadata"] and wk_(rd(n4)["metadata"]) == wk46, (rd(n4)["metadata"], res))
n5 = mk46(); res = server._update(n5, hold=True, wake=wk46, sender="work-osprey-x")
check("auto-name: …nor does hold=true with its wake", "needs" not in rd(n5)["metadata"] and "(named" not in res and hd_(rd(n5)["metadata"]), (rd(n5)["metadata"], res))
n6 = mk46(); e = refusal(lambda: server._update(n6, hold=True, sender="work-osprey-x"))
check("auto-name: …and a bare hold, refused as an indefinite park, leaves no naming behind", e.startswith("Refused: a hold names what it waits for") and "needs" not in rd(n6)["metadata"], (e, rd(n6)["metadata"]))
n7 = mk46(); res = server._update(n7, recycle=True, sender="work-osprey-x")
check("auto-name: a background agent's recycle=true alone names nobody; the recycle lands", "needs" not in rd(n7)["metadata"] and "(named" not in res and rd(n7)["metadata"].get("recycle"), (rd(n7)["metadata"], res))
n8 = mk46(); res = server._update(n8, next="building it", sender="work-osprey-x")
check("auto-name: plain work (next, needs left alone) still names it", needs46(n8) == ["work-osprey-x"] and f"(named work-osprey-x in {n8}'s needs: update by work-osprey-x)" in res, (needs46(n8), res))
# A page rename done with update(project=<new key>) by a background agent must not add it to the needs of every item. A write whose only
# arguments are filing ones (project, subject, priority, owner_name, observers) is bookkeeping, not work: it names nobody.
f1 = mk46(); res = server._update(f1, project="projects/alpha", sender="work-osprey-x")
check("auto-name: a background agent's update of only the project key names nobody (a page rename's mover); the write lands", "needs" not in rd(f1)["metadata"] and "(named" not in res and rd(f1)["metadata"]["project"] == "projects/alpha", (rd(f1)["metadata"], res))
f2 = mk46(); res = server._update(f2, project="projects/beta", sender="work-osprey-x")
check("auto-name: …also when the key names another page (the item refiles itself to its owner's page, as for any project edit)", "needs" not in rd(f2)["metadata"] and "(named" not in res, (rd(f2)["metadata"], res))
f3 = mk46(); res = server.stackshot_update(f3, project="projects/beta", sender="work-osprey-x")
check("auto-name: …through the update tool itself, whose wrapper passes every parameter", "needs" not in rd(f3)["metadata"] and "(named" not in res, (rd(f3)["metadata"], res))
f4 = mk46(); res = server._update(f4, subject="[home] auto-name test, renamed", priority="p1", sender="work-osprey-x")
check("auto-name: …and a subject or priority edit alone", "needs" not in rd(f4)["metadata"] and "(named" not in res, (rd(f4)["metadata"], res))
f5 = mk46(); res = server._update(f5, project="projects/alpha", next="building it", sender="work-osprey-x")
check("auto-name: the project key together with real work (next) still names the agent, as before", needs46(f5) == ["work-osprey-x"] and f"(named work-osprey-x in {f5}'s needs: update by work-osprey-x)" in res, (needs46(f5), res))
f6 = mk46(); res = server._update(f6, project="projects/alpha", work={"text": "moving it"}, sender="work-osprey-x")
check("auto-name: …and with a step status", needs46(f6) == ["work-osprey-x"] and "(named" in res, (needs46(f6), res))
f7 = mk46(needs=["work-osprey-x"]); res = server._update(f7, project="projects/beta", sender="work-osprey-x")
check("auto-name: a background agent already named stays named by a project-only update (nothing removed)", needs46(f7) == ["work-osprey-x"] and "(named" not in res, (needs46(f7), res))
# …and finishing its own step by a status done: a background agent that is not the owner marks its own step done by a status done, and that is the last of its part, not new work: it is not
# named in needs; a status done with no step of its own to finish, or together with other work, still names it as before
st46 = lambda g: [(_stp.opener(x["text"]), x["status"], (x.get("tag") or {}).get("text")) for x in rd(g)["metadata"].get("steps") or []]
d1 = mk46(); server._update(d1, work={"text": "moving the docs", "agent": "work-osprey-x"}, sender="work-osprey-main")
check("auto-name: the owner makes a step for the agent with a status without naming it", needs46(d1) is None and ("work-osprey-x", "open", "moving the docs") in st46(d1), (needs46(d1), st46(d1)))
res = server._update(d1, work={"state": "done"}, sender="work-osprey-x")
check("auto-name: a non-owner marking its own step done by a status done is not named in needs; the step is done", needs46(d1) is None and "(named" not in res and ("work-osprey-x", "done", "moving the docs") in st46(d1), (needs46(d1), st46(d1), res))
res = server._update(d1, work={"state": "done"}, sender="work-osprey-x")
check("auto-name: …again, with no open step left to finish: nothing recorded, the reply says so", "(work: not recorded, work-osprey-x has no open step" in res, (needs46(d1), res))
d2 = mk46(); server._update(d2, work={"text": "moving the docs"}, sender="work-osprey-main")
res = server._update(d2, work={"state": "done"}, sender="work-osprey-x")
check("auto-name: a done when the writer has no step of its own (the open step is the owner's) still names it, as today, and ticks nothing", needs46(d2) == ["work-osprey-x"] and "(named" in res and all(x[1] == "open" for x in st46(d2)), (needs46(d2), st46(d2), res))
d4 = mk46(); server._update(d4, work={"text": "moving the docs", "agent": "work-osprey-x"}, sender="work-osprey-main")
res = server._update(d4, work={"state": "done"}, next="and the next thing", sender="work-osprey-x")
check("auto-name: …and a done together with other work (next) names the writer", needs46(d4) == ["work-osprey-x"] and "(named" in res, (needs46(d4), res))
# …what counts as finishing is exact: the spec changes nothing else (no other session's step), the writer has an open step, the item is open
def own46():
    g = mk46(); server._update(g, work={"text": "moving the docs", "agent": "work-osprey-x"}, sender="work-osprey-main"); return g
e1 = own46(); res = server._update(e1, work={"state": "done", "agent": "work-osprey-main"}, sender="work-osprey-x")
check("auto-name: a done that is for another session's step is not a finish: the writer is named, as before, and that step is the one ticked", needs46(e1) == ["work-osprey-x"] and "(named" in res
      and ("work-osprey-main", "done", "carry on") in st46(e1), (needs46(e1), st46(e1), res))
e3 = own46(); res = server._update(e3, work={"text": "moving other docs", "state": "done"}, sender="work-osprey-x")
check("auto-name: a done with a final status text is a finish: not named; the step is done with that text", needs46(e3) is None and "(named" not in res and ("work-osprey-x", "done", "moving other docs") in st46(e3), (needs46(e3), st46(e3), res))
e3b = own46(); res = server._update(e3b, work={"text": "moving the docs", "state": "done", "agent": "work-osprey-x"}, sender="work-osprey-x")
check("auto-name: …also with its own name repeated", needs46(e3b) is None and "(named" not in res, (needs46(e3b), res))
e4 = own46(); res = server._update(e4, work={"text": "moving the docs", "state": "done"}, said=[{"tag": "Suggested-by", "quote": "finish it", "msg": "11111111-1111-4111-8111-0000000000e4", "session": "cse_e4unreadable"}], sender="work-osprey-x")
check("auto-name: a finish together with said is still a finish: not named", needs46(e4) is None and "(named" not in res and ("work-osprey-x", "done", "moving the docs") in st46(e4), (needs46(e4), st46(e4), res))
e6 = own46(); server.stackshot_complete(e6, sender="work-osprey-main", outcome="done", reason="landed", description="- Goal: Done")
e = refusal(lambda: server._update(e6, work={"state": "done"}, sender="work-osprey-x"))
check("auto-name: a finish on a completed item is refused as before, the writer not named", "work-osprey-x is neither" in e and "needs" not in rd(e6)["metadata"], (e, rd(e6)["metadata"]))
# …and the status text is the one the update path gets: it rewrites a bare store id (g9999) to first (patched here so that g9999 maps)
e7 = mk46()
_shown_was = server._shown_ids; server._shown_ids = lambda t: str(t or "").replace("g9999", f"board#{BID_B}")
try:
    res = server._update(e7, work={"text": "wait for g9999 now"}, sender="work-osprey-x")
finally:
    server._shown_ids = _shown_was
check(f"auto-name: a status whose text the update path rewrites (g9999 → board#{BID_B}) is stored as rewritten, and the writer is named",
      needs46(e7) == ["work-osprey-x"] and "(named" in res and ("work-osprey-x", "open", f"wait for board#{BID_B} now") in st46(e7), (needs46(e7), st46(e7), res))
wait_push(0)
z1 = mk46(); server.stackshot_complete(z1, sender="work-osprey-main", outcome="done", reason="landed", description="- Goal: Done")
res = server._update(z1, priority="p1", sender="work-osprey-x"); res2 = server._message("work-osprey-x", f"look at {z1}", "home-beta"); time.sleep(0.3)
check("auto-name: a closed item is never touched, by a write or by a message", "needs" not in rd(z1)["metadata"] and rd(z1)["status"] == "completed" and "(named" not in res and "(named" not in res2, (rd(z1)["metadata"], res, res2))
x1 = mk46(); n0 = len(wait_push(0))
res = server.stackshot_complete(x1, sender="work-osprey-x", outcome="done", reason="built", description="- Goal: Built"); p = wait_push(n0 + 2); time.sleep(0.3); p = wait_push(0)
check("auto-name: a close by an unnamed background agent names it first (the record), then closes with no needs; the owner hears the close only",
      rd(x1)["status"] == "completed" and "needs" not in rd(x1)["metadata"] and f"(named work-osprey-x in {x1}'s needs: close by work-osprey-x)" in res
      and not [m for m in p[n0:] if "now names work-osprey-x" in m[1]] and any(f"{x1} (mover work-osprey-main, a front agent) was completed (done: built) by work-osprey-x" in m[1] for m in p[n0:]), (res, p[n0:]))
check("auto-name: the client API's handover write takes the same path (a box's hook reporting a SendMessage), with the path in the record",
      (lambda g: server._client_post("testbox", "handover", {"to": "work-osprey-x", "text": f"SendMessage about {g}", "sender": "home-beta"}) == (200, {"result": f"(named work-osprey-x in {g}'s needs: handover message from home-beta (SendMessage on testbox))"})
       and needs46(g) == ["work-osprey-x"])(mk46(owner="home-beta")))
check("auto-name: …and refuses a body without a sender", server._client_post("testbox", "handover", {"to": "work-osprey-x", "text": "x"})[0] == 400)
# [pilot] never_named (a follow-up): a background agent whose mandate never works items (a maintainer agent, the audit) is
# never named by the server, at either moment; an unlisted background agent still is; a listed one can still be named by hand
O = "55555555-5555-4555-8555-555555555555"; _fl46 = (T / "fleet/a/sessions.json").read_text()
(T / "fleet/a/sessions.json").write_text(json.dumps({**json.loads(_fl46), O: {"name": "work-osprey-ops", "machine": "a", "url": "", "seen": "x"}}))
_rg46["pages"]["projects/alpha"]["agents"]["work-osprey-ops"] = "back"; _rg46["pages"]["projects/alpha"]["back_agents"]["work-osprey-ops"] = "back"
(T / "store/projects.json").write_text(json.dumps(_rg46)); server._cfg.CFG["pilot"]["never_named"] = ["work-osprey-ops"]
m_a = mk46(); n0 = len(wait_push(0))
res = server._message("work-osprey-ops", f"release PR #102, which touches {m_a} in passing", "home-beta"); wait_push(n0 + 1); time.sleep(0.3)
check("never_named: a message-tool handover to a listed background agent that names an item names nobody", "needs" not in rd(m_a)["metadata"] and "(named" not in res, (rd(m_a)["metadata"], res))
res = server._update(m_a, next="released", sender="work-osprey-ops"); time.sleep(0.3)
check("never_named: …nor does an update by that agent; the write still lands", "needs" not in rd(m_a)["metadata"] and "(named" not in res and rd(m_a)["metadata"].get("next", "").endswith("\nreleased"), (rd(m_a)["metadata"], res))
res = server._message("work-osprey-x", f"please take {m_a}", "home-beta"); time.sleep(0.3)
check("never_named: an unlisted background agent is still named, with the list set", needs46(m_a) == ["work-osprey-x"] and f"(named work-osprey-x in {m_a}'s needs" in res, (needs46(m_a), res))
m_b = mk46(); res = server._update(m_b, next="x", sender="work-osprey-x")
check("never_named: …and an update by it still names it", needs46(m_b) == ["work-osprey-x"] and f"(named work-osprey-x in {m_b}'s needs: update by work-osprey-x)" in res, (needs46(m_b), res))
v3 = mk46(); server._update(v3, needs=["work-osprey-ops"], sender="work-osprey-main")
check("never_named: a listed agent can still be named by hand through needs=", needs46(v3) == ["work-osprey-ops"], rd(v3)["metadata"])
server._cfg.CFG["pilot"]["never_named"] = []; v4 = mk46(); res = server._update(v4, next="x", sender="work-osprey-ops")
check("never_named: read at each naming (a reload applies it): off the list, the same agent is named again", needs46(v4) == ["work-osprey-ops"] and "(named work-osprey-ops" in res, (needs46(v4), res))
(T / "fleet/a/sessions.json").write_text(_fl46)
time.sleep(0.4); (T / "store/projects.json").write_text(_reg46)

# ---- 47. green release.sh results are log-only (the turn rule):
# logged with no recipient and marked log_only, ruled merged by `stackshot (auto)`, a comment on the open items anchored to the
# PR, no page owed; the item waiting on the PR still closes on its pr_merged check and releases the item after it; the keeper
# stays on the routing page (the keeper's daily digest of automatic rulings is gone); a red result is held for the router like any message
check("release: this checkout's own repository is read from its origin remote", server._own_repo() != "", server._own_repo())
server._OWN_REPO[:] = ["example-owner/stackshot"]      # the fixture's repo, whatever remote the checkout running the test has
PRU = "https://github.com/example-owner/stackshot/pull/113"
def item47(i, **meta):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": "A thing. It lives here. Done when done.",
                                                      "status": "open", "metadata": {"owner": A, "project": "projects/alpha", **meta}, "updated": 5.0, "state_updated": 5.0, "confirmed": 5.0}))
item47(33, check="pr_merged example-owner/stackshot#113", next="work-osprey-x: merge PR #113"); item47(39, after=["a33"], next="after the merge")
_anc47 = (T / "store/anchors.json").read_text()
(T / "store/anchors.json").write_text(json.dumps({**json.loads(_anc47), "projects/alpha": json.loads(_anc47)["projects/alpha"] + [{"url": PRU, "items": ["a33"], "added": 1, "by": "t"}]}))
GREEN = "[release] PR #113 merged and deployed — a change — main at 0606060, restarted: stackshot.service, healthz ok · log /x/pr-113.log"
n0 = len(wait_push(0)); owed0 = json.dumps(server._owed_load(), sort_keys=True); comments = []
_ge, _goc = server._gh.enabled, server._gh.on_change
server._gh.enabled = lambda: True; server._gh.on_change = lambda gid, before, after, name="", sid="", note="", background=False: comments.append((gid, before == {k: ({kk: vv for kk, vv in v.items() if kk != "phase"} if k == "metadata" else v) for k, v in after.items() if k not in ("activity", "progress")}, name, note, after.get("activity")))      # an item from before the activity and progress clocks gains the fields at its first save (seeded from its last update, so a server note moves nothing), and an open item gains its stored phase: the item is otherwise unchanged
st, body = server._client_post("testbox", "message", {"to": "projects/alpha", "text": GREEN, "sender": "release", "release": "green", "pr": PRU})
server._gh.enabled, server._gh.on_change = _ge, _goc
time.sleep(0.3)
m47 = re.search(r"notice ([0-9a-f]{6}) on projects/alpha", str(body.get("result")))
check("green release: answered as logged, not delivered, ruled by stackshot (auto), kept on the routing page",
      st == 200 and m47 and "not delivered" in body["result"] and "ruled merged by stackshot (auto)" in body["result"] and "it stays on the routing page" in body["result"] and "digest" not in body["result"], (st, body))
nid47 = m47.group(1) if m47 else ""
check("green release: nothing is delivered", len(wait_push(0)) == n0, wait_push(0)[n0:])
raw47 = [json.loads(l) for l in open(routing._file("projects/alpha"), encoding="utf-8") if f'"{nid47}"' in l]
check("green release: one routing-log line marked log-only, with no recipient, the PR as its link",
      raw47 and raw47[0].get("log_only") is True and raw47[0]["to"] == "" and raw47[0]["kind"] == "message" and raw47[0]["url"] == PRU and raw47[0]["pilot"] is True
      and raw47[0]["who"] == "release (a script on testbox)" and raw47[0]["text"].startswith("[release] PR #113 merged and deployed"), raw47)
n47 = next(n for n in routing.read("projects/alpha") if n["id"] == nid47)
check("green release: the ruling is recorded, merged by stackshot (auto)", (n47.get("ruling"), n47.get("ruled_by")) == ("merged", "stackshot (auto)") and "log-only" in n47.get("reason", ""), n47)
check("green release: no notice left pending", nid47 not in [n["id"] for n in routing.read("projects/alpha") if n.get("pilot") and not n.get("ruling")])
check("green release: the open item anchored to the PR is saved with the item unchanged, and the server's note no longer travels to GitHub as a comment (the hook gets the item before and after, nothing else)",
      comments == [("a33", True, "", "", 5.0)]
      and rd("a33")["updated"] == 5.0 and rd("a33")["status"] == "open", comments)
check("green release: no page is owed", json.dumps(server._owed_load(), sort_keys=True) == owed0, server._owed_load())
_prm = server._pr_merged; server._pr_merged = lambda ref, now, gh_st: (ref == "example-owner/stackshot#113", "")
server._CHECK_LAST[0] = 0; closed47 = server._check_tick(); server._pr_merged = _prm; time.sleep(0.3)
check("green release: the item waiting on the PR still closes on its pr_merged check",
      "a33" in closed47 and rd("a33")["status"] == "completed" and rd("a33")["metadata"].get("reason") == "done check passed: pr_merged example-owner/stackshot#113", (closed47, rd("a33")))
check("…and the close releases the item after it", rd("a39")["status"] == "open" and "after" not in rd("a39")["metadata"], rd("a39")["metadata"])
wait_push(0)

# a red result, and the cases that cannot go log-only, are held for the router like any message to a project (nothing is delivered here)
def held47(body, k0):      # the notice id of a message held for the router, or ""
    m = re.match(r"held for the router — the router rules notice ([0-9a-f]{6}) ", str(body.get("result")))
    return m.group(1) if m and len(wait_push(0)) == k0 else ""
n0 = len(wait_push(0))
RED = "[release] PR #114 FAILED at deploy: healthz did not answer · log /x/pr-114.log"
st, body = server._client_post("testbox", "message", {"to": "projects/alpha", "text": RED, "sender": "release"})
nr = held47(body, n0); nrl = next((n for n in routing.read("projects/alpha") if n["id"] == nr), {})
check("red release: held for the router, a [stackshot message] with its notice id waiting for a ruling; nothing is delivered to the keeper", st == 200 and nr and (router_live.stashed(nr) or "").startswith("[stackshot message] from release (a script on testbox) · ")
      and "[release] PR #114 FAILED" in (router_live.stashed(nr) or ""), (body, wait_push(0)[n0:]))
check("red release: its routing line is live, has no recipient, no log-only mark and no ruling", nrl.get("live") is True and nrl["to"] == "" and not nrl.get("log_only") and not nrl.get("ruling"), nrl)
st, body = server._client_post("testbox", "message", {"to": "projects/alpha", "text": RED, "sender": "release", "release": "red", "pr": PRU})
check("red release: --release red is held the same way", held47(body, n0) != "" and "PR #114 FAILED" in (router_live.stashed(held47(body, n0)) or ""), body)
st, body = server._client_post("testbox", "message", {"to": "projects/beta", "text": GREEN, "sender": "release", "release": "green", "pr": PRU})
check("green release to a project with one session (beta, no longer outside any list: the router rules every page): logged, not delivered, like alpha's", body["result"].startswith("logged, not delivered") and len(wait_push(0)) == n0, body)
for n in routing.read("projects/beta"):
    if n.get("pilot") and not n.get("ruling"): routing.rule(n["id"], "dropped", reason="done with the release checks", by="work-osprey")
_rg = server._release_green; server._release_green = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("disk full"))
st, body = server._client_post("testbox", "message", {"to": "projects/alpha", "text": GREEN, "sender": "release", "release": "green", "pr": PRU})
server._release_green = _rg
check("a log-only path that fails hands the result to the router instead, never loses it", held47(body, n0) != "" and "PR #113 merged" in (router_live.stashed(held47(body, n0)) or ""), body)
# only release.sh's own report of a PR of this repo goes log-only: anything else is held for the router
for why, extra in (("another sender", {"sender": "size-watch"}), ("a sender that only contains release", {"sender": "release-bot"}),
                   ("no pr", {"pr": ""}), ("a garbage pr", {"pr": "not a url"}), ("an issue, not a PR", {"pr": "https://github.com/example-owner/stackshot/issues/113"}),
                   ("another repository's PR", {"pr": "https://github.com/someone/else/pull/113"})):
    k0 = len(wait_push(0))
    st, body = server._client_post("testbox", "message", {"to": "projects/alpha", "text": GREEN, "sender": "release", "release": "green", "pr": PRU, **extra})
    nx = held47(body, k0)
    check(f"green with {why}: not log-only, held for the router, waiting for a ruling",
          st == 200 and nx and not next(n for n in routing.read("projects/alpha") if n["id"] == nx).get("ruling") and not next(n for n in routing.read("projects/alpha") if n["id"] == nx).get("log_only"), body)
k0 = len(wait_push(0)); _or = server._OWN_REPO[:]; server._OWN_REPO[:] = [""]
st, body = server._client_post("testbox", "message", {"to": "projects/alpha", "text": GREEN, "sender": "release", "release": "green", "pr": PRU})
server._OWN_REPO[:] = _or
check("a checkout whose own repository cannot be read sends nothing log-only: held for the router", held47(body, k0) != "", body)
for n in routing.read("projects/alpha"):
    if n.get("pilot") and not n.get("ruling"): routing.rule(n["id"], "dropped", reason="done with the release checks", by="work-osprey")

# the daily digest of automatic rulings is gone with the keeper: a ruling by stackshot (auto) stays on the routing page, and route() overrules it
st, body = server._client_post("testbox", "message", {"to": "projects/alpha", "text": GREEN.replace("PR #113", "PR #115"), "sender": "release", "release": "green", "pr": PRU.replace("113", "115")})
nid47c = re.search(r"notice ([0-9a-f]{6})", body["result"]).group(1)
res = server._route(nid47c, "passed", to="work-osprey-main", reason="the owner should hear of this one", sender="work-osprey")
nc = next(n for n in routing.read("projects/alpha") if n["id"] == nid47c)
check("overrule: route() on an automatic ruling records the keeper's own, which wins",
      res.startswith(f"ruled {nid47c} (projects/alpha): passed to work-osprey-main") and (nc["ruling"], nc["ruled_by"], nc["ruled_to"]) == ("passed", "work-osprey", "work-osprey-main"), (res, nc))
check("the digest machinery is gone: no _digest_tick, no _digest_rows, no digest hour in a green release's reply", not hasattr(server, "_digest_tick") and not hasattr(server, "_digest_rows") and "digest" not in body["result"], body)
(T / "store/anchors.json").write_text(_anc47)

# ---- 48. the fleet's own PR events are log-only by event type (the turn rule): on a repository in [pilot] own_repos, a PR opened, merged, closed or given new commits and CI passing again are logged for
# the pilot keeper with no recipient, ruled merged by stackshot (auto) and kept on the routing page, never delivered; a review, a
# comment, failing CI, a reopen and anything on someone else's repository are delivered as before; and a log-only event still
# releases the held item scoped to its anchor, as the keeper's own `merged` would
import types as _types
from stackshot.anchors.anchorhub import github as ghr
server._cfg.CFG["pilot"]["own_repos"] = ["example-owner/stackshot", "example-org/*"]
PR48, HUB48, FOR48, BETA48 = ("https://github.com/example-owner/stackshot/pull/116", "https://github.com/example-org/board-repo",
                              "https://github.com/example-upstream/tool/pull/77", "https://github.com/example-owner/stackshot/pull/117")
A48, AH48, AF48, AB48 = "github:example-owner/stackshot#116", "github:example-org/board-repo@notifications", "github:example-upstream/tool#77", "github:example-owner/stackshot#117"
def item48(i, **meta):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": "A thing. It lives here. Done when done.",
                                                      "status": "open", "metadata": {"owner": A, "project": "projects/alpha", **meta}, "updated": 5.0, "state_updated": 5.0, "confirmed": 5.0}))
item48(54, hold=True, wake="2099-01-01", next=f"wait on [#95]({PR48})")
_anc48 = (T / "store/anchors.json").read_text(); _a48 = json.loads(_anc48)
_a48["projects/alpha"] = _a48["projects/alpha"] + [{"url": PR48, "items": ["a54"], "added": 1, "by": "t"}, {"url": HUB48, "items": None, "added": 1, "by": "t"},
                                                   {"url": FOR48, "items": None, "added": 1, "by": "t"}]
_a48["projects/beta"] = _a48.get("projects/beta", []) + [{"url": BETA48, "items": None, "added": 1, "by": "t"}]
(T / "store/anchors.json").write_text(json.dumps(_a48))
hub48 = core.Hub(); out48 = []
hub48.deliver = lambda anchor, session, text: out48.append((session, text)); hub48.write_status = lambda: None
hub48.bindings = core.load_bindings()
check("own PRs: the anchors are bound (the PR to the keeper, for its item's owner; the repo root and the foreign PR project-wide; beta's to home-beta)",
      hub48.bindings.get(A48) == {S} and hub48.bindings.get(AH48) == {S} and hub48.bindings.get(AF48) == {S} and hub48.bindings.get(AB48) == {B}, hub48.bindings)
def lines48(project, anchor): return [n for n in routing.read(project) if n.get("anchor") == anchor]
def ev48(anchor, etype, text="merged it", who="example-owner", kind="github-state", url=PR48, repo_id=None):
    """One event through the hub, nothing pending before it → (what was delivered, the routing line it left)."""
    hub48.pending.clear(); out48.clear()
    proj = "projects/beta" if anchor == AB48 else "projects/alpha"; k0 = len(lines48(proj, anchor))
    hub48.event(anchor, {"title": f"{anchor[7:].split('#')[0].split('@')[0].split('/')[1]}#x \"a change\"", "who": who, "text": text, "url": url, "ts": "1", "etype": etype, **({"repo_id": repo_id} if repo_id is not None else {})}, kind=kind)
    new = lines48(proj, anchor)[k0:]
    return list(out48), (new[0] if len(new) == 1 else new)
ROUT48 = {"pr_opened": "opened it", "pr_merged": "merged it", "pr_closed": "closed it", "pr_synchronize": "pushed 2 commits", "ci_passed": "passing again on abc1234 (3 checks)"}
auto48 = []
for et, txt in ROUT48.items():
    got, ln = ev48(A48, et, txt)
    ok = isinstance(ln, dict)
    check(f"own repo, {et}: nothing delivered, nothing held for a follow-up", got == [] and not hub48.pending, (got, hub48.pending))
    check(f"own repo, {et}: one routing line with no recipient, marked log-only, its type in the reason",
          ok and ln["to"] == "" and ln.get("log_only") is True and ln["kind"] == "anchor" and ln["pilot"] is True and ln["target"] == "for work-osprey-main"
          and f"log-only: {et} on example-owner/stackshot" in ln.get("reason", "") and ln["url"] == PR48 and txt in ln["text"], ln)
    check(f"own repo, {et}: ruled merged by stackshot (auto), nothing left for the keeper to rule",
          ok and (ln.get("ruling"), ln.get("ruled_by")) == ("merged", "stackshot (auto)"), ln)
    if ok: auto48.append(ln["id"])
check("own repo: the five routine types are what ROUTINE holds, all in GH_TYPES", core.ROUTINE == set(ROUT48) and core.ROUTINE <= set(core.GH_TYPES), core.ROUTINE)
got, ln = ev48(AH48, "pr_merged", "merged on #12 \"a board change\"", url="https://github.com/example-org/board-repo/pull/12")
check("own repo by owner wildcard (example-org/*), a repo root's merge: logged, not delivered", got == [] and isinstance(ln, dict) and ln.get("log_only") and ln.get("ruled_by") == "stackshot (auto)" and ln["target"] == "project-wide", (got, ln))
if isinstance(ln, dict): auto48.append(ln["id"])

def delivered48(name, anchor, etype, text, kind="github-state", who="kim", to=S):
    got, ln = ev48(anchor, etype, text, who=who, kind=kind)
    check(f"{name}: delivered as before, with its notice id, waiting for the keeper's ruling", len(got) == 1 and got[0][0] == to and got[0][1].startswith("[anchor] GitHub ")
          and isinstance(ln, dict) and ln["to"] == to and not ln.get("log_only") and not ln.get("ruling") and (to != S or re.search(r" · notice [0-9a-f]{6}$", got[0][1])), (got, ln))
    return ln
delivered48("own repo, a comment", A48, "comment", "looks good to me", kind="github")
delivered48("own repo, a review", AH48, "review", "review approved on #12 \"a board change\"")
delivered48("own repo, a review comment", AH48, "review_comment", "1 review comment on #12 \"a board change\"")
delivered48("own repo, failing CI on the PR", A48, "ci_failed", "failed on abc1234: 1 of 3 checks — tests", who="CI")
delivered48("own repo, GitHub's own CI notice", AH48, "ci_activity", "\"tests workflow run failed for main branch\"", who="CI")
delivered48("own repo, a merge with a comment beside it", AH48, "pr_merged+comment", "merged; 1 new comment on #12 \"a board change\"")
delivered48("own repo, a reopen", A48, "pr_reopened", "open it")
delivered48("own repo, an unclassified event", AH48, "", "(subscribed) Discussion \"a thread\"")
for et, txt in ROUT48.items():
    delivered48(f"foreign repo (example-upstream/tool), {et}", AF48, et, txt, who="example-upstream")
got, ln = ev48(AB48, "pr_merged", "merged it")
check("own repo, a page with one session (beta: the router rules every page): a routine merge is logged and ruled automatically like alpha's, not delivered", got == [] and isinstance(ln, dict) and ln.get("log_only") and ln.get("ruled_by") == "stackshot (auto)", (got, ln))
server._cfg.CFG["pilot"]["own_repos"] = []
delivered48("own_repos empty (the default): nothing is own", A48, "pr_merged", "merged it")
server._cfg.CFG["pilot"]["own_repos"] = "example-owner/stackshot, example-org/*"
got, ln = ev48(A48, "pr_closed", "closed it")
check("own_repos as one comma-separated string reads the same", got == [] and isinstance(ln, dict) and ln.get("log_only"), (got, ln))
if isinstance(ln, dict): auto48.append(ln["id"])
check("the repo match is exact (no prefix match) and an owner wildcard is that owner only",
      core.is_own("example-owner/stackshot") and not core.is_own("example-owner/stackshot-fork") and core.is_own("example-org/anything") and not core.is_own("example-owner/salamander")
      and not core.is_own("evil/example-org") and core.repo_of(AH48) == "example-org/board-repo" and core.repo_of("slack:C1") == "")
# own_repos by GitHub's numeric repository ID (a transfer to another owner changes owner/name, never the ID): an ID entry, an int or a digit string, in
# the list or in the comma string, matches the event's repository.id (Event.repo_id) under any owner; a name entry matches the name; an event with no ID
# is matched by name only; a different ID does not match
ID_A48, ID_B48 = 9000019, 9000020
server._cfg.CFG["pilot"]["own_repos"] = [ID_A48]
got, ln = ev48(AF48, "pr_merged", "merged it", who="example-upstream", repo_id=ID_A48)
check("own_repos ID entry (an int) matches an event carrying that ID under a different owner (example-upstream/tool): logged, not delivered", got == [] and isinstance(ln, dict) and ln.get("log_only") and ln.get("ruled_by") == "stackshot (auto)", (got, ln))
if isinstance(ln, dict): auto48.append(ln["id"])
got, ln = ev48(AF48, "pr_merged", "merged it", who="example-upstream", repo_id=ID_B48)
check("own_repos ID entry does not match a different ID: delivered as before", len(got) == 1 and got[0][0] == S and isinstance(ln, dict) and not ln.get("log_only"), (got, ln))
got, ln = ev48(A48, "pr_merged", "merged it")
check("an ID-only list and an event with no ID: the name does not match (no name entry), delivered", len(got) == 1 and got[0][0] == S and isinstance(ln, dict) and not ln.get("log_only"), (got, ln))
server._cfg.CFG["pilot"]["own_repos"] = [str(ID_A48)]
got, ln = ev48(AF48, "pr_closed", "closed it", who="example-upstream", repo_id=ID_A48)
check("own_repos ID entry as a digit string matches the same", got == [] and isinstance(ln, dict) and ln.get("log_only"), (got, ln))
if isinstance(ln, dict): auto48.append(ln["id"])
server._cfg.CFG["pilot"]["own_repos"] = ["example-owner/stackshot", ID_A48]
got, ln = ev48(A48, "pr_merged", "merged it")
check("a name entry beside an ID entry still matches an event with no ID (falls back to the name)", got == [] and isinstance(ln, dict) and ln.get("log_only"), (got, ln))
if isinstance(ln, dict): auto48.append(ln["id"])
got, ln = ev48(A48, "pr_merged", "merged it", repo_id=ID_B48)
check("a name entry matches by name even when the event carries some other ID", got == [] and isinstance(ln, dict) and ln.get("log_only"), (got, ln))
if isinstance(ln, dict): auto48.append(ln["id"])
server._cfg.CFG["pilot"]["own_repos"] = f"example-org/*, {ID_A48}"
got, ln = ev48(AF48, "pr_opened", "opened it", who="example-upstream", repo_id=ID_A48)
check("own_repos as a comma-separated string with an ID reads the same", got == [] and isinstance(ln, dict) and ln.get("log_only"), (got, ln))
if isinstance(ln, dict): auto48.append(ln["id"])
check("is_own by ID: exact digits, any owner, no ID or another ID falls to the name, zero/empty/bool IDs count as none",
      core.is_own("x/y", [str(ID_A48)], ID_A48) and core.is_own("x/y", [str(ID_A48)], str(ID_A48)) and not core.is_own("x/y", [str(ID_A48)], ID_B48)
      and not core.is_own("x/y", [str(ID_A48)]) and not core.is_own("x/y", [str(ID_A48)], 0) and not core.is_own("x/y", ["1"], True)
      and core.is_own("o/r", ["o/r", str(ID_A48)], ID_B48) and core.is_own("o/r", ["o/r"], None) and not core.is_own("", [str(ID_A48)])
      and core.is_own("", [str(ID_A48)], ID_A48) is True
      and core._repo_id(ID_A48) == ID_A48 and core._repo_id(str(ID_A48)) == ID_A48 and core._repo_id(None) == 0 and core._repo_id("x") == 0 and core._repo_id(True) == 0 and core._repo_id(-5) == 0)
check("own_repos reads an int entry from a list as digits", (lambda: (server._cfg.CFG["pilot"].__setitem__("own_repos", [ID_A48, True, "Oliver/Repo"]), core.own_repos())[1])() == [str(ID_A48), "oliver/repo"], core.own_repos())
server._cfg.CFG["pilot"]["own_repos"] = "example-owner/stackshot, example-org/*"
_rec48 = routing.record_auto; routing.record_auto = lambda *a, **k: (_ for _ in ()).throw(OSError("disk full"))
got, ln = ev48(A48, "pr_merged", "merged it")
routing.record_auto = _rec48
check("a log line that cannot be written is delivered instead, never lost", len(got) == 1 and got[0][0] == S and "merged it" in got[0][1], got)

# the keeper's condition: a log-only event still releases the item waiting on it, exactly as the keeper's ruling would
for n in routing.read("projects/alpha"):
    if n.get("pilot") and not n.get("ruling"): routing.rule(n["id"], "dropped", reason="done with the delivery checks", by="work-osprey")
check("the held item a54 is still held: the earlier log-only lines came while it was parked at 5.0, so the minute pass releases it now",
      server._is_held(rd("a54")))
n0 = len(wait_push(0)); rel = server._anchor_pass(); p = wait_push(n0 + 1)
check("release: the minute pass releases the item held on the PR's anchor, by the log-only line, its hold and wake gone",
      rel == ["a54"] and not server._is_held(rd("a54")) and "wake" not in rd("a54")["metadata"] and rd("a54")["status"] == "open", (rel, rd("a54")["metadata"]))
check("release: the page's keeper (its -main agent, the page has no builder) is told what released it, naming the automatic ruling", any(m[0] == A and m[1].startswith(f"[stackshot] a54 woke: a notice from {A48}, the anchor it waited on, was logged and ruled merged by stackshot (auto)") for m in p[n0:]), p[n0:])
check("release: once (the release moves the clocks)", server._anchor_pass() == [])
server._update("a54", hold=True, wake="2099-01-01", sender="work-osprey-main"); time.sleep(0.05)
check("release: a log-only line older than the park releases nothing", server._anchor_pass() == [] and server._is_held(rd("a54")))
got, ln = ev48(A48, "pr_synchronize", "pushed 1 commit"); auto48.append(ln["id"])
server._route(ln["id"], "dropped", reason="not what a54 waits on", sender="work-osprey")
check("release: an automatic ruling the keeper overrules with dropped releases nothing", server._anchor_pass() == [] and server._is_held(rd("a54")))
routing.record("projects/alpha", kind="anchor", to="", label="GitHub stackshot#116", who="hub", text="logged, not delivered", target="direct", anchor=A48, reason="direct: log only")
check("release: a log-only direct anchor's line (no log_only mark, no ruling) still releases nothing", server._anchor_pass() == [] and server._is_held(rd("a54")))
got, ln = ev48(A48, "pr_merged", "merged it"); auto48.append(ln["id"])
check("release: a log-only merge on the PR the item waits on releases it", got == [] and server._anchor_pass() == ["a54"] and not server._is_held(rd("a54")))
# the same release through a delivered notice and the keeper's ruling: the notice names the anchor by id (github:…), the store by URL
server._update("a54", hold=True, wake="2099-01-01", sender="work-osprey-main"); time.sleep(0.05)
got, ln = ev48(A48, "comment", "a question for the owner", who="kim", kind="github")
res = server._route(ln["id"], "passed", to="work-osprey-main", reason="Kim asks", sender="work-osprey")
check("release: a delivered notice the keeper passes releases it too, its anchor id matched to the store's URL",
      "(a54 waited on this anchor and is released from hold)" in res and not server._is_held(rd("a54")), res)
wait_push(0)
# an item whose done check is pr_merged, and the item after it: untouched by the log-only path, closed by the check as before
item48(57, check="pr_merged example-owner/stackshot#116", next="work-osprey-x: merge PR #116"); item48(58, after=["a57"], next="after the merge")
got, ln = ev48(A48, "pr_merged", "merged it"); auto48.append(ln["id"])
_prm = server._pr_merged; server._pr_merged = lambda ref, now, gh_st: (ref == "example-owner/stackshot#116", "")
server._CHECK_LAST[0] = 0; closed48 = server._check_tick(); server._pr_merged = _prm; time.sleep(0.3)
check("pr_merged: the item checked on the PR closes on its check as before, and the item after it is released",
      "a57" in closed48 and rd("a57")["status"] == "completed" and rd("a58")["status"] == "open" and "after" not in rd("a58")["metadata"], (closed48, rd("a58")["metadata"]))
wait_push(0)

# the receiver: the GitHub poll tags each event with its type at the source, and the hub decides by that type
G48 = {}; caught48 = []
def _gh48(args, capture_output=True, text=True, timeout=30):
    a = [x for x in args[2:] if x != "-i"]; path = a[0]; cond = "-i" in args
    if path not in G48: return _types.SimpleNamespace(returncode=1, stdout="", stderr="gh: Not Found (HTTP 404)")
    body = json.dumps(G48[path])
    return _types.SimpleNamespace(returncode=0, stdout=("HTTP/2.0 200 OK\netag: \"x\"\n\n" + body) if cond else body, stderr="")
class _Stop48(Exception): pass
def _no_sleep(s): raise _Stop48()
_gsub, _gthr, _gtime = ghr.subprocess, ghr.threading, ghr.time
ghr.subprocess = _types.SimpleNamespace(run=_gh48)
ghr.threading = _types.SimpleNamespace(Thread=lambda target, daemon=True: _types.SimpleNamespace(start=lambda: caught48.append(target)))
ghr.time = _types.SimpleNamespace(time=time.time, sleep=_no_sleep)
hubr = core.Hub(); hubr.write_status = lambda: None; evs48 = []; hubr.emit = lambda ev: evs48.append(ev)
hubr.bindings = {A48: {S}, AH48: {S}}
R, N = "/repos/example-owner/stackshot", "/repos/example-org/board-repo"
G48.update({"/user": {"login": "example-owner"},
            f"{R}/pulls/116": {"head": {"sha": "a" * 40}, "base": {"repo": {"id": ID_A48}}}, f"{R}/commits/{'a' * 40}/check-runs?per_page=100": {"check_runs": [{"name": "tests", "status": "completed", "conclusion": "success"}]},
            f"{R}/issues/116": {"state": "open", "comments": 0, "updated_at": "2026-03-05T00:00:00Z", "title": "a change", "html_url": PR48, "pull_request": {"merged_at": None}},
            f"{N}/notifications?all=true&per_page=50": [{"id": "t1", "updated_at": "2026-03-05T00:00:00Z", "reason": "subscribed", "repository": {"id": ID_B48, "full_name": "example-org/board-repo"}, "subject": {"type": "PullRequest", "url": f"https://api.github.com{N}/pulls/12", "title": "a board change"}},
                                                        {"id": "t2", "updated_at": "2026-03-05T00:00:00Z", "reason": "ci_activity", "subject": {"type": "CheckSuite", "url": "", "title": "tests workflow run failed"}},
                                                        {"id": "t3", "updated_at": "2026-03-05T00:00:00Z", "reason": "subscribed", "subject": {"type": "PullRequest", "url": f"https://api.github.com{N}/pulls/13", "title": "another"}}]})
def pass48():
    try: caught48[0]()
    except _Stop48: pass
try:
    ghr.run(hubr); pass48()                                       # the first pass seeds silently
    check("receiver: the first pass seeds, no event", evs48 == [], [e.etype for e in evs48])
    G48[f"{R}/pulls/116"] = {"head": {"sha": "b" * 40}}
    G48[f"{R}/commits/{'b' * 40}/check-runs?per_page=100"] = {"check_runs": [{"name": "tests", "status": "completed", "conclusion": "failure"}]}
    G48[f"{R}/issues/116"] = {**G48[f"{R}/issues/116"], "comments": 1, "updated_at": "2026-03-05T01:00:00Z"}
    G48[f"{R}/issues/116/comments?since=2026-03-05T00:00:00Z&per_page=20"] = [{"user": {"login": "kim"}, "body": "why this?", "html_url": PR48 + "#c1", "created_at": "2026-03-05T01:00:00Z"}]
    G48[f"{N}/notifications?all=true&per_page=50"] = [{**x, "updated_at": "2026-03-05T02:00:00Z"} for x in G48[f"{N}/notifications?all=true&per_page=50"]]
    G48[f"{N}/issues/12"] = {"html_url": "https://github.com/example-org/board-repo/pull/12", "pull_request": {"merged_at": "2026-03-05T02:00:00Z"}, "closed_by": {"login": "example-owner"}, "closed_at": "2026-03-05T02:00:00Z", "state": "closed"}
    G48[f"{N}/issues/12/comments?since=2026-03-05T00:00:00Z&per_page=50"] = []; G48[f"{N}/pulls/12/reviews?per_page=100"] = []; G48[f"{N}/pulls/12/comments?since=2026-03-05T00:00:00Z&per_page=50"] = []
    G48[f"{N}/issues/13"] = {"html_url": "https://github.com/example-org/board-repo/pull/13", "pull_request": {"merged_at": None}, "state": "open"}
    G48[f"{N}/issues/13/comments?since=2026-03-05T00:00:00Z&per_page=50"] = []; G48[f"{N}/pulls/13/comments?since=2026-03-05T00:00:00Z&per_page=50"] = []
    G48[f"{N}/pulls/13/reviews?per_page=100"] = [{"user": {"login": "kim", "type": "User"}, "state": "CHANGES_REQUESTED", "submitted_at": "2026-03-05T02:00:00Z", "html_url": "https://github.com/example-org/board-repo/pull/13#r1"}]
    pass48(); got1 = sorted((e.anchor, e.etype) for e in evs48); evs1 = list(evs48); evs48.clear()
    check("receiver: a comment, a CI failure, a merge seen through the repo's notifications, GitHub's CI notice and a review, each tagged by type",
          got1 == sorted([(A48, "ci_failed"), (A48, "comment"), (AH48, "pr_merged"), (AH48, "ci_activity"), (AH48, "review")]), got1)
    check("receiver: the events carry the repository ID the responses gave (a PR's base.repo, a notification's repository)",
          {(e.anchor, e.repo_id) for e in evs1} == {(A48, ID_A48), (AH48, ID_B48)} and all(isinstance(e.repo_id, int) for e in evs1), [(e.anchor, e.repo_id) for e in evs1])
    G48[f"{R}/pulls/116"] = {"head": {"sha": "c" * 40}}
    G48[f"{R}/commits/{'c' * 40}/check-runs?per_page=100"] = {"check_runs": [{"name": "tests", "status": "completed", "conclusion": "success"}]}
    G48[f"{R}/issues/116"] = {**G48[f"{R}/issues/116"], "state": "closed", "updated_at": "2026-03-05T03:00:00Z", "closed_by": {"login": "example-owner"}, "pull_request": {"merged_at": "2026-03-05T03:00:00Z"}}
    pass48(); got2 = sorted((e.anchor, e.etype) for e in evs48); evs2 = list(evs48); evs48.clear()
    check("receiver: CI passing again and the PR's merge, tagged ci_passed and pr_merged", got2 == sorted([(A48, "ci_passed"), (A48, "pr_merged")]), got2)
    check("receiver: a later event on the same repo keeps the ID it learnt", {e.repo_id for e in evs2} == {ID_A48}, [e.repo_id for e in evs2])
    G48[f"{R}/issues/116"] = {**G48[f"{R}/issues/116"], "state": "open", "updated_at": "2026-03-05T04:00:00Z", "pull_request": {"merged_at": None}}
    for _k in range(10):                                           # a merged PR is looked at once in 10 passes, so a reopen is seen within 10
        pass48()
        if evs48: break
    got3 = [(e.anchor, e.etype) for e in evs48]; evs48.clear()
    check("receiver: a reopen is tagged pr_reopened (delivered), seen within 10 passes", got3 == [(A48, "pr_reopened")], got3)
finally:
    ghr.subprocess, ghr.threading, ghr.time = _gsub, _gthr, _gtime
# the receiver's real events through the pilot hub: the merges and the CI pass logged, the rest delivered
dl48 = {}
for e in evs1 + evs2:
    hub48.pending.clear(); out48.clear(); hub48.emit(e); dl48[(e.anchor, e.etype)] = bool(out48)
check("receiver → hub: merged and ci_passed on own repos logged; the comment, the review, failing CI and GitHub's CI notice delivered",
      dl48 == {(A48, "ci_failed"): True, (A48, "comment"): True, (AH48, "pr_merged"): False, (AH48, "ci_activity"): True, (AH48, "review"): True,
               (A48, "ci_passed"): False, (A48, "pr_merged"): False}, dl48)
for n in routing.read("projects/alpha"):
    if n.get("pilot") and not n.get("ruling"): routing.rule(n["id"], "dropped", reason="done with the PR-event checks", by="work-osprey")
server._cfg.CFG["pilot"]["own_repos"] = []
(T / "store/anchors.json").write_text(_anc48)

# ---- 48b. [github.moved]: after a repository is transferred to another owner, its old and its new owner/repo are one wherever names are compared.
# Matching only (stored anchors, items and URLs are never rewritten); the table is empty by default and read at each use.
def moved49(tbl):
    g = server._cfg.CFG.setdefault("github", {})
    if tbl is None: g.pop("moved", None)
    else: g["moved"] = tbl
OLD49, NEW49 = "oldowner/thing", "newowner/thing"
TBL49 = {OLD49: NEW49}
oldpr49, newpr49 = lambda n: f"https://github.com/{OLD49}/pull/{n}", lambda n: f"https://github.com/{NEW49}/pull/{n}"
_anc49 = (T / "store/anchors.json").read_text()
def put_anchors49(url, items):
    d = json.loads((T / "store/anchors.json").read_text()); d["projects/alpha"] = d["projects/alpha"] + [{"url": url, "items": items, "added": 1, "by": "t"}]
    (T / "store/anchors.json").write_text(json.dumps(d))
try:
    # the table itself: empty and absent change nothing, a malformed one is ignored, an entry is read per call
    moved49(None)
    check("moved: no table = nothing moved; canon_repo only lower-cases, canon_name leaves a name exactly as written",
          server._cfg.moved_repos() == {} and server._cfg.canon_repo(" Old/Thing ") == "old/thing" and server._cfg.canon_name("Old/Thing") == "Old/Thing" and server._cfg.canon_repo("") == "")
    moved49({})
    check("moved: an empty table = nothing moved", server._cfg.moved_repos() == {} and server._cfg.canon_repo(OLD49) == OLD49 and server._cfg.canon_name(OLD49) == OLD49)
    for why, bad in (("a string", "oldowner/thing = newowner/thing"), ("a list", [OLD49, NEW49]), ("a number", 5)):
        moved49(bad); check(f"moved: a table that is {why} is ignored", server._cfg.moved_repos() == {} and server._cfg.canon_repo(OLD49) == OLD49, server._cfg.moved_repos())
    moved49({"noslash": "a/b", "a/b": "noslash", "a/b/c": "d/e", "o/r": "o/r", "x/y": ["z/w"], "p/q": 7, "": "a/b", "has space/x": "a/b", "a/*": "b/*", "UP/Low": " New/Name "})
    check("moved: malformed entries are ignored one by one (no owner/repo form, a list, a number, a wildcard, itself); a valid one is lower-cased",
          server._cfg.moved_repos() == {"up/low": "new/name"}, server._cfg.moved_repos())
    moved49({"a/b": "c/d", "c/d": "e/f", "x/y": "z/w", "z/w": "x/y", "p/q": "r/s", "r/s": "t/u", "t/u": "p/q", "m/n": "p/q"})
    check("moved: a chain is followed to the end; every entry of a loop (two names or three) is dropped, one leading into a loop stays", server._cfg.canon_repo("A/B") == "e/f" and server._cfg.canon_repo("c/d") == "e/f"
          and server._cfg.moved_repos() == {"a/b": "c/d", "c/d": "e/f", "m/n": "p/q"} and server._cfg.canon_repo("x/y") == "x/y" and server._cfg.canon_repo("p/q") == "p/q" and server._cfg.canon_repo("m/n") == "p/q"
          and server._cfg.repo_aliases("e/f") == {"a/b", "c/d", "e/f"}, (server._cfg.moved_repos(), server._cfg.repo_aliases("e/f")))
    moved49(TBL49)
    check("moved: read per call: a table set now applies at once, and removed it applies no longer", server._cfg.canon_repo(OLD49) == NEW49 and (moved49(None) or server._cfg.canon_repo(OLD49) == OLD49))

    # anchor identity: anchor_id, the anchor store's add and remove
    moved49(None)
    check("anchor_id, no table: the old and the new name are two anchors, a name keeps its case",
          a.anchor_id(oldpr49(5)) == f"github:{OLD49}#5" and a.anchor_id(newpr49(5)) == f"github:{NEW49}#5" and a.anchor_id("https://github.com/Foo/Bar/pull/5") == "github:Foo/Bar#5"
          and a.anchor_id("github:Foo/Bar#5") == "github:Foo/Bar#5")
    st0 = {"projects/alpha": []}; a.add(st0, "projects/alpha", [oldpr49(5), newpr49(5)], ["a1"], "t")
    check("anchors.add, no table: a PR under the old and under the new name is added twice, as before", [e["url"] for e in st0["projects/alpha"]] == [oldpr49(5), newpr49(5)])
    moved49(TBL49)
    ids49 = [a.anchor_id(u) for u in (oldpr49(5), newpr49(5), f"github:{OLD49}#5", f"github:{NEW49}#5", f"https://github.com/{OLD49.upper()}/issues/5")]
    check("anchor_id: the old and the new URL or id of one PR are one id, by the current name", set(ids49) == {f"github:{NEW49}#5"}, ids49)
    check("anchor_id: releases and a repo root too; another repo and a Slack id are untouched",
          a.anchor_id(f"https://github.com/{OLD49}/releases") == a.anchor_id(f"github:{NEW49}@releases") == f"github:{NEW49}@releases"
          and a.anchor_id(f"https://github.com/{OLD49}") == a.anchor_id(f"github:{OLD49}@notifications") == f"github:{NEW49}@notifications"
          and a.anchor_id("https://github.com/other/thing/pull/5") == "github:other/thing#5" and a.anchor_id("https://x.slack.com/archives/C0000000001") == "slack:C0000000001")
    st1 = {"projects/alpha": []}; a.add(st1, "projects/alpha", [oldpr49(5)], ["a1"], "t"); lst1 = a.add(st1, "projects/alpha", [newpr49(5)], ["a2"], "t")
    check("anchors.add: a PR added under the new name resolves to the entry stored under the old one (scope widened), the stored URL unchanged",
          len(lst1) == 1 and lst1[0]["url"] == oldpr49(5) and lst1[0]["items"] == ["a1", "a2"], lst1)
    st1b = {"projects/alpha": []}; a.add(st1b, "projects/alpha", [newpr49(5)], ["a1"], "t"); lst1b = a.add(st1b, "projects/alpha", [oldpr49(5)], None, "t")
    check("anchors.add: …and the reverse (stored under the new name, added under the old; project-wide wins as for the same URL)", len(lst1b) == 1 and lst1b[0]["url"] == newpr49(5) and lst1b[0]["items"] is None, lst1b)
    lst1c = a.add(st1, "projects/alpha", [newpr49(6)], ["a1"], "t")
    check("anchors.add: another PR is another anchor", [e["url"] for e in lst1c] == [oldpr49(5), newpr49(6)], lst1c)
    check("anchors.remove: the new URL removes the entry stored under the old one", a.remove(st1, "projects/alpha", [newpr49(5)]) and [e["url"] for e in st1["projects/alpha"]] == [newpr49(6)])
    d49 = json.loads(_anc49); d49["projects/alpha"] = d49["projects/alpha"] + [{"url": oldpr49(7), "items": ["a1"], "added": 1, "by": "t"}, {"url": newpr49(7), "items": ["a1"], "added": 1, "by": "t"}]
    (T / "store/anchors.json").write_text(json.dumps(d49)); r49 = a.routes(a.load())
    check("anchors.routes: an old-name and a new-name entry of one PR are one anchor id, with no second route", [k for k in r49 if "thing" in k] == [f"github:{NEW49}#7"] and len(r49[f"github:{NEW49}#7"]) == 1, [k for k in r49 if "thing" in k])
    check("core.load_bindings: bound under the current name", set(k for k in core.load_bindings() if "thing" in k) == {f"github:{NEW49}#7"})

    # _pr_items and recycle-due: an old-name anchor and a new-name PR URL (and the reverse)
    item(71, "projects/alpha", A); item(73, "projects/alpha", A)
    put_anchors49(oldpr49(300), ["a71"])
    check("_pr_items: an old-name anchor is found by the new-name PR URL, keyed by the stored URL", server._pr_items([newpr49(300)]) == {oldpr49(300): ["a71"]}, server._pr_items([newpr49(300)]))
    check("_pr_items: …and by the old-name URL, with /files after it; another PR finds nothing", server._pr_items([oldpr49(300) + "/files"]) == {oldpr49(300): ["a71"]} and server._pr_items([newpr49(301)]) == {})
    r_due = server._recycle_due("testbox", pr=newpr49(300))
    check("recycle_due --pr: the new-name URL finds the item anchored under the old name", [(x["item"], x["action"]) for x in r_due["items"]] == [("a71", "set")], r_due)
    put_anchors49(newpr49(310), ["a73"])
    r_due2 = server._recycle_due("testbox", pr=oldpr49(310))
    check("recycle_due --pr: …and the reverse (anchored under the new name, asked by the old)", [(x["item"], x["action"]) for x in r_due2["items"]] == [("a73", "set")], r_due2)
    moved49(None)
    refused49 = ""
    try: server._recycle_due("testbox", pr=newpr49(300))
    except server.ToolError as e: refused49 = str(e)
    check("recycle_due --pr, no table: the new-name URL finds no item anchored under the old name (refused as before)", "no open item is anchored" in refused49, refused49)
    check("_pr_items, no table: nothing crosses names", server._pr_items([newpr49(300)]) == {} and server._pr_items([oldpr49(300)]) == {oldpr49(300): ["a71"]})
    (T / "store/anchors.json").write_text(_anc49)

    # pr_merged checks: one read and one kept answer for the old and the new name of one PR
    moved49(TBL49)
    calls49 = []
    class _Cl49:
        def request(self, method, path, **kw): calls49.append((method, path)); return {"merged": True, "state": "closed"}
    _cg49 = server._check_gh; server._check_gh = lambda repo: (calls49.append(("client", repo)), _Cl49())[1]
    try:
        gh49 = {}; ok1 = server._pr_merged(f"{OLD49}#7", 1000.0, gh49); ok2 = server._pr_merged(f"{NEW49}#7", 1001.0, gh49)
    finally: server._check_gh = _cg49
    check("pr_merged: the old and the new name of one PR share one GET (at the current name) and one kept answer", ok1 == (True, "") and ok2 == (True, "") and list(gh49) == [f"{NEW49}#7"]
          and calls49 == [("client", NEW49), ("GET", f"/repos/{NEW49}/pulls/7")], (calls49, list(gh49)))
    gh49 = {f"{NEW49}#8": {"dead": "its pull request was closed without being merged"}}
    check("pr_merged: a check written with the old name reads the answer kept under the new one (dead check, kept refs)", server._check_dead(f"pr_merged {OLD49}#8", gh49).startswith("its pull request")
          and server._check_ref(f"{OLD49}#8") == f"{NEW49}#8" and server._check_ref("Foo/Bar#8") == "Foo/Bar#8" and server._check_ref("nonsense") == "nonsense")
    moved49(None)
    check("pr_merged, no table: the ref is kept exactly as written", server._check_ref(f"{OLD49}#8") == f"{OLD49}#8" and server._check_dead(f"pr_merged {OLD49}#8", {f"{NEW49}#8": {"dead": "x"}}) == "")

    # release-green, log-only: origin old and PR new, and the reverse
    moved49(TBL49); server._OWN_REPO[:] = [OLD49]
    check("release green ok: origin old, PR new", server._release_green_ok("release", newpr49(113)) and server._release_green_ok("release", oldpr49(113)))
    server._OWN_REPO[:] = [NEW49]
    check("release green ok: origin new, PR old (and new)", server._release_green_ok("release", oldpr49(113)) and server._release_green_ok("release", newpr49(113)))
    check("release green ok: still only release's own report of a PR of this repo", not server._release_green_ok("size-watch", newpr49(113)) and not server._release_green_ok("release", "https://github.com/someone/else/pull/113")
          and not server._release_green_ok("release", "") and not server._release_green_ok("release", f"https://github.com/{NEW49}/issues/113"))
    GREEN49 = "[release] PR #113 merged and deployed — a change — main at 0606060, restarted: stackshot.service, healthz ok · log /x/pr-113.log"
    for origin49, pr49, what49 in ((OLD49, newpr49(113), "origin old, PR new"), (NEW49, oldpr49(113), "origin new, PR old")):
        server._OWN_REPO[:] = [origin49]; n0 = len(wait_push(0))
        st, body = server._client_post("testbox", "message", {"to": "projects/alpha", "text": GREEN49, "sender": "release", "release": "green", "pr": pr49})
        check(f"green release, {what49}: logged, not delivered, ruled merged by stackshot (auto)", st == 200 and str(body.get("result")).startswith("logged, not delivered") and "ruled merged by stackshot (auto)" in body["result"]
              and len(wait_push(0)) == n0, (st, body))
    moved49(None); server._OWN_REPO[:] = [OLD49]; n0 = len(wait_push(0))
    st, body = server._client_post("testbox", "message", {"to": "projects/alpha", "text": GREEN49, "sender": "release", "release": "green", "pr": newpr49(113)})
    check("green release, no table: origin old, PR new is not this repo's PR, held for the router as before", not str(body.get("result")).startswith("logged, not delivered"), body)
    server._OWN_REPO[:] = ["example-owner/stackshot"]
    for n in routing.read("projects/alpha"):
        if n.get("pilot") and not n.get("ruling"): routing.rule(n["id"], "dropped", reason="done with the [github.moved] checks", by="work-osprey")
    wait_push(0)

    # [pilot] own_repos by name, across names
    moved49(TBL49)
    check("own_repos: an old-name entry matches a new-name repository, and the reverse; owner/* sees the owner a moved repo had",
          core.is_own(NEW49, [OLD49]) and core.is_own(OLD49, [NEW49]) and core.is_own(NEW49, [NEW49]) and core.is_own(OLD49, ["newowner/*"]) and core.is_own(NEW49, ["oldowner/*"])
          and core.is_own(NEW49, ["newowner/*"]) and core.is_own(NEW49, [str(ID_A48), OLD49]))
    check("own_repos: …but not another repo of either owner under an owner/* of the other, nor an unrelated name",
          not core.is_own("newowner/other", ["oldowner/*"]) and not core.is_own("oldowner/other", ["newowner/*"]) and not core.is_own("newowner/other", [OLD49]) and not core.is_own("evil/thing", [OLD49]) and not core.is_own("", [OLD49]))
    check("repo_of: an old-name anchor reads as the current name", core.repo_of(f"github:{OLD49}#5") == core.repo_of(f"github:{NEW49}@releases") == NEW49 and core.repo_of("slack:C1") == "")
    ev49 = lambda anchor, et: core.Event(anchor=anchor, kind="github-state", title="x", who="w", text="merged it", url="u", ts="1", etype=et)
    server._cfg.CFG["pilot"]["own_repos"] = [OLD49]
    r_a = core.routine_own(ev49(f"github:{NEW49}#5", "pr_merged"))
    server._cfg.CFG["pilot"]["own_repos"] = [NEW49]
    r_b = core.routine_own(ev49(f"github:{OLD49}#5", "pr_merged"))
    check("routine_own: a new-name event on an own_repos entry written with the old name is routine, and the reverse", r_a.startswith("log-only: pr_merged on newowner/thing") and r_b.startswith("log-only: pr_merged on newowner/thing"), (r_a, r_b))
    moved49(None)
    server._cfg.CFG["pilot"]["own_repos"] = [OLD49]; r_c = core.routine_own(ev49(f"github:{NEW49}#5", "pr_merged"))
    server._cfg.CFG["pilot"]["own_repos"] = [NEW49]; r_d = core.routine_own(ev49(f"github:{OLD49}#5", "pr_merged"))
    check("routine_own, no table: an entry with the other name does not cover the repository", r_c == "" and r_d == "", (r_c, r_d))
    server._cfg.CFG["pilot"]["own_repos"] = []

    # the hub's direct lane is keyed by the current name
    moved49(TBL49); server._cfg.CFG.setdefault("anchor_hub", {})["direct"] = {f"github:{OLD49}#8": "none"}
    check("direct: a key written with the old name is found by the new-name anchor", core.direct().get(f"github:{NEW49}#8") == "none" and f"github:{OLD49}#8" not in core.direct(), core.direct())
    server._cfg.CFG["anchor_hub"].pop("direct", None)

    # the hub's dedupe: a notification thread of a PR (or a release) another anchor reports, under the other name
    caught48.clear(); evs49 = []
    ghr.subprocess = _types.SimpleNamespace(run=_gh48)
    ghr.threading = _types.SimpleNamespace(Thread=lambda target, daemon=True: _types.SimpleNamespace(start=lambda: caught48.append(target)))
    ghr.time = _types.SimpleNamespace(time=time.time, sleep=_no_sleep)
    def th49(i, typ, url, reason="subscribed", at="2026-03-05T00:00:00Z"): return {"id": i, "updated_at": at, "reason": reason, "subject": {"type": typ, "url": url, "title": "t " + i}}
    for bound49, what49 in (({f"github:{NEW49}@notifications": {S}, f"github:{OLD49}#12": {S}, f"github:{OLD49}@releases": {S}}, "bound under the old name, notifications under the new"),
                            ({f"github:{OLD49}@notifications": {S}, f"github:{NEW49}#12": {S}, f"github:{NEW49}@releases": {S}}, "bound under the new name, notifications under the old"),
                            ({f"github:{NEW49}@notifications": {S}, f"github:{NEW49}#12": {S}, f"github:{NEW49}@releases": {S}}, "all under one name")):
        notif49 = next(k for k in bound49 if k.endswith("@notifications")); nrepo49 = notif49[7:-14]
        NOT49 = f"/repos/{nrepo49}/notifications?all=true&per_page=50"
        G48.clear(); G48.update({"/user": {"login": "example-owner"}, NOT49: [th49("t1", "PullRequest", f"https://api.github.com/repos/{nrepo49}/pulls/12"), th49("t2", "Release", f"https://api.github.com/repos/{nrepo49}/releases/9"),
                                                                          th49("t3", "CheckSuite", "", reason="ci_activity")]})
        h49 = core.Hub(); h49.write_status = lambda: None; h49.emit = lambda ev: evs49.append(ev); h49.bindings = dict(bound49); evs49.clear(); caught48.clear()
        ghr.run(h49); pass48()                                         # the first pass seeds
        G48[NOT49] = [{**x, "updated_at": "2026-03-05T02:00:00Z"} for x in G48[NOT49]]
        pass48()
        check(f"hub dedupe ({what49}): the PR's and the release's threads are not reported again by the notifications anchor; GitHub's own CI notice still is",
              [e.etype for e in evs49 if e.anchor == notif49] == ["ci_activity"], [(e.anchor, e.etype) for e in evs49])
    # state across a reload that adds the pair: a CI run in flight, and a merge in the gap, are still reported under the new name; nothing is left under the old id
    PRO, PRN = f"/repos/{OLD49}", f"/repos/{NEW49}"; A_OLD, A_NEW = f"github:{OLD49}#20", f"github:{NEW49}#20"
    def pr20(path_prefix, sha, conclusion, status, state, merged):
        G48.clear(); G48.update({"/user": {"login": "example-owner"}, f"{path_prefix}/pulls/20": {"head": {"sha": sha}},
                                 f"{path_prefix}/commits/{sha}/check-runs?per_page=100": {"check_runs": [{"name": "tests", "status": status, "conclusion": conclusion}]},
                                 f"{path_prefix}/issues/20": {"state": state, "comments": 0, "updated_at": "2026-03-05T00:00:00Z", "title": "a change", "html_url": f"https://github.com/{NEW49}/pull/20",
                                                              "pull_request": {"merged_at": "2026-03-05T01:00:00Z" if merged else None}}})
    moved49(None)
    h50 = core.Hub(); h50.write_status = lambda: None; h50.emit = lambda ev: evs49.append(ev); h50.bindings = {A_OLD: {S}}; evs49.clear(); caught48.clear()
    pr20(PRO, "c" * 40, "success", "completed", "open", False); ghr.run(h50); pass48()      # seeded under the old name: a finished run, then a new commit whose check is still running
    pr20(PRO, "d" * 40, None, "in_progress", "open", False); pass48()
    moved49(TBL49); h50.bindings = {A_NEW: {S}}                                               # a config reload adds the pair; the bindings now carry the new id
    pr20(PRN, "d" * 40, "failure", "completed", "closed", True); pass48()
    check("state across a reload that adds the pair: the run in flight finishes failed and the merge in the gap is reported, both under the new id",
          sorted((e.anchor, e.etype) for e in evs49) == sorted([(A_NEW, "ci_failed"), (A_NEW, "pr_merged")]), [(e.anchor, e.etype) for e in evs49])
    gs50 = h50.gh_state
    check("…and no entry is left under the old id", A_OLD not in gs50["ci"] and A_OLD not in gs50["state"] and A_NEW in gs50["ci"] and A_NEW in gs50["state"], (list(gs50["ci"]), list(gs50["state"])))
    moved49(None)
    check("…and with the table emptied again nothing moves back or twice (the new id keeps its state)", (lambda: (pass48(), A_NEW in gs50["state"] and A_OLD not in gs50["state"])[1])())
    # the same through saved state: a restart with the pair already in the config reads the entries stored under the old id
    moved49(TBL49); evs49.clear(); caught48.clear()
    h51 = core.Hub(); h51.write_status = lambda: None; h51.emit = lambda ev: evs49.append(ev); h51.bindings = {A_NEW: {S}}
    h51.saved = {"github": {"state": {A_OLD: {"state": "open", "comments": 0, "updated": "2026-03-05T00:00:00Z"}}, "ci": {A_OLD: {"pr": True, "sha": "e" * 40, "key": ["c" * 40, []]}}}}
    pr20(PRN, "e" * 40, "failure", "completed", "open", False); ghr.run(h51); pass48()
    check("saved state stored under the old id is read under the new one at start: the failure is reported", [(e.anchor, e.etype) for e in evs49] == [(A_NEW, "ci_failed")], [(e.anchor, e.etype) for e in evs49])
    check("…and the entries are keyed by the new id", list(h51.gh_state["ci"]) == [A_NEW] and list(h51.gh_state["state"]) == [A_NEW], (list(h51.gh_state["ci"]), list(h51.gh_state["state"])))
    moved49(None)
    for bound49 in ({f"github:{NEW49}@notifications": {S}, f"github:{OLD49}#12": {S}, f"github:{OLD49}@releases": {S}},):
        NOT49 = f"/repos/{NEW49}/notifications?all=true&per_page=50"
        G48.clear(); G48.update({"/user": {"login": "example-owner"}, NOT49: [th49("t2", "Release", f"https://api.github.com/repos/{NEW49}/releases/9")]})
        h49 = core.Hub(); h49.write_status = lambda: None; h49.emit = lambda ev: evs49.append(ev); h49.bindings = dict(bound49); evs49.clear(); caught48.clear()
        ghr.run(h49); pass48(); G48[NOT49] = [{**x, "updated_at": "2026-03-05T02:00:00Z"} for x in G48[NOT49]]; pass48()
        check("hub dedupe, no table: a release bound under the other name is not deduped (the notification is reported, as before)", len([e for e in evs49 if e.anchor == f"github:{NEW49}@notifications"]) == 1,
              [(e.anchor, e.etype) for e in evs49])
finally:
    ghr.subprocess, ghr.threading, ghr.time = _gsub, _gthr, _gtime
    moved49(None); server._OWN_REPO[:] = ["example-owner/stackshot"]; server._cfg.CFG["pilot"]["own_repos"] = []; server._cfg.CFG.get("anchor_hub", {}).pop("direct", None)
    (T / "store/anchors.json").write_text(_anc49)

# ---- the owner hears what another session changed ([board] tell_owner; a builder's `next` on another
# session's item, or a non-owner's close, is told to the owner at once). The switch is off for every check above.
server._cfg.CFG["board"]["tell_owner"] = True
server._cfg.CFG["pilot"]["writer_owes_page"] = True     # every page is the router's, so a write would also relay a page-owed notice to the keeper at once; the writer owes it here, and the pushes counted below are the owner notices only
server._refuse_if_owing = lambda debtor: None        # the page rule is not under test here
Xn = "work-osprey-x"
def told_owner(to, g):
    """The [board] lines this section's notices put to one session for one item (the pilot relay's own lines start `[board] a1 changed`)."""
    return [m for m in wait_push(0) if m[0] == to and m[1].startswith(f"[board] {g} [home] item ")]
for i_, o_ in ((78, B), (79, B), (93, server.OWNER), (94, "Kim Lee")): item(i_, "projects/beta", o_)
item(95, "projects/alpha", A)
time.sleep(0.3); n0 = len(wait_push(0))
res = server._update("a78", next="Live since 09:15", sender=Xn); wait_push(n0 + 1); time.sleep(0.3)
t1 = told_owner(B, "a78")
check("tell owner: a non-owner's change to next tells the owner once, in the notice's form, with the item's link",
      len(t1) == 1 and t1[0][1] == "[board] a78 [home] item 78: work-osprey-x set next: Live since 09:15 → https://stackshot.example.com/items/a78"
      and "(its mover home-beta has been told)" in res, (t1, res[-200:]))
n1 = len(wait_push(0)); res = server._update("a78", next="Rolled back at 09:40\nsecond line", sender=Xn); time.sleep(0.5)
check("tell owner: a second change inside ten minutes sends no second notice, and the reply says nothing of it", len(told_owner(B, "a78")) == 1 and len(wait_push(0)) == n1 and "has been told" not in res, (told_owner(B, "a78"), res[-200:]))
server._OWNER_HEARD[("a78", B)] -= 601; n1 = len(wait_push(0))
res = server._update("a78", next="Rolled back at 09:50\nsecond line", sender=Xn); wait_push(n1 + 1); time.sleep(0.3)
t3 = told_owner(B, "a78")
check("tell owner: after the ten minutes the next change is told again, naming only the first line of next", len(t3) == 2 and "set next: Rolled back at 09:50 →" in t3[1][1] and "second line" not in t3[1][1], t3)
server._OWNER_HEARD[("a78", B)] -= 601; n1 = len(wait_push(0))
res = server._update("a78", priority="p1", sender=Xn); time.sleep(0.5)
res2 = server._update("a78", description="- Goal: A thing\n- It lives here, now live\n- Done when it is on the board", sender=Xn); time.sleep(0.5)
check("tell owner: a filing edit (priority) and a rewritten description send nothing", len(told_owner(B, "a78")) == 2 and len(wait_push(0)) == n1, (told_owner(B, "a78"), wait_push(0)[n1:]))
n1 = len(wait_push(0)); res = server._update("a78", needs=["external"], sender=Xn); wait_push(n1 + 1); time.sleep(0.3)
t5 = told_owner(B, "a78")
check("tell owner: a change of needs is told (the window had expired), as 'changed needs: …'", len(t5) == 3 and "work-osprey-x changed needs: external →" in t5[2][1], t5)
server._OWNER_HEARD[("a78", B)] -= 601; n1 = len(wait_push(0))
res = server._update("a78", next="its own step", sender="home-beta"); time.sleep(0.5)
check("tell owner: the owner's own update sends nothing", len(told_owner(B, "a78")) == 3 and len(wait_push(0)) == n1 and "has been told" not in res, (told_owner(B, "a78"), res[-200:]))
n1 = len(wait_push(0)); res = server.stackshot_complete("a78", sender=Xn, outcome="done", reason="it is live", description="- Goal: The thing is live"); wait_push(n1 + 1); time.sleep(0.3)
t6 = [m for m in wait_push(0) if m[0] == B and m[1].startswith("[stackshot] a78 was completed")]
check("tell owner: a non-owner's close tells the owner at once even inside the window, though the item is closed, with the outcome and the reason (every page is a router page: the close notice of _tell_owner, once, and no second '[board]' line)",
      len(told_owner(B, "a78")) == 3 and len(t6) == 1 and t6[0][1] == "[stackshot] a78 was completed (done: it is live) by work-osprey-x: [home] item 78 → https://stackshot.example.com/items/a78" and rd("a78")["status"] == "completed", (t6, told_owner(B, "a78")))
n1 = len(wait_push(0)); res = server.stackshot_complete("a79", sender=Xn, outcome="dropped", reason="not needed", description="- Goal: Dropped"); wait_push(n1 + 1); time.sleep(0.3)
t7 = [m for m in wait_push(0) if m[0] == B and m[1].startswith("[stackshot] a79 was completed")]
check("tell owner: …and a close with no change before it is told too", len(t7) == 1 and "(dropped: not needed) by work-osprey-x" in t7[0][1] and not told_owner(B, "a79"), (t7, told_owner(B, "a79")))
n1 = len(wait_push(0)); server._update("a93", next="a step", sender=Xn); server._update("a94", next="a step", sender=Xn); time.sleep(0.5)
check("tell owner: an item Oliver moves, or one whose mover is no session, tells no one named Oliver or Kim; the project's default holder (here its keeper) hears the one change", not told_owner(server.OWNER, "a93") and not told_owner("Kim Lee", "a94") and len(wait_push(0)) <= n1 + 2, wait_push(0)[n1:])

def to_page(n1): return [m for m in wait_push(0)[n1:] if "may need to act" in m[1]]
# the reviewer's five scenarios, and the page key's own cases: one event makes at most one inbound
P_, Y_ = "55555555-5555-4555-8555-555555555555", "66666666-6666-4666-8666-666666666666"
_rg9 = json.loads((T / "store/projects.json").read_text())
_rg9["pages"]["projects/alpha"].update(agents={"work-osprey-main": "front", "work-osprey-y": "back"}, back_agents={"work-osprey-y": "back"})
_rg9["pages"]["projects/epsilon"] = {**_rg9["pages"]["projects/beta"], "title": "Epsilon", "name": "Epsilon", "session": ""}      # a page with no keeper, agent or stand-in
_rg9["pages"]["projects/delta"] = {**_rg9["pages"]["projects/beta"], "title": "Delta", "name": "Delta", "session": "work-osprey-x"}      # a plain page whose keeper is a pane that is no front agent
_rg9["pages"]["projects/beta"].update(agents={"home-beta-main": "front", "home-beta-ops": "back"}, back_agents={"home-beta-ops": "back"})   # beta: a page of user-facing agents with no router, so its stand-in is its -main agent
(T / "store/projects.json").write_text(json.dumps(_rg9))
_sj = json.loads((T / "fleet/a/sessions.json").read_text()); _sj[P_] = {"name": "plain-owner", "machine": "a", "url": "", "seen": "x"}; _sj[Y_] = {"name": "plain-y", "machine": "a", "url": "", "seen": "x"}
(T / "fleet/a/sessions.json").write_text(json.dumps(_sj))
def item2(i, proj, owner, **m): (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": "A thing. It lives here. Done when done.", "status": "open", "metadata": {"owner": owner, "mover": owner, "project": proj, "next": "orig", **m}, "updated": 1, "state_updated": 1, "confirmed": 1}))
mine = lambda g: [m for m in wait_push(0) if m[1].startswith(f"[board] {g} [home] item ")]
item2(10, "projects/alpha", P_)
n1 = len(wait_push(0)); res = server._update("a10", next="builder step", sender="work-osprey-y"); time.sleep(0.7)
to_p = [m for m in wait_push(0)[n1:] if m[0] in (P_, "plain-owner")]
check("tell owner: a background agent's first write names it in needs and tells the owner once ('now names'), not again as a needs change",
      len(to_p) == 1 and "a10 now names work-osprey-y in its needs" in to_p[0][1] and not mine("a10") and res.count("its mover plain-owner has been told") == 1, (to_p, res[-300:]))
item2(12, "projects/alpha", P_, needs=["decision", P_], ask="Decide: pick · Recommend: a · Stakes: none · By: no date")
n1 = len(wait_push(0)); res = server._update("a12", needs=[P_], sender="plain-y"); time.sleep(0.7)
to_p = [m for m in wait_push(0)[n1:] if m[0] in (P_, "plain-owner")]
check("tell owner: the decision leaving the needs tells the named owner once ('has decided'), not again as a needs change",
      len(to_p) == 1 and "a12: " in to_p[0][1] and "has decided" in to_p[0][1] and not mine("a12"), (to_p, res[-300:]))
item2(15, "projects/alpha", A); item2(16, "projects/alpha", A); item2(17, "projects/alpha", A)
n1 = len(wait_push(0)); res = server._update("a15", next="the keeper changes the front owner's next", sender="work-osprey"); time.sleep(0.7)
check("tell owner: the project's keeper changing a front agent owner's next sends nothing to the page key", not to_page(n1) and "went to projects/alpha" not in res, (wait_push(0)[n1:], res[-200:]))
n1 = len(wait_push(0)); res = server.stackshot_complete("a16", sender="work-osprey", outcome="done", reason="the keeper closes", description="- Goal: Done"); time.sleep(0.7)
check("tell owner: the keeper closing a front agent owner's item sends nothing to the page key, the quiet line standing", not to_page(n1) and "went to projects/alpha" not in res, (wait_push(0)[n1:], res[-200:]))
n1 = len(wait_push(0)); res = server.stackshot_complete("a17", sender="plain-y", outcome="done", reason="plain closes", description="- Goal: Done"); time.sleep(0.7)
check("tell owner: a close by another session on a front agent's item that is also its project's keeper (no builder) reaches the owner in its one marked line (_tell_owner_close) and sends nothing to the page key",
      not to_page(n1) and [m[1] for m in wait_push(0)[n1:] if m[0] == A] == ["[for the owner] [stackshot] a17 [home] item 17: closed by plain-y: done (plain closes) → https://stackshot.example.com/items/a17"], (wait_push(0)[n1:], res[-200:]))
# a front agent owner whose write no relay carried (outside the pilot): the page key, through its keeper or stand-in, once
_NOTE = lambda g, n, what: f"[board] {g} [home] item {n[1:]}: plain-y {what} (mover work-osprey-main may need to act) → https://stackshot.example.com/items/{g}"
item2(18, "projects/delta", A)
general(True)
n1 = len(wait_push(0)); res = server._update("a18", next="the front owner's next", sender="plain-y"); time.sleep(0.7); got_res_delta = res
got = to_page(n1)
nd = [x for x in routing.read("projects/delta") if x["kind"] == "message" and "may need to act" in x["text"]]
check("tell owner: a front agent owner's change that no relay carried (a next change is no state change) goes to the project's page key once, saying the owner may need to act: held for the router in the routing log, stashed for it, nobody pushed",
      not got and len(nd) == 1 and nd[0]["to"] == "" and nd[0].get("live") is True and _NOTE("a18", "a18", "set next: the front owner's next") in (router_live.stashed(nd[0]["id"]) or "") and "the notice went to projects/delta, where the router rules it" in res
      and "not told; the board shows it" not in res, (wait_push(0)[n1:], nd, res[-300:]))
check("tell owner: …naming no builder in the item's needs (the page key's delivery is not the message tool's)", "needs" not in rd("a18")["metadata"], rd("a18")["metadata"])
n1 = len(wait_push(0)); server._update("a18", next="a second front change", sender="plain-y"); time.sleep(0.5)
check("tell owner: …and a second change inside ten minutes sends no second inbound", not to_page(n1) and len([x for x in routing.read("projects/delta") if x["kind"] == "message" and "may need to act" in x["text"]]) == 1, wait_push(0)[n1:])
item2(19, "projects/delta", A); n1 = len(wait_push(0)); res = server.stackshot_complete("a19", sender="plain-y", outcome="done", reason="front owner's item closed", description="- Goal: Done"); time.sleep(0.7)
check("tell owner: a close of a front agent owner's item no relay carried is told to the owner itself, once, marked, and not also to the page key; the 'not told' line is gone",
      not to_page(n1) and [m[1] for m in wait_push(0)[n1:] if m[0] == A] == ["[for the owner] [stackshot] a19 [home] item 19: closed by plain-y: done (front owner's item closed) \u2192 https://stackshot.example.com/items/a19"]
      and "not told; the board shows it" not in res and "told at once that it was closed" in res, (wait_push(0)[n1:], res[-300:]))
# a builder's step on a front agent owner's item is never pushed to the owner
item2(129, "projects/alpha", A, needs=[Xn], next=f"{Xn}: w"); item2(142, "projects/alpha", A, needs=["external", Xn])
n1 = len(wait_push(0)); res1 = server._update("a129", work={"state": "done"}, sender=Xn); time.sleep(0.7); res2 = server._update("a142", needs=["external"], next="builder done", sender=Xn); time.sleep(0.7)
check("tell owner: a builder marking its last step done by a status done, or taking itself out of needs, sends the front agent owner nothing and the reply promises nothing (no step line)",
      not [m for m in wait_push(0)[n1:] if m[0] in (A, "work-osprey-main") and re.search(r"a987[01]\b", m[1])] and "told at once" not in res1 + res2 and "step came back" not in res1 + res2, (wait_push(0)[n1:], res1[-200:], res2[-200:]))
general(False)      # a page with no agent of its own and no scope general behind it
item2(20, "projects/epsilon", A); n1 = len(wait_push(0)); res = server._update("a20", next="no page behind it", sender=Xn); time.sleep(0.5)
check("tell owner: a front agent owner's item on a page with no keeper or stand-in sends nothing and records no undelivered notice", not to_page(n1) and "undelivered" not in rd("a20")["metadata"] and "went to" not in res, (wait_push(0)[n1:], rd("a20")["metadata"]))
_rec = server._routing.record
def _boom(*a, **k): raise OSError("disk full")
server._routing.record = _boom
item2(22, "projects/delta", A); n1 = len(wait_push(0)); res = server._update("a22", next="when the log cannot be written", sender="plain-y"); time.sleep(0.5)
server._routing.record = _rec
general(False)
check("tell owner: when the routing record cannot be written nothing is pushed (no fall-through to a push naming a builder), and the write goes through",
      not to_page(n1) and rd("a22")["metadata"]["next"].endswith("when the log cannot be written") and "needs" not in rd("a22")["metadata"], (wait_push(0)[n1:], rd("a22")["metadata"]))
server._cfg.CFG["board"]["tell_owner"] = False; item(95, "projects/beta", B); n1 = len(wait_push(0))
server._update("a95", next="with the switch off", sender=Xn); server.stackshot_complete("a95", sender=Xn, outcome="done", reason="closed with it off", description="- Goal: Done"); time.sleep(0.5)
check("tell owner: with [board] tell_owner = false neither a next change nor a close sends a '[board]' line: the close is told once by the older close notice alone",
      not told_owner(B, "a95") and [m[1] for m in wait_push(0)[n1:] if m[0] == B] == ["[stackshot] a95 was completed (done: closed with it off) by work-osprey-x: [home] item 95 \u2192 https://stackshot.example.com/items/a95"], wait_push(0)[n1:])
server._cfg.CFG["board"]["tell_owner"] = True

# the keepers are retired: with home-beta's pane not running, a non-pilot page of user-facing agents answers its page key with its -main agent,
# a front agent. Nothing is ever pushed to a front agent, the owner itself included; the reply says the board shows it (the reviewer's A, A2, B, K)
_sj2 = json.loads((T / "fleet/a/sessions.json").read_text()); _sj2.pop(B, None); (T / "fleet/a/sessions.json").write_text(json.dumps(_sj2))
_rg10 = json.loads((T / "store/projects.json").read_text()); _rg10["pages"]["projects/beta"]["agents"]["home-beta-two"] = "front"; (T / "store/projects.json").write_text(json.dumps(_rg10))
FRONTS = {A, "work-osprey-main", "home-beta-main", "home-beta-two"}
QB = "(its mover {} is a front agent: not told; the board shows it)"
def to_front(n1): return [m for m in wait_push(0)[n1:] if m[0] in FRONTS]
replies = []
item2(23, "projects/beta", "home-beta-main"); n1 = len(wait_push(0)); res = server._update("a23", next="x step", sender="plain-y"); time.sleep(0.7); replies.append(res)
check("tell owner: a front agent owner who is also the page key's stand-in is pushed nothing: the notice goes to the page key, where the router rules it (once), not 'the board shows it'",
      not to_front(n1) and not to_page(n1) and res.count("the notice went to projects/beta, where the router rules it") == 1 and QB.format("home-beta-main") not in res, (wait_push(0)[n1:], res[-300:]))
item2(24, "projects/beta", "home-beta-two"); n1 = len(wait_push(0)); res = server._update("a24", next="x step", sender="plain-y"); time.sleep(0.7); replies.append(res)
check("tell owner: a second front agent owner, the page key's stand-in being the -main agent, is pushed nothing, and the reply says the router has it",
      not to_front(n1) and not to_page(n1) and res.count("the notice went to projects/beta, where the router rules it") == 1 and QB.format("home-beta-two") not in res, (wait_push(0)[n1:], res[-300:]))
item2(26, "projects/beta", "home-beta-main"); n1 = len(wait_push(0)); res = server._update("a26", next="bg step", sender="home-beta-ops"); time.sleep(0.7); replies.append(res)
check("tell owner: a background agent's first write on a front agent owner's item (it names itself in needs) pushes nothing to a front agent, and the reply says once that the router has it",
      not to_front(n1) and not to_page(n1) and res.count("the notice went to projects/beta, where the router rules it") == 1 and "not told" not in res, (wait_push(0)[n1:], res[-400:]))
item2(27, "projects/beta", "home-beta-main"); n1 = len(wait_push(0))
res = server._update("a27", needs=["decision"], ask="Decide: a or b · Recommend: yes · Stakes: none · By: no date", sender="plain-y"); time.sleep(0.7); replies.append(res)
check("tell owner: a move to needs=decision on a front agent owner's item outside the pilot is told to nobody, and the reply says so once",
      not to_front(n1) and not to_page(n1) and res.count("not told; the board shows it") == 1, (wait_push(0)[n1:], res[-300:]))
item2(28, "projects/alpha", A); n1 = len(wait_push(0))
res = server._update("a28", needs=["decision"], ask="Decide: a or b · Recommend: yes · Stakes: none · By: no date", sender="plain-y"); time.sleep(0.7); replies.append(res)
check("tell owner: …and in the pilot too (the older rule), with no 'may need to act' line", not to_page(n1) and not [m for m in wait_push(0)[n1:] if m[0] == A], (wait_push(0)[n1:], res[-300:]))
# a reopen is told inside the window that a close opened
item2(29, "projects/beta", P_); n1 = len(wait_push(0))
server._update("a29", next="n1", sender="plain-y"); server.stackshot_complete("a29", sender="plain-y", outcome="done", reason="r", description="- Goal: Done")
res = server._update("a29", status="open", next="reopened step", sender="plain-y"); wait_push(n1 + 3); time.sleep(0.5); replies.append(res)
t_ = [m[1] for m in wait_push(0)[n1:] if m[0] in (P_, "plain-owner", B, "home-beta-main", "home-beta-ops") and m[1].startswith(("[board] a29 [home] item ", "[stackshot] a29 "))]
check("tell owner: set next and the close are told to the mover (each once); the reopen is not: a close drops the mover, the item falls to the project's default holder, a front agent, which is not pushed",
      len(t_) == 2 and sum(m_.startswith("[board] a29") and "set next: n1 \u2192" in m_ for m_ in t_) == 1 and sum(m_.startswith("[stackshot] a29 was completed (done: r) by plain-y") for m_ in t_) == 1
      and not any("was reopened" in m_ for m_ in t_), t_)    # each notice goes out on its own thread: the order varies
check("tell owner: no reply says both 'not told' and 'the notice went to'", not [r_ for r_ in replies if "not told; the board shows it" in r_ and "the notice went to" in r_] and "not told" not in got_res_delta, replies[-1][-300:])

_froms = [json.loads(l) for l in from_log.read_text().splitlines()]
check("every push from the server passes --from", _froms and None not in _froms, _froms)
check("stackshot's own notices are from stackshot, a message from its sender", "stackshot" in _froms and "home-beta" in _froms, sorted(set(map(str, _froms))))

print(f"ok: pilot scenario, {len(ran)} checks" if not fails else f"{len(fails)} check(s) failed"); sys.stdout.flush(); os._exit(1 if fails else 0)
