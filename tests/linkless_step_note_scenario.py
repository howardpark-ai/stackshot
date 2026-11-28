"""Scenario test for the note on a step for the owner that asks him to open or check something but holds no link (stackshot/web/tools/notes.py `_linkless_open_note`) — fixture data, the tools called
in-process, no live store, no network.

A step is read alone: "open the mockup" with "the link above" or "an earlier message" in place of the link leaves the owner no page to open. When update (step=) or create/update (a next line that opens
with `<owner>:`) writes such a step, the reply carries one note saying so and to put the link in the step itself; the write goes through (never a refusal). The cases:

  1  a link in the step ([words](url) or a bare https URL): no note
  2  an open/check verb and "the link above" or "the mockup I sent" with no link: the note (a step=, a next line of the owner, a create)
  3  the same in another language, through [keywords.server] open_cues and back_refs (the test instance lists Japanese words; the repository holds no Hangul)
  4  a step that asks nothing of the kind (no verb, or no point-back phrase), and a session's own next line that says "the link above": no note

    tests/run-suite linkless_step_note        -> exit 0 / 1"""
import asyncio, contextlib, datetime as dt, io, json, logging, os, pathlib, re, sys, time, types
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="fivefixestest-"); T = pathlib.Path(tmp)
toml = _instance.set_person(_instance.apply(_instance.base_toml(), keywords=True))
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
from stackshot.web.tools import notes as _wt_notes
from fastmcp.exceptions import ToolError
_cfg.CFG.setdefault("model", {})["guards"] = False      # fixture owners the fleet does not know; the write guards have their own suite
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._owing_note = lambda debtor: ""

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
from stackshot.core.instance import OWNER as OWN
NOTE = "holds no link"
def noted(res): return isinstance(res, str) and NOTE in res
def seed(i): item(i, next_=f"{MAIN}: build it")

# ---------------------------------------------------------------- 1 a link in the step: no note
for n, text in ((1, "Open [the mockup](https://example.com/m/1) and tell me if the header reads right"), (2, "Open https://example.com/m/2 and check the header above the fold"),
                (3, "Check the link above: [mockup](https://example.com/m/3)")):
    seed(n); res, made = upd(n, step=text)
    check(f"1.{n} a step with a link: no note, the write went through", isinstance(res, str) and "updated" in res and not noted(res), res)

# ---------------------------------------------------------------- 2 the link is pointed at, not given
for n, text in ((4, "Open the mockup at the link above and tell me if the header reads right"), (5, "Check the mockup I sent earlier"), (6, "Try the page in an earlier message and say what is off")):
    seed(n); res, made = upd(n, step=text)
    check(f"2.{n} update step={text[:30]!r}: the note, and the write went through", noted(res) and "put the link in the step itself" in res and mt(n).get("step"), res)
seed(7); res, made = upd(7, next=f"{MAIN}: build it\n{OWN}: open the page from the link above and check it")
check("2.7 update next: a line of the owner's that points back: the note", noted(res), res)
res, made = create(next=f"{MAIN}: carry on\n{OWN}: open the mockup from the link above")
check("2.8 create: the same line of next: the note, the item made", noted(res) and "created" in res, res)
res, made = create(next=f"{MAIN}: carry on\n{OWN}: open [the mockup](https://example.com/m/9) and check it")
check("2.9 create: a link on the owner's line: no note", isinstance(res, str) and "created" in res and not noted(res), res)

# ---------------------------------------------------------------- 3 another language, by the configured words
seed(8); res, made = upd(8, step="上のリンクを開いてください")
check("3.1 a step in another language (open cue + point-back words, no link): the note", noted(res), res)
seed(9); res, made = upd(9, step="[目標](https://example.com/m/10) を開いてください")
check("3.2 …the same with a link: no note", isinstance(res, str) and "updated" in res and not noted(res), res)
cues_were = dict(_cfg.CFG.get("keywords", {}).get("server", {}))
_cfg.CFG["keywords"]["server"] = {"command_cues": [], "open_cues": [], "back_refs": []}
seed(10); res, made = upd(10, step="上のリンクを開いてください")
check("3.3 with no configured words the other language draws no note", not noted(res), res)
_cfg.CFG["keywords"]["server"] = cues_were

# ---------------------------------------------------------------- 4 nothing asked, nothing noted
for n, text in ((11, "Decide which of the two headers you prefer"), (12, "Reply to the link checker's email"), (13, "Open the mockup and tell me what is off")):
    seed(n); res, made = upd(n, step=text)
    check(f"4.{n} {text[:34]!r}: no note", isinstance(res, str) and "updated" in res and not noted(res), res)
seed(14); res, made = upd(14, next=f"{MAIN}: build it\n{MAIN}: send the link above to the reviewer and check it landed")
check("4.14 a session's own line that says 'the link above': no note", not noted(res), res)
check("4.15 the helper, called with nothing: no note", _wt_notes._linkless_open_note() == "" and _wt_notes._linkless_open_note("", "") == "")

import shutil; shutil.rmtree(tmp, ignore_errors=True)
print(("ok" if not fails else "FAILED") + f": linkless step note scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
