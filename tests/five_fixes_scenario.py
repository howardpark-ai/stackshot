"""Scenario test for the five misshaped writes the server fixes with a default instead of refusing, and tells the writer how — fixture data, the tools called in-process, no live store, no network.

Each of these was a refusal because it has two reasonable fixes; the writer's choice is now the default below, the reply carries one plain line saying what was changed, the call log counts it under
fixes (the weekly report's "corrected by the server instead of refused"), and the History gets no line of its own (nothing the writer wrote is lost):

  1  step-kept     an update whose next no longer lists an open step of the writer's, with no done/dropped/reword for it: the step stays open, its line carried over unchanged into next
  2  subject-cut   a subject over [subject] max_length: cut at the last whole word that fits, ` …` after it, the whole counted in the limit (a create and an update)
  3  work-cut      a status line (work) over 40 characters: cut the same way
  4  ask-by-day    an ask-by day given with a time of day (ask_by, until or wake on a relay or event wait): the day is kept, the time dropped
  5  description-url  a session's bare http(s) address in a description: written as a link to itself, [address](address)

and what stays as it was: a write that was fine is stored byte for byte (and no fix is counted), the refusals that remain (a line rewritten with words added, a subject or status line with no whole word
that fits, a subject with no scope prefix, a bare address in next, a script's bare address left as written), each fix is one counted kind in the call log and the weekly report, a fix does not invite a
resend, and nothing is added to the item's History.

    tests/run-suite five_fixes        -> exit 0 / 1"""
import asyncio, contextlib, datetime as dt, io, json, logging, os, pathlib, re, sys, time, types
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="fivefixestest-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store (session links off)
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/s1", "brain/projects", "brain/infra"): (T / d).mkdir(parents=True)
NAMES = ("falcon-main", "home-other")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
(T / "store/next-id").write_text("100"); (T / "store/anchors.json").write_text("{}")
def page(rel, front):
    q = T / "brain" / rel; q.parent.mkdir(parents=True, exist_ok=True); q.write_text("---\n" + front + "\n---\n\n# x\n", encoding="utf-8")
page("projects/example.md", "type: project\ntitle: Stackshot\ndisplay-name: falcon\nagents:\n  falcon-main: builds it\nstatus: active")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))

from stackshot.projects import pages as p
p.cmd_registry(quiet=True)
from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route
from stackshot.service import update as _update_svc
from stackshot.service import store as _service_store
from stackshot.service import gates as G
from stackshot.core import config as _cfg
from stackshot.core import call_log as CL
from stackshot.tools import refusal_report as RR
from stackshot.web import middleware as _wmw
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
from stackshot.model import ids as _model_ids
from stackshot.model import bullet_text as BT
from stackshot.model import field_gates as _fg
from stackshot.model import steps as S
from stackshot.model import work as WK
from stackshot.waits import waiting as W
from stackshot.web.tools import create as _wt_create
from stackshot.web.tools import update as _wt_update
from fastmcp.exceptions import ToolError
_cfg.CFG.setdefault("model", {})["guards"] = False      # fixture owners the fleet does not know; the write guards have their own suite
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._refuse_if_owing = lambda debtor: None

MAIN = "falcon-main"; OTHER = "home-other"; STK = "projects/example"
DESC = "- Goal: A thing\n- It lives here\n- Done when done"
SUBJ_MAX = int(_cfg.CFG["subject"]["max_length"]); assert SUBJ_MAX == 80, SUBJ_MAX
NOW = time.time()
def item(i, next_="falcon-main: build it\nfalcon-main: test it", subject="[home] a thing", desc=DESC, **meta):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": subject, "description": desc, "status": "open", "updated": NOW - 3600, "state_updated": NOW - 3600, "confirmed": NOW - 3600,
                                                     "metadata": {"owner": U[MAIN], "project": STK, "needs": [MAIN], "next": next_, **meta}}))
def digits(i): return re.sub(r"\D", "", str(i))
def rd(i):
    """a seeded item by its number, or a created one by the gid its reply names"""
    if i == "" or i is None:
        return {"subject": "", "description": "", "metadata": {}}          # a refused create has no gid: the check that reads it then fails with its message, no crash
    return _service_store._load(i) if isinstance(i, str) and not i.isdigit() else json.loads((T / f"store/a/{i}.json").read_text())
def mt(i): return rd(i)["metadata"]
def fx(fn):
    """(the result or the ToolError, [(kind, note)] the call made)"""
    tok = CL.begin()
    try: res = fn()
    except ToolError as e: res = e
    finally: made = CL.end(tok)
    return res, made
kinds = lambda made: [k for k, _ in made]
def upd(i, **kw): return fx(lambda: _wt_update.stackshot_update(f"a{i}", sender=kw.pop("sender", MAIN), **kw))          # a session's write
def script(i, **kw): return fx(lambda: _update_svc._update(f"a{i}", sender=MAIN, **kw))                                  # a script's write (not the tool's own call)
def create(subject="[home] a thing", desc=DESC, **kw):
    kw.setdefault("next", f"{MAIN}: carry on")
    return fx(lambda: _wt_create.stackshot_create(subject=subject, description=desc, project=STK, owner=MAIN, **kw))
def gid_of(res): return _model_ids._norm_id(res.split()[1]) if isinstance(res, str) else ""
def subj(g): return rd(g)["subject"] if g else ""          # a refused create has no gid: the check then fails with its message, no crash
def num(g): return re.sub(r"\D", "", g)
def noise(i):
    """the History lines (metadata.stall.log) of the item that speak of one of the five fixes: none may"""
    log = [x.get("text") or "" for x in ((rd(i).get("metadata") or {}).get("stall") or {}).get("log") or []]
    return [t for t in log if re.search(r"step-kept|subject-cut|work-cut|ask-by-day|description-url|kept open|cut at|time of day|link to itself|dropped the time|carried", t)]
def steps_of(i): return [(x["status"], S.first_line(x["text"])) for x in S.view(mt(i))]

# ================================================================ 1. a step left out of next stays open
item(1)
res, made = upd(1, next="falcon-main: test it")
check("1 a next that leaves out an open step of the writer's, with no mark, goes through", not isinstance(res, ToolError), res)
check("1 …the step stays open, as written, back at its place: next lists both lines as before", mt(1)["next"] == "falcon-main: build it\nfalcon-main: test it", mt(1))
check("1 …the checklist keeps both steps open, in order", steps_of(1) == [("open", "falcon-main: build it"), ("open", "falcon-main: test it")], steps_of(1))
check("1 …one step-kept fix names the step and its position and how to end it", kinds(made) == ["step-kept"] and "1. falcon-main: build it" in made[0][1] and "done=[n]" in made[0][1] and "dropped=[n]" in made[0][1], made)
check("1 …and the History has no line of its own for it", noise(1) == [], noise(1))
item(2, "falcon-main: one\nfalcon-main: two\nfalcon-main: three")
res, made = upd(2, next="falcon-main: two")
check("1 two steps left out: both stay, each back in its place, both named, one fix", mt(2)["next"] == "falcon-main: one\nfalcon-main: two\nfalcon-main: three" and kinds(made) == ["step-kept"]
      and "1. falcon-main: one" in made[0][1] and "3. falcon-main: three" in made[0][1], (mt(2), made))
item(3, "falcon-main: one\nfalcon-main: two\nfalcon-main: three")
res, made = upd(3, next="falcon-main: three\nfalcon-main: a new step")
check("1 a step left out beside a new line: the kept steps and the new line are all in next, nothing the writer wrote is lost", {"falcon-main: one", "falcon-main: two", "falcon-main: three", "falcon-main: a new step"} == set(mt(3)["next"].split("\n"))
      and len(mt(3)["next"].split("\n")) == 4 and kinds(made) == ["step-kept"], (mt(3), made))
item(4)
res, made = upd(4, next="none")
check("1 next=none with no mark: both steps stay open", mt(4)["next"] == "falcon-main: build it\nfalcon-main: test it" and kinds(made) == ["step-kept"], (mt(4), made))
item(5)
res, made = upd(5, next="falcon-main: test it", done=[1])
check("1 a step marked done in the same call is no case: it leaves, no fix", mt(5)["next"] == "falcon-main: test it" and kinds(made) == [] and steps_of(5)[0][0] == "done", (mt(5), made))
item(6)
res, made = upd(6, next="falcon-main: test it", dropped=[1])
check("1 a step marked dropped in the same call is no case either", mt(6)["next"] == "falcon-main: test it" and kinds(made) == [], (mt(6), made))
item(7)
res, made = upd(7, next="falcon-main: compile it\nfalcon-main: test it", reword={1: "falcon-main: compile it"})
check("1 a step reworded with reword in the same call is no case: it changes, no fix", mt(7)["next"] == "falcon-main: compile it\nfalcon-main: test it" and kinds(made) == [], (res, mt(7), made))
item(8)
res, made = upd(8, next="falcon-main: test it\nfalcon-main: build it")
check("1 a next that lists every open step in another order is stored as written, no fix", mt(8)["next"] == "falcon-main: test it\nfalcon-main: build it" and kinds(made) == [], (mt(8), made))
item(9)
res, made = upd(9, next="falcon-main: build it\nfalcon-main: test it\nfalcon-main: open the PR")
check("1 a next that only adds a step is stored as written, no fix", mt(9)["next"] == "falcon-main: build it\nfalcon-main: test it\nfalcon-main: open the PR" and kinds(made) == [], (mt(9), made))
item(10, "falcon-main: build it")
res, made = upd(10, sender=OTHER, next="home-other: wait for the build")
check("1 setup: a second session puts its own line on the item", not isinstance(res, ToolError) and "home-other: wait for the build" in mt(10)["next"].split("\n"), (res, mt(10)))
res, made = upd(10, next="falcon-main: build it\nfalcon-main: test it")
check("1 another session's step is never the writer's to answer for: it stays, no fix", "home-other: wait for the build" in mt(10)["next"].split("\n") and kinds(made) == [], (res, mt(10), made))
item(11)
res, made = upd(11, next="falcon-main: build it (in progress)\nfalcon-main: test it")
check("1 a step rewritten with words added (progress) is refused as ever, nothing written", isinstance(res, ToolError) and "with words added" in str(res) and mt(11)["next"] == "falcon-main: build it\nfalcon-main: test it", (res, mt(11)))
item(12)
res, made = upd(12, clear_next=True, next="falcon-main: start over")
check("1 clear_next=true is a deliberate wipe: the lines become dropped steps, no fix", mt(12)["next"] == "falcon-main: start over" and kinds(made) == [] and [s for s, _ in steps_of(12)][:2] == ["dropped", "dropped"], (mt(12), made, steps_of(12)))
item(13, "falcon-main: build it\nfalcon-main: test it", state="doing")
res, made = upd(13, status="completed", outcome="done", reason="finished", outcome_text="- All done")
check("1 a close is no case: the open steps are marked by the close, no fix", kinds(made) == [] and not isinstance(res, ToolError), (res, made))
item(15)
res, made = upd(15, next="falcon-main: test it", reword={1: "falcon-main: compile it"})
check("1 a reword whose new text next does not list keeps its own refusal: nothing is carried over for it", isinstance(res, ToolError) and "does not list that text" in str(res) and kinds(made) == [] and mt(15)["next"] == "falcon-main: build it\nfalcon-main: test it", (res, made, mt(15)))
item(16)
res, made = upd(16, status="completed", outcome="done", reason="finished", outcome_text="- All done", next="falcon-main: test it")
check("1 a close that names a shorter next is no case for the carry-over: the close marks the steps", "step-kept" not in kinds(made), (res, made))
item(14, "falcon-main: only step")
res, made = upd(14, description=DESC + "\n- one more fact")
check("1 an update that leaves next out is no case: nothing in next changes, no fix", mt(14)["next"] == "falcon-main: only step" and kinds(made) == [], (mt(14), made))
item(60)
res, made = upd(60, next="falcon-main: test it\nfalcon-main: open the PR")
check("1 a step finished and another added, none marked (one step out, one new line in): the new line is a new step and the old step stays open, never a reword of it", not isinstance(res, ToolError) and kinds(made) == ["step-kept"]
      and mt(60)["next"] == "falcon-main: build it\nfalcon-main: test it\nfalcon-main: open the PR" and [x for x, _ in steps_of(60)] == ["open"] * 3, (res if isinstance(res, ToolError) else "", mt(60), made))
check("1 …the fix names the step by its position and says how to end it or give it new words (done, dropped or the reword parameter)", "1. falcon-main: build it" in made[0][1] and "done=[n]" in made[0][1] and "dropped=[n]" in made[0][1] and "reword=" in made[0][1], made)
check("1 …no step is marked done by the server, and the History has no line of its own for it", not any(x == "done" for x, _ in steps_of(60)) and noise(60) == [], (steps_of(60), noise(60)))
res, made = upd(60, next="falcon-main: test it\nfalcon-main: open the PR", done=[1])
check("1 …the retry the reply names works: done=[1] with the same next ticks the step the writer meant", not isinstance(res, ToolError) and kinds(made) == [] and steps_of(60)[0] == ("done", "falcon-main: build it") and mt(60)["next"] == "falcon-main: test it\nfalcon-main: open the PR", (res if isinstance(res, ToolError) else "", steps_of(60), made))
item(61)
res, made = upd(61, next="falcon-main: build and test it")
check("1 two steps written as one new line: both stay open beside it (step-kept), as the reply says", kinds(made) == ["step-kept"] and sorted(mt(61)["next"].split("\n")) == ["falcon-main: build and test it", "falcon-main: build it", "falcon-main: test it"], (mt(61), made))
item(62, "falcon-main: one\nfalcon-main: two\nfalcon-main: three")
res, made = upd(62, next="falcon-main: uno\nfalcon-main: two\nfalcon-main: tres")
check("1 two steps out, two new lines of other words in: no new line takes an old step's place (no implied reword), both old steps stay open and the new lines are new steps", kinds(made) == ["step-kept"]
      and sorted(mt(62)["next"].split("\n")) == ["falcon-main: one", "falcon-main: three", "falcon-main: tres", "falcon-main: two", "falcon-main: uno"] and "1. falcon-main: one" in made[0][1] and "3. falcon-main: three" in made[0][1], (mt(62), made))
item(63, "falcon-main: build it")
res, made = upd(63, next="falcon-main: compile it\nfalcon-main: lint it")
check("1 one step out beside two new lines: the step stays open beside them (step-kept)", kinds(made) == ["step-kept"] and sorted(mt(63)["next"].split("\n")) == ["falcon-main: build it", "falcon-main: compile it", "falcon-main: lint it"], (mt(63), made))
item(64, "falcon-main: build it")
res, made = upd(64, sender=OTHER, next="home-other: wait for the build")
res, made = upd(64, next="falcon-main: compile it")
check("1 a new line beside another session's line: the writer's old step stays open, the other line is as it was", not isinstance(res, ToolError) and sorted(mt(64)["next"].split("\n")) == ["falcon-main: build it", "falcon-main: compile it", "home-other: wait for the build"] and kinds(made) == ["step-kept"], (res if isinstance(res, ToolError) else "", mt(64), made))
item(69)
res, made = upd(69, next="falcon-main: compile it\nfalcon-main: test it", reword={1: "falcon-main: compile it"})
check("1 the way to replace a step's words is the reword parameter: the step changes in place and is never left open beside its new words, no fix", not isinstance(res, ToolError) and kinds(made) == [] and steps_of(69) == [("open", "falcon-main: compile it"), ("open", "falcon-main: test it")], (res if isinstance(res, ToolError) else "", steps_of(69), made))
item(65)
res, made = upd(65, next="falcon-main: build it (in progress)\nfalcon-main: test it", dropped=[1])
check("1 a step marked dropped beside a new line is no case: the mark says what became of it, no fix", kinds(made) == [] and mt(65)["next"] == "falcon-main: build it (in progress)\nfalcon-main: test it", (res if isinstance(res, ToolError) else "", mt(65), made))

# ================================================================ 2. a subject over its limit is cut at a word
def expected_cut(text, limit=SUBJ_MAX, keep_to=0):
    """the longest run of whole words of `text` that, with ` …` after it, fits the limit (independent of the server's code)"""
    best = ""
    for n in range(1, len(text.split(" ")) + 1):
        cand = " ".join(text.split(" ")[:n])
        if len(cand) + 2 <= limit: best = cand
    return best + " …"
WORDS = " ".join(["measure", "the", "export", "run", "before", "and", "after", "the", "queue", "change", "lands", "on", "every", "box"] * 2)
LONG = "[home] " + WORDS
assert len(LONG) > SUBJ_MAX and " " in LONG[8:]
res, made = create(subject=LONG)
g = gid_of(res)
check("2 create: a subject over the limit is cut at the last word that fits and ends with the mark, the whole within the limit", subj(g) == expected_cut(LONG) and len(subj(g)) <= SUBJ_MAX and subj(g).startswith("[home] "), (res, subj(g) if g else ""))
check("2 create: …one subject-cut fix, which says the length and the limit", kinds(made) == ["subject-cut"] and str(len(LONG)) in made[0][1] and str(SUBJ_MAX) in made[0][1], made)
check("2 create: …and the History has no line for it", noise(g) == [], noise(g))
item(20)
res, made = upd(20, subject=LONG)
check("2 update: the same cut on a new subject; the stored subject is the cut one", rd(20)["subject"] == expected_cut(LONG) and kinds(made) == ["subject-cut"], (rd(20)["subject"], made))
EXACT = "[home] " + " ".join(["word"] * 100)
EXACT = EXACT[:SUBJ_MAX].rstrip()
item(21)
res, made = upd(21, subject=EXACT)
check("2 a subject of exactly the limit is stored byte for byte, no fix", rd(21)["subject"] == EXACT and len(EXACT) <= SUBJ_MAX and kinds(made) == [], (rd(21)["subject"], made))
exact80 = "[home] " + "w" * (SUBJ_MAX - 7)
if len(exact80) == SUBJ_MAX:
    item(22)
    res, made = upd(22, subject=exact80)
    check("2 a subject of 80 characters is stored byte for byte, no fix", rd(22)["subject"] == exact80 and kinds(made) == [], (rd(22)["subject"], made))
else:
    check("2 setup: an 80-character subject", False, exact80)
SHORT = "[home] a short subject"
item(23)
res, made = upd(23, subject=SHORT)
check("2 a short subject is stored byte for byte, no fix", rd(23)["subject"] == SHORT and kinds(made) == [], (rd(23)["subject"], made))
STORED_LONG = "[home] " + " ".join(["stored"] * 30)
item(24, subject=STORED_LONG)
res, made = upd(24, description=DESC + "\n- one more fact")
check("2 an update that leaves subject out on an item with a stored long subject: untouched, no fix", rd(24)["subject"] == STORED_LONG and kinds(made) == [], (rd(24)["subject"], made))
res, made = upd(24, subject=STORED_LONG)
check("2 …one that sets the very subject it has: untouched, no fix", rd(24)["subject"] == STORED_LONG and kinds(made) == [], (rd(24)["subject"], made))
item(25)
res, made = create(subject="[home] " + "s" * 81)
check("2 a subject whose first word alone does not fit is still refused, with its length and the limit", isinstance(res, ToolError) and "the subject is" in str(res) and "limit is 80" in str(res) and kinds(made) == [], (res, made))
res, made = create(subject="[mine] " + WORDS)
check("2 a long subject that opens with a tag that is no scope prefix is still refused for the prefix, nothing cut", isinstance(res, ToolError) and "subject must start with one of" in str(res) and kinds(made) == [], (res, made))
for name, text, limit, want in (
        ("a code span", "[work] Fix `the long code span that continues here` now", 40, "[work] Fix …"),
        ("link words", "[work] See [the long documentation page about things](https://example.com/x) more", 40, "[work] See …"),
        ("parentheses", "[work] Make the export work (when the queue is empty and the box is up) now", 50, "[work] Make the export work …"),
        ("a link's title", "[work] Read [docs](https://example.com/p \"a long title of it\") first", 50, "[work] Read …"),
        ("a closed span", "[work] Fix `the span` and then the rest of the very long text here", 40, "[work] Fix `the span` and then the …")):
    got = BT.cut_words(text, limit)
    check(f"2 cut_words: a cut never ends inside {name} (it falls before it)", got == want and len(got) <= limit, got)
check("2 cut_words: no gap outside a code span or parentheses means no cut (the caller refuses)", BT.cut_words("`" + "word " * 30 + "`", 20) is None and BT.cut_words("(" + "word " * 30 + ")", 20) is None, None)
res, made = create(subject="[work] Fix `the long code span that continues here and goes on and on and on` now and later")
g = gid_of(res)
check("2 create: a long subject with a code span is cut before the span, never inside it", g and subj(g).count("`") % 2 == 0 and len(subj(g)) <= SUBJ_MAX and subj(g).endswith(" …") and kinds(made) == ["subject-cut"], (res if isinstance(res, ToolError) else "", subj(g) if g else ""))

# ================================================================ 3. a work line over its limit is cut at a word
WL = "reading the export run before the queue change lands everywhere"
assert len(WL) > WK.TEXT_MAX
def work_text(i):
    return [ (S.tag_of(s) or {}).get("text") for s in S.view(mt(i)) if S.tag_of(s)]
def expected_work(text):
    best = ""
    for n in range(1, len(text.split(" ")) + 1):
        cand = " ".join(text.split(" ")[:n])
        if len(cand) + 2 <= WK.TEXT_MAX: best = cand
    return best + " …"
item(30)
res, made = upd(30, work={"text": WL, "state": "in progress"})
check("3 a status line over 40 characters is cut at the last word that fits, the mark counted in the limit", work_text(30) == [expected_work(WL)] and len(work_text(30)[0]) <= WK.TEXT_MAX, (res if isinstance(res, ToolError) else "", work_text(30)))
check("3 …one work-cut fix, with the length it was and the limit", kinds(made) == ["work-cut"] and str(len(WL)) in made[0][1] and str(WK.TEXT_MAX) in made[0][1], made)
check("3 …and the History has no line of its own for the cut", noise(30) == [], noise(30))
item(31)
res, made = upd(31, work={"text": "x" * WK.TEXT_MAX, "state": "in progress"})
check("3 a status line of exactly 40 characters is stored as written, no fix", work_text(31) == ["x" * WK.TEXT_MAX] and kinds(made) == [], (work_text(31), made))
item(32)
res, made = upd(32, work={"text": "building the parser", "state": "in progress"})
check("3 a short status line is stored as written, no fix", work_text(32) == ["building the parser"] and kinds(made) == [], (work_text(32), made))
item(33)
res, made = upd(33, work={"text": "x" * 45, "state": "in progress"})
check("3 a status line whose first word alone is over the limit is still refused", isinstance(res, ToolError) and "a status line is a few words" in str(res) and kinds(made) == [], (res, made))
check("3 work.parse: the text and the length it was", WK.parse({"text": WL})["text"] == expected_work(WL) and WK.parse({"text": WL})["cut"] == len(WL) and WK.parse({"text": "ok"})["cut"] == 0, (WK.parse({"text": WL}), WK.parse({"text": "ok"})))

# ================================================================ 4. an ask-by day with a time of day keeps its day
DAY = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=3)).strftime("%Y-%m-%d")
for form in (f"{DAY}T10:00", f"{DAY} 10:00", f"{DAY}T10:00:30", f"{DAY}T10:00:30Z", f"{DAY}T10:00+04:00", f"{DAY}T10:00:30.5+0400"):
    got, made = fx(lambda form=form: G.ask_by_day(form, "ask_by"))
    check(f"4 ask_by_day: {form} keeps its day and the fix is counted", got == DAY and kinds(made) == ["ask-by-day"] and form in made[0][1] and DAY in made[0][1], (got, made))
for form in (DAY, "", "none", "soon", "2026-13-45T10:00", "tomorrow 10:00", f"{DAY}T25", f"{DAY}T10"):
    got, made = fx(lambda form=form: G.ask_by_day(form, "ask_by"))
    check(f"4 ask_by_day: {form!r} comes back as it was (the checks that judge it do), no fix", got == form and kinds(made) == [], (got, made))
got, made = fx(lambda: G.until_in("a1", "open", f"{DAY}T09:30", "", "", False, "relay"))
check("4 until_in: a timed until on a relay wait is the day alone, one ask-by-day fix naming until", got[1] == DAY and kinds(made) == ["ask-by-day"] and "until" in made[0][1], (got, made))
got, made = fx(lambda: G.until_in("a1", "open", f"{DAY}T09:30", "", "", False, "event"))
check("4 until_in: …and on an event wait", got[1] == DAY and kinds(made) == ["ask-by-day"], (got, made))
got, made = fx(lambda: G.until_in("a1", "open", "", f"{DAY}T09:30", "", False, "relay"))
check("4 until_in: a timed wake on a relay wait is the day alone, naming wake", got[1] == DAY and kinds(made) == ["ask-by-day"] and "wake" in made[0][1], (got, made))
got, made = fx(lambda: G.until_in("a1", "open", f"{DAY}T09:30", "", "", False, "anchor"))
check("4 until_in: a timed until on a wait that takes a time is kept as written, no fix", f"{DAY}T09:30" in json.dumps(got) and kinds(made) == [], (got, made))
got, made = fx(lambda: G.until_in("a1", "open", DAY, "", "", False, "relay"))
check("4 until_in: a day alone on a relay wait is unchanged, no fix", got[1] == DAY and kinds(made) == [], (got, made))
got, made = fx(lambda: G.until_in("a1", "open", "", "", f"{DAY}T09:30", False, "relay"))
check("4 until_in: a timed ask_by on a relay wait is the day alone, naming ask_by", got[1] == DAY and kinds(made) == ["ask-by-day"] and "ask_by" in made[0][1], (got, made))
got, made = fx(lambda: G.until_in("a1", "open", "", "", f"{DAY}T09:30", False, ""))
check("4 until_in: a timed ask_by beside no relay or event wait is no ask-by day's: it keeps its time (as until does), no fix", got[0] == f"{DAY}T09:30" and got[1] == "" and got[2] is True and kinds(made) == [], (got, made))

# the writes themselves: update and create, the tool's own calls
DAY2 = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=5)).strftime("%Y-%m-%d")
YESTERDAY = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=2)).strftime("%Y-%m-%d")
def relay_item(i, **meta): item(i, wait_kind="relay", wait_event="vendor reply", until=DAY2, needs=["external"], **meta)
def until_of(i): return W.stored_until(mt(i))
REASON = "the vendor replies only after that date"
for k, param in enumerate(("ask_by", "until", "wake")):
    i = 70 + k
    relay_item(i)
    res, made = upd(i, **{param: f"{DAY}T14:00", "wait_reason": REASON})
    check(f"4 update: {param} with a time of day on a relay wait keeps the day and drops the time, one ask-by-day fix naming {param}", not isinstance(res, ToolError) and until_of(i) == DAY and kinds(made) == ["ask-by-day"] and param in made[0][1] and "relay" in made[0][1], (res if isinstance(res, ToolError) else "", mt(i), made))
relay_item(73)
res, made = upd(73, ask_by=DAY, wait_reason=REASON)
check("4 update: the day alone on a relay wait is stored as given, no fix", until_of(73) == DAY and kinds(made) == [], (mt(73), made))
item(74)
res, made = upd(74, wait_kind="relay", wait_event="vendor reply", needs=["external"], ask_by=f"{DAY}T14:00", wait_reason=REASON)
check("4 update: a timed ask_by beside a wait_kind=relay given in the same call is cut to its day too", not isinstance(res, ToolError) and until_of(74) == DAY and kinds(made) == ["ask-by-day"], (res if isinstance(res, ToolError) else "", mt(74), made))
item(75); item(76)
res, made = upd(75, ask_by=f"{DAY}T08:00", wait_reason="back in the morning")
res2, made2 = upd(76, until=f"{DAY}T08:00", wait_reason="back in the morning")
check("4 update: a timed ask_by on an item with no relay or event wait keeps its time, as until does: the same wait is stored whichever name gave it", not isinstance(res, ToolError) and not isinstance(res2, ToolError) and until_of(75) == f"{DAY}T08:00" and until_of(76) == until_of(75), (res if isinstance(res, ToolError) else "", mt(75), mt(76)))
check("4 update: …no ask-by-day fix, and no word of a relay or event wait's day in the reply", kinds(made) == [] and kinds(made2) == [] and "relay or event" not in str(res), (made, str(res)[-400:]))
item(77, wait_kind="time", until=DAY2)
res, made = upd(77, ask_by=f"{DAY}T08:00", wait_reason="back in the morning")
check("4 update: …and on a plain time wait", not isinstance(res, ToolError) and until_of(77) == f"{DAY}T08:00" and kinds(made) == [], (res if isinstance(res, ToolError) else "", mt(77), made))
res, made = create(wait_kind="relay", wait_event="vendor reply", needs=["external"], until=f"{DAY}T14:00")
g = gid_of(res)
check("4 create: until with a time of day on a relay wait keeps the day, one ask-by-day fix", g and until_of(g) == DAY and kinds(made) == ["ask-by-day"] and "until" in made[0][1], (res if isinstance(res, ToolError) else "", made))
res, made = create(wait_kind="relay", wait_event="vendor reply", needs=["external"], ask_by=f"{DAY}T14:00")
g = gid_of(res)
check("4 create: ask_by (the old name of until) with a time of day on a relay wait is cut to its day the same way, naming ask_by", g and until_of(g) == DAY and kinds(made) == ["ask-by-day"] and "ask_by" in made[0][1], (res if isinstance(res, ToolError) else "", made))
res, made = create(until=f"{DAY}T08:00", needs=["external"], wait_event="vendor reply", wait_kind="time")
g = gid_of(res)
check("4 create: until with a time on a time wait keeps its time", g and until_of(g) == f"{DAY}T08:00" and kinds(made) == [], (res if isinstance(res, ToolError) else "", made))
res, made = create(ask_by=f"{DAY}T08:00", wait_kind="time")
g = gid_of(res)
check("4 create: …and ask_by on it keeps its time, as until does", g and until_of(g) == f"{DAY}T08:00" and kinds(made) == [], (res if isinstance(res, ToolError) else "", made))

# a time later today is no day that can be kept: a day falls due at 00:00, so today is past
NOWZ = p.zone_now()
if NOWZ.hour < 23:
    LATE = f"{NOWZ.date().isoformat()}T23:59"
    TOMORROW = (NOWZ.date() + dt.timedelta(days=1)).isoformat()
    def past_refused(name, res, made, i=None):
        check(name, isinstance(res, ToolError) and "already past" in str(res) and TOMORROW in str(res) and "ask-by day" in str(res) and kinds(made) == [], (res, made))
        if i is not None:
            check(name + ": …nothing stored", until_of(i) == DAY2 and mt(i).get("wait_kind") == "relay", mt(i))
    for k, param in enumerate(("ask_by", "until", "wake")):
        i = 80 + k
        relay_item(i)
        res, made = upd(i, **{param: LATE, "wait_reason": REASON})
        past_refused(f"4 update: {param} later today on a relay wait is refused (today's day is already past), naming tomorrow", res, made, i)
    relay_item(83)
    res, made = upd(83, ask_by=f"{YESTERDAY}T10:00", wait_reason=REASON)
    past_refused("4 update: a time on a day gone by on a relay wait is refused the same way", res, made, 83)
    res, made = create(wait_kind="relay", wait_event="vendor reply", needs=["external"], until=LATE)
    past_refused("4 create: until later today on a relay wait is refused", res, made)
    res, made = create(wait_kind="relay", wait_event="vendor reply", needs=["external"], ask_by=LATE)
    past_refused("4 create: ask_by later today on a relay wait is refused", res, made)
    got, made = fx(lambda: G.ask_by_day(LATE))
    check("4 ask_by_day: a time later today raises, and counts no fix", isinstance(got, ToolError) and kinds(made) == [], (got, made))
    item(84); res, made = upd(84, ask_by=LATE, wait_reason="back this evening")
    check("4 update: a time later today beside no relay or event wait is a plain timed wait, as until is", not isinstance(res, ToolError) and until_of(84) == LATE and kinds(made) == [], (res if isinstance(res, ToolError) else "", mt(84), made))
else:
    check("4 setup: it is too late in the day (board timezone) for the later-today checks; run again earlier", True, None)

# a day alone that is not after now is refused on a relay or event wait like a timed one (a day falls due at 00:00 of that day)
TODAY_ = NOWZ.date().isoformat(); TOMORROW_ = (NOWZ.date() + dt.timedelta(days=1)).isoformat()
def day_refused(name, res, made, i=None):
    check(name, isinstance(res, ToolError) and "already past" in str(res) and TOMORROW_ in str(res) and kinds(made) == [], (res, made))
    if i is not None:
        check(name + ": ...nothing stored", until_of(i) == DAY2 and mt(i).get("wait_kind") == "relay", mt(i))
for k, (param, day_) in enumerate((("ask_by", TODAY_), ("until", TODAY_), ("wake", YESTERDAY), ("ask_by", YESTERDAY))):
    relay_item(85 + k)
    res, made = upd(85 + k, **{param: day_, "wait_reason": REASON})
    day_refused(f"4 update: {param}={day_} (a day with no time, already past) on a relay wait is refused, naming tomorrow", res, made, 85 + k)
res, made = create(wait_kind="relay", wait_event="vendor reply", needs=["external"], until=TODAY_)
day_refused("4 create: until=today (no time) on a relay wait is refused", res, made)
res, made = create(wait_kind="relay", wait_event="vendor reply", needs=["external"], ask_by=YESTERDAY)
day_refused("4 create: ask_by=a day gone by on a relay wait is refused", res, made)
got, made = fx(lambda: G.ask_by_day(TODAY_))
check("4 ask_by_day: today alone raises, and counts no fix", isinstance(got, ToolError) and kinds(made) == [], (got, made))
got, made = fx(lambda: G.ask_by_day(TOMORROW_))
check("4 ask_by_day: tomorrow alone is unchanged, no fix", got == TOMORROW_ and kinds(made) == [], (got, made))

# a time with an offset is read in the instance timezone first: its day there is the day kept, and one fix is logged
OFF_DAY = (dt.date.fromisoformat(DAY2) - dt.timedelta(days=1)).isoformat()          # 02:00 at +09:00 is the evening before at the instance's +04:00
for k, param in enumerate(("until", "ask_by", "wake")):
    relay_item(90 + k)
    res, made = upd(90 + k, **{param: f"{DAY2}T02:00+09:00", "wait_reason": REASON})
    check(f"4 update: {param} with an offset time on a relay wait keeps the day it falls on in the instance timezone, one ask-by-day fix and no wake fix", not isinstance(res, ToolError) and until_of(90 + k) == OFF_DAY
          and kinds(made) == ["ask-by-day"] and OFF_DAY in made[0][1], (res if isinstance(res, ToolError) else "", mt(90 + k), made))
    if param != "until":
        txt_ = res if isinstance(res, str) else ""
        check(f"4 update: {param} with an offset time: the alias note names the day stored, never the time the fix cut (one date in the whole reply)", f"stored as until={OFF_DAY} " in txt_ and f"{DAY2}T02:00+09:00" not in txt_.split("(note:")[-1], txt_)
res, made = create(wait_kind="relay", wait_event="vendor reply", needs=["external"], until=f"{DAY2}T02:00+09:00")
g = gid_of(res)
check("4 create: an offset time on a relay wait: the instance-timezone day, one fix", g and until_of(g) == OFF_DAY and kinds(made) == ["ask-by-day"], (res if isinstance(res, ToolError) else "", made))
got, made = fx(lambda: G.ask_by_day(f"{DAY2}T23:30Z", "ask_by"))
check("4 ask_by_day: a Z time late in the day is the next day at the instance's offset", got == (dt.date.fromisoformat(DAY2) + dt.timedelta(days=1)).isoformat() and kinds(made) == ["ask-by-day"], (got, made))

# the old name ask_by is read as a timed until only when wake is not given too
got, made = fx(lambda: G.until_in("a1", "open", "", DAY, f"{DAY}T09:30", False, ""))
check("4 until_in: ask_by with a time beside a wake in the same call is not read as until: both come back as given, no fix", got[0] == DAY and got[1] == f"{DAY}T09:30" and got[2] is False and kinds(made) == [], (got, made))

# ================================================================ 5. a bare address in a description is written as a link to itself
URL = "https://example.com/a/b?c=1"
def desc_of(i): return rd(i)["description"] if i else ""
res, made = create(desc=f"- Goal: A thing\n- Lives at {URL}")
g = gid_of(res)
check("5 create: a bare address in a description is written as a link to itself", desc_of(g) == f"- Goal: A thing\n- Lives at [{URL}]({URL})", desc_of(g) if g else res)
check("5 create: …one description-url fix, and no naked-URL note after it", kinds(made) == ["description-url"] and "naked URL" not in str(res), (made, str(res)[-300:]))
check("5 create: …and the History has no line for it", noise(g) == [], noise(g))
check("5 create: …the note does not claim the page draws no bare address as a link (it links one by its own rule), and says how to give a link words", "does not draw" not in made[0][1] and "its own rule" in made[0][1] and "[words](address)" in made[0][1], made)
item(40)
res, made = upd(40, description=f"- Goal: A thing\n- See {URL}. And {URL}x, or (https://example.org/z).")
check("5 update: a trailing full stop, a second address and one in parentheses: each written as a link to itself, the punctuation left outside", desc_of(40) == f"- Goal: A thing\n- See [{URL}]({URL}). And [{URL}x]({URL}x), or ([https://example.org/z](https://example.org/z)).", desc_of(40))
check("5 update: …counted once", kinds(made) == ["description-url"], made)
item(41)
res, made = upd(41, description="- Goal: A thing\n- A link [the doc](https://example.com/doc) and a span `https://example.com/span`")
check("5 unchanged: a Markdown link and a code span are stored as written, no fix", desc_of(41) == "- Goal: A thing\n- A link [the doc](https://example.com/doc) and a span `https://example.com/span`" and kinds(made) == [], (desc_of(41), made))
item(42)
res, made = upd(42, description="- Goal: A thing\n- A link [the doc](https://example.com/doc), a span `https://example.com/span`, and " + URL)
check("5 mixed: only the bare address becomes a link, the link and the span stay byte for byte", desc_of(42) == f"- Goal: A thing\n- A link [the doc](https://example.com/doc), a span `https://example.com/span`, and [{URL}]({URL})" and kinds(made) == ["description-url"], (desc_of(42), made))
item(43, desc=f"- Goal: A thing\n- Lives at [{URL}]({URL})")
res, made = upd(43, description=f"- Goal: A thing\n- Lives at {URL}")
check("5 the bare text sent again to an item that stores the link: nothing changes, no fix, no note", desc_of(43) == f"- Goal: A thing\n- Lives at [{URL}]({URL})" and kinds(made) == [] and "naked" not in str(res), (desc_of(43), made, str(res)[-200:]))
item(46, desc=f"- Goal: A thing\n- Lives at {URL}")
res, made = upd(46, description=f"- Goal: A thing\n- Lives at {URL}")
check("5 a bare address the item already stores, sent again as it stands: left as it is, no fix", desc_of(46) == f"- Goal: A thing\n- Lives at {URL}" and kinds(made) == [], (desc_of(46), made))
res, made = upd(46, description=f"- Goal: A thing\n- Lives at {URL}\n- And https://example.org/new")
check("5 …a new bare address beside it becomes a link, the stored one is not touched, and the fix counts one address", desc_of(46) == f"- Goal: A thing\n- Lives at {URL}\n- And [https://example.org/new](https://example.org/new)" and kinds(made) == ["description-url"] and "1 bare address" in made[0][1], (desc_of(46), made))
item(44)
res, made = script(44, description=f"- Goal: A thing\n- Lives at {URL}")
check("5 a script's write is no session's: its bare address is stored as written, no fix", not isinstance(res, ToolError) and desc_of(44) == f"- Goal: A thing\n- Lives at {URL}" and kinds(made) == [], (res if isinstance(res, ToolError) else "", desc_of(44), made))
item(45)
res, made = upd(45, next=f"falcon-main: read {URL}\nfalcon-main: test it")
check("5 a bare address in next is still refused, nothing written", isinstance(res, ToolError) and "bare URL" in str(res) and mt(45)["next"] == "falcon-main: build it\nfalcon-main: test it" and kinds(made) == [], (res, mt(45)))
A_ = "https://a.example/x"
check("5 bullet_text.link_bare_urls: links the bare ones only, and returns the addresses it linked", BT.link_bare_urls("- see https://a.example/x.") == ("- see [https://a.example/x](https://a.example/x).", [A_])
      and BT.link_bare_urls("- see [x](https://a.example/x)") == ("- see [x](https://a.example/x)", []) and BT.link_bare_urls("- a\n- b") == ("- a\n- b", []), BT.link_bare_urls("- see https://a.example/x."))
PART = "\uc785\ub2c8\ub2e4"                 # a Korean particle, written as an escape (no Hangul in the file)
LEAD = "\uc8fc\uc18c\ub294"
def link_of(u): return f"[{u}]({u})"
def linked(text, skip=()):
    return BT.link_bare_urls(text, skip)
# the address ends at its last URL character
got = linked(f"- {LEAD} https://example.com/a{PART} ok")
check("5 link: an address followed by a Korean particle ends before the particle (the particle stays outside the link)", got == (f"- {LEAD} {link_of('https://example.com/a')}{PART} ok", ["https://example.com/a"]), got)
got = linked("- see https://en.wikipedia.org/wiki/Foo_(bar) now")
check("5 link: an address with a balanced parenthesis keeps its closing one", got == ("- see " + link_of("https://en.wikipedia.org/wiki/Foo_(bar)") + " now", ["https://en.wikipedia.org/wiki/Foo_(bar)"]), got)
got = linked("- (see https://example.com/a) now")
check("5 link: a closing parenthesis that closes one outside the address stays outside", got == ("- (see " + link_of("https://example.com/a") + ") now", ["https://example.com/a"]), got)
got = linked("- see https://example.com/a_b_ and https://example.com/c*")
check("5 link: a real trailing underscore or asterisk stays in the address", got == ("- see " + link_of("https://example.com/a_b_") + " and " + link_of("https://example.com/c*"), ["https://example.com/a_b_", "https://example.com/c*"]), got)
for name, text in (("a link's title", '- [x](https://example.com/a "https://example.com/t")'), ("a code span", "- `https://example.com/a` and `https://example.com/b`")):
    got = linked(text)
    check(f"5 link: an address inside {name} is left as it is, nothing linked", got is not None and got[0] == text and got[1] == [], got)
for name, text in (("an angle autolink", "- see <https://example.com/a> now"), ("a reference definition", "- x\n[1]: https://example.com/a\n- y"), ("an attribute", '- <a href="https://example.com/a">x</a>')):
    got = linked(text)
    check(f"5 link: an address inside {name} is never rewritten into a broken link: the text is left for the form's own refusal (None)", got is None, got)
    got = linked(text + " and https://example.com/b")
    check(f"5 link: ...also when a plain bare address is beside it (nothing is half-linked)", got is None, got)
got = linked("- `https://example.com/a` and https://example.com/b")
check("5 link: a code span and a bare address on the same line: only the bare one is linked", got == ("- `https://example.com/a` and " + link_of("https://example.com/b"), ["https://example.com/b"]), got)
got = linked(f"- see https://example.com/a{PART} and `https://example.com/code` and https://example.com/z.")
check("5 link: a particle, a code span and a plain address together are each treated by their own rule", got == (f"- see {link_of('https://example.com/a')}{PART} and `https://example.com/code` and {link_of('https://example.com/z')}.", ["https://example.com/a", "https://example.com/z"]), got)
got = linked("- see https://a.example/held and https://a.example/new", skip={"https://a.example/held"})
check("5 link: an address the item holds (skip) is left bare, the new one beside it is linked", got == ("- see https://a.example/held and " + link_of("https://a.example/new"), ["https://a.example/new"]), got)
got = linked(f"- see https://a.example/held{PART} ok", skip={"https://a.example/held" + PART})
check("5 link: ...and the same with a particle after a held address", got is not None and got[1] == [] and got[0] == f"- see https://a.example/held{PART} ok", got)
big = "`a` https://e.com/x " * 10000
t0 = time.time(); gotb = BT.link_bare_urls("- " + big); dtb = time.time() - t0
check("5 link: a 200 kB line of many addresses is linked in well under a second (linear)", gotb is not None and len(gotb[1]) == 10000 and dtb < 2.0, (dtb, None if gotb is None else len(gotb[1])))
t0 = time.time(); gotb = BT.link_bare_urls("- " + "https://e.com/x" * 20000, skip={"https://e.com/other"}); dtb = time.time() - t0
check("5 link: one very long run of address text with a skip set is linked in well under a second too", dtb < 2.0, dtb)
# an emphasis mark round an address is not the address's own (M2): the target never ends in the closing mark
E = "https://example.com/a"
for name, text, want in (("bold round the address", f"- see **{E}** now", f"- see **{link_of(E)}** now"), ("italic with underscores", f"- see _{E}_ now", f"- see _{link_of(E)}_ now"),
                         ("italic with asterisks", f"- see *{E}* now", f"- see *{link_of(E)}* now"), ("bold opened earlier in the bullet", f"- **see {E}** now", f"- **see {link_of(E)}** now"),
                         ("bold underscores", f"- __{E}__ now", f"- __{link_of(E)}__ now"), ("emphasis then a full stop", f"- see **{E}**.", f"- see **{link_of(E)}**.")):
    got = linked(text)
    check(f"5 link: {name}: the closing mark stays outside the link and the target is the address", got == (want, [E]), got)
for name, text, addr in (("a lone trailing underscore with no emphasis before it", f"- see {E}_ now", E + "_"), ("a lone trailing asterisk", f"- see {E}* now", E + "*"),
                         ("an underscore inside and at the end", "- see https://example.com/a_b_ now", "https://example.com/a_b_")):
    got = linked(text)
    check(f"5 link: {name}: kept as the address's own", got == (text.replace(addr, link_of(addr)), [addr]), got)
DUNDER = "https://docs.python.org/3/reference/datamodel.html#object.__init__"
CALL = "https://docs.python.org/3/reference/datamodel.html#object.__call__"
for name, text, addr, after in (("a dunder name ending the address", f"- {DUNDER}", DUNDER, ""), ("a dunder name then a full stop", f"- see {CALL}.", CALL, "."), ("an address ending in a double underscore", "- https://example.com/a__", "https://example.com/a__", ""),
                                ("a glob ending in a double asterisk", "- files: https://example.com/src/**", "https://example.com/src/**", ""), ("a triple underscore ending the address", "- see https://example.com/a___ now", "https://example.com/a___", " now"),
                                ("a double asterisk after an emphasis that closed already", "- *a* see https://example.com/a** now", "https://example.com/a**", " now"),
                                ("a double asterisk after a bold of the same length that closed already", "- **a** see https://example.com/a** now", "https://example.com/a**", " now"), ("a double underscore after an underscore bold that closed already", "- __a__ see https://example.com/a__ now", "https://example.com/a__", " now"), ("a double underscore after an intraword underscore", "- snake_case see https://example.com/a__ now", "https://example.com/a__", " now"),
                                ("a double underscore after an intraword double underscore", "- my__var see https://example.com/a__ now", "https://example.com/a__", " now"), ("a lone underscore after an intraword underscore", "- snake_case see https://example.com/a_ now", "https://example.com/a_", " now"), ("a double asterisk after a spaced operator", "- 2 ** 3 see https://example.com/a** now", "https://example.com/a**", " now")):
    got = linked(text)
    check(f"5 link: {name}: no emphasis opened it, so it stays in the address and its target", got is not None and got[1] == [addr] and link_of(addr) + after in got[0], got)
for name, text, want, addr in (("a bold opened earlier in the line", f"- **see {E}** now", f"- **see {link_of(E)}** now", E), ("a bold with words between its opener and the address", f"- **see also {E}** now", f"- **see also {link_of(E)}** now", E),
                               ("a bold opened with the mark before a parenthesis", f"- (**{E}**) now", f"- (**{link_of(E)}**) now", E), ("an underscore pair round the address", f"- _{E}_.", f"- _{link_of(E)}_.", E),
                               ("a single asterisk emphasis opened earlier", f"- *see {E}* now", f"- *see {link_of(E)}* now", E)):
    got = linked(text)
    check(f"5 link: {name}: its closing run still stays outside the link", got == (want, [addr]), got)
for k, (name, line, addr) in enumerate((("a dunder name", DUNDER, DUNDER), ("a double underscore", "https://example.com/a__", "https://example.com/a__"), ("a glob", "files: https://example.com/src/**", "https://example.com/src/**"))):
    item(100 + k)
    res, made = upd(100 + k, description=f"- Goal: A thing\n- {line}")
    check(f"5 update: {name} at the end of a bare address is stored whole in the link, the target the address as written", not isinstance(res, ToolError) and desc_of(100 + k) == f"- Goal: A thing\n- {line.replace(addr, link_of(addr))}" and kinds(made) == ["description-url"], (str(res)[:200], desc_of(100 + k), made))
item(95)
res, made = upd(95, description=f"- Goal: A thing\n- see **{E}** now")
check("5 update: bold round a bare address: stored as a link with a live target, the bold outside it", desc_of(95) == f"- Goal: A thing\n- see **{link_of(E)}** now" and kinds(made) == ["description-url"], (desc_of(95), made))

# a non-ASCII letter in the path cuts nowhere (M3): the text is left for the refusal, a short particle after the address still stays out
HPATH = "\ud55c\uae00"                  # two Hangul syllables, written as escapes
for name, text in (("a non-ASCII title after the path's slash", f"- https://ko.example.org/wiki/{HPATH} is the page"), ("a non-ASCII value after =", f"- see https://example.com/a?q={HPATH} ok"),
                   ("a non-ASCII letter between path letters", f"- see https://example.com/a{HPATH}b ok"), ("a non-ASCII word after a dot", f"- see https://example.com/a.{HPATH} ok")):
    got = linked(text)
    check(f"5 link: {name}: not rewritten at the first non-ASCII character, left as written for the main refusal (None)", got is None, got)
got = linked(f"- see https://example.com/a?q=1{PART} ok")
check("5 link: a particle after an address with a query still ends it before the particle", got == (f"- see {link_of('https://example.com/a?q=1')}{PART} ok", ["https://example.com/a?q=1"]), got)
item(96)
res, made = upd(96, description=f"- Goal: A thing\n- https://ko.example.org/wiki/{HPATH} is the page")
check("5 update: a non-ASCII path in a bare address is refused as on main, nothing stored, no fix", isinstance(res, ToolError) and "bare URL" in str(res) and desc_of(96) == DESC and kinds(made) == [], (str(res)[:300], desc_of(96), made))

# the other characters a URL cannot hold end an address only when nothing address-like follows (LOW 1)
for name, text in (("a vertical bar", f"- see {E}|b ok"), ("a bracketed index", f"- see {E}[1] ok"), ("a brace", f"- see {E}{{x}} ok"), ("a backslash", f"- see {E}\\b ok"),
                   ("a caret", f"- see {E}^b ok"), ("a quote in the path", f'- see {E}"b" ok'), ("an unclosed parenthesis", f"- see {E}(b ok"), ("an unclosed parenthesis then more", "- see https://example.com/p(1 and 2")):
    got = linked(text)
    check(f"5 link: {name} inside an address: not linked at a wrong, shorter target, left for the main refusal (None)", got is None, got)
for name, text, addr, after in (("a closing bracket", f"- [see {E}] ok", E, "]"), ("a closing quote", f'- say "{E}" ok', E, '"'), ("a closing brace", f"- {{see {E}}} ok", E, "}"),
                                ("a closing parenthesis and a comma", f"- (see {E}), ok", E, "),")):
    got = linked(text)
    check(f"5 link: {name} after an address stays outside the link", got is not None and got[1] == [addr] and link_of(addr) + after in got[0], got)
item(97)
res, made = upd(97, description=f"- Goal: A thing\n- see {E}|b ok")
check("5 update: an address with a vertical bar in it is refused as on main, nothing stored, no fix", isinstance(res, ToolError) and "bare URL" in str(res) and desc_of(97) == DESC and kinds(made) == [], (str(res)[:300], desc_of(97), made))

# a code span of any backtick count is never rewritten inside (LOW 2)
for name, text in (("a double-backtick span", f"- ``x {E} y`` ok"), ("a triple-backtick span", f"- ```{E}``` ok"), ("a double-backtick span holding a single backtick", f"- ``a ` {E}`` ok")):
    got = linked(text)
    check(f"5 link: {name}: no link markup lands inside it", got is None or (got[0] == text and got[1] == []), got)
got = linked(f"- ``x {E} y`` and https://example.com/z")
check("5 link: a double-backtick span beside a bare address: the span is byte for byte as written, never rewritten inside", got is None or (f"``x {E} y``" in got[0] and got[1] == ["https://example.com/z"]), got)

# an unclosed parenthesis run is scanned once, not once per parenthesis (LOW 3): a generous bound, a quadratic scan takes many seconds
for name, text in (("a run of 'https://a('", "- " + "https://a(" * 8000), ("a run of 'https://a(b '", "- " + "https://a(b " * 8000), ("one address and a long run of parentheses", "- https://a" + "(" * 80000),
                   ("a long run of closing parentheses", "- https://a" + ")" * 80000), ("a long run of underscores", "- https://a/" + "_" * 80000)):
    t0 = time.time(); gotb = linked(text); dtb = time.time() - t0
    check(f"5 link: {name} (about 80 kB) is scanned in linear time: well under the bound", dtb < 3.0, dtb)

item(47)
res, made = upd(47, description="- Goal: A thing\n" + "\n".join(f"- line {n} https://example.com/{n}" for n in range(30)))
check("5 update: a description over the line cap is refused for its size, not scanned and not fixed", isinstance(res, ToolError) and kinds(made) == [], (str(res)[:300], made))
item(48)
res, made = upd(48, description=f"- Goal: A thing\n- Lives at {URL} and https://example.org/second and https://example.net/third and https://example.io/fourth")
check("5 update: the reply note names the addresses (up to three) and counts the rest", kinds(made) == ["description-url"] and URL in made[0][1] and "4 bare addresses" in made[0][1] and "and 1 more" in made[0][1] and "https://example.io/fourth" not in made[0][1], made)
item(49)
res, made = upd(49, description=f"- Goal: A thing\n- Lives at {URL} and https://example.org/second")
check("5 update: two addresses: the plural is counted ('2 bare addresses ... were written')", kinds(made) == ["description-url"] and "2 bare addresses" in made[0][1] and "were written" in made[0][1], made)
item(66)
res, made = upd(66, description=f"- Goal: A thing\n- see <https://example.com/a> and {URL}\n  not a bullet at all")
check("5 update: a description whose form is refused for another reason than a long bullet is not rewritten: the form refusal comes first, no fix", isinstance(res, ToolError) and kinds(made) == [], (str(res)[:300], made))
item(67)
res, made = upd(67, description=f"- Goal: A thing\n- Lives at <https://example.com/a> and https://example.com/{PART}")
check("5 update: an angle autolink in a description is never rewritten into a broken link: the main refusal stands, nothing stored, no fix", isinstance(res, ToolError) and "bare URL" in str(res) and desc_of(67) == DESC and kinds(made) == [], (str(res)[:300], desc_of(67), made))

# ================================================================ 6. the call log and the weekly report count each fix, and no fix invites a resend
def reply(text): return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=text)], structured_content={"result": text})
def run_mw(name, args, call):
    async def nxt(ctx): return call()
    ctx = types.SimpleNamespace(message=types.SimpleNamespace(name=name, arguments=args))
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        try: out = asyncio.run(_wmw._RefusalLog().on_call_tool(ctx, nxt))
        except ToolError as e: out = e
    return out, buf.getvalue()
def txt(out): return str(out) if isinstance(out, ToolError) else out.content[0].text          # a refusal where a fix was due fails its check, it does not crash the run
def mw_update(i, **kw): return run_mw("update", {"item_id": f"a{i}", "sender": MAIN}, lambda: reply(_wt_update.stackshot_update(f"a{i}", sender=MAIN, **kw)))
def mw_ask(): return run_mw("update", {"item_id": "a1", "sender": MAIN}, lambda: reply(str(G.until_in("a1", "open", f"{DAY}T09:30", "", "", False, "relay"))))
item(50); item(51); item(52); item(53)
shown = {}
out, err = mw_update(50, next="falcon-main: test it"); shown["step-kept"] = txt(out)
out, err = mw_update(51, subject=LONG); shown["subject-cut"] = txt(out)
out, err = mw_update(52, work={"text": WL, "state": "in progress"}); shown["work-cut"] = txt(out)
out, err = mw_ask(); shown["ask-by-day"] = txt(out)
out, err = mw_update(53, description=f"- Goal: A thing\n- Lives at {URL}"); shown["description-url"] = txt(out)
for kind, text in shown.items():
    note = text.split("\n(fixed for you:", 1)[1] if "\n(fixed for you:" in text else ""
    check(f"6 reply: {kind} puts one plain '(fixed for you: …)' line on the reply, with no invitation to send it again", note.count("fixed for you") == 0 and note != "" and note.rstrip().endswith(".)") and "send it again" not in note and "write that field again" not in note, text[-400:])
rows = list(CL.read(0, time.time() + 86400))
mine = [r for r in rows if r.get("fix")]
check("6 call log: each of the five calls is logged ok with its one fix kind", sorted(k for r in mine for k in r["fix"]) == sorted(["step-kept", "subject-cut", "work-cut", "ask-by-day", "description-url"]) and all(r["ok"] is True for r in mine), mine)
cur = RR.tally(rows)
check("6 report: the tally counts each of the five kinds once under fixes", all(cur["fixes"][k] == 1 for k in ("step-kept", "subject-cut", "work-cut", "ask-by-day", "description-url")), dict(cur["fixes"]))
report = RR.build(dt.date(2026, 11, 16), cur, RR.tally([]))
check("6 report: the text says each kind under 'corrected by the server instead of refused'", "corrected by the server instead of refused" in report and all(f"{k} 1" in report for k in ("step-kept", "subject-cut", "work-cut", "ask-by-day", "description-url")), report)
check("6 report: none of the five counts as a refusal", not cur["refused"], dict(cur["refused"]))
check("6 call log: the five kinds are in NO_RESEND, and the send-back check knows the text fixes", {"step-kept", "subject-cut", "work-cut", "ask-by-day", "description-url"} <= set(CL.NO_RESEND) and {"subject-cut", "description-url"} <= set(CL.CHECKED), (CL.NO_RESEND, CL.CHECKED))
for kind, field, stored, sent, other in (("subject-cut", "subject", "[home] cut …", LONG, "[home] words of my own"), ("description-url", "description", f"- Goal: A\n- [{URL}]({URL})", f"- Goal: A\n- {URL}", "- Goal: A\n- the doc, not the link")):
    d = {"fields": [field], "stored": CL._h(stored), "sent": CL._h(sent)}
    check(f"6 send-back: {kind}: a later write of the field with other words undoes the fix", CL.undone(kind, d, {field: other}) is True, None)
    check(f"6 send-back: {kind}: the stored text or the text first sent, written again, is no undoing", CL.undone(kind, d, {field: stored}) is False and CL.undone(kind, d, {field: sent}) is False and CL.undone(kind, d, {}) is False, None)
# a refusal that remains is still counted as one
out, err = run_mw("update", {"item_id": "a11", "sender": MAIN}, lambda: reply(_wt_update.stackshot_update("a11", sender=MAIN, next="falcon-main: build it (in progress)\nfalcon-main: test it")))
check("6 a refusal that remains (words added to a step) is logged refused, with no fix", isinstance(out, ToolError) and [r for r in CL.read(0, time.time() + 86400) if r.get("ok") is False and "words added" in str(r.get("why"))] != [], str(out)[:200])

# ================================================================ 7. the tool text says what the server does
from stackshot.web.tools import text as _wt_text
shared = (pathlib.Path(STACK) / "stackshot/web/tools/text/shared.md").read_text(encoding="utf-8")
upd_md = (pathlib.Path(STACK) / "stackshot/web/tools/text/update.md").read_text(encoding="utf-8")
check("7 tool text: it says a longer subject is cut at a word, a bare address in a description becomes a link, and a time of day on an ask-by is dropped", "a longer one is cut at a word" in shared and "in a description it becomes a link to itself" in shared and "a time of day is dropped" in shared, None)
check("7 tool text: it says a step left out unmarked stays open and the reply names it, and no longer says it is refused", "keeps that step open as written and the reply names it" in upd_md and "the old one is refused" not in upd_md, None)
app_src = (pathlib.Path(STACK) / "stackshot/web/app.py").read_text(encoding="utf-8")
check("7 tool text: the server instructions no longer say a left-out line is marked done or dropped in that update", "is marked done or dropped in that update" not in app_src and "stays open unless marked done or dropped" in app_src, None)
check("7 tool text: …and the work line is cut, not refused, over its limit (no 'refused' beside the limit)", "refused" not in re.search(r"## param WORK.*?(?=\n## )", upd_md, re.S).group(0), None)

print(("ok" if not fails else "FAILED") + f": five fixes scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
