"""Scenario test for the cross-process store locks (stackshot/core/xlock.py: `XLock`, and the nine locks that use it) — a scratch instance, real OS processes, no server running.

The locks around the stores whole-file writers share (the item, the For you list, the Landed list, the held hand-back lines, the page-debt ledger, the pending answers, the machine anchors, the wake pass, the
stall record) were thread locks. A second process that writes the same files (the minute passes, in their own process) could then overwrite what the server had just written. `XLock` keeps the RLock
surface the callers and the suites use and adds a flock on `<state>/<name>.lock`. This suite starts real processes (this file, run with `child <what>`), so what it checks is what two processes do:

  1  item          two processes read, change and save one item through `writes.save` under `ITEM_LOCK`, 50 rounds each: the file holds all 100 changes
  2  for-you       the same for `for-you.json` (`foryou.add`), and the For you list's lock is the one that serializes it
  3  hand-back     the same for `handback-held.json` (`telling._handback_hold`)
  4  surface       nesting by one thread does not deadlock and the lock is released at the last release; a second thread waits until the first lets go; `acquire(blocking=False)` and a timed acquire fail while a
                   thread of this process holds it and while another process does; `_is_owned()` is true for the holder alone; releasing a lock one does not hold raises; the lock is the thread lock's drop-in
  5  the nine       each of the nine locks is an XLock on its own file in the state dir (never the store), a hold of it by another process blocks it and frees it again, and holding one blocks none of the other eight
  6  crash         a holder killed by SIGKILL (by its pid) leaves the lock file and not the lock: the next acquire gets it at once
  7  switch        [locks] cross_process = false is the thread lock alone: another process's hold does not block it, a thread of this process still does, and no lock file is made
  8  no lock file  a lock file that cannot be had (a permission, no descriptor left, an unset state path): with `xlock.strict` off the hold falls back to the thread lock and every fallback is logged (one a minute for each lock);
                   with it on the hold raises LockUnavailable naming the file and the errno; a transient failure is tried again and then takes the real flock
  9  deadline      a timed acquire has one deadline for the thread lock and the flock together
  10 waiting       a timed wait is not a spin (it sleeps between tries); a waiter that waits long says so, naming the lock; a blocking wait still gets the lock when it is let go
  11 release       an unlock that fails still gives the thread lock back
  12 instance      one XLock per name (a second one on the same file would lock a thread out of its own lock); the lock file is opened read-only
  13 standby       the read-only standby never takes the flock
  14 wake pass     the wake pass and a request's save on one item, two processes, 50 rounds each: both changes survive (the pass takes the item lock from its read to its write)
  15 every save    every writes.save in stackshot/ runs under the item lock, lexically or by its caller; the sites that do not are the listed ones
  16 starvation    100 takes of a lock another process takes again the moment it lets go: median under 50 ms, 99th under 250 ms (a poll starves behind it)
  17 the edges     a flock refused with EBADF takes the fallback (strict: LockUnavailable); the retry's pause is taken before the front lock; the wait line comes after the first interval and not on every try (timed and
                   blocking); a timed wait does not spin; a wait with no limit blocks in the flock
  18 the sites     each site that reads and writes an item (the three branches of the check pass, confirm, a release after a close, an anchor release, the green release) with another process saving the item
                   all the while: the site's effect happens and every save of the other process survives
  19 order         a recorder over the passes that take more than one lock: wake before item, never item before wake, no two locks in both orders
  20 no send       the wake pass, a release after a close and an anchor release send nothing, push nothing, start no process and open no connection while the item lock is held

    tests/run-suite xlock        -> exit 0 / 1"""
import ast, contextlib, errno, fcntl, io, json, os, re, signal, subprocess, sys, pathlib, threading, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
sys.path.insert(0, STACK)
CHILD = len(sys.argv) > 1 and sys.argv[1] == "child"
if CHILD:
    tmp = os.environ["XLOCK_TEST_TMP"]; T = pathlib.Path(tmp)
else:
    tmp = _scratch.mkdtemp(prefix="xlocktest-"); T = pathlib.Path(tmp)
    toml = _instance.apply(_instance.base_toml())
    toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
    for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                     ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md")):
        toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
    toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1
    (T / "stackshot.toml").write_text(toml, encoding="utf-8")
    for d in ("store/a", "fleet/a", "state/one", "brain/projects", "transcripts/-home-x", "home"): (T / d).mkdir(parents=True)
    (T / "store/next-id").write_text("500"); (T / "store/anchors.json").write_text("{}")
    (T / "store/a/1.json").write_text(json.dumps({"id": "1", "subject": "[home] one item", "description": "- A thing\n- It lives here\n- Done when done", "status": "open",
                                                    "updated": time.time(), "state_updated": time.time(), "confirmed": time.time(), "metadata": {"project": "projects/none", "next": "do the thing"}}))
    os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet", HOME=f"{tmp}/home", XLOCK_TEST_TMP=tmp)
    os.environ.pop("STACKSHOT_URL", None)

fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""), flush=True)

from stackshot.core import config as _cfg, xlock                  # noqa: E402
GO, ROUNDS = T / "xl-go", 50


def wait_for(path, secs=60.0):
    end = time.time() + secs
    while not path.exists():
        if time.time() > end: raise TimeoutError(f"{path.name} never came")
        time.sleep(0.01)


def hold_child(name, tag):
    """Take the lock `name` (a fresh XLock on the file, so the child imports nothing else), say so, and keep it until the release file comes or the process is killed."""
    lk = xlock.XLock(name); lk.acquire()
    (T / f"xl-held-{tag}").write_text(str(os.getpid()))
    end = time.time() + 120
    while not (T / f"xl-release-{tag}").exists() and time.time() < end: time.sleep(0.01)
    lk.release()


if CHILD and sys.argv[2] == "hold":      # a holder imports nothing beyond the lock
    hold_child(sys.argv[3], sys.argv[4]); sys.exit(0)

from stackshot.web import server                                  # noqa: E402,F401  (the wiring installs the save's steps: a save here is the real one)
from stackshot.service import foryou, landed, stall, telling, wakes, writes   # noqa: E402
from stackshot.web import answers, page_debts                     # noqa: E402
from stackshot.anchors import machine_anchor                      # noqa: E402

LOCKS = {"item": writes.ITEM_LOCK, "for-you": foryou._LOCK, "landed": landed._LOCK, "handback-held": telling._HANDBACK_LOCK, "ledger": page_debts._OWED_LOCK,
         "answers": answers._ANSWER_LOCK, "machine-anchors": machine_anchor.LOCK, "wake": wakes._WAKE_LOCK, "stall": stall.STALL_LOCK}
# ---------------------------------------------------------------------------- the child processes
def slow(mod, name, secs=0.003):
    """The write the loop ends in takes a moment longer: the window between a process's read and its write is wide, so two unlocked processes overlap in it (as they would on a loaded box)."""
    real = getattr(mod, name)
    def slowed(*a, **k):
        time.sleep(secs); return real(*a, **k)
    setattr(mod, name, slowed)


SITE_URL = "https://github.com/o/r/pull/1"
def site_child(tag, arg):
    """The rounds of one site (`arg` = "<site>:<rounds>"): each round the item is put back as the site needs it (under the item lock, as any writer does, so the other process's keys stay), the site's own function runs, and the effect it owes is counted."""
    from stackshot.core import store as cstore
    from stackshot.service import checks, released, update
    name, rounds = arg.split(":"); rounds = int(rounds)
    slow(cstore, "_write_item")
    p = T / "store/a/1.json"; effects = 0
    def seed(**meta):
        with writes.ITEM_LOCK:
            it = json.loads(p.read_text()); m = it["metadata"]
            for k in ("hold", "wake", "after", "check", "needs", "ask", "wait_failed"): m.pop(k, None)
            m.update(meta); it["status"] = "open"; it["state_updated"] = time.time() - 1000
            writes.save("a1", it, writer="")
    def now(): return json.loads(p.read_text())
    ASK = "Decide: x · Recommend: y · Stakes: z · By: no date"
    for i in range(rounds):
        t0 = time.time()
        if name in ("check_close", "check_wait", "check_fail"):
            checks.check_eval = lambda c, n, g: (name != "check_fail", "")
            checks.check_dead = lambda c, g: "closed without being merged"
            (checks.checks_path()).unlink(missing_ok=True); checks.CHECK_LAST[0] = 0.0
            if name == "check_wait": seed(check="item_closed a2", needs=["decision"], ask=ASK)
            elif name == "check_fail": seed(check="pr_merged o/r#5")
            else: seed(check="item_closed a2")
            checks.check_tick(now=time.time())
            effects += {"check_close": now()["status"] == "completed", "check_wait": bool(checks.checks_load()["items"].get("a1", {}).get("met")),
                        "check_fail": "wait_failed" in now()["metadata"]}[name]
        elif name == "confirm":
            seed(); update.confirm_item("a1")
            effects += now()["confirmed"] >= t0
        elif name == "release_after":
            seed(after=["a2"], hold=True, wake="2000-01-01"); wakes.release_after("a2", "done", "", "")
            effects += "after" not in now()["metadata"]
        elif name == "anchor_release":
            seed(hold=True, wake="2099-01-01"); wakes.anchor_release("projects/none", {"kind": "anchor", "anchor": SITE_URL, "to": "x", "ts": time.time() + 60, "id": "n1", "ruling": "passed"})
            effects += "hold" not in now()["metadata"]
        elif name == "release_green":
            seed()
            released._release_green_ok = lambda sender, pr: True
            released._anc.registry = lambda: {"projects/none": {}}; released._anc.pilot_root = lambda k: True
            released._routing.record = lambda *a, **k: "n1"; released._routing.rule = lambda *a, **k: None
            released._pr_items = lambda prs: {SITE_URL: ["a1"]}
            out = released._release_green("projects/none", "[release] green", "release", "m", SITE_URL)
            effects += "commented on" in (out or "")
        else:
            raise SystemExit(f"no such site {name}")
    print(f"effects {effects} of {rounds}")


def child(kind, tag, arg):
    (T / f"xl-ready-{tag}").write_text("1")
    wait_for(GO)
    if kind == "item":
        from stackshot.core import store as cstore
        slow(cstore, "_write_item")
        p = T / "store/a/1.json"
        for i in range(int(arg)):
            with writes.ITEM_LOCK:
                it = json.loads(p.read_text()); it.setdefault("xl", {})[f"{tag}{i}"] = i
                writes.save("a1", it, writer="")
    elif kind == "foryou":
        slow(foryou, "_save")
        for i in range(int(arg)):
            foryou.add(key=f"xl-{tag}-{i}", kind=sorted(foryou._fy.KINDS)[0], what=f"row {tag} {i}")
    elif kind == "wake":
        from stackshot.core import store as cstore
        slow(cstore, "_write_item")
        p = T / "store/a/1.json"; woke = 0
        for i in range(int(arg)):
            with writes.ITEM_LOCK:          # a request parks the item (a hold and a wake that has come): the pass has one to release every round
                it = json.loads(p.read_text()); it.setdefault("xl", {})[f"{tag}{i}"] = i
                it["metadata"]["hold"] = True; it["metadata"]["wake"] = "2000-01-01"
                writes.save("a1", it, writer="")
            woke += len(wakes.wake_pass())
        (T / "xl-wake-done").write_text("1"); print(f"woke {woke}")
    elif kind == "until":                   # a request side that saves for as long as the wake side runs (the pass takes longer than a save: the two overlap the whole time)
        from stackshot.core import store as cstore
        slow(cstore, "_write_item")
        p = T / "store/a/1.json"; i = 0; gap = float(arg)        # arg: the pause between two saves (0: none)
        while i < 3 or not (T / "xl-wake-done").exists():
            with writes.ITEM_LOCK:
                it = json.loads(p.read_text()); it.setdefault("xl", {})[f"{tag}{i}"] = i
                writes.save("a1", it, writer="")
            i += 1
            time.sleep(gap)
        print(f"rounds {i}")
    elif kind == "hog":                     # a process that takes the lock again the moment it lets go of it, for as long as the stop file is absent
        lk = xlock.XLock("starve")
        while not (T / "xl-stop").exists():
            with lk: time.sleep(0.001)
    elif kind == "site":                    # one site that reads the item and writes it back, the real function, with the write slowed (the window between its read and its write is wide), 60 rounds
        site_child(tag, arg)
    elif kind == "handback":
        slow(telling, "handback_write")
        for i in range(int(arg)):
            telling._handback_hold({"gid": f"a{tag}{i}", "oid": "o", "olabel": "o", "project": "p", "who": "w", "subject": "s", "line": "l"}, 60.0, now=1000.0)
    else:
        raise SystemExit(f"no such child {kind}")


if CHILD:
    child(sys.argv[2], sys.argv[3], sys.argv[4])
    sys.exit(0)

KIDS = []
def spawn(*args):
    pr = subprocess.Popen([sys.executable, os.path.abspath(__file__), "child", *args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=STACK); KIDS.append(pr); return pr

def two_processes(kind, rounds=ROUNDS):
    GO.unlink(missing_ok=True)
    kids = [spawn(kind, tag, str(rounds)) for tag in ("p", "q")]
    for tag in ("p", "q"): wait_for(T / f"xl-ready-{tag}")
    GO.write_text("1")
    outs = []
    for k in kids:
        try: out, _ = k.communicate(timeout=60)
        except subprocess.TimeoutExpired: k.kill(); out, _ = k.communicate(); out += "\n(timed out)"
        outs.append((k.returncode, out))
    for tag in ("p", "q"): (T / f"xl-ready-{tag}").unlink(missing_ok=True)
    return outs

def holder(name, tag):
    (T / f"xl-held-{tag}").unlink(missing_ok=True); (T / f"xl-release-{tag}").unlink(missing_ok=True)
    pr = spawn("hold", name, tag); wait_for(T / f"xl-held-{tag}"); return pr

def let_go(pr, tag):
    (T / f"xl-release-{tag}").write_text("1"); pr.wait(timeout=30)

class Hung(Exception): pass
def guarded(f, secs=10):
    """f() with a clock on it: a lock that hangs fails the check instead of the suite."""
    def on_alarm(*_): raise Hung(f"no answer in {secs}s")
    old = signal.signal(signal.SIGALRM, on_alarm); signal.alarm(secs)
    try: return f()
    except Hung as e: return e
    finally: signal.alarm(0); signal.signal(signal.SIGALRM, old)

def raw_free(name):
    """Could another holder of the lock's file take it now? (a fresh descriptor on the file, as a second process has: the flock is the same for it)"""
    fd = os.open(xlock.XLock(name).path(), os.O_RDONLY | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB); return True
    except BlockingIOError: return False
    finally: os.close(fd)

def try_take(lk, **kw):
    ok = lk.acquire(**kw)
    if ok: lk.release()
    return ok


try:
    # ---- 1-3. two processes, one file each
    for n, (kind, what) in enumerate((("item", "item"), ("foryou", "for-you"), ("handback", "hand-back")), 1):
        outs = two_processes(kind)
        check(f"{n} {what}: both processes ran to the end", all(rc == 0 for rc, _ in outs), outs)
        if kind == "item":
            got = json.loads((T / "store/a/1.json").read_text()).get("xl") or {}
            check("1 item: the file holds every change both processes made (50 each, none lost)", len(got) == 2 * ROUNDS and all(got.get(f"{t}{i}") == i for t in "pq" for i in range(ROUNDS)), (len(got), outs))
        elif kind == "foryou":
            d = json.loads((T / "state/for-you.json").read_text())
            check("2 for-you: the list holds every row both processes made, and every key (50 each, none lost)", len(d["rows"]) == 2 * ROUNDS and len(d["keys"]) == 2 * ROUNDS, (len(d["rows"]), len(d["keys"]), outs))
        else:
            d = json.loads((T / "state/handback-held.json").read_text())
            check("3 hand-back: the file holds every line both processes held (50 each, none lost)", len(d) == 2 * ROUNDS, (len(d), outs))

    # ---- 4. the surface of the lock
    lk = xlock.XLock("unit")
    check("4 surface: not held before the first acquire", lk._is_owned() is False)
    def nested():
        with lk:
            with lk:
                with lk: return lk._is_owned()
    got = guarded(nested)
    check("4 surface: nesting by one thread does not deadlock and the thread holds the lock inside", got is True, got)
    check("4 surface: not held after the last release", lk._is_owned() is False)
    check("4 surface: the lock file is made in the state dir", (T / "state/unit.lock").exists())
    nest = guarded(lambda: (lk.acquire(), lk.acquire(), lk.release()))
    check("4 surface: a nested release keeps the lock: still held, and another holder of the file still waits", not isinstance(nest, Hung) and lk._is_owned() and guarded(lambda: raw_free("unit")) is False, nest)
    lk.release()
    check("4 surface: the last release frees the file for another holder", raw_free("unit") is True and lk._is_owned() is False)
    seen = {}
    def other():
        seen["owned"] = lk._is_owned(); seen["nb"] = lk.acquire(blocking=False); seen["timed"] = lk.acquire(timeout=0.2)
        t0 = time.time(); seen["blocked"] = lk.acquire(); seen["waited"] = time.time() - t0; lk.release()
    lk.acquire(); th = threading.Thread(target=other, daemon=True); th.start(); time.sleep(0.6)
    check("4 surface: a second thread does not hold it, and neither a non-blocking nor a timed acquire gets it", seen.get("owned") is False and seen.get("nb") is False and seen.get("timed") is False, seen)
    check("4 surface: a second thread waits for the holder (it has not come through while it is held)", "waited" not in seen and th.is_alive(), seen)
    lk.release(); th.join(10)
    check("4 surface: ...and comes through when the holder lets go", seen.get("blocked") is True and not th.is_alive(), seen)
    try: lk.release(); check("4 surface: releasing a lock one does not hold raises", False)
    except RuntimeError: check("4 surface: releasing a lock one does not hold raises", True)
    check("4 surface: acquire(timeout=...) on a free lock gets it", try_take(lk, timeout=1) is True)
    pr = holder("unit", "u1")
    check("4 surface: another process holds it: acquire(blocking=False) is False, a timed acquire is False, this process does not hold it",
          guarded(lambda: (lk.acquire(blocking=False), lk.acquire(timeout=0.2), lk._is_owned())) == (False, False, False))
    t0 = time.time(); th = threading.Thread(target=lambda: (lk.acquire(), seen.update(late=time.time() - t0), lk.release()), daemon=True); th.start(); time.sleep(0.4)
    check("4 surface: a blocking acquire waits for the other process", "late" not in seen)
    let_go(pr, "u1"); th.join(10)
    check("4 surface: ...and gets the lock when that process lets go", seen.get("late") is not None and try_take(lk, blocking=False) is True, seen)

    # ---- 5. the nine locks
    check("5 the nine: every lock is an XLock", all(isinstance(v, xlock.XLock) for v in LOCKS.values()), {k: type(v).__name__ for k, v in LOCKS.items()})
    check("5 the nine: each is on its own file in the state dir, not in the store", all(v.path() == T / "state" / f"{k}.lock" for k, v in LOCKS.items()) and len({v.path() for v in LOCKS.values()}) == 9,
          {k: str(v.path()) for k, v in LOCKS.items()})
    for name, lock in LOCKS.items():
        pr = holder(name, "n1")
        blocked = guarded(lambda: lock.acquire(blocking=False)) is False
        others = all(try_take(v, blocking=False) for k, v in LOCKS.items() if k != name)
        let_go(pr, "n1")
        check(f"5 the nine: {name}: another process's hold blocks it and none of the other eight", blocked and others, (blocked, others))
        check(f"5 the nine: {name}: free again when that process lets go", guarded(lambda: try_take(lock, blocking=False)) is True)

    # ---- 6. a holder that dies
    pr = holder("item", "k1"); pid = int(pathlib.Path(T / "xl-held-k1").read_text())
    check("6 crash: while the holder lives the item lock is out of reach", guarded(lambda: writes.ITEM_LOCK.acquire(blocking=False)) is False)
    os.kill(pid, signal.SIGKILL); pr.wait(timeout=30)
    check("6 crash: the holder was killed (SIGKILL) and left its lock file behind", pr.returncode == -signal.SIGKILL and (T / "state/item.lock").exists(), pr.returncode)
    check("6 crash: the lock is free at once and can be taken and released again", guarded(lambda: (try_take(writes.ITEM_LOCK, blocking=False), try_take(writes.ITEM_LOCK, timeout=1))) == (True, True))

    # ---- 7. the switch
    (T / "state/sw.lock").unlink(missing_ok=True)
    _cfg.CFG["locks"] = {"cross_process": False}
    try:
        sw = xlock.XLock("sw")
        pr = holder("item", "s1")
        check("7 switch: another process's hold does not block a lock with the switch off (the thread lock alone)", guarded(lambda: try_take(writes.ITEM_LOCK, blocking=False)) is True)
        let_go(pr, "s1")
        seen.clear()
        def other2(): seen["nb"] = sw.acquire(blocking=False)
        with sw:
            with sw: nested_ok = sw._is_owned()
            th = threading.Thread(target=other2, daemon=True); th.start(); th.join(10)
        check("7 switch: it is still re-entrant and still keeps another thread of this process out", nested_ok and seen.get("nb") is False, seen)
        check("7 switch: with the switch off no lock file is made", not (T / "state/sw.lock").exists())
    finally:
        _cfg.CFG.pop("locks", None)
    check("7 switch: the switch is read as a setting: absent it is on (the default), true is on", xlock.enabled() is True and (_cfg.CFG.update(locks={"cross_process": True}) or xlock.enabled()) is True)
    _cfg.CFG.pop("locks", None)

    # ---- 8. a lock file that cannot be had
    real_open, real_state = xlock._open, _cfg.state
    def failing(*errs):
        todo = list(errs); calls = []
        def f(path):
            calls.append(str(path))
            if todo: raise todo.pop(0)
            return real_open(path)
        return f, calls
    def lines(buf): return [l for l in buf.getvalue().splitlines() if l.startswith("xlock:")]
    EMFILE, EACCES = OSError(errno.EMFILE, "Too many open files"), PermissionError(errno.EACCES, "Permission denied")
    try:
        fb = xlock.XLock("fb")
        xlock.strict = False
        buf = io.StringIO(); xlock._open, calls = failing(EACCES, EACCES, EACCES)
        with contextlib.redirect_stderr(buf):
            got = guarded(lambda: (fb.acquire(), fb._is_owned(), fb.release(), fb._is_owned()))
        check("8 no lock file: strict off: a permission failure falls back to the thread lock (the hold is made, once tried, not tried again)", got == (True, True, None, False) and len(calls) == 1, (got, calls))
        check("8 no lock file: ...and says so on stderr, naming the lock, the file and the error", len(lines(buf)) == 1 and "fb" in lines(buf)[0] and str(fb.path()) in lines(buf)[0] and "Permission denied" in lines(buf)[0], buf.getvalue())
        with contextlib.redirect_stderr(buf): xlock._open, calls = failing(EACCES); guarded(lambda: (fb.acquire(), fb.release()))
        check("8 no lock file: ...a second fallback within the minute is not said again (one a minute for each lock)", len(lines(buf)) == 1, buf.getvalue())
        fb._said_at -= xlock.FALLBACK_LOG_EVERY + 1
        with contextlib.redirect_stderr(buf): xlock._open, calls = failing(EACCES); guarded(lambda: (fb.acquire(), fb.release()))
        check("8 no lock file: ...and a fallback a minute later is said again (every fallback is logged, never once for ever)", len(lines(buf)) == 2, buf.getvalue())
        xlock.strict = True
        xlock._open, calls = failing(EACCES)
        try: guarded(lambda: fb.acquire()); got = None
        except xlock.LockUnavailable as e: got = e
        check("8 no lock file: strict on: a permission failure raises LockUnavailable naming the lock file and the errno", got is not None and str(fb.path()) in str(got) and str(errno.EACCES) in str(got) and got.errno == errno.EACCES, got)
        check("8 no lock file: ...and the hold is not left made", fb._is_owned() is False and raw_free("fb") is True)
        xlock._open, calls = failing(EMFILE, EMFILE, EMFILE, EMFILE, EMFILE)
        try: guarded(lambda: fb.acquire()); got = None
        except xlock.LockUnavailable as e: got = e
        check("8 no lock file: strict on: no descriptor left is tried again for a moment and then raises (errno named)", got is not None and len(calls) == xlock._RETRIES and str(errno.EMFILE) in str(got), (got, calls))
        xlock.strict = False
        buf = io.StringIO(); xlock._open, calls = failing(EMFILE, EMFILE)
        with contextlib.redirect_stderr(buf):
            got = guarded(lambda: (fb.acquire(), raw_free("fb"), fb.release()))
        check("8 no lock file: a transient failure then success takes the real flock (another holder of the file is kept out), and says nothing", got == (True, False, None) and len(calls) == 3 and not lines(buf), (got, calls, buf.getvalue()))
        for strict_ in (False, True):
            xlock.strict = strict_; fb._said_at = 0.0
            def nostate(*a, **k): raise KeyError("state")
            _cfg.state = nostate
            buf = io.StringIO()
            try:
                with contextlib.redirect_stderr(buf): got = guarded(lambda: (fb.acquire(), fb.release()))
            except Exception as e: got = e
            finally: _cfg.state = real_state
            fb._said_at = 0.0
            check(f"8 no lock file: the state path unset (a KeyError): strict {'on raises LockUnavailable' if strict_ else 'off falls back'}", isinstance(got, xlock.LockUnavailable) if strict_ else (got == (True, None) and len(lines(buf)) == 1), (got, buf.getvalue()))
    finally:
        xlock._open, _cfg.state, xlock.strict = real_open, real_state, False

    # ---- 9. one deadline
    dl = xlock.XLock("dl"); seen = {}
    real_lock_fd = xlock.XLock._lock_fd
    def spy(self, fd, blocking, deadline): seen["deadline"] = deadline; return False
    th = threading.Thread(target=lambda: (dl.acquire(), time.sleep(0.4), dl.release()), daemon=True); th.start(); time.sleep(0.1)
    xlock.XLock._lock_fd = spy
    try:
        t0 = time.monotonic(); got = guarded(lambda: dl.acquire(timeout=0.6)); took = time.monotonic() - t0
    finally: xlock.XLock._lock_fd = real_lock_fd
    th.join(5)
    check("9 deadline: a timed acquire that waited for the thread lock gives the flock only what is left of its own deadline", got is False and seen.get("deadline") is not None and seen["deadline"] - (t0 + 0.6) < 0.05, (got, seen, took))
    pr = holder("dl", "d1")
    t0 = time.monotonic(); got = guarded(lambda: dl.acquire(timeout=0.6)); took = time.monotonic() - t0
    check("9 deadline: a timed acquire on a lock another process holds gives up at its deadline, not before and not much after", got is False and 0.55 <= took <= 0.9, (got, took))
    let_go(pr, "d1")

    # ---- 10. waiting
    pr = holder("dl", "w1")
    c0, t0 = time.process_time(), time.monotonic(); got = guarded(lambda: dl.acquire(timeout=0.5)); cpu, took = time.process_time() - c0, time.monotonic() - t0
    check("10 waiting: a timed wait sleeps between its tries (it is not a spin: well under the time it waited in cpu)", got is False and took >= 0.45 and cpu < 0.2, (got, took, cpu))
    old = xlock.WAIT_LOG_FIRST, xlock.WAIT_LOG_EVERY; xlock.WAIT_LOG_FIRST = xlock.WAIT_LOG_EVERY = 0.15
    buf = io.StringIO()
    try:
        with contextlib.redirect_stderr(buf): got = guarded(lambda: dl.acquire(timeout=0.7))
    finally: xlock.WAIT_LOG_FIRST, xlock.WAIT_LOG_EVERY = old
    check("10 waiting: a wait that lasts says so, naming the lock and the file, again and again, and still gives up at its deadline", got is False and len(lines(buf)) >= 2 and all("dl" in l and str(dl.path()) in l for l in lines(buf)), buf.getvalue())
    seen.clear(); th = threading.Thread(target=lambda: (dl.acquire(), seen.update(got=True), dl.release()), daemon=True); th.start(); time.sleep(0.3)
    let_go(pr, "w1"); th.join(10)
    check("10 waiting: a blocking wait on the other process's hold comes through when it lets go", seen.get("got") is True and not th.is_alive(), seen)

    # ---- 11. release
    rl = xlock.XLock("rl"); real_flock = fcntl.flock
    def bad_unlock(fd, op):
        if op == fcntl.LOCK_UN: raise OSError(errno.EIO, "unlock failed")
        return real_flock(fd, op)
    rl.acquire(); fcntl.flock = bad_unlock
    try:
        try: rl.release(); raised = False
        except OSError: raised = True
    finally: fcntl.flock = real_flock
    check("11 release: an unlock that fails raises, and the thread lock is given back all the same (nothing is held for ever)", raised and rl._is_owned() is False and guarded(lambda: try_take(rl, blocking=False)) is True and raw_free("rl") is True, raised)

    # ---- 12. one instance per name, a read-only descriptor
    check("12 instance: XLock(name) is the one instance of that name (the nine are the ones the modules hold)", xlock.XLock("item") is writes.ITEM_LOCK and xlock.XLock("unit") is lk and all(xlock.XLock(k) is v for k, v in LOCKS.items()), None)
    def twice():
        with xlock.XLock("twice"):
            with xlock.XLock("twice"): return True
    check("12 instance: a lock taken again through a second XLock(name) in the same thread does not block it", guarded(twice) is True)
    with xlock.XLock("ro"):
        flags = int(next(l for l in pathlib.Path(f"/proc/self/fdinfo/{xlock.XLock('ro')._fd}").read_text().splitlines() if l.startswith("flags:")).split()[1], 8)
    check("12 instance: the lock file is opened read-only (a flock needs no write access)", flags & os.O_ACCMODE == os.O_RDONLY, oct(flags))

    # ---- 13. the standby
    from stackshot.core import readonly as _ro
    pr = holder("item", "r1")
    _ro._reload_for_test(True)
    try:
        got = guarded(lambda: (try_take(writes.ITEM_LOCK, blocking=False), xlock.XLock("standby-unit").acquire(), xlock.XLock("standby-unit").release()))
        made = (T / "state/standby-unit.lock").exists()
    finally: _ro._reload_for_test(False)
    let_go(pr, "r1")
    check("13 standby: the read-only standby never takes the flock: another process's hold does not block it, and no lock file is made", got == (True, True, None) and not made, (got, made))

    # ---- 14. the wake pass and a request's save, two processes
    it = json.loads((T / "store/a/1.json").read_text()); it["xl"] = {}; it["metadata"].pop("hold", None); it["metadata"].pop("wake", None); (T / "store/a/1.json").write_text(json.dumps(it))
    GO.unlink(missing_ok=True); (T / "xl-wake-done").unlink(missing_ok=True)
    kids = [spawn("wake", "p", str(ROUNDS)), spawn("until", "q", "0")]
    for tag in ("p", "q"): wait_for(T / f"xl-ready-{tag}")
    GO.write_text("1"); outs = []
    for k in kids:
        try: out, _ = k.communicate(timeout=60)
        except subprocess.TimeoutExpired: k.kill(); out, _ = k.communicate(); out += "\n(timed out)"
        outs.append((k.returncode, out))
    got = json.loads((T / "store/a/1.json").read_text()); xl = got.get("xl") or {}
    check("14 wake pass: both processes ran to the end", all(rc == 0 for rc, _ in outs), outs)
    qn = int(m.group(1)) if (m := re.search(r"rounds (\d+)", outs[1][1])) else 0
    check("14 wake pass: every change the request side saved (as many as the pass took rounds to run) and every park the wake side made (50) is in the file: none lost to the pass", qn >= 3 and len(xl) == ROUNDS + qn and all(f"p{i}" in xl for i in range(ROUNDS)) and all(f"q{i}" in xl for i in range(qn)), (len(xl), qn, outs))
    check("14 wake pass: the pass released the item every round (50 woke) and nothing parked it again", "woke 50" in outs[0][1] and "hold" not in got["metadata"] and "wake" not in got["metadata"], (outs, got["metadata"]))

    # ---- 15. every save is under the item lock
    LOCKED_BY_CALLER = {     # (file, function): why its writes.save has no `with ITEM_LOCK` of its own
        ("service/answer.py", "_record_told"): "its caller (the answer's ack) holds the item lock",
        ("service/answer_handover.py", "_keep_note"): "its caller (answer._answer) holds the item lock and the answers lock",
        ("service/proofs.py", "proof_item"): "its callers (released, the sweep, the proof tick) take the item lock round the loop",
        ("service/watching.py", "_wl_mark_save"): "its callers take the item lock",
        ("service/update.py", "update_unlocked"): "its one caller, update_item, takes the item lock",
        ("service/agent_names.py", "_auto_name_save"): "its callers (an update, _name_on_handover) take the item lock",
        ("service/create.py", "create_item"): "a new item: a fresh id nothing else writes (the id is a flock on next-id), no record to lose",
        ("service/writes.py", "save"): "the write itself: the callers take the lock round their read",
    }
    UNLOCKED_FOLLOW_UP = {   # the writer of an item file that is not writes.save
        ("github/ghsync.py", "take"): "the GitHub id re-key keeps the newer of two files by `updated` (its own protocol); the sync worker is not a minute pass",
        ("github/ghsync.py", "_move"): "the same re-key: the `after` lists it rewrites",
    }
    found = []
    for path in sorted((pathlib.Path(STACK) / "stackshot").rglob("*.py")):
        src = path.read_text(encoding="utf-8")
        try: tree = ast.parse(src)
        except SyntaxError: continue
        rel = str(path.relative_to(pathlib.Path(STACK) / "stackshot"))
        def walk(node, withs, func):
            for ch in ast.iter_child_nodes(node):
                w, f = withs, func
                if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef)): f, w = ch.name, ()
                if isinstance(ch, ast.With): w = withs + tuple(ast.get_source_segment(src, i.context_expr) or "" for i in ch.items)
                if isinstance(ch, ast.Call):
                    name = ast.get_source_segment(src, ch.func) or ""
                    if (name.endswith("_writes.save") or name.endswith("writes.save") or name.endswith("_write_item")) and rel not in ("web/search.py",) and not any("ITEM_LOCK" in t for t in w):
                        found.append((rel, f))
                walk(ch, w, f)
        walk(tree, (), None)
    unlisted = sorted({x for x in found if x not in LOCKED_BY_CALLER and x not in UNLOCKED_FOLLOW_UP})
    check("15 every save: every writes.save in stackshot/ is under `with ITEM_LOCK` in its own function, or is one of the listed sites", not unlisted, unlisted)
    check("15 every save: the list has no site that is locked after all (a stale entry hides the next one)", all(x in set(found) for x in (*LOCKED_BY_CALLER, *UNLOCKED_FOLLOW_UP)), sorted(set((*LOCKED_BY_CALLER, *UNLOCKED_FOLLOW_UP)) - set(found)))
    # ---- 16. starvation: a waiter behind a process that takes the lock again the moment it lets go
    (T / "xl-stop").unlink(missing_ok=True); GO.unlink(missing_ok=True)
    hog = spawn("hog", "h", "0"); wait_for(T / "xl-ready-h"); GO.write_text("1"); time.sleep(0.3)
    sl, waits = xlock.XLock("starve"), []
    try:
        for _ in range(100):
            t0 = time.monotonic(); guarded(lambda: sl.acquire(), 30); waits.append(time.monotonic() - t0); sl.release(); time.sleep(0.002)
    finally:
        (T / "xl-stop").write_text("1"); hog.communicate(timeout=30)
    waits.sort(); print(f"starvation: 100 waits behind a process that takes the lock again at once: median {waits[50]*1e3:.1f} ms, 99th {waits[98]*1e3:.1f} ms, longest {waits[-1]*1e3:.1f} ms", flush=True)
    check("16 starvation: 100 takes of a lock that another process holds nearly all the time and takes again the moment it lets go: the median wait is under 50 ms and the 99th under 250 ms (a poll starves: 150 ms and 1.4 s)",
          waits[50] < 0.05 and waits[98] < 0.25, (waits[50], waits[98], waits[-1]))

    # ---- 17. a filesystem that refuses a flock on a read-only descriptor, the retry's place, the pause, the lines, no spin
    eb, real_flock = xlock.XLock("eb"), fcntl.flock
    def ebadf(fd, op):
        if op & fcntl.LOCK_EX: raise OSError(errno.EBADF, "Bad file descriptor")
        return real_flock(fd, op)
    fcntl.flock = ebadf
    try:
        xlock.strict = False; fds0 = len(os.listdir("/proc/self/fd")); buf = io.StringIO()
        with contextlib.redirect_stderr(buf): got = guarded(lambda: (eb.acquire(), eb._is_owned(), eb.release(), eb._is_owned()))
        check("17 EBADF: a flock refused with EBADF (a filesystem that wants the descriptor open for writing) falls back to the thread lock and says so, naming the lock and the error", got == (True, True, None, False) and len(lines(buf)) == 1 and "Bad file descriptor" in lines(buf)[0] and "eb" in lines(buf)[0], (got, buf.getvalue()))
        check("17 EBADF: ...and leaves no descriptor open", len(os.listdir("/proc/self/fd")) == fds0, (fds0, len(os.listdir("/proc/self/fd"))))
        xlock.strict = True
        try: guarded(lambda: eb.acquire()); got = None
        except xlock.LockUnavailable as e: got = e
        out = []
        def other_thread():
            out.append(eb._t.acquire(timeout=2))
            if out[0]: eb._t.release()
        th = threading.Thread(target=other_thread); th.start(); th.join(5)
        check("17 EBADF: strict on raises LockUnavailable naming the lock file and the errno, and gives the thread lock back", got is not None and got.errno == errno.EBADF and str(eb.path()) in str(got) and eb._is_owned() is False and out == [True], (got, out))
    finally:
        fcntl.flock = real_flock; xlock.strict = False
    rt, calls = xlock.XLock("rt"), []
    def probing(path):
        calls.append(rt._t._is_owned())
        if len(calls) < 3: raise OSError(errno.EMFILE, "Too many open files")
        return real_open(path)
    xlock._open = probing
    try:
        t0 = time.monotonic(); got = guarded(lambda: (rt.acquire(), rt.release())); took = time.monotonic() - t0
    finally: xlock._open = real_open
    check("17 retry: the pause between the tries to open the lock file is taken before the front lock, so it holds no other thread up", calls == [False, False, False], calls)
    check("17 retry: ...and the pause is there (two failures: two pauses of the retry's own length)", took >= 2 * xlock._RETRY_PAUSE * 0.9, took)
    class Stamped(io.StringIO):
        def __init__(s): super().__init__(); s.at = []
        def write(s, x):
            if x.startswith("xlock:"): s.at.append(time.monotonic())
            return super().write(x)
    xlock.WAIT_LOG_FIRST = xlock.WAIT_LOG_EVERY = 0.3
    try:
        for how in ("timed", "blocking"):
            sd = xlock.XLock("sd"); pr = holder("sd", "s" + how); buf = Stamped(); t0 = time.monotonic()
            if how == "timed":
                with contextlib.redirect_stderr(buf): got = guarded(lambda: sd.acquire(timeout=1.0))
                let_go(pr, "s" + how)
            else:
                th = threading.Thread(target=lambda: (sd.acquire(), sd.release()), daemon=True)
                with contextlib.redirect_stderr(buf):
                    th.start(); time.sleep(1.0)
                let_go(pr, "s" + how); th.join(10)
            first, n = (buf.at[0] - t0) if buf.at else 99, len(buf.at)
            check(f"17 wait line ({how}): the first line comes after the first interval, not at once, and not on every try: 2 to 4 lines in 1 s at a 0.3 s interval", first >= 0.25 and 2 <= n <= 4, (first, n, buf.getvalue()))
    finally: xlock.WAIT_LOG_FIRST, xlock.WAIT_LOG_EVERY = old
    sp, count = xlock.XLock("sp"), [0]
    def counting(fd, op):
        if op & fcntl.LOCK_EX: count[0] += 1
        return real_flock(fd, op)
    pr = holder("sp", "sp1"); fcntl.flock = counting
    try:
        got = guarded(lambda: sp.acquire(timeout=0.5)); n_timed = count[0]; count[0] = 0
        th = threading.Thread(target=lambda: (sp.acquire(), sp.release()), daemon=True); th.start(); time.sleep(0.6); n_block = count[0]
    finally: fcntl.flock = real_flock
    let_go(pr, "sp1"); th.join(10)
    check("17 spin: a timed wait of half a second tries the flock fewer than 300 times (it sleeps between tries: no spin, no sleep(0))", got is False and n_timed < 300, (got, n_timed))
    check("17 spin: a wait with no limit blocks in the flock (the try and the wait: at most 3 calls in 0.6 s), it does not poll", 1 <= n_block <= 3, n_block)

    # ---- 18. every newly locked site: a writer in another process saves between the site's read and its write: both survive
    def race_reset():
        it = json.loads((T / "store/a/1.json").read_text()); it["xl"] = {}; it["status"] = "open"
        for k in ("hold", "wake", "after", "check", "needs", "ask", "wait_failed", "outcome", "reason"): it["metadata"].pop(k, None)
        (T / "store/a/1.json").write_text(json.dumps(it)); (T / "store/anchors.json").write_text(json.dumps({"projects/none": [{"url": SITE_URL, "items": ["a1"]}]}))
        (T / "store/a/2.json").write_text(json.dumps({"id": "2", "subject": "[home] two", "description": "- x\n- y\n- z", "status": "completed", "updated": time.time(), "metadata": {"project": "projects/none"}}))
    EVERY_ROUND = ("confirm", "release_after", "anchor_release", "release_green")
    def site_race(site, rounds=60):
        gap = "0.004" if site in EVERY_ROUND else "0.02"        # a pass skips an item that changed between its read and the lock: the saving side pauses longer, so most rounds find it unchanged
        race_reset(); GO.unlink(missing_ok=True); (T / "xl-wake-done").unlink(missing_ok=True)
        kids = [spawn("site", "p", f"{site}:{rounds}"), spawn("until", "q", gap)]
        for tag in ("p", "q"): wait_for(T / f"xl-ready-{tag}")
        GO.write_text("1"); outs = []
        for k in kids:
            try: out, _ = k.communicate(timeout=120)
            except subprocess.TimeoutExpired: k.kill(); out, _ = k.communicate(); out += "\n(timed out)"
            outs.append((k.returncode, out))
            if k is kids[0]: (T / "xl-wake-done").write_text("1")        # the site side is done: the saving side stops
        for tag in ("p", "q"): (T / f"xl-ready-{tag}").unlink(missing_ok=True)
        xl = (json.loads((T / "store/a/1.json").read_text()).get("xl") or {})
        qn = int(m.group(1)) if (m := re.search(r"rounds (\d+)", outs[1][1])) else 0
        pn = int(m.group(1)) if (m := re.search(r"effects (\d+) of", outs[0][1])) else 0
        print(f"site {site}: effect in {pn} of {rounds} rounds, {qn} saves by the other process", flush=True)
        check(f"18 {site}: both processes ran to the end", all(rc == 0 for rc, _ in outs), outs)
        check(f"18 {site}: every save the other process made while the site read and wrote ({qn} of them) is in the file: none lost to the site's write", qn >= 3 and all(f"q{i}" in xl for i in range(qn)), (qn, len(xl), outs))
        every = site in EVERY_ROUND
        check(f"18 {site}: the site did what it owes in {'every round' if every else 'some of the rounds (a pass that finds the item changed leaves it to the next, and the other process saves all the while: at least a sixth)'} ({pn} of {rounds})", pn == rounds if every else pn >= rounds // 6, (pn, outs))
    for site in ("check_close", "check_wait", "check_fail", "confirm", "release_after", "anchor_release", "release_green"):
        site_race(site)

    # ---- 19. the order of the locks, recorded: a lock wanted while another is held, over the passes that take more than one
    EDGES, HELD = set(), threading.local()
    real_acq, real_rel = xlock.XLock.acquire, xlock.XLock.release
    def rec_acquire(self, *a, **k):
        stack = HELD.__dict__.setdefault("s", [])
        if self.name not in stack:
            for h in stack: EDGES.add((h, self.name))
        ok = real_acq(self, *a, **k)
        if ok: stack.append(self.name)
        return ok
    def rec_release(self):
        stack = HELD.__dict__.setdefault("s", [])
        real_rel(self)
        if self.name in stack: stack.pop(len(stack) - 1 - stack[::-1].index(self.name))
    def put(**meta):
        it = json.loads((T / "store/a/1.json").read_text()); it["status"] = "open"; it["state_updated"] = time.time() - 1000
        for k in ("hold", "wake", "after", "check", "needs", "ask", "wait_failed"): it["metadata"].pop(k, None)
        it["metadata"].update(meta); (T / "store/a/1.json").write_text(json.dumps(it))
    def passes():
        from stackshot.service import checks, released, update
        put(hold=True, wake="2000-01-01"); wakes.wake_pass()
        put(after=["a2"], hold=True, wake="2000-01-01"); wakes.release_after("a2", "done", "", "")
        put(hold=True, wake="2099-01-01"); wakes.anchor_release("projects/none", {"kind": "anchor", "anchor": SITE_URL, "to": "x", "ts": time.time() + 60, "id": "n1", "ruling": "passed"})
        (T / "brain/projects/none.md").write_text("---\ntitle: None\ndisplay-name: none\n---\n\n# None\n")      # the update names a page of the registry
        put(); update.update_item("a1", status="completed", outcome="done", reason="finished", outcome_text="- finished"); put()
        real_ev = checks.check_eval; checks.check_eval = lambda c, n, g: (True, "")
        try:
            put(check="item_closed a2"); checks.CHECK_LAST[0] = 0.0; checks.check_tick(now=time.time())
            put(check="item_closed a2", needs=["decision"], ask="Decide: x · Recommend: y · Stakes: z · By: no date"); checks.checks_path().unlink(missing_ok=True); checks.CHECK_LAST[0] = 0.0; checks.check_tick(now=time.time())
        finally: checks.check_eval = real_ev
        put(); update.confirm_item("a1")
    race_reset(); xlock.XLock.acquire, xlock.XLock.release = rec_acquire, rec_release
    try: passes(); err = None
    except Exception as e: err = f"{type(e).__name__}: {e}"
    finally: xlock.XLock.acquire, xlock.XLock.release = real_acq, real_rel
    check("19 order: the passes ran (a wake, a release after a close, an anchor release, an update that closes, a check that closes and one that waits, a confirm)", err is None, err)
    check("19 order: the recorder sees the documented order (the wake lock, then the item lock), so it records something", ("wake", "item") in EDGES, sorted(EDGES))
    check("19 order: no pass takes the wake lock while holding the item lock (the order is wake, then item)", ("item", "wake") not in EDGES, sorted(EDGES))
    check("19 order: no two locks are taken in both orders", not any((b, a) in EDGES for a, b in EDGES), sorted(EDGES))

    # ---- 20. the notices of the wake pass, a release after a close and an anchor release go out after the item lock is let go: no send, push, subprocess or connection under it
    import socket
    BAD, SEEN = [], []
    def watched(mod, name):
        real = getattr(mod, name)
        def w(*a, **k):
            SEEN.append(name)
            if writes.ITEM_LOCK._is_owned(): BAD.append(name)
            return real(*a, **k)
        setattr(mod, name, w); return mod, name, real
    real_popen, real_connect = subprocess.Popen, socket.socket.connect
    class P(real_popen):
        def __init__(self, *a, **k):
            SEEN.append("Popen")
            if writes.ITEM_LOCK._is_owned(): BAD.append("Popen")
            super().__init__(*a, **k)
    def conn(self, *a, **k):
        SEEN.append("connect")
        if writes.ITEM_LOCK._is_owned(): BAD.append("connect")
        return real_connect(self, *a, **k)
    patched = [watched(wakes, n) for n in ("wake_notify", "wake_tell") if hasattr(wakes, n)] + [watched(wakes._watching, "watch_tell"), watched(wakes._telling, "tell_close_mentions")]
    subprocess.Popen, socket.socket.connect = P, conn
    race_reset()
    try:
        put(hold=True, wake="2000-01-01"); wakes.wake_pass()
        put(after=["a2"], hold=True, wake="2000-01-01"); wakes.release_after("a2", "done", "", "")
        put(hold=True, wake="2099-01-01"); wakes.anchor_release("projects/none", {"kind": "anchor", "anchor": SITE_URL, "to": "x", "ts": time.time() + 60, "id": "n1", "ruling": "passed"})
        err = None
    except Exception as e: err = f"{type(e).__name__}: {e}"
    finally:
        subprocess.Popen, socket.socket.connect = real_popen, real_connect
        for mod, name, real in patched: setattr(mod, name, real)
    check("20 no send under the lock: the wake pass, a release after a close and an anchor release ran, and each told through the notice functions", err is None and SEEN.count("wake_notify") >= 3, (err, SEEN))
    check("20 no send under the lock: no notice, push, subprocess or connection was made while the item lock was held", not BAD, (BAD, SEEN))
finally:
    for k in KIDS:
        if k.poll() is None: k.kill()

print(f"xlock: {len(ran)} checks, {len(fails)} failed")
sys.exit(1 if fails else 0)
