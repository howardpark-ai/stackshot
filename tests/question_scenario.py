"""Scenario test for the client verbs a script files a question with and reads its answer by (`client.py post question`,
`client.py get answer <id>`, POST /client/question and GET /client/answer) — fixture data, no live store, no network, no
server process (the server module is imported and called in-process, on a temporary config).

Covers: a question filed over the client API and through client.py (the item id printed alone on stdout, exit 0; the item open,
needs = decision, with its ask and options, owned by the project's -main agent, filed under the project's page, the text as its
description cut to the line limit, the given subject (required, no default prefix), the sender recorded as the creator); the project taken by
id, key and bare slug, and a sub-page through its hub; a project whose page lists no front agent refused (and one with a front
agent that is not -main owned by it); the create tool's own checks applying to a script (a bad ask, bad options, a subject with
no prefix or none, an ask of several decisions, an unknown or ambiguous project, a sender naming Oliver), refused with the tool's own text and
no item filed; the owner's own page debt not refusing a script's filing; client.py's misuse (usage, exit 1, nothing filed) and its
failures (no token, a server that does not answer: stderr, exit 1); a request id making a repeat safe (the same id and sender twice: one item, the same id printed; another sender or id: another item); no default subject prefix; and `get answer`: empty before he answers, his latest answer
after (the chosen option's label and text in one stable line, a comment counting), an unknown item exit 1.

    tests/run-suite question        → exit 0 / 1"""
import contextlib, io, json, os, re, socket, sys, pathlib, tempfile, logging, time
BID_A = 9171
BID_B = 9172
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="questiontest-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store (session links off)
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
for d in ("store/a", "fleet/a", "state/anchor-hub", "brain/projects", "brain/infra", "secrets"): (T / d).mkdir(parents=True)
NAMES = ("home-sparrow", "home-sparrow-main", "home-sparrow-docs", "home-sparrow-engineer", "home-delta", "home-delta-docs", "home-beta")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a", "url": "", "seen": "x"} for n, u in U.items()}))
(T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")
def page(rel, front):
    q = T / "brain" / rel; q.parent.mkdir(parents=True, exist_ok=True); q.write_text("---\n" + front + "\n---\n\n# x\n", encoding="utf-8")
page("projects/alpha.md", "type: project\ntitle: Alpha\ndisplay-name: home-sparrow\nagents:\n  home-sparrow-docs: keeps the docs\n  home-sparrow-main: talks to Oliver\n"
                          "  background:\n    home-sparrow-engineer: builds and merges\nstatus: active")
page("projects/alpha/sub.md", "type: project\ntitle: Sub")
page("projects/beta.md", "type: project\ntitle: Beta\ndisplay-name: home-beta\nstatus: active")
page("ops/beta.md", "type: note\ntitle: Beta ops\ndisplay-name: home-beta\nstatus: active")
page("projects/delta.md", "type: project\ntitle: Delta\ndisplay-name: home-delta\nagents:\n  home-delta-docs: keeps the docs\nstatus: active")
page("projects/gamma.md", "type: project\ntitle: Gamma\ndisplay-name: home-gamma\nstatus: active")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:500]}" if got is not None else ""))

from stackshot.projects import pages as p
p.cmd_registry(quiet=True)
from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route; from stackshot.service import writes; from stackshot.fleet import client; from stackshot.model import ids as _model_ids; from stackshot.service import create as create_svc
from stackshot.web import publish as _web_publish
from stackshot.web.tools import create as _wt_create
from stackshot.web.tools import get as _wt_get
from stackshot.web.tools import text as _wt_text
from stackshot.service import telling
from stackshot.service import writes
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
from starlette.testclient import TestClient
me = socket.gethostname(); tok = open(client.mint(me)).read().strip(); H = {"Authorization": "Bearer " + tok}
ASK = "Decide: whether to cut the retry to three · Recommend: yes · Stakes: the run waits an hour either way · By: Fri Mar 13th"
OPTS = [{"label": "Cut", "line": "Cut the retry to three and go on.", "recommended": True}, {"label": "Keep", "line": "Keep five retries and wait.", "recommended": False}]
SUBJ = "[home] Cut the nightly retry?"
BODY = "The nightly run failed twice on the same step.\nCut the retry to three, or keep five and wait?"
import itertools, threading
RIDS = itertools.count(1)
def desc(sender="q-script", machine=me, text=BODY): return "\n".join("- " + l.strip() for l in text.strip().splitlines() if l.strip()) + f"\n- Filed by {sender} (a script on {machine})"   # one bullet per line
def q(machine=None, **kw):
    """The client API's write, in-process; every call a new request id unless it passes one (None leaves it out)."""
    b = {"project": "alpha", "ask": ASK, "text": BODY, "sender": "q-script", "options": OPTS, "subject": SUBJ, "request_id": f"t-{next(RIDS)}"}; b.update(kw)
    return server._client_post(machine or me, "question", {k: v for k, v in b.items() if v is not None})
def items():
    return sorted(p_.stem for d in (T / "store").iterdir() if d.is_dir() for p_ in d.glob("*.json") if p_.stem.isdigit() and p_.stem != "1")
def item(shown): return server._load(_model_ids._norm_id(shown))
n0 = len(items())

# ---- 1. a question filed over the client API
st, out = q()
check("filed: 200 with the item's id as shown, the project's key and its -main agent", st == 200 and out["project"] == "projects/alpha" and out["owner"] == "home-sparrow-main" and out["repeat"] is False
      and out["item"] == server._gh.shown(_model_ids._norm_id(out["item"])), (st, out))
it = item(out["item"]); m = it["metadata"]
check("the item is open, needs = decision, with the ask and the two options (one recommended)", it["status"] == "open" and m["needs"] == ["decision"] and m["ask"] == ASK
      and m["options"] == OPTS, (it["status"], m))
check("…owned by the project's -main agent (not the first front agent by name), filed under the page's key", server._session_label(m["owner"]) == "home-sparrow-main" and m["project"] == "projects/alpha", m)
check("…the text is the description, ending with the line that says who filed it; the subject is the one given", it["description"] == desc() and it["subject"] == SUBJ, (it["description"], it["subject"]))
check("…the sender is recorded as the creator, a script on this machine", it["filed_by"] == f"q-script (a script on {me})", it.get("filed_by"))
check("…the item is in the board's brief as waiting on the owner's decision", out["item"] in _wt_get.stackshot_get(out["item"]) and "needs: decision" in _wt_get.stackshot_get(out["item"]), _wt_get.stackshot_get(out["item"])[:300])
st, out2 = q(project="projects/alpha", subject="[work] Decide the nightly retry", options=None, ask="Decide: whether to cut the retry to three · Recommend: yes · Stakes: an hour either way · By: no date")
check("a given subject is the subject; no options is fine for a yes/no ask; the project by key", st == 200 and item(out2["item"])["subject"] == "[work] Decide the nightly retry" and "options" not in item(out2["item"])["metadata"], (st, out2))
A_ID = server.project_ref("alpha")["id"]
st, out3 = q(project=A_ID); check("the project by its id", st == 200 and out3["project"] == "projects/alpha", (st, out3))
st, out4 = q(project="projects/alpha/sub"); check("a sub-page is filed under itself and owned by its hub's -main agent", st == 200 and out4["project"] == "projects/alpha/sub" and out4["owner"] == "home-sparrow-main", (st, out4))
st, out5 = q(project="delta"); check("a project whose front agent is not -main: that agent owns it", st == 200 and out5["owner"] == "home-delta-docs", (st, out5))
long = "\n".join(f"line {i}: {'word ' * 30}" for i in range(1, 10)) + "\n"
five = "\n".join(f"line {i}" for i in range(1, 8))
st, out6 = q(text="\n\n  " + five + "\n")
check("the longest text that fits (max_lines less the provenance line) is kept whole, leading blank lines trimmed", st == 200 and item(out6["item"])["description"] == desc(text=five) and len([l for l in item(out6["item"])["description"].splitlines() if l.strip()]) == 8, out6)
st, out7 = q(sender=None); check("no sender: the script is called client.py", st == 200 and item(out7["item"])["filed_by"] == f"client.py (a script on {me})", out7)
filed = len(items()) - n0
check("every successful filing wrote one item", filed == 7, filed)


# ---- 2. refused: nothing filed, the tool's own text
def refused(name, status, needle, **kw):
    before = len(items()); st, out = q(**kw)
    check(name, st == status and needle in out.get("error", "") and len(items()) == before, (st, out))
    return out.get("error", "")
def tool_says(**kw):
    a = dict(subject="[home] a thing", description="- Goal: A thing\n- It lives here\n- Done when done", project="projects/alpha", owner="home-sparrow-main", needs=["decision"], ask=ASK); a.update(kw)
    try: _wt_create.stackshot_create(**a); return ""
    except server.ToolError as e: return str(e)
e = refused("a bad ask is refused with the tool's own text", 400, "Refused: ask must read", ask="please decide")
ALARM_ASK = "Decide: whether to kill the stuck run and rotate the credentials · Recommend: yes · Stakes: the quota is nearly spent · By: Fri Mar 13th"
st, out = q(subject="[home] Kill the run? The credentials leaked", ask=ALARM_ASK)
check("a script's question with alarming words (kill, credentials, quota, leaked) is filed: guard 11 does not judge that route", st == 200 and item(out["item"])["metadata"]["ask"] == ALARM_ASK, (st, out))
check("…while the create tool refuses the same words (the exemption is that route's only)", "uses \"" in tool_says(subject="[home] Kill the run?", ask=ALARM_ASK) and not getattr(writes.QUESTION, "on", False), tool_says(subject="[home] Kill the run?", ask=ALARM_ASK))
check("…word for word what the create tool says", e == tool_says(ask="please decide"), (e, tool_says(ask="please decide")))
e = refused("options with no recommended one: refused", 400, "exactly one option is recommended", options=[{"label": "A", "line": "do a", "recommended": False}, {"label": "B", "line": "do b", "recommended": False}])
check("…as the tool says", e == tool_says(options=[{"label": "A", "line": "do a", "recommended": False}, {"label": "B", "line": "do b", "recommended": False}]), e)
e = refused("one option only: refused", 400, "options takes", options=[OPTS[0]])
check("…as the tool says", e == tool_says(options=[OPTS[0]]), e)
refused("two recommended: refused", 400, "exactly one option is recommended", options=[{**OPTS[0]}, {**OPTS[1], "recommended": True}])
refused("two options with one label: refused", 400, "two options are labelled", options=[OPTS[0], {**OPTS[1], "label": "cut", "recommended": False}])
refused("a subject with no prefix: refused by the create gate", 400, "subject must start with", subject="Cut the retry?")
e = refused("no subject: refused, naming the configured prefixes (no default prefix)", 400, "subject is required", subject="")
check("…the prefixes are in the message", "'[work] '" in e and "'[home] '" in e, e)
refused("a request id with a line break: refused", 400, "request_id", request_id="a\nb")
refused("a request id of more than 120 characters: refused", 400, "request_id", request_id="r" * 121)
refused("no request id: refused (the call must be safe to repeat)", 400, "request_id is required", request_id=None)
e = refused("an ask of several decisions: refused by the one-decision gate", 400, "One decision per item", ask="Decide: whether to cut the retry; whether to move the run to night · Recommend: both · Stakes: time · By: no date")
check("…as the tool says", e == tool_says(ask="Decide: whether to cut the retry; whether to move the run to night · Recommend: both · Stakes: time · By: no date"), e)
OPEN_ASK = "Decide: what to do about the retry · Recommend: none, your call · Stakes: the run waits an hour either way · By: no date"
st, out = q(ask=OPEN_ASK, options=None)
check("an open question with no options still files an item: the open-question gate is the tools', a script's item is never lost", st == 200 and item(out["item"])["metadata"]["ask"] == OPEN_ASK and "options" not in item(out["item"])["metadata"], (st, out))
check("…while the create tool refuses the same ask", "open question" in tool_says(ask=OPEN_ASK) and "lists no options" in tool_says(ask=OPEN_ASK), tool_says(ask=OPEN_ASK))
st, out = q(ask=OPEN_ASK)
check("…and filed with its options it is stored as given", st == 200 and item(out["item"])["metadata"]["options"] == OPTS, (st, out))
refused("a description with a forbidden token: refused", 400, "contains", text="resolved: the retry")
refused("an unknown project: 404", 404, "no project", project="projects/nowhere")
refused("an ambiguous bare slug: 400, naming both pages", 400, "ambiguous", project="beta")
refused("a project whose page lists no front agent: refused, naming the page", 409, "projects/gamma lists no front agent", project="gamma")
refused("a sender that names the owner (the instance owner): refused", 400, "Only the board writes as", sender="the owner")
refused("a sender with a line break: refused", 400, "one line", sender="a\nb")
refused("a text over the line limit is refused, never cut", 400, "8 lines and an item's description takes at most 7", text=five + "\nline 8")
e = refused("a text over the character cap is refused, never cut", 400, "at most 8000", text="x" * 8001)
st, okcap = q(text="y" * 8000); check("…8000 characters exactly is taken", st == 200 and item(okcap["item"])["description"].startswith("- " + "y" * 50), (st, okcap))
# the text goes through the create gate as bullets, each line clipped to [description] line_max
dl = item(okcap["item"])["description"].splitlines()
check("…as one bullet clipped to the line limit with an ellipsis, then the Filed by bullet", len(dl) == 2 and len(dl[0]) <= 120 and dl[0].endswith(" …") and dl[1].startswith("- Filed by"), dl)
st, mk = q(text="- Already a bullet\n* A star bullet\nPlain prose line.")
check("a marker the text already carries is not doubled; prose becomes a bullet", st == 200 and item(mk["item"])["description"].splitlines()[:3] == ["- Already a bullet", "- A star bullet", "- Plain prose line."], (st, mk))
check("the route's items pass the create gate in full: every line is a bullet within the limit", all(l.startswith("- ") and len(l) <= 120 for l in item(mk["item"])["description"].splitlines()))
refused("a forbidden token in the text is still refused through the create gate (400)", 400, "contains 'resolved:'", text="resolved: the retry")
refused("missing text: 400", 400, "required", text="  \n ")
refused("missing ask: 400", 400, "required", ask="")
st, out = server._client_post(me, "question", {"project": "alpha", "ask": ASK, "text": BODY, "options": "nope"}); check("options that are not a list: 400", st == 400 and "options" in out["error"], (st, out))
st, out = server._client_post(me, "question", {"project": "alpha", "ask": ASK, "text": 5}); check("text that is not a string: 400", st == 400, (st, out))

# ---- 3. the page-debt rules: a script owes no page, the owner is charged none, and its own debt is not the script's to be refused for
old = time.time() - 8 * 3600; os.utime(T / "brain/projects/alpha.md", (old, old))     # the page is older than the debt, so nothing settles it
d = server._owed_load(); d.setdefault("projects/alpha", {})[server._session_id("home-sparrow-main")] = {"ts": time.time() - 4 * 3600, "item": "s5"}; server._owed_save(d)
debt = tool_says()
check("fixture: the -main agent owes a page past the grace, so the create tool would refuse its own filing", "you owe a project-page update" in debt, debt)
st, out = q()
check("…and the script's filing for it still goes through", st == 200, (st, out))
server._owed_save({})                                                           # (the page stays older than any new debt, so a reply's settling pass drops none)
OWNER_ID = server._session_id("home-sparrow-main")
def owes(who): return {k: e for k, os_ in server._owed_load().items() for o, e in os_.items() if o == who}
for _ in range(3): q()
check("a burst of script filings leaves the owner owing nothing (so its own board writes are not blocked); the page's keeper carries them", owes(OWNER_ID) == {} and set(server._owed_load()) <= {"projects/alpha"}, server._owed_load())
check("…and the tool's own create by that session, whose keeper is the page's own agent, charges nobody (a project page's keeper is never charged for its own filing; every project is the router's)", (_wt_create.stackshot_create(subject="[home] a thing by the session", description="- Goal: A thing\n- It lives here\n- Done when done", project="projects/alpha", owner="home-sparrow-main", next="home-sparrow-engineer: carry on"), owes(OWNER_ID))[1] == {}, owes(OWNER_ID))
server._owed_save({})
# a pilot project: the page's keeper is charged and told, the owner still is not
pushlog = T / "push.log"
(T / "fakepush.py").write_text("import sys, json\na = sys.argv[1:]\nif a[:1] == ['--from']: a = a[2:]\n"
                               f"open({str(pushlog)!r}, 'a').write(json.dumps(a) + '\\n')\nprint('delivered')\n")
telling.PUSH = [sys.executable, str(T / "fakepush.py")]
def pilot_toml(roots):
    pass            # every project page is the router's since there is no [pilot] projects list to set
pilot_toml(["projects/alpha"])
try:
    st, out = q()
    pend = server._owed_load()
    STEW = server._session_id("home-sparrow")
    check("in a pilot project the script's filing is charged to the page's keeper, not to the owner", st == 200 and owes(OWNER_ID) == {} and "projects/alpha" in pend and STEW in pend["projects/alpha"] and OWNER_ID not in pend["projects/alpha"], (st, pend))
finally:
    pilot_toml([]); server._owed_save({})
os.utime(T / "brain/projects/alpha.md", None)

# ---- 3a. the page-debt ledger under concurrent writers
errs = []
def mark(i):
    try: server._owed_mark("projects/alpha", f"lock-test-{i}", f"s{i}")
    except Exception as e: errs.append(e)
os.utime(T / "brain/projects/alpha.md", (old, old))
ths = [threading.Thread(target=mark, args=(i,)) for i in range(40)]
[t.start() for t in ths]; [t.join() for t in ths]
led = server._owed_load().get("projects/alpha", {})
check("forty threads charging debts at once lose none and fail none", not errs and all(f"lock-test-{i}" in led for i in range(40)), (errs[:2], len(led)))
check("…and leave no temporary file beside the ledger", not [f for f in os.listdir(server._owed_path().parent) if f.startswith(".ledger.json.")], os.listdir(server._owed_path().parent))
server._owed_save({}); os.utime(T / "brain/projects/alpha.md", None)

# ---- 3b. a request id makes a repeat safe
n1 = len(items())
st, r1 = q(request_id="park-17"); st2, r2 = q(request_id="park-17")
check("two posts with the same request id and sender give one item: the same id twice, the second marked a repeat", st == st2 == 200 and r1["item"] == r2["item"] and r1["repeat"] is False and r2["repeat"] is True and len(items()) == n1 + 1, (r1, r2))
st, r3 = q(request_id="park-17", text="another text altogether, a retry that came back different")
check("…whatever the retry carries: the first item stands, untouched", r3["item"] == r1["item"] and item(r1["item"])["description"] == desc() and len(items()) == n1 + 1, r3)
st, r4 = q(request_id="park-17", sender="other-script")
check("the same request id from another sender is another question", r4["item"] != r1["item"] and r4["repeat"] is False and len(items()) == n1 + 2, (r1, r4))
st, r4b = q(machine="home-other", request_id="park-17")
check("the same request id and sender from another machine is another question (two items)", r4b["item"] not in (r1["item"], r4["item"]) and r4b["repeat"] is False and len(items()) == n1 + 3
      and item(r4b["item"])["filed_by"] == "q-script (a script on home-other)" and item(r4b["item"])["description"] == desc(machine="home-other"), (r4b, len(items()) - n1))
st, r4c = q(machine="home-other", request_id="park-17")
check("…and each machine's repeat is its own item again", r4c["item"] == r4b["item"] and r4c["repeat"] is True and len(items()) == n1 + 3, r4c)
st, r5 = q(request_id="park-18"); st, r6 = q()
check("another request id files a new item each time", len({r1["item"], r5["item"], r6["item"]}) == 3 and len(items()) == n1 + 5 and r6["repeat"] is False, (r5, r6))
check("the triple is kept in the server's request map", server._gh.resolve(create_svc._requests()[f"question\x1f{me}\x1fq-script\x1fpark-17"]) == _model_ids._norm_id(r1["item"]), list(create_svc._requests())[-3:])
st, rg = q(project="gamma", request_id="park-19")
check("a refused call remembers nothing: after the project is fixed the same id files", st == 409 and "park-19" not in " ".join(create_svc._requests()) and q(request_id="park-19")[0] == 200)
# a stale entry: the mapped item is gone -> filed anew, the map follows
gone = server._path(_model_ids._norm_id(r5["item"])); gone.unlink()
n2 = len(items()); st, r7 = q(request_id="park-18")
check("a request id whose item no longer exists files anew (no previous entry), and the map now names the new item", st == 200 and r7["repeat"] is False and r7["item"] != r5["item"] and len(items()) == n2 + 1
      and server._gh.resolve(create_svc._requests()[f"question\x1f{me}\x1fq-script\x1fpark-18"]) == _model_ids._norm_id(r7["item"]), (st, r7))
check("…and the same id again is a repeat of that new item", q(request_id="park-18")[1]["item"] == r7["item"])
# the tool's own request_id, same fix
tk = dict(subject="[home] a tool thing", description="- Goal: A thing\n- It lives here\n- Done when done", project="projects/alpha", owner="home-sparrow-main", request_id="tool-req-1", next="home-sparrow-engineer: carry on")
t1 = _wt_create.stackshot_create(**tk); tg = _model_ids._norm_id(t1.split()[1]); server._path(tg).unlink()
t2 = _wt_create.stackshot_create(**tk)
check("the create tool: a request id whose item is gone creates anew instead of failing", t2.startswith("created ") and _model_ids._norm_id(t2.split()[1]) != tg, t2[:120])
# concurrency: one triple from many threads is one item; different ids from many threads all land in the map
import threading
n3 = len(items()); res = []
ths = [threading.Thread(target=lambda: res.append(q(request_id="race-1"))) for _ in range(8)]
[t.start() for t in ths]; [t.join() for t in ths]
check("eight threads posting one triple at once file one item and all get its id", len(items()) == n3 + 1 and len({r[1]["item"] for r in res}) == 1 and all(r[0] == 200 for r in res) and sum(1 for r in res if not r[1]["repeat"]) == 1, [r for r in res][:3])
errs = []
def remember(i):
    try: create_svc._remember_request(f"map-race-{i}", f"s{9000 + i}")
    except Exception as e: errs.append(e)
ths = [threading.Thread(target=remember, args=(i,)) for i in range(40)]
[t.start() for t in ths]; [t.join() for t in ths]
mp = create_svc._requests()
check("forty threads writing the request map at once lose no entry and fail none", not errs and all(mp.get(f"map-race-{i}") == f"s{9000 + i}" for i in range(40)), (errs[:2], sum(1 for i in range(40) if f"map-race-{i}" in mp)))
check("…and leave no temporary file beside it", not [f for f in os.listdir(create_svc.REQUESTS.parent) if f.startswith(".requests.json.")], os.listdir(create_svc.REQUESTS.parent))

# ---- 4. get answer
import datetime as _dt
def W(ts): return _dt.datetime.fromtimestamp(ts, _wt_text.ZONE).isoformat(timespec="seconds")      # the line's fourth field
def TS(i): return 1_800_000_000 + 100 * i
def put_answers(shown, *answers):
    gid = _model_ids._norm_id(shown); it = server._load(gid)
    it["metadata"]["answers"] = [{"ts": TS(i), "via": "board", **a} for i, a in enumerate(answers)]; writes.save(gid, it)
st, ct, body = server._client_get("answer", {"key": out["item"]})
check("get answer: an empty body before he answers", st == 200 and body == "", (st, body))
put_answers(out["item"], {"kind": "decision", "choice": "Cut", "text": "Yes, cut it.\nTell Pat."})
st, ct, body = server._client_get("answer", {"key": out["item"]})
check("get answer: the kind (decision), the option's label, his text and when, tab-separated on one line", st == 200 and body == f"decision\tCut\tYes, cut it. / Tell Pat.\t{W(TS(0))}\n", (st, body))
put_answers(out["item"], {"kind": "decision", "choice": "Keep", "text": ""}, {"kind": "comment", "text": "wait, make that\ttwo."})
st, ct, body = server._client_get("answer", {"key": out["item"]})
check("get answer: a decision followed by a later comment returns the decision (the comment does not hide it)", body == f"decision\tKeep\t\t{W(TS(0))}\n", repr(body))
put_answers(out["item"], {"kind": "comment", "text": "first thought\tone"}, {"kind": "comment", "text": "wait, make that\ttwo."})
check("get answer: comments alone return the newest comment (kind comment, no label, a tab in the text a space)", server._client_get("answer", {"key": out["item"]})[2] == f"comment\t\twait, make that two.\t{W(TS(1))}\n", server._client_get("answer", {"key": out["item"]})[2])
put_answers(out["item"], {"kind": "decision", "choice": "Cut", "text": "early"}, {"kind": "comment", "text": "hm"}, {"kind": "decision", "choice": "Keep", "text": ""}, {"kind": "comment", "text": "and another"})
check("get answer: the newest of several decisions wins over comments before and after it; a choice with no text", server._client_get("answer", {"key": out["item"]})[2] == f"decision\tKeep\t\t{W(TS(2))}\n", server._client_get("answer", {"key": out["item"]})[2])
put_answers(out["item"], {"kind": "comment", "text": "c"}, {"kind": "decision", "text": "Neither: do the smaller fix."})
check("get answer: a decision in words (no option) after a comment", server._client_get("answer", {"key": out["item"]})[2] == f"decision\t\tNeither: do the smaller fix.\t{W(TS(1))}\n")
put_answers(out["item"], {"kind": "decision", "choice": "Keep", "text": ""})
(T / "store/a/64.json").write_text(json.dumps({"id": "64", "subject": "[home] an old item", "description": "Old. Here. Done.", "status": "open", "metadata": {"owner": "home-sparrow-main", "project": "projects/alpha",
      "answers": [{"ts": 1.0, "kind": "decision", "choice": "Go", "text": "ok", "via": "board"}]}}))
for form in ("a64", "A64"):
    check(f"get answer: an older item's id ({form}) is read as the tools read it", server._client_get("answer", {"key": form}) == (200, "text/plain; charset=utf-8", f"decision\tGo\tok\t{W(1.0)}\n"), server._client_get("answer", {"key": form}))
sid_new = _model_ids._norm_id(out["item"])
check("get answer: the store form of a new item's id (s<n>) works as well as the form shown", server._client_get("answer", {"key": sid_new})[2] == server._client_get("answer", {"key": out["item"]})[2], sid_new)
st, ct, body = server._client_get("answer", {"key": f"board#{BID_A}"}); check("get answer: an item that does not exist is 404", st == 404, (st, body))
st, ct, body = server._client_get("answer", {"key": "nonsense"}); check("get answer: a malformed id is 404", st == 404, (st, body))
st, ct, body = server._client_get("answer", {}); check("get answer: no key is 400", st == 400, (st, body))

# ---- 5. over HTTP and through client.py
app = server.mcp.http_app()
with TestClient(app) as c:
    r = c.post("/client/question", json={"project": "alpha", "ask": ASK, "text": BODY}); check("http: question without a token -> 401", r.status_code == 401, r.status_code)
    r = c.get("/client/answer", params={"key": out["item"]}); check("http: answer without a token -> 401", r.status_code == 401, r.status_code)
    r = c.post("/client/question", json={"project": "alpha", "ask": ASK, "text": BODY, "sender": "http-script", "options": OPTS, "subject": SUBJ, "request_id": "http-1"}, headers=H)
    check("http: question with a machine token -> 200 and the item", r.status_code == 200 and r.json()["owner"] == "home-sparrow-main" and r.headers["cache-control"] == "no-store", r.text)
    r = c.post("/client/question", json={"project": "alpha", "ask": "no", "text": BODY, "subject": SUBJ, "request_id": "http-2"}, headers=H); check("http: a refusal is 400 with the tool's text", r.status_code == 400 and r.json()["error"].startswith("Refused: ask must read"), r.text)
    r = c.post("/client/question", json={"project": "gamma", "ask": ASK, "text": BODY, "subject": SUBJ, "request_id": "http-2"}, headers=H); check("http: no front agent is 409", r.status_code == 409, r.text)
    r = c.get("/client/answer", params={"key": out["item"]}, headers=H); check("http: answer -> 200 and the line", r.status_code == 200 and r.text == f"decision\tKeep\t\t{W(TS(0))}\n" and r.headers["cache-control"] == "no-store", (r.status_code, r.text))
    import urllib.request, urllib.error
    class _Resp:
        def __init__(s, r): s.status = r.status_code; s._b = r.content
        def read(s): return s._b
        def __enter__(s): return s
        def __exit__(s, *a): return False
    down = {"on": False}
    def fake_urlopen(req, timeout=0):
        if down["on"]: raise urllib.error.URLError("connection refused")
        path = req.full_url.replace(client.server_url(), "")
        r = c.post(path, content=req.data, headers=dict(req.header_items())) if req.get_method() == "POST" else c.get(path, headers=dict(req.header_items()))
        if r.status_code >= 400: raise urllib.error.HTTPError(req.full_url, r.status_code, "x", {}, io.BytesIO(r.content))
        return _Resp(r)
    client.urllib.request.urlopen = fake_urlopen
    def run(*argv, stdin="", norid=False):
        if argv[:2] == ("post", "question") and not norid and "--request-id" not in argv: argv = (*argv, "--request-id", f"cli-{next(RIDS)}")
        so, se = io.StringIO(), io.StringIO(); old = sys.stdin; sys.stdin = io.StringIO(stdin)
        try:
            with contextlib.redirect_stdout(so), contextlib.redirect_stderr(se): rc = client.main(["client.py", *argv])
        finally: sys.stdin = old
        return rc, so.getvalue(), se.getvalue()
    # an earlier scenario's one-shot push threads (a hand-off's push result) may still be finishing: they print to the process's stderr, which run() swaps for its own,
    # so one that lands inside the call below is counted as the call's stderr (main's measured run 9000021: "handoff: the item push result not recorded"). Let them end first.
    for _t in threading.enumerate():
        if _t is not threading.current_thread() and _t.daemon: _t.join(timeout=3)
    before = len(items())
    rc, o, e = run("post", "question", "--project", "alpha", "--ask", ASK, "--option", "Cut=Cut the retry to three and go on.", "--option", "Keep=Keep five retries and wait.",
                   "--recommended", "cut", "--sender", "cli-script", "--subject", "[home] Cut the nightly retry?", stdin=BODY)
    gid_cli = o.strip()
    check("client.py post question: exactly the item id on stdout, nothing on stderr, exit 0", rc == 0 and re.fullmatch(r"\S+", o.rstrip("\n")) and o.endswith("\n") and o.count("\n") == 1 and e == "" and len(items()) == before + 1, (rc, o, e))
    it = item(gid_cli); m = it["metadata"]
    check("…the item has the options (the recommended one by label, any case), the ask, the owner, the subject, the description, the creator", it["status"] == "open" and m["needs"] == ["decision"] and m["options"] == OPTS and m["ask"] == ASK
          and server._session_label(m["owner"]) == "home-sparrow-main" and it["subject"] == "[home] Cut the nightly retry?" and it["description"] == desc("cli-script") and it["filed_by"] == f"cli-script (a script on {me})", (it, m))
    rc, o, e = run("get", "answer", gid_cli); check("client.py get answer: nothing printed before he answers, exit 0", rc == 0 and o == "" and e == "", (rc, o, e))
    put_answers(gid_cli, {"kind": "decision", "choice": "Cut", "text": "Do it."})
    rc, o, e = run("get", "answer", gid_cli); check("client.py get answer: the line after he answers, exit 0", rc == 0 and o == f"decision\tCut\tDo it.\t{W(TS(0))}\n" and e == "", (rc, o, e))
    put_answers(gid_cli, {"kind": "decision", "choice": "Cut", "text": "Do it."}, {"kind": "comment", "text": "Actually, wait."})
    rc, o, e = run("get", "answer", gid_cli); check("client.py get answer: a decision then a later comment prints the decision", rc == 0 and o == f"decision\tCut\tDo it.\t{W(TS(0))}\n", (rc, o, e))
    put_answers(gid_cli, {"kind": "comment", "text": "Actually, wait."})
    rc, o, e = run("get", "answer", gid_cli); check("client.py get answer: comments alone, the newest comment", rc == 0 and o == f"comment\t\tActually, wait.\t{W(TS(0))}\n", (rc, o, e))
    rc, o, e = run("get", "answer", f"board#{BID_A}"); check("client.py get answer: an unknown item is exit 1, the reason on stderr, nothing on stdout", rc == 1 and o == "" and "[404]" in e, (rc, o, e))
    rc, o, e = run("get", "answer"); check("client.py get answer with no id: usage, exit 1", rc == 1 and o == "" and "usage: client.py get answer" in e, (rc, o, e))
    before = len(items())
    rc, o, e = run("post", "question", "--project", "alpha", "--ask", "please decide", "--subject", SUBJ, stdin=BODY)
    check("client.py post question, a bad ask: the tool's text on stderr, nothing on stdout, exit 1, nothing filed", rc == 1 and o == "" and "[400]" in e and "Refused: ask must read" in e and len(items()) == before, (rc, o, e))
    rc, o, e = run("post", "question", "--project", "alpha", "--ask", ASK, "--option", "Cut=go", "--option", "Keep=stay", "--subject", SUBJ, stdin=BODY)
    check("client.py post question, options and no --recommended: the tool's refusal, exit 1", rc == 1 and o == "" and "exactly one option is recommended" in e and len(items()) == before, (rc, o, e))
    rc, o, e = run("post", "question", "--project", "gamma", "--ask", ASK, "--subject", SUBJ, stdin=BODY)
    check("client.py post question, a project with no front agent: exit 1 and the reason on stderr", rc == 1 and o == "" and "[409]" in e and "lists no front agent" in e, (rc, o, e))
    before = len(items())
    rc, o, e = run("post", "question", "--project", "alpha", "--ask", ASK, "--subject", SUBJ, stdin=long)
    check("client.py post question, a text over the line limit: refused (exit 1), the reason on stderr, nothing on stdout, nothing filed, never cut", rc == 1 and o == "" and "[400]" in e and "at most 7" in e and len(items()) == before, (rc, o, e))
    rc, o, e = run("post", "question", "--project", "alpha", "--ask", ASK, "--subject", SUBJ, stdin="x" * 8001)
    check("client.py post question, a text over 8000 characters: refused the same way", rc == 1 and o == "" and "at most 8000" in e and len(items()) == before, (rc, o, e))
    rc, o, e = run("post", "question", "--project", "alpha", "--ask", ASK, "--subject", SUBJ, stdin=BODY, norid=True)
    check("client.py post question with no --request-id: usage, exit 1, nothing on stdout, nothing filed", rc == 1 and o == "" and "usage: client.py post question" in e and "--request-id" in e and len(items()) == before, (rc, o, e))
    before = len(items())
    rc, o, e = run("post", "question", "--project", "alpha", "--ask", ASK, stdin=BODY)
    check("client.py post question with no --subject: exit 1, the reason names the configured prefixes, nothing on stdout, nothing filed", rc == 1 and o == "" and "[400]" in e and "subject is required" in e and "'[work] '" in e and "'[home] '" in e and len(items()) == before, (rc, o, e))
    rc, o, e = run("post", "question", "--project", "alpha", "--ask", ASK, "--subject", "no prefix here", stdin=BODY)
    check("client.py post question with a subject without a prefix: the create gate's refusal, exit 1", rc == 1 and o == "" and "subject must start with" in e and len(items()) == before, (rc, o, e, len(items()), before))
    before = len(items())
    rc, o, e = run("post", "question", "--project", "alpha", "--ask", ASK, "--subject", SUBJ, "--request-id", "cli-1", "--sender", "cli-script", stdin=BODY)
    rc2, o2, e2 = run("post", "question", "--project", "alpha", "--ask", ASK, "--subject", SUBJ, "--request-id", "cli-1", "--sender", "cli-script", stdin=BODY)
    check("client.py post question --request-id: the same call twice prints the same id twice, exit 0, one item filed", rc == rc2 == 0 and o == o2 and re.fullmatch(r"\S+\n", o) and e == e2 == "" and len(items()) == before + 1, (rc, o, e, rc2, o2, e2))
    before = n_before = len(items())
    for name, argv, text in (("no --project", ["--ask", ASK], BODY), ("no --ask", ["--project", "alpha"], BODY), ("an empty text", ["--project", "alpha", "--ask", ASK, "--subject", SUBJ], "  \n"),
                             ("an --option with no =", ["--project", "alpha", "--ask", ASK, "--option", "Cut"], BODY), ("an --option with an empty line", ["--project", "alpha", "--ask", ASK, "--option", "Cut="], BODY),
                             ("--recommended naming no option", ["--project", "alpha", "--ask", ASK, "--option", "Cut=go", "--option", "Keep=stay", "--recommended", "Zip"], BODY),
                             ("--recommended with no options", ["--project", "alpha", "--ask", ASK, "--recommended", "Cut"], BODY),
                             ("a flag with no value", ["--project", "alpha", "--ask"], BODY), ("a stray word", ["--project", "alpha", "--ask", ASK, "stray"], BODY), ("--request-id with no value", ["--project", "alpha", "--ask", ASK, "--request-id"], BODY)):
        rc, o, e = run("post", "question", *argv, stdin=text, norid=argv[-1] in ("--ask", "--request-id"))
        check(f"client.py post question misuse, {name}: usage on stderr, nothing on stdout, exit 1", rc == 1 and o == "" and any(w in e for w in ("usage: client.py post question", "needs a value", "text is empty")), (rc, o, e))
    check("…and none of them filed an item", len(items()) == n_before, (len(items()), n_before))
    # no token, and a server that does not answer
    tokfile = pathlib.Path(client.TOKEN); hold = tokfile.with_suffix(".held"); tokfile.rename(hold)
    try:
        rc, o, e = run("post", "question", "--project", "alpha", "--ask", ASK, "--subject", SUBJ, stdin=BODY)
        check("client.py post question with no token on the machine: exit 1, the reason on stderr, nothing on stdout, nothing filed", rc == 1 and o == "" and "no token on this machine" in e and len(items()) == n_before, (rc, o, e))
        rc, o, e = run("get", "answer", gid_cli)
        check("client.py get answer with no token: exit 1, the reason on stderr", rc == 1 and o == "" and "no token on this machine" in e, (rc, o, e))
    finally: hold.rename(tokfile)
    down["on"] = True
    rc, o, e = run("post", "question", "--project", "alpha", "--ask", ASK, "--subject", SUBJ, stdin=BODY)
    check("client.py post question with the server not reached: exit 1, [0] and the reason on stderr, nothing on stdout", rc == 1 and o == "" and "[0]" in e and "URLError" in e, (rc, o, e))
    rc, o, e = run("get", "answer", gid_cli)
    check("client.py get answer with the server not reached: exit 1", rc == 1 and o == "" and "[0]" in e, (rc, o, e))
    down["on"] = False
    rc, o, e = run("get", "answer", gid_cli); check("…and the same call works again when the server does", rc == 0 and o == f"comment\t\tActually, wait.\t{W(TS(0))}\n", (rc, o, e))

# ---- 5b. provenance: Oliver sees who filed it, on the item page and in the issue body (the mirror on)
from stackshot.web.ui import render as ui_render
from stackshot.github import ghsync as G
st, pv = q(sender="nightly-job")
LINE = f"Filed by nightly-job (a script on {me})"
check("the item page shows the line that says who filed it", LINE in ui_render.Board(str(T / "store")).item_html(_model_ids._norm_id(pv["item"])), pv)
check("…and the description ends with it, as a bullet", item(pv["item"])["description"].splitlines()[-1] == "- " + LINE, item(pv["item"])["description"])
def write_toml(sync):
    t = (T / "stackshot.toml").read_text(encoding="utf-8"); t, n = re.subn(r'(?m)^sync = (true|false)', f'sync = {"true" if sync else "false"}', t); assert n == 1
    (T / "stackshot.toml").write_text(t, encoding="utf-8"); server._cfg.reload()
write_toml(True)
try:
    check("fixture: the mirror is on", G.enabled())
    before_jobs = set(p_.name for p_ in G.pending())
    st, pm = q(sender="nightly-job")
    new_jobs = [p_ for p_ in G.pending() if p_.name not in before_jobs]
    gid_pm = _model_ids._norm_id(pm["item"])
    check("with the mirror on, filing a question queues one job for the new issue and it is the script's item", st == 200 and len(new_jobs) == 1 and json.loads(new_jobs[0].read_text(encoding="utf-8"))["gid"] == gid_pm, (st, [p_.name for p_ in new_jobs]))
    body_md = G.body_of(gid_pm, server._load(gid_pm))
    check("…the GitHub issue body carries the same line (the description is in it) and no Ask or Options section", LINE in body_md and "### Ask" not in body_md and "### Options" not in body_md, body_md[:400])
    check("…the item records the script as its creator (filed_by), the issue comment is not claimed", item(pm["item"])["filed_by"] == f"nightly-job (a script on {me})")
finally: write_toml(False)

# ---- 6. the docs
help_text = client.__doc__
check("the client help documents both verbs, the stable answer line and the fresh-item-per-question rule", "client.py post question" in help_text and "client.py get answer" in help_text
      and "TAB" in help_text and "a fresh item for each question" in help_text and "answer <board#N>" in help_text
      and "A caller resumes only on a line\n                                whose kind is decision" in help_text and "his newest decision on the item" in help_text and "<when>" in help_text and "503" in help_text and "--request-id is required" in help_text and "Filed by <label>" in help_text and "clipped as it reads" in help_text)
import _docs
readme = _docs.page("client-contract")
check("the docs' client contract documents POST /client/question and GET /client/answer", "POST /client/question" in readme and "GET /client/answer" in readme and "fresh item per question" in readme
      and "A caller resumes only on `decision`" in readme and "**the fleet tool passes one per parked question**" in readme and "Filed by <sender> (a script on" in readme and "GitHub issue comment" not in readme and "the keeper is the owner itself" in readme and "never reads the project record" in readme and "newest `decision`" in readme)
check("the pilot_charge docstring says a script's filing is never charged to the owner, the keeper being the owner included", "the owner itself" in telling.pilot_charge.__doc__)
check("the 404 lists of the client API name the new entries", "question" in server._client_post(me, "nope", {})[1]["error"] and "answer?key=" in server._client_get("nope", {})[2])

# ---- a script's subject is cut to the subject limit, never refused (a script's item must not be lost on a 400)
LONG_SUBJ = "[home] " + " ".join(f"Cut the retry of step {i}?" for i in range(1, 8))       # about 170 characters
check("fixture: the long subject is over 150 characters", len(LONG_SUBJ) > 150, len(LONG_SUBJ))
st, outc = q(subject=LONG_SUBJ[:150])
cut = item(outc["item"])["subject"] if st == 200 else ""
check("post question with a 150-character subject files the item, its subject at most 80 characters, the scope prefix and the start of the words kept, cut at a word with an ellipsis",
      st == 200 and len(cut) <= 80 and cut.startswith("[home] Cut the retry of step 1?") and cut.endswith(" …") and len(cut) > 60, (st, outc, cut))
st, outd = q(subject="[home] " + "s" * 73)
check("…a subject of exactly 80 characters is kept as it is", st == 200 and item(outd["item"])["subject"] == "[home] " + "s" * 73, (st, outd))
(T / "store/g").mkdir(exist_ok=True)
(T / "store/g/9172.json").write_text(json.dumps({"id": "9172", "subject": "[home] a target", "description": "- x", "status": "open", "updated": time.time(), "state_updated": time.time(), "confirmed": time.time(), "metadata": {"owner": "home-sparrow-main", "project": "projects/alpha"}}))
GSUBJ = "[home] " + " ".join(["Decide g9172"] * 14)           # 7 + 14 * 12 + 13 = 188 characters; expanded (g9172 to) longer still
st, oute = q(subject=GSUBJ)
cut_g = item(oute["item"])["subject"] if st == 200 else ""
check("…ids are expanded before the cut: the subject is at most 80 characters and carries board#<a>, never a bare g9172", st == 200 and len(cut_g) <= 80 and f"board#{BID_B}" in cut_g and "g9172" not in cut_g.replace(f"board#{BID_B}", ""), (st, oute, cut_g))
(T / "store/g/9172.json").unlink()
(T / "store/g").rmdir()

if fails:
    print(f"\n{len(fails)} of {len(ran)} checks FAILED"); sys.exit(1)
print(f"ok: {len(ran)} checks"); sys.exit(0)
