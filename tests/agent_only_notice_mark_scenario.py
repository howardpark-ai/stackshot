"""Scenario test for: a notice the server builds for a front agent that asks the person for nothing does not open with the owner mark ("[for <owner>]"), and the front agent is still told —
fixture data, no live store, no network, no server socket, no tmux.

The mark means the person has something to do. A comment on an item, a board answer, an ask taken off his move, a close, the ladder's and the recovery's request to -main each ask the front
agent to act (or tell it news); none asks him anything, so none carries the mark (the audit's and page-debt notices, with the same rule, are checked in their own suites). Whether such
a notice is pushed to a front agent is decided by its kind (telling.FRONT_TAG_KIND, front_gate), never by the mark. This suite drives the real senders and the real delivery path (telling.tell_woken -> front_gate
-> the push command; only the push command's last hop is replaced by a recorder) and proves:

  1  comment          the owner's comment is told to the front mover unmarked, and pushed to it while nobody is there for its pane
  2  answer           his board answer relayed to the front mover: unmarked, pushed
  3  ask              an ask taken off his move, told to the front mover: unmarked, pushed
  4  close            the three close notices to a front mover (a session's close, the done check's, the fallback of a close with his words): unmarked, and held or pushed exactly as the same text with the mark
  5  hand-back        (unchanged) an item handed back to a front mover alone in a front-only project keeps the router's mark on its direct fallback, and is pushed
  6  ladder           the ladder's one notice to -main about silent background movers (a lone item and a list): unmarked, pushed
  7  recovery         the last rung's request to -main in a front-only project: unmarked, pushed
  8  what stays marked  an item handed back (a front-only project's direct fallback, 5), a wake of an item that waits on his decision, the router's pass of a notice that needs him, and the audit's finding for a front agent keep the mark

    tests/run-suite agent_only_notice_mark        -> exit 0 / 1"""
import json, os, re, sys, pathlib, time, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="agentonlymark-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's fleet store
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1   # never the host's transcripts
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/demo", "brain/projects", "transcripts/-home-x"): (T / d).mkdir(parents=True)
F_B, B_B, SOLO = "home-echo-main", "home-echo-build", "home-loner"
NAMES = (F_B, B_B, SOLO)
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
now0 = time.time()
DAY = 86400.0
ZONE_HOURS = 4      # the instance timezone pinned above (Asia/Dubai, UTC+4, no DST)
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
page = lambda **kw: {"title": "T", "name": "T", "org": "home", "tags": [], "type": "project", "session": "", "status": "active", "board": [], "board_open": 0, **kw}
(T / "store/projects.json").write_text(json.dumps({"pages": {
    "projects/echo": page(title="Echo", name="Echo", agents={F_B: "the front"}),                                                                  # a front agent alone: no builder
    "projects/delta": page(title="Delta", name="Delta", agents={F_B: "the front", B_B: "builds it"}, back_agents={B_B: "builds it"})}}))          # a front agent and a builder
(T / "brain/projects/echo.md").write_text(f"---\ntitle: Echo\nagents:\n  {F_B}: the front\n---\n\n# Echo\n")
(T / "brain/projects/delta.md").write_text(f"---\ntitle: Delta\nagents:\n  {F_B}: the front\n  background:\n    {B_B}: builds it\n---\n\n# Delta\n")
(T / "store/next-id").write_text("900"); (T / "store/anchors.json").write_text("{}")
DESC = "- A thing\n- It lives here\n- Done when done"
def item(i, status="open", su=None, project="projects/echo", **meta):
    su = now0 - 10 * DAY if su is None else su
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": DESC, "status": status, "updated": su, "state_updated": su, "confirmed": su,
                                                      "metadata": {"owner": SOLO, "project": project, "next": f"{B_B}: do the thing", **meta}}))
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
def mt(i): return rd(i)["metadata"]
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
sys.path.insert(0, STACK); logging.disable(logging.INFO)
from stackshot.web import server
assert server.__name__      # the import is what installs the telling's hooks (web/wiring.py)
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
from stackshot.web.tools import anchors as _wt_anchors
from stackshot.web.tools import route as _wt_route
from stackshot.web.tools import text as _wt_text
from stackshot.service import watching as watching_svc
from stackshot.service import telling
from stackshot.core import config as _cfg
from stackshot.service import answer as answer_svc, asks as asks_svc, pane_recovery, ladder as ladder_svc
from stackshot.router import router_live as _router_live
from stackshot.audit import audit_run as _audit_run
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._refuse_if_owing = lambda debtor: None
CFG = _cfg.CFG.setdefault("model", {})
CFG.update(guards=False, pause=False)
MARK = _wt_text._FOR_OWNER

# the real delivery path, but for the program that writes into the pane: every push the server makes is a line in this log
PUSHLOG = T / "push.log"
(T / "fakepush.py").write_text(f"import sys, json\na = sys.argv[1:]\nif a[:1] == ['--from']: a = a[2:]\nopen({str(PUSHLOG)!r}, 'a').write(json.dumps(a) + '\\n')\nprint('delivered \u2192 ' + a[0])\n")
telling.PUSH = [sys.executable, str(T / "fakepush.py")]
THREADS = []
_real_tell = telling.tell_woken
def _tell(gid, owner, note, tag="wake", result=None):
    th = _real_tell(gid, owner, note, tag)
    if th: THREADS.append(th)
    return th
telling.tell_woken = _tell
def drain():
    while THREADS: THREADS.pop(0).join(30)
def pushes(): return [json.loads(l) for l in PUSHLOG.read_text().splitlines()] if PUSHLOG.exists() else []
def reset():
    drain(); PUSHLOG.unlink(missing_ok=True)
day = lambda n: time.strftime("%Y-%m-%d", time.gmtime(now0 + n * DAY + ZONE_HOURS * 3600))
def board_lines(i): return (mt(i).get("front_quiet") or {}).get("log") or []

# nobody is present for any pane here (see the setup check). A notice of a held kind to a front agent is held in this state (4); a watch notice is not.
check("setup: the front agent is one for both projects, the builder is not", telling.front_keeper(F_B, "projects/echo")[0] and telling.front_keeper(F_B, "projects/delta")[0] and not telling.front_keeper(B_B, "projects/delta")[0], None)
check("setup: nobody is there for the front agent's pane", not telling.presence_here(U[F_B]), None)


# every notice the server tells a session, with its kind (the hint tell_kind gives the gate), as the real senders pass it to tell_woken
REC = []
_t_inner = telling.tell_woken
def _rec(gid, owner, note, tag="wake", result=None):
    REC.append((gid, owner, note, tag, getattr(telling.FRONT_HINT, "kind", "")))
    return _t_inner(gid, owner, note, tag, result)
telling.tell_woken = _rec
def start(): reset(); REC.clear()
def to_front(tag=None): return [r for r in REC if r[1] == U[F_B] and (tag is None or r[3] == tag)]
def unmarked(label, tag, first="[stackshot] ", n=1):
    got = to_front(tag)
    check(f"{label}: the front mover is told {n} time(s), by the notice's own first line, no mark anywhere in it", len(got) == n and all(r[2].startswith(first) and MARK not in r[2] for r in got), REC)
    return got
def pushed(label, got):
    p = pushes()
    check(f"{label}: …and it is pushed to the front agent, as it was told, while nobody is there for its pane", len(p) == len(got) and all(x[0] == U[F_B] for x in p) and [x[1] for x in p] == [r[2] for r in got], (p, [r[2] for r in got]))
def same_as_marked(label, got):
    """a notice of a held kind (a close): the gate holds the unmarked text exactly as it holds the same text with the old mark: the mark never decided it"""
    note, tag, kind = got[0][2], got[0][3], got[0][4]
    a = (pushes(), telling.FRONT_HINT.result)
    reset()
    telling.tell_kind(kind, got[0][0], U[F_B], MARK + " " + note, tag=tag); drain()
    b = (pushes(), telling.FRONT_HINT.result)
    check(f"{label}: …held or pushed exactly as the same text with the old mark (kind {kind!r}): the gate reads the kind, not the mark", a == b and kind == "close", (a, b))

def item_full(i, **meta):
    item(i, mover=F_B, needs=[], next=f"{F_B}: look at it", **meta)
    return rd(i)

# ================================================================ 1. the owner's comment
it = item_full(1); start()
telling.tell_comment("a1", it, "yes, go ahead"); drain()
got = unmarked("1 comment", "comment"); pushed("1 comment", got)
check("1 comment: kind exempt (it asks the mover to act), so a front agent is pushed it", got and telling.FRONT_TAG_KIND.get("comment") == "exempt" and "commented on" in got[0][2], got)

# ================================================================ 2. his board answer
it = item_full(2); start()
answer_svc._answer_deliver("a2", it, {"kind": "decision", "choice": "a", "text": ""}); drain()
got = unmarked("2 answer", "answer"); pushed("2 answer", got)
check("2 answer: kind exempt, and the line says what he answered", got and telling.FRONT_TAG_KIND.get("answer") == "exempt" and "answered" in got[0][2], got)

# ================================================================ 3. an ask taken off his move
item(3, needs=["decision"], ask="Decide: a or b · Recommend: a · Stakes: none · By: no date", mover=F_B, next=f"{F_B}: wait for his answer"); start()
asks_svc._ask_leave("a3", "the ask was wrong, it asks him something that is not his"); drain()
got = unmarked("3 ask", "ask"); pushed("3 ask", got)
check("3 ask: kind exempt, and the line says the ask was taken off his move", got and telling.FRONT_TAG_KIND.get("ask") == "exempt" and "taken off" in got[0][2], got)

# ================================================================ 4. the close notices to a front mover (kind close: held while he is away, marked or not)
it = item_full(4, outcome="done"); it["status"] = "completed"; start()
telling.tell_owner_close("a4", it, B_B, True, []); drain()
got = unmarked("4 a session's close", "owner"); check("4 a session's close: kind close, nothing pushed while he is away", got and got[0][4] == "close" and pushes() == [], (REC, pushes())); same_as_marked("4 a session's close", got)
it = item_full(5, outcome="done"); it["status"] = "completed"; start()
telling.tell_owner_check_closed("a5", it, []); drain()
got = unmarked("4 the done check's close", "owner"); check("4 the done check's close: kind close, nothing pushed while he is away", got and got[0][4] == "close" and pushes() == [], (REC, pushes())); same_as_marked("4 the done check's close", got)
it = item_full(6, outcome="done"); it["status"] = "completed"; start()
telling.close_owner_notice("a6", it, F_B, "projects/echo", B_B, "a session", "said"); drain()
got = unmarked("4 the fallback of a close with his words", "owner"); check("4 the fallback of a close with his words: kind close, nothing pushed while he is away", got and got[0][4] == "close" and pushes() == [], (REC, pushes())); same_as_marked("4 the fallback of a close with his words", got)

# ================================================================ 5. an item handed back to a front mover alone (front-only project): the router's own hand-back mark stays, and so does its direct fallback
item_full(7); start()
_il = _router_live.is_live; _router_live.is_live = lambda project: False      # the router is not live for the project: the line is pushed at once
try:
    telling.handback_send({"gid": "a7", "oid": U[F_B], "olabel": F_B, "project": "projects/echo", "who": B_B, "wid": U[B_B], "subject": "[home] item 7",
                           "line": "[stackshot] a7 is back with you alone (handed back by home-echo-build): [home] item 7 \u2192 https://x/items/a7"}); drain()
finally:
    _router_live.is_live = _il
got = to_front("owner")
check("5 hand-back: the router decides it (its hand-back rule marks the pass it makes), so the fallback push to a front-only project's mover keeps the mark the router's pass has", len(got) == 1 and got[0][2].startswith(MARK + " [stackshot] a7 is back with you alone") and got[0][4] == "exempt", REC)
pushed("5 hand-back", got)

# ================================================================ 6. the ladder's notice to -main about silent background movers
item_full(8); item_full(9)
INFO = {g: {"subject": f"[home] item {g[1:]}", "mover": B_B, "since": "Mon Nov 23rd 08:24", "span": "101 minutes", "told": ""} for g in ("a8", "a9")}
start(); ladder_svc.ladder_main_tell(F_B, [("a8", "a8 line")], INFO); drain()
got = unmarked("6 ladder, one item", "stall"); pushed("6 ladder, one item", got)
start(); ladder_svc.ladder_main_tell(F_B, [("a8", "a8 line"), ("a9", "a9 line")], INFO); drain()
got = unmarked("6 ladder, a list", "stall"); pushed("6 ladder, a list", got)
check("6 ladder: kind exempt, and the notice asks the agent to decide (nothing for him)", got and telling.FRONT_TAG_KIND.get("stall") == "exempt" and "Decide for each" in got[0][2], got)

# ================================================================ 7. the last rung's request to -main in a front-only project
it = item_full(10); start()
pane_recovery._recovery_tell("a10", it, B_B, "its pane is gone", "the notice and a reminder", tag="stall", target=(F_B, "main", True)); drain()
got = unmarked("7 recovery", "stall"); pushed("7 recovery", got)
check("7 recovery: it asks the agent to decide what the item needs", got and "Please decide what it needs" in got[0][2], got)

# ================================================================ 8. what stays marked: a real need of his
dec = [("a2", {"id": "2", "subject": "[home] item 2", "metadata": {"project": "projects/echo", "needs": ["decision"]}}, "its wake came")]
check("8 a wake of an item that waits on his decision is marked for the front agent", watching_svc.watch_text(U[F_B], dec)[1] == MARK, None)
n_ = {"id": "n1", "label": "board a1", "who": "x", "text": "t"}
check("8 the router's pass of a notice that needs him is marked, one that does not is not",
      _router_live.compose(n_, "projects/echo", F_B, "he must decide", True, body="[board] a1 waits on his decision").startswith(MARK + " ") and not _router_live.compose(n_, "projects/echo", F_B, "", False, body="[board] a1").startswith(MARK), None)
check("8 an audit finding for a front agent keeps the mark on its first line", _audit_run.compose(["a1 · check · detail · fix"], "[stackshot] audit: 1 item for you", True).splitlines()[0] == MARK and not _audit_run.compose(["x"], "[stackshot] audit", False).startswith(MARK), None)

print(f"\n{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
