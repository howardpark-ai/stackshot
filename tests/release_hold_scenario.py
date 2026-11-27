"""Scenario test for release.sh hold: holding every release's deploy for a short, named time.
No network, no real gh, git, systemd or deploy: release.sh is copied into a temp dir beside stubs (tests/_release_harness.py), whose clock moves with the sleeps release.sh asks for, so a
hold's minutes pass at once.

The command: set, --status, --end; a second holder is refused and the same one replaces its own; what it refuses; the end of a hold, a file that does not read as one and one that names a time far off
(120 minutes at most, counted from the file's last change); a deploy under way is waited for. A release: it waits before its deploy without the deploy lock, says who holds and why once, and goes on when
the hold ends by itself, by --end or after a replacement; a group release and a rollback wait the same way. The queue's list and the commands that start a release say that releases are held.

    tests/run-suite release_hold        → exit 0 / 1"""
import fcntl, json, os, pathlib, re, subprocess, sys, time
import _scratch
from _release_harness import BASE, ENV0, GOOD, MERGE, at, check, dirs, enqueues, fast, finish, lock_free, merges, plain_merges, scenario

os.environ["RELEASE_SUITE_PAR"] = "1"          # nothing here is started ahead: several runs continue one folder
HOOKS = pathlib.Path(_scratch.mkdtemp(prefix="releasetest-holdhook-")); dirs.append(HOOKS)
# a sleep that writes down whether the deploy lock was free while the release slept, and runs the scenario's RT_HOOK (n = the number of sleeps so far)
(HOOKS / "sleep").write_text('#!/bin/sh\necho "$*" >> "$RT_DIR/sleep.log"\nmkdir -p "$RT_DIR/releases"\n'
                             'if flock -n "$RT_DIR/releases/deploy.lock" true; then echo "free $*"; else echo "held $*"; fi >> "$RT_DIR/sleep.lock"\n'
                             'n=$(wc -l < "$RT_DIR/sleep.log")\n[ -z "${RT_HOOK:-}" ] || eval "$RT_HOOK"\n')
(HOOKS / "sleep").chmod(0o755)

def folder(name):
    d = pathlib.Path(_scratch.mkdtemp(prefix=f"releasetest-{name}-")); (d / "releases").mkdir(); return {"dir": d}
def cmd(*args, at_=None, **kw):
    """`release.sh hold <args>` in a folder (a new one, or `at_`: a run or folder before)"""
    return scenario("holdcmd", raw=["hold", *args], reuse=at_ or folder("holdcmd"), **kw)
def holdfile(until, by="tester", why="moving the board"): return f"until={until}\nby={by}\nwhy={why}\n"
def put(where, text, age=0):
    p = where["dir"] / "releases/hold"; p.write_text(text)
    if age: os.utime(p, (time.time() - age,) * 2)
    return p
def stamp(t): return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))
def fields(p): return dict(l.split("=", 1) for l in p.read_text().splitlines())
def hfile(s): return s["dir"] / "releases/hold"
def left(s): return sorted(p.name for p in (s["dir"] / "releases").glob("hold*"))
now = lambda: int(time.time())
SET = ("--minutes", "30", "--by", "tester", "--why", "moving the board")

# ---------------------------------------------------------------- the command
s = cmd("--status")
check("status with no hold: says so, exit 0, writes nothing", s["rc"] == 0 and s["out"] == "no hold on releases\n" and left(s) == [], (s["rc"], s["out"], left(s)))
e = cmd("--end", at_=s)
check("end with no hold: says so, exit 0", e["rc"] == 0 and e["out"] == "no hold on releases\n", (e["rc"], e["out"]))
t0 = now(); s = cmd(*SET); t1 = now()
f = fields(hfile(s)) if hfile(s).exists() else {}
check("set: exit 0, says who, until when, the minutes left and why", s["rc"] == 0 and re.fullmatch(r"releases are held by tester until \d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ \(30 min left\): moving the board\. "
      r"No release deploys until then; release\.sh hold --end lets them go on sooner\n", s["out"]), (s["rc"], s["out"]))
check("set: the file holds the end (30 minutes on), the holder and the reason, and nothing else is left beside it",
      list(f) == ["until", "by", "why"] and t0 + 1800 - 2 <= int(f["until"]) <= t1 + 1800 + 2 and f["by"] == "tester" and f["why"] == "moving the board" and left(s) == ["hold"], (f, t0, t1, left(s)))
check("set: the deploy lock is free afterwards", lock_free(s))
st = cmd("--status", at_=s)
check("status: the hold in one line", st["rc"] == 0 and st["out"] == f"releases are held by tester until {stamp(int(f['until']))} (30 min left): moving the board\n", st["out"])
before = hfile(s).read_text()
o = cmd("--minutes", "5", "--by", "someone else", "--why", "another thing", at_=s)
check("another holder is refused while the hold stands: exit 1, names the holder, the file unchanged",
      o["rc"] == 1 and "not held: releases are already held by tester until" in o["out"] and "(release.sh hold --end ends it)" in o["out"] and hfile(s).read_text() == before and lock_free(o), (o["rc"], o["out"]))
r = cmd("--minutes", "10", "--by", "tester", "--why", "the second restart", at_=s)
f2 = fields(hfile(s))
check("the same holder replaces its own hold: a new end and reason, said", r["rc"] == 0 and "(your earlier hold is replaced)" in r["out"] and f2["why"] == "the second restart" and now() + 590 <= int(f2["until"]) <= now() + 602, (r["out"], f2))
e = cmd("--end", at_=s)
check("end: says whose hold ended and removes it", e["rc"] == 0 and e["out"] == f"hold ended: it was held by tester until {stamp(int(f2['until']))}: the second restart\n" and left(s) == [], (e["out"], left(s)))
check("...after which status says there is none", cmd("--status", at_=s)["out"] == "no hold on releases\n")
w = folder("holdrefuse")
for label, args in (("nothing", ()), ("no --why", ("--minutes", "5", "--by", "a")), ("no --by", ("--minutes", "5", "--why", "w")), ("no --minutes", ("--by", "a", "--why", "w")),
                    ("0 minutes", ("--minutes", "0", "--by", "a", "--why", "w")), ("121 minutes", ("--minutes", "121", "--by", "a", "--why", "w")), ("1000 minutes", ("--minutes", "1000", "--by", "a", "--why", "w")),
                    ("a leading zero", ("--minutes", "05", "--by", "a", "--why", "w")), ("half a minute", ("--minutes", "5.5", "--by", "a", "--why", "w")), ("negative minutes", ("--minutes", "-1", "--by", "a", "--why", "w")),
                    ("words for minutes", ("--minutes", "ten", "--by", "a", "--why", "w")), ("a blank --by", ("--minutes", "5", "--by", "   ", "--why", "w")), ("an empty --why", ("--minutes", "5", "--by", "a", "--why", "")),
                    ("a --by of 81 characters", ("--minutes", "5", "--by", "b" * 81, "--why", "w")), ("a --why of 201 characters", ("--minutes", "5", "--by", "a", "--why", "w" * 201)),
                    ("a second line in --why", ("--minutes", "5", "--by", "a", "--why", "w\nuntil=9999999999")), ("a tab in --by", ("--minutes", "5", "--by", "a\tb", "--why", "w")),
                    ("an option with no value", ("--minutes",)), ("an unknown option", ("--forever", "1")), ("--status with more", ("--status", "x")), ("--end with more", ("--end", "now"))):
    x = cmd(*args, at_=w)
    check(f"refused, exit 2, nothing written: {label}", x["rc"] == 2 and ("usage: release.sh hold" in x["out"] or "release.sh hold: " in x["out"]) and left(x) == [], (x["rc"], x["out"], left(x)))
x = cmd("--minutes", "120", "--by", "b" * 80, "--why", "w" * 200)
check("the longest hold, holder and reason are taken", x["rc"] == 0 and fields(hfile(x))["by"] == "b" * 80 and len(fields(hfile(x))["why"]) == 200 and "(120 min left)" in x["out"], (x["rc"], x["out"]))
x = cmd("--minutes", "1", "--by", "a", "--why", "w")
check("one minute is taken", x["rc"] == 0 and "(1 min left)" in x["out"], x["out"])

# a hold past its end
w = folder("holdold"); ended = now() - 60; put(w, holdfile(ended))
x = cmd("--status", at_=w)
check("status after the end: no hold, and whose ended when", x["rc"] == 0 and x["out"] == f"no hold on releases: the one by tester ended at {stamp(ended)} (moving the board)\n" and left(x) == ["hold"], x["out"])
x = cmd("--minutes", "5", "--by", "someone else", "--why", "w", at_=w)
check("an ended hold does not stand in another holder's way", x["rc"] == 0 and "replaced" not in x["out"] and fields(hfile(x))["by"] == "someone else", (x["rc"], x["out"]))
put(w, holdfile(ended)); x = cmd("--end", at_=w)
check("end after the end: says so and removes the file", x["rc"] == 0 and x["out"] == f"no hold on releases: the one by tester had ended at {stamp(ended)}; its file is removed\n" and left(x) == [], x["out"])
# a file that does not read as a hold holds, for 120 minutes from its last change
for label, text in (("junk", "junk\n"), ("empty", ""), ("no reason", f"until={now() + 600}\nby=tester\n"), ("no holder", f"until={now() + 600}\nwhy=w\n"), ("an end that is no number", "until=soon\nby=tester\nwhy=w\n")):
    w = folder("holdjunk"); put(w, text)
    x = cmd("--status", at_=w)
    check(f"a file that does not read as a hold ({label}) holds, and says so", x["rc"] == 0 and x["out"].startswith("releases are held by unknown until ") and "(120 min left)" in x["out"] and "does not read as a hold" in x["out"], x["out"])
x = cmd(*SET, at_=w)
check("...nobody takes it over", x["rc"] == 1 and "held by unknown" in x["out"], (x["rc"], x["out"]))
x = cmd("--end", at_=w)
check("...and --end removes it", x["rc"] == 0 and x["out"].startswith("hold ended: it was held by unknown") and left(x) == [], (x["out"], left(x)))
put(w, "junk\n", age=3 * 3600); x = cmd("--status", at_=w)
check("such a file left from 3 hours ago holds no longer", x["out"].startswith("no hold on releases: the one by unknown ended at "), x["out"])
w = folder("holdfar"); put(w, holdfile(now() + 10 * 86400))
x = cmd("--status", at_=w)
check("an end days off counts as 120 minutes at most", "(120 min left)" in x["out"], x["out"])
put(w, holdfile(now() + 10 * 86400), age=3 * 3600); x = cmd("--status", at_=w)
check("...counted from the file's last change, so an old file with such an end holds no longer", x["out"].startswith("no hold on releases: the one by tester ended at "), x["out"])
w = folder("holddir"); (w["dir"] / "releases/hold").mkdir()
x = cmd("--end", at_=w)
check("a hold that cannot be removed is not reported as ended: exit 1, says until when it stands", x["rc"] == 1 and "the hold could not be ended" in x["out"] and "it stands until " in x["out"] and "hold ended" not in x["out"], (x["rc"], x["out"]))
x = cmd("--status", at_=w)
check("...and a folder at that path holds like any file that does not read, said", x["rc"] == 0 and x["out"].startswith("releases are held by unknown until ") and "does not read as a hold" in x["out"], (x["rc"], x["out"]))
x = cmd(*SET, at_=w)
check("...and cannot be taken over", x["rc"] == 1 and "held by unknown" in x["out"] and (w["dir"] / "releases/hold").is_dir() and not list((w["dir"] / "releases/hold").iterdir()), (x["rc"], x["out"]))
w = folder("holdclosed"); put(w, holdfile(now() + 600)).chmod(0)
if os.geteuid() != 0:
    x = cmd("--status", at_=w)
    check("a hold file nobody may read holds, said", x["rc"] == 0 and x["out"].startswith("releases are held by unknown until "), (x["rc"], x["out"]))

# the deploy under way is waited for
x = cmd(*SET, hold=True, extra={"DEPLOY_LOCK_WAIT": "1"})
check("a deploy that holds the lock past the wait: not held, exit 1, nothing written", x["rc"] == 1 and "a deploy is under way: waiting for it, up to 1 s" in x["out"] and "not held: another deploy held the lock" in x["out"] and left(x) == [], (x["rc"], x["out"], left(x)))
b = cmd("--status"); d = b["dir"]
env = {**ENV0, "PATH": f"{d}/bin:" + os.environ.get("PATH", ""), "RT_DIR": str(d), "XDG_CONFIG_HOME": str(d / "xdg")}
lk = open(d / "releases/deploy.lock", "a"); fcntl.flock(lk, fcntl.LOCK_EX)
out = d / "hold.out"; p = None
try:
    with open(out, "w") as o: p = subprocess.Popen(["bash", str(d / "box/release.sh"), "hold", *SET], env=env, stdout=o, stderr=o)
    end = time.time() + 60
    while time.time() < end and "a deploy is under way" not in out.read_text() and p.poll() is None: time.sleep(0.05)
    time.sleep(0.5)
    check("while a deploy is under way the command waits and holds nothing yet", p.poll() is None and "a deploy is under way" in out.read_text() and not (d / "releases/hold").exists(), (p.poll(), out.read_text()))
    fcntl.flock(lk, fcntl.LOCK_UN)
    rc = p.wait(60)
    check("...and takes the hold once the deploy is over", rc == 0 and (d / "releases/hold").exists() and "releases are held by tester" in out.read_text(), (rc, out.read_text()))
finally:
    lk.close()
    if p is not None and p.poll() is None: p.kill(); p.wait(20)

# ---------------------------------------------------------------- a release under a hold
def held_release(name, hook="", files=None, extra=None, **kw):
    w = folder(name)
    kw.setdefault("merge", "ok")
    s = fast(name, reuse=w, hook=hook, files=files or {}, extra={"PATH": f"{HOOKS}:{w['dir']}/bin:" + os.environ.get("PATH", ""), **(extra or {})}, **kw)
    s["slept"] = (w["dir"] / "sleep.lock").read_text().splitlines() if (w["dir"] / "sleep.lock").exists() else []
    return s
def waits(s): return [m for m in s["msgs"] if "waits before its deploy" in m]
def tens(s): return [x for x in s["sleeps"] if x == "10"]

s = held_release("hold-none")
check("no hold: the release deploys with no word of one", s["rc"] == 0 and s["deploys"] == [MERGE] and not tens(s) and not any(w in s["log"] + s["msg"] for w in ("releases are held", "hold on releases", "release.sh hold", "Waiting before the deploy")), (s["rc"], s["sleeps"], s["log"]))
t0 = now(); s = held_release("hold-wait", files={"releases/hold": holdfile(t0 + 300, why="after the FAILED run, done: step 2")})
check("a held release deploys once the hold has ended, and exits 0", s["rc"] == 0 and s["deploys"] == [MERGE], (s["rc"], s["deploys"], s["log"][-900:]))
check("...it waited the hold's five minutes, a look every 10 s", 27 <= len(tens(s)) <= 31, len(tens(s)))
check("...the deploy lock was free at every one of those waits", s["slept"] and all(l == "free 10" for l in s["slept"] if l.endswith(" 10")), s["slept"][:5])
check("...the log says it at the start, then that it waits, then that the hold ended, and only then takes the lock and deploys",
      at(s["log"], "note: releases are held by tester until", "releases are held by tester until", "Waiting before the deploy; release.sh hold --end lets it go on", "the hold on releases by tester ended at", "going on", "deploy lock taken")
      and s["log"].count("deploy lock taken") == 1 and s["log"].count("Waiting before the deploy") == 1, s["log"])
check("...one message says that it waits, who holds and why", len(waits(s)) == 1 and "[release] PR #23 waits before its deploy: releases are held by tester until" in waits(s)[0] and "release.sh hold --end lets it go on" in waits(s)[0], s["msgs"])
check("...the PR was merged before the wait", s["msgs"] and s["msgs"][0] == waits(s)[0] and (plain_merges(s) or enqueues(s)), (s["msgs"], merges(s)))
check("...the report of the deploy follows, and the ended hold's file is gone", any("merged and deployed" in m for m in s["msgs"]) and not hfile(s).exists() and lock_free(s), (s["msgs"], left(s)))
held_lines = [l for l in s["log"].splitlines() if "held by tester" in l or "on releases by tester" in l] + waits(s)
check("...the holder's words never read as a release's result in the log or the message", held_lines and not any(" FAILED" in l or " done:" in l for l in held_lines) and any("failed run, done step 2" in l for l in held_lines), held_lines)

END_AT_3 = '[ "$n" != 3 ] || bash "$RT_DIR/box/release.sh" hold --end >> "$RT_DIR/hold_end.out" 2>&1'
s = held_release("hold-ended", hook=END_AT_3, files={"releases/hold": holdfile(now() + 3600)})
check("hold --end lets a waiting release go on at its next look", s["rc"] == 0 and s["deploys"] == [MERGE] and s["sleeps"] == ["10"] * 3 and "hold ended: it was held by tester" in (s["dir"] / "hold_end.out").read_text()
      and "going on" not in s["log"] and len(waits(s)) == 1 and not hfile(s).exists(), (s["rc"], s["sleeps"], s["log"][-900:]))
s = held_release("hold-every", hook=END_AT_3, files={"releases/hold": holdfile(now() + 3600)}, extra={"RELEASE_POLL_HOLD": "30"})
check("the time between two looks is RELEASE_POLL_HOLD", s["rc"] == 0 and s["sleeps"] == ["30"] * 3, s["sleeps"])
s = held_release("hold-replaced", hook='[ "$n" != 2 ] || bash "$RT_DIR/box/release.sh" hold --minutes 2 --by tester --why "the second restart" >> "$RT_DIR/hold_again.out" 2>&1',
                 files={"releases/hold": holdfile(now() + 3600)})
check("a hold replaced while a release waits: it waits for the new end, and says the new one in a second message",
      s["rc"] == 0 and s["deploys"] == [MERGE] and 12 <= len(tens(s)) <= 16 and len(waits(s)) == 2 and "the second restart" in waits(s)[1] and "moving the board" in waits(s)[0]
      and "the hold on releases by tester ended at" in s["log"], (s["rc"], len(tens(s)), s["msgs"], s["log"][-900:]))
s = held_release("hold-past", files={"releases/hold": holdfile(now() - 5)})
check("a hold that has ended does not stop a release: said, its file removed", s["rc"] == 0 and s["deploys"] == [MERGE] and not tens(s) and not waits(s) and "the hold on releases by tester ended at" in s["log"] and not hfile(s).exists(), (s["rc"], s["sleeps"], s["log"][-600:]))
s = held_release("hold-junk", hook=END_AT_3, files={"releases/hold": "junk\n"})
check("a file that does not read as a hold stops a release too, until --end", s["rc"] == 0 and s["sleeps"] == ["10"] * 3 and len(waits(s)) == 1 and "held by unknown" in waits(s)[0] and "does not read as a hold" in waits(s)[0], (s["sleeps"], s["msgs"]))

# a rollback waits
HOLD_AFTER_DEPLOY = ('[ ! -f "$RT_DIR/deployed" ] || [ -e "$RT_DIR/held-once" ] || { : > "$RT_DIR/held-once"; '
                     'printf "until=%s\\nby=tester\\nwhy=moving the board\\n" "$(( $(date +%s) + 60 ))" > "$RT_DIR/releases/hold"; }')
s = held_release("hold-rollback", hook=HOLD_AFTER_DEPLOY, main="pending,fail", heads=f"{BASE},{BASE},{MERGE}")
check("a rollback waits for the hold too, and runs when it has ended", s["rc"] == 1 and s["deploys"] == [MERGE, f"rollback {GOOD}"] and len(waits(s)) == 1 and "PR #23" in waits(s)[0]
      and at(s["log"], "deploy lock taken", "Waiting before the deploy", "going on", "deploy lock taken") and "FAILED at main's tests: rolled back to 600d000" in s["msgs"][-1]
      and 5 <= len(tens(s)) <= 7 and s["slept"] and all(l == "free 10" for l in s["slept"] if l.endswith(" 10")), (s["rc"], s["deploys"], s["sleeps"], s["msgs"], s["log"][-900:]))

# a group release waits
M1 = "a1a1a1a" + "0" * 33; M2 = "b2b2b2b" + "0" * 33
ON = 'mode = "on"\ndeploy_lock = "@DIR@/releases/deploy.lock"\n'
s = held_release("hold-group", raw=["--run-group", "23", "25"], mqhost=ON, mq="off", units="", history=",".join([GOOD, BASE, M1, M2]), live=BASE, live_after=M2, tip=M2, fullshas=f"{M1},{M2}",
                 runs=json.dumps([{"databaseId": 7, "headSha": M2}]), mq_prs=f"23=merged@{M1[:7]},25=merged@{M2[:7]}",
                 files={"releases/queue": "23\n25\n", "releases/queue.started": "23\n", "releases/hold": holdfile(now() + 120)})
glog = (s["dir"] / "releases/group-23.log").read_text() if (s["dir"] / "releases/group-23.log").exists() else ""
check("a group release waits for the hold before its one deploy", s["rc"] == 0 and s["deploys"] == [M2] and 9 <= len(tens(s)) <= 13 and at(glog, "note: releases are held by tester", "Waiting before the deploy", "going on", "deploy lock taken"),
      (s["rc"], s["deploys"], len(tens(s)), glog[-900:], s["out"][-600:]))
check("...and its one message names the group", len(waits(s)) == 1 and "[release] the group release of PRs #23" in waits(s)[0] and "#25" in waits(s)[0], s["msgs"])

# ---------------------------------------------------------------- where a hold is seen
def raw(name, args, text=None, **kw):
    w = folder(name)
    if text is not None: put(w, text)
    return scenario(name, raw=args, reuse=w, units="", **kw)
until = now() + 1800
s = raw("list-held", ["queue", "--list"], holdfile(until))
check("queue --list shows the hold and how to end it", s["rc"] == 0 and f"on hold: releases are held by tester until {stamp(until)} (30 min left): moving the board (release.sh hold --end)" in s["out"], s["out"])
s = raw("list-past", ["queue", "--list"], holdfile(now() - 60))
check("queue --list: an ended hold is said to be no hold now", "no hold now: the one by tester ended at " in s["out"] and "on hold" not in s["out"], s["out"])
s = raw("list-none", ["queue", "--list"])
check("queue --list with no hold says nothing of one", s["rc"] == 0 and "hold" not in s["out"], s["out"])
NOTE = "note: releases are held by tester until "
for label, args in (("release.sh <pr>", ["23"]), ("release.sh queue <pr>", ["queue", "23"]), ("release.sh --group", ["--group", "23", "25"])):
    kw = {"mqhost": ON} if "--group" in args else {}
    s = raw("start-held", args, holdfile(now() + 1800), **kw)
    check(f"{label} under a hold starts the release and says it will wait", s["rc"] == 0 and s["started"] == ["23"] and NOTE in s["out"] and "A release merges its PR and then waits before its deploy" in s["out"] and hfile(s).exists(), (s["rc"], s["started"], s["out"]))
    s = raw("start-free", args, **kw)
    check(f"{label} with no hold: no note", s["rc"] == 0 and s["started"] == ["23"] and "note:" not in s["out"], (s["rc"], s["out"]))
    s = raw("start-past", args, holdfile(now() - 60), **kw)
    check(f"{label} after a hold's end: no note", s["rc"] == 0 and "note:" not in s["out"], (s["rc"], s["out"]))
s = raw("usage", ["nonsense"])
check("a wrong call's usage names the hold commands", s["rc"] == 2 and "hold --minutes N --by NAME --why TEXT | hold --status | hold --end" in s["out"], s["out"][:900])
s = raw("help", ["--help"])
check("--help explains the hold", "./release.sh hold --minutes N --by NAME --why TEXT" in s["out"] and "./release.sh hold --end" in s["out"], s["out"][:600])

finish()
