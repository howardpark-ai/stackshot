"""Scenario test for reading a notice's ruling (the get tool with a notice id, `client.py get notice <id>`) on fixture data -- no live store, no network, never the real `claude` (a fake script answers the router's thin call)
and never a real pane (push.py is a fake).

Covers: the reply of a message (and of a script's message) to a project ends by naming the call, `get(item_id="<id>") shows its ruling`; get on a notice
the router passed (sender, local time, project, a one-line excerpt of at most 120 characters, ruling and target, reason, rule, ruler, ruled time), one it
held, one it dropped, a repeat the rule in code dropped (it names the notice it repeats), one a code rule put onto an item (the `item:` line), one not
ruled yet (still held, when the router expects to rule it; late; the last try's error; stuck), one ruled by hand with the route tool, one logged and ruled
at once, one older than the log's 30-day read, and an unknown id; an item id still reads as an item; the client read (`get notice`); the lookup across
projects' files and the live log's hint.

    tests/run-suite notice        → exit 0 / 1"""
import json, os, re, sys, time, pathlib, logging, datetime as dt
BID_A = 9156
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="noticetest-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
toml = toml.replace('lanes_file = ""', f'lanes_file = "{tmp}/sala/lanes.tsv"', 1); assert f'lanes_file = "{tmp}/sala/lanes.tsv"' in toml
toml = toml.replace('limit_file = ""', f'limit_file = "{tmp}/sala/limit.json"', 1); assert f'limit_file = "{tmp}/sala/limit.json"' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"),
                 ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^owner = "the owner"', 'owner = "Oliver"', toml); assert n == 1
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet")
S, A, X, DOC, B = ("11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222", "44444444-4444-4444-8444-444444444444",
                   "77777777-7777-4777-8777-777777777777", "33333333-3333-4333-8333-333333333333")
for d in ("store/a", "fleet/a", "state/anchor-hub", "state/site", "secrets", "touch", "repo", "sala", "brain/projects"): (T / d).mkdir(parents=True)
(T / "state/site/favicon.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"/>')
(T / "fleet/a/sessions.json").write_text(json.dumps({S: {"name": "work-osprey", "machine": "a", "url": "", "seen": "x"}, A: {"name": "work-osprey-main", "machine": "a", "url": "", "seen": "x"},
                                                      X: {"name": "work-osprey-x", "machine": "a", "url": "", "seen": "x"}, DOC: {"name": "work-osprey-docs", "machine": "a", "url": "", "seen": "x"},
                                                      B: {"name": "home-beta", "machine": "a", "url": "", "seen": "x"}}))
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
page = lambda name, sess, **kw: {"title": name, "name": name, "org": "home", "tags": [], "type": "project", "session": sess, "status": "active", "board": [], "board_row": False, "updated": 1, "mirror": f"https://example.invalid/{name}", **kw}
(T / "store/projects.json").write_text(json.dumps({"pages": {
    "projects/alpha": page("Alpha", "work-osprey", agents={"work-osprey-main": "Oliver's point of contact", "work-osprey-docs": "keeps the pages and the documents", "work-osprey-x": "builds, merges and releases the code"},
                           back_agents={"work-osprey-x": "builds, merges and releases the code", "work-osprey-docs": "keeps the pages and the documents"}),
    "projects/gamma": page("Gamma", "work-gamma", agents={"work-gamma-main": "the contact"}),
    "projects/example-general": page("General", "home-commons", agents={"home-commons-main": "Oliver's general contact"})}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n# Alpha\n\n## Current state\n\nALPHA-STATE-MARK.\n\n<!-- timeline -->\n- 2026-10-01 | old\n")
(T / "store/a/2.json").write_text(json.dumps({"id": "2", "subject": "[home] item 2", "description": "A thing. It lives here. Done when done.", "status": "open", "metadata": {"owner": X, "project": "projects/alpha"}}))
(T / "store/next-id").write_text("10")
push_log = T / "push.log"
(T / "fakepush.py").write_text(f"import sys, json\na = sys.argv[1:]\nif a[:1] == ['--from']: a = a[2:]\nopen({str(push_log)!r}, 'a').write(json.dumps(a) + '\\n')\nprint('delivered → ' + a[0])\n")
CTL, CALLS = T / "fake-control.json", T / "fake-calls.jsonl"
(T / "fake_claude.py").write_text(f'''import sys, os, json
ctl = json.load(open({str(CTL)!r}))
stdin = sys.stdin.read()
with open({str(CALLS)!r}, "a") as f: f.write(json.dumps({{"stdin": stdin}}) + "\\n")
print(json.dumps({{"type": "result", "subtype": "success", "is_error": False, "duration_api_ms": 700, "num_turns": 1, "result": ctl.get("text", ""), "total_cost_usd": 0.01, "usage": {{"input_tokens": 100, "output_tokens": 10}}}}))
''')
def fake(text=""): CTL.write_text(json.dumps({"mode": "good", "text": text}))
def settle(): time.sleep(0.6)

sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))

from stackshot.core import config as _cfg; from stackshot.router import routing; from stackshot.router import router; from stackshot.router import router_live as live
from stackshot.web import server
from stackshot.web.tools import anchors as _wt_anchors
from stackshot.web.tools import route as _wt_route
from stackshot.web.tools import get as _wt_get
from stackshot.service import telling
from stackshot.fleet import client
from fastmcp.exceptions import ToolError
server._publish = _wt_anchors._publish = _wt_route._publish = lambda: None; telling.PUSH = [sys.executable, str(T / "fakepush.py")]
CMD = [sys.executable, str(T / "fake_claude.py")]
_cfg.CFG["router"] = {"command": CMD, "timeout_seconds": 20}
def answer(rows): return json.dumps([{"id": i, "ruling": r, "target": t, "reason": reason, "for_owner": False} for i, r, t, reason in rows])
def nid_of(reply): return re.search(r"notice ([0-9a-f]{6}) ", reply).group(1)
def get(i): return _wt_get.stackshot_get(i)
def err(i):
    try: get(i)
    except ToolError as e: return str(e)
    return ""
def field(txt, label): return next((l.split(": ", 1)[1] for l in txt.split("\n") if l.startswith(label + ": ")), None)
ZONE = dt.timezone(dt.timedelta(hours=4))   # the pinned instance timezone, Asia/Dubai: UTC+4, no DST

# ---- 1. the reply of a send names the call
LONG = "please look at the quote from the vendor " + "and the terms they attached, which differ from last year's in three places; " * 4 + "thanks"
r1 = server._message("projects/alpha", LONG, "home-beta"); id_pass = nid_of(r1)
check("1: a message to a project is held for the router and its reply ends by naming the call: get(item_id=\"<id>\") shows its ruling",
      r1.startswith(f"held for the router — the router rules notice {id_pass} within about ") and r1.endswith(f'get(item_id="{id_pass}") shows its ruling') and "a reply, if any" in r1 and "client.py" not in r1, r1)
r1b = server._message("projects/alpha", "the nightly backup finished: 10 files copied, 2 skipped on Mon Jan 5th, the run took 40 s and wrote 80 MB to the archive disk, all good", "nightly-backup", origin="box-far")
id_base = nid_of(r1b)
check("1: a script's message to a project ends with the same call, and names the client's read before it",
      r1b.endswith(f'get(item_id="{id_base}") shows its ruling') and f"client.py get notice {id_base}" in r1b, r1b)
r1c = server._message("projects/alpha", "the vendor's reply is short: yes to the new terms, call on Friday", "home-beta"); id_held = nid_of(r1c)
r1d = server._message("projects/alpha", "ack", "home-beta"); id_drop = nid_of(r1d)

# ---- 2. not ruled yet: still held, when the router expects to rule it
t_wait = get(id_pass)
n_pass = routing.lookup(id_pass)[1]
check("2: a notice the router has not ruled yet says it is still held, who sent it, the project and when the router expects to rule it",
      field(t_wait, "ruling") == "none yet, still held for the router" and field(t_wait, "sender") == "home-beta" and field(t_wait, "project") == "projects/alpha"
      and (field(t_wait, "expected") or "").startswith("by ") and f"every {int(live.tick_s())} s" in field(t_wait, "expected") and "late" not in field(t_wait, "expected")
      and field(t_wait, "ruled") is None and field(t_wait, "reason") is None, t_wait)
check("2: …the sent time is the notice's own, in the instance timezone, in the server's time style (Wed Jun 17th 14:23)",
      re.fullmatch(r"[A-Z][a-z]{2} [A-Z][a-z]{2} \d{1,2}(st|nd|rd|th) \d\d:\d\d", field(t_wait, "sent") or "")
      and field(t_wait, "sent") == server._rmod.when_words(dt.datetime.fromtimestamp(n_pass["ts"], ZONE)), t_wait)
check("2: …and its text is one line of at most 120 characters, cut with an ellipsis", len(field(t_wait, "text")) <= 120 and field(t_wait, "text").endswith("…") and field(t_wait, "text").startswith("please look at the quote"), field(t_wait, "text"))

# ---- 3. the tick: passed (the call), held, dropped, merged; each one's ruling shows
fake(answer([(id_pass, "passed", "work-osprey-x", "the builder reads vendor quotes"), (id_base, "merged", "", "a backup report, nobody needs to act"),
             (id_held, "held", "", "wait for the page pass"), (id_drop, "dropped", "", "an acknowledgement")]))
res = live.tick(); settle()
t_pass, t_held, t_drop, t_mer = get(id_pass), get(id_held), get(id_drop), get(id_base)
check("3: passed: the ruling names who it went to, the reason, the call that ruled it, who ruled it and when; no item",
      field(t_pass, "ruling") == "passed to work-osprey-x" and field(t_pass, "reason") == "the builder reads vendor quotes" and field(t_pass, "rule") == "the router's call"
      and field(t_pass, "ruled by") == "stackshot (router)" and re.fullmatch(r"[A-Z][a-z]{2} [A-Z][a-z]{2} \d{1,2}(st|nd|rd|th) \d\d:\d\d", field(t_pass, "ruled") or "")
      and field(t_pass, "item") == "none" and field(t_pass, "expected") is None and t_pass.startswith(f"notice {id_pass}: message to projects/alpha"), (t_pass, res))
check("3: held: the ruling says it is kept for the digest and tells nobody at once, with the router's reason",
      (field(t_held, "ruling") or "").startswith("held (kept for the daily digest") and field(t_held, "reason") == "wait for the page pass" and field(t_held, "ruled by") == "stackshot (router)", t_held)
check("3: dropped: the ruling and the reason", (field(t_drop, "ruling") or "").startswith("dropped") and field(t_drop, "reason") == "an acknowledgement" and field(t_drop, "text") == "ack", t_drop)
check("3: merged: the ruling says merged into a digest", (field(t_mer, "ruling") or "").startswith("merged into a digest") and field(t_mer, "sender") == "nightly-backup (a script on box-far)", t_mer)
check("3: a notice that is ruled no longer says it is waiting", all(field(t, "expected") is None for t in (t_pass, t_held, t_drop, t_mer)))

# ---- 4. a repeat the rule in code drops names the notice it repeats
r4 = server._message("projects/alpha", "the nightly backup finished: 10 files copied, 4 skipped on Tue Jan 6th, the run took 50 s and wrote 90 MB to the archive disk, all good", "nightly-backup", origin="box-far")
id_rep = nid_of(r4); fake("[]"); live.tick(); settle()
t_rep = get(id_rep)
check("4: a repeat dropped by the rule in code: ruling dropped, the reason and a line naming the notice it repeats, the rule and that code ruled it",
      (field(t_rep, "ruling") or "").startswith("dropped") and field(t_rep, "repeat of") == f"notice {id_base}" and f"repeat of {id_base}" in field(t_rep, "reason")
      and field(t_rep, "rule") == "repeat (code)" and field(t_rep, "ruled by") == "stackshot (router)", t_rep)

# ---- 5. a rule in code that puts a message onto an item: the item line
r5 = server._message("projects/alpha", "a2 needs a look: the vendor replied and the date moved", "home-beta"); id_item = nid_of(r5); fake("[]"); live.tick(); settle()
t_item = get(id_item)
check("5: a notice a rule in code put onto an item names it", field(t_item, "rule") == "message-item (code)" and field(t_item, "item") == "a2" and (field(t_item, "ruling") or "").startswith("passed to "), t_item)

# ---- 6. an unknown id, an item id, a bare item-shaped notice id
e6 = err("deadbe")
check("6: an unknown notice id answers `no notice <id>` and says what an id looks like", e6.startswith("no notice deadbe in the routing log") and "board#<n>" in e6, e6)
check("6: …the same with the word notice before it, and for an id with capitals", err("notice deadbe").startswith("no notice deadbe") and err("DEADBE").startswith("no notice deadbe"))
e6b = err("a12345")
check("6: an id that could be an item's and is no item's says so for both", e6b.startswith("no notice a12345 in the routing log") and "no item a12345" in e6b, e6b)
check("6: an item id still reads as an item (`a2`), and a bad id still gets the item id error", "[home] item 2" in get("a2") and "bad item id" in err("zz-9"), (get("a2")[:200], err("zz-9")))
check("6: the word notice before a known id reads the notice, and a bare id of a notice reads it too", get(f"notice {id_drop}") == t_drop and get(f"  {id_drop.upper()} ") == t_drop)

# ---- 7. the pending states: late, the last try's error, stuck, a pilot notice nobody holds, a count-only line
n_late = routing.record("projects/alpha", kind="message", to="", label="message to projects/alpha", who="home-beta", text="late one", target="project-wide", pilot=True, live=True, ts=time.time() - 3600)
t_late = get(n_late)
check("7: a held notice past the router's tick and a judgment call is late, and says a failed judgment is tried again", "it is late" in (field(t_late, "expected") or ""), t_late)
live._log({"id": n_late, "ts": time.time(), "project": "projects/alpha", "key": "projects/alpha", "status": "error", "error": "the call failed: exit 3"})
check("7: …and the last try's error shows", field(get(n_late), "last try") == "the call failed: exit 3", get(n_late))
live._log({"id": n_late, "ts": time.time(), "project": "projects/alpha", "key": "projects/alpha", "status": "error", "error": "failed: " + "x" * 500})
check("7: …a long error is cut at 200 characters", len(field(get(n_late), "last try")) == 200, len(field(get(n_late), "last try")))
live._log({"id": n_late, "ts": time.time(), "project": "projects/alpha", "key": "projects/alpha", "status": "stuck", "reason": "could not be ruled: " + "y" * 500})
t_stuck = get(n_late)
check("7: …and so is a stuck notice's reason", len(field(t_stuck, "reason")) == 200, len(field(t_stuck, "reason")))
check("7: …and a notice the router gave up on says it is stuck and why", field(t_stuck, "ruling") == "none, stuck" and "could not be ruled" in field(t_stuck, "reason"), t_stuck)
n_pilot = routing.record("projects/alpha", kind="board", to="work-osprey-docs", label="board", who="home-beta", text="delivered to an agent", target="x", pilot=True)
n_count = routing.record("projects/alpha", kind="anchor", to="work-osprey-x", label="Slack", who="Dana", text="a direct anchor", pilot=False)
check("7: a pilot notice delivered and unruled waits for a ruling; a count-only line owes none", "waiting for a ruling" in field(get(n_pilot), "ruling") and "recorded as a count only" in field(get(n_count), "ruling"), (get(n_pilot), get(n_count)))

# ---- 8. a ruling by hand, an automatic one, a time in the instance timezone, a notice older than the log's read
n_hand = routing.record("projects/alpha", kind="message", to="", label="message to projects/alpha", who="home-beta", text="overruled", target="project-wide", pilot=True, live=True)
routing.rule(n_hand, "dropped", reason="router said passed, wrong", by="falcon-engineer")
t_hand = get(n_hand)
check("8: a ruling by hand names who made it and that the rule is the route tool's, not the router's rule or call", field(t_hand, "ruled by") == "falcon-engineer" and field(t_hand, "rule") == "overruled by hand with the route tool" and field(t_hand, "item") is None, t_hand)
n_auto = routing.record_auto("projects/gamma", "merged", "a green release, logged at once", kind="anchor", label="PR event", who="release.sh", text="merged", pilot=True)
t_auto = get(n_auto)
check("8: a notice logged and ruled at once (log-only) says so, in another project's file", field(t_auto, "project") == "projects/gamma" and field(t_auto, "ruled by") == "stackshot (auto)" and "ruled at once" in field(t_auto, "rule"), t_auto)
EPOCH = dt.datetime(2026, 9, 17, 2, 40, tzinfo=ZONE).timestamp()          # Thu Sep 17th 02:40 +04 = Wed Sep 16th 22:40 UTC (the local day differs from the UTC day)
n_zone = routing.record("projects/gamma", kind="message", to="", label="m", who="home-beta", text="zone check", pilot=True, live=True, ts=EPOCH)
check("8: the time is in the instance timezone, whatever the box's clock: 22:40 UTC the day before reads Thu Sep 17th 02:40", field(get(n_zone), "sent") == "Thu Sep 17th 02:40", get(n_zone))
OLD = time.time() - 40 * 86400
n_old = routing.record("projects/gamma", kind="message", to="", label="m", who="home-beta", text="forty days ago", pilot=True, live=True, ts=OLD)
with open(routing._file("projects/gamma"), "a", encoding="utf-8") as f:
    f.write(json.dumps({"id": n_old, "ruling": "passed", "to": "work-gamma-main", "reason": "old", "by": "stackshot (router)", "ts": OLD + 60}) + "\n")
check("8: a notice older than the log's 30-day read is still found (route's find keeps its window)", routing.find(n_old) is None and field(get(n_old), "ruling") == "passed to work-gamma-main", get(n_old))

# ---- 9. the lookup: one project's file by the live log's hint, the others by a substring prefilter; read and rule behave as before
hit = routing.lookup(id_pass, "projects/gamma")
check("9: lookup finds a notice with a wrong hint (the hint is only tried first) and returns the folded notice", hit is not None and hit[0] == "projects/alpha" and hit[1]["ruling"] == "passed" and hit[1]["ruled_to"] == "work-osprey-x", hit)
check("9: lookup gives None for an id that is not six hex characters, or that no file holds", routing.lookup("zzzzzz") is None and routing.lookup("12") is None and routing.lookup("deadbe") is None and routing.lookup("") is None)
tr = live.trace(id_pass)
check("9: the live log's trace of a ruled notice carries the router's rule line and the project's key", (tr["ruled"] or {}).get("key") == "projects/alpha" and tr["ruled"].get("source") == "call" and live.trace("deadbe") == {"ruled": None, "last": None, "stuck": None}, tr)
check("9: read still folds rulings: the passed notice carries its ruling, and route can overrule it", routing.read("projects/alpha") and next(n for n in routing.read("projects/alpha") if n["id"] == id_pass)["ruled_by"] == "stackshot (router)"
      and routing.rule(id_pass, "held", reason="by hand", by="x")[1]["ruling"] == "held" and field(get(id_pass), "ruling").startswith("held (kept"), get(id_pass))

# ---- 10. the client's read
check("10: client.py knows the read", "notice" in client.READS)
st, ctype, body = server._client_get("notice", {"key": id_drop})
check("10: get notice <id> answers the lines get shows (200)", st == 200 and body == t_drop, (st, body))
st, _c, body = server._client_get("notice", {"key": "deadbe"})
check("10: an unknown notice id is a 404 with the no-notice line", st == 404 and body.startswith("no notice deadbe"), (st, body))
st, _c, body = server._client_get("notice", {"key": ""})
check("10: no id is a 400 that says what an id is", st == 400 and "six hex characters" in body, (st, body))
st, _c, body = server._client_get("notice", {"key": f"board#{BID_A}"})
check("10: an item id is a 400, not a notice", st == 400, (st, body))

# ---- 11. the tool text says it
tools = {t.name: t for t in __import__("asyncio").run(server.mcp.list_tools())}
g, m = tools["get"], tools["message"]
check("11: get's description and its parameter say it takes a notice id", "notice id" in g.description and "no notice <id>" in g.description and "notice id" in g.parameters["properties"]["item_id"].get("description", ""), g.parameters)
check("11: message's description names the reply line", 'get(item_id="<id>") shows its ruling' in m.description, m.description[-900:])

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
