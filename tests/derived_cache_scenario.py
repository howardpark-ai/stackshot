"""Scenario test for what the server works out from files and keeps while they are as they were (core/filecache.py `derived`): the project registry the readers see (anchors.registry), the
session index of the fleet (fleet.view, behind anchors.names) and the retired words (projects.retired_statuses) — fixture data, no live store, no network, no server socket.

The once-a-minute passes ask for the registry and for the session names hundreds of times each, and each ask laid the project record over the page registry again, or indexed every session row again. They are
now worked out once per change of the files they read, and the answers are the ones the work gave before.

  1  hits: the registry asked five times is worked out once; the sessions asked five times are read once
  2  the same results: the registry, the roles built from it and the session names equal what the uncached work gives, byte for byte, over several projects and sessions
  3  this process's own writes are seen at the next call, whatever the file's stamp says: a registry written through the writer of projects.py, a write of anchors.json
  4  another process's writes are seen: a file of another size, of the same size and another time, replaced by one of the same size and time, the project record written and removed, a changed setting
  5  a value is not kept when it could be wrong: a file younger than the cache's window, a file written while it was being worked out, a file that cannot be read (nothing is kept, and the file read after it is read)
  6  a caller that only looks does not change what is kept: the readers of the registry leave it as it was
  7  the session index: the same pairs as fleet.by_name at any time (running, gone within the grace, gone long ago, namesakes, ties, a stamp nobody can read), the clock moving without a file write, a changed sessions file seen
  8  the retired words are made once per value of the setting, each caller gets its own set, a changed setting or default is seen, and the roles ask for them once

    tests/run-suite derived_cache        → exit 0 / 1"""
import contextlib, copy, json, os, re, sys, pathlib, time, logging
from unittest import mock
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="derivedcache-"); T = pathlib.Path(tmp)
PID = {n: "prj_" + format(n, "08x") for n in range(1, 5)}      # the permanent project ids, in the form the code requires, made here
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store", "fleet/a", "state/demo", "brain/projects"): (T / d).mkdir(parents=True)
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0", "online": {"ok": True}}))

fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:300]}" if got is not None else ""))
sys.path.insert(0, STACK); logging.disable(logging.INFO)
from stackshot.anchors import anchors as _anc
from stackshot.core import config as _cfg
from stackshot.core import filecache as FC
from stackshot.fleet import fleet as _fleet
from stackshot.projects import project_registry as _pr
from stackshot.projects import projects as _prj

REG = pathlib.Path(_anc.REGISTRY); REC = pathlib.Path(_pr.record_path()); ANC = pathlib.Path(_anc.FILE)
SESS = T / "fleet/a/sessions.json"
def age(p, seconds=30.0, bump=0):
    """Give a file a modification time `seconds` in the past (plus `bump` ns): old enough for the cache to keep it."""
    t = time.time_ns() - int(seconds * 1e9) + bump
    os.utime(p, ns=(t, t))
def put(p, text, old=True, seconds=30.0):
    """Write a file the way another process does (a temp file beside it, then a rename: a new inode), and give it an old time."""
    p = pathlib.Path(p); tmpf = p.with_name(p.name + ".other"); tmpf.write_text(text, encoding="utf-8"); os.replace(tmpf, p)
    if old: age(p, seconds)

def pages(title="alpha", back="builds, merges and releases the code"):
    return {"pages": {
        "projects/alpha": {"id": PID[1], "key": "projects/alpha", "title": title, "name": "alpha", "org": "home", "tags": [], "type": "project", "session": "home-lead", "status": "active", "board": [], "board_open": 0,
                           "agents": {"home-front": "the front", "team-back": back}, "back_agents": {"team-back": back}},
        "projects/alpha/sub": {"id": PID[2], "key": "projects/alpha/sub", "title": "sub", "name": "", "org": "home", "tags": [], "type": "project", "session": "home-sub", "role": "name", "status": "active", "board": [], "board_open": 0},
        "projects/beta": {"id": PID[3], "key": "projects/beta", "title": "beta", "name": "beta", "org": "home", "tags": [], "type": "project", "session": "home-beta", "status": "archived", "board": [], "board_open": 0,
                          "agents": {"home-old": "was the front"}},
        "projects/gamma": {"id": PID[4], "key": "projects/gamma", "title": "gamma", "name": "gamma", "org": "home", "tags": [], "type": "project", "session": "home-gam", "status": "active", "board": [], "board_open": 0,
                           "hub": "projects/alpha", "agents": {"home-g": "the front of gamma"}}}}
def text(**kw): return json.dumps(pages(**kw))
def uncached(): return _pr.apply(json.load(open(REG, encoding="utf-8")).get("pages", {}) or {})
def same(a, b): return json.dumps(a) == json.dumps(b)

APPLY = [0]; _real_apply = _pr.apply
def _counting_apply(*a, **kw):
    APPLY[0] += 1
    return _real_apply(*a, **kw)
_pr.apply = _counting_apply
def calls(fn):
    """How many times the registry was laid over the pages while `fn` ran, and what it gave."""
    before = APPLY[0]; got = fn()
    return APPLY[0] - before, got
def reset(reg_text=None, record=None):
    """A clean start: the cache emptied, the registry file old, no record."""
    FC.forget()
    put(REG, reg_text if reg_text is not None else text())
    if record is None:
        try: REC.unlink()
        except FileNotFoundError: pass
    else:
        put(REC, json.dumps(record))
    put(ANC, "{}")

# ================================================================ 1. hits
reset()
n, got = calls(lambda: [_anc.registry() for _ in range(5)])
check("1 hits: the registry asked five times is worked out once", n == 1, n)
check("1 hits: and each ask gives the same registry", all(same(got[0], g) for g in got) and len(got[0]) == 4, len(got[0]))

# ================================================================ 2. the same results
reset()
check("2 same: the registry equals the uncached one, byte for byte", same(_anc.registry(), uncached()), (list(_anc.registry()), list(uncached())))
reset(record={"projects_schema": 1, "projects": {PID[1]: {"page": "projects/alpha", "title": "Alpha by record", "agents": {"home-front": {"front": True, "mandate_line": "the front"}, "home-extra": {"front": False, "mandate_line": "extra"}}}}})
cached = _anc.registry()
check("2 same: with a project record laid over the pages, the registry equals the uncached one", same(cached, uncached()) and cached["projects/alpha"].get("title") == "Alpha by record", cached["projects/alpha"].get("title"))
check("2 same: the roles built from it equal the roles built from the uncached registry", same(_anc.session_roles(cached), _anc.session_roles(uncached())) and "home-extra" in _anc.session_roles(cached), list(_anc.session_roles(cached)))

# ================================================================ 3. this process's writes
reset()
_anc.registry()
old_stamp = FC.stamp(str(REG)); real_stamp = FC.stamp
_prj.write_atomic(REG, text(title="omega"))                              # the writer of projects.py, as the publisher uses it
FC.stamp = lambda p: old_stamp if os.fspath(p) == str(REG) else real_stamp(p)       # a coarse clock: the file reads as it did before the write
try: got = _anc.registry()
finally: FC.stamp = real_stamp
check("3 own write: a registry written through projects.write_atomic is seen at the next call, whatever the stamp says", got["projects/alpha"]["title"] == "omega", got["projects/alpha"]["title"])
reset()
_anc.registry()
n, _ = calls(lambda: (_anc.save({"k": [{"a": 1}]}), _anc.registry()))
check("3 own write: a write of anchors.json through anchors.save makes the registry be worked out again", n == 1, n)

# ================================================================ 4. other processes' writes
reset(text(title="alpha"))
_anc.registry()
put(REG, text(title="alpha-and-more"))
check("4 other: a registry file of another size is seen", _anc.registry()["projects/alpha"]["title"] == "alpha-and-more")
reset(text(title="aaaaa"))
_anc.registry()
with open(REG, "w", encoding="utf-8") as f: f.write(text(title="bbbbb"))        # in place: the same inode, the same size
age(REG, 77.0)
check("4 other: a registry file of the same size and another time is seen", _anc.registry()["projects/alpha"]["title"] == "bbbbb")
reset(text(title="aaaaa"))
_anc.registry(); st = os.stat(REG)
put(REG, text(title="ccccc"), old=False); os.utime(REG, ns=(st.st_atime_ns, st.st_mtime_ns))        # replaced by a file of the same size and time
check("4 other: a registry file replaced by one of the same size and time is seen (its inode differs)", _anc.registry()["projects/alpha"]["title"] == "ccccc")
reset(text(title="aaaaa"))
_anc.registry(); st = os.stat(REG)
with open(REG, "w", encoding="utf-8") as f: f.write(text(title="a-longer-title"))        # in place: the same inode, another size
os.utime(REG, ns=(st.st_atime_ns, st.st_mtime_ns))                                       # and the old time put back
check("4 other: a registry file of another size and the same time is seen", _anc.registry()["projects/alpha"]["title"] == "a-longer-title")
reset()
before_title = _anc.registry()["projects/alpha"]["title"]
put(REC, json.dumps({"projects_schema": 1, "projects": {PID[1]: {"page": "projects/alpha", "title": "From the record"}}}))
check("4 other: a project record written by another process is seen", _anc.registry()["projects/alpha"]["title"] == "From the record" and before_title == "alpha", _anc.registry()["projects/alpha"]["title"])
put(REC, json.dumps({"projects_schema": 1, "projects": {PID[1]: {"page": "projects/alpha", "title": "From the record, again"}}}), seconds=60.0)
check("4 other: and one rewritten", _anc.registry()["projects/alpha"]["title"] == "From the record, again")
REC.unlink()
check("4 other: and one removed", _anc.registry()["projects/alpha"]["title"] == "alpha")
reset()
_anc.registry()
was = _cfg.CFG.get("project_scopes")
_cfg.CFG["project_scopes"] = {**(was or {}), "retired_statuses": ["paused"]}
try:
    n, got = calls(lambda: _anc.registry())
    check("4 other: a changed setting that the registry's work reads is seen (the registry is worked out again, as the uncached work gives it)", n == 1 and same(got, uncached()), n)
finally:
    if was is None: _cfg.CFG.pop("project_scopes", None)
    else: _cfg.CFG["project_scopes"] = was
reset()
_anc.registry()
_prj._RETIRED.append("shelved")
try:
    n, _ = calls(lambda: _anc.registry())
    check("4 other: a changed built-in default that the registry's work reads is seen", n == 1, n)
finally:
    _prj._RETIRED.remove("shelved")

# ================================================================ 5. never kept when it could be wrong
reset()
put(REG, text(title="aaaaa"), old=False)                                   # written just now
n, _ = calls(lambda: [_anc.registry() for _ in range(3)])
check("5 safe: a file younger than the cache's window is not kept (each call works it out)", n == 3, n)
reset(text(title="aaaaa"))
def _apply_that_writes(reg, *a, **kw):
    put(REG, text(title="zzzzz"))                                          # another process writes while the registry is worked out
    return _real_apply(reg, *a, **kw)
_pr.apply = _apply_that_writes
try: first = _anc.registry()
finally: _pr.apply = _counting_apply
second = _anc.registry()
check("5 safe: a file written while the registry was worked out is not kept: the next call sees it", second["projects/alpha"]["title"] == "zzzzz", (first["projects/alpha"]["title"], second["projects/alpha"]["title"]))
reset()
REG.unlink()
check("5 safe: a missing registry file gives {} as before", _anc.registry() == {})
put(REG, text(title="after"))
check("5 safe: and the file read after it is read", _anc.registry()["projects/alpha"]["title"] == "after")
put(REG, "{ this is not json")
check("5 safe: a registry file that cannot be read gives {} as before, and is not kept", _anc.registry() == {} and _anc.registry() == {})
put(REG, text(title="fixed"))
check("5 safe: and the file read after it is read", _anc.registry()["projects/alpha"]["title"] == "fixed")

# ================================================================ 6. a caller that only looks
reset(record={"projects_schema": 1, "projects": {PID[1]: {"page": "projects/alpha", "title": "Alpha by record"}}})
shared = _anc.registry(); snap = copy.deepcopy(shared)
roles = _anc.session_roles(shared)
for fn in (lambda: _anc.file_roles(shared), lambda: _anc.hub_of("projects/gamma", shared), lambda: _anc.fallback_main("projects/alpha", shared),
           lambda: _anc.general_main("projects/gamma", shared), lambda: _prj.with_pending(shared, made=True), lambda: _prj.with_made(shared), lambda: _anc.session_roles()):
    try: fn()
    except Exception: pass
check("6 look: the readers of the registry leave it as it was", same(shared, snap) and same(_anc.registry(), snap), [k for k in snap if snap[k] != shared.get(k)][:3])
shared["ops/new"] = {"title": "added"}; shared["projects/alpha"] = {"title": "replaced"}; del shared["projects/beta"]
check("6 look: a key added, replaced or deleted in the registry one caller got is no other caller's", same(_anc.registry(), snap), list(_anc.registry()))

# ================================================================ 7. the session index
NOW = time.time(); ISO = lambda ago: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(NOW - ago))
ROWS = {"u-run": {"name": "run-one"}, "u-d1": {"name": "run-dup"}, "u-d2": {"name": "run-dup"}, "u-rec": {"name": "gone-recent", "gone": ISO(120)}, "u-old": {"name": "gone-old", "gone": ISO(3 * 3600)},
        "u-r1": {"name": "reuse", "gone": ISO(3600)}, "u-r2": {"name": "reuse"}, "u-t1": {"name": "twice", "gone": ISO(300)}, "u-t2": {"name": "twice", "gone": ISO(180)},
        "u-tie1": {"name": "tied", "gone": ISO(240)}, "u-tie2": {"name": "tied", "gone": ISO(240)}, "u-bad": {"name": "bad-stamp", "gone": "garbage"}, "u-bad2": {"name": "bad-and-good", "gone": "garbage"},
        "u-bad3": {"name": "bad-and-good", "gone": ISO(400)}, "u-none": {"gone": ISO(5)}, "u-blank": {"name": "", "gone": ISO(5)}, "u-edge": {"name": "edge", "gone": ISO(_fleet._grace() - 1)},
        "u-late": {"name": "just-past", "gone": ISO(_fleet._grace() + 5)}}
(T / "fleet/a/sessions.json").write_text(json.dumps(ROWS)); age(SESS)
FC.forget()
rows = _fleet.sessions()
view = getattr(_fleet, "view", None)
if view is None:
    check("7 index: a session index exists (fleet.view)", False, "fleet.view is missing")
else:
    v = view()
    for dt_ in (0, 61, 400, 700, 3000, 5 * 3600):
        for po in (True, False):
            want = _fleet.by_name(rows, NOW + dt_, po); got = v.by_name(NOW + dt_, po)
            check(f"7 index: by_name({dt_} s later, present_only={po}) gives the pairs fleet.by_name gives", got == want, (sorted(set(got.items()) ^ set(want.items())))[:4])
    check("7 index: the names are the rows' names", v.names == {k: str(r.get("name") or "") for k, r in rows.items()})
    check("7 index: a running namesake wins over a gone one, two running namesakes resolve to nobody, an equal time goes to the first row", v.by_name(NOW, True).get("reuse") == "u-r2" and "run-dup" not in v.by_name(NOW, True) and v.by_name(NOW, True).get("tied") == "u-tie1", v.by_name(NOW, True))
def uncached_names():
    r = _fleet.sessions()
    return {k: str(x.get("name") or "") for k, x in r.items()}, _fleet.by_name(r, present_only=True)
FC.forget()
cnt = [0]; _real_sessions = _fleet.sessions
def _counting_sessions():
    cnt[0] += 1
    return _real_sessions()
_fleet.sessions = _counting_sessions
try:
    got = [_anc.names() for _ in range(5)]
    check("7 index: the sessions asked five times are read once", cnt[0] == 1, cnt[0])
    wn, wb = uncached_names()
    check("7 index: names() equals the uncached work, byte for byte (the uuid names and the names by present session)", json.dumps(dict(got[0])) == json.dumps(wn) and got[0].by_name == wb, (len(got[0]), len(wn)))
    got[0].by_name["x"] = "y"; got[0]["x"] = "y"
    again = _anc.names()
    check("7 index: a caller that changes what names() gave leaves the next call's alone", "x" not in again and "x" not in again.by_name)
    with mock.patch("time.time", return_value=NOW + 3 * 3600):
        late = _anc.names(); wn2, wb2 = uncached_names()
        check("7 index: the clock moving past the grace with no file written is seen (gone-recent drops out of the present sessions)", late.by_name == wb2 and "gone-recent" not in late.by_name and "gone-recent" in again.by_name, (sorted(late.by_name), sorted(again.by_name)))
    ROWS2 = {**ROWS, "u-new": {"name": "brand-new"}}
    put(SESS, json.dumps(ROWS2))
    check("7 index: a sessions file written by another process is seen", _anc.names().by_name.get("brand-new") == "u-new")
    body = json.dumps({**ROWS2, "u-new": {"name": "brand-nex"}}); put(SESS, body, old=False); age(SESS, 91.0)
    check("7 index: a sessions file of the same size and another time is seen", _anc.names().by_name.get("brand-nex") == "u-new" and "brand-new" not in _anc.names().by_name)
finally:
    _fleet.sessions = _real_sessions
FC.forget()
put(SESS, json.dumps(ROWS), old=False)
cnt[0] = 0; _fleet.sessions = _counting_sessions
try:
    [_anc.names() for _ in range(3)]
    check("7 index: a sessions file written a moment ago is not kept", cnt[0] == 3, cnt[0])
finally:
    _fleet.sessions = _real_sessions

# ================================================================ 8. the retired words
_RET_DEFAULT = ["archived", "retired", "closed", "done", "dropped", "completed", "merged"]
check("8 retired: the words are the defaults' lowercase set", _prj.retired_statuses() == set(_RET_DEFAULT), _prj.retired_statuses())
a = _prj.retired_statuses(); a.add("mine")
check("8 retired: each caller gets its own set (a word added to one is in no other)", "mine" not in _prj.retired_statuses())
was = _cfg.CFG.get("project_scopes")
_cfg.CFG["project_scopes"] = {**(was or {}), "retired_statuses": [" Paused ", "SHELVED"]}
try:
    check("8 retired: a changed setting is seen at the next call, lowercased and stripped", _prj.retired_statuses() == {"paused", "shelved"}, _prj.retired_statuses())
    _cfg.CFG["project_scopes"]["retired_statuses"].append("wound-down")
    check("8 retired: a setting changed in place is seen", _prj.retired_statuses() == {"paused", "shelved", "wound-down"}, _prj.retired_statuses())
finally:
    if was is None: _cfg.CFG.pop("project_scopes", None)
    else: _cfg.CFG["project_scopes"] = was
check("8 retired: and the defaults come back with the setting gone", _prj.retired_statuses() == set(_RET_DEFAULT), _prj.retired_statuses())
was = _cfg.CFG.get("project_scopes")
_cfg.CFG["project_scopes"] = {k: v for k, v in (was or {}).items() if k != "retired_statuses"}       # no setting: the built-in defaults are the words
_prj._RETIRED.append("Shelved ")
try: check("8 retired: a changed default is seen", "shelved" in _prj.retired_statuses())
finally:
    _prj._RETIRED.pop()
    if was is None: _cfg.CFG.pop("project_scopes", None)
    else: _cfg.CFG["project_scopes"] = was
RC = [0]; _real_ret = _prj.retired_statuses
def _counting_ret():
    RC[0] += 1
    return _real_ret()
reset(record=None)
reg = _anc.registry()
_prj.retired_statuses = _counting_ret
try:
    _anc.session_roles(reg)
finally:
    _prj.retired_statuses = _real_ret
check("8 retired: the roles of four projects ask for the retired words once, not once per offer", RC[0] <= 1, RC[0])

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
