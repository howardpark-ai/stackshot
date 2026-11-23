"""Scenario tests for the work the server keeps while files are as they were and the work it does between requests, in two parts that each run in a process of their own (formerly the suites derived_cache and idle_scan): what the passes read and parse again and again.

Part `derived_cache` - what the server works out from files and keeps while they are as they were (core/filecache.py `derived`): the project registry the readers see (anchors.registry), the
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

Part `idle_scan` - what the server does between requests: the minute passes read the store, and the board's publish and the search index read the store's git (made-up data in a temp store and temp git repos,
no live store, no network).

  1  the scans of the store: a pass that looks for the open items (the anchor pass, the sent-mail views, the merge pass's ties, the phase sweep, the stall tick, the check pass) parses the files of the open items only
     once it has seen the closed ones: a closed item whose file has not changed is skipped on its `stat`. Pinned by counting the item files `json.load` parses over a store of many closed items and a few open ones, and
     by what a write does to the answer (a replaced file, a file written in place at once after a read, a later write of the same size).
  2  the History of an item (item_history.commits, behind Board.item_versions of both renderers): `git log --follow` over the whole store is read once per item and HEAD; a new commit asks only for the commits
     since (identical to the whole walk, checked against it at every step, a rename and a rewritten history included); the same HEAD asks git nothing.
  3  the page times of a brain (pages.git_times): the walk of every commit is made once per HEAD; a new commit is read on the next call.

The two parts set up two different instances (a base config with a fleet of sessions; a base config with the store, the brain and a transcripts folder), and each replaces or counts module state of the code under test that the other would find changed: so each part runs in a process of its own (this file started again with `--part <name>`), exactly as the two suites did, and the parent adds their check counts.

    tests/run-suite derived_cache        -> exit 0 / 1"""
import os, subprocess, sys
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
PARTS = ("derived_cache", "idle_scan")


# ================================================================ part derived_cache: what the server works out from files and keeps while they are as they were
def part_derived_cache():
    import contextlib, copy, json, os, re, sys, pathlib, time, logging
    from unittest import mock
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

    return ran, fails


# ================================================================ part idle_scan: what the server does between requests: the scans of the store, the History of an item, the page times
def part_idle_scan():
    import json, logging, os, pathlib, re, subprocess, sys, time
    import _scratch, _instance
    tmp = _scratch.mkdtemp(prefix="idlescan-"); T = pathlib.Path(tmp)
    toml = _instance.apply(_instance.base_toml())
    toml, n = re.subn(r'(?m)^session_links = "[^"]*"', 'session_links = ""', toml); assert n == 1
    for key, val in (("repo", f"{tmp}/store"), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/store/board.md"), ("brain", f"{tmp}/brain"),
                     ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
        toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
    toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
    toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1
    (T / "stackshot.toml").write_text(toml, encoding="utf-8")
    (T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
    os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
    os.environ.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")      # the commits go into the temp repos only
    for d in ("store/a", "fleet/a", "state", "brain/projects", "transcripts/-home-x"): (T / d).mkdir(parents=True)
    (T / "store/projects.json").write_text(json.dumps({"pages": {}})); (T / "store/next-id").write_text("500"); (T / "store/anchors.json").write_text("{}")
    (T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"})); (T / "fleet/a/sessions.json").write_text("{}")
    sys.path.insert(0, STACK); sys.path.insert(0, os.path.join(STACK, "tools")); logging.disable(logging.INFO)
    fails = []; ran = []
    def check(name, cond, got=None):
        ran.append(name)
        if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:300]}" if got is not None else ""))
    now0 = time.time()
    LONG_AGO = now0 - 3600.0


    def item_file(i, status, mtime=LONG_AGO, **meta):
        p = T / f"store/a/{i}.json"
        p.write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": "a thing\n" * 20, "status": status, "updated": now0 - 100, "state_updated": now0 - 100, "confirmed": now0 - 100,
                                 "metadata": {"project": "projects/alpha", **meta}}))
        if mtime: os.utime(p, ns=(int(mtime * 1e9), int(mtime * 1e9)))
        return p


    class Parsed:
        """Counts the reads of the item files while it is on: the files `json.load` parses and the ones `Path.read_text` reads (the two ways an item's file is read)."""
        def __init__(self): self.n = 0; self.real = json.load; self.real_text = pathlib.Path.read_text
        def __enter__(self):
            me = self
            def load(f, *a, **kw):
                if re.search(r"/store/a/\d+\.json$", str(getattr(f, "name", ""))): me.n += 1
                return me.real(f, *a, **kw)
            def read_text(path, *a, **kw):
                if re.search(r"/store/a/\d+\.json$", str(path)): me.n += 1
                return me.real_text(path, *a, **kw)
            json.load = load; pathlib.Path.read_text = read_text; return self
        def __exit__(self, *e): json.load = self.real; pathlib.Path.read_text = self.real_text


    try:
        from stackshot.web import server, wiring           # noqa: F401  — wires the hooks the passes call
        from stackshot.core import store as cstore
        from stackshot.service import store as svcstore, wakes, stamp, merge_progress, sent_match, checks, stall_tick, stall as stall_svc, event_waits, watching, proofs

        # ---- 1  the scans of the store
        N_CLOSED, OPEN = 60, (1, 2, 3, 4)
        for i in OPEN: item_file(i, "open")
        for i in range(10, 10 + N_CLOSED): item_file(i, "completed")
        item_file(9, "on_hold")                                                    # an old stored form of a hold: read as an open item
        scans = {
            "anchor_pass": lambda: wakes.anchor_pass(),
            "sent_match._views": lambda: sent_match._views(),
            "merge_progress._merge_tied": lambda: merge_progress._merge_tied([], now0),
            "stamp._phase_sweep": lambda: stamp._phase_sweep(),
            "checks.check_tick": lambda: (checks.CHECK_LAST.__setitem__(0, 0.0), checks.check_tick())[1],
            "event_waits.evwait_report": lambda: event_waits.evwait_report(event_waits._evwait_pr_event("pr_merged", "acme/widgets", 1), now0),
            "event_waits.evwait_box_poll": lambda: event_waits.evwait_box_poll(now0, {}),
            "event_waits._evwait_poll_prs": lambda: event_waits._evwait_poll_prs(now0, {}),
            "wakes.wake_rows": lambda: wakes.wake_rows(),
            "watching.watch_pass": lambda: watching.watch_pass(now0),
            "watching.watch_refresh_asks": lambda: watching.watch_refresh_asks(now0),
            "watching.watch_anchor_notice": lambda: watching.watch_anchor_notice("projects/alpha", "https://example.com/a", {"id": "n1", "text": "hi"}, now0, "a notice"),
            "proofs.sweep_proofs": lambda: proofs.sweep_proofs(dry=True, tick=True),
            "stall_tick": lambda: (stall_svc.STALL_LAST.__setitem__(0, 0.0), stall_tick.stall_tick())[1],
        }
        n_open = len(OPEN) + 1
        for name, run in scans.items():
            for k in list(svcstore._CLOSED): svcstore._CLOSED.pop(k)
            with Parsed() as first:
                try: run()
                except Exception as e: print(f"  ({name} raised {e.__class__.__name__}: {e})")
            with Parsed() as again:
                try: run()
                except Exception as e: print(f"  ({name} raised {e.__class__.__name__}: {e})")
            check(f"{name}: the first scan reads every file ({first.n} of {N_CLOSED + n_open})", first.n >= N_CLOSED, first.n)
            check(f"{name}: the next scan parses the files of the open items only ({again.n} of {N_CLOSED + n_open})", again.n <= 2 * n_open, again.n)

        # ---- the answer of the cheap path is the answer of `_load`
        for i in list(OPEN) + [9, 10, 11]:
            g = f"a{i}"; got = svcstore._load_open(g); want = svcstore._load(g)
            check(f"_load_open({g}): the item as `_load` reads it when it is open (a held one too), None when it is not", got == (want if want.get("status") == "open" else None), (got, want.get("status")))
        try: svcstore._load_open("a9999"); raised = False
        except Exception as e: raised = "no item" in str(e)
        check("_load_open of an item that does not exist raises 'no item', as `_load` does", raised)

        # ---- what a write does to the answer
        svcstore._CLOSED.clear()
        p = item_file(20, "completed")
        check("a closed item: None, and remembered", svcstore._load_open("a20") is None and str(p) in svcstore._CLOSED, list(svcstore._CLOSED)[:2])
        old = p.stat()
        item_file(20, "open", mtime=None)                                          # written in place: same inode, a later time
        check("a write in place (later time) shows the item again", (svcstore._load_open("a20") or {}).get("status") == "open", p.stat().st_mtime_ns)
        svcstore._CLOSED.clear()
        item_file(21, "completed"); check("a closed item again: remembered", svcstore._load_open("a21") is None and len(svcstore._CLOSED) == 1)
        tmpf = T / "store/a/.21.json.tmp"; tmpf.write_text(json.dumps({**json.loads((T / "store/a/21.json").read_text()), "status": "open"}))
        st21 = (T / "store/a/21.json").stat(); os.utime(tmpf, ns=(st21.st_atime_ns, st21.st_mtime_ns))
        pad = st21.st_size - tmpf.stat().st_size
        if pad > 0: tmpf.write_text(tmpf.read_text() + " " * pad); os.utime(tmpf, ns=(st21.st_atime_ns, st21.st_mtime_ns))
        same_size_and_time = tmpf.stat().st_size == st21.st_size and tmpf.stat().st_mtime_ns == st21.st_mtime_ns
        os.replace(tmpf, T / "store/a/21.json")                                     # the server's own way: a file renamed over it, the same size and time but another inode
        check("a replaced file of the same size and time shows the item again (the inode is part of what is remembered)", same_size_and_time and (svcstore._load_open("a21") or {}).get("status") == "open", same_size_and_time)
        svcstore._CLOSED.clear()
        pr = item_file(22, "completed", mtime=time.time())                                # written just now
        check("a file written within the last moments is never remembered", svcstore._load_open("a22") is None and not svcstore._CLOSED, list(svcstore._CLOSED))
        st = pr.stat(); body = json.loads(pr.read_text()); body["status"] = "open"; txt = json.dumps(body)
        txt = txt + " " * (st.st_size - len(txt)) if st.st_size >= len(txt) else txt
        pr.write_text(txt); os.utime(pr, ns=(st.st_atime_ns, st.st_mtime_ns))     # the same size, the same time, the same inode: a second write in one clock tick
        check("a second write of the same size in the same clock tick shows the item", pr.stat().st_size == st.st_size and (svcstore._load_open("a22") or {}).get("status") == "open", (pr.stat().st_size, st.st_size))

        # ---- 2  the History of an item
        from stackshot.web import item_history as ih
        G = T / "hist"; G.mkdir()
        def git(*a, when=None, cwd=G):
            env = {**os.environ, **({"GIT_AUTHOR_DATE": f"{int(when)} +0000", "GIT_COMMITTER_DATE": f"{int(when)} +0000"} if when else {})}
            r = subprocess.run(["git", "-C", str(cwd), *a], capture_output=True, text=True, env=env)
            assert r.returncode == 0, (a, r.stderr); return r.stdout
        def write(rel, n, repo=G):
            f = repo / rel; f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps({"id": "1", "subject": "item", "n": n, "description": "text\n" * 40})); git("add", rel, cwd=repo)
        def truth(rel, repo=G):
            r = subprocess.run(["git", "-C", str(repo), "log", "--follow", "--name-only", "--format=%x01%H%x09%ct", "--", rel], capture_output=True)
            return ih._parse(r.stdout)
        git("init", "-q", "-b", "main")
        for k in range(3): write("a/1.json", k); git("commit", "-q", "-m", f"c{k}", when=1_700_000_000 + 100 * k)
        logs = []; real_git = ih._git
        def spy(d, *args, **kw): logs.append(args); return real_git(d, *args, **kw)
        ih._git = spy
        try:
            ih._CACHE.clear(); ih.CALLS["log"] = 0
            a = ih.commits(str(G), "a/1.json")
            check("History: the whole walk, as `git log --follow` gives it", a == truth("a/1.json") and len(a) == 3 and ih.CALLS["log"] == 1, (a, ih.CALLS))
            logs.clear(); b = ih.commits(str(G), "a/1.json")
            check("History: the same HEAD asks git for no log", b == a and not [x for x in logs if x[0] == "log"] and ih.CALLS["log"] == 1, (logs, ih.CALLS))
            write("a/1.json", 3); git("commit", "-q", "-m", "c3", when=1_700_000_400); logs.clear()
            c = ih.commits(str(G), "a/1.json")
            ranged = [x for x in logs if x[0] == "log"]
            check("History: a new commit of the item asks only for the commits since, and the answer is the whole walk's", c == truth("a/1.json") and len(c) == 4 and ih.CALLS["log"] == 1 and len(ranged) == 1 and ".." in " ".join(ranged[0]), (len(c), ih.CALLS, ranged))
            write("b/2.json", 0); git("commit", "-q", "-m", "other", when=1_700_000_500); logs.clear()
            d_ = ih.commits(str(G), "a/1.json")
            check("History: a commit of another file changes nothing, and the walk is not made again", d_ == c == truth("a/1.json") and ih.CALLS["log"] == 1, (len(d_), ih.CALLS))
            git("mv", "a/1.json", "g1.json"); git("commit", "-q", "-m", "rename", when=1_700_000_600)
            e = ih.commits(str(G), "g1.json")
            check("History: after a rename the new path is walked whole and follows the old one", e == truth("g1.json") and len(e) == 5 and e[-1][2] == "a/1.json" and ih.CALLS["log"] == 2, (e, ih.CALLS))
            write("g1.json", 4); git("commit", "-q", "-m", "c4", when=1_700_000_700)
            f_ = ih.commits(str(G), "g1.json")
            check("History: a commit after the rename is asked for alone, the old names kept", f_ == truth("g1.json") and len(f_) == 6 and ih.CALLS["log"] == 2, (f_, ih.CALLS))
            git("reset", "-q", "--hard", "HEAD~1"); write("g1.json", 5); git("commit", "-q", "-m", "c5", when=1_700_000_800)
            g_ = ih.commits(str(G), "g1.json")
            check("History: a history that was rewritten (the HEAD kept is no ancestor) is walked whole again", g_ == truth("g1.json") and len(g_) == 6 and g_[0][0] not in {x[0] for x in f_} and ih.CALLS["log"] == 3, (g_, ih.CALLS))
            # a merge since the answer kept: the order of the walk is another one, so it is walked whole
            write("g1.json", 6); git("commit", "-q", "-m", "c6", when=1_700_000_900); ih.commits(str(G), "g1.json"); walks = ih.CALLS["log"]
            git("checkout", "-q", "-b", "side"); write("g1.json", 7); git("commit", "-q", "-m", "side", when=1_700_001_000)
            git("checkout", "-q", "main"); write("b/2.json", 8); git("commit", "-q", "-m", "main", when=1_700_001_100); git("merge", "-q", "--no-ff", "-m", "merge", "side", when=1_700_001_200)
            h_ = ih.commits(str(G), "g1.json")
            check("History: a merge since the answer kept makes the walk whole again, and the answer is its", h_ == truth("g1.json") and ih.CALLS["log"] == walks + 1, (len(h_), ih.CALLS, walks))
            # a deletion and a creation of the file since: for the whole walk too
            ih.commits(str(G), "g1.json"); walks = ih.CALLS["log"]
            git("rm", "-q", "g1.json"); git("commit", "-q", "-m", "gone", when=1_700_001_300); write("g1.json", 9); git("commit", "-q", "-m", "back", when=1_700_001_400)
            i_ = ih.commits(str(G), "g1.json")
            check("History: a file deleted and created again since is walked whole, and the answer is the walk's", i_ == truth("g1.json") and ih.CALLS["log"] == walks + 1, (len(i_), ih.CALLS, walks))
            check("History: git failing (no repository) is None, and nothing is kept", ih.commits(str(T / "brain"), "a/1.json") is None and (str(T / "brain"), "a/1.json") not in ih._CACHE)
        finally:
            ih._git = real_git
        # the two renderers read it through the module
        from stackshot.web import render as old_render
        from stackshot.web.ui import render as ui_render
        H = T / "histstore"; (H / "a").mkdir(parents=True)
        for fn in ("projects.json", "next-id", "anchors.json"): (H / fn).write_text((T / "store" / fn).read_text())
        git("init", "-q", "-b", "main", cwd=H)
        def put(n, when):
            (H / "a/7.json").write_text(json.dumps({"id": "7", "subject": "[home] seven", "description": "d", "status": "open", "updated": when, "state_updated": when, "confirmed": when, "written_by": "w",
                                                    "metadata": {"project": "projects/alpha", "n": n}}))
            git("add", "a/7.json", cwd=H); git("commit", "-q", "-m", f"v{n}", when=when, cwd=H)
        put(0, now0 - 900); put(1, now0 - 600)
        for label, mod in (("web/render.py", old_render), ("web/ui/render.py", ui_render)):
            bd = mod.Board(str(H)); row = next(r for r in bd.rows if r["gid"] == "a7"); ih._CACHE.clear(); ih.CALLS["log"] = 0
            v1 = bd.item_versions(row); v2 = bd.item_versions(row)
            check(f"{label} Board.item_versions: two reads, one walk of the history, the same versions", v1 == v2 and len(v1) >= 2 and ih.CALLS["log"] == 1, (len(v1), len(v2), ih.CALLS))
            put(len(v1) + 5, now0 - 100 * len(v1)); bd2 = mod.Board(str(H)); v3 = bd2.item_versions(next(r for r in bd2.rows if r["gid"] == "a7"))
            check(f"{label} Board.item_versions: a commit since is in the next read, with no new walk", len(v3) == len(v1) + 1 and ih.CALLS["log"] == 1, (len(v1), len(v3), ih.CALLS))
            git("reset", "-q", "--hard", "HEAD~1", cwd=H)

        # ---- 3  the page times of a brain
        from stackshot.projects import pages
        B = T / "brainrepo"; (B / "projects").mkdir(parents=True)
        git("init", "-q", "-b", "main", cwd=B)
        (B / "projects/x.md").write_text("# x\n"); git("add", "projects/x.md", cwd=B); git("commit", "-q", "-m", "x", when=1_700_000_000, cwd=B)
        pages._GT_CACHE.clear(); pages.GT_WALKS[0] = 0
        t1 = pages.git_times(("projects",), str(B)); t1b = pages.git_times(("projects",), str(B))
        check("git_times: the whole walk once for the same HEAD, the same answer", t1 == t1b == {"projects/x.md": 1_700_000_000} and pages.GT_WALKS[0] == 1, (t1, pages.GT_WALKS))
        t1b["projects/x.md"] = 5; t1c = pages.git_times(("projects",), str(B))
        check("git_times: a caller changing the answer does not change the one kept", t1c == {"projects/x.md": 1_700_000_000}, t1c)
        (B / "projects/y.md").write_text("# y\n"); (B / "projects/x.md").write_text("# x2\n"); git("add", "-A", cwd=B); git("commit", "-q", "-m", "y", when=1_700_000_900, cwd=B)
        t2 = pages.git_times(("projects",), str(B))
        check("git_times: a new commit is read on the next call (x is newer, y is there)", t2 == {"projects/x.md": 1_700_000_900, "projects/y.md": 1_700_000_900} and pages.GT_WALKS[0] == 2, (t2, pages.GT_WALKS))
        check("git_times: a second brain is kept apart", pages.git_times(("projects",), str(B)) == t2 and pages.GT_WALKS[0] == 2 and len(pages._GT_CACHE) == 1)
        check("git_times: a directory that is no repository is {} and is not kept", pages.git_times(("projects",), str(T / "state")) == {} and len(pages._GT_CACHE) == 1)
    except Exception:
        import traceback; traceback.print_exc(); fails.append("scenario raised")

    return ran, fails

MARK = "@@derived_cache part"
if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--part":
        name = sys.argv[2]; assert name in PARTS, name
        ran, fails = {"derived_cache": part_derived_cache, "idle_scan": part_idle_scan}[name]()
        print(f"{MARK} {name} {len(ran)} {len(fails)}"); sys.stdout.flush()
        os._exit(0)      # as both suites always ended: nothing a thread of the part left behind holds the process (tests/_scratch.py removes the scratch folder first)
    total = bad = 0
    for name in PARTS:
        r = subprocess.run([sys.executable, os.path.abspath(__file__), "--part", name], stdout=subprocess.PIPE, text=True)
        seen = [l for l in r.stdout.splitlines() if l.startswith(MARK + " ")]
        print("\n".join(l for l in r.stdout.splitlines() if not l.startswith(MARK + " ")))
        if r.returncode != 0 or len(seen) != 1:
            print(f"FAIL part {name} did not end cleanly (exit {r.returncode})"); bad += 1; continue
        _, _, _, n, f = seen[0].split(); total += int(n); bad += int(f)
        print(f"part {name}: {int(n) - int(f)}/{n} checks passed")
    if bad:
        print(f"\n{bad} failures in {total} checks"); sys.exit(1)
    print(f"ok: derived_cache scenario, {total} checks")
