"""Scenario tests for anchor-hub's GitHub receiver and the receivers service around it (stackshot/anchors), in three parts that each run in a process of their own (formerly the suites anchorhub_idle,
anchorhub_restart and anchorhub_catchup): fakes only, no network, no process of the hub is started.

Part `idle` - the CPU the receivers service uses between requests (fakes only, no network, no process of the hub is started).

What it pins, each as a scenario on the real code (1, 3 and 4 fail on the code before the change; 2 pins what must not change):
  1. The id switch ([github.moved]). adopt() runs for every bound anchor in a pass; it names every saved entry's current name once per table, not once per anchor:
     with 60 bound anchors and 300 saved entries a pass asks anchor_id a few hundred times (it asked tens of thousands of times), and the entry saved under
     the old name still moves to the id the bindings use, in the state and in the CI state.
  2. A merged pull request's look is as it was (the branch does not change it): its pull request and check runs are read at each of its looks, whatever its issue answers, so a
     check that finishes late or is re-run on it is seen. Its looks are the passes in which its repository's list of changed issues shows it changed (after the one pass of a repository's first start).
  3. The watch on the bindings' folders asks watchdog for the four kinds of change the handler counts (modified, created, deleted, moved), so a read of
     the store (open, read, close) reaches no handler; a write still sets the flag, as before.
  4. A paused or held queue is not flushed by a process (push.py answers exit 5 and does nothing), a queue that is not held is, and a lifted hold flushes at the next
     pass; the question is push.py's own (flush_held), the same test as its --flush makes.

Part `restart` - anchor-hub's GitHub reads across a restart (a restart used to send a burst of
reads that hit the hourly cap and cut the pass short, so the board showed anchor-hub's github row as "error") - a fake GitHub that counts
its calls and answers ETags like GitHub (a 200 with an ETag, a 304 for a matching If-None-Match), the real hub and receiver, no network.

Covers: the first start (nothing saved) reads each anchor in full; a warm pass costs no counted read but the repository's list, asked for once; the read position is saved with its ETags, the
resolutions of the board's labels and the learnt repository IDs, and the file write is atomic (temp + os.replace; a failed replace leaves the old
file). A restart with that file costs no counted read but GitHub's /user (and, in its first pass, the repository's list: its ETag is not kept): every conditional read of an unchanged anchor is a 304, the start-up
rescan names every anchor from the saved resolution (a finished anchor with no call at all), nothing is reported twice. A change during the
downtime (a comment, a close, a reopening, on open and on finished anchors) is a 200 and is reported, once, with the repository ID. A finished
(closed or merged) anchor is not read one by one: its repository's list of changed issues is read once per pass, and a late comment, a reopening or a merge after one is read in full in that pass. An ETag is saved only once the pass has finished with its anchor: a save in the middle of a read, or after a comments read that failed,
leaves the older ETag, so the change is read again after a restart, not answered 304. ETags of another login, and a saved section that is damaged,
are not used. The first start with the new code over a file from before it (state, no ETags) costs less than a cold one.

Part `catchup` - a catch-up of the GitHub receiver (stackshot/anchors/anchorhub/github.py): the first pass after a first start or after the `gh` login
changed. GitHub answers an ETag only for the token it was given, so such a pass reads every anchor in full, and every full read is counted in the host's one hourly ledger
(stackshot/core/ghbudget.py, [github] read_budget), which the server shares. A fake `gh` (the module's own injection point for subprocess.run) that answers ETags like
GitHub (a 304 for a validator of the same login only), the real Hub with its status file and saved positions, a small read_budget, no network, no thread of the receiver.

Covers: a catch-up pass starts no further anchor once the hour's ledger holds two thirds of the budget (CATCHUP_SHARE), so a third is left for the server and the anchors
already read; the anchors not yet read go first, then the others by when each was read, the one read longest ago first; the next passes carry on from where it stopped, as the
hour's reads expire, and the note goes when every anchor has been read; the card is healthy (the status file, receiver_state, the receivers endpoint) with the note
"catching up: n of m anchors read", never the cap error, and the server can still read; the cap spent by someone else's reads, a bad credential and a GitHub that answers 5xx at
the start are still errors; a look that failed is not a read (a failed read of the pull request or its check runs included); a restart in the middle of a catch-up goes on from the saved position; a file from before the position was kept
counts the anchors with ETags as read. After a login change an anchor that is merged or closed is read in full and paced like the others, never skipped and counted as read (so no later turn of it reads it unpaced past the allowance);
a 410 is an answer like a 404; an anchor whose look keeps failing (not a failure of everything) goes behind the others and is tried less often, and is said apart in the note; a failure of every look
is an outage, not any anchor's, and starts no back-off; a read budget of 1 does not break the pacing.

The parts set up different instances (an example config with only the state and secrets folders in the scratch folder, for part `idle`; a base config with the store, the board, the brain and a fleet of sessions in it, for part `restart`; a base config with only those two folders, for part `catchup`) and
each replaces module state of the code under test (the GitHub receiver's subprocess, threading and time, the watchdog classes) that the other would find changed: so each part runs in a process of its own (this file started again with
`--part <name>`), exactly as the three suites did, and the parent adds their check counts. (A check against a real watchdog observer in part `idle` runs only where watchdog is installed; the others do not depend on it.)

    tests/run-suite anchorhub_restart        -> exit 0 / 1"""
import json, os, re, sys, pathlib, logging, types, subprocess, hashlib, time, threading
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
PARTS = ("idle", "restart", "catchup")

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
        if cond and mode["304"] and "-H" in args and "/issues?" not in path: return types.SimpleNamespace(returncode=0, stdout="HTTP/2.0 304 Not Modified\n\n", stderr="")
        if "/issues?" in path: body = mode.get("list", [])      # the repository's list of changed issues: what a test puts in mode["list"]
        elif path.endswith("/check-runs?per_page=100"): body = {"check_runs": [{"name": "suites", "status": "completed", "conclusion": "success"}]}
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

    def new_hub(bound, saved_state, saved_ci, position=True):
        h = core.Hub(); h.write_status = lambda: None; h.emit = lambda ev: None; h.bindings = {a: {"s"} for a in bound}
        h.saved = {"github": {"me": "oliver", "state": saved_state, "ci": saved_ci, "looked": {k: 1.0 for k in saved_state}}}      # every saved anchor was read before (an anchor not in `looked` is a catch-up's, read in full whatever its state)
        if position: h.saved["github"]["lists"] = {"new/repo": {"since": "2026-10-28T00:00:00Z", "at": time.time(), "owed": [], "catch": False}}      # the repository's list position is saved too (without it the first pass is the fallback: every finished anchor is read once)
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

        # ---- 2. a merged pull request's look is as it was: its CI first, then the issue, and the CI is read whatever the issue answers (a finished anchor is read when its repository's list shows it changed)
        n = 7; a_id = f"github:new/repo#{n}"
        def listed(updated): return [{"number": n, "state": "closed", "comments": 0, "updated_at": updated, "pull_request": {"merged_at": "2026-10-27T00:00:00Z"}}]
        mode["list"] = listed("2026-10-28T00:00:00Z")
        h = new_hub([a_id], {a_id: dict(CLOSED)}, {a_id: dict(CI)}, position=False)
        mode["304"] = False; calls.clear(); one_pass()
        rest = [c for c in calls if "/issues?" not in c]
        check("merged look: no position is saved for the repository, so the one pass of the fallback reads it: its pull request and check runs, then the issue (after one read of the newest change GitHub shows)",
              len(calls) == 4 and "/issues?" in calls[0] and rest[:2] == [f"{RP}/pulls/{n}", f"{RP}/commits/{'a' * 40}/check-runs?per_page=100"] and rest[-1] == f"{RP}/issues/{n}", calls)
        calls.clear(); one_pass()
        check("…the pass after it asks for the list alone and reads nothing of it", len(calls) == 1 and "direction=asc" in calls[0] and "since=2026-10-27T23:59:00Z" in calls[0], calls)
        mode["list"] = listed("2026-10-29T00:00:00Z"); mode["304"] = True; calls.clear(); one_pass()
        check("…and when the list shows it changed and the issue answers 304 the pull request and its check runs are read all the same (a check that finishes late or is re-run on a merged pull request is not missed)",
              f"{RP}/issues/{n}" in calls and f"{RP}/pulls/{n}" in calls and any("check-runs" in c for c in calls), calls)
        mode["304"] = False; mode["updated"] = "2026-10-29T00:00:00Z"; mode["list"] = listed("2026-10-29T00:00:00Z"); calls.clear(); one_pass()
        check("…the anchor's saved state takes in a change of the issue", h.gh_state["state"][a_id]["updated"] == "2026-10-29T00:00:00Z", h.gh_state["state"][a_id])
        calls.clear(); one_pass()
        check("…and once it has, the list showing it again (the overlap before the position) costs it no read", [c for c in calls if "/issues?" not in c] == [], calls)
        mode.pop("updated"); mode.pop("list")
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
    FINISHED = (MERGED, MERGED2, MERGED3) + CLOSED_ISSUES                      # merged pull requests and closed issues: read when the repository's list shows them changed
    CLOSED = FINISHED + (CLOSED_PR,)                                          # …and a closed pull request that is not merged: the same (a reopening and a merge after it show in the list)
    aid = lambda n: f"github:o/r#{n}"
    (T / "store/anchors.json").write_text(json.dumps({"projects/alpha": [{"url": f"https://github.com/o/r/{'pull' if n in PRS else 'issues'}/{n}", "items": None, "added": 1, "by": "t"} for n in ALL]}))
    (T / "store/next-id").write_text("10")
    # ---- a fake GitHub: one repository o/r (ID 7), ETags like GitHub's (the hash of the answer), every call logged
    class Fake:
        def __init__(self):
            self.login = "oliver"; self.token = 0; self.tick = 0; self.issues = {}; self.comments = {}; self.ci = {}; self.fail = set(); self.fail_list = False
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
        def renew(self): self.token += 1      # an App's installation token is renewed: GitHub honors no ETag of the one before
        def listing(self, query):
            """GET /repos/o/r/issues?<query>: the issues and pull requests that match, as GitHub pages them."""
            q = dict(kv.split("=", 1) for kv in query.split("&")); rows = [dict(i) for i in self.issues.values() if q.get("state", "open") in ("all", i["state"]) and i["updated_at"] >= q.get("since", "")]
            rows.sort(key=lambda i: (i["updated_at"], i["number"]), reverse=q.get("direction", "desc") == "desc")
            per = int(q.get("per_page", 30)); page = int(q.get("page", 1)); return rows[(page - 1) * per:page * per]
        def body(self, path):
            if path == "/user": return 200, {"login": self.login}
            if m := re.fullmatch(r"/repos/o/r/issues\?(.*)", path): return (502, {"message": "Bad Gateway"}) if self.fail_list else (200, self.listing(m.group(1)))
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
            code, obj = self.body(path); text_ = json.dumps(obj, sort_keys=True); tag = '"' + str(self.token) + hashlib.sha1(text_.encode()).hexdigest()[:16] + '"'
            if code == 502: self.log.append((path, 502, cond, self.phase)); return types.SimpleNamespace(returncode=1, stdout="", stderr="gh: Bad Gateway (HTTP 502)")
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
    check("cold first pass: a pull request costs 3 reads (pull, check runs, issue), an issue 2 (the pull request it is not, the issue): 5×3 + 4×2 (no anchor has a saved state yet, so no list is asked for)", cold1 == 5 * 3 + 4 * 2, [c[0] for c in F.counted("cold-pass1")])
    check("…nothing is reported (a first sight seeds)", not events, events)
    st0 = status(); labels0 = {a: st0[a]["label"] for a in st0}
    check("…the board names every anchor", len(labels0) == 9 and all(f'thing {a.rsplit("#", 1)[1]}' in l for a, l in labels0.items()), labels0)
    passes(2, phase="warm"); warm = F.counted("warm")
    check("warm passes: two counted reads, both of the repository's list (the first warm pass makes its position, the fallback: the newest change GitHub shows; the second asks for the list for the first time); every other read is a 304",
          [c[0].split("?")[0] for c in warm] == ["/repos/o/r/issues"] * 2 and "direction=desc&per_page=1" in warm[0][0] and "direction=asc" in warm[1][0], [c[0] for c in warm])
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
    check("restart, first pass: one counted read, the repository's list (a list's ETag is not kept over a restart; the position is), nothing reported (what else was read is a 304)",
          [c[0].split("?")[0] for c in F.counted("restart-1-pass1")] == ["/repos/o/r/issues"] and not events, ([c[0] for c in F.counted("restart-1-pass1")], events))
    check("…none of the 6 finished anchors was read (the list shows nothing of them that the saved state does not hold)", not [n for n in FINISHED if F.calls("restart-1-pass1", is_issue(n))], [c[0] for c in F.calls("restart-1-pass1")])

    # ---- 4. a finished anchor is not read one by one: the repository's list is, once per pass
    F.phase = "cadence"; passes(20, phase="cadence")
    check("20 passes: no finished anchor is read at all (no issue, no pull request, no check runs)", not [c for n in FINISHED for c in F.calls("cadence", is_issue(n))], [c[0] for c in F.calls("cadence") if "/issues?" not in c[0]])
    lst = F.calls("cadence", lambda p: p.startswith("/repos/o/r/issues?"))
    check("…the repository's list is asked for in every pass, as a 304", len(lst) == 20 and all(c[1] == 304 for c in lst), [(c[0], c[1]) for c in lst][:3])
    check("…an open one is read every pass", len(F.calls("cadence", lambda p: p == "/repos/o/r/issues/17")) == 20, len(F.calls("cadence", lambda p: p == "/repos/o/r/issues/17")))
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
    check("…and so are the late comment on the merged pull request and the reopening of the closed one, which the repository's list showed (finished anchors, read only for that)", (aid(MERGED), "comment") in got and (aid(CLOSED_PR), "pr_reopened") in got, events)
    check("…the repository ID learnt before the restart is on the event (it is saved with the position)", all(e[4] == 7 for e in events), events)
    unchanged = [c for c in F.counted("restart-2-pass1") if not (is_issue(OPEN_PR)(c[0]) or is_issue(OPEN_ISSUE)(c[0]) or is_issue(MERGED)(c[0]) or is_issue(CLOSED_PR)(c[0]) or c[0].startswith("/repos/o/r/issues?"))]
    check("…and the unchanged anchors cost nothing in it (the repository's list is the one read that is not an anchor's)", not unchanged, [c[0] for c in unchanged])
    passes(10, phase="restart-2-late")
    got = [(e[0], e[1]) for e in events]
    check("…the late comment on the merged pull request is reported once", got.count((aid(MERGED), "comment")) == 1 , events)
    check("…the reopening of the closed pull request is reported once", got.count((aid(CLOSED_PR), "pr_reopened")) == 1, events)
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
    doc["github"].pop("lists", None)                                                               # a file from before the list position was kept
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
    check("…and the restart after it costs /user only to start", [c[0] for c in F.counted("after-upgrade")] == ["/user"], [c[0] for c in F.counted("after-upgrade")])
    fb = F.calls("after-upgrade-pass1"); n_ev = len(events)
    check("…its first pass is the fallback of a file with no list position: the newest change GitHub shows is read first, then each of the 7 finished anchors in full once (its issue, and for a pull request its CI)",
          any("direction=desc&per_page=1" in c[0] for c in fb) and all(any(is_issue(int(a.rsplit("#", 1)[1]))(c[0]) for c in fb) for a in closed_now), [c[0] for c in fb])
    passes(1, phase="after-upgrade-pass2"); passes(1, phase="after-upgrade-pass3")
    check("…and from then on it is the list alone: one counted read (its first), then none", [c[0].split("?")[0] for c in F.counted("after-upgrade-pass2")] == ["/repos/o/r/issues"] and not F.counted("after-upgrade-pass3") and len(events) == n_ev,
          [c[0] for c in F.counted("after-upgrade-pass2") + F.counted("after-upgrade-pass3")])
    hub11.persist()

    # ---- 10. a pull request closed, reopened and merged: nothing is lost to the list
    def kinds(a, since): return [e[1] for e in events[since:] if e[0] == aid(a)]
    n_ev = len(events); F.set_state(OPEN_PR, "closed"); passes(1, phase="cycle-1")
    check("a pull request closed (not merged) is reported", "pr_closed" in kinds(OPEN_PR, n_ev), events[n_ev:])
    passes(3, phase="cycle-2")
    check("…and is finished from then on: not read in 3 passes (the list shows nothing the saved state does not hold)", not F.calls("cycle-2", is_issue(OPEN_PR)), F.calls("cycle-2", is_issue(OPEN_PR)))
    n_ev = len(events); F.set_state(OPEN_PR, "open"); passes(1, phase="cycle-3")
    check("…its reopening is seen in the next pass", kinds(OPEN_PR, n_ev) == ["pr_reopened"], events[n_ev:])
    def merge(n):
        F.set_state(n, "closed"); F.issues[n]["pull_request"]["merged_at"] = F.issues[n]["updated_at"]
    n_ev = len(events); merge(OPEN_PR); passes(1, phase="cycle-4")
    check("…and its merge too", kinds(OPEN_PR, n_ev) == ["pr_merged"], events[n_ev:])
    n_ev = len(events); passes(12, phase="cycle-5")
    check("a merged pull request is a finished anchor now: not read in 12 passes, nothing reported", not F.calls("cycle-5", is_issue(OPEN_PR)) and not events[n_ev:], (F.calls("cycle-5", is_issue(OPEN_PR)), events[n_ev:]))
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
    check("…the first look at the one with no state is a full read (a 200) that seeds it, and no other anchor is read (all the others are finished, and the list shows nothing of them)",
          [c[1] for c in c20] == [200] and not [c for c in F.calls("no-state-pass1") if not (c[0].startswith("/repos/o/r/issues?") or is_issue(OPEN_ISSUE)(c[0]) or is_issue(MERGED3)(c[0]))], (c20, c1, [c[0] for c in F.calls("no-state-pass1")]))
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


# ================================================================ part catchup: a catch-up of the GitHub receiver (formerly anchorhub_catchup)
def part_catchup():
    import sys, os, re, json, time, types, pathlib, threading, logging, subprocess, hashlib
    import _scratch, _instance
    tmp = _scratch.mkdtemp(prefix="ah-catchup-")
    toml = _instance.apply(_instance.base_toml())
    toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's store of sessions
    toml, n1 = re.subn(r'(?m)^state = "[^"]*"', f'state = "{tmp}/state"', toml); toml, n2 = re.subn(r'(?m)^secrets = "[^"]*"', f'secrets = "{tmp}/secrets"', toml)
    assert (n1, n2) == (1, 1), (n1, n2)
    pathlib.Path(tmp, "stackshot.toml").write_text(toml, encoding="utf-8"); os.environ["STACKSHOT_CONFIG"] = f"{tmp}/stackshot.toml"
    os.environ.pop("ANCHOR_HUB_ALLOW_SELF", None)
    sys.path.insert(0, STACK); logging.disable(logging.WARNING)

    _wd = threading.Timer(240, lambda: (print("FAIL: the scenario did not end in 240 s", flush=True), os._exit(3))); _wd.daemon = True; _wd.start()
    fails = []; ran = []
    def check(name, ok, got=None):
        ran.append(name)
        print(("ok:   " if ok else "FAIL: ") + name + ("" if ok else f"\n      got: {str(got)[:700]}"), flush=True)
        if not ok: fails.append(name)

    from stackshot.anchors.anchorhub import core, github as ghr
    from stackshot.core import ghbudget as _gb, config as _cfg
    from stackshot.web.ui import render as ui_render
    from stackshot.web.routes import board_pages

    N = 12
    aids = [f"github:o/r#{n}" for n in range(1, N + 1)]
    def num(a): return int(a.rsplit("#", 1)[1])


    def set_budget(n): _cfg.CFG.setdefault("github", {})["read_budget"] = n
    def age_ledger():
        """An hour passes: every stamp of the ledger is older than an hour, so the ledger is empty."""
        p = _cfg.state("github", _gb.LEDGER_NAME)
        try: doc = json.loads(p.read_text(encoding="utf-8"))
        except OSError: return
        shift = lambda rows: [t - 3700 for t in rows]
        doc = {"w": shift(doc.get("w", [])), "r": shift(doc.get("r", [])), "by": {k: {c: shift(v) for c, v in (d or {}).items()} for k, d in (doc.get("by") or {}).items()}}
        p.write_text(json.dumps(doc), encoding="utf-8")
    def clear_ledger(): _cfg.state("github", _gb.LEDGER_NAME).unlink(missing_ok=True)


    # ---- a fake GitHub: N open issues of one repository (no pull request under any number), an ETag per token (like GitHub's: an ETag is answered 304 only for the token it was given; `renew()` is the hourly renewal of an
    # App's installation token, the login the same), the repository's list of issues (state, since, sort, direction, per_page, page, as GitHub answers it), every call logged
    MORE = 6      # anchors 13 to 18 exist on the fake too: a test binds them later
    class Fake:
        def __init__(self):
            self.login = "oliver"; self.user = "ok"; self.log = []; self.token = 0; self.tick = 0; self.reset()
        def reset(self, total=None):
            """Every number an open issue, no pull request, no failing path (`total` numbers; N + MORE when none is given)."""
            self.status = {}; self.fail = set(); self.prs = set(); self.fail_list = False; self.comments = {}
            self.issues = {n: {"number": n, "state": "open", "comments": 0, "title": f"thing {n}", "user": {"login": "kim"}, "html_url": f"https://github.com/o/r/issues/{n}",
                               "created_at": "2026-10-20T00:00:00Z", "updated_at": "2026-10-25T%02d:%02d:%02dZ" % (n * 10 // 3600, n * 10 // 60 % 60, n * 10 % 60), "closed_at": None} for n in range(1, (total or N + MORE) + 1)}      # each changed ten seconds after the one before
        def renew(self): self.token += 1      # GitHub honors no ETag of the token before it
        def stamp(self): self.tick += 1; return "2026-10-26T%02d:%02d:%02dZ" % (self.tick // 3600, self.tick // 60 % 60, self.tick % 60)
        def touch(self, n): self.issues[n]["updated_at"] = self.stamp(); return self.issues[n]
        def make_pr(self, n, merged=False):
            """Number n is a pull request: open, or merged (and so finished)."""
            self.prs.add(n); i = self.issues[n]; i["pull_request"] = {"merged_at": "2026-10-20T00:00:00Z" if merged else None}
            if merged: self.close(n)
        def close(self, n): self.issues[n]["state"] = "closed"; self.issues[n]["closed_at"] = "2026-10-20T00:00:00Z"
        def comment(self, n, body="a word"):
            """A comment on number n: its count and its update time move."""
            i = self.touch(n); self.comments.setdefault(n, []).append({"user": {"login": "kim"}, "body": body, "html_url": f"https://github.com/o/r/issues/{n}#c{len(self.comments.get(n, []))}", "created_at": i["updated_at"]})
            i["comments"] = len(self.comments[n])
        def reopen(self, n): i = self.touch(n); i["state"] = "open"; i["closed_at"] = None
        def listing(self, query):
            """GET /repos/o/r/issues?<query>: the issues and pull requests that match, as GitHub pages them."""
            q = dict(kv.split("=", 1) for kv in query.split("&")); rows = [dict(i) for i in self.issues.values() if q.get("state", "open") in ("all", i["state"]) and i["updated_at"] >= q.get("since", "")]
            rows.sort(key=lambda i: (i["updated_at"], i["number"]), reverse=q.get("direction", "desc") == "desc")
            per = int(q.get("per_page", 30)); page = int(q.get("page", 1)); return rows[(page - 1) * per:page * per]
        def gh(self, args, capture_output=True, text=True, timeout=30):
            cond = "-i" in args
            inm = next((args[k + 1][len("If-None-Match: "):] for k, x in enumerate(args) if x == "-H"), None)
            path = next(x for x in args[2:] if x not in ("-i", "-H") and not x.startswith("If-None-Match"))
            def fail(code, msg): self.log.append((path, code, inm)); return types.SimpleNamespace(returncode=1, stdout="", stderr=msg)
            if path == "/user":
                if self.user == "401": return fail(401, "HTTP 401: Bad credentials (https://api.github.com/user)")
                if self.user == "500": return fail(500, "gh: Server Error (HTTP 500)")
                self.log.append((path, 200, inm)); return types.SimpleNamespace(returncode=0, stdout=json.dumps({"login": self.login}), stderr="")
            if path in self.fail: return fail(500, "gh: Server Error (HTTP 500)")
            if path in self.status: return fail(*self.status[path])
            obj = None
            if m := re.fullmatch(r"/repos/o/r/issues\?(.*)", path):
                if self.fail_list: return fail(502, "gh: Bad Gateway (HTTP 502)")
                obj = self.listing(m.group(1))
            elif (m := re.fullmatch(r"/repos/o/r/issues/(\d+)", path)) and int(m.group(1)) in self.issues: obj = self.issues[int(m.group(1))]
            elif (m := re.fullmatch(r"/repos/o/r/issues/(\d+)/comments\?since=([^&]+)&per_page=\d+", path)) and int(m.group(1)) in self.issues:
                obj = [c for c in self.comments.get(int(m.group(1)), []) if c["created_at"] >= m.group(2)]
            elif (m := re.fullmatch(r"/repos/o/r/pulls/(\d+)", path)) and int(m.group(1)) in self.prs:
                k = int(m.group(1)); obj = {"head": {"sha": f"sha{k}", "ref": f"br{k}", "repo": {"full_name": "o/r"}}, "base": {"repo": {"full_name": "o/r", "id": 77}}, "user": {"login": "kim"}}
            elif (m := re.fullmatch(r"/repos/o/r/commits/sha(\d+)/check-runs\?per_page=100", path)) and int(m.group(1)) in self.prs:
                obj = {"check_runs": [{"name": "unit", "status": "completed", "conclusion": "success", "completed_at": "2026-10-20T00:00:00Z"}]}
            if obj is None: return fail(404, "gh: Not Found (HTTP 404)")      # a pull request read of any number that is none lands here: no pull request is under it
            text_ = json.dumps(obj, sort_keys=True); tag = '"' + self.login + str(self.token) + "-" + hashlib.sha1(text_.encode()).hexdigest()[:12] + '"'
            if cond and inm == tag:
                self.log.append((path, 304, inm)); return types.SimpleNamespace(returncode=0, stdout="HTTP/2.0 304 Not Modified\n\n", stderr="")
            self.log.append((path, 200, inm)); return types.SimpleNamespace(returncode=0, stdout=(f"HTTP/2.0 200 OK\netag: {tag}\n\n" + text_) if cond else text_, stderr="")
        def counted(self, since=0): return [c for c in self.log[since:] if c[1] != 304]


    F = Fake()
    class _Stop(Exception): pass
    def _no_sleep(s): raise _Stop()
    caught: list = []
    ghr.subprocess = types.SimpleNamespace(run=F.gh, TimeoutExpired=subprocess.TimeoutExpired)
    ghr.threading = types.SimpleNamespace(Thread=lambda target, daemon=True: types.SimpleNamespace(start=lambda: caught.append(target)))
    CLOCK = [0.0]      # seconds the receiver's own clock is ahead of the real one: a test lets minutes pass without waiting (the ledger of reads keeps the real time, and age_ledger() moves its hour)
    ghr.time = types.SimpleNamespace(time=lambda: time.time() + CLOCK[0], sleep=_no_sleep)
    events: list = []

    def boot(order=None):
        """A start of the receiver over whatever cursors.json holds (as the service makes it) → the hub, the anchors bound in `order`."""
        del caught[:]
        h = core.Hub(); h.emit = lambda ev: events.append(ev); h.bindings = {a: {"sess"} for a in (order or aids)}
        ghr.run(h); return h
    def one_pass():
        try: caught[0]()
        except _Stop: pass
    def card():
        """What the board's card reads: the status file the hub wrote, as the receivers endpoint serves it, and the card's own word and class."""
        v = json.load(open(core.STATUS))["receivers"]["github"]
        api = json.loads(board_pages._receivers_response().body)["github"]
        return v, api, ui_render.receiver_state(v)
    def run_pass():
        """One pass → (counted reads it made by GitHub's count, the paths it asked in order, the card)."""
        n = len(F.log); one_pass()
        return len(F.counted(n)), [c[0] for c in F.log[n:]], card()
    def drop_cursors(): pathlib.Path(core.CURSORS).unlink(missing_ok=True)


    # ---- 1. a first start: nothing saved, every anchor is read in full (an issue costs 2 counted reads: the pull request that is not there, then the issue); read_budget 18 → a catch-up line of 12
    set_budget(18); clear_ledger(); P = int(18 * ghr.CATCHUP_SHARE)
    check("the catch-up line is two thirds of the read budget, and a third is left", P == 12 and ghr.CATCHUP_SHARE == 2 / 3, (P, ghr.CATCHUP_SHARE))
    h = boot(); cost = len(F.counted())
    check("start: the check is one counted read (GET /user), and the receiver reports nothing yet", cost == 1 and "github" in h.status, F.log)
    reads, paths, (v, api, word) = run_pass()
    read_now = [a for a in aids if f"/repos/o/r/issues/{num(a)}" in paths]
    check("a catch-up pass reads only its allowance: it starts no anchor once the ledger holds 12 of the 18 (6 anchors, 12 reads; one anchor can pass the line by its own cost, never more)",
          reads == 12 and _gb.count("r") == 13 and len(read_now) == 6, (reads, _gb.count("r"), read_now))
    check("…and it reads the anchors never read in the order they are bound", read_now == aids[:6], read_now)
    check("…the card is healthy, with the note of how far it is: ok, 'catching up: 6 of 12 anchors read', no error", v["ok"] is True and v["error"] == "catching up: 6 of 12 anchors read" and word == ("healthy ✓", "ok"), (v, word))
    check("…the receivers endpoint serves the same: ok, the note, not stale", api["ok"] is True and api["error"] == "catching up: 6 of 12 anchors read" and not api["stale"], api)
    check("…the pass is a finished check (last_pass set), nothing is told to anyone", h.status["github"].get("last_pass") and not events, (h.status["github"], events))
    check("…the cap is not spent and the server can still read: the ledger has room, and a server read is allowed (a third of the budget is left)",
          _gb.wait("r") == 0 and _gb.take("r", caller="step_proof") == 0 and 18 - _gb.count("r") >= 18 // 3 - 2, (_gb.wait("r"), _gb.count("r")))
    for _ in range(2): _gb.take("r", caller="step_proof")

    # ---- 2. the next pass in the same hour: nothing more is started, the anchors already read go on (free), in the order of when each was read, whatever the order they are bound in
    h.bindings = {a: {"sess"} for a in reversed(aids)}
    reads, paths, (v, api, word) = run_pass()
    check("the next pass, the hour not over: no counted read, the six anchors not read are not started", reads == 0 and not [p for p in paths if re.search(r"/issues/(7|8|9|10|11|12)$", p)], (reads, paths))
    check("…the anchors already read are asked as 304s, the one read longest ago first (not in the order they are bound in)", paths == [f"/repos/o/r/issues/{n}" for n in range(1, 7)], paths)
    check("…the card still says healthy with the note, unchanged", v["ok"] is True and v["error"] == "catching up: 6 of 12 anchors read" and word == ("healthy ✓", "ok"), (v, word))

    # ---- 3. an hour on: the catch-up carries on from where it stopped (the anchors never read first, in the order bound), and finishes; the note goes
    age_ledger()
    reads, paths, (v, api, word) = run_pass()
    first_new = [p for p in paths if re.search(r"/issues/\d+$|/pulls/\d+$", p)][0]
    check("an hour later the pass reads the anchors never read first (before the ones already read), in the order bound: #12 first", first_new == "/repos/o/r/pulls/12" and paths[:2] == ["/repos/o/r/pulls/12", "/repos/o/r/issues/12"], paths[:4])
    check("…it reads the 6 it had left, 12 reads, and every anchor has been read", reads == 12 and all(a in h.gh_state["looked"] for a in aids), (reads, len(h.gh_state["looked"])))
    check("…the note is gone: healthy, no text at all", v["ok"] is True and not v.get("error") and not api["error"] and word == ("healthy ✓", "ok"), (v, word))
    reads, paths, (v, api, word) = run_pass()
    check("…and the pass after it reads nothing counted", reads == 0 and v["ok"] is True and not v.get("error"), (reads, v))
    h.persist(); doc = json.load(open(core.CURSORS))["github"]
    check("the position is saved with the ETags: when each of the 12 anchors was read", sorted(doc["looked"]) == sorted(aids) and all(isinstance(t, float) for t in doc["looked"].values()) and sorted(doc["etags"]) == sorted(aids), (list(doc["looked"]), list(doc["etags"])))

    # ---- 4. the login changes: GitHub honors no ETag across tokens, so every anchor is read in full again; read_budget 9 → a line of 6 (an issue is 1 counted read now: its pull request is known to be none)
    set_budget(9); P = 6; clear_ledger(); F.login = "marlow"
    h = boot(); n0 = len(F.log)
    check("a login change: the ETags and the record of what was read are not used (the position of the other login is dropped)", not h.gh_state["etags"] and not h.gh_state["looked"], (list(h.gh_state["etags"]), list(h.gh_state["looked"])))
    reads, paths, (v, api, word) = run_pass()
    full = [c for c in F.log[n0:] if c[0].startswith("/repos/o/r/issues/")]
    check("…the pass reads each anchor in full, with no validator, and stops at its allowance: 5 anchors, the start check's read and theirs making 6", reads == 5 and len(full) == 5 and all(c[1] == 200 and c[2] is None for c in full) and _gb.count("r") == 6, (reads, full, _gb.count("r")))
    check("…the card reads healthy, 'catching up: 5 of 12 anchors read'; no error, never the cap's", v["ok"] is True and v["error"] == "catching up: 5 of 12 anchors read" and "cap" not in v["error"] and word == ("healthy ✓", "ok"), (v, word))
    reads, paths, (v, api, word) = run_pass()
    check("…the pass after it, in the same hour, reads nothing counted (the five read are 304s now) and keeps the note", reads == 0 and v["error"] == "catching up: 5 of 12 anchors read" and len([p for p in paths if p.endswith("/1")]) == 1, (reads, paths, v))
    age_ledger(); reads, paths, (v, api, word) = run_pass()
    check("…an hour later it reads 6 more and says so", reads == 6 and v["ok"] is True and v["error"] == "catching up: 11 of 12 anchors read", (reads, v))
    reads, paths, (v, api, word) = run_pass()
    check("…the same hour: nothing more", reads == 0 and v["error"] == "catching up: 11 of 12 anchors read", (reads, v))
    age_ledger(); reads, paths, (v, api, word) = run_pass()
    check("…the next hour: the last one, and the note goes", reads == 1 and v["ok"] is True and not v.get("error") and word == ("healthy ✓", "ok"), (reads, v))
    check("…the first read of each anchor is not reported as news (nothing changed under the new login)", not events, events)
    h.persist()

    # ---- 5. the cap spent by someone else's reads is a real failure, a catch-up or not
    set_budget(18); clear_ledger(); drop_cursors(); F.login = "oliver"
    h = boot()
    for _ in range(18): _gb.note("r", caller="step_proof")          # the server's own reads take the whole budget
    reads, paths, (v, api, word) = run_pass()
    check("the cap spent by the server's reads, in the middle of nothing read: the pass reads nothing and the card reads error ('reads held by the hourly cap, resume in …')",
          reads == 0 and not paths and v["ok"] is False and v["error"].startswith("reads held by the hourly cap, resume in ") and word == ("error ✗", "bad") and "last_pass" not in h.status["github"], (reads, v, word))
    check("…the receivers endpoint serves the error too", api["ok"] is False and api["error"].startswith("reads held by the hourly cap"), api)
    clear_ledger(); reads, paths, (v, api, word) = run_pass()
    check("…the hour's reads free again, the next pass runs and the card is healthy again", reads == 12 and v["ok"] is True and v["error"] == "catching up: 6 of 12 anchors read", (reads, v))

    # ---- 6. the server's reads that take the room of the catch-up (over its line, under the cap) slow it down; they are not an error
    clear_ledger(); drop_cursors()
    h = boot()
    for _ in range(14): _gb.note("r", caller="step_proof")          # 15 with the start check: over the line of 12, under the cap of 18
    reads, paths, (v, api, word) = run_pass()
    check("the server has used the catch-up's room (the ledger is over the line, under the cap): no anchor is started, and the card is healthy with the note, not an error", reads == 0 and v["ok"] is True and v["error"] == "catching up: 0 of 12 anchors read" and word == ("healthy ✓", "ok"), (reads, v, word))

    # ---- 7. a restart in the middle of a catch-up goes on from the saved position: the anchors read are 304s, the rest wait for room
    clear_ledger(); drop_cursors()
    h = boot(); reads, paths, (v, api, word) = run_pass(); h.persist()
    check("a catch-up cut at its allowance, saved", reads == 12 and v["error"] == "catching up: 6 of 12 anchors read", (reads, v))
    h = boot(); n0 = len(F.log); reads, paths, (v, api, word) = run_pass()
    check("restart in the middle of it (same login): the six read are asked as 304s, the others are still waiting for the hour's room, and the note says how far it was", reads == 0 and len([c for c in F.log[n0:] if c[1] == 304]) == 6 and v["error"] == "catching up: 6 of 12 anchors read", (reads, F.log[n0:], v))
    age_ledger(); reads, paths, (v, api, word) = run_pass(); h.persist()
    check("…and an hour on it finishes the rest", reads == 12 and v["ok"] is True and not v.get("error"), (reads, v))
    doc = json.load(open(core.CURSORS)); del doc["github"]["looked"]; open(core.CURSORS, "w").write(json.dumps(doc))
    h = boot(); reads, paths, (v, api, word) = run_pass()
    check("a file from before the position was kept (ETags saved, no record of what was read): the anchors with ETags count as read, no catch-up, no counted read", reads == 0 and v["ok"] is True and not v.get("error"), (reads, v))
    for a in aids[:2]: doc["github"]["etags"].pop(a)
    open(core.CURSORS, "w").write(json.dumps(doc)); h = boot()
    check("…an anchor with no ETags saved in such a file is not read yet", sorted(a for a in aids if a not in h.gh_state["looked"]) == sorted(aids[:2]), list(h.gh_state["looked"]))
    doc["github"]["looked"] = {aids[0]: "nope", aids[1]: True, aids[2]: 123.0, aids[3]: -1, "github:gone/x#9": 5}; open(core.CURSORS, "w").write(json.dumps(doc)); h = boot(); h.persist()
    check("…and a record that is not a time (text, a boolean, a negative number) is not believed; a time is, and an anchor no longer bound is not kept", aids[0] not in h.gh_state["looked"] and aids[1] not in h.gh_state["looked"] and h.gh_state["looked"][aids[2]] == 123.0
          and "github:gone/x#9" not in json.load(open(core.CURSORS))["github"]["looked"], (dict(h.gh_state["looked"])))

    # ---- 8. a look that failed is not a read: the anchor stays unread, is tried again first, and the card says so
    set_budget(1000); clear_ledger(); drop_cursors()
    F.fail = {f"/repos/o/r/issues/{n}" for n in (2, 3)}
    h = boot(); reads, paths, (v, api, word) = run_pass()
    check("two anchors whose read fails (GitHub's 500) are not counted as read: the note says 10 of 12, the pass is a finished check as before", v["ok"] is True and v["error"] == "catching up: 10 of 12 anchors read", (v, paths))
    F.fail = set(); n0 = len(F.log); reads, paths, (v, api, word) = run_pass()
    check("…the next pass tries them first, they are read, and the note goes", [p for p in paths if "/issues/" in p][:2] == ["/repos/o/r/issues/2", "/repos/o/r/issues/3"] and v["ok"] is True and not v.get("error"), (paths, v))

    # ---- 9. a real failure at the start: a bad credential, and a GitHub that answers 5xx. The receiver is not ready, retried, and its card reads error (the pass loop is never reached)
    set_budget(1000); clear_ledger(); drop_cursors()
    def start_with(user):
        F.user = user; del caught[:]; h = core.Hub(); h.status["receivers"] = {}; h.bindings = {a: {"sess"} for a in aids}; stop = threading.Event()
        th = core.start_receiver(h, "github", ghr.run, lambda: bool(h.status.get("github")), backoff=(0.02, 0.05), stop=stop)
        time.sleep(0.15); st = dict(h.status["receivers"]["github"]); stop.set()
        if th: th.join(10)
        return st, th
    st, th = start_with("401")
    check("a bad credential: the receiver is not ready, retried, and its card reads error 'gh not authenticated'", st["ok"] is False and "not authenticated" in st["error"] and st.get("retrying") is True and ui_render.receiver_state(st) == ("error ✗", "bad"), st)
    st, th = start_with("500")
    check("GitHub answering 5xx at the start: not ready, retried, the card reads error with GitHub's own words", st["ok"] is False and "HTTP 500" in st["error"] and st.get("retrying") is True, st)
    F.user = "ok"

    # ---- 10. after a login change, the anchors that are FINISHED (merged pull requests, closed issues) are read in full and paced like any other: none is skipped and counted as read (its later turn would read it unpaced, past the allowance)
    F.reset(); MERGED = {n for n in range(1, N + 1) if n % 2 == 0}
    for n in range(1, N + 1): F.make_pr(n, merged=True) if n in MERGED else F.close(n)      # even numbers merged pull requests (3 counted reads in full), odd ones closed issues (1)
    set_budget(1000); clear_ledger(); drop_cursors(); F.login = "oliver"
    h = boot(); reads, paths, (v, api, word) = run_pass(); h.persist()
    check("setup: under the first login every finished anchor is read once and seeded, nothing is news", all(a in h.gh_state["looked"] for a in aids) and all(h.gh_state["state"][a]["state"] == "closed" for a in aids) and not events, (list(h.gh_state["looked"]), events))
    set_budget(9); P = 6; clear_ledger(); F.login = "marlow"
    h = boot(); n0 = len(F.log)
    def really_read(since):
        """The anchors whose issue was read in full (a 200 sent with no validator) in the calls made since `since`."""
        return {a for a in aids if any(c[0] == f"/repos/o/r/issues/{num(a)}" and c[1] == 200 and c[2] is None for c in F.log[since:])}
    worst = 0; red = []; same = []; hours = 0
    while hours < 10 and len(h.gh_state["looked"]) < N:
        hours += 1
        for _ in range(12):      # a pass a minute for a while
            reads, paths, (v, api, word) = run_pass()
            worst = max(worst, _gb.count("r")); same.append(set(h.gh_state["looked"]) == really_read(n0))
            if not (v["ok"] is True and word == ("healthy ✓", "ok") and "cap" not in (v.get("error") or "")): red.append((hours, v))
        age_ledger()
    check("a login change over finished anchors: the ledger never goes past the catch-up line (6) by more than one anchor's cost (a merged pull request: 3 reads): at most 8 of the 9", worst <= P - 1 + 3, worst)
    check("…`looked` holds exactly the anchors really read in full, after every pass (none counted for a skipped turn)", all(same) and len(same) >= 12, same)
    check("…the card never reads error or 'reads held by the hourly cap' on the way: healthy with a note each pass", not red, red)
    check("…the catch-up finishes as the ledger expires (within a few hours), every anchor read, and the note is gone", len(h.gh_state["looked"]) == N and hours <= 6 and not (card()[0].get("error")), (hours, len(h.gh_state["looked"]), card()[0]))
    reads, paths, (v, api, word) = run_pass()
    check("…afterwards the finished anchors cost nothing (no read of any of them; the repository's list is the only call that can be a counted one), whatever the pass", reads <= 1 and [p for p in paths if "/issues?" not in p] == [] and v["ok"] is True, (reads, paths, v))
    check("…and none of it is reported as news", not events, events)

    # ---- 11. a 410 (a deleted issue) is an answer like a 404; another failure that stays is not
    F.reset(); set_budget(1000); clear_ledger(); drop_cursors(); F.login = "oliver"
    F.status = {"/repos/o/r/issues/3": (410, "gh: Gone (HTTP 410)"), "/repos/o/r/issues/4": (404, "gh: Not Found (HTTP 404)"), "/repos/o/r/issues/5": (422, "gh: Validation Failed (HTTP 422)")}
    h = boot(); reads, paths, (v, api, word) = run_pass()
    check("a 410 and a 404 are answers: those anchors count as read; a 422 is not a look", aids[2] in h.gh_state["looked"] and aids[3] in h.gh_state["looked"] and aids[4] not in h.gh_state["looked"], list(h.gh_state["looked"]))
    check("…the note says 11 of 12 (the 422's is the only one still to read) and the card is healthy", v["ok"] is True and v["error"] == "catching up: 11 of 12 anchors read", v)

    # ---- 12. anchors whose look keeps failing do not starve the others
    # a. a small budget (18: a line of 12) and the six failing ones first in the order bound: the first pass cannot know, and spends the line on them; an hour on, they have failed once and go behind the ones never tried
    F.reset(); set_budget(18); clear_ledger(); drop_cursors(); CLOCK[0] = 0.0
    BAD = aids[:6]; F.status = {f"/repos/o/r/issues/{num(a)}": (422, "gh: Validation Failed (HTTP 422)") for a in BAD}
    h = boot(); reads, paths, (v, api, word) = run_pass()
    check("six anchors that always fail, first in the order bound, at a small budget: the first pass spends the allowance on them (it cannot know yet)", reads == 12 and not [a for a in aids[6:] if a in h.gh_state["looked"]], (reads, list(h.gh_state["looked"])))
    age_ledger(); reads, paths, (v, api, word) = run_pass()
    issue_paths = [p for p in paths if re.search(r"/issues/\d+$", p)]
    check("…an hour on, the anchors never tried go first and are all read, and the six that failed wait behind them", issue_paths[:6] == [f"/repos/o/r/issues/{n}" for n in range(7, 13)] and all(a in h.gh_state["looked"] for a in aids[6:]), (issue_paths, list(h.gh_state["looked"])))
    check("…the card is healthy, the note counts what is still to read ('catching up: 6 of 12')", v["ok"] is True and v["error"] == "catching up: 6 of 12 anchors read", v)
    # b. a budget that holds a pass: everything not failing is read in the first hour; the failing ones are tried a few times, then less and less often, and the anchors bound later are read at once
    F.reset(); set_budget(300); clear_ledger(); drop_cursors(); CLOCK[0] = 0.0
    F.status = {f"/repos/o/r/issues/{num(a)}": (422, "gh: Validation Failed (HTTP 422)") for a in BAD}
    h = boot(); n12 = len(F.log); reads, paths, (v, api, word) = run_pass()
    check("six failing anchors first in the order bound: in the first hour all six others are read, the failing ones are not counted as read", all(a in h.gh_state["looked"] for a in aids[6:]) and not [a for a in BAD if a in h.gh_state["looked"]] and v["error"] == "catching up: 6 of 12 anchors read", (list(h.gh_state["looked"]), v))
    late = [f"github:o/r#{n}" for n in range(13, 19)]; noted = []; late_ok = None
    for minute in range(1, 181):      # a pass a minute for three hours, the receiver's clock moving with it
        CLOCK[0] += 60
        if minute % 60 == 0: age_ledger()
        if minute == 60: h.bindings.update({a: {"sess"} for a in late})
        reads, paths, (v, api, word) = run_pass()
        if minute == 60: late_ok = all(a in h.gh_state["looked"] for a in late)
        noted.append((v["ok"], v.get("error")))
    tries = [len([c for c in F.log[n12:] if c[0] == f"/repos/o/r/issues/{num(a)}"]) for a in BAD]
    check("…each is tried three times in a row, then less and less often: 4 to 9 tries in three hours, not one a minute", all(4 <= t <= 9 for t in tries), tries)
    check("…anchors bound an hour in are read in the pass they appear, ahead of the failing ones", late_ok is True, late_ok)
    check("…the card stays healthy through it and, once they are given up on for now, says so apart: no 'catching up' for good", all(ok for ok, _ in noted) and noted[-1][1] == "6 anchors could not be read, tried again less often", (noted[-1], [x for x in noted if not x[0]][:2]))
    F.status = {}; CLOCK[0] += 7200; age_ledger(); reads, paths, (v, api, word) = run_pass()
    check("…and they are read the moment the cause goes and their turn comes (no anchor is dropped), and the note goes", all(a in h.gh_state["looked"] for a in aids + late) and not v.get("error") and not h.gh_state["retry"], (list(h.gh_state["looked"]), v, dict(h.gh_state["retry"])))
    CLOCK[0] = 0.0

    # ---- 13. GitHub failing for everything is an outage, not any anchor's: nothing is counted as read, no anchor goes into back-off, and the first pass that GitHub answers reads them all
    F.reset(); set_budget(1000); clear_ledger(); drop_cursors(); CLOCK[0] = 0.0
    F.status = {f"/repos/o/r/issues/{n}": (500, "gh: Server Error (HTTP 500)") for n in range(1, N + 1)}
    h = boot()
    for _ in range(6): CLOCK[0] += 60; reads, paths, (v, api, word) = run_pass()
    check("every read failing for six passes: no anchor counted as read, none put in back-off (they are tried every pass), the card says how far it is and is not red for it", not h.gh_state["looked"] and not [a for a, (n, wait) in h.gh_state["retry"].items() if wait] and v["ok"] is True and v["error"] == "catching up: 0 of 12 anchors read", (dict(h.gh_state["retry"]), v))
    F.status = {}; CLOCK[0] += 60; reads, paths, (v, api, word) = run_pass()
    check("…the first pass GitHub answers reads every one of them, and the note goes", all(a in h.gh_state["looked"] for a in aids) and not v.get("error"), (len(h.gh_state["looked"]), v))
    CLOCK[0] = 0.0

    # ---- 14. a failed read of the pull request, or of its check runs, is not a look either
    F.reset(); set_budget(1000); clear_ledger(); drop_cursors()
    for n in range(1, N + 1): F.make_pr(n)
    F.status = {"/repos/o/r/pulls/5": (500, "gh: Server Error (HTTP 500)"), "/repos/o/r/commits/sha6/check-runs?per_page=100": (500, "gh: Server Error (HTTP 500)")}
    h = boot(); reads, paths, (v, api, word) = run_pass()
    check("a pull request read that fails (#5) and a check-runs read that fails (#6): neither anchor is counted as read, the other ten are", sorted(a for a in aids if a not in h.gh_state["looked"]) == sorted([aids[4], aids[5]]) and v["error"] == "catching up: 10 of 12 anchors read", (list(h.gh_state["looked"]), v))
    F.status = {}; reads, paths, (v, api, word) = run_pass()
    check("…the next pass reads them, and the note goes", all(a in h.gh_state["looked"] for a in aids) and not v.get("error"), (list(h.gh_state["looked"]), v))

    # ---- 15. a read budget of 1, 2 or 3 (two thirds of it is less than one, or one) does not break the pacing
    for b in (1, 2, 3):
        F.reset(); set_budget(b); clear_ledger(); drop_cursors()
        h = boot(); clear_ledger(); err = None
        try: one_pass()
        except _Stop: pass
        except Exception as e: err = repr(e)
        try: shown = card()[0]["ok"] in (True, False)      # the pass ended in a report to the card (the loop's guard would have logged a crash and written none)
        except Exception as e: shown = False; err = err or repr(e)
        check(f"read_budget {b}: a pass starts at most the anchors the budget holds and does not raise", err is None and shown, err)

    # ---- the finished anchors of a repository are read through its list of changed issues: 518 anchors, 27 open, the rest merged pull requests (even numbers) and closed issues (odd)
    TOTAL, OPENN = 518, 27
    def fleet(total=TOTAL, open_n=OPENN):
        F.reset(total)
        for n in range(open_n + 1, total + 1):
            if n % 2 == 0: F.make_pr(n, merged=True)
            else: F.close(n)
        return [f"github:o/r#{n}" for n in range(1, total + 1)]
    def read_nums(paths, above=OPENN):
        """The numbers above `above` that a call of `paths` read (an issue, a pull request, its check runs)."""
        rx = re.compile(r"/repos/o/r/(?:issues|pulls)/(\d+)|/repos/o/r/commits/sha(\d+)/")
        return sorted({int(g) for p in paths for m in [rx.match(p)] if m for g in m.groups() if g and int(g) > above})
    lists = lambda paths: [p for p in paths if "/issues?" in p]
    def started(order):
        """A first start over the fleet, then the passes that bring its read position to rest: the first look, the fallback (the position), the first list, a pass that costs nothing."""
        set_budget(100000); clear_ledger(); drop_cursors(); F.login = "oliver"; F.token = 0; del events[:]
        h = boot(order); costs = [run_pass()[0] for _ in range(4)]; return h, costs

    # ---- 16. a token renewed: the finished anchors cost nothing, whatever their number
    ids = fleet(); h, costs = started(ids)
    check("518 anchors, first start: the first look reads every anchor in full; the pass after it is the fallback (the repository's newest change is read, each finished anchor again with its ETags: 304s); then the list's first read; then nothing",
          costs[0] > TOTAL and costs[1:] == [1, 1, 0], costs)
    ent = h.gh_state["lists"]["o/r"]
    check("…the repository's position is made, and nothing is owed any more", ent["owed"] == set() and ent["catch"] is False and ent["since"].startswith("2026-"), ent)
    F.renew(); reads, paths, (v, api, word) = run_pass()
    check(f"the token is renewed (GitHub honors none of the ETags): the pass costs the list read and the {OPENN} open anchors, not the {TOTAL - OPENN} finished ones", reads == 1 + OPENN and not read_nums(paths) and len(lists(paths)) == 1, (reads, read_nums(paths), lists(paths)))
    check("…and the card is healthy with no note", v["ok"] is True and not v.get("error"), v)
    reads, paths, _ = run_pass()
    check("…the pass after it costs nothing (the list and the open anchors answer 304 for the new token)", reads == 0 and not read_nums(paths), (reads, read_nums(paths)))

    # ---- 17. a comment on a merged pull request: that anchor alone is read
    n_ev = len(events); F.comment(50)
    reads, paths, _ = run_pass()
    check("a comment on a merged pull request: only that anchor is read, in full (the list, its issue, its comments, its pull request and its check runs: 5 counted reads, the ETags of its pull request and CI being of the token before) and it is reported", read_nums(paths) == [50] and reads == 5 and h.gh_state["state"][ids[49]]["comments"] == 1 and len(events) > n_ev, (reads, read_nums(paths), len(events) - n_ev))
    n_ev = len(events); reads, paths, _ = run_pass()
    check("…and the pass after it reads no anchor and reports nothing (the list shows it again for the overlap, and its saved state already holds the comment)", read_nums(paths) == [] and reads <= 1 and len(events) == n_ev, (reads, read_nums(paths)))
    reads, paths, _ = run_pass()
    check("…then nothing at all", reads == 0 and not read_nums(paths), (reads, read_nums(paths)))

    # ---- 18. a reopening returns the anchor to full watching, and a merge after it is the finished anchor's again
    F.reopen(60); reads, paths, _ = run_pass()
    check("a merged pull request reopened: it is read in that pass and the state says open", read_nums(paths) == [60] and h.gh_state["state"][ids[59]]["state"] == "open", (read_nums(paths), h.gh_state["state"][ids[59]]))
    reads, paths, _ = run_pass(); reads2, paths2, _ = run_pass()
    check("…and in every pass after it (its issue, its pull request, its check runs: 304s), as an open anchor is", read_nums(paths) == [60] and read_nums(paths2) == [60] and reads <= 1 and reads2 == 0, (reads, reads2, read_nums(paths), read_nums(paths2)))
    F.close(60); F.touch(60); reads, paths, _ = run_pass()
    check("…closed again, it is read once more and is a finished anchor again", read_nums(paths) == [60] and h.gh_state["state"][ids[59]]["state"] == "closed" and h.gh_state["state"][ids[59]]["merged"] is True, (read_nums(paths), h.gh_state["state"][ids[59]]))
    run_pass(); reads, paths, _ = run_pass()
    check("…and cost nothing in the passes after it", reads == 0 and not read_nums(paths), (reads, read_nums(paths)))

    # ---- 19. a failed list read keeps the position, reads and marks nothing, and is asked for again
    before = dict(h.gh_state["lists"]["o/r"]); lk = dict(h.gh_state["looked"]); F.fail_list = True; F.comment(70)
    reads, paths, (v, api, word) = run_pass(); reads2, paths2, _ = run_pass()
    check("a list read that fails (a 502): it is asked for again in the next pass, and no finished anchor is read in either", len(lists(paths)) == 1 and len(lists(paths2)) == 1 and not read_nums(paths) and not read_nums(paths2), (lists(paths), lists(paths2), read_nums(paths), read_nums(paths2)))
    check("…the position stays where it was", h.gh_state["lists"]["o/r"]["since"] == before["since"] and h.gh_state["lists"]["o/r"]["at"] == before["at"], (h.gh_state["lists"]["o/r"], before))
    check("…no finished anchor is marked read in them", all(h.gh_state["looked"][a] == lk[a] for a in ids[OPENN:]), [a for a in ids[OPENN:] if h.gh_state["looked"][a] != lk[a]][:3])
    F.fail_list = False; reads, paths, _ = run_pass()
    check("…and when GitHub answers the list again the change is read (the one anchor)", read_nums(paths) == [70] and h.gh_state["state"][ids[69]]["comments"] == 1, (read_nums(paths), h.gh_state["state"][ids[69]]))
    run_pass(); run_pass()

    # ---- 20. a position that is absent, or older than a day, or a file from before positions were kept: one fallback pass over the finished anchors, then the list
    for how_ in ("absent", "old", "from before"):
        h.persist(); doc = json.load(open(core.CURSORS)); g = doc["github"]
        if how_ == "absent": g["lists"].pop("o/r")
        elif how_ == "old": g["lists"]["o/r"]["at"] -= 2 * 86400
        else: g.pop("lists")
        open(core.CURSORS, "w").write(json.dumps(doc))
        h = boot(ids); reads, paths, (v, api, word) = run_pass(); reads2, paths2, _ = run_pass(); reads3, paths3, _ = run_pass()
        check(f"a position {how_}: the first pass reads the repository's newest change, then each of the {TOTAL - OPENN} finished anchors once (304s with the saved ETags), so none is lost", len(lists(paths)) == 1 and "direction=desc&per_page=1" in lists(paths)[0] and read_nums(paths) == list(range(OPENN + 1, TOTAL + 1)), (how_, lists(paths), len(read_nums(paths))))
        check("…the pass after it is the list alone, and no finished anchor is read in it or after", len(lists(paths2)) == 1 and "direction=asc" in lists(paths2)[0] and not read_nums(paths2) and not read_nums(paths3), (lists(paths2), read_nums(paths2)[:3], read_nums(paths3)[:3]))
        check("…and the card is healthy with no note", v["ok"] is True and not v.get("error") and not card()[0].get("error"), v)

    # ---- 21. a restart over a saved position goes on from it
    h.persist(); saved_since = json.load(open(core.CURSORS))["github"]["lists"]["o/r"]["since"]
    h2 = boot(ids); reads, paths, _ = run_pass()
    check("a restart: the position comes back from the file, and the first pass asks for the list from it (60 s before) and for nothing of a finished anchor",
          h2.gh_state["lists"]["o/r"]["since"] == saved_since and len(lists(paths)) == 1 and f"since={ghr.zulu(ghr._ts(saved_since) - ghr.LIST_OVERLAP)}" in lists(paths)[0] and "direction=asc" in lists(paths)[0] and not read_nums(paths), (h2.gh_state["lists"], lists(paths)))
    F.comment(120); run_pass(); h2.persist(); F.comment(130)
    h3 = boot(ids); reads, paths, _ = run_pass()
    check("…a change while it was down is read in the first pass, and only that anchor", read_nums(paths) == [130] and h3.gh_state["state"][ids[129]]["comments"] == 1, (read_nums(paths),))

    # ---- 22. more than a page of changes: the list is paged, each changed anchor read once
    for n in range(OPENN + 1, OPENN + 151): F.touch(n)
    reads, paths, _ = run_pass()
    check("150 changes at once: the list is read in two pages (the first conditional, the second not), and each of the 150 anchors is read", len(lists(paths)) == 2 and "page=2" in lists(paths)[1] and "&page=" not in lists(paths)[0] and read_nums(paths) == list(range(OPENN + 1, OPENN + 151)), (lists(paths), len(read_nums(paths))))
    reads, paths, _ = run_pass()
    check("…and none of them again in the next pass", not read_nums(paths), len(read_nums(paths)))

    # ---- 23. an anchor the list showed changed, whose read then fails, is not lost: it stays owed, over the next pass and over a restart, though the position has gone past it
    F.comment(190); F.status = {"/repos/o/r/issues/190": (500, "gh: Server Error (HTTP 500)")}; F.issues[200]["updated_at"] = "2026-10-27T12:00:00Z"      # #200 changed hours after #190
    reads, paths, _ = run_pass(); ent = h3.gh_state["lists"]["o/r"]
    check("a changed finished anchor whose read fails (a 500) is not marked read, and is owed still while the position has gone past it (to the change of #200, read meanwhile)",
          ids[189] in ent["owed"] and ids[199] not in ent["owed"] and ent["since"] == "2026-10-27T12:00:00Z" and h3.gh_state["state"][ids[189]]["comments"] == 0 and h3.gh_state["state"][ids[199]]["updated"] == "2026-10-27T12:00:00Z", (ent, h3.gh_state["state"][ids[189]]))
    h3.persist(); F.status = {}; h4 = boot(ids); reads, paths, _ = run_pass()
    check("…a restart, with GitHub answering again: its first pass reads that anchor, and only it (the owed anchors are saved with the position)", read_nums(paths) == [190] and h4.gh_state["state"][ids[189]]["comments"] == 1 and h4.gh_state["lists"]["o/r"]["owed"] == set(), (read_nums(paths), h4.gh_state["lists"]["o/r"]))

    return ran, fails


MARK = "@@anchorhub part"
if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--part":
        name = sys.argv[2]; assert name in PARTS, name
        ran, fails = {"idle": part_idle, "restart": part_restart, "catchup": part_catchup}[name]()
        print(f"{MARK} {name} {len(ran)} {len(fails)}"); sys.stdout.flush()
        os._exit(0)      # as the suites always ended: nothing a thread of the part left behind holds the process (tests/_scratch.py removes the scratch folder first)
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
