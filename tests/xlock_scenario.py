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
  17 the edges     a flock refused with EBADF takes the fallback (strict: LockUnavailable); the lock file is opened after the front lock is taken; the wait line comes after the first interval and not on every try (timed and
                   blocking); a timed wait does not spin; a wait with no limit blocks in the flock
  18 the sites     each site that reads and writes an item (the three branches of the check pass, confirm, a release after a close, an anchor release, the green release) with another process saving the item
                   all the while: the site's effect happens and every save of the other process survives
  19 order         a recorder over the passes that take more than one lock: wake before item, never item before wake, no two locks in both orders
  20 no send       the wake pass, a release after a close and an anchor release send nothing, push nothing, start no process and open no connection while the item lock is held
  21 strict        off by default in production, on by the environment variable (1, true, yes, on), exported on by tests/run-suite; LockUnavailable and LockOrderError are no OSError
  22 order         with strict on a lock is refused when one that comes after it is held (wake, item, answers, then for-you, landed, handback-held, ledger, stall), and a refusal leaves nothing held; strict off refuses nothing
  23 the lock      the review points of the lock: no descriptor opened by a thread that only waits on the front lock, the constructor publishes last, an open's retries do not sleep for a try that may not wait or past a
                   deadline, the front lock is given back on a failed close, a non-OSError and an interrupt, the descriptor is never inheritable, no watchdog outlives its wait
  24 the sends     each send that moved out from under a lock (the wake pass, a release after a close, his answer that drops an item, the escalation pass, the hand-over, a proof, the proof pass, release.sh's call) is made with
                   no lock held, and the page-debt settle reads git with no lock held and keeps a debt written meanwhile; the order of `_answer`'s two locks is recorded
  25 re-key        the GitHub re-key moves the file, the map and the `after` lists with the item lock held; two processes (40 re-keys, saves all the while): every rewritten entry and every save survive
  26 callers       every call of a function whose save is its caller's to lock is under the item lock or in a listed function
  27 the six       landed, ledger, answers, machine anchors, wake and stall: the real function waits while another process holds the lock and completes with its effect when it is let go

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
STRICT0 = xlock.strict                                            # as the environment set it (on under tests/run-suite): the checks that turn it off or on put it back to this
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


def rekey_child(tag, arg):
    """The GitHub re-key of 40 items whose id is in an open item's `after` list (put there under the item lock, as a writer does), the write the re-key ends in slowed: its read-then-rewrite of that list is a wide window."""
    from stackshot.github import ghsync
    rounds = int(arg)
    slow(ghsync, "_write_item")
    p = T / "store/a/6.json"; moved = []
    for i in range(rounds):
        old = f"a{200 + i}"
        (T / "store/a" / f"{200 + i}.json").write_text(json.dumps({"id": old, "subject": f"[home] moved {old}", "description": "- x\n- y\n- z", "status": "open", "updated": time.time(), "metadata": {"project": "projects/none"}}))
        with writes.ITEM_LOCK:
            it = json.loads(p.read_text()); it["metadata"]["after"] = [*it["metadata"].get("after", []), old]; writes.save("a6", it, writer="")
        moved.append(ghsync.rekey(T / "store", old, 900 + i))
    (T / "xl-wake-done").write_text("1"); print("moved " + " ".join(moved))


def saves_child(tag, arg):
    """Saves to the same open item, under the item lock, for as long as the re-keys run."""
    p = T / "store/a/6.json"; i = 0
    while i < 3 or not (T / "xl-wake-done").exists():
        with writes.ITEM_LOCK:
            it = json.loads(p.read_text()); it.setdefault("xl", {})[f"{tag}{i}"] = i; writes.save("a6", it, writer="")
        i += 1; time.sleep(0.004)
    print(f"rounds {i}")


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
    elif kind == "rekey":
        rekey_child(tag, arg)
    elif kind == "saves":
        saves_child(tag, arg)
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
        xlock._open, _cfg.state, xlock.strict = real_open, real_state, STRICT0

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
    LOCKED_BY_CALLER[("github/ghsync.py", "take")] = "the re-key's file move (_move): it holds the item lock, `XLock(\"item\")`, from its read to the last removal of the old file"
    UNLOCKED_FOLLOW_UP = {}   # the writers of an item file that are neither writes.save nor under the lock: none (the GitHub re-key took the item lock)
    def is_item_lock(t): return "ITEM_LOCK" in t or t.replace(" ", "").endswith('XLock("item")')
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
                    if (name.endswith("_writes.save") or name.endswith("writes.save") or name.endswith("_write_item")) and rel not in ("web/search.py",) and not any(is_item_lock(t) for t in w):
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
        fcntl.flock = real_flock; xlock.strict = STRICT0
    rt, calls = xlock.XLock("rt"), []
    def probing(path):
        calls.append(rt._t._is_owned())
        if len(calls) < 3: raise OSError(errno.EMFILE, "Too many open files")
        return real_open(path)
    xlock._open = probing
    try:
        t0 = time.monotonic(); got = guarded(lambda: (rt.acquire(), rt.release())); took = time.monotonic() - t0
    finally: xlock._open = real_open
    check("17 retry: the lock file is opened after the front lock is taken (a thread that only waits on it holds no descriptor)", calls == [True, True, True], calls)
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

    # ======================================================================== strict, the sends, the re-key, the review points
    PATCHED = []
    def swap(mod, name, new):
        PATCHED.append((mod, name, getattr(mod, name))); setattr(mod, name, new)
    def unswap():
        while PATCHED:
            mod, name, real = PATCHED.pop(); setattr(mod, name, real)
    def lockstate(): return [n for n, l in LOCKS.items() if l._is_owned()]
    def noting(log, name, ret=None):
        def f(*a, **k):
            log.append((name, lockstate())); return ret
        return f
    def edges_of(fn):
        EDGES.clear(); HELD.__dict__.pop("s", None)
        xlock.XLock.acquire, xlock.XLock.release = rec_acquire, rec_release
        try: out, err = fn(), None
        except Exception as e: out, err = None, f"{type(e).__name__}: {e}"
        finally: xlock.XLock.acquire, xlock.XLock.release = real_acq, real_rel
        return set(EDGES), out, err
    ASK2 = "Decide: x · Recommend: y · Stakes: z · By: no date"

    # ---- 21. strict: where it is set, and what it does
    def strict_of(val):
        env = {k: v for k, v in os.environ.items() if k != "STACKSHOT_XLOCK_STRICT"}
        if val is not None: env["STACKSHOT_XLOCK_STRICT"] = val
        r = subprocess.run([sys.executable, "-c", f"import sys; sys.path.insert(0, {STACK!r}); from stackshot.core import xlock; print(xlock.strict)"], env=env, capture_output=True, text=True, cwd=STACK, timeout=120)
        return r.stdout.strip() or r.stderr[-300:]
    got = {v: strict_of(v) for v in (None, "", "0", "false", "off", "1", "true", "YES", " on ")}
    check("21 strict: off by default in production: the variable unset, empty or false leaves it off, so the single-process server is never broken by a lock rule",
          all(got[v] == "False" for v in (None, "", "0", "false", "off")), got)
    check("21 strict: ...and the variable (1, true, yes, on, any case) turns it on", all(got[v] == "True" for v in ("1", "true", "YES", " on ")), got)
    rs = (pathlib.Path(SCR) / "run-suite").read_text(encoding="utf-8")
    check("21 strict: tests/run-suite turns it on for every suite (the variable is exported, 1 unless the caller set it)", re.search(r"(?m)^STACKSHOT_XLOCK_STRICT=\$\{STACKSHOT_XLOCK_STRICT:-1\}$", rs) is not None and re.search(r"(?m)^export STACKSHOT_XLOCK_STRICT$", rs) is not None, None)
    check("21 strict: this process has it as its environment says (on under tests/run-suite)", STRICT0 is (os.environ.get("STACKSHOT_XLOCK_STRICT", "").strip().lower() in ("1", "true", "yes", "on")), (STRICT0, os.environ.get("STACKSHOT_XLOCK_STRICT")))
    check("21 strict: LockUnavailable and LockOrderError are RuntimeErrors and no OSError (a broad `except OSError` cannot swallow them)",
          all(issubclass(c, RuntimeError) and not issubclass(c, OSError) for c in (xlock.LockUnavailable, xlock.LockOrderError)), None)

    # ---- 22. the order, enforced when strict
    def nest(first, second):
        a, b = xlock.XLock(first), xlock.XLock(second)
        try:
            with a:
                with b: return "ok"
        except xlock.LockOrderError: return "order"
        except Exception as e: return repr(e)
    CASES = (("wake", "item", "ok"), ("item", "wake", "order"), ("item", "answers", "ok"), ("answers", "item", "order"), ("answers", "for-you", "ok"), ("for-you", "answers", "order"),
             ("answers", "landed", "ok"), ("answers", "handback-held", "ok"), ("item", "ledger", "ok"), ("ledger", "item", "order"), ("item", "stall", "ok"), ("stall", "item", "order"),
             ("landed", "for-you", "ok"), ("wake", "answers", "ok"), ("answers", "wake", "order"), ("machine-anchors", "item", "ok"), ("item", "machine-anchors", "ok"), ("item", "item", "ok"))
    xlock.strict = True
    try:
        res = {(a, b): nest(a, b) for a, b, _ in CASES}
        bad = {k: v for (a, b, want) in CASES if (v := res[(a, b)]) != want for k in [(a, b)]}
        check("22 order: with strict on a lock is refused (LockOrderError) when a lock that comes after it is held: wake, item, answers, then for-you, landed, handback-held, ledger, stall; machine-anchors is outside the order", not bad, bad)
        check("22 order: ...and a refused lock leaves nothing held: no lock of the nine is owned by this thread, no file is locked", not lockstate() and xlock._held() == [] and all(raw_free(n) for n in LOCKS), (lockstate(), xlock._held()))
        def swapped():
            with xlock.XLock("answers"):
                with xlock.XLock("item"): return "ok"
        try: swapped(); got = "ok"
        except xlock.LockOrderError as e: got = str(e)
        check("22 order: answers before item (the swap of `_answer`'s order) is refused with a message naming both", got != "ok" and "item" in got and "answers" in got, got)
    finally: xlock.strict = STRICT0
    xlock.strict = False
    try:
        check("22 order: with strict off nothing is refused, whatever the order (a lock rule never breaks the single-process server)", all(nest(a, b) == "ok" for a, b, _ in CASES), {(a, b): nest(a, b) for a, b, _ in CASES})
    finally: xlock.strict = STRICT0

    # ---- 23. the review points of the lock itself
    real_thread_open = xlock._open
    # (a) and (e): the lock file is opened after the front lock is taken: a waiter holds no descriptor, a failed timed try opens none
    xl_a = xlock.XLock("fdw"); opens = []
    xlock._open = lambda p: (opens.append(threading.get_ident()), real_thread_open(p))[1]
    try:
        xl_a.acquire(); me = threading.get_ident(); fds0 = len(os.listdir("/proc/self/fd")); res = {}
        def waiter():
            res["timed"] = [xl_a.acquire(timeout=0.02) for _ in range(30)]
            res["ident"] = threading.get_ident()
        th = threading.Thread(target=waiter, daemon=True); th.start(); th.join(30)
        fds1 = len(os.listdir("/proc/self/fd"))
        blk = threading.Thread(target=lambda: (res.update(b=threading.get_ident()), xl_a.acquire(), xl_a.release()), daemon=True); blk.start(); time.sleep(0.3)
        opened_by_waiters = [i for i in opens if i != me]
        fds2 = len(os.listdir("/proc/self/fd"))
        xl_a.release(); blk.join(10)
    finally: xlock._open = real_thread_open
    check("23 descriptor (a, e): a thread that waits on the front lock opens no lock file: 30 timed tries that fail and a blocking wait open none and hold none", not any(res["timed"]) and not opened_by_waiters and fds1 == fds0 and fds2 == fds0, (res, opened_by_waiters, fds0, fds1, fds2))
    # (e): a timed or non-blocking try that gets the front lock but not the flock (another process holds the file) gives its descriptor back
    xl_e = xlock.XLock("fde"); raw_e = os.open(xl_e.path(), os.O_RDONLY | os.O_CREAT, 0o644); fcntl.flock(raw_e, fcntl.LOCK_EX)
    try:
        fde0 = len(os.listdir("/proc/self/fd"))
        timed_e = [xl_e.acquire(timeout=0.02) for _ in range(20)]; nb_e = [xl_e.acquire(blocking=False) for _ in range(20)]
        fde1 = len(os.listdir("/proc/self/fd")); owned_e = xl_e._is_owned()
    finally: fcntl.flock(raw_e, fcntl.LOCK_UN); os.close(raw_e)
    check("23 descriptor (e): a timed try and a non-blocking try that lose the flock to another process leave no descriptor open and no front lock held (20 of each)", not any(timed_e) and not any(nb_e) and fde1 == fde0 and not owned_e and xl_e.acquire(timeout=1) and xl_e._fd is not None, (timed_e, nb_e, fde0, fde1, owned_e))
    if xl_e._is_owned(): xl_e.release()
    # (b): the constructor publishes last
    seen_pub = []
    real_rlock = threading.RLock
    def spy_rlock(*a, **k):
        seen_pub.append("pubx" in xlock.XLock._by_name); return real_rlock(*a, **k)
    threading.RLock = spy_rlock
    try: pub = xlock.XLock("pubx")
    finally: threading.RLock = real_rlock
    check("23 constructor (b): a new XLock is published (findable by name) only after it is made whole: its thread lock is made before the name is known", seen_pub == [False] and xlock.XLock("pubx") is pub and pub._t is not None and hasattr(pub, "_fd"), seen_pub)
    # (c): the open's retries: none for a try that may not wait, none past a timed try's deadline
    xlock.strict = False
    try:
        calls = []; emf = OSError(errno.EMFILE, "Too many open files")
        def always_emfile(p): calls.append(time.monotonic()); raise emf
        xlock._open = always_emfile
        nb = xlock.XLock("nbo")
        with contextlib.redirect_stderr(io.StringIO()):
            t0 = time.monotonic(); got_nb = nb.acquire(blocking=False); took_nb = time.monotonic() - t0
            if got_nb: nb.release()
            n_nb = len(calls); calls.clear()
            t0 = time.monotonic(); got_t = nb.acquire(timeout=0.03); took_t = time.monotonic() - t0
            if got_t: nb.release()
            n_t = len(calls)
    finally: xlock._open, xlock.strict = real_thread_open, STRICT0
    check("23 retries (c): a non-blocking acquire whose lock file cannot be opened (no descriptor left) tries once and does not sleep: one call, under one pause of time", n_nb == 1 and took_nb < xlock._RETRY_PAUSE, (n_nb, took_nb))
    check("23 retries (c): a timed acquire does not sleep past its deadline (30 ms): at most two tries and well under the three pauses an unbounded retry takes", n_t <= 2 and took_t < 2 * xlock._RETRY_PAUSE + 0.02, (n_t, took_t))
    # (d): the front lock is given back on every way out
    cl = xlock.XLock("cls"); real_close = os.close
    def bad_close(fd):
        real_close(fd); raise OSError(errno.EIO, "close failed")
    cl.acquire(); os.close = bad_close
    try:
        try: cl.release(); err = None
        except Exception as e: err = e
    finally: os.close = real_close
    check("23 release (d): a descriptor that will not close (it is gone all the same) neither raises from release nor keeps the front lock: another thread takes it at once", err is None and cl._is_owned() is False and raw_free("cls") and guarded(lambda: try_take(cl, blocking=False)) is True, err)
    boom = xlock.XLock("boom"); real_lock_fd2 = xlock.XLock._lock_fd
    def exploding(self, fd, blocking, deadline): raise RuntimeError("boom")
    fds0 = len(os.listdir("/proc/self/fd")); xlock.XLock._lock_fd = exploding
    try:
        try: boom.acquire(); err = None
        except RuntimeError as e: err = e
    finally: xlock.XLock._lock_fd = real_lock_fd2
    out = []; th = threading.Thread(target=lambda: (out.append(boom._t.acquire(timeout=2)), boom._t.release() if out[0] else None), daemon=True); th.start(); th.join(5)
    check("23 acquire (d): an error that is not an OSError (here a RuntimeError out of the flock step) gives the front lock back and leaves no descriptor open", isinstance(err, RuntimeError) and out == [True] and len(os.listdir("/proc/self/fd")) == fds0 and boom._is_owned() is False, (err, out, fds0, len(os.listdir("/proc/self/fd"))))
    xlock.XLock._lock_fd = lambda self, fd, blocking, deadline: (_ for _ in ()).throw(KeyboardInterrupt())
    try:
        try: boom.acquire(); err = None
        except KeyboardInterrupt as e: err = e
    finally: xlock.XLock._lock_fd = real_lock_fd2
    check("23 acquire (d): ...an interrupt too (a BaseException), and a later acquire is not blocked by it", err is not None and boom._is_owned() is False and guarded(lambda: try_take(boom, blocking=False)) is True, err)
    # (f): close-on-exec is pinned
    real_os_open = os.open
    def inheritable_open(path, flags, mode=0o777):
        fd = real_os_open(path, flags, mode); os.set_inheritable(fd, True); return fd
    os.open = inheritable_open
    try: fd = xlock._open(T / "state" / "pinned.lock"); inh = os.get_inheritable(fd); os.close(fd)
    finally: os.open = real_os_open
    check("23 close-on-exec (f): the descriptor the lock opens is never inheritable, whatever os.open gave (a child process must not hold the lock past its owner)", inh is False, inh)
    with xlock.XLock("exe"):
        check("23 close-on-exec (f): ...and the live one carries FD_CLOEXEC", bool(fcntl.fcntl(xlock.XLock("exe")._fd, fcntl.F_GETFD) & fcntl.FD_CLOEXEC) and not os.get_inheritable(xlock.XLock("exe")._fd), None)
    # (g): no watchdog outlives the wait it watched
    real_watch = xlock.XLock._watch
    def lingering(self, stop, started):
        real_watch(self, stop, started); time.sleep(0.4)
    xlock.XLock._watch = lingering
    try:
        wd = xlock.XLock("wdg"); pr = holder("wdg", "wd1"); seen = {}
        th = threading.Thread(target=lambda: (wd.acquire(), seen.update(alive=[t.name for t in threading.enumerate() if t.name.startswith("xlock-wait-")]), wd.release()), daemon=True)
        th.start(); time.sleep(0.4)
        during = [t.name for t in threading.enumerate() if t.name.startswith("xlock-wait-")]
        let_go(pr, "wd1"); th.join(15)
    finally: xlock.XLock._watch = real_watch
    check("23 watchdog (g): a blocked acquire has its watchdog while it waits, and none is alive when the acquire returns (it is stopped and waited for)", during == ["xlock-wait-wdg"] and seen.get("alive") == [], (during, seen))

    # ---- 24. the sends that moved out from under the locks, each seen from the lock it used to be under
    def site_item(**meta):
        race_reset(); put(**meta)
    from stackshot.service import answer as answer_svc, proofs, released as released_svc, event_waits as evw_svc, wait_gates
    from stackshot.waits import watchers as watchers_mod
    from stackshot.anchors import machine_anchor as ma_mod
    try:
        # the wake pass: what it collected under the wake lock is sent after it
        site_item(hold=True, wake="2000-01-01"); log = []
        swap(wakes, "wake_notify", lambda gid, it, what, out=None, reminder=False: (out.setdefault("sidx", []).append((gid, it, what, "", False)) if out is not None else None, ["sidx"])[1])
        swap(wakes, "wake_tell", noting(log, "wake_tell"))
        swap(wakes._watching, "watch_text", lambda sid, rows: ("", "", []))
        swap(wakes._watching, "watch_pass", lambda epoch, wout: (wout.setdefault("sidw", []).append(("a1", {}, "x")), [])[1])
        swap(wakes._watching, "watch_tell", noting(log, "watch_tell"))
        wakes.wake_pass(); unswap()
        check("24 wake pass: the wake message and the watchers' message are sent with no lock held (they were sent under the wake lock)", sorted(n for n, _ in log) == ["wake_tell", "watch_tell"] and all(h == [] for _, h in log), log)
        # a release after a close hands its notices to a caller that holds the item lock round a loop
        site_item(after=["a2"], hold=True, wake="2000-01-01"); log = []; later = []
        swap(wakes, "wake_notify", noting(log, "wake_notify", []))
        swap(wakes._telling, "tell_close_mentions", noting(log, "tell_close_mentions"))
        with writes.ITEM_LOCK: rel = wakes.release_after("a2", "done", "", "", defer=later)
        sent_inside = list(log)
        for fn in later: fn()
        check("24 release after (defer): with a `defer` list nothing is sent by the call (the caller holds the item lock), the writes are made, and the list holds the notices to send once the lock is let go", rel == ["a1"] and sent_inside == [] and len(later) == 2, (rel, sent_inside, len(later)))
        check("24 release after (defer): ...and they go out, each, when the caller runs them", sorted(n for n, _ in log) == ["tell_close_mentions", "wake_notify"] and all(h == [] for _, h in log), log)
        unswap()

        # a waiter whose save raises: the waiters released before it have their notice (the error goes on up, the close's own mention notice waits for a loop that ended)
        site_item(after=["a2"], hold=True, wake="2000-01-01")
        three = json.loads((T / "store/a/1.json").read_text()); three["id"] = "3"; (T / "store/a/3.json").write_text(json.dumps(three))
        real_save = writes.save
        def failing_save(g, *a, **k):
            if g == "a3": raise OSError("disk full")
            return real_save(g, *a, **k)
        try:
            log = []; later = []
            swap(wakes, "wake_notify", noting(log, "wake_notify", [])); swap(wakes._telling, "tell_close_mentions", noting(log, "tell_close_mentions")); swap(wakes._writes, "save", failing_save)
            try: wakes.release_after("a2", "done", "", ""); err = None
            except OSError as e: err = f"OSError: {e}"
            one = json.loads((T / "store/a/1.json").read_text()); unswap()
            check("24 release after (a failed save): the waiter saved and released before the one whose save raised is told it was woken (with no lock held), and the error goes on up", err == "OSError: disk full" and [n for n, _ in log] == ["wake_notify"] and log[0][1] == [] and "hold" not in one["metadata"], (err, log))
            site_item(after=["a2"], hold=True, wake="2000-01-01"); log = []
            swap(wakes, "wake_notify", noting(log, "wake_notify", [])); swap(wakes._telling, "tell_close_mentions", noting(log, "tell_close_mentions")); swap(wakes._writes, "save", failing_save)
            try:
                with writes.ITEM_LOCK: wakes.release_after("a2", "done", "", "", defer=later)
                err = None
            except OSError as e: err = f"OSError: {e}"
            inside = list(log)
            for fn in later: fn()
            unswap()
            check("24 release after (a failed save, defer): the same with a `defer` list: nothing is sent under the caller's lock, the waiter's notice is on the list, the error goes on up, and the close's mention notice is not queued", err == "OSError: disk full" and inside == [] and [n for n, _ in log] == ["wake_notify"] and len(later) == 1, (err, inside, log, len(later)))
        finally:
            unswap(); (T / "store/a/3.json").unlink(missing_ok=True)
        # his answer drops the item: the items that waited on it are released after both locks are let go
        site_item(needs=["decision"], ask=ASK2); log = []
        swap(watchers_mod, "answer_effect", lambda meta, choice, text, today=None: {"do": "drop"})
        swap(wait_gates, "_watch_answer", lambda item, meta, eff, now: "dropped")
        swap(wakes, "release_after", lambda *a, **k: (log.append(("release_after", lockstate())), [])[1])
        edges, res, err = edges_of(lambda: answer_svc._answer("a1", "Yes", "", ""))
        unswap(); answers._answers_save({})
        check("24 answer: his answer that drops an item ran (the answer is recorded) and released the items that waited on it", err is None and res == "decision" and [n for n, _ in log] == ["release_after"], (err, res, log))
        check("24 answer: ...with neither the item lock nor the answers lock held (the release tells the waiters; it was called under both)", log and log[0][1] == [], log)
        check("24 answer: the order of its two locks: the item lock, then the answers lock, never the reverse (a swap fails here, and raises under strict)", ("item", "answers") in edges and ("answers", "item") not in edges, sorted(edges))
        # the escalation pass: the keeper is told after the answers lock is let go
        answers._answers_save({"a1": {"ts": 1000.0, "owner": "", "project": "projects/none", "told": [], "words": "x"}}); site_item(); log = []
        swap(answer_svc._telling, "page_keeper", lambda p: "keeperx"); swap(answer_svc._telling, "project_keeper", lambda *a, **k: "keeperx")
        swap(answer_svc._telling, "keeper_words", lambda *a, **k: "its keeper"); swap(answer_svc, "_session_id", lambda s: str(s or ""))
        swap(answer_svc._telling, "tell_woken", noting(log, "tell_woken"))
        edges, res, err = edges_of(lambda: answer_svc._answer_tick(4e9)); unswap(); answers._answers_save({})
        check("24 answer tick: the keeper of an answer that was not acted on is told, with no lock held (the answers lock was held), and the pass says whom it escalated", err is None and res == ["a1"] and [n for n, _ in log] == ["tell_woken"] and log[0][1] == [], (err, res, log))
        check("24 answer tick: the item lock is never taken while the answers lock is held (the order is item, then answers)", ("answers", "item") not in edges, sorted(edges))
        # the hand-over: the item moves under its lock, the next session is told after it
        site_item(); log = []
        swap(proofs._hv, "decide", lambda *a, **k: {"action": "moved", "to": "home-agent", "hash": "h1", "step": "do the thing", "why": ""})
        swap(proofs._live, "released_skip", lambda *a, **k: "")
        swap(proofs._telling, "tell_woken", noting(log, "tell_woken"))
        row = proofs.handover("a1", time.time(), ["a step"])
        check("24 hand-over: the item moved and its new session was told, with no lock held (it was told under the item lock)", row and row.get("action") == "moved" and [n for n, _ in log] == ["tell_woken"] and log[0][1] == [], (row, log))
        site_item(); log.clear(); later = []
        with writes.ITEM_LOCK: row = proofs.handover("a1", time.time(), ["a step"], defer=later)
        inside = list(log)
        for fn in later: fn()
        unswap()
        check("24 hand-over (defer): called from a loop that holds the item lock it tells nobody itself: the notice comes back to the caller, and goes out when the caller runs it with no lock held", row and row.get("action") == "moved" and inside == [] and len(later) == 1 and log and log[0][1] == [], (row, inside, later, log))
        # a proof: the notices of proof_item are handed back to the pass that holds the item lock
        site_item(next="do the release step 7"); log = []; sendl = []
        swap(proofs, "proof_hits", lambda *a, **k: {0: False}); swap(proofs._live, "released_skip", lambda *a, **k: "")
        swap(proofs._telling, "holder", lambda it: "home-agent"); swap(proofs._telling, "tell_woken", noting(log, "tell_woken"))
        try:
            with writes.ITEM_LOCK: row = proofs.proof_item("a1", 7, "o/r#7", "", set(), False, time.time(), proofs._sp.PR_MERGED, dead="closed without a merge", sends=sendl)
            err = None
        except Exception as e: row, err = None, f"{type(e).__name__}: {e}"
        inside = list(log)
        proofs.flush_sends(sendl); unswap()
        check("24 proof: a pull request closed without a merge tells its item's mover through the `sends` the pass gave it, not while the pass holds the item lock", err is None and row and row.get("action") == "told" and inside == [] and len(sendl) == 1 and [n for n, _ in log] == ["tell_woken"] and log[0][1] == [], (err, row, inside, sendl, log))
        site_item(next="do the release step 7"); log = []; sendl = []; rel_calls = []
        swap(proofs, "proof_hits", lambda cl, opened, *a, **k: {i: True for i in opened}); swap(proofs._live, "released_skip", lambda *a, **k: "")
        swap(proofs._wakes, "release_after", lambda *a, **k: (rel_calls.append(k.get("defer") is sendl), [])[1])
        try:
            with writes.ITEM_LOCK: row = proofs.proof_item("a1", 7, "o/r#7", "merged", set(), False, time.time(), proofs._sp.PR_MERGED, sends=sendl)
            err = None
        except Exception as e: row, err = None, f"{type(e).__name__}: {e}"
        unswap()
        check("24 proof: a proof that closes the item hands the release of the items that waited on it the pass's `sends` list (it is called under the item lock)", err is None and row and row.get("action") == "closed" and rel_calls == [True], (err, row, rel_calls))
        # a proof that ticks a step and leaves another open hands the hand-over the pass's `sends` list too (it tells the next session, and is called under the item lock)
        site_item(next="do the release step 7"); sendl = []; seen = []
        swap(proofs._steps, "view", lambda meta, keeper="": [{"text": "release PR #7 is live", "status": proofs._steps.OPEN}, {"text": "then check the page", "status": proofs._steps.OPEN}])
        swap(proofs, "proof_hits", lambda cl, opened, *a, **k: {0: True}); swap(proofs._live, "released_skip", lambda *a, **k: "")
        swap(proofs._telling, "holder", lambda it: "home-agent"); swap(proofs._telling, "tell_woken", lambda *a, **k: None)
        swap(proofs, "handover", lambda gid, now, done, dry=False, defer=None: (seen.append(defer is sendl), None)[1])
        try:
            with writes.ITEM_LOCK: row = proofs.proof_item("a1", 7, "o/r#7", "merged", set(), False, time.time(), proofs._sp.PR_MERGED, sends=sendl)
            err = None
        except Exception as e: row, err = None, f"{type(e).__name__}: {e}"
        unswap()
        check("24 proof: a proof that ticks a step and leaves another open hands the hand-over the pass's `sends` list (the hand-over's notice is sent with the rest, not under the item lock)", err is None and row and row.get("action") == "ticked" and seen == [True], (err, row, seen))
        # the passes: the notices are sent when the item lock is let go
        site_item(next="do the release step 7"); log = []
        def stub_item(*a, sends=None, **k):
            if sends is not None: sends.append(lambda: log.append(("sent", lockstate())))
            return {"item": a[0], "action": "told"}
        swap(proofs, "proof_item", stub_item); swap(proofs, "proof_events", lambda *a, **k: [(proofs._sp.PR_MERGED, 7, "o/r#7")])
        swap(proofs._checks, "pr_merged", lambda *a, **k: (True, "")); swap(proofs._live, "released_live_base", lambda: ("g" * 40, "h" * 40))
        try: out = proofs.sweep_proofs(); err = None
        except Exception as e: out, err = None, f"{type(e).__name__}: {e}"
        unswap()
        check("24 proof pass: the notices the pass collects round the items are sent after the item lock is let go (one per item the pass settled)", err is None and log and all(n == "sent" and h == [] for n, h in log), (err, log))
        site_item(next="do the release step 7"); log = []
        hk = released_svc._hooks()
        class OwnRepo:      # the hooks are a frozen record: the repository this checkout belongs to is the one the PR is of
            def __getattr__(self, n): return (lambda: "o/r") if n == "own_repo" else getattr(hk, n)
        swap(released_svc, "_hooks", lambda: OwnRepo())
        swap(released_svc, "released_item", lambda *a, **k: (k.get("sends") if k.get("sends") is not None else a[7]).append(lambda: log.append(("sent", lockstate()))) or {"item": a[0], "action": "told"})
        swap(released_svc._live, "git_commit", lambda *a, **k: "f" * 40); swap(released_svc._live, "merged_prs", lambda *a, **k: {7: ("m" * 40, 1.0)})
        swap(released_svc._live, "released_live_base", lambda: ("g" * 40, "h" * 40)); swap(released_svc._live, "released_is_live", lambda *a, **k: "")
        swap(released_svc._live, "released_foreign", lambda *a, **k: None); swap(released_svc._evwaits, "evwait_hook", lambda *a, **k: None)
        try: out = released_svc.released("https://github.com/o/r/pull/7", "f" * 40); err = None
        except Exception as e: out, err = None, f"{type(e).__name__}: {e}"
        finally: unswap()
        check("24 release: release.sh's call tells the items' movers after the item lock is let go", err is None and log and all(n == "sent" and h == [] for n, h in log), (err, log))

        site_item(next="release PR #7"); log = []
        swap(released_svc, "_hooks", lambda: OwnRepo())
        swap(released_svc, "released_item", lambda gid, n, key, live, anchored, dry, now, sends=None: (sends.append(lambda: log.append(("sent", lockstate()))), {"item": gid, "action": "none"})[1])
        swap(released_svc._live, "git_commit", lambda *a, **k: "f" * 40); swap(released_svc._live, "merged_prs", lambda *a, **k: {7: ("m" * 40, 1.0)})
        swap(released_svc._live, "released_live_base", lambda: ("g" * 40, "h" * 40)); swap(released_svc._live, "released_is_live", lambda *a, **k: "")
        swap(released_svc._live, "released_anchors", lambda *a, **k: {}); swap(released_svc._evwaits, "evwait_poll", lambda *a, **k: None)
        try: out = released_svc.sweep_released(); err = None
        except Exception as e: out, err = None, f"{type(e).__name__}: {e}"
        finally: unswap()
        check("24 release sweep: the sweep's notices are sent after its loop lets the item lock go (a sweep that never sends them loses every notice of the pass)", err is None and out and len(out["items"]) == 1 and log == [("sent", [])], (err, out, log))
        # the ledger: the pages' git is read with no lock held, and a debt written meanwhile survives
        ledger_p = page_debts._owed_path()
        ledger_p.write_text(json.dumps({"projects/none": {"o1": {"ts": 1000.0}}}), encoding="utf-8"); log = []
        def late_debt(key):
            log.append(("page_ts", lockstate()))
            page_debts._owed_save({**json.loads(ledger_p.read_text()), "projects/none": {**json.loads(ledger_p.read_text())["projects/none"], "o2": {"ts": 2000.0}}})
            return 5000.0
        swap(page_debts, "_page_ts", late_debt); swap(page_debts, "_debt_strict", lambda *a, **k: True)
        swap(page_debts._pages, "ct_changed_since", lambda *a, **k: (log.append(("ct", lockstate())), True)[1])
        try: res = page_debts._owed_settle(); err = None
        except Exception as e: res, err = None, f"{type(e).__name__}: {e}"
        unswap(); left = json.loads(ledger_p.read_text()); ledger_p.write_text("{}", encoding="utf-8")
        check("24 ledger: the page's time and compiled truth are read with the ledger lock not held (they are git processes)", err is None and [n for n, _ in log] == ["page_ts", "ct"] and all(h == [] for _, h in log), (err, log))
        check("24 ledger: ...a debt written while they were read is kept (the settle applies its verdicts to the ledger as it stands then), and the debt that was settled is gone", err is None and "o1" not in left.get("projects/none", {}) and "o2" in left.get("projects/none", {}) and "o2" in (res or {}).get("projects/none", {}), (err, left, res))
        # ...and a debt charged again on the same debtor while they were read (a new `ts`) is not the one that was settled: it stays for the next pass
        ledger_p.write_text(json.dumps({"projects/none": {"o1": {"ts": 1000.0}}}), encoding="utf-8")
        def recharge(key):
            page_debts._owed_save({"projects/none": {"o1": {"ts": 3000.0}}}); return 5000.0
        swap(page_debts, "_page_ts", recharge); swap(page_debts, "_debt_strict", lambda *a, **k: True); swap(page_debts._pages, "ct_changed_since", lambda *a, **k: True)
        try: res = page_debts._owed_settle(); err = None
        except Exception as e: res, err = None, f"{type(e).__name__}: {e}"
        unswap(); left = json.loads(ledger_p.read_text()); ledger_p.write_text("{}", encoding="utf-8")
        check("24 ledger: ...and a debt written again for the same debtor meanwhile (a different `ts`) is kept, not deleted by the verdict on the debt that was read", err is None and left.get("projects/none", {}).get("o1", {}).get("ts") == 3000.0, (err, left))
    finally: unswap(); answers._answers_save({})

    # ---- 25. the GitHub re-key is under the item lock
    from stackshot.github import ghsync
    store = T / "store"
    def rekey_items(old_ids, after_of=()):
        for i in old_ids:
            (store / "a" / f"{i[1:]}.json").write_text(json.dumps({"id": i, "subject": f"[home] moved {i}", "description": "- x\n- y\n- z", "status": "open", "updated": time.time(), "metadata": {"project": "projects/none"}}))
        (store / "a" / "6.json").write_text(json.dumps({"id": "a6", "subject": "[home] waits", "description": "- x\n- y\n- z", "status": "open", "updated": time.time(), "metadata": {"project": "projects/none", "after": list(after_of)}}))
    rekey_items(["a5"], after_of=["a5", "a2"]); log = []
    def noting_real(mod, name):
        real = getattr(mod, name)
        def f(*a, **k):
            log.append((name, lockstate())); return real(*a, **k)
        swap(mod, name, f)
    noting_real(ghsync, "_write_item"); noting_real(ghsync, "record_issue")
    try: new = ghsync.rekey(store, "a5", 77); err = None
    except Exception as e: new, err = None, f"{type(e).__name__}: {e}"
    unswap()
    names = [n for n, _ in log]
    check("25 re-key: the move ran: the item has its new id, the map names it, the old file is gone and the list that waited on the old id waits on the new", err is None and new and (store / "a" / "5.json").exists() is False and ghsync.resolve("a5") == new and json.loads((store / "a" / "6.json").read_text())["metadata"]["after"] == [new, "a2"], (err, new))
    check("25 re-key: the file move, the map and the rewrite of the `after` list each happen with the item lock held (a save of the item waits for them, in this process or another)", err is None and names.count("_write_item") >= 2 and "record_issue" in names and all("item" in h for _, h in log), log)
    # a list that stopped naming the old id between the scan and the lock (the item closed meanwhile) is left as it is: the re-key reads it again under the lock
    import types
    rekey_items(["a7"], after_of=["a7", "a2"]); entries = [0]
    class HookLock:
        def __init__(self, real): self.real = real
        def __enter__(self):
            if not self.real._is_owned():
                entries[0] += 1
                if entries[0] == 2:             # the second hold of the item lock is the rewrite of the list: a writer closes the item just before it
                    six = json.loads((store / "a/6.json").read_text()); six["status"] = "completed"; (store / "a/6.json").write_text(json.dumps(six))
            self.real.acquire(); return self.real
        def __exit__(self, *e): self.real.release()
    swap(ghsync, "_xlock", types.SimpleNamespace(XLock=lambda name: HookLock(xlock.XLock(name))))
    try: new = ghsync.rekey(store, "a7", 88); err = None
    except Exception as e: new, err = None, f"{type(e).__name__}: {e}"
    unswap()
    six = json.loads((store / "a/6.json").read_text())
    check("25 re-key: a list that no longer names the old id when the lock is held (its item closed after the scan) is left as it was: it is read again under the lock", err is None and new and entries[0] == 2 and six["status"] == "completed" and six["metadata"]["after"] == ["a7", "a2"], (err, new, entries, six["metadata"]))
    (store / "g/88.json").unlink(missing_ok=True); (store / "a/7.json").unlink(missing_ok=True)
    # two processes: the re-key rewrites an `after` list while the other process saves the same item (the children are rekey_child and saves_child above)
    rekey_items([], after_of=[]); (T / "store/github-map.json").unlink(missing_ok=True)
    GO.unlink(missing_ok=True); (T / "xl-wake-done").unlink(missing_ok=True)
    kids = [spawn("rekey", "p", "40"), spawn("saves", "q", "0")]
    for tag in ("p", "q"): wait_for(T / f"xl-ready-{tag}")
    GO.write_text("1"); outs = []
    for k in kids:
        try: out, _ = k.communicate(timeout=120)
        except subprocess.TimeoutExpired: k.kill(); out, _ = k.communicate(); out += "\n(timed out)"
        outs.append((k.returncode, out))
    six = json.loads((T / "store/a/6.json").read_text()); xl = six.get("xl") or {}; after = six["metadata"].get("after") or []
    moved = (re.search(r"moved ((?:\S+ ?)+)", outs[0][1]) or [None, ""])[1].split()
    qn = int(m.group(1)) if (m := re.search(r"rounds (\d+)", outs[1][1])) else 0
    check("25 re-key race: both processes ran to the end (40 re-keys, the saves of the other all the while)", all(rc == 0 for rc, _ in outs) and len(moved) == 40, outs)
    check("25 re-key race: every `after` entry the re-keys rewrote is the new id (40 of 40: none still names an old id, none lost to the saves)", sorted(after) == sorted(moved) and len(after) == 40, (len(after), after[:5], moved[:5]))
    check("25 re-key race: every save the other process made while the re-keys read and rewrote the list is in the file (the re-key took the item lock round each rewrite)", qn >= 3 and all(f"q{i}" in xl for i in range(qn)), (qn, len(xl), outs))
    for i in range(40):
        for f in (T / "store/a" / f"{200 + i}.json", T / "store/g" / f"{900 + i}.json"): f.unlink(missing_ok=True)

    # ---- 26. a call of a function whose save is the caller's to lock is itself under the item lock
    CALLERS_UNLOCKED = {     # (file, function) that calls such a function with no `with ITEM_LOCK` of its own: why it still runs under the lock
        ("service/agent_names.py", "_auto_name"): "stores the naming `_name_on_write` hands out; that one is run by update_unlocked, which update_item calls under the item lock",
        ("service/answer.py", "_answer_deliver"): "its one caller, `_answer`, holds the item lock",
        ("service/released.py", "released_item"): "a wrapper: its callers (released, sweep_released) take the item lock round their loop",
        ("service/agent_names.py", "_name_on_write"): "its caller, update_unlocked (through the hooks), runs under update_item's item lock",
    }
    OWED_IN = {("github/ghsync.py", "_move", "take")}      # a name too common to follow everywhere: followed where the re-key calls it
    owed = {fn for (rel, fn) in LOCKED_BY_CALLER if fn not in ("save", "create_item", "take")} | {fn for (_r, fn) in CALLERS_UNLOCKED}
    calls_unlocked = []
    for path in sorted((pathlib.Path(STACK) / "stackshot").rglob("*.py")):
        src = path.read_text(encoding="utf-8")
        try: tree = ast.parse(src)
        except SyntaxError: continue
        rel = str(path.relative_to(pathlib.Path(STACK) / "stackshot"))
        def walk2(node, withs, func):
            for ch in ast.iter_child_nodes(node):
                w, f = withs, func
                if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef)): f, w = ch.name, ()
                if isinstance(ch, ast.With): w = withs + tuple(ast.get_source_segment(src, i.context_expr) or "" for i in ch.items)
                if isinstance(ch, ast.Call):
                    n = (ast.get_source_segment(src, ch.func) or "").split(".")[-1]
                    if (n in owed or (rel, f, n) in OWED_IN) and f != n and not any(is_item_lock(t) for t in w): calls_unlocked.append((rel, f, n))
                walk2(ch, w, f)
        walk2(tree, (), None)
    unlisted = sorted({(r, f) for r, f, _n in calls_unlocked if (r, f) not in CALLERS_UNLOCKED and (r, f) not in LOCKED_BY_CALLER and (r, f) not in UNLOCKED_FOLLOW_UP})
    check("26 callers: every call of a function whose save the caller must lock (the LOCKED_BY_CALLER list) is itself under `with ITEM_LOCK`, or is in a listed function (a dropped lock in `_name_on_handover` fails here)", not unlisted, unlisted)
    check("26 callers: the list of listed callers has no stale entry", all((r, f) in {(a, b) for a, b, _ in calls_unlocked} for (r, f) in CALLERS_UNLOCKED), sorted(CALLERS_UNLOCKED))

    # ---- 27. each of the six locks that had only a type check: the real function blocks while another process holds the lock, and completes with its effect when it is let go
    def blocks_then_runs(name, run, effect, tag):
        pr = holder(name, tag); out = {}
        def go():
            try: out["r"] = run()
            except Exception as e: out["err"] = f"{type(e).__name__}: {e}"
        th = threading.Thread(target=go, daemon=True); th.start(); time.sleep(0.5)
        waiting = th.is_alive() and not effect()
        let_go(pr, tag); th.join(20)
        return waiting, (not th.is_alive()) and bool(effect()), out
    def raw(p):
        try: return json.loads(pathlib.Path(p).read_text(encoding="utf-8"))
        except (OSError, ValueError): return {}
    from stackshot.service import landed as landed_svc
    landed_svc.forget("a1")
    ok = blocks_then_runs("landed", lambda: landed_svc.record("a1", int(time.time()), "done", "x", "projects/none"), lambda: "a1" in landed_svc._load(), "j1")
    check("27 landed: `landed.record` waits for another process's hold of the landed lock, then records the close", ok[0] and ok[1] and "err" not in ok[2], ok)
    landed_svc.forget("a1")
    page_debts._owed_path().write_text(json.dumps({"projects/none": {"o": {"ts": 5.0, "retired_only": True}}}), encoding="utf-8")
    ok = blocks_then_runs("ledger", lambda: page_debts._owed_settle(), lambda: not raw(page_debts._owed_path()).get("projects/none"), "j2")
    check("27 ledger: the settle of the page-debt ledger waits for another process's hold of the ledger lock, then strips the entry that owed nothing", ok[0] and ok[1] and "err" not in ok[2], ok)
    answers._answers_save({"a1": {"ts": time.time(), "owner": "", "project": "projects/none", "told": [answer_svc._session_id("sx")], "words": "x"}})
    ok = blocks_then_runs("answers", lambda: answer_svc._answer_ack("a1", "sx"), lambda: "a1" not in raw(answers._answers_path()), "j3")
    check("27 answers: a session's write settling a pending answer waits for another process's hold of the answers lock, then removes the answer", ok[0] and ok[1] and "err" not in ok[2], ok)
    answers._answers_save({})
    race_reset(); ma_p = pathlib.Path(ma_mod._file()); ma_p.write_text(json.dumps({"projects/none": [{"machine": "mx", "items": ["a2"], "added": 1.0, "by": "x"}]}), encoding="utf-8")
    ok = blocks_then_runs("machine-anchors", lambda: evw_svc.machine_anchor_poll(time.time(), set()), lambda: not raw(ma_p), "j4")
    check("27 machine anchors: the machine anchors' pass waits for another process's hold of their lock, then drops the entry whose item is closed", ok[0] and ok[1] and "err" not in ok[2], ok)
    ma_p.write_text("{}", encoding="utf-8")
    site_item(hold=True, wake="2000-01-01")
    ok = blocks_then_runs("wake", lambda: wakes.wake_pass(), lambda: "hold" not in raw(T / "store/a/1.json").get("metadata", {}), "j5")
    check("27 wake: the wake pass waits for another process's hold of the wake lock, then releases the parked item", ok[0] and ok[1] and "err" not in ok[2], ok)
    (T / "state/stall.json").unlink(missing_ok=True)
    ok = blocks_then_runs("stall", lambda: stall.stall_since(1234.0), lambda: raw(stall.stall_path()).get(stall.STALL_PASS, {}).get("since") == 1234.0, "j6")
    check("27 stall: the stall pass's first-run mark waits for another process's hold of the stall lock, then writes the mark", ok[0] and ok[1] and "err" not in ok[2], ok)
finally:
    for k in KIDS:
        if k.poll() is None: k.kill()

print(f"xlock: {len(ran)} checks, {len(fails)} failed")
sys.exit(1 if fails else 0)
