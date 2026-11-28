"""Scenario test for: a wait that ends on a front agent passes the item to the project's background agent — fixture data, no live store, no network, no server socket.

A front agent is a session the person talks to: a message marked for him starts its turn. A watched wait that ended on one used to start that turn marked for him, for an item that asked him nothing. Now the
wake moves the item (watching.watch_fire, the one place every watched wait turns an item):

  * the post-wake mover is a front agent and its project has a builder: the item's mover becomes the builder and the one session in needs, on every path (a wait on a date alone included, so the mover, needs,
    the notice and reminder recipients and the holder all name the same session), the builder is told unmarked, the front agent is not told at all, and the History line says the wait ended and who continues;
    this holds for every wait kind and cause (a time wait, an item wait, an anchor, an event, a list) and for a wait on a date alone that stored no mover;
  * the project has no builder (none at all, or only background agents with another mandate): the front agent keeps the item and is told as before, but without the mark a front agent takes, which a wake
    carries only for an item that waits on his decision;
  * a step only the front agent can take (the first open step or the ask opens with its name) keeps the item with it, told, and not marked: the move is the agent's, he has nothing to do (the notice is pushed to
    a front agent all the same, tests/watch_notice_delivery_scenario.py);
  * unchanged: a post-wake mover that is a background agent or a session no page lists, the person himself as the post-wake mover (a ready question, nobody told), a front agent that is the keeper of the
    item's own project, and a wake whose end is his decision (the mark stays).

    tests/run-suite wake_to_background        → exit 0 / 1"""
import json, os, re, sys, pathlib, time, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="wakebg-"); T = pathlib.Path(tmp)
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
for d in ("store/a", "store/g", "fleet/a", "state/demo", "brain/projects", "transcripts/-home-x"): (T / d).mkdir(parents=True)
F_A, B_A, F_B, F_C, B_C, SOLO, F_G, B_G = "home-delta-main", "home-delta-build", "home-echo-main", "home-foxtrot-main", "home-foxtrot-watch", "home-loner", "home-golf-main", "home-golf-build"
NAMES = (F_A, B_A, F_B, F_C, B_C, SOLO, F_G, B_G)
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
now0 = time.time()
DAY = 86400.0
ZONE_HOURS = 4      # the instance timezone pinned above (Asia/Dubai, UTC+4, no DST)
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
page = lambda **kw: {"title": "T", "name": "T", "org": "home", "tags": [], "type": "project", "session": "", "status": "active", "board": [], "board_open": 0, **kw}
(T / "store/projects.json").write_text(json.dumps({"pages": {
    "projects/delta": page(title="Delta", name="Delta", agents={F_A: "the front", B_A: "builds it"}, back_agents={B_A: "builds it"}),              # a front agent and a builder
    "projects/echo": page(title="Echo", name="Echo", agents={F_B: "the front"}),                                                                       # a front agent alone
    "projects/foxtrot": page(title="Foxtrot", name="Foxtrot", agents={F_C: "the front", B_C: "watches the clock"}, back_agents={B_C: "watches the clock"}),   # a background agent that is no builder
    "projects/golf": page(title="Golf", name="Golf", session=F_G, agents={F_G: "the front", B_G: "builds it"}, back_agents={B_G: "builds it"})}}))      # a builder, and a front agent that is the keeper of its own page
(T / "brain/projects/delta.md").write_text(f"---\ntitle: Delta\nagents:\n  {F_A}: the front\n  background:\n    {B_A}: builds it\n---\n\n# Delta\n")
(T / "brain/projects/echo.md").write_text(f"---\ntitle: Echo\nagents:\n  {F_B}: the front\n---\n\n# Echo\n")
(T / "brain/projects/foxtrot.md").write_text(f"---\ntitle: Foxtrot\nagents:\n  {F_C}: the front\n  background:\n    {B_C}: watches the clock\n---\n\n# Foxtrot\n")
(T / "brain/projects/golf.md").write_text(f"---\ntitle: Golf\nsession: {F_G}\nagents:\n  {F_G}: the front\n  background:\n    {B_G}: builds it\n---\n\n# Golf\n")
(T / "store/next-id").write_text("900"); (T / "store/anchors.json").write_text("{}")
DESC = "- A thing\n- It lives here\n- Done when done"
def item(i, status="open", su=None, project="projects/delta", **meta):
    su = now0 - 10 * DAY if su is None else su
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": DESC, "status": status, "updated": su, "state_updated": su, "confirmed": su,
                                                      "metadata": {"owner": SOLO, "project": project, "next": f"{B_A}: do the thing", **meta}}))
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
def mt(i): return rd(i)["metadata"]
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
sys.path.insert(0, STACK); logging.disable(logging.INFO)
from stackshot.web import server; from stackshot.service import writes; from stackshot.model import model
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
from stackshot.web.tools import anchors as _wt_anchors
from stackshot.web.tools import route as _wt_route
from stackshot.web.tools import text as _wt_text
from stackshot.service import wakes as wakes_svc, watching as watching_svc
from stackshot.service import telling
from stackshot.anchors import anchors as _anc
from stackshot.core import config as _cfg
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._owing_note = lambda debtor: ""
SENT: list[tuple[str, str, str, str]] = []
telling.tell_woken = lambda gid, owner, note, tag="wake": SENT.append((gid, owner, note, tag))
NOTES: list[tuple[str, str]] = []                      # the History line of every save the server makes on its own (writes.save's note)
_save = writes.save
def _spy(gid, item_, *a, **kw):
    NOTES.append((gid, kw.get("note", "")))
    return _save(gid, item_, *a, **kw)
writes.save = _spy
ST = T / "state/waiting.json"
ST.parent.mkdir(parents=True, exist_ok=True); ST.write_text(json.dumps({"baseline": now0 - 56 * DAY, "seen": {}, "reported": []}))
day = lambda n: time.strftime("%Y-%m-%d", time.gmtime(now0 + n * DAY + ZONE_HOURS * 3600))
MARK = _wt_text._FOR_OWNER
CFG = _cfg.CFG.setdefault("model", {})
CFG.update(guards=False, pause=False)
def reset(): SENT.clear(); NOTES.clear()
def to(sid): return [x for x in SENT if x[1] == sid]
def notes_of(g): return [n for gid, n in NOTES if gid == g]
def told(g): return [x[1] for x in SENT if g in x[0].split(",")]      # the recipients of the message that names item g (a batch names several)

# the lookups the rule stands on
check("setup: the sessions are the roles the rule reads (a front agent is one for its project, the builder and the loner are not)",
      telling.front_keeper(F_A, "projects/delta")[0] and telling.front_keeper(F_B, "projects/echo")[0] and telling.front_keeper(F_C, "projects/foxtrot")[0]
      and not telling.front_keeper(B_A, "projects/delta")[0] and not telling.front_keeper(SOLO, "projects/delta")[0], None)
check("setup: the project's builder is the one the hand-off machinery names (a builder; a background agent that is no builder is none; none)",
      _anc.builder_of("projects/delta") == [B_A] and _anc.builder_of("projects/foxtrot") == [] and _anc.builder_of("projects/echo") == [] and _anc.background_agent("projects/foxtrot") == B_C, None)

# ================================================================ 1. a time wait ends on a front agent, the project has a background agent
item(1, wait_kind="time", hold=True, wake=day(-1), mover=F_A, needs=[], subject="[home] time wait")
reset()
woke = wakes_svc.wake_pass()
m = mt(1)
check("1 the wake turns the item alive, with the background agent as its mover and the only one in needs", "a1" in woke and m.get("mover") == B_A and m.get("needs") == [B_A]
      and "wait_kind" not in m and "wake" not in m and "hold" not in m, m)
check("1 …the arrival on record names the background agent", m.get("woke", {}).get("to") == B_A and m["woke"].get("what") == f"its wake {day(-1)} came", m.get("woke"))
mod = model.derive({**rd(1), "gid": "a1"}) if hasattr(model, "derive") else None
check("1 …the model reads it as alive with that mover", mod is None or (mod.state == "alive" and mod.mover == B_A), mod)
check("1 the background agent is told once, in the watchers' line, with no mark, and learns whose wait it was",
      len(SENT) == 1 and SENT[0][1] == U[B_A] and SENT[0][3] == "watch" and not SENT[0][2].startswith(MARK) and MARK not in SENT[0][2] and "is yours now" in SENT[0][2]
      and F_A in SENT[0][2] and "front agent" in SENT[0][2] and "\n" not in SENT[0][2], SENT)
check("1 the front agent is told nothing", not to(U[F_A]) and not to(F_A), SENT)
check("1 the History line says the wait ended and who continues", len(notes_of("a1")) == 1 and notes_of("a1")[0].startswith("woke: its wake") and f"→ {B_A}" in notes_of("a1")[0] and F_A in notes_of("a1")[0]
      and "front agent" in notes_of("a1")[0] and "not told" in notes_of("a1")[0], notes_of("a1"))
ho = mt(1).get("handoff") or {}
check("1 the hand-off record follows the new mover (the save's own rule: a record from the server to the background agent)", ho.get("to") == B_A, ho)
reset(); wakes_svc.wake_pass()
check("1 a second pass tells nobody and moves nothing", not SENT and mt(1).get("mover") == B_A, SENT)

# ================================================================ 2. an item wait ends the same way, in another kind of wait
item(2, wait_kind="item", after=["a3"], mover=F_A, ask_by=day(9), needs=[], subject="[home] item wait")
item(3, subject="[home] the blocker")
it = rd(3); it["status"] = "completed"; it["metadata"].update(outcome="done", reason="r"); (T / "store/a/3.json").write_text(json.dumps(it))
reset(); wakes_svc.release_after("a3", "done", "", SOLO)
m = mt(2)
check("2 an item wait whose last `after` item closed passes to the background agent too", m.get("mover") == B_A and m.get("needs") == [B_A] and "wait_kind" not in m and "after" not in m, m)
check("2 …told once, unmarked; the front agent not at all", len([x for x in SENT if "a2" in x[0]]) == 1 and to(U[B_A]) and not to(U[F_A]) and not any(x[2].startswith(MARK) for x in SENT), SENT)

# ================================================================ 3. one pass, several items for the front agent: one message to the background agent
item(4, wait_kind="time", hold=True, wake=day(-1), mover=F_A, needs=[], subject="[home] batch four")
item(5, wait_kind="time", hold=True, wake=day(-1), mover=F_A, needs=[], subject="[home] batch five")
reset(); wakes_svc.wake_pass()
check("3 two items woken in one pass for a front agent reach the background agent as one message, no mark, and nothing goes to the front agent",
      len(SENT) == 1 and SENT[0][1] == U[B_A] and "2 items are yours now" in SENT[0][2] and "a4:" in SENT[0][2] and "a5:" in SENT[0][2] and not SENT[0][2].startswith(MARK), SENT)

# ================================================================ 4. a wait on a date alone, no stored mover: the front agent is the fallback or named in needs
item(6, until=day(-1), needs=["external"], mover=F_A, subject="[home] date alone")
reset(); woke = wakes_svc.wake_pass()
m = mt(6)
check("4 a wait on a date alone that ends on a front agent passes to the project's builder", "a6" in woke and m.get("mover") == B_A and "until" not in m, m)
check("4 …told unmarked, the front agent not told", len(SENT) == 1 and SENT[0][1] == U[B_A] and not SENT[0][2].startswith(MARK) and not to(U[F_A]), SENT)
item(14, until=day(-1), needs=[F_A], subject="[home] date alone, front in needs")
reset(); woke = wakes_svc.wake_pass()
m = mt(14)
check("4 …a front agent in needs (how a front agent parks its own item) is replaced there too: the builder is the mover and the one session in needs", "a14" in woke and m.get("mover") == B_A and m.get("needs") == [B_A] and "until" not in m, m)
check("4 …so every reader of who has it agrees: the holder, the notice and the reminder go to the builder, none to the front agent",
      telling.holder(rd(14)) in (B_A, U[B_A]) and [x for x, _w in telling.notice_to(mt(14))] == [U[B_A]] and [x for x, _w in wakes_svc.reminder_to(mt(14))] == [U[B_A]], (telling.holder(rd(14)), telling.notice_to(mt(14))))
check("4 …and it is told once, to the builder", len(SENT) == 1 and SENT[0][1] == U[B_A] and not to(U[F_A]), SENT)

# a wait on a date alone that goes back to others (`external` in needs) stays that way: only its mover changes, whichever way the front agent holds it; its siblings (no stored mover, the builder stored) are as before
def asof(i): return model.derive({**rd(i), "gid": f"a{i}"})
mod6 = asof(6)
check("4 …with `external` in needs and a stored front mover the item keeps `external` and stays a wait on others, the builder as its mover", mt(6).get("needs") == ["external"] and mod6.state == "waiting", (mt(6), mod6.state))
item(31, until=day(-1), needs=["external"], subject="[home] external, no stored mover")
item(32, until=day(-1), needs=["external"], mover=B_A, subject="[home] external, the builder stored")
item(33, until=day(-1), needs=["external", F_A], subject="[home] external beside the front agent")
reset(); wakes_svc.wake_pass()
check("4 …its siblings: no stored mover keeps `external` and writes no mover; the builder stored as mover keeps `external` and is told", mt(31).get("needs") == ["external"] and not mt(31).get("mover") and asof(31).state == "waiting"
      and mt(32).get("needs") == ["external"] and mt(32).get("mover") == B_A and asof(32).state == "waiting" and any(x[1] == U[B_A] and "a32" in x[0] for x in SENT), (mt(31), mt(32), SENT))
check("4 …`external` beside the front agent in needs keeps `external` too, the builder is the mover and the front agent is not told", "external" in mt(33).get("needs") and mt(33).get("mover") == B_A and not to(U[F_A]) and any(x[1] == U[B_A] and "a33" in x[0] for x in SENT), (mt(33), SENT))

# ================================================================ 5. the project has no background agent: today's path, without the mark
item(7, wait_kind="time", hold=True, wake=day(-1), mover=F_B, needs=[], project="projects/echo", subject="[home] front only")
reset(); woke = wakes_svc.wake_pass()
m = mt(7)
check("5 no background agent: the front agent keeps the item as its mover", "a7" in woke and m.get("mover") == F_B and m.get("needs") == [F_B] and m.get("woke", {}).get("to") == F_B, m)
check("5 …it is told once, in the watchers' line, and the line carries no mark for him", len(SENT) == 1 and SENT[0][1] == U[F_B] and SENT[0][3] == "watch" and "is yours now" in SENT[0][2]
      and not SENT[0][2].startswith(MARK) and MARK not in SENT[0][2], SENT)
check("5 …and the History line is the plain one", notes_of("a7") == [f"woke: its wake {day(-1)} came → {F_B}"], notes_of("a7"))
item(8, wait_kind="time", hold=True, wake=day(-1), mover=F_B, needs=[], project="projects/echo", subject="[home] front only two")
item(9, wait_kind="time", hold=True, wake=day(-1), mover=F_B, needs=[], project="projects/echo", subject="[home] front only three")
reset(); wakes_svc.wake_pass()
check("5 several items for the front agent of a project with no background agent are one message, unmarked", len(SENT) == 1 and SENT[0][1] == U[F_B] and "2 items are yours now" in SENT[0][2] and not SENT[0][2].startswith(MARK), SENT)

item(15, wait_kind="time", hold=True, wake=day(-1), mover=F_C, needs=[], project="projects/foxtrot", subject="[home] a background agent that is no builder")
item(16, until=day(-1), needs=[F_C], project="projects/foxtrot", subject="[home] date alone, no builder")
reset(); wakes_svc.wake_pass()
check("5 a project whose only background agent is no builder (its mandate is another) has no builder: the front agent keeps a time wait's item, told, unmarked",
      mt(15).get("mover") == F_C and mt(15).get("needs") == [F_C] and notes_of("a15") == [f"woke: its wake {day(-1)} came → {F_C}"]
      and [x for x in SENT if "a15" in x[0] and x[1] == U[F_C] and not x[2].startswith(MARK)] and not to(U[B_C]), (mt(15), SENT))
check("5 …and a wait on a date alone there stays as stored (needs the front agent, no mover written), the background agent not told", mt(16).get("needs") == [F_C]
      and not mt(16).get("mover") and not to(U[B_C]) and "until" not in mt(16), mt(16))

# ================================================================ 6. unchanged: a background agent or a session no page lists as the post-wake mover
item(10, wait_kind="time", hold=True, wake=day(-1), mover=B_A, needs=[], subject="[home] builder mover")
item(11, wait_kind="time", hold=True, wake=day(-1), mover=SOLO, needs=[], subject="[home] loner mover")
reset(); wakes_svc.wake_pass()
check("6 a background agent as the post-wake mover is told as before: mover as set, no mark, the plain line and History",
      mt(10).get("mover") == B_A and [x for x in SENT if "a10" in x[0]] and all("front agent" not in x[2] and not x[2].startswith(MARK) for x in SENT) and notes_of("a10") == [f"woke: its wake {day(-1)} came → {B_A}"], (SENT, notes_of("a10")))
check("6 a session no page lists is not a front agent: it keeps the item", mt(11).get("mover") == SOLO and any(x[1] == U[SOLO] and "a11" in x[0] for x in SENT) and notes_of("a11") == [f"woke: its wake {day(-1)} came → {SOLO}"], (SENT, notes_of("a11")))
check("6 …so the background agent was told of its own item only", not to(U[F_A]), SENT)

# ================================================================ 7. unchanged: the person himself as the post-wake mover (a ready question, nobody told)
item(12, wait_kind="time", hold=True, wake=day(-1), mover=model.owner_display(), needs=[], subject="[home] his item")
reset(); wakes_svc.wake_pass()
m = mt(12)
check("7 the person as the post-wake mover: the item asks him, no session is told", m.get("needs") == ["decision"] and not m.get("mover") and not SENT, (m, SENT))

# ================================================================ 8. the mark stays for an item that waits on his decision (the message text rule, on the rows the watchers collect)
def row(i, **meta): return (f"a{i}", {"id": str(i), "subject": f"[home] item {i}", "metadata": {"project": "projects/echo", **meta}}, "its wake came")
dec = watching_svc.watch_text(U[F_B], [row(20, needs=["decision"])])
check("8 a front agent told of an item that waits on his decision gets his mark", dec and dec[1] == MARK, dec)
plain = watching_svc.watch_text(U[F_B], [row(21, needs=[F_B])])
check("8 …and one told of an item that asks him nothing does not", plain and plain[1] == "", plain)
mixed = watching_svc.watch_text(U[F_B], [row(21, needs=[F_B]), row(22, needs=["decision"])])
check("8 …a message listing both is marked (one of its items is his)", mixed and mixed[1] == MARK and mixed[2] == ["a21", "a22"], mixed)
check("8 a background agent's message is never marked", watching_svc.watch_text(U[B_A], [row(23, needs=["decision"], project="projects/delta")])[1] == "", None)
item(13, until=day(-1), needs=["decision"], ask="Decide: a or b · Recommend: a · Stakes: none · By: no date", project="projects/foxtrot", subject="[home] a decision parked to a date")
reset(); woke = wakes_svc.wake_pass()
check("8 a wait whose end is his decision is his, as before: the item asks him, and nothing passes to the background agent or goes to the front agent",
      "a13" in woke and mt(13).get("needs") == ["decision"] and not mt(13).get("mover") and not SENT, (mt(13), SENT))

# ================================================================ 9. a step only the front agent can take keeps the item with it
item(17, wait_kind="time", hold=True, wake=day(-1), mover=F_A, needs=[], next=f"{F_A}: ask him which one to keep", subject="[home] its own step")
reset(); wakes_svc.wake_pass()
m = mt(17)
check("9 an open step that opens with the front agent's name keeps the item with it, told", m.get("mover") == F_A and m.get("needs") == [F_A] and len(SENT) == 1 and SENT[0][1] == U[F_A] and not to(U[B_A]), (m, SENT))
check("9 …unmarked (the move is its own, the person has nothing to do), and the History line is the plain one", not SENT[0][2].startswith(MARK) and MARK not in SENT[0][2] and "is yours now" in SENT[0][2] and notes_of("a17") == [f"woke: its wake {day(-1)} came → {F_A}"], (SENT, notes_of("a17")))
item(18, until=day(-1), needs=[F_A], next=f"{F_A}: ask him which one to keep", subject="[home] its own step, date alone")
reset(); wakes_svc.wake_pass()
check("9 …also a wait on a date alone: nothing passes, needs and mover stay as stored", mt(18).get("needs") == [F_A] and not mt(18).get("mover") and len(SENT) == 1 and SENT[0][1] == U[F_A] and not SENT[0][2].startswith(MARK) and not to(U[B_A]), (mt(18), SENT))
item(19, wait_kind="time", hold=True, wake=day(-1), mover=F_A, needs=[], ask=f"{F_A}: which one do you keep?", subject="[home] its own ask")
reset(); wakes_svc.wake_pass()
check("9 …an ask that opens with the front agent's name does the same", mt(19).get("mover") == F_A and len(SENT) == 1 and SENT[0][1] == U[F_A] and not to(U[B_A]), (mt(19), SENT))
item(20, wait_kind="time", hold=True, wake=day(-1), mover=F_A, needs=[], next=f"{B_A}: do the thing\n{F_A}: then review it", subject="[home] its later step")
reset(); wakes_svc.wake_pass()
check("9 …but a step of the front agent that comes after the builder's is not the one the wake leads to: the item passes", mt(20).get("mover") == B_A and to(U[B_A]) and not to(U[F_A]), (mt(20), SENT))
item(21, wait_kind="time", hold=True, wake=day(-1), mover=F_A, needs=[], next="- a sub step\n- another", subject="[home] bare steps")
reset(); wakes_svc.wake_pass()
check("9 …and steps that name nobody are nobody's: the item passes", mt(21).get("mover") == B_A and to(U[B_A]) and not to(U[F_A]), (mt(21), SENT))

item(34, wait_kind="time", hold=True, wake=day(-1), mover=F_A, needs=[], next=f"- a sub step\n{F_A}: ask him which one to keep", subject="[home] bare first")
item(35, wait_kind="time", hold=True, wake=day(-1), mover=F_A, needs=[], next=f"check the CI\n{F_A}: review it", subject="[home] plain line first")
item(36, wait_kind="time", hold=True, wake=day(-1), mover=F_A, needs=[], next=f"{B_A}: do the thing", steps=[{"text": f"{F_A}: an old one", "status": "done", "by": B_A, "at": now0 - DAY}], subject="[home] a done step of its own")
item(37, wait_kind="time", hold=True, wake=day(-1), mover=U[F_A], needs=[], next=f"{F_A}: ask him which one to keep", subject="[home] its id, the step by name")
item(38, wait_kind="time", hold=True, wake=day(-1), mover=F_A, needs=[], next=f"{F_A.upper()}: ask him which one to keep", subject="[home] its name in capitals")
reset(); wakes_svc.wake_pass()
check("9 …a bare line before the front agent's step is skipped, and so is a line with no `<name>:` opener: the front agent's step is the first that names someone, the item stays",
      mt(34).get("mover") == F_A and mt(35).get("mover") == F_A and told("a34") == [U[F_A]] and told("a35") == [U[F_A]], (mt(34), mt(35), SENT))
check("9 …a step of the front agent that is already done is not an open step: the item passes", mt(36).get("mover") == B_A and told("a36") == [U[B_A]], (mt(36), SENT))
check("9 …the front agent held by its id and named by its name in the step is one session: the item stays", mt(37).get("mover") in (F_A, U[F_A]) and told("a37") == [U[F_A]], (mt(37), SENT))
check("9 …a name in another letter case is the same session: the item stays", mt(38).get("mover") == F_A and told("a38") == [U[F_A]], (mt(38), SENT))

# ================================================================ 10. the keeper of the item's own project is no front agent for it: it keeps the item, told as before (no pass, no mark)
item(22, wait_kind="time", hold=True, wake=day(-1), mover=F_G, needs=[], project="projects/golf", subject="[home] the keeper's own")
reset(); wakes_svc.wake_pass()
check("10 the keeper of the item's own project keeps it although the project has a builder: mover and needs the keeper, told once, unmarked, the builder not told",
      mt(22).get("mover") == F_G and mt(22).get("needs") == [F_G] and len(SENT) == 1 and SENT[0][1] == U[F_G] and not SENT[0][2].startswith(MARK) and not to(U[B_G]) and notes_of("a22") == [f"woke: its wake {day(-1)} came → {F_G}"], (mt(22), SENT, notes_of("a22")))
item(23, wait_kind="time", hold=True, wake=day(-1), mover=F_G, needs=[], project="projects/delta", subject="[home] the same agent, another project's item")
reset(); wakes_svc.wake_pass()
check("10 …but the same agent on another project's item is a front agent there: the item passes to that project's builder", mt(23).get("mover") == B_A and to(U[B_A]) and not to(U[F_G]), (mt(23), SENT))

# ================================================================ 11. every cause that ends a wait ends the same way (anchor, event, list, relay line, the backstops)
AURL = "https://github.com/o/r/pull/5"
def fire(i, cause, detail=None, **kw):
    item(i, mover=F_A, needs=[], subject=f"[home] {cause} {i}", **kw)
    out: dict = {}; reset()
    ok = watching_svc.watch_fire(f"a{i}", cause, now0, out, detail)
    return ok, out
for i, cause, kw in ((24, "anchor", dict(wait_kind="anchor", wait_anchor=AURL, ask_by=day(5))), (25, "backstop", dict(wait_kind="anchor", wait_anchor=AURL, ask_by=day(-1))),
                     (26, "event", dict(wait_kind="event", wait_event="recycle", ask_by=day(5))), (27, "backstop", dict(wait_kind="event", wait_event="recycle", ask_by=day(-1))),
                     (28, "backstop", dict(wait_kind="item", after=["a3"], hold=True, ask_by=day(-1))),
                     (29, "relay", dict(wait_kind="list", hold=True, wait_mode="any", until=day(9), waits=[{"kind": "time", "until": day(3)}, {"kind": "relay", "event": "the lease"}], watch={"set_at": now0 - 3600})),
                     (30, "time", dict(wait_kind="list", hold=True, wait_mode="any", until=day(-1), waits=[{"kind": "time", "until": day(-1)}, {"kind": "item", "after": "a3"}], watch={"set_at": now0 - 3600}))):
    ok, out = fire(i, cause, {"what": "the event came"} if cause == "event" else None, **kw)
    m = mt(i)
    check(f"11 {kw['wait_kind']} wait, cause {cause}: the item passes to the builder (mover and needs), the front agent is told nothing, the builder is, unmarked",
          ok and m.get("mover") == B_A and m.get("needs") == [B_A] and list(out) == [U[B_A]]
          and any("front agent" in n and f"→ {B_A}" in n for n in notes_of(f"a{i}")), (ok, m, out, notes_of(f"a{i}")))

# ================================================================ 12. one message lists items of two projects for one recipient: each row reads the recipient by its own project
# F_G keeps projects/golf (a front agent of no other kind there) and is a front agent of projects/delta, which has a builder
def own_step_row(i): return row(i, project="projects/delta", next=f"{F_G}: ask him which one to keep")
def decision_row(i): return row(i, project="projects/delta", needs=["decision"])
def golf_row(i): return row(i, project="projects/golf")
both = watching_svc.watch_text(U[F_G], [golf_row(60), decision_row(61)])
rev = watching_svc.watch_text(U[F_G], [decision_row(61), golf_row(60)])
check("12 a batch of the keeper's own item first and another project's item that waits on his decision second is marked (the second row is his)", both and both[1] == MARK, both)
check("12 …and with the rows the other way round it is marked too", rev and rev[1] == MARK, rev)
check("12 …a step of the agent's own on another project's item is its move, not his: a batch with it is not marked, in either order",
      watching_svc.watch_text(U[F_G], [golf_row(60), own_step_row(61)])[1] == "" and watching_svc.watch_text(U[F_G], [own_step_row(61), golf_row(60)])[1] == "", None)
check("12 …a batch of the keeper's own item alone is not marked", watching_svc.watch_text(U[F_G], [golf_row(60), golf_row(62)])[1] == "", None)
for first, second, ids in (("golf", "delta", (39, 40)), ("delta", "golf", (41, 42))):
    for i, which in zip(ids, (first, second)):
        if which == "golf": item(i, wait_kind="time", hold=True, wake=day(-1), mover=F_G, needs=[], project="projects/golf", subject=f"[home] the keeper's own {i}")
        else: item(i, wait_kind="time", hold=True, wake=day(-1), mover=F_G, needs=[], project="projects/delta", next=f"{F_G}: ask him which one to keep", subject=f"[home] another project's, its own step {i}")
    reset(); wakes_svc.wake_pass()
    msgs = to(U[F_G])
    check(f"12 end to end, the {first} item then the {second} item: one message to the recipient, naming both, and it carries no mark, in either order (each is the agent's own move)",
          len(msgs) == 1 and all(f"a{i}" in msgs[0][0].split(",") for i in ids) and not msgs[0][2].startswith(MARK) and MARK not in msgs[0][2] and not to(U[B_A]) and mt(ids[0]).get("mover") == F_G and mt(ids[1]).get("mover") == F_G, (msgs, [mt(i).get("mover") for i in ids]))

# ================================================================ 13. a standalone relay wait: the person's later answer hands the item on the same way a wake does
from stackshot.service import answer as answer_svc
def relay(i, **kw):
    item(i, wait_kind="relay", wait_event="the parcel", ask_by=day(-1), mover=F_A, needs=[], subject=f"[home] relay {i}", **kw)
    reset(); wakes_svc.wake_pass()
for i, how in ((43, "arrived"), (44, "words")):
    relay(i)
    check(f"13 {how}: the ask-by day asks the person and tells nobody, the front agent is kept as the one after the wait", not SENT and mt(i).get("then") == F_A and "decision" in (mt(i).get("needs") or []), (mt(i), SENT))
    reset()
    out = answer_svc._answer(f"a{i}", "arrived", "", "answer") if how == "arrived" else answer_svc._answer(f"a{i}", "", "it came yesterday, thanks", "answer")
    m = mt(i)
    check(f"13 {how}: his answer passes the item to the project's builder (mover and needs), only the builder is told, unmarked", out == "decision" and m.get("mover") == B_A and m.get("needs") == [B_A]
          and told(f"a{i}") == [U[B_A]] and not any(x[2].startswith(MARK) for x in SENT), (out, m, SENT))
    check(f"13 {how}: …the History line says the front agent is not told", any("front agent" in n and f"→ {B_A}" in n for n in notes_of(f"a{i}")), notes_of(f"a{i}"))
for i, how in ((45, "arrived"), (46, "words")):
    relay(i, next=f"{F_A}: ask him which one to keep")
    reset()
    out = answer_svc._answer(f"a{i}", "arrived", "", "answer") if how == "arrived" else answer_svc._answer(f"a{i}", "", "it came yesterday, thanks", "answer")
    m = mt(i)
    check(f"13 {how}, a step of the front agent's own: the item stays with it, the builder is not told", m.get("mover") == F_A and m.get("needs") == [F_A] and told(f"a{i}") == [U[F_A]] and not told(f"a{i}").count(U[B_A]), (out, m, SENT))

print(f"\n{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
