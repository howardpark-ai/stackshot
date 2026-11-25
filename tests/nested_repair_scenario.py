"""Scenario test for the repair of long steps that were split into flat lines before a list under a lead-in became one line with sub-lines — fixture data, in-process, no live store, no network.

A long step used to split into one flat line of next per action, a lead-in that ends with a colon and each item of its list included. Now such a list is one line with its items as indented `- ` lines under
it, ticked as one step. model/nested_repair.py reads an open item that was split the old way in the new shape; the server's start-up pass (migrations._nested_steps_pass) runs it once before it serves, and
tools/nested_steps_report.py is its read-only dry run. The fixtures are made through the tool (a short step, then the flat lines as next), so the checklist, the writers and the record of the split are the real ones.

  1  the shape: a lead-in with three items and a closing sentence, and a lead-in with items and no closing sentence, come out as the new split makes them (the same lines, byte for byte, as step_split gives for the same text);
     the record of the split follows; the summary line, the other writer's lines and the clocks are untouched
  2  ticks: an item done before stays done on the checklist, the open lines around it are nested; a line dropped likewise
  3  what is left alone: lines no split made (not in the record), lines of two writers, no colon, a list of one line, a closed item, a line waiting on a proof, a line with sub-lines already
  4  idempotent: a second pass finds nothing and writes nothing; a dry run writes nothing and says what the pass will do
  5  the start-up pass: the rows, the one log line, nothing else in the store changed; the report tool (read only, --json, a config that is not there)
  7  the words are kept byte for byte (`**`, double spaces); 8  an earlier open line that reads like an item is not the one taken out; 9  one bad item file never skips the others;
  10 the summary and the server's line for it follow the lines; 11 the undo record (written first, a long one says so, one that cannot be written leaves the item as it is)

    tests/run-suite nested_repair        → exit 0 / 1"""
import contextlib, io, json, logging, os, pathlib, re, subprocess, sys, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="nestedrepairtest-"); T = pathlib.Path(tmp)
BOARD = "https://board.example.org"

toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's session store (session links off)
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
for pat, rep in ((r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]'), (r'(?m)^board_url = "[^"]*"', f'board_url = "{BOARD}"'),
                 (r'(?m)^base_url = "[^"]*"', f'base_url = "{BOARD}"'), (r'(?m)^owner = "the owner"', 'owner = "Oliver"'),
                 (r'(?m)^ui_open = true', 'ui_open = false'), (r'(?m)^sync = false', 'sync = true'), (r'(?m)^issues_repo = ""', 'issues_repo = "o/r"'),
                 (r'(?m)^api_url = "[^"]*"', 'api_url = "http://127.0.0.1:9"'), (r'(?m)^token_file = ""', f'token_file = "{tmp}/github.token"')):
    toml, n = re.subn(pat, rep, toml); assert n == 1, pat
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "github.token").write_text("test-token\n")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "brain/projects", "secrets"): (T / d).mkdir(parents=True)
OWNER = "00000000-0000-4000-8000-000000000001"
AGENT = "00000000-0000-4000-8000-000000000002"
OTHER = "00000000-0000-4000-8000-000000000003"
now = time.time()
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({OWNER: {"name": "home-here", "machine": "a", "seen": now}, AGENT: {"name": "home-agent", "machine": "a", "seen": now}, OTHER: {"name": "home-other", "machine": "a", "seen": now}}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                "session": "home-agent", "status": "active", "board": [], "board_open": 0}}}))
DESC = "- Goal: A thing, finished when it works"
def item(i, status="open", **meta):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item a{i}", "description": DESC, "status": status,
                                                     "updated": now - 3600, "state_updated": now - 3600, "confirmed": now - 3600,
                                                     "metadata": {"owner": OWNER, "project": "projects/alpha", "needs": ["home-agent"], "next": "home-agent: build it", **meta}}))
for i in range(1, 30):
    item(i)
(T / "store/next-id").write_text("60"); (T / "store/anchors.json").write_text("{}")
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n\n# Alpha\n")
git = lambda *a: subprocess.run(["git", "-C", f"{tmp}/store", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], check=True, capture_output=True)
git("init", "-q"); git("add", "-A"); git("commit", "-q", "-m", "fixture")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:1200]}" if got is not None else ""))
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
def mt(i): return rd(i)["metadata"]
def raw(i): return (T / f"store/a/{i}.json").read_text()

from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route
from stackshot.model import steps as S; from stackshot.model import nextlines as NL; from stackshot.model import step_split as SS; from stackshot.model import nested_repair as NR
from stackshot.anchors.anchorhub import core
os.makedirs(core.ADIR, exist_ok=True)
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
from stackshot.web.tools import update as _wt_update
from stackshot.service import migrations as migsvc
from stackshot.service import telling
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._refuse_if_owing = lambda debtor: None
telling.tell_woken = lambda gid, owner, note, tag="wake": None
def upd(i, **kw): return _wt_update.stackshot_update(f"a{i}", sender="home-agent", **kw)
def st(i): return [(x["status"], x["text"]) for x in S.view(mt(i), keeper=OWNER)]
def his(i): return [(s, t) for s, t in st(i) if t.startswith("Oliver:")]
def his_open(i): return [t for s, t in his(i) if s == "open"]
LR = 200

# the text the new split reads, and the same text as the OLD split wrote it: one flat line per action, each opening with his name
ITEMS = ["open the setup page of the vendor", "copy the key from the page into the form", "press save and look for the green mark"]
LEAD = "Please do these things in order:"
CLOSING = "Then tell the session it went well"
TEXT_END = LEAD + " " + " ".join(f"{n}) {t}" for n, t in enumerate(ITEMS, 1)) + ". " + CLOSING + "."
TEXT_NONE = LEAD + " " + " ".join(f"{n}) {t}" for n, t in enumerate(ITEMS, 1))
NEW_END = SS.split_step(TEXT_END, LR)[1]; NEW_NONE = SS.split_step(TEXT_NONE, LR)[1]
check("0 the fixtures are what the new split makes: the lead-in with three sub-lines and the closing line; the lead-in alone", len(NEW_END) == 2 and len(NEW_NONE) == 1 and NEW_END[0] == NEW_NONE[0] and NEW_END[0].count("\n  - ") == 3, (NEW_END, NEW_NONE))


def old_split(i, flat, summary, step_lines=True):
    """An item as the old split left it: the step (a summary), the server's line for it, and `flat` as open lines of his written by the sender, the record of the split naming them."""
    item(i)
    upd(i, step=summary)
    upd(i, next=mt(i)["next"] + "\n" + "\n".join(f"Oliver: {x}" for x in flat))
    d = rd(i)
    if step_lines: d["metadata"]["step_lines"] = [S.key(f"Oliver: {x}") for x in flat]
    (T / f"store/a/{i}.json").write_text(json.dumps(d))
def nest_now(i):
    d = rd(i); out = NR.nest(d["metadata"], OWNER); (T / f"store/a/{i}.json").write_text(json.dumps(d)); return out
def settle(i, line, how):       # the line of his marked done or dropped on the item (as a tick or a drop leaves it), and gone from next
    d = rd(i); m_ = d["metadata"]
    for e_ in m_["steps"]:
        if e_["text"] == f"Oliver: {line}": e_["status"], e_["by"], e_["at"] = how, "Oliver", now
    m_["next"] = "\n".join(x for x in m_["next"].splitlines() if x != f"Oliver: {line}")
    (T / f"store/a/{i}.json").write_text(json.dumps(d))
def edit(i, f):
    d = rd(i); f(d); (T / f"store/a/{i}.json").write_text(json.dumps(d))
def kept(i, f):      # a case where nothing may change: the file as it was, byte for byte, after nest_now
    was = raw(i); out = f(); return out == [] and raw(i) == was
def lead_with(*items): return f"Oliver: {LEAD}" + "".join(f"\n  - {x}" for x in items)
FLAT_END = [LEAD, *ITEMS, CLOSING]
FLAT_NONE = [LEAD, *ITEMS]
SUM_END, SUM_NONE = f"{LEAD} (+4 more)", f"{LEAD} (+3 more)"      # the summaries the old split made
NOW_END, NOW_NONE = f"{LEAD} (+1 more)", LEAD                       # what the repair makes of them: the items are no lines of the top level any more (nothing after the lead-in: no tail)

# ---- 1. the shape
old_split(1, FLAT_END, SUM_END)
was1 = rd(1)
check("1 the old shape is what the fixture says: the server's line for the summary and five flat lines of his, all open, all in the record of the split",
      his_open(1) == [f"Oliver: {SUM_END}", *(f"Oliver: {x}" for x in FLAT_END)] and len(mt(1)["step_lines"]) == 5, st(1))
plan1 = NR.plan(mt(1), OWNER)
check("1 plan: one list, the lead-in's line, the three items, and the closing sentence left as a line of its own", len(plan1) == 1 and plan1[0][0] == f"Oliver: {LEAD}" and plan1[0][1] == [f"Oliver: {x}" for x in ITEMS] and plan1[0][2] == [f"Oliver: {CLOSING}"], plan1)
check("1 plan: changes nothing (it is the dry run)", rd(1) == was1, None)
rep1 = nest_now(1)
check("1 nest: the report names the lead-in, the three items and the line that stays", rep1 == [{"lead": f"Oliver: {LEAD}", "items": ITEMS, "left": [f"Oliver: {CLOSING}"]}], rep1)
check("1 …next is the agent's line, the server's line for the summary, the lead-in with its three sub-lines as one entry, then the closing sentence: the same two lines the new split makes for the text, byte for byte",
      NL.split(mt(1)["next"]) == ["home-agent: build it", f"Oliver: {NOW_END}", *NEW_END], (NL.split(mt(1)["next"]), NEW_END))
check("1 …the checklist holds the lead-in with its sub-lines as ONE open step, the closing sentence, the summary line and the agent's line: four steps, none for an item",
      st(1) == [("open", "home-agent: build it"), ("open", f"Oliver: {NOW_END}"), *(("open", x) for x in NEW_END)], st(1))
check("1 …the record of the split follows the lines: the key of the lead-in with its sub-lines and of the closing sentence, none for the items", mt(1)["step_lines"] == [S.key(x) for x in NEW_END], mt(1)["step_lines"])
wr = dict(NL.resolve(mt(1), OWNER))
check("1 …the lead-in line and the closing sentence keep their writer (the sender); the items are no lines of next to have one", wr.get(NEW_END[0]) == AGENT and wr.get(NEW_END[1]) == AGENT and not any(k.startswith(f"Oliver: {ITEMS[0]}") for k in wr), wr)
check("1 …nothing else changed: the state, the owner, the clocks (the summary and the server's line for it say (+1 more) now: the next check)",
      {k: v for k, v in rd(1).items() if k != "metadata"} == {k: v for k, v in was1.items() if k != "metadata"}
      and {k: v for k, v in mt(1).items() if k not in ("next", "next_by", "steps", "step_lines", "step", "owner_step")} == {k: v for k, v in was1["metadata"].items() if k not in ("next", "next_by", "steps", "step_lines", "step", "owner_step")}, None)
from stackshot.web.ui import render as ui_render
bd = ui_render.Board(str(T / "store"))
check("1 …and the board's list for his step is two entries: the lead-in with its sub-lines under it, then the closing sentence", [f for f, _ in bd.your_steps(bd.item("a1"))] == [LEAD, CLOSING], None)

old_split(2, FLAT_NONE, SUM_NONE)
nest_now(2)
check("1 a lead-in with items and no closing sentence: every line after the lead-in is an item: one line with three sub-lines, the same line the new split makes",
      NL.split(mt(2)["next"]) == ["home-agent: build it", f"Oliver: {NOW_NONE}", *NEW_NONE] and mt(2)["step_lines"] == [S.key(NEW_NONE[0])] and [t for s_, t in st(2) if s_ == "open"].count(NEW_NONE[0]) == 1, (NL.split(mt(2)["next"]), mt(2)["step_lines"]))
CAPS = [ITEMS[0], "Copy the key from the page into the form", "Press save and look for the green mark", CLOSING]
old_split(3, [LEAD, *CAPS], SUM_END)
nest_now(3)
check("1 …when a line before the last also starts with a capital, the last is no closing sentence: all four lines are items", NL.split(mt(3)["next"])[2:] == [lead_with(*CAPS)], NL.split(mt(3)["next"]))

# ---- 2. ticks: a line done or dropped before stays on the checklist as it was, the open lines around it are nested
old_split(4, FLAT_END, SUM_END)
settle(4, ITEMS[0], "done")
nest_now(4)
check("2 a done item stays done on the checklist (as its own line), and the open lines around it are nested: the lead-in holds the two items still open, the closing sentence is its own line",
      ("done", f"Oliver: {ITEMS[0]}") in st(4) and ("open", lead_with(ITEMS[1], ITEMS[2])) in st(4) and ("open", f"Oliver: {CLOSING}") in st(4) and len(st(4)) == 5, st(4))
check("2 …the done line is the one that was ticked: its mark, who ticked it and when, untouched", [x for x in mt(4)["steps"] if x["text"] == f"Oliver: {ITEMS[0]}"] == [x for x in rd(4)["metadata"]["steps"] if x["text"] == f"Oliver: {ITEMS[0]}" and x["status"] == "done" and x["by"] == "Oliver"], mt(4)["steps"])
old_split(5, FLAT_END, SUM_END)
settle(5, ITEMS[1], "dropped")
settle(5, CLOSING, "done")
nest_now(5)
check("2 a dropped item and a done closing sentence stay as they are; the lead-in takes the two items still open", ("dropped", f"Oliver: {ITEMS[1]}") in st(5) and ("done", f"Oliver: {CLOSING}") in st(5)
      and ("open", lead_with(ITEMS[0], ITEMS[2])) in st(5), st(5))
old_split(6, FLAT_END, SUM_END)
settle(6, LEAD, "done")
check("2 a lead-in done before (nothing opens a list now): the lines after it are no list, nothing is changed", NR.plan(mt(6), OWNER) == [] and kept(6, lambda: nest_now(6)), st(6))

# ---- 3. what is left alone
old_split(10, FLAT_END, SUM_END, step_lines=False)
check("3 lines no split made (the record of the split is not on the item: a writer's own flat lines) are never read as a list", kept(10, lambda: nest_now(10)), None)
old_split(11, ["Do these in order", *ITEMS, CLOSING], "Do these in order (+5 more)")
check("3 a flat run with no colon at the end of any line is no list under a lead-in: left as the old split made it", kept(11, lambda: nest_now(11)), None)
old_split(12, [LEAD, ITEMS[0]], f"{LEAD} (+1 more)")
check("3 a lead-in with one line after it is no list: left as it is", kept(12, lambda: nest_now(12)), None)
old_split(13, FLAT_END, SUM_END)
edit(13, lambda d: d["metadata"].update(next_by=[[OTHER if k == NL.key_of(f"Oliver: {ITEMS[1]}") else w, k] for w, k in d["metadata"]["next_by"]]))
check("3 lines of two writers are not one list: left as they are", kept(13, lambda: nest_now(13)), NL.resolve(mt(13), OWNER))
old_split(14, FLAT_END, SUM_END)
edit(14, lambda d: d.update(status="completed"))
was14 = raw(14)
check("3 a closed item is not the pass's: the pass finds nothing in it", all(r["gid"] != "a14" for r in migsvc._nested_steps_pass(apply=False)), None)
old_split(15, FLAT_END, SUM_END)
edit(15, lambda d: d["metadata"].update(step_proof={S.key(f"Oliver: {ITEMS[1]}"): {"kind": "x"}}))
check("3 a run that holds a line a proof waits on is left as it is (the proof ticks that line by its words)", kept(15, lambda: nest_now(15)), None)
check("3 a line that has sub-lines already is no single line, it starts no run: a nested item is left as it is", NR.plan(mt(1), OWNER) == [] and kept(1, lambda: nest_now(1)), None)
old_split(17, ["Read the notice first", LEAD, *ITEMS], "Read the notice first (+4 more)")
nest_now(17)
check("3 a line before the lead-in in the run stays a line of its own, the lead-in takes the items after it", NL.split(mt(17)["next"])[2:] == ["Oliver: Read the notice first", lead_with(*ITEMS)], NL.split(mt(17)["next"]))
old_split(18, [LEAD, *ITEMS, "Then pay by card", "Then tell the session"], "Please (+5 more)")
nest_now(18)
check("3 the last line is a closing sentence only when it alone starts with a capital: here two lines do, so all five lines after the lead-in are items (the one guess, stated)",
      NL.split(mt(18)["next"])[2:] == [lead_with(*ITEMS, "Then pay by card", "Then tell the session")], NL.split(mt(18)["next"]))

# ---- 4. idempotent, and the dry run
old_split(20, FLAT_END, SUM_END)
old_split(21, FLAT_NONE, SUM_NONE)
old_split(22, FLAT_END, SUM_END)
settle(22, ITEMS[0], "done")
snap = lambda: {p.name: p.read_text() for p in (T / "store/a").glob("*.json")}
s0 = snap()
dry = migsvc._nested_steps_pass(apply=False)
check("4 the dry run lists the three items that hold a flat list (a20, a21, a22) and no other, and writes nothing", sorted({r["gid"] for r in dry}) == ["a20", "a21", "a22"] and snap() == s0, ([r["gid"] for r in dry], snap() == s0))
check("4 …each row has the lead-in, the items that go under it and the lines that stay", [r for r in dry if r["gid"] == "a20"][0]["lead"] == f"Oliver: {LEAD}" and [r for r in dry if r["gid"] == "a20"][0]["items"] == ITEMS
      and [r for r in dry if r["gid"] == "a20"][0]["left"] == [f"Oliver: {CLOSING}"] and [r for r in dry if r["gid"] == "a21"][0]["left"] == [] and [r for r in dry if r["gid"] == "a22"][0]["items"] == ITEMS[1:], dry)

check("4 …and the dry run writes no undo record (no file under the state folder)", not (T / "state/migration/nested_steps.jsonl").exists(), None)

# ---- 5. the tool
tool = os.path.join(STACK, "stackshot/tools/nested_steps_report.py"); cfg = f"{tmp}/stackshot.toml"
def run(*a): return subprocess.run([sys.executable, tool, *a], capture_output=True, text=True, env={**os.environ}, timeout=300)
d1 = run("--config", cfg)
lines_ = [x for x in d1.stdout.splitlines() if x.strip()]
check("5 the report tool: exit 0, one line for each list to nest, the count on stderr, nothing written", d1.returncode == 0 and len(lines_) == 3 and all(f'"Oliver: {LEAD}"' in x and "takes" in x for x in lines_) and "3 lists to nest; nothing written" in d1.stderr and snap() == s0, (d1.returncode, d1.stdout, d1.stderr[-400:]))
dj = run("--config", cfg, "--json")
rows = json.loads(dj.stdout) if dj.returncode == 0 else []
check("5 …--json is the rows of the dry run", [r["gid"] for r in rows] == ["a20", "a21", "a22"] and rows == dry, dj.stdout[:500])
check("5 …it has no --apply: the server is the only writer", run("--apply").returncode == 2 and snap() == s0, None)
nc = run("--config", f"{tmp}/no-such.toml")
check("5 …a config that is not there is an error", nc.returncode == 2 and "not a file" in nc.stderr, (nc.returncode, nc.stderr))

# ---- 6. the start-up pass
buf = io.StringIO()
with contextlib.redirect_stderr(buf): got = migsvc._nested_steps_pass()
log = buf.getvalue()
check("6 the start-up pass nests the three items (the rows the dry run listed) and logs one line with the counts", [r["gid"] for r in got] == ["a20", "a21", "a22"] and sum(1 for x in log.splitlines() if "migrate: nested steps:" in x) == 1 and "3 list(s) of 3 open item(s)" in log and "(8 lines nested)" in log, (got, log[-500:]))
check("6 …a20 is the new split's own lines, byte for byte; a21 the lead-in alone; a22 keeps its done item and nests the two open ones",
      NL.split(mt(20)["next"])[2:] == NEW_END and NL.split(mt(21)["next"])[2:] == NEW_NONE and ("done", f"Oliver: {ITEMS[0]}") in st(22) and ("open", lead_with(ITEMS[1], ITEMS[2])) in st(22), (st(20), st(21), st(22)))
def apart(d): d = json.loads(json.dumps(d)); [d["metadata"].pop(k, None) for k in ("next", "next_by", "steps", "step_lines", "step", "owner_step")]; d.pop("activity", None); return d
check("6 …nothing else in those files changed: the same fields and clocks (the activity clock apart), the records of the other items byte for byte",
      all(apart(json.loads(s0[f"{i}.json"])) == apart(rd(i)) for i in (20, 21, 22)) and all(snap()[n] == s0[n] for n in s0 if n not in ("20.json", "21.json", "22.json")) and set(snap()) == set(s0), None)
s1 = snap()
buf = io.StringIO()
with contextlib.redirect_stderr(buf): again = migsvc._nested_steps_pass()
check("6 a second start is idempotent: it nests nothing, writes no file and logs nothing", again == [] and snap() == s1 and "nested steps" not in buf.getvalue(), (again, buf.getvalue()))
check("6 …and the dry run finds nothing", migsvc._nested_steps_pass(apply=False) == [] and run("--config", cfg).stdout.strip() == "" and "0 lists to nest" in run("--config", cfg).stderr, None)
old_split(23, FLAT_END, SUM_END)
check("6 a later start nests an item split the old way meanwhile, and only it", [r["gid"] for r in migsvc._nested_steps_pass()] == ["a23"] and NL.split(mt(23)["next"])[2:] == NEW_END, None)

# ---- 7. the words are kept: an item's text comes out byte for byte (no `**` removed, no spaces collapsed)
def flat_raw(i, flat, summary, before=(), writer=AGENT):
    """An item as the old split left it, with the lines put in the file as they are written (the tool would not change them, but this is the stored text itself): `before` are other open lines ahead of the run."""
    item(i); upd(i, step=summary)
    def f(d):
        m_ = d["metadata"]; add = [*before, *(f"Oliver: {x}" for x in flat)]
        m_["next"] = m_["next"] + "\n" + "\n".join(add)
        m_["next_by"] = list(m_.get("next_by") or []) + [[writer, NL.key_of(e)] for e in add]
        m_["step_lines"] = [S.key(f"Oliver: {x}") for x in flat]
    edit(i, f)
RAW = ["run `git add **/*.md`", "run `python -c 'print(2**8)'`", "run `grep  -e  a  b`", "mark the **vendor** page done"]
flat_raw(30, [LEAD, *RAW], f"{LEAD} (+4 more)")
check("7 the fixture: five flat lines as written, `**`, double spaces and all", [x for x in NL.split(mt(30)["next"])[2:]] == [f"Oliver: {x}" for x in (LEAD, *RAW)], NL.split(mt(30)["next"]))
plan30 = NR.plan(mt(30), OWNER)
check("7 plan: the items are the lines as they stand (the opener off, nothing else)", len(plan30) == 1 and [NR._body(x) for x in plan30[0][1]] == RAW, plan30)
rep30 = nest_now(30)
check("7 the report says the items byte for byte", len(rep30) == 1 and rep30[0]["items"] == RAW, rep30)
want30 = f"Oliver: {LEAD}" + "".join(f"\n  - {x}" for x in RAW)
check("7 `git add **/*.md`, `print(2**8)`, `grep  -e  a  b` and a bold word are in the sub-lines exactly as they were: the whole entry equals the text built from the raw lines",
      NL.split(mt(30)["next"])[2:] == [want30], NL.split(mt(30)["next"]))
nx30 = mt(30)["next"]
check("7 …each of the four, spelled out: the stars, the spaces and the marks are all there; the forms the key would make are not",
      "\n  - run `git add **/*.md`" in nx30 and "\n  - run `python -c 'print(2**8)'`" in nx30 and "\n  - run `grep  -e  a  b`" in nx30 and "\n  - mark the **vendor** page done" in nx30
      and "git add /*.md" not in nx30 and "print(28)" not in nx30 and "grep -e a b" not in nx30 and "mark the vendor page" not in nx30, nx30)
check("7 …the checklist holds the same text for the lead-in step (open, once)", [t for s_, t in st(30) if s_ == "open"].count(want30) == 1, st(30))
check("7 …and the lead-in's key in the record of the split is the key of that text", S.key(want30) in mt(30)["step_lines"], mt(30)["step_lines"])
was30 = raw(30)
check("7 a second pass over it changes nothing, byte for byte", kept(30, lambda: nest_now(30)) and NR.plan(mt(30), OWNER) == [] and raw(30) == was30, None)

# ---- 8. a line that reads like an item, earlier and unrelated, is not the one taken out
flat_raw(31, [LEAD, *ITEMS, CLOSING], SUM_END, before=[f"Oliver: {ITEMS[0]}", "home-agent: another line"])
check("8 the fixture: the same words stand once before the run, by the same writer, with a line of the agent's between", NL.split(mt(31)["next"])[2:5] == [f"Oliver: {ITEMS[0]}", "home-agent: another line", f"Oliver: {LEAD}"]
      and [t for s_, t in st(31) if s_ == "open"].count(f"Oliver: {ITEMS[0]}") == 2, st(31))
nest_now(31)
check("8 the earlier line stays where it was and the run's own copy is the one nested: the lead-in has all three items under it",
      NL.split(mt(31)["next"]) == ["home-agent: build it", f"Oliver: {NOW_END}", f"Oliver: {ITEMS[0]}", "home-agent: another line", *NEW_END], NL.split(mt(31)["next"]))
check("8 …the checklist: the earlier line is ONE open step (the run's copy is not a step of its own, and the earlier one's step is not dropped with it), six steps in all",
      [t for s_, t in st(31) if s_ == "open"].count(f"Oliver: {ITEMS[0]}") == 1 and len(st(31)) == 6 and all(s_ == "open" for s_, _ in st(31)), st(31))
check("8 …the record of the split still names the earlier line (it is a line of the split's words), the lead-in under its new key, the closing sentence, and not the other two items",
      mt(31)["step_lines"] == [S.key(NEW_END[0]), S.key(f"Oliver: {ITEMS[0]}"), S.key(f"Oliver: {CLOSING}")], mt(31)["step_lines"])
check("8 …writers: every line is the sender's still", [w for _, w in NL.resolve(mt(31), OWNER)][2:] == [AGENT] * 4, NL.resolve(mt(31), OWNER))

# ---- 9. one bad item never skips the others
bad = {51: "[]", 52: json.dumps({"id": "52", "status": "open", "metadata": "oops"}), 53: json.dumps({"id": "53", "status": "open", "metadata": None}), 55: json.dumps("just a string"),
       54: json.dumps({"id": "54", "subject": "[home] item a54", "status": "open", "metadata": {"owner": OWNER, "step": "x (+1 more)", "step_lines": 5, "next": "Oliver: x"}})}
old_split(41, FLAT_END, SUM_END)
old_split(59, FLAT_NONE, SUM_NONE)
for n_, txt in bad.items(): (T / f"store/a/{n_}.json").write_text(txt)
buf = io.StringIO()
try:
    with contextlib.redirect_stderr(buf): got9 = migsvc._nested_steps_pass()
finally:
    for n_ in bad: (T / f"store/a/{n_}.json").unlink()
check("9 a store with an item that is no object, one with metadata that is no object, a null one and one whose record of the split is a number: the good items before and after are nested, the pass does not fail",
      [r["gid"] for r in got9] == ["a41", "a59"] and NL.split(mt(41)["next"])[2:] == NEW_END and NL.split(mt(59)["next"])[2:] == NEW_NONE, ([r["gid"] for r in got9], buf.getvalue()[-400:]))
check("9 …the item with the number is named on stderr as not written, the others are passed over without a word", "a54 nested steps not written" in buf.getvalue() and not any(f"a{n_} " in buf.getvalue() for n_ in (51, 52, 53, 55)), buf.getvalue())

# ---- 10. the summary follows the lines
check("10 the summary the old split made (+4 more) says (+1 more) now: two lines at the top level; the server's line for it is the same words (reworded in place, the owner_step record with it)",
      mt(1)["step"] == NOW_END and mt(1)["owner_step"] == f"Oliver: {NOW_END}" and NL.split(mt(1)["next"])[1] == f"Oliver: {NOW_END}", (mt(1)["step"], mt(1).get("owner_step")))
check("10 …at the line's own place and under its own writer, and its step on the checklist is that line (one open step, no drop, no second one)",
      [w for _, w in NL.resolve(mt(1), OWNER)][1] == [w for _, w in NL.resolve(was1["metadata"], OWNER)][1] and [t for s_, t in st(1)].count(f"Oliver: {NOW_END}") == 1 and not any(s_ == "dropped" for s_, _ in st(1)), (st(1), NL.resolve(mt(1), OWNER)))
from stackshot.model import owner_steps as OS
m1 = json.loads(json.dumps(mt(1)))
check("10 …the server's next save agrees with it: ensure() for the new step changes nothing", OS.ensure(m1, mt(1)["step"], OWNER, "stackshot", now, "stackshot") == "" and m1 == mt(1), m1)
check("10 …a lead-in with nothing after it keeps no tail: the summary is the lead-in's words (a21)", mt(2)["step"] == NOW_NONE and mt(2)["owner_step"] == f"Oliver: {NOW_NONE}", (mt(2)["step"], mt(2).get("owner_step")))
flat_raw(32, [LEAD, *ITEMS], "Doing these things in order")
nest_now(32)
check("10 a summary with no `(+N more)` is left as it is, and so is the line for it; the lines are nested", mt(32)["step"] == "Doing these things in order" and mt(32)["owner_step"] == "Oliver: Doing these things in order" and NL.split(mt(32)["next"])[2:] == NEW_NONE, (mt(32)["step"], NL.split(mt(32)["next"])))
flat_raw(33, [LEAD, *ITEMS, CLOSING], SUM_END)
edit(33, lambda d: d["metadata"].update(owner_step="Oliver: a line that says something else"))
nest_now(33)
check("10 a server's line that is not the step's own is left as it is, with the summary (the item is not one the repair can reword on its own): the lines are nested, the step and owner_step untouched",
      mt(33)["step"] == SUM_END and mt(33)["owner_step"] == "Oliver: a line that says something else" and NL.split(mt(33)["next"])[2:] == NEW_END, (mt(33)["step"], mt(33)["owner_step"]))

# ---- 11. the undo record
rec_path = T / "state/migration/nested_steps.jsonl"
recs = [json.loads(x) for x in rec_path.read_text(encoding="utf-8").splitlines()]
by_gid = {r["gid"]: r for r in recs}
check("11 one record line for each item the pass rewrote, in order, with the item, a time, and what it held before", [r["gid"] for r in recs][:3] == ["a20", "a21", "a22"] and all(isinstance(r["t"], float) and r["item"] for r in recs), [r["gid"] for r in recs])
old20 = json.loads(s0["20.json"])["metadata"]
check("11 …the old next, next_by, step_lines, step, owner_step and steps are the item's as they were before the pass (what an undo puts back)",
      all(by_gid["a20"]["was"].get(k) == old20.get(k) for k in NR.FIELDS) and by_gid["a20"]["was"]["step"] == SUM_END and len(by_gid["a20"]["was"]["step_lines"]) == 5, by_gid["a20"])
check("11 …and nothing else of the item is in it", set(by_gid["a20"]["was"]) <= set(NR.FIELDS) and set(by_gid["a20"]) == {"t", "gid", "item", "was"}, by_gid["a20"].keys())
check("11 …the records follow the apply only: the dry run wrote none (the first lines are the first start's)", len([r for r in recs if r["gid"] in ("a20", "a21", "a22")]) == 3, [r["gid"] for r in recs])
migsvc.NESTED_RECORD_MAX = 300
try:
    old_split(42, FLAT_END, SUM_END)
    with contextlib.redirect_stderr(io.StringIO()): got11 = migsvc._nested_steps_pass()
finally:
    migsvc.NESTED_RECORD_MAX = 200_000
last = [json.loads(x) for x in rec_path.read_text(encoding="utf-8").splitlines()][-1]
check("11 a record over the cap is not written whole: its line says so; the repair goes on (a42 is nested)",
      last["gid"] == "a42" and "skipped" in last and "was" not in last and len(json.dumps(last)) < 400 and [r["gid"] for r in got11] == ["a42"] and NL.split(mt(42)["next"])[2:] == NEW_END, (last, got11))
old_split(43, FLAT_END, SUM_END)
was43 = raw(43)
mig_dir = T / "state/migration"; mig_bak = T / "state/migration.bak"
mig_dir.rename(mig_bak); mig_dir.write_text("a file where the folder should be")
buf = io.StringIO()
try:
    with contextlib.redirect_stderr(buf): got43 = migsvc._nested_steps_pass()
finally:
    mig_dir.unlink(); mig_bak.rename(mig_dir)
check("11 a record that cannot be written leaves the item as it is, byte for byte (counted, said on stderr, not in the rows)",
      got43 == [] and raw(43) == was43 and "a43 nested steps not written: the undo record could not be written" in buf.getvalue() and "1 item(s) left as they are for want of an undo record" in buf.getvalue(), (got43, buf.getvalue()))
with contextlib.redirect_stderr(io.StringIO()): again43 = migsvc._nested_steps_pass()
check("11 …the next start, with the record writable again, nests it", [r["gid"] for r in again43] == ["a43"] and NL.split(mt(43)["next"])[2:] == NEW_END and json.loads(rec_path.read_text(encoding="utf-8").splitlines()[-1])["gid"] == "a43", again43)

print(("ok" if not fails else "FAILED") + f": nested_repair scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
