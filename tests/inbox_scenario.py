"""Scenario test for messages to a running session that sit in the server's inbox — fixture data, no live store, no network, no server process (the server
module is imported and called in-process on a temporary config; the sala registry is a fixture file in a temporary directory, never the host's). Two parts in
one process, the second on a clean store: the lines that wait for a running session and the flag that reports them, then the permanent session id.

Part 1, the lines that wait. The rule: a line put by name must be matched by the session's id, not by its display name. A line put by name waits unseen when two running
sessions carry the name (fleet.by_name resolves two namesakes to nobody, and inbox._target refuses to pick one of two matching names) or when the pane's puller reports the CLI's
placeholder name instead of the server's kept one. Nothing flagged the waiting lines.

Covers: a poll hands a name-addressed line to the newest of two live namesakes; a poll matches by the server's kept name when the puller reports a placeholder;
two namesakes registered at the same time still strand the line (no guess); a line that waits for a running session is reported once after the minutes in
[client] inbox_flag_minutes, to its sender and the keeper, and not before, not for a session that is gone, not twice; the message tool's `inbox` reply says so.

Part 2, the permanent id (code finds a session by its permanent id, names are for people): an inbox line is for a permanent session id, resolved when it is put and matched
at the poll. The rule it enforces: a line put by name must be matched by the session's id, not by its display name (a name can be carried by two running sessions, or
replaced by the CLI's placeholder name); the earlier name match is replaced by a match on the id.

Covers: put resolves a name, an alias, a transcript id or the permanent id to the permanent id of a LIVE registry session and stores it (`pid`) with the session's
current name for display; a name the registry does not know, a retired session's name, a name two live sessions carry and a registry that is missing store none;
take offers a line to the live transcript that carries its permanent id: two live namesakes (the stale one belongs to another session, or is an older transcript of
the same one), a relaunch whose puller reports a placeholder name, a rename, a relaunch with a new transcript id (listed by the registry, or not yet listed and
carrying the server-kept name), a transcript that cannot be tied to the id (waits, and the flag says why); the name fallback for a line with no permanent id (an
unknown name, a line stored before this change, a registry that went away); a hold that lists the id; the poll through the client API; push.py and the message
tool keep the permanent id; the flag keys on the permanent id (a renamed session is still found, the reason is in words, the keeper's line shows the current name).

    tests/run-suite inbox        → exit 0 / 1"""
import json, os, re, socket, subprocess, sys, pathlib, logging, threading, time, contextlib, io, shutil
BID_A = 9155
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="inbox-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"), ("fleet_names", f"{tmp}/names.tsv"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("session_links", f"{tmp}/sala"), ("project_touch", f"{tmp}/touch"), ("timezone", "Asia/Dubai"), ("base_url", "https://stackshot.test")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r"(?m)^ui_open = (true|false)", "ui_open = false", toml); assert n == 1
toml, n = re.subn(r"(?m)^allowed_emails = .*$", 'allowed_emails = ["you@example.com"]', toml); assert n == 1
toml, n = re.subn(r'(?m)^mode = "google"', 'mode = "google"', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_GOOGLE_CLIENT_ID="test-client-id.apps.googleusercontent.com", STACKSHOT_GOOGLE_CLIENT_SECRET="test-secret",
                  PUSH_INBOX_WAIT="0.05", ANCHOR_PUSH_SOURCE="msg")
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

# ================================================================= PART 1: the lines that wait for a running session, and the flag
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
from stackshot.service import messaging as _messaging
from stackshot.core import instance as _core_instance
from stackshot.web import publish as _web_publish
from stackshot.service import fleet_events as fleetev
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
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
    iid_f = inbox.put(NAME, "a flag line to a stuck recipient", "msg", now=TN, sender=_core_instance.NAME)
    check("overdue: a line sent by the server itself (a flag) is not flagged again", inbox.new_overdue(300.0, now=TN + 840, idx=fl.sessions(), skip_from=(_core_instance.NAME,)) == [])
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

    # ---- the two hold files: another tool's held-msg.txt and a reboot's resume's held-resume-msg.txt are read as one list (the union)
    HM, HR = inbox.FLAGS / "held-msg.txt", inbox.FLAGS / "held-resume-msg.txt"
    live_n = {NEW: NAME}
    def holds(main=None, resume=None):
        for f, v in ((HM, main), (HR, resume)):
            if v is None: f.unlink(missing_ok=True)
            else: f.write_text(v, encoding="utf-8")
    def drain(): inbox.ack([i["id"] for i in inbox._items("msg")])
    def probe(tag, main, resume, held, where):
        holds(main, resume); drain()
        pid_ = inbox.put(NAME, f"two files {tag}", "msg", now=TN + 3000, sender="x")
        got = inbox.take(live_n, only_src="msg", now=TN + 3001)
        why_ = inbox.deliberate(inbox.peek([pid_])[0])
        flagged = inbox.new_overdue(300.0, now=TN + 3700, idx=fl.sessions())
        check(f"two hold files, {tag}: take " + ("holds the line" if held else "hands the line out"), (got == []) == held and (held or (len(got) == 1 and got[0]["ids"] == [pid_])), got)
        check(f"two hold files, {tag}: the line still waits in the inbox until it is delivered", inbox.waiting("msg") == {NAME: 1}, inbox.waiting("msg"))
        check(f"two hold files, {tag}: the reason names " + (" and ".join(where) if where else "no hold"),
              (all(w in why_ for w in where) and all(x not in why_ for x in {"held-msg.txt", "held-resume-msg.txt"} - set(where))) if held else "has not been lifted" not in why_, why_)
        check(f"two hold files, {tag}: a held line is a known wait (not flagged), a free one is", ([x["id"] for x in flagged] == []) == held, flagged)
        drain()
    probe("a key only in the resume's file", None, NAME + "\n", True, ["held-resume-msg.txt"])
    probe("a key only in the other tool's file", NAME + "\n", None, True, ["held-msg.txt"])
    probe("a key in both files", NAME + "\n", NAME + "\n", True, ["held-msg.txt", "held-resume-msg.txt"])
    probe("the key in the resume's file, another key in the other tool's", "somebody-else\n", NAME + "\n", True, ["held-resume-msg.txt"])
    probe("the key in the other tool's file, another key in the resume's", NAME + "\n", "somebody-else\n", True, ["held-msg.txt"])
    probe("the key in neither file (both list others)", "somebody-else\n", "somebody-more\n", False, [])
    probe("the resume's file missing, the other tool's empty", "", None, False, [])
    probe("the resume's file empty, the other tool's missing", None, "\n\n", False, [])
    probe("neither file exists", None, None, False, [])
    probe("the resume's file empty, the key in the other tool's", NAME + "\n", "", True, ["held-msg.txt"])
    # a hold in the resume's file lifts when the file is replaced: the line goes out at once
    holds(None, NAME + "\n"); drain()
    lift = inbox.put(NAME, "two files, lifted", "msg", now=TN + 3000, sender="x")
    held_now = inbox.take(live_n, only_src="msg", now=TN + 3001); holds(None, "")
    out_now = inbox.take(live_n, only_src="msg", now=TN + 3002)
    check("two hold files: the resume's hold, once its file is replaced, no longer holds the line", held_now == [] and [i for r in out_now for i in r["ids"]] == [lift], (held_now, out_now))
    drain(); holds(None, None)
    # each source reads its own pair of files
    (inbox.FLAGS / "held-resume-hub.txt").write_text(NAME + "\n")
    check("two hold files: a hub hold holds no msg line, and is read for hub", inbox.blocked("msg")[2] == set() and inbox.blocked("hub")[2] == {NAME}, (inbox.blocked("msg"), inbox.blocked("hub")))
    (inbox.FLAGS / "held-resume-hub.txt").unlink()

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
    inbox.put(NAME, "[stackshot] a flag line that the server itself sent to a stuck recipient", "msg", now=TN + 2110, sender=_core_instance.NAME)
    fleetev.INBOX_FLAG_LAST[0] = 0.0
    check("flag pass: …and a flag line the server sent (from its own name) waiting for a stuck recipient is not flagged in its turn", fleetev.inbox_flag_tick(now=TN + 9000) == [] and sent == [], sent)
    inbox.ack([i["id"] for i in inbox._items()])
    fleetev.INBOX_FLAG_LAST[0] = 0.0; cfg.CFG.setdefault("client", {})["inbox_flag_minutes"] = 0
    inbox.put(NAME, "while it is off", "msg", now=TN, sender="site-main (00000004…)")
    check("flag pass: [client] inbox_flag_minutes = 0 turns it off", fleetev.inbox_flag_tick(now=TN + 2200) == [] and sent == [])
    cfg.CFG["client"]["inbox_flag_minutes"] = 5

    # ============================================================= 3. what the message tool answers for a line that waits
    class _R:  # a push.py that answered "inbox": the session's machine has not fetched the line within the wait
        returncode = 0; stdout = f"inbox → {NAME}\n"; stderr = ""
    real_run = subprocess.run
    subprocess.run = lambda *a, **k: _R()
    try:
        out = _messaging._message(NAME, "hello", "site-main")
    finally:
        subprocess.run = real_run
    check("message: an `inbox` reply no longer calls a running session away; it says when the sender is told", out.startswith(f"inbox → {NAME} — it waits in the server's inbox") and "is away" not in out
          and "after 5 minutes" in out and "the fleet's keeper is told why" in out and "running pane" in out and "stackshot tells you" not in out, out)
    cfg.CFG["client"]["inbox_flag_minutes"] = 0
    subprocess.run = lambda *a, **k: _R()
    try:
        out0 = _messaging._message(NAME, "hello", "site-main")
    finally:
        subprocess.run = real_run
    cfg.CFG["client"]["inbox_flag_minutes"] = 5
    check("message: …with the flag off the reply promises none", out0.startswith("inbox → ") and "If the session is running" not in out0, out0)

# ================================================================= between the parts: a clean store (the first part's lines, clients and flags are not the second's)
for _d in ("state/inbox", "state/clients", "state/anchor-hub"): shutil.rmtree(T / _d, ignore_errors=True)
(T / "state/anchor-hub").mkdir(parents=True); (T / "sala/a").mkdir(parents=True)

# ================================================================= PART 2: an inbox line is for a permanent session id
from stackshot.fleet import push
from stackshot.fleet import sessions_registry as sr
P = lambda n: f"00000000-0000-4000-9000-{n:012d}"            # permanent ids (U, above, makes the transcript ids)
# ----------------------------------------------------------------------------- the fixture registry
OLD, NEW, NEW2, NEW3, STALE, MAIN, SENDER, LONE = U(1), U(2), U(3), U(4), U(5), U(6), U(7), U(8)
ENG, OTHER, KEEPER, GONE, TWIN_A, TWIN_B = P(1), P(2), P(3), P(4), P(5), P(6)
NAME = "site-builder"
SALA = T / "sala/a/session-registry.json"
def row(pid, name, transcripts, state="live", aliases=()):
    return {"id": pid, "name": name, "aliases": list(aliases), "project": None, "project_key": None, "role": None, "lane": "max", "model": "opus", "effort": "medium", "pane": name,
            "cwd": "/home/user", "state": state, "created": "2026-10-21T21:00:00Z", "retired_at": None if state == "live" else "2026-10-22T01:00:00Z",
            "transcripts": [{"id": t, "machine": "a", "at": f"2026-10-21T2{i}:00:00Z", "why": "fresh"} for i, t in enumerate(transcripts, 1)]}
N = [0]
def put_registry(rows):
    tmp_ = SALA.with_name(".r.tmp"); tmp_.write_text(json.dumps({"schema": 1, "machine": "a", "written": "2026-10-22T07:00:00Z", "sessions": {r["id"]: r for r in rows}}), encoding="utf-8")
    os.replace(tmp_, SALA); N[0] += 1
    st = os.stat(SALA); os.utime(SALA, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000 * N[0])); sr.reset()
ENG_ROW = lambda transcripts=(OLD, NEW), name=NAME, aliases=(): row(ENG, name, list(transcripts), aliases=aliases)
BASE = lambda: [row(OTHER, "ops-other", [STALE]), row(KEEPER, "ops-keeper", [MAIN]), row(GONE, "ops-gone", [LONE], state="retired"),
                row(TWIN_A, "ops-twin", [U(20)]), row(TWIN_B, "ops-twin", [U(21)])]
put_registry([ENG_ROW(), *BASE()])

def items(): return {i["id"]: i for i in inbox._items("msg")}
def clear(): inbox.ack(list(items()))
def poll_to(live, rank=None, now=None):
    d = inbox.take(live, only_src="msg", rank=rank, now=now)
    return d

# ================================================================= 1. put: the permanent id is resolved when the line is put
def put(to, text="x", **kw):
    iid = inbox.put(to, text, "msg", sender="site-main", **kw); return items()[iid]
l = put(NAME)
check("put by name: the permanent id is stored, the name is kept for display", l["pid"] == ENG and l["name"] == NAME and l["to"] == NAME, l)
l = put(ENG)
check("put by permanent id: the id is stored; `to` is the address (the name now), not the id", l["pid"] == ENG and l["to"] == NAME and l["name"] == NAME, l)
l = put(OLD)
check("put by transcript id (an old one the session has since left): the permanent id is stored", l["pid"] == ENG and l["to"] == OLD, l)
put_registry([ENG_ROW(name="ops-builder", aliases=[NAME]), *BASE()])
l = put(NAME)
check("put by an old name (an alias): the permanent id is stored, the display name is the current one", l["pid"] == ENG and l["name"] == "ops-builder", l)
put_registry([ENG_ROW(), *BASE()]); clear()
l = put("ops-unknown")
check("put by a name the registry does not know: no permanent id (the name fallback holds it)", l["pid"] == "" and l["to"] == "ops-unknown", l)
l = put("ops-gone")
check("put by a retired session's name: no permanent id (it may be a pane's new name the registry has not listed)", l["pid"] == "", l)
l = put("ops-twin")
check("put by a name two live sessions carry: no permanent id (the registry never picks)", l["pid"] == "", l)
l = put("cse_" + "A" * 24)
check("put to a cloud session: no permanent id", l["pid"] == "", l)
clear()

# ================================================================= 2. take: the line goes to the live transcript that carries the id
# 2a. the board item phase 1: two live namesakes. (i) the stale one is another session's transcript
put(NAME, "to the right one")
live = {STALE: NAME, NEW: NAME}
tk = poll_to(live, rank={STALE: 9.0, NEW: 1.0})
check("two live namesakes, the stale one is another session's transcript: the line goes to the one that carries the id, though the stale one registered later",
      len(tk) == 1 and tk[0]["session"] == NEW, tk)
clear()
# (ii) both transcripts belong to the session: the newest registration, else the one the registry lists last
put(NAME, "to the newer")
live = {OLD: NAME, NEW: NAME}
tk = poll_to(live, rank={OLD: 1.0, NEW: 9.0})
check("two live transcripts of one session: the newest registration carries it", len(tk) == 1 and tk[0]["session"] == NEW, tk); clear()
put(NAME, "to the listed-last")
tk = poll_to(live, rank={OLD: 5.0, NEW: 5.0})
check("…registered at the same time: the transcript the registry lists last", len(tk) == 1 and tk[0]["session"] == NEW, tk); clear()
put(NAME, "no rank at all")
tk = poll_to(live)
check("…with no registration times: the transcript the registry lists last", len(tk) == 1 and tk[0]["session"] == NEW, tk); clear()
put_registry([ENG_ROW(transcripts=()), *BASE()])
put(NAME, "two unlisted carriers")
tk = poll_to({OLD: NAME, NEW: NAME}, rank={OLD: 5.0, NEW: 5.0})
check("…two transcripts the registry does not list, registered together: nobody (no guess)", tk == [], tk)
tk = poll_to({OLD: NAME, NEW: NAME}, rank={OLD: 1.0, NEW: 5.0})
check("…but the newer registration still settles it", len(tk) == 1 and tk[0]["session"] == NEW, tk); clear()
put_registry([ENG_ROW(), *BASE()])

# 2b. the board item phase 2: the puller reports the CLI's placeholder name for a relaunched pane
put(NAME, "after the placeholder")
tk = poll_to({NEW: "demo-3f"})
check("the poll names the session by the CLI's placeholder: the line goes by the id of the transcript the registry lists", len(tk) == 1 and tk[0]["session"] == NEW and tk[0]["name"] == "demo-3f", tk)
clear()

# 2c. a rename
put(NAME, "put before the rename")
put_registry([ENG_ROW(name="ops-builder", aliases=[NAME]), *BASE()])
tk = poll_to({NEW: "ops-builder"})
check("a rename between the put and the poll: the line still goes to the session", len(tk) == 1 and tk[0]["session"] == NEW, tk); clear()
put(ENG, "put by the id after the rename")
tk = poll_to({NEW: "whatever-the-puller-says"})
check("…and a line put by the id goes to it whatever name the poll carries", len(tk) == 1 and tk[0]["session"] == NEW, tk); clear()
put_registry([ENG_ROW(), *BASE()])

# 2d. a relaunch with a new transcript id
put(NAME, "put before the relaunch")
put_registry([ENG_ROW(transcripts=(OLD, NEW, NEW2)), *BASE()])
tk = poll_to({NEW2: "background-9z"})
check("a relaunch with a new transcript id the registry lists: the line goes to it (the old transcript is gone)", len(tk) == 1 and tk[0]["session"] == NEW2, tk); clear()
put(NAME, "a relaunch the registry has not recorded yet")
tk = poll_to({NEW3: NAME})
check("…not yet listed, and the server kept the session's name for it: the name resolves to the id and the line goes to it", len(tk) == 1 and tk[0]["session"] == NEW3, tk); clear()
put(NAME, "a relaunch nothing ties to the id")
tk = poll_to({NEW3: "background-9z"})
check("…not yet listed and reported by its placeholder: nothing ties it to the id, the line waits (the flag says so below)", tk == [], tk)
put_registry([ENG_ROW(transcripts=(OLD, NEW, NEW3)), *BASE()])
tk = poll_to({NEW3: "background-9z"})
check("…and goes as soon as the registry lists the transcript", len(tk) == 1 and tk[0]["session"] == NEW3, tk); clear()
put_registry([ENG_ROW(), *BASE()])

# 2e. a line is never offered to another session
put(NAME, "only for eng")
tk = poll_to({STALE: NAME, MAIN: "ops-keeper", NEW2: "background-9z"})
check("a line is not offered to a session of another permanent id, nor to one nothing ties to its id", tk == [], tk); clear()

# 2f. several lines, one turn; failure offers again
a = put(NAME, "one")["id"]; b = put(ENG, "two")["id"]; c = put(NEW, "three")["id"]
tk = poll_to({NEW: "demo-3f"})
check("lines put by name, by permanent id and by transcript id fold into one turn for the session", len(tk) == 1 and sorted(tk[0]["ids"]) == sorted([a, b, c]), tk)
inbox.ack([], [a, b, c])
tk = poll_to({NEW: "demo-3f"}, now=time.time() + 30)
check("…a failed delivery is offered again to the same session", len(tk) == 1 and sorted(tk[0]["ids"]) == sorted([a, b, c]), tk); clear()

# ================================================================= 3. the name fallback: a line with no permanent id
put("ops-unknown", "to a name the registry does not know")
tk = poll_to({U(30): "ops-unknown"})
check("fallback: a line for a name the registry does not know goes by the name", len(tk) == 1 and tk[0]["session"] == U(30), tk); clear()
iid = "0000000000001-aaaaaa"
(T / "state/inbox/msg").mkdir(parents=True, exist_ok=True)
(T / "state/inbox/msg" / f"{iid}.json").write_text(json.dumps({"id": iid, "ts": time.time(), "src": "msg", "to": NAME, "uuid": "", "name": NAME, "text": "stored before the change", "from": "x"}))
tk = poll_to({U(31): NAME})
check("fallback: a line stored before this change (no `pid` at all) goes by its name", len(tk) == 1 and tk[0]["session"] == U(31) and tk[0]["ids"] == [iid], tk); clear()
(T / "state/inbox/msg" / f"{iid}.json").write_text(json.dumps({"id": iid, "ts": time.time(), "src": "msg", "to": OLD, "uuid": OLD, "name": NAME, "text": "stored before, by id", "from": "x"}))
tk = poll_to({OLD: NAME})
check("fallback: …and by the transcript id it was addressed to", len(tk) == 1 and tk[0]["session"] == OLD, tk); clear()
put(NAME, "the registry goes away")
SALA.rename(SALA.with_name("session-registry.json.off")); sr.reset()
tk = poll_to({U(32): NAME})
check("fallback: a registry that is gone while the line waits → the line is matched by its name again", len(tk) == 1 and tk[0]["session"] == U(32), tk); clear()
SALA.with_name("session-registry.json.off").rename(SALA); sr.reset()
put_registry([ENG_ROW(), *BASE()])
# the registry of the session's own machine is missing or stale, while another machine's registry reads (available() is true): the line is matched by its name
(T / "sala/b").mkdir(exist_ok=True)
SALA_B = T / "sala/b/session-registry.json"
SALA_B.write_text(json.dumps({"schema": 1, "machine": "b", "written": "2026-10-22T07:00:00Z", "sessions": {r["id"]: r for r in [row(P(40), "home-elsewhere", [U(40)])]}}), encoding="utf-8")
put(NAME, "its machine's registry file is missing")
SALA.rename(SALA.with_name("session-registry.json.off")); sr.reset()
check("fixture: another machine's registry still reads, the session's row is not in it", sr.available() and sr.row(ENG) is None)
tk = poll_to({U(33): NAME})
check("fallback: only the other machine's rows are present → the line is matched by its name, not stranded", len(tk) == 1 and tk[0]["session"] == U(33), tk); clear()
SALA.with_name("session-registry.json.off").rename(SALA); os.remove(SALA_B); sr.reset()
# the session was retired and a pane was spawned again under its name after the line was put
before = put(NAME, "put before the respawn")
check("fixture: the line was put with the session's permanent id", before["pid"] == ENG, before)
ENG2, NEWPANE = P(7), U(34)
put_registry([row(ENG, NAME, [OLD, NEW], state="retired"), row(ENG2, NAME, [NEWPANE]), *BASE()])
idx_ = {NEWPANE: {"name": NAME, "machine": "b"}}
w = inbox.why(before, idx_)
check("why: a line whose id is retired gives the name reasons (not the permanent id's)", "permanent id" not in w and "no puller has asked for it" in w, w)
tk = poll_to({NEWPANE: NAME})
check("fallback: the line's session was retired and a new pane carries its name → the line finds the new pane", len(tk) == 1 and tk[0]["session"] == NEWPANE, tk)
clear()
put_registry([ENG_ROW(), *BASE()])

# a hold that lists the session by its permanent id holds a line that carries it
put(NAME, "held by the id")
(T / "state/anchor-hub/held-msg.txt").write_text(ENG + "\n")
check("a hold that lists the permanent id holds the line", poll_to({NEW: NAME}) == [])
(T / "state/anchor-hub/held-msg.txt").write_text("ops-keeper\n")
check("…a hold on another session does not", len(poll_to({NEW: NAME})) == 1)
os.remove(T / "state/anchor-hub/held-msg.txt"); clear()

# ================================================================= 4. the client API's poll, and push.py / the message tool
tok = open(client.mint("box-far")).read().strip()
app = server.mcp.http_app()
HB = {"Authorization": "Bearer " + tok}
S = lambda u, n, **kw: {"uuid": u, "name": n, "name_source": "user", **kw}
T0 = 1790780400.0
with TestClient(app) as c:
    def poll(sessions):
        r = c.post("/client/poll", json={"sessions": sessions, "wait": 0}, headers=HB)
        return r.json().get("deliveries", []) if r.status_code == 200 else [r.status_code]
    def ackall(d): c.post("/client/ack", json={"delivered": [i for x in d for i in x["ids"]]}, headers=HB)
    cl.checkin("box-far", [S(OLD, NAME), S(NEW, NAME), S(SENDER, "site-main"), S(MAIN, "ops-keeper")], {}, now=T0)
    cl.checkin("box-far", [S(OLD, NAME), S(NEW, NAME), S(SENDER, "site-main"), S(MAIN, "ops-keeper")], {}, now=T0 + 3 * 3600)
    # push.py: a permanent id as the target
    with contextlib.redirect_stdout(io.StringIO()) as out:
        rc = push.deliver(ENG, "pushed to the permanent id", "site-main")
    pl = [i for i in items().values() if i["text"] == "pushed to the permanent id"]
    check("push.py to a permanent id: the line waits in the inbox with the permanent id and the address", rc in (0, 1) and len(pl) == 1 and pl[0]["pid"] == ENG and pl[0]["to"] == NAME, (rc, pl))
    with contextlib.redirect_stdout(io.StringIO()):
        push.deliver(NAME, "pushed to the name", "site-main")
    pl2 = [i for i in items().values() if i["text"] == "pushed to the name"]
    check("push.py to a name: the permanent id is found from the name", len(pl2) == 1 and pl2[0]["pid"] == ENG, pl2)
    # the message tool hands push.py the target as written
    seen = []
    class _R:
        returncode = 0; stdout = "inbox → x\n"; stderr = ""
    real_run = subprocess.run
    subprocess.run = lambda argv, *a, **k: (seen.append(argv), _R())[1]
    try:
        _messaging._message(ENG, "hello", "site-main")
    finally:
        subprocess.run = real_run
    check("the message tool passes the permanent id on to push.py (the inbox resolves it once, from what the sender wrote)", seen and seen[-1][seen[-1].index("--from") + 2] == ENG, seen[-1:] )
    # the poll: placeholder name for the pane, the old transcript still reported too
    d = poll([S(OLD, NAME), S(NEW, "demo-3f", name_source="derived", user="home"), S(SENDER, "site-main")])
    got = sorted(i for x in d for i in x["ids"])
    check("poll: both pushed lines go to the newer transcript of the session, one turn", len(d) == 1 and d[0]["session"] == NEW and got == sorted(i["id"] for i in pl + pl2), d)
    ackall(d)
    check("fixture: nothing waits", inbox.waiting() == {}, inbox.waiting())
    # a line put by name; a stale pane of another session reports the same name and registered later
    cl.checkin("box-far", [S(OLD, NAME), S(NEW, NAME), S(STALE, NAME), S(SENDER, "site-main"), S(MAIN, "ops-keeper")], {}, now=T0 + 4 * 3600)
    put(NAME, "with a stale namesake that registered last")
    d = poll([S(OLD, NAME), S(NEW, NAME), S(STALE, NAME), S(SENDER, "site-main")])
    check("poll: a stale pane of another session reports the same name and registered last: the line goes to the session it is for", len(d) == 1 and d[0]["session"] == NEW, d)
    ackall(d)

    # ============================================================= 5. the flag keys on the permanent id
    cl.checkin("box-far", [S(NEW, NAME), S(SENDER, "site-main"), S(MAIN, "ops-keeper")], {}, now=T0 + 10 * 3600)
    TN = time.time()
    iid = inbox.put(NAME, "waits for a running session", "msg", now=TN, sender="site-main (00000004…)")
    put_registry([ENG_ROW(name="ops-builder", aliases=[NAME]), *BASE()])                                    # renamed in the registry
    cl.checkin("box-far", [S(NEW, "ops-builder"), S(SENDER, "site-main"), S(MAIN, "ops-keeper")], {}, now=T0 + 10 * 3600 + 5)    # …and the heartbeat has the new name
    late = inbox.new_overdue(300.0, now=TN + 301, idx=fl.sessions())
    check("flag: a line put by a name the session no longer goes by is still found waiting for its (running) session, by the permanent id",
          [x["id"] for x in late] == [iid] and late[0]["pid"] == ENG, late)
    check("flag: …shown under the session's name now, with the reason in words", late[0]["name"] == "ops-builder" and "no puller has asked for it" in late[0]["why"], late[0])
    check("flag: …once", inbox.new_overdue(300.0, now=TN + 400, idx=fl.sessions()) == [])
    inbox.ack([iid])
    # two live carriers of one id
    cl.checkin("box-far", [S(OLD, "ops-builder"), S(NEW, "ops-builder"), S(SENDER, "site-main"), S(MAIN, "ops-keeper")], {}, now=T0 + 10 * 3600 + 10)
    iid2 = inbox.put(ENG, "two carriers", "msg", now=TN, sender="site-main (00000004…)")
    late = inbox.new_overdue(300.0, now=TN + 310, idx=fl.sessions())
    check("flag: two running transcripts of one permanent id → the reason says so", [x["id"] for x in late] == [iid2] and "2 running sessions carry the permanent id" in late[0]["why"], late)
    inbox.ack([iid2])
    # a relaunch the registry has not recorded, reported under a placeholder: alive by its name, the reason names the registry
    put_registry([ENG_ROW(name="ops-builder", aliases=[NAME]), *BASE()])
    cl.checkin("box-far", [S(NEW3, "ops-builder"), S(SENDER, "site-main"), S(MAIN, "ops-keeper")], {}, now=T0 + 10 * 3600 + 20)
    iid3 = inbox.put(ENG, "unlisted transcript", "msg", now=TN, sender="site-main (00000004…)")
    late = inbox.new_overdue(300.0, now=TN + 320, idx=fl.sessions())
    check("flag: …a running session under the session's name that the registry does not tie to its id (unlisted, but it carries the name): it is the carrier, so the plain reason",
          [x["id"] for x in late] == [iid3], late)
    inbox.ack([iid3])
    # the server's pass: names the session by its current name, groups by it
    cl.checkin("box-far", [S(NEW, "ops-builder"), S(SENDER, "site-main"), S(MAIN, "ops-keeper")], {}, now=T0 + 10 * 3600 + 30)
    sent = []
    fleetev.inbox_flag_send = lambda to, text: sent.append((to, text))
    fleetev.fleet_builder = lambda: "ops-keeper"
    inbox.put(NAME, "pass line one", "msg", now=TN + 1700, sender="site-main (00000004…)")
    inbox.put(ENG, "pass line two", "msg", now=TN + 1705, sender="site-main (00000004…)")
    fleetev.INBOX_FLAG_LAST[0] = 0.0; fleetev.INBOX_FLAG_START[0] = 0.0
    told = fleetev.inbox_flag_tick(now=TN + 2010)
    txt = dict(sent)
    check("flag pass: the sender and the keeper are told once, and both name the session as it is called now",
          sorted(told) == ["ops-keeper", "site-main"] and "to ops-builder" in txt["site-main"] and "2 line(s) for ops-builder" in txt["ops-keeper"], (told, txt))
    inbox.ack(list(items()))
    # the message tool's own text is unchanged
    cfg.CFG.setdefault("client", {})["inbox_flag_minutes"] = 5

# the pull of everything above: nothing is left in the inbox
check("nothing waits at the end", inbox.waiting() == {}, inbox.waiting())
shutil.rmtree(tmp, ignore_errors=True)
print(("ok" if not fails else "FAILED") + f": inbox scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush()
os._exit(1 if fails else 0)