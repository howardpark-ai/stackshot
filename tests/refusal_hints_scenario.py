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

print(("ok" if not fails else "FAILED") + f": refusal hints scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
