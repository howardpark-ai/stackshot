"""Scenario test for the two script calls a failed run of a scheduled job is reported with (`client.py job-failed` and `client.py job-ok`, POST /client/job-failed and /client/job-ok) — fixture data,
no live store, no network, no server process (the server module is imported and called in-process, on a temporary config; the pages are fixture files in a temporary directory).

Covers: a failure opens ONE item (marked metadata.job_alert = "<unit> on <host>", under the given project page, its builder the mover and in needs, its -main agent the keeper of record, p2, the script
recorded as creator as "job alert (a script on <machine>)", a description that says which job on which machine, the count, the time of the run in the instance's timezone and what to do; the builder is
told once, nothing is owed to the page); a repeat failure with another time adds the line and the count and files nothing, the same time again counts once; another unit or another host is another item;
job-ok closes it (outcome done, the run's time in the reason and in the end state), a second job-ok and a job-ok with no item are ignored (200, nothing closed), a job-ok older than the item's latest failed run
leaves it open; a failure after the close opens a NEW item unless its time is no later than the success that closed the last one (a retry or a late call: seen, nothing filed); a time later than now plus 5 minutes is refused
on both routes (so is one the board cannot show), one instant spelled two ways counts once, the kept times stay in order whatever order they arrive in, a project key that names several pages is refused; a project of `-`, one the registry does not have and a project with no builder (the -main agent moves it, and says so) are filed as the text says,
the general project missing is a 409; the key is read from the item (the module is reloaded between calls: nothing is kept in memory); the newest 20 times are kept while the count goes on; bad input is refused
with nothing filed; eight threads failing one job file one item; over HTTP (401 without a token) and through client.py (the id alone on stdout, usage on misuse, exit 1 when refused or not reached).

    tests/run-suite job_alert        → exit 0 / 1"""
import contextlib, datetime, importlib, io, json, os, re, socket, sys, pathlib, logging, threading, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="jobalerttest-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = ""', f'session_links = "{tmp}/links"', 1); assert f'session_links = "{tmp}/links"' in toml   # the fixture registry, never the host's store
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^owner = "the owner"', 'owner = "Oliver"', toml, count=1); assert n == 1       # the person the tools speak of
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
for d in ("store/a", "fleet/a", "links/a", "brain/projects", "brain/infra", "secrets"): (T / d).mkdir(parents=True)
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")

def uid(n): return f"00000000-0000-4000-8000-{n:012d}"
S = {"build": uid(101), "main": uid(102), "docs": uid(103), "nbmain": uid(104), "gbuild": uid(105), "gmain": uid(106), "tmain": uid(107)}
def row(key, name, project_key):
    return {"id": S[key], "name": name, "aliases": [], "project": None, "project_key": project_key, "role": None, "lane": "max", "model": "opus", "effort": "medium", "pane": name,
            "cwd": "/work", "state": "live", "created": "2026-10-21T21:00:00Z", "retired_at": None,
            "transcripts": [{"id": uid(200 + int(S[key][-3:]) - 100), "machine": "a", "at": "2026-10-21T21:00:00Z", "why": "import"}]}
ROWS = [row("build", "home-sparrow-builder", "projects/alpha"), row("main", "home-sparrow-main", "projects/alpha"), row("docs", "home-sparrow-docs", "projects/alpha"), row("nbmain", "home-nobuild-main", "projects/nobuild"),
        row("gbuild", "heron-engineer", "ops/general"), row("gmain", "heron-main", "ops/general"), row("tmain", "home-twin-main", "projects/twin")]
(T / "links/a/session-registry.json").write_text(json.dumps({"schema": 1, "machine": "a", "written": "2026-10-22T07:00:00Z", "sessions": {r["id"]: r for r in ROWS}}), encoding="utf-8")
def page(rel, front):
    q = T / "brain" / rel; q.parent.mkdir(parents=True, exist_ok=True); q.write_text("---\n" + front + "\n---\n\n# x\n", encoding="utf-8")
page("projects/alpha.md", "type: project\ntitle: Alpha\ndisplay-name: home-sparrow\nagents:\n  home-sparrow-docs: keeps the docs\n  home-sparrow-main: talks to Oliver\n  background:\n    home-sparrow-notes: keeps the notes\n    home-sparrow-builder: builds\nstatus: active")
page("projects/nobuild.md", "type: project\ntitle: Nobuild\ndisplay-name: home-nobuild\nagents:\n  home-nobuild-main: talks to Oliver\nstatus: active")
page("projects/twin.md", "type: project\ntitle: Twin\ndisplay-name: home-twin\nagents:\n  home-twin-main: talks to Oliver\nstatus: active")
page("ops/twin.md", "type: project\ntitle: Twin ops\ndisplay-name: home-twinops\nagents:\n  home-twinops-main: talks to Oliver\nstatus: active")
page("ops/general.md", "type: project\ntitle: General\ndisplay-name: heron\nagents:\n  heron-main: talks to Oliver\n  background:\n    heron-engineer: builds and fixes needing no decision\nstatus: active")
for pg in (T / "brain").rglob("*.md"): os.utime(pg, (time.time() - 8 * 3600, time.time() - 8 * 3600))      # the pages are older than any debt (and the 5-minute slack), so a debt charged by a write would stand
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))

from stackshot.projects import pages as p
p.cmd_registry(quiet=True)
from stackshot.fleet import sessions_registry as sr
sr.TTL = 0
from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route; from stackshot.fleet import client; from stackshot.model import model as M; from stackshot.model import ids as _model_ids
from stackshot.service import job_alert as _ja_first
from stackshot.web.routes import client_api as _rt_client
import subprocess
from stackshot.service import store as _service_store
from stackshot.core import config as _cfg
from stackshot.web import page_debts as _pdebts
from stackshot.github import ghsync as _gh
from stackshot.web import publish as _web_publish
from stackshot.model import field_gates as _fg
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
def items(): return sorted(p_.stem for d in (T / "store").iterdir() if d.is_dir() for p_ in d.glob("*.json") if p_.stem.isdigit())
def item(shown): return _service_store._load(_model_ids._norm_id(shown))
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
    """The server's clock for the future-time guard: the fixture's times are all before NOW. The module is reloaded in section 3, so this is called again there."""
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
check("…the subject names the unit and the machine", it["subject"] == "[home] nightly.service failed on host-a", it["subject"])
check("…p2; the project's builder (not the notes keeper) is the mover and is in needs", m.get("priority") == "p2" and sr._session_label(m.get("mover")) == "home-sparrow-builder"
      and [sr._session_label(x) for x in m.get("needs") or []] == ["home-sparrow-builder"], m)
check("…the keeper of record is the -main agent; the creator reads `job alert (a script on <machine>)`", sr._session_label(m["owner"]) == "home-sparrow-main" and it["filed_by"] == f"job alert (a script on {me})", (m["owner"], it.get("filed_by")))
check("…next names the builder and what to do", m.get("next", "") == "home-sparrow-builder: read the journal of nightly.service on host-a, fix the cause; the next successful run closes this item", m.get("next"))
d = it["description"].splitlines()
check("…the description is bullets: the job and machine, the count, the run's time in the instance's zone, what to do, who opened it",
      len(d) == 5 and all(x.startswith("- ") for x in d) and d[0] == "- nightly.service on host-a ended a scheduled run in failure" and d[1] == "- Failed runs since this item opened: 1"
      and d[2].startswith("- Failed run at Mon Nov 23rd 06:15 ") and "journal of nightly.service on host-a" in d[3] and "next successful run closes this item" in d[3] and d[4] == f"- Opened by job alert (a script on {me})", it["description"])
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
check("…the description has the count 2 and both runs' times, the earlier first", d[1] == "- Failed runs since this item opened: 2" and d[2].startswith("- Failed run at Mon Nov 23rd 06:15 ") and d[3].startswith("- Failed run at Mon Nov 23rd 18:15 "), d)
check("…the item is still open under the same mover, with the metadata kept", item(gid1)["status"] == "open" and item(gid1)["metadata"]["job_alert_count"] == 2 and item(gid1)["metadata"]["job_alert_runs"] == ["2026-11-23T02:15:00Z", "2026-11-23T14:15:00Z"]
      and sr._session_label(item(gid1)["metadata"]["mover"]) == "home-sparrow-builder", item(gid1)["metadata"])
settle()
check("…and the builder is not told again", pushed == [], pushed)
st, o3 = failed(time_="2026-11-23T14:15:00Z")
check("the same run's time again (a call sent twice): seen, still two failures, nothing changed", st == 200 and o3["item"] == gid1 and o3["action"] == "seen" and o3["failures"] == 2 and item(gid1)["metadata"]["job_alert_count"] == 2 and len(items()) == n1, (st, o3))
st, o4 = failed(host="host-b")
check("the same unit on another host is another item", st == 200 and o4["item"] != gid1 and o4["action"] == "opened" and item(o4["item"])["metadata"]["job_alert"] == "nightly.service on host-b", (st, o4))
st, o5 = failed(unit="weekly.timer")
check("another unit on the same host is another item", st == 200 and o5["item"] not in (gid1, o4["item"]) and o5["action"] == "opened" and item(o5["item"])["subject"] == "[home] weekly.timer failed on host-a", (st, o5))
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
      and it["metadata"]["reason"] == "the next run of nightly.service on host-a succeeded at Tue Nov 24th 07:00 +04" and "ran successfully at Tue Nov 24th 07:00 +04" in it["metadata"]["outcome_text"]
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
check("a unit name too long for the subject limit still opens: a subject of at most 80 characters that keeps the scope prefix, the cut name and the machine", st == 200 and len(sub) <= 80 and sub.startswith("[home] very-long")
      and sub.endswith(" … failed on host-a"), (st, o, sub))
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
check("…and the description lists them in that order", d[2].startswith("- Failed run at Fri Dec 11th 12:00 ") and d[3].startswith("- Failed run at Fri Dec 11th 14:00 "), d)
ok(unit="sort.service", time_="2026-12-11T11:00:00Z")

# ---- 9e. a project key that names several pages is refused, never the first one
n9 = len(items())
st, e = failed(unit="twin.service", project="twin")
check("a bare slug that names two pages: 409 that names both and asks for the full key, nothing filed", st == 409 and "projects/twin" in e["error"] and "ops/twin" in e["error"] and "full key" in e["error"] and len(items()) == n9 and open_for("twin.service", "host-a") == [], (st, e))
st, e = failed(unit="twin.service", project="projects/twin")
check("…while the full key of one of them files under it", st == 200 and e["project"] == "projects/twin" and e["owner"] == "home-twin-main" and e["mover"] == "home-twin-main", (st, e)); ok(unit="twin.service")

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

if fails:
    print(f"\n{len(fails)} of {len(ran)} checks FAILED"); sys.exit(1)
print(f"ok: {len(ran)} checks"); sys.exit(0)
