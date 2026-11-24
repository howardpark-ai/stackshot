"""Scenario test for: the mark on a watcher's "is yours now" notice does not decide whether the notice is delivered — fixture data, no live store, no network, no server socket, no tmux.

A watched wait that ends on a session turns the item and tells that session in one line ("... is yours now ..."). A front agent used to get the mark ("[for <owner>]" on the first line) for an item whose open
step is its own, although the person has nothing to do there: the move is the agent's. Now the mark goes only on an item that waits on his decision (watching.watch_text). This suite drives the real wake pass
and the real delivery path (watching.watch_tell -> telling.tell_woken -> telling.front_gate -> the push command; only the push command's last hop, the program that writes into the pane, is replaced by a
recorder) and proves that dropping the mark changes nothing about who is told:

  1  a front agent that is the item's mover with a named step of its own (the wait ending on it in a project with no builder) is told the notice once and it starts its turn: pushed although nobody is there for its pane,
     unmarked (the item waits on no decision of his): the step is the agent's work (telling.tell_own_move named=True; before, the notice was progress and sat for hours)
  1b the same wake for an item whose step has no name, or is another session's, is a progress notice (the item waits on no decision of his): no turn, nothing pushed while the person is not there for its pane, the news on
     the item's board line; unmarked; the same text with the old mark on it is held exactly the same (the gate decides by the notice's kind, not by its first line); sent with its tag alone (no kind from its sender)
     it would be pushed, so what makes it progress is its sender (telling.tell_own_move)
  2  an item that waits on his decision (the mark stays) is pushed to the front agent too, marked
  3  a background agent is told as before: pushed once, unmarked, nothing held
  4  the contrast: a notice of the kind that is held (a progress notice) to the same front agent in the same state is held whether it carries the mark or not, so the gate does read
     the kind; the watch and stall tags are still of the kind that asks
  5  the delivery program does not read the mark (push.py and inbox.py name no `[for ...]` test)
  6  the other notices a front agent hears for its own move carry no mark either and are delivered as they were: a close by another session (pushed under his ask, held without it, marked or not),
     the ladder's notice about a silent background mover (a progress notice: held with nobody there; with his decision in it, pushed), the page-debt fallback to a front agent (the agent's own page update to write: pushed, unmarked); a notice that
     carries his own words (his comment) keeps the mark

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
TOLD = []      # every notice the server tells, as [session id, text], pushed or not: a front agent's own move is told as a progress notice (telling.tell_own_move), held while nobody is there
def _tell(gid, owner, note, tag="wake", result=None):
    TOLD.append([owner, note])
    th = _real_tell(gid, owner, note, tag)
    if th: THREADS.append(th)
    return th
telling.tell_woken = _tell
def drain():
    while THREADS: THREADS.pop(0).join(30)
def pushes(): return [json.loads(l) for l in PUSHLOG.read_text().splitlines()] if PUSHLOG.exists() else []
def reset():
    drain(); PUSHLOG.unlink(missing_ok=True); TOLD.clear()
day = lambda n: time.strftime("%Y-%m-%d", time.gmtime(now0 + n * DAY + ZONE_HOURS * 3600))
def board_lines(i): return (mt(i).get("front_quiet") or {}).get("log") or []

# nobody is present for any pane here (see the setup check). A notice of a held kind to a front agent is held in this state (4); a watch notice is not.
check("setup: the front agent is one for both projects, the builder is not", telling.front_keeper(F_B, "projects/echo")[0] and telling.front_keeper(F_B, "projects/delta")[0] and not telling.front_keeper(B_B, "projects/delta")[0], None)
check("setup: nobody is there for the front agent's pane", not telling.presence_here(U[F_B]), None)

# ================================================================ 1. the front agent's own named step is the item's work: a wake that hands it over starts its turn
item(1, wait_kind="time", hold=True, wake=day(-1), post_wake_mover=F_B, needs=[], next=f"{F_B}: ask him which one to keep", subject="[home] its own step")
reset(); woke = wakes_svc.wake_pass(); drain()
p, tl = pushes(), [t for t in TOLD if t[0] == U[F_B]]
check("1 the wake turns the item and the front agent keeps it (no builder in the project)", "a1" in woke and mt(1).get("mover") == F_B, (woke, mt(1)))
check("1 the real wake pass tells the front agent once, and the notice is pushed (a turn) although nobody is there for its pane: its own named step is the work (telling.tell_own_move named=True)", len(tl) == 1 and len(p) == 1 and p[0][0] == U[F_B] and "is yours now" in p[0][1], (tl, p))
check("1 …the notice is unmarked: no mark on the first line or anywhere in it (the item is not his), and it says whose move it is", tl and not tl[0][1].startswith(MARK) and MARK not in tl[0][1] and "is yours now" in tl[0][1] and tl[0][1].startswith("[stackshot] "), tl)
check("1 …it names the item and where to find it", tl and " a1 " in tl[0][1] and "/items/a1" in tl[0][1], tl)
check("1 …nothing held, no archived line and no board line for it: the gate let it through", held.count(U[F_B]) == 0 and board_lines(1) == [] and telling.FRONT_HINT.result == ("", ""), (held.count(U[F_B]), board_lines(1)))
check("1 …the same item whose step is the agent's by its ask alone (no named step) is a turn too", telling.own_move_kind(U[F_B], "a1", {"a1": {"status": "open", "metadata": {"next": "re-raise", "ask": f"{F_B}: which one"}}}, named=True) == "", None)

# ================================================================ 1b. no step of its own: the wake is progress, no turn (what the commit that made own-move notices turn-less meant)
item(21, wait_kind="time", hold=True, wake=day(-1), post_wake_mover=F_B, needs=[], next="ask him which one to keep", subject="[home] an unnamed step")
item(22, wait_kind="time", hold=True, wake=day(-1), post_wake_mover=F_B, needs=[], next=f"{SOLO}: ask him which one to keep", subject="[home] a step of another session")
reset(); woke = wakes_svc.wake_pass(); drain()
p, tl = pushes(), [t for t in TOLD if t[0] == U[F_B]]
check("1b the wake turns both items and the front agent keeps them", {"a21", "a22"} <= set(woke) and mt(21).get("mover") == F_B and mt(22).get("mover") == F_B, (woke, mt(21), mt(22)))
check("1b the front agent is told, and starts no turn of its own: nothing is pushed while nobody is there for its pane (a step with no name, a step of another session, the item waits on no decision of his)", len(tl) >= 1 and p == [], (tl, p))
check("1b …the notices are unmarked and say whose move it is", tl and all(not t[1].startswith(MARK) and MARK not in t[1] and "yours now" in t[1] for t in tl), tl)
check("1b …no held line for its next turn (nobody is there), and each item's board line carries the news", held.count(U[F_B]) == 0 and all(len(board_lines(i)) == 1 and "was not told" in board_lines(i)[0]["text"] for i in (21, 22)), (held.count(U[F_B]), board_lines(21), board_lines(22)))
text = next((t[1] for t in tl if " a21 " in t[1]), tl[0][1] if tl else "")
reset()
telling.tell_kind("progress", "a21", U[F_B], MARK + " " + text, tag="watch"); drain()
check("1b the same notice carrying the old mark is held exactly the same: nothing pushed (the gate reads the kind, not the first line)", pushes() == [], pushes())
reset()
telling.tell_woken("a21", U[F_B], text, tag="watch"); drain()
check("1b the same line through the gate with the tag alone (tell_woken, tag watch, no kind from its sender) is pushed: the tag's kind is exempt, and what makes an unnamed step's notice progress is its sender", len(pushes()) == 1 and pushes()[0][0] == U[F_B], pushes())
check("1b …the gate's verdict for it is none: no hold and no log line", telling.FRONT_TAG_KIND.get("watch") == "exempt" and telling.FRONT_HINT.result == ("", ""), (telling.FRONT_TAG_KIND.get("watch"), telling.FRONT_HINT.result))
reset(); watching_svc.watch_tell(U[F_B], [("a21", rd(21), "its wake came")]); drain()
check("1b watch_tell for an item whose step has no name is progress and held; with its step named for the agent it is pushed", pushes() == [], pushes())
reset(); watching_svc.watch_tell(U[F_B], [("a1", rd(1), "its wake came")]); drain()
check("1b …(named)", len(pushes()) == 1 and pushes()[0][0] == U[F_B], pushes())

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
check("4 …so the watch notice in 1 was held because its sender told it as progress: the same gate, the same agent, the same state; the tags themselves are as they were", telling.FRONT_TAG_KIND.get("owner") == "progress" and telling.FRONT_TAG_KIND.get("watch") == "exempt", None)

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
# 6b. the ladder's notice to a -main agent about a silent background mover: no mark; with nothing in it for the owner it is a progress notice (no turn while nobody is there), with his decision in it it is pushed
item(8, mover=B_B, project="projects/delta", subject="[home] a silent mover's item")
INFO = lambda g: {g: {"subject": "[home] item 8", "mover": B_B, "since": "Mon Nov 9th 02:00", "span": "4 hours", "told": ""}}
reset(); ladder_svc.ladder_main_tell(F_B, [("a8", "a8 line")], INFO("a8")); drain()
p, tl = pushes(), [t for t in TOLD if t[0] == U[F_B]]
check("6b the ladder's notice about a silent background mover is told to the -main agent, once, and starts no turn of its own: nothing pushed with nobody there for its pane", len(tl) == 1 and p == [] and "has had no write from its background mover" in tl[0][1], (tl, p))
check("6b …unmarked, and it asks the agent to decide (the agent's move, nothing for the owner)", tl and MARK not in tl[0][1] and tl[0][1].startswith("[stackshot] ") and "Decide whether it needs a nudge" in tl[0][1], tl)
item(11, mover=B_B, project="projects/delta", needs=["decision"], ask="Decide: a or b \u00b7 Recommend: a \u00b7 Stakes: none \u00b7 By: no date", subject="[home] a silent mover's item that waits on his decision")
reset(); ladder_svc.ladder_main_tell(F_B, [("a11", "a11 line")], INFO("a11")); drain()
p = pushes()
check("6b …with an item that waits on his decision in it the notice is pushed to the -main agent, once, with nobody there (the kind of its tag, stall, asks the agent to act)", len(p) == 1 and p[0][0] == U[F_B] and "has had no write from its background mover" in p[0][1], p)
check("6b …delivered because of its tag: stall is of the kind that asks the agent to act", telling.FRONT_TAG_KIND.get("stall") == "exempt" and telling.FRONT_TAG_KIND.get("ask") == "exempt", None)
# 6c. his own words keep the mark: his comment on GitHub and an item that waits on his decision are for him, the mover is told marked
item(9, mover=F_B, subject="[home] he commented")
reset(); told9 = telling.tell_comment("a9", rd(9), "please ship it on Friday"); drain()
p = pushes()
check("6c his comment on GitHub reaches the front agent that moves the item, marked: they are his own words", len(p) == 1 and p[0][0] == U[F_B] and p[0][1].startswith(MARK + " "), (told9, p))

# 6d. the page-debt fallback to a front agent: the page update is the agent's own to write and holds nothing for the owner, so it carries no mark, and it is pushed to the front agent all the same (its delivery reads no mark)
from stackshot.service import page_debt as pdebt_svc
item(10, mover=F_B, subject="[home] a page update owed")
def waited_pushes(n, secs=15):
    t = time.time() + secs
    while len(pushes()) < n and time.time() < t: time.sleep(0.1)
    return pushes()
reset(); to_d = pdebt_svc.page_debt_fallback("projects/echo", {SOLO: {"ts": time.time(), "item": "a10", "moved": True}}, [("a10", "changed (description)", SOLO)], "the call failed", time.time())
p = waited_pushes(1)
check("6d the page-debt fallback goes to the project's front -main agent and is pushed to it once", to_d == F_B and len(p) == 1 and p[0][0] in (F_B, U[F_B]) and "yours to write" in p[0][1], (to_d, p))
check("6d …with no owner mark anywhere in it, a notice that opens with the board's own tag", p and MARK not in p[0][1] and p[0][1].startswith("[board] 1 page update on projects/echo is yours to write"), p)
reset(); to_e = pdebt_svc.page_debt_fallback("projects/delta", {SOLO: {"ts": time.time(), "item": "a10", "moved": True}}, [("a10", "changed (description)", SOLO)], "the call failed", time.time())
p = waited_pushes(1)
check("6d …and to a builder, as before: unmarked, pushed once", to_e == B_B and len(p) == 1 and p[0][0] in (B_B, U[B_B]) and MARK not in p[0][1] and p[0][1].startswith("[board] 1 page update"), (to_e, p))

print(f"\n{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
