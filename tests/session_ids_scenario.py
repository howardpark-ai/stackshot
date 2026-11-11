"""Scenario test for sala's permanent session id, step B of the permanent-id work (the design doc) — fixture data, no live store, no network, no server process (the server module is imported and called in-process,
on a temporary config; the sala registry is a fixture file in a temporary directory, never the host's).

Covers: the resolver (a sala id, a name, an alias or a transcript id → one sala id; a name two live sessions carry, two retired sessions carry,
or no one carries → None; a name a live and a retired session carry → the live one; a registry that is missing, garbled or of another schema → every
lookup None; a file changed on disk read again; display name, delivery address, same, expand); the owner an item stores (the sala id when the
registry resolves the name, the old stored value when it does not or when it is ambiguous); a renamed session (the owner stored as its id shows its
new name in get and on the web pages, the needs gate still matches by the old name and by the id, a write by the id passes); a transcript id left
behind by a fresh start (resolves through the registry's transcripts, and the client API's owner lookup finds the item by the new transcript id);
no registry at all (every value stored and shown as before); delivery (a message to a sala id goes to the session's name, the inbox keys a line by
the name, a hold listing the id holds it); roles.json (the extra `ids` map, `sessions` unchanged); the GitHub mirror's words; and the migration
(dry run changes nothing, apply rewrites open items only, a closed item is untouched, ambiguous and cloud values are kept with the reason, a second
run changes nothing, holds and roles.json follow).

    tests/run-suite session_ids        → exit 0 / 1"""
import hashlib, json, os, re, sys, pathlib, tempfile, logging, subprocess, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="sidtest-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = ""', f'session_links = "{tmp}/sala"', 1); assert f'session_links = "{tmp}/sala"' in toml   # the fixture registry, never the host's sala store
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1   # this suite is about session ids, its writes replace next wholesale; the checklist has its own suite: checklist
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet", PUSH_INBOX_WAIT="0.05"); os.environ.pop("STACKSHOT_URL", None)
os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
for d in ("store/a", "fleet/a", "state/anchor-hub", "brain/projects", "brain/infra", "sala/a"): (T / d).mkdir(parents=True)
SALA = T / "sala/a/session-registry.json"

def uid(n): return f"00000000-0000-4000-8000-{n:012d}"
# sala ids (S), claude transcript ids (T). home-sparrow-main: renamed later, restarted once (T1a then T1b); site-builder: renamed to site-build.
S = {"main": uid(101), "eng": uid(102), "dup_old": uid(103), "dup_new": uid(104), "twin1": uid(105), "twin2": uid(106), "gone1": uid(107), "gone2": uid(108), "docs": uid(109)}
Tr = {"main_a": uid(201), "main_b": uid(202), "eng": uid(203), "dup_old": uid(204), "dup_new": uid(205), "twin1": uid(206), "twin2": uid(207), "gone1": uid(208), "gone2": uid(209),
      "docs": uid(210), "fresh": uid(211)}
def row(key, name, state="live", aliases=(), transcripts=(), **kw):
    return {"id": S[key], "name": name, "aliases": list(aliases), "project": None, "project_key": None, "role": None, "lane": "max", "model": "opus", "effort": "medium", "pane": name,
            "cwd": "/home/user", "state": state, "created": "2026-10-21T21:00:00Z", "retired_at": None if state == "live" else "2026-10-22T01:00:00Z",
            "transcripts": [{"id": Tr[t], "machine": "a", "at": f"2026-10-21T2{i}:00:00Z", "why": "import" if i == 1 else "fresh"} for i, t in enumerate(transcripts, 1)], **kw}
def registry(rows, schema=1):
    return {"schema": schema, "machine": "a", "written": "2026-10-22T07:00:00Z", "sessions": {r["id"]: r for r in rows}}
ROWS = [row("main", "home-sparrow-main", aliases=["home-sparrow"], transcripts=["main_a", "main_b"]),
        row("eng", "site-builder", transcripts=["eng"]),
        row("dup_old", "home-reused", state="retired", transcripts=["dup_old"]), row("dup_new", "home-reused", transcripts=["dup_new"]),
        row("twin1", "home-twin", transcripts=["twin1"]), row("twin2", "home-twin", transcripts=["twin2"]),
        row("gone1", "home-gone", state="retired", transcripts=["gone1"]), row("gone2", "home-gone", state="retired", transcripts=["gone2"]),
        row("docs", "home-sparrow-docs", transcripts=["docs"])]
def put_registry(rows=ROWS, schema=1):
    tmp_ = SALA.with_name(".r.tmp"); tmp_.write_text(json.dumps(registry(rows, schema)), encoding="utf-8"); os.replace(tmp_, SALA)
    st = os.stat(SALA); os.utime(SALA, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000 * put_registry.n)); put_registry.n += 1   # a distinct mtime for each write
put_registry.n = 1

# the heartbeat the server holds: the pane of each session under its current transcript (T1b, not T1a); the fresh start sala has not recorded yet
FLEET = {Tr["main_b"]: "home-sparrow-main", Tr["eng"]: "site-builder", Tr["dup_new"]: "home-reused", Tr["twin1"]: "home-twin", Tr["twin2"]: "home-twin", Tr["docs"]: "home-sparrow-docs"}
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0", "online": {"ok": True}}))
def put_fleet(m): (T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a", "url": "", "seen": "2026-10-22T07:00:00Z"} for u, n in m.items()}))
put_fleet(FLEET)
(T / "store/next-id").write_text("10"); (T / "store/anchors.json").write_text("{}")
def page(rel, front):
    q = T / "brain" / rel; q.parent.mkdir(parents=True, exist_ok=True); q.write_text("---\n" + front + "\n---\n\n# x\n", encoding="utf-8")
# the page lists the engineer under its OLD name: the rename has not reached the page
page("projects/alpha.md", "type: project\ntitle: Alpha\ndisplay-name: home-sparrow\nagents:\n  home-sparrow-main: talks to Oliver\n  home-sparrow-docs: keeps the docs\n  background:\n    site-builder: builds\nstatus: active")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:600]}" if got is not None else ""))

from stackshot.projects import pages as p
p.cmd_registry(quiet=True)
from stackshot.fleet import sessions_registry as sr; from stackshot.anchors import anchors as A; from stackshot.fleet import inbox; from stackshot.fleet import push
sr.TTL = 0          # the directory is looked at on every call here: the test rewrites the registry at once (production trusts a look for a second)
from stackshot.web import server
from stackshot.projects import project_registry as _projects_registry
from stackshot.core import store as _core_store
from stackshot.web.ui import render as ui_render
server._publish = lambda: None
def create(owner, **kw): return server.stackshot_create(subject="[home] a thing", description="- Goal: A thing\n- It lives here\n- Done when done", project="projects/alpha", owner=owner, **{"mover": owner, "next": f"{owner}: carry on", **kw})
def item(gid): return json.loads(server._path(gid).read_text(encoding="utf-8"))
def meta(gid): return item(gid)["metadata"]

# ---- 1. no registry yet: everything behaves as before
check("no registry file: every lookup is None", sr.resolve("home-sparrow-main") is None and sr.resolve(Tr["main_b"]) is None and sr.display_name("home-sparrow-main") is None
      and not sr.available() and sr.delivery(S["main"]) == S["main"] and sr.same("a", "b") is None)
check("no registry: canonical is the old rule (a live pane's name → its transcript uuid)", A.canonical("home-sparrow-main") == Tr["main_b"], A.canonical("home-sparrow-main"))
r = create("home-sparrow-main"); g0 = r.split()[1]
check("no registry: the owner is stored as the transcript uuid, as before", meta(g0)["owner"] == Tr["main_b"], meta(g0))
check("no registry: get shows the owner as it always did (the stored id's name is not looked up)", "mover: home-sparrow-main" in server.stackshot_get(g0), server.stackshot_get(g0))
rr = create("home-sparrow-docs", needs=["site-builder"]); g_docs0 = rr.split()[1]
check("no registry: a needs entry is stored as its name, as before", meta(g_docs0)["needs"] == ["site-builder"], meta(g_docs0))

# ---- 2. the resolver
put_registry()
check("the registry is read from the directory [client] session_links names", sr.available() and len(sr.load().rows) == len(ROWS))
check("resolve: a sala id", sr.resolve(S["main"]) == S["main"])
check("resolve: a name, an alias", sr.resolve("home-sparrow-main") == S["main"] and sr.resolve("home-sparrow") == S["main"])
check("resolve: a transcript id, an old one and the current one", sr.resolve(Tr["main_a"]) == S["main"] and sr.resolve(Tr["main_b"]) == S["main"])
check("resolve: a name a live and a retired session carry → the live one", sr.resolve("home-reused") == S["dup_new"])
check("resolve: a name two live sessions carry → None (never a pick)", sr.resolve("home-twin") is None)
check("resolve: a name two retired sessions carry → None", sr.resolve("home-gone") is None)
check("resolve: nothing, an empty string, a cloud id, an unknown uuid → None", all(sr.resolve(x) is None for x in ("nobody", "", "  ", "cse_0123456789abcdefghijklmn", uid(999))))
check("resolve: case of an id does not matter; padding does not", sr.resolve(S["main"].upper()) == S["main"] and sr.resolve("  home-sparrow-main ") == S["main"])
check("explain: the reason it cannot tell", sr.explain("home-twin")[1].startswith("ambiguous: 2 sessions") and "no registry session" in sr.explain("nobody")[1], (sr.explain("home-twin"), sr.explain("nobody")))
check("display_name: the current name, for an id, an alias, an old transcript", {sr.display_name(x) for x in (S["main"], "home-sparrow", Tr["main_a"])} == {"home-sparrow-main"} and sr.display_name("nobody") is None)
check("delivery: a sala id → the name now; anything else as it came", sr.delivery(S["main"]) == "home-sparrow-main" and sr.delivery("home-sparrow") == "home-sparrow" and sr.delivery(Tr["main_b"]) == Tr["main_b"])
check("same: True/False when both resolve, None when either cannot be told", sr.same(Tr["main_a"], "home-sparrow") is True and sr.same("home-sparrow-docs", "home-sparrow-main") is False and sr.same("home-twin", "home-sparrow-main") is None)
check("expand: a hold list in either form", sr.expand(["home-sparrow-main", "x"]) == {"home-sparrow-main", "x", S["main"]})
# a changed file is read again; a garbled one says nothing; another schema says nothing
put_registry([r_ if r_["id"] != S["main"] else {**r_, "name": "home-sparrow-lead", "aliases": ["home-sparrow", "home-sparrow-main"]} for r_ in ROWS])
check("a file changed on disk is read again (a rename: the new name resolves, the old one is an alias)", sr.display_name(S["main"]) == "home-sparrow-lead" and sr.resolve("home-sparrow-main") == S["main"])
sr.STALE = 0          # (the stale-on-error window has its own checks below)
SALA.write_text("{not json", encoding="utf-8"); os.utime(SALA, ns=(1, 1))
check("a garbled file (no grace): every lookup is None and nothing raises", sr.resolve(S["main"]) is None and sr.display_name("home-sparrow-main") is None and sr.names_of("x") == [] and sr.all_names() == {})
put_registry(schema=2)
check("a registry of another schema is not read", sr.resolve(S["main"]) is None)
SALA.unlink()
check("a removed file: none", sr.resolve(S["main"]) is None and not sr.available())
sr.STALE = 1800.0
put_registry()

# ---- 2b. a read that fails after a good one (M2), the real TTL path, rows of the wrong shape, a resolver that never raises
put_registry(); sr.resolve(S["main"])
SALA.write_text("{torn", encoding="utf-8"); os.utime(SALA, ns=(2, 2))
check("stale on error: a torn file is served from the last good read", sr.resolve(S["main"]) == S["main"] and sr.display_name(S["main"]) == "home-sparrow-main", sr.display_name(S["main"]))
sr.STALE = 0.3; sr.reset(); time.sleep(0.4); sr.reset()
check("stale on error: …and dropped once the window is over", sr.resolve(S["main"]) is None and not sr.available())
sr.STALE = 1800.0
put_registry(); sr.resolve(S["main"])
put_registry(schema=2)
check("a file that reads but is another schema is not stood in for by the last good read", sr.resolve(S["main"]) is None)
put_registry(); sr.resolve(S["main"])
SALA.write_text("{torn", encoding="utf-8"); os.utime(SALA, ns=(3, 3))
sr.STALE = 0.3; sr.reset(); time.sleep(0.15)
check("stale on error: still served inside the window (TTL 0 path)", sr.resolve(S["main"]) == S["main"])
time.sleep(0.3)
check("stale on error: the window ends by itself, with no new write of the file (a cached read does not outlive it)", sr.resolve(S["main"]) is None)
sr.TTL = 1.0; sr.STALE = 0.3; put_registry(); sr.reset(); sr.resolve(S["main"])
SALA.write_text("{torn", encoding="utf-8"); os.utime(SALA, ns=(4, 4)); sr.reset()
check("stale on error: with the real TTL a torn file stands in at first", sr.resolve(S["main"]) == S["main"])
time.sleep(0.4)
check("stale on error: …and the window ends inside the TTL, by the grace running out", sr.resolve(S["main"]) is None)
sr.TTL = 0; sr.STALE = 1800.0; put_registry()
# the stale window counts from the FIRST failed read, not from the last good one (a registry unchanged for hours, then torn)
import types
clock = [1000.0]; real_time = sr.time; sr.time = types.SimpleNamespace(monotonic=lambda: clock[0])
sr.reset(); put_registry(); sr.resolve(S["main"])
clock[0] += sr.STALE + 100                                   # unchanged for longer than the window
SALA.write_text("{torn", encoding="utf-8"); os.utime(SALA, ns=(6, 6)); sr.reset()
check("stale window: a registry good for hours then torn still serves its good rows", sr.resolve(S["main"]) == S["main"])
clock[0] += sr.STALE - 5; sr.reset()
check("stale window: …until the window since the FIRST failed read is nearly over", sr.resolve(S["main"]) == S["main"])
clock[0] += 10; sr.reset()
check("stale window: …and dropped once it is over", sr.resolve(S["main"]) is None)
put_registry(); sr.reset(); sr.resolve(S["main"]); SALA.write_text("{torn", encoding="utf-8"); os.utime(SALA, ns=(7, 7)); sr.reset(); sr.resolve(S["main"])
clock[0] += sr.STALE - 5; put_registry(); sr.reset(); sr.resolve(S["main"]); SALA.write_text("{torn", encoding="utf-8"); os.utime(SALA, ns=(8, 8)); clock[0] += 10; sr.reset()
check("stale window: a good read in between starts a new window", sr.resolve(S["main"]) == S["main"])
sr.time = real_time; sr.reset(); put_registry()
bad = [row("main", "home-sparrow-main", transcripts=["main_a"]), {**row("eng", "site-builder"), "transcripts": "abc", "aliases": "xyz"}, {**row("docs", "home-sparrow-docs"), "transcripts": [7, None, {"id": 5}, "x"]}, "junk", 5]
SALA.write_text(json.dumps({"schema": 1, "machine": "a", "sessions": {**{r_["id"]: r_ for r_ in bad if isinstance(r_, dict)}, "junk": "junk", "5": 5}}), encoding="utf-8"); os.utime(SALA, ns=(5, 5))
check("rows of the wrong shape (transcripts or aliases not a list, junk rows) are tolerated", sr.resolve("site-builder") == S["eng"] and sr.transcripts(S["eng"]) == [] and sr.resolve("xyz") is None
      and sr.resolve("home-sparrow-docs") == S["docs"] and sr.resolve(Tr["main_a"]) == S["main"])
real_build = sr._build
sr._build = lambda files: (_ for _ in ()).throw(RuntimeError("boom"))
put_registry(); sr.reset()
try: v = sr.resolve(S["main"]); sr.display_name("x"); sr.delivery(S["main"]); raised = False
except Exception: raised = True
check("load never raises, whatever the build does", not raised)
sr._build = real_build; sr.reset()
# the real TTL: a look at the directory is trusted for TTL seconds; the same read is shared; a changed file shows after it
sr.TTL = 1.0; put_registry(); sr.reset(); r1 = sr.load()
put_registry([r_ if r_["id"] != S["main"] else {**r_, "name": "home-sparrow-ttl"} for r_ in ROWS])
check("TTL: within the window the last look stands", sr.load() is r1 and sr.display_name(S["main"]) == "home-sparrow-main", sr.display_name(S["main"]))
time.sleep(1.1)
check("TTL: after it the changed file is read", sr.display_name(S["main"]) == "home-sparrow-ttl", sr.display_name(S["main"]))
r2 = sr.load(); time.sleep(1.1)
check("TTL: an unchanged file is not rebuilt", sr.load() is r2)
sr.TTL = 0; put_registry()

# ---- 2c. a name that is one live row's current name beats another live row's alias (M4); delivery of twins and retired rows (M1)
put_registry([*ROWS, row("gone1", "home-pick", aliases=[]) | {"id": uid(150)}, row("gone2", "home-other", aliases=["home-pick"]) | {"id": uid(151)},
              row("gone1", "home-old", state="retired", aliases=["home-sparrow"], transcripts=["gone1"]) | {"id": uid(152)},
              row("docs", "", transcripts=["fresh"]) | {"id": uid(153), "name": ""}])
check("resolve: a live row's current name beats another live row's alias", sr.resolve("home-pick") == uid(150) and sr.resolve("home-other") == uid(151))
check("resolve: two live rows that both carry it only as an alias is still None", sr.resolve("home-twin") is None)
check("delivery: a live unique name is the address", sr.delivery(S["main"]) == "home-sparrow-main")
check("delivery: a twin name is NOT an address (it could land on the other twin): the latest transcript instead", sr.delivery(S["twin1"]) == Tr["twin1"] and sr.delivery(S["twin2"]) == Tr["twin2"], sr.delivery(S["twin1"]))
check("delivery: a retired row's name is not an address either: its latest transcript", sr.delivery(S["dup_old"]) == Tr["dup_old"] and sr.delivery(uid(152)) == Tr["gone1"], (sr.delivery(S["dup_old"]), sr.delivery(uid(152))))
check("delivery: a live row that is not the one its name resolves to goes by transcript too", sr.delivery(uid(151)) == "home-other")
check("delivery: a row with no name goes to its latest transcript, never a bare sala id", sr.delivery(uid(153)) == Tr["fresh"], sr.delivery(uid(153)))
iid = inbox.put(uid(153), "to a nameless row", "msg", sender="tester"); got = [i for i in inbox._items("msg") if i["id"] == iid][0]
check("inbox.put to a nameless sala id: `to` is its latest transcript, not the id", got["to"] == Tr["fresh"], got)
roles_t = {"home-sparrow": {"role": "x"}, "home-other": {"role": "y"}}
check("_role_name: a retired row never takes a live row's roles entry by alias", server._role_name(roles_t, uid(152)) == "" and server._role_name(roles_t, S["main"]) == "home-sparrow"
      and server._role_name(roles_t, uid(151)) == "home-other", (server._role_name(roles_t, uid(152)), server._role_name(roles_t, S["main"])))
put_registry()

# ---- 3. what an item stores, and what people read
check("canonical: a name → the sala id; an old transcript → the sala id; the id stays; a cse_ id passes", A.canonical("home-sparrow-main") == S["main"] and A.canonical(Tr["main_a"]) == S["main"]
      and A.canonical(S["main"]) == S["main"] and A.canonical("cse_0123456789abcdefghijklmn") == "cse_0123456789abcdefghijklmn")
check("canonical: a name two live sessions carry falls to the old rule (the fleet names two panes: nobody)", A.canonical("home-twin") == "home-twin", A.canonical("home-twin"))
check("canonical: a fresh start the registry does not list yet, which the heartbeat knows under a name the registry resolves, is that session",
      (put_fleet({**FLEET, Tr["fresh"]: "home-sparrow-docs", Tr["docs"]: "home-sparrow-docs-old"}), A.canonical(Tr["fresh"]))[1] == S["docs"], A.canonical(Tr["fresh"]))
put_fleet(FLEET)
r = create("home-sparrow-main"); g1 = r.split()[1]
check("create: the owner is stored as the sala id", meta(g1)["owner"] == S["main"], meta(g1))
check("get shows the owner by name", "mover: home-sparrow-main\n" in server.stackshot_get(g1) + "\n" and S["main"] not in server.stackshot_get(g1), server.stackshot_get(g1))
rr = create("home-sparrow-docs", needs=["site-builder"]); g2 = rr.split()[1]
check("create: a needs entry (the engineer by the name the page lists) is stored as the sala id", meta(g2)["needs"] == [S["eng"]], meta(g2))
check("get shows needs by name", "needs: site-builder" in server.stackshot_get(g2) and S["eng"] not in server.stackshot_get(g2), server.stackshot_get(g2))
rr = create("home-sparrow-docs", needs=[S["eng"]]); g2b = rr.split()[1]
check("create: needs by the sala id passes the gate even though the page lists the old name", meta(g2b)["needs"] == [S["eng"]], (rr, meta(g2b)))
try: create("home-sparrow-docs", needs=["home-twin"]); r = ""
except Exception as e: r = str(e)
check("a name two live sessions carry is not resolved: the gate refuses it as it refused an unknown name", "not a background agent" in r or "Refused" in r, r)
# an owner the registry cannot tell: written straight (as an old item) and read back
gk = create("home-sparrow-docs").split()[1]; it = item(gk); it["metadata"]["owner"] = it["metadata"]["mover"] = "home-twin"; server._save(gk, it)
check("an owner the registry cannot tell is shown as stored", "mover: home-twin" in server.stackshot_get(gk), server.stackshot_get(gk))
check("update by the owner as the sala id (the session writes under its permanent id) passes", "Refused" not in server._update(g1, next="home-sparrow: the next step", sender=S["main"]))
check("update by the old name passes too", "Refused" not in server._update(g1, next="home-sparrow: the next step again", sender="home-sparrow"))
check("a work line by the engineer named in needs: by the sala id and by the old name", "Refused" not in server._update(g2, work={"text": "building", "state": "in progress"}, sender=S["eng"])
      and "Refused" not in server._update(g2, work={"text": "tests", "state": "in progress"}, sender="site-builder"))

# ---- 4. a rename: the item is untouched, the readings follow
before = hashlib.sha256(server._path(g1).read_bytes()).hexdigest()
put_registry([r_ if r_["id"] != S["main"] else {**r_, "name": "home-sparrow-lead", "aliases": ["home-sparrow", "home-sparrow-main"]} for r_ in ROWS] )
put_fleet({**FLEET, Tr["main_b"]: "home-sparrow-lead"})
check("rename: the stored item did not change", hashlib.sha256(server._path(g1).read_bytes()).hexdigest() == before)
check("rename: get shows the new name", "mover: home-sparrow-lead" in server.stackshot_get(g1), server.stackshot_get(g1))
check("rename: the web page shows the new name, the board.md the new name", "home-sparrow-lead" in ui_render.Board(str(_core_store.STORE)).item_html(g1) and "home-sparrow-lead" in server._rmod.render(str(_core_store.STORE), "full"))
check("rename: the item page never shows the bare id", S["main"] not in ui_render.Board(str(_core_store.STORE)).item_html(g1))
check("rename: the owner is still the same session by its old name and by its id (comparisons by sala id)", server._same_sess("home-sparrow-main", meta(g1)["owner"]) and server._same_sess("home-sparrow-lead", meta(g1)["owner"]) and server._session_label(meta(g1)["owner"]) == "home-sparrow-lead")
check("rename: the client API lists the item for the session by its new name, its old name, its id and its first transcript", all(
      g1 in {i["gid"] for i in json.loads(server._client_items(k)[2])["items"]} for k in ("home-sparrow-lead", "home-sparrow-main", S["main"], Tr["main_a"], Tr["main_b"])))
check("rename: the client API names the needs by name", [i for i in json.loads(server._client_items("home-sparrow-docs")[2])["items"] if i["gid"] == g2][0]["needs"] == ["site-builder"])
check("rename: an update with the old name as owner= keeps the stored id, no change of owner", (server._update(g1, owner="home-sparrow-main"), meta(g1)["owner"])[1] == S["main"])
put_registry(); put_fleet(FLEET)

# ---- 5. a fresh start left the owner pointing at a finished transcript
gt = create("home-sparrow-docs").split()[1]; it = item(gt); it["metadata"]["owner"] = it["metadata"]["mover"] = Tr["main_a"]; server._save(gt, it)       # an old item: owner stored as the first transcript of home-sparrow-main
check("old transcript owner: shown as the session's name", "mover: home-sparrow-main" in server.stackshot_get(gt), server.stackshot_get(gt))
check("old transcript owner: found by the session's current transcript, which is another one", gt in {i["gid"] for i in json.loads(server._client_items(Tr["main_b"])[2])["items"]})
check("old transcript owner: compared by sala id (the update by the session's id is its owner's)", "Refused" not in server._update(gt, next="home-sparrow: mine", sender=S["main"]))
fa = json.loads(server._client_item_facts(Tr["main_b"], gt)[2])["items"][gt]
check("old transcript owner: item-facts says it is mine and gives the name", fa["mover_me"] is True and fa["mover"] == "home-sparrow-main", fa)

# ---- 6. delivery
sent = []
real_run = subprocess.run
def fake_run(argv, *a, **k):
    if isinstance(argv, list) and argv and str(argv[-1]).startswith("[stackshot message]") or (isinstance(argv, list) and "--from" in argv):
        sent.append(argv); return subprocess.CompletedProcess(argv, 0, stdout="delivered → x\n", stderr="")
    return real_run(argv, *a, **k)
subprocess.run = fake_run
try:
    out = server._message(S["main"], server._FOR_OWNER + " hello", "home-sparrow-docs")
    to_arg = sent[-1][sent[-1].index("--from") + 2]
    check("message to a sala id: push.py is handed the sala id as written (the inbox stores the permanent id; push.py turns it into the session's name as the address)", to_arg == S["main"] and out.startswith("delivered"), (sent[-1][:5], out))
    sent.clear()
    out = server._message("home-sparrow-docs", server._FOR_OWNER + " hello back", S["main"])
    check("message from a sala id: accepted as the sender, labelled by name", out.startswith("delivered") and "home-sparrow-main" in sent[-1][sent[-1].index("--from") + 1], (sent, out))
finally:
    subprocess.run = real_run
os.environ["ANCHOR_PUSH_SOURCE"] = "msg"
import importlib; importlib.reload(push)
import contextlib, io
with contextlib.redirect_stdout(io.StringIO()): rc = push.deliver(S["main"], "a line", "tester")
lines = [i for i in inbox._items("msg") if i["text"] == "a line"]
check("a notice the server sent to a needs entry stored as a sala id reached the inbox under the engineer's name", any(i["to"] == "site-builder" and i["uuid"] == Tr["eng"] for i in inbox._items("msg") if "now needs you" in i["text"]), [i["to"] for i in inbox._items("msg")])
check("push to a sala id: the line waits in the inbox under the session's name, the transcript id found", rc in (0, 1) and lines and lines[-1]["to"] == "home-sparrow-main" and lines[-1]["uuid"] == Tr["main_b"] and lines[-1]["pid"] == S["main"], lines[-1:] )
iid = inbox.put(S["main"], "second", "msg", sender="tester"); got = [i for i in inbox._items("msg") if i["id"] == iid][0]
check("inbox.put: the key is the name, never the sala id (the line keeps the permanent id in `pid`)", got["to"] == "home-sparrow-main" and got["pid"] == S["main"], got)
(T / "state/anchor-hub/held-msg.txt").write_text(S["main"] + "\n", encoding="utf-8")
live = {Tr["main_b"]: "home-sparrow-main"}
check("inbox.take: a hold that lists the session by its sala id holds its lines", inbox.take(live, only_src="msg") == [], inbox.take(live, only_src="msg"))
(T / "state/anchor-hub/held-msg.txt").write_text("home-sparrow-main\n", encoding="utf-8")
check("inbox.take: a hold by name holds them too", inbox.take(live, only_src="msg") == [])
# a hold on a name the session no longer carries (an alias: home-sparrow was home-sparrow-main's name; the permanent id is the same) holds nothing of the session that carries the id now
class _Cap(logging.Handler):
    def __init__(self): super().__init__(); self.msgs = []
    def emit(self, r): self.msgs.append(r.getMessage())
cap = _Cap(); logging.getLogger("stackshot.inbox").addHandler(cap)
def unlease(res): inbox.ack([], failed=[i for r_ in res for i in r_["ids"]], now=0)       # the lines are offered again at once
(T / "state/anchor-hub/held-msg.txt").write_text("home-sparrow\nsomebody-else\n", encoding="utf-8")
check("expand_flag: an alias adds no permanent id; the current name, the id and a transcript id do", S["main"] not in sr.expand_flag(["home-sparrow"]) and "home-sparrow" in sr.expand_flag(["home-sparrow"])
      and S["main"] in sr.expand_flag(["home-sparrow-main"]) and S["main"] in sr.expand_flag([S["main"]]) and S["main"] in sr.expand_flag([Tr["main_a"]]), (sr.expand_flag(["home-sparrow"]), sr.expand_flag(["home-sparrow-main"])))
t_alias = inbox.take(live, only_src="msg", now=time.time())
check("inbox.take: a hold on an old name (an alias) of the live session holds none of its lines", t_alias and t_alias[0]["session"] == Tr["main_b"], t_alias)
check("inbox.take: …and logs nothing, the line is not skipped", not cap.msgs, cap.msgs)
unlease(t_alias)
(T / "state/anchor-hub/held-msg.txt").write_text("home-sparrow\nhome-sparrow-main\n", encoding="utf-8")
check("inbox.take: the old name AND the live name held → the live name still holds", inbox.take(live, only_src="msg", now=time.time()) == [])
check("inbox.take: …and a hold on the live name logs nothing (a live name is no stale entry)", not cap.msgs, cap.msgs)
(T / "state/anchor-hub/held-msg.txt").write_text(Tr["main_a"] + "\n", encoding="utf-8")
check("inbox.take: a hold on one of its transcript ids still holds it", inbox.take(live, only_src="msg", now=time.time()) == [])
(T / "state/anchor-hub/held-msg.txt").write_text("home-gone\n", encoding="utf-8")
t_other = inbox.take(live, only_src="msg", now=time.time())
check("inbox.take: a hold on a retired session's name holds none of the live session's lines", t_other and t_other[0]["session"] == Tr["main_b"], t_other)
unlease(t_other)
# a line put for the old name, held by that same name, is held (the hold names it); the server says why once an hour
iid_old = inbox.put("home-sparrow", "to the old name", "msg", sender="tester"); old_it = [i for i in inbox._items("msg") if i["id"] == iid_old][0]
(T / "state/anchor-hub/held-msg.txt").write_text("home-sparrow\n", encoding="utf-8")
t0 = time.time(); inbox.take({}, only_src="msg", now=t0)
check("inbox.take: a line addressed to the old name is held by a hold on that name, and the server logs why (an old name of the live session)", len(cap.msgs) == 1 and "home-sparrow" in cap.msgs[0] and "an old name of home-sparrow-main" in cap.msgs[0], cap.msgs)
inbox.take({}, only_src="msg", now=t0 + 60)
check("inbox.take: the same stale entry logs once per hour, again after it", len(cap.msgs) == 1 and (inbox.take({}, only_src="msg", now=t0 + 3700) or True) and len(cap.msgs) == 2, cap.msgs)
inbox.ack([iid_old]); logging.getLogger("stackshot.inbox").removeHandler(cap)
# the release list of a paused source reads the same way: an old name releases nothing of the live session
(T / "state/anchor-hub/held-msg.txt").write_text("", encoding="utf-8")
(T / "state/anchor-hub/paused-msg.json").write_text("{}", encoding="utf-8")
(T / "state/anchor-hub/release-msg.txt").write_text("home-sparrow\n", encoding="utf-8")
check("inbox.take: a paused source: a release of an old name releases none of the live session's lines", inbox.take(live, only_src="msg", now=time.time()) == [])
(T / "state/anchor-hub/release-msg.txt").write_text("home-sparrow-main\n", encoding="utf-8")
t_rel = inbox.take(live, only_src="msg", now=time.time())
check("inbox.take: …a release of its current name does", t_rel and t_rel[0]["session"] == Tr["main_b"], t_rel)
unlease(t_rel)
(T / "state/anchor-hub/paused-msg.json").unlink(); (T / "state/anchor-hub/release-msg.txt").unlink()
(T / "state/anchor-hub/held-msg.txt").write_text("home-sparrow\n", encoding="utf-8")
check("push: a hold on an old name does not pause the session that carries the id now; the hold on the live name does",
      not push.paused("home-sparrow-main") and (T / "state/anchor-hub/held-msg.txt").write_text("home-sparrow-main\n") and push.paused("home-sparrow-main"))
(T / "state/anchor-hub/held-msg.txt").write_text("", encoding="utf-8")
taken = inbox.take(live, only_src="msg")
check("inbox.take: with nothing held the lines go to the pane", taken and taken[0]["session"] == Tr["main_b"], taken)
check("push: a hold file that lists the sala id holds the name", (T / "state/anchor-hub/held-msg.txt").write_text(S["main"] + "\n") and push.paused("home-sparrow-main") and not push.paused("home-sparrow-docs"))
(T / "state/anchor-hub/held-msg.txt").write_text("")
check("sessions index: a lookup by sala id finds the pane's row with the registry's name; iteration lists each session once", server._sessions_index().get(S["main"], {}).get("name") == "home-sparrow-main"
      and S["main"] not in list(server._sessions_index()) and len(list(server._sessions_index())) == len(FLEET) and S["main"] in server._sessions_index())

# ---- 7. roles.json and the mirror
RJ = T / "state/roles.json"
_projects_registry._roles_sync(now=time.time())
j = json.loads(RJ.read_text())
check("roles.json: `sessions` is keyed by name as before; `ids` is the extra key with the sala id of each name the registry resolves",
      "home-sparrow-main" in j["sessions"] and j["ids"].get("home-sparrow-main") == S["main"] and j["ids"].get("site-builder") == S["eng"] and "home-sparrow" in j["ids"] and set(j) == {"generated", "sessions", "ids"}, j)

# ---- 8. the migration: a read-only dry run on the command line; the apply and the rollback run inside the server, from a request file
import threading; from stackshot.fleet import session_ids as sid
# an open item that stores a transcript id, one a name, a closed item, an ambiguous name, a cloud id, a person
mig = {}
mig["tr"] = create("home-sparrow-docs").split()[1]; it = item(mig["tr"]); it["metadata"]["owner"] = it["metadata"]["mover"] = Tr["main_a"]; it["metadata"]["needs"] = ["decision", "site-builder", "home-twin", "cse_0123456789abcdefghijklmn", "some-outsider"]
it["metadata"]["observers"] = ["home-sparrow-docs", S["docs"]]; server._save(mig["tr"], it)
mig["name"] = create("home-sparrow-docs").split()[1]; it = item(mig["name"]); it["metadata"]["owner"] = it["metadata"]["mover"] = "home-sparrow-main"; it["metadata"]["owner_name"] = "kept as it is"; server._save(mig["name"], it)
mig["closed"] = create("home-sparrow-docs").split()[1]; server._update(mig["closed"], status="completed", sender="home-sparrow-docs", outcome="done", reason="the work landed", description="- Goal: The test item's work is in place")
it = item(mig["closed"]); it["metadata"]["owner"] = it["metadata"]["mover"] = "home-sparrow-main"; it["metadata"]["needs"] = ["site-builder"]; server._save(mig["closed"], it)
mig["good"] = g1
files = {k: server._path(g) for k, g in mig.items()}
digest = lambda: {k: hashlib.sha256(f.read_bytes()).hexdigest() for k, f in files.items()}
d0 = digest()
HELD = T / "state/anchor-hub/held-msg.txt"; HELD.write_text("home-sparrow-main\nsomebody-else\n", encoding="utf-8")
(T / "state/anchor-hub/release-msg.txt").write_text("home-sparrow-docs\n", encoding="utf-8")
rj0 = RJ.read_bytes(); RJ.write_text(json.dumps({"generated": j["generated"], "sessions": j["sessions"]}))
undo_files = lambda: sorted((T / "state").glob("session-ids-undo-*.json"))
rep = sid.scan()
check("dry run: nothing written", digest() == d0 and HELD.read_text() == "home-sparrow-main\nsomebody-else\n" and "ids" not in json.loads(RJ.read_text()) and rep["written"] == 0 and not undo_files() and not sid.request_path().exists())
ch = {(g, f): (o, n) for g, f, o, n in rep["changed"]}
check("dry run: the transcript owner, the old-name needs entry and the observer by name would change; the closed item is not looked at",
      ch.get((mig["tr"], "owner")) == (Tr["main_a"], S["main"]) and ch[(mig["tr"], "needs")][1] == ["decision", S["eng"], "home-twin", "cse_0123456789abcdefghijklmn", "some-outsider"]
      and ch.get((mig["tr"], "observers")) == (["home-sparrow-docs", S["docs"]], [S["docs"]]) and not any(g == mig["closed"] for g, *_ in rep["changed"]) and rep["closed"] >= 1, rep["changed"])
kept = {(g, f, v): why for g, f, v, why in rep["kept"]}
check("dry run: an ambiguous name, a cloud id and a person are kept, each with the reason", kept.get((mig["tr"], "needs", "home-twin"), "").startswith("ambiguous")
      and (mig["tr"], "needs", "cse_0123456789abcdefghijklmn") in kept and (mig["tr"], "needs", "some-outsider") in kept and "cloud" in kept[(mig["tr"], "needs", "cse_0123456789abcdefghijklmn")], rep["kept"])
check("dry run: the summary says what and how many", "would change: " in sid.summary(rep, False) and "kept: " in sid.summary(rep, False) and "dry run (nothing written)" in sid.summary(rep, False))
run_py = lambda *a, **k: subprocess.run([sys.executable, str(pathlib.Path(STACK, "stackshot/fleet/session_ids.py")), *a], capture_output=True, text=True, **k)
r = run_py("migrate", "--apply")
check("the command has no apply of its own: --apply is a usage error and writes nothing", r.returncode != 0 and "usage" in (r.stderr + r.stdout) and digest() == d0 and not sid.request_path().exists(), (r.returncode, r.stderr[-200:]))
r = run_py("migrate", "--dry-run", env={k: v for k, v in os.environ.items() if k != "STACKSHOT_CONFIG"} | {"HOME": str(T)})
check("the command refuses a run outside the production checkout without a config", r.returncode != 0 and "STACKSHOT_CONFIG is unset" in (r.stderr + r.stdout), r.stderr[-300:])
r = run_py("migrate", "--dry-run")
check("the command line: a dry run prints the summary and exits 0, changes nothing", r.returncode == 0 and "dry run (nothing written)" in r.stdout and digest() == d0, (r.returncode, r.stdout[-300:], r.stderr[-300:]))
# the request: the CLI writes only the request file
r = run_py("migrate", "--request")
check("migrate --request writes the request file and nothing else", r.returncode == 0 and sid.read_request() == ("apply", "") and digest() == d0 and not undo_files(), (r.stdout, r.stderr))
# the pass holds the item lock too: a thread holding it keeps the pass waiting (the pass is safe because it runs before any writer thread starts)
held = threading.Event(); free = threading.Event(); done = []
def holder():
    with server._ITEM_LOCK: held.set(); free.wait(5)
th = threading.Thread(target=holder); th.start(); held.wait(2)
runner = threading.Thread(target=lambda: done.append(server._session_ids_pass())); runner.start(); time.sleep(0.4)
check("the pass waits for a thread that holds the item lock", not done and digest() == d0)
free.set(); th.join(); runner.join(10)
line = done[0] if done else ""
check("the pass consumed the request and logged a one-line summary", not sid.request_path().exists() and line.startswith("session ids: apply done") and "\n" not in line, line)
check("apply: the open items are rewritten", item(mig["tr"])["metadata"]["owner"] == S["main"] and item(mig["tr"])["metadata"]["needs"] == ["decision", S["eng"], "home-twin", "cse_0123456789abcdefghijklmn", "some-outsider"]
      and item(mig["tr"])["metadata"]["observers"] == [S["docs"]] and item(mig["name"])["metadata"]["owner"] == S["main"], item(mig["tr"])["metadata"])
check("apply: owner_name and the clocks stay; the closed item is byte for byte as it was", item(mig["name"])["metadata"]["owner_name"] == "kept as it is" and digest()["closed"] == d0["closed"]
      and item(mig["closed"])["metadata"]["owner"] == "home-sparrow-main" and item(mig["closed"])["metadata"]["needs"] == ["site-builder"])
check("apply: roles.json and the hold lists are NOT touched (roles sync and sala own them)", RJ.read_text() == json.dumps({"generated": j["generated"], "sessions": j["sessions"]})
      and HELD.read_text() == "home-sparrow-main\nsomebody-else\n" and (T / "state/anchor-hub/release-msg.txt").read_text() == "home-sparrow-docs\n")
uf = undo_files()
ud = json.loads(uf[0].read_text()) if uf else {}
check("apply: one undo file, gid/field/old/new for each change", len(uf) == 1 and ud.get("schema") == 1 and {(c["gid"], c["field"]) for c in ud["changes"]} >= {(mig["tr"], "owner"), (mig["tr"], "needs"), (mig["tr"], "observers"), (mig["name"], "owner")}
      and all(set(c) == {"gid", "field", "old", "new"} for c in ud["changes"]) and not any(c["gid"] == mig["closed"] for c in ud["changes"]), ud)
check("apply: no temp file left in the store", not [x for x in (T / "store").rglob("*") if x.name.endswith(".tmp")])
check("apply: get reads the same names as before the migration", "then: home-sparrow-main" in server.stackshot_get(mig["tr"]) and "needs: decision, site-builder, home-twin" in server.stackshot_get(mig["tr"]), server.stackshot_get(mig["tr"]))
d1 = digest()
sid.main(["migrate", "--request"]); line2 = server._session_ids_pass()
check("a second request changes nothing (idempotent) and writes no second undo file", digest() == d1 and "0 field(s)" in line2 and len(undo_files()) == 1, line2)
check("no request file: the pass does nothing and says nothing", server._session_ids_pass() == "")
# rollback through the same door
sid.main(["rollback", str(uf[0])])
check("rollback: the request names the undo file", sid.read_request() == ("rollback", str(uf[0])))
it = item(mig["name"]); it["metadata"]["owner"] = it["metadata"]["mover"] = S["docs"]; server._save(mig["name"], it)         # changed since: must be left
line3 = server._session_ids_pass()
back = {k: hashlib.sha256(f.read_bytes()).hexdigest() for k, f in files.items()}
check("rollback: the fields go back to what they were; a field changed since is left and said so", item(mig["tr"])["metadata"]["owner"] == Tr["main_a"] and item(mig["tr"])["metadata"]["needs"] == ["decision", "site-builder", "home-twin", "cse_0123456789abcdefghijklmn", "some-outsider"]
      and item(mig["tr"])["metadata"]["observers"] == ["home-sparrow-docs", S["docs"]] and item(mig["name"])["metadata"]["owner"] == S["docs"] and "1 skipped" in line3 and back["tr"] == d0["tr"] and back["closed"] == d0["closed"], (line3, item(mig["tr"])["metadata"]))
for bad_req in ("nonsense\n", "rollback /no/such/undo.json\n"):
    sid.request_path().write_text(bad_req, encoding="utf-8")
    try: ln = server._session_ids_pass(); ok = True
    except BaseException: ln, ok = "", False
    check(f"a bad request ({bad_req.split()[0]}) is consumed, logged, and never fails the start", ok and not sid.request_path().exists() and ln.startswith("session ids:"), ln)
SALA.unlink()
d2 = digest(); sid.main(["migrate", "--request"]); ln = server._session_ids_pass()
check("no registry: the request is consumed all the same (ask again once the registry reads)", not sid.request_path().exists())
rep3 = sid.scan()
check("no registry: the pass says so and touches nothing; the dry run says so", digest() == d2 and "no session registry" in ln and rep3["errors"] and "no session registry" in rep3["errors"][0][1], (ln, rep3["errors"]))
put_registry()

# ---- 8b. a said entry is checked against a transcript, never the sala id (B1)
root = T / "transcripts" / "proj"; root.mkdir(parents=True)
MSG = "11111111-1111-4111-8111-111111111111"
(root / f"{Tr['main_b']}.jsonl").write_text(json.dumps({"type": "user", "uuid": MSG, "origin": {"kind": "human"}, "message": {"role": "user", "content": "yes please do the thing"}, "timestamp": "2026-10-22T07:00:00Z"}) + "\n", encoding="utf-8")
server._said_roots = lambda: (str(T / "transcripts"),)
def said(quote, sess):
    try: return server._gate_said([{"tag": "Acked-by", "quote": quote, "msg": MSG}], sess, "tester"), ""
    except Exception as e: return None, str(e)
for how, sess in (("the transcript id", Tr["main_b"]), ("the pane name", "home-sparrow-main"), ("the sala id", S["main"]), ("an old transcript id of the session", Tr["main_a"])):
    bad_, why = said("NOT IN THE MESSAGE", sess)
    check(f"said by {how}, registry present: a wrong quote is refused", bad_ is None and "Refused" in why, (bad_, why))
    ok_, why = said("do the thing", sess)
    check(f"said by {how}, registry present: a right quote is accepted, checked, and stored under the transcript, not the sala id", ok_ and ok_[0]["checked"] and ok_[0]["session"] == Tr["main_b"] and ok_[0]["session"] != S["main"], (ok_, why))
ok_, _ = said("do the thing", S["docs"])
check("said by a session whose transcript is not on this box: stored unchecked, under a transcript id (never the sala id)", ok_ and not ok_[0]["checked"] and ok_[0]["session"] == Tr["docs"], ok_)
SALA.unlink()
bad_, why = said("NOT IN THE MESSAGE", Tr["main_b"]); ok_, _ = said("do the thing", Tr["main_b"])
check("said, no registry: as before (a wrong quote refused, a right one accepted)", bad_ is None and ok_ and ok_[0]["checked"] and ok_[0]["session"] == Tr["main_b"])
put_registry()

# ---- 8c. `pages.py clear` finds the caller's own debt when the server keyed it by the sala id (B3)
LEDGER = server._owed_path(); E = lambda: {"ts": time.time(), "item": "s11"}
def clear(*args, sid_=Tr["main_b"], env_extra=None):
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_CODE_SESSION_ID"} | (env_extra or {})
    if sid_: env["CLAUDE_CODE_SESSION_ID"] = sid_
    r = subprocess.run([sys.executable, os.path.join(STACK, "stackshot/projects/pages.py"), "clear", *args], capture_output=True, text=True, env=env)
    return r.returncode, r.stdout
led = lambda: json.loads(LEDGER.read_text(encoding="utf-8"))
LEDGER.write_text(json.dumps({"projects/alpha": {S["main"]: E()}}), encoding="utf-8")
rc, out = clear("alpha")
check("pages clear: a debt keyed by the caller's sala id is the caller's own (exit 0, entry gone)", rc == 0 and "projects/alpha" not in led() and "1 server owed entry" in out, (rc, out, led()))
LEDGER.write_text(json.dumps({"projects/alpha": {S["main"]: E(), S["docs"]: E()}}), encoding="utf-8")
rc, out = clear("alpha")
check("pages clear: another session's sala-id debt on the same page is named and kept (exit 3)", rc == 3 and list(led().get("projects/alpha", {})) == [S["docs"]] and "home-sparrow-docs" in out, (rc, out, led()))
LEDGER.write_text(json.dumps({"projects/alpha": {Tr["main_a"]: E()}}), encoding="utf-8")
rc, out = clear("alpha")
check("pages clear: a debt under an older transcript id of the same session is the caller's too", rc == 0 and "projects/alpha" not in led(), (rc, out, led()))
SALA.unlink(); RJ.write_text(json.dumps({"generated": j["generated"], "sessions": j["sessions"], "ids": {"home-sparrow-main": S["main"]}}))
LEDGER.write_text(json.dumps({"projects/alpha": {S["main"]: E()}}), encoding="utf-8")
rc, out = clear("alpha")
check("pages clear: with no registry here, roles.json's `ids` tells the caller's sala id", rc == 0 and "projects/alpha" not in led(), (rc, out, led()))
LEDGER.write_text(json.dumps({"projects/alpha": {S["docs"]: E()}}), encoding="utf-8")
rc, out = clear("alpha")
check("pages clear: …and does not clear another session's", rc == 3 and S["docs"] in led().get("projects/alpha", {}), (rc, out))
put_registry(); _projects_registry._roles_sync(now=time.time() + 10000)
LEDGER.write_text("{}", encoding="utf-8")
it = item(mig["name"]); it["metadata"]["owner"] = it["metadata"]["mover"] = S["main"]; server._save(mig["name"], it)      # as the migration left it, for section 9

# ---- 9. a registry that disappears again: everything reads as stored, nothing raises
SALA.unlink()
check("registry gone: get shows the stored value", "mover: " + S["main"] in server.stackshot_get(mig["name"]) or "mover: home-sparrow-main" in server.stackshot_get(mig["name"]), server.stackshot_get(mig["name"]))
check("registry gone: the client API still lists the item for the id (the stored form)", mig["name"] in {i["gid"] for i in json.loads(server._client_items(S["main"])[2])["items"]})
check("registry gone: the web page still renders", "<html" in ui_render.Board(str(_core_store.STORE)).item_html(mig["name"]).lower())

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
