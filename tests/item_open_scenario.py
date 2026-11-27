"""Scenario test for the script route that opens one board item for a project's background agent (`client.py post item-open`, POST /client/item-open) — fixture data, no live store, no
network, no server process (the server module is imported and called in-process, on a temporary config; the pages are fixture files in a temporary directory).

Covers: open (one item filed through the create tool's own code: the subject takes the project scope's prefix from the server and replaces a prefix the caller wrote, marked metadata.item_open = the
marker, the mover a background agent of the page and in needs, the project's -main agent the creator, one step that names the mover, description bullets ending with the attribution line, no machine
host name anywhere in the item, the mover told once, nothing owed to the page); a repeat call while the item is open answers it and files nothing, another marker is another item, and the same marker on another project is that project's own item (a call never answers or shows another project's item); a call after the
item was closed files a new item (the open state is read from the store); a mover that is not a background agent the page lists (a front agent, the owner, another project's agent, a made-up name)
is refused with the listed ones named (a front-only project, whose page lists none, files the item under its -main agent as its mover and says so, as the job-gap route does); bad bullets (none, too many, too long, a control character, a wrong type) are refused and never cut; a missing or malformed marker, a missing field, a step that
does not start with the mover, a key the route does not take (needs, owner, priority) and a sender with markup or the owner's name are refused with nothing filed; an @name is broken so the mirror pings
no one; an unknown project a 404, a project with no front agent a 409; a cap of 10 open items per project (the eleventh marker is refused, a repeat at the cap is still answered, a closed item frees a place, the cap is per project); a long sender and a doubled caller prefix; the unknown-write 404 lists the route; eight threads calling at once file one item; over HTTP (401 without a token) and through client.py (the id alone on stdout,
usage on misuse, the server's refusal on stderr, a server that is not reached).

Also covers `client.py post item-sync <marker> open|refresh|close` (POST /client/item-sync), the route that keeps one item for the person in step with a condition a script checks: open files an item whose mover is the person,
whose then is an agent of the project and whose one step is his; a repeat open while it is open is a refresh and files nothing; refresh changes the description alone; close completes it as done, ticks his step and says the script saw the
condition gone; refresh and close with none open are no-ops; an open after a close files a new item; misshaped input is refused with the board's text; an item the route did not open (an item-open item with the same marker text) is out of its reach; a cap of 10 open items per project; eight threads, one item; over HTTP and
through client.py (one line on stdout, usage on misuse).

    tests/run-suite item_open        → exit 0 / 1"""
import contextlib, datetime, io, json, os, re, socket, sys, pathlib, logging, threading, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="itemopentest-"); T = pathlib.Path(tmp)
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
for d in ("store/a", "fleet/a", "sala/a", "brain/projects", "brain/infra", "secrets"): (T / d).mkdir(parents=True)
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")

def uid(n): return f"00000000-0000-4000-8000-{n:012d}"
S = {"build": uid(101), "main": uid(102), "docs": uid(103), "nbmain": uid(104), "gbuild": uid(105), "bmain": uid(106), "bbuild": uid(107), "cmain": uid(108), "cbuild": uid(109), "side": uid(110)}
def row(key, name, project_key):
    return {"id": S[key], "name": name, "aliases": [], "project": None, "project_key": project_key, "role": None, "lane": "max", "model": "opus", "effort": "medium", "pane": name,
            "cwd": "/work", "state": "live", "created": "2026-10-21T21:00:00Z", "retired_at": None,
            "transcripts": [{"id": uid(200 + int(S[key][-3:]) - 100), "machine": "a", "at": "2026-10-21T21:00:00Z", "why": "import"}]}
ROWS = [row("build", "home-sparrow-builder", "projects/alpha"), row("main", "home-sparrow-main", "projects/alpha"), row("docs", "home-sparrow-docs", "projects/alpha"), row("nbmain", "home-nobuild-main", "projects/nobuild"),
        row("gbuild", "heron-engineer", "ops/general"),
        row("bmain", "home-beta-main", "projects/beta"), row("bbuild", "home-beta-builder", "projects/beta"), row("cmain", "home-capped-main", "projects/capped"), row("cbuild", "home-capped-builder", "projects/capped"), row("side", "home-sparrow-side", "projects/alpha/side")]
(T / "sala/a/session-registry.json").write_text(json.dumps({"schema": 1, "machine": "a", "written": "2026-10-22T07:00:00Z", "sessions": {r["id"]: r for r in ROWS}}), encoding="utf-8")
def page(rel, front):
    q = T / "brain" / rel; q.parent.mkdir(parents=True, exist_ok=True); q.write_text("---\n" + front + "\n---\n\n# x\n", encoding="utf-8")
page("projects/alpha.md", "type: project\ntitle: Alpha\ndisplay-name: home-sparrow\nagents:\n  home-sparrow-docs: keeps the docs\n  home-sparrow-main: talks to Oliver\n  background:\n    home-sparrow-notes: keeps the notes\n    home-sparrow-builder: builds\nstatus: active")
page("projects/alpha/side.md", "type: project\ntitle: Alpha side\ndisplay-name: home-sparrow-side\nagents:\n  home-sparrow-side: talks to Oliver\nstatus: active")
page("projects/nobuild.md", "type: project\ntitle: Nobuild\ndisplay-name: home-nobuild\nagents:\n  home-nobuild-main: talks to Oliver\nstatus: active")
page("projects/beta.md", "type: project\ntitle: Beta\ndisplay-name: home-beta\nagents:\n  home-beta-main: talks to Oliver\n  background:\n    home-beta-builder: builds\nstatus: active")
page("projects/capped.md", "type: project\ntitle: Capped\ndisplay-name: home-capped\nagents:\n  home-capped-main: talks to Oliver\n  background:\n    home-capped-builder: builds\nstatus: active")
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
from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route; from stackshot.fleet import client; from stackshot.model import model as M; from stackshot.model import ids as _model_ids; from stackshot.service import item_open as item_open_svc
from stackshot.web.routes import client_api as _rt_client
from stackshot.service import update as _update_svc
import subprocess
from stackshot.service import store as _service_store
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

def bare_at(text): return re.search(r"(?<!\w)@(?!\u200b)\w", str(text)) is not None
def io_(marker="test_trim:alpha", **kw):
    b = {"marker": marker, "project": "projects/alpha", "subject": "Deep-scan the alpha suites", "mover": "home-sparrow-builder", "step": "home-sparrow-builder: deep-scan the suites, delete what is obsolete, report",
         "description": ["- Repo alpha tripped max_suites: 120 > 100", "- A deep scan for duplicate or obsolete suites is the first step"], "sender": "test-trim-job"}
    b.update(kw)
    return _rt_client._client_post(me, "item-open", {k: v for k, v in b.items() if v is not None})
def open_for(marker, project="projects/alpha"): return [g for g, m_ in item_open_svc._itemopen_open_items(project) if m_ == marker]
def close(shown):
    _update_svc._update(_model_ids._norm_id(shown), outcome_text="- done", status="completed", outcome="done", reason="the deep scan is done", sender="home-sparrow-builder")
n0 = len(items())

# ---- 1. open: the item and its shape
st, out = io_()
check("open: 200 with the item id as shown, the marker, the project, the mover, the creator, repeat false", st == 200 and out["marker"] == "test_trim:alpha" and out["project"] == "projects/alpha" and out["mover"] == "home-sparrow-builder"
      and out["owner"] == "home-sparrow-main" and out["repeat"] is False and out["item"] == _gh.shown(_model_ids._norm_id(out["item"])), (st, out))
it = item(out["item"]); m = it["metadata"]
check("the item is open, filed under the project page, marked with the marker", it["status"] == "open" and m["project"] == "projects/alpha" and m["item_open"] == "test_trim:alpha", (it["status"], m))
check("…the subject is the caller's words under the project scope's prefix", it["subject"] == "[home] Deep-scan the alpha suites", it["subject"])
check("…the mover is the page's background agent and is in needs; the project's -main agent is the creator; the script is recorded as the writer", sr._session_label(m.get("mover")) == "home-sparrow-builder"
      and [sr._session_label(x) for x in m.get("needs") or []] == ["home-sparrow-builder"] and sr._session_label(m["owner"]) == "home-sparrow-main"
      and it["filed_by"] == "test-trim-job (a script on a client machine)", (m, it.get("filed_by")))
check("…next is the one step, and it names the mover", m.get("next", "").strip() == "home-sparrow-builder: deep-scan the suites, delete what is obsolete, report", m.get("next"))
d = it["description"].splitlines()
check("…the description is the caller's bullets, then who opened it", d == ["- Repo alpha tripped max_suites: 120 > 100", "- A deep scan for duplicate or obsolete suites is the first step",
      "- Opened by test-trim-job (a script on a client machine)"], d)
check("…no host name in the item (description, subject, creator), and none in what the call answered", me not in json.dumps(it) and me not in json.dumps(out), me)
settle()
check("…the mover is told once, no one else is: nothing is owed to the page", len(pushed) == 1 and pushed[0][0] in ("home-sparrow-builder", S["build"]) and out["item"] in pushed[0][1] and _pdebts._owed_load() == {}, (pushed, _pdebts._owed_load()))
check("…the item is alive with the builder as its mover", M.derive(it).state == M.ALIVE and M.derive(it).mover == "home-sparrow-builder", (M.derive(it).state, M.derive(it).mover))
gid1 = out["item"]

# ---- 2. a repeat call while the item is open changes nothing; another marker is another item
n1 = len(items()); pushed.clear()
st, o2 = io_(subject="A different subject", description=["- Different text"])
settle()
check("a repeat call with the same marker: 200, the same item, repeat true, nothing filed, nothing told", st == 200 and o2["item"] == gid1 and o2["repeat"] is True and len(items()) == n1 and pushed == [], (st, o2, pushed))
check("…the item is as it was", item(gid1)["description"] == it["description"] and item(gid1)["subject"] == it["subject"] and item(gid1)["metadata"]["next"] == m["next"])
st, o3 = io_(mover="home-sparrow-notes", step="home-sparrow-notes: deep-scan")
check("…the marker alone is the key: another listed mover with the same marker still answers the open item", st == 200 and o3["item"] == gid1 and o3["repeat"] is True and len(items()) == n1, (st, o3))
st, o4 = io_(marker="test_trim:beta")
check("another marker is another item", st == 200 and o4["item"] != gid1 and o4["repeat"] is False and len(items()) == n1 + 1 and open_for("test_trim:beta") != [] and len(open_for("test_trim:alpha")) == 1, (st, o4))
close(o4["item"])

# ---- 3. after the item is closed a call files a new one (the open state is read from the store)
n2 = len(items())
close(gid1)
check("closing the item: it is completed and the marker has no open item", item(gid1)["status"] == "completed" and open_for("test_trim:alpha") == [], (item(gid1)["status"], open_for("test_trim:alpha")))
st, o5 = io_()
check("a call after the close files a new item: 200, a new id, repeat false, open, marked", st == 200 and o5["item"] != gid1 and o5["repeat"] is False and item(o5["item"])["status"] == "open"
      and item(o5["item"])["metadata"]["item_open"] == "test_trim:alpha" and len(items()) == n2 + 1, (st, o5))
st, o6 = io_()
check("…and a repeat of that one answers it", st == 200 and o6["item"] == o5["item"] and o6["repeat"] is True, (st, o6))
check("…a marker of an item removed from the store is no open item (nothing the caller keeps is read)", open_for("test_trim:never-filed") == [])
close(o5["item"])

# ---- 4. the mover must be a background agent the page lists
n3 = len(items())
for who, why in (("home-sparrow-main", "a front agent"), ("home-sparrow-docs", "a front agent"), ("Oliver", "the owner"), ("heron-engineer", "another project's background agent"), ("no-such-agent", "a made-up name"),
                 ("HOME-SPARROW-BUILDER", "the right name in other capitals"), ("home-sparrow", "a prefix of a name")):
    st, e = io_(mover=who, step=f"{who}: deep-scan")
    check(f"mover {who!r} ({why}): 400 naming the listed background agents, nothing filed", st == 400 and "not a background agent" in e["error"] and "home-sparrow-builder" in e["error"] and "home-sparrow-notes" in e["error"] and len(items()) == n3, (st, e))
# a front-only project (no builder) whose page lists no background agent has nobody to hold the item: it is with its -main agent and says so (as the job-gap route does); a project that lists one is unchanged (above)
st, fo = io_(marker="test_trim:nobuild", project="projects/nobuild", mover="home-nobuild-builder", step="home-nobuild-builder: deep-scan the suites")
fit = item(fo["item"]) if st == 200 else {"metadata": {}, "description": ""}; fm = fit["metadata"]
check("a front-only project: 200, the mover is its -main agent (also the creator), fallback true", st == 200 and fo["mover"] == "home-nobuild-main" and fo["owner"] == "home-nobuild-main" and fo["fallback"] is True and fo["repeat"] is False
      and len(items()) == n3 + 1, (st, fo))
check("…the item holds the -main agent as its mover, the step keeps its words under that name, no needs, and the item says it is with the front agent", sr._session_label(fm.get("mover")) == "home-nobuild-main"
      and fm.get("next", "").strip() == "home-nobuild-main: deep-scan the suites" and not fm.get("needs") and fm.get("item_open_fallback") is True and fm.get("item_open") == "test_trim:nobuild"
      and fit["description"].splitlines()[-2:] == ["- projects/nobuild lists no background agent, so this is with home-nobuild-main, its front agent", "- Opened by test-trim-job (a script on a client machine)"], (fm, fit["description"]))
st, fo2 = io_(marker="test_trim:nobuild", project="projects/nobuild", mover="home-nobuild-builder", step="home-nobuild-builder: deep-scan the suites")
check("…a repeat call answers it (repeat true, fallback true) and files nothing", st == 200 and fo2["item"] == fo["item"] and fo2["repeat"] is True and fo2["fallback"] is True and len(items()) == n3 + 1, (st, fo2))
st, e = io_(marker="test_trim:nobuild2", project="projects/nobuild", mover="x", step="y: no name of the mover")
check("…the step must still start with the mover the caller named (nothing filed)", st == 400 and "starts with the mover's name" in e["error"] and len(items()) == n3 + 1, (st, e))
st, e = io_(marker="test_trim:nobuild3", project="projects/nobuild", mover="x", step="x: y", description=[f"- line {i}" for i in range(7)])
check("…its one more line leaves one fewer for the caller: seven lines are refused, never cut", st == 400 and "lists no background agent" in e["error"] and len(items()) == n3 + 1, (st, e))
close(fo["item"])

# a sub-page with a map of its own that lists front agents only, under a hub that lists a builder, is not front-only (anchors.front_only: the hub has a builder), so it has no fallback: the route reads the
# mover from the sub-page's own background agents, finds none and refuses, as it does for a sub-page with no map of its own under that hub. Nothing is filed.
n_sub = len(items())
for who in ("home-sparrow-builder", "home-sparrow-side"):
    st, e = io_(marker="test_trim:side", project="projects/alpha/side", mover=who, step=f"{who}: deep-scan the suites")
    check(f"a sub-page of front agents under a hub with a builder is no front-only project: mover {who!r} is refused, the page lists none, nothing filed", st == 400 and "not a background agent listed on projects/alpha/side" in e["error"]
          and e["error"].endswith("the page lists none") and "fallback" not in e and len(items()) == n_sub, (st, e))
n3 = len(items())
st, ok_ = io_(mover="home-sparrow-builder")
check("a project that lists a background agent is unchanged: the named agent is the mover, needs name it, fallback false", st == 200 and ok_["mover"] == "home-sparrow-builder" and ok_["fallback"] is False
      and [sr._session_label(x) for x in item(ok_["item"])["metadata"].get("needs") or []] == ["home-sparrow-builder"] and "item_open_fallback" not in item(ok_["item"])["metadata"], (st, ok_))
close(ok_["item"]); n3 = len(items())
st, o = io_(marker="test_trim:notes", mover="home-sparrow-notes", step="home-sparrow-notes: deep-scan the suites")
check("any background agent of the page is taken (not only the builder)", st == 200 and o["mover"] == "home-sparrow-notes" and sr._session_label(item(o["item"])["metadata"]["mover"]) == "home-sparrow-notes", (st, o))
close(o["item"])

# ---- 5. bad bullets: refused, never cut, nothing filed
n4 = len(items())
max_lines, line_max = _fg._description_limits()
ok_lines = ["- a fact"] * (max_lines - 1)
st, o = io_(marker="test_trim:max", description=ok_lines)
check(f"{max_lines - 1} lines (the most that leaves room for the attribution line) are taken, the description has {max_lines} lines", st == 200 and len(item(o["item"])["description"].splitlines()) == max_lines, (st, o))
close(o["item"]) if st == 200 else None
n4 = len(items())
for name, desc, needle in (("too many lines", ["- a fact"] * max_lines, "lines"), ("one line over the limit", ["- " + "x" * line_max], "line 1"), ("the second line over the limit", ["- ok", "y" * (line_max - 1)], "line 2"),
                           ("no lines", [], "no line of words"), ("only markers", ["-", "*", "  "], "no line of words"), ("a control character", ["- a\x01b"], "control character"),
                           ("a wrong type", {"a": 1}, "bullets"), ("a list with a number", ["- ok", 3], "list of text lines"), ("no description at all", None, "no line of words"), ("prose of one long sentence", ["z" * 400], "line 1")):
    st, e = io_(marker="test_trim:bad", description=desc)
    check(f"bad bullets, {name}: 400 and the reason, nothing filed", st == 400 and needle in e["error"] and len(items()) == n4, (st, e))
st, o = io_(marker="test_trim:exact", description=["- " + "x" * (line_max - 2)])
check(f"a line of exactly {line_max} characters as a bullet is taken", st == 200, (st, o)); close(o["item"]) if st == 200 else None
st, o = io_(marker="test_trim:one", description="- one text\n- of two lines")
check("a text of lines is taken as bullets as a list is", st == 200 and item(o["item"])["description"].splitlines()[:2] == ["- one text", "- of two lines"], (st, o)); close(o["item"]) if st == 200 else None
st, o = io_(marker="test_trim:at", description=["- ask @octocat or mail me@example.org"], sender="at-script")
oi = item(o["item"]) if st == 200 else {"description": "@x", "filed_by": "@x"}
check("an @name in a bullet is broken (no bare @ before a word), the text otherwise kept", st == 200 and not bare_at(oi["description"]) and "octocat" in oi["description"], (st, oi["description"])); close(o["item"]) if st == 200 else None

# ---- 6. missing or malformed fields: nothing filed
n5 = len(items())
for name, kw, needle in (("no marker", dict(marker=""), "marker is required"), ("a marker with no kind", dict(marker="alpha"), "marker ="), ("a marker with a space", dict(marker="test_trim:a b"), "marker ="),
                         ("a marker in capitals", dict(marker="Test:alpha"), "marker ="), ("a marker with markup", dict(marker="test_trim:<b>"), "marker ="), ("a marker with a mention", dict(marker="a:@b"), "marker ="),
                         ("a marker of 41 kind characters", dict(marker="k" * 41 + ":x"), "marker ="), ("a marker of 81 characters after the colon", dict(marker="k:" + "x" * 81), "marker ="),
                         ("no project", dict(project=""), "project is required"), ("no subject", dict(subject=""), "subject is required"), ("no step", dict(step=""), "step is required"), ("no mover", dict(mover=""), "mover is required"),
                         ("a step that does not name the mover", dict(step="deep-scan the suites"), "starts with the mover"), ("a step that names another agent", dict(step="home-sparrow-notes: deep-scan"), "starts with the mover"),
                         ("a step with only the name", dict(step="home-sparrow-builder: "), "starts with the mover"), ("a step with a line break", dict(step="home-sparrow-builder: a\nb"), "one line"),
                         ("a subject with a line break", dict(subject="a\nb"), "one line"), ("a sender with a space", dict(sender="a b"), "sender ="), ("a sender with markup", dict(sender="<i>x</i>"), "sender ="),
                         ("a sender with a mention", dict(sender="@octocat"), "sender ="), ("a sender of 61 characters", dict(sender="s" * 61), "sender ="), ("the owner as the sender", dict(sender="Oliver"), "Only the board writes as"),
                         ("a marker that is not text", dict(marker=7), "marker is text")):
    st, e = io_(**kw)
    check(f"{name}: 400 and the reason, nothing filed", st == 400 and needle in e["error"] and len(items()) == n5, (st, e))
for key, val in (("needs", ["decision"]), ("owner", "Oliver"), ("priority", "p0"), ("ask", "Decide: x"), ("until", "2030-01-01"), ("then", "Oliver"), ("project_key", "x")):
    st, e = io_(**{key: val})
    check(f"a key the route does not take ({key}): 400 that names it, nothing filed", st == 400 and key in e["error"] and "takes" in e["error"] and len(items()) == n5, (st, e))
st, o = io_(marker="test_trim:nosender", sender=None)
check("no sender: taken as client.py, recorded as the writer", st == 200 and item(o["item"])["filed_by"] == "client.py (a script on a client machine)" and "- Opened by client.py (a script on a client machine)" in item(o["item"])["description"], (st, o)); close(o["item"]) if st == 200 else None
st, o = io_(marker="test_trim:prefix", subject="[work] Wrong prefix")
check("a prefix the caller wrote is replaced by the project scope's own", st == 200 and item(o["item"])["subject"] == "[home] Wrong prefix", (st, o)); close(o["item"]) if st == 200 else None
st, o = io_(marker="test_trim:twice", subject="[work] [home] twice")
check("every prefix the caller wrote is taken off and the scope's goes on once", st == 200 and item(o["item"])["subject"] == "[home] twice", (st, o)); close(o["item"]) if st == 200 else None
st, o = io_(marker="test_trim:nospace", subject="[work][home] z")
check("prefixes written with no space between them are all taken off, the scope's goes on once", st == 200 and item(o["item"])["subject"] == "[home] z", (st, o)); close(o["item"]) if st == 200 else None
for i_, (subj, want, why) in enumerate((("[work]z", "[home] [work]z", "a bracket word with text glued to it is part of the subject, not a prefix"), ("[home]-style fix", "[home] [home]-style fix", "a bracket word followed by a hyphen keeps its word"),
                                        ("[work][home]-style fix", "[home] [home]-style fix", "prefixes in a row come off, the bracket word glued to text after them stays"))):
    st, o = io_(marker=f"test_trim:glued{i_}", subject=subj)
    check(f"{why}: {subj!r}", st == 200 and item(o["item"])["subject"] == want, (st, o)); close(o["item"]) if st == 200 else None
st, o = io_(marker="test_trim:inner", subject="Fix [work] things")
check("a prefix inside the subject, not at its start, is left alone", st == 200 and item(o["item"])["subject"] == "[home] Fix [work] things", (st, o)); close(o["item"]) if st == 200 else None
for name, subj in (("only an instance prefix", "[work] "), ("only an instance prefix, no space", "[work]"), ("only two prefixes", "[work] [home] "), ("only prefixes with no space between", "[work][home]"),
                   ("only a prefix and spaces", "   [home]   ")):
    n5b = len(items())
    st, e = io_(marker="test_trim:onlyprefix", subject=subj)
    check(f"a subject that is {name}: 400 that says so, nothing filed", st == 400 and "only an instance prefix" in e["error"] and open_for("test_trim:onlyprefix") == [] and len(items()) == n5b, (st, e))
st, o = io_(marker="test_trim:s60", sender="s" * 60, description=["- a fact"])
oi = item(o["item"]) if st == 200 else {"description": ""}
check("a sender of exactly 60 characters is taken and its attribution line is whole (not clipped by the line limit)", st == 200 and oi["description"].splitlines()[-1] == "- Opened by " + "s" * 60 + " (a script on a client machine)"
      and "…" not in oi["description"], (st, oi["description"])); close(o["item"]) if st == 200 else None
st, e = _rt_client._client_post(me, "no-such-write", {})
check("the 404 for an unknown write lists item-open", st == 404 and "item-open" in e["error"] and "job-gap" in e["error"], (st, e))
st, o = io_(marker="test_trim:longsubj", subject="x" * 90)
check("a subject over the limit is refused by the create tool's own gate, nothing filed", st == 400 and "Refused" in o["error"] and open_for("test_trim:longsubj") == [], (st, o))
st, o = io_(marker="test_trim:alarm", description=["- the token is exposed and the box was killed"])
check("a bullet with everyday-alarming words is kept as written (the create tool's description gate has no wording guard)", st == 200 and "- the token is exposed and the box was killed" in item(o["item"])["description"], (st, o))
if st == 200: close(o["item"])

# ---- 7. the project: unknown, ambiguous, no front agent
n6 = len(items())
st, e = io_(project="projects/ghost")
check("an unknown project: 404, nothing filed", st == 404 and "no project" in e["error"] and len(items()) == n6, (st, e))
st, e = io_(project="projects/gamma", mover="x", step="x: y")
check("a project page with no agents is front-only, and has no front agent to hold the item either: 409, nothing filed", st == 409 and "front agent" in e["error"] and len(items()) == n6, (st, e))
page("projects/solo.md", "type: project\ntitle: Solo\ndisplay-name: home-solo\nagents:\n  background:\n    home-solo-builder: builds\nstatus: active")
os.utime(T / "brain/projects/solo.md", (time.time() - 8 * 3600, time.time() - 8 * 3600)); p.cmd_registry(quiet=True)
st, e = io_(project="projects/solo", mover="home-solo-builder", step="home-solo-builder: deep-scan")
check("a project with a background agent and no front agent: 409, nothing filed", st == 409 and "front agent" in e["error"] and len(items()) == n6 and open_for("test_trim:alpha") == [], (st, e))
st, o = io_(project="alpha", marker="test_trim:slug")
check("a bare slug names the project", st == 200 and o["project"] == "projects/alpha", (st, o)); close(o["item"]) if st == 200 else None

# ---- 7b. a marker belongs to its project
nb0 = len(items())
st, a = io_(marker="size:report")
st2, b = io_(marker="size:report", project="projects/beta", mover="home-beta-builder", step="home-beta-builder: deep-scan the beta suites", subject="Deep-scan the beta suites")
check("the same marker on a second project files that project's own item (not the first project's, and nothing of it is shown)", st == 200 and st2 == 200 and b["item"] != a["item"] and b["repeat"] is False and b["project"] == "projects/beta"
      and b["mover"] == "home-beta-builder" and b["owner"] == "home-beta-main" and len(items()) == nb0 + 2 and item(b["item"])["metadata"]["project"] == "projects/beta", (st, a, st2, b))
st3, a2 = io_(marker="size:report"); st4, b2 = io_(marker="size:report", project="projects/beta", mover="home-beta-builder", step="home-beta-builder: deep-scan", subject="x")
check("…a repeat on each project dedupes on its own: each answers its own open item and nothing is filed", st3 == 200 and st4 == 200 and a2["item"] == a["item"] and a2["repeat"] and b2["item"] == b["item"] and b2["repeat"] and b2["project"] == "projects/beta" and len(items()) == nb0 + 2, (a2, b2))
check("…the store lookup is per project", [m_ for _g, m_ in item_open_svc._itemopen_open_items("projects/beta")] == ["size:report"] and [m_ for _g, m_ in item_open_svc._itemopen_open_items("projects/nobuild")] == [], item_open_svc._itemopen_open_items("projects/beta"))
close(a["item"]); st5, a3 = io_(marker="size:report")
check("…closing one project's item leaves the other's open: the first project files a new item, the second still answers its own", st5 == 200 and a3["item"] != a["item"] and a3["repeat"] is False and item(b["item"])["status"] == "open"
      and io_(marker="size:report", project="projects/beta", mover="home-beta-builder", step="home-beta-builder: deep-scan", subject="x")[1]["item"] == b["item"], (st5, a3))
close(a3["item"]); close(b["item"])

# ---- 7c. a cap of 10 open items per project
CAP = item_open_svc._ITEMOPEN_OPEN_MAX
cp = dict(project="projects/capped", mover="home-capped-builder", step="home-capped-builder: deep-scan", subject="Deep-scan")
check("the cap is 10", CAP == 10, CAP)
ids = []
for i in range(CAP):
    st, o = io_(marker=f"size:run{i}", **cp); ids.append(o.get("item") if st == 200 else None)
check("ten different markers file ten open items on one project", all(ids) and len({*ids}) == CAP and len(item_open_svc._itemopen_open_items("projects/capped")) == CAP, ids)
nc = len(items()); settle(); pushed.clear()     # the ten creates' notices first: a late one is not the refused call's
st, e = io_(marker="size:run-new", **cp)
check("an eleventh marker is refused: 400 that names the cap and says an open item must close first; nothing filed, no one told", st == 400 and "cap is 10" in e["error"] and "must close" in e["error"] and len(items()) == nc, (st, e)); settle()
check("…nobody was told of the refused call", pushed == [], pushed)
st, o = io_(marker="size:run3", **cp)
check("…a repeat of an open marker at the cap is still answered (never counted as new)", st == 200 and o["item"] == ids[3] and o["repeat"] is True and len(items()) == nc, (st, o))
st, o = io_(marker="size:report", project="projects/beta", mover="home-beta-builder", step="home-beta-builder: deep-scan", subject="x")
check("…the cap is per project: another project still files", st == 200 and o["repeat"] is False, (st, o)); close(o["item"]) if st == 200 else None
close(ids[0])
check("…closed items do not count", len(item_open_svc._itemopen_open_items("projects/capped")) == CAP - 1, len(item_open_svc._itemopen_open_items("projects/capped")))
st, o = io_(marker="size:run-new", **cp)
check("…after one item closes, a new marker files again, and the cap holds again", st == 200 and o["repeat"] is False and io_(marker="size:run-next", **cp)[0] == 400, (st, o))
for g in ids[1:] + ([o["item"]] if st == 200 else []): close(g)
check("…everything closed, the project is empty again", item_open_svc._itemopen_open_items("projects/capped") == [], item_open_svc._itemopen_open_items("projects/capped"))

# ---- 8. concurrency: one marker, many calls, one item
n7 = len(items()); res = []
ths = [threading.Thread(target=lambda: res.append(io_(marker="test_trim:race"))) for _ in range(8)]
[t.start() for t in ths]; [t.join() for t in ths]
check("eight threads calling with one marker at once file one item and all get its id", len(items()) == n7 + 1 and len({r[1]["item"] for r in res}) == 1 and all(r[0] == 200 for r in res) and sum(1 for r in res if not r[1]["repeat"]) == 1, res[:3])
close(res[0][1]["item"]); settle()

# ---- 8b. item-sync: a script keeps one item for the person in step with a condition (open, refresh, close by its marker)
def isy(action, marker="plugin_sync:alpha", **kw):
    b = {"action": action, "marker": marker}
    if action == "open":
        b.update(project="projects/alpha", subject="Press Sync on the plugin page", mover="Oliver", then="home-sparrow-builder", step="open the plugin page and press Sync",
                 description=["- The plugin is 2 versions behind", "- Pressing Sync brings it up to date"], sender="demo-timer")
    elif action == "refresh":
        b.update(description=["- The plugin is 3 versions behind"], sender="demo-timer")
    b.update(kw)
    return _rt_client._client_post(me, "item-sync", {k: v for k, v in b.items() if v is not None})
def sync_open(marker="plugin_sync:alpha"):
    out = []
    for g, p_ in _item_files_():
        try:
            if '"item_sync"' not in p_.read_text(encoding="utf-8"): continue
            it_ = _service_store._load(g)
        except (OSError, ValueError): continue
        if it_.get("status") == "open" and it_["metadata"].get("item_sync") == marker: out.append(g)
    return out
from stackshot.core.store import _item_files as _item_files_
from stackshot.model import steps as _steps_mod
def shape(gid):
    """what refresh must leave alone: everything of the item but its description"""
    i_ = item(gid); m_ = i_["metadata"]
    return {"subject": i_["subject"], "status": i_["status"], "mover": m_.get("mover"), "then": m_.get("then"), "step": m_.get("step"), "state": m_.get("state"), "next": m_.get("next"), "needs": m_.get("needs"),
            "steps": [(x["text"], x["status"]) for x in _steps_mod.view(m_)], "project": m_.get("project"), "owner": m_.get("owner"), "item_sync": m_.get("item_sync"), "filed_by": i_.get("filed_by")}

ns0 = len(items()); settle(); pushed.clear(); owed0 = json.dumps(_pdebts._owed_load(), sort_keys=True)
st, so = isy("open")
check("item-sync open: 200, opened, the item as shown, the project, the person as mover, the agent as then, the project's -main agent as creator, repeat false", st == 200 and so["action"] == "opened" and so["marker"] == "plugin_sync:alpha"
      and so["project"] == "projects/alpha" and so["mover"] == "Oliver" and so["then"] == "home-sparrow-builder" and so["owner"] == "home-sparrow-main" and so["repeat"] is False and len(items()) == ns0 + 1
      and so["item"] == _gh.shown(_model_ids._norm_id(so["item"])), (st, so))
sit = item(so["item"]); sm = sit["metadata"]
check("…the item is open, marked item_sync, filed under the project, with the subject under the scope's prefix", sit["status"] == "open" and sm["item_sync"] == "plugin_sync:alpha" and sm["project"] == "projects/alpha"
      and sit["subject"] == "[home] Press Sync on the plugin page", (sit["status"], sm, sit["subject"]))
check("…the mover is the person and the then is the agent; the state is your-step with his step", sm.get("mover") == "Oliver" and sr._session_label(sm.get("then")) == "home-sparrow-builder" and sm.get("state") == "your-step"
      and sm.get("step") == "open the plugin page and press Sync" and M.derive(sit).mover == "Oliver", (sm, M.derive(sit).mover))
check("…his step is the only step, open, and it opens with his name (the caller's words are not doubled)", [(x["text"], x["status"]) for x in _steps_mod.view(sm)] == [("Oliver: open the plugin page and press Sync", "open")], _steps_mod.view(sm))
check("…the description is the caller's bullets, then who opened it, and the script is recorded as the writer; no host name anywhere", sit["description"].splitlines() == ["- The plugin is 2 versions behind", "- Pressing Sync brings it up to date",
      "- Opened by demo-timer (a script on a client machine)"] and sit["filed_by"] == "demo-timer (a script on a client machine)" and me not in json.dumps(sit) and me not in json.dumps(so), sit)
settle()
check("…the row tells no one and owes no page (the debts are as they were before it)", pushed == [] and json.dumps(_pdebts._owed_load(), sort_keys=True) == owed0, (pushed, _pdebts._owed_load()))
sgid = so["item"]; shape0 = shape(sgid)

# a second open of a marker whose item is open is a refresh: no duplicate, only the description changes
st, so2 = isy("open", subject="Another subject", then="home-sparrow-notes", description=["- Now 4 versions behind"])
settle()
check("a second open with the same marker: 200, the same item, refreshed, repeat true, nothing filed, no one told", st == 200 and so2["item"] == sgid and so2["action"] == "refreshed" and so2["repeat"] is True and len(items()) == ns0 + 1 and pushed == [], (st, so2, pushed))
check("…only the description changed: the subject, step, mover, then and checklist are as they were", item(sgid)["description"].splitlines() == ["- Now 4 versions behind", "- Opened by demo-timer (a script on a client machine)"] and shape(sgid) == shape0, (item(sgid)["description"], shape(sgid), shape0))
st, e = isy("open", project="projects/beta", then="home-beta-main")
check("…the marker open on another project is refused, naming the project it is open on; nothing changed", st == 400 and "already open on projects/alpha" in e["error"] and shape(sgid) == shape0 and len(items()) == ns0 + 1, (st, e))

# refresh: the description alone
st, rf = isy("refresh")
check("refresh: 200, refreshed, the same item, nothing filed", st == 200 and rf["action"] == "refreshed" and rf["item"] == sgid and len(items()) == ns0 + 1, (st, rf))
check("…the description is the new bullets and the attribution; everything else of the item is as it was", item(sgid)["description"].splitlines() == ["- The plugin is 3 versions behind", "- Opened by demo-timer (a script on a client machine)"] and shape(sgid) == shape0, (item(sgid)["description"], shape(sgid)))
st, e = isy("refresh", description=["- " + "x" * 200])
check("…a misshaped description is refused with the board's text (a line over the limit), the item unchanged", st == 400 and "line 1" in e["error"] and item(sgid)["description"].splitlines()[0] == "- The plugin is 3 versions behind", (st, e))
st, e = isy("refresh", description=[f"- fact {i}" for i in range(9)])
check("…too many lines are refused, never cut", st == 400 and "lines" in e["error"] and item(sgid)["description"].splitlines()[0] == "- The plugin is 3 versions behind", (st, e))
st, e = isy("refresh", description=None)
check("…no description is refused", st == 400 and "no line of words" in e["error"], (st, e))
st, e = isy("refresh", step="a new step")
check("…refresh takes no step (nor project, subject, mover or then): refused and named", st == 400 and "step" in e["error"] and "does not take" in e["error"] and shape(sgid) == shape0, (st, e))
st, e = isy("refresh", marker="plugin_sync:none-open")
check("refresh with no open item for the marker: 200, a no-op that says so, no item, nothing filed or changed", st == 200 and e["action"] == "none" and e["item"] == "" and "no open item" in e["note"] and len(items()) == ns0 + 1 and shape(sgid) == shape0, (st, e))

# an item the route did not open is out of its reach: refresh and close find an item by the mark this route puts on it, and no other
st, other = io_(marker="plugin_sync:other")
before_o = (item(other["item"])["description"], item(other["item"])["status"], item(other["item"])["metadata"].get("next"))
st1, r1 = isy("refresh", marker="plugin_sync:other", description=["- overwritten"]); st2, c1 = isy("close", marker="plugin_sync:other")
check("the route cannot refresh or close an item it did not open: an item-open item under the same marker text is found by neither (both are no-ops) and is as it was", st1 == 200 and st2 == 200 and r1["action"] == "none" and c1["action"] == "none"
      and (item(other["item"])["description"], item(other["item"])["status"], item(other["item"])["metadata"].get("next")) == before_o, (r1, c1))
st5, o5_ = isy("open", marker="plugin_sync:other")
check("…and an open for that marker files its own item beside it, leaving the item-open item alone", st5 == 200 and o5_["action"] == "opened" and o5_["item"] != other["item"] and item(other["item"])["status"] == "open", (st5, o5_))
isy("close", marker="plugin_sync:other"); close(other["item"])
check("…the item-open item's marker is not the route's: no open item of the route is found for a marker only item-open used", sync_open("plugin_sync:never") == [] and isy("close", marker="plugin_sync:never")[1]["action"] == "none")

# close: done, with outcome, reason and outcome text; his step ticked; the reason says the script saw the condition gone
st, cl = isy("close")
cit = item(sgid); cm = cit["metadata"]
check("close: 200, closed, the same item", st == 200 and cl["action"] == "closed" and cl["item"] == sgid and cl["repeat"] is False, (st, cl))
check("…the item is completed as done, with the reason that says the script saw the condition gone, and the end state in outcome_text", cit["status"] == "completed" and cm.get("outcome") == "done"
      and "the script saw the condition (plugin_sync:alpha) is gone" in str(cm.get("reason") or cit.get("reason") or ""), (cit["status"], {k: cm.get(k) for k in ("outcome", "reason", "outcome_text")}, cit.get("reason")))
check("…his open step is ticked by the close (done, not left open), and no step stays open", [(x["text"], x["status"]) for x in _steps_mod.view(cm, closed=True)] == [("Oliver: open the plugin page and press Sync", "done")]
      and not [x for x in _steps_mod.view(cm, closed=True) if x["status"] == "open"], _steps_mod.view(cm, closed=True))
check("…the description is unchanged by the close", cit["description"].splitlines()[0] == "- The plugin is 3 versions behind", cit["description"])
check("…and the marker has no open item", sync_open() == [], sync_open())
n_cl = len(items())
st, cl2 = isy("close")
check("close with no open item: 200, a no-op that says so, nothing filed, the closed item unchanged", st == 200 and cl2["action"] == "none" and cl2["item"] == "" and "no open item" in cl2["note"] and len(items()) == n_cl and item(sgid)["status"] == "completed", (st, cl2))

# reopen after a close: the sync recurs, a new item
st, so3 = isy("open")
check("an open after the close files a new item (the sync recurs): a new id, opened, repeat false, the old one stays closed", st == 200 and so3["action"] == "opened" and so3["item"] != sgid and so3["repeat"] is False and item(sgid)["status"] == "completed"
      and item(so3["item"])["status"] == "open" and len(items()) == n_cl + 1, (st, so3))
st, cl4 = isy("close", reason="the plugin is in sync again")
check("a close with the caller's reason: the reason is stored as given", st == 200 and cl4["action"] == "closed" and item(so3["item"])["metadata"].get("reason", item(so3["item"]).get("reason")) == "the plugin is in sync again", (st, cl4, item(so3["item"])))

# misshaped input is refused with the board's text, nothing filed
ns1 = len(items())
for name, kw, needle in (("no marker", dict(marker=""), "marker is required"), ("a marker with no kind", dict(marker="alpha"), "marker ="), ("a marker with a space", dict(marker="a:b c"), "marker ="), ("a marker that is not text", dict(marker=7), "marker is text"),
                         ("no project", dict(project=""), "project is required"), ("no subject", dict(subject=""), "subject is required"),
                         ("no step", dict(step=""), "step is required"), ("no mover", dict(mover=""), "mover is required"), ("no then", dict(then=""), "then is required"),
                         ("a mover that is an agent", dict(mover="home-sparrow-builder"), "mover is Oliver"), ("a then that is not listed", dict(then="no-such-agent"), "not an agent listed"),
                         ("a then of another project", dict(then="heron-engineer"), "not an agent listed"), ("a step with a line break", dict(step="a\nb"), "one line"), ("a step that is only his name", dict(step="Oliver: "), "step is empty"),
                         ("a subject with a line break", dict(subject="a\nb"), "one line"), ("a subject that is only a prefix", dict(subject="[work] "), "only an instance prefix"),
                         ("a sender with a space", dict(sender="a b"), "sender ="), ("a sender that is the person", dict(sender="Oliver"), "Only the board writes as"),
                         ("a description of too many lines", dict(description=[f"- fact {i}" for i in range(9)]), "lines"), ("a description line over the limit", dict(description=["- " + "x" * 200]), "line 1"),
                         ("no description", dict(description=None), "no line of words"), ("a description with a control character", dict(description=["- a\x01b"]), "control character")):
    st, e = isy("open", marker=kw.pop("marker", "plugin_sync:bad"), **kw)
    check(f"item-sync open, {name}: 400 and the reason, nothing filed", st == 400 and needle in e["error"] and len(items()) == ns1 and sync_open("plugin_sync:bad") == [], (st, e))
st, e = _rt_client._client_post(me, "item-sync", {"action": "drop", "marker": "plugin_sync:bad"})
check("item-sync: an unknown action is refused naming the three", st == 400 and "action = open | refresh | close" in e["error"] and len(items()) == ns1, (st, e))
for key, val in (("needs", ["decision"]), ("owner", "Oliver"), ("priority", "p0"), ("ask", "Decide: x"), ("until", "2030-01-01"), ("project_key", "x")):
    st, e = isy("open", marker="plugin_sync:bad", **{key: val})
    check(f"item-sync: a key the route does not take ({key}): 400 that names it, nothing filed", st == 400 and key in e["error"] and "takes" in e["error"] and len(items()) == ns1, (st, e))
st, e = isy("close", step="x")
check("item-sync close takes no step: refused and named", st == 400 and "does not take" in e["error"], (st, e))
st, e = isy("open", marker="plugin_sync:ghost", project="projects/ghost")
check("an unknown project: 404, nothing filed", st == 404 and "no project" in e["error"] and len(items()) == ns1, (st, e))
st, e = isy("open", marker="plugin_sync:gamma", project="projects/gamma")
check("a project with no front agent to keep the item: 409, nothing filed", st == 409 and "front agent" in e["error"] and len(items()) == ns1, (st, e))
st, e = isy("open", marker="plugin_sync:longsubj", subject="x" * 90)
check("a subject over the limit is refused by the create tool's own gate, nothing filed", st == 400 and "Refused" in e["error"] and sync_open("plugin_sync:longsubj") == [] and len(items()) == ns1, (st, e))
st, e = isy("open", marker="plugin_sync:longstep", step="y" * 400)
check("a step over the limit is refused with the limit named and nothing is left half made: no open item, nothing filed", st == 400 and "limit is 200" in e["error"] and sync_open("plugin_sync:longstep") == [] and len(items()) == ns1, (st, e))
st, o_ = isy("open", marker="plugin_sync:front", then="home-sparrow-main")
check("a front agent is taken as then as a background agent is", st == 200 and sr._session_label(item(o_["item"])["metadata"]["then"]) == "home-sparrow-main", (st, o_)); isy("close", marker="plugin_sync:front")
st, o_ = isy("open", marker="plugin_sync:namestep", step="Oliver: press Sync")
check("a step that already opens with his name is not doubled", st == 200 and [x["text"] for x in _steps_mod.view(item(o_["item"])["metadata"])] == ["Oliver: press Sync"], (st, o_)); isy("close", marker="plugin_sync:namestep")
st, o_ = isy("open", marker="plugin_sync:slug", project="alpha", sender=None)
check("a bare slug names the project; no sender is client.py", st == 200 and o_["project"] == "projects/alpha" and "- Opened by client.py (a script on a client machine)" in item(o_["item"])["description"], (st, o_)); isy("close", marker="plugin_sync:slug")
st, o_ = isy("open", marker="plugin_sync:at", description=["- ask @octocat"])
check("an @name in a bullet is broken, no bare @ before a word", st == 200 and not bare_at(item(o_["item"])["description"]) and "octocat" in item(o_["item"])["description"], (st, o_)); isy("close", marker="plugin_sync:at")
st, o_ = isy("open", marker="plugin_sync:prefix", subject="[work] [home] Wrong prefix")
check("a prefix the caller wrote is replaced by the project scope's own", st == 200 and item(o_["item"])["subject"] == "[home] Wrong prefix", (st, o_)); isy("close", marker="plugin_sync:prefix")

# a cap of 10 open items per project, refreshes and repeats never counted
ids_ = []
for i in range(10):
    st, o_ = isy("open", marker=f"plugin_sync:run{i}"); ids_.append(o_.get("item") if st == 200 else None)
nc2 = len(items())
st, e = isy("open", marker="plugin_sync:run-new")
check("ten markers file ten open items on one project; an eleventh is refused, naming the cap, nothing filed", all(ids_) and len({*ids_}) == 10 and st == 400 and "cap is 10" in e["error"] and len(items()) == nc2, (ids_, st, e))
st, o_ = isy("open", marker="plugin_sync:run4")
check("…a repeat of an open marker at the cap is still answered (a refresh)", st == 200 and o_["item"] == ids_[4] and o_["action"] == "refreshed" and len(items()) == nc2, (st, o_))
st, o_ = isy("open", marker="plugin_sync:run-b", project="projects/beta", then="home-beta-main")
check("…the cap is per project: another project still files", st == 200 and o_["action"] == "opened", (st, o_)); isy("close", marker="plugin_sync:run-b")
isy("close", marker="plugin_sync:run0")
st, o_ = isy("open", marker="plugin_sync:run-new")
check("…after one item closes a new marker files again", st == 200 and o_["action"] == "opened", (st, o_))
for m_ in [f"plugin_sync:run{i}" for i in range(1, 10)] + ["plugin_sync:run-new"]: isy("close", marker=m_)
check("…everything closed, no open item of the route remains", [g for g in sync_open("plugin_sync:run1")] == [] and not [1 for g, p_ in _item_files_() if '"item_sync"' in p_.read_text(encoding="utf-8") and item(g)["status"] == "open"], None)

# eight threads, one marker, one item
n8 = len(items()); res = []
ths = [threading.Thread(target=lambda: res.append(isy("open", marker="plugin_sync:race"))) for _ in range(8)]
[t.start() for t in ths]; [t.join() for t in ths]
check("item-sync: eight threads opening one marker at once file one item and all get its id", len(items()) == n8 + 1 and len({r[1]["item"] for r in res}) == 1 and all(r[0] == 200 for r in res) and sum(1 for r in res if r[1]["action"] == "opened") == 1, res[:3])
isy("close", marker="plugin_sync:race"); settle()

# ---- 8c. item-sync close and open against other writers, the lock, the rollback and the repair
from stackshot.service import answer as _answer_svc
from stackshot.service import item_sync as item_sync_svc
from stackshot.model import states as _states_mod
from stackshot.service import writes as _writes_s
from stackshot.model.field_gates import _close_reason_max
def steps_of(gid): return [(x["text"], x["status"]) for x in _steps_mod.view(item(gid)["metadata"])]
def add_step(gid, who, text): _update_svc._update(_model_ids._norm_id(gid), next=f"{who}: {text}", sender=who)
def mark(gid, who, text): _update_svc._update(_model_ids._norm_id(gid), done=[text], sender=who)

# a close never settles another writer's step: nothing is ticked, the item stays open, the answer says so in one line (the board lets only his answer tick his step, so a script leaves it be)
st, o8 = isy("open", marker="plugin_sync:others"); g8 = o8["item"]; pushed.clear()
add_step(g8, "home-sparrow-notes", "write the changelog"); add_step(g8, "home-sparrow-builder", "review the sync"); settle(); pushed.clear()
st, c8 = isy("close", marker="plugin_sync:others"); settle()
check("close with two other writers' open steps: 200, the item left open, the one plain line says so", st == 200 and c8["action"] == "left-open" and c8["item"] == g8 and c8["note"] == "left open: open steps of others remain", (st, c8))
check("…the item is still open and every step is as it was: his open, the two others' open, nothing ticked in anyone's name", item(g8)["status"] == "open" and sorted(steps_of(g8)) == sorted([("Oliver: open the plugin page and press Sync", "open"),
      ("home-sparrow-notes: write the changelog", "open"), ("home-sparrow-builder: review the sync", "open")]), steps_of(g8))
check("…nobody was told by the call", pushed == [], pushed)
st, c8b = isy("close", marker="plugin_sync:others")
check("…a second close says the same, writes nothing and leaves the checklist as it is", st == 200 and c8b["action"] == "left-open" and c8b["note"] == c8["note"] and item(g8)["status"] == "open" and len(steps_of(g8)) == 3, (st, c8b, steps_of(g8)))
st, r8 = isy("refresh", marker="plugin_sync:others")
check("…refresh still answers for the open item", st == 200 and r8["action"] == "refreshed", (st, r8))
mark(g8, "home-sparrow-notes", "home-sparrow-notes: write the changelog")
st, c8c = isy("close", marker="plugin_sync:others")
check("…while one other writer's step is open the item stays open", st == 200 and c8c["action"] == "left-open" and item(g8)["status"] == "open" and ("home-sparrow-builder: review the sync", "open") in steps_of(g8), (st, c8c, steps_of(g8)))
mark(g8, "home-sparrow-builder", "home-sparrow-builder: review the sync")
st, c8d = isy("close", marker="plugin_sync:others")
check("…when the others' steps are done the close completes the item as done", st == 200 and c8d["action"] == "closed" and item(g8)["status"] == "completed" and item(g8)["metadata"].get("outcome") == "done", (st, c8d))
check("…and no step is left open on the closed item", not [x for x in _steps_mod.view(item(g8)["metadata"], closed=True) if x["status"] == "open"], _steps_mod.view(item(g8)["metadata"], closed=True))

# he presses Done, the agent that takes the item adds a follow-up step: the next close leaves it alone
st, o9 = isy("open", marker="plugin_sync:handed"); g9 = o9["item"]
check("he answers Done: his step is done and the item goes on", _answer_svc._answer(_model_ids._norm_id(g9), "", "", "done") == "done" and ("Oliver: open the plugin page and press Sync", "done") in steps_of(g9), steps_of(g9))
add_step(g9, "home-sparrow-builder", "do the follow-up"); settle(); pushed.clear()
st, c9 = isy("close", marker="plugin_sync:handed"); settle()
check("a close after his Done, with the agent's follow-up step open: the item is left open, the follow-up stays open, the answer says so", st == 200 and c9["action"] == "left-open" and c9["note"] == "left open: open steps of others remain"
      and item(g9)["status"] == "open" and ("home-sparrow-builder: do the follow-up", "open") in steps_of(g9), (st, c9, steps_of(g9)))
check("…and the agent is not told by the call, nothing is completed over it", pushed == [] and item(g9)["status"] == "open", pushed)
mark(g9, "home-sparrow-builder", "home-sparrow-builder: do the follow-up")
st, c9b = isy("close", marker="plugin_sync:handed")
check("…once the follow-up is done the close completes the item", st == 200 and c9b["action"] == "closed" and item(g9)["status"] == "completed", (st, c9b))
st, o9b = isy("open", marker="plugin_sync:handed2"); g9b = o9b["item"]
_answer_svc._answer(_model_ids._norm_id(g9b), "", "", "done")
st, c9c = isy("close", marker="plugin_sync:handed2")
check("a close after his Done with no other step open completes the item as before", st == 200 and c9c["action"] == "closed" and item(g9b)["status"] == "completed", (st, c9c))

# a repeat open sets the step it sends only when it differs from the step the route last sent, and never beside a line of his that is not the route's own
def his_open(g): return [t for t, s_ in steps_of(g) if s_ == "open" and t.startswith("Oliver: ")]
def edit_meta(g, fn):
    p_ = _service_store._path(g); d_ = json.loads(p_.read_text(encoding="utf-8")); fn(d_["metadata"]); p_.write_text(json.dumps(d_), encoding="utf-8")
S1, S2, S3, S4 = "open the plugin page and press Sync", "press Sync on the plugin page again", "press Sync and check the version", "check the version number on the page"
def meta_of(g): return item(g)["metadata"]
def own(g): return meta_of(g).get("item_sync_step")
def sent(g): return meta_of(g).get("item_sync_sent")
RECORD = ("item_sync_step", "item_sync_sent")      # forgetting both makes an item as one filed before the records
def forget(g, *keys): edit_meta(g, lambda m_: [m_.pop(k_, None) for k_ in keys])
def opened(marker, **kw):
    st_, r_ = isy("open", marker=marker, **kw); settle()
    assert st_ == 200 and r_["action"] == "opened", (marker, st_, r_)
    return r_["item"]
def done(g): assert _answer_svc._answer(_model_ids._norm_id(g), "", "", "done") == "done", (g, meta_of(g)); settle()
def note(g, words): _answer_svc._answer(_model_ids._norm_id(g), "", words, "note"); settle()
def by_builder(g, **kw): _update_svc._update(_model_ids._norm_id(g), sender="home-sparrow-builder", **kw); settle()
def is_waiting(g): return M.shown_waiting(item(g))
def mine(*steps): return sorted("Oliver: " + s_ for s_ in steps)
runs = []
def untouched(name, g, marker, step):
    """a repeat open that writes the description and no step: everything else of the item is as it was, the route's record with it"""
    before, until_, own_ = shape(g), meta_of(g).get("until"), own(g); runs.append(1); fact = f"- run {len(runs)} saw it"
    st_, r_ = isy("open", marker=marker, step=step, description=[fact]); settle()
    check(name, st_ == 200 and r_["action"] == "refreshed" and shape(g) == before and meta_of(g).get("until") == until_ and own(g) == own_ and item(g)["description"].splitlines()[0] == fact, (st_, r_, before, shape(g), own_, own(g), item(g)["description"]))
def asks(name, g, marker, step, opens, record=True):
    """a repeat open that sets the step: his move again, `opens` the open steps of his after it, `record` whether the line it asks is the route's own; the step is recorded as sent"""
    st_, r_ = isy("open", marker=marker, step=step); settle()
    m_ = meta_of(g)
    check(name, st_ == 200 and r_["action"] == "refreshed" and sorted(his_open(g)) == mine(*opens) and m_.get("state") == "your-step" and m_.get("step") == step and m_.get("owner_step") == "Oliver: " + step and M.derive(item(g)).mover == "Oliver"
          and own(g) == (step if record else None) and sent(g) == step, (st_, r_, steps_of(g), m_.get("state"), m_.get("step"), m_.get("owner_step"), own(g), sent(g)))

settle(); pushed.clear()
gr = opened("plugin_sync:rules")
check("rules setup: the open files his step as the one open step, recorded as the route's own and as sent", steps_of(gr) == [("Oliver: " + S1, "open")] and own(gr) == S1 and sent(gr) == S1, (steps_of(gr), own(gr), sent(gr)))
pushed.clear()
asks("a new step on a repeat open is set: one open step of his, the new one, recorded; the item waits on him", gr, "plugin_sync:rules", S2, [S2])
check("...the route's old step is dropped, and nobody is told", ("Oliver: " + S1, "dropped") in steps_of(gr) and pushed == [], (steps_of(gr), pushed))
untouched("the step that stands open on him, sent again while the item asks it: left alone", gr, "plugin_sync:rules", S2)
untouched("...with his name on it, it is the same step: left alone", gr, "plugin_sync:rules", "Oliver: " + S2)
done(gr); pushed.clear()
check("setup: he answers Done: S2 is finished, no step of his is open, and the route's record went with its open line", his_open(gr) == [] and ("Oliver: " + S2, "done") in steps_of(gr) and own(gr) is None, (steps_of(gr), own(gr)))
untouched("the step he finished last, sent again: nothing is opened", gr, "plugin_sync:rules", S2)
asks("a step that differs from the finished one is set", gr, "plugin_sync:rules", S3, [S3])
done(gr)
asks("only the step finished last is compared: an older finished one is asked again", gr, "plugin_sync:rules", S2, [S2])
close(gr)

# he finished A, B is asked and unanswered: A again changes no step
g_ = opened("plugin_sync:unanswered"); done(g_)
asks("setup: B is set after he finished A", g_, "plugin_sync:unanswered", S2, [S2])
untouched("A, the step he finished last, sent while B is open and unanswered: no step changes, B stays", g_, "plugin_sync:unanswered", S1)
close(g_)

# a step a session wrote and he finished is his finished step as much as the route's
g_ = opened("plugin_sync:theirs")
by_builder(g_, step=S3)
check("setup: a session's step= takes the route's line over: one open step of his, and the route owns none", his_open(g_) == mine(S3) and own(g_) is None and sent(g_) == S1, (steps_of(g_), own(g_), sent(g_)))
done(g_)
untouched("a step a session wrote and he finished, sent by the route: not asked again", g_, "plugin_sync:theirs", S3)
edit_meta(g_, lambda m_: m_.__setitem__("steps", [*m_["steps"], {"text": "Oliver: " + S4, "status": "done", "by": "home-sparrow-builder", "at": time.time() + 60}]))
untouched("...nor after a line for him was ticked later by a session: only his own mark makes a step the one he finished last", g_, "plugin_sync:theirs", S3)
close(g_)
g_ = opened("plugin_sync:ticked")
by_builder(g_, next="Oliver: " + S3); by_builder(g_, done=["Oliver: " + S3])
check("setup: a session wrote a line for him and ticked it itself; the route's step is open", his_open(g_) == mine(S1) and any(s_["status"] == "done" and s_["by"] != "Oliver" for s_ in _steps_mod.view(meta_of(g_))), _steps_mod.view(meta_of(g_)))
asks("a step a session ticked is not one he finished: it is set", g_, "plugin_sync:ticked", S3, [S3])
close(g_)

# the step the route last sent is never asked again, whatever became of its line
def not_asked(tag, mk, change, still):
    """the route sends S1 again after a session's `change` of its line: nothing is written, the open steps of his stay `still`; then a newer step waits for any line of the session's to go"""
    g_ = opened(mk); change(g_); settle()
    check(f"setup ({tag}): the route's line is gone", "Oliver: " + S1 not in his_open(g_) and own(g_) is None and sent(g_) == S1 and sorted(his_open(g_)) == mine(*still), (meta_of(g_), steps_of(g_)))
    for n_ in (1, 2):
        untouched(f"after a session {tag} the route's step, the same text again asks nothing (run {n_})", g_, mk, S1)
    if still:
        untouched(f"after a session {tag} the route's step, a newer step is not put beside the session's", g_, mk, S2)
        check(f"...and is not recorded as sent ({tag})", sent(g_) == S1, sent(g_))
        done(g_)
        untouched(f"after his Done on the session's step ({tag}), the route's old text still asks nothing", g_, mk, S1)
    asks(f"after a session {tag} the route's step, a newer step is set once no line of the session's stands", g_, mk, S2, [S2])
    close(g_)

not_asked("replaced", "plugin_sync:replaced", lambda g: by_builder(g, step=S3), [S3])
not_asked("reworded", "plugin_sync:reworded", lambda g: _update_svc._update(_model_ids._norm_id(g), step=S4, sender="home-sparrow-main"), [S4])
not_asked("withdrew", "plugin_sync:withdrew", lambda g: by_builder(g, next="home-sparrow-builder: watch the sync", step="none"), [])

# crash repair: the create wrote his line and the route's own record, the state write never happened
def cut_short(g, *keys): forget(g, "state", "step", "owner_step", "item_sync_sent", *keys)
g4 = opened("plugin_sync:rule4"); cut_short(g4)
check("crash setup: his step open and recorded as the route's, never sent, no state", his_open(g4) == mine(S1) and not meta_of(g4).get("state") and own(g4) == S1 and sent(g4) is None, (steps_of(g4), meta_of(g4)))
asks("his open step on an item that does not ask him is made whole by a repeat open, and stays the route's", g4, "plugin_sync:rule4", S1, [S1])
asks("...so a newer step replaces it", g4, "plugin_sync:rule4", S2, [S2])
close(g4)
g_ = opened("plugin_sync:rule4new"); cut_short(g_)
asks("a filing cut short, sent a newer step first: the route's line is replaced", g_, "plugin_sync:rule4new", S2, [S2])
close(g_)
g_ = opened("plugin_sync:rule4beside"); by_builder(g_, next="Oliver: " + S3); cut_short(g_)      # the line first: an item with no state takes no line for him from a session
check("setup: a cut-short filing with a session's line beside the route's", sorted(his_open(g_)) == mine(S1, S3) and not meta_of(g_).get("state"), (steps_of(g_), meta_of(g_)))
untouched("...a newer step is not put beside the session's line, and the route's is not dropped", g_, "plugin_sync:rule4beside", S2)
asks("...the route's own line sent again makes the item ask it", g_, "plugin_sync:rule4beside", S1, [S1, S3])
close(g_)

# the record is the step as sent, compared as the board stores it, however it is spelled
for i_, (tag, spelled) in enumerate((("his name on it", "Oliver: " + S1), ("his name on it twice, spaced", "Oliver:  Oliver:   " + S1))):
    mk = f"plugin_sync:spelled{i_}"; g_ = opened(mk)
    edit_meta(g_, lambda m_: m_.__setitem__("item_sync_step", spelled))
    asks(f"a record spelled otherwise ({tag}) still names the route's line: it is replaced", g_, mk, S2, [S2])
    close(g_)
bold = f"**{S1}**"
g_ = opened("plugin_sync:bold")
edit_meta(g_, lambda m_: m_.__setitem__("item_sync_step", bold))
st_, r_ = isy("refresh", marker="plugin_sync:bold", description=["- the check ran again"]); settle()
check("a save keeps a record that reads as the open line, however it is spelled", st_ == 200 and r_["action"] == "refreshed" and own(g_) == bold, (st_, r_, own(g_)))
asks("...so a newer step still replaces the route's line", g_, "plugin_sync:bold", S2, [S2])
close(g_)

# the record goes with the write that asks a session's line, also when another line still reads as the route's old step
g_ = opened("plugin_sync:twice")
by_builder(g_, next=f"Oliver: {S1}\nOliver: {bold}\nOliver: {S3}")
check("setup: the route's line, a session's line that reads the same, and a session's other step", len(his_open(g_)) == 3 and own(g_) == S1, (steps_of(g_), own(g_)))
st_, r_ = isy("open", marker="plugin_sync:twice", step=S3); settle()
check("a step standing as a session's line replaces the route's own: the record is gone, the session's lines are open", st_ == 200 and own(g_) is None and sent(g_) == S3 and sorted(his_open(g_)) == sorted([f"Oliver: {bold}", "Oliver: " + S3]), (st_, r_, steps_of(g_), own(g_), sent(g_)))
untouched("...so a later step is not put beside them", g_, "plugin_sync:twice", S2)
close(g_)

# a step that names an item by its id is the same line at the create, in the record and in every comparison; the board writes the id of an issue-numbered item otherwise than it is sent
from stackshot.github import ghsync as _ghsync
ref = opened("plugin_sync:referred"); ref_id = _model_ids._norm_id(ref); by_id = f"look at {ref_id} and press Sync"
letter_ = _ghsync.letter
_ghsync.letter = lambda: ref_id[0]       # the test's items count as issue-numbered for this case
try:
    written = _service_store._shown_ids(by_id)
    check("setup: the board writes the named item's id otherwise than it is sent", written != by_id, (by_id, written))
    g_ = opened("plugin_sync:byid", step=by_id)
    check("a first step naming an item by id: one open line as the board writes it, recorded as the route's", his_open(g_) == mine(written) and own(g_) == written, (steps_of(g_), own(g_)))
    untouched("...the same words again are the same step", g_, "plugin_sync:byid", by_id)
    asks("...and a newer step replaces it", g_, "plugin_sync:byid", S2, [S2])
    close(g_)
finally:
    _ghsync.letter = letter_
close(ref)

# a note of his that parks the item: nothing is written while it waits; the step the park dropped was sent, so only a newer one is asked after the wait
from stackshot.service import wakes as _wakes_svc
def wake_all():
    _wakes_svc.wake_pass(now=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=30)); settle()
for i_, words in enumerate(("I'll do it tomorrow evening", "I'll do it next week", "I'll do it on Friday")):
    mk = f"plugin_sync:park{i_}"; g_ = opened(mk)
    note(g_, words)
    check(f"parked setup ({words}): the item waits, no step of his is open, his step is dropped", is_waiting(g_) and his_open(g_) == [] and ("Oliver: " + S1, "dropped") in steps_of(g_) and meta_of(g_).get("until") and own(g_) is None, (meta_of(g_), steps_of(g_)))
    untouched(f"parked ({words}): the same step again writes no step", g_, mk, S1)
    untouched(f"parked ({words}): a newer step writes no step onto the waiting item", g_, mk, S2)
    check(f"parked ({words}): the step not set is not recorded as sent", sent(g_) == S1, sent(g_))
    wake_all()
    check(f"parked ({words}): the wake ends the wait", not is_waiting(g_) and meta_of(g_).get("state") != "your-step", meta_of(g_))
    untouched(f"after the wait ({words}): the step the park dropped before he answered is not asked again", g_, mk, S1)
    asks(f"after the wait ({words}): the newer step is set", g_, mk, S2, [S2])
    close(g_)

# a session's wait on a date, and on another item
def day(n): return (datetime.date.today() + datetime.timedelta(days=n)).isoformat()
g_ = opened("plugin_sync:hold")
by_builder(g_, wait_kind="time", wake=day(20), wait_basis=f"the vendor ships the fix on {day(20)}")
check("hold setup: a session's dated wait: the item reads as waiting", is_waiting(g_), meta_of(g_))
untouched("a newer step on a builder's hold writes no step", g_, "plugin_sync:hold", S2)
wake_all()
check("hold: the wake ends the wait", not is_waiting(g_), meta_of(g_))
asks("after the hold the newer step is set", g_, "plugin_sync:hold", S2, [S2])
close(g_)
g_, blocker = opened("plugin_sync:blocked"), opened("plugin_sync:blocker")
by_builder(g_, wait_kind="item", after=[blocker])
check("blocked setup: a wait on another item: the item reads as waiting", is_waiting(g_), meta_of(g_))
untouched("a newer step on a blocked item writes no step", g_, "plugin_sync:blocked", S2)
isy("close", marker="plugin_sync:blocker"); settle(); wake_all()
check("blocked: the other item's close ends the wait", not is_waiting(g_), meta_of(g_))
asks("after the blocker closed the newer step is set", g_, "plugin_sync:blocked", S2, [S2])
close(g_)

# work the board shows as waiting though it is stored as doing (a dated wait with its basis)
g_ = opened("plugin_sync:dated")
def dated_(m_):
    for k_ in ("step", "owner_step", "phase", "waits_on"): m_.pop(k_, None)
    m_.update(state="doing", mover="home-sparrow-builder", needs=["home-sparrow-builder"], wake=day(5), wait_basis={"text": f"the nightly run ends {day(5)}", "wake": day(5)})
edit_meta(g_, dated_)
check("dated setup: stored as doing, shown as waiting", M.derive(item(g_)).state == M.ALIVE and is_waiting(g_), (M.derive(item(g_)).state, meta_of(g_)))
st, r_ = isy("open", marker="plugin_sync:dated", step=S2); settle()
check("a newer step on an item shown as waiting writes no step", st == 200 and meta_of(g_).get("state") == "doing" and "Oliver: " + S2 not in [t for t, _s in steps_of(g_)], (st, meta_of(g_), steps_of(g_)))
close(g_)

# arrows: a step that holds one is itself; a shorter step is another step
A1, A0 = "open Settings → Plugins and press Sync", "open Settings"
for tag, answer_it in (("done", done), ("note", lambda g: note(g, "it still shows the old version"))):
    for legacy in (False, True):
        mk = f"plugin_sync:arrow-{tag}-{int(legacy)}"; g_ = opened(mk, step=A1); label = f"arrow step, {tag}{', an item with no record of the step' if legacy else ''}"
        if legacy: forget(g_, *RECORD)
        answer_it(g_)
        check(f"{label}: setup: his step is finished", his_open(g_) == [] and any(s_ == "done" and t.startswith("Oliver: " + A1) for t, s_ in steps_of(g_)) and (tag == "done" or any('→ "it still' in t for t, _s in steps_of(g_))), steps_of(g_))
        untouched(f"{label}: the same words again ask nothing", g_, mk, A1)
        asks(f"{label}: a newer, shorter step is set", g_, mk, A0, [A0])
        close(g_)
g_ = opened("plugin_sync:oldpark"); forget(g_, *RECORD); note(g_, "I'll do it next week"); wake_all()
untouched("an item with no record: the step a park dropped, the one it was filed with, is not asked again after the wait", g_, "plugin_sync:oldpark", S1)
asks("...a newer step is", g_, "plugin_sync:oldpark", S2, [S2])
close(g_)

# an arrow after the sent words is his answer only when the item records that answer at the moment the step was marked
BARE = "set the sync mode"
for i_, words_ in enumerate(("fast", '"fast"')):
    mk = f"plugin_sync:arrowwords{i_}"; g_ = opened(mk)
    by_builder(g_, step=f"{BARE} → {words_}"); done(g_)
    check(f"setup: he finished a step whose own words end in → {words_}", his_open(g_) == [] and ("Oliver: " + f"{BARE} → {words_}", "done") in steps_of(g_), steps_of(g_))
    asks(f"\"{BARE}\" is not matched by a finished \"{BARE} → {words_}\" that is the step's own words", g_, mk, BARE, [BARE])
    close(g_)
g_ = opened("plugin_sync:arrowlater")
by_builder(g_, step=f"{BARE} → fast"); done(g_)
edit_meta(g_, lambda m_: m_.__setitem__("answers", [{"ts": 1.0, "kind": "decision", "choice": "fast"}, *m_["answers"]]))
check("setup: an answer with the same words is recorded at another moment than the step was marked", his_open(g_) == [] and ("Oliver: " + f"{BARE} → fast", "done") in steps_of(g_), (meta_of(g_).get("answers"), steps_of(g_)))
asks("an answer recorded at another moment makes no arrow his answer: the step is set", g_, "plugin_sync:arrowlater", BARE, [BARE])
close(g_)
g_ = opened("plugin_sync:choice")
by_builder(g_, needs=["decision"], ask=f"Decide: {BARE} · Recommend: yes · Stakes: none · By: no date")
_answer_svc._answer(_model_ids._norm_id(g_), "Yes", "", "answer"); settle()
check("setup: his choice is shown after the finished step, the route's own step open beside it", his_open(g_) == mine(S1) and ("Oliver: " + BARE + " → Yes", "done") in steps_of(g_), steps_of(g_))
untouched("the step he finished with a choice after it, sent by the route: not asked again", g_, "plugin_sync:choice", BARE)
close(g_)

# one Done can tick two steps of his at once: each is the step he finished last
NOTES = "read the release notes"
g_ = opened("plugin_sync:together")
by_builder(g_, next="Oliver: " + NOTES)
check("setup: his step and a session's step for him are both open", sorted(his_open(g_)) == mine(S1, NOTES), steps_of(g_))
done(g_)
check("setup: one Done ticks both", [s_ for t, s_ in steps_of(g_) if t in mine(S1, NOTES)] == ["done", "done"], steps_of(g_))
untouched("one Done ticked his step and a session's: the first sent again asks nothing", g_, "plugin_sync:together", S1)
untouched("...nor does the second", g_, "plugin_sync:together", NOTES)
close(g_)

# while a decision ask to him is pending no step is written; once he answered it, the answer is what he finished last
ASK = "Decide: keep the old version · Recommend: yes · Stakes: none · By: no date"
for finished_first in (True, False):
    kind_ = "after his Done" if finished_first else "beside the route's open step"
    mk = f"plugin_sync:ask{int(finished_first)}"; g_ = opened(mk)
    if finished_first: done(g_)
    by_builder(g_, needs=["decision"], ask=ASK)
    check(f"setup: a decision ask is pending {kind_}", meta_of(g_).get("ask") == ASK and his_open(g_) == mine("keep the old version" if finished_first else S1), (meta_of(g_), steps_of(g_)))
    untouched(f"a pending ask {kind_}: the route's step again writes no step", g_, mk, S1)
    untouched(f"a pending ask {kind_}: a newer step writes no step and drops no line", g_, mk, S2)
    close(g_)
g_ = opened("plugin_sync:answered"); done(g_); asks("setup: a second step", g_, "plugin_sync:answered", S2, [S2]); done(g_); by_builder(g_, needs=["decision"], ask=ASK)
_answer_svc._answer(_model_ids._norm_id(g_), "Yes", "", "answer"); settle()
check("setup: he answered the later decision", not meta_of(g_).get("ask") and his_open(g_) == [], (meta_of(g_), steps_of(g_)))
asks("after a later decision a step finished before it is an older one: asked again", g_, "plugin_sync:answered", S1, [S1])
close(g_)
g_ = opened("plugin_sync:yourcall"); edit_meta(g_, lambda m_: m_.__setitem__("state", "your-call"))
untouched("an item stored as his call writes no step", g_, "plugin_sync:yourcall", S2)
close(g_)

# while a line of his that is not the route's own stands, the route sets nothing but to ask a line that reads as the sent step
g_ = opened("plugin_sync:beside")
by_builder(g_, next="Oliver: " + NOTES)
untouched("a session's line for him beside the route's open step: the route's step again changes nothing", g_, "plugin_sync:beside", S1)
untouched("...a newer step adds nothing and drops nothing", g_, "plugin_sync:beside", S2)
check("...and is not recorded as sent", sent(g_) == S1 and own(g_) == S1, (sent(g_), own(g_)))
by_builder(g_, dropped=["Oliver: " + NOTES])
asks("...once the session's line is gone the newer step replaces the route's", g_, "plugin_sync:beside", S2, [S2])
close(g_)
g_ = opened("plugin_sync:stands")
by_builder(g_, next="Oliver: " + S2)
check("setup: the route's step and a session's, the same words as the next send, are open", sorted(his_open(g_)) == mine(S1, S2), steps_of(g_))
asks("the step sent stands as a session's and the route's own other step is open: the route's is dropped, one step open, asked, not the route's", g_, "plugin_sync:stands", S2, [S2], record=False)
untouched("...sent again it is left alone", g_, "plugin_sync:stands", S2)
untouched("...and a newer step is not put beside the session's line", g_, "plugin_sync:stands", S3)
done(g_)
asks("...after his Done on it the newer step is set", g_, "plugin_sync:stands", S3, [S3])
close(g_)

# a session's current step is never written over; its split record and its draft stay
def keeps(name, g, marker, step, opens, was_sent):
    """a repeat open that leaves the session's current step, its split record and its draft; `opens` the open steps of his after it, `was_sent` the record of the step sent"""
    before = {k_: meta_of(g).get(k_) for k_ in ("state", "step", "step_lines", "draft", "owner_step")}
    st_, r_ = isy("open", marker=marker, step=step); settle()
    after = {k_: meta_of(g).get(k_) for k_ in before}
    check(name, st_ == 200 and r_["action"] == "refreshed" and after == before and sorted(his_open(g)) == sorted(opens) and sent(g) == was_sent, (st_, r_, before, after, steps_of(g), sent(g)))
LONG = ". ".join(f"Open the settings page number {n} of the plugin and check that every field reads as the note says" for n in range(1, 4)) + "."
g_ = opened("plugin_sync:split")
with _writes_s.session_write(): by_builder(g_, step=LONG)
by_builder(g_, draft="the settings read as the note says")
split_ = [t for t in his_open(g_) if t != meta_of(g_).get("owner_step")]
check("setup: a session's long step is split into lines of his, with a draft", meta_of(g_).get("step_lines") and len(split_) >= 2 and meta_of(g_).get("draft"), (meta_of(g_), steps_of(g_)))
open_ = his_open(g_)
keeps("a newer step of the route leaves the session's step, its split record, its draft and every line", g_, "plugin_sync:split", S2, open_, S1)
action_ = split_[0].removeprefix("Oliver: ")
keeps("a line of the split sent by the route: asked already, the session's step stays the current one", g_, "plugin_sync:split", action_, open_, action_)
close(g_)
g_ = opened("plugin_sync:current")
by_builder(g_, step=S3); by_builder(g_, next="Oliver: " + NOTES)
keeps("a session's line sent while the item asks the session's step: the current step stays", g_, "plugin_sync:current", NOTES, mine(S3, NOTES), NOTES)
close(g_)
g_ = opened("plugin_sync:leftover"); by_builder(g_, next="Oliver: " + NOTES); cut_short(g_); by_builder(g_, step=NOTES)
check("setup: the item asks a session's step, the route's own line still open beside it", meta_of(g_).get("step") == NOTES and sorted(his_open(g_)) == mine(S1, NOTES) and own(g_) == S1, (meta_of(g_), steps_of(g_)))
by_builder(g_, next="Oliver: " + S3)
keeps("a session's line sent while another session step is current and the route's older line is open: only the route's line goes", g_, "plugin_sync:leftover", S3, mine(NOTES, S3), S3)
check("...it is dropped", ("Oliver: " + S1, "dropped") in steps_of(g_) and own(g_) is None, (steps_of(g_), own(g_)))
close(g_)
g_ = opened("plugin_sync:summary")
by_builder(g_, next="Oliver: " + NOTES)
edit_meta(g_, lambda m_: m_.__setitem__("step_lines", ["Oliver: " + NOTES]))
keeps("while the current step is split into lines, no line is the route's own: nothing is dropped, whatever the summary reads", g_, "plugin_sync:summary", NOTES, mine(S1, NOTES), NOTES)
close(g_)

# a step a session set with step= is the session's: the route sets nothing beside it
for after_done in (False, True):
    kind_ = "after his Done" if after_done else "over the route's open step"
    mk = f"plugin_sync:sessionstep{int(after_done)}"; g_ = opened(mk)
    if after_done: done(g_)
    by_builder(g_, step=S3)
    keeps(f"a session's step= {kind_}, sent by the route: it is asked already", g_, mk, S3, mine(S3), S3)
    untouched(f"a session's step= {kind_}: the route's newer step is not put beside it", g_, mk, S2)
    close(g_)

# the record goes with the route's open line, so a line a session writes later with the same words is the session's
for i_, (tag, close_it) in enumerate((("his Done", done), ("a session withdrew it", lambda g: by_builder(g, step="none")))):
    mk = f"plugin_sync:rewritten{i_}"; g_ = opened(mk)
    if tag != "his Done": by_builder(g_, next="home-sparrow-builder: watch the sync")
    close_it(g_)
    check(f"setup ({tag}): the route's line is closed and its record gone, the step sent stays", "Oliver: " + S1 not in his_open(g_) and own(g_) is None and sent(g_) == S1, (meta_of(g_), steps_of(g_)))
    by_builder(g_, next="home-sparrow-builder: watch the sync\nOliver: " + S1)
    check(f"setup ({tag}): a session writes the same words again", "Oliver: " + S1 in his_open(g_), (meta_of(g_), steps_of(g_)))
    untouched(f"after {tag}, the session's line with the route's old words is not taken for the route's: a newer step drops nothing", g_, mk, S2)
    close(g_)

# after his Done, an agent holds the item and a session's line for him is open: it is asked, unless it is what he finished
for legacy in (False, True):
    kind_ = " (an item with no record of the step)" if legacy else ""
    mk = f"plugin_sync:held{int(legacy)}"; g_ = opened(mk)
    if legacy: forget(g_, *RECORD)
    done(g_)
    by_builder(g_, next="home-sparrow-builder: watch the sync\nOliver: " + NOTES)
    check(f"setup: after Done an agent holds the item, a session's step for him open{kind_}", his_open(g_) == mine(NOTES) and meta_of(g_).get("state") != "your-step" and M.derive(item(g_)).mover != "Oliver", (meta_of(g_), steps_of(g_)))
    untouched(f"the step he finished, sent now: the agent keeps the item{kind_}", g_, mk, S1)
    untouched(f"a step no line reads as, sent now: nothing beside the session's line{kind_}", g_, mk, S2)
    asks(f"the open step he has not finished, sent now: he is the mover again{kind_}", g_, mk, NOTES, [NOTES], record=False)
    close(g_)
g_ = opened("plugin_sync:heldsame"); done(g_)
by_builder(g_, next="home-sparrow-builder: watch the sync\nOliver: " + S1)
untouched("a line open again with the words he finished: not asked, the agent keeps the item", g_, "plugin_sync:heldsame", S1)
close(g_)

# a close takes the record of the route's own line and keeps the step sent
for i_, (tag, close_it) in enumerate((("the route's close", lambda g, mk: isy("close", marker=mk)), ("a session's close", lambda g, mk: close(g)))):
    mk = f"plugin_sync:closed{i_}"; g_ = opened(mk)
    check(f"setup ({tag}): the open item records the route's own line", own(g_) == S1, meta_of(g_))
    close_it(g_, mk); settle()
    check(f"{tag} clears the record of the route's own line; the step sent stays", item(g_)["status"] == "completed" and own(g_) is None and sent(g_) == S1, meta_of(g_))

# an item filed before the records: the line its create wrote is read as the route's where the record shows that
def old(marker):
    g_ = opened(marker); forget(g_, *RECORD); return g_
g_ = old("plugin_sync:old")
untouched("an old item: the step it was filed with, sent again, changes nothing", g_, "plugin_sync:old", S1)
asks("an old item: a newer step replaces the line the route wrote at filing", g_, "plugin_sync:old", S2, [S2])
done(g_)
check("...so his Done marks the one step he was asked, not the old one beside it", [s_ for t, s_ in steps_of(g_) if t == "Oliver: " + S1] == ["dropped"], steps_of(g_))
close(g_)
g_ = old("plugin_sync:oldwithdrawn"); by_builder(g_, next="home-sparrow-builder: watch the sync", step="none")
untouched("an old item whose step a session withdrew: the step it was filed with is not asked again", g_, "plugin_sync:oldwithdrawn", S1)
asks("...a newer one is", g_, "plugin_sync:oldwithdrawn", S2, [S2])
close(g_)
g_ = old("plugin_sync:oldreplaced"); by_builder(g_, step=S3)
untouched("an old item whose step a session replaced: the step it was filed with is not asked again", g_, "plugin_sync:oldreplaced", S1)
untouched("...and a newer one is not put beside the session's", g_, "plugin_sync:oldreplaced", S2)
done(g_)
asks("...it is set after his Done", g_, "plugin_sync:oldreplaced", S2, [S2])
close(g_)
g_ = opened("plugin_sync:oldcut"); cut_short(g_, "item_sync_step")
asks("an old filing cut short before its state: the same step makes the item ask it, as the route's own", g_, "plugin_sync:oldcut", S1, [S1])
asks("...so a newer step replaces it", g_, "plugin_sync:oldcut", S2, [S2])
close(g_)
g_ = opened("plugin_sync:oldcutnew"); cut_short(g_, "item_sync_step")
asks("an old filing cut short, sent a newer step: the filing's line is replaced", g_, "plugin_sync:oldcutnew", S2, [S2])
close(g_)
# where it cannot be told: an older repeat completed a cut-short filing with a different step, two lines open and the first not the current one
g_ = opened("plugin_sync:oldunknown"); cut_short(g_, "item_sync_step")
_update_svc._update(_model_ids._norm_id(g_), step=S2, sender="x (a script on a client machine)"); settle()
check("setup: an old item with the filing's line and a different current step", meta_of(g_).get("step") == S2 and sorted(his_open(g_)) == mine(S1, S2) and own(g_) is None and sent(g_) is None, (meta_of(g_), steps_of(g_)))
untouched("an old item whose route line cannot be told: no newer step is set, no line is dropped", g_, "plugin_sync:oldunknown", S3)
done(g_)
asks("...his Done frees it and the newer step is set", g_, "plugin_sync:oldunknown", S3, [S3])
close(g_)
g_ = opened("plugin_sync:oldcutbeside"); by_builder(g_, next="Oliver: " + NOTES); cut_short(g_, "item_sync_step")
asks("an old filing cut short with a second step on the list: the filing's step sent again is asked, as a line that is not known to be the route's", g_, "plugin_sync:oldcutbeside", S1, [S1, NOTES], record=False)
by_builder(g_, dropped=["Oliver: " + NOTES])
untouched("...so a newer step drops nothing", g_, "plugin_sync:oldcutbeside", S2)
close(g_)
g_ = old("plugin_sync:oldwriter")
edit_meta(g_, lambda m_: m_["next_by"][0].__setitem__(0, "home-sparrow-builder"))
untouched("an old item whose first line another writer wrote is not taken for the route's: nothing beside it, nothing dropped", g_, "plugin_sync:oldwriter", S2)
close(g_)

# none, clear and - are no step: a repeat open withdraws nothing
g_ = opened("plugin_sync:nostep")
for word in ("none", "None", "clear", "-", "Oliver: none", "Oliver: -"):
    untouched(f"a repeat open with the step {word!r} changes no step", g_, "plugin_sync:nostep", word)
    n_ = len(items()); st_, e_ = isy("open", marker="plugin_sync:nostep-first", step=word)
    check(f"a first open with the step {word!r} is refused, nothing filed", st_ == 400 and "no step" in e_["error"] and len(items()) == n_ and sync_open("plugin_sync:nostep-first") == [], (st_, e_))

# a step the board's step gates refuse: neither the description, the list nor the record is written
before_, before_d = shape(g_), item(g_)["description"]
st, e_g = isy("open", marker="plugin_sync:nostep", step="run `systemctl restart demo` on the host", description=["- must not be written"]); settle()
check("a repeat open with a step a step gate refuses: 400, description, step and record unchanged", st == 400 and "step" in e_g["error"] and shape(g_) == before_ and own(g_) == S1 and item(g_)["description"] == before_d, (st, e_g, item(g_)["description"]))
close(g_)

# one limit for a first and a repeat open, checked before anything is written
gl = opened("plugin_sync:long")
before_d = item(gl)["description"]; before_s = steps_of(gl)
over, edge = "Press Sync " + "x" * 190, "Press Sync " + "y" * 189
long_link = "Press Sync on [the page](https://example.com/" + "p" * 300 + ")"
for name, step_, needle in (("over the next line's limit", over, "limit is 200"), ("with a link, over the step's own limit", long_link, "at most 300")):
    st, e_l = isy("open", marker="plugin_sync:long", step=step_, description=["- must not be written"]); settle()
    check(f"a step {name} on a repeat open is refused with the limit named; the description and steps are unchanged", st == 400 and needle in e_l["error"] and item(gl)["description"] == before_d and steps_of(gl) == before_s, (st, e_l))
    n_ = len(items()); st, e_f = isy("open", marker="plugin_sync:long-first", step=step_)
    check(f"a step {name} on a first open is refused the same way, nothing filed", st == 400 and needle in e_f["error"] and len(items()) == n_ and sync_open("plugin_sync:long-first") == [], (st, e_f))
check("setup: the steps at and over the limit", len(edge) == 200 and len(over) == 201)
asks("a step of exactly the limit (200 characters) on a repeat open is set", gl, "plugin_sync:long", edge, [edge])
ge = opened("plugin_sync:long-edge", step=edge)
check("a step of exactly the limit on a first open is filed", his_open(ge) == ["Oliver: " + edge], steps_of(ge))
close(ge)

# a step with ';' sent twice: set the first time, left alone the second
semi = "run the sync; then press Sync; confirm the version"
asks("a ';' step on a repeat open is set as sent", gl, "plugin_sync:long", semi, [semi])
untouched("the same ';' step sent again is left alone", gl, "plugin_sync:long", semi)

# the reason is cut to the board's limit, never refused for its length
st, o10 = isy("open", marker="plugin_sync:longreason")
st, c10 = isy("close", marker="plugin_sync:longreason", reason="word " * 80)
rs10 = item(o10["item"])["metadata"].get("reason", item(o10["item"]).get("reason")) or ""
check("a close reason over the board's limit is cut to it: 200, closed, a stored reason of at most [close] reason_max characters that starts as given", st == 200 and c10["action"] == "closed" and 0 < len(rs10) <= _close_reason_max() < 400 and rs10.startswith("word word"), (st, c10, len(rs10), _close_reason_max()))

# a session's close between the route's look and its write cannot land: the route holds the board's item lock across both
st, o11 = isy("open", marker="plugin_sync:lock"); g11 = _model_ids._norm_id(o11["item"])
_real_open_items = item_sync_svc._itemsync_open_items; blocked = []
def _look_then_close():
    found_ = _real_open_items()
    t_ = threading.Thread(target=lambda: _update_svc._update(g11, outcome_text="- closed by a session", status="completed", outcome="done", reason="a session closed it", sender="home-sparrow-builder"), daemon=True)
    t_.start(); t_.join(1.5); blocked.extend([t_.is_alive(), t_])
    return found_
item_sync_svc._itemsync_open_items = _look_then_close
try: st, r11 = isy("refresh", marker="plugin_sync:lock", description=["- written while the item is open"])
finally: item_sync_svc._itemsync_open_items = _real_open_items
blocked[1].join(5)
check("a session's close cannot land between the route's look and its write: the close waits for the route (it held the item lock), the refresh lands on the open item, then the close completes",
      st == 200 and r11["action"] == "refreshed" and blocked[0] is True and item(g11)["status"] == "completed" and item(g11)["description"].splitlines()[0] == "- written while the item is open", (st, r11, blocked[:1], item(g11)["status"], item(g11)["description"]))

# a state write that fails: the item the create made is closed again (the rollback), never left open
_real_update = _update_svc._update
def _fail_state(gid, *a, **kw):
    if "step" in kw: raise RuntimeError("the state write failed")
    return _real_update(gid, *a, **kw)
ids12 = {g for g, _p in _item_files_()}; _update_svc._update = _fail_state
try:
    try: isy("open", marker="plugin_sync:rollback"); raised12 = False
    except RuntimeError: raised12 = True
finally: _update_svc._update = _real_update
new12 = sorted({g for g, _p in _item_files_()} - ids12)
check("a failed state write: the error reaches the caller, the one item the create made is closed as dropped, no open item is left for the marker", raised12 and len(new12) == 1 and sync_open("plugin_sync:rollback") == []
      and item(_gh.shown(new12[0]))["status"] == "completed" and item(_gh.shown(new12[0]))["metadata"].get("outcome") == "dropped", (raised12, new12, sync_open("plugin_sync:rollback")))

# a state write and the rollback both fail: the item stays open half made, and the next open makes it whole
def _fail_all(gid, *a, **kw): raise RuntimeError("the board is down")
_update_svc._update = _fail_all
try:
    try: isy("open", marker="plugin_sync:repair"); raised13 = False
    except RuntimeError: raised13 = True
finally: _update_svc._update = _real_update
half = sync_open("plugin_sync:repair")
hm = item(_gh.shown(half[0]))["metadata"] if half else {}
check("a state write and the rollback both failing leaves one open item for the marker, with no your-step state", raised13 and len(half) == 1 and hm.get("state") != "your-step", (raised13, half, hm.get("state"), hm.get("step")))
check("…and the create's own write records his line as the route's, not yet as sent", hm.get("item_sync_step") == S1 and "item_sync_sent" not in hm, (hm.get("item_sync_step"), hm.get("item_sync_sent")))
st, r13 = isy("open", marker="plugin_sync:repair")
hm2 = item(_gh.shown(half[0]))["metadata"] if half else {}
check("the next open of the marker makes the item whole (the state your-step with his step) and files nothing", st == 200 and r13["action"] == "refreshed" and r13["repeat"] is True and r13["item"] == _gh.shown(half[0]) and hm2.get("state") == "your-step"
      and _states_mod.clean(hm2.get("step")) and sync_open("plugin_sync:repair") == half, (st, r13, hm2.get("state"), hm2.get("step")))
hs = _gh.shown(half[0]); _answer_svc._answer(_model_ids._norm_id(hs), "", "", "done"); state13 = item(hs)["metadata"].get("state")
st, r13c = isy("open", marker="plugin_sync:repair")
check("…once he has answered Done a repeat open refreshes the description and does not put the item back to his step", st == 200 and r13c["action"] == "refreshed" and item(hs)["metadata"].get("state") == state13 and state13 != "your-step", (st, r13c, state13))
isy("close", marker="plugin_sync:repair"); settle()

# a new item's create (it reaches GitHub for the number) is made without the board's item lock, and under the route's own lock alone
from stackshot.service import create as _create_svc_t
from stackshot.service import writes as _writes_t
_real_create = _create_svc_t.create_item
def _slow_create(*a, **kw):
    time.sleep(1.0); return _real_create(*a, **kw)
st, ou = isy("open", marker="plugin_sync:unrelated"); gu = ou["item"]
# The create is held open until the update has returned, so the order of the two is what is checked, never how long the update takes: an update that waits for the create returns only after the hold runs out.
in_create_, go_, gave_up_ = threading.Event(), threading.Event(), []
def _held_create(*a, **kw):
    in_create_.set()
    if not go_.wait(60): gave_up_.append(True)
    return _real_create(*a, **kw)
_create_svc_t.create_item = _held_create
try:
    ts_ = threading.Thread(target=lambda: isy("open", marker="plugin_sync:slow"), daemon=True); ts_.start(); held_ = in_create_.wait(60)
    _update_svc._update(_model_ids._norm_id(gu), description="- an unrelated update while the create is slow", sender="home-sparrow-builder")
    free_ = held_ and not gave_up_ and ts_.is_alive()
    go_.set(); ts_.join(60)
finally:
    go_.set(); _create_svc_t.create_item = _real_create
check("an unrelated update is not blocked while a new item's create is slow (the board's item lock is not held across the create)", free_ and not ts_.is_alive() and len(sync_open("plugin_sync:slow")) == 1, (held_, gave_up_, sync_open("plugin_sync:slow")))
isy("close", marker="plugin_sync:slow"); isy("close", marker="plugin_sync:unrelated")
n_dbl = len([1 for g, _p in _item_files_()]); _create_svc_t.create_item = _slow_create; dbl = []
try:
    tds_ = [threading.Thread(target=lambda: dbl.append(isy("open", marker="plugin_sync:double")), daemon=True) for _ in range(2)]
    tds_[0].start(); time.sleep(0.3); tds_[1].start(); [t_.join(15) for t_ in tds_]
finally: _create_svc_t.create_item = _real_create
check("two opens of one marker at once, the create slow: one item is filed (the route's own lock holds the second until the first is made), both answered with it", len(sync_open("plugin_sync:double")) == 1 and len([1 for g, _p in _item_files_()]) == n_dbl + 1
      and len({r[1].get("item") for r in dbl}) == 1 and sorted(r[1]["action"] for r in dbl) == ["opened", "refreshed"], (dbl, sync_open("plugin_sync:double")))
isy("close", marker="plugin_sync:double")

# the script-row flag is off again after every call: a success, a refusal of the board, an error that is not a refusal
def row_flag(): return _writes_t.terminal_row()
st, oz = isy("open", marker="plugin_sync:flag"); f1 = row_flag()
st, rz = isy("refresh", marker="plugin_sync:flag"); f2 = row_flag()
def _tool_refusal(gid, *a, **kw): raise ToolError_t("Refused: no")
from fastmcp.exceptions import ToolError as ToolError_t
_update_svc._update = _tool_refusal
try: st3, _e3 = isy("refresh", marker="plugin_sync:flag"); f3 = row_flag()
finally: _update_svc._update = _real_update
def _crash(gid, *a, **kw): raise RuntimeError("down")
_update_svc._update = _crash
try:
    try: isy("refresh", marker="plugin_sync:flag")
    except RuntimeError: pass
    f4 = row_flag()
finally: _update_svc._update = _real_update
check("the script-row flag is off again after a success, after the board's refusal (a 400) and after an error that is no refusal", (f1, f2, f3, f4) == (False, False, False, False) and st3 == 400, (f1, f2, f3, f4, st3))
isy("close", marker="plugin_sync:flag")

# the update's own close gate stands behind the route's check: with the check blind, a close over another session's step is refused by the board and ticks nothing
import types as _types
st, ob = isy("open", marker="plugin_sync:gate"); gb = ob["item"]
add_step(gb, "home-sparrow-notes", "write the changelog"); settle()
_real_steps = item_sync_svc._steps
item_sync_svc._steps = _types.SimpleNamespace(**{k: getattr(_real_steps, k) for k in dir(_real_steps) if not k.startswith("__")}); item_sync_svc._steps.others_open = lambda *a, **kw: []
try: st, cb = isy("close", marker="plugin_sync:gate")
finally: item_sync_svc._steps = _real_steps
check("a close the route's own check let through is refused by the update's gate for another session's open step (a 400, nothing ticked, the item open)", st == 400 and "nothing is ticked" in cb.get("error", "") and item(gb)["status"] == "open"
      and sorted(steps_of(gb)) == sorted([("Oliver: open the plugin page and press Sync", "open"), ("home-sparrow-notes: write the changelog", "open")]), (st, cb, steps_of(gb)))
mark(gb, "home-sparrow-notes", "home-sparrow-notes: write the changelog"); isy("close", marker="plugin_sync:gate")

# ---- 9. over HTTP and through client.py
app = server.mcp.http_app()
with TestClient(app) as c:
    body = {"marker": "test_trim:http", "project": "projects/alpha", "subject": "Over http", "mover": "home-sparrow-builder", "step": "home-sparrow-builder: deep-scan", "description": ["- over http"], "sender": "http-script"}
    r = c.post("/client/item-open", json=body); check("http: without a token -> 401 and nothing filed", r.status_code == 401 and open_for("test_trim:http") == [], r.status_code)
    r = c.post("/client/item-open", json=body, headers={"Authorization": "Bearer not-a-token"}); check("http: with a token the server never minted -> 401 and nothing filed", r.status_code == 401 and open_for("test_trim:http") == [], r.status_code)
    r = c.post("/client/item-open", json=body, headers=HD)
    check("http: with a machine token -> 200 and the item", r.status_code == 200 and r.json()["repeat"] is False and r.headers["cache-control"] == "no-store", r.text)
    gid_http = r.json()["item"]
    r = c.post("/client/item-open", json=body, headers=HD)
    check("http: the same call again -> 200, the same item, repeat true", r.status_code == 200 and r.json()["item"] == gid_http and r.json()["repeat"] is True, r.text)
    r = c.post("/client/item-open", json={**body, "mover": "home-sparrow-main"}, headers=HD)
    check("http: a mover the page does not list as a background agent -> 400", r.status_code == 400 and "not a background agent" in r.json()["error"], r.text)
    r = c.post("/client/item-open", content=b"not json", headers=HD); check("http: a body that is not JSON is a 4xx, never a 500", 400 <= r.status_code < 500, r.status_code)
    close(gid_http)
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
    BASE = ["post", "item-open", "test_trim:cli", "--project", "projects/alpha", "--subject", "Over the client", "--mover", "home-sparrow-builder", "--step", "home-sparrow-builder: deep-scan",
            "--line", "first fact", "--line", "second fact", "--sender", "cli-script"]
    before = len(items())
    rc, o, e = run(*BASE)
    gid_cli = o.strip()
    check("client.py: exactly the item id on stdout, nothing on stderr, exit 0, one item filed", rc == 0 and re.fullmatch(r"\S+\n", o) and e == "" and len(items()) == before + 1, (rc, o, e))
    check("…the item has both lines as bullets, then the attribution", item(gid_cli)["description"].splitlines() == ["- first fact", "- second fact", "- Opened by cli-script (a script on a client machine)"] and item(gid_cli)["metadata"]["item_open"] == "test_trim:cli", item(gid_cli)["description"])
    rc, o2, e = run(*BASE)
    check("client.py again: the same id printed, exit 0, nothing filed", rc == 0 and o2 == o and e == "" and len(items()) == before + 1, (rc, o2, e))
    close(gid_cli)
    rc, o3, e = run(*BASE)
    check("client.py after the item was closed: a new id, exit 0", rc == 0 and o3 != o and re.fullmatch(r"\S+\n", o3) and len(items()) == before + 2, (rc, o3, e))
    close(o3.strip())
    # item-sync over HTTP and through client.py
    sbody = {"action": "open", "marker": "plugin_sync:http", "project": "projects/alpha", "subject": "Over http", "mover": "Oliver", "then": "home-sparrow-builder", "step": "press Sync", "description": ["- over http"], "sender": "http-script"}
    r = c.post("/client/item-sync", json=sbody); check("item-sync http: without a token -> 401 and nothing filed", r.status_code == 401 and sync_open("plugin_sync:http") == [], r.status_code)
    r = c.post("/client/item-sync", json=sbody, headers={"Authorization": "Bearer not-a-token"}); check("item-sync http: with a token the server never minted -> 401 and nothing filed", r.status_code == 401 and sync_open("plugin_sync:http") == [], r.status_code)
    r = c.post("/client/item-sync", json=sbody, headers=HD)
    check("item-sync http: with a machine token -> 200, opened", r.status_code == 200 and r.json()["action"] == "opened" and r.headers["cache-control"] == "no-store", r.text)
    r = c.post("/client/item-sync", json={"action": "close", "marker": "plugin_sync:http"}, headers=HD)
    check("item-sync http: close -> 200, closed", r.status_code == 200 and r.json()["action"] == "closed" and sync_open("plugin_sync:http") == [], r.text)
    r = c.post("/client/item-sync", content=b"not json", headers=HD); check("item-sync http: a body that is not JSON is a 4xx, never a 500", 400 <= r.status_code < 500, r.status_code)
    SBASE = ["post", "item-sync", "plugin_sync:cli"]
    SOPEN = [*SBASE, "open", "--project", "projects/alpha", "--subject", "Press Sync", "--mover", "Oliver", "--then", "home-sparrow-builder", "--step", "press Sync", "--line", "first fact", "--line", "second fact", "--sender", "cli-script"]
    before = len(items())
    rc, o, e = run(*SOPEN)
    sc_id = o.split()[0] if o.split() else ""
    check("client.py item-sync open: one line '<item> opened' on stdout, nothing on stderr, exit 0, one item filed", rc == 0 and re.fullmatch(r"\S+ opened\n", o) and e == "" and len(items()) == before + 1, (rc, o, e))
    check("…the item has both lines as bullets, then the attribution, and the person as mover", item(sc_id)["description"].splitlines() == ["- first fact", "- second fact", "- Opened by cli-script (a script on a client machine)"]
          and item(sc_id)["metadata"]["item_sync"] == "plugin_sync:cli" and item(sc_id)["metadata"]["mover"] == "Oliver", item(sc_id))
    rc, o2, e = run(*SOPEN)
    check("client.py item-sync open again: '<item> refreshed', the same item, exit 0, nothing filed", rc == 0 and o2 == o.replace("opened", "refreshed") and e == "" and len(items()) == before + 1, (rc, o2, e))
    rc, o2, e = run(*SBASE, "refresh", "--line", "a newer fact")
    check("client.py item-sync refresh: '<item> refreshed', the description is the new line and the attribution, exit 0", rc == 0 and o2 == o.replace("opened", "refreshed") and e == ""
          and item(sc_id)["description"].splitlines() == ["- a newer fact", "- Opened by client.py (a script on a client machine)"], (rc, o2, e, item(sc_id)["description"]))
    rc, o2, e = run(*SBASE, "close", "--reason", "all in sync")
    check("client.py item-sync close: '<item> closed', exit 0, the item is completed with the caller's reason", rc == 0 and o2 == o.replace("opened", "closed") and e == "" and item(sc_id)["status"] == "completed" and item(sc_id)["metadata"]["reason"] == "all in sync", (rc, o2, e))
    rc, o2, e = run(*SBASE, "close")
    check("client.py item-sync close with none open: one plain line on stdout, exit 0, no error", rc == 0 and e == "" and o2.startswith("no open item for plugin_sync:cli") and o2.count("\n") == 1, (rc, o2, e))
    rc, o2, e = run(*SBASE, "refresh", "--line", "x")
    check("client.py item-sync refresh with none open: one plain line on stdout, exit 0, no error", rc == 0 and e == "" and o2.startswith("no open item for plugin_sync:cli") and o2.count("\n") == 1, (rc, o2, e))
    rc, o3, e = run(*SOPEN)
    check("client.py item-sync open after the close: a new item, opened", rc == 0 and o3.endswith(" opened\n") and o3 != o and len(items()) == before + 2, (rc, o3, e))
    run(*SBASE, "close")
    rc, o4, e = run(*SOPEN); sc2 = o4.split()[0] if o4.split() else ""
    add_step(sc2, "home-sparrow-notes", "write the changelog"); settle()
    rc, o5, e = run(*SBASE, "close")
    check("client.py item-sync close while another writer's step is open: the one plain line '<item> left open: open steps of others remain' on stdout, nothing on stderr, exit 0, the item still open", rc == 0 and e == "" and o5 == f"{sc2} left open: open steps of others remain\n" and item(sc2)["status"] == "open", (rc, o5, e))
    mark(sc2, "home-sparrow-notes", "home-sparrow-notes: write the changelog"); run(*SBASE, "close")
    before = len(items())
    SU = "usage: client.py post item-sync"
    for name, argv, needle in (("no marker", ["post", "item-sync"], SU), ("a flag first", ["post", "item-sync", "--project", "p"], SU), ("no action", [*SBASE], SU), ("an unknown action", [*SBASE, "drop"], SU),
                               ("open with no then", [x for x in SOPEN if x not in ("--then", "home-sparrow-builder")], SU), ("open with no line", [x for x in SOPEN if x not in ("--line", "first fact", "second fact")], SU),
                               ("refresh with no line", [*SBASE, "refresh"], SU), ("refresh with a project", [*SBASE, "refresh", "--line", "x", "--project", "p"], SU), ("close with a line", [*SBASE, "close", "--line", "x"], SU),
                               ("a flag with no value", [*SBASE, "close", "--reason"], "needs a value"), ("a stray word", [*SOPEN, "stray"], SU)):
        rc, o, e = run(*argv)
        check(f"client.py item-sync misuse, {name}: usage or reason on stderr, nothing on stdout, exit 1", rc == 1 and o == "" and needle in e, (rc, o, e))
    check("…and none of them filed an item", len(items()) == before, (len(items()), before))
    rc, o, e = run(*[x if x != "Oliver" else "home-sparrow-main" for x in SOPEN])
    check("client.py item-sync with a mover that is not the person: the server's 400 on stderr, exit 1, nothing on stdout, nothing filed", rc == 1 and o == "" and "[400]" in e and "mover is Oliver" in e and len(items()) == before, (rc, o, e))
    _post = client.post
    client.post = lambda what, body, timeout=20.0: (200, {"project": "projects/alpha"})
    try:
        rc, o, e = run(*SOPEN)
        check("client.py item-sync when the answer has no item and is no no-op: exit 1 with a line on stderr, never silent", rc == 1 and o == "" and "item not synced" in e, (rc, o, e))
    finally: client.post = _post
    usage_src = pathlib.Path(client.__file__).read_text(encoding="utf-8")
    check("the client's usage text lists the three item-sync calls", all(f"client.py post item-sync <marker> {v}" in usage_src for v in ("open", "refresh", "close")))
    st, e = _rt_client._client_post(me, "no-such-write", {})
    check("the 404 for an unknown write lists item-sync", st == 404 and "item-sync" in e["error"], (st, e))
    before = len(items())
    U = "usage: client.py post item-open"
    short = ["post", "item-open", "test_trim:x"]
    for name, argv, needle in (("no marker", ["post", "item-open"], U), ("a flag first", ["post", "item-open", "--project", "projects/alpha"], U), ("no project", [*short, "--subject", "s", "--mover", "m", "--step", "m: a", "--line", "l"], U),
                               ("no line", [*short, "--project", "p", "--subject", "s", "--mover", "m", "--step", "m: a"], U), ("a flag with no value", [*short, "--project"], "needs a value"),
                               ("a stray word", [*BASE, "stray"], U)):
        rc, o, e = run(*argv)
        check(f"client.py misuse, {name}: usage or reason on stderr, nothing on stdout, exit 1", rc == 1 and o == "" and needle in e, (rc, o, e))
    check("…and none of them filed an item", len(items()) == before, (len(items()), before))
    rc, o, e = run(*[x if x != "home-sparrow-builder" else "home-sparrow-main" for x in BASE[:9]], "--step", "home-sparrow-main: x", "--line", "l")
    check("client.py with a mover the page does not list: the server's 400 on stderr, exit 1, nothing on stdout", rc == 1 and o == "" and "[400]" in e and "not a background agent" in e and len(items()) == before, (rc, o, e))
    tokfile = pathlib.Path(client.TOKEN); hold = tokfile.with_suffix(".held"); tokfile.rename(hold)
    try:
        rc, o, e = run(*BASE)
        check("client.py with no token on the machine: exit 1, the reason on stderr, nothing filed", rc == 1 and o == "" and "no token on this machine" in e and len(items()) == before, (rc, o, e))
    finally: hold.rename(tokfile)
    _post = client.post
    client.post = lambda what, body, timeout=20.0: (200, {"project": "projects/alpha"})
    try:
        rc, o, e = run(*BASE)
        check("client.py when the answer has no item id: exit 1 with a line on stderr, never silent", rc == 1 and o == "" and "item not opened" in e, (rc, o, e))
    finally: client.post = _post
    down["on"] = True
    rc, o, e = run(*BASE)
    check("client.py with the server not reached: exit 1 and the reason on stderr", rc == 1 and o == "" and e.strip() != "" and len(items()) == before, (rc, o, e))
    down["on"] = False
settle()

if fails:
    print(f"\n{len(fails)} of {len(ran)} checks FAILED"); sys.exit(1)
print(f"ok: {len(ran)} checks"); sys.exit(0)
