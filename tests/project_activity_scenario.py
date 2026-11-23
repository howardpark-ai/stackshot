"""Scenario test for the project activity read: per project, the newest anchor notice from outside and the newest input of the board's owner
(stackshot/service/project_activity.py, GET /client/project-activity, client.py project-activity) - fixture pages, sessions, routing logs, items and stamp files in a temporary store, no network, no model call.

  1  the anchor time: what counts (a delivered anchor notice, one the router holds, a direct one delivered to a session) and what does not (a routine event on the fleet's own repository, a log-only direct anchor, the hub's
     own warning, a board notice, a message, a line that is no JSON, a time in the future); the newest such line wins whatever follows it in the file; a sub-page's notices count for its project
  2  the owner's board actions: an answer, a decision, a comment on the board or on GitHub, on an open or a closed item; not a step the server settled on a mail, not a time that is no time; the newest wins; an item
     filed on a sub-page counts for its project; an item with no answers or no project counts for none
  3  the owner's front-chat messages: a stamp file of a front agent counts for its project, and so does the only session of a one-session project; a background agent's, an unknown session's, a stamp in the future and a
     stamp that is no number do not; two front agents of one project give the newer; no stamp folder is no stamps, while an unreadable folder, roles that cannot be worked out, an empty page registry with stamps
     present, and a time found while the registry cannot be read all raise Unreadable (a failure is never an empty answer)
  4  the answer: only a project with either time has a row; each time is a whole second or null; the owner's time is the newer of his board action and his front-chat message; rows are by key
  5  the endpoint: the machine token, JSON, no cache, a read (a POST is no write), the empty board answers {"projects": {}}, an unreadable registry with stamps present answers 503 with the reason
  6  the client: plain lines, `-` for none, --json, nothing printed for an empty answer, a server that cannot be asked or refuses is exit 1 with the reason on stderr and nothing on stdout (never an empty answer), misuse
  7  the text: the docs name the read, the served text is neutral (no machine, fleet-tool or person names), and the module only reads

    tests/run-suite project_activity       -> exit 0 / 1"""
import contextlib, io, json, logging, os, pathlib, re, sys, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="pactivity-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml(), owner=True)
toml, n = re.subn(r'(?m)^session_links = "[^"]*"', 'session_links = ""', toml); assert n == 1      # never the host's fleet store
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
for pat, rep in ((r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]'), (r'(?m)^ui_open = true', 'ui_open = false'),
                 (r'(?m)^allowed_emails = \[[^\]]*\]', 'allowed_emails = ["oliver@example.org"]'), (r'(?m)^require_marks = true', 'require_marks = false')):
    toml, n = re.subn(pat, rep, toml); assert n == 1, pat
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/site", "state/prompts", "secrets", "touch", "brain/projects"): (T / d).mkdir(parents=True)
(T / "state/site/favicon.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"/>')
(T / "store/next-id").write_text("100"); (T / "store/anchors.json").write_text("{}")

BUILDS, FRONT = "builds, merges and releases the code", "Oliver's point of contact"
def page(front=(), back=None, **kw):
    back = back or {}
    return {"title": "x", "name": "x", "org": "home", "tags": [], "type": "project", "session": kw.pop("session", ""), "status": kw.pop("status", "active"), "board": [], "board_row": False,
            "updated": 1, "mirror": "", "agents": {**{f: FRONT for f in front}, **back}, "back_agents": dict(back), **kw}
PAGES = {
    "projects/solo": page(["solo-main"], session="solo"),
    "projects/solo/side": page(["side-main"], session="side"),                       # a sub-page of solo
    "projects/alpha": page(["alpha-main", "alpha-desk"], {"alpha-builder": BUILDS}, session="alpha"),
    "projects/quiet": page(["quiet-main"], session="quiet"),                          # never has anything
    "projects/other": page(["other-main"], session="other"),
    "projects/one": page([], session="one-session"),                                  # a one-session project: a name line, no agents map
}
def publish(**changes):
    pg = dict(PAGES)
    for k, v in changes.items():
        if v is None: pg.pop(k, None)
        else: pg[k] = v
    p = T / "store/projects.json"; tp = T / "store/projects.json.new"
    tp.write_text(json.dumps({"pages": pg})); os.replace(tp, p)
    for key in pg:
        f = T / f"brain/{key}.md"; f.parent.mkdir(parents=True, exist_ok=True); f.write_text(f"---\ntitle: {key}\n---\n# {key}\n\n## Current state\n\nx\n\n<!-- timeline -->\n")
publish()
(T / "store/project-record.json").write_text(json.dumps({"schema": 1, "ids": {}, "pending_agents": {}, "marks": {}}))
NAMES = ("solo-main", "side-main", "alpha-main", "alpha-desk", "alpha-builder", "quiet-main", "other-main", "loose-session", "one-session")
U = {n: "%08x-0000-4000-8000-%012x" % (i, i) for i, n in enumerate(NAMES, 1)}
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a", "url": "", "seen": "x"} for n, u in U.items()}))

sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))

from stackshot.core import config as _cfg
from stackshot.router import routing
from stackshot.fleet import client
from stackshot.web import server
from stackshot.service import project_activity as pa
from stackshot.projects import projects as _prj
from stackshot.anchors import anchors as _anc
NOW = time.time()
for k in PAGES: _prj.ref(k)        # every page has its project id, as the record gives them

def routing_reset():
    for p in routing.DIR.glob("*.jsonl"): p.unlink()
def notice(key, ts, **kw):
    """One routing line as the hub writes it (routing.record), at `ts`; → its id."""
    base = dict(kind="anchor", to="solo-main", label="slack anchor", who="someone", text="a post", target="project-wide", pilot=True, ts=ts)
    base.update(kw)
    return routing.record(key, **base)
def anchors(): return pa.anchor_times(NOW)

# ---- 1. the anchor time
routing_reset()
check("1a: no routing log: no time", anchors() == {})
notice("projects/solo", NOW - 5000)
check("1b: a delivered anchor notice counts, at its own time", anchors() == {"projects/solo": NOW - 5000}, anchors())
notice("projects/solo", NOW - 4000, to="", live=True)
check("1c: one the router holds (live, no recipient) counts: it is an event all the same", anchors()["projects/solo"] == NOW - 4000, anchors())
notice("projects/solo", NOW - 3000, target="direct", to="solo-main", pilot=False)
check("1d: a direct anchor delivered to a session counts", anchors()["projects/solo"] == NOW - 3000, anchors())
newest = NOW - 3000
routing.record_auto("projects/solo", "merged", "log-only: ci_passed on the fleet's own repository", kind="anchor", label="github anchor", who="ci", text="CI passing", target="project-wide", pilot=True, ts=NOW - 100)
check("1e: a routine event on the fleet's own repository (filed log-only, ruled by the instance) does not count, though it is the newest line", anchors()["projects/solo"] == newest, anchors())
notice("projects/solo", NOW - 90, target="direct", to="", pilot=False, reason="direct: log only")
check("1f: a log-only direct anchor (no recipient, nothing delivered) does not count", anchors()["projects/solo"] == newest, anchors())
notice("projects/solo", NOW - 80, who=pa.HUB_SENDER, label="slack anchor", text="cannot read it")
check("1g: the hub's own warning that an anchor cannot be read does not count", anchors()["projects/solo"] == newest, anchors())
routing.record("projects/solo", kind="board", to="solo-main", label="board x", who="stackshot", text="a board notice", ts=NOW - 70)
routing.record("projects/solo", kind="message", to="solo-main", label="message", who="other-main", text="a message", ts=NOW - 60)
check("1h: a board notice and a message are other kinds and do not count", anchors()["projects/solo"] == newest, anchors())
notice("projects/solo", NOW + 86400)
check("1i: a time a day ahead of the clock did not happen: left out", anchors()["projects/solo"] == newest, anchors())
f = routing._file("projects/solo")
with open(f, "a", encoding="utf-8") as fh: fh.write('{"id": "zzzzzz", "kind": "anchor", "ts": "soon"}\nnot json at all "kind": "anchor"\n{"id": "yyyyyy", "kind": "anchor", "ts": true}\n\n')
check("1j: a line that is no JSON, a time that is no number and a bool are skipped, and the file is still read", anchors()["projects/solo"] == newest, anchors())
notice("projects/solo", NOW - 3500)
check("1k: the newest counted line wins, not the last one written (a backlog line after a newer one)", anchors()["projects/solo"] == newest, anchors())
notice("projects/solo/side", NOW - 1000)
notice("projects/alpha", NOW - 20000, text="x")
check("1l: a sub-page's notice counts for its project, and the newer of the two is kept", anchors() == {"projects/solo": NOW - 1000, "projects/alpha": NOW - 20000}, anchors())
routing.record("projects/quiet", kind="board", to="quiet-main", label="board x", who="stackshot", text="a board notice", ts=NOW - 5)
check("1m: a project with only board notices has no anchor time", "projects/quiet" not in anchors(), anchors())
import shutil; shutil.rmtree(routing.DIR)
check("1n: a routing folder that is missing reads as no time", anchors() == {}, anchors())
routing.DIR.mkdir(parents=True, exist_ok=True)

# ---- 2. the owner's board actions
def item(n, project, answers=None, status="open", letter="a", **meta):
    m = {"project": project, **meta}
    if answers is not None: m["answers"] = answers
    (T / f"store/{letter}").mkdir(parents=True, exist_ok=True)
    (T / f"store/{letter}/{n}.json").write_text(json.dumps({"id": f"{letter}{n}", "subject": f"item {n}", "status": status, "metadata": m}))
def clear_items():
    for p in (T / "store").glob("*/*.json"): p.unlink()
def ans(ts, via="board", kind="decision", **kw): return {"ts": ts, "kind": kind, "via": via, **kw}
def answers(): return pa.answer_times(NOW)
check("2a: no items: no time", answers() == {})
item(1, "projects/solo", [ans(NOW - 9000, text="a note", kind="comment")])
check("2b: a board comment counts, for the item's project, at its time", answers() == {"projects/solo": NOW - 9000}, answers())
item(2, "projects/solo", [ans(NOW - 8000, choice="Yes"), ans(NOW - 8500, via="github", kind="comment")])
check("2c: a decision and a GitHub comment count; the newest of an item's answers wins", answers()["projects/solo"] == NOW - 8000, answers())
item(3, "projects/solo", [ans(NOW - 7000, via="mail", server_note="the mail he sent settled the step")], status="closed")
check("2d: a step the server settled on a mail (via mail) is no action of his: it does not count, though it is the newest", answers()["projects/solo"] == NOW - 8000, answers())
item(4, "projects/alpha", [ans(NOW - 6000, via="github", kind="comment")], status="closed")
check("2e: an answer on a closed item counts", answers()["projects/alpha"] == NOW - 6000, answers())
item(5, "projects/solo/side", [ans(NOW - 500, kind="comment")])
check("2f: an item filed on a sub-page counts for the project that owns it", answers()["projects/solo"] == NOW - 500 and "projects/solo/side" not in answers(), answers())
item(6, "projects/other", [ans("yesterday"), ans(True), ans(NOW + 86400), ans(0), "junk", {"kind": "comment"}])
check("2g: a time that is a word, a bool, zero or a day ahead, a record that is no object and one with no time count for nothing", "projects/other" not in answers(), answers())
item(7, "projects/other", [])
item(8, "projects/other")
item(9, "", [ans(NOW - 10)])
item(10, "projects/other", "not a list")
check("2h: an item with no answers, an empty list, no project or a list that is no list counts for none", "projects/other" not in answers() and "" not in answers(), answers())
(T / "store/a/11.json").write_text("{not json"); (T / "store/a/12.json").write_text('"answers"'); (T / "store/a/13.json").write_text('{"metadata": "x", "answers": 1}')
check("2i: an item file that cannot be read or has the wrong shape is skipped, the rest are read", answers().get("projects/solo") == NOW - 500, answers())
item(14, "projects/alpha", [ans(NOW - 400, kind="comment")], letter="s")
check("2j: items of every letter are read", answers()["projects/alpha"] == NOW - 400, answers())

# ---- 3. the owner's front-chat messages
def stamp(who, ago=0, text=None):
    (T / "state/prompts" / U[who]).write_text(text if text is not None else f"{NOW - ago:.0f}")
def at(ago): return float(f"{NOW - ago:.0f}")      # the second a stamp written `ago` seconds back holds
def prompts(): return pa.prompt_times(NOW)
check("3a: no stamp: no time", prompts() == {})
stamp("solo-main", 600)
check("3b: a front agent's stamp counts for its project", prompts() == {"projects/solo": at(600)}, prompts())
stamp("alpha-builder", 5)
check("3c: a background agent's pane is not his front chat: its stamp does not count", "projects/alpha" not in prompts(), prompts())
stamp("loose-session", 5)
(T / "state/prompts" / "ffffffff-0000-4000-8000-ffffffffffff").write_text(f"{NOW - 5:.0f}")
check("3d: a session no page lists, and a stamp of a session the fleet does not know, count for none", set(prompts()) == {"projects/solo"}, prompts())
stamp("quiet-main", text="never")
stamp("other-main", 86400 * -2)
check("3e: a stamp that is no number, and one two days ahead of the clock, count for nothing", set(prompts()) == {"projects/solo"}, prompts())
stamp("alpha-main", 4000); stamp("alpha-desk", 1000)
check("3f: two front agents of one project give the newer stamp", prompts()["projects/alpha"] == at(1000), prompts())
stamp("side-main", 30)
check("3g: a front agent of a sub-page counts for its project, the newer of the two", prompts()["projects/solo"] == at(30) and "projects/solo/side" not in prompts(), prompts())
(T / "state/prompts/.tmp-partial").write_text(f"{NOW:.0f}"); (T / "state/prompts/emptyfile").write_text("")
check("3h: a half-written temp stamp and an empty file are left out and the rest read", set(prompts()) == {"projects/solo", "projects/alpha"}, prompts())
_state = _cfg.state
try:
    _cfg.state = lambda *a: (_ for _ in ()).throw(FileNotFoundError("no folder"))
    with contextlib.redirect_stderr(io.StringIO()): r_nofolder = pa.prompt_times(NOW)
finally: _cfg.state = _state
check("3i: a stamp folder that does not exist is no stamps: no time, nothing raised", r_nofolder == {}, r_nofolder)
def raises(fn, *a):
    try: fn(*a)
    except pa.Unreadable as e: return str(e)
    except Exception as e: return f"WRONG {e.__class__.__name__}: {e}"
    return None
try:
    _cfg.state = lambda *a: (_ for _ in ()).throw(PermissionError("denied"))
    r_deny = raises(pa.prompt_times, NOW)
finally: _cfg.state = _state
check("3j: a stamp folder that exists but cannot be read raises Unreadable (never an empty answer)", r_deny and "stamp folder" in r_deny, r_deny)
stamp("one-session", 20)
check("3k: the only session of a one-session project (no agents map; session_roles calls it keeper) is its front chat: its stamp counts", prompts().get("projects/one") == at(20), prompts())
_roles = _anc.file_roles
try:
    _anc.file_roles = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("roles broke"))
    r_roles = raises(pa.prompt_times, NOW)
finally: _anc.file_roles = _roles
check("3l: roles that cannot be worked out, with stamps present, raise Unreadable", r_roles and "roles cannot be read" in r_roles, r_roles)
def break_registry(): (T / "store/projects.json").write_text("{not json")
break_registry()
r_empty = raises(pa.prompt_times, NOW)
check("3m: an empty page registry (cannot be read) with stamps present raises Unreadable: no stamp is dropped silently", r_empty and "roles are empty" in r_empty, r_empty)
for p in (T / "state/prompts").iterdir(): p.unlink()
check("3n: …but with no stamps the roles are not asked for: no time, no error", raises(pa.prompt_times, NOW) is None and prompts() == {})
notice("projects/solo", NOW - 70)
r_map = raises(pa.activity, NOW)
check("3o: a time found while the page registry cannot be read (the sub-page mapping would fall back to the sub-page's own key) raises Unreadable", r_map and "registry" in r_map, r_map)
routing_reset(); publish()
stamp("solo-main", 600); stamp("alpha-main", 4000); stamp("alpha-desk", 1000); stamp("side-main", 30)
check("3p: the registry published again, the stamps read as before", prompts() == {"projects/solo": at(30), "projects/alpha": at(1000)}, prompts())

# ---- 4. the answer
routing_reset(); clear_items()
for p in (T / "state/prompts").iterdir(): p.unlink()
check("4a: nothing anywhere: no row at all", pa.activity(NOW) == {} and pa.payload(NOW) == {"projects": {}})
notice("projects/solo", NOW - 5000.7)
check("4b: a project with an anchor time only has a row with the owner's time null, the time a whole second", pa.activity(NOW) == {"projects/solo": {"anchor": int(NOW - 5000.7), "owner": None}}, pa.activity(NOW))
item(1, "projects/alpha", [ans(NOW - 3000.2)])
check("4c: a project with a board action only has the anchor time null", pa.activity(NOW)["projects/alpha"] == {"anchor": None, "owner": int(NOW - 3000.2)}, pa.activity(NOW))
stamp("alpha-main", 100)
check("4d: the owner's time is the newer of his board action and his front-chat message", pa.activity(NOW)["projects/alpha"]["owner"] == int(at(100)), pa.activity(NOW))
stamp("alpha-main", 9000)
check("4e: …whichever is newer: a board action newer than the stamp wins", pa.activity(NOW)["projects/alpha"]["owner"] == int(NOW - 3000.2), pa.activity(NOW))
notice("projects/alpha", NOW - 50)
check("4f: both times on one row", pa.activity(NOW)["projects/alpha"] == {"anchor": int(NOW - 50), "owner": int(NOW - 3000.2)}, pa.activity(NOW))
check("4g: only projects that have either time are listed, by key, and every value is an int or null", list(pa.activity(NOW)) == ["projects/alpha", "projects/solo"]
      and all(isinstance(v, int) or v is None for r in pa.activity(NOW).values() for v in r.values()), pa.activity(NOW))
check("4h: payload wraps the rows as {\"projects\": …}", pa.payload(NOW) == {"projects": pa.activity(NOW)})
real_now = pa.activity()
check("4i: with no clock given it uses the clock", isinstance(real_now, dict) and set(real_now) == {"projects/alpha", "projects/solo"}, real_now)

# ---- 5. the endpoint
from starlette.testclient import TestClient
tok = open(client.mint("testbox")).read().strip(); H = {"Authorization": "Bearer " + tok}
app = server.mcp.http_app()
with TestClient(app) as c:
    r = c.get("/client/project-activity"); check("5a: no token: 401, and nothing is read", r.status_code == 401 and "projects/solo" not in r.text, r.status_code)
    r = c.get("/client/project-activity", headers={"Authorization": "Bearer " + "x" * 43}); check("5b: a wrong token: 401", r.status_code == 401 and "projects/solo" not in r.text, r.status_code)
    r = c.post("/client/project-activity", headers=H, json={}); check("5c: it is a read: a POST to it is no write", r.status_code in (400, 404, 405), (r.status_code, r.text[:100]))
    r = c.get("/client/project-activity", headers=H)
    body = r.json() if r.status_code == 200 else {}
    check("5d: with the machine's token: 200, JSON, no cache", r.status_code == 200 and r.headers["content-type"].startswith("application/json") and r.headers["cache-control"] == "no-store", (r.status_code, r.headers.get("content-type")))
    check("5e: the body is {\"projects\": {key: {anchor, owner}}} with the rows above", set(body) == {"projects"} and set(body["projects"]) == {"projects/alpha", "projects/solo"}
          and all(set(v) == {"anchor", "owner"} for v in body["projects"].values()) and abs(body["projects"]["projects/solo"]["anchor"] - int(NOW - 5000.7)) <= 1, body)
    routing_reset(); clear_items()
    for p in (T / "state/prompts").iterdir(): p.unlink()
    r = c.get("/client/project-activity", headers=H); check("5f: an empty board answers 200 {\"projects\": {}}", r.status_code == 200 and r.json() == {"projects": {}}, r.text)
    stamp("solo-main", 5); break_registry()
    r = c.get("/client/project-activity", headers=H)
    check("5f2: a registry that cannot be read with a stamp present: 503 with the reason and no cache, never 200 with a smaller answer", r.status_code == 503 and "roles are empty" in r.text and r.headers["cache-control"] == "no-store", (r.status_code, r.text[:200]))
    publish(); (T / "state/prompts" / U["solo-main"]).unlink()
    r = c.get("/client/recycle-wanted", headers=H); check("5g: the neighboring reads are as before", r.status_code == 200 and r.text.split()[0].isdigit(), r.text)
check("5h: client.py knows the read", "project-activity" in client.READS)

# ---- 6. the client
ROWS = {"projects": {"projects/b": {"anchor": None, "owner": 1700000200}, "projects/a": {"anchor": 1700000100, "owner": None}, "projects/c": {"anchor": 5, "owner": 6}}}
def run(argv, got):
    out, err = io.StringIO(), io.StringIO(); client.get = got
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err): rc = client.main(["client.py", "project-activity", *argv])
    return rc, out.getvalue(), err.getvalue()
ok = lambda what, key="", timeout=10.0: (200, json.dumps(ROWS)) if what == "project-activity" else (404, "")
rc, out, err = run([], ok)
check("6a: plain: one line per project by key, `<key> <anchor> <owner>`, - for none", rc == 0 and out == "projects/a 1700000100 -\nprojects/b - 1700000200\nprojects/c 5 6\n" and err == "", (rc, out, err))
rc, out, err = run(["--json"], ok)
check("6b: --json: the server's object, whole", rc == 0 and json.loads(out) == ROWS and out.count("\n") == 1 and err == "", (rc, out, err))
empty = lambda what, key="", timeout=10.0: (200, '{"projects": {}}')
check("6c: no project has either time: plain prints nothing, --json prints the empty object, both exit 0", run([], empty) == (0, "", "") and run(["--json"], empty) == (0, '{"projects": {}}\n', ""), (run([], empty), run(["--json"], empty)))
for label, fn in (("the server cannot be asked", lambda *a, **k: (0, "URLError: refused")), ("a refusal", lambda *a, **k: (401, "unauthorized")), ("no token", lambda *a, **k: (401, "no token on this machine")),
                  ("a server error", lambda *a, **k: (500, "oops")), ("an answer that is not the object", lambda *a, **k: (200, "[]")), ("a body that is no JSON", lambda *a, **k: (200, "<html>")),
                  ("an object without projects", lambda *a, **k: (200, "{}"))):
    for argv in ([], ["--json"]):
        rc, out, err = run(argv, fn)
        check(f"6d: {label} ({' '.join(argv) or 'plain'}): exit 1, the reason on stderr, nothing on stdout (a failure is never an empty answer)", rc == 1 and out == "" and "project activity not read" in err, (rc, out, err))
for argv in (["--nope"], ["--json", "--json"], ["projects/a"], ["--json", "x"]):
    rc, out, err = run(argv, ok)
    check(f"6e: misuse {argv}: exit 1, the usage on stderr, nothing on stdout, the server not asked", rc == 1 and out == "" and "usage: client.py project-activity [--json]" in err, (rc, out, err))
rc, out, err = run([], lambda *a, **k: (503, "the session roles cannot be read (RuntimeError: x)"))
check("6h: a 503 from the server with its reason: exit 1, the reason on stderr, nothing on stdout", rc == 1 and out == "" and "roles cannot be read" in err and "[503]" in err, (rc, out, err))
def boom(*a, **k): raise RuntimeError("socket")
rc, out, err = run([], boom)
check("6f: an exception in the read is exit 1 with the reason on stderr", rc == 1 and out == "" and "project activity not read (RuntimeError" in err, (rc, out, err))
rows_odd = lambda what, key="", timeout=10.0: (200, json.dumps({"projects": {"projects/x": {"anchor": "soon", "owner": True}, "projects/y": "junk"}}))
rc, out, err = run([], rows_odd)
check("6g: a row whose times are not integers prints `-` for them, whatever the server sent", rc == 0 and out == "projects/x - -\nprojects/y - -\n", (rc, out, err))

# ---- 7. the text
doc = {p: (pathlib.Path(STACK) / "docs" / p).read_text() for p in ("fleet-tool.md", "client-contract.md")}
check("7a: the docs name the read and the module", "project-activity" in doc["fleet-tool.md"] and "project_activity.py" in doc["fleet-tool.md"] and "project-activity" in doc["client-contract.md"], [k for k, v in doc.items() if "project-activity" not in v])
src = pathlib.Path(STACK, "stackshot/service/project_activity.py").read_text()
check("7b: the module only reads: no save, no routing record, no publish, no push, no subprocess", not re.search(r"\b(_writes|save\(|\.record\(|record_auto|publish|subprocess|\.write_text|write_bytes|os\.replace|open\([^)]*[\"']w)", src.split('"""', 2)[2]), re.findall(r"\b(_writes|save\(|\.record\(|record_auto|publish|subprocess|write_text|open\([^)]*[\"']w)", src))
_csrc = pathlib.Path(STACK, "stackshot/fleet/client.py").read_text(encoding="utf-8"); usage = _csrc[_csrc.index("  client.py project-activity"):_csrc.index("  client.py recycle-due")]
served = usage + src.split('"""', 2)[1] + (pathlib.Path(STACK, "stackshot/web/routes/client_api.py").read_text().split('what == "project-activity"')[1].split("\n")[0])
check("7c: the served text names no machine and no fleet tool by product name", not re.search(r"(?i)\bhp-|\bsala\b|salamander|\bboard#\d", served), re.findall(r"(?i)\bhp-\w+|\bsala\b|salamander|board#\d+", served))
check("7d: the served text has no Hangul", not re.search(r"[\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]", served))
check("7e: the usage says what is counted and what is not, and that a failure is exit 1", all(w in usage for w in ("anchor notice from outside", "front-chat", "a message", "routine event", "Exit 0", "1 and the reason on stderr")), usage[:300])

print(f"project_activity: {len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
