"""Scenario test for the two repairs the server makes to a messy list written on an item, with no refusal — fixture data, the tools called in-process, no live store, no network.

Covers: list_repair.repair (the pure part): a numbered run written on one bullet line (`- Do: 1) a 2) b 3) c`, with or without a lead-in) comes out as lines of their own, each bullet keeping its number and its words; a doubled
bullet mark (`- - x`, `- - - x`) is made one; a clean text, a number in a sentence, a `1.` run, a run inside a code span or a link, a fenced block, a quote and a lone `- - -` rule come back as the same string; nothing is
re-nested, reordered or reworded; a split that would pass the line cap is not made. step_split: a step written `- 1) … 2) …` is read as a list like one with no dash. Through create, update and a close: the repaired text is stored,
the reply says so (kind list-shape), a clean text writes no line, and the same text sent again changes nothing.

    tests/run-suite list_repair        → exit 0 / 1"""
import json, os, re, sys, pathlib, tempfile, logging, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="listrepairtest-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store (session links off)
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "brain/projects", "brain/infra"): (T / d).mkdir(parents=True)
NAMES = ("falcon-main", "home-other")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
(T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")
def page(rel, front):
    q = T / "brain" / rel; q.parent.mkdir(parents=True, exist_ok=True); q.write_text("---\n" + front + "\n---\n\n# x\n", encoding="utf-8")
page("projects/example.md", "type: project\ntitle: Stackshot\ndisplay-name: falcon\nagents:\n  falcon-main: builds it\nstatus: active")
page("projects/other.md", "type: project\ntitle: Other\ndisplay-name: home-other\nstatus: active")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))

from stackshot.projects import pages as p
p.cmd_registry(quiet=True)
from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route; from stackshot.model import ids as _model_ids; from stackshot.service import question as question_svc
from stackshot.web.tools import notes as _notes_tool
from stackshot.service import wait_gates as wait_gates_svc
from stackshot.service import update as _update_svc
from stackshot.service import store as _service_store
from stackshot.core import config as _cfg
from stackshot.core import call_log as _CL
from stackshot.core import instance as _core_instance
from stackshot.web import render as _rmod
from fastmcp.exceptions import ToolError
from stackshot.web import publish as _web_publish
from stackshot.model import field_gates as _fg
from stackshot.service import checks as checks_svc
from stackshot.service import wakes as wakes_svc
from stackshot.web.tools import complete as _wt_complete
from stackshot.web.tools import create as _wt_create
from stackshot.service import telling
from stackshot.service import writes
_cfg.CFG.setdefault("model", {})["guards"] = False      # fixture owners the fleet does not know; the write guards have their own suite
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None

MAIN = "falcon-main"
STK = "projects/example"
def goaled(desc):
    """the goal gate reads the first bullet; these tests are about the other limits, so a first bullet that is not a Goal bullet gets the label (a text that is no bullet is left to the form gate)"""
    return re.sub(r"^(-[ \t]+)(?!Goal:)", r"\1Goal: ", desc, count=1)
def create(desc="- Goal: A thing\n- It lives here\n- Done when done", **kw):
    desc = goaled(desc)
    if not kw.get("next") and "ask" not in kw:
        kw["next"] = f"{MAIN}: carry on"          # an open item has an open step (N6): a create with no next of its own gets a named one
    r = _wt_create.stackshot_create(subject=kw.pop("subject", "[home] a thing"), description=desc, project=STK, owner=MAIN, **kw)
    return r, _model_ids._norm_id(r.split()[1])
def refused(name, f, *want):
    try:
        out = f(); check(name, False, out)
    except ToolError as e:
        check(name, all(w in str(e) for w in want), str(e))
def passes(name, f):
    try:
        f(); check(name, True)
    except ToolError as e:
        check(name, False, str(e))

from stackshot.model import list_repair as _lr
from stackshot.model import step_split as _ss
LINE = "- Goal: ok\n- It lives here"


def with_fixes(f):
    tok = _CL.begin()
    try:
        out = f()
    except BaseException:
        _CL.end(tok)
        raise
    return out, _CL.end(tok)


def rep(t, cap=8): return _lr.repair(t, cap)[0]


# ---- 1. the pure repair
check("1 a numbered run on a bullet line is put on lines of its own, the lead-in a bullet, each item with its number", rep("- Do: 1) open it 2) read it 3) close it") == "- Do:\n- 1) open it\n- 2) read it\n- 3) close it")
check("1 …with a dash before the run, and with no lead-in", rep("- - 1) a 2) b") == "- 1) a\n- 2) b" and rep("- 1) a 2) b") == "- 1) a\n- 2) b")
check("1 …the last item keeps what follows it, an indent stays on every line", rep("  - Steps. 1) a. 2) b. Then rest.") == "  - Steps.\n  - 1) a.\n  - 2) b. Then rest.")
check("1 a doubled bullet mark is made one, however many", rep("- - x\n- - - y\n-  - z") == "- x\n- y\n- z")
check("1 …and the counts are told", _lr.repair("- - x\n- 1) a 2) b", 8) == ("- x\n- 1) a\n- 2) b", 1, 1))
CLEAN = ["- Goal: ok\n- It lives here\n  - sub one\n  - sub two", "- Pick plan 1) basic or 2) pro", "- Version 1. then 2. later", "- Use `1) a 2) b` as is", "- See [1) a 2) b](http://x.y/z)",
         "- Goal: ok\n```\n- - x\n- 1) a 2) b\n```", "> - - quoted 1) a 2) b", "- - -", "- 1) only one", "- Later 2) a 3) b", "- Do: 1) a 2) ", "", "- a - b\n- --flag", "- 1) a\n- 2) b"]
check("1 clean text and look-alikes come back as the same string, byte for byte", all(rep(t) is t or rep(t) == t for t in CLEAN) and all(_lr.repair(t, 8) == (t, 0, 0) for t in CLEAN), [t for t in CLEAN if rep(t) != t])
check("1 a split that would pass the line cap is not made, the doubled mark is still dropped", _lr.repair("- - Do: 1) a 2) b 3) c", 3) == ("- Do: 1) a 2) b 3) c", 1, 0), _lr.repair("- - Do: 1) a 2) b 3) c", 3))
check("1 repairing the repaired text changes nothing", rep(rep("- - Do: 1) a 2) b")) == rep("- - Do: 1) a 2) b"))

# ---- 2. a step with a dash before 1)
STEP = "1) open the board page and read the whole item through 2) write the answer on the item in plain words 3) tick the step done and tell the owner"
got = _ss.split_step("- " + STEP, 200); plain = _ss.split_step(STEP, 200)
check("2 a step with a dash before `1)` is split into one line per item, as one with no dash is", got is not None and got == plain and len(got[1]) == 3, got)
check("2 a dash before a sentence is no list, and a dash after a word is none", _ss.split_step("- open the board page and read the whole item through then write the answer on the item in plain words 1) tick it", 200) is None)

# ---- 3. writes
def create(desc, **kw):
    r = _wt_create.stackshot_create(subject="[home] a thing", description=desc, project=STK, owner=MAIN, next=f"{MAIN}: carry on", **kw)
    return r, _model_ids._norm_id(r.split()[1])
def stored(g): return _service_store._load(g)["description"]
r, fx = with_fixes(lambda: create("- Goal: ok\n- - Background: 1) the old way 2) the new way 3) the switch"))
check("3 create: a doubled mark and a numbered run are stored repaired", stored(r[1]) == "- Goal: ok\n- Background:\n- 1) the old way\n- 2) the new way\n- 3) the switch", stored(r[1]))
check("3 …counted once as list-shape, told with the words kept", [k for k, _ in fx] == ["list-shape"] and "no word changed" in fx[0][1] and "doubled bullet mark" in fx[0][1] and "numbered run" in fx[0][1], fx)
r, fx = with_fixes(lambda: create(LINE))
check("3 create: a clean description is stored as sent and says nothing", stored(r[1]) == LINE and fx == [], (stored(r[1]), fx))
g = r[1]
_, fx = with_fixes(lambda: _update_svc._update(g, description="- Goal: ok\n- - Why: 1) a 2) b", sender=MAIN))
check("3 update: the same repair on an update, told", stored(g) == "- Goal: ok\n- Why:\n- 1) a\n- 2) b" and [k for k, _ in fx] == ["list-shape"], (stored(g), fx))
_, fx = with_fixes(lambda: _update_svc._update(g, description=stored(g), sender=MAIN))
check("3 update: the stored text sent back says nothing and changes nothing", fx == [] and stored(g) == "- Goal: ok\n- Why:\n- 1) a\n- 2) b", (stored(g), fx))
_, fx = with_fixes(lambda: _update_svc._update(g, description="- Goal: ok\n- Why:\n- 1) a\n- 2) b", sender=MAIN))
check("3 update: a clean list is not touched", fx == [] and stored(g) == "- Goal: ok\n- Why:\n- 1) a\n- 2) b")
g2 = create(LINE)[1]
_, fx = with_fixes(lambda: _wt_complete.stackshot_complete(g2, outcome="done", reason="finished", outcome_text="- - Result: 1) built 2) tested", sender=MAIN))
check("3 close: the outcome text is repaired the same way", _service_store._load(g2)["metadata"].get("outcome_text") == "- Result:\n- 1) built\n- 2) tested" and "list-shape" in [k for k, _ in fx], (_service_store._load(g2)["metadata"].get("outcome_text"), fx))

print(("ok" if not fails else "FAILED") + f": list_repair scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
