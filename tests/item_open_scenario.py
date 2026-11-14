"""Scenario test for the script route that opens one board item for a project's background agent (`client.py post item-open`, POST /client/item-open) — fixture data, no live store, no
network, no server process (the server module is imported and called in-process, on a temporary config; the pages are fixture files in a temporary directory).

Covers: open (one item filed through the create tool's own code: the subject takes the project scope's prefix from the server and replaces a prefix the caller wrote, marked metadata.item_open = the
marker, the mover a background agent of the page and in needs, the project's -main agent the creator, one step that names the mover, description bullets ending with the attribution line, no machine
host name anywhere in the item, the mover told once, nothing owed to the page); a repeat call while the item is open answers it and files nothing, another marker is another item, and the same marker on another project is that project's own item (a call never answers or shows another project's item); a call after the
item was closed files a new item (the open state is read from the store); a mover that is not a background agent the page lists (a front agent, the owner, another project's agent, a made-up name)
is refused with the listed ones named; bad bullets (none, too many, too long, a control character, a wrong type) are refused and never cut; a missing or malformed marker, a missing field, a step that
does not start with the mover, a key the route does not take (needs, owner, priority) and a sender with markup or the owner's name are refused with nothing filed; an @name is broken so the mirror pings
no one; an unknown project a 404, a project with no front agent a 409; a cap of 10 open items per project (the eleventh marker is refused, a repeat at the cap is still answered, a closed item frees a place, the cap is per project); a long sender and a doubled caller prefix; the unknown-write 404 lists the route; eight threads calling at once file one item; over HTTP (401 without a token) and through client.py (the id alone on stdout,
usage on misuse, the server's refusal on stderr, a server that is not reached).

    tests/run-suite item_open        → exit 0 / 1"""
import contextlib, io, json, os, re, socket, sys, pathlib, logging, threading, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="itemopentest-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
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
for d in ("store/a", "fleet/a", "sala/a", "brain/projects", "brain/infra", "secrets"): (T / d).mkdir(parents=True)
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")

def uid(n): return f"00000000-0000-4000-8000-{n:012d}"
S = {"build": uid(101), "main": uid(102), "docs": uid(103), "nbmain": uid(104), "gbuild": uid(105), "bmain": uid(106), "bbuild": uid(107), "cmain": uid(108), "cbuild": uid(109)}
def row(key, name, project_key):
    return {"id": S[key], "name": name, "aliases": [], "project": None, "project_key": project_key, "role": None, "lane": "max", "model": "opus", "effort": "medium", "pane": name,
            "cwd": "/work", "state": "live", "created": "2026-10-21T21:00:00Z", "retired_at": None,
            "transcripts": [{"id": uid(200 + int(S[key][-3:]) - 100), "machine": "a", "at": "2026-10-21T21:00:00Z", "why": "import"}]}
ROWS = [row("build", "home-sparrow-builder", "projects/alpha"), row("main", "home-sparrow-main", "projects/alpha"), row("docs", "home-sparrow-docs", "projects/alpha"), row("nbmain", "home-nobuild-main", "projects/nobuild"),
        row("gbuild", "heron-engineer", "ops/general"),
        row("bmain", "home-beta-main", "projects/beta"), row("bbuild", "home-beta-builder", "projects/beta"), row("cmain", "home-capped-main", "projects/capped"), row("cbuild", "home-capped-builder", "projects/capped")]
(T / "sala/a/session-registry.json").write_text(json.dumps({"schema": 1, "machine": "a", "written": "2026-10-22T07:00:00Z", "sessions": {r["id"]: r for r in ROWS}}), encoding="utf-8")
def page(rel, front):
    q = T / "brain" / rel; q.parent.mkdir(parents=True, exist_ok=True); q.write_text("---\n" + front + "\n---\n\n# x\n", encoding="utf-8")
page("projects/alpha.md", "type: project\ntitle: Alpha\ndisplay-name: home-sparrow\nagents:\n  home-sparrow-docs: keeps the docs\n  home-sparrow-main: talks to Oliver\n  background:\n    home-sparrow-notes: keeps the notes\n    home-sparrow-builder: builds\nstatus: active")
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
from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route; from stackshot.fleet import client; from stackshot.model import model as M; from stackshot.model import ids as _model_ids
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
    return server._client_post(me, "item-open", {k: v for k, v in b.items() if v is not None})
def open_for(marker, project="projects/alpha"): return [g for g, m_ in server._itemopen_open_items(project) if m_ == marker]
def close(shown):
    server._update(_model_ids._norm_id(shown), outcome_text="- done", status="completed", outcome="done", reason="the deep scan is done", sender="home-sparrow-builder")
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
st, e = io_(project="projects/nobuild", mover="home-nobuild-main", step="home-nobuild-main: deep-scan")
check("a page that lists no background agent: 400 that says so", st == 400 and "lists none" in e["error"] and len(items()) == n3, (st, e))
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
st, e = server._client_post(me, "no-such-write", {})
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
check("a project page with no agents: the mover is refused first (it lists none)", st == 400 and len(items()) == n6, (st, e))
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
check("…the store lookup is per project", [m_ for _g, m_ in server._itemopen_open_items("projects/beta")] == ["size:report"] and [m_ for _g, m_ in server._itemopen_open_items("projects/nobuild")] == [], server._itemopen_open_items("projects/beta"))
close(a["item"]); st5, a3 = io_(marker="size:report")
check("…closing one project's item leaves the other's open: the first project files a new item, the second still answers its own", st5 == 200 and a3["item"] != a["item"] and a3["repeat"] is False and item(b["item"])["status"] == "open"
      and io_(marker="size:report", project="projects/beta", mover="home-beta-builder", step="home-beta-builder: deep-scan", subject="x")[1]["item"] == b["item"], (st5, a3))
close(a3["item"]); close(b["item"])

# ---- 7c. a cap of 10 open items per project
CAP = server._ITEMOPEN_OPEN_MAX
cp = dict(project="projects/capped", mover="home-capped-builder", step="home-capped-builder: deep-scan", subject="Deep-scan")
check("the cap is 10", CAP == 10, CAP)
ids = []
for i in range(CAP):
    st, o = io_(marker=f"size:run{i}", **cp); ids.append(o.get("item") if st == 200 else None)
check("ten different markers file ten open items on one project", all(ids) and len({*ids}) == CAP and len(server._itemopen_open_items("projects/capped")) == CAP, ids)
nc = len(items()); pushed.clear()
st, e = io_(marker="size:run-new", **cp)
check("an eleventh marker is refused: 400 that names the cap and says an open item must close first; nothing filed, no one told", st == 400 and "cap is 10" in e["error"] and "must close" in e["error"] and len(items()) == nc, (st, e)); settle()
check("…nobody was told of the refused call", pushed == [], pushed)
st, o = io_(marker="size:run3", **cp)
check("…a repeat of an open marker at the cap is still answered (never counted as new)", st == 200 and o["item"] == ids[3] and o["repeat"] is True and len(items()) == nc, (st, o))
st, o = io_(marker="size:report", project="projects/beta", mover="home-beta-builder", step="home-beta-builder: deep-scan", subject="x")
check("…the cap is per project: another project still files", st == 200 and o["repeat"] is False, (st, o)); close(o["item"]) if st == 200 else None
close(ids[0])
check("…closed items do not count", len(server._itemopen_open_items("projects/capped")) == CAP - 1, len(server._itemopen_open_items("projects/capped")))
st, o = io_(marker="size:run-new", **cp)
check("…after one item closes, a new marker files again, and the cap holds again", st == 200 and o["repeat"] is False and io_(marker="size:run-next", **cp)[0] == 400, (st, o))
for g in ids[1:] + ([o["item"]] if st == 200 else []): close(g)
check("…everything closed, the project is empty again", server._itemopen_open_items("projects/capped") == [], server._itemopen_open_items("projects/capped"))

# ---- 8. concurrency: one marker, many calls, one item
n7 = len(items()); res = []
ths = [threading.Thread(target=lambda: res.append(io_(marker="test_trim:race"))) for _ in range(8)]
[t.start() for t in ths]; [t.join() for t in ths]
check("eight threads calling with one marker at once file one item and all get its id", len(items()) == n7 + 1 and len({r[1]["item"] for r in res}) == 1 and all(r[0] == 200 for r in res) and sum(1 for r in res if not r[1]["repeat"]) == 1, res[:3])
close(res[0][1]["item"]); settle()

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
