import asyncio, contextlib, datetime as dt, io, json, logging, os, pathlib, re, sys, time, types
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="formgatestest-"); T = pathlib.Path(tmp)
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

URL = "https://example.com/a/b?c=1"
def local_day(n): return (dt.datetime.now(_cfg.tz()) + dt.timedelta(days=n)).strftime("%Y-%m-%d")
def msg(res): return str(res) if isinstance(res, ToolError) else ""
def show(label, res): print(f"--- {label}\n{msg(res) or res}")
HEAD = "Refused: {n} problems in this call; fix all of them and send the call once more.\n"
def parts(res):
    """the numbered faults of a combined refusal, in order, and the line of checks not made ('' when none)"""
    t = msg(res)
    body, _, skipped = t.partition("\nNot checked yet")
    got = re.split(r"\n\((\d+)\) ", body)
    return [got[k + 1] for k in range(1, len(got), 2)], ("Not checked yet" + skipped if skipped else "")
def unchanged(i, before):
    return rd(i)["subject"] == before["subject"] and rd(i)["description"] == before["description"] and rd(i)["metadata"].get("next") == before["metadata"].get("next") and not rd(i)["metadata"].get("hold")
NOGOAL = "- no goal here\n- another"

# ================================================================ 1. an update with several faults in the words of its fields: one refusal
item(1)
was = rd(1)
res, made = upd(1, subject="no prefix at all", description=NOGOAL, next=f"falcon-main: read {URL}\nfalcon-main: test it")
fl, skipped = parts(res)
check("1 three faults in the words (subject, description, next): one refusal that counts them on its first line", msg(res).startswith(HEAD.format(n=3) + "(1) "), msg(res)[:200])
check("1 …each fault has its own numbered line, in the gates' order, with the text its gate gives it alone", len(fl) == 3 and "bare URL" in fl[0] and fl[1].startswith("subject must start with one of") and fl[2].startswith("the description must open with its goal"), fl)
check("1 …the corrected description the goal gate shows is there once, with its example", msg(res).count("- Goal: no goal here\n- another") == 1 and skipped == "", msg(res)[:500])
check("1 …nothing was stored and no fix was counted for the refused call", unchanged(1, was) and kinds(made) == [], (rd(1), made))
check("1 …and the refusal is counted in the call log under its first fault, as that fault alone is", CL.kind_of(msg(res)) == CL.kind_of("Refused: " + fl[0]) != CL.kind_of(HEAD.format(n=3)), (CL.kind_of(msg(res)), CL.kind_of("Refused: " + fl[0])))
res, made = upd(1, subject="[home] a prefixed subject", description=DESC, next=f"falcon-main: read [the page]({URL})\nfalcon-main: test it")
check("1 …the same call with the three faults fixed goes through", not isinstance(res, ToolError), res)

# ================================================================ 2. one fault: refused as it always was
item(2)
was = rd(2)
res, made = upd(2, subject="no prefix at all")
check("2 a subject with no prefix alone: the refusal is the subject gate's own text, with no count and no list", msg(res) == "Refused: " + _fg.subject_faults("no prefix at all")[0].removeprefix("Refused: ") and "problems in this call" not in msg(res), msg(res))
res, made = upd(2, description=NOGOAL)
check("2 a description with no goal alone: the goal gate's own text", msg(res).startswith("Refused: the description must open with its goal") and "problems in this call" not in msg(res) and "Not checked" not in msg(res), msg(res)[:200])
res, made = upd(2, next=f"falcon-main: read {URL}")
check("2 a bare address in next alone: the gate's own text", msg(res).startswith("Refused: next has a bare URL") and "problems in this call" not in msg(res), msg(res)[:200])
res, made = upd(2, hold=True)
check("2 a park with nothing it waits for, alone: that refusal as it was, no count", msg(res).startswith("Refused: a park names what it waits for") and "problems in this call" not in msg(res) and unchanged(2, was), msg(res)[:200])

# ================================================================ 3. a fault in the words beside a fault of the item as the call would store it
item(3)
was = rd(3)
res, made = upd(3, description=NOGOAL, hold=True)
fl, skipped = parts(res)
check("3 a description with no goal beside a park that names nothing it waits for: both come back, one refusal", msg(res).startswith(HEAD.format(n=2)) and len(fl) == 2 and fl[0].startswith("the description must open with its goal") and fl[1].startswith("a park names what it waits for"), msg(res)[:300])
check("3 …nothing was stored", unchanged(3, was), rd(3))
item(4)
res, made = upd(4, subject="no prefix at all", next="falcon-main: build it (in progress)\nfalcon-main: test it")
fl, skipped = parts(res)
check("3 a subject with no prefix beside a step rewritten with words added: both come back", msg(res).startswith(HEAD.format(n=2)) and fl[0].startswith("subject must start") and "with words added" in fl[1], msg(res)[:400])
check("3 …the unmarked-step check reads the step refused beside it, so it is named as not made, not told as a third fault", len(fl) == 2 and "Not checked yet" in skipped and "none of your open steps unmarked" in skipped, (fl, skipped))
res, made = upd(4, subject="no prefix at all", next="falcon-main: build it\nfalcon-main: test it")
check("3 …and the same call with the step as it was: only the subject, alone, as it always was", msg(res).startswith("Refused: subject must start") and "problems in this call" not in msg(res), msg(res)[:200])

# ================================================================ 4. a check that reads what another fault leaves out is not made, and the refusal says so
item(5)
was = rd(5)
res, made = upd(5, said='[{"tag": "Nope", "quote": "x"}]', description=NOGOAL, hold=True, wake=local_day(400), wait_basis="a long wait")
fl, skipped = parts(res)
check("4 a said with a tag the rule does not know, a description with no goal and a wake past the cap: three faults in one refusal", msg(res).startswith(HEAD.format(n=3)) and fl[0].startswith("said[0]: tag must be one of") and fl[1].startswith("the description must open with its goal") and fl[2].startswith("wait_basis stands for a wake at most"), msg(res)[:500])
check("4 …the cap on how far out a wake may be reads the said and the wait_basis, so it is named as not made, with the checks of the item as it would be stored", skipped.startswith("Not checked yet, because they read what the faults above leave out: the cap on how far out a wake may be") and "the wait's reason and end" in skipped and skipped.endswith("once these are fixed."), skipped)
check("4 …nothing was stored", unchanged(5, was), rd(5))
res, made = upd(5, said='[{"tag": "Nope", "quote": "z", "msg": "w"}, {"tag": "Also", "quote": "q"}]')
fl, skipped = parts(res)
check("4 a said list with two bad entries: each fault is its own line, named by its place", msg(res).startswith(HEAD.format(n=2)) and fl[0].startswith("said[0]:") and fl[1].startswith("said[1]:"), msg(res)[:500])

# ================================================================ 5. a create with several faults
res, made = create(subject="[home] x", desc=NOGOAL, next=f"falcon-main: read {URL}")
fl, skipped = parts(res)
check("5 a create with a description with no goal and a bare address in next: one refusal with both, each with its own text", msg(res).startswith(HEAD.format(n=2)) and fl[0].startswith("the description must open with its goal") and fl[1].startswith("next has a bare URL"), msg(res)[:400])
check("5 …nothing was filed", not any(x.name.endswith(".json") and json.loads(x.read_text()).get("subject") == "[home] x" for x in (T / "store/a").glob("*.json")), None)
res, made = create(subject="[home] x", desc=NOGOAL)
check("5 a create with one fault: the goal gate's own text, no count", msg(res).startswith("Refused: the description must open with its goal") and "problems in this call" not in msg(res), msg(res)[:200])
res, made = create(subject="[home] x", desc=NOGOAL, next=f"falcon-main: read {URL}", wait_kind="relay", wait_event="the vendor's reply", needs=["external"])
fl, skipped = parts(res)
check("5 a create with a relay wait that names no day, beside the two faults in its words: the words' faults come back, and so does the wait's", msg(res).startswith("Refused: ") and "the description must open with its goal" in msg(res) and "next has a bare URL" in msg(res), msg(res)[:600])

# ================================================================ 6. the checks that read what another fault leaves out
item(6)
was = rd(6)
res, made = upd(6, description="A prose line, not a bullet.")
check("6 a description that is prose, alone: the form gate's own refusal, and no second one for a goal it could not read", msg(res).startswith("Refused: description line is not a `- ` bullet") and "problems in this call" not in msg(res) and "goal" not in msg(res).split("\n")[0], msg(res)[:300])
res, made = upd(6, description="A prose line, not a bullet.", subject="no prefix at all")
fl, skipped = parts(res)
check("6 …beside a subject with no prefix: two faults, and the goal check is named as not made, since it reads the first bullet the form fault leaves unread", len(fl) == 2 and fl[0].startswith("subject must start") and fl[1].startswith("description line is not a `- ` bullet") and "the check that the description opens with its goal" in skipped, (fl, skipped))
item(7, "falcon-main: build it", desc=DESC)
ASKO = "Decide: which of the two vendors · Recommend: Vendor A · Stakes: a month · By: no date"
res, made = create(subject="[home] x", desc=DESC, needs=["decision"], ask=ASKO, next="")
check("6 an ask that names alternatives and lists no options, alone: one fault, as before, with none of the other checks of the decision beside it", "names alternatives" in msg(res) and "problems in this call" not in msg(res) and msg(res).startswith("Refused: this needs=decision item names alternatives"), msg(res)[:300])
res, made = create(subject="[home] x", desc=NOGOAL, needs=["decision"], ask=ASKO, next=f"falcon-main: carry on")
fl, skipped = parts(res)
check("6 …beside a description with no goal: the description's fault and the first of the decision's, the rest of the decision's checks named as not made", len(fl) == 2 and fl[0].startswith("the description must open with its goal") and fl[1].startswith("this needs=decision item names alternatives") and "the other checks of the decision's wording and options" in skipped, (fl, skipped))


# ================================================================ 7. with the model guards on, one mistake is one fault, in the words it has on main
# The guards judge the mover and the event wait beside the gates that refuse the same mistake first; a call with one mistake is refused with that mistake's text alone, as on main
# (the strings below are main's own refusals for these calls, taken from main), and a call with two mistakes lists both.
_cfg.CFG["model"]["guards"] = True
MAIN_TEXT = {
    "upd mover": "Refused: @ID@ is alive and its mover, home-nobody, is no session the registry or the fleet knows. An alive item's mover is the owner, a live session or the project's background agent: set mover=<that name> (or name the session in needs), or, when nothing can move it now, put it in a wait.",
    "create mover": "Refused: this item is alive and its mover, home-nobody, is no session the registry or the fleet knows. An alive item's mover is the owner, a live session or the project's background agent: set mover=<that name> (or name the session in needs), or, when nothing can move it now, put it in a wait.",
    "upd evt none": "Refused: an event wait names its event in wait_event: pr_released <owner/repo#n> | pr_merged <owner/repo#n> | recycle [<machine>] | fleet_op <verb | any | many> [<machine>] | job_run <name> | box_online <machine>",
    "upd evt bad": "Refused: wait_event 'whenever it feels right' is not an event the server watches. Pass one of: pr_released <owner/repo#n> | pr_merged <owner/repo#n> | recycle [<machine>] | fleet_op <verb | any | many> [<machine>] | job_run <name> | box_online <machine>",
    "create evt none": "Refused: an event wait names its event in wait_event: pr_released <owner/repo#n> | pr_merged <owner/repo#n> | recycle [<machine>] | fleet_op <verb | any | many> [<machine>] | job_run <name> | box_online <machine>",
    "create evt bad": "Refused: wait_event 'whenever it feels right' is not an event the server watches. Pass one of: pr_released <owner/repo#n> | pr_merged <owner/repo#n> | recycle [<machine>] | fleet_op <verb | any | many> [<machine>] | job_run <name> | box_online <machine>",
    "upd anchor": "Refused: wait_anchor https://github.com/o/r/pull/9 is not on projects/example's anchors list, so nothing watches it and the wait would end only at its backstop. Add the anchor first: anchors(project=\"projects/example\", add=[\"https://github.com/o/r/pull/9\"], items=[\"@ID@\"]), then set the wait again",
    "create anchor": "Refused: wait_anchor https://github.com/o/r/pull/9 is not on projects/example's anchors list, so nothing watches it and the wait would end only at its backstop. Add the anchor first: add it project-wide first: anchors(project=\"projects/example\", add=[\"https://github.com/o/r/pull/9\"]); or create the item without the wait, then anchors(project=\"projects/example\", add=[\"https://github.com/o/r/pull/9\"], items=[<its id>]), then set the wait",
}
def same(name, res, key, i):
    want = MAIN_TEXT[key].replace("@ID@", f"a{i}")
    check(f"7 {name}: one problem, with the text it has on main", msg(res) == want and "problems in this call" not in msg(res), (msg(res)[:600], want[:300]))
item(30); item(31)
FILED = lambda: len(list((T / "store/a").glob("*.json")))
filed_before = FILED()
BAD_EVENT = "whenever it feels right"; ANCHOR = "https://github.com/o/r/pull/9"
was = rd(30)
res, made = upd(30, mover="home-nobody")
same("an unknown mover on an update", res, "upd mover", 30)
check("7 …nothing was stored", unchanged(30, was) and mt(30).get("mover") is None, mt(30))
res, made = create(mover="home-nobody")
same("an unknown mover on a create (the front agent's step and the hand-off say it again, and are not kept as faults)", res, "create mover", "")
res, made = upd(31, hold=True, wait_kind="event", ask_by=local_day(5))
same("an event wait with no phrase, on an update", res, "upd evt none", 31)
res, made = upd(31, hold=True, wait_kind="event", wait_event=BAD_EVENT, ask_by=local_day(5))
same("an event wait with a phrase that is no event, on an update", res, "upd evt bad", 31)
res, made = create(wait_kind="event", ask_by=local_day(5))
same("an event wait with no phrase, on a create", res, "create evt none", "")
res, made = create(wait_kind="event", wait_event=BAD_EVENT, ask_by=local_day(5))
same("an event wait with a phrase that is no event, on a create", res, "create evt bad", "")
res, made = upd(31, hold=True, wait_kind="anchor", wait_anchor=ANCHOR, wait_event="merged", ask_by=local_day(5))
same("an anchor wait with an anchor that is not on the list, on an update", res, "upd anchor", 31)
res, made = create(wait_kind="anchor", wait_anchor=ANCHOR, wait_event="merged", ask_by=local_day(5))
same("an anchor wait with an anchor that is not on the list, on a create", res, "create anchor", "")
check("7 …none of these stored an item or a wait", mt(31).get("wait_kind") is None and FILED() == filed_before, (mt(31), FILED(), filed_before))
# two mistakes are two faults, each once
res, made = upd(30, mover="home-nobody", subject="no prefix at all")
fl, skipped = parts(res)
check("7 an unknown mover beside a subject with no prefix: two faults, the subject's and the mover's, each once", msg(res).startswith(HEAD.format(n=2)) and len(fl) == 2 and fl[0].startswith("subject must start") and fl[1].startswith("a30 is alive and its mover, home-nobody, is no session"), msg(res)[:700])
check("7 …the hand-off check reads the mover refused beside it, so it is named as not made, not told as a third fault", "the check that the mover has a pane" in skipped and not any("no pane of it is in the heartbeat" in f for f in fl), (fl, skipped))
res, made = create(mover="home-nobody", desc=NOGOAL)
fl, skipped = parts(res)
check("7 …on a create: the description's fault and the mover's, and neither the front agent's step nor the hand-off as a fault of its own", len(fl) == 2 and fl[0].startswith("the description must open with its goal") and fl[1].startswith("this item is alive and its mover, home-nobody") and "the check of a step that opens with a front agent" in skipped, (fl, skipped))
res, made = create(desc=NOGOAL, wait_kind="event", wait_event=BAD_EVENT, ask_by=local_day(5))
fl, skipped = parts(res)
check("7 a phrase that is no event beside a description with no goal: two faults, and the guards' own line on the phrase is not a third", len(fl) == 2 and fl[0].startswith("the description must open with its goal") and fl[1].startswith("wait_event 'whenever it feels right' is not an event"), (fl, skipped))
res, made = upd(31, hold=True, wait_kind="anchor", wait_anchor=ANCHOR, ask_by=local_day(5))
fl, skipped = parts(res)
check("7 an anchor wait that names no event beside an anchor that is not on the list: two mistakes, both come back", len(fl) == 2 and "and the event it expects" in fl[0] and fl[1].startswith("wait_anchor https://github.com/o/r/pull/9 is not on projects/example's anchors list"), (fl, skipped))
_cfg.CFG["model"]["guards"] = False

# ================================================================ 8. one mistake is one problem, with the guards off and on, in the words main has for it
URL_A = "https://github.com/o/r/pull/9"
def item_nosteps(i): item(i, next_="")      # an item with no open step: the next step a write gives it is its first
PLACEHOLDERS = [("tbd", "tbd"), ("TBD", "TBD"), ("a question mark", "?"), ("dots", "..."), ("to be decided", "to be decided")]
ASK8 = "Decide: ship it now · Recommend: yes · Stakes: a week of delay · By: no date"
OPTS8 = [{"label": "yes", "line": "ship it now", "recommended": True}, {"label": "no", "line": "wait a week", "recommended": False}]
LIST2 = [{"kind": "relay", "event": "the lease"}, {"kind": "relay", "event": "the vendor"}]
def item_closed(i):      # a completed item: its checklist is the record
    item(i); d = rd(i); d["status"] = "completed"; (T / f"store/a/{i}.json").write_text(json.dumps(d))
# every call below has ONE mistake: main refuses it with one problem, and so does this change, in main's own words (guards off and on)
CASES8 = [
    ("update, a relay wait with an ask_by that is no date", lambda: upd(40, hold=True, wait_kind="relay", wait_event="the vendor", ask_by="garbage")),
    ("update, an event wait with an ask_by that is no date", lambda: upd(40, hold=True, wait_kind="event", wait_event="recycle", ask_by="garbage")),
    ("update, an anchor wait with an ask_by that is no date", lambda: upd(40, hold=True, wait_kind="anchor", wait_anchor=URL_A, wait_event="merged", ask_by="garbage")),
    ("update, a wait_kind that is none", lambda: upd(40, hold=True, wait_kind="bogus")),
    ("update, a line of next that names no one", lambda: upd(40, next="do the thing")),
    ("create, a relay wait with an ask_by that is no date", lambda: create(wait_kind="relay", wait_event="the vendor", ask_by="garbage")),
    ("create, an event wait with an ask_by that is no date", lambda: create(wait_kind="event", wait_event="recycle", ask_by="garbage")),
    ("create, an anchor wait with an ask_by that is no date", lambda: create(wait_kind="anchor", wait_anchor=URL_A, wait_event="merged", ask_by="garbage")),
    ("create, a relay wait with an until that is no date", lambda: create(wait_kind="relay", wait_event="the vendor", until="garbage")),
    ("create, a wait_kind that is none", lambda: create(wait_kind="bogus")),
    ("create, a line of next that names no one", lambda: create(next="do the thing")),
    ("create, an after id that is none", lambda: create(after=["nonsense"])),
    ("create, an unknown mover beside an item wait with an after id that is none", lambda: create(mover="home-nobody", wait_kind="item", after=["nonsense"])),
    ("create, a waits list with an until that is no date", lambda: create(waits=LIST2, until="garbage")),
    ("create, a waits list with an until that is in the past", lambda: create(waits=LIST2, until=local_day(-3))),
    ("update, a step marked done on a closed item", lambda: upd(47, done=[1])),
    ("update, a step marked dropped on a closed item", lambda: upd(47, dropped=[1])),
    ("update, a step reworded on a closed item", lambda: upd(47, reword={1: "falcon-main: build it another way"})),
    ("update, a step marked done beside a new next on a closed item", lambda: upd(47, next="falcon-main: build it again", done=[1])),
    ("update, a wait_basis on a hold with no wake", lambda: upd(40, hold=True, wait_basis=f"the vendor ships {local_day(9)}")),
    ("update, a hold with a wake on a closed item", lambda: upd(47, hold=True, wake=local_day(5))),
]
CASES8_ON = [      # the guards judge the mover: they are on
    ("update, an unknown mover on a relay wait", lambda: upd(40, hold=True, mover="home-nobody", wait_kind="relay", wait_event="the vendor", ask_by=local_day(5))),
    ("update, an unknown mover and the first step of an item opening with a front agent", lambda: upd(46, mover="home-nobody", next="falcon-main: carry on")),
    ("create, an unknown mover on a relay wait, the step opening with a front agent", lambda: create(mover="home-nobody", wait_kind="relay", wait_event="the vendor", ask_by=local_day(5))),
    ("create, an unknown mover on an event wait, the step opening with a front agent", lambda: create(mover="home-nobody", wait_kind="event", wait_event="recycle", ask_by=local_day(5))),
    ("create, a next of none", lambda: create(next="none")),
    ("create, a next of None beside the owner as mover", lambda: create(next="None", mover=MAIN)),
    ("create, a session as mover of a decision, the step opening with a front agent", lambda: create(mover=OTHER, needs=["decision"], ask=ASK8, options=OPTS8)),
] + [
    (f"{verb}, a line of next that is {tag} and names no one", fn) for tag, ph in PLACEHOLDERS for verb, fn in (
        ("create", lambda ph=ph: create(next=ph)), ("update", lambda ph=ph: upd(40, next=ph)))
] + [
    (f"{verb}, an event wait whose event is {tag}", fn) for tag, ph in PLACEHOLDERS for verb, fn in (
        ("create", lambda ph=ph: create(wait_kind="event", wait_event=ph, ask_by=local_day(5))),
        ("update", lambda ph=ph: upd(40, hold=True, wait_kind="event", wait_event=ph, ask_by=local_day(5))))
]
MAIN8 = {      # main's own refusal for each call, by label and guards (taken from main)
    "update, a relay wait with an ask_by that is no date|False": "Refused: ask_by is YYYY-MM-DD, a real date (got 'garbage')",
    "update, an event wait with an ask_by that is no date|False": "Refused: ask_by is YYYY-MM-DD, a real date (got 'garbage')",
    "update, an anchor wait with an ask_by that is no date|False": "Refused: metadata.wake must be YYYY-MM-DD or YYYY-MM-DDTHH:MM (+04) \u2014 got 'garbage'",
    "update, a wait_kind that is none|False": "Refused: wait_kind is one of time | anchor | item | relay | event (got 'bogus')",
    "update, a line of next that names no one|False": "Refused: a line of next names no one: \"do the thing\". One step is one action with one named actor: open the line with who takes it: `<session>:`, `the owner:` or the outside party's name. A line under a step that belongs to it starts with `- `; results go on the project page (Current state or a timeline line), never into next",
    "create, a relay wait with an ask_by that is no date|False": "Refused: until is YYYY-MM-DD or YYYY-MM-DDTHH:MM, a real date (got 'garbage')",
    "create, an event wait with an ask_by that is no date|False": "Refused: until is YYYY-MM-DD or YYYY-MM-DDTHH:MM, a real date (got 'garbage')",
    "create, an anchor wait with an ask_by that is no date|False": "Refused: until is YYYY-MM-DD or YYYY-MM-DDTHH:MM, a real date (got 'garbage')",
    "create, a relay wait with an until that is no date|False": "Refused: until is YYYY-MM-DD or YYYY-MM-DDTHH:MM (+04), a real date (got 'garbage')",
    "create, a wait_kind that is none|False": "Refused: wait_kind is one of time | anchor | item | relay | event (got 'bogus')",
    "create, a line of next that names no one|False": "Refused: a line of next names no one: \"do the thing\". One step is one action with one named actor: open the line with who takes it: `<session>:`, `the owner:` or the outside party's name. A line under a step that belongs to it starts with `- `; results go on the project page (Current state or a timeline line), never into next",
    "create, an after id that is none|False": "bad item id 'nonsense' \u2014 ids read board#<n> (a temporary one board-tmp-local#<n>), or <letter><n> for an older item",
    "create, an unknown mover beside an item wait with an after id that is none|False": "bad item id 'nonsense' \u2014 ids read board#<n> (a temporary one board-tmp-local#<n>), or <letter><n> for an older item",
    "update, a relay wait with an ask_by that is no date|True": "Refused: ask_by is YYYY-MM-DD, a real date (got 'garbage')",
    "update, an event wait with an ask_by that is no date|True": "Refused: ask_by is YYYY-MM-DD, a real date (got 'garbage')",
    "update, an anchor wait with an ask_by that is no date|True": "Refused: metadata.wake must be YYYY-MM-DD or YYYY-MM-DDTHH:MM (+04) \u2014 got 'garbage'",
    "update, a wait_kind that is none|True": "Refused: wait_kind is one of time | anchor | item | relay | event (got 'bogus')",
    "update, a line of next that names no one|True": "Refused: a line of next names no one: \"do the thing\". One step is one action with one named actor: open the line with who takes it: `<session>:`, `the owner:` or the outside party's name. A line under a step that belongs to it starts with `- `; results go on the project page (Current state or a timeline line), never into next",
    "create, a relay wait with an ask_by that is no date|True": "Refused: until is YYYY-MM-DD or YYYY-MM-DDTHH:MM, a real date (got 'garbage')",
    "create, an event wait with an ask_by that is no date|True": "Refused: until is YYYY-MM-DD or YYYY-MM-DDTHH:MM, a real date (got 'garbage')",
    "create, an anchor wait with an ask_by that is no date|True": "Refused: until is YYYY-MM-DD or YYYY-MM-DDTHH:MM, a real date (got 'garbage')",
    "create, a relay wait with an until that is no date|True": "Refused: until is YYYY-MM-DD or YYYY-MM-DDTHH:MM (+04), a real date (got 'garbage')",
    "create, a wait_kind that is none|True": "Refused: wait_kind is one of time | anchor | item | relay | event (got 'bogus')",
    "create, a line of next that names no one|True": "Refused: a line of next names no one: \"do the thing\". One step is one action with one named actor: open the line with who takes it: `<session>:`, `the owner:` or the outside party's name. A line under a step that belongs to it starts with `- `; results go on the project page (Current state or a timeline line), never into next",
    "create, an after id that is none|True": "bad item id 'nonsense' \u2014 ids read board#<n> (a temporary one board-tmp-local#<n>), or <letter><n> for an older item",
    "create, an unknown mover beside an item wait with an after id that is none|True": "bad item id 'nonsense' \u2014 ids read board#<n> (a temporary one board-tmp-local#<n>), or <letter><n> for an older item",
    "update, an unknown mover on a relay wait|True": "Refused: a40's wait: the mover who takes it then, home-nobody, is no session the registry or the fleet knows. Set mover=<the owner, a live session or the project's background agent> (when it is unset, the first session in needs, else the project's builder or -main agent, takes it). If the item should not wait, drop the wait with update clear_wait=true (wait_kind, wait_anchor, wait_event and ask_by go together).",
    "update, an unknown mover and the first step of an item opening with a front agent|True": "Refused: a46 is alive and its mover, home-nobody, is no session the registry or the fleet knows. An alive item's mover is the owner, a live session or the project's background agent: set mover=<that name> (or name the session in needs), or, when nothing can move it now, put it in a wait.",
    "create, an unknown mover on a relay wait, the step opening with a front agent|True": "Refused: this item's wait: the mover who takes it then, home-nobody, is no session the registry or the fleet knows. Set mover=<the owner, a live session or the project's background agent> (when it is unset, the first session in needs, else the project's builder or -main agent, takes it). If the item should not wait, drop the wait with update clear_wait=true (wait_kind, wait_anchor, wait_event and ask_by go together).",
    "create, an unknown mover on an event wait, the step opening with a front agent|True": "Refused: this item's wait: the mover who takes it then, home-nobody, is no session the registry or the fleet knows. Set mover=<the owner, a live session or the project's background agent> (when it is unset, the first session in needs, else the project's builder or -main agent, takes it). If the item should not wait, drop the wait with update clear_wait=true (wait_kind, wait_anchor, wait_event and ask_by go together).",
}
MAIN8.update({      # the same, for the calls with ONE mistake that were refused twice or three times (taken from main)
    "create, a waits list with an until that is no date|False": "Refused: until is YYYY-MM-DD or YYYY-MM-DDTHH:MM (+04), a real date (got 'garbage')",
    "create, a waits list with an until that is in the past|False": "Refused: until must be in the future (+04)",
    "update, a step marked done on a closed item|False": "Refused: a47 is closed and its checklist is the record of what was done; reopen it (status=open with a next) before marking or rewording a step",
    "update, a step marked dropped on a closed item|False": "Refused: a47 is closed and its checklist is the record of what was done; reopen it (status=open with a next) before marking or rewording a step",
    "update, a step reworded on a closed item|False": "Refused: a47 is closed and its checklist is the record of what was done; reopen it (status=open with a next) before marking or rewording a step",
    "update, a step marked done beside a new next on a closed item|False": "Refused: a47 is closed and its checklist is the record of what was done; reopen it (status=open with a next) before marking or rewording a step",
    "update, a wait_basis on a hold with no wake|False": "Refused: wait_basis explains the wake of a time wait (a park's or a verifying item's), or a wake past the cap, by the real-world date it waits for, and this item has no wake date. A park with no date is refused too: give the wake (hold=true with wake=YYYY-MM-DD, the date the outside event or the owner's words give) and the basis with it",
    "update, a hold with a wake on a closed item|False": "Refused: a completed item cannot be parked; set it open first",
    "create, a waits list with an until that is no date|True": "Refused: until is YYYY-MM-DD or YYYY-MM-DDTHH:MM (+04), a real date (got 'garbage')",
    "create, a waits list with an until that is in the past|True": "Refused: until must be in the future (+04)",
    "update, a step marked done on a closed item|True": "Refused: a47 is closed and its checklist is the record of what was done; reopen it (status=open with a next) before marking or rewording a step",
    "update, a step marked dropped on a closed item|True": "Refused: a47 is closed and its checklist is the record of what was done; reopen it (status=open with a next) before marking or rewording a step",
    "update, a step reworded on a closed item|True": "Refused: a47 is closed and its checklist is the record of what was done; reopen it (status=open with a next) before marking or rewording a step",
    "update, a step marked done beside a new next on a closed item|True": "Refused: a47 is closed and its checklist is the record of what was done; reopen it (status=open with a next) before marking or rewording a step",
    "update, a wait_basis on a hold with no wake|True": "Refused: wait_basis explains the wake of a time wait (a park's or a verifying item's), or a wake past the cap, by the real-world date it waits for, and this item has no wake date. A park with no date is refused too: give the wake (hold=true with wake=YYYY-MM-DD, the date the outside event or the owner's words give) and the basis with it",
    "update, a hold with a wake on a closed item|True": "Refused: a completed item cannot be parked; set it open first",
    "create, a next of none|True": "Refused: next line 'none' does not say who takes it: start every line with `<name>: ` where name is the owner, a session, the project's background agent or the outside party who takes the step (for example `the owner: run \u2026`, `<session>: \u2026` or `Kim: \u2026`); a name in the line's body is not enough. Put file names, commands and code in backticks.",
    "create, a next of None beside the owner as mover|True": "Refused: next line 'None' does not say who takes it: start every line with `<name>: ` where name is the owner, a session, the project's background agent or the outside party who takes the step (for example `the owner: run \u2026`, `<session>: \u2026` or `Kim: \u2026`); a name in the line's body is not enough. Put file names, commands and code in backticks.",
    "create, a session as mover of a decision, the step opening with a front agent|True": "Refused: this item has mover=home-other on an item whose state is your-call, which is the owner's move. An item that is the owner's makes him the mover: leave mover out, or set mover=the owner, and name home-other in then=home-other (his answer or Done hands the item to them). To give the item to home-other now, take decision out of needs and name a session as mover instead.",
})
NEXT_TAIL = ". One step is one action with one named actor: open the line with who takes it: `<session>:`, `the owner:` or the outside party's name. A line under a step that belongs to it starts with `- `; results go on the project page (Current state or a timeline line), never into next"
EVENT_TAIL = " is not an event the server watches. Pass one of: pr_released <owner/repo#n> | pr_merged <owner/repo#n> | recycle [<machine>] | fleet_op <verb | any | many> [<machine>] | job_run <name> | box_online <machine>"
for _tag, _ph in PLACEHOLDERS:      # a placeholder in next, and as an event: main says the one mistake once (guards on)
    for _v in ("create", "update"):
        MAIN8[f"{_v}, a line of next that is {_tag} and names no one|True"] = 'Refused: a line of next names no one: "' + _ph + '"' + NEXT_TAIL
        MAIN8[f"{_v}, an event wait whose event is {_tag}|True"] = "Refused: wait_event '" + _ph + "'" + EVENT_TAIL
for g, cl in ((False, CASES8), (True, CASES8 + CASES8_ON)):
    _cfg.CFG["model"]["guards"] = g
    for lab, fn in cl:
        item(40); item_nosteps(46); item_closed(47)
        res, made = fn()
        check(f"8 {lab} (guards {'on' if g else 'off'}): one problem, main's text", msg(res) == MAIN8[f"{lab}|{g}"] and "problems in this call" not in msg(res), (msg(res)[:500], MAIN8[f"{lab}|{g}"][:300]))
_cfg.CFG["model"]["guards"] = True
item(40)
res, made = upd(40, next="do the thing", mover="home-nobody")
fl, skipped = parts(res)
check("8 a line of next that names no one beside an unknown mover: two mistakes, two problems, each once", msg(res).startswith(HEAD.format(n=2)) and len(fl) == 2 and fl[0].startswith("a line of next names no one") and fl[1].startswith("a40 is alive and its mover, home-nobody"), msg(res)[:600])
res, made = create(next="do the thing", mover="home-nobody")
fl, skipped = parts(res)
check("8 …on a create", msg(res).startswith(HEAD.format(n=2)) and len(fl) == 2 and fl[0].startswith("a line of next names no one") and fl[1].startswith("this item is alive and its mover, home-nobody"), msg(res)[:600])
_cfg.CFG["model"]["guards"] = False

sys.stdout.flush()
print(("ok" if not fails else "FAILED") + f": form gates scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
