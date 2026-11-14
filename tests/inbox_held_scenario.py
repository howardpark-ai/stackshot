"""Scenario test for messages to a running session that sit in the server's inbox — fixture data, no live store, no network.

The rule: a line put by name must be matched by the session's id, not by its display name. A line put by name waits unseen when two running sessions carry the
name (fleet.by_name resolves two namesakes to nobody, and inbox._target refuses to pick one of two matching names) or when the pane's puller reports the CLI's
placeholder name instead of the server's kept one. Nothing flagged the waiting lines.

Covers: a poll hands a name-addressed line to the newest of two live namesakes; a poll matches by the server's kept name when the puller reports a placeholder;
two namesakes registered at the same time still strand the line (no guess); a line that waits for a running session is reported once after the minutes in
[client] inbox_flag_minutes, to its sender and the keeper, and not before, not for a session that is gone, not twice; the message tool's `inbox` reply says so.

    tests/run-suite inbox_held        → exit 0 / 1"""
import json, os, re, socket, subprocess, sys, pathlib, logging, threading, time
BID_A = 9155
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="inboxheld-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"), ("fleet_names", f"{tmp}/names.tsv"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("session_links", f"{tmp}/sala"), ("project_touch", f"{tmp}/touch"), ("timezone", "Asia/Dubai"), ("base_url", "https://stackshot.test")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r"(?m)^ui_open = (true|false)", "ui_open = false", toml); assert n == 1
toml, n = re.subn(r"(?m)^allowed_emails = .*$", 'allowed_emails = ["you@example.com"]', toml); assert n == 1
toml, n = re.subn(r'(?m)^mode = "google"', 'mode = "google"', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_GOOGLE_CLIENT_ID="test-client-id.apps.googleusercontent.com", STACKSHOT_GOOGLE_CLIENT_SECRET="test-secret")
for k in ("STACKSHOT_FLEET_DIR", "STACKSHOT_URL", "STACKSHOT_AUTH", "BOARD_MCP_AUTH"): os.environ.pop(k, None)
ME = socket.gethostname()
for d in ("store/a", "state/anchor-hub", "state/site", "secrets", "brain/projects"): (T / d).mkdir(parents=True)
(T / "names.tsv").write_text(f"# hostname\tfleet\tletter\n{ME}\ttestbox\ta\nWIN-BOX\tbox-far\tb\n")
U = lambda n: f"{n:08d}-0000-4000-8000-000000000000"
(T / "store/projects.json").write_text(json.dumps({"pages": {}}))
(T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")
(T / "state/site/index.html").write_text("<html>the board</html>")
(T / "state/site/favicon.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"/>')
sys.path.insert(0, STACK); logging.disable(logging.WARNING)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:500]}" if got is not None else ""))
rd = lambda p: json.loads(pathlib.Path(p).read_text())

from stackshot.core import config as cfg; from stackshot.fleet import clients as cl; from stackshot.fleet import fleet as fl; from stackshot.fleet import inbox
V = T / "state/clients/fleet"; T0 = 1790780400.0
OLD, NEW, MAIN, SENDER = U(1), U(2), U(3), U(4)
NAME = "site-builder"

# ================================================================= 1. an earlier case: two live namesakes, then the placeholder name
cl.checkin("box-far", [{"uuid": OLD, "name": NAME, "name_source": "user"}], {}, now=T0)                       # the old transcript, since long
cl.checkin("box-far", [{"uuid": OLD, "name": NAME, "name_source": "user"}, {"uuid": NEW, "name": NAME, "name_source": "user"},
                          {"uuid": SENDER, "name": "site-main", "name_source": "user"}], {}, now=T0 + 3 * 3600)   # the new one, registered 3 h later
rows = rd(V / "b/sessions.json")
reg = cl.load()["sessions"]
check("fixture: two running sessions carry the name, the new one registered later", rows[OLD]["name"] == rows[NEW]["name"] == NAME and "gone" not in rows[OLD] and "gone" not in rows[NEW]
      and reg[OLD]["registered"] < reg[NEW]["registered"], (rows, reg))
check("fixture: fleet.by_name resolves two running namesakes to nobody", NAME not in fl.by_name(fl.sessions()))
t_put = T0 + 3 * 3600 + 60
ids = [inbox.put(NAME, f"board#{BID_A} line {i}", "msg", now=t_put + i, sender="site-main (00000004…)") for i in range(3)]
line = json.load(open(T / "state/inbox/msg" / f"{ids[0]}.json"))
check("a line put by name while two namesakes run records no uuid (an earlier case)", line["uuid"] == "" and line["to"] == NAME, line)
live2 = {OLD: NAME, NEW: NAME}
check("take: two live namesakes and no registration times → nobody (no guess)", inbox.take(live2, only_src="msg") == [])
check("take: two namesakes registered at the same time → nobody", inbox.take(live2, only_src="msg", rank={OLD: 5.0, NEW: 5.0}) == [])
tk = inbox.take(live2, only_src="msg", rank={OLD: 1.0, NEW: 9.0})
check("take: …the newest registration holds the name: all three lines go to it, folded into one turn", len(tk) == 1 and tk[0]["session"] == NEW and tk[0]["ids"] == ids and tk[0]["text"].count(f"board#{BID_A} line") == 3, tk)
inbox.ack([], ids)                                      # the puller reports a failed delivery: offered again shortly
tk = inbox.take(live2, only_src="msg", rank={OLD: 1.0, NEW: 9.0}, now=time.time() + 30)
check("take: …a failed delivery is offered again to the same session", len(tk) == 1 and tk[0]["session"] == NEW, tk)
inbox.ack(ids)
check("fixture: the three lines are gone once confirmed", inbox.waiting() == {}, inbox.waiting())

from stackshot.fleet import client; from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route
from stackshot.service import fleet_events as fleetev
server._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
tok = open(client.mint("box-far")).read().strip()
from starlette.testclient import TestClient
app = server.mcp.http_app()
HB = {"Authorization": "Bearer " + tok}
with TestClient(app) as c:
    def poll(sessions):
        r = c.post("/client/poll", json={"sessions": sessions, "wait": 0}, headers=HB)
        return r.json().get("deliveries", []) if r.status_code == 200 else [r.status_code]
    def ack(d):
        c.post("/client/ack", json={"delivered": [i for x in d for i in x["ids"]]}, headers=HB)
    S = lambda u, n, **kw: {"uuid": u, "name": n, "name_source": "user", **kw}
    # ---- case 1: both namesakes live, the puller reports the same name for both
    i1 = inbox.put(NAME, f"the board#{BID_A} brief", "msg", sender="site-main (00000004…)")
    d = poll([S(OLD, NAME), S(NEW, NAME), S(SENDER, "site-main")])
    check("poll, two live namesakes: the line goes to the newer session (it would have waited before)", len(d) == 1 and d[0]["session"] == NEW and d[0]["ids"] == [i1], d)
    ack(d)
    # ---- case 2: the old transcript is gone and the pane's puller reports the CLI's placeholder name for the new one
    i2 = inbox.put(NAME, "a message put while the namesake was still live", "msg", sender="site-main (00000004…)")
    check("fixture: the line recorded no uuid (two namesakes were live when it was put)", json.load(open(T / "state/inbox/msg" / f"{i2}.json"))["uuid"] == "")
    cl.checkin("box-far", [S(NEW, NAME), S(SENDER, "site-main")], {}, now=T0 + 4 * 3600)          # the old one is reported gone
    check("fixture: the old transcript is marked gone", "gone" in rd(V / "b/sessions.json")[OLD])
    d = poll([S(NEW, "demo-3f", name_source="derived", user="home"), S(SENDER, "site-main")])
    row = rd(V / "b/sessions.json")[NEW]
    check("fixture: the server keeps the name on record against the placeholder", row["name"] == NAME, row)
    check("poll, the puller reports a placeholder name: the line is matched by the name the server kept and goes to the pane",
          len(d) == 1 and d[0]["session"] == NEW and d[0]["ids"] == [i2], d)
    ack(d)
    i3 = inbox.put(NAME, "a message put after the old one was gone", "msg", sender="site-main (00000004…)")
    check("a line put by name now records the new session's id", json.load(open(T / "state/inbox/msg" / f"{i3}.json"))["uuid"] == NEW)
    d = poll([S(NEW, "demo-3f", name_source="derived", user="home"), S(SENDER, "site-main")])
    check("…and is delivered", len(d) == 1 and d[0]["ids"] == [i3], d); ack(d)
    check("fixture: nothing waits", inbox.waiting() == {}, inbox.waiting())

    # ============================================================= 2. the flag: a line that waits for a running session
    # a session shows a sign of life for the flag while its machine's puller reports it (not marked gone) and checks in
    TN = T0 + 10 * 3600
    cl.checkin("box-far", [S(NEW, NAME), S(SENDER, "site-main"), S(MAIN, "ops-keeper")], {}, now=TN)
    iid = inbox.put(NAME, "waits for a running session", "msg", now=TN, sender="site-main (00000004…)")
    gone_id = inbox.put("ops-gone", "waits for nobody", "msg", now=TN, sender="site-main (00000004…)")
    check("overdue: a line younger than the minutes is not reported", inbox.new_overdue(300.0, now=TN + 299, idx=fl.sessions()) == [])
    late = inbox.new_overdue(300.0, now=TN + 301, idx=fl.sessions())
    check("overdue: past the minutes, for a session that shows a sign of life, it is (the line for a session no row holds is not)",
          [x["id"] for x in late] == [iid] and 300 <= late[0]["age"] < 310, late)
    check("overdue: …with the likeliest reason in words", "no puller has asked for it" in late[0]["why"], late[0]["why"])
    check("overdue: …once", inbox.new_overdue(300.0, now=TN + 400, idx=fl.sessions()) == [])
    cl.checkin("box-far", [S(SENDER, "site-main"), S(MAIN, "ops-keeper")], {}, now=TN + 405)         # the session went
    iid2 = inbox.put(NAME, "waits for a gone session", "msg", now=TN + 100, sender="site-main (00000004…)")
    check("overdue: a session its puller no longer reports shows no sign of life: nothing is reported", inbox.new_overdue(300.0, now=TN + 800, idx=fl.sessions()) == [])
    cl.checkin("box-far", [S(NEW, NAME), S(SENDER, "site-main"), S(MAIN, "ops-keeper")], {}, now=TN + 810)
    late = inbox.new_overdue(300.0, now=TN + 815, idx=fl.sessions())
    check("overdue: …until it is back, then the line is reported (the first one stays reported once)", [x["id"] for x in late] == [iid2], late)
    # a deliberate wait (sala's relaunch hold, a paused source) is not flagged; once the hold is gone and the line still waits, it is
    (T / "state/anchor-hub/held-msg.txt").write_text(f"{NAME}\n")
    iid3 = inbox.put(NAME, "held", "msg", now=TN, sender="x")
    check("overdue: a line held by an entry in held-msg.txt is a known wait: not flagged", inbox.new_overdue(300.0, now=TN + 830, idx=fl.sessions()) == [])
    check("deliberate: …and says why", "held-msg.txt" in inbox.deliberate(inbox.peek([iid3])[0]), inbox.deliberate(inbox.peek([iid3])[0]))
    os.remove(T / "state/anchor-hub/held-msg.txt")
    (T / "state/anchor-hub/paused-msg.json").write_text("{}")
    check("overdue: …nor a line of a paused source (a reboot's hold)", inbox.new_overdue(300.0, now=TN + 832, idx=fl.sessions()) == [])
    (T / "state/anchor-hub/release-msg.txt").write_text(f"{NAME}\n")
    late = inbox.new_overdue(300.0, now=TN + 834, idx=fl.sessions())
    check("overdue: …a pause that released this session's lines no longer excuses them", [x["id"] for x in late] == [iid3], late)
    os.remove(T / "state/anchor-hub/paused-msg.json"); os.remove(T / "state/anchor-hub/release-msg.txt")
    # the flag's own lines (sent from the instance's name) are never flagged in their turn
    iid_f = inbox.put(NAME, "a flag line to a stuck recipient", "msg", now=TN, sender=server.NAME)
    check("overdue: a line sent by the server itself (a flag) is not flagged again", inbox.new_overdue(300.0, now=TN + 840, idx=fl.sessions(), skip_from=(server.NAME,)) == [])
    check("overdue: …it would be without the guard", [x["id"] for x in inbox.new_overdue(300.0, now=TN + 841, idx=fl.sessions())] == [iid_f])
    inbox.ack([iid_f])
    # two live namesakes: the reason names both
    cl.checkin("box-far", [S(OLD, NAME), S(NEW, NAME), S(SENDER, "site-main"), S(MAIN, "ops-keeper")], {}, now=TN + 900)
    iid4 = inbox.put(NAME, "two namesakes", "msg", now=TN + 600, sender="x")
    late = inbox.new_overdue(300.0, now=TN + 905, idx=fl.sessions())
    check("overdue: …and so does a name that two running sessions carry", [x["id"] for x in late] == [iid4] and "2 running sessions carry the name" in late[0]["why"], late)
    inbox.ack([iid, iid2, iid3, iid4, gone_id])
    inbox.new_overdue(300.0, now=TN + 1000, idx=fl.sessions())
    check("overdue: the record of reported lines keeps only the lines still waiting", rd(T / "state/inbox/flagged.json") == {}, rd(T / "state/inbox/flagged.json"))

    # ---- the server's pass: who is told, when, and what
    sent = []
    fleetev.inbox_flag_send = lambda to, text: sent.append((to, text))
    fleetev.fleet_builder = lambda: "ops-keeper"
    cl.checkin("box-far", [S(NEW, NAME), S(SENDER, "site-main"), S(MAIN, "ops-keeper")], {}, now=TN + 2000)
    inbox.put(NAME, "the pass line one", "msg", now=TN + 1700, sender="site-main (00000004…)")
    inbox.put(NAME, "the pass line two", "msg", now=TN + 1705, sender="site-main (00000004…)")
    fleetev.INBOX_FLAG_LAST[0] = 0.0; fleetev.INBOX_FLAG_START[0] = 0.0
    check("flag pass: nothing is reported before the minutes", fleetev.inbox_flag_tick(now=TN + 1900) == [] and sent == [], sent)
    fleetev.INBOX_FLAG_LAST[0] = 0.0; fleetev.INBOX_FLAG_START[0] = TN + 1990
    check("flag pass: …nor in the first minute after the server's start (the pullers have not polled again yet), and the pass is not used up by it",
          fleetev.inbox_flag_tick(now=TN + 2010) == [] and sent == [] and fleetev.INBOX_FLAG_LAST[0] == 0.0, (sent, fleetev.INBOX_FLAG_LAST))
    fleetev.INBOX_FLAG_START[0] = TN + 1900
    told = fleetev.inbox_flag_tick(now=TN + 2010)
    check("flag pass: the sender and the keeper are told, once each", sorted(told) == ["ops-keeper", "site-main"] and sorted(t for t, _x in sent) == ["ops-keeper", "site-main"], (told, sent))
    txt = dict(sent)
    check("flag pass: the sender's line names the session, the time with the instance timezone's abbreviation and why", "to site-builder" in txt["site-main"] and " +04" in txt["site-main"] and "no puller has asked for it" in txt["site-main"]
          and "ops-keeper has been told" in txt["site-main"], txt["site-main"])
    check("flag pass: the keeper's line says how many lines wait, from whom, since when, and the usual causes", "2 line(s) for site-builder" in txt["ops-keeper"] and "site-main (00000004…)" in txt["ops-keeper"]
          and "held on purpose" in txt["ops-keeper"] and "nothing is lost" in txt["ops-keeper"], txt["ops-keeper"])
    sent.clear(); fleetev.INBOX_FLAG_LAST[0] = 0.0
    check("flag pass: a second pass tells nobody again", fleetev.inbox_flag_tick(now=TN + 2100) == [] and sent == [], sent)
    # a long list: the sender's flag names five lines and counts the rest
    for k in range(8):
        inbox.put(NAME, f"a long list {k}", "msg", now=TN + 2100 + k, sender="site-main (00000004…)")
    cl.checkin("box-far", [S(NEW, NAME), S(SENDER, "site-main"), S(MAIN, "ops-keeper")], {}, now=TN + 2500)
    fleetev.INBOX_FLAG_LAST[0] = 0.0
    told = fleetev.inbox_flag_tick(now=TN + 2500)
    txt = dict(sent)
    check("flag pass: eight waiting lines → the sender's flag counts 8, lists five and says '+3 more'", "8 of your message(s) are" in txt["site-main"] and txt["site-main"].count("to site-builder (") == 5
          and "+3 more" in txt["site-main"], txt["site-main"])
    check("flag pass: …and the keeper's line is one line for the session, not eight", txt["ops-keeper"].count("line(s) for site-builder") == 1 and "8 line(s) for site-builder" in txt["ops-keeper"], txt["ops-keeper"])
    sent.clear()
    inbox.put(NAME, "[stackshot] a flag line that the server itself sent to a stuck recipient", "msg", now=TN + 2110, sender=server.NAME)
    fleetev.INBOX_FLAG_LAST[0] = 0.0
    check("flag pass: …and a flag line the server sent (from its own name) waiting for a stuck recipient is not flagged in its turn", fleetev.inbox_flag_tick(now=TN + 9000) == [] and sent == [], sent)
    inbox.ack([i["id"] for i in inbox._items()])
    fleetev.INBOX_FLAG_LAST[0] = 0.0; server._cfg.CFG.setdefault("client", {})["inbox_flag_minutes"] = 0
    inbox.put(NAME, "while it is off", "msg", now=TN, sender="site-main (00000004…)")
    check("flag pass: [client] inbox_flag_minutes = 0 turns it off", fleetev.inbox_flag_tick(now=TN + 2200) == [] and sent == [])
    server._cfg.CFG["client"]["inbox_flag_minutes"] = 5

    # ============================================================= 3. what the message tool answers for a line that waits
    class _R:  # a push.py that answered "inbox": the session's machine has not fetched the line within the wait
        returncode = 0; stdout = f"inbox → {NAME}\n"; stderr = ""
    real_run = server.subprocess.run
    server.subprocess.run = lambda *a, **k: _R()
    try:
        out = server._message(NAME, "hello", "site-main")
    finally:
        server.subprocess.run = real_run
    check("message: an `inbox` reply no longer calls a running session away; it says when the sender is told", out.startswith(f"inbox → {NAME} — it waits in the server's inbox") and "is away" not in out
          and "after 5 minutes" in out and "the fleet's keeper is told why" in out and "running pane" in out and "stackshot tells you" not in out, out)
    server._cfg.CFG["client"]["inbox_flag_minutes"] = 0
    server.subprocess.run = lambda *a, **k: _R()
    try:
        out0 = server._message(NAME, "hello", "site-main")
    finally:
        server.subprocess.run = real_run
    server._cfg.CFG["client"]["inbox_flag_minutes"] = 5
    check("message: …with the flag off the reply promises none", out0.startswith("inbox → ") and "If the session is running" not in out0, out0)

import shutil; shutil.rmtree(tmp, ignore_errors=True)
print(("ok" if not fails else "FAILED") + f": inbox held scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush()
os._exit(1 if fails else 0)
