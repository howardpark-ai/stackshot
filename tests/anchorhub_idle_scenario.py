"""Scenario test for the CPU the receivers service uses between requests (stackshot/anchors): fakes only, no network, no process of the hub is started.

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

    tests/run-suite anchorhub_idle      → exit 0 / 1"""
import sys, os, re, json, time, types, pathlib, threading, logging, subprocess, zlib
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="ahidle-")
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's store of sessions
toml, n1 = re.subn(r'(?m)^state = "[^"]*"', f'state = "{tmp}/state"', toml); toml, n2 = re.subn(r'(?m)^secrets = "[^"]*"', f'secrets = "{tmp}/secrets"', toml)
assert (n1, n2) == (1, 1), (n1, n2)
pathlib.Path(tmp, "stackshot.toml").write_text(toml, encoding="utf-8"); os.environ["STACKSHOT_CONFIG"] = f"{tmp}/stackshot.toml"
for v in ("ANCHOR_HUB_ALLOW_SELF", "ANCHOR_PUSH_FORCE", "ANCHOR_PUSH_SOURCE"): os.environ.pop(v, None)
sys.path.insert(0, STACK)

_wd = threading.Timer(150, lambda: (print("FAIL: the scenario did not end in 150 s", flush=True), os._exit(3))); _wd.daemon = True; _wd.start()
fails = checks = 0
def check(name, ok, got=None):
    global fails, checks
    checks += 1
    print(("ok:   " if ok else "FAIL: ") + name + ("" if ok else f"\n      got: {str(got)[:700]}"), flush=True)
    if not ok: fails += 1

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
    h.saved = {"github": {"me": "oliver", "state": saved_state, "ci": saved_ci}}
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

print(f"\n{checks} checks, {fails} failed", flush=True)
sys.exit(1 if fails else 0)
