"""Scenario tests for anchor-hub's GitHub receiver and the receivers service around it (stackshot/anchors), in two parts that each run in a process of their own (formerly the suites anchorhub_idle and
anchorhub_restart): fakes only, no network, no process of the hub is started.

Part `idle` - the CPU the receivers service uses between requests (fakes only, no network, no process of the hub is started).

What it pins, each as a scenario on the real code (1, 3 and 4 fail on the code before the change; 2 pins what must not change):
  1. The id switch ([github.moved]). adopt() runs for every bound anchor in a pass; it names every saved entry's current name once per table, not once per anchor:
     with 60 bound anchors and 300 saved entries a pass asks anchor_id a few hundred times (it asked tens of thousands of times), and the entry saved under
     the old name still moves to the id the bindings use, in the state and in the CI state.
  2. A merged pull request's look is as it was (the branch does not change it): its pull request and check runs are read at each of its looks, whatever its issue answers, so a
     check that finishes late or is re-run on it is seen.
  3. The watch on the bindings' folders asks watchdog for the four kinds of change the handler counts (modified, created, deleted, moved), so a read of
     the store (open, read, close) reaches no handler; a write still sets the flag, as before.
  4. A paused or held queue is not flushed by a process (push.py answers exit 5 and does nothing), a queue that is not held is, and a lifted hold flushes at the next
     pass; the question is push.py's own (flush_held), the same test as its --flush makes.

Part `restart` - anchor-hub's GitHub reads across a restart (a restart used to send a burst of
reads that hit the hourly cap and cut the pass short, so the board showed anchor-hub's github row as "error") - a fake GitHub that counts
its calls and answers ETags like GitHub (a 200 with an ETag, a 304 for a matching If-None-Match), the real hub and receiver, no network.

Covers: the first start (nothing saved) reads each anchor in full; a warm pass costs no counted read; the read position is saved with its ETags, the
resolutions of the board's labels and the learnt repository IDs, and the file write is atomic (temp + os.replace; a failed replace leaves the old
file). A restart with that file costs no counted read but GitHub's /user: every conditional read of an unchanged anchor is a 304, the start-up
rescan names every anchor from the saved resolution (a finished anchor with no call at all), nothing is reported twice. A change during the
downtime (a comment, a close, a reopening, on open and on finished anchors) is a 200 and is reported, once, with the repository ID. A finished
(closed or merged) anchor is read once in 10 passes (its CI, its issue and its comments), staggered; a reopening or a late comment is seen within
10 passes. An ETag is saved only once the pass has finished with its anchor: a save in the middle of a read, or after a comments read that failed,
leaves the older ETag, so the change is read again after a restart, not answered 304. ETags of another login, and a saved section that is damaged,
are not used. The first start with the new code over a file from before it (state, no ETags) costs less than a cold one.

The two parts set up two different instances (an example config with only the state and secrets folders in the scratch folder; a base config with the store, the board, the brain and a fleet of sessions in it) and
each replaces module state of the code under test (the GitHub receiver's subprocess, threading and time, the watchdog classes) that the other would find changed: so each part runs in a process of its own (this file started again with
`--part <name>`), exactly as the two suites did, and the parent adds their check counts. (A check against a real watchdog observer in part `idle` runs only where watchdog is installed; the others do not depend on it.)

    tests/run-suite anchorhub_restart        -> exit 0 / 1"""
import json, os, re, sys, pathlib, logging, types, subprocess, hashlib, zlib, time, threading
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
PARTS = ("idle", "restart")

def _setup(prefix, toml, paths, extra=()):
    """The scratch folder of a part and its instance config: the host's store of sessions switched off, each key of `paths` set (every path inside the scratch folder, and any other value), the (pattern, replacement) pairs
    of `extra` applied once each, stackshot.toml written and named in STACKSHOT_CONFIG. Returns (tmp, T)."""
    import _scratch
    tmp = _scratch.mkdtemp(prefix=prefix); T = pathlib.Path(tmp)
    toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's store of sessions
    for key, val in paths:
        toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val.replace("TMP", tmp)}"', toml); assert n == 1, key
    for pat, rep in extra:
        toml, n = re.subn(pat, rep, toml); assert n == 1, pat
    (T / "stackshot.toml").write_text(toml, encoding="utf-8"); os.environ["STACKSHOT_CONFIG"] = f"{tmp}/stackshot.toml"
    return tmp, T

def _checker(chatty):
    """check(name, cond, got) for a part: counts every check, prints a failing one with what it got; `chatty` also prints a passing one."""
    fails = []; ran = []
    def check(name, ok, got=None):
        ran.append(name)
        if chatty and ok: print("ok:   " + name, flush=True)
        if not ok: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""), flush=True)
    return check, fails, ran


# ================================================================ part idle: the CPU the receivers service uses between requests (formerly anchorhub_idle)
def part_idle():
    import _instance
    tmp, T = _setup("ahidle-", _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8")), (("state", "TMP/state"), ("secrets", "TMP/secrets")))
    for v in ("ANCHOR_HUB_ALLOW_SELF", "ANCHOR_PUSH_FORCE", "ANCHOR_PUSH_SOURCE"): os.environ.pop(v, None)
    sys.path.insert(0, STACK)

    _wd = threading.Timer(150, lambda: (print("FAIL: the scenario did not end in 150 s", flush=True), os._exit(3))); _wd.daemon = True; _wd.start()
    check, fails, ran = _checker(chatty=True)

    from stackshot.anchors.anchorhub import core, github as ghr
    from stackshot.anchors import anchor_hub as ah
    from stackshot.core import config as _cfg
    core.log.addHandler(logging.NullHandler()); core.log.propagate = False
    os.makedirs(core.ADIR, exist_ok=True)
    ADIR = pathlib.Path(core.ADIR)

    # ---- 1 and 2. the GitHub poll on a fake `gh`
    RP = "/repos/new/repo"
    calls: list[str] = []; cond_calls: list[str] = []; mode = {"304": False}
    def fake_gh(args, capture_output=True, text=True, timeout=30):
        a = [x for x in args[2:] if x != "-i" and x != "-H" and not x.startswith("If-None-Match")]; path = a[0]; cond = "-i" in args; calls.append(path)
        if path == "/user": return types.SimpleNamespace(returncode=0, stdout=json.dumps({"login": "oliver"}), stderr="")
        if cond and mode["304"] and "-H" in args: return types.SimpleNamespace(returncode=0, stdout="HTTP/2.0 304 Not Modified\n\n", stderr="")
        if path.endswith("/check-runs?per_page=100"): body = {"check_runs": [{"name": "suites", "status": "completed", "conclusion": "success"}]}
        elif "/pulls/" in path: body = {"head": {"sha": "a" * 40, "ref": "x/y"}, "user": {"login": "oliver"}, "base": {"repo": {"id": 7}}}
        else: body = {"state": "closed", "comments": 0, "updated_at": mode.get("updated", "2026-10-28T00:00:00Z"), "title": "a thing", "html_url": "https://github.com/new/repo/pull/1",
                      "pull_request": {"merged_at": "2026-10-27T00:00:00Z"}}
        return types.SimpleNamespace(returncode=0, stdout=("HTTP/2.0 200 OK\netag: \"x\"\n\n" + json.dumps(body)) if cond else json.dumps(body), stderr="")
    class _Stop(Exception): pass
    def _no_sleep(s): raise _Stop()
    caught: list = []
    ghr.subprocess = types.SimpleNamespace(run=fake_gh, TimeoutExpired=subprocess.TimeoutExpired)
    ghr.threading = types.SimpleNamespace(Thread=lambda target, daemon=True: types.SimpleNamespace(start=lambda: caught.append(target)))
    ghr.time = types.SimpleNamespace(time=time.time, sleep=_no_sleep)
    def one_pass():
        try: caught[-1]()
        except _Stop: pass

    def new_hub(bound, saved_state, saved_ci):
        h = core.Hub(); h.write_status = lambda: None; h.emit = lambda ev: None; h.bindings = {a: {"s"} for a in bound}
        h.saved = {"github": {"me": "oliver", "state": saved_state, "ci": saved_ci, "looked": {k: 1.0 for k in saved_state}}}      # every saved anchor was read before (an anchor not in `looked` is a catch-up's, read in full whatever its state)
        caught.clear(); ghr.run(h); return h

    CLOSED = {"state": "closed", "comments": 0, "updated": "2026-10-28T00:00:00Z", "pr": True, "merged": True}
    CI = {"pr": True, "sha": "a" * 40, "key": ["a" * 40, []], "head_ref": "x/y", "author": "oliver", "own_branch": True, "looked": time.time()}
    N, M = 60, 300
    bound = [f"github:new/repo#{i}" for i in range(N)]
    saved = {f"github:new/repo#{i}": dict(CLOSED) for i in range(M)}
    saved_ci = {f"github:new/repo#{i}": dict(CI) for i in range(M)}
    saved["github:old/repo#5"] = dict(CLOSED, comments=3); saved_ci["github:old/repo#5"] = dict(CI, sha="b" * 40)      # the entry of an anchor saved under the repository's old name
    saved.pop("github:new/repo#5"); saved_ci.pop("github:new/repo#5")
    saved["github:older/repo#7"] = dict(CLOSED, comments=9); saved.pop("github:new/repo#7")      # a repository the first table does not know, and the second does
    real_moved = _cfg.moved_repos; real_anchor_id = ghr._anc.anchor_id
    n_anchor_id = [0]
    def counting_anchor_id(u): n_anchor_id[0] += 1; return real_anchor_id(u)
    try:
        h = new_hub(bound, saved, saved_ci)          # started with an empty table: the old name stays what it was saved as
        check("setup: the saved entry of the old name is still under it before the table is given", "github:old/repo#5" in h.gh_state["state"] and "github:new/repo#5" not in h.gh_state["state"], list(h.gh_state["state"])[:3])
        _cfg.moved_repos = lambda: {"old/repo": "new/repo"}          # a pair added while the hub runs (a config reload)
        ghr._anc.anchor_id = counting_anchor_id
        mode["304"] = True; one_pass()
        n_ids = n_anchor_id[0]
        check(f"adopt: a pass over {N} bound anchors and {M} saved entries names each entry once, not once per anchor ({n_ids} asks; it was {2 * N * M} and more)", n_ids <= 2 * (M + N), n_ids)
        ghr._anc.anchor_id = real_anchor_id
        check("…the entry saved under the old name moved to the id the bindings use, in the state and in the CI state, and nothing stays under the old name",
              h.gh_state["state"].get("github:new/repo#5", {}).get("comments") == 3 and h.gh_state["ci"].get("github:new/repo#5", {}).get("sha") == "b" * 40
              and "github:old/repo#5" not in h.gh_state["state"] and "github:old/repo#5" not in h.gh_state["ci"], (h.gh_state["state"].get("github:new/repo#5"), "github:old/repo#5" in h.gh_state["state"]))
        # the table changes (a second pair): what was remembered is made again
        saved2 = h.gh_state["state"]
        saved2.pop("github:new/repo#7", None); h.gh_state["ci"].pop("github:new/repo#7", None)      # the first pass seeded it (the entry of the older name stayed, as that name was no repository's old name yet)
        check("setup: the first table left the entry of the repository it does not know where it was", "github:older/repo#7" in saved2 and "github:new/repo#7" not in saved2, [k for k in saved2 if k.endswith("#7")])
        _cfg.moved_repos = lambda: {"old/repo": "new/repo", "older/repo": "new/repo"}; one_pass()
        check("…and a table that changes is read afresh: an entry of the newly named repository moves too", saved2.get("github:new/repo#7", {}).get("comments") == 9 and "github:older/repo#7" not in saved2, saved2.get("github:new/repo#7"))
        _cfg.moved_repos = real_moved

        # the memo is bounded: past 20000 remembered names it is dropped and made again, and the move still happens
        big = {f"github:new/repo#{i}": dict(CLOSED) for i in range(20100, 40300)}; big_ci = {k: dict(CI) for k in big}
        big["github:old/repo#9"] = dict(CLOSED, comments=4); big_ci["github:old/repo#9"] = dict(CI, sha="c" * 40)
        _cfg.moved_repos = lambda: {"old/repo": "new/repo"}
        h = new_hub(["github:new/repo#9", "github:new/repo#10", "github:new/repo#11"], big, big_ci); mode["304"] = True; one_pass()
        check("adopt: with more than 20000 saved entries the memo is dropped and made again, and the entry of the old name still moves to the id the bindings use",
              h.gh_state["state"].get("github:new/repo#9", {}).get("comments") == 4 and h.gh_state["ci"].get("github:new/repo#9", {}).get("sha") == "c" * 40
              and "github:old/repo#9" not in h.gh_state["state"], h.gh_state["state"].get("github:new/repo#9"))
        _cfg.moved_repos = real_moved

        # ---- 2. a merged pull request's look is as it was: its CI first, then the issue, and the CI is read whatever the issue answers
        n = next(i for i in range(1000) if zlib.crc32(f"github:new/repo#{i}".encode()) % ghr.FINISHED_EVERY == 0)      # an anchor whose turn is the first pass
        a_id = f"github:new/repo#{n}"
        h = new_hub([a_id], {a_id: dict(CLOSED)}, {a_id: dict(CI)})
        mode["304"] = False; calls.clear(); one_pass()
        check("merged look: its pull request and check runs are read, then the issue",
              calls[:2] == [f"{RP}/pulls/{n}", f"{RP}/commits/{'a' * 40}/check-runs?per_page=100"] and calls[-1] == f"{RP}/issues/{n}", calls)
        for _ in range(ghr.FINISHED_EVERY - 1): one_pass()
        mode["304"] = True; calls.clear(); one_pass()
        check("…and when the issue answers 304 the pull request and its check runs are read all the same (a check that finishes late or is re-run on a merged pull request is not missed)",
              f"{RP}/issues/{n}" in calls and f"{RP}/pulls/{n}" in calls and any("check-runs" in c for c in calls), calls)
        calls.clear(); one_pass()
        check("…and the pass after its turn reads nothing of it", calls == [], calls)
        for _ in range(ghr.FINISHED_EVERY - 2): one_pass()
        mode["304"] = False; mode["updated"] = "2026-10-29T00:00:00Z"; calls.clear(); one_pass()
        check("…the anchor's saved state takes in a change of the issue", h.gh_state["state"][a_id]["updated"] == "2026-10-29T00:00:00Z", h.gh_state["state"][a_id])
        mode.pop("updated")
    finally:
        _cfg.moved_repos = real_moved; ghr._anc.anchor_id = real_anchor_id

    # ---- 3. the watch on the bindings' folders
    class Obs:
        def __init__(self): self.sched = []
        def schedule(self, handler, path, recursive=False, **kw): self.sched.append((path, recursive, kw))
    try: import watchdog.events, watchdog.observers; HAVE_WD = True
    except ImportError:      # the test environment has no watchdog (the receivers' extra carries it): the four classes stand in for it, and the check against a real observer is skipped
        HAVE_WD = False
        class _Ev:
            def __init__(self, *a): self.src_path = a[0] if a else ""; self.dest_path = a[1] if len(a) > 1 else ""
        _evs = types.ModuleType("watchdog.events"); _evs.FileSystemEventHandler = object
        for _n in ("FileCreatedEvent", "FileDeletedEvent", "FileModifiedEvent", "FileMovedEvent"): setattr(_evs, _n, type(_n, (_Ev,), {}))
        sys.modules["watchdog"] = types.ModuleType("watchdog"); sys.modules["watchdog.events"] = _evs
    from watchdog.events import FileCreatedEvent, FileDeletedEvent, FileModifiedEvent, FileMovedEvent
    o = Obs(); ah.watch_dirs(o, object(), ["/a", "/b"])
    check("watch: every folder is scheduled with the four kinds of change the handler counts, and only those",
          [p for p, _, _ in o.sched] == ["/a", "/b"] and all(not r and set(kw.get("event_filter") or ()) == {FileModifiedEvent, FileCreatedEvent, FileDeletedEvent, FileMovedEvent} for _, r, kw in o.sched), o.sched)
    class Old:
        def __init__(self): self.sched = []
        def schedule(self, handler, path, recursive=False):
            self.sched.append(path)
    o2 = Old(); ah.watch_dirs(o2, object(), ["/a"])
    check("…a watchdog without event_filter is scheduled as before (every event, the handler drops the rest)", o2.sched == ["/a"], o2.sched)

    def hit(etype, path, dest=""):
        d = threading.Event(); ah.change_handler(d).on_any_event(types.SimpleNamespace(event_type=etype, src_path=path, dest_path=dest)); return d.is_set()
    check("handler: a change of a .json file in the store counts (modified, created, deleted, moved to a .json name); an open, a close and another file do not",
          hit("modified", "/s/anchors.json") and hit("created", "/s/a/x.json") and hit("deleted", "/s/a/x.json") and hit("moved", "/s/a/x.tmp", "/s/a/x.json")
          and not hit("opened", "/s/anchors.json") and not hit("closed", "/s/anchors.json") and not hit("modified", "/s/notes.txt"))
    check("…in the hub's own folder only extra.json and a pause flag count, never its status or read positions",
          hit("modified", f"{core.ADIR}/extra.json") and hit("created", f"{core.ADIR}/paused-hub.json") and not hit("modified", f"{core.ADIR}/status.json") and not hit("modified", f"{core.ADIR}/cursors.json"))

    if not HAVE_WD: print("skip: no watchdog in this environment, the observer on a real folder is not run", flush=True)
    if HAVE_WD:
      from watchdog.observers import Observer
      wd = pathlib.Path(tmp, "watched"); wd.mkdir(); (wd / "anchors.json").write_text("{}")
      dirty = threading.Event(); handler = ah.change_handler(dirty); seen: list[str] = []
      real_on = handler.on_any_event
      handler.on_any_event = lambda e: (seen.append(type(e).__name__), real_on(e))[1]
      obs = Observer(); ah.watch_dirs(obs, handler, [str(wd)]); obs.daemon = True; obs.start()
      try:
          time.sleep(0.5)
          for _ in range(20): open(wd / "anchors.json").read(); os.stat(wd / "anchors.json"); os.listdir(wd)
          time.sleep(1.0)
          check("watch: reading the store (open, read, close, list) reaches no handler and sets no flag", seen == [] and not dirty.is_set(), (seen, dirty.is_set()))
          (wd / "anchors.json.tmp").write_text("{\"a\": 1}"); os.replace(wd / "anchors.json.tmp", wd / "anchors.json")
          dirty.wait(5)
          check("…a write (a file replaced over anchors.json) still sets the flag", dirty.is_set() and seen, (seen, dirty.is_set()))
          dirty.clear(); seen.clear(); (wd / "x.json").write_text("1"); dirty.wait(5)
          check("…a created file does, and so does a deleted one", dirty.is_set(), seen)
          dirty.clear(); os.remove(wd / "x.json"); dirty.wait(5)
          check("…a deletion of a .json file sets it", dirty.is_set(), seen)
      finally:
          obs.stop(); obs.join(5)

    # ---- 4. the flush of the queues
    spawned: list[tuple[str, str]] = []
    def fake_run(args, capture_output=True, text=True, env=None, **k):
        spawned.append((args[-1], (env or {}).get("ANCHOR_PUSH_SOURCE", ""))); return types.SimpleNamespace(returncode=5, stdout="", stderr="")
    real_sub = core.subprocess; core.subprocess = types.SimpleNamespace(run=fake_run, TimeoutExpired=subprocess.TimeoutExpired, PIPE=subprocess.PIPE)
    try:
        hq = core.Hub(); qh = ADIR / "queue"; qm = ADIR / "queue-msg"; qh.mkdir(exist_ok=True); qm.mkdir(exist_ok=True)
        for d, names in ((qh, ("held-one", "free-one")), (qm, ("held-one", "free-msg"))):
            for nm in names: (d / f"{nm}.jsonl").write_text('{"text": "x"}\n')
        (ADIR / "held-hub.txt").write_text("held-one\n")          # a hold on the hub's queue of one session
        hq.flush_queues()
        check("flush: a queue held by a hold file starts no process; the queues that are not held do", sorted(spawned) == [("free-msg", "msg"), ("free-one", "hub"), ("held-one", "msg")], spawned)
        (ADIR / "paused-msg.json").write_text("{}"); spawned.clear(); hq.flush_queues()
        check("…a source paused for a reboot flushes nothing (every one of its queues is skipped); the other source is flushed as before", sorted(spawned) == [("free-one", "hub")], spawned)
        (ADIR / "paused-msg.json").unlink(); (ADIR / "held-hub.txt").unlink(); spawned.clear(); hq.flush_queues()
        check("…a lifted hold or pause flushes at the next pass: all four queues are flushed", len(spawned) == 4, spawned)
        (ADIR / "held-hub.txt").write_text("free-one\n"); (ADIR / "held-api-msg.txt").write_text("free-msg\n"); spawned.clear(); hq.flush_queues()
        check("…the three hold files all count (held-<source>, held-resume-<source>, held-api-<source>)", sorted(spawned) == [("held-one", "hub"), ("held-one", "msg")], spawned)
        real_held = core.Hub.held_queue
        core.Hub.held_queue = lambda self, name, src: False
        spawned.clear(); hq.flush_queues(); core.Hub.held_queue = real_held
        check("…and a queue is flushed by a process whenever the hold test says no (the process decides, as ever)", len(spawned) == 4, spawned)
    finally:
        core.subprocess = real_sub

    return ran, fails


# ================================================================ part restart: anchor-hub's GitHub reads across a restart (formerly anchorhub_restart)
def part_restart():
    import _instance
    tmp, T = _setup("ah-restart-", _instance.apply(_instance.base_toml()),
                    (("repo", "TMP"), ("store", "TMP/store"), ("markdown", "TMP/board.md"), ("brain", "TMP/brain"), ("state", "TMP/state"), ("secrets", "TMP/secrets"), ("project_touch", "TMP/touch"), ("timezone", "Asia/Dubai")),
                    ((r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]'),))
    os.environ.update(STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet")
    sys.path.insert(0, STACK); logging.disable(logging.WARNING)
    check, fails, ran = _checker(chatty=False)
    S, A = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"
    for d in ("store/a", "fleet/a", "state/anchor-hub", "secrets", "touch", "repo"): (T / d).mkdir(parents=True)
    (T / "fleet/a/sessions.json").write_text(json.dumps({S: {"name": "osprey", "machine": "a", "url": "", "seen": "x"}, A: {"name": "osprey-main", "machine": "a", "url": "", "seen": "x"}}))
    (T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
    (T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project", "session": "osprey", "status": "active",
                                                                                  "board": [], "board_row": False, "updated": 1, "mirror": "https://example.invalid/alpha"}}}))
    OPEN_PR, MERGED, CLOSED_PR, MERGED2, MERGED3 = 1, 2, 3, 4, 5            # pull requests
    CLOSED_ISSUES, OPEN_ISSUE = (13, 14, 15), 17
    PRS = (OPEN_PR, MERGED, CLOSED_PR, MERGED2, MERGED3)
    ALL = PRS + CLOSED_ISSUES + (OPEN_ISSUE,)
    FINISHED = (MERGED, MERGED2, MERGED3) + CLOSED_ISSUES                      # merged pull requests and closed issues: looked at once in 10 passes
    CLOSED = FINISHED + (CLOSED_PR,)                                          # …and a closed pull request that is not merged: still read every pass (it can be reopened and merged)
    aid = lambda n: f"github:o/r#{n}"
    (T / "store/anchors.json").write_text(json.dumps({"projects/alpha": [{"url": f"https://github.com/o/r/{'pull' if n in PRS else 'issues'}/{n}", "items": None, "added": 1, "by": "t"} for n in ALL]}))
    (T / "store/next-id").write_text("10")
    # ---- a fake GitHub: one repository o/r (ID 7), ETags like GitHub's (the hash of the answer), every call logged
    class Fake:
        def __init__(self):
            self.login = "oliver"; self.tick = 0; self.issues = {}; self.comments = {}; self.ci = {}; self.fail = set()
            for n in ALL:
                fin = n in CLOSED
                self.issues[n] = {"number": n, "state": "closed" if fin else "open", "comments": 0, "title": f"thing {n}", "user": {"login": "kim"},
                                  "html_url": f"https://github.com/o/r/{'pull' if n in PRS else 'issues'}/{n}", "created_at": "2026-10-20T00:00:00Z",
                                  "closed_at": "2026-10-25T00:00:00Z" if fin else None, "closed_by": {"login": "kim"} if fin else None,
                                  "updated_at": "2026-10-25T00:00:00Z", "repository": {"id": 7}}
                if n in PRS: self.issues[n]["pull_request"] = {"merged_at": "2026-10-25T00:00:00Z" if n in (MERGED, MERGED2, MERGED3) else None}
                self.comments[n] = []; self.ci[n] = "success"
            for n, k in ((MERGED, 1), (14, 2), (OPEN_ISSUE, 1)):
                for j in range(k): self.add_comment(n, f"early {j}", "2026-10-21T00:0%d:00Z" % j)
            self.log = []; self.phase = ""
        def stamp(self):
            self.tick += 1; return "2026-10-28T%02d:%02d:00Z" % (self.tick // 60, self.tick % 60)
        def add_comment(self, n, body, at=None, login="kim"):
            at = at or self.stamp(); i = self.issues[n]
            self.comments[n].append({"user": {"login": login}, "body": body, "html_url": f"https://github.com/o/r/issues/{n}#c{len(self.comments[n])}", "created_at": at})
            i["comments"] = len(self.comments[n]); i["updated_at"] = max(i["updated_at"], at)
        def set_state(self, n, st):
            i = self.issues[n]; i["state"] = st; i["updated_at"] = self.stamp(); i["closed_at"] = i["updated_at"] if st == "closed" else None; i["closed_by"] = {"login": "kim"} if st == "closed" else None
        def body(self, path):
            if path == "/user": return 200, {"login": self.login}
            if (m := re.fullmatch(r"/repos/o/r/issues/(\d+)", path)) and int(m.group(1)) in self.issues: return 200, self.issues[int(m.group(1))]
            if m := re.fullmatch(r"/repos/o/r/issues/(\d+)/comments\?(.*)", path):
                cs = self.comments[int(m.group(1))]; since = re.search(r"since=([^&]+)", m.group(2))
                return 200, [c for c in cs if not since or c["created_at"] >= since.group(1)]
            if (m := re.fullmatch(r"/repos/o/r/pulls/(\d+)", path)) and int(m.group(1)) in PRS:
                return 200, {"head": {"sha": f"{int(m.group(1)):040x}", "ref": "x/y"}, "user": {"login": "kim"}, "base": {"repo": {"id": 7}}}
            if m := re.fullmatch(r"/repos/o/r/commits/([0-9a-f]{40})/check-runs\?per_page=100", path):
                return 200, {"check_runs": [{"name": "suites", "status": "completed", "conclusion": self.ci[int(m.group(1), 16)]}]}
            return 404, {"message": "Not Found"}
        def gh(self, args, capture_output=True, text=True, timeout=30):
            cond = "-i" in args
            inm = next((args[k + 1][len("If-None-Match: "):] for k, x in enumerate(args) if x == "-H"), None)
            path = next(x for x in args[2:] if x not in ("-i", "-H") and not x.startswith("If-None-Match"))
            if path in self.fail:
                self.log.append((path, 500, cond, self.phase)); return types.SimpleNamespace(returncode=1, stdout="", stderr="gh: Server Error (HTTP 500)")
            code, obj = self.body(path); text_ = json.dumps(obj, sort_keys=True); tag = '"' + hashlib.sha1(text_.encode()).hexdigest()[:16] + '"'
            if code == 200 and cond and inm == tag:
                self.log.append((path, 304, cond, self.phase)); return types.SimpleNamespace(returncode=0, stdout="HTTP/2.0 304 Not Modified\n\n", stderr="")
            self.log.append((path, code, cond, self.phase))
            if code != 200: return types.SimpleNamespace(returncode=1, stdout=("HTTP/2.0 404 Not Found\n\n" + text_) if cond else "", stderr="gh: Not Found (HTTP 404)")
            return types.SimpleNamespace(returncode=0, stdout=(f"HTTP/2.0 200 OK\netag: {tag}\n\n" + text_) if cond else text_, stderr="")
        def counted(self, phase=None, path=None):
            """Calls GitHub counts against the budget: every answer but a 304 (the fake's own 500 is a call too)."""
            return [c for c in self.log if c[1] != 304 and (phase is None or c[3] == phase) and (path is None or path(c[0]))]
        def calls(self, phase=None, path=None): return [c for c in self.log if (phase is None or c[3] == phase) and (path is None or path(c[0]))]


    F = Fake()
    from stackshot.anchors.anchorhub import core
    import stackshot.anchors.anchorhub.github as ghr
    from stackshot.core import ghbudget as _gb
    ghr.subprocess = types.SimpleNamespace(run=F.gh, TimeoutExpired=subprocess.TimeoutExpired)
    caught = []; ghr.threading = types.SimpleNamespace(Thread=lambda target, daemon=True: types.SimpleNamespace(start=lambda: caught.append(target)))
    class Stop(Exception): pass
    tick = {"pass": 0, "limit": 1, "between": None}
    def _sleep(s):
        k = tick["pass"]; tick["pass"] += 1
        if tick["between"]: tick["between"](k)
        if tick["pass"] >= tick["limit"]: raise Stop()
    ghr.time = types.SimpleNamespace(time=__import__("time").time, sleep=_sleep)
    events = []
    def boot(phase):
        """A start of anchor-hub as anchor-hub.py makes it: the hub (reading the saved positions), a rescan before the receivers, the github receiver, a rescan after."""
        F.phase = phase; caught.clear()
        hub = core.Hub(); hub.deliver = lambda *a, **k: None; hub.flush_queues = lambda: None
        hub.event = lambda a_id, ev, kind=None: events.append((a_id, ev.get("etype"), ev.get("who"), ev.get("text"), ev.get("repo_id"))) or (on_event[0] and on_event[0](hub, a_id, ev))
        hub.rescan(); ghr.run(hub); hub.rescan()
        return hub
    on_event = [None]
    def passes(k, between=None, phase=None):
        """k passes of the poll loop (one call runs them; `between(i)` runs after pass i, before the next)."""
        if phase is not None: F.phase = phase
        tick.update({"pass": 0, "limit": k, "between": between})
        try: caught[0]()
        except Stop: pass
    def saved(): return json.load(open(core.CURSORS)).get("github") or {}
    def saved_state(h): h.persist(); return saved()["state"]
    def status(): return json.load(open(core.STATUS))["anchors"]
    is_issue = lambda n: (lambda p: bool(re.match(rf"/repos/o/r/(issues|pulls)/{n}(?:/|\?|$)", p)) or p.startswith(f"/repos/o/r/commits/{n:040x}/"))

    # ---- 1. the first start, nothing saved: every anchor is read in full
    hub = boot("cold-start")
    cold_start = len(F.counted("cold-start"))
    passes(1, phase="cold-pass1"); cold1 = len(F.counted("cold-pass1"))
    check("cold start: GET /user, then the start-up rescan names each of the 9 anchors (its issue, and one comments page for the 3 that have comments)", cold_start == 1 + 9 + 3, [c[0] for c in F.counted("cold-start")])
    check("cold first pass: a pull request costs 3 reads (pull, check runs, issue), an issue 2 (the pull request 18 it is not, the issue): 5×3 + 4×2", cold1 == 5 * 3 + 4 * 2, [c[0] for c in F.counted("cold-pass1")])
    check("…nothing is reported (a first sight seeds)", not events, events)
    st0 = status(); labels0 = {a: st0[a]["label"] for a in st0}
    check("…the board names every anchor", len(labels0) == 9 and all(f'thing {a.rsplit("#", 1)[1]}' in l for a, l in labels0.items()), labels0)
    passes(2, phase="warm"); warm = F.counted("warm")
    check("warm passes: no counted read (every conditional read is a 304; the finished anchors are mostly not read at all)", not warm, [c[0] for c in warm])
    check("…the open pull request is read (as 304) every pass", len(F.calls("warm", is_issue(OPEN_PR))) == 3 * 2 and all(c[1] == 304 for c in F.calls("warm", is_issue(OPEN_PR))), F.calls("warm", is_issue(OPEN_PR)))
    check("the cold run's ledger agrees: the reads GitHub counted are the fake's non-304 answers", _gb.count("r") == len(F.counted()), (_gb.count("r"), len(F.counted())))

    # ---- 2. the saved file
    hub.persist(); sv = saved()
    check("the saved github position holds state and ci as before", set(sv["state"]) == {aid(n) for n in ALL} and aid(OPEN_PR) in sv["ci"], list(sv))
    check("…and the ETags of every anchor, the labels' resolutions and the repository ID", set(sv["etags"]) == {aid(n) for n in ALL}
          and set(sv["resolved"]) == {aid(n) for n in ALL} and sv["repo_ids"] == {"o/r": 7} and sv["me"] == "oliver", {k: (list(v)[:3] if isinstance(v, dict) else v) for k, v in sv.items()})
    check("…an issue's ETags are its issue (and for a pull request its pull request and check runs of the newest commit)", sorted(sv["etags"][aid(OPEN_PR)]) == sorted(["/repos/o/r/issues/1", "/repos/o/r/pulls/1", f"/repos/o/r/commits/{1:040x}/check-runs?per_page=100"]), sv["etags"][aid(OPEN_PR)])
    check("…the file is written aside and replaced: no temp file is left", not os.path.exists(core.CURSORS + ".tmp") and json.load(open(core.CURSORS))["saved"], os.listdir(os.path.dirname(core.CURSORS)))
    before = open(core.CURSORS).read(); _rep = core.os.replace
    def _boom(a, b): raise OSError("disk full")
    core.os.replace = _boom
    try:
        try: hub.persist(); err = ""
        except OSError as e: err = str(e)
    finally: core.os.replace = _rep
    check("a save whose replace fails leaves the old file whole (atomic write)", err == "disk full" and open(core.CURSORS).read() == before, err)
    hub.persist()

    # ---- 3. a restart with the file: no counted read but /user; nothing reported; the rescan does not read every anchor again
    hub2 = boot("restart-1")
    n_boot = F.counted("restart-1"); rescan_calls = F.calls("restart-1")
    check("restart: the start-up costs one counted read (GET /user)", [c[0] for c in n_boot] == ["/user"], [c[0] for c in n_boot])
    check("…the rescan reads no finished anchor at all (their labels come from the saved resolution)", not [c for c in rescan_calls if any(is_issue(n)(c[0]) for n in FINISHED)], [c[0] for c in rescan_calls])
    check("…and the two open ones are asked as 304s", sorted(c[0] for c in rescan_calls if c[0] != "/user") == ["/repos/o/r/issues/1", "/repos/o/r/issues/17"] and all(c[1] == 304 for c in rescan_calls if c[0] != "/user"), [(c[0], c[1]) for c in rescan_calls])
    st1 = status()
    check("…every anchor is named exactly as before", {a: st1[a]["label"] for a in st1} == labels0, {a: st1[a]["label"] for a in st1})
    passes(1, phase="restart-1-pass1")
    check("restart, first pass: no counted read, nothing reported (what was read is a 304)", not F.counted("restart-1-pass1") and not events, ([c[0] for c in F.counted("restart-1-pass1")], events))
    first_read = {n for n in FINISHED if F.calls("restart-1-pass1", is_issue(n))}
    check("…of the 6 finished anchors only those due in this pass were read (not all of them)", len(first_read) < 6, first_read)

    # ---- 4. a finished anchor is read once in 10 passes
    F.phase = "cadence"; passes(20, phase="cadence")
    for n in (MERGED2, CLOSED_ISSUES[0]):
        cs = F.calls("cadence", lambda p, n=n: p == f"/repos/o/r/issues/{n}")
        check(f"a finished anchor (#{n}) is read twice in 20 passes, as 304s", len(cs) == 2 and all(c[1] == 304 for c in cs), cs)
    cp = F.calls("cadence", lambda p: p == f"/repos/o/r/pulls/{MERGED2}")
    check("…and so is its pull request's CI read (not every pass)", len(cp) == 2, cp)
    check("…an open one is read every pass", len(F.calls("cadence", lambda p: p == "/repos/o/r/issues/17")) == 20, len(F.calls("cadence", lambda p: p == "/repos/o/r/issues/17")))
    stag = {k: sum(1 for n in FINISHED if (k + zlib.crc32(aid(n).encode())) % 10 == 0) for k in range(10)}
    check("…they are staggered over the 10 passes, not all in one", max(stag.values()) < 6 and sum(stag.values()) == 6, stag)
    check("…and nothing was reported meanwhile", not events and not F.counted("cadence"), (events, F.counted("cadence")))
    hub2.persist()

    # ---- 5. changes while the hub was down are still reported after a restart with ETags
    F.add_comment(OPEN_PR, "please look"); F.add_comment(OPEN_ISSUE, "me too"); F.set_state(OPEN_ISSUE, "closed")     # on open anchors
    F.add_comment(MERGED, "late word"); F.set_state(CLOSED_PR, "open")                                              # on finished anchors: a late comment, a reopening
    F.ci[OPEN_PR] = "failure"
    hub3 = boot("restart-2")
    check("a change during downtime: the restart still costs /user only (the rescan finds the changed open anchors as 200s: 1 issue each, + 1 comments page for the two with comments)",
          sorted(c[0] for c in F.counted("restart-2")) == sorted(["/user", "/repos/o/r/issues/1", "/repos/o/r/issues/17", "/repos/o/r/issues/17/comments?per_page=100&page=1", "/repos/o/r/issues/1/comments?per_page=100&page=1"]), [c[0] for c in F.counted("restart-2")])
    passes(1, phase="restart-2-pass1")
    got = {(e[0], e[1]) for e in events}
    check("…the comment and the CI failure on the open pull request and the comment and close on the open issue are reported in the first pass",
          (aid(OPEN_PR), "comment") in got and (aid(OPEN_PR), "ci_failed") in got and (aid(OPEN_ISSUE), "comment") in got and (aid(OPEN_ISSUE), "issue_closed") in got, events)
    check("…the repository ID learnt before the restart is on the event (it is saved with the position)", all(e[4] == 7 for e in events), events)
    unchanged = [c for c in F.counted("restart-2-pass1") if not (is_issue(OPEN_PR)(c[0]) or is_issue(OPEN_ISSUE)(c[0]) or is_issue(MERGED)(c[0]) or is_issue(CLOSED_PR)(c[0]))]
    check("…and the unchanged anchors cost nothing in it", not unchanged, [c[0] for c in unchanged])
    passes(10, phase="restart-2-late")
    got = [(e[0], e[1]) for e in events]
    check("…the late comment on the merged pull request is reported once, within 10 passes", got.count((aid(MERGED), "comment")) == 1, events)
    check("…the reopening of the closed pull request is reported once, within 10 passes", got.count((aid(CLOSED_PR), "pr_reopened")) == 1, events)
    check("…and nothing is reported twice", len(got) == len(set(got)), events)
    passes(3, phase="restart-2-after")
    pl = F.calls("restart-2-after", lambda p: p == f"/repos/o/r/issues/{CLOSED_PR}")
    check("…the reopened anchor is read in every pass from then on (it is not finished any more), as a 304", len(pl) == 3 and all(c[1] == 304 for c in pl), pl)
    hub3.persist()

    # ---- 6. a save in the middle of a read never holds an ETag the saved state has not taken in
    F.add_comment(OPEN_PR, "second thing")
    mid = {}
    def save_mid(hub, a_id, ev):
        if "file" not in mid: hub.persist(); mid["file"] = open(core.CURSORS).read()
    on_event[0] = save_mid
    hub4 = boot("restart-3")
    n_ev = len(events); passes(1, phase="restart-3-pass1")
    on_event[0] = None
    check("a change is read and reported", [e for e in events[n_ev:] if e[0] == aid(OPEN_PR) and e[1] == "comment"], events[n_ev:])
    open(core.CURSORS, "w").write(mid["file"])           # the process dies right after that save
    n_ev = len(events); hub5 = boot("crash"); passes(1, phase="crash-pass1")
    check("…after a crash at that moment the change is read in full again (a 200) and reported again, not lost to a 304",
          [c for c in F.counted("crash-pass1") if c[0] == "/repos/o/r/issues/1"] and [e for e in events[n_ev:] if e[0] == aid(OPEN_PR) and e[1] == "comment"], (F.calls("crash-pass1", is_issue(OPEN_PR)), events[n_ev:]))
    hub5.persist()

    # ---- 7. a comments read that fails after the issue's 200: the issue is not saved as seen
    since = saved()["state"][aid(OPEN_PR)]["updated"]; old_tag = saved()["etags"][aid(OPEN_PR)]["/repos/o/r/issues/1"]
    F.add_comment(OPEN_PR, "third thing"); F.fail.add(f"/repos/o/r/issues/1/comments?since={since}&per_page=20"); n_ev = len(events)
    hub6 = boot("fail"); passes(1, phase="fail-pass1"); hub6.persist()
    check("a comments read that failed after the issue's 200: nothing is reported, and the saved file keeps the issue's older ETag", not [e for e in events[n_ev:] if e[1] == "comment"] and saved()["etags"][aid(OPEN_PR)]["/repos/o/r/issues/1"] == old_tag, (events[n_ev:], saved()["etags"][aid(OPEN_PR)]))
    F.fail.clear(); hub7 = boot("fail-restart"); passes(1, phase="fail-restart-pass1")
    check("…after a restart it is read in full and the comment is reported", [e for e in events[n_ev:] if e[0] == aid(OPEN_PR) and e[1] == "comment"], events[n_ev:])
    hub7.persist()

    # ---- 8. a file that cannot be trusted
    doc = json.load(open(core.CURSORS)); good = json.dumps(doc)
    doc["github"]["me"] = "someone-else"; open(core.CURSORS, "w").write(json.dumps(doc))
    hub8 = boot("other-login"); passes(1, phase="other-login-pass1")
    check("ETags saved by another login are not used: the open anchors are read in full, in the rescan and in the pass",
          len([c for c in F.counted("other-login") if c[0].startswith("/repos/o/r/issues/")]) >= 2 and len([c for c in F.counted("other-login-pass1") if c[0].startswith("/repos/o/r/issues/")]) >= 2, [c[0] for c in F.counted("other-login") + F.counted("other-login-pass1")])
    doc = json.loads(good); doc["github"]["etags"] = {aid(OPEN_PR): {"/repos/o/r/issues/1": 7}}; doc["github"]["resolved"] = {aid(OPEN_PR): "nope"}; doc["github"]["repo_ids"] = {"o/r": "seven"}
    open(core.CURSORS, "w").write(json.dumps(doc))
    try: hub9 = boot("damaged"); passes(1, phase="damaged-pass1"); ok_ = True
    except Exception as e: ok_ = False; print(repr(e))
    check("a damaged ETag section is not used and does not stop the receiver: everything is read in full", ok_ and len(F.counted("damaged")) > 1 + 2, [c[0] for c in F.counted("damaged")])
    doc = json.loads(good); del doc["github"]["etags"]; del doc["github"]["resolved"]; del doc["github"]["repo_ids"]; del doc["github"]["me"]
    for v in doc["github"]["state"].values(): v.pop("merged", None); v.pop("pr", None)           # a file from before: the state did not keep whether an anchor is a merged pull request
    closed_now = sorted(a for a, v in doc["github"]["state"].items() if v["state"] == "closed")
    open(core.CURSORS, "w").write(json.dumps(doc))

    # ---- 9. the first start with this code over a file from before it (state and CI state, no ETags, no resolutions, no `merged` in the state)
    hub10 = boot("upgrade"); passes(1, phase="upgrade-pass1")
    up = len(F.counted("upgrade")) + len(F.counted("upgrade-pass1"))
    check("upgrade: costs less than a cold start (the closed anchors are read as issues only, once): the open ones in full, the rescan in full", up < cold_start + cold1, (up, cold_start + cold1))
    check("…every closed anchor is read once as an issue, with no CI read (its pull request and check runs are not asked), to learn whether it is a merged pull request",
          len(closed_now) == 7 and all(len(F.calls("upgrade-pass1", lambda p, n=int(a.rsplit("#", 1)[1]): p == f"/repos/o/r/issues/{n}")) == 1 and not F.calls("upgrade-pass1", lambda p, n=int(a.rsplit("#", 1)[1]): p.startswith(f"/repos/o/r/pulls/{n}") or p.startswith(f"/repos/o/r/commits/{n:040x}")) for a in closed_now),
          [(a, [c[:2] for c in F.calls("upgrade-pass1", lambda p, a=a: p.startswith(f"/repos/o/r/issues/{a.rsplit('#', 1)[1]}"))]) for a in closed_now])
    check("…and the state now says which are merged pull requests", {a: (v["pr"], v["merged"]) for a, v in saved_state(hub10).items() if v["state"] == "closed"}.get(aid(MERGED)) == (True, True) and all("merged" in v and "pr" in v for v in saved_state(hub10).values()), saved_state(hub10))
    hub10.persist()
    hub11 = boot("after-upgrade"); passes(1, phase="after-upgrade-pass1")
    check("…and the restart after it costs /user only", [c[0] for c in F.counted("after-upgrade")] == ["/user"] and not F.counted("after-upgrade-pass1"), [c[0] for c in F.counted("after-upgrade") + F.counted("after-upgrade-pass1")])

    # ---- 10. a pull request closed, reopened and merged: nothing is lost to the 10-pass turn of finished anchors
    def kinds(a, since): return [e[1] for e in events[since:] if e[0] == aid(a)]
    n_ev = len(events); F.set_state(OPEN_PR, "closed"); passes(1, phase="cycle-1")
    check("a pull request closed (not merged) is reported, and is not a finished anchor: it is read in every pass", "pr_closed" in kinds(OPEN_PR, n_ev), events[n_ev:])
    passes(3, phase="cycle-2")
    check("…read as 304s, its issue every pass", len(F.calls("cycle-2", lambda p: p == "/repos/o/r/issues/1")) == 3, F.calls("cycle-2", lambda p: p == "/repos/o/r/issues/1"))
    n_ev = len(events); F.set_state(OPEN_PR, "open"); passes(1, phase="cycle-3")
    check("…its reopening is seen in the next pass", kinds(OPEN_PR, n_ev) == ["pr_reopened"], events[n_ev:])
    def merge(n):
        F.set_state(n, "closed"); F.issues[n]["pull_request"]["merged_at"] = F.issues[n]["updated_at"]
    n_ev = len(events); merge(OPEN_PR); passes(1, phase="cycle-4")
    check("…and its merge too", kinds(OPEN_PR, n_ev) == ["pr_merged"], events[n_ev:])
    n_ev = len(events); passes(12, phase="cycle-5")
    check("a merged pull request is a finished anchor now: read in 1 or 2 of 12 passes, nothing reported", 1 <= len(F.calls("cycle-5", lambda p: p == "/repos/o/r/issues/1")) <= 2 and not events[n_ev:], (F.calls("cycle-5", lambda p: p == "/repos/o/r/issues/1"), events[n_ev:]))
    n_ev = len(events); F.set_state(CLOSED_PR, "closed"); passes(1, phase="cycle-6")      # #3 was reopened earlier (section 5): closed again, not merged
    F.set_state(CLOSED_PR, "open"); merge(CLOSED_PR); passes(1, phase="cycle-7")              # reopened and merged between two looks
    check("a pull request closed, then reopened and merged between two looks, is reported as merged (the state stays 'closed', the merge is what changed)", kinds(CLOSED_PR, n_ev) == ["pr_closed", "pr_merged"], events[n_ev:])
    hub11.persist()

    # ---- 11. ETags are kept only with the state they were taken at
    doc = json.load(open(core.CURSORS)); g = doc["github"]
    del g["state"][aid(OPEN_ISSUE)]; del g["ci"][aid(CLOSED_ISSUES[0])]; g["state"].pop(aid(MERGED3), None)
    open(core.CURSORS, "w").write(json.dumps(doc))
    hub12 = boot("no-state"); etg = hub12.gh_state["etags"]; n_ev = len(events)
    check("an anchor with ETags saved but no seeded state, or no CI state, keeps none of them after the restore; the others keep theirs",
          not [p for p in etg if re.match(r"/repos/o/r/(issues|pulls)/(17|13|5)(?:/|\?|$)", p) or p.startswith(f"/repos/o/r/commits/{5:040x}/")] and "/repos/o/r/issues/1" in etg and "/repos/o/r/issues/14" in etg, sorted(etg))
    passes(1, phase="no-state-pass1")
    c20 = F.calls("no-state-pass1", lambda p: p == "/repos/o/r/issues/17"); c1 = F.calls("no-state-pass1", lambda p: p == "/repos/o/r/issues/1")
    check("…the first look at the one with no state is a full read (a 200) that seeds it, and the others go on as 304s", [c[1] for c in c20] == [200] and all(c[1] == 304 for c in c1), (c20, c1))
    check("…and it is seeded (state saved again, nothing reported)", aid(OPEN_ISSUE) in saved_state(hub12) and not events[n_ev:], events[n_ev:])

    # ---- 12. a green head saved before a restart: the key comes back from the file as a list, and a head read again (no ETag) is not reported as new
    n12 = OPEN_PR; F.set_state(n12, "open"); F.issues[n12]["pull_request"]["merged_at"] = None; F.ci[n12] = "success"; i12 = F.issues[n12]
    doc = json.load(open(core.CURSORS)); g = doc["github"]; g["state"][aid(n12)] = {"state": "open", "comments": i12["comments"], "updated": i12["updated_at"], "pr": True, "merged": False}
    g["ci"][aid(n12)] = {"pr": True, "sha": f"{n12:040x}", "key": [f"{n12:040x}", []], "head_ref": "x/y", "author": "kim", "own_branch": True}      # a green head, as the file keeps it: the key a list
    g["etags"] = {a_: {p_: t_ for p_, t_ in e_.items() if "check-runs" not in p_} for a_, e_ in g["etags"].items()}      # the check runs are asked in full again after the restart
    open(core.CURSORS, "w").write(json.dumps(doc)); n_ev = len(events)
    hub13 = boot("green-restart"); passes(2, phase="green-restart-pass")
    ck = [c for c in F.counted("green-restart") + F.counted("green-restart-pass") if c[0] == f"/repos/o/r/commits/{n12:040x}/check-runs?per_page=100"]
    check("restart over a saved green head (its key a list in the file): the check runs are read in full again and the same head is not reported as a new green",
          bool(ck) and not [e for e in events[n_ev:] if e[0] == aid(n12) and e[1] in ("ci_passed", "ci_failed")] and isinstance(hub13.gh_state["ci"][aid(n12)]["key"], tuple), (ck, events[n_ev:], hub13.gh_state["ci"].get(aid(n12))))

    # ---- 13. a pending marker saved before a restart (CI was still running when the pull request was first looked at): after the restart the first finished result is reported once
    doc = json.load(open(core.CURSORS)); g = doc["github"]
    g["ci"][aid(n12)] = {"pr": True, "sha": f"{n12:040x}", "key": None, "pending": True, "head_ref": "x/y", "author": "kim", "own_branch": True}
    g["etags"] = {a_: {p_: t_ for p_, t_ in e_.items() if "check-runs" not in p_} for a_, e_ in g["etags"].items()}
    open(core.CURSORS, "w").write(json.dumps(doc)); n_ev = len(events)
    hub14 = boot("pending-restart"); passes(3, phase="pending-restart-pass")
    got13 = [(e[0], e[1], e[3]) for e in events[n_ev:] if e[0] == aid(n12) and e[1] in ("ci_passed", "ci_failed")]
    check("restart over a saved pending marker: the first finished result is reported once (a green: passing on), the marker is gone, and the passes after add none",
          got13 == [(aid(n12), "ci_passed", "passing on " + f"{n12:040x}"[:7] + " (1 checks)")] and "pending" not in hub14.gh_state["ci"][aid(n12)] and isinstance(hub14.gh_state["ci"][aid(n12)]["key"], tuple), (got13, hub14.gh_state["ci"].get(aid(n12))))

    # ---- 14. a save while a receiver's start is being retried keeps the position that receiver loaded (a second restart before it comes up must not lose it)
    import socket, urllib.error
    DNS = urllib.error.URLError(socket.gaierror(-3, "Temporary failure in name resolution"))      # a network error: its start is retried
    def misconfigured(h): raise KeyError("SLACK_USER_TOKEN")                                  # a missing credential: waiting cannot fix it
    TINY = (0.02, 0.08)                                                                       # s: the backoff
    EV15 = threading.Event(); up15 = threading.Event()
    def comes_up(h):
        if not up15.is_set(): raise DNS                         # the network is down until the test says it is back
        h.savers["google"] = lambda: {"a@x.test": {"hist": "9"}}; h.hooks["/hook/g15"] = lambda hd, body: (200, "ok"); h.status["g15"] = {"since": "x"}
    h15 = core.Hub(); h15.status["receivers"] = {}
    LOADED = {"a@x.test": {"hist": "7", "sent": ["m1"], "retry": [["m2", "t2", 1]]}}
    h15.saved = {"google": LOADED, "nope": {"n": 1}, "gone": {"n": 2}, "saved": "then"}
    th15 = core.start_receiver(h15, "google", comes_up, lambda: bool(h15.status.get("g15")), routes=("/hook/g15",), backoff=(0.02, 0.05), stop=EV15)
    core.start_receiver(h15, "nope", misconfigured, lambda: True, backoff=TINY)         
    h15.persist(); doc15 = json.load(open(core.CURSORS))
    check("save: while a receiver's start is being retried, the position it loaded is written back as it was", th15 is not None and doc15.get("google") == LOADED, doc15)
    check("save: the section of a receiver whose start failed for good, and of one nobody starts, is not written", "nope" not in doc15 and "gone" not in doc15, doc15)
    up15.set(); th15.join(10); h15.persist(); doc15 = json.load(open(core.CURSORS))
    check("save: once the receiver is up its own saver gives the position, and the loaded section is not kept beside it", not th15.is_alive() and doc15.get("google") == {"a@x.test": {"hist": "9"}}, doc15)
    EV15.set()

    return ran, fails


MARK = "@@anchorhub part"
if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--part":
        name = sys.argv[2]; assert name in PARTS, name
        ran, fails = {"idle": part_idle, "restart": part_restart}[name]()
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
    print(f"ok: anchorhub scenario, {total} checks")
