"""Scenario test for the script post kind a gap in a scheduled job is filed with (`client.py post job-gap open|clear`, POST /client/job-gap, Oliver's pick A) — fixture data, no
live store, no network, no server process (the server module is imported and called in-process, on a temporary config; the pages are fixture files in a temporary directory).

Covers: open (one open item per (timer, code), marked metadata.job_gap = "<timer>: <code>", subject "[home] <timer>: <the gap>", under the project page that owns the repo, the project's builder the
mover and in needs, its -main agent the keeper of record, p2, next "<builder>: <the fix>", description bullets that say the gap and the fix, the script recorded as creator; the builder is told
once and no front agent is woken, nothing is owed to the page); a repeat open of an open (timer, code) files nothing and answers the same item, another code or another timer is another item;
clear (closes it: outcome done, a reason within the limit, the end state in outcome_text, the id answered), clear with none open a 200 that says so, an open again after a clear
files a new item; a repo the server does not know a 400 that names the known ones; a project with no builder moves the item by its -main agent and says so; a project with no front agent
a 409; the repo map ([job_gap.repos] over the defaults); the sender gate (the owner's name, a long or multi-line label refused; none given taken as client.py); a long unit name cut
so the subject stays within the limit; bad timer, code, action and repo refused with nothing filed; eight threads opening one gap file one item; over HTTP (401 without a token) and through
client.py (the id alone on stdout, the note on stderr when a front agent moves it, usage on misuse, a server that is not reached).

    tests/run-suite job_gap        → exit 0 / 1"""
import contextlib, io, json, os, re, socket, sys, pathlib, logging, threading, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="jobgaptest-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml = toml.replace('session_links = ""', f'session_links = "{tmp}/sala"', 1); assert f'session_links = "{tmp}/sala"' in toml   # the fixture registry, never the host's sala store
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^owner = "the owner"', 'owner = "Oliver"', toml, count=1); assert n == 1       # the person the tools speak of
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
for d in ("store/a", "fleet/a", "sala/a", "state/anchor-hub", "brain/projects", "brain/infra", "secrets"): (T / d).mkdir(parents=True)
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")

def uid(n): return f"00000000-0000-4000-8000-{n:012d}"
S = {"build": uid(101), "main": uid(102), "docs": uid(103), "nbmain": uid(104), "gbuild": uid(105)}
def row(key, name, project_key):
    return {"id": S[key], "name": name, "aliases": [], "project": None, "project_key": project_key, "role": None, "lane": "max", "model": "opus", "effort": "medium", "pane": name,
            "cwd": "/home/user", "state": "live", "created": "2026-10-21T21:00:00Z", "retired_at": None,
            "transcripts": [{"id": uid(200 + int(S[key][-3:]) - 100), "machine": "a", "at": "2026-10-21T21:00:00Z", "why": "import"}]}
ROWS = [row("build", "home-sparrow-builder", "projects/alpha"), row("main", "home-sparrow-main", "projects/alpha"), row("docs", "home-sparrow-docs", "projects/alpha"), row("nbmain", "home-nobuild-main", "projects/nobuild"),
        row("gbuild", "heron-engineer", "ops/general")]
(T / "sala/a/session-registry.json").write_text(json.dumps({"schema": 1, "machine": "a", "written": "2026-10-22T07:00:00Z", "sessions": {r["id"]: r for r in ROWS}}), encoding="utf-8")
def page(rel, front):
    q = T / "brain" / rel; q.parent.mkdir(parents=True, exist_ok=True); q.write_text("---\n" + front + "\n---\n\n# x\n", encoding="utf-8")
page("projects/alpha.md", "type: project\ntitle: Alpha\ndisplay-name: home-sparrow\nagents:\n  home-sparrow-docs: keeps the docs\n  home-sparrow-main: talks to Oliver\n  background:\n    home-sparrow-notes: keeps the notes\n    home-sparrow-builder: builds\nstatus: active")
page("projects/nobuild.md", "type: project\ntitle: Nobuild\ndisplay-name: home-nobuild\nagents:\n  home-nobuild-main: talks to Oliver\nstatus: active")
page("projects/gamma.md", "type: project\ntitle: Gamma\ndisplay-name: home-gamma\nstatus: active")
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
from stackshot.web import server; from stackshot.fleet import client; from stackshot.model import model as M
server._publish = lambda: None
pushed = []                           # every push to a session the server would make: [to, note]
_orig_run = server.subprocess.run
def _fake_run(cmd, *a, **kw):
    if isinstance(cmd, list) and any(str(x).endswith("push.py") or str(x).endswith("fakepush.py") for x in cmd):
        pushed.append(list(cmd)[-2:]); return server.subprocess.CompletedProcess(cmd, 0, "delivered\n", "")
    return _orig_run(cmd, *a, **kw)
server.subprocess.run = _fake_run
def settle():
    """The notices go out on threads: wait for them (at most 3 s each)."""
    for t in threading.enumerate():
        if t is not threading.current_thread() and t.daemon and t.is_alive(): t.join(3)
from starlette.testclient import TestClient
me = socket.gethostname(); tok = open(client.mint(me)).read().strip(); HD = {"Authorization": "Bearer " + tok}
def items(): return sorted(p_.stem for d in (T / "store").iterdir() if d.is_dir() for p_ in d.glob("*.json") if p_.stem.isdigit())
def item(shown): return server._load(server._norm_id(shown))
def jg(action, timer="sala-foo.timer", code="no-lane", repo="acme/alpha", sender="sala-unit-gaps", machine=None, **kw):
    b = {"action": action, "timer": timer, "code": code, "repo": repo, "sender": sender}
    b.update(kw)
    return server._client_post(machine or me, "job-gap", {k: v for k, v in b.items() if v is not None})
def open_for(timer, code): return server._jobgap_open_items(f"{timer}: {code}")
# the repo map of this instance: the test repos over the defaults
server._cfg.CFG["job_gap"] = {"repos": {"acme/alpha": "projects/alpha", "acme/nobuild": "projects/nobuild", "acme/gamma": "projects/gamma", "acme/ghost": "projects/ghost", "Acme/Mixed-Case": "projects/alpha"}}
n0 = len(items())

# ---- 1. open: the item and its shape
st, out = jg("open", detail="/home/user/.config/systemd/user/sala-foo.timer, script /home/user/bin/foo.sh")
check("open: 200 with the item id as shown, the timer, the code, the project, the mover, the keeper, repeat false, no fallback",
      st == 200 and out["timer"] == "sala-foo.timer" and out["code"] == "no-lane" and out["project"] == "projects/alpha" and out["mover"] == "home-sparrow-builder" and out["owner"] == "home-sparrow-main"
      and out["repeat"] is False and out["fallback"] is False and out["item"] == server._gh.shown(server._norm_id(out["item"])), (st, out))
it = item(out["item"]); m = it["metadata"]
check("the item is open, filed under the repo's project page, marked with the timer and the code", it["status"] == "open" and m["project"] == "projects/alpha" and m["job_gap"] == "sala-foo.timer: no-lane", (it["status"], m))
check("…the subject names the unit and the gap", it["subject"] == "[home] sala-foo.timer: has no X-Model-Lane", it["subject"])
check("…p2; the project's builder (the one whose mandate builds, not the notes keeper) is the mover and is in needs", m.get("priority") == "p2" and server._session_label(m.get("mover")) == "home-sparrow-builder"
      and [server._session_label(x) for x in m.get("needs") or []] == ["home-sparrow-builder"], m)
check("…the keeper of record is the project's -main agent (not the builder, not the docs agent); the script is the creator", server._session_label(m["owner"]) == "home-sparrow-main"
      and it["filed_by"] == f"sala-unit-gaps via a script on {me}", (m["owner"], it.get("filed_by")))
check("…next is one line that names the builder and the fix: the unit in the repo with X-Model-Lane, linked from there", m.get("next", "").startswith("home-sparrow-builder: put sala-foo.timer's unit file in acme/alpha with an X-Model-Lane= line, linked from there")
      and "\n" not in m["next"].strip(), m.get("next"))
d = it["description"].splitlines()
check("…the description is bullets: the gap, the detail, the fix, the repo, who opened it", len(d) == 5 and all(x.startswith("- ") for x in d) and d[0].startswith("- sala-foo.timer has no X-Model-Lane= line")
      and "script /home/user/bin/foo.sh" in d[1] and d[2].startswith("- Fix: put sala-foo.timer") and "acme/alpha" in d[3] and d[4] == f"- Opened by sala-unit-gaps (a script on {me}); it closes when the watcher finds the gap fixed", it["description"])
settle()
check("…the builder is told once and no one else is: no push names the keeper of record or another agent", len(pushed) == 1 and pushed[0][0] in ("home-sparrow-builder", S["build"]) and out["item"] in pushed[0][1] and "now needs you" in pushed[0][1], pushed)
check("…one item filed, and the row owes no page: no debt is charged to the script, the builder or the keeper", len(items()) == n0 + 1 and server._owed_load() == {}, (len(items()) - n0, server._owed_load()))
check("…the item is alive with the builder as the mover (not in the owner's list)", M.derive(it).state == M.ALIVE and M.derive(it).mover == "home-sparrow-builder", (M.derive(it).state, M.derive(it).mover))
check("…the item is in the brief", out["item"] in server.stackshot_get(out["item"]), server.stackshot_get(out["item"])[:300])
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
check("another code on the same timer is another item", st == 200 and o4["item"] != gid1 and o4["repeat"] is False and item(o4["item"])["subject"] == "[home] sala-foo.timer: is not in git" and len(items()) == n1 + 1, (st, o4))
st, o5 = jg("open", timer="sala-bar.timer")
check("another timer with the same code is another item", st == 200 and o5["item"] not in (gid1, o4["item"]) and item(o5["item"])["subject"] == "[home] sala-bar.timer: has no X-Model-Lane" and len(items()) == n1 + 2, (st, o5))
check("…each open gap finds its own item", open_for("sala-foo.timer", "no-lane") == [server._norm_id(gid1)] and len(open_for("sala-foo.timer", "not-git")) == 1 and len(open_for("sala-bar.timer", "no-lane")) == 1)
for code, subj in (("no-description", "has no Description="), ("bad-lane", "has a bad X-Model-Lane"), ("git-differs", "differs from its file in git"), ("odd-new-code", "has the gap odd-new-code")):
    st, o = jg("open", timer="sala-codes.timer", code=code)
    check(f"code {code}: its words in the subject", st == 200 and item(o["item"])["subject"] == f"[home] sala-codes.timer: {subj}", (st, o, item(o["item"])["subject"] if st == 200 else ""))
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
check("an @ between letters or digits in a timer (a template unit) is taken", st == 200 and oi["subject"] == "[home] sala-job@1.service: has no X-Model-Lane", (st, o, oi["subject"]))
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
      and "no-lane is fixed on sala-foo.timer" in it["metadata"].get("reason", "") and len(it["metadata"]["reason"]) <= server._close_reason_max() and it["metadata"]["outcome_text"].splitlines()[0] == "- sala-foo.timer: the gap (no-lane) is fixed"
      and it["metadata"]["outcome_text"].splitlines()[-1].startswith("- Closed by sala-unit-gaps (a script on") and "is fixed" not in it["description"], (it["status"], it["metadata"].get("reason"), it["description"]))
settle()
check("…the close tells no session and charges no page; the other gaps stay open", pushed == [] and server._owed_load() == {} and open_for("sala-foo.timer", "not-git") != [] and open_for("sala-foo.timer", "no-lane") == [], (pushed, server._owed_load()))
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
      and not it["metadata"].get("needs") and server._session_label(it["metadata"].get("mover")) == "home-nobuild-main" and pushed == [], (it["description"], it["metadata"], pushed))
st, o7 = jg("open", timer="sala-nb.timer", repo="acme/nobuild")
check("…and a repeat answers the same item with the fallback still true", st == 200 and o7["item"] == o["item"] and o7["repeat"] is True and o7["fallback"] is True, (st, o7))
jg("clear", timer="sala-nb.timer", repo=None)
st, e = jg("open", timer="sala-g.timer", repo="acme/gamma")
check("a project that lists no front agent: 409, nothing filed", st == 409 and "front agent" in e["error"] and open_for("sala-g.timer", "no-lane") == [], (st, e))
st, e = jg("open", timer="sala-g.timer", repo="acme/ghost")
check("a repo mapped to a page that is not in the registry: 409 that says to fix the map", st == 409 and "projects/ghost" in e["error"] and "no project page" in e["error"], (st, e))
# the defaults: no [job_gap] section at all -> the fleet's three repos
server._cfg.CFG.pop("job_gap", None)
check("the defaults (no [job_gap.repos]): no repo is listed (the code names none)", server._jobgap_repos() == {}, server._jobgap_repos())
server._cfg.CFG["job_gap"] = {"repos": {"example-owner/ops-hub": "ops/general", "example-org/fleet-tool": "projects/fleet-tool", "example-org/board": "projects/board"}}   # the example-owner instance's table
pushed.clear()
st, o = jg("open", timer="sala-hub.timer", repo="example-owner/ops-hub", code="not-git")
check("…ledger-hub is ops/general, its builder heron-engineer is the mover, heron-main the keeper", st == 200 and o["project"] == "ops/general" and o["mover"] == "heron-engineer" and o["owner"] == "heron-main"
      and item(o["item"])["metadata"]["next"].startswith("heron-engineer: put sala-hub.timer's unit file in example-owner/ops-hub"), (st, o))
settle()
check("…and the builder is told", len(pushed) == 1 and pushed[0][0] in ("heron-engineer", S["gbuild"]), pushed)
jg("clear", timer="sala-hub.timer", code="not-git", repo=None)
server._cfg.CFG["job_gap"] = {"repos": "not a table"}
st, e = jg("open", repo="acme/alpha")
check("a [job_gap] repos that is not a table lists no repo: 400 'none is listed'", st == 400 and "none is listed" in e["error"], (st, e))
server._cfg.CFG["job_gap"] = {"repos": {"acme/alpha": "projects/alpha", "acme/odd": 7}}
check("…an entry that is not text is skipped", server._jobgap_repos() == {"acme/alpha": "projects/alpha"}, server._jobgap_repos())

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
server._cfg.CFG["job_gap"] = {"repos": {"acme/alpha": "projects/alpha", "acme/nobuild": "projects/nobuild"}}
LONG = "sala-" + "very-long-unit-name-" * 5 + "x.timer"          # 105 characters: the subject would be over 80
st, o = jg("open", timer=LONG, code="no-lane")
sub = item(o["item"])["subject"] if st == 200 else ""
check("a unit name too long for the subject limit still opens: 200, a subject of at most 80 characters that keeps the scope prefix, the cut name and the gap", st == 200 and len(sub) <= 80 and sub.startswith("[home] sala-very-long")
      and sub.endswith(" …: has no X-Model-Lane"), (st, o, sub))
check("…the mark keeps the whole name and a clear by the whole name closes it", item(o["item"])["metadata"]["job_gap"] == f"{LONG}: no-lane" and jg("clear", timer=LONG, repo=None)[1]["cleared"] == [o["item"]])
st, o = jg("open", timer="t" * 120, code="a" * 40)
sub = item(o["item"])["subject"] if st == 200 else ""
check("the longest timer and code the call takes: still a subject within the limit", st == 200 and len(sub) <= 80, (st, o, sub)); jg("clear", timer="t" * 120, code="a" * 40, repo=None)
st, o = jg("open", timer="sala-detail.timer", detail="x" * 600)
dd = item(o["item"])["description"].splitlines() if st == 200 else []
max_lines, line_max = server._description_limits()
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

if fails:
    print(f"\n{len(fails)} of {len(ran)} checks FAILED"); sys.exit(1)
print(f"ok: {len(ran)} checks"); sys.exit(0)
