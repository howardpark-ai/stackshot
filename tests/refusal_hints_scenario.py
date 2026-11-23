"""Scenario test for the write-time hints of the board's refusals and the two small server fixes that came with them (write refusals, stage 2) — fixture data, the tools called in-process,
no live store, no network.

A refusal names the fix and shows the corrected call, so a writer does not need a second try; where the server can read the intent, it puts the fault right with one plain line instead.

  a  wait-basis-dropped  a wait_basis sent with a wake that is within the cap and holds no time wait: dropped, the wake kept as sent, the reply says so (no send-back check: sending it again is dropped again)
  b  description-goal    a description whose first bullet opens with a goal word in another form (`goal:`, `Goal -`, the Korean label) is relabelled `- Goal: ...`; any other first bullet is refused with
                         the corrected description shown
  c  hints               the refusal for an ask in the wrong form, a said entry that is not JSON, a wait set without its reason, a wait_basis the rule does not take and an option without its label
                         and line names the fault and shows the corrected call; each corrected call is sent back to the same gate and goes through

    tests/run-suite refusal_hints        -> exit 0 / 1"""
import asyncio, contextlib, datetime as dt, io, json, logging, os, pathlib, re, sys, time, types
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="refusalhints-"); T = pathlib.Path(tmp)
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

def reply(text): return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=text)], structured_content={"result": text})
def run_mw(name, args, call):
    async def nxt(ctx): return call()
    ctx = types.SimpleNamespace(message=types.SimpleNamespace(name=name, arguments=args))
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        try: out = asyncio.run(_wmw._RefusalLog().on_call_tool(ctx, nxt))
        except ToolError as e: out = e
    return out, buf.getvalue()
def txt(out): return str(out) if isinstance(out, ToolError) else out.content[0].text

MARK_A = 0
# ================================================================ a. a wait_basis the wake does not need is dropped
def local_day(n): return (dt.datetime.now(_cfg.tz()) + dt.timedelta(days=n)).strftime("%Y-%m-%d")
BASIS = lambda n: f"The vendor visits Tue {local_day(n)} 14:00"
item(101)
res, made = upd(101, until=local_day(3), wait_basis=BASIS(3), wait_reason="the vendor replies after that date")
check("a a wake within the cap with a wait_basis: the call goes through", not isinstance(res, ToolError), res)
check("a …the reply says in one plain line that the basis was dropped and why", "wait-basis-dropped" in kinds(made) and "wait_basis was dropped" in dict(made)["wait-basis-dropped"] and "needs no basis" in dict(made)["wait-basis-dropped"], made)
check("a …the date is stored as sent, no basis is stored", "wait_basis" not in mt(101) and W.stored_until(mt(101)) == local_day(3), mt(101))
check("a …the line names no machine and no fleet tool", not re.search(r"\b(box-[a-d]|sala|salamander)\b", dict(made)["wait-basis-dropped"], re.I), made)
item(102)
res, made = upd(102, until=local_day(3), wait_reason="the vendor replies after that date")
check("a the same call with no basis: no fix", "wait-basis-dropped" not in kinds(made), made)
item(103)
res, made = upd(103, hold=True, until=local_day(40), wait_basis=BASIS(40))
check("a a park past the cap keeps its basis: no fix, the basis is stored", not isinstance(res, ToolError) and "wait-basis-dropped" not in kinds(made) and bool(W.basis_of(mt(103))), (res, made, mt(103)))
item(104)
res, made = upd(104, until=local_day(40), wait_basis=BASIS(40))
check("a a bare date past the cap keeps its basis: no fix, the basis is stored", not isinstance(res, ToolError) and "wait-basis-dropped" not in kinds(made) and bool(W.basis_of(mt(104))), (res, made, mt(104)))
CAP = int(W.cap_days())
item(105)
res, made = upd(105, until=local_day(CAP + 1), wait_basis=BASIS(CAP + 1))
check("a a wake just past the cap (day+8) with a basis keeps it: no fix, the basis is stored", not isinstance(res, ToolError) and "wait-basis-dropped" not in kinds(made) and bool(W.basis_of(mt(105))), (str(res)[:200], made, mt(105)))
item(106); j106 = rd(106); j106["status"] = "completed"; (T / "store/a/106.json").write_text(json.dumps(j106))
res, made = upd(106, until=local_day(3), wait_basis=BASIS(3))
check("a a closed item with a wake and a basis is refused, and no basis is dropped for it", isinstance(res, ToolError) and "wait-basis-dropped" not in kinds(made), (str(res)[:200], made))
check("a …the check of what a basis needs says nothing of a closed item, a day too far out or no wake, and reads an open one within the cap", G.basis_unneeded({"status": "completed"}, G._hooks().parse_wake(local_day(3))) is None and G.basis_unneeded({"status": "open"}, "") is None
      and G.basis_unneeded({"status": "open"}, G._hooks().parse_wake(local_day(CAP + 1))) is None and G.basis_unneeded({"status": "open"}, G._hooks().parse_wake(local_day(3))) is not None
      and G.basis_unneeded({"status": "open"}, G._hooks().parse_wake(local_day(3)), True) is None, None)
item(107)
_waiting = _cfg.CFG.setdefault("waiting", {}); _was_owner = _waiting.get("cap_needs_owner")
try:
    _waiting["cap_needs_owner"] = False
    res, made = upd(107, until=local_day(40), wait_basis=BASIS(40), wait_reason="the vendor replies after that date")
    check("a with the cap off (cap_needs_owner = false) a basis on any wake is dropped: the fix is told, no basis is stored", not isinstance(res, ToolError) and "wait-basis-dropped" in kinds(made) and "wait_basis" not in mt(107), (str(res)[:200], made, mt(107)))
finally:
    if _was_owner is None: _waiting.pop("cap_needs_owner", None)
    else: _waiting["cap_needs_owner"] = _was_owner
same_keys = ("hold", "state", "wait_kind", "wait_basis", "wake", "until", "wait_until")
check("a a wake sent with a dropped basis is stored as the same wake sent alone is (the item before, with the same call and no basis)", {k: mt(102).get(k) for k in same_keys if k != "state"} == {k: mt(101).get(k) for k in same_keys if k != "state"}, (mt(101), mt(102)))
item(114)
res, made = upd(114, until=local_day(3), wait_basis=BASIS(3), clear_wait_basis=True, wait_reason="the vendor replies after that date")
check("a clear_wait_basis with a basis is refused, the basis is not dropped to make the call pass", isinstance(res, ToolError) and "clear_wait_basis drops the basis" in str(res) and "wait-basis-dropped" not in kinds(made), (str(res)[:200], made))
# the drop skips a call that drops the wake or the hold: its basis meets the write's own refusal, never a drop that lets the call through
item(115, wake=local_day(3))
res, made = upd(115, clear_wake=True, wait_basis=BASIS(3))
check("a clear_wake with a basis is refused as a basis for a wake the call drops, the basis is not dropped to make the call pass", isinstance(res, ToolError) and "wait_basis goes with a wake" in str(res) and "wait-basis-dropped" not in kinds(made), (str(res)[:200], made))
item(116, hold=True, wake=local_day(3))
res, made = upd(116, clear_hold=True, wait_basis=BASIS(3))
check("a clear_hold with a basis is refused the same way, no basis is dropped", isinstance(res, ToolError) and "wait_basis goes with a wake" in str(res) and "wait-basis-dropped" not in kinds(made), (str(res)[:200], made))
# a bare clear word is no basis: it clears a stored one and drops nothing, whatever the wake it stands beside (a relay wait's date included)
for k, w in enumerate(("none", "Clear", " - ")):
    item(130 + k)
    res, made = upd(130 + k, until=local_day(3), wait_basis=w, wait_reason="the vendor replies after that date")
    check(f"a wait_basis {w!r} beside a wake within the cap clears, it is no basis to drop: no fix is told", not isinstance(res, ToolError) and "wait-basis-dropped" not in kinds(made) and "wait_basis" not in mt(130 + k), (str(res)[:200], made, mt(130 + k)))
item(134)
res, made = upd(134, wait_kind="relay", wait_event="the vendor", ask_by=local_day(3), needs=["external"], wait_basis="none")
check("a wait_basis 'none' on a relay wait (its date in ask_by) is no basis to drop: the call goes through and no fix is told", not isinstance(res, ToolError) and "wait-basis-dropped" not in kinds(made) and "wait_basis" not in mt(134), (str(res)[:200], made, mt(134)))
item(135)
res, made = upd(135, wait_kind="relay", wait_event="the vendor", ask_by=local_day(3), needs=["external"], wait_basis=f"the vendor answers {local_day(3)}")
check("a wait_basis with a real basis on that relay wait within the cap is dropped, as for a wake: the fix is told", not isinstance(res, ToolError) and "wait-basis-dropped" in kinds(made) and "wait_basis" not in mt(135), (str(res)[:200], made, mt(135)))
check("a the fix has no send-back check (sending it again is dropped again) and invites no resend", "wait-basis-dropped" not in CL.CHECKED and "wait-basis-dropped" in CL.NO_RESEND, None)
out_mw, err_mw = run_mw("update", {"item_id": "a101", "sender": MAIN}, lambda: reply(_wt_update.stackshot_update("a101", sender=MAIN, until=local_day(4), wait_basis=BASIS(4), wait_reason="the vendor replies after that date")))
check("a the reply carries the line, and the call log counts the fix", "(fixed for you:" in txt(out_mw) and "wait_basis was dropped" in txt(out_mw) and any("wait-basis-dropped" in (r.get("fix") or []) for r in CL.read(0, time.time() + 86400)), txt(out_mw)[-300:])

# ================================================================ b. a goal label in another form is relabelled; any other first bullet is refused with the corrected description shown
KO_GOAL = "\ubaa9\ud45c"            # the Korean word for goal, as escapes: no Hangul in the repository
def created(desc, **kw):
    res, made = create(desc=desc, **kw)
    return res, made, (rd(gid_of(res))["description"] if gid_of(res) else "")
for name, desc, want in (("lowercase `goal:`", "- goal: the run finishes\n- It lives here", "- Goal: the run finishes\n- It lives here"),
                         ("`Goal -`", "- Goal - the run finishes\n- It lives here", "- Goal: the run finishes\n- It lives here"),
                         ("`GOALS :`", "- GOALS : the run finishes", "- Goal: the run finishes"),
                         ("a bold label", "- **Goal:** the run finishes\n- It lives here", "- Goal: the run finishes\n- It lives here"),
                         ("the Korean label", f"- {KO_GOAL}: the run finishes\n- It lives here", "- Goal: the run finishes\n- It lives here"),
                         ("an en dash", "- Goal \u2013 the run finishes", "- Goal: the run finishes"),
                         ("the label on the first bullet after a quote line", "> a note\n- goal: the run finishes", "> a note\n- Goal: the run finishes")):
    res, made, got = created(desc)
    check(f"b create: {name} is stored as `- Goal: ...`, one description-goal fix", not isinstance(res, ToolError) and got == want and kinds(made) == ["description-goal"], (str(res)[:200], got, made))
res, made, got = created(f"- {KO_GOAL}: the run finishes")
check("b create: the reply line names the label as written and says the words are as written", "description-goal" in kinds(made) and KO_GOAL in dict(made)["description-goal"] and "as you wrote them" in dict(made)["description-goal"], made)
check("b create: the line names no machine and no fleet tool", not re.search(r"\b(box-[a-d]|sala|salamander)\b", dict(made)["description-goal"], re.I), made)
res, made, got = created("- Goal: the run finishes")
check("b create: a first bullet that opens `Goal:` is stored as written, no fix", got == "- Goal: the run finishes" and kinds(made) == [], (got, made))
res, made, got = created("- goal-oriented work happens here")
check("b create: a first bullet that only starts with the letters (goal-oriented) is no label: refused", isinstance(res, ToolError) and "must open with its goal" in str(res) and kinds(made) == [], (str(res)[:200], made))
res, made, got = created("- Goal:\n- Problem: x")
check("b create: a label with nothing after it is refused as before, and shows no example to copy", isinstance(res, ToolError) and "Send the description again" not in str(res) and kinds(made) == [], str(res)[:300])
res, made = fx(lambda: _wt_create._create(subject="[home] built by the server", description="- goal: x\n- b", project=STK, owner=MAIN, next=f"{MAIN}: carry on"))
check("b a script's create is filed whatever its first bullet: stored as written, no fix", isinstance(res, str) and "- goal: x\n- b" == rd(gid_of(res))["description"] and kinds(made) == [], (str(res)[:200], made))
item(110, desc="- A thing\n- It lives here")
res, made = upd(110, description="- goal: the thing works\n- It lives here")
check("b update: a replacement with `goal:` is stored as `Goal:`, one fix", not isinstance(res, ToolError) and rd(110)["description"] == "- Goal: the thing works\n- It lives here" and kinds(made) == ["description-goal"], (str(res)[:200], made))
res, made = upd(110, description="- Goal: the thing works\n- It lives here")
check("b update: the stored text sent back changes nothing and counts no fix", kinds(made) == [] and rd(110)["description"] == "- Goal: the thing works\n- It lives here", made)
item(111, desc="- goal: legacy label\n- It lives here")
res, made = upd(111, description="- goal: legacy label\n- It lives here")
check("b update: the stored text sent back with its old label is no rewrite: no fix", kinds(made) == [] and rd(111)["description"] == "- goal: legacy label\n- It lives here", (str(res)[:200], made))
res, made = script(110, description="- goal: written by a script\n- It lives here")
check("b update: a script's replacement is left as written, no fix", not isinstance(res, ToolError) and "description-goal" not in kinds(made) and rd(110)["description"].startswith("- goal: written by a script"), (str(res)[:200], made))
res, made, got = created("- " + "w" * 95 + "\n- It lives here")
KO_LONG = "- " + KO_GOAL + ": " + "w" * 112
res, made, got = created(KO_LONG)
check("b create: the Korean label is two characters shorter than `Goal:`, so the relabelled line is judged for its length as stored", not isinstance(res, ToolError) and got.startswith("- Goal: ") and all(len(x) <= 120 for x in got.split("\n")), (str(res)[:200], got))

for name, desc, want in (("a wide colon", "- Goal\uff1a the run finishes\n- It lives here", "- Goal: the run finishes\n- It lives here"),
                         ("a wide colon after the Korean label", f"- {KO_GOAL}\uff1a the run finishes", "- Goal: the run finishes"),
                         ("a CRLF first bullet, the line ends kept", "- goal: the run finishes\r\n- It lives here\r\n", "- Goal: the run finishes\r\n- It lives here\r\n"),
                         ("an indented first bullet, the indent kept", "  - goal: the run finishes\n  - It lives here", "  - Goal: the run finishes\n  - It lives here"),
                         ("a bold phrase that holds the colon and the sentence", "- **Goal: the run finishes**\n- It lives here", "- Goal: the run finishes\n- It lives here"),
                         ("a bold label with the colon outside it", "- **Goal**: the run finishes\n- It lives here", "- Goal: the run finishes\n- It lives here"),
                         ("an italic phrase", "- *goal: the run finishes*\n- It lives here", "- Goal: the run finishes\n- It lives here")):
    got_bt = BT.relabel_goal(desc)
    check(f"b relabel: {name}", got_bt is not None and got_bt[0] == want, got_bt)
check("b relabel: a bold phrase that would be left open is not relabelled (the refusal shows the example instead); one opened and never closed leaves no mark", BT.relabel_goal("- **Goal: the run** and **more\n") is None and BT.relabel_goal("- Goal: **the run\n") is None and BT.relabel_goal("- **Goal: the run finishes\n")[0] == "- Goal: the run finishes\n", None)
check("b relabel: a bold phrase that closes before more words is left to the refusal (a mark inside the sentence the label's would have paired with)", BT.relabel_goal("- **Goal: x** more") is None, None)
res, made, got = created("- **Goal: the run** and more\n- It lives here")
check("b create: …and the refusal shows the first bullet as the goal, nothing stored", isinstance(res, ToolError) and "must open with its goal" in str(res), str(res)[:300])
check("b relabel: a bold close after a bold label is left to the refusal (the marks would not pair)", BT.relabel_goal("- **Goal:** x**") is None, None)
check("b relabel: the space before the bold close goes with it: no trailing space is stored", BT.relabel_goal("- **Goal: the run finishes **\n- It lives here")[0] == "- Goal: the run finishes\n- It lives here", BT.relabel_goal("- **Goal: the run finishes **\n- It lives here"))
check("b relabel: two dashes are no one spaced dash: not relabelled, no `- ` carried into the sentence", BT.relabel_goal("- Goal -- the run finishes") is None and BT.relabel_goal("- Goal \u2013\u2013 the run finishes") is None and BT.relabel_goal("- Goal - the run finishes")[0] == "- Goal: the run finishes", None)
for sep_name, sep in (("a vertical tab", "\x0b"), ("a form feed", "\x0c"), ("the line separator", "\u2028"), ("the paragraph separator", "\u2029"), ("a next-line mark", "\x85")):
    got_bt = BT.relabel_goal(f"- goal: the run finishes{sep}- It lives here")
    check(f"b relabel: {sep_name} ends the first bullet and stays where it was", got_bt is not None and got_bt[0] == f"- Goal: the run finishes{sep}- It lives here", got_bt)
    got_bt = BT.relabel_goal(f"- goal: the run - fine{sep}- It lives here")
    check(f"b relabel: …{sep_name} inside the sentence's neighbourhood leaves the words as they were", got_bt is not None and got_bt[0] == f"- Goal: the run - fine{sep}- It lives here", got_bt)
check("b relabel: a fenced block before the first real bullet is passed over, its lines untouched", BT.relabel_goal("```\n- goal: in a fence\n```\n- goal: the run finishes")[0] == "```\n- goal: in a fence\n```\n- Goal: the run finishes", None)
check("b relabel: a text whose only `- goal:` is in a fence has no bullet to relabel", BT.relabel_goal("```\n- goal: in a fence\n```\nprose") is None, None)
res, made, got = created("- **Goal: the run finishes**\n- It lives here")
check("b create: a bold phrase is stored with no stray marks", got == "- Goal: the run finishes\n- It lives here" and got.count("**") == 0, got)
res, made, got = created("  - goal: the run finishes\n  - It lives here")
check("b create: an indented first bullet keeps its indent, one fix, and every other line is as written", not isinstance(res, ToolError) and got.startswith("  - Goal: the run finishes") and "description-goal" in kinds(made), (str(res)[:200], got, made))
res, made, got = created("- goal: the run finishes\r\n- It lives here")
check("b create: a CRLF first bullet is stored with its line ends (CRLF kept) or put right, never merged", not isinstance(res, ToolError) and got.startswith("- Goal: the run finishes") and "It lives here" in got, (str(res)[:200], got))
res, made, got = created("- goal: x\u2028- b")
check("b create: a first bullet that ends in the line separator keeps what follows it as it was", not isinstance(res, ToolError) and "\u2028" in got and got.startswith("- Goal: x"), (str(res)[:200], got))
BODY113 = "a" * 50 + ". " + "b" * 61               # 113 characters
res, made, got = created("- " + KO_GOAL + ": " + BODY113 + "\n- It lives here")
check("b create: the relabel runs before the bullet split: a 113-character body after the Korean label (119 characters before, 121 after) is split, no stored line is over 120", not isinstance(res, ToolError) and got.startswith("- Goal: ") and all(len(x) <= 120 for x in got.split("\n")) and len(got.split("\n")) >= 3, (str(res)[:300], got))
_desc_cfg = _cfg.CFG.setdefault("description", {}); _was_bullets = _desc_cfg.get("require_bullets")
try:
    _desc_cfg["require_bullets"] = False
    res, made, got = created("- goal: the run finishes\n- It lives here")
    check("b create: with the bullet checks off a goal label is stored as written, no fix", not isinstance(res, ToolError) and got == "- goal: the run finishes\n- It lives here" and "description-goal" not in kinds(made), (str(res)[:200], got, made))
finally:
    if _was_bullets is None: _desc_cfg.pop("require_bullets", None)
    else: _desc_cfg["require_bullets"] = _was_bullets
res, made = upd(110, description="- goal: the thing works\n- Another line", sender="a script on testbox")
check("b update: a script sender's write (`a script on ...`) is left as written, no fix", not isinstance(res, ToolError) and "description-goal" not in kinds(made) and rd(110)["description"].startswith("- goal: the thing works"), (str(res)[:200], made))
item(113, desc="- Goal: the run finishes\n- It lives here")
res, made = upd(113, description="- goal: the run finishes\n- It lives here")
check("b update: a text that differs from the stored one only in the label's form changes nothing and counts no fix", kinds(made) == [] and rd(113)["description"] == "- Goal: the run finishes\n- It lives here", (str(res)[:200], made, rd(113)["description"]))
res, made = upd(113, description="- goal: the run ends\n- It lives here")
check("b update: …and one that also changes a word is a fix, stored with the new word", kinds(made) == ["description-goal"] and rd(113)["description"] == "- Goal: the run ends\n- It lives here", (str(res)[:200], made))

# the refusal shows the corrected description, and sent back as shown it goes through
SYM = "- The run fails when the disk is full\n- It lives here\n- Done when done"
res, made, got = created(SYM)
shown = "- Goal: The run fails when the disk is full\n- It lives here\n- Done when done"
check("b create refused: a first bullet that is no goal word: the refusal shows the description with that bullet as the goal", isinstance(res, ToolError) and "Send the description again with that bullet as the goal:\n" + shown + "\n" in str(res) and kinds(made) == [], str(res)[:500])
check("b …it says what to do when that bullet names a symptom, and keeps the rule and the retry hint", "move the bullet to a later bullet that opens `Problem:`" in str(res) and "The subject and the first bullet state the outcome wanted" in str(res) and "Retry the call" in str(res), str(res)[:900])
check("b …the refusal names no machine and no fleet tool", not re.search(r"\b(box-[a-d]|sala|salamander)\b", str(res), re.I), str(res)[:300])
n_before = len(list((T / "store").rglob("[0-9]*.json")))
res2, made2, got2 = created(shown)
check("b …resend the description as shown: it goes through, stored as shown", not isinstance(res2, ToolError) and got2 == shown, (str(res2)[:200], got2))
item(112, desc="- A thing\n- It lives here")
res, made = upd(112, description=SYM)
check("b update refused: the same example, and the stored text is unchanged", isinstance(res, ToolError) and "Send the description again with that bullet as the goal:\n" + shown in str(res) and rd(112)["description"] == "- A thing\n- It lives here", str(res)[:400])
res, made = upd(112, description=shown)
check("b …resend it as shown: it goes through", not isinstance(res, ToolError) and rd(112)["description"] == shown, str(res)[:300])
NEAR = "- " + "x" * 116                         # 118 characters: `- Goal: ` in front of it makes the line 126, and it has no place to be split
res, made, got = created(NEAR + "\n- It lives here")
check("b create refused: a first bullet that would be over the limit with the label in front, and cannot be split, shows no example to copy", isinstance(res, ToolError) and "must open with its goal" in str(res) and "Send the description again" not in str(res), str(res)[:400])
CLAUSE_TEXT = "the nightly run reads the whole table, " * 2 + "then writes the report to disk now ok"          # 115 characters: a bullet of 117 passes the form gate, `Goal: ` in front makes it 125, with commas to split at
res, made, got = created("- " + CLAUSE_TEXT + "\n- It lives here")
shown_long = "- Goal: " + CLAUSE_TEXT + "\n- It lives here"
check("b create refused: a first bullet that the bullet fix can split once the label is in front still shows its example", isinstance(res, ToolError) and "Send the description again with that bullet as the goal:\n" + shown_long + "\n" in str(res), str(res)[:600])
res2, made2, got2 = created(shown_long)
check("b …and resent as shown it goes through: split by the bullet fix, the goal kept first", not isinstance(res2, ToolError) and got2.startswith("- Goal: ") and all(len(x) <= 120 for x in got2.split("\n")), (str(res2)[:300], got2))
res, made, got = created("> only a quote line")
check("b create refused: no `- ` bullet at all shows no corrected description", isinstance(res, ToolError) and "no `- ` bullet" in str(res) and "Send the description again" not in str(res), str(res)[:300])
check("b the fix has no send-back check and invites no resend", "description-goal" not in CL.CHECKED and "description-goal" in CL.NO_RESEND, None)

# ================================================================ c. refusals that name the fix and show the corrected call; the corrected call goes through the same gate
from stackshot.model import said as SAID
from stackshot.service import wait_gates as WG
from stackshot.service import asks as ASKS
no_machine = lambda t: not re.search(r"\b(box-[a-d]|sala|salamander)\b", t, re.I)

# an ask in the wrong form: the test it failed and an ask that passes (the board-wide cases are in pilot_scenario)
def ask_msg(a):
    try:
        ASKS._gate_ask(a); return ""
    except ToolError as e:
        return str(e)
for name, a, why in (("a pipe between the parts", "Decide: ship it | Recommend: yes | Stakes: a week | By: Fri", "the parts are joined by \u201c|\u201d and the separator is \u201c · \u201d"),
                     ("a semicolon", "Decide: ship it; Recommend: yes; Stakes: a week; By: Fri", "the parts are joined by \u201c;\u201d"),
                     ("a line break", "Decide: ship it\nRecommend: yes\nStakes: a week\nBy: Fri", "it holds a line break, and an ask is one line"),
                     ("the By part left out", "Decide: ship it · Recommend: yes · Stakes: a week", "the part By is missing"),
                     ("two parts left out", "Decide: ship it · Recommend: yes", "the part Stakes is missing (and By)"),
                     ("too long", "Decide: " + "x" * 230 + " · Recommend: yes · Stakes: a week · By: Fri", "it is 282 characters, and the limit is 240")):
    m = ask_msg(a)
    check(f"c ask: {name}: the refusal names the test it failed", m.startswith('Refused: ask must read "') and f"This ask fails because {why}" in m, m[:300])
    shown_a = m.split(":\n")[-1]
    check(f"c ask: {name}: …and shows an ask that the same gate takes as it stands", ASKS._gate_ask(shown_a) == shown_a, m[-200:])
check("c ask: the pipe case shows the writer's own parts in the form", "Your ask in the form, to send again:\nDecide: ship it · Recommend: yes · Stakes: a week · By: Fri" in ask_msg("Decide: ship it | Recommend: yes | Stakes: a week | By: Fri"), None)
check("c ask: the refusals name no machine and no fleet tool", no_machine(ask_msg("x")), None)

# said: not valid JSON
try:
    SAID.parse("said=[{tag: Acked-by, quote: go on}]"); said_msg = ""
except ValueError as e:
    said_msg = str(e)
check("c said: a text that is not JSON is refused naming what it started with", "not valid JSON (it starts 'said=[{tag: Acked-by, quote: go on}]')" in said_msg, said_msg[:200])
check("c said: …and shows the exact shape as JSON, with its keys and values in double quotes", SAID.JSON_EXAMPLE in said_msg and '"tag": "Acked-by"' in said_msg and '"quote"' in said_msg and '"msg"' in said_msg, said_msg[-300:])
shown_said = json.loads(re.search(r'said=(\[\{"tag".*?\}\])', said_msg).group(1)) if re.search(r'said=(\[\{"tag".*?\}\])', said_msg) else None
check("c said: the shown example is itself valid JSON", isinstance(shown_said, list) and shown_said and shown_said[0]["tag"] == "Acked-by", said_msg[-300:])
got_said = SAID.parse(json.dumps(shown_said)) if shown_said else []
check("c said: …and resent as shown, the shape gate takes it as one entry", len(got_said) == 1 and got_said[0]["tag"] == "Acked-by", got_said)
check("c said: …the text names no machine and no fleet tool", no_machine(said_msg), said_msg)
try:
    SAID.parse("x" * 200); long_said = ""
except ValueError as e:
    long_said = str(e)
check("c said: what it started with is cut at 60 characters", f"it starts {'x' * 60!r})" in long_said and "x" * 61 not in long_said, long_said[:160])

# an option without its label or its line
def opt_msg(opts):
    try:
        WG._gate_options(opts); return ""
    except ToolError as e:
        return str(e)
m1 = opt_msg([{"label": "Approve"}, {"label": "Decline", "line": "Keep it", "recommended": True}])
check("c option: a missing line is named as the line, with the option's place", m1.startswith("Refused: option 1 has no line.") and "no label" not in m1, m1[:200])
m2 = opt_msg([{"label": "Approve", "line": "Ship it", "recommended": True}, {"line": "Keep it"}])
check("c option: a missing label is named as the label", m2.startswith("Refused: option 2 has no label."), m2[:200])
m3 = opt_msg([{"name": "Approve", "description": "Ship it"}, {"title": "Decline", "text": "Keep it"}])
check("c option: both missing: named together, with the keys it did carry", m3.startswith("Refused: option 1 has no label and no line. It carries the keys 'name', 'description';") and "label, line and recommended only" in m3, m3[:300])
ex_opts = json.loads(m3.split("An example that passes: options=", 1)[1])
check("c option: the example in the refusal is a valid list", len(ex_opts) == 2 and sum(o["recommended"] for o in ex_opts) == 1, ex_opts)
check("c option: …and resent as shown, the same gate takes it", len(WG._gate_options(json.dumps(ex_opts))) == 2, None)
check("c option: …the form line stays and no machine or fleet tool is named", "recommended\": true" in m3 and no_machine(m3), m3)

# a wait_basis the rule does not take: the forms and the corrected call
item(120)
res, made = upd(120, hold=True, until=local_day(40), wait_basis="waiting for the vendor reply")
basis_msg = str(res) if isinstance(res, ToolError) else ""
def shown_basis(m):
    """the value the refusal shows for wait_basis, decoded as the JSON string it is"""
    q = re.search(r'Send the same call again with wait_basis=("(?:[^"\\]|\\.)*"), the date being the day the wait ends', m)
    return json.loads(q.group(1)) if q else None
corr = shown_basis(basis_msg)
check("c wait_basis: a basis with no date names the forms it takes", 'The forms it takes are "<what happens> YYYY-MM-DD" and, for a window the work itself needs, "<what the window collects> ends YYYY-MM-DD".' in basis_msg, basis_msg[-400:])
check("c wait_basis: …and shows the call with the writer's own words and the wake's day filled in", corr == f"waiting for the vendor reply {local_day(40)}", basis_msg[-300:])
res, made = upd(120, hold=True, until=local_day(40), wait_basis=corr or "")
check("c wait_basis: …resent as shown, it goes through and stores the basis", not isinstance(res, ToolError) and W.basis_of(mt(120)) == f"waiting for the vendor reply {local_day(40)}", (str(res)[:200], mt(120)))
item(121)
res, made = upd(121, hold=True, until=local_day(40), wait_basis=f"the vendor answered on {local_day(2)}")
basis_msg2 = str(res) if isinstance(res, ToolError) else ""
corr2 = shown_basis(basis_msg2)
check("c wait_basis: a basis whose date is off shows a placeholder for the words and the wake's day", corr2 == f"<what the wait stands on> {local_day(40)}", basis_msg2[-300:])
res, made = upd(121, hold=True, until=local_day(40), wait_basis=(corr2 or "").replace("<what the wait stands on>", "the vendor answers"))
check("c wait_basis: …with the placeholder replaced by words, the shown call goes through", not isinstance(res, ToolError) and bool(W.basis_of(mt(121))), (str(res)[:200], mt(121)))
check("c wait_basis: …the text names no machine and no fleet tool", no_machine(basis_msg) and no_machine(basis_msg2), basis_msg)


# a basis that holds a quote or a line break: the shown call reads as one string
item(122)
EVIL = 'waiting"; hold=false, clear_wait=true'
res, made = upd(122, hold=True, until=local_day(40), wait_basis=EVIL)
basis_msg3 = str(res) if isinstance(res, ToolError) else ""
check("c wait_basis: a basis with a quote in it is shown inside one string, the quote escaped", shown_basis(basis_msg3) == f"{EVIL} {local_day(40)}" and 'wait_basis="waiting"; hold=false' not in basis_msg3, basis_msg3[-300:])
res, made = upd(122, hold=True, until=local_day(40), wait_basis="waiting for\nthe vendor reply")
basis_msg4 = str(res) if isinstance(res, ToolError) else ""
check("c wait_basis: …and a line break in it is flattened before it is shown, so the shown value is one line", shown_basis(basis_msg4) == f"waiting for the vendor reply {local_day(40)}", basis_msg4[-300:])

# an ask the length refuses: its parts are not built, and a long run of separators costs next to nothing
RUN = "Decide: x | Recommend: y | Stakes: z | By: " + "|" * 200000 + "x"          # all four parts, the last ends in a run and then a letter: the case that costs the square of the run
t0 = time.perf_counter(); m_run = ask_msg(RUN); took = time.perf_counter() - t0
check("c ask: a 200,000-character run of separators is refused for its length in well under a second", "characters, and the limit is" in m_run and took < 1.0, (took, m_run[:120]))
RUN2 = "Decide: x | Recommend: " + "-" * 100000 + "x | Stakes: a | By: b"
t0 = time.perf_counter(); m_run2 = ask_msg(RUN2); took2 = time.perf_counter() - t0
check("c ask: …so is one with all four labels and a long run in a part", "characters, and the limit is" in m_run2 and took2 < 1.0, (took2, m_run2[:160]))
m_edge = ask_msg("Decide: " + "x" * 150 + " ,;| Recommend: yes | Stakes: a week | By: Fri")
check("c ask: an ask within the limit with a run of separators after a part is cleaned: the parts are cut of them", ("Decide: " + "x" * 150 + " · Recommend: yes") in m_edge, m_edge[-300:])
PADDED = "Decide:" + " " * 100 + "ship it ; Recommend: yes | Stakes: a week" + " " * 150 + "| By: Fri"          # about 300 raw characters, 60 once the white space is collapsed
m_pad = ask_msg(PADDED)
check("c ask: an ask over the limit as written whose collapsed form fits still shows the writer's own parts in the form", len(PADDED.strip()) > 240 and "it is " in m_pad and "Your ask in the form, to send again:\nDecide: ship it · Recommend: yes · Stakes: a week · By: Fri" in m_pad, (len(PADDED), m_pad[-300:]))
check("c ask: …and what it shows goes through the same gate", ASKS._gate_ask(m_pad.split(":\n")[-1]) == m_pad.split(":\n")[-1], m_pad[-200:])
t0 = time.perf_counter(); m_pad2 = ask_msg("Decide: x" + " " * 200000 + "| Recommend: y | Stakes: z | By: w"); took3 = time.perf_counter() - t0
check("c ask: …and a long run of white space is as cheap", took3 < 1.0 and "Your ask in the form" in m_pad2, (took3, m_pad2[-200:]))
_tail = " | Recommend: yes | Stakes: a week | By: Fri"
EXACT = "Decide: " + "x" * (240 - len("Decide: ") - len(_tail)) + _tail          # 240 characters collapsed: exactly the limit
check("c ask: an ask whose collapsed form is exactly the limit still shows its parts in the form", len(EXACT) == 240 and ("Your ask in the form, to send again:\nDecide: " + "x" * (240 - len("Decide: ") - len(_tail)) + " · Recommend: yes") in ask_msg(EXACT.replace(" | ", "  |   ")), None)
m_over = ask_msg("Decide: " + "x" * (241 - len("Decide: ") - len(_tail)) + _tail)
check("c ask: …and one a character longer is refused for its length and shows the example", "it is 241 characters" in m_over and "An ask that passes, to copy the shape from" in m_over, m_over[-300:])
m_sep = ask_msg("Decide: ship it ,;/ Recommend: yes - Stakes: a week \u2014 By: Fri")
check("c ask: separators at the end of a part (comma, dash, em dash, semicolon, slash) are all cut off the corrected ask", m_sep.endswith("Decide: ship it · Recommend: yes · Stakes: a week · By: Fri"), m_sep[-200:])

# an option key shown back: cut, quoted, counted
m_key = opt_msg([{"x" * 5000: "a", "line": "b"}, {"label": "Decline", "line": "Keep it"}])
check("c option: a huge key is shown cut at 30 characters", "x" * 30 in m_key and "x" * 31 not in m_key and len(m_key) < 1200, len(m_key))
m_key2 = opt_msg([{'a"b\nc': "a", "line": "b"}, {"label": "Decline", "line": "Keep it"}])
check("c option: a key with a quote and a line break is shown as a quoted string with the break escaped, on one line", "'a\"b\\nc'" in m_key2 or '"a\\"b\\nc"' in m_key2 or "a\"b\\nc" in m_key2, m_key2[:300])
check("c option: …and the refusal stays one line up to its example", "\n" not in m_key2.split("An example that passes:")[0], m_key2[:300])
m_key3 = opt_msg([{"k1": 1, "k2": 2, "k3": 3, "k4": 4, "k5": 5, "k6": 6}, {"label": "Decline", "line": "Keep it"}])
check("c option: more than four other keys are counted: the first four, and the rest as a number", "It carries the keys 'k1', 'k2', 'k3', 'k4' and 2 more;" in m_key3, m_key3[:300])
m_key4 = opt_msg([{"k1": 1, "k2": 2, "k3": 3, "k4": 4}, {"label": "Decline", "line": "Keep it"}])
check("c option: …exactly four are all named, with no count", "It carries the keys 'k1', 'k2', 'k3', 'k4';" in m_key4 and "more" not in m_key4.split("An example")[0], m_key4[:300])

# said: a text with a quote and a line break is shown quoted, as one string
try:
    SAID.parse('said=["go\non", \'x\']'); said_msg2 = ""
except ValueError as e:
    said_msg2 = str(e)
check("c said: what it started with is shown with its quote marks and line break escaped (repr), on one line", "it starts " + repr('said=["go\non", \'x\']') + ")" in said_msg2 and "\n" not in said_msg2.split("); pass a list")[0], said_msg2[:200])

print(("ok" if not fails else "FAILED") + f": refusal hints scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
