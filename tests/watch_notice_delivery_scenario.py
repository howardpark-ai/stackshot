"""Scenario test for: the mark on a watcher's "is yours now" notice does not decide whether the notice is delivered — fixture data, no live store, no network, no server socket, no tmux.

A watched wait that ends on a session turns the item and tells that session in one line ("... is yours now ..."). A front agent used to get the mark ("[for <owner>]" on the first line) for an item whose open
step is its own, although the person has nothing to do there: the move is the agent's. Now the mark goes only on an item that waits on his decision (watching.watch_text). This suite drives the real wake pass
and the real delivery path (watching.watch_tell -> telling.tell_woken -> telling.front_gate -> the push command; only the push command's last hop, the program that writes into the pane, is replaced by a
recorder) and proves that dropping the mark changes nothing about who is told:

  1  a front agent that is the item's mover (a step of its own, the wait ending on it in a project with no builder) is pushed the notice while the person is not there for its pane: unmarked, once, with no held
     line and no front-agent board line; the same text with the old mark on it is pushed exactly the same (the gate decides by the notice's kind, not by its first line)
  2  an item that waits on his decision (the mark stays) is pushed to the front agent too, marked
  3  a background agent is told as before: pushed once, unmarked, nothing held
  4  the contrast that makes 1 mean something: a notice of the kind that is held (a progress notice) to the same front agent in the same state is held whether it carries the mark or not, so the gate does read
     the kind, and a watch notice is not of that kind
  5  the delivery program does not read the mark (push.py and inbox.py name no `[for ...]` test)
  6  the other notices a front agent hears for its own move carry no mark either and are delivered as they were: a close by another session (pushed under his ask, held without it, marked or not),
     the ladder's notice about a silent background mover (pushed with nobody there); a notice that carries his own words (his comment) keeps the mark

    tests/run-suite watch_notice_delivery        -> exit 0 / 1"""
import json, os, re, sys, pathlib, time, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="watchdeliv-"); T = pathlib.Path(tmp)
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
from stackshot.web import server; from stackshot.service import writes
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
from stackshot.web.tools import anchors as _wt_anchors
from stackshot.web.tools import route as _wt_route
from stackshot.web.tools import text as _wt_text
from stackshot.service import wakes as wakes_svc, watching as watching_svc
from stackshot.service import telling
from stackshot.waits import held
from stackshot.core import config as _cfg
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

# ================================================================ 1. the front agent's own move: pushed, unmarked, as it is pushed with the mark
item(1, wait_kind="time", hold=True, wake=day(-1), post_wake_mover=F_B, needs=[], next=f"{F_B}: ask him which one to keep", subject="[home] its own step")
reset(); woke = wakes_svc.wake_pass(); drain()
p = pushes()
check("1 the wake turns the item and the front agent keeps it (no builder in the project)", "a1" in woke and mt(1).get("mover") == F_B, (woke, mt(1)))
check("1 the real wake pass pushes the notice to the front agent, once, while nobody is there for its pane", len(p) == 1 and p[0][0] == U[F_B], p)
check("1 …unmarked: no mark on the first line or anywhere in it, and it says whose move it is", p and not p[0][1].startswith(MARK) and MARK not in p[0][1] and "is yours now" in p[0][1] and p[0][1].startswith("[stackshot] "), p)
check("1 …it names the item and where to find it", p and " a1 " in p[0][1] and "/items/a1" in p[0][1], p)
check("1 …nothing held for the agent's next turn and no front-agent line on the item", held.count(U[F_B]) == 0 and not board_lines(1), (held.count(U[F_B]), board_lines(1)))
text = p[0][1] if p else ""
reset()
telling.tell_woken("a1", U[F_B], MARK + " " + text, tag="watch"); drain()
q = pushes()
check("1 the same notice carrying the old mark is pushed exactly as the unmarked one: same recipient, same count, the mark the only difference", len(q) == 1 and q[0][0] == p[0][0] and q[0][1] == MARK + " " + text, q)
check("1 …and that left nothing held either", held.count(U[F_B]) == 0 and not board_lines(1), (held.count(U[F_B]), board_lines(1)))
reset()
telling.tell_woken("a1", U[F_B], text, tag="watch"); drain()
check("1 the unmarked line through the gate directly (tell_woken, tag watch): pushed", len(pushes()) == 1 and pushes()[0][0] == U[F_B], pushes())
check("1 …the gate's verdict for it is none: it is of the kind that asks its mover to act (exempt), so no hold and no log line",
      telling.FRONT_TAG_KIND.get("watch") == "exempt" and telling.FRONT_HINT.result == ("", ""), (telling.FRONT_TAG_KIND.get("watch"), telling.FRONT_HINT.result))

# ================================================================ 2. an item that waits on his decision: marked, pushed
item(2, needs=["decision"], ask="Decide: a or b \u00b7 Recommend: a \u00b7 Stakes: none \u00b7 By: no date", subject="[home] waits on his decision")
rows = [("a2", {"id": "2", "subject": "[home] item 2", "metadata": {"project": "projects/echo", "needs": ["decision"]}}, "its wake came")]
x = watching_svc.watch_text(U[F_B], rows)
check("2 an item that waits on his decision reads marked for the front agent", x and x[1] == MARK, x)
reset(); watching_svc.watch_tell(U[F_B], rows); drain()
p = pushes()
check("2 …and the real delivery pushes it to the front agent, marked, once", len(p) == 1 and p[0][0] == U[F_B] and p[0][1].startswith(MARK + " [stackshot] ") and "is yours now" in p[0][1], p)
own = [("a1", {"id": "1", "subject": "[home] item 1", "metadata": {"project": "projects/echo", "next": f"{F_B}: ask him which one to keep"}}, "its wake came")]
reset(); watching_svc.watch_tell(U[F_B], own + rows); drain()
p = pushes()
check("2 a message listing his item and the agent's own is one push, marked (one of its items is his)", len(p) == 1 and p[0][1].startswith(MARK + " ") and "2 items are yours now" in p[0][1], p)

# ================================================================ 3. a background agent: told as before
item(3, wait_kind="time", hold=True, wake=day(-1), post_wake_mover=B_B, needs=[], project="projects/delta", subject="[home] the builder's")
reset(); woke = wakes_svc.wake_pass(); drain()
p = pushes()
check("3 a wait that ends on the project's builder is pushed to it, once, unmarked", "a3" in woke and len(p) == 1 and p[0][0] == U[B_B] and not p[0][1].startswith(MARK) and "is yours now" in p[0][1], p)
check("3 …nothing held for it, and the front agent is told nothing", held.count(U[B_B]) == 0 and held.count(U[F_B]) == 0 and not [x for x in p if x[0] == U[F_B]], p)
check("3 a background agent's message is never marked, even for an item that waits on a decision", watching_svc.watch_text(U[B_B], [("a2", {"id": "2", "subject": "s", "metadata": {"project": "projects/delta", "needs": ["decision"]}}, "w")])[1] == "", None)
item(4, wait_kind="time", hold=True, wake=day(-1), post_wake_mover=F_B, needs=[], project="projects/delta", subject="[home] the front agent's, with a builder")
reset(); woke = wakes_svc.wake_pass(); drain()
p = pushes()
check("3 a wait that ends on a front agent in a project with a builder passes to the builder: the builder is pushed, the front agent is not told",
      "a4" in woke and mt(4).get("mover") == B_B and len(p) == 1 and p[0][0] == U[B_B] and not p[0][1].startswith(MARK), (mt(4), p))

# ================================================================ 4. the contrast: a notice of a held kind to the same front agent in the same state is held, marked or not
NOTE = "[stackshot] a1 \"[home] item 1\" (projects/echo): a session wrote the item \u2192 https://stackshot.example.com/items/a1"
item(5, wait_kind="time", hold=True, wake=day(-1), post_wake_mover=F_B, needs=[], subject="[home] a progress notice's item")
for label, note in (("unmarked", NOTE), ("marked", MARK + " " + NOTE)):
    reset(); h0 = held.count(U[F_B])
    telling.tell_woken("a5", U[F_B], note, tag="owner"); drain()
    check(f"4 a progress notice, {label}, to the front agent while nobody is there: not pushed (the gate reads the kind, not the mark)", pushes() == [], pushes())
check("4 …so the watch notice in 1 was pushed because of its kind: the same gate, the same agent, the same state", telling.FRONT_TAG_KIND.get("owner") == "progress" and telling.FRONT_TAG_KIND.get("watch") == "exempt", None)

# ================================================================ 5. the delivery program does not read the mark
for f in ("push.py", "inbox.py"):
    src = (pathlib.Path(STACK) / "stackshot" / "fleet" / f).read_text(encoding="utf-8")
    check(f"5 stackshot/fleet/{f} has no test of the owner mark (nothing there reads `[for ...]`)", not re.search(r"\[for\b|for_owner|_owner_mark|FOR_OWNER", src), f)

# ================================================================ 6. the other notices a front agent hears for its own move: no mark, delivered the same, and his own words keep it
from stackshot.service import ladder as ladder_svc
FR = "projects/echo"
# 6a. a close by another session of an item the front agent moves and was asked to tell him about: one line, no mark, pushed (a close is delivered by its kind, here under his ask)
item(6, status="completed", mover=F_B, tell_him=[F_B], needs=[], subject="[home] closed by another session")
reset(); r6 = telling.tell_owner_close("a6", rd(6), SOLO, True, []); drain()
p = pushes()
check("6a a close by another session is pushed to the front agent that moves the item, once", len(p) == 1 and p[0][0] == U[F_B] and "closed by" in p[0][1], (r6, p))
check("6a …with no owner mark anywhere in it, a notice that opens with the server's own tag", p and MARK not in p[0][1] and p[0][1].startswith("[stackshot] "), p)
item(7, status="completed", mover=F_B, needs=[], subject="[home] closed, nobody asked")
reset(); telling.tell_owner_close("a7", rd(7), SOLO, True, []); drain()
check("6a the same close with no ask of his and nobody there is held, as it was with the mark: the gate reads the kind and the state, never the first line", pushes() == [] and telling.gate_result()[0] == "held", (pushes(), telling.gate_result()))
reset(); telling.tell_woken("a7", U[F_B], MARK + " [stackshot] a7 closed", tag="owner"); drain()
check("6a …and a close that carries the old mark is held exactly the same", pushes() == [], pushes())
# 6b. the ladder's notice to a -main agent about a silent background mover: no mark, pushed while nobody is there (the stall tag asks its agent to act)
item(8, mover=B_B, project="projects/delta", subject="[home] a silent mover's item")
reset(); ladder_svc.ladder_main_tell(F_B, [("a8", "a8 line")], {"a8": {"subject": "[home] item 8", "mover": B_B, "since": "Mon Nov 9th 02:00", "span": "4 hours", "told": ""}}); drain()
p = pushes()
check("6b the ladder's notice about a silent background mover is pushed to the -main agent, once, with nobody there for its pane", len(p) == 1 and p[0][0] == U[F_B] and "has had no write from its background mover" in p[0][1], p)
check("6b …unmarked, and it asks the agent to decide (the agent's move, nothing for the owner)", p and MARK not in p[0][1] and p[0][1].startswith("[stackshot] ") and "Decide whether it needs a nudge" in p[0][1], p)
check("6b …delivered because of its tag: stall is of the kind that asks the agent to act", telling.FRONT_TAG_KIND.get("stall") == "exempt" and telling.FRONT_TAG_KIND.get("ask") == "exempt", None)
# 6c. his own words keep the mark: his comment on GitHub and an item that waits on his decision are for him, the mover is told marked
item(9, mover=F_B, subject="[home] he commented")
reset(); told9 = telling.tell_comment("a9", rd(9), "please ship it on Friday"); drain()
p = pushes()
check("6c his comment on GitHub reaches the front agent that moves the item, marked: they are his own words", len(p) == 1 and p[0][0] == U[F_B] and p[0][1].startswith(MARK + " "), (told9, p))

print(f"\n{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
