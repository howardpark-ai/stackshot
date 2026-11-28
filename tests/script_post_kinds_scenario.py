"""Scenario test for the three calls a script files an item with (`client.py post job-gap open|clear`, `client.py post terminal-prompt open|clear`, `client.py job-failed` and `client.py job-ok`; the
routes POST /client/job-gap, /client/terminal-prompt, /client/job-failed and /client/job-ok) — fixture data, no live store, no network, no server process (the server module is imported and called in-process,
on a temporary config; the sessions and pages are fixture files in a temporary directory). The three kinds were three suites with the same harness (a temporary instance, a fixture session registry and project
pages, the client post route called in-process, a fake push, the same HTTP and client.py section); they run here one after another in one process, each part as a function, each starting from the same state
its own suite did (the pages aged, no page debt, no push recorded). The registry and the pages hold what the three suites held together.

Part 1, a gap in a scheduled job (job_gap):
Scenario test for the script post kind a gap in a scheduled job is filed with (`client.py post job-gap open|clear`, POST /client/job-gap, Oliver's pick A) — fixture data, no
live store, no network, no server process (the server module is imported and called in-process, on a temporary config; the pages are fixture files in a temporary directory).

Covers: open (one open item per (timer, code), marked metadata.job_gap = "<timer>: <code>", subject "<the task>", under the project page that owns the repo, the project's builder the
mover and in needs, its -main agent the keeper of record, p2, next "<builder>: <the fix>", description bullets that say the gap and the fix, the script recorded as creator; the builder is told
once and no front agent is woken, nothing is owed to the page); a repeat open of an open (timer, code) files nothing and answers the same item, another code or another timer is another item;
clear (closes it: outcome done, a reason within the limit, the end state in outcome_text, the id answered), clear with none open a 200 that says so, an open again after a clear
files a new item; a repo the server does not know a 400 that names the known ones; a project with no builder moves the item by its -main agent and says so; a project with no front agent
a 409; the repo map ([job_gap.repos] over the defaults); the sender gate (the owner's name, a long or multi-line label refused; none given taken as client.py); a long unit name cut
so the subject stays within the limit; bad timer, code, action and repo refused with nothing filed; eight threads opening one gap file one item; over HTTP (401 without a token) and through
client.py (the id alone on stdout, the note on stderr when a front agent moves it, usage on misuse, a server that is not reached).

Part 2, a pane waiting in its terminal (terminal_prompt):
Scenario test for the script post kind a pane waiting in its terminal is filed with (`client.py post terminal-prompt open|clear`, POST /client/terminal-prompt;
) — fixture data, no live store, no network, no server process (the server module is imported and called in-process, on a temporary config; the session
registry is a fixture file in a temporary directory, never the host's).

Covers: open (the item id alone on stdout, exit 0; one open item, marked metadata.terminal_prompt with the session's name, subject "Answer <session>
in its terminal", the owner the mover and the item in his Your move list, state your-step with the step "Answer <session>'s question in its terminal", p1, next "<owner>: open
<the pane's address> and answer: <question>", under the session's project from the registry, else projects/example-two, the project's -main agent the keeper of record, the script
recorded as creator); a second open for the session changes the question and files nothing, the same question again writes nothing; a session id, a transcript id, an old name
and the current name reach one item; clear (closes the session's open item: outcome done, reason "the pane stopped waiting", a state dropped, a description rewritten to the end
state), clear with none open or for an unknown session a no-op that answers 200, an open again after a clear files a new item; one session's item never touched by another's calls;
the question refused when empty, over 200 characters or over several lines, a missing or owner-named sender, a bad action, with nothing filed; a question with alarming words and
one that overruns the next-line limit (cut at a word with an ellipsis) filed; the page-debt rules (the script owes no page, the owner and the -main agent are charged none, and
nothing is told to any session); a failed state write closes the item again rather than leaving it half made; client.py (usage, exit codes, no token, a server not reached) and its docs.

Part 3, a failed run of a scheduled job (job_alert):
Scenario test for the two script calls a failed run of a scheduled job is reported with (`client.py job-failed` and `client.py job-ok`, POST /client/job-failed and /client/job-ok) — fixture data,
no live store, no network, no server process (the server module is imported and called in-process, on a temporary config; the pages are fixture files in a temporary directory).

Covers: a failure opens ONE item (marked metadata.job_alert = "<unit> on <host>", under the given project page, its builder the mover and in needs, its -main agent the keeper of record, p2, the script
recorded as creator as "job alert (a script on <machine>)", a description that says which job on which machine, the count, the time of the run in the instance's timezone and what to do; the builder is
told once, nothing is owed to the page); a repeat failure with another time adds the line and the count and files nothing, the same time again counts once; another unit or another host is another item;
job-ok closes it (outcome done, the run's time in the reason and in the end state), a second job-ok and a job-ok with no item are ignored (200, nothing closed), a job-ok older than the item's latest failed run
leaves it open; a failure after the close opens a NEW item unless its time is no later than the success that closed the last one (a retry or a late call: seen, nothing filed); a time later than now plus 5 minutes is refused
on both routes (so is one the board cannot show), one instant spelled two ways counts once, the kept times stay in order whatever order they arrive in, a project key that names several pages is refused; a `scope/project` label is resolved by the instance's `[job_alert.projects]` map, then the key, then the one page whose display-name is the label with `/` made `-` (two such pages are refused; only an active page of `type: project` counts, a finished, merged, archived or note page of the name is no match, and a note says how the label was resolved); a time stored in the old spelling counts as the same instant; the 400 for a clock that is ahead says by how many minutes; a project of `-`, one the registry does not have and a project with no builder (the -main agent moves it, and says so) are filed as the text says,
the general project missing is a 409; the key is read from the item (the module is reloaded between calls: nothing is kept in memory); the newest 20 times are kept while the count goes on; bad input is refused
with nothing filed; eight threads failing one job file one item; over HTTP (401 without a token) and through client.py (the id alone on stdout, usage on misuse, exit 1 when refused or not reached).

    tests/run-suite script_post_kinds        → exit 0 / 1"""

import contextlib, datetime, importlib, io, json, os, re, socket, sys, pathlib, logging, threading, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="scriptpostkindstest-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = ""', f'session_links = "{tmp}/sala"', 1); assert f'session_links = "{tmp}/sala"' in toml   # the fixture registry, never the host's sala store
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml = _instance.set_person(toml)       # the person the tools speak of
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
for d in ("store/a", "fleet/a", "sala/a", "state/anchor-hub", "brain/projects", "brain/infra", "secrets"): (T / d).mkdir(parents=True)
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")

def uid(n): return f"00000000-0000-4000-8000-{n:012d}"
# sala ids (S) and claude transcript ids (Tr) of every fixture session of the three parts: one row per session, the builder and the -main agent of projects/alpha shared by all of them.
# The builder of alpha carries two transcript ids (eng_old, eng_new), one per run, and the old name home-sparrow-eng (the terminal-prompt part reaches the session by each).
S = {"build": uid(101), "main": uid(102), "docs": uid(103), "nbmain": uid(104), "gbuild": uid(105), "gmain": uid(106), "tmain": uid(107), "wmain": uid(108), "wbuild": uid(109), "bmain": uid(110),
     "loner": uid(111), "nofront": uid(112), "other": uid(113), "slug": uid(114), "longname": uid(115)}
S["eng"] = S["build"]
Tr = {"eng_old": uid(201), "eng_new": uid(202), "main": uid(203), "docs": uid(204), "nbmain": uid(205), "gbuild": uid(206), "gmain": uid(207), "tmain": uid(208), "wmain": uid(209), "wbuild": uid(210),
      "bmain": uid(211), "loner": uid(212), "nofront": uid(213), "other": uid(214), "slug": uid(215), "longname": uid(216)}
def row(key, name, project_key=None, aliases=(), transcripts=None, cwd="/home/user", **kw):
    transcripts = [key] if transcripts is None else transcripts
    return {"id": S[key], "name": name, "aliases": list(aliases), "project": None, "project_key": project_key, "role": None, "lane": "max", "model": "opus", "effort": "medium", "pane": name,
            "cwd": cwd, "state": "live", "created": "2026-10-21T21:00:00Z", "retired_at": None,
            "transcripts": [{"id": Tr[t], "machine": "a", "at": f"2026-10-21T2{i}:00:00Z", "why": "import" if i == 1 else "fresh"} for i, t in enumerate(transcripts, 1)], **kw}
LONGNAME = "home-sparrow-" + "n" * 60            # a pane name that would make the server's own subject over the 80-character limit (terminal-prompt part)
ROWS = [row("build", "home-sparrow-builder", "projects/alpha", aliases=["home-sparrow-eng"], transcripts=["eng_old", "eng_new"]),
        row("main", "home-sparrow-main", "projects/alpha"), row("docs", "home-sparrow-docs", "projects/alpha"), row("nbmain", "home-nobuild-main", "projects/nobuild"),
        row("gbuild", "heron-engineer", "ops/general"),
        row("gmain", "heron-main", "ops/general", cwd="/work"), row("tmain", "home-twin-main", "projects/twin", cwd="/work"),
        row("wmain", "acme-widgets-main", "projects/acme-widgets", cwd="/work"), row("wbuild", "acme-widgets-builder", "projects/acme-widgets", cwd="/work"), row("bmain", "acme-bolts-main", "projects/acme-bolts", cwd="/work"),
        row("loner", "home-loner", None),                         # no project: filed under projects/example-two
        row("nofront", "home-nofront", "projects/gamma"),         # a project that lists no front agent: projects/example-two as well
        row("other", "home-other", "projects/alpha"),
        row("slug", "home-slug", None, project="alpha"),          # the project by its bare name only
        row("longname", LONGNAME, "projects/alpha")]
(T / "sala/a/session-registry.json").write_text(json.dumps({"schema": 1, "machine": "a", "written": "2026-10-22T07:00:00Z", "sessions": {r["id"]: r for r in ROWS}}), encoding="utf-8")
def page(rel, front):
    q = T / "brain" / rel; q.parent.mkdir(parents=True, exist_ok=True); q.write_text("---\n" + front + "\n---\n\n# x\n", encoding="utf-8")
page("projects/alpha.md", "type: project\ntitle: Alpha\ndisplay-name: home-sparrow\nagents:\n  home-sparrow-docs: keeps the docs\n  home-sparrow-main: talks to Oliver\n  background:\n    home-sparrow-notes: keeps the notes\n    home-sparrow-builder: builds\nstatus: active")
page("projects/nobuild.md", "type: project\ntitle: Nobuild\ndisplay-name: home-nobuild\nagents:\n  home-nobuild-main: talks to Oliver\nstatus: active")
page("projects/gamma.md", "type: project\ntitle: Gamma\ndisplay-name: home-gamma\nstatus: active")
page("projects/example-two.md", "type: project\ntitle: Example Two\ndisplay-name: example-two\nagents:\n  example-two-main: talks to Oliver\nstatus: active")
page("projects/twin.md", "type: project\ntitle: Twin\ndisplay-name: home-twin\nagents:\n  home-twin-main: talks to Oliver\nstatus: active")
page("ops/twin.md", "type: project\ntitle: Twin ops\ndisplay-name: home-twinops\nagents:\n  home-twinops-main: talks to Oliver\nstatus: active")
page("projects/acme-widgets.md", "type: project\ntitle: Widgets\ndisplay-name: acme-widgets\nagents:\n  acme-widgets-main: talks to Oliver\n  background:\n    acme-widgets-builder: builds\nstatus: active")
page("projects/acme-widgets/mechanics.md", "type: project\ntitle: Widget mechanics\ndisplay-name: acme-widgets\nstatus: active")      # a sub-page carries its project's name line: it is no second page of the name
page("projects/dupe-a.md", "type: project\ntitle: Dupe A\ndisplay-name: acme-dupe\nagents:\n  acme-dupe-main: talks to Oliver\nstatus: active")
page("projects/dupe-b.md", "type: project\ntitle: Dupe B\ndisplay-name: acme-dupe\nagents:\n  acme-dupe-main: talks to Oliver\nstatus: active")
page("projects/acme-bolts.md", "type: project\ntitle: Bolts\ndisplay-name: acme-bolts\nagents:\n  acme-bolts-main: talks to Oliver\nstatus: active")
page("projects/acme-bolts-old.md", "type: project\ntitle: Bolts, finished\ndisplay-name: acme-bolts\nagents:\n  acme-bolts-main: talks to Oliver\nstatus: completed")
page("projects/acme-gone.md", "type: project\ntitle: Gone\ndisplay-name: acme-gone\nagents:\n  acme-gone-main: talks to Oliver\nstatus: merged")
page("projects/acme-shelved.md", "type: project\ntitle: Shelved\ndisplay-name: acme-shelved\nagents:\n  acme-shelved-main: talks to Oliver\nstatus: archived")
page("projects/acme-finished.md", "type: project\ntitle: Finished\ndisplay-name: acme-finished\nagents:\n  acme-finished-main: talks to Oliver\nstatus: done")
page("projects/acme-memo.md", "type: note\ntitle: Memo\ndisplay-name: acme-memo\nstatus: completed")
page("projects/acme-memo-live.md", "type: note\ntitle: Memo, live\ndisplay-name: acme-memo\nstatus: active")
page("projects/acme-twin-a.md", "type: project\ntitle: Twin A\ndisplay-name: acme-twin\nagents:\n  acme-twin-main: talks to Oliver\nstatus: active")
page("projects/acme-twin-b.md", "type: project\ntitle: Twin B\ndisplay-name: acme-twin\nagents:\n  acme-twin-main: talks to Oliver\nstatus: active")
page("projects/acme-twin-old.md", "type: project\ntitle: Twin, finished\ndisplay-name: acme-twin\nagents:\n  acme-twin-main: talks to Oliver\nstatus: completed")
page("ops/general.md", "type: project\ntitle: General\ndisplay-name: heron\nagents:\n  heron-main: talks to Oliver\n  background:\n    heron-engineer: builds and fixes needing no decision\nstatus: active")
def age_pages():
    for pg in (T / "brain").rglob("*.md"): os.utime(pg, (time.time() - 8 * 3600, time.time() - 8 * 3600))      # the pages are older than any debt (and the 5-minute slack), so a debt charged by a write would stand
age_pages()
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))

from stackshot.projects import pages as p
p.cmd_registry(quiet=True)
from stackshot.fleet import sessions_registry as sr
sr.TTL = 0
from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route; from stackshot.service import writes; from stackshot.fleet import client; from stackshot.model import model as M; from stackshot.web import home as H_; from stackshot.model import ids as _model_ids
from stackshot.service import job_gap as job_gap_svc; from stackshot.service import terminal_prompt as terminal_prompt_svc
from stackshot.service import job_alert as _ja_first
from stackshot.web.routes import client_api as _rt_client
from stackshot.service import update as _update_svc
import subprocess
from stackshot.service import store as _service_store
from stackshot.core import config as _cfg
from stackshot.web import page_debts as _pdebts
from stackshot.github import ghsync as _gh
from fastmcp.exceptions import ToolError
from stackshot.web import publish as _web_publish
from stackshot.web.tools import create as _wt_create
from stackshot.model import field_gates as _fg
from stackshot.web.tools import get as _wt_get
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
pushed = []                           # every push to a session the server would make: [to, note]
_orig_run = subprocess.run
def _fake_run(cmd, *a, **kw):
    if isinstance(cmd, list) and any(str(x).endswith("push.py") or str(x).endswith("fakepush.py") for x in cmd):
        pushed.append(list(cmd)[-2:]); return subprocess.CompletedProcess(cmd, 0, "delivered\n", "")
    return _orig_run(cmd, *a, **kw)
subprocess.run = _fake_run
def settle():
    """The notices go out on threads: wait for them (at most 3 s each)."""
    for t in threading.enumerate():
        if t is not threading.current_thread() and t.daemon and t.is_alive(): t.join(3)
from starlette.testclient import TestClient
me = socket.gethostname(); tok = open(client.mint(me)).read().strip(); HD = {"Authorization": "Bearer " + tok}
def items(): return sorted((p_.stem for d in (T / "store").iterdir() if d.is_dir() for p_ in d.glob("*.json") if p_.stem.isdigit()), key=int)   # in id order: the three parts file items one after another in one store
def item(shown): return _service_store._load(_model_ids._norm_id(shown))
def fresh():
    """Each part starts as its former suite did: the pages older than any debt, no page debt owed, no push recorded."""
    settle(); age_pages(); _pdebts._owed_save({}); pushed.clear()

# ======== part 1: a gap in a scheduled job (the former job_gap suite) ========
def part_job_gap():
    def jg(action, timer="sala-foo.timer", code="no-lane", repo="acme/alpha", sender="sala-unit-gaps", machine=None, **kw):
        b = {"action": action, "timer": timer, "code": code, "repo": repo, "sender": sender}
        b.update(kw)
        return _rt_client._client_post(machine or me, "job-gap", {k: v for k, v in b.items() if v is not None})
    def open_for(timer, code): return job_gap_svc._jobgap_open_items(f"{timer}: {code}")
    # the repo map of this instance: the test repos over the defaults
    _cfg.CFG["job_gap"] = {"repos": {"acme/alpha": "projects/alpha", "acme/nobuild": "projects/nobuild", "acme/gamma": "projects/gamma", "acme/ghost": "projects/ghost", "Acme/Mixed-Case": "projects/alpha"}}
    n0 = len(items())

    # ---- 1. open: the item and its shape
    st, out = jg("open", detail="/home/user/.config/systemd/user/sala-foo.timer, script /home/user/bin/foo.sh")
    check("open: 200 with the item id as shown, the timer, the code, the project, the mover, the keeper, repeat false, no fallback",
          st == 200 and out["timer"] == "sala-foo.timer" and out["code"] == "no-lane" and out["project"] == "projects/alpha" and out["mover"] == "home-sparrow-builder" and out["owner"] == "home-sparrow-main"
          and out["repeat"] is False and out["fallback"] is False and out["item"] == _gh.shown(_model_ids._norm_id(out["item"])), (st, out))
    it = item(out["item"]); m = it["metadata"]
    check("the item is open, filed under the repo's project page, marked with the timer and the code", it["status"] == "open" and m["project"] == "projects/alpha" and m["job_gap"] == "sala-foo.timer: no-lane", (it["status"], m))
    check("…the subject is the task that closes the gap, naming the unit", it["subject"] == "Add X-Model-Lane= to sala-foo.timer", it["subject"])
    check("…p2; the project's builder (the one whose mandate builds, not the notes keeper) is the mover and is in needs", m.get("priority") == "p2" and sr._session_label(m.get("mover")) == "home-sparrow-builder"
          and [sr._session_label(x) for x in m.get("needs") or []] == ["home-sparrow-builder"], m)
    check("…the keeper of record is the project's -main agent (not the builder, not the docs agent); the script is the creator", sr._session_label(m["owner"]) == "home-sparrow-main"
          and it["filed_by"] == f"sala-unit-gaps via a script on {me}", (m["owner"], it.get("filed_by")))
    check("…next is one line that names the builder and the fix: the unit in the repo with X-Model-Lane, linked from there", m.get("next", "").startswith("home-sparrow-builder: put sala-foo.timer's unit file in acme/alpha with an X-Model-Lane= line, linked from there")
          and "\n" not in m["next"].strip(), m.get("next"))
    d = it["description"].splitlines()
    check("…the description is bullets: the gap, the detail, the fix, the repo, who opened it", len(d) == 5 and all(x.startswith("- ") for x in d) and d[0].startswith("- sala-foo.timer has no X-Model-Lane= line")
          and "script /home/user/bin/foo.sh" in d[1] and d[2].startswith("- Fix: put sala-foo.timer") and "acme/alpha" in d[3] and d[4] == f"- Opened by sala-unit-gaps (a script on {me}); it closes when the watcher finds the gap fixed", it["description"])
    settle()
    check("…the builder is told once and no one else is: no push names the keeper of record or another agent", len(pushed) == 1 and pushed[0][0] in ("home-sparrow-builder", S["build"]) and out["item"] in pushed[0][1] and "now needs you" in pushed[0][1], pushed)
    check("…one item filed, and the row owes no page: no debt is charged to the script, the builder or the keeper", len(items()) == n0 + 1 and _pdebts._owed_load() == {}, (len(items()) - n0, _pdebts._owed_load()))
    check("…the item is alive with the builder as the mover (not in the owner's list)", M.derive(it).state == M.ALIVE and M.derive(it).mover == "home-sparrow-builder", (M.derive(it).state, M.derive(it).mover))
    check("…the item is in the brief", out["item"] in _wt_get.stackshot_get(out["item"]), _wt_get.stackshot_get(out["item"])[:300])
    gid1 = out["item"]

    # ---- 2. a repeat open changes nothing; another code or timer is another item
    n1 = len(items()); pushed.clear()
    st, o2 = jg("open", detail="a different text")
    settle()
    check("a repeat open of the open (timer, code): 200, the same item, repeat true, nothing filed, nothing told", st == 200 and o2["item"] == gid1 and o2["repeat"] is True and len(items()) == n1 and pushed == [], (st, o2, pushed))
    check("…the item is as it was (same description and next)", item(gid1)["description"] == it["description"] and item(gid1)["metadata"]["next"] == m["next"])
    st, o3 = jg("open", repo="acme/nobuild")
    check("…even with another repo: the open gap's item is answered", st == 200 and o3["item"] == gid1 and o3["repeat"] is True and len(items()) == n1, (st, o3))
    st, o4 = jg("open", code="not-git")
    check("another code on the same timer is another item", st == 200 and o4["item"] != gid1 and o4["repeat"] is False and item(o4["item"])["subject"] == "Put sala-foo.timer in git" and len(items()) == n1 + 1, (st, o4))
    st, o5 = jg("open", timer="sala-bar.timer")
    check("another timer with the same code is another item", st == 200 and o5["item"] not in (gid1, o4["item"]) and item(o5["item"])["subject"] == "Add X-Model-Lane= to sala-bar.timer" and len(items()) == n1 + 2, (st, o5))
    check("…each open gap finds its own item", open_for("sala-foo.timer", "no-lane") == [_model_ids._norm_id(gid1)] and len(open_for("sala-foo.timer", "not-git")) == 1 and len(open_for("sala-bar.timer", "no-lane")) == 1)
    for code, subj in (("no-description", "Add Description= to sala-codes.timer"), ("bad-lane", "Correct X-Model-Lane= of sala-codes.timer"), ("git-differs", "Match sala-codes.timer to its file in git"),
                       ("odd-new-code", "Fix the odd-new-code gap of sala-codes.timer")):
        st, o = jg("open", timer="sala-codes.timer", code=code)
        check(f"code {code}: its task in the subject", st == 200 and item(o["item"])["subject"] == f"{subj}", (st, o, item(o["item"])["subject"] if st == 200 else ""))
        jg("clear", timer="sala-codes.timer", code=code, repo=None)
    st, o = jg("open", timer="sala-codes.timer", code="odd-new-code")
    oi = item(o["item"])
    check("a code outside the five: a neutral fix line (the watcher's report), not the not-git text", "see the watcher's report" in oi["description"] and oi["metadata"]["next"].startswith("home-sparrow-builder: see the watcher's report for the fix to sala-codes.timer")
          and "X-Model-Lane=" not in oi["metadata"]["next"] and "put sala-codes.timer" not in oi["description"], (oi["description"], oi["metadata"]["next"]))
    jg("clear", timer="sala-codes.timer", code="odd-new-code", repo=None)
    st, o = jg("open", timer="sala-known.timer", code="no-description")
    check("…a known code keeps its own fix", "Description=" in item(o["item"])["metadata"]["next"] and "see the watcher's report" not in item(o["item"])["description"], item(o["item"])["metadata"]["next"])
    jg("clear", timer="sala-known.timer", code="no-description", repo=None)

    # ---- 2b. mentions: no @name reaches the item (the GitHub mirror would ping that user)
    def bare_at(text): return re.search(r"(?<!\w)@(?!​)\w", str(text)) is not None      # a mention starts at an @ after a non-word character (job@1 and me@host are no mention)
    n_m = len(items())
    for bad in ("a.@name", "@name", "name@", "a@@b", "a@.b", "a.timer@", "a-@b", "ab@c@d.@e"):
        st, e = jg("open", timer=bad)
        check(f"a timer {bad!r} with an @ that starts a mention: 400, nothing filed", st == 400 and len(items()) == n_m, (st, e))
    st, o = jg("open", timer="sala-job@1.service", detail="the file is /home/@octocat/x.timer, mail me@example.org or ask @octocat")
    oi = item(o["item"])
    check("an @ between letters or digits in a timer (a template unit) is taken", st == 200 and oi["subject"] == "Add X-Model-Lane= to sala-job@1.service", (st, o, oi["subject"]))
    check("…and an @name in the detail is broken in the description (no bare @ before a word), the text otherwise kept", not bare_at(oi["description"]) and "octocat" in oi["description"] and "/home/@​octocat/x.timer" in oi["description"], oi["description"])
    jg("clear", timer="sala-job@1.service", repo=None)
    st, o = jg("open", timer="sala-sender.timer", sender="@octocat-bot")
    oi = item(o["item"])
    check("an @name in the sender is broken everywhere the label is written: the description, the creator", st == 200 and not bare_at(oi["description"]) and not bare_at(oi["filed_by"]) and "octocat-bot" in oi["filed_by"], (st, oi["description"], oi["filed_by"]))
    check("…and a clear by the same label does not ping either", not bare_at(item(jg("clear", timer="sala-sender.timer", repo=None, sender="@octocat-bot")[1]["cleared"][0])["description"]))

    # ---- 3. clear: closes the item; none open is a 200 that says so; an open after a clear files a new item
    n2 = len(items()); pushed.clear()
    st, c = jg("clear", repo=None)
    check("clear: 200 with the closed item's id, the timer and the code", st == 200 and c["cleared"] == [gid1] and c["timer"] == "sala-foo.timer" and c["code"] == "no-lane", (st, c))
    it = item(gid1)
    check("…the item is completed, outcome done, a one-line reason within the limit that names the code, the end state in outcome_text and the description kept", it["status"] == "completed" and it["metadata"].get("outcome") == "done"
          and "no-lane is fixed on sala-foo.timer" in it["metadata"].get("reason", "") and len(it["metadata"]["reason"]) <= _fg._close_reason_max() and it["metadata"]["outcome_text"].splitlines()[0] == "- sala-foo.timer: the gap (no-lane) is fixed"
          and it["metadata"]["outcome_text"].splitlines()[-1].startswith("- Closed by sala-unit-gaps (a script on") and "is fixed" not in it["description"], (it["status"], it["metadata"].get("reason"), it["description"]))
    settle()
    check("…the close tells no session and charges no page; the other gaps stay open", pushed == [] and _pdebts._owed_load() == {} and open_for("sala-foo.timer", "not-git") != [] and open_for("sala-foo.timer", "no-lane") == [], (pushed, _pdebts._owed_load()))
    st, c2 = jg("clear", repo=None)
    check("clear with none open: 200, nothing cleared, a note that says so", st == 200 and c2["cleared"] == [] and "no open item for sala-foo.timer: no-lane" in c2["note"], (st, c2))
    st, c3 = jg("clear", timer="never-seen.timer", code="no-lane", repo=None)
    check("clear for a gap never opened: the same no-op", st == 200 and c3["cleared"] == [] and len(items()) == n2, (st, c3))
    st, o6 = jg("open")
    check("an open again after a clear files a new item", st == 200 and o6["item"] != gid1 and o6["repeat"] is False and item(o6["item"])["status"] == "open" and item(gid1)["status"] == "completed", (st, o6))
    jg("clear", repo=None)

    # ---- 4. repos: unknown (400 naming the known ones), the map, a repo with no builder, a project with no front agent, a page missing
    n3 = len(items())
    st, e = jg("open", repo="acme/unknown")
    check("an unknown repo: 400 naming the known repos, nothing filed", st == 400 and "acme/unknown" in e["error"] and "acme/alpha" in e["error"] and "acme/nobuild" in e["error"] and len(items()) == n3, (st, e))
    st, e = jg("open", repo=None)
    check("no repo on an open: 400 that names the option", st == 400 and "--repo" in e["error"] and len(items()) == n3, (st, e))
    for bad in ("alpha", "a/b/c", "acme/", "/alpha", "acme/al pha", "acme/alpha;rm"):
        st, e = jg("open", repo=bad)
        check(f"a repo {bad!r} that is not owner/name: 400, nothing filed", st == 400 and len(items()) == n3, (st, e))
    st, o = jg("open", timer="sala-case.timer", repo="ACME/MIXED-case")
    check("the repo name is matched in any case (through the repo name canon)", st == 200 and o["project"] == "projects/alpha", (st, o))
    jg("clear", timer="sala-case.timer", repo=None)
    pushed.clear()
    st, o = jg("open", timer="sala-nb.timer", repo="acme/nobuild")
    it = item(o["item"]) if st == 200 else {"metadata": {}, "description": ""}
    check("a project with no builder: 200, the -main agent is mover and keeper, the answer says fallback", st == 200 and o["fallback"] is True and o["mover"] == "home-nobuild-main" and o["owner"] == "home-nobuild-main"
          and o["project"] == "projects/nobuild", (st, o))
    settle()
    check("…the item says so: a description bullet and a next that names the -main agent; nobody is in needs and no one is pushed", "lists no builder" in it["description"] and it["metadata"]["next"].startswith("home-nobuild-main: ")
          and not it["metadata"].get("needs") and sr._session_label(it["metadata"].get("mover")) == "home-nobuild-main" and pushed == [], (it["description"], it["metadata"], pushed))
    st, o7 = jg("open", timer="sala-nb.timer", repo="acme/nobuild")
    check("…and a repeat answers the same item with the fallback still true", st == 200 and o7["item"] == o["item"] and o7["repeat"] is True and o7["fallback"] is True, (st, o7))
    jg("clear", timer="sala-nb.timer", repo=None)
    st, e = jg("open", timer="sala-g.timer", repo="acme/gamma")
    check("a project that lists no front agent: 409, nothing filed", st == 409 and "front agent" in e["error"] and open_for("sala-g.timer", "no-lane") == [], (st, e))
    st, e = jg("open", timer="sala-g.timer", repo="acme/ghost")
    check("a repo mapped to a page that is not in the registry: 409 that says to fix the map", st == 409 and "projects/ghost" in e["error"] and "no project page" in e["error"], (st, e))
    # the defaults: no [job_gap] section at all -> the fleet's three repos
    _cfg.CFG.pop("job_gap", None)
    check("the defaults (no [job_gap.repos]): no repo is listed (the code names none)", job_gap_svc._jobgap_repos() == {}, job_gap_svc._jobgap_repos())
    _cfg.CFG["job_gap"] = {"repos": {"example-owner/ops-hub": "ops/general", "example-org/fleet-tool": "projects/fleet-tool", "example-org/board": "projects/board"}}   # the example-owner instance's table
    pushed.clear()
    st, o = jg("open", timer="sala-hub.timer", repo="example-owner/ops-hub", code="not-git")
    check("…ledger-hub is ops/general, its builder heron-engineer is the mover, heron-main the keeper", st == 200 and o["project"] == "ops/general" and o["mover"] == "heron-engineer" and o["owner"] == "heron-main"
          and item(o["item"])["metadata"]["next"].startswith("heron-engineer: put sala-hub.timer's unit file in example-owner/ops-hub"), (st, o))
    settle()
    check("…and the builder is told", len(pushed) == 1 and pushed[0][0] in ("heron-engineer", S["gbuild"]), pushed)
    jg("clear", timer="sala-hub.timer", code="not-git", repo=None)
    _cfg.CFG["job_gap"] = {"repos": "not a table"}
    st, e = jg("open", repo="acme/alpha")
    check("a [job_gap] repos that is not a table lists no repo: 400 'none is listed'", st == 400 and "none is listed" in e["error"], (st, e))
    _cfg.CFG["job_gap"] = {"repos": {"acme/alpha": "projects/alpha", "acme/odd": 7}}
    check("…an entry that is not text is skipped", job_gap_svc._jobgap_repos() == {"acme/alpha": "projects/alpha"}, job_gap_svc._jobgap_repos())

    # ---- 5. the sender gate: the terminal prompt's (a label of at most 80 characters on one line, never the owner's name); none given is client.py
    n4 = len(items())
    for who in ("Oliver", "oliver"):
        st, e = jg("open", sender=who)
        check(f"a sender that names the owner ({who!r}): 400 with the server's refusal, nothing filed", st == 400 and "Only the board writes as" in e["error"] and len(items()) == n4, (st, e))
    st, e = jg("clear", sender="Oliver", repo=None)
    check("…a clear is refused the same way", st == 400 and "Only the board writes as" in e["error"], (st, e))
    st, e = jg("open", sender="s" * 81)
    check("a sender over 80 characters: 400", st == 400 and "at most 80" in e["error"] and len(items()) == n4, (st, e))
    st, e = jg("open", sender="a\nb")
    check("a sender over several lines: 400", st == 400 and "one line" in e["error"] and len(items()) == n4, (st, e))
    st, o = jg("open", timer="sala-nosender.timer", sender=None)
    check("no sender: taken as client.py, recorded as the creator", st == 200 and item(o["item"])["filed_by"] == f"client.py via a script on {me}", (st, o))
    jg("clear", timer="sala-nosender.timer", repo=None, sender=None)
    st, o = jg("open", timer="sala-label80.timer", sender="s" * 80)
    check("a sender of exactly 80 characters is taken", st == 200, (st, o)); jg("clear", timer="sala-label80.timer", repo=None, sender="s" * 80)

    # ---- 6. a subject that is too long is cut, never refused
    _cfg.CFG["job_gap"] = {"repos": {"acme/alpha": "projects/alpha", "acme/nobuild": "projects/nobuild"}}
    LONG = "sala-" + "very-long-unit-name-" * 5 + "x.timer"          # 105 characters: the subject would be over 80
    st, o = jg("open", timer=LONG, code="no-lane")
    sub = item(o["item"])["subject"] if st == 200 else ""
    check("a unit name too long for the subject limit still opens: 200, a subject of at most 80 characters that keeps the task and the cut name", st == 200 and len(sub) <= 80 and sub.startswith("Add X-Model-Lane= to sala-very-long")
          and sub.endswith(" …"), (st, o, sub))
    check("…the mark keeps the whole name and a clear by the whole name closes it", item(o["item"])["metadata"]["job_gap"] == f"{LONG}: no-lane" and jg("clear", timer=LONG, repo=None)[1]["cleared"] == [o["item"]])
    st, o = jg("open", timer="t" * 120, code="a" * 40)
    sub = item(o["item"])["subject"] if st == 200 else ""
    check("the longest timer and code the call takes: still a subject within the limit", st == 200 and len(sub) <= 80, (st, o, sub)); jg("clear", timer="t" * 120, code="a" * 40, repo=None)
    st, o = jg("open", timer="sala-detail.timer", detail="x" * 600)
    dd = item(o["item"])["description"].splitlines() if st == 200 else []
    max_lines, line_max = _fg._description_limits()
    check("a detail of 600 characters: the bullet is cut to the line limit, the item is made", st == 200 and len(dd) <= max_lines and all(len(x) <= line_max for x in dd) and any("xxx" in x and x.endswith("…") for x in dd), (st, dd))
    jg("clear", timer="sala-detail.timer", repo=None)
    st, e = jg("open", timer="sala-detail.timer", detail="y" * 601)
    check("a detail over 600 characters: 400, nothing filed", st == 400 and "at most 600" in e["error"] and open_for("sala-detail.timer", "no-lane") == [], (st, e))
    st, o = jg("open", timer="sala-words.timer", detail="a fatal breach: the token is exposed and the box was killed")
    check("the watcher's detail is not judged for alarming words (a script's item is never lost on a wording refusal)", st == 200, (st, o)); jg("clear", timer="sala-words.timer", repo=None)
    st, o = jg("open", timer="sala-multi.timer", detail="line one\nline two\n\nline three")
    check("a multi-line detail is joined into one bullet", st == 200 and "- line one line two line three" in item(o["item"])["description"], (st, o)); jg("clear", timer="sala-multi.timer", repo=None)

    # ---- 7. bad input: nothing filed
    n5 = len(items())
    for name, kw in (("a bad action", dict(action="reopen")), ("an empty timer", dict(timer="")), ("a timer with a space", dict(timer="a b.timer")), ("a timer with markup", dict(timer="a<b>.timer")),
                     ("a timer with a mention", dict(timer="a@b c")), ("a timer starting with a dot", dict(timer=".hidden")), ("a timer of 121 characters", dict(timer="t" * 121)),
                     ("an empty code", dict(code="")), ("a code in capitals", dict(code="No-Lane")), ("a code with a space", dict(code="no lane")), ("a code of 41 characters", dict(code="c" * 41))):
        action = kw.pop("action", "open")
        st, e = jg(action, **kw)
        check(f"{name}: 400, nothing filed", st == 400 and len(items()) == n5, (st, e))
    st, e = jg("clear", timer="a b", repo=None)
    check("a clear with a bad timer is refused the same way", st == 400, (st, e))
    for ok in ("sala-job@1.service", "user.slice:job.timer", "a_b.c-d.timer"):
        st, o = jg("open", timer=ok)
        check(f"a plain unit name {ok!r} is taken", st == 200 and item(o["item"])["metadata"]["job_gap"] == f"{ok}: no-lane", (st, o)); jg("clear", timer=ok, repo=None)

    # ---- 8. concurrency: one gap, many calls, one item
    n6 = len(items()); res = []
    ths = [threading.Thread(target=lambda: res.append(jg("open", timer="sala-race.timer"))) for _ in range(8)]
    [t.start() for t in ths]; [t.join() for t in ths]
    check("eight threads opening one gap at once file one item and all get its id", len(items()) == n6 + 1 and len({r[1]["item"] for r in res}) == 1 and all(r[0] == 200 for r in res) and sum(1 for r in res if not r[1]["repeat"]) == 1, res[:3])
    ths = [threading.Thread(target=lambda: res.append(jg("clear", timer="sala-race.timer", repo=None))) for _ in range(4)]
    [t.start() for t in ths]; [t.join() for t in ths]
    check("…and four clears at once close it once, the others find none", all(r[0] == 200 for r in res[8:]) and sum(len(r[1]["cleared"]) for r in res[8:]) == 1 and open_for("sala-race.timer", "no-lane") == [], res[8:])
    settle()

    # ---- 9. over HTTP and through client.py
    app = server.mcp.http_app()
    with TestClient(app) as c:
        r = c.post("/client/job-gap", json={"action": "open", "timer": "x.timer", "code": "no-lane", "repo": "acme/alpha"}); check("http: without a token -> 401", r.status_code == 401, r.status_code)
        r = c.post("/client/job-gap", json={"action": "open", "timer": "http.timer", "code": "no-lane", "repo": "acme/alpha", "sender": "http-script"}, headers=HD)
        check("http: with a machine token -> 200 and the item", r.status_code == 200 and r.json()["repeat"] is False and r.headers["cache-control"] == "no-store", r.text)
        gid_http = r.json()["item"]
        r = c.post("/client/job-gap", json={"action": "open", "timer": "http.timer", "code": "no-lane", "repo": "acme/zzz", "sender": "http-script"}, headers=HD)
        check("http: an unknown repo is a 400 with the known ones, even for a gap that is open", r.status_code == 400 and "acme/alpha" in r.json()["error"], r.text)
        r = c.post("/client/job-gap", json={"action": "clear", "timer": "http.timer", "code": "no-lane", "sender": "http-script"}, headers=HD)
        check("http: clear -> 200 and the closed item", r.status_code == 200 and r.json()["cleared"] == [gid_http], r.text)
        import urllib.request, urllib.error
        class _Resp:
            def __init__(s, r): s.status = r.status_code; s._b = r.content
            def read(s): return s._b
            def __enter__(s): return s
            def __exit__(s, *a): return False
        down = {"on": False}
        def fake_urlopen(req, timeout=0):
            if down["on"]: raise urllib.error.URLError("connection refused")
            path = req.full_url.replace(client.server_url(), "")
            r = c.post(path, content=req.data, headers=dict(req.header_items())) if req.get_method() == "POST" else c.get(path, headers=dict(req.header_items()))
            if r.status_code >= 400: raise urllib.error.HTTPError(req.full_url, r.status_code, "x", {}, io.BytesIO(r.content))
            return _Resp(r)
        client.urllib.request.urlopen = fake_urlopen
        def run(*argv):
            so, se = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(so), contextlib.redirect_stderr(se): rc = client.main(["client.py", *argv])
            return rc, so.getvalue(), se.getvalue()
        before = len(items())
        rc, o, e = run("post", "job-gap", "open", "cli.timer", "no-lane", "--repo", "acme/alpha", "--detail", "file /x/cli.timer", "--sender", "sala-unit-gaps")
        gid_cli = o.strip()
        check("client.py open: exactly the item id on stdout, nothing on stderr, exit 0, one item filed", rc == 0 and re.fullmatch(r"\S+\n", o) and e == "" and len(items()) == before + 1, (rc, o, e))
        check("…the item is the gap's open item, with the detail", item(gid_cli)["metadata"]["job_gap"] == "cli.timer: no-lane" and item(gid_cli)["status"] == "open" and "file /x/cli.timer" in item(gid_cli)["description"])
        rc, o2, e = run("post", "job-gap", "open", "cli.timer", "no-lane", "--repo", "acme/alpha")
        check("client.py open again: the same id printed, exit 0, nothing filed (no --sender: client.py)", rc == 0 and o2 == o and e == "" and len(items()) == before + 1, (rc, o2, e))
        rc, o, e = run("post", "job-gap", "clear", "cli.timer", "no-lane", "--sender", "sala-unit-gaps")
        check("client.py clear: the closed item's id on stdout, exit 0, the item closed", rc == 0 and o.strip() == gid_cli and e == "" and item(gid_cli)["status"] == "completed" and item(gid_cli)["metadata"]["outcome"] == "done", (rc, o, e))
        rc, o, e = run("post", "job-gap", "clear", "cli.timer", "no-lane", "--sender", "sala-unit-gaps")
        check("client.py clear with none open: exit 0, nothing on stdout, a note on stderr that says so", rc == 0 and o == "" and "no open item" in e, (rc, o, e))
        rc, o, e = run("post", "job-gap", "open", "nb.timer", "not-git", "--repo", "acme/nobuild", "--sender", "sala-unit-gaps")
        check("client.py open for a project with no builder: the id on stdout, exit 0, the fallback said on stderr", rc == 0 and re.fullmatch(r"\S+\n", o) and "no builder" in e and "home-nobuild-main" in e, (rc, o, e))
        run("post", "job-gap", "clear", "nb.timer", "not-git")
        before = len(items())
        U = "usage: client.py post job-gap"
        for name, argv, needle in (("no verb", [], U), ("a wrong verb", ["reopen", "x.timer", "no-lane"], U), ("open without --repo", ["open", "x.timer", "no-lane"], "--repo"),
                                   ("open without a code", ["open", "x.timer", "--repo", "acme/alpha"], U), ("open without a timer", ["open", "--repo", "acme/alpha"], U),
                                   ("clear without a code", ["clear", "x.timer"], U), ("clear with a --repo", ["clear", "x.timer", "no-lane", "--repo", "acme/alpha"], U), ("clear with a --detail", ["clear", "x.timer", "no-lane", "--detail", "d"], U),
                                   ("a flag with no value", ["open", "x.timer", "no-lane", "--repo"], "needs a value"), ("a stray word", ["open", "x.timer", "no-lane", "stray", "--repo", "acme/alpha"], U),
                                   ("a detail over 600 characters", ["open", "x.timer", "no-lane", "--repo", "acme/alpha", "--detail", "d" * 601], "at most 600")):
            rc, o, e = run("post", "job-gap", *argv)
            check(f"client.py misuse, {name}: usage or reason on stderr, nothing on stdout, exit 1", rc == 1 and o == "" and needle in e, (rc, o, e))
        check("…and none of them filed an item", len(items()) == before, (len(items()), before))
        rc, o, e = run("post", "job-gap", "open", "x.timer", "no-lane", "--repo", "acme/elsewhere", "--sender", "sala-unit-gaps")
        check("client.py open for an unknown repo: the server's 400 with the known repos on stderr, exit 1, nothing on stdout", rc == 1 and o == "" and "[400]" in e and "acme/alpha" in e and len(items()) == before, (rc, o, e))
        rc, o, e = run("post", "job-gap", "open", "x.timer", "no-lane", "--repo", "acme/alpha", "--sender", "Oliver")
        check("client.py open with a sender that names the owner: the server's refusal on stderr, exit 1", rc == 1 and o == "" and "[400]" in e and "Only the board writes as" in e, (rc, o, e))
        tokfile = pathlib.Path(client.TOKEN); hold = tokfile.with_suffix(".held"); tokfile.rename(hold)
        try:
            rc, o, e = run("post", "job-gap", "open", "x.timer", "no-lane", "--repo", "acme/alpha")
            check("client.py open with no token on the machine: exit 1, the reason on stderr, nothing filed", rc == 1 and o == "" and "no token on this machine" in e and len(items()) == before, (rc, o, e))
        finally: hold.rename(tokfile)
        _post = client.post
        client.post = lambda what, body, timeout=20.0: (200, {"project": "projects/alpha"})
        try:
            rc, o, e = run("post", "job-gap", "open", "x.timer", "no-lane", "--repo", "acme/alpha")
            check("client.py open when the answer has no item id: exit 1 with a line on stderr, never silent", rc == 1 and o == "" and "no item id" in e, (rc, o, e))
        finally: client.post = _post
        down["on"] = True
        rc, o, e = run("post", "job-gap", "open", "x.timer", "no-lane", "--repo", "acme/alpha")
        check("client.py open with the server not reached: exit 1 and the reason on stderr", rc == 1 and o == "" and e.strip() != "" and len(items()) == before, (rc, o, e))
        rc, o, e = run("post", "job-gap", "clear", "x.timer", "no-lane")
        check("client.py clear with the server not reached: exit 1", rc == 1 and o == "", (rc, o, e))
        down["on"] = False
    settle()

# ======== part 2: a pane waiting in its terminal (the former terminal_prompt suite) ========
def part_terminal_prompt():
    SALA = "https://sala.example.org/#s="
    def tp(action, session="home-sparrow-builder", question="May I run the migration against the staging database?", sender="sala-hook", machine=None, **kw):
        b = {"action": action, "session": session, "sender": sender}
        if question is not None: b["question"] = question
        b.update(kw)
        return _rt_client._client_post(machine or me, "terminal-prompt", {k: v for k, v in b.items() if v is not None})
    def nxt(name, question): return f"Oliver: open {SALA}{name} and answer: `{question}`"
    def open_for(session): return [g for g in terminal_prompt_svc._terminal_open_items(session)]
    n0 = len(items())

    # ---- 1. open: the item and its shape
    Q = "May I run the migration against the staging database?"
    st, out = tp("open", "home-sparrow-builder", Q)
    check("open: 200 with the item id as shown, the session's name, the project, repeat false", st == 200 and out["session"] == "home-sparrow-builder" and out["project"] == "projects/alpha" and out["repeat"] is False
          and out["item"] == _gh.shown(_model_ids._norm_id(out["item"])), (st, out))
    it = item(out["item"]); m = it["metadata"]
    check("the item is open, filed under the session's project from the registry, marked with the resolved session name", it["status"] == "open" and m["project"] == "projects/alpha" and m["terminal_prompt"] == "home-sparrow-builder", (it["status"], m))
    check("…the subject names the session and what it waits for", it["subject"] == "Answer home-sparrow-builder in its terminal", it["subject"])
    check("…priority p1; the owner is the mover; state your-step with the one-line step, no command", m.get("priority") == "p1" and m.get("mover") == "Oliver" and m.get("state") == "your-step"
          and m.get("step") == "Answer home-sparrow-builder's question in its terminal" and "`" not in m["step"], m)
    check("…next is the one line that links the pane and carries the question", m.get("next") == nxt("home-sparrow-builder", Q), m.get("next"))
    check("…the keeper of record is the project's -main agent (not the background builder that is asking), the script is the creator", sr._session_label(m["owner"]) == "home-sparrow-main"
          and it["filed_by"] == f"sala-hook via a script on {me}", (m["owner"], it.get("filed_by")))
    check("…the description is bullets that say who waits and who opened it", it["description"].splitlines()[0] == "- home-sparrow-builder is waiting in its terminal for Oliver's answer"
          and it["description"].splitlines()[-1] == f"- Opened by sala-hook (a script on {me}); it closes when the pane stops waiting", it["description"])
    mod = M.derive(it)
    check("…the item is alive with the owner as the mover: it is in his Your move list", H_.list_of(mod) == H_.YOUR_MOVE and mod.state == M.ALIVE, (mod.state, mod.mover))
    check("…and nothing else is made or told: one item, no message to any session", len(items()) == n0 + 1 and pushed == [], (len(items()) - n0, pushed))
    check("…the row owes no page: no debt is charged to the script, the keeper of record, the page's keeper or anyone (the page is older than the item, so a debt would stand)", _pdebts._owed_load() == {}, _pdebts._owed_load())
    check("…the item is in the brief as the owner's", out["item"] in _wt_get.stackshot_get(out["item"]) and "your-step" in _wt_get.stackshot_get(out["item"]), _wt_get.stackshot_get(out["item"])[:300])

    # ---- 1b. a long pane name: the server's own subject is cut to the limit, never refused
    st, outl = tp("open", LONGNAME, Q)
    itl = item(outl["item"]) if st == 200 else {"subject": ""}
    check("a pane name too long for the subject limit still opens: 200, a subject of at most 80 characters that keeps the words after the name",
          st == 200 and len(itl["subject"]) <= 80 and itl["subject"].startswith("Answer home-sparrow-n") and itl["subject"].endswith(" …" + " in its terminal"), (st, outl, itl["subject"]))
    check("…the marker keeps the whole name", itl["metadata"]["terminal_prompt"] == LONGNAME if st == 200 else False)
    st, _c = tp("clear", LONGNAME, None)
    check("…and it clears", st == 200 and _c["cleared"], (st, _c))

    # ---- 2. a second open: the question changes, nothing is created
    n1 = len(items()); Q2 = "Run it now, or wait for the nightly window?"
    st, out2 = tp("open", "home-sparrow-builder", Q2)
    check("a second open for the session answers the same item, marked a repeat, and files nothing", st == 200 and out2["item"] == out["item"] and out2["repeat"] is True and len(items()) == n1, (st, out2))
    m2 = item(out["item"])["metadata"]
    check("…its next line is the new question, one line only (the old one is replaced, not kept beside it)", m2["next"] == nxt("home-sparrow-builder", Q2) and len([l for l in m2["next"].splitlines() if l.strip()]) == 1, m2.get("next"))
    check("…the state, step, mover and mark are as they were", m2["state"] == "your-step" and m2["mover"] == "Oliver" and m2["terminal_prompt"] == "home-sparrow-builder" and m2["step"] == m["step"], m2)
    upd = item(out["item"]).get("updated")
    st, out2b = tp("open", "home-sparrow-builder", Q2)
    check("the same question again writes nothing (the item's clock does not move)", st == 200 and out2b["repeat"] is True and item(out["item"]).get("updated") == upd and len(items()) == n1, (st, out2b))
    check("…and no message went to any session", pushed == [], pushed)

    # ---- 3. the session through the registry: an id, a transcript id, an old name and the current name are one session
    for how, ref in (("a sala id", S["eng"]), ("an old transcript id", Tr["eng_old"]), ("the current transcript id", Tr["eng_new"]), ("an old name (an alias)", "home-sparrow-eng"), ("the current name", "home-sparrow-builder")):
        st, o = tp("open", ref, f"asked through {how}")
        check(f"open through {how}: the same item, the question changed, nothing created", st == 200 and o["item"] == out["item"] and o["repeat"] is True and len(items()) == n1
              and item(out["item"])["metadata"]["next"] == nxt("home-sparrow-builder", f"asked through {how}"), (st, o, len(items()) - n1))
    check("…the mark is still the resolved name, not the reference the call used", item(out["item"])["metadata"]["terminal_prompt"] == "home-sparrow-builder")
    # another session of the same project has its own item
    st, oo = tp("open", "home-other", "Is the plan right?")
    check("another session has its own item, under the same project, owned by the same -main agent", st == 200 and oo["item"] != out["item"] and oo["repeat"] is False and len(items()) == n1 + 1
          and item(oo["item"])["metadata"]["terminal_prompt"] == "home-other", (st, oo))
    # the session found by an old name when it was renamed after the item was filed: the mark is the old name, the call uses the new one
    rn = _service_store._load(_model_ids._norm_id(oo["item"])); rn["metadata"]["terminal_prompt"] = "home-sparrow-eng"; writes.save(_model_ids._norm_id(oo["item"]), rn)
    check("a mark that holds an old name (a rename since) still matches the session by the registry", terminal_prompt_svc._terminal_open_items("home-sparrow-builder") == [_model_ids._norm_id(out["item"]), _model_ids._norm_id(oo["item"])]
          or terminal_prompt_svc._terminal_open_items("home-sparrow-builder") == sorted([_model_ids._norm_id(out["item"]), _model_ids._norm_id(oo["item"])]), terminal_prompt_svc._terminal_open_items("home-sparrow-builder"))
    rn["metadata"]["terminal_prompt"] = "home-other"; writes.save(_model_ids._norm_id(oo["item"]), rn)
    st, c2 = tp("clear", "home-other", None)
    check("…and a clear of one session closes only its own item", c2["cleared"] == [oo["item"]] and item(oo["item"])["status"] == "completed" and item(out["item"])["status"] == "open", (c2, item(out["item"])["status"]))

    # ---- 4. the project: the registry's, else projects/example-two
    st, ol = tp("open", "home-loner", "Which branch?")
    check("a session the registry gives no project is filed under projects/example-two, owned by its -main agent, with no tag in the subject", st == 200 and ol["project"] == "projects/example-two"
          and sr._session_label(item(ol["item"])["metadata"]["owner"]) == "example-two-main" and item(ol["item"])["subject"].startswith("Answer home-loner in its terminal"), (st, ol))
    st, onf = tp("open", "home-nofront", "Which branch?")
    check("…and so is a session whose project lists no front agent", st == 200 and onf["project"] == "projects/example-two", (st, onf))
    st, osl = tp("open", "home-slug", "Which branch?")
    check("a project given by its bare name only is found as the question route finds one", st == 200 and osl["project"] == "projects/alpha", (st, osl))
    st, ou = tp("open", "home-unknown-pane", "Which branch?")
    check("a session no registry holds is filed too, under projects/example-two, by the name it was given", st == 200 and ou["project"] == "projects/example-two" and item(ou["item"])["metadata"]["terminal_prompt"] == "home-unknown-pane", (st, ou))
    for who in ("home-loner", "home-nofront", "home-slug", "home-unknown-pane"): tp("clear", who, None)

    # ---- 5. clear
    n2 = len(items()); gid = out["item"]
    st, cl = tp("clear", "home-sparrow-eng", None)           # by the old name
    it = item(gid)
    check("clear (by an old name): 200, names the closed item", st == 200 and cl["cleared"] == [gid] and cl["session"] == "home-sparrow-builder", (st, cl))
    check("…the item is completed with outcome done and the reason \"the pane stopped waiting\"", it["status"] == "completed" and it["metadata"]["outcome"] == "done" and it["metadata"]["reason"] == "the pane stopped waiting", it["metadata"])
    check("…it keeps no state, mover or next (a closed item is dead), and the end state goes in outcome_text, the description stays as it was", "state" not in it["metadata"] and "mover" not in it["metadata"] and not it["metadata"].get("next")
          and it["metadata"]["outcome_text"].splitlines()[0] == "- home-sparrow-builder stopped waiting in its terminal" and "pane stopped waiting" in it["metadata"]["outcome_text"]
          and "stopped waiting" not in it["description"].splitlines()[-1], it)
    check("…it is in no list (dead)", M.derive(it).state == M.DEAD, M.derive(it).state)
    check("…nothing was told to any session (the keeper of record, the builder, the router), no debt, and no item was made", pushed == [] and _pdebts._owed_load() == {} and len(items()) == n2, (pushed, _pdebts._owed_load(), len(items()) - n2))
    upd = it.get("updated")
    st, cl2 = tp("clear", "home-sparrow-builder", None)
    check("clear with none open is a no-op: 200, nothing cleared, the closed item untouched", st == 200 and cl2["cleared"] == [] and item(gid).get("updated") == upd and len(items()) == n2, (st, cl2))
    st, cl3 = tp("clear", "home-never-seen", None)
    check("clear for a session that has no item and is in no registry: 200, nothing", st == 200 and cl3["cleared"] == [], (st, cl3))
    st, o3 = tp("open", "home-sparrow-builder", "A new question after the first cleared")
    check("an open after a clear files a new item (the closed one stays closed)", st == 200 and o3["repeat"] is False and o3["item"] != gid and item(gid)["status"] == "completed" and item(o3["item"])["status"] == "open", (st, o3))
    tp("clear", "home-sparrow-builder", None)

    # ---- 6. refused: nothing filed
    def refused(name, needle, action="open", **kw):
        before = len(items()); st, o = tp(action, **kw)
        check(name, st == 400 and needle in o.get("error", "") and len(items()) == before, (st, o)); return o.get("error", "")
    refused("an empty question is refused", "question is required", question="  ")
    refused("a question missing is refused", "question is required", question=None)
    refused("a question of 201 characters is refused with its length", "at most 200 characters (201 now)", question="x" * 201)
    st, ok_a = tp("open", question="y" * 200); check("…200 characters exactly is taken", st == 200 and ok_a["repeat"] is False, (st, ok_a)); tp("clear", "home-sparrow-builder", None)
    refused("a question of several lines is refused", "one line", question="first line\nsecond line")
    refused("a question with a control character is refused", "one line", question="tab\there")
    refused("no sender is refused", "sender", sender="")
    refused("a sender that names the owner is refused", "Only the board writes as", sender="Oliver")
    refused("a sender with a line break is refused", "sender", sender="a\nb")
    refused("a session missing is refused", "session", session="")
    refused("a session of more than 120 characters is refused", "session", session="s" * 121)
    refused("an action that is neither open nor clear is refused", "action = open | clear", action="reopen")
    refused("a clear with no sender is refused", "sender", action="clear", question=None, sender="")
    st, o = _rt_client._client_post(me, "terminal-prompt", {"action": "open", "session": "home-sparrow-builder", "sender": "s", "question": 5}); check("a question that is not a string is refused", st == 400, (st, o))
    check("…the refusals left no item and no part of one", terminal_prompt_svc._terminal_open_items("home-sparrow-builder") == [], terminal_prompt_svc._terminal_open_items("home-sparrow-builder"))

    # ---- 7. what a pane writes: alarming words, a long line, characters
    ALARM = "Shall I kill the stuck run and rotate the credentials, or leave the quota alone?"
    st, oa = tp("open", question=ALARM)
    check("a question with alarming words (kill, credentials, quota) is filed: a pane's own words are not judged", st == 200 and item(oa["item"])["metadata"]["next"] == nxt("home-sparrow-builder", ALARM), (st, oa))
    create_says = ""
    try: _wt_create.stackshot_create(subject="[home] Kill the run?", description="- Goal: A thing", project="projects/alpha", owner="home-sparrow-main", next="Oliver: kill it and rotate the credentials")
    except ToolError as e: create_says = str(e)
    check("…while the create tool refuses the same words (the exemption is that route's only)", "uses \"" in create_says and not getattr(writes.QUESTION, "on", False), create_says[:200])
    tp("clear", "home-sparrow-builder", None)
    LONG = "Should I " + " ".join(f"word{i}" for i in range(1, 40)) + " end?"
    LONG = LONG[:200]
    st, ol2 = tp("open", question=LONG)
    nl = item(ol2["item"])["metadata"]["next"]
    check("a question that overruns the next-line limit is filed, cut at a word with an ellipsis (the link does not count)", st == 200 and nl.endswith(" …`") and len(nl.replace(SALA + "home-sparrow-builder", "")) <= 200 and nl.startswith(f"Oliver: open {SALA}home-sparrow-builder and answer: `Should I word1"), (st, nl, len(nl)))
    st, ol3 = tp("open", question=LONG[:150])
    check("…one that fits is kept whole", ol3["repeat"] is True and item(ol2["item"])["metadata"]["next"] == nxt("home-sparrow-builder", LONG[:150]), item(ol2["item"])["metadata"]["next"])
    # another writer's line beside the question survives a changed question; the old question is a dropped step
    _update_svc._update(ol2["item"], next=item(ol2["item"])["metadata"]["next"] + "\nhome-sparrow-builder: check the nightly run", sender="home-sparrow-builder")
    st, ol4 = tp("open", question="Another question?")
    m4 = item(ol2["item"])["metadata"]
    check("a changed question replaces only the terminal's own line: another session's line stays, the old question is a dropped step",
          st == 200 and "home-sparrow-builder: check the nightly run" in m4["next"] and "Another question?" in m4["next"] and LONG[:40] not in m4["next"]
          and any(s["status"] == "dropped" and "and answer:" in s["text"] for s in m4.get("steps", [])), m4)
    tp("clear", "home-sparrow-builder", None)
    st, ou2 = tp("open", question="Which one: a/b? 100% sure — `rm -rf` (yes/no) [x] \"quoted\" ünïcode 日本語?")
    check("punctuation and non-ASCII are kept in the next line, a backtick in the question becomes an apostrophe (the question stands as a code span)", st == 200 and item(ou2["item"])["metadata"]["next"].endswith("'rm -rf' (yes/no) [x] \"quoted\" ünïcode 日本語?`"), (st, item(ou2["item"])["metadata"]["next"] if st == 200 else ou2))
    tp("clear", "home-sparrow-builder", None)
    st, ow = tp("open", session="pane/odd?name", question="Q")
    check("a session name with a slash and a question mark is url-quoted in the link", st == 200 and f"{SALA}pane%2Fodd%3Fname and answer: `Q`" in item(ow["item"])["metadata"]["next"], (st, ow))
    tp("clear", "pane/odd?name", None)
    cfg_view = _cfg.CFG["client"]
    cfg_view["session_view"] = "https://sala.example.org/view?name={name}"
    try:
        st, ov = tp("open", question="Q")
        check("[client] session_view, when set, is the pane's address", st == 200 and item(ov["item"])["metadata"]["next"] == "Oliver: open https://sala.example.org/view?name=home-sparrow-builder and answer: `Q`", (st, ov))
    finally: cfg_view["session_view"] = "https://sala.example.org/#s={name}"
    tp("clear", "home-sparrow-builder", None)

    # ---- 8. the page-debt rules: the script owes no page; the owner is never made to answer for it
    import os as _os
    old = time.time() - 8 * 3600; _os.utime(T / "brain/projects/alpha.md", (old, old))     # the page is older than any debt, so nothing settles it
    d = _pdebts._owed_load(); d.setdefault("projects/alpha", {})[_pdebts._session_id("home-sparrow-main")] = {"ts": time.time() - 4 * 3600, "item": "s5"}; _pdebts._owed_save(d)
    st, od = tp("open", question="Debt check")
    check("a keeper of record who owes a page past the grace does not stop a script's open", st == 200, (st, od))
    _pdebts._owed_save({})
    for i in range(3):
        tp("open", question=f"burst {i}"); tp("clear", "home-sparrow-builder", None); tp("open", question=f"burst again {i}")
    owed = _pdebts._owed_load()
    OWNER_ID = _pdebts._session_id("home-sparrow-main")
    check("a burst of opens and clears leaves the keeper of record owing nothing (its own board writes are not blocked)", not any(sr._same_sess(o, OWNER_ID) for os_ in owed.values() for o in os_), owed)
    check("…and no script label is made to owe a page either", not any(("sala-hook" in o or "script" in o) for os_ in owed.values() for o in os_), owed)
    tp("clear", "home-sparrow-builder", None); _pdebts._owed_save({}); _os.utime(T / "brain/projects/alpha.md", None)

    # ---- 9. a state write that is refused closes the item again
    real_update = _update_svc._update
    def failing_update(gid_, *a, **kw):
        if kw.get("step"): raise ToolError("Refused: a pretend refusal of the state")
        return real_update(gid_, *a, **kw)
    _update_svc._update = failing_update
    try:
        before = len(items()); st, of = tp("open", question="Will this half-made item be left?")
    finally: _update_svc._update = real_update
    check("a refused state write answers 400 with the refusal", st == 400 and "pretend refusal" in of.get("error", ""), (st, of))
    check("…and the item that was made for it is closed again, not left half made, so the next open files a clean one", len(items()) == before + 1 and terminal_prompt_svc._terminal_open_items("home-sparrow-builder") == []
          and _service_store._load("s" + str(int(items()[-1])))["metadata"]["outcome"] == "dropped", (items()[-3:], terminal_prompt_svc._terminal_open_items("home-sparrow-builder")))
    st, og = tp("open", question="Will this one be whole?")
    check("…the next open is a clean item in your-step", st == 200 and og["repeat"] is False and item(og["item"])["metadata"]["state"] == "your-step", (st, og))
    tp("clear", "home-sparrow-builder", None)

    # ---- 9b. a state write that fails with any error (not only a refusal) closes the item; a crash between the two writes is repaired by the next open
    def oserror_state(gid_, *a, **kw):
        if kw.get("step"): raise OSError("disk went away")
        return real_update(gid_, *a, **kw)
    _update_svc._update = oserror_state
    try:
        try: tp("open", question="OSError on the state"); raised = None
        except OSError as e: raised = e
    finally: _update_svc._update = real_update
    last = _service_store._load("s" + str(int(items()[-1])))
    check("an OSError on the state write propagates and the half-made item is closed (dropped), not left open", raised is not None and last["status"] == "completed" and last["metadata"]["outcome"] == "dropped"
          and terminal_prompt_svc._terminal_open_items("home-sparrow-builder") == [], (raised, last["status"]))
    st, og2 = tp("open", question="After the OSError")
    check("…and the next open files a clean item in your-step", st == 200 and og2["repeat"] is False and item(og2["item"])["metadata"]["state"] == "your-step", (st, og2))
    tp("clear", "home-sparrow-builder", None)
    real_state = terminal_prompt_svc._terminal_state
    def crash_state(*a, **kw): raise KeyboardInterrupt()       # not an Exception: nothing between the two writes can close the item
    terminal_prompt_svc._terminal_state = crash_state
    try:
        try: tp("open", question="Crash between the writes")
        except KeyboardInterrupt: pass
    finally: terminal_prompt_svc._terminal_state = real_state
    half = terminal_prompt_svc._terminal_open_items("home-sparrow-builder")
    hm = item(half[0])["metadata"] if half else {}
    check("fixture: a crash between the create and the state write leaves an open item with the owner as mover and no state", len(half) == 1 and "state" not in hm and hm.get("mover") == "Oliver", (half, hm))
    st, og3 = tp("open", question="Crash between the writes")
    fm = item(og3["item"])["metadata"]
    check("the next open (same question) repairs it: the same item, repeat true, now your-step with its step, nothing new filed", st == 200 and og3["repeat"] is True and og3["item"] == _gh.shown(half[0]) and fm.get("state") == "your-step"
          and fm.get("step") == "Answer home-sparrow-builder's question in its terminal" and terminal_prompt_svc._terminal_open_items("home-sparrow-builder") == half, (st, og3, fm))
    tp("clear", "home-sparrow-builder", None)

    # ---- 9c. a question with no space in it overruns the next line: a hard cut with an ellipsis, never an empty question
    for n_ in (173, 185, 200):
        st, ox = tp("open", question="x" * n_); nl = item(ox["item"])["metadata"]["next"]
        check(f"a {n_}-character question with no space (it overruns the line) is cut hard with an ellipsis and keeps its start; the line fits the limit", st == 200 and re.fullmatch(r"Oliver: open \S+ and answer: `x{20,}…`", nl) and len(nl.replace(SALA + "home-sparrow-builder", "")) <= 200, (st, nl))
        tp("clear", "home-sparrow-builder", None)

    # ---- 9d. a session name that would render as markup or notify is refused; a plain name the registry does not know yet is taken
    for bad in ("[x](https://evil.example) @example-owner", "a b", "a\tb", "x@y", "<b>x</b>", "a`b", "a(b", "a]b", "a>b", "a\u00a0b"):
        before = len(items()); st, o = tp("open", session=bad, question="Q")
        check(f"a session name {bad!r} is refused with a clear message, nothing filed", st == 400 and "without spaces or any of" in o.get("error", "") and len(items()) == before, (st, o))
    st, o = tp("clear", session="a b", question=None); check("…a clear refuses it the same way", st == 400 and "without spaces" in o.get("error", ""), (st, o))
    for plain in ("brand-new_pane.1", "dir/pane-2", "日本語-pane"):
        st, o = tp("open", session=plain, question="Q")
        check(f"an unknown but plain name {plain!r} is taken", st == 200 and o["session"] == plain and o["project"] == "projects/example-two", (st, o)); tp("clear", plain, None)

    # ---- 10. concurrency: one session, many calls, one item
    n3 = len(items()); res = []
    ths = [threading.Thread(target=lambda i=i: res.append(tp("open", question=f"racing {i}"))) for i in range(8)]
    [t.start() for t in ths]; [t.join() for t in ths]
    check("eight threads opening for one session at once file one item and all get its id", len(items()) == n3 + 1 and len({r[1]["item"] for r in res}) == 1 and all(r[0] == 200 for r in res)
          and sum(1 for r in res if not r[1]["repeat"]) == 1, [r for r in res][:3])
    ths = [threading.Thread(target=lambda: res.append(tp("clear", question=None))) for _ in range(4)]
    [t.start() for t in ths]; [t.join() for t in ths]
    check("…and four clears at once close it once, the others find none", all(r[0] == 200 for r in res[8:]) and sum(len(r[1]["cleared"]) for r in res[8:]) == 1 and terminal_prompt_svc._terminal_open_items("home-sparrow-builder") == [], res[8:])

    # ---- 11. over HTTP and through client.py
    app = server.mcp.http_app()
    with TestClient(app) as c:
        r = c.post("/client/terminal-prompt", json={"action": "open", "session": "home-sparrow-builder", "sender": "s", "question": "q"}); check("http: without a token -> 401", r.status_code == 401, r.status_code)
        r = c.post("/client/terminal-prompt", json={"action": "open", "session": "home-sparrow-builder", "sender": "http-script", "question": "Via http?"}, headers=HD)
        check("http: with a machine token -> 200 and the item", r.status_code == 200 and r.json()["repeat"] is False and r.headers["cache-control"] == "no-store", r.text)
        gid_http = r.json()["item"]
        r = c.post("/client/terminal-prompt", json={"action": "open", "session": "home-sparrow-builder", "sender": "http-script", "question": "x" * 201}, headers=HD)
        check("http: a refusal is 400 with the reason", r.status_code == 400 and "at most 200" in r.json()["error"], r.text)
        r = c.post("/client/terminal-prompt", json={"action": "clear", "session": "home-sparrow-builder", "sender": "http-script"}, headers=HD)
        check("http: clear -> 200 and the closed item", r.status_code == 200 and r.json()["cleared"] == [gid_http], r.text)
        import urllib.request, urllib.error
        class _Resp:
            def __init__(s, r): s.status = r.status_code; s._b = r.content
            def read(s): return s._b
            def __enter__(s): return s
            def __exit__(s, *a): return False
        down = {"on": False}
        def fake_urlopen(req, timeout=0):
            if down["on"]: raise urllib.error.URLError("connection refused")
            path = req.full_url.replace(client.server_url(), "")
            r = c.post(path, content=req.data, headers=dict(req.header_items())) if req.get_method() == "POST" else c.get(path, headers=dict(req.header_items()))
            if r.status_code >= 400: raise urllib.error.HTTPError(req.full_url, r.status_code, "x", {}, io.BytesIO(r.content))
            return _Resp(r)
        client.urllib.request.urlopen = fake_urlopen
        def run(*argv):
            so, se = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(so), contextlib.redirect_stderr(se): rc = client.main(["client.py", *argv])
            return rc, so.getvalue(), se.getvalue()
        before = len(items())
        rc, o, e = run("post", "terminal-prompt", "open", "--session", "home-sparrow-builder", "--question", Q, "--sender", "sala-hook")
        gid_cli = o.strip()
        check("client.py open: exactly the item id on stdout, nothing on stderr, exit 0, one item filed", rc == 0 and re.fullmatch(r"\S+\n", o) and e == "" and len(items()) == before + 1, (rc, o, e))
        check("…the item is the session's open terminal prompt", item(gid_cli)["metadata"]["terminal_prompt"] == "home-sparrow-builder" and item(gid_cli)["status"] == "open")
        rc, o2, e = run("post", "terminal-prompt", "open", "--session", S["eng"], "--question", "Same pane, new words", "--sender", "sala-hook")
        check("client.py open again (by the pane's id): the same id printed, exit 0, nothing filed, the question changed", rc == 0 and o2 == o and e == "" and len(items()) == before + 1
              and item(gid_cli)["metadata"]["next"].endswith("`Same pane, new words`"), (rc, o2, e))
        rc, o, e = run("post", "terminal-prompt", "clear", "--session", "home-sparrow-eng", "--sender", "sala-hook")
        check("client.py clear: nothing on stdout, exit 0, the item closed with its reason", rc == 0 and o == "" and e == "" and item(gid_cli)["status"] == "completed" and item(gid_cli)["metadata"]["reason"] == "the pane stopped waiting", (rc, o, e))
        rc, o, e = run("post", "terminal-prompt", "clear", "--session", "home-sparrow-builder", "--sender", "sala-hook")
        check("client.py clear with none open: exit 0, nothing on either stream (a no-op)", rc == 0 and o == "" and e == "", (rc, o, e))
        before = len(items())
        for name, argv, needle in (("no verb", [], "usage: client.py post terminal-prompt"), ("a wrong verb", ["reopen", "--session", "x", "--sender", "s"], "usage: client.py post terminal-prompt"),
                                   ("open without --question", ["open", "--session", "x", "--sender", "s"], "usage:"), ("open without --session", ["open", "--question", "q", "--sender", "s"], "usage:"),
                                   ("open without --sender", ["open", "--session", "x", "--question", "q"], "usage:"), ("clear without --session", ["clear", "--sender", "s"], "usage:"),
                                   ("clear without --sender", ["clear", "--session", "x"], "usage:"), ("clear with a --question", ["clear", "--session", "x", "--sender", "s", "--question", "q"], "usage:"),
                                   ("a flag with no value", ["open", "--session"], "needs a value"), ("a stray word", ["open", "--session", "x", "--question", "q", "--sender", "s", "stray"], "usage:"),
                                   ("a question over 200 characters", ["open", "--session", "x", "--question", "q" * 201, "--sender", "s"], "at most 200"),
                                   ("a question over several lines", ["open", "--session", "x", "--question", "a\nb", "--sender", "s"], "one line")):
            rc, o, e = run("post", "terminal-prompt", *argv)
            check(f"client.py misuse, {name}: usage or reason on stderr, nothing on stdout, exit 1", rc == 1 and o == "" and needle in e, (rc, o, e))
        check("…and none of them filed an item", len(items()) == before, (len(items()), before))
        rc, o, e = run("post", "terminal-prompt", "open", "--session", "x", "--question", "q", "--sender", "Oliver")
        check("client.py open with a sender that names the owner: the server's refusal on stderr, exit 1, nothing on stdout", rc == 1 and o == "" and "[400]" in e and "Only the board writes as" in e, (rc, o, e))
        tokfile = pathlib.Path(client.TOKEN); hold = tokfile.with_suffix(".held"); tokfile.rename(hold)
        try:
            rc, o, e = run("post", "terminal-prompt", "open", "--session", "home-sparrow-builder", "--question", "q", "--sender", "s")
            check("client.py open with no token on the machine: exit 1, the reason on stderr, nothing filed", rc == 1 and o == "" and "no token on this machine" in e and len(items()) == before, (rc, o, e))
            rc, o, e = run("post", "terminal-prompt", "clear", "--session", "home-sparrow-builder", "--sender", "s")
            check("client.py clear with no token: exit 1", rc == 1 and "no token on this machine" in e, (rc, o, e))
        finally: hold.rename(tokfile)
        down["on"] = True
        rc, o, e = run("post", "terminal-prompt", "open", "--session", "home-sparrow-builder", "--question", "q", "--sender", "s")
        check("client.py open with the server not reached: exit 1, [0] and the reason on stderr, nothing on stdout", rc == 1 and o == "" and "[0]" in e and "URLError" in e, (rc, o, e))
        rc, o, e = run("post", "terminal-prompt", "clear", "--session", "home-sparrow-builder", "--sender", "s")
        check("client.py clear with the server not reached: exit 1", rc == 1 and o == "" and "[0]" in e, (rc, o, e))
        down["on"] = False

    # ---- 12. the docs
    help_text = " ".join(client.__doc__.split())    # the help wraps its lines
    check("the client help documents both verbs, the key, the shape and the exit codes", "client.py post terminal-prompt open" in help_text and "client.py post terminal-prompt clear" in help_text
          and "terminal_prompt" in help_text and "the pane stopped waiting" in help_text and "Your move" in help_text and "200 characters" in help_text, help_text[help_text.find("post terminal-prompt") - 50:][:300])
    import _docs
    readme = _docs.page("client-contract")
    check("the docs document the post kind: both verbs, the route, the item's shape, the idempotency and the page-debt rule", "POST /client/terminal-prompt" in readme and "post terminal-prompt open" in readme
          and "post terminal-prompt clear" in readme and "metadata.terminal_prompt" in readme and "the pane stopped waiting" in readme)
    check("the 404 list of the client API names the new write", "terminal-prompt" in _rt_client._client_post(me, "nope", {})[1]["error"])
    check("the server's docstring and the client's usage line carry the shape", "terminal-prompt" in client.TERMINAL_PROMPT_USAGE and "Answer <session>'s question in its terminal" in " ".join(terminal_prompt_svc._terminal_prompt.__doc__.split()))

    # no tag is put on the server's own subjects, whatever the scope of the project: the group is the project's
    check("the server files its own items with no tag in front: the terminal-prompt, job-gap and job-alert subjects open with the pane, timer or unit name", not hasattr(terminal_prompt_svc, "_terminal_subject_prefix"))

# ======== part 3: a failed run of a scheduled job (the former job_alert suite) ========
def part_job_alert():
    def failed(unit="nightly.service", host="host-a", time_="2026-11-23T02:15:00Z", project="projects/alpha", **kw):
        b = {"unit": unit, "host": host, "time": time_, "project": project}; b.update(kw)
        return _rt_client._client_post(me, "job-failed", {k: v for k, v in b.items() if v is not None})
    def ok(unit="nightly.service", host="host-a", time_="2026-11-23T03:00:00Z", **kw):
        b = {"unit": unit, "host": host, "time": time_}; b.update(kw)
        return _rt_client._client_post(me, "job-ok", {k: v for k, v in b.items() if v is not None})
    def open_for(unit, host):
        import stackshot.service.job_alert as ja
        return ja._jobalert_open_items(f"{unit} on {host}")
    NOW = "2027-01-01T00:00:00Z"
    def pin(iso):
        """The server's clock for the future-time guard: the fixture's times are all before NOW (so a written run time is of a past year and says it). The module is reloaded in section 3, so this is called again there."""
        import stackshot.service.job_alert as ja
        t = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00")); ja._jobalert_now = lambda: t
    pin(NOW)
    n0 = len(items())

    # ---- 1. a failure opens one item
    st, out = failed()
    check("job-failed: 200 with the item id as shown, the unit, the host, the project, the builder as mover, the -main agent as keeper, opened, one failure, no fallback",
          st == 200 and out["unit"] == "nightly.service" and out["host"] == "host-a" and out["project"] == "projects/alpha" and out["mover"] == "home-sparrow-builder" and out["owner"] == "home-sparrow-main"
          and out["action"] == "opened" and out["failures"] == 1 and out["fallback"] is False and out["item"] == _gh.shown(_model_ids._norm_id(out["item"])), (st, out))
    gid1 = out["item"]; it = item(gid1); m = it["metadata"]
    check("the item is open under the project, marked with the unit and the host", it["status"] == "open" and m["project"] == "projects/alpha" and m["job_alert"] == "nightly.service on host-a", (it["status"], m))
    check("…the subject names the unit and the machine", it["subject"] == "Fix nightly.service on host-a", it["subject"])
    check("…p2; the project's builder (not the notes keeper) is the mover and is in needs", m.get("priority") == "p2" and sr._session_label(m.get("mover")) == "home-sparrow-builder"
          and [sr._session_label(x) for x in m.get("needs") or []] == ["home-sparrow-builder"], m)
    check("…the keeper of record is the -main agent; the creator reads `job alert (a script on <machine>)`", sr._session_label(m["owner"]) == "home-sparrow-main" and it["filed_by"] == f"job alert (a script on {me})", (m["owner"], it.get("filed_by")))
    check("…next names the builder and what to do", m.get("next", "") == "home-sparrow-builder: read the journal of nightly.service on host-a, fix the cause; the next successful run closes this item", m.get("next"))
    d = it["description"].splitlines()
    check("…the description is bullets: the job and machine, the count, the run's time in the instance's zone, what to do, who opened it",
          len(d) == 5 and all(x.startswith("- ") for x in d) and d[0] == "- nightly.service on host-a ended a scheduled run in failure" and d[1] == "- Failed runs since this item opened: 1"
          and d[2].startswith("- Failed run at Mon Nov 23rd 2026 06:15 ") and "journal of nightly.service on host-a" in d[3] and "next successful run closes this item" in d[3] and d[4] == f"- Opened by job alert (a script on {me})", it["description"])
    check("…the state a later call needs is on the item: the times, the count, the unit and the host", m["job_alert_runs"] == ["2026-11-23T02:15:00Z"] and m["job_alert_count"] == 1 and m["job_alert_unit"] == "nightly.service" and m["job_alert_host"] == "host-a", m)
    settle()
    check("…the builder is told once and no one else is", len(pushed) == 1 and pushed[0][0] in ("home-sparrow-builder", S["build"]) and gid1 in pushed[0][1] and "now needs you" in pushed[0][1], pushed)
    check("…one item filed, and the row owes no page", len(items()) == n0 + 1 and _pdebts._owed_load() == {}, (len(items()) - n0, _pdebts._owed_load()))
    check("…the item is alive with the builder as the mover", M.derive(it).state == M.ALIVE and M.derive(it).mover == "home-sparrow-builder", (M.derive(it).state, M.derive(it).mover))

    # ---- 2. a repeat failure adds a line; the same time again counts once; another unit or host is another item
    n1 = len(items()); pushed.clear()
    st, o2 = failed(time_="2026-11-23T14:15:00Z")
    check("a second failure: 200, the same item, added, two failures, nothing filed", st == 200 and o2["item"] == gid1 and o2["action"] == "added" and o2["failures"] == 2 and len(items()) == n1, (st, o2))
    d = item(gid1)["description"].splitlines()
    check("…the description has the count 2 and both runs' times, the earlier first", d[1] == "- Failed runs since this item opened: 2" and d[2].startswith("- Failed run at Mon Nov 23rd 2026 06:15 ") and d[3].startswith("- Failed run at Mon Nov 23rd 2026 18:15 "), d)
    check("…the item is still open under the same mover, with the metadata kept", item(gid1)["status"] == "open" and item(gid1)["metadata"]["job_alert_count"] == 2 and item(gid1)["metadata"]["job_alert_runs"] == ["2026-11-23T02:15:00Z", "2026-11-23T14:15:00Z"]
          and sr._session_label(item(gid1)["metadata"]["mover"]) == "home-sparrow-builder", item(gid1)["metadata"])
    settle()
    check("…and the builder is not told again", pushed == [], pushed)
    st, o3 = failed(time_="2026-11-23T14:15:00Z")
    check("the same run's time again (a call sent twice): seen, still two failures, nothing changed", st == 200 and o3["item"] == gid1 and o3["action"] == "seen" and o3["failures"] == 2 and item(gid1)["metadata"]["job_alert_count"] == 2 and len(items()) == n1, (st, o3))
    st, o4 = failed(host="host-b")
    check("the same unit on another host is another item", st == 200 and o4["item"] != gid1 and o4["action"] == "opened" and item(o4["item"])["metadata"]["job_alert"] == "nightly.service on host-b", (st, o4))
    st, o5 = failed(unit="weekly.timer")
    check("another unit on the same host is another item", st == 200 and o5["item"] not in (gid1, o4["item"]) and o5["action"] == "opened" and item(o5["item"])["subject"] == "Fix weekly.timer on host-a", (st, o5))
    check("…three items are open now, one per (unit, host)", len(items()) == n1 + 2 and {open_for("nightly.service", "host-a")[0], open_for("nightly.service", "host-b")[0], open_for("weekly.timer", "host-a")[0]} == {_model_ids._norm_id(x) for x in (gid1, o4["item"], o5["item"])})
    failed(host="host-b", time_="2026-11-23T05:00:00Z"); failed(unit="weekly.timer", time_="2026-11-23T05:00:00Z")

    # ---- 3. restart safety: the key is read from the item, nothing is kept in memory
    import stackshot.service.job_alert as _ja_mod
    _ja_mod = importlib.reload(_ja_mod); _rt_client._job_alert = _ja_mod; pin(NOW)
    st, o6 = failed(time_="2026-11-24T01:00:00Z")
    check("after the module is loaded afresh (a restart): a failure finds the open item by its mark and adds to it", st == 200 and o6["item"] == gid1 and o6["action"] == "added" and o6["failures"] == 3, (st, o6))
    raw = json.loads(_service_store._path(_model_ids._norm_id(gid1)).read_text(encoding="utf-8"))
    check("…the mark, the times and the count are in the item's own file", raw["metadata"]["job_alert"] == "nightly.service on host-a" and raw["metadata"]["job_alert_count"] == 3 and len(raw["metadata"]["job_alert_runs"]) == 3, raw["metadata"])
    st, o7 = ok(time_="2026-11-24T02:00:00Z", host="host-b")
    check("…and so does a job-ok, which closes only its own (unit, host)", st == 200 and o7["closed"] and item(gid1)["status"] == "open", (st, o7))
    b_item = o4["item"]; check("…(that was the host-b item)", o7["closed"] == [b_item] and item(b_item)["status"] == "completed", o7)

    # ---- 4. job-ok closes; a second job-ok and one with no item are ignored; a failure after the close is a new item
    n2 = len(items())
    st, c1 = ok(time_="2026-11-24T03:00:00Z")
    it = item(gid1)
    check("job-ok: 200 and the item's id closed", st == 200 and c1["closed"] == [gid1] and c1["unit"] == "nightly.service" and c1["host"] == "host-a", (st, c1))
    check("…completed, outcome done, the run's time in the reason (in the instance's zone), the end state in the description", it["status"] == "completed" and it["metadata"]["outcome"] == "done"
          and it["metadata"]["reason"] == "the next run of nightly.service on host-a succeeded at Tue Nov 24th 2026 07:00 +04" and "ran successfully at Tue Nov 24th 2026 07:00 +04" in it["metadata"]["outcome_text"]
          and it["description"].splitlines()[0] == "- nightly.service on host-a ended a scheduled run in failure", it["metadata"])
    st, c2 = ok(time_="2026-11-24T03:00:00Z")
    check("a second job-ok for the same run: 200, nothing closed, nothing changed", st == 200 and c2["closed"] == [] and "no open item" in c2["note"] and item(gid1)["status"] == "completed" and len(items()) == n2, (st, c2))
    st, c3 = ok(unit="never-failed.service", host="host-z")
    check("a job-ok for a unit and host that never failed: 200, nothing closed, no item made", st == 200 and c3["closed"] == [] and len(items()) == n2, (st, c3))
    st, n_ = failed(time_="2026-11-25T02:15:00Z")
    check("a failure after the close opens a NEW item with a count of one", st == 200 and n_["item"] != gid1 and n_["action"] == "opened" and n_["failures"] == 1 and item(n_["item"])["status"] == "open"
          and item(n_["item"])["metadata"]["job_alert_runs"] == ["2026-11-25T02:15:00Z"], (st, n_))
    gid2 = n_["item"]
    st, c4 = ok(time_="2026-11-25T01:00:00Z")
    check("a job-ok older than the item's latest failed run (sent late) leaves it open and says why", st == 200 and c4["closed"] == [] and "older" in c4["note"] and item(gid2)["status"] == "open", (st, c4))
    st, c5 = ok(time_="2026-11-25T02:15:00Z")
    check("a job-ok at the very time of the failed run closes it", st == 200 and c5["closed"] == [gid2], (st, c5))
    st, n2_ = failed(time_="2026-11-26T02:15:00Z"); st, c6 = ok(time_="2026-11-26T03:15:00Z")
    check("fail, ok, fail, ok: two more items, each closed by its own success", st == 200 and c6["closed"] == [n2_["item"]] and n2_["item"] not in (gid1, gid2), (n2_, c6))

    # ---- 5. where an item goes: no project, an unknown one, a project with no builder, no general project
    n3 = len(items())
    _cfg.CFG.pop("job_alert", None)
    st, e = failed(unit="unset.service", project="-")
    check("with no [job_alert] fallback_project set, a job with no project is a 409 that names the setting, nothing filed", st == 409 and "no general project is set" in e["error"] and "[job_alert] fallback_project" in e["error"] and len(items()) == n3, (st, e))
    st, e = failed(unit="unset.service", project="projects/ghost")
    check("…and so is a project the server has no page for", st == 409 and len(items()) == n3, (st, e))
    st, o = failed(unit="unset.service", project="projects/alpha")
    check("…while a job with a project of its own is filed as before", st == 200 and o["fallback"] is False and ok(unit="unset.service")[1]["closed"] == [o["item"]], (st, o))
    _cfg.CFG["job_alert"] = {"fallback_project": "ops/general"}      # the instance names its general project
    n3 = len(items())
    st, g1 = failed(unit="orphan.service", project="-")
    mg = item(g1["item"])["metadata"] if st == 200 else {}
    check("a job with no project (`-`): the general project's builder moves it, the item says it names none, fallback true", st == 200 and g1["project"] == "ops/general" and g1["mover"] == "heron-engineer" and g1["owner"] == "heron-main"
          and g1["fallback"] is True and "the job names no project" in item(g1["item"])["description"] and mg.get("job_alert_fallback") is True, (st, g1, item(g1["item"])["description"] if st == 200 else ""))
    st, g2 = failed(unit="lost.service", project="projects/ghost")
    check("a project this server has no page for: the same, and the item names the project it was told", st == 200 and g2["project"] == "ops/general" and g2["mover"] == "heron-engineer" and g2["fallback"] is True
          and "projects/ghost is no project page here" in item(g2["item"])["description"], (st, g2))
    st, g3 = failed(unit="nb.service", project="projects/nobuild")
    check("a project with no builder: its -main agent moves it and the item says so, fallback true", st == 200 and g3["mover"] == "home-nobuild-main" and g3["owner"] == "home-nobuild-main" and g3["fallback"] is True
          and "lists no builder, so this is with home-nobuild-main" in item(g3["item"])["description"] and item(g3["item"])["metadata"].get("needs") in (None, [], ""), (st, g3, item(g3["item"])["metadata"].get("needs")))
    st, g4 = failed(unit="bare.service", project="alpha")
    check("a bare slug of a project page is taken as its page", st == 200 and g4["project"] == "projects/alpha" and g4["mover"] == "home-sparrow-builder" and g4["fallback"] is False, (st, g4))
    _cfg.CFG["job_alert"] = {"fallback_project": "ops/nowhere"}
    st, e = failed(unit="nowhere.service", project="-")
    check("with the general project missing too: 409 that names the setting, nothing filed", st == 409 and "[job_alert] fallback_project" in e["error"] and len(items()) == n3 + 4 and open_for("nowhere.service", "host-a") == [], (st, e))
    _cfg.CFG["job_alert"] = {"fallback_project": "projects/nobuild"}
    st, g5 = failed(unit="elsewhere.service", project="-")
    check("[job_alert] fallback_project names another general project: it is used (its -main agent here: no builder)", st == 200 and g5["project"] == "projects/nobuild" and g5["mover"] == "home-nobuild-main", (st, g5))
    _cfg.CFG["job_alert"] = {"fallback_project": "ops/general"}

    # ---- 6. the newest 20 times are kept, the count goes on
    for i in range(23):
        st, last = failed(unit="chatty.service", time_=f"2026-12-01T{i:02d}:00:00Z")
    it = item(last["item"])
    check("23 failures of one job: one item, a count of 23, the newest 20 times kept, the oldest first", len(items()) == n3 + 6 and last["failures"] == 23 and it["metadata"]["job_alert_count"] == 23 and len(it["metadata"]["job_alert_runs"]) == 20
          and it["metadata"]["job_alert_runs"][0] == "2026-12-01T03:00:00Z" and it["metadata"]["job_alert_runs"][-1] == "2026-12-01T22:00:00Z", (last, it["metadata"]))
    d = it["description"].splitlines()
    check("…the description keeps its limit: the count, only the newest three runs, no more lines than the board takes", d[1] == "- Failed runs since this item opened: 23" and sum(1 for x in d if x.startswith("- Failed run at")) == 3 and len(d) <= _fg._description_limits()[0], d)
    st, old = failed(unit="chatty.service", time_="2026-12-01T00:00:00Z")
    check("a time older than every one kept is a time the item has had: seen, not counted again", st == 200 and old["action"] == "seen" and old["failures"] == 23, (st, old))
    st, late = failed(unit="chatty.service", time_="2026-11-30T00:00:00Z")
    check("…the same for a run a day earlier", st == 200 and late["action"] == "seen" and late["failures"] == 23, (st, late))

    # ---- 7. a subject that is too long is cut, never refused
    LONG = "very-long-unit-name-" * 5 + "x.service"          # 105 characters: the subject would be over 80
    st, o = failed(unit=LONG)
    sub = item(o["item"])["subject"] if st == 200 else ""
    check("a unit name too long for the subject limit still opens: a subject of at most 80 characters that keeps the cut name and the machine", st == 200 and len(sub) <= 80 and sub.startswith("Fix very-long")
          and sub.endswith(" … on host-a"), (st, o, sub))
    check("…the mark keeps the whole name, and a job-ok by the whole name closes it", item(o["item"])["metadata"]["job_alert"] == f"{LONG} on host-a" and ok(unit=LONG)[1]["closed"] == [o["item"]])
    st, o = failed(unit="u" * 120, host="h" * 63)
    sub = item(o["item"])["subject"] if st == 200 else ""
    check("the longest unit and host the call takes: still a subject within the limit", st == 200 and len(sub) <= 80, (st, o, sub)); ok(unit="u" * 120, host="h" * 63)
    st, o = failed(unit="words.service")
    check("the job's own words are not judged for alarming ones (the text of every item has `failure` in it)", st == 200, (st, o))

    # ---- 8. bad input: nothing filed
    n5 = len(items())
    for name, kw in (("an empty unit", dict(unit="")), ("a unit with a space", dict(unit="a b.service")), ("a unit with markup", dict(unit="a<b>.service")), ("a unit with a mention", dict(unit="a@b c")),
                     ("a unit starting with a dot", dict(unit=".hidden")), ("a unit of 121 characters", dict(unit="t" * 121)), ("an empty host", dict(host="")), ("a host with a space", dict(host="host a")),
                     ("a host of 64 characters", dict(host="h" * 64)), ("a host with a slash", dict(host="a/b")), ("a time with no Z", dict(time_="2026-11-23T02:15:00")), ("a time with an offset", dict(time_="2026-11-23T02:15:00+09:00")),
                     ("a date only", dict(time_="2026-11-23")), ("a time that is no time", dict(time_="2026-13-45T99:99:99Z")), ("a time with words", dict(time_="2026-11-23T02:15:00Z please")),
                     ("an empty project", dict(project="")), ("a project with a space", dict(project="projects/a b")), ("a project with four parts", dict(project="a/b/c/d")), ("a project with a space before the slash", dict(project="projects /alpha")), ("a project with a space inside its first part", dict(project="pro jects/alpha")), ("a project with markup", dict(project="projects/<x>")),
                     ("an extra key", dict(sender="x")), ("a missing project", dict(project=None)), ("a number for the unit", dict(unit=7)), ("a list for the host", dict(host=["a"]))):
        st, e = failed(**kw)
        check(f"job-failed with {name}: 400, nothing filed", st == 400 and len(items()) == n5, (st, e))
    for name, kw in (("an empty unit", dict(unit="")), ("a bad host", dict(host="host a")), ("a bad time", dict(time_="yesterday")), ("an extra key", dict(project="-")), ("a number for the time", dict(time_=5))):
        st, e = ok(**kw)
        check(f"job-ok with {name}: 400", st == 400, (st, e))
    st, e = _rt_client._client_post(me, "job-ok", {"unit": "x.service", "host": "host-a"})
    check("job-ok with no time: 400 that says which key", st == 400 and "time is required" in e["error"], (st, e))
    for good in ("job@1.service", "user.slice:job.timer", "a_b.c-d.timer"):
        st, o = failed(unit=good)
        check(f"a plain unit name {good!r} is taken and kept whole in the mark", st == 200 and item(o["item"])["metadata"]["job_alert"] == f"{good} on host-a", (st, o)); ok(unit=good)
    st, o = failed(unit="frac.service", time_="2026-11-23T02:15:00.123Z")
    check("a time with fractional seconds is taken", st == 200, (st, o)); ok(unit="frac.service", time_="2026-11-23T02:16:00Z")

    # ---- 9. concurrency: one job, many calls, one item
    n6 = len(items()); res = []
    ths = [threading.Thread(target=lambda i=i: res.append(failed(unit="race.service", time_=f"2026-12-02T00:0{i}:00Z"))) for i in range(8)]
    [t.start() for t in ths]; [t.join() for t in ths]
    check("eight threads failing one job at once file one item, all get its id, and every run is counted", len(items()) == n6 + 1 and len({r[1]["item"] for r in res}) == 1 and all(r[0] == 200 for r in res)
          and sum(1 for r in res if r[1]["action"] == "opened") == 1 and item(res[0][1]["item"])["metadata"]["job_alert_count"] == 8, res[:3])
    ths = [threading.Thread(target=lambda: res.append(ok(unit="race.service", time_="2026-12-03T00:00:00Z"))) for _ in range(4)]
    [t.start() for t in ths]; [t.join() for t in ths]
    check("…and four job-ok at once close it once, the others find none", all(r[0] == 200 for r in res[8:]) and sum(len(r[1]["closed"]) for r in res[8:]) == 1 and open_for("race.service", "host-a") == [], res[8:])
    settle()

    # ---- 9b. a time that cannot be right: refused on both routes, and it never ruins an open item
    n7 = len(items())
    st, e = failed(unit="far.service", time_="9999-12-31T23:59:59Z")
    check("job-failed with a time in year 9999: 400 with a plain reason (no 500), nothing filed", st == 400 and "later than now" in e["error"] and len(items()) == n7, (st, e))
    st, e = ok(unit="far.service", time_="9999-12-31T23:59:59Z")
    check("job-ok with a time in year 9999: the same 400", st == 400 and "later than now" in e["error"], (st, e))
    st, e = failed(unit="far.service", time_="2099-01-01T00:00:00Z")
    check("job-failed with a time far ahead of the clock: 400, nothing filed", st == 400 and "later than now" in e["error"] and len(items()) == n7, (st, e))
    st, e = failed(unit="far.service", time_="2027-01-01T01:00:00Z")
    check("a time an hour ahead of the clock: the 400 says plainly that the machine's clock is ahead of the server's by 60 minutes, nothing filed", st == 400 and "the machine's clock is ahead of the server's by 60 minutes" in e["error"] and len(items()) == n7, (st, e))
    st, e = ok(unit="far.service", time_="2027-01-01T00:06:30Z")
    check("…the same text on job-ok, the whole minutes only (6 minutes 30 seconds ahead is 6)", st == 400 and "the machine's clock is ahead of the server's by 6 minutes" in e["error"], (st, e))
    st, f0 = failed(unit="future.service", time_="2026-12-08T02:15:00Z")
    st, e = failed(unit="future.service", time_="2099-01-01T00:00:00Z")
    check("a far-future failure sent for an open item is refused and adds nothing", st == 400 and item(f0["item"])["metadata"]["job_alert_count"] == 1 and item(f0["item"])["metadata"]["job_alert_runs"] == ["2026-12-08T02:15:00Z"], (st, e))
    st, c = ok(unit="future.service", time_="2026-12-08T03:00:00Z")
    check("…so the next ordinary job-ok still closes the item", st == 200 and c["closed"] == [f0["item"]], (st, c))
    st, a = failed(unit="edge.service", time_="2027-01-01T00:05:00Z")
    check("a time exactly 5 minutes past the clock is taken (the machines' clocks differ a little)", st == 200 and a["action"] == "opened", (st, a))
    st, e = failed(unit="edge2.service", time_="2027-01-01T00:05:01Z")
    check("…one second more is refused", st == 400 and "later than now" in e["error"], (st, e)); ok(unit="edge.service", time_="2027-01-01T00:05:00Z")
    pin("9999-12-31T23:00:00Z")
    st, e = failed(unit="wide.service", time_="9999-12-31T22:00:00Z")
    check("a time the board cannot show in the instance's zone (past the last year there): 400, never a 500", st == 400 and "can show" in e["error"] and len(items()) == n7 + 2, (st, e))
    st, e = ok(unit="wide.service", time_="9999-12-31T22:00:00Z")
    check("…and the same on job-ok", st == 400 and "can show" in e["error"], (st, e)); pin(NOW)

    # ---- 9c. a failure that comes late, after the success that closed its item, is that item's and opens nothing
    n8 = len(items())
    st, l1 = failed(unit="late.service", time_="2026-12-10T02:00:00Z"); ok(unit="late.service", time_="2026-12-10T03:00:00Z")
    check("(setup) fail 02:00, ok 03:00: the item is closed and keeps the time of the success", item(l1["item"])["status"] == "completed" and item(l1["item"])["metadata"]["closed_by_ok_at"] == "2026-12-10T03:00:00Z", item(l1["item"])["metadata"])
    st, l2 = failed(unit="late.service", time_="2026-12-10T02:30:00Z")
    check("a failure at 02:30 sent after that ok (a retry, a call out of order): 200, seen, that closed item's id, nothing filed, nothing reopened", st == 200 and l2["action"] == "seen" and l2["item"] == l1["item"]
          and item(l1["item"])["status"] == "completed" and len(items()) == n8 + 1 and open_for("late.service", "host-a") == [], (st, l2, len(items()) - n8))
    st, l3 = failed(unit="late.service", time_="2026-12-10T03:00:00Z")
    check("a failure at the very time of the success is seen too", st == 200 and l3["action"] == "seen" and len(items()) == n8 + 1, (st, l3))
    st, l4 = failed(unit="late.service", time_="2026-12-10T03:00:01Z")
    check("a failure after the success opens a NEW item, as before", st == 200 and l4["action"] == "opened" and l4["item"] != l1["item"] and len(items()) == n8 + 2, (st, l4))
    ok(unit="late.service", time_="2026-12-10T05:00:00Z")
    st, l5 = failed(unit="late.service", time_="2026-12-10T04:00:00Z")
    check("with two closed items, the latest success counts: a failure at 04:00 (after the first ok, before the second) is seen, and the item is the second", st == 200 and l5["action"] == "seen" and l5["item"] == l4["item"] and len(items()) == n8 + 2, (st, l5))
    st, l6 = failed(unit="late.service", time_="2026-12-10T05:00:01Z")
    check("…and one after the second opens a third", st == 200 and l6["action"] == "opened" and len(items()) == n8 + 3, (st, l6))
    st, h0 = ok(unit="late.service", time_="2026-12-10T04:30:00Z")
    check("a job-ok held back as older than the failed run does not mark the item as closed by it", st == 200 and h0["closed"] == [] and "closed_by_ok_at" not in item(l6["item"])["metadata"], (st, h0, item(l6["item"])["metadata"]))
    ok(unit="late.service", time_="2026-12-10T06:00:00Z")
    st, g0 = failed(unit="late.service", host="host-b", time_="2026-12-10T01:00:00Z")
    check("another host's failure is not held by this host's successes", st == 200 and g0["action"] == "opened", (st, g0)); ok(unit="late.service", host="host-b", time_="2026-12-10T02:00:00Z")

    # ---- 9d. one instant, one spelling; the kept times stay in order
    st, k1 = failed(unit="canon.service", time_="2026-12-09T02:00:00Z")
    st, k2 = failed(unit="canon.service", time_="2026-12-09T02:00:00.000Z")
    check("the same instant spelled with .000: seen, still one failure", st == 200 and k2["action"] == "seen" and k2["failures"] == 1 and item(k1["item"])["metadata"]["job_alert_runs"] == ["2026-12-09T02:00:00Z"], (st, k2, item(k1["item"])["metadata"]))
    st, k3 = failed(unit="canon.service", time_="2026-12-09T02:00:00.500Z"); st, k4 = failed(unit="canon.service", time_="2026-12-09T02:00:00.500000Z")
    check("a fraction is kept in one form (.5 and .500000 are one run, a second one beside the whole second)", k3["action"] == "added" and k4["action"] == "seen" and k4["failures"] == 2
          and item(k1["item"])["metadata"]["job_alert_runs"] == ["2026-12-09T02:00:00Z", "2026-12-09T02:00:00.500000Z"], (k3, k4, item(k1["item"])["metadata"]))
    st, k5 = ok(unit="canon.service", time_="2026-12-09T03:00:00.000Z")
    check("a job-ok with .000 closes it, and the success is kept in the one form", st == 200 and k5["closed"] == [k1["item"]] and item(k1["item"])["metadata"]["closed_by_ok_at"] == "2026-12-09T03:00:00Z", (st, k5))
    st, k6 = failed(unit="canon.service", time_="2026-12-09T03:00:00.000Z")
    check("…and a failure spelled 03:00:00.000Z is the same instant as that success: seen", st == 200 and k6["action"] == "seen", (st, k6))
    st, o1 = failed(unit="sort.service", time_="2026-12-11T10:00:00Z"); st, o2_ = failed(unit="sort.service", time_="2026-12-11T08:00:00Z")
    check("an older failure sent after a newer one is added and the kept times stay in time order", o2_["action"] == "added" and item(o1["item"])["metadata"]["job_alert_runs"] == ["2026-12-11T08:00:00Z", "2026-12-11T10:00:00Z"], (o2_, item(o1["item"])["metadata"]))
    d = item(o1["item"])["description"].splitlines()
    check("…and the description lists them in that order", d[2].startswith("- Failed run at Fri Dec 11th 2026 12:00 ") and d[3].startswith("- Failed run at Fri Dec 11th 2026 14:00 "), d)
    ok(unit="sort.service", time_="2026-12-11T11:00:00Z")

    # ---- 9d2. an item written with the old spelling of a time: the instants are compared, never the strings
    st, w1 = failed(unit="spell.service", time_="2026-12-12T02:00:00Z")
    raw_ = item(w1["item"]); raw_["metadata"]["job_alert_runs"] = ["2026-12-12T02:00:00.000Z"]
    from stackshot.service import writes as _wr
    with _wr.ITEM_LOCK: _wr.save(_model_ids._norm_id(w1["item"]), raw_, note="test: the old spelling of the time")
    check("(setup) the open item holds its failed run's time in the old spelling `:00.000Z`", item(w1["item"])["metadata"]["job_alert_runs"] == ["2026-12-12T02:00:00.000Z"], item(w1["item"])["metadata"])
    st, w2 = failed(unit="spell.service", time_="2026-12-12T02:00:00Z")
    check("the same instant sent as `:00Z` is seen on that open item: one failure, the stored time untouched, nothing filed", st == 200 and w2["action"] == "seen" and w2["item"] == w1["item"] and w2["failures"] == 1
          and item(w1["item"])["metadata"]["job_alert_runs"] == ["2026-12-12T02:00:00.000Z"] and item(w1["item"])["metadata"]["job_alert_count"] == 1, (st, w2, item(w1["item"])["metadata"]))
    ok(unit="spell.service", time_="2026-12-12T03:00:00Z")
    raw_ = item(w1["item"]); raw_["metadata"]["closed_by_ok_at"] = "2026-12-12T03:00:00.000Z"
    with _wr.ITEM_LOCK: _wr.save(_model_ids._norm_id(w1["item"]), raw_, note="test: the old spelling of the time")
    n_sp = len(items())
    st, w3 = failed(unit="spell.service", time_="2026-12-12T03:00:00Z")
    check("…and so is a failure at the instant of a success stored as `:00.000Z` on the closed item: seen, nothing filed", st == 200 and w3["action"] == "seen" and w3["item"] == w1["item"] and len(items()) == n_sp, (st, w3))

    # ---- 9e. a project key that names several pages is refused, never the first one
    n9 = len(items())
    st, e = failed(unit="twin.service", project="twin")
    check("a bare slug that names two pages: 409 that names both and asks for the full key, nothing filed", st == 409 and "projects/twin" in e["error"] and "ops/twin" in e["error"] and "full key" in e["error"] and len(items()) == n9 and open_for("twin.service", "host-a") == [], (st, e))
    st, e = failed(unit="twin.service", project="projects/twin")
    check("…while the full key of one of them files under it", st == 200 and e["project"] == "projects/twin" and e["owner"] == "home-twin-main" and e["mover"] == "home-twin-main", (st, e)); ok(unit="twin.service")

    # ---- 9f. a `scope/project` label: the instance's map, then the key or slug, then the project's name with the `/` made `-`, then the general project
    n10 = len(items())
    st, l1 = failed(unit="lab1.service", project="acme/widgets")
    check("a label `acme/widgets`: the one top-level page whose display-name is `acme-widgets` (its sub-page with the same name line is no second page), its builder moves it, not a fallback",
          st == 200 and l1["project"] == "projects/acme-widgets" and l1["mover"] == "acme-widgets-builder" and l1["owner"] == "acme-widgets-main" and l1["fallback"] is False
          and "no project page here" not in item(l1["item"])["description"], (st, l1)); ok(unit="lab1.service")
    check("…and the item's note says it was found by the project's name", "acme/widgets is the project name of projects/acme-widgets" in item(l1["item"])["description"], item(l1["item"])["description"])
    st, l2 = failed(unit="lab2.service", project="Acme/Widgets")
    check("…the name is compared without regard to case", st == 200 and l2["project"] == "projects/acme-widgets" and l2["fallback"] is False, (st, l2)); ok(unit="lab2.service")
    st, l3 = failed(unit="lab3.service", project="acme/gadgets")
    check("a label no page's name matches is the general project's, and the item says so", st == 200 and l3["project"] == "ops/general" and l3["fallback"] is True and "acme/gadgets is no project page here" in item(l3["item"])["description"], (st, l3)); ok(unit="lab3.service")
    n_l = len(items())
    st, e = failed(unit="lab4.service", project="acme/dupe")
    check("a label that two top-level pages' names match: 409 that names both pages, nothing filed", st == 409 and "projects/dupe-a" in e["error"] and "projects/dupe-b" in e["error"] and "full key" in e["error"] and len(items()) == n_l, (st, e))
    st, l4a = failed(unit="lab4a.service", project="acme/bolts")
    check("the name match counts active project pages only: `acme/bolts` is the active page, a completed page with the same name line is no second match (no 409)", st == 200 and l4a["project"] == "projects/acme-bolts" and "no project page here" not in item(l4a["item"])["description"], (st, l4a)); ok(unit="lab4a.service")
    n_f = len(items())
    for lab_, unit_, status_ in (("acme/gone", "lab4b.service", "merged"), ("acme/shelved", "lab4c.service", "archived"), ("acme/finished", "lab4d.service", "done")):
        st, l4b = failed(unit=unit_, project=lab_)
        check(f"a label whose only page is `status: {status_}` is no match: the general project's, the item says so", st == 200 and l4b["project"] == "ops/general" and l4b["fallback"] is True and f"{lab_} is no project page here" in item(l4b["item"])["description"], (st, l4b)); ok(unit=unit_)
    st, l4e = failed(unit="lab4e.service", project="acme/memo")
    check("a page of `type: note` whose name line is the label is ignored, finished or not: the general project's", st == 200 and l4e["project"] == "ops/general" and l4e["fallback"] is True, (st, l4e)); ok(unit="lab4e.service")
    n_g = len(items())
    st, e = failed(unit="lab4f.service", project="acme/twin")
    check("two active pages of one name still give the 409, naming the two active pages (not the finished one) and saying the map pins the label", st == 409 and "projects/acme-twin-a" in e["error"] and "projects/acme-twin-b" in e["error"] and "acme-twin-old" not in e["error"] and "[job_alert.projects]" in e["error"] and len(items()) == n_g, (st, e))
    st, l4 = failed(unit="lab5.service", project="projects/alpha")
    check("a full page key still wins as before", st == 200 and l4["project"] == "projects/alpha", (st, l4)); ok(unit="lab5.service")
    st, l5 = failed(unit="lab6.service", project="home-sparrow")
    check("a text with no `/` is a key or slug only, never read as a project name (`home-sparrow` is the name of projects/alpha, and no page's key): the general project's", st == 200 and l5["project"] == "ops/general" and l5["fallback"] is True, (st, l5)); ok(unit="lab6.service")
    _cfg.CFG["job_alert"] = {"fallback_project": "ops/general", "projects": {"shop/cart": "projects/alpha", "acme/widgets": "projects/nobuild", "alpha": "projects/nobuild", "shop/ghost": "projects/ghost", "acme/dupe": "projects/twin"}}
    st, m1 = failed(unit="lab7.service", project="shop/cart")
    check("[job_alert.projects] maps a label no page's name matches to its page key, and it is not a fallback", st == 200 and m1["project"] == "projects/alpha" and m1["mover"] == "home-sparrow-builder" and m1["fallback"] is False, (st, m1)); ok(unit="lab7.service")
    check("…and the item's note says the map did it", "shop/cart is mapped to projects/alpha by [job_alert.projects]" in item(m1["item"])["description"], item(m1["item"])["description"])
    st, m2 = failed(unit="lab8.service", project="acme/widgets")
    check("the map is consulted before the project's name: `acme/widgets` goes where the map says", st == 200 and m2["project"] == "projects/nobuild", (st, m2)); ok(unit="lab8.service")
    st, m3 = failed(unit="lab9.service", project="alpha")
    check("…and before the page key or slug: `alpha` goes where the map says, not to projects/alpha", st == 200 and m3["project"] == "projects/nobuild", (st, m3)); ok(unit="lab9.service")
    st, m4 = failed(unit="lab10.service", project="shop/ghost")
    check("a mapped key that names no page falls through (here to the general project, the label being no page's name)", st == 200 and m4["project"] == "ops/general" and m4["fallback"] is True, (st, m4)); ok(unit="lab10.service")
    st, m5 = failed(unit="lab11.service", project="acme/dupe")
    check("a label that two pages' names match is no longer ambiguous once the map names its page", st == 200 and m5["project"] == "projects/twin", (st, m5)); ok(unit="lab11.service")
    _cfg.CFG["job_alert"] = {"fallback_project": "ops/general", "projects": "not a table"}
    st, m6 = failed(unit="lab12.service", project="acme/widgets")
    check("a map that is no table is ignored (the label goes by its name)", st == 200 and m6["project"] == "projects/acme-widgets", (st, m6)); ok(unit="lab12.service")
    _cfg.CFG["job_alert"] = {"fallback_project": "ops/general"}
    st, m7 = failed(unit="lab13.service", project="shop/cart")
    check("with no map set the same label is the general project's", st == 200 and m7["project"] == "ops/general" and m7["fallback"] is True, (st, m7)); ok(unit="lab13.service")
    _cfg.CFG.pop("job_alert", None)
    st, e = failed(unit="lab14.service", project="acme/gadgets")
    check("a label that matches nothing with no general project set: the 409 as before", st == 409 and "no general project is set" in e["error"], (st, e))
    _cfg.CFG["job_alert"] = {"fallback_project": "ops/general"}

    # ---- 10. over HTTP and through client.py
    app = server.mcp.http_app()
    with TestClient(app) as c:
        r = c.post("/client/job-failed", json={"unit": "x.service", "host": "host-a", "time": "2026-12-05T00:00:00Z", "project": "projects/alpha"}); check("http: job-failed without a token -> 401", r.status_code == 401, r.status_code)
        r = c.post("/client/job-ok", json={"unit": "x.service", "host": "host-a", "time": "2026-12-05T00:00:00Z"}); check("http: job-ok without a token -> 401", r.status_code == 401, r.status_code)
        r = c.post("/client/job-failed", json={"unit": "http.service", "host": "host-a", "time": "2026-12-05T00:00:00Z", "project": "projects/alpha"}, headers=HD)
        check("http: job-failed with a machine token -> 200 and the item", r.status_code == 200 and r.json()["action"] == "opened" and r.headers["cache-control"] == "no-store", r.text)
        gid_http = r.json()["item"]
        r = c.post("/client/job-failed", json={"unit": "http.service", "host": "host-a", "time": "bad", "project": "projects/alpha"}, headers=HD)
        check("http: a bad time is a 400 with the reason", r.status_code == 400 and "ISO time" in r.json()["error"], r.text)
        r = c.post("/client/job-ok", json={"unit": "http.service", "host": "host-a", "time": "2026-12-05T01:00:00Z"}, headers=HD)
        check("http: job-ok -> 200 and the closed item", r.status_code == 200 and r.json()["closed"] == [gid_http], r.text)
        r = c.post("/client/job-ok", json={"unit": "http.service", "host": "host-a", "time": "2026-12-05T01:00:00Z"}, headers=HD)
        check("http: the same job-ok again -> 200, nothing closed", r.status_code == 200 and r.json()["closed"] == [], r.text)
        r = c.post("/client/job-failed", content=b"[1]", headers=HD)
        check("http: a body that is no object -> 400", r.status_code == 400, r.text)
        import urllib.request, urllib.error
        class _Resp:
            def __init__(s, r): s.status = r.status_code; s._b = r.content
            def read(s): return s._b
            def __enter__(s): return s
            def __exit__(s, *a): return False
        down = {"on": False}
        def fake_urlopen(req, timeout=0):
            if down["on"]: raise urllib.error.URLError("connection refused")
            path = req.full_url.replace(client.server_url(), "")
            r = c.post(path, content=req.data, headers=dict(req.header_items())) if req.get_method() == "POST" else c.get(path, headers=dict(req.header_items()))
            if r.status_code >= 400: raise urllib.error.HTTPError(req.full_url, r.status_code, "x", {}, io.BytesIO(r.content))
            return _Resp(r)
        client.urllib.request.urlopen = fake_urlopen
        def run(*argv):
            so, se = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(so), contextlib.redirect_stderr(se): rc = client.main(["client.py", *argv])
            return rc, so.getvalue(), se.getvalue()
        before = len(items())
        rc, o, e = run("job-failed", "cli.service", "host-a", "2026-12-06T02:00:00Z", "projects/alpha")
        gid_cli = o.strip()
        check("client.py job-failed: exactly the item id on stdout, nothing on stderr, exit 0, one item filed", rc == 0 and re.fullmatch(r"\S+\n", o) and e == "" and len(items()) == before + 1, (rc, o, e))
        check("…the item is the job's open item", item(gid_cli)["metadata"]["job_alert"] == "cli.service on host-a" and item(gid_cli)["status"] == "open" and item(gid_cli)["filed_by"] == f"job alert (a script on {me})")
        rc, o2, e = run("job-failed", "cli.service", "host-a", "2026-12-06T14:00:00Z", "projects/alpha")
        check("client.py job-failed again with another time: the same id, exit 0, nothing filed, two failures on the item", rc == 0 and o2 == o and e == "" and len(items()) == before + 1 and item(gid_cli)["metadata"]["job_alert_count"] == 2, (rc, o2, e))
        rc, o, e = run("job-ok", "cli.service", "host-a", "2026-12-06T15:00:00Z")
        check("client.py job-ok: the closed item's id on stdout, exit 0, the item closed", rc == 0 and o.strip() == gid_cli and e == "" and item(gid_cli)["status"] == "completed" and item(gid_cli)["metadata"]["outcome"] == "done", (rc, o, e))
        rc, o, e = run("job-ok", "cli.service", "host-a", "2026-12-06T15:00:00Z")
        check("client.py job-ok again: nothing on either stream, exit 0 (the caller may send it on every success)", rc == 0 and o == "" and e == "", (rc, o, e))
        rc, o, e = run("job-failed", "cli.service", "host-a", "2026-12-07T02:00:00Z", "projects/alpha"); gid_cli2 = o.strip()
        rc, o, e = run("job-ok", "cli.service", "host-a", "2026-12-07T01:00:00Z")
        check("client.py job-ok older than the failed run: exit 0, the item left open, a line on stderr that says why", rc == 0 and o == "" and "older" in e and item(gid_cli2)["status"] == "open", (rc, o, e))
        rc, o, e = run("job-ok", "cli.service", "host-a", "2026-12-07T03:00:00Z")
        rc, o, e = run("job-failed", "cli-gen.service", "host-a", "2026-12-06T02:00:00Z", "-")
        check("client.py job-failed with `-` for the project: the id on stdout, exit 0, the general project's builder named on stderr", rc == 0 and re.fullmatch(r"\S+\n", o) and "heron-engineer" in e and item(o.strip())["metadata"]["project"] == "ops/general", (rc, o, e))
        run("job-ok", "cli-gen.service", "host-a", "2026-12-06T03:00:00Z")
        rc, o, e = run("job-failed", "cli-nb.service", "host-a", "2026-12-06T02:00:00Z", "projects/nobuild")
        check("client.py job-failed for a project with no builder: the id on stdout, the front agent named on stderr", rc == 0 and re.fullmatch(r"\S+\n", o) and "home-nobuild-main" in e, (rc, o, e))
        run("job-ok", "cli-nb.service", "host-a", "2026-12-06T03:00:00Z")
        before = len(items())
        UF, UO = "usage: client.py job-failed", "usage: client.py job-ok"
        for name, verb, argv, needle in (("job-failed with no argument", "job-failed", [], UF), ("job-failed with three", "job-failed", ["x.service", "host-a", "2026-12-06T02:00:00Z"], UF),
                                         ("job-failed with five", "job-failed", ["x.service", "host-a", "2026-12-06T02:00:00Z", "-", "more"], UF), ("job-failed with an empty project", "job-failed", ["x.service", "host-a", "2026-12-06T02:00:00Z", ""], UF),
                                         ("job-failed with an option", "job-failed", ["--sender", "x", "x.service", "host-a", "2026-12-06T02:00:00Z", "-"], UF), ("job-ok with no argument", "job-ok", [], UO),
                                         ("job-ok with two", "job-ok", ["x.service", "host-a"], UO), ("job-ok with four", "job-ok", ["x.service", "host-a", "2026-12-06T02:00:00Z", "-"], UO)):
            rc, o, e = run(verb, *argv)
            check(f"client.py misuse, {name}: usage on stderr, nothing on stdout, exit 1", rc == 1 and o == "" and needle in e, (rc, o, e))
        check("…and none of them filed an item", len(items()) == before, (len(items()), before))
        rc, o, e = run("job-failed", "x.service", "host-a", "yesterday", "projects/alpha")
        check("client.py job-failed with a bad time: the server's 400 on stderr, exit 1, nothing on stdout", rc == 1 and o == "" and "[400]" in e and "ISO time" in e and len(items()) == before, (rc, o, e))
        rc, o, e = run("job-ok", "x.service", "host a", "2026-12-06T02:00:00Z")
        check("client.py job-ok with a bad host: the server's 400 on stderr, exit 1", rc == 1 and o == "" and "[400]" in e, (rc, o, e))
        tokfile = pathlib.Path(client.TOKEN); hold = tokfile.with_suffix(".held"); tokfile.rename(hold)
        try:
            rc, o, e = run("job-failed", "x.service", "host-a", "2026-12-06T02:00:00Z", "projects/alpha")
            check("client.py job-failed with no token on the machine: exit 1, the reason on stderr, nothing filed", rc == 1 and o == "" and "no token on this machine" in e and len(items()) == before, (rc, o, e))
        finally: hold.rename(tokfile)
        _post = client.post
        client.post = lambda what, body, timeout=20.0: (200, {"project": "projects/alpha"})
        try:
            rc, o, e = run("job-failed", "x.service", "host-a", "2026-12-06T02:00:00Z", "projects/alpha")
            check("client.py job-failed when the answer has no item id: exit 1 with a line on stderr, never silent", rc == 1 and o == "" and "no item id" in e, (rc, o, e))
        finally: client.post = _post
        down["on"] = True
        rc, o, e = run("job-failed", "x.service", "host-a", "2026-12-06T02:00:00Z", "projects/alpha")
        check("client.py job-failed with the server not reached: exit 1 and the reason on stderr", rc == 1 and o == "" and e.strip() != "" and len(items()) == before, (rc, o, e))
        rc, o, e = run("job-ok", "x.service", "host-a", "2026-12-06T02:00:00Z")
        check("client.py job-ok with the server not reached: exit 1 (the caller sends it again), the reason on stderr", rc == 1 and o == "" and e.strip() != "", (rc, o, e))
        down["on"] = False
    settle()

fresh(); part_job_gap()
fresh(); _sv = _cfg.CFG["client"].get("session_view")
_cfg.CFG["client"]["session_view"] = "https://sala.example.org/#s={name}"       # the example-owner instance links a pane to sala's web view (its live config); the other parts run without it
try: part_terminal_prompt()
finally: _cfg.CFG["client"]["session_view"] = _sv
fresh(); part_job_alert()

if fails:
    print(f"\n{len(fails)} of {len(ran)} checks FAILED"); sys.exit(1)
print(f"ok: {len(ran)} checks"); sys.exit(0)
