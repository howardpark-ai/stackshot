"""Scenario test for the router acting on notices (router_live.py; stackshot.toml [router] general_home, general_ops, general_work,
live_tick_seconds) on fixture data -- no live store, no network, never the real `claude` (a fake script answers the thin call) and never
a real pane (push.py is a fake that logs what it was asked to deliver).

The router rules every project page: there is no live switch, no pilot list and no rollback to keepers. Fixture pages:
`projects/alpha` (a -main agent, a second front agent, a builder and a page-keeping background agent), `projects/gamma` (-main),
`projects/delta` (no agent: it falls to the scope's general -main), `projects/beta` (one session), a hub with a sub-page, and the
work-/ops- pages for the scope fallback. Covers: a message to a project, an anchor-hub notice, a board relay and a wake are
recorded for the router and delivered to nobody; the tick's pass (delivered to the target, with the mark only for a front agent and a
notice for Oliver), dropped / merged / held (ruled, nothing delivered); a failed judgment goes to -main with the mark; the
stand-in (builder, else the page's -main, else the hub's -main, else the scope's general -main: home-, work-, ops-) and the
`general_*` config keys; a page with no agent anywhere holds the notice and refuses a message; a leftover `[router] live = false` or
`[pilot] projects` is ignored; a failed delivery is retried and then goes to -main; a hold waiting on an anchor is released by the
router's ruling; the status line; a ruling's `note` written to the page's timeline once (a gbrain failure logged, `notes = false`);
the cap of three writes of a ruling, then stuck; the status line.

The audit's batch finding (`projects/zeta`: three front agents and a background agent): each item's lines go to that item's owner, one
message per owner, -main getting its own items, those of an owner that is no agent of the project and the lines that are no finding;
a batch whose items one agent owns goes whole to it; an owner that cannot be reached is retried alone.

    tests/run-suite router_live        → exit 0 / 1"""
import json, os, re, sys, threading, time, pathlib, tempfile, logging, subprocess, types
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="routerlivetest-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"), gbrain=True)
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
toml = toml.replace('lanes_file = ""', f'lanes_file = "{tmp}/sala/lanes.tsv"', 1); assert f'lanes_file = "{tmp}/sala/lanes.tsv"' in toml
toml = toml.replace('limit_file = ""', f'limit_file = "{tmp}/sala/limit.json"', 1); assert f'limit_file = "{tmp}/sala/limit.json"' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"),
                 ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^owner = "the owner"', 'owner = "Oliver"', toml); assert n == 1
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1   # this suite is about the live router, its writes replace next wholesale; the checklist has its own suite: checklist
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet")
PL = "88888888-8888-4888-8888-888888888888"
AU, ZS = "99999999-9999-4999-8999-999999999999", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
S, A, B, X, G, D, DOC = ("11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222", "33333333-3333-4333-8333-333333333333",
                         "44444444-4444-4444-8444-444444444444", "55555555-5555-4555-8555-555555555555", "66666666-6666-4666-8666-666666666666",
                         "77777777-7777-4777-8777-777777777777")
EM = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
for d in ("store/a", "fleet/a", "state/anchor-hub", "state/site", "secrets", "touch", "repo", "sala", "brain/projects"): (T / d).mkdir(parents=True)
(T / "state/site/favicon.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"/>')
(T / "fleet/a/sessions.json").write_text(json.dumps({S: {"name": "work-osprey", "machine": "a", "url": "", "seen": "x"}, A: {"name": "work-osprey-main", "machine": "a", "url": "", "seen": "x"},
                                                      B: {"name": "home-beta", "machine": "a", "url": "", "seen": "x"}, X: {"name": "work-osprey-x", "machine": "a", "url": "", "seen": "x"},
                                                      G: {"name": "work-gamma", "machine": "a", "url": "", "seen": "x"}, D: {"name": "work-delta", "machine": "a", "url": "", "seen": "x"},
                                                      DOC: {"name": "work-osprey-docs", "machine": "a", "url": "", "seen": "x"}, AU: {"name": "falcon-audit", "machine": "a", "url": "", "seen": "x"}, ZS: {"name": "work-zeta", "machine": "a", "url": "", "seen": "x"}, EM: {"name": "home-eta-main", "machine": "a", "url": "", "seen": "x"}, PL: {"name": "work-example-site", "machine": "a", "url": "", "seen": "x"}}))
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
page = lambda name, sess, **kw: {"title": name, "name": name, "org": "home", "tags": [], "type": "project", "session": sess, "status": "active", "board": [], "board_row": False, "updated": 1, "mirror": f"https://example.invalid/{name}", **kw}
ALPHA_AGENTS = {"work-osprey-main": "Oliver's point of contact", "work-osprey-docs": "keeps the pages and the documents", "work-osprey-x": "builds, merges and releases the code"}
(T / "store/projects.json").write_text(json.dumps({"pages": {
    "projects/alpha": page("Alpha", "work-osprey", agents=ALPHA_AGENTS, back_agents={"work-osprey-x": "builds, merges and releases the code", "work-osprey-docs": "keeps the pages and the documents"}),
    "projects/beta": page("Beta", "home-beta"), "projects/gamma": page("Gamma", "work-gamma", agents={"work-gamma-main": "the contact"}),
    "projects/delta": page("Delta", "work-delta"), "projects/epsilon": page("Epsilon", "work-gamma", hub="projects/gamma"),
    "projects/example-site": page("Example site", "work-example-site", agents={"work-example-site-main": "the contact", "example-site-builder": "does the site work"}, back_agents={"example-site-builder": "does the site work"}),
    "projects/eta": page("Eta", "home-eta", agents={"home-eta-main": "Oliver's point of contact"}), "projects/theta": page("Theta", "home-eta", hub="projects/eta"),
    "projects/iota": page("Iota", "home-beta", agents={"home-iota-main": "the contact"}),
    "projects/example-general": page("General", "home-commons", agents={"home-commons-main": "Oliver's general contact"}),
    "projects/zeta": page("Zeta", "work-zeta", agents={"work-zeta-main": "Oliver's point of contact", "work-zeta-news": "the news posts", "work-zeta-site": "the website content", "work-zeta-lib": "keeps the pages"}, back_agents={"work-zeta-lib": "keeps the pages"})}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n# Alpha\n\n## Current state\n\nALPHA-STATE-MARK: the vendor call is open.\n\n<!-- timeline -->\n- 2026-10-01 | old\n")
def item(i, proj, owner, status="open", **meta): (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": "A thing. It lives here. Done when done.", "status": status, "metadata": {"owner": owner, **({} if {"needs", "mover", "then", "hold", "after"} & set(meta) else {"mover": owner}), "project": proj, **meta}, "updated": 1.0, "state_updated": 1.0}))
item(1, "projects/alpha", A); item(2, "projects/alpha", X, mover=S); item(6, "projects/alpha", A, hold=True, mover=A); item(7, "projects/alpha", A, hold=True, mover=A)
(T / "store/next-id").write_text("10")
URL_HOLD, URL_HOLD2 = "https://mail.google.com/mail/u/0/#all/6666666666666666", "https://mail.google.com/mail/u/0/#all/7777777777777777"
(T / "store/anchors.json").write_text(json.dumps({
    "projects/alpha": [{"url": "https://x.slack.com/archives/C0000000001", "items": None, "added": 1, "by": "t"}, {"url": URL_HOLD, "items": ["a6"], "added": 1, "by": "t"},
                       {"url": URL_HOLD2, "items": ["a7"], "added": 1, "by": "t"}],
    "projects/gamma": [{"url": "https://x.slack.com/archives/C0000000003", "items": None, "added": 1, "by": "t"}],
    "projects/delta": [{"url": "https://x.slack.com/archives/C0000000004", "items": None, "added": 1, "by": "t"}],
    "projects/beta": [{"url": "https://x.slack.com/archives/C0000000002", "items": None, "added": 1, "by": "t"}],
    "projects/example-site": [{"url": "https://drive.google.com/drive/folders/FILE1", "items": None, "added": 1, "by": "t"}]}))
push_log, FAIL = T / "push.log", T / "push-fail.txt"
(T / "fakepush.py").write_text(f"import sys, json\na = sys.argv[1:]\nif a[:1] == ['--from']: a = a[2:]\n"
                               f"import os\nif os.path.exists({str(FAIL)!r}) and a[0] in open({str(FAIL)!r}).read().split():\n    print('failed: not live'); sys.exit(2)\n"
                               f"open({str(push_log)!r}, 'a').write(json.dumps(a) + '\\n')\nprint('delivered → ' + a[0])\n")
CTL, CALLS = T / "fake-control.json", T / "fake-calls.jsonl"
(T / "fake_claude.py").write_text(f'''import sys, os, json
ctl = json.load(open({str(CTL)!r}))
stdin = sys.stdin.read()
with open({str(CALLS)!r}, "a") as f: f.write(json.dumps({{"stdin": stdin}}) + "\\n")
if ctl["mode"] == "exit": sys.stderr.write("boom"); sys.exit(3)
print(json.dumps({{"type": "result", "subtype": "success", "is_error": False, "duration_api_ms": 700, "num_turns": 1, "result": ctl.get("text", ""), "total_cost_usd": 0.01, "usage": {{"input_tokens": 100, "output_tokens": 10}}}}))
''')
def fake(mode, text=""): CTL.write_text(json.dumps({"mode": mode, "text": text}))
def calls(): return [json.loads(l) for l in CALLS.read_text().splitlines()] if CALLS.exists() else []
def settle(until=30):
    """wait until the board's relay threads have ended: each push runs in a thread of its own, and none lives on in this test. A fixed
    0.6 s was too short under coverage on a busy box"""
    end = time.time() + until
    while time.time() < end and any(t is not threading.main_thread() and t.is_alive() for t in threading.enumerate()):
        time.sleep(0.02)
def pushes(): return [json.loads(l) for l in push_log.read_text().splitlines()] if push_log.exists() else []

sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:600]}" if got is not None else ""))

from stackshot.core import config as _cfg; from stackshot.router import routing; from stackshot.router import router; from stackshot.router import router_live as live; from stackshot.anchors import anchors as a; from stackshot.waits import held
from stackshot.web import server
from stackshot.anchors.anchorhub import core
for _bg in ("work-osprey-x", "work-osprey-docs", "work-zeta-lib"): held.mark_client(_bg)      # the rollout gate: these background agents' hooks fetch held lines (a notice is held only for such a session)
server._publish = lambda: None; server._PUSH = [sys.executable, str(T / "fakepush.py")]
# a front agent is told of a close only while Oliver is there and it touched the item (tests/front_quiet_scenario.py covers the gate). These checks are about what the router and
# the server record and push, so Oliver is there for every front pane unless a check flips PRESENT; with it off the gate's own verdict is used (this fixture runs no panes: nobody is told).
PRESENT = [True]
_real_verdict = server._front_verdict
server._front_verdict = lambda gid, owner, kind: ("send", "") if PRESENT[0] else _real_verdict(gid, owner, kind)
CMD = [sys.executable, str(T / "fake_claude.py")]
OLIVER_ROUTER = {"general_home": "home-commons-main", "general_ops": "heron-main", "general_work": "projects/work-commons",      # the example-owner instance (tests/_instance.py), kept when a step re-sets [router]
                 "watch": [{"page": "projects/example-brain", "anchor": "github:example-upstream/tool#32", "agent": "kestrel-main"}], "quiet": [{"page": "projects/example-site", "agent": "example-site-builder"}]}
def cfg(**kw): _cfg.CFG["router"] = {"command": CMD, "timeout_seconds": 20, **OLIVER_ROUTER, **kw}
def rule_of(i, key="projects/alpha"): return next(n for n in routing.read(key) if n["id"] == i)
def lines(): return router._read(live.live_path())
def to_name_line(p, name="work-osprey"): return [x for x in p if x[0] == name]
def answer(rows): return json.dumps([{"id": i, "ruling": r, "target": t, "reason": f"canned {i}", "for_owner": fh} for i, r, t, fh in rows])

# ---- 1. the router is not switched: it rules every project; the older "live off" section is gone
cfg()

# ---- 2. every project page is the router's; the stand-in
cfg()
check("every project page is the router's, a sub-page with its top-level page (even beta, which lists no agent); a key that names no page is not", all(live.is_live(k) for k in ("projects/alpha", "projects/gamma", "projects/delta", "projects/alpha/sub", "projects/beta", "projects/epsilon")) and not live.is_live("projects/nowhere") and not live.is_live(""))
cfg(live=True)
check("stand-in: alpha's builder (a background agent whose mandate says builds, merges), gamma's -main, a page with no agent and no hub (delta, beta) the scope's general -main", live.stand_in("projects/alpha") == "work-osprey-x" and live.stand_in("projects/gamma") == "work-gamma-main"
      and live.stand_in("projects/delta") == "home-commons-main" and live.stand_in("projects/beta") == "home-commons-main", [live.stand_in(k) for k in ("projects/alpha", "projects/gamma", "projects/delta")])
check("a page that lists agents: the stand-in is what _page_keeper answers; a one-session page (delta, a name line and no agents) keeps its own session as keeper, the general -main agent is only the router's pass target",
      server._page_keeper("projects/alpha") == "work-osprey-x" and server._page_keeper("projects/gamma") == "work-gamma-main" and server._page_keeper("projects/delta") == "work-delta"
      and server._stand_in_keeper("projects/delta") == "home-commons-main", (server._page_keeper("projects/alpha"), server._page_keeper("projects/delta")))
check("the page's name line still names the project's notices", a.notice_name("projects/alpha") == "work-osprey" and a.pilot_root("projects/alpha") == "projects/alpha")
check("the item notices' keeper follows the stand-in, whatever session moves the item", server._keeper("projects/alpha") == "work-osprey-x" and server._keeper("projects/alpha", "home-other") == "work-osprey-x", (server._keeper("projects/alpha"), server._keeper("projects/alpha", "home-other")))
check("a front agent is told nothing about its own project through its stand-in (the stand-in is itself)", server._front_keeper("work-gamma-main", "projects/gamma") in ((True, ""), (False, "")), server._front_keeper("work-gamma-main", "projects/gamma"))
cfg()

T_LIVE = time.time()
# ---- 3. live on: a message, an anchor-hub notice, a board relay and a wake are held for the router, not delivered to the keeper
cfg(live=True)
p0 = len(pushes())
r1 = server._message("projects/alpha", "please look at the quote from the vendor (see https://example.invalid/q)", "home-beta")
m_quote = routing.read("projects/alpha")[-1]
check("live: a message to a project is held for the router, nothing is pushed", r1.startswith("held for the router") and len(pushes()) == p0, (r1, pushes()[p0:]))
check("live: its routing line has no recipient and the live mark; it is a pilot notice, unruled", m_quote["to"] == "" and m_quote["live"] is True and m_quote["pilot"] is True and not m_quote.get("ruling"), m_quote)
msg_rows = [json.loads(l) for l in server.MSG_LOG.read_text(encoding="utf-8").splitlines() if l.strip()]
check("live: the message log names the page key it was addressed to, not the retired name-line session, and says it was held for the router",
      msg_rows[-1]["to"] == "projects/alpha" and msg_rows[-1]["outcome"] == "held for the router", msg_rows[-1])
item(94, "projects/alpha", A, mover=X)         # an item the builder moves: the builder's message to its own project about it reaches no one, and the reply says so
_rec, _stash = server._routing.record, server._router_live.stash          # the two sends below leave no notice for the tick checks that follow
server._routing.record = lambda *a, **k: "abc123"; server._router_live.stash = lambda *a, **k: None
try:
    r_own = server._message("projects/alpha", "a94: the handback is done, so the next session's step is due", "work-osprey-x")
    r_oth = server._message("projects/alpha", "a94: the handback is done, so the next session's step is due", "home-beta")
finally:
    server._routing.record, server._router_live.stash = _rec, _stash
    (T / "store/a/94.json").unlink()
check("live: a message to a project about an item the sender moves is answered NOT PASSED ON (the router merges it), one from another session or about no item of its own is not",
      r_own.startswith("held for the router") and "NOT PASSED ON: you move a94 yourself" in r_own and "update" in r_own and "NOT PASSED ON" not in r_oth and "NOT PASSED ON" not in r1, (r_own, r_oth))
stash = live.stashed(m_quote["id"])
check("live: the full message is kept for the router, framed as a message, with no keeper ruling line", "[stackshot message] from" in stash and "vendor" in stash and "route(notice" not in stash, stash)

hub = core.Hub(); hub_out = []
hub.deliver = lambda anchor, session, text: hub_out.append((anchor, session, text)); hub.write_status = lambda: None
core._ROUTES.clear(); core._ROUTES["slack:C0000000001"] = [{"project": "projects/alpha", "session": "work-osprey", "target": "project-wide", "pilot": True, "filter": ""}]
core._ROUTES["gmail:6666666666666666"] = [{"project": "projects/alpha", "session": "work-osprey", "target": "for work-osprey-main", "pilot": True, "filter": ""}]
core._ROUTES["gmail:7777777777777777"] = [{"project": "projects/alpha", "session": "work-osprey", "target": "for work-osprey-main", "pilot": True, "filter": ""}]
core._ROUTES["slack:C0000000003"] = [{"project": "projects/gamma", "session": "work-gamma", "target": "project-wide", "pilot": True, "filter": ""}]
core._ROUTES["slack:CAGENT"] = [{"project": "projects/alpha", "session": "work-osprey-x", "target": "", "pilot": False, "filter": ""}]
ev = lambda label="Slack anchor", who="Dana", url="https://u/1": types.SimpleNamespace(label=label, who=who, url=url)
hub.send("slack:C0000000001", "work-osprey", "[anchor] Slack #general: new message from Dana: can you move the call to Friday? → https://u/1", ev(), "new message from Dana: can you move the call to Friday?")
n_hub = routing.read("projects/alpha")[-1]
check("live: anchor-hub records the notice for the router and delivers it to nobody", hub_out == [] and n_hub["live"] is True and n_hub["to"] == "" and n_hub["kind"] == "anchor" and "Friday" in live.stashed(n_hub["id"]), (hub_out, n_hub))
hub.send("slack:CAGENT", "work-osprey-x", "[anchor] something for the builder", ev(), "something")
check("live: anchor-hub's other recipients (a session that is not the keeper) are delivered to as ever", [x[1] for x in hub_out] == ["work-osprey-x"], hub_out)
hub_out.clear(); hub.send("slack:C0000000003", "work-gamma", "[anchor] gamma talk", ev(), "gamma talk")
check("live: …and so is every project (live for all): gamma's notice is held too", hub_out == [] and routing.read("projects/gamma")[-1]["live"] is True)
cfg(live=True)

item1 = server._load("a1")
server._pilot_relay("projects/alpha", "a1", item1, "completed", "work-osprey-x", "work-osprey")
n_board = routing.read("projects/alpha")[-1]
check("live: a board relay to the keeper is held for the router, not pushed", n_board["kind"] == "board" and n_board["live"] is True and n_board["to"] == "" and len(pushes()) == p0 and "completed" in live.stashed(n_board["id"]), (n_board, pushes()[p0:]))
server._pilot_relay("projects/alpha", "a1", item1, "completed", "work-osprey-x", "work-osprey-docs", tail="a page keeper's relay"); settle()
check("live: a relay to a background agent that keeps the page (not the keeper) is held for its next turn (a page-owed notice asks nothing), not pushed, and not the router's",
      [x[0] for x in pushes()[p0:]] == [] and held.count("work-osprey-docs") == 1 and routing.read("projects/alpha")[-1].get("ruling") == "held" and not routing.read("projects/alpha")[-1].get("live")
      and routing.read("projects/alpha")[-1].get("reason") == "held: asks nothing (page-owed)", (pushes()[p0:], routing.read("projects/alpha")[-1]))
held.take("work-osprey-docs")
nids = server._pilot_relay_many("work-osprey", [("projects/alpha", "a1", item1, "completed", "work-osprey-x"), ("projects/alpha", "a2", server._load("a2"), "changed", "work-osprey-x")])
check("live: several page debts moved to the keeper are held, one routing line each, nothing pushed", len(nids) == 2 and all(rule_of(i).get("live") for i in nids) and len(pushes()) == p0, (nids, pushes()[p0:]))
server._wake_tell(S, [("a2", server._load("a2"), "woke", "as the keeper of its page", False)])
n_wake = routing.read("projects/alpha")[-1]
check("live: a wake meant for the keeper is held for the router", n_wake["label"].startswith("wake") and n_wake["live"] is True and len(pushes()) == p0, (n_wake, pushes()[p0:]))

# the keeper of a live project's board relays resolves through _keeper, which answers the stand-in (the builder): that relay is the router's too
check("the keeper of a live project's board writes is the stand-in", server._keeper("projects/alpha") == "work-osprey-x")
p1 = len(pushes()); server._pilot_relay("projects/alpha", "a1", item1, "updated", "work-osprey-main", server._keeper("projects/alpha")); settle()
n_sb = routing.read("projects/alpha")[-1]
check("live: a board write by another session, relayed to the stand-in (the builder), is held for the router and not pushed to the builder", n_sb["live"] is True and n_sb["to"] == "" and n_sb["label"] == "board a1" and len(pushes()) == p1, (n_sb, pushes()[p1:]))
nm_ = server._pilot_relay_many("work-osprey-x", [("projects/alpha", "a1", item1, "completed", "work-osprey-main")]); settle()
check("live: page debts relayed to the stand-in are held for the router too", len(nm_) == 1 and rule_of(nm_[0]).get("live") and len(pushes()) == p1, (nm_, pushes()[p1:]))
server._pilot_relay("projects/alpha", "a1", item1, "updated", "work-osprey-main", "work-osprey-x", role="agent", tail="you keep this page"); settle()
check("…while the relay to a page's own agent (role agent) skips the router and, to a background agent such as the builder, is held for its next turn", [x[0] for x in pushes()[p1:]] == [] and held.count("work-osprey-x") == 1, (pushes()[p1:], held.count("work-osprey-x")))
held.take("work-osprey-x")
p1 = len(pushes()); server._pilot_relay_many("work-osprey-main", [("projects/alpha", "a1", item1, "completed", "work-osprey-x")], head="[for Oliver] the page-debt fallback"); settle()
check("…and a caller that names its recipient (the page-debt fallback to -main) is delivered to, not held", [x[0] for x in pushes()[p1:]] == ["work-osprey-main"], pushes()[p1:])
for _i in (n_sb["id"], *nm_): routing.rule(_i, "dropped", by="test")      # settled by hand: the plan below is about the other notices
p0 = len(pushes())

# ---- 4. no reminder and no digest for a live project
rem0 = len(pushes())
check("no unruled-notice reminder and no daily digest of automatic rulings exist any more: nothing chases a keeper (the board's waiting flag shows an unruled notice)", not hasattr(server, "_remind_tick") and not hasattr(server, "_digest_tick") and not hasattr(routing, "due") and not hasattr(routing, "remind") and len(pushes()) == rem0)
cfg(live=True)

# ---- 5. the tick: judge with the router's own code, then act
all_live = [n for n in routing.read("projects/alpha") if n.get("live") and not n.get("ruling")]
ids = {n["id"] for n in all_live}
check("the unruled held notices are the ones above", {m_quote["id"], n_hub["id"], n_board["id"], n_wake["id"], *nids} <= ids, ids)
# an anchor notice on the hold-item anchors (rule in code: the anchor is scoped to one open item, whose owner is -main)
hub.send("gmail:6666666666666666", "work-osprey", "[anchor] Gmail thread: the vendor wrote back → https://mail.google.com/x", ev("Gmail anchor", "Vee", "https://mail.google.com/x"), "the vendor wrote back")
n_hold = routing.read("projects/alpha")[-1]
hub.send("gmail:7777777777777777", "work-osprey", "[anchor] Gmail thread: out of office reply → https://mail.google.com/y", ev("Gmail anchor", "Vee", "https://mail.google.com/y"), "out of office reply")
n_hold2 = routing.read("projects/alpha")[-1]
plan = [(m_quote["id"], "passed", "work-osprey-x", False), (n_hub["id"], "passed", "work-osprey-main", True), (n_board["id"], "passed", "work-osprey-docs", False),
        (nids[0], "dropped", "", False), (nids[1], "held", "", False)]      # the wake notice is settled by a rule in code (the wake rule: a live wake for the item's mover passes to it)
fake("good", answer(plan)); p0 = len(pushes())
res = live.tick()
rb = {n["id"]: n for n in routing.read("projects/alpha")}
ca = [c for c in calls() if "Project: projects/alpha" in c["stdin"]]
check("a tick takes one call for the project's notices the rules in code did not settle (and one for gamma's)", len(ca) == 1 and len(calls()) == 2 and res["retry"] == 1 and all(f'"id": "{i}"' in ca[0]["stdin"] for i, *_ in plan) and f'"id": "{n_hold["id"]}"' not in ca[0]["stdin"], res)
settle(); npush = len(pushes()); pp = [x for x in pushes()[p0:] if x[0] != "work-gamma-main"]
check("passed → delivered to the target, ruled passed by stackshot (router) with the reason and the target", all(rb[i]["ruling"] == "passed" and rb[i]["ruled_by"] == "stackshot (router)" and rb[i]["ruled_to"] == t and rb[i]["reason"] == f"canned {i}"
      for i, r, t, _fh in plan if r == "passed"), [rb[i] for i, r, *_ in plan if r == "passed"])
to_x = next(x for x in pp if x[0] == "work-osprey-x"); to_main = next(x for x in pp if x[0] == "work-osprey-main" and m_quote["id"] not in x[1] and n_hub["id"] in x[1])
check("a pass to a background agent carries no mark; the notice text and the reason are in it", not to_x[1].startswith("[for Oliver]") and "vendor" in to_x[1] and "canned" in to_x[1] and m_quote["id"] in to_x[1], to_x)
check("a pass to a front agent for Oliver opens with [for Oliver]", to_main[1].startswith("[for Oliver]") and "Friday" in to_main[1], to_main)
check("a pass to the agent that keeps the page carries the board notice, unmarked (the default relay says the page update is the keeper's, an ask: it does not hold it)", any(x[0] == "work-osprey-docs" and not x[1].startswith("[for Oliver]") and "completed" in x[1] for x in pp) and rb[n_board["id"]]["ruling"] == "passed" and held.count("work-osprey-docs") == 0, pp)
check("merged and dropped are ruled and nothing is delivered for them; held is ruled held; the mover's own wake is passed to it (never dropped)", (rb[n_wake["id"]]["ruling"], rb[nids[0]]["ruling"], rb[nids[1]]["ruling"]) == ("passed", "dropped", "held")
      and len([x for x in pp if "router: notice" in x[1]]) == 6 and all(rb[i]["ruled_by"] == "stackshot (router)" for i in (n_wake["id"], nids[0], nids[1])), ([x[0] for x in pp], [rb[i].get("ruling") for i in (n_wake["id"], nids[0], nids[1])]))
check("the keeper heard none of it but its own wake (it moves the woken item)", [x[1][:60] for x in to_name_line(pushes()[p0:])] == [x[1][:60] for x in to_name_line(pushes()[p0:]) if "a2" in x[1] and "woke" in x[1]] and not to_name_line(pushes()[p0:], "work-gamma"))
check("every action is a line in live.jsonl: ruled, with the ruling and target", {l["id"] for l in lines() if l["status"] == "ruled"} >= {i for i, *_ in plan}
      and next(l for l in lines() if l["id"] == m_quote["id"])["target"] == "work-osprey-x" and next(l for l in lines() if l["id"] == m_quote["id"])["marked"] is False
      and next(l for l in lines() if l["id"] == n_hub["id"])["marked"] is True, lines()[:2])
check("the rule in code took the anchor notices scoped to one item: passed to its owner -main, no call for them", rb[n_hold["id"]]["ruling"] == "passed" and rb[n_hold["id"]]["ruled_to"] == "work-osprey-main" and rb[n_hold["id"]]["ruled_by"] == "stackshot (router)", rb[n_hold["id"]])
it6, it7 = server._load("a6"), server._load("a7")
check("a hold waiting on that anchor is released by the router's passed ruling", not it6["metadata"].get("hold"), it6["metadata"])

check("a notice the call left out (gamma's: the answer was alpha's) stays held on the first try: nothing delivered, nothing ruled, one retry counted", res["retry"] == 1 and not any(x[0] == "work-gamma-main" for x in pushes()[p0:npush])
      and not routing.read("projects/gamma")[-1].get("ruling") and any(router._load_attempts().values()), (res, router._load_attempts()))
res2 = live.tick(); settle()
gp = pushes()[npush:]
check("…and the second try is the fallback: passed to gamma's -main agent, marked, the attempts entry gone", res2["retry"] == 0 and res2["fallback"] == 1 and [x[0] for x in gp] == ["work-gamma-main"] and gp[0][1].startswith("[for Oliver]") and not router._load_attempts(), (res2, gp, router._load_attempts()))
n_calls = len(calls()); npush = len(pushes()); res3 = live.tick()
check("a third tick judges nothing", res3["ruled"] == 0 and len(calls()) == n_calls and len(pushes()) == npush, res3)

check("live: a notice delivered at once to an agent (a relay to the page's agent, a wake for the stand-in) is ruled passed by the router's name, so none sits unruled",
      not [n for n in routing.read("projects/alpha") if n.get("pilot") and not n.get("ruling") and not n.get("live") and float(n["ts"]) >= T_LIVE], [n for n in routing.read("projects/alpha") if n.get("pilot") and not n.get("ruling") and not n.get("live") and float(n["ts"]) >= T_LIVE])
# a dropped ruling does not release a hold (as a keeper's does not); a merged one does
fake("good", answer([(n_hold2["id"], "dropped", "", False)]))
# the rule in code settles n_hold2 (passed to its owner); force the call by recording the notice as a repeat-free board notice instead
hub.send("slack:C0000000001", "work-osprey", "[anchor] Slack: bot chatter → https://u/9", ev("Slack anchor", "bot", "https://u/9"), "bot chatter")
n_chat = routing.read("projects/alpha")[-1]
fake("good", answer([(n_chat["id"], "dropped", "", False)])); live.tick()
# gamma has no background agent, so PR A's clamp lets a front pass without for_owner stand: -main is the only fit, and the mark still goes on
hub.send("slack:C0000000003", "work-gamma", "[anchor] Slack: the vendor needs a yes → https://u/10", ev("Slack anchor", "Vee", "https://u/10"), "the vendor needs a yes"); n_fr = routing.read("projects/gamma")[-1]
fake("good", answer([(n_fr["id"], "passed", "work-gamma-main", False)])); p0 = len(pushes()); live.tick(); settle()
fl = next(l for l in lines() if l["id"] == n_fr["id"])
check("a delivery to a front agent carries [for Oliver] whatever for_owner says (a front pass without it, in a project with no background agent)", [x for x in pushes()[p0:] if x[0] == "work-gamma-main" and n_fr["id"] in x[1]][0][1].startswith("[for Oliver]")
      and fl["for_owner"] is False and fl["marked"] is True and fl["target"] == "work-gamma-main", (fl, pushes()[p0:]))
check("…and one to a background agent does not (alpha's builder, above)", next(l for l in lines() if l["id"] == m_quote["id"])["marked"] is False)
check("a dropped ruling is ruled and delivers nothing", rule_of(n_chat["id"])["ruling"] == "dropped" and rule_of(n_chat["id"])["ruled_by"] == "stackshot (router)")
check("the second hold's notice (passed by the rule in code) released its item too", not server._load("a7")["metadata"].get("hold"))

item(6, "projects/alpha", A, hold=True)          # held again, waiting on the Gmail anchor
note_ = {"id": "feed01", "kind": "anchor", "anchor": "gmail:6666666666666666", "live": True, "to": "", "ts": time.time(), "ruled_at": time.time()}
server._router_live_after("projects/alpha", {**note_, "ruling": "dropped"}); held_d = bool(server._load("a6")["metadata"].get("hold"))
server._router_live_after("projects/alpha", {**note_, "ruling": "held"}); held_h = bool(server._load("a6")["metadata"].get("hold"))
server._router_live_after("projects/alpha", {**note_, "ruling": "merged"}); held_m = bool(server._load("a6")["metadata"].get("hold"))
check("a hold waiting on an anchor: the router's dropped or held ruling leaves it held (as a keeper's does), a merged one releases it", (held_d, held_h, held_m) == (True, True, False), (held_d, held_h, held_m))

# ---- 6. a notice the router cannot judge goes to -main with the mark; the keeper gets nothing
server._message("projects/alpha", "an odd one", "home-beta"); n_odd = routing.read("projects/alpha")[-1]
fake("exit"); p0 = len(pushes()); r1_ = live.tick(); settle()
check("a failed call: the notice stays held on the first try (nothing delivered, nothing ruled), one retry", r1_["retry"] == 1 and not [x for x in pushes()[p0:] if n_odd["id"] in x[1]] and not rule_of(n_odd["id"]).get("ruling") and router._load_attempts().get(n_odd["id"]) == 1, (r1_, router._load_attempts()))
live.tick(); settle()
pp = [x for x in pushes()[p0:] if "router: notice" in x[1] or x[0] == "work-osprey"]; ro = rule_of(n_odd["id"])
check("a call that failed twice: the notice is passed to -main, ruled passed with the reason, marked [for Oliver]", len(pp) == 1 and pp[0][0] == "work-osprey-main" and pp[0][1].startswith("[for Oliver]")
      and ro["ruling"] == "passed" and ro["ruled_to"] == "work-osprey-main" and "call failed" in ro["reason"], (pp, ro))
check("the keeper heard nothing of it", not to_name_line(pp))
fake("good", "this is not JSON"); server._message("projects/alpha", "another odd one", "home-beta"); n_odd2 = routing.read("projects/alpha")[-1]; p0 = len(pushes()); live.tick(); live.tick(); settle()
check("an answer that does not parse is handled the same way (one retry, then -main)", [x[0] for x in pushes()[p0:] if n_odd2["id"] in x[1]] == ["work-osprey-main"] and rule_of(n_odd2["id"])["ruled_to"] == "work-osprey-main", pushes()[p0:])
_orig = router.call_project
router.call_project = lambda *a_, **k_: (_ for _ in ()).throw(RuntimeError("kaboom"))
server._message("projects/alpha", "a third odd one", "home-beta"); n_odd3 = routing.read("projects/alpha")[-1]; p0 = len(pushes()); live.tick()
router.call_project = _orig
check("an exception while judging is passed to -main with the mark too, the exception in the reason", [x[0] for x in pushes()[p0:]] == ["work-osprey-main"] and pushes()[p0:][0][1].startswith("[for Oliver]") and "kaboom" in rule_of(n_odd3["id"])["reason"], (pushes()[p0:], rule_of(n_odd3["id"])))

# ---- 7. a project with no agent and no hub: the scope's general -main takes it
server._message("projects/delta", "delta wants something", "home-beta"); n_d = routing.read("projects/delta")[-1]
fake("exit"); p0 = len(pushes()); live.tick(); live.tick(); pp = pushes()[p0:]
check("no agent and no hub: a notice that cannot be judged (twice) is passed to the scope's general -main (home-commons-main), marked, never to a keeper name", [x[0] for x in pp] == ["home-commons-main"] and pp[0][1].startswith("[for Oliver]") and "delta wants" in pp[0][1], pp)
check("…and it is ruled passed by the router (not left to a keeper) and not taken again", routing.read("projects/delta")[-1].get("ruling") == "passed" and routing.read("projects/delta")[-1].get("ruled_to") == "home-commons-main" and (live.tick() is not None and len(pushes()) == p0 + 1), routing.read("projects/delta")[-1])

# ---- 7b. a pilot root with no agent of its own (projects/example-portal, ops/example-hub) is served by its hub's agents
server._message("projects/epsilon", "epsilon wants something", "home-beta"); n_e = routing.read("projects/epsilon")[-1]
check("a component page (hub: projects/gamma) is held for the router like any pilot root", n_e["live"] is True and live.holds("projects/epsilon", "work-gamma") and live.agent_root("projects/epsilon", a.registry()) == "projects/gamma")
check("…and its stand-in is its hub's", live.stand_in("projects/epsilon") == "work-gamma-main", live.stand_in("projects/epsilon"))
fake("good", answer([(n_e["id"], "passed", "work-gamma-main", True)])); p0 = len(pushes()); live.tick(); settle()
pe = [x for x in pushes()[p0:] if n_e["id"] in x[1]]
check("…and a notice on it goes to its hub's agent, marked, ruled by the router; the keeper hears nothing", [x[0] for x in pe] == ["work-gamma-main"] and pe[0][1].startswith("[for Oliver]") and rule_of(n_e["id"], "projects/epsilon")["ruled_to"] == "work-gamma-main"
      and "Project: projects/gamma" in calls()[-1]["stdin"], (pe, calls()[-1]["stdin"][:200]))

# ---- 8. a failed delivery is retried, then goes to -main
FAIL.write_text("work-osprey-x\n"); server._message("projects/alpha", "tell the builder about the deploy", "home-beta"); n_f = routing.read("projects/alpha")[-1]
fake("good", answer([(n_f["id"], "passed", "work-osprey-x", False)])); p0 = len(pushes())
for _ in range(3): live.tick()
errs = [l for l in lines() if l["id"] == n_f["id"] and l["status"] == "error"]
check("a delivery that fails is not ruled and is tried again at each tick", len(errs) == 3 and not rule_of(n_f["id"]).get("ruling") and "failed" in errs[0]["error"], (errs, rule_of(n_f["id"])))
fake("good", answer([(n_f["id"], "passed", "work-osprey-x", False)])); live.tick()
r_f = rule_of(n_f["id"])
check("after three failures it goes to -main, marked, ruled passed with the reason", r_f["ruled_to"] == "work-osprey-main" and "failed 3 times" in r_f["reason"] and [x[0] for x in pushes()[p0:]] == ["work-osprey-main"] and pushes()[p0:][0][1].startswith("[for Oliver]"), (r_f, pushes()[p0:]))
FAIL.unlink()

# ---- 10. status
cfg()
st = {r["project"]: r for r in live.status()}
check("status: a line per project, with what was acted on in the last hour and the last error (there is no mode: the router rules every project)", "mode" not in st["projects/alpha"] and set(st) >= {"projects/alpha", "projects/gamma", "projects/delta", "projects/beta"}
      and st["projects/alpha"]["acted_last_hour"] >= 10 and "failed" in st["projects/alpha"]["last_error"] and st["projects/gamma"]["acted_last_hour"] >= 1, st)
cli = subprocess.run([sys.executable, str(pathlib.Path(STACK, "stackshot/router/router_live.py")), "status"], capture_output=True, text=True, timeout=60, env=dict(os.environ))
check("`router_live.py status` prints a line per project from the logs", cli.returncode == 0 and "projects/alpha" in cli.stdout and "projects/delta" in cli.stdout, (cli.returncode, cli.stderr[-300:], cli.stdout[:300]))

# ---- 11. there is no rollback to the keepers: `[router] live = false` in an old config is ignored, and no notice is delivered to a keeper
cfg(live=False, live_projects=["projects/nowhere"]); p0 = len(pushes())
r2 = server._message("projects/alpha", "after the rollback key was set", "home-beta"); last = routing.read("projects/alpha")[-1]
res = live.tick()
check("[router] live = false (and live_projects naming another page) is ignored: a message is still held for the router, delivered to no keeper, and the tick strands nothing", r2.startswith("held for the router") and last["to"] == "" and last.get("live") is True
      and live.holds("projects/alpha", "work-osprey") and "stranded" not in res and not [x for x in pushes()[p0:] if x[0] == "work-osprey"], (r2, last, res, pushes()[p0:]))
check("…and no function of the router delivers a notice to a keeper by name any more", not hasattr(live, "_to_steward_text") and not hasattr(live, "flush_stranded") and not hasattr(live, "enabled") and not hasattr(live, "scope"))
cfg(live=True)

# ---- 12. the daily digest of held notices, a ruling's note on the page's timeline, the cap on writing a ruling
import datetime as dt; from stackshot.projects import rename_page as rp
mid_ = dt.datetime.now(_cfg.tz()).replace(hour=0, minute=0, second=0, microsecond=0)
D0 = (mid_ + dt.timedelta(hours=10)).timestamp()
day = lambda k: D0 + k * 86400
def digests(since): return [x for x in pushes()[since:] if "router digest" in x[1]]
def dlines(): return [l for l in lines() if l.get("kind") == "digest"]
def ledger(): return json.loads((router._dir() / "digest.json").read_text(encoding="utf-8"))
cfg(live=True)
for k_ in routing.projects():          # what the sections above left unruled is settled by hand: this part is about its own notices
    for n_ in routing.read(k_):
        if n_.get("live") and n_.get("pilot") and not n_.get("ruling"): routing.rule(n_["id"], "dropped", by="test")
PLU = "projects/example-site"
core._ROUTES["drive:FILE1"] = [{"project": PLU, "session": "work-example-site", "target": "project-wide", "pilot": True, "filter": ""}]
hub.send("drive:FILE1", "work-example-site", "[anchor] Drive: Plan.docx edited → https://drive.google.com/x", ev("Drive anchor", "Kim", "https://drive.google.com/x"), "Plan.docx edited")
n_q = routing.read(PLU)[-1]
server._message(PLU, "keeper: the plan page is stale", "nightly-job"); n_pp = routing.read(PLU)[-1]
server._message("projects/alpha", "keeper: the roadmap page is stale", "nightly-job"); n_ap = routing.read("projects/alpha")[-1]
live.tick()
lq = next(l for l in lines() if l.get("id") == n_q["id"]); lp = next(l for l in lines() if l.get("id") == n_pp["id"])
check("example-site: the Drive anchor notice is held by the quiet rule, the nightly job's page message by the page pass; the router rules both held",
      n_q["live"] and n_pp["live"] and rule_of(n_q["id"], PLU)["ruling"] == "held" and rule_of(n_pp["id"], PLU)["ruling"] == "held" and (lq["rule"], lp["rule"]) == ("quiet", "page-pass"), (lq, lp))
exp_all = [n["id"] for n in routing.read("projects/alpha") if n.get("ruling") == "held" and n.get("ruled_by") == "stackshot (router)"]
exp_alpha = [i for i in exp_all if i != n_ap["id"]]          # the -main digest's: the page-pass hold goes to the builder
check("alpha's page-pass hold is among the router's held rulings", n_ap["id"] in exp_all and next(l for l in lines() if l.get("id") == n_ap["id"])["rule"] == "page-pass")
check("the router ruled some alpha notices held in the sections above", len(exp_alpha) >= 1, exp_alpha)
st0 = {r["project"]: r for r in live.status()}
check("status: held since the last digest and the last digest's time (none yet)", st0["projects/alpha"]["held_since_digest"] == len(exp_all) and st0["projects/alpha"]["last_digest_at"] == 0
      and st0[PLU]["held_since_digest"] == 2 and st0["projects/gamma"]["held_since_digest"] == 0, st0)

# the digest: before the hour nothing; from it, one message per project with something held; the mark on -main's, none on the background agent's
p0 = len(pushes()); r_early = live.digest_tick(now=D0 - 2 * 3600)
check("before [router] digest_hour nothing is sent", r_early["sent"] == 0 and not digests(p0) and live.digest_hour() == 9)
r_d = live.digest_tick(now=D0)
dg = digests(p0); by = {x[0]: x[1] for x in dg}
check("only the quiet-hour agent is sent a digest: held notices owe nothing, so the -main digests and the page-pass digests are logged, not sent",
      len(dg) == 1 and set(by) == {"example-site-builder"} and r_d["sent"] == 1 and r_d["logged"] == 3, ([x[0] for x in dg], r_d))
check("a held notice is delivered to no front agent: not to alpha's -main, not to its builder, nothing marked [for Oliver]",
      not any(x[0] in ("work-osprey-main", "work-osprey-x", "work-example-site-main", "work-osprey") for x in dg) and not any("[for Oliver]" in x[1] and "router digest" in x[1] for x in dg), [x[0] for x in dg])
lg = [l for l in lines() if l.get("kind") == "digest_logged"]
lg_main = next(l for l in lg if l["group"] == "main" and l["project"] == "projects/alpha")
check("the -main group's held notices are a line of live.jsonl instead: kind digest_logged, project, count, ids and the digest's text, unmarked, listing every held notice with its reason",
      lg_main["status"] == "logged" and "target" not in lg_main and sorted(lg_main["ids"]) == sorted(exp_alpha) and lg_main["count"] == len(exp_alpha) and "[for Oliver]" not in lg_main["text"]
      and "by the router and not passed to any agent" in lg_main["text"].split("\n")[0] and all(i in lg_main["text"] for i in exp_alpha) and f"canned {nids[1]}" in lg_main["text"]
      and f"{len(exp_alpha)} notice" in lg_main["text"], lg_main)
check("a logged digest line shows id, label, sender, gist and reason", re.search(rf"- {nids[1]} · .+ · from .+ · \"", lg_main["text"]) is not None, lg_main["text"])
lg_pp = [l for l in lg if l["group"] == "pagepass"]
check("…a page-pass hold is logged the same way: its own group, the page-pass head, unmarked, and not in the -main group's text",
      len(lg_pp) == 2 and all(l["status"] == "logged" and "target" not in l and "for the page pass" in l["text"].split("\n")[0] and "[for Oliver]" not in l["text"] for l in lg_pp)
      and {(l["project"], l["count"], tuple(l["ids"])) for l in lg_pp} == {("projects/alpha", 1, (n_ap["id"],)), (PLU, 1, (n_pp["id"],))} and n_ap["id"] in next(l for l in lg_pp if l["project"] == "projects/alpha")["text"]
      and n_ap["id"] not in lg_main["text"] and len(lg) == 3, lg)
check("example-site: the quiet-hour hold goes to example-site-builder unmarked, and not the page-pass one", n_q["id"] in by["example-site-builder"] and "[for Oliver]" not in by["example-site-builder"] and n_pp["id"] not in by["example-site-builder"], by["example-site-builder"])
check("an empty list sends nothing: no digest for gamma, delta or epsilon", not any(x[0] in ("work-gamma-main", "work-delta", "work-gamma") for x in dg) and r_d["empty"] >= 2, (r_d, [x[0] for x in dg]))
check("the routing log keeps the held ruling as it was, with no new line of the router's", all(rule_of(i)["ruling"] == "held" and rule_of(i)["ruled_by"] == "stackshot (router)" and "digest" not in (rule_of(i).get("reminders") or {}) for i in exp_alpha))
dl = dlines()
check("each digest sent is a line of live.jsonl: kind digest, project, count, target, outcome", len(dl) == 1 and all(l["status"] == "sent" and l["outcome"].startswith("delivered") for l in dl)
      and {(l["project"], l["target"], l["count"]) for l in dl} == {(PLU, "example-site-builder", 1)}, dl)
led = ledger()
check("the digested notices and the time of the last digest are in <state>/router/digest.json", all(i in led["sent"] for i in [*exp_all, n_q["id"], n_pp["id"]]) and led["last"]["projects/alpha"] == D0, led)
p1 = len(pushes()); r_again = live.digest_tick(now=D0 + 3600); live.digest_tick(now=D0 + 7200)
check("no double send: a later tick the same day sends nothing and logs nothing", r_again["sent"] == 0 and r_again["logged"] == 0 and not digests(p1) and len([l for l in lines() if l.get("kind") == "digest_logged"]) == 3)
st1 = {r["project"]: r for r in live.status()}
check("status after the digest: nothing held since it, its time shown", st1["projects/alpha"]["held_since_digest"] == 0 and st1["projects/alpha"]["last_digest_at"] == D0 and "last digest" in live.render(live.status()))

# a notice held later the same day waits for the next day's digest, and the digest lists it alone, with the router's reason
server._message("projects/alpha", "a photo of the whiteboard, please file it", "home-beta"); n_img = routing.read("projects/alpha")[-1]
fake("good", json.dumps([{"id": n_img["id"], "ruling": "held", "target": "", "reason": "held for the digest: image not read", "for_owner": False}]))
live.tick(); p1 = len(pushes()); live.digest_tick(now=D0 + 4 * 3600)
check("a notice held after the day's digest is not sent the same day", rule_of(n_img["id"])["ruling"] == "held" and not digests(p1))
n_lg0 = len([l for l in lines() if l.get("kind") == "digest_logged"]); live.digest_tick(now=day(1)); d1 = digests(p1)
lg1 = [l for l in lines() if l.get("kind") == "digest_logged"][n_lg0:]
check("the next day's digest is logged, not sent: it lists it alone (not the ones already digested), with the reason; example-site has nothing new, so nothing",
      not d1 and len(lg1) == 1 and lg1[0]["group"] == "main" and lg1[0]["ids"] == [n_img["id"]] and "image not read" in lg1[0]["text"] and not any(i in lg1[0]["text"] for i in exp_alpha)
      and "1 notice was held" in lg1[0]["text"] and n_img["id"] in ledger()["sent"], (d1, lg1))

# a held-only digest is logged, never pushed
server._message("projects/alpha", "someone left a voicemail about the paper order", "home-beta"); n_v = routing.read("projects/alpha")[-1]
fake("good", answer([(n_v["id"], "held", "", False)])); live.tick()
n_lg0 = len([l for l in lines() if l.get("kind") == "digest_logged"]); p1 = len(pushes()); n_dl0 = len(dlines())
FAIL.write_text("work-osprey-main\nwork-osprey-x\n")
for k_ in range(5): live.digest_tick(now=day(2) + k_ * 60)
check("a held-only digest never pushes, so a failing pane cannot fail it: logged once, marked digested, no error line, nothing tried again",
      len(dlines()) == n_dl0 and not digests(p1) and n_v["id"] in ledger()["sent"] and len([l for l in lines() if l.get("kind") == "digest_logged"]) - n_lg0 == 1, (dlines()[n_dl0:], ledger()["sent"].keys()))
FAIL.unlink()

# ---- 12b. a ruling's note goes to the page's timeline, once; a gbrain failure is logged and the ruling stands; notes = false
GB = {"calls": [], "mode": "ok"}
def fake_gb(args, stdin=None):
    GB["calls"].append(args)
    return (0, '{"status": "ok"}') if GB["mode"] == "ok" else (1, '{"error": "gbrain is down"}')
rp.gb = fake_gb
NOTES = {}; _cp = router.call_project
def cp_notes(*a_, **k_):
    got_, rec_ = _cp(*a_, **k_)
    for ln_ in got_:
        if ln_["id"] in NOTES: ln_["note"] = NOTES[ln_["id"]]       # PR X's optional `note` key of a ruling line
    return got_, rec_
router.call_project = cp_notes
def one(text, note=None, ruling="dropped"):
    server._message("projects/alpha", text, "home-beta"); n_ = routing.read("projects/alpha")[-1]
    if note is not None: NOTES[n_["id"]] = note
    fake("good", answer([(n_["id"], ruling, "", False)])); live.tick(); return n_
today = dt.datetime.now(_cfg.tz()).strftime("%Y-%m-%d")
g0 = len(GB["calls"]); n_a = one("the vendor says the quote is final", "The vendor confirmed the quote is final.")
la = next(l for l in lines() if l.get("id") == n_a["id"]); args_ = json.loads(GB["calls"][g0][2]) if len(GB["calls"]) == g0 + 1 else {}
check("a note on a ruling is written once to the project page's timeline with the gbrain CLI (call add_timeline_entry, JSON args), dated today, source stackshot (router)",
      len(GB["calls"]) == g0 + 1 and GB["calls"][g0][:2] == ["call", "add_timeline_entry"] and args_.get("slug") == "projects/alpha" and args_.get("date") == today
      and args_.get("summary") == "The vendor confirmed the quote is final." and args_.get("source") == "stackshot (router)" and n_a["id"] in args_.get("detail", "") and args_.get("request_id"), (GB["calls"][g0:], la))
check("…the ruling stands and the line records it: ruled, noted", rule_of(n_a["id"])["ruling"] == "dropped" and la["status"] == "ruled" and la["noted"] is True and "note_error" not in la, la)
live.tick(); live.tick()
check("…and a later tick does not write it again", len(GB["calls"]) == g0 + 1)
g0 = len(GB["calls"]); n_b = one("nothing to add here")
check("a ruling with no note writes nothing to the page", len(GB["calls"]) == g0 and rule_of(n_b["id"])["ruling"] == "dropped")
g0 = len(GB["calls"]); n_l = one("a long one", "x" * 400)
check("a note is cut to 300 characters", len(GB["calls"]) == g0 + 1 and len(json.loads(GB["calls"][g0][2])["summary"]) == 300)
GB["mode"] = "fail"; g0 = len(GB["calls"]); n_e2 = one("the page is down today", "A note gbrain will refuse.")
le = next(l for l in lines() if l.get("id") == n_e2["id"])
check("a gbrain failure is logged on the line (note_error) and the ruling stands: ruled, not noted, no retry", len(GB["calls"]) == g0 + 1 and rule_of(n_e2["id"])["ruling"] == "dropped" and le["status"] == "ruled"
      and "timeline note not written" in le["note_error"] and not le.get("noted"), (le, GB["calls"][g0:]))
live.tick(); check("…and it is not tried again", len(GB["calls"]) == g0 + 1)
check("status shows the note failure as the last error", "timeline note not written" in {r["project"]: r for r in live.status()}["projects/alpha"]["last_error"], {r["project"]: r for r in live.status()}["projects/alpha"])
GB["mode"] = "ok"; cfg(live=True, notes=False); g0 = len(GB["calls"]); n_off = one("notes are off", "This note is ignored.")
lo = next(l for l in lines() if l.get("id") == n_off["id"])
check("[router] notes = false: the note is ignored, the ruling stands", len(GB["calls"]) == g0 and rule_of(n_off["id"])["ruling"] == "dropped" and lo["status"] == "ruled" and not lo.get("noted") and "note_error" not in lo, lo)
cfg(live=True); router.call_project = _cp

# ---- 12c. the cap: a ruling that cannot be written is tried three times, then stuck, never judged again, and listed in the next digest
BREAK = set(); _rr = routing.rule
def rr(nid, *a_, **k_):
    if nid in BREAK: raise OSError("disk full")
    return _rr(nid, *a_, **k_)
routing.rule = rr
server._message("projects/alpha", "this ruling cannot be written", "home-beta"); n_c = routing.read("projects/alpha")[-1]; BREAK.add(n_c["id"])
fake("good", answer([(n_c["id"], "dropped", "", False)])); c0 = len(calls())
for _ in range(3): live.tick()
ls_ = [l for l in lines() if l.get("id") == n_c["id"]]
check("a ruling that cannot be written is tried three times (three calls), the third failure logs it stuck, and it stays unruled", [l["status"] for l in ls_] == ["error", "error", "error", "stuck"] and len(calls()) - c0 == 3
      and not rule_of(n_c["id"]).get("ruling") and "could not be ruled" in ls_[-1]["reason"], ([l["status"] for l in ls_], len(calls()) - c0))
c1 = len(calls()); live.tick(); live.tick()
check("…and it is never judged again: no further call, no further line", len(calls()) == c1 and len([l for l in lines() if l.get("id") == n_c["id"]]) == 4)
routing.rule = _rr
p1 = len(pushes()); live.digest_tick(now=day(4)); d4 = digests(p1)
check("…the next digest lists it as one that could not be ruled, to the project's builder (alpha has one), unmarked, not to -main",
      [x[0] for x in d4] == ["work-osprey-x"] and n_c["id"] in d4[0][1] and "COULD NOT BE RULED" in d4[0][1] and "1 could not be ruled" in d4[0][1] and "[for Oliver]" not in d4[0][1], d4)
live.digest_tick(now=day(5))
check("…once: the digest after it does not list it again", len(digests(p1)) == 1)
cli2 = subprocess.run([sys.executable, str(pathlib.Path(STACK, "stackshot/router/router_live.py")), "status"], capture_output=True, text=True, timeout=60, env=dict(os.environ))
check("`router_live.py status` shows the held count and the last digest", cli2.returncode == 0 and "last digest" in cli2.stdout and "held" in cli2.stdout, (cli2.returncode, cli2.stderr[-300:], cli2.stdout[:400]))

# ---- 12d. who gets a digest that holds a notice the router could not rule: the builder unmarked, else -main marked; held rows are only listed with it
routing.rule = rr
server._message("projects/alpha", "the supplier quote is attached for the record", "home-beta"); n_h2 = routing.read("projects/alpha")[-1]
server._message("projects/alpha", "this second ruling cannot be written either", "home-beta"); n_s2 = routing.read("projects/alpha")[-1]; BREAK.add(n_s2["id"])
fake("good", answer([(n_h2["id"], "held", "", False), (n_s2["id"], "dropped", "", False)])); live.tick()
fake("good", answer([(n_s2["id"], "dropped", "", False)])); live.tick(); live.tick()
server._message("projects/gamma", "this gamma ruling cannot be written", "home-beta"); n_g = routing.read("projects/gamma")[-1]; BREAK.add(n_g["id"])
fake("good", answer([(n_g["id"], "dropped", "", False)]))
for _ in range(3): live.tick()
routing.rule = _rr
check("12d setup: alpha has one held and one stuck notice, gamma (no builder) one stuck notice",
      rule_of(n_h2["id"])["ruling"] == "held" and not rule_of(n_s2["id"]).get("ruling") and [l for l in lines() if l.get("id") == n_s2["id"]][-1]["status"] == "stuck"
      and not rule_of(n_g["id"], "projects/gamma").get("ruling") and [l for l in lines() if l.get("id") == n_g["id"]][-1]["status"] == "stuck",
      ([l["status"] for l in lines() if l.get("id") in (n_h2["id"], n_s2["id"], n_g["id"])]))
p2 = len(pushes()); n_lg0 = len([l for l in lines() if l.get("kind") == "digest_logged"]); n_dl0 = len(dlines())
live.SINCE_DAYS = 30            # the test's days run ahead of the clock: keep the notices made above in the window
FAIL.write_text("work-gamma-main\n")
for k_ in range(5): live.digest_tick(now=day(6) + k_ * 60)
da = [x for x in digests(p2) if n_s2["id"] in x[1]]
check("stuck plus held: the digest goes to the builder, unmarked, once, listing the held row and the stuck row; nothing to alpha's -main",
      len(da) == 1 and da[0][0] == "work-osprey-x" and not da[0][1].startswith("[for Oliver]") and "[for Oliver]" not in da[0][1] and n_h2["id"] in da[0][1] and "COULD NOT BE RULED" in da[0][1]
      and "1 notice was held" in da[0][1] and "1 could not be ruled" in da[0][1] and not any(x[0] == "work-osprey-main" for x in digests(p2)), digests(p2))
la_ = [l for l in dlines()[n_dl0:] if l["project"] == "projects/alpha"]
check("…its line of live.jsonl: kind digest, target the builder, not marked, both ids; both notices are digested",
      len(la_) == 1 and la_[0]["target"] == "work-osprey-x" and la_[0]["marked"] is False and la_[0]["status"] == "sent" and sorted(la_[0]["ids"]) == sorted([n_h2["id"], n_s2["id"]])
      and n_h2["id"] in ledger()["sent"] and n_s2["id"] in ledger()["sent"], (la_, list(ledger()["sent"])[-4:]))
eg = [l for l in dlines()[n_dl0:] if l["project"] == "projects/gamma"]
check("stuck with no builder: the digest is for gamma's -main, whose push failed here: an error line, tried three times, not digested",
      len(eg) == 3 and all(l["status"] == "error" and l["target"] == "work-gamma-main" and "was not delivered" in l["error"] for l in eg) and n_g["id"] not in ledger()["sent"]
      and not any(x[0] == "work-gamma-main" for x in digests(p2)), (eg, digests(p2)))
FAIL.unlink(); live.digest_tick(now=day(6) + 7200)
check("…and after the third failure it is left for the next day", not any(x[0] == "work-gamma-main" for x in digests(p2)))
live.digest_tick(now=day(7)); live.digest_tick(now=day(7) + 60); live.digest_tick(now=day(8))
dgm = [x for x in digests(p2) if x[0] == "work-gamma-main"]
check("…the next day it goes to -main, marked [for Oliver] on line 1, once", len(dgm) == 1 and dgm[0][1].startswith("[for Oliver]") and n_g["id"] in dgm[0][1] and "COULD NOT BE RULED" in dgm[0][1]
      and n_g["id"] in ledger()["sent"] and [l for l in dlines() if l["project"] == "projects/gamma" and l["status"] == "sent"][-1]["marked"] is True, (dgm, digests(p2)))
check("…and the held row that went with the stuck one is not listed again, and nothing else was delivered", not any(n_h2["id"] in x[1] for x in digests(p2)[len(da):]) and len(digests(p2)) == 2, [(x[0], x[1][:60]) for x in digests(p2)])
live.SINCE_DAYS = 7

# ---- the retired name-line sessions: the live text and gates name the router, the keeper or the builder; roles.json keeps the role field
from fastmcp.exceptions import ToolError
cfg()
rl = a.session_roles(); fr = a.file_roles()
check("roles: a keeper of a page that lists a user-facing agent keeps role keeper and gains retired (the readers of the role field)",
      rl["work-osprey"] == {"role": "keeper", "project": "projects/alpha", "retired": True} and fr["work-osprey"] == rl["work-osprey"]
      and rl["work-osprey-main"] == {"role": "front", "project": "projects/alpha"} and rl["work-osprey-x"]["role"] == "back", (rl["work-osprey"], rl["work-osprey-main"]))
check("roles: …the keeper of a page with no agent and no hub (delta: a one-session project) is not retired, and is front in the file", "retired" not in rl["work-delta"] and rl["work-delta"]["role"] == "keeper" and fr["work-delta"]["role"] == "front", (rl["work-delta"], fr["work-delta"]))
cfg(live=False, live_projects=["projects/gamma"], shadow=True)
check("roles: …[router] live, live_projects and shadow are no longer read: the same entries", a.session_roles() == rl and a.file_roles() == fr)
cfg()
try: server._gate_needs_session("work-osprey", "projects/alpha", ""); e = ""
except ToolError as x: e = str(x)
check("needs: a retired name-line session is refused, naming who can act", "retired name-line session of projects/alpha" in e and "work-osprey-x" in e and "work-osprey-main" not in e.split("For projects/alpha:")[-1], e)
check("needs: …a background agent is allowed", server._gate_needs_session("work-osprey-x", "projects/alpha", "") == "work-osprey-x")
check("_hub_sessions: no page offers a keeper any more", all(server._hub_sessions(k)[1] == "" for k in ("projects/alpha", "projects/beta", "projects/delta", "projects/eta")), [server._hub_sessions(k)[1] for k in ("projects/alpha", "projects/beta")])
cfg(live=False)
try: server._gate_needs_session("work-osprey", "projects/alpha", ""); e = ""
except ToolError as x: e = str(x)
check("needs: [router] live = false does not open the keeper again (e)", "retired name-line session of projects/alpha" in e, e)
cfg()
check("builder: alpha's builder, none for gamma (-main only), none for a page with no agents (beta)", live.builder("projects/alpha") == "work-osprey-x" and live.builder("projects/gamma") == "" and live.builder("projects/beta") == ""
      and server._builder_agent("projects/alpha") == "work-osprey-x")
check("message gate: an unmarked message to a front agent is sent to the project, where the router rules it (no keeper named)",
      "the project, where the router rules it (to='projects/alpha')" in server._project_takes("projects/alpha") and "steward" not in server._project_takes("projects/alpha"), server._project_takes("projects/alpha"))
try: server._message("work-osprey-main", "unmarked", "home-beta"); e = ""
except ToolError as x: e = str(x)
check("…and the refusal says so", e.startswith("Refused: work-osprey-main is a front agent") and "router rules it" in e and "steward" not in e, e)
out = server._anchors("projects/alpha", who="home-beta")
check("anchors: the list names the router and the keeper, not the retired name-line session", "alpha anchors (router: rules this project; keeper: work-osprey-x" in out.replace("projects/", "") and "steward:" not in out.splitlines()[0], out.splitlines()[0])
cfg(live=False)
check("anchors: [router] live = false changes nothing in the list", server._anchors("projects/alpha", who="home-beta").splitlines()[0] == out.splitlines()[0], server._anchors("projects/alpha", who="home-beta").splitlines()[0])
cfg()
check("the page debt moves to the router (page call off), and says so, for every page", all("the router, which passes the page update" in server._debt_mover(k) for k in ("projects/alpha", "projects/beta")), server._debt_mover("projects/alpha"))
_pdl = server._page_debt.live; server._page_debt.live = lambda: True
check("…or to the audit's page call while it is live", server._debt_mover("projects/alpha").startswith("the audit's page call"))
server._page_debt.live = _pdl
_op = _cfg.CFG.setdefault("fleet", {}).get("operator_session")
_cfg.CFG["fleet"]["operator_session"] = "work-osprey"
check("fleet recovery: a retired name-line session named as the operator resolves to its project's keeper, never to itself", server._fleet_builder() == "work-osprey-x", server._fleet_builder())
_cfg.CFG["fleet"]["operator_session"] = _op or ""
p_f = len(pushes()); to_f = server._page_debt_fallback("projects/alpha", {S: {"ts": time.time(), "item": "a1", "moved": True}}, [("a1", "changed", "work-osprey-main")], "the call failed", time.time()); settle()
check("page debt fallback: a project's page update goes to its builder, unmarked, not to the -main agent or the retired name-line session",
      to_f == "work-osprey-x" and [x[0] for x in pushes()[p_f:]] == ["work-osprey-x"] and "[for Oliver]" not in pushes()[p_f][1] and "yours to write" in pushes()[p_f][1], (to_f, pushes()[p_f:]))
check("anchor-hub: a log-only line is kept as the hub wrote it for every project (there is no keeper's digest to promise it to)",
      core.Hub._why_for("projects/alpha", "log-only: x") == "log-only: x" and core.Hub._why_for("projects/beta", "log-only: x") == "log-only: x")

# ---- 18. the fallback chain (a board item): a page with no agent of its own falls to its hub's -main, else the scope's general -main (home-commons-main;
# work: the -main of projects/work-commons, home's when there is none; ops: heron-main); a page with agents is ruled by the router like any other
cfg()
check("(a) a page that lists agents and is on no [pilot] projects list (eta, whose keeper home-eta has no pane) is the router's, its stand-in is its own -main agent", live.is_live("projects/eta") and live.stand_in("projects/eta") == "home-eta-main" and live.stand_in("projects/iota") == "home-iota-main", live.stand_in("projects/eta"))
check("(b) a page with no agent of its own falls to its hub's -main: theta (hub eta) → home-eta-main, epsilon (hub gamma) → work-gamma-main", live.stand_in("projects/theta") == "home-eta-main" and live.stand_in("projects/epsilon") == "work-gamma-main"
      and a.fallback_main("projects/theta") == "home-eta-main", (live.stand_in("projects/theta"), live.stand_in("projects/epsilon")))
check("(c) a standalone page falls to the scope's general -main: an home page (beta) and a work page (delta, no projects/work-commons) → home-commons-main", a.fallback_main("projects/beta") == "home-commons-main" and a.fallback_main("projects/delta") == "home-commons-main"
      and a.general_main("projects/delta")[1] == "projects/example-general", (a.fallback_main("projects/beta"), a.fallback_main("projects/delta"), a.general_main("projects/delta")))
reg2 = {**a.registry(), "projects/work-commons": page("Work general", "work-commons", agents={"work-commons-main": "the ACME general contact"}),
        "ops/general": page("Harbor general", "heron", agents={"heron-main": "the ops general contact"}), "ops/solo": page("Solo", "ops-solo"),
        "projects/work-solo": page("Work solo", "work-solo"), "projects/home-solo": page("Home solo", "home-solo")}
check("(c) …with projects/work-commons in the registry a work page falls to its -main, an ops page to heron-main, an home page to home-commons-main",
      a.fallback_main("projects/work-solo", reg2) == "work-commons-main" and a.fallback_main("ops/solo", reg2) == "heron-main" and a.fallback_main("projects/home-solo", reg2) == "home-commons-main",
      [a.fallback_main(k, reg2) for k in ("projects/work-solo", "ops/solo", "projects/home-solo")])
# a general page that lists no agent but has a name line (a `display-name:` and no agents map) is a one-session page: the scope's general agent is its own session
reg3 = {**a.registry(), "projects/work-commons": page("Work general", "work-commons"), "projects/work-solo": page("Work solo", "work-solo")}
check("(c) a general page with a name line and no agents map: a work page with no agent falls to its session, end to end through fallback_main and general_main",
      a.fallback_main("projects/work-solo", reg3) == "work-commons" and a.general_main("projects/work-solo", reg3) == ("work-commons", "projects/work-commons"),
      (a.fallback_main("projects/work-solo", reg3), a.general_main("projects/work-solo", reg3)))
check("(c) …a page with agents of its own and a page under a hub are unchanged by it: the page's own -main, the hub's -main", a.fallback_main("projects/epsilon", reg3) == "work-gamma-main" and a.fallback_main("projects/gamma", reg3) == "work-gamma-main",
      (a.fallback_main("projects/epsilon", reg3), a.fallback_main("projects/gamma", reg3)))
reg3["projects/work-commons"] = page("Work general", "work-commons", agents={"work-commons-main": "the general contact"})
check("(c) …a general page that lists an agent keeps its -main agent, not its name-line session", a.general_main("projects/work-solo", reg3) == ("work-commons-main", "projects/work-commons") and a.fallback_main("projects/work-solo", reg3) == "work-commons-main",
      a.general_main("projects/work-solo", reg3))
reg3["projects/work-commons"] = page("Work general", "work-commons", agents={"work-commons-bg": "builds"}, back_agents={"work-commons-bg": "builds"})
check("(c) …a general page that lists background agents only has no front agent: its name-line session", a.general_main("projects/work-solo", reg3) == ("work-commons", "projects/work-commons"), a.general_main("projects/work-solo", reg3))
reg3["projects/work-commons"] = page("Work general", "work-commons", role="inherited")
check("(c) …a page whose session line is an agent's or inherited from its parent is no name line: the work page falls on to home's general -main", a.fallback_main("projects/work-solo", reg3) == "home-commons-main", a.fallback_main("projects/work-solo", reg3))
reg3["projects/work-commons"] = page("Work general", "cse_0123456789abcdef")
check("(c) …a name line that is a session id is no agent either", a.fallback_main("projects/work-solo", reg3) == "home-commons-main", a.fallback_main("projects/work-solo", reg3))
del reg3["projects/work-commons"]
check("(c) …a scope whose general page is not in the registry still falls to the default scope's general agent", a.fallback_main("projects/work-solo", reg3) == "home-commons-main" and a.general_main("projects/work-solo", reg3)[1] == "projects/example-general",
      a.general_main("projects/work-solo", reg3))
cfg(general_home="home-eta-main", general_ops="projects/eta", general_work="projects/nowhere")
check("(c) …the general_* keys are config: an agent name or a page key, and a work value that resolves to nothing falls back to home's", a.fallback_main("projects/beta") == "home-eta-main" and a.fallback_main("ops/solo", reg2) == "home-eta-main" and a.fallback_main("projects/delta") == "home-eta-main",
      [a.fallback_main(k, reg2) for k in ("projects/beta", "ops/solo", "projects/delta")])
cfg()
_pil = _cfg.CFG.get("pilot"); _cfg.CFG["pilot"] = {**(_pil or {}), "projects": ["projects/alpha"]}
check("a leftover [pilot] projects list is ignored: every page is the router's", live.is_live("projects/beta") and live.is_live("projects/eta") and a.pilot_root("projects/beta") == "projects/beta" and a.pilot_root("projects/nowhere") == "")
_cfg.CFG["pilot"] = _pil if _pil is not None else {}
cfg(live=True)
p_e = len(pushes()); r_e = server._message("projects/eta", "audit batch for the general page", "home-beta"); n_e = routing.read("projects/eta")
check("(d) a message to eta's page key is held for the router, not delivered to the keeper home-eta or to anyone", "router" in r_e, r_e)
check("(d) …the routing line is live and records no keeper as the recipient; nothing was pushed", n_e and n_e[-1].get("live") is True and n_e[-1]["to"] != "home-eta" and len(pushes()) == p_e, (n_e[-1:] if n_e else n_e, pushes()[p_e:]))
fake("good", answer([(n_e[-1]["id"], "passed", "home-eta-main", True)])); live.tick(); settle()
check("(d) …the router passes it to the page's -main agent, marked, ruled by the router", [x[0] for x in pushes()[p_e:]] == ["home-eta-main"] and pushes()[p_e][1].startswith("[for Oliver]") and rule_of(n_e[-1]["id"], "projects/eta")["ruled_to"] == "home-eta-main", (pushes()[p_e:], routing.read("projects/eta")[-1]))
p_e = len(pushes()); r_e2 = server._message("projects/theta", "hub-keyed", "home-beta"); n_t = routing.read("projects/theta")[-1]
fake("good", answer([(n_t["id"], "passed", "home-eta-main", True)])); live.tick(); settle()
check("(d) a message to a sub-page (theta, hub eta) is held, then reaches the hub's -main agent", n_t.get("live") is True and [x[0] for x in pushes()[p_e:]] == ["home-eta-main"] and "Project: projects/eta" in calls()[-1]["stdin"], (pushes()[p_e:], calls()[-1]["stdin"][:300]))
p_b = len(pushes()); server._message("projects/beta", "beta has no agent and no hub", "home-eta-main"); n_b = routing.read("projects/beta")[-1]
check("(d) a message to a page with no agent (beta, whose keeper home-beta runs a pane) is held for the router too, not delivered to home-beta", n_b.get("live") is True and n_b["to"] != "home-beta" and len(pushes()) == p_b, (n_b, pushes()[p_b:]))
fake("good", answer([(n_b["id"], "passed", "home-commons-main", True)])); live.tick(); settle()
check("(d) …and the router passes it to the scope's general -main", [x[0] for x in pushes()[p_b:]] == ["home-commons-main"] and rule_of(n_b["id"], "projects/beta")["ruled_to"] == "home-commons-main", (pushes()[p_b:], routing.read("projects/beta")[-1]))
check("(d) …and the thin call was told of the general -main as the page's one agent", "home-commons-main" in calls()[-1]["stdin"], calls()[-1]["stdin"][:400])
p_i = len(pushes()); server._message("projects/iota", "its keeper's pane is up", "home-eta-main"); n_i = routing.read("projects/iota")[-1]
check("(d) a page that lists an agent but whose keeper's pane runs (iota: home-beta) is held for the router, never delivered to the keeper", n_i.get("live") is True and len(pushes()) == p_i and n_i["to"] != "home-beta", (n_i, pushes()[p_i:]))
routing.rule(n_i["id"], "dropped", by="test")      # settled by hand, so the later ticks of this file make no call for it
check("retired page: an unmarked message to its -main agent is refused with the page key, not the retired name-line session",
      "the project, where the router rules it (to='projects/eta')" in server._project_takes("projects/eta") and "steward" not in server._project_takes("projects/eta"), server._project_takes("projects/eta"))
try: server._message("home-eta-main", "unmarked", "home-beta"); e = ""
except ToolError as x: e = str(x)
check("…the refusal names projects/eta, not home-eta", e.startswith("Refused: home-eta-main is a front agent") and "to='projects/eta'" in e and "home-eta " not in e and "steward" not in e, e)
SJ = T / "fleet/a/sessions.json"; SJ_SAVE = SJ.read_text()
p_a = len(pushes())
try: server._message("home-eta", "to the retired name-line session", "home-beta"); e = ""
except ToolError as x: e = str(x)
check("retired-name: a message to the retired name-line session of projects/eta is refused, naming the page key, where the router rules it", e.startswith("Refused:") and "message(to='projects/eta'" in e and "the project, where the router rules it (to='projects/eta')" in e and len(pushes()) == p_a, (e, pushes()[p_a:]))
SJ.write_text(json.dumps({**json.loads(SJ_SAVE), "ffffffff-ffff-4fff-8fff-ffffffffffff": {"name": "home-eta", "machine": "a", "url": "", "seen": "x"}}))
try: server._message("home-eta", "to a keeper whose pane runs", "home-beta"); e = ""
except ToolError as x: e = str(x)
check("retired-name: …but a keeper whose pane is running under that name is a pane and is delivered to, as before", e == "" and [x[0] for x in pushes()[p_a:]] == ["home-eta"], (e, pushes()[p_a:]))
_gone = (__import__("datetime").datetime.now(__import__("datetime").timezone.utc) - __import__("datetime").timedelta(hours=2)).isoformat().replace("+00:00", "Z")
SJ.write_text(json.dumps({**json.loads(SJ_SAVE), "ffffffff-ffff-4fff-8fff-ffffffffffff": {"name": "home-eta", "machine": "a", "url": "", "seen": "x", "gone": _gone}}))
p_a = len(pushes())
try: server._message("home-eta", "to the retired name-line session, its row gone", "home-beta"); e = ""
except ToolError as x: e = str(x)
check("retired-name: a retired name-line session that has a gone row is refused (the retired-and-not-running branch), naming the page key", a.session_roles()["home-eta"].get("retired") and e.startswith("Refused: 'home-eta' cannot receive this (a retired name-line session") and "message(to='projects/eta'" in e and len(pushes()) == p_a, (e, pushes()[p_a:]))
SJ.write_text(SJ_SAVE)
check("retired-name: a retired name-line session (the router is live for projects/alpha) whose pane is running is still delivered to: a running pane is a pane",
      a.session_roles()["work-osprey"].get("retired") and server._message("work-osprey", "to a running retired name-line session", "home-beta").startswith("delivered") and [x[0] for x in pushes()[p_a:]][-1:] == ["work-osprey"], pushes()[p_a:])
check("the keeper of eta's items is its -main agent, of theta's the hub's; none is a retired name-line session", server._keeper("projects/eta") == "home-eta-main" and server._keeper("projects/theta") == "home-eta-main"
      and server._page_keeper("projects/eta") == "home-eta-main", (server._keeper("projects/eta"), server._keeper("projects/theta")))
# ---- 19. review of the one-session-keeper change: a one-session page keeps its own session as keeper; a nameless page's debts reach the general -main agent
check("one-session page (beta: a name line, no agents map): the keeper of its items is that session, whoever owns the item; the general -main agent is not its keeper",
      server._keeper("projects/beta", "home-beta") == "home-beta" and server._keeper("projects/beta", "home-other") == "home-beta" and server._page_keeper("projects/beta") == "home-beta"
      and server._stand_in_keeper("projects/beta") == "home-commons-main", (server._keeper("projects/beta", "home-beta"), server._keeper("projects/beta", "home-other")))
check("one-session page: an item moved by the name-line pane on its own page has that pane as the session its notices go to (wake, done-check, completion anchor)",
      server._notice_to({"mover": "home-beta", "project": "projects/beta"}) == [(server._session_id("home-beta"), "as its mover")] and server._keeper("projects/beta", "home-beta") == "home-beta"
      and server._notice_to({"mover": "home-other", "project": "projects/beta"}) == [(server._session_id("home-other"), "as its mover")], (server._notice_to({"mover": "home-beta", "project": "projects/beta"}), server._notice_to({"mover": "home-other", "project": "projects/beta"})))
_pj_save = (T / "store/projects.json").read_text(); _pj = json.loads(_pj_save)
_pj["pages"]["ops/general"] = page("Harbor general", "heron", agents={"heron-main": "the ops general contact"})
_pj["pages"]["ops/note-x"] = page("Note X", ""); _pj["pages"]["ops/note-x/child"] = page("Note X child", "")      # pages with no `session:` line and no agents (ops/* note pages)
_pj["pages"]["projects/bgonly"] = page("Bg only", "home-bg", hub="projects/eta", agents={"home-bg-docs": "keeps the pages"}, back_agents={"home-bg-docs": "keeps the pages"})
(T / "store/projects.json").write_text(json.dumps(_pj))
check("a page with background agents only is served by its hub's -main agent, the same in the stand-in and in anchors.fallback_main", live.stand_in("projects/bgonly") == "home-eta-main" == a.fallback_main("projects/bgonly"), (live.stand_in("projects/bgonly"), a.fallback_main("projects/bgonly")))
check("a nameless page's notices are addressed to its scope's general -main agent, and that agent is front there: (True, no keeper), so a pass to it is marked", a.notice_name("ops/note-x") == "heron-main" and a.notice_name("ops/note-x/child") == "heron-main"
      and server._front_keeper("heron-main", "ops/note-x") == (True, "") and server._front_keeper("heron-main", "ops/note-x/child") == (True, ""), (server._front_keeper("heron-main", "ops/note-x"), a.notice_name("ops/note-x")))
item(30, "ops/note-x", "work-osprey-main"); item(31, "ops/note-x/child", "work-osprey-main")
p_n = len(pushes()); n_log = len(routing.read("ops/note-x"))
who_, role_ = server._pilot_charge("ops/note-x", "work-osprey-x")
check("a nameless page: a board change is charged to the router (the address of its notices), not passed by as a front keeper", who_ == server._session_id("heron-main") and role_ == "name", (who_, role_))
r_ = server._pilot_relay("ops/note-x", "a30", server._load("a30"), "changed (next)", "work-osprey-x", "heron-main", "name"); settle()
ln_ = routing.read("ops/note-x")[n_log:]
check("a nameless page: the board relay is held for the router (live line, stashed, nobody pushed)", "charged to the router" in r_ and len(ln_) == 1 and ln_[0].get("live") is True and ln_[0]["to"] == "" and live.stashed(ln_[0]["id"]) and len(pushes()) == p_n, (r_, ln_, pushes()[p_n:]))
p_n = len(pushes()); n_log = len(routing.read("ops/note-x"))
to_n = server._page_debt_fallback("ops/note-x", {S: {"ts": time.time(), "item": "a30", "moved": True}}, [("a30", "changed", "work-osprey-x")], "the call failed", time.time()); settle()
ln_ = routing.read("ops/note-x")[n_log:]
check("page debt fallback on a page with no `session:` line: the debt is delivered to the general -main agent with the mark, in a routing line ruled passed to it; it is not held for the router and forgotten",
      to_n == "heron-main" and [x[0] for x in pushes()[p_n:]] == ["heron-main"] and pushes()[p_n][1].startswith("[for Oliver]") and "yours to write" in pushes()[p_n][1]
      and len(ln_) == 1 and ln_[0]["to"] == "heron-main" and not ln_[0].get("live") and not live.stashed(ln_[0]["id"]) and ln_[0].get("ruling") == "passed" and ln_[0].get("ruled_to") == "heron-main", (to_n, pushes()[p_n:], ln_))
# review round 2: the 30-minute move of a nameless page's debt (page call not live), a sub-page's own agent, a one-session page's front-agent owner, the completion anchor
_pj["pages"]["ops/note-x/kept"] = page("Note X kept", "work-osprey-main", role="agent")      # a sub-page kept by a front agent (role agent): its `session:` is its agent, not the project's keeper
(T / "store/projects.json").write_text(json.dumps(_pj))
check("the page call is not live here (the 30-minute move below is the relay of today)", not server._page_debt.live())
p_n = len(pushes()); n_log = len(routing.read("ops/note-x"))
server._owed_mark("ops/note-x", "work-osprey-x", "a30", settle="ct", moves="heron-main", what="changed (next)")
k_n = server._pilot_fallback_tick(time.time() + 31 * 60); settle()
ln_ = routing.read("ops/note-x")[n_log:]
check("30-minute move on a nameless page (page call not live): the debt that moved to the general -main agent is held for the router in one routing line, not dropped",
      k_n == 1 and len(ln_) == 1 and ln_[0].get("live") is True and ln_[0]["to"] == "" and live.stashed(ln_[0]["id"]) and len(pushes()) == p_n, (k_n, ln_, pushes()[p_n:]))
check("a sub-page kept by a front agent (ops/note-x/kept, role agent, nameless root): the agent is front there, its `session:` is no keeper of the project",
      server._front_keeper("work-osprey-main", "ops/note-x/kept")[0] is True and server._pilot_keeper("ops/note-x/kept") == ("work-osprey-main", "agent"), (server._front_keeper("work-osprey-main", "ops/note-x/kept"), server._pilot_keeper("ops/note-x/kept")))
who_, role_ = server._pilot_charge("ops/note-x/kept", "work-osprey-x")
check("…a board change on it is charged to the router (the address of the project's notices), never to the front agent", who_ == server._session_id("heron-main") and role_ == "name", (who_, role_))
k_, r_k = server._pilot_keeper("ops/note-x/kept"); p_n = len(pushes())
res_ = server._pilot_relay("ops/note-x/kept", "a31", server._load("a31"), "changed (next)", "work-osprey-x", k_, r_k); settle()
check("…and the relay to the agent keeper pushes nothing unmarked to it", res_ == "" and len(pushes()) == p_n and not [x for x in pushes() if x[0] == "work-osprey-main" and "the page update is yours" in x[1]], (res_, pushes()[p_n:]))
check("a front agent that owns an item on a one-session page (beta, name line home-beta): its keeper is the page's own session, not the general -main agent", server._front_keeper("home-eta-main", "projects/beta") == (True, "home-beta"), server._front_keeper("home-eta-main", "projects/beta"))
check("…a reminder for an item it moves goes to the mover itself (no keeper stands in for a front agent)", server._reminder_to({"mover": "home-eta-main", "project": "projects/beta"})[:1] == [(server._session_id("home-eta-main"), "as its mover")], server._reminder_to({"mover": "home-eta-main", "project": "projects/beta"}))
_an = json.loads((T / "store/anchors.json").read_text()); _an["projects/beta"].append({"url": "https://x.slack.com/archives/C0000000009", "items": ["a40"], "added": 1, "by": "t"}); (T / "store/anchors.json").write_text(json.dumps(_an))
item(40, "projects/beta", "home-other", status="completed")
p_n = len(pushes()); txt_ = server._completion_anchor_prompt("a40", server._load("a40")); settle()
check("completion anchor on a one-session page: the keeper told is the page's own session (home-beta), not the general -main agent", "(keeper home-beta notified)" in txt_ and [x[0] for x in pushes()[p_n:]] == ["home-beta"], (txt_, pushes()[p_n:]))
(T / "store/anchors.json").write_text(json.dumps({**_an, "projects/beta": _an["projects/beta"][:-1]}))
(T / "store/projects.json").write_text(_pj_save)
item(21, "projects/eta", "home-beta", status="open", needs=[])
got = server.stackshot_get("a21")
check("get shows the -main agent as the mover of an item whose needs names no session and which has no mover stored (the creator is nothing), not the retired name-line session", "mover: home-eta-main" in got and "home-eta (" not in got and "mover: home-eta\n" not in got, got)
try: server._gate_needs_session("home-eta", "projects/eta", ""); e = ""
except ToolError as x: e = str(x)
check("…the gate refuses naming the retired name-line session", "retired name-line session of projects/eta" in e, e)
out = server._anchors("projects/eta", who="home-beta")
check("anchors: the list names the keeper of the page, not the one-session name-line session", out.splitlines()[0].startswith("projects/eta anchors (router: rules this project; keeper: home-eta-main"), out.splitlines()[0])
cfg()

# ---- 13. a close with Oliver's words on the item is a row on his For you list (and a routine close is not)
# a front agent owner was told a close only when his own words were on the item (a `said` entry, or a quoted attribution; a
# board answer alone is not his words about the close), by the router, in one line with the mark a front pane takes. Such a close
# is a row on his For you list and no turn of the front agent: no router notice, no [for Oliver] push, router live or not.
# Otherwise a front owner hears nothing, as before.
server._refuse_if_owing = lambda debtor: None        # the page rule is not under test here
NEWD = "- The thing works and is in use"
def cl(i, sender="work-osprey-x", reason="PR 33 is live", description=NEWD): return server.stackshot_complete(f"a{i}", outcome="done", reason=reason, description=description, sender=sender)
ANS = [{"ts": 1.0, "kind": "decision", "choice": "Go", "via": "board"}]
SAID = [{"tag": "Acked-by", "quote": "go ahead", "msg": "m1", "session": "s1", "ts": 1.0, "checked": True}]
item(20, "projects/alpha", A, said=SAID); item(21, "projects/alpha", A); item(22, "projects/alpha", A, said=SAID); item(23, "projects/alpha", A, said=SAID)
item(24, "projects/alpha", A); item(25, "projects/alpha", A, answers=[{"ts": 1.0, "kind": "comment", "text": "ok", "via": "github"}]); item(26, "projects/alpha", A, answers=[]); item(27, "projects/alpha", A)
item(31, "projects/alpha", A, answers=ANS)
cfg(live=True)
p13 = len(pushes()); n13 = len(routing.read("projects/alpha"))
from stackshot.web import foryou as fy
fy_rows = lambda g, kind="closed": [r for r in fy.rows() if r.get("gid") == g and r["kind"] == kind]
out20 = cl(20); settle()
new13 = routing.read("projects/alpha")[n13:]; c20 = [n for n in new13 if n.get("label") == "close a20"]
check("close, Oliver's `said` entry on it, owner a front agent, router live: a row on his For you list; nothing is recorded for the router; the owner is pushed its own one marked line at once (Sun Oct 25th 2026); the reply says both",
      len(fy_rows("a20")) == 1 and not c20 and [x[1] for x in pushes()[p13:] if x[0] == A or "a20" in x[1] and "closed" in x[1]] == ["[for Oliver] [stackshot] a20 [home] item 20: closed by work-osprey-x: done (PR 33 is live) \u2192 https://stackshot.example.com/items/a20"]
      and "is a row on his For you list" in out20 and "not a message to" not in out20 and "told at once that it was closed" in out20 and "not told" not in out20, (fy.rows(), c20, pushes()[p13:], out20))
check("…the row: who closed it, the outcome, the subject, the reason (the item id is shown beside it, not inside), and the link",
      fy_rows("a20")[0]["what"] == "closed by work-osprey-x (done): [home] item 20 — PR 33 is live" and fy_rows("a20")[0]["url"].endswith("/items/a20") and "\n" not in fy_rows("a20")[0]["what"], fy_rows("a20"))
cw = [x for x in new13]
for _n in cw: routing.rule(_n["id"], "dropped", by="test")      # the page-update notices of the close: settled by hand, this section is about the owner's
fake("good", "[]"); calls0 = len(calls()); t13 = live.tick(); p13b = [x for x in pushes()[p13:] if x[0] == "work-osprey-main"]
check("the router's tick has nothing of the close to rule or deliver: no call, nothing marked [for Oliver] reaches the owner by the router's name (the one line of the close went by id, from the server)", len(calls()) == calls0 and not [x for x in p13b if "[for Oliver]" in x[1]], (calls()[calls0:], p13b))
out21 = cl(21); settle()
check("close, no words of his on it and not watched: no row, nothing is recorded for the router; the front agent owner is told by the one marked line (it was told nothing before), and the reply says so",
      "told at once that it was closed" in out21 and "not told" not in out21 and not fy_rows("a21") and not [n for n in routing.read("projects/alpha")[n13:] if n.get("label") == "close a21"]
      and len([x for x in pushes()[p13:] if x[0] == A and "a21" in x[1]]) == 1, (out21, pushes()[p13:]))
p13c = len(pushes()); out22 = cl(22, sender="work-osprey-main"); settle()
check("the owner closing its own item with his words on it: nobody tells it, no notice is recorded; the row is made all the same (the list is his)",
      "front agent" not in out22 and "told at once" not in out22 and not [n for n in routing.read("projects/alpha")[n13:] if n.get("label") == "close a22"] and not [x for x in pushes()[p13c:] if x[0] == "work-osprey-main"] and len(fy_rows("a22")) == 1, (out22, pushes()[p13c:], fy.rows()))
out23 = cl(23); out25 = cl(25); out26 = cl(26); out31 = cl(31); settle()
lbl = lambda l: [n for n in routing.read("projects/alpha")[n13:] if n.get("label") == l]
check("a `said` entry counts as his words (a row); an empty answers list does not (no row, the quiet line)",
      len(fy_rows("a23")) == 1 and not lbl("close a23") and not fy_rows("a26") and "told at once that it was closed" in out26 and "not told" not in out26, (fy_rows("a23"), lbl("close a23"), out26))
check("a board answer alone (his choice on the buttons, or his comment from GitHub) is not his words about the close, so the reply does not say 'a row for his words' (but he answered on the item, so he watches it: a row each, Sat Oct 24th 2026); "
      "the owner is told by its own one line each, nothing recorded for the router",
      not lbl("close a31") and not lbl("close a25") and "not told" not in out31 and "told at once that it was closed" in out31 and "told at once that it was closed" in out25 and "not told" not in out25 and len(fy_rows("a31")) == 1 and len(fy_rows("a25")) == 1
      and len([x for x in pushes()[p13:] if x[0] == A and "a31" in x[1]]) == 1 and len([x for x in pushes()[p13:] if x[0] == A and "a25" in x[1]]) == 1, (lbl("close a31"), lbl("close a25"), out31, out25, fy.rows()))
out24 = cl(24, reason="CI is green", description='- The thing works\n- Oliver, Fri Jan 9th 2099: "go ahead once the checks pass"'); out27 = cl(27, reason='Oliver, Mon Jan 12th 2099: "no longer needed"')
check("a quoted attribution in the description or the close's reason counts as his words (the loosest signal): a row each, no notice for the router",
      len(fy_rows("a24")) == 1 and len(fy_rows("a27")) == 1 and not lbl("close a24") and not lbl("close a27") and "For you list" in out24 and "For you list" in out27, (fy_rows("a24"), fy_rows("a27")))
cfg(live=False)
item(28, "projects/alpha", A, said=SAID); item(29, "projects/alpha", A); p13d = len(pushes())
out28 = cl(28); settle(); to_main28 = [x for x in pushes()[p13d:] if x[0] == A and "a28" in x[1]]       # a notice the server pushes itself names its session by id
check("[router] live = false is no longer read: the same close is a row too, and the front agent owner is pushed its one marked line, the same as before",
      len(to_main28) == 1 and to_main28[0][1].startswith("[for Oliver] [stackshot] a28 [home] item 28: closed by work-osprey-x: done (PR 33 is live)") and len(fy_rows("a28")) == 1
      and "is a row on his For you list" in out28 and "not a message to" not in out28 and "told at once that it was closed" in out28, (to_main28, out28, fy.rows()))
out29 = cl(29); settle()
check("[router] live = false is no longer read, no words of his: the owner is told by its one marked line, no keeper is told in its place", len([x for x in pushes()[p13d:] if x[0] == A and "a29" in x[1]]) == 1 and "has been told instead" not in out29
      and "told at once that it was closed" in out29 and not fy_rows("a29"), out29)

cfg(live=True)
item(30, "projects/epsilon", "work-gamma-main", said=SAID); p13e = len(pushes()); n13e = len(routing.read("projects/epsilon"))
out30 = server.stackshot_complete("a30", outcome="done", reason="PR 34 is live", description=NEWD, sender="home-beta")
c30 = [n for n in routing.read("projects/epsilon")[n13e:] if n.get("label") == "close a30"]
for _n in routing.read("projects/epsilon")[n13e:]: routing.rule(_n["id"], "dropped", by="test")      # the page-update notice of the close: settled by hand, so the router's later tick makes no call for it
settle(); p30 = [x for x in pushes()[p13e:] if x[0] == "work-gamma-main" and "a30 closed" in x[1]]
p30b = [x for x in pushes()[p13e:] if "a30 " in x[1] and "[for Oliver]" in x[1]]
check("a hub component root (projects/epsilon, hub projects/gamma): a close with a said entry, owner listed on the hub page, is a row too (the row names the component as its project), with no router notice and no old-style message; the owner's one marked line (Sun Oct 25th 2026) is the only push marked for it",
      len(fy_rows("a30")) == 1 and fy_rows("a30")[0]["project"] == "projects/epsilon" and not c30 and not p30 and len(p30b) == 1 and "closed by home-beta: done (PR 34 is live)" in p30b[0][1], (fy.rows(), c30, p30, p30b))
cfg(live=True)

# ---- 13b. an item a session hands back to its front agent owner alone is told to the owner in one line (nothing else wakes a front agent)
# a write by another session that leaves needs naming only the owner, when it named someone else (or others beside it) before,
# was the one item notice a front agent owner heard. Since stackshot hands nothing to a front agent by itself: the project's builder is told instead
# (pushed to it, not recorded for the router), and when the builder wrote the hand-back itself, or the project has none, nobody is told and the board shows it.
BK = "work-osprey-x"
_cfg.CFG.setdefault("board", {})["handback_hold_seconds"] = 0      # a hand-back line is held 3 minutes by default; the checks below are about its delivery and ruling, so no hold here (the hold has its own suite: fewer_wakes)
HB_NEXT = "Oliver: Review the PR and merge it\nOliver: then tell the site"
def hb(i, needs=None, sender=BK, **kw):      # next opens with Oliver, so the stored state is his (step= stores your-step), not an agent's
    kw.setdefault("step", "Review the PR and merge it")
    return server._update(f"a{i}", needs=needs or [A], next=kw.pop("next", HB_NEXT), sender=sender, **kw)
def hb_pushes(i, since, who=A, name="work-osprey-main"): return [x for x in pushes()[since:] if x[0] in (who, name) and f"a{i}" in x[1]]       # the server pushes by id, the router by name
def hb_notes(i, since_n): return [n for n in routing.read("projects/alpha")[since_n:] if n.get("label") == f"hand-back a{i}"]
def hb_dropall(since_n=0):
    for _n in routing.read("projects/alpha")[since_n:]:
        if not _n.get("label", "").startswith("hand-back") and not _n.get("ruling"): routing.rule(_n["id"], "dropped", by="test")
def hb_tick(): fake("good", "[]"); live.tick(); settle()      # the router delivers the hand-backs it holds (a rule in code: no call)
cfg(live=True); hb_dropall()      # what earlier sections left unruled is settled by hand, so the tick judges only this section's
DC = "work-osprey-docs"      # a background agent that is not the project's builder (work-osprey-x builds)
item(50, "projects/alpha", A, then=A, needs=[X]); p50 = len(pushes()); n50 = len(routing.read("projects/alpha"))
out50 = hb(50); settle(); h50 = hb_notes(50, n50)
check("hand-back, router live: the builder leaves needs naming the front agent owner alone: stackshot hands the item to nobody, since the writer is the builder: nothing recorded for the router, nothing pushed, the reply says so",
      not h50 and not hb_pushes(50, p50) and not hb_pushes(50, p50, X, BK) and "nobody is told: a front agent is not handed an item on stackshot's own motion" in out50 and "told it is back with them alone" not in out50, (h50, pushes()[p50:], out50[-300:]))
check("…the routing log says it was held, by stackshot (auto), for the owner",
      [n for n in routing.read("projects/alpha")[n50:] if n.get("ruling") == "held" and n.get("ruled_by") == "stackshot (auto)" and n.get("target") == "for work-osprey-main" and "hand-back" in n.get("reason", "")] != [], routing.read("projects/alpha")[n50:])
p50b = len(pushes()); n50b = len(routing.read("projects/alpha")); out50b = hb(50, [A], next="Oliver: a second look"); settle()
check("…the same needs written again (already the owner alone) is no hand-back: nothing recorded, nothing pushed", not hb_notes(50, n50b) and not hb_pushes(50, p50b), (hb_notes(50, n50b), out50b[-200:]))
item(70, "projects/alpha", A, then=A, needs=[DC]); p70 = len(pushes()); n70 = len(routing.read("projects/alpha"))
held.take(BK); h70 = held.count(BK)
out70 = hb(70, sender=DC); settle(); d70 = hb_pushes(70, p70, X, BK); t70 = held.take(BK)
check("hand-back by another background agent (an earlier review): the project's builder is passed the hand-back line for its next turn (held: it asks the builder nothing), not woken by a turn of its own; the line is reworded to say it is back with the front agent and that it is told to the builder, not to the front agent; the owner is told nothing and nothing is recorded for the router",
      not d70 and h70 == 0 and t70.count("a70 is back with") == 1 and "[stackshot] a70 is back with work-osprey-main, a front agent, alone (handed back by work-osprey-docs): [home] item 70; next: Oliver: Review the PR and merge it \u2192 " in t70
      and "told to you, not to work-osprey-main" in t70 and "[for Oliver]" not in t70
      and not hb_pushes(70, p70) and not hb_notes(70, n70) and "its builder work-osprey-x is passed a note that it is back with them alone, not them (a note for its next turn, not a wake-up)" in out70, (d70, t70, hb_notes(70, n70), pushes()[p70:], out70[-300:]))
cfg(live=False)
item(51, "projects/alpha", A, then=A, needs=[X]); p51 = len(pushes()); n51 = len(routing.read("projects/alpha"))
out51 = hb(51); settle()
check("hand-back, [router] live = false (no longer read): the same as live: nobody is told when the builder wrote it, nothing recorded", not hb_pushes(51, p51) and not hb_notes(51, n51) and "nobody is told" in out51, (pushes()[p51:], out51[-300:]))
cfg()
item(52, "projects/alpha", A, then=A, needs=[X, B]); p52 = len(pushes()); n52 = len(routing.read("projects/alpha"))
out52 = hb(52, [A, "work-osprey-docs"]); settle()
check("needs narrowing to the owner and another session: no hand-back line (the owner is not alone) and no step line either (a builder's step is never pushed to a front agent owner); the other session is told it is named",
      not hb_pushes(52, p52) and not hb_notes(52, n52) and "back with them alone" not in out52 and "told at once" not in out52 and "step came back" not in out52 and "is a front agent: not told; the board shows it" in out52 and hb_pushes(52, p52, DOC, "work-osprey-docs"), (pushes()[p52:], out52[-300:]))
# the board item (a) to (d), in sequence on one item: a builder leaves needs while another session stays, marks its own step status done (its last step), then the other session hands the item back
item(67, "projects/alpha", A, then=A, needs=[X, "work-osprey-docs"], next=f"{BK}: build", steps=[{"text": f"{BK}: build", "status": "open", "by": BK, "at": 1.0, "tag": {"text": "build", "state": "in progress", "ts": 1.0}}]); p67 = len(pushes()); n67 = len(routing.read("projects/alpha"))
out67a = hb(67, ["work-osprey-docs"]); settle()
check("(a) a builder takes itself out of needs while another session stays: nothing is pushed to the front agent owner and no hand-back is recorded",
      not hb_pushes(67, p67) and not hb_notes(67, n67) and "told at once" not in out67a and "back with them alone" not in out67a, (pushes()[p67:], out67a[-300:]))
out67b = server._update("a67", work={"state": "done"}, sender=BK); settle()
check("(b) the builder marks the status of its own last step done: nothing is pushed to the front agent owner, a background owner's item alike (for_you_scenario)",
      not hb_pushes(67, p67) and not hb_notes(67, n67) and "told at once" not in out67b, (pushes()[p67:], out67b[-300:]))
held.take(BK)
out67c = hb(67, [A], sender="work-osprey-docs"); settle(); d67 = hb_pushes(67, p67, X, BK); t67 = held.take(BK)
check("(c) the last other session leaves needs, the owner alone: the owner is told nothing and nothing is recorded for the router; the builder is passed the line once, for its next turn, in the reworded form, and there is no step line anywhere in the sequence",
      not hb_notes(67, n67) and not d67 and t67.count("a67 is back with work-osprey-main, a front agent, alone (handed back by work-osprey-docs)") == 1 and len(hb_pushes(67, p67)) == 0
      and not [x for x in pushes()[p67:] if "handed back its step" in x[1]] and "its builder work-osprey-x is passed a note that it is back with them alone, not them" in out67c, (hb_notes(67, n67), t67, pushes()[p67:], out67c[-300:]))
item(68, "projects/alpha", A, mover=A, needs=[X, "work-osprey-docs"]); p68 = len(pushes())
out68 = server.stackshot_complete("a68", outcome="done", reason="finished", description=NEWD, sender=BK); settle(); d68 = [x for x in hb_pushes(68, p68) if x[0] in (A, "work-osprey-main")]
check("(d) another session closes the item while a second session is still named: the owner's close line still reaches it, marked",
      len(d68) == 1 and d68[0][1].startswith("[for Oliver] [stackshot] a68 [home] item 68: closed by work-osprey-x: done (finished) \u2192 ") and "told at once that it was closed" in out68, (pushes()[p68:], out68[-300:]))
item(53, "projects/alpha", A, then=A, needs=[A, X]); p53 = len(pushes()); out53 = hb(53, [A]); settle(); d53 = hb_pushes(53, p53)
check("the owner named beside the builder, the builder taken out: that leaves the owner alone, and nobody is told, since the builder wrote it", not d53 and "nobody is told" in out53, (d53, out53[-200:]))
item(54, "projects/alpha", A, then=A, needs=[X]); p54 = len(pushes()); n54 = len(routing.read("projects/alpha")); out54 = hb(54, [A], sender="work-osprey-main"); settle()
check("the owner writes it itself: nothing is told, nothing recorded", not hb_pushes(54, p54) and not hb_notes(54, n54) and "back with them alone" not in out54, (pushes()[p54:], out54[-200:]))
item(55, "projects/alpha", S, then=S, needs=[X]); p55 = len(pushes()); n55 = len(routing.read("projects/alpha")); out55 = hb(55, [S]); settle(); d55 = [x for x in hb_pushes(55, p55, S, "work-osprey") if "now needs you" in x[1]]
check("a non-front owner (the keeper) named alone by the builder is told as before, 'now needs you', unmarked; no hand-back line",
      len(d55) == 1 and d55[0][1].startswith("[stackshot] a55 now needs you") and "back with you alone" not in d55[0][1] and not hb_notes(55, n55) and "back with them alone" not in out55, (d55, out55[-300:]))
item(56, "projects/alpha", A, then=A, needs=[X]); p56 = len(pushes()); n56 = len(routing.read("projects/alpha"))
server._cfg.CFG.setdefault("model", {})["one_mover"] = False      # this case writes decision beside the front agent on purpose (the hand-back notice is what is tested); the guard has its own suite
out56 = hb(56, ["decision", A], ask="Decide: a or b \u00b7 Recommend: yes \u00b7 Stakes: none \u00b7 By: no date"); settle(); server._cfg.CFG["model"]["one_mover"] = True
check("needs = decision beside the owner: Oliver's, not a hand-back; nothing is told to the owner",
      not hb_pushes(56, p56) and not hb_notes(56, n56) and "back with them alone" not in out56, (pushes()[p56:], out56[-300:]))
item(57, "projects/alpha", A, then=A, needs=[X]); p57 = len(pushes()); n57 = len(routing.read("projects/alpha"))
out57 = server.stackshot_complete("a57", outcome="done", reason="finished", description=NEWD, sender=BK); settle()
check("a close by the builder is no hand-back (the owner's own close line is another thing)", not hb_notes(57, n57) and "back with them alone" not in out57 and not [x for x in hb_pushes(57, p57) if "back with you alone" in x[1]], (hb_notes(57, n57), out57[-200:]))
item(58, "projects/alpha", A, "completed", then=A, needs=[X]); p58 = len(pushes()); n58 = len(routing.read("projects/alpha"))
out58 = server._update("a58", status="open", needs=[A], next=HB_NEXT, sender=BK, step="Review the PR and merge it"); settle()
check("a reopen by the builder that leaves the owner alone is no hand-back (the owner's keeper hears reopens, as before)", not hb_notes(58, n58) and "back with them alone" not in out58 and not hb_pushes(58, p58), (hb_notes(58, n58), pushes()[p58:], out58[-200:]))
item(59, "projects/alpha", A, then=A); p59 = len(pushes()); n59 = len(routing.read("projects/alpha")); out59 = hb(59); settle()
check("needs empty before: naming the owner alone is no hand-back, the older silence stays", not hb_notes(59, n59) and "back with them alone" not in out59 and not hb_pushes(59, p59) and "not told; the board shows it" in out59, (pushes()[p59:], out59[-200:]))
server._cfg.CFG.setdefault("board", {})["tell_owner"] = False
item(60, "projects/alpha", A, then=A, needs=[X]); p60 = len(pushes()); n60 = len(routing.read("projects/alpha")); out60 = hb(60); settle()
server._cfg.CFG["board"]["tell_owner"] = True
check("[board] tell_owner off: nothing is told, nothing recorded", not hb_notes(60, n60) and not hb_pushes(60, p60) and "back with them alone" not in out60, (pushes()[p60:], out60[-200:]))
held.take(BK)
item(61, "projects/alpha", "work-osprey-main", then="work-osprey-main", needs=[DC]); p61 = len(pushes()); out61 = hb(61, [A], sender=DC); settle(); t61 = held.take(BK)
item(62, "projects/alpha", A, then=A, needs=[DC]); p62 = len(pushes()); out62 = hb(62, ["work-osprey-main"], sender=DC); settle(); t62 = held.take(BK)
check("the owner stored as a name and needs by id, and the owner stored as an id and needs by name: each fires once, to the builder, as a line for its next turn",
      t61.count("a61 is back with") == 1 and t62.count("a62 is back with") == 1 and not hb_pushes(61, p61, X, BK) and not hb_pushes(62, p62, X, BK) and not hb_pushes(61, p61) and not hb_pushes(62, p62)
      and out61.count("not them") == 1 and out62.count("not them") == 1, (t61, t62, pushes()[p61:], out61[-200:], out62[-200:]))
item(63, "projects/eta", EM, then=EM, needs=[B]); p63 = len(pushes()); n63 = len(routing.read("projects/eta")); out63 = server._update("a63", needs=["home-eta-main"], next=HB_NEXT, sender="home-beta", step="Review the PR and merge it"); hb_tick()
d63 = [x for x in pushes()[p63:] if x[0] in (EM, "home-eta-main") and "a63" in x[1]]
check("a project with a front agent owner and no builder (projects/eta): the hand-back is told to nobody, the item stays with its mover, the routing log holds a line ruled `held` that says the project lists no builder, and the reply says so",
      a.pilot_root("projects/eta") == "projects/eta" and not d63 and "nobody is told" in out63 and "stays with them" in out63
      and [n for n in routing.read("projects/eta")[n63:] if n.get("ruling") == "held" and "no builder" in n.get("reason", "")] != [], (d63, pushes()[p63:], out63[-300:], routing.read("projects/eta")[n63:]))
cfg(live=True); hb_dropall()

# ---- 14. the audit's batch finding goes to each item's owner (one message per owner), not only to the -main agent
# projects/zeta: front agents work-zeta-main, work-zeta-news, work-zeta-site and a background agent work-zeta-lib. The batch is one message
# to the project from falcon-audit, one line per item. An item owned by -main, by another front agent, by a background agent, by a session
# that is no agent of the project, and a closed one: the lines are cut by owner, the unknown owner's and the closed item's go to -main as before.
ZM, ZP, ZT, ZL = "work-zeta-main", "work-zeta-news", "work-zeta-site", "work-zeta-lib"
item(40, "projects/zeta", ZM); item(41, "projects/zeta", ZP); item(42, "projects/zeta", ZP); item(43, "projects/zeta", ZL); item(44, "projects/zeta", "home-beta"); item(45, "projects/zeta", ZT)
item(46, "projects/zeta", ZP, "completed"); item(47, "projects/zeta", ZL)
cfg(live=True)
HEAD = "from: falcon-audit · board audit, Tue Jun 16th 13:25 +00 · 6 items. Re-read each against the page."
def batch(*body, to="projects/zeta", sender="falcon-audit"):
    n_before = len(routing.read(to)); server._message(to, "\n".join([HEAD, *body]), sender); settle()
    return [n for n in routing.read(to)[n_before:] if n.get("kind") == "message"]
L40 = "a40 · stale · external, confirmed Mon Jun 15th 17:10 (20 h) · confirm"
L41 = "a41 · stale · external, confirmed Mon Jun 15th 20:00 (17 h); the page's last entry is from Jun 15th · confirm, or record any new request"
L42 = "a42 · wrong-needs · needs: external, nothing outside waits · clear needs"
L43 = "a43 · stale · confirmed Sun Jun 14th · confirm"
L44 = "a44 · stale · confirmed Sun Jun 14th · confirm"
L45 = "a45 · ask-missing · the ask line is empty · add the ask"
L46 = "a46 · stale · closed since · none"
p14 = len(pushes()); calls14 = len(calls()); fake("good", "[]")
b14 = batch(L40, L41, L42, L43, L44, L45, L46)
check("14: the batch is held for the router (a live project), nothing pushed yet", len(b14) == 1 and b14[0].get("live") and len(pushes()) == p14, (b14, pushes()[p14:]))
t14 = live.tick(); got14 = pushes()[p14:]
got14 = [x for x in got14 if x[0].startswith("work-zeta")]      # earlier sections may leave held notices of other projects for this tick
by14 = {x[0]: x[1] for x in got14}
check("14: one message per owner (-main, news, site and the background agent: the board item, a finding is a task, never held) and no thin call for the batch",
      sorted(by14) == sorted([ZM, ZP, ZT, ZL]) and len(got14) == 4 and not any(b14[0]["id"] in c["stdin"] for c in calls()[calls14:]), ([x[0] for x in got14], t14))
lines_of = lambda text: [l for l in text.split("\n") if re.match(r"a\d+ · ", l)]
check("14: -main gets its own item, the item of the unknown owner and the closed one (a46), none of the others'",
      lines_of(by14[ZM]) == [L40, L44, L46], lines_of(by14[ZM]))
check("14: the second front agent gets both its items, the other front agent its own; the background agent its own, woken at once, nothing held for it",
      lines_of(by14[ZP]) == [L41, L42] and lines_of(by14[ZT]) == [L45] and lines_of(by14[ZL]) == [L43] and held.count(ZL) == 0, ([lines_of(by14[k]) for k in (ZP, ZT, ZL)], held.count(ZL)))
check("14: every message keeps the batch's opening line and the relay's closing paragraph, and names the notice",
      all(HEAD in t and "— Relayed by " in t and f"notice {b14[0]['id']}" in t for t in by14.values()), by14[ZP][:400])
check("14: a front agent's message carries the mark a front pane takes, the background agent's is unmarked and ends as a task (\"act on it within your mandate\")",
      all(by14[k].startswith("[for Oliver] ") for k in (ZM, ZP, ZT)) and not by14[ZL].startswith("[for Oliver]") and by14[ZL].rstrip().endswith("Act on it within your mandate."), [by14[k][:40] for k in by14])
r14 = rule_of(b14[0]["id"], "projects/zeta"); l14 = [x for x in lines() if x.get("id") == b14[0]["id"]][-1]
check("14: ruled passed once by the router, `to` (the \"passed to\" line) listing every owner including the background agent, by a rule in code (audit-owners); the live line records what each was sent, none held",
      r14["ruling"] == "passed" and r14["ruled_by"] == live.BY and sorted(x.strip() for x in r14["ruled_to"].split(",")) == sorted([ZM, ZP, ZT, ZL])
      and l14["rule"] == "audit-owners" and l14["source"] == "code" and l14["status"] == "ruled" and set(l14["sent"]) == {ZM, ZP, ZT, ZL}
      and not any(v.endswith(": held") for v in l14["sent"].values()), (r14, l14))
t14b = live.tick()
check("14: a second tick delivers nothing more", len([x for x in pushes()[p14:] if x[0].startswith("work-zeta")]) == 4 and t14b["ruled"] == 0, (len(pushes()[p14:]), t14b))

# every item owned by one agent: a plain pass to it, the whole batch, no split
p14 = len(pushes()); b14b = batch(L41, L42); live.tick(); g = pushes()[p14:]
check("14: items all owned by one front agent: one message to it with the whole batch (not to -main)", [x[0] for x in g] == [ZP] and lines_of(g[0][1]) == [L41, L42], g)
l = [x for x in lines() if x.get("id") == b14b[0]["id"]][-1]
check("14: …a pass without a split on its line", l["rule"] == "audit-owners" and not l.get("split") and l["target"] == ZP, l)
# items owned by -main only
p14 = len(pushes()); batch(L40); live.tick(); g = pushes()[p14:]
check("14: items all owned by -main: one message, to -main, as before", [x[0] for x in g] == [ZM] and lines_of(g[0][1]) == [L40], g)
# a line that is no finding goes to -main, with its own opening
p14 = len(pushes()); batch(L41, "page-lag · projects/zeta · Current state is behind its timeline · update the page"); live.tick(); g = {x[0]: x[1] for x in pushes()[p14:]}
check("14: a line that is no finding (a page note) goes to -main with the batch's opening line; the owner gets only its item",
      set(g) == {ZP, ZM} and "page-lag" in g[ZM] and not lines_of(g[ZM]) and "page-lag" not in g[ZP] and lines_of(g[ZP]) == [L41], g)
# a delivery that fails: only that agent is retried, the others are not told twice
FAIL.write_text(ZP)
p14 = len(pushes()); b14c = batch(L40, L41, L45); t = live.tick(); g = [x[0] for x in pushes()[p14:]]; l = [x for x in lines() if x.get("id") == b14c[0]["id"]][-1]
check("14: one owner not reachable: the others are told, the notice is not ruled yet, and the line records who was told",
      sorted(g) == sorted([ZM, ZT]) and l["status"] == "error" and set(l["sent"]) == {ZM, ZT} and not rule_of(b14c[0]["id"], "projects/zeta").get("ruling"), (g, l))
FAIL.unlink()
t = live.tick(); g2 = [x[0] for x in pushes()[p14:]]
check("14: at the retry only the owner left is told (nobody twice), then the notice is ruled", sorted(g2) == sorted([ZM, ZT, ZP]) and g2.count(ZM) == 1 and rule_of(b14c[0]["id"], "projects/zeta")["ruling"] == "passed", (g2, t))
# an owner that stays unreachable: after MAX_TRIES errors its lines go to -main as a separate message, nobody told is told again, ruled once
FAIL.write_text(ZP)
p14 = len(pushes()); b14e = batch(L40, L41, L45)
for _ in range(live.MAX_TRIES): live.tick()
g3 = [x[0] for x in pushes()[p14:]]
check("14: owner unreachable for three ticks: the others were told once and the notice is still unruled", sorted(g3) == sorted([ZM, ZT]) and not rule_of(b14e[0]["id"], "projects/zeta").get("ruling"), g3)
live.tick(); g4 = pushes()[p14:]; r4 = rule_of(b14e[0]["id"], "projects/zeta"); l4 = [x for x in lines() if x.get("id") == b14e[0]["id"]][-1]
to_main4 = [x for x in g4[len(g3):] if x[0] == ZM]
check("14: tick 4: the unreachable owner's lines go to -main as a separate message; nobody already told is sent again; ruled once, `to` without a repeat",
      len(g4) == len(g3) + 1 and len(to_main4) == 1 and lines_of(to_main4[0][1]) == [L41] and lines_of([x for x in g4 if x[0] == ZM][0][1]) == [L40]
      and r4["ruling"] == "passed" and [x.strip() for x in r4["ruled_to"].split(",")] == [ZM, ZT] and l4["status"] == "ruled", (g4[len(g3):], r4, l4))
FAIL.unlink()
# the sender's label with a uuid suffix is still the audit
p14 = len(pushes()); b14f = batch(L41, L45, sender="falcon-audit (99999999)"); live.tick(); g = {x[0] for x in pushes()[p14:] if x[0].startswith("work-zeta")}
l = [x for x in lines() if x.get("id") == b14f[0]["id"]][-1:]
check("14: the sender label with a uuid suffix is the audit too", b14f and b14f[0]["who"] != "falcon-audit" and g == {ZP, ZT} and l and l[0]["rule"] == "audit-owners", (b14f and b14f[0]["who"], g, l))
# a batch with a LONG opening, one front mover and one background mover (two items). (a) Each is woken with its own lines, whole, the opening and closing paragraph with them.
# (b) The ruling's "passed to" line lists every recipient, a held one (an earlier try's) named too.
L47 = "a47 · stale · expected Tue 09:30, no write since 08:15 · confirm or move the date"
LONG = HEAD + " Counts: 60 items read (45 active, 15 held); 24 findings: stale 8, stuck-elsewhere 6, next-done 2, idle-pass 1 new. Stuck (no write since the 03:00 run): a71, a12."
STASH_B = "\n".join([LONG, L41, L43, "  continued evidence of a43", L47, "— Relayed by stackshot"])
held.take(ZL); p14 = len(pushes()); b14g = batch(L41, L43, L47); n14g = b14g[0]["id"]
live.stash(n14g, STASH_B)
live.tick(); g = {x[0]: x[1] for x in pushes()[p14:] if x[0].startswith("work-zeta")}
check("14 (a): the front mover and the background mover are both messaged at once, each with its own findings: a41 for the front agent, a43 and a47 for the builder",
      set(g) == {ZP, ZL} and lines_of(g[ZP]) == [L41] and lines_of(g[ZL]) == [L43, L47]
      and not re.search(r"\ba41\b", g[ZL]) and not re.search(r"\ba43\b", g[ZP]), {k: lines_of(v) for k, v in g.items()})      # whole-word: a message names its notice by a random six-hex-digit id, which can hold an item's id as a substring
check("14 (a): the builder's lines are whole (a finding's continued line and the batch's opening and closing paragraph with them), a normal notice that asks it to act, unmarked, and nothing is held for it",
      "continued evidence of a43" in g[ZL] and "Counts: 60 items read" in g[ZL] and "— Relayed by stackshot" in g[ZL] and not g[ZL].startswith("[for Oliver]")
      and g[ZL].rstrip().endswith("Act on it within your mandate.") and "asked nothing" not in g[ZL] and held.count(ZL) == 0, (g[ZL], held.count(ZL)))
l_b = [x for x in lines() if x.get("id") == n14g][-1]; r_b = rule_of(n14g, "projects/zeta")
check("14 (b): ruled passed, `to` lists both recipients, the builder included, none held",
      r_b["ruling"] == "passed" and sorted(x.strip() for x in r_b["ruled_to"].split(",")) == sorted([ZP, ZL]) and "held" not in r_b["ruled_to"] and "held" not in r_b["reason"]
      and not any(v.endswith(": held") for v in l_b["sent"].values()), (l_b, r_b))
# a notice an earlier try (before) held for the builder: not delivered again, and the "passed to" line names it, "(held)", so it does not look dropped
b14h = batch(L41, L43, L47); n14h = b14h[0]["id"]; live.stash(n14h, STASH_B)
router._append(live.live_path(), {"id": n14h, "ts": time.time(), "project": "projects/zeta", "rule": "audit-owners", "status": "error", "error": "delivery to " + ZP + " failed: down",
                                   "split": {ZP: ["a41"], ZL: ["a43", "a47"]}, "sent": {ZL: ZL + ": held"}})
p14 = len(pushes()); held.take(ZL); live.tick(); g = {x[0]: x[1] for x in pushes()[p14:] if x[0].startswith("work-zeta")}
l_bh = [x for x in lines() if x.get("id") == n14h][-1]; r_bh = rule_of(n14h, "projects/zeta")
check("14 (b): an agent an earlier try held is not told again, the other is, and the ruling's `to` names the held one too",
      set(g) == {ZP} and r_bh["ruling"] == "passed" and [x.strip() for x in r_bh["ruled_to"].split(",")] == [ZP, ZL + " (held)"] and l_bh["status"] == "ruled", (g, r_bh, l_bh))
# not the audit's, or no stash: the call rules as before
p14 = len(pushes()); calls14 = len(calls()); fake("good", "[]")
b14d = batch(L40, L41, sender="home-beta"); live.tick()
check("14: the same text from another sender is not the audit's: the thin call takes it", len(calls()) == calls14 + 1, (len(calls()), calls14))
cfg()

# ---- 15. the keeper of a page that lists two builders is the first one the PAGE lists, not the first in alphabet (the registry kept the agent maps sorted)
# projects/example: the page listed falcon-engineer before falcon-aux-engineer (a second background agent whose
# mandate says builds), and the registry, written with sorted keys, put "aux" first: the server named the aux builder the project's keeper.
from stackshot.projects import pages as pg
OM = T / "omega-brain"; (OM / "projects").mkdir(parents=True)
(OM / "projects/alpha.md").write_text("---\ntype: project\ntitle: Alpha\ndisplay-name: ops-tide\nagents:\n  background:\n    ops-tide-audit: 'keep the board fresh: the daily audit'\n"
                                      "    ops-tide-engineer: builds the project, via subagents\n"
                                      "    ops-tide-aux-engineer: builds the second target, no decisions\n  ops-tide-main: Oliver's contact, builds to -engineer\n"
                                      "  ops-tide-aux: the second target\nstatus: active\n---\n\n# Alpha\n", encoding="utf-8")
real = (pg.BRAIN, pg.REG, a.REGISTRY); pg.BRAIN, pg.REG, a.REGISTRY = str(OM), str(T / "omega-registry.json"), T / "omega-registry.json"
try:
    pg.cmd_registry(quiet=True); omega = json.loads((T / "omega-registry.json").read_text())["pages"]["projects/alpha"]
    cfg(live=True)
    check("15: the registry keeps the page's order of its agents and background agents (not the alphabet's)",
          list(omega["back_agents"]) == ["ops-tide-audit", "ops-tide-engineer", "ops-tide-aux-engineer"]
          and list(omega["agents"]) == ["ops-tide-audit", "ops-tide-engineer", "ops-tide-aux-engineer", "ops-tide-main", "ops-tide-aux"], (list(omega["back_agents"]), list(omega["agents"])))
    check("15: …while every other key of the file is still sorted", list(omega) == sorted(omega), list(omega))
    check("15: the builder is the first background agent the page lists whose mandate says build, whatever the alphabet says",
          live.builder("projects/alpha") == "ops-tide-engineer" and live.stand_in("projects/alpha") == "ops-tide-engineer", (live.builder("projects/alpha"), live.stand_in("projects/alpha")))
    check("15: …so the project's keeper (anchors, item notices) is that builder", server._page_keeper("projects/alpha") == "ops-tide-engineer" and server._keeper("projects/alpha") == "ops-tide-engineer", (server._page_keeper("projects/alpha"), server._keeper("projects/alpha")))
    check("15: the other builder is still one of the page's own agents, and is no keeper", live.agent_root("projects/alpha", a.registry()) == "projects/alpha" and "ops-tide-aux-engineer" in a.registry()["projects/alpha"]["back_agents"], a.registry()["projects/alpha"].get("back_agents"))
    # the one-time backfill rewrites the file when it adds fields: it must not sort the agents again
    doc = json.loads((T / "omega-registry.json").read_text()); doc["pages"]["projects/alpha"].pop("agent_records", None); (T / "omega-registry.json").write_text(json.dumps(doc))
    from stackshot.projects import projects as prj
    real_rp = prj.registry_path; prj.registry_path = lambda: T / "omega-registry.json"
    try: stamped = prj.stamp_registry()
    finally: prj.registry_path = real_rp
    after = json.loads((T / "omega-registry.json").read_text())["pages"]["projects/alpha"]
    check("15: the registry backfill keeps the page's order too", stamped and list(after["back_agents"]) == ["ops-tide-audit", "ops-tide-engineer", "ops-tide-aux-engineer"] and "agent_records" in after, (stamped, list(after["back_agents"])))
finally:
    pg.BRAIN, pg.REG, a.REGISTRY = real
    cfg()

# ---- 16. a message whose first line is "For <agent>" reaches that agent, a front agent included (notices a1b2c6 and a1b2c7)
cfg(live=True); c15 = len(calls())
server._message("projects/alpha", "For work-osprey-main: you were renamed and your brief is now ~/briefs/alpha-main.md. No action needed.", "home-beta"); f15 = routing.read("projects/alpha")[-1]
server._message("projects/epsilon", "For work-gamma-main, from home-beta: the hand-over is ready.", "home-beta"); e15 = routing.read("projects/epsilon")[-1]
server._message("projects/alpha", "For work-osprey-nobody: this agent is not on the page.", "home-beta"); u15 = routing.read("projects/alpha")[-1]
fake("good", answer([(u15["id"], "merged", "", False)])); p15 = len(pushes()); live.tick(); settle(); g15 = pushes()[p15:]
pf = [x for x in g15 if f15["id"] in x[1]]; pe15 = [x for x in g15 if e15["id"] in x[1]]
check("16: 'For <front agent>' is delivered to that front agent with the mark, ruled by the router in code, no call made for it",
      [x[0] for x in pf] == ["work-osprey-main"] and pf[0][1].startswith(live._owner_mark()) and rule_of(f15["id"])["ruled_to"] == "work-osprey-main"
      and [x for x in lines() if x.get("id") == f15["id"]][-1]["rule"] == "for-agent" and not any(f15["id"] in c["stdin"] for c in calls()[c15:]), (pf, lines()[-3:]))
check("16: the reason line says it was addressed on its first line", rule_of(f15["id"])["reason"] == "addressed to work-osprey-main on its first line", rule_of(f15["id"]))
check("16: a component page (hub: projects/gamma) reads its hub's agents: 'For work-gamma-main' reaches it", [x[0] for x in pe15] == ["work-gamma-main"] and rule_of(e15["id"], "projects/epsilon")["ruled_to"] == "work-gamma-main", (pe15, rule_of(e15["id"], "projects/epsilon")))
check("16: a name the page does not list is not passed by the rule: the call takes it", any(u15["id"] in c["stdin"] for c in calls()[c15:]) and [x for x in lines() if x.get("id") == u15["id"]][-1]["rule"] != "for-agent", [x for x in lines() if x.get("id") == u15["id"]][-1:])
cfg()

# ---- 17. the interpreter this process runs on is gone (its uv environment deleted under it): a delivery still goes out
from stackshot.core import interp
DEAD = str(T / "gone-env/bin/python")          # a path that does not exist, as sys.executable after the clean-up
FAKE = str(T / "fakepush.py")
check("17: the interpreter exists: the argv is returned as it is, no lookup", interp.resilient([sys.executable, FAKE, "x"]) == [sys.executable, FAKE, "x"])
check("17: a bare command name is left alone", interp.resilient(["python3", FAKE]) == ["python3", FAKE])
real_uv, real_py = interp._uv, interp._python3
try:
    interp._uv = lambda: "/opt/uv/uv"
    fb16 = interp.resilient([DEAD, FAKE, "--from", "x", "t", "hi"])
    check("17: interpreter gone: uv run --quiet --no-project --script <script> <args>", fb16 == ["/opt/uv/uv", "run", "--quiet", "--no-project", "--script", FAKE, "--from", "x", "t", "hi"], fb16)
    check("17: the fallback argv has no --locked (push.py has no lock file: uv would warn on stderr, read as an error text)", "--locked" not in fb16, fb16)
    interp._uv = lambda: None; interp._python3 = lambda: "/usr/bin/python3"
    check("17: no uv: the system python3 runs the (standard-library) script", interp.resilient([DEAD, FAKE, "a"]) == ["/usr/bin/python3", FAKE, "a"])
    interp._python3 = lambda: None
    check("17: no uv and no python3: the argv comes back as it was, so the delivery fails into its own undelivered record", interp.resilient([DEAD, FAKE, "a"]) == [DEAD, FAKE, "a"])
finally:
    interp._uv, interp._python3 = real_uv, real_py
check("17: a script that is not there has no fallback", interp.fallback_argv([DEAD, str(T / "nope.py")]) is None)
check("17: uv is found on this box (the fallback below runs for real)", interp._uv() is not None, interp._uv())

real_exe = sys.executable
sys.executable = DEAD
try:
    st = interp.interpreter_status(); body = server._healthz_body()
finally:
    sys.executable = real_exe
check("17: the self-check says the interpreter is missing and what stands in for it", st["exists"] is False and st["path"] == DEAD and st["fallback"], st)
check("17: /healthz stays 'ok' on its first line and names the missing path on the second", body.splitlines()[0] == "ok" and DEAD in body.splitlines()[1], body)
check("17: /healthz is a bare 'ok' while the interpreter exists", server._healthz_body() == "ok" and interp.interpreter_status()["exists"] is True)

n0 = len(pushes())
check("17: deliver_via with a dead interpreter delivers through the fallback", live.deliver_via([DEAD, FAKE], "work-osprey", "no env, still delivered") == "delivered → work-osprey", None)
check("17: …and the fake push saw the line", pushes()[n0:] == [["work-osprey", "no env, still delivered"]], pushes()[n0:])
server._PUSH = [DEAD, FAKE]; cfg()
try:
    server._message("work-osprey-docs", "sent with the env gone", "home-beta"); settle()      # a session by name: a message to a project key is held for the router, nothing is spawned for it
finally:
    server._PUSH = [sys.executable, FAKE]
check("17: the server's own message relay delivers with a dead interpreter", any(x[0] == "work-osprey-docs" and "sent with the env gone" in x[1] for x in pushes()[n0 + 1:]), pushes()[n0 + 1:])
# anchor-hub's own delivery (core.Hub.deliver) runs on a deleted interpreter too
real_push = core.PUSH; core.PUSH = [DEAD, FAKE]; n1 = len(pushes())
try:
    hub16 = core.Hub(); hub16.deliver("anchor-16", "work-osprey", "hub notice, env gone")
finally:
    core.PUSH = real_push
check("17: anchor-hub's deliver goes out through the fallback and records the push's answer", pushes()[n1:] == [["work-osprey", "hub notice, env gone"]] and hub16.status["last_notice"]["result"] == "delivered → work-osprey", (pushes()[n1:], hub16.status.get("last_notice")))
# nothing to fall back to: the failure keeps its words, so the caller's undelivered record is written as before
interp._uv, interp._python3 = (lambda: None), (lambda: None)
try:
    out = live.deliver_via([DEAD, FAKE], "work-osprey", "lost?")
finally:
    interp._uv, interp._python3 = real_uv, real_py
check("17: no way to start the child: deliver_via answers failed, never a silent success", out.startswith("failed"), out)
real_run = subprocess.run(interp.resilient([DEAD, FAKE, "work-osprey", "stderr probe"]), capture_output=True, text=True)
check("17: the real fallback child runs with an empty stderr (no uv warning stored as a delivery error)", real_run.returncode == 0 and real_run.stderr == "" and real_run.stdout.strip() == "delivered → work-osprey", (real_run.returncode, real_run.stderr, real_run.stdout))

# ---- 18. the hand-off path (handoff.py): a notice the router passes to a session, which hands the item on; the clock takes it to the builder
(T / "cli").mkdir(exist_ok=True); server.CLI_SESSIONS = T / "cli"        # the CLI's own registry on this box: nothing in it, so no turn-end rule fires
cfg(live=True); fake("good", "[]")
item(40, "projects/alpha", A, next="work-osprey-docs: look at the quote")
r18 = server._message("projects/alpha", "the vendor's quote for a40 came in; someone should look at it", "home-beta")
m18 = routing.read("projects/alpha")[-1]
fake("good", answer([(m18["id"], "passed", "work-osprey-docs", False)])); p0 = len(pushes()); live.tick(); settle()
check("18 hand-off: the router passes the notice to the page's keeper (a background agent), delivered", rule_of(m18["id"])["ruling"] == "passed" and rule_of(m18["id"])["ruled_to"] == "work-osprey-docs"
      and any(x[0] == "work-osprey-docs" and m18["id"] in x[1] for x in pushes()[p0:]), (rule_of(m18["id"]), pushes()[p0:]))
ZONE_HOURS = 4                                    # the instance timezone pinned above (Asia/Dubai, UTC+4, no DST)
FUT18 = time.strftime("%Y-%m-%d", time.gmtime(time.time() + 5 * 86400 + ZONE_HOURS * 3600))
p0 = len(pushes()); server._update("a40", sender="work-osprey-docs", mover="home-beta", next="home-beta: answer the vendor about the quote", wake=FUT18); time.sleep(1.0); settle()
h18 = json.loads((T / "store/a/40.json").read_text())["metadata"].get("handoff") or {}
check("18 hand-off: that session hands the item on: a hand-off record to home-beta from it, told once and delivered", h18.get("to") == "home-beta" and h18.get("from") == "work-osprey-docs" and isinstance(h18.get("delivered_at"), float)
      and len([x for x in pushes()[p0:] if x[0] in ("home-beta", B) and "a40" in x[1]]) == 1, (h18, pushes()[p0:]))
p0 = len(pushes()); done18 = server._handoff_tick(now=h18["delivered_at"] + 11 * 60, only=["a40"]); time.sleep(1.0); settle()
m40 = json.loads((T / "store/a/40.json").read_text())["metadata"]; g18 = m40.get("handoff") or {}
check("18 hand-off: home-beta does not take it in 10 minutes: it goes to the project's builder, which the router also takes for its stand-in (work-osprey-x), not to the page's other background agent, not back to the sender",
      done18 == ["a40"] and g18.get("to") == "work-osprey-x" and g18.get("via") == "redirect" and g18.get("redirected_from") == "home-beta" and live.builder("projects/alpha") == "work-osprey-x" and live.stand_in("projects/alpha") == "work-osprey-x"
      and (m40.get("needs") or [""])[0] == "work-osprey-x" and "home-beta did not take it in 10 min" in g18.get("reason", ""), (done18, g18, m40))
check("18 hand-off: …the builder is told once (the sender, the page's keeper, one line)", len([x for x in pushes()[p0:] if x[0] in ("work-osprey-x", X) and "a40" in x[1]]) == 1
      and len([x for x in pushes()[p0:] if x[0] in ("work-osprey-docs", DOC) and "a40" in x[1]]) == 1, pushes()[p0:])

# ---- 19. the board item review: a notice for the item's own mover reaches the mover, though the mover is the project's notice-name session and the router holds the project
cfg(live=True); fake("good", "[]")
item(50, "projects/alpha", A, hold=True, wake="2020-01-01", hold_set={"by": "t", "at": 1.0}, mover=S)       # a hold whose wake has come; its mover is the -main notice session
item(51, "projects/alpha", A, mover=S, next="work-osprey: go on once a52 is in")
item(52, "projects/alpha", A, mover=A)
p0 = len(pushes()); server._wake_pass(); live.tick(); settle()
w19 = [n for n in routing.read("projects/alpha") if str(n.get("label") or "").startswith("wake") and "a50" in str(n.get("label"))]
check("19 a hold wakes on a live project whose mover is the notice-name session: the wake is ruled passed, not dropped, and the mover is told",
      bool(w19) and rule_of(w19[-1]["id"]).get("ruling") == "passed" and rule_of(w19[-1]["id"]).get("ruled_to") == "work-osprey"
      and any(x[0] == "work-osprey" and "a50" in x[1] and "woke" in x[1] for x in pushes()[p0:]), (w19[-1:], pushes()[p0:]))
p0 = len(pushes()); told19 = server._tell_close_mentions("a52", "done", "it is in", "work-osprey-x"); live.tick(); settle()
check("19 the close-mentions path: an open item that names the closed one, moved by the notice-name session, gets the notice through the router",
      S in told19 and any(x[0] == "work-osprey" and "a52" in x[1] and "a51" in x[1] for x in pushes()[p0:]), (told19, pushes()[p0:]))

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
