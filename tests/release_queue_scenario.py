"""Scenario test for release.sh --run, second half: what comes after the merge, the deploy lock, main's tests, the fast path and the update of a branch behind main
(those are release_scenario.py). Same setup: no network, no real gh, git or deploy, release.sh copied into a temp dir beside stubs (tests/_release_harness.py).

Ride-along (section 13h, a release that took the old path left the live checkout behind main): a merge release.sh made on a passing PR check and
an up-to-date head (2c, main's tip then exactly the merge of the tip and the head) is recorded in <state>/releases/fast-ok.json, whether that release deployed at the merge or took
the old path; fast_gate (a) counts the live checkout as at the tip when every commit between it and main's tip is a ledger merge or docs-only. Two releases back to back: the second
deploys on the fast path although the first's merge is not deployed and its main run has not finished; a commit that is neither in the ledger nor docs-only blocks it (the old path, the
reason in the log); a merge of a branch that was not up to date is never recorded; a ledger that cannot be read as one is left alone and (a) counts docs-only merges alone, as before; a
rollback takes the failing merge and every merge it takes out of the ledger (the whole file goes when they cannot be taken out), and so does an old-path release whose main run fails.
An old-path release whose own run fails while its merge is LIVE (a release rode along and deployed on top) takes the fast deploy's rollback and reports "LIVE via ride-along, rolled back".
Every write prunes the entries already deployed (ancestors of the live HEAD) or at or before the last-good commit; (a) counts only entries that descend from the live checkout. The ledger's
file rules (the shape check: 40 or 64 hex keys, integer epoch and pr; 30 days; the 200-entry cap; the prune list) are run on release.sh's own code, and docs_only_between with a ledger on a
throwaway real repository (a side-branch merge, a direct push, a ledger merge, a docs commit). WAIT_MAIN defaults to 90 min (longer than main's full run).

Covering runs (section 14: three PRs merged close together; main cancelled two runs and every release waited for the tip's
queued run until it gave up): a release whose merge commit is M is satisfied by a passed main run on any commit that contains M (git merge-base
--is-ancestor), deployed at the newest such passed commit; a cancelled run is skipped; a run still queued or going is waited for; a failed run on a commit
that contains M fails the release, but one that comes after a pass on M or between M and it does not (the oldest failed commit decides, and the log names its
run); WAIT_MAIN counts from when a covering run starts, CAP_MAIN from the merge, and the last log line names both; the same rule for the fast path's watch
(main_green post): a cancelled run with a later passing one is not unknown, a cancelled run alone is unknown after the cap, a failing later commit with no pass
before it rolls back.

The CI-run poller (section 15): while it waits for the PR's checks and for main's run, release.sh first asks `salamander ci-runs <repo> --sha <sha> --max-age 120` (a fake
`salamander` on PATH here, never the host's). A fresh answer that lists a run of the commit still going (in progress or queued, or one run of several) makes the cycle wait with no
GitHub call at all (no `gh pr checks`, no git fetch, no `gh run list`/`view`); the cap and WAIT_MAIN still end the wait. A run listed as completed (whatever its conclusion), no run of the sha
listed, exit 3, 4 or 5, output that is not JSON, or no salamander on PATH: the GitHub read, which alone passes or fails the release (never the poller). Main's wait counts only push runs.

The merge queue, shadow (section 17): the host file (the scenario's own XDG_CONFIG_HOME, never the real ~/.config) says off | shadow | on. No file, off, a file with no mode, and a file that does not
read leave the release exactly as it was (same sleeps, gh calls and report, no `salamander mq` call, no unit, nothing about a queue in the log; a file that does not read adds one log line). Shadow runs
`salamander mq add <pr> --repo <repo>` before the wait for the PR's checks (a fake `salamander` on PATH), and when the release ends, whichever way, a unit `stackshot-mq-shadow-<pr>-<run>` (the run is the epoch and pid, so a rerun of the PR has its own unit and its own record; a fake systemd-run runs it at once) asks
`salamander mq wait` and appends ONE comparison line to the release log: agree / DISAGREE / no comparison, for a merged PR, a PR refused at its checks, one merged and then failed by main's run, and one that stopped at a
lock; a queue with no verdict, a queue error (a `salamander mq:` message even at exit 1), a deploy that failed after the merge and a PR the old path merged before the queue read it are no comparison; a rerun of a PR gets its own unit and record; the words ` FAILED` and ` done:` are softened in the line. A missing salamander, an `mq add` that fails or hangs (cut at RELEASE_MQ_ADD_TIMEOUT) and a unit that
does not start are one log line each and change nothing in the release or its exit status. Mode on is section 18 below.

    tests/run-suite release_queue        → exit 0 / 1"""
import fcntl, json, os, pathlib, re, shutil, subprocess, sys, tempfile, threading, time
import _scratch
from _release_harness import *
# ---- 13h. the ride-along ledger (main's full run never blocks a release; one release on the old path left the live checkout behind main, and every later release failed (a) too and waited for a full run of main). A merge release.sh made on a passing PR check
# and an up-to-date head goes into <state>/releases/fast-ok.json; (a) counts the live checkout as at the tip when everything between it and the tip is such a merge or docs-only.
# The git stub's history is linear, oldest first (HIST_R); RT_LIVE (live=) is the live checkout in it, so "an ancestor of HEAD" means "at or before live".
def LEDG(*shas): return json.dumps({"v": 1, "merges": {x: {"pr": 1, "epoch": int(time.time())} for x in shas}})
def led(s):   # the ledger's merges after a run, None when the file is not there or not a ledger
    try: return set(json.loads(s["ledger"])["merges"])
    except Exception: return None
RIDER = "7ada0000000000000000000000000000000000d1"; RIDER2 = "7ada0000000000000000000000000000000000d2"; OTHER = "0a1d000000000000000000000000000000000001"
STRAY = "57a40000000000000000000000000000000000a4"; AHEAD = "a4ead000000000000000000000000000000000a1"
HIST_R = ",".join([OTHER, GOOD, RIDER, RIDER2, STRAY, BASE, HEADSHA, MERGE, LATER, NEWER, AHEAD])
OLDORDER = ["run-view", f"deploy:{MERGE}", "client:message"]   # the old path: main's run is read before the deploy
MD_FM = dict(diff=MD, fm="fake")
def ride(name, **kw): return fast(name, **{**dict(merge="ok", heads=f"{GOOD},{BASE}", live=GOOD, history=HIST_R), **kw})

s = ride("ride-seeded", docs=RIDER, ledger=LEDG(RIDER, OTHER))
check("ride-along: the live checkout is behind main's tip only by a merge in the ledger: (a) holds, the fast path (deployed at the merge, main's run after), said in the log; no docs-merge.sh needed",
      s["rc"] == 0 and s["order"][:2] == [f"deploy:{MERGE}", "client:message"] and "only by 1 merge(s) release.sh made on a passing PR check and an up-to-date head" in s["log"]
      and "(a) the live checkout" not in s["log"] and "main's full run follows" in s["msgs"][0], (s["order"], s["log"], s["out"]))
check("ride-along: the release's own merge joins the ledger (atomic: only the ledger and its lock file beside it); the entry at or before the last good commit is pruned on the write; the ride-along stays",
      led(s) == {RIDER, MERGE} and s["ledger_files"] == ["fast-ok.json", "fast-ok.json.lock"] and f"recorded the merge {MERGE[:7]} in the fast-ok ledger" in s["log"], (s["ledger"], s["ledger_files"], s["log"]))
s = ride("ride-seeded-two", docs=f"{RIDER},{RIDER2}", ledger=LEDG(RIDER2, RIDER))
check("ride-along: two ledger merges between the live checkout and the tip, in the ledger in any order: both ride along", s["rc"] == 0 and s["order"][0] == f"deploy:{MERGE}" and "only by 2 merge(s)" in s["log"], (s["order"], s["log"]))
s = ride("ride-pruned-live", docs=STRAY, ledger=LEDG(RIDER, STRAY), heads=f"{RIDER},{BASE}", live=RIDER)
check("pruning on a write: an entry that is an ancestor of the live HEAD (deployed already) goes, one ahead of it stays", led(s) == {STRAY, MERGE}, (s["ledger"], s["log"]))
s = ride("ride-nondescendant", docs=OTHER, ledger=LEDG(OTHER))
check("(a) ignores a ledger entry that does not descend from the live checkout (it is in the range but cannot be on the way to the tip from here): the old path", s["rc"] == 0 and s["order"] == OLDORDER and "neither a merge of the fast-ok ledger nor docs-only" in s["log"], (s["order"], s["log"]))

# two releases back to back, the first's main run not finished (it never started: its deploy failed after the merge, the live checkout stays where it was): the second rides along on the first's merge
s1 = ride("b2b-ride-1", heads=BASE, live=BASE, deploy_fail="1")
check("back to back (1): the first release merges on a passing PR check and an up-to-date head, its deploy fails: merged, not deployed, and its merge is in the ledger",
      s1["rc"] == 1 and s1["deploys"] == [MERGE] and "FAILED at deploy" in s1["log"] and led(s1) == {MERGE}, (s1["rc"], s1["deploys"], s1["ledger"], s1["log"]))
s2 = ride("b2b-ride-2", pr="25", head=NEWPR, base=MERGE, heads=BASE, live=BASE, history=",".join([OTHER, GOOD, BASE, HEADSHA, MERGE, NEWPR, NEWER]), tips=NEWER, docs=MERGE, range=MERGE,
          runs=json.dumps([{"databaseId": 8, "headSha": NEWER}, {"databaseId": 7, "headSha": MERGE}]), main7="pending", ledger=s1["ledger"])
check("back to back (2): the second deploys on the fast path, at its own merge, although the first's merge is not deployed and its main run has not finished: it rides along; green",
      s2["rc"] == 0 and s2["deploys"] == [NEWER] and s2["order"][0] == f"deploy:{NEWER}" and "only by 1 merge(s) release.sh made on a passing PR check" in s2["log"]
      and "main's full run follows" in s2["msgs"][0] and "run view 7" not in s2["gh"] and led(s2) == {MERGE, NEWER}, (s2["rc"], s2["order"], s2["log"], s2["out"], s2["ledger"]))

# blocked: a commit between the live checkout and the tip that is neither in the ledger nor docs-only
s = ride("ride-blocked", docs=f"{RIDER},{STRAY}", ledger=LEDG(RIDER), diff=CODE, fm="fake")
check("ride-along blocked: one of the commits is not in the ledger and changes code: (a) fails, the old path (main's run first), the reason in the log",
      s["rc"] == 0 and s["order"] == OLDORDER and "(a) the live checkout (600d000) is not at main's tip ba5e000" in s["log"] and "neither a merge of the fast-ok ledger nor docs-only" in s["log"]
      and "main's full run follows" not in s["msgs"][0], (s["order"], s["log"]))
check("…but its own merge was made on a passing PR check and an up-to-date head, so it is in the ledger though it took the old path; the stray commit is not", led(s) == {RIDER, MERGE}, s["ledger"])
s = ride("ride-blocked-noledger", docs=RIDER, **MD_FM)
check("ride-along: no ledger at all and the commit is docs-only: as before, the docs-only rule carries it",
      s["rc"] == 0 and s["order"][0] == f"deploy:{MERGE}" and "only by merges docs-merge.sh accepts" in s["log"], (s["order"], s["log"]))
s = ride("ride-blocked-notinledger", docs=STRAY, ledger=LEDG(RIDER))
check("ride-along blocked: a commit that is not in the ledger and cannot be shown docs-only (no docs-merge.sh): the old path, fail closed", s["rc"] == 0 and s["order"] == OLDORDER, (s["order"], s["log"]))
s = ride("ride-mixed", docs=f"{STRAY},{RIDER}", ledger=LEDG(RIDER), **MD_FM)
check("ride-along: a docs-only commit and a ledger merge together: the fast path", s["rc"] == 0 and s["order"][0] == f"deploy:{MERGE}" and "only by 1 merge(s)" in s["log"], (s["order"], s["log"]))

# an old-path merge of a branch that was not up to date is never recorded
s = scenario("ride-not-utd", merge="ok", base="")
check("a merge of the old path because the branch was not up to date (main's tip unreadable here) is not recorded: no ledger", s["rc"] == 0 and s["ledger"] == "" and "fast-ok" not in s["log"], (s["ledger"], s["log"]))

# an unreadable ledger: today's behaviour (docs-only alone), never written over
good_entry = {"pr": 1, "epoch": int(time.time())}
for nm, bad in (("garbage", "{not json"), ("shape", json.dumps({"v": 2, "merges": {}})), ("list", "[]"), ("empty", ""), ("badsha", json.dumps({"v": 1, "merges": {"not a sha": good_entry}})),
                ("short-sha", json.dumps({"v": 1, "merges": {RIDER[:39]: good_entry}})), ("no-epoch", json.dumps({"v": 1, "merges": {RIDER: {"pr": 1}}})),
                ("str-epoch", json.dumps({"v": 1, "merges": {RIDER: {"pr": 1, "epoch": "1"}}})), ("bool-epoch", json.dumps({"v": 1, "merges": {RIDER: {"pr": 1, "epoch": True}}}))):
    s = ride(f"ride-unreadable-{nm}", docs=RIDER, ledger=bad)
    check(f"unreadable ledger ({nm}): the old path as before (the commit rides on no one's word), the file left alone and said so",
          s["rc"] == 0 and s["order"] == OLDORDER and s["ledger"] == bad and "cannot be read as a ledger" in s["log"] and "(a) the live checkout" in s["log"], (s["order"], s["ledger"], s["log"]))
s = ride("ride-unreadable-docs", docs=RIDER, ledger="{not json", **MD_FM)
check("unreadable ledger: docs-only merges still ride, exactly as before the ledger", s["rc"] == 0 and s["order"][0] == f"deploy:{MERGE}" and "only by merges docs-merge.sh accepts" in s["log"] and s["ledger"] == "{not json", (s["order"], s["log"]))

# a rollback takes out of the ledger the failing merge and every merge it takes out (and what is stale); an entry beyond the live checkout that the reset does not take out stays
REM = f"{LATER} Merge pull request #35 from agent/other;{NEWER} Merge pull request #37 from agent/more"
s = ride("ride-rollback", main="fail", heads=f"{BASE},{LATER}", live=LATER, removed=REM, ledger=LEDG(OTHER, LATER, NEWER, AHEAD))
check("a rollback clears the ledger: the failing merge and the merges the reset takes out are gone (a rolled-back commit, still on main, never rides along), a merge beyond them stays",
      s["rc"] == 1 and s["deploys"] == [MERGE, f"rollback {GOOD}"] and led(s) == {AHEAD}, (s["deploys"], s["ledger"], s["log"]))
s = ride("ride-rollback-byhand", main="fail", heads=f"{BASE},{LATER}", live=LATER, removed=REM, ledger=LEDG(AHEAD), rollback_fail="1")
check("a rollback that fails to deploy gives the by-hand command and names the ledger file to delete", s["rc"] == 1 and "the rollback to 600d000 failed" in red(s)[0] and f"delete the fast-ok ledger {s['dir']}/releases/fast-ok.json" in red(s)[0], red(s))
s = ride("ride-rollback-lockdir", main="fail", heads=f"{BASE},{LATER}", live=LATER, removed=REM, ledger=LEDG(OTHER, LATER, NEWER, AHEAD), ledger_lockdir="1")
check("a rollback that cannot take the entries out (the ledger's lock is unusable) removes the whole ledger: nothing rides along rather than a failed commit",
      s["rc"] == 1 and s["deploys"] == [MERGE, f"rollback {GOOD}"] and s["ledger"] == "" and "the ledger is removed" in s["log"] and "could not be recorded in the fast-ok ledger" in s["log"], (s["ledger"], s["log"]))
s = ride("ride-rollback-skipped", main="fail", marker="#26 (main's tests failed on abc1234)", heads=f"{BASE},{BASE}", live=BASE, ledger=LEDG(AHEAD))
check("a failing run whose merge is no longer live (nothing to roll back): its merge leaves the ledger all the same", s["rc"] == 1 and "NOT rolled back" in red(s)[0] and led(s) == {AHEAD}, (s["ledger"], s["msgs"]))
s = ride("ride-oldpath-fail", main="fail", heads=GOOD, ledger=LEDG(AHEAD))
check("an old-path release whose main run fails while its merge is not live (merged, not deployed) drops its merge from the ledger: recorded at the merge, it does not ride along on the next release",
      s["rc"] == 1 and not s["deploys"] and "FAILED at main's tests" in s["log"] and "merged, not deployed" in s["log"] and "recorded the merge" in s["log"] and led(s) == {AHEAD}, (s["deploys"], s["ledger"], s["log"]))

# an old-path release whose run fails while its merge is LIVE (a release rode along on it and deployed on top): the rollback of a fast deploy, with the rider, not "merged, not deployed"
s = ride("ride-live-fail", main="fail", heads=f"{GOOD},{NEWER}", live=NEWER, removed=f"{NEWER} Merge pull request #35 from agent/rider", ledger=LEDG(AHEAD), docs="")
check("an old-path release whose main run fails while its merge is live through a ride-along: rolled back to the last good commit at once, the report says LIVE via ride-along, rolled back (not merged, not deployed); the rider gets its own message",
      s["rc"] == 1 and s["deploys"] == [f"rollback {GOOD}"] and "LIVE via ride-along, rolled back to 600d000" in red(s)[0] and "merged, not deployed" not in red(s)[0]
      and "PR #35 was rolled back with #23's failure" in "\n".join(s["msgs"]) and (s["dir"] / "releases/pr-35.rolledback").exists() and led(s) == {AHEAD}, (s["deploys"], s["msgs"], s["ledger"], s["log"]))
s = ride("ride-live-fail-norecord", main="fail", heads=f"{GOOD},{NEWER}", live=NEWER, lastgood="", ledger=LEDG(AHEAD), docs="")
check("…and with no last-good commit to go back to it is NOT rolled back, said so in the report (deployed, not 'merged, not deployed')", s["rc"] == 1 and not any(d.startswith("rollback") for d in s["deploys"]) and "NOT rolled back" in red(s)[0], (s["deploys"], s["msgs"]))

# the ledger's own file: pruning by 30 days and by the 200-entry cap, the shape check, and the prune list, on the very code release.sh runs
src = pathlib.Path(STACK, "release.sh").read_text()
ledger_py = src.split("LEDGER_PY='", 1)[1].split("'\nledger_read()", 1)[0]
ld = pathlib.Path(_scratch.mkdtemp(prefix="releasetest-ledgerfile-")); dirs.append(ld)
def hx(i): return f"{i:040x}"
def ledger_op(name, entries, op, *args, prune=""):   # run LEDGER_PY on a file holding entries ({sha: epoch}); returns (exit code, merges after, text before)
    p = ld / name; txt = json.dumps({"v": 1, "merges": {k: {"pr": 1, "epoch": v} for k, v in entries.items()}}) if isinstance(entries, dict) else entries; p.write_text(txt)
    r = subprocess.run([sys.executable, "-I", "-c", ledger_py, op, str(p), *args], env={"LEDGER_PRUNE": prune, "PATH": os.environ.get("PATH", "")}, capture_output=True, text=True, timeout=30)
    return r.returncode, (json.loads(p.read_text())["merges"] if r.returncode == 0 and op != "read" else None), txt, r.stdout
nowe = int(time.time()); DAY = 86400
rc_, after, _, _ = ledger_op("age", {hx(1): nowe - 31 * DAY, hx(2): nowe - 29 * DAY, hx(3): nowe - 1}, "add", hx(9), "7")
check("ledger: an entry older than 30 days is dropped on a write, one of 29 days and a fresh one stay, and the new one is in", rc_ == 0 and set(after) == {hx(2), hx(3), hx(9)}, (rc_, after))
rc_, after, _, _ = ledger_op("cap", {hx(i): nowe - 1000 + i for i in range(1, 206)}, "add", hx(999), "7")
check("ledger: more than 200 entries are cut to the newest 200 (the oldest go, the new one stays)", rc_ == 0 and len(after) == 200 and hx(999) in after and hx(1) not in after and hx(6) not in after and hx(7) in after and hx(205) in after, (rc_, len(after or {})))
rc_, after, _, _ = ledger_op("prune", {hx(1): nowe, hx(2): nowe, hx(3): nowe}, "drop", hx(3), prune=f"{hx(1)} {hx(77)}")
check("ledger: the prune list (LEDGER_PRUNE) and the dropped commits both leave on one write", rc_ == 0 and set(after) == {hx(2)}, (rc_, after))
for nm, bad in (("noepoch", {"v": 1, "merges": {hx(1): {"pr": 1}}}), ("strepoch", {"v": 1, "merges": {hx(1): {"pr": 1, "epoch": "5"}}}), ("boolepoch", {"v": 1, "merges": {hx(1): {"pr": 1, "epoch": True}}}),
                ("nopr", {"v": 1, "merges": {hx(1): {"epoch": 5}}}), ("sha39", {"v": 1, "merges": {hx(1)[1:]: {"pr": 1, "epoch": 5}}}), ("sha41", {"v": 1, "merges": {"0" + hx(1): {"pr": 1, "epoch": 5}}}),
                ("upper", {"v": 1, "merges": {hx(1).upper().replace("0", "A"): {"pr": 1, "epoch": 5}}})):
    rc_, after, txt, _ = ledger_op(f"bad-{nm}", json.dumps(bad), "add", hx(9), "7")
    check(f"ledger shape ({nm}): refused with exit 2 and the file untouched", rc_ == 2 and (ld / f"bad-{nm}").read_text() == txt, (rc_, (ld / f"bad-{nm}").read_text()))
rc_, after, _, out = ledger_op("sha64", {hx(1) + hx(2)[:24]: nowe}, "read")
check("ledger shape: a 64-character sha is a sha (40 or 64 hex)", rc_ == 0 and out.split() == [hx(1) + hx(2)[:24]], (rc_, out))
rc_, after, txt, _ = ledger_op("addbad", {}, "add", hx(9)[1:], "7")
check("ledger: a merge that is not a full sha is not recorded (exit 4)", rc_ == 4, rc_)

# docs_only_between with a ledger, on a throwaway real repository and the real git: a side-branch merge, a direct push, a ledger merge and a docs commit
rd_ = pathlib.Path(_scratch.mkdtemp(prefix="releasetest-ledgergit-")); dirs.append(rd_)
rp = rd_ / "r"; g("init", "-q", "-b", "main", str(rp))
def commit(name, text, msg):
    (rp / name).write_text(text); g("add", "-A", cwd=rp); g("commit", "-qm", msg, cwd=rp); return g("rev-parse", "HEAD", cwd=rp)
a0 = commit("README.md", "0\n", "live")
g("checkout", "-q", "-b", "feat", cwd=rp); commit("feature.py", "x = 1\n", "feature work")      # the PR branch: a code commit that is not on main's first-parent line
g("checkout", "-q", "main", cwd=rp); g("merge", "-q", "--no-ff", "-m", "Merge pull request #1 from agent/feat", "feat", cwd=rp); m1 = g("rev-parse", "HEAD", cwd=rp)   # the ledger merge
d1 = commit("README.md", "1\n", "docs after the merge")
dp1 = commit("app.py", "y = 2\n", "a direct push of code")                                       # not in the ledger, not docs-only
d2 = commit("README.md", "2\n", "docs after the push")
(rd_ / "fm.sh").write_text(FAKE_FM)
(rd_ / "h.sh").write_text('set -u\nREPO=x\neval "$(sed -n \'/^fm_pysrc() {/,/^fast_gate() {/p\' "$1" | sed \'$d\')"\ncd "$2"\ndocs_only_between "$3" "$4" "${5:-}"; rc=$?\necho "ride_n=$ride_n"; exit $rc\n')
def dob2(a, b, ledger="", fm="fm.sh"):
    r = subprocess.run(["bash", str(rd_ / "h.sh"), os.path.join(STACK, "release.sh"), str(rp), a, b, ledger], env={**genv, "DOCS_MERGE_SCRIPT": str(rd_ / fm)}, capture_output=True, text=True, timeout=60)
    return r.returncode, r.stdout.strip()
check("real git: a side-branch merge in the ledger (its feature commit is code, on the second parent only) rides along: the range is the merge alone", dob2(a0, m1, m1) == (0, "ride_n=1"), dob2(a0, m1, m1))
check("real git: the same merge without the ledger is not docs-only (it changes code)", dob2(a0, m1)[0] == 1, dob2(a0, m1))
check("real git: the ledger merge needs no docs-merge.sh (the checker is only read for a commit that is not in the ledger)", dob2(a0, m1, m1, fm="no-such.sh") == (0, "ride_n=1"), dob2(a0, m1, m1, fm="no-such.sh"))
check("real git: a ledger merge and a docs commit after it ride along together", dob2(a0, d1, m1) == (0, "ride_n=1"), dob2(a0, d1, m1))
check("real git: a direct push of code after the ledger merge, in neither the ledger nor docs-only, blocks", dob2(a0, dp1, m1)[0] == 1 and dob2(a0, d2, m1)[0] == 1, (dob2(a0, dp1, m1), dob2(a0, d2, m1)))
check("real git: the direct push in the ledger would ride (the ledger is the only word it needs)", dob2(a0, d2, f"{m1} {dp1}") == (0, "ride_n=2"), dob2(a0, d2, f"{m1} {dp1}"))
check("real git: from the ledger merge on, only docs between: docs-only alone, nothing from the ledger", dob2(m1, d1) == (0, "ride_n=0"), dob2(m1, d1))

# the rest of release.sh's rules the change touches
check("WAIT_MAIN defaults to 5400 s (90 min: main's full run can be slow on a loaded host), with the reason given", 'WAIT_MAIN="${RELEASE_WAIT_MAIN:-5400}"' in src and "90 min" in src.split("WAIT_MAIN=")[1].split("\n")[0])
check("the header documents the ride-along (the ledger file, the old path's merge not counting, the rollback clearing it, the live-via-ride-along rollback)", all(w in src.split("set -uo pipefail")[0] for w in ("RIDE-ALONG", "fast-ok.json", "is not in the ledger", "a rollback drops the failing", "LIVE via ride-along, rolled back")))

# ---- 13j. no retest when nothing could differ: a PR that is behind main used to be brought up to date and tested again. When no suite reads both a file
# the PR changed and a file main's new commits changed (tools/retest_skip.py reads the suite map that main's measured run publishes), the retest cannot find anything the first run did not: release.sh merges the head
# its checks passed on and deploys at the merge, main's full run after it. Two halves: release.sh's wiring with a stub of the helper (RELEASE_RETEST_SKIP; the answer is the stub's), then the helper itself on throwaway
# git repositories with a made-up map.
rt = pathlib.Path(_scratch.mkdtemp(prefix="releasetest-retest-")); dirs.append(rt)
RETEST_STUB = rt / "retest_skip_stub.py"
RETEST_STUB.write_text('''import os, sys
d = os.environ["RT_DIR"]
open(d + "/retest.log", "a").write(" ".join(sys.argv[1:]) + "\\n")
n = len(open(d + "/retest.log").read().splitlines())
seq = os.environ.get("RT_RETEST", "retest: no answer").split("|")
ans = seq[min(n, len(seq)) - 1]
print("a first line the caller must not read"); print(ans)
sys.exit(0 if ans.startswith("skip: ") else 1)
''')
SKIP_ON = {"RELEASE_RETEST_SKIP": str(RETEST_STUB), "RELEASE_SKIP_DISJOINT": "1"}
NOTE = "no suite reads both sides (map of 1a2b3c4); the PR changed 1 file(s): alpha_one.txt; main's 2 new commit(s) since ba5e000 changed 1 file(s): zeta_two.txt"
SKIP = "skip: " + NOTE
def rlog(s): return (s["dir"] / "retest.log").read_text().splitlines() if (s["dir"] / "retest.log").exists() else []

s = fast("skip-pass", merge="ok", history=HIST_B, retest=SKIP, extra=SKIP_ON)
check("no retest: the branch is not updated and its tests are not waited for again; the merge is pinned to the head the checks passed on, deployed at the merge, main's run read after",
      s["rc"] == 0 and s["deploys"] == [MERGE] and s["order"] == [f"deploy:{MERGE}", "client:message", "run-view"] and "update-branch" not in s["gh"] and not s["sleeps"]
      and f"pr merge 23 --repo example-owner/stackshot --merge --match-head-commit {HEADSHA}" in s["gh"].splitlines() and s["lastgood"] == MERGE, (s["rc"], s["order"], s["gh"], s["sleeps"], s["out"]))
check("no retest: the helper is asked twice (before the lock, then again under it on main's tip as it is then) with the PR head, main's tip and the published map's repository and cache; the log names the two file sets",
      len(rlog(s)) == 2 and all(l == f"--repo {s['dir']}/box --head {HEADSHA} --main {BASE} --slug example-owner/stackshot --cache {s['dir']}/releases/suitemap" for l in rlog(s))
      and at(s["log"], "checks pass", f"retest skipped for the PR head abc1234 on main's tip ba5e000: {NOTE}", "deploy lock taken", "retest skipped for the PR head abc1234", "no retest: the PR's last green checks stand",
             "deploying 0106c0d at once: the PR's last green checks stand", "done: ", "main's tests passed on 0106c0d") and "update lock" not in s["log"], (rlog(s), s["log"]))
check("no retest: one green report at the deploy that says it was NOT retested and why, with both file sets, and that main's full run follows; no update lock was taken",
      len(s["msgs"]) == 1 and s["msgs"][0].endswith(GREEN_ARGS) and "was NOT retested: its last green checks stand" in s["msgs"][0] and "the PR changed 1 file(s): alpha_one.txt" in s["msgs"][0]
      and "changed 1 file(s): zeta_two.txt" in s["msgs"][0] and "main's full run follows" in s["msgs"][0] and upd_lock_free(s), s["msgs"])
check("no retest: the merge is not entered in the ride-along ledger (the tree was not the one tested), and the locks are free at the end", not s["ledger"] and s["ledger_files"] in ([], ["fast-ok.json.lock"]) and lock_free(s), (s["ledger"], s["ledger_files"]))

s = fast("skip-main-fails", merge="ok", history=HIST_B, retest=SKIP, extra=SKIP_ON, main="fail", heads=f"{BASE},{MERGE}")
check("no retest, main's run fails after the deploy: rolled back to the last good commit as for any fast deploy", s["rc"] == 1 and s["deploys"] == [MERGE, "rollback " + GOOD] and any("FAILED at main's tests" in m for m in s["msgs"]), (s["rc"], s["deploys"], s["msgs"]))

s = fast("skip-no", merge="ok", history=HIST_1, prheads=f"{HEADSHA},{HEADSHA},{H1}", p2=H1, checks="pass,pending,pass", retest="retest: suite(s) alpha read both what the PR changed (alpha_one.txt) and what main's new commits changed (alpha_two.txt)", extra=SKIP_ON)
check("retest needed: update-branch, the wait for the tests on the new head and the deploy happen exactly as before, and the log says why the retest was not skipped",
      s["rc"] == 0 and s["deploys"] == [MERGE] and UPD_LINE in s["gh"].splitlines() and f"--match-head-commit {H1}" in s["gh"] and len(rlog(s)) == 1
      and at(s["log"], "checks pass", "retest needed for the PR head abc1234 on main's tip ba5e000: suite(s) alpha read both what the PR changed (alpha_one.txt) and what main's new commits changed (alpha_two.txt)",
             "update lock taken", "update-branch round 1 of 3") and "NOT retested" not in s["msgs"][0] and "brought it up to date with update-branch (1 round(s))" in s["msgs"][0], (rlog(s), s["log"], s["msgs"]))
for nm, ans in (("garbage", "something else entirely"), ("nothing", "")):
    s = fast(f"skip-{nm}", merge="ok", history=HIST_1, prheads=f"{HEADSHA},{HEADSHA},{H1}", p2=H1, retest=ans, extra=SKIP_ON)
    check(f"retest needed: a helper that answers {nm} is a retest (update-branch as before), never a skip",
          s["rc"] == 0 and UPD_LINE in s["gh"].splitlines() and "the check gave no answer (retest_skip_stub.py, exit 1)" in s["log"] and "NOT retested" not in s["msgs"][0], (s["log"], s["msgs"]))
s = fast("skip-no-helper", merge="ok", history=HIST_1, prheads=f"{HEADSHA},{HEADSHA},{H1}", p2=H1, extra={"RELEASE_RETEST_SKIP": str(rt / "no-such-helper.py"), "RELEASE_SKIP_DISJOINT": "1"})
check("retest needed: a helper that is missing (or crashes) is a retest too, the release goes on as before", s["rc"] == 0 and UPD_LINE in s["gh"].splitlines() and "the check gave no answer (no-such-helper.py, exit 2)" in s["log"], (s["rc"], s["log"]))
s = fast("skip-off", merge="ok", history=HIST_1, prheads=f"{HEADSHA},{HEADSHA},{H1}", p2=H1, retest=SKIP, extra={**SKIP_ON, "RELEASE_SKIP_DISJOINT": "0"})
check("RELEASE_SKIP_DISJOINT=0: the helper is not run and every branch behind main is updated and retested, as before", s["rc"] == 0 and not rlog(s) and UPD_LINE in s["gh"].splitlines() and "RELEASE_SKIP_DISJOINT is off" in s["log"], (rlog(s), s["log"]))
s = fast("skip-up-to-date", merge="ok", retest=SKIP, extra=SKIP_ON)
check("a PR that is up to date never asks (nothing to catch up on)", s["rc"] == 0 and not rlog(s) and s["deploys"] == [MERGE] and "up to date: the PR head abc1234 contains main's tip" in s["log"], (rlog(s), s["log"]))

# main moves between the first answer and the lock: the answer is asked again on the tip as it is then; when it no longer holds the old path takes the merge (main's run first), never a deploy on an untested tree
HIST_M = ",".join([GOOD, HEADSHA, BASE, B2, *TAIL])
s = fast("skip-lost", merge="ok", history=HIST_M, bases=f"{BASE},{B2}", base=B2, heads=B2, retest=SKIP + "|retest: both sides change shared.txt", extra=SKIP_ON, p1=B2)
check("the skip no longer holds under the lock (main moved, both sides now change a file): the old path, main's run first and then the deploy, the reason in the log and the report",
      s["rc"] == 0 and s["order"] == ["run-view", f"deploy:{MERGE}", "client:message"] and len(rlog(s)) == 2 and "--main " + B2 in rlog(s)[1]
      and at(s["log"], "retest skipped for the PR head abc1234 on main's tip ba5e000", "retest needed for the PR head abc1234 on main's tip ba5e200: both sides change shared.txt", "not up to date for a deploy at the merge",
             "the retest skip no longer holds: both sides change shared.txt", "(the old path)", "merged", "main's tests pass at 0106c0d")
      and "its retest was skipped, but then both sides change shared.txt, so it took the old path" in s["msgs"][0] and "main's full run follows" not in s["msgs"][0] and not s["ledger"], (s["order"], s["log"], s["msgs"]))
s = fast("skip-tip-moved", merge="ok", history=HIST_B, retest=SKIP, extra=SKIP_ON, p1=B2)
check("the skip holds but main's tip is not the merge of the tip checked and the head (something landed between): the old path, the reason in the log",
      s["rc"] == 0 and s["order"][:1] == ["run-view"] and "not deployed at the merge" in s["log"] and "is not the merge of ba5e000 and abc1234" in s["log"] and not s["ledger"], (s["order"], s["log"]))
s = fast("skip-live-behind", merge="ok", history=HIST_B, retest=SKIP, extra=SKIP_ON, heads=GOOD, live=GOOD)
check("the skip holds but the live checkout is not at main's tip (fast_gate (a)): the old path, as for an up-to-date PR, the reason in the log",
      s["rc"] == 0 and s["order"][:1] == ["run-view"] and "(a) the live checkout" in s["log"], (s["order"], s["log"]))
check("the header documents it (step 2a'', the knobs, the fact that the report names both file sets)",
      all(w in src.split("set -uo pipefail")[0] for w in ("2a''. NO RETEST WHEN NOTHING COULD DIFFER", "tools/retest_skip.py", "RELEASE_SKIP_DISJOINT=0", "RELEASE_SUITEMAP=<file>", "name both file sets")), "usage")
hp_ = subprocess.run(["bash", os.path.join(STACK, "release.sh"), "--help"], capture_output=True, text=True); usage = hp_.stdout + hp_.stderr
check("--help carries the rule for a branch behind main whose changes share no test group", "share no test group" in usage and "NOT retested" in usage, usage[:600])

# ---- 13k. the helper on throwaway repositories (real git, a made-up map, made-up file names): tools/retest_skip.py
import datetime
HELPER = os.path.join(STACK, "tools", "retest_skip.py"); WF0 = pathlib.Path(STACK, ".github/workflows/tests.yml").read_text()
rp = rt / "repo"; rp.mkdir()
g("init", "-q", "-b", "main", str(rp))
def put(base, path, text):
    f = base / path; f.parent.mkdir(parents=True, exist_ok=True); f.write_text(text)
def body(path, tag="0"):   # a made-up file's text: valid Python for a .py (with an import of os that is there from the start), shell for a .sh
    if path.endswith(".py"): return f"import os\nx = {tag}  # {path}\n"
    if path.endswith(".sh"): return f"echo {tag}\n"
    return f"{path} {tag}\n"
SCRIPT_BLOCK = '# /// script\n# dependencies = []\n# ///\n'
for path in ("tests/alpha_scenario.py", "tests/beta_scenario.py", "mod_b.py", "lib_one.txt", "lib_two.txt", "lib_shared.txt", "notes_plain.txt", "pkg/gone.txt", "pkg/stay.txt",
             ".github/workflows/ci.yml", "release.sh", "deploy.sh", "tests/run-suite", "tests/suitemap.py", "tools/retest_skip.py", "api_mod.py", "units/u.service", "LICENSE", "Makefile", "scripts/run_one.sh", "sub/tool_x.py.lock",
             "tests/pyproject.toml", "tests/uv.lock", "tools/tool_text.py", "tools/text_check.py", "tests/tool_text.snapshot.json", "tools/clean_text.py"):
    put(rp, path, body(path))
put(rp, "sub/tool_x.py", SCRIPT_BLOCK + body("sub/tool_x.py"))
g("add", "-A", cwd=rp); g("commit", "-qm", "c0", cwd=rp); C0 = g("rev-parse", "HEAD", cwd=rp)
def branch(name, changes, frm=None):   # a branch from C0 (or frm) with {path: text, path: None (deleted)}; returns its tip
    g("checkout", "-q", "-B", name, frm or C0, cwd=rp)
    for p, t in changes.items():
        if t is None: (rp / p).unlink()
        else: put(rp, p, t)
    g("add", "-A", cwd=rp); g("commit", "-q", "--allow-empty", "-m", name, cwd=rp)
    return g("rev-parse", "HEAD", cwd=rp)
def mkmap(commit=C0, age_h=1, **over):
    m = {"format": 1, "commit": commit, "strace": True, "suites": {
         "alpha": {"ok": True, "seconds": 1.0, "py": {}, "files": ["lib_one.txt", "lib_shared.txt"], "whole": [], "dirs": ["", "pkg"]},
         "beta": {"ok": True, "seconds": 1.0, "py": {"mod_b.py": ["f"]}, "files": ["lib_two.txt", "lib_shared.txt", "pkg/gone.txt"], "whole": [], "dirs": [""]}}}
    m["measured"] = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=age_h)).isoformat(timespec="seconds")
    m.update(over); return m
def helper(head, main_, m, name="map.json"):
    mp = rt / name
    if m is not None: mp.write_text(m if isinstance(m, str) else json.dumps(m))
    r = subprocess.run([sys.executable, HELPER, "--repo", str(rp), "--head", head, "--main", main_, "--map", str(mp)], capture_output=True, text=True, timeout=60)
    return r.returncode, r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "", r.stderr
def verdict(name, changes_pr, changes_main, m=None):
    pr_ = branch(f"pr-{name}", changes_pr); mn_ = branch(f"main-{name}", changes_main)
    return helper(pr_, mn_, mkmap() if m is None else m)
def chg(*paths): return {p: body(p, "1") for p in paths}

rc, out, err = verdict("disjoint", chg("lib_one.txt"), chg("lib_two.txt"))
check("helper: a file one suite reads on the PR side and a file another suite reads on main's: skip, naming both file sets",
      rc == 0 and out.startswith("skip: no suite reads both sides (map of " + C0[:7] + ")") and "the PR changed 1 file(s): lib_one.txt" in out and "changed 1 file(s): lib_two.txt" in out, (rc, out, err))
rc, out, err = verdict("plain", chg("notes_plain.txt"), chg("lib_two.txt"))
check("helper: a file in the map's tree that no suite reads reaches no suite: skip", rc == 0 and out.startswith("skip: ") and "notes_plain.txt" in out, (rc, out, err))
rc, out, err = verdict("shared", chg("lib_one.txt"), chg("lib_shared.txt"))
check("helper: a suite that reads both what the PR changed and what main changed: retest, naming the suite and the files",
      rc == 1 and out.startswith("retest: suite(s) alpha read both what the PR changed (lib_one.txt) and what main's side changed (lib_shared.txt)"), (rc, out, err))
rc, out, err = verdict("python", chg("mod_b.py"), chg("lib_two.txt"))
check("helper: a Python file counts as read by the suite whose coverage ran it (py keys)", rc == 1 and "suite(s) beta" in out, (rc, out))
rc, out, err = verdict("scenario", chg("tests/alpha_scenario.py"), chg("lib_one.txt"))
check("helper: a suite's own file is read by that suite", rc == 1 and "suite(s) alpha" in out, (rc, out))
rc, out, err = verdict("same", chg("notes_plain.txt"), {"notes_plain.txt": "other\n"})
check("helper: a file changed on both sides: retest, even when no suite reads it", rc == 1 and out == "retest: both sides change notes_plain.txt", (rc, out))
rc, out, err = verdict("unknown", chg("brand_new_file.txt"), chg("lib_two.txt"))
check("helper: a file the map has never seen (not in any suite's reads, not in its tree): retest, naming it", rc == 1 and out.startswith("retest: unknown to the suite map of " + C0[:7] + ": brand_new_file.txt"), (rc, out))
rc, out, err = verdict("unknown-main", chg("lib_one.txt"), chg("brand_new_file.txt"))
check("helper: an unknown file on main's side is a retest as well", rc == 1 and "unknown to the suite map" in out and "brand_new_file.txt" in out, (rc, out))
rc, out, err = verdict("deleted", chg("lib_one.txt"), {"pkg/gone.txt": None})
check("helper: a file main deleted is read by the suites that read it and by those that listed its directory (alpha lists pkg/): shared with the PR's alpha file: retest",
      rc == 1 and "suite(s) alpha" in out and "pkg/gone.txt" in out, (rc, out))
rc, out, err = verdict("deleted-ok", chg("lib_two.txt"), {"pkg/stay.txt": None})
check("helper: a deleted file that only alpha's directory listing reaches, against a PR file only beta reads: skip", rc == 0 and out.startswith("skip: "), (rc, out))
for nm, path in (("workflow", ".github/workflows/ci.yml"), ("release", "release.sh"), ("deploy", "deploy.sh"), ("runner", "tests/run-suite"), ("mapper", "tests/suitemap.py"), ("self", "tools/retest_skip.py")):
    rc, out, err = verdict(f"h-{nm}-pr", chg(path), chg("lib_two.txt"))
    rc2, out2, err2 = verdict(f"h-{nm}-main", chg("lib_one.txt"), chg(path))
    check(f"helper: {path} changed by the PR, or by main's new commits: retest", rc == 1 and rc2 == 1 and path in out and path in out2 and "the CI workflow, the release or the test runner" in out, (out, out2))
# F1: the map's read sets are those of its commit, so a dependency a change adds is invisible to it: a scenario edited to import a module no suite read at the map's commit, while main changes that module
import importlib.util, re
ALPHA = "tests/alpha_scenario.py"; TOOLX = "sub/tool_x.py"
def alpha(text): return {ALPHA: text}
rc, out, err = verdict("dep-none", alpha("import os\nx = 5  # edited, nothing new\n"), chg("api_mod.py"))
check("helper: the control for the cases below: a scenario edit that adds no import, call or path (the import it had stays) while main changes a module no suite reads: skip", rc == 0 and out.startswith("skip: "), (rc, out, err))
for nm, text, what in (("import", "import os\nimport api_mod\nx = 0\n", "an import"), ("from", "import os\nfrom api_mod import thing\nx = 0\n", "an import"),
                       ("dunder", "import os\nm = __import__('api_mod')\n", "a call that loads, runs or reads a file"), ("open", "import os\nd = open('data_file')\n", "a call that loads, runs or reads a file"),
                       ("popen", "import os\nos.popen('true')\n", "a call that loads, runs or reads a file"), ("exec", "import os\nos.execv('/bin/true', [])\n", "a call that loads, runs or reads a file"),
                       ("read", "import os\nt = os.path.join('a', 'b').read_text()\n", "a call that loads, runs or reads a file"),
                       ("path", "import os\nx = 'tools/other_tool.py'\n", "a string that looks like a repository path"), ("file", "import os\nx = 'server.py'\n", "a string that looks like a repository path"),
                       ("fstring", "import os\nn = 1\nx = f'conf/{n}.json'\n", "a string that looks like a repository path"), ("inside", "import os\nx = 'run python3 sub/tool_y.py --now'\n", "a string that looks like a repository path")):
    rc, out, err = verdict(f"dep-{nm}", alpha(text), chg("api_mod.py"))
    check(f"helper: the PR side adds {nm} to a scenario while main changes a module the map shows no suite reading: retest, saying what and where",
          rc == 1 and out.startswith(f"retest: the PR: {ALPHA} adds or changes {what}") and "cannot show" in out, (nm, rc, out, err))
for nm, text, what in (("listdir", "import os\nl = os.listdir(os.getcwd())\n", "a call that loads, runs or reads a file"), ("scandir", "import os\nl = os.scandir('.')\n", "a call"),
                       ("iterdir", "import os\nl = list(os.getcwd().iterdir())\n", "a call"), ("glob", "import os\nl = os.getcwd().glob(n)\n", "a call"),
                       ("exists", "import os\nok = os.path.exists(n)\n", "a call"), ("stat", "import os\ns = os.stat(n)\n", "a call"), ("load", "import os\nd = os.getcwd().load(n)\n", "a call"),
                       ("globstr", "import os\nx = 'u*.service'\n", "a string that looks like a repository path"), ("qmark", "import os\nx = 'unit?.service'\n", "a string that looks like a repository path"),
                       ("rootdir", "import os\nx = 'units'\n", "a string that looks like a repository path"), ("rootfile", "import os\nx = 'LICENSE'\n", "a string that looks like a repository path"),
                       ("rootfile2", "import os\nx = 'Makefile'\n", "a string that looks like a repository path")):
    rc, out, err = verdict(f"dep2-{nm}", alpha(text), chg("units/u.service"))
    check(f"helper: the PR adds {nm} to a scenario (a listing, glob, existence check or a name at the root) while main changes units/u.service that no suite read: retest",
          rc == 1 and out.startswith(f"retest: the PR: {ALPHA} adds or changes {what}"), (nm, rc, out, err))
rc, out, err = verdict("dep2-none", alpha("import os\nx = 'plain words'\n"), chg("units/u.service"))
check("helper: the control for the listing and glob cases: a plain string and no new call: skip", rc == 0 and out.startswith("skip: "), (rc, out, err))
rc, out, err = verdict("dep-doc", alpha('"""see tools/other_tool.py and sub/tool_y.py"""\nimport os\nx = 0\n'), chg("api_mod.py"))
check("helper: a path named in a docstring loads nothing: skip", rc == 0 and out.startswith("skip: "), (rc, out, err))
rc, out, err = verdict("dep-comment", alpha("import os\n# see tools/other_tool.py, import api_mod\nx = 0\n"), chg("api_mod.py"))
check("helper: a comment names nothing the program loads: skip", rc == 0 and out.startswith("skip: "), (rc, out, err))
rc, out, err = verdict("dep-syntax", alpha("def (:\n"), chg("api_mod.py"))
check("helper: a Python file that cannot be parsed is a retest, naming it", rc == 1 and out.startswith(f"retest: the PR: {ALPHA} cannot be read as Python"), (rc, out, err))
rc, out, err = verdict("dep-main", chg("lib_one.txt"), {"mod_b.py": "import os\nimport api_mod\nx = 0\n"})
check("helper: main's side adds an import to a file another suite reads: retest (a dependency the map cannot show), naming the file", rc == 1 and out.startswith("retest: main's side: mod_b.py adds or changes an import"), (rc, out, err))
rc, out, err = verdict("dep-main-ok", chg("lib_one.txt"), {"mod_b.py": "import os\nx = 7  # changed\n"})
check("helper: main's side edits a file without adding an import, call or path: skip", rc == 0 and out.startswith("skip: "), (rc, out, err))
rc, out, err = verdict("sh-source", {"scripts/run_one.sh": "echo 0\nsource other_lib.sh\n"}, chg("lib_two.txt"))
check("helper: a shell script that gains a source line: retest", rc == 1 and out.startswith("retest: the PR: scripts/run_one.sh adds or changes a line that sources or names a file"), (rc, out, err))
rc, out, err = verdict("sh-path", {"scripts/run_one.sh": "echo 0\npython3 tools/other_tool.py\n"}, chg("lib_two.txt"))
check("helper: a shell script that gains a line naming a repository path: retest", rc == 1 and "scripts/run_one.sh adds or changes a line that sources or names a file" in out, (rc, out, err))
rc, out, err = verdict("sh-plain", {"scripts/run_one.sh": "echo 0\n# see tools/other_tool.py\necho hi there\n"}, chg("lib_two.txt"))
check("helper: a shell script that gains an echo and a comment naming a path: skip", rc == 0 and out.startswith("skip: "), (rc, out, err))

# the map's commit is older than main's tip: whatever changed since it counts as main's side, with the same reads and checks
D1 = branch("drift-base", {"lib_shared.txt": "drifted\n"})
pr_d = branch("pr-drift", chg("lib_one.txt"), frm=D1); mn_d = branch("main-drift", chg("lib_two.txt"), frm=D1)
rc, out, err = helper(pr_d, mn_d, mkmap(commit=D1))
check("helper: the control: a file changed before the PR branched, the map made at that commit: skip (alpha's file on the PR side, beta's on main's)", rc == 0 and out.startswith("skip: ") and "since the map's commit" not in out, (rc, out, err))
rc, out, err = helper(pr_d, mn_d, mkmap())
check("helper: the same, the map one commit older: lib_shared.txt changed since the map counts as main's side, and alpha reads it and the PR's file: retest, naming both",
      rc == 1 and out.startswith("retest: suite(s) alpha read both what the PR changed (lib_one.txt) and what main's side changed (lib_shared.txt") , (rc, out, err))
D2 = branch("drift-new", {"brand_new_drift.txt": "x\n"})
rc, out, err = helper(branch("pr-drift2", chg("lib_one.txt"), frm=D2), branch("main-drift2", chg("lib_two.txt"), frm=D2), mkmap())
check("helper: a file added since the map's commit is unknown to the map, even though both sides left it alone: retest", rc == 1 and out.startswith("retest: unknown to the suite map of " + C0[:7] + ": brand_new_drift.txt"), (rc, out, err))
D3 = branch("drift-imp", {"mod_b.py": "import os\nimport api_mod\nx = 0\n"})
pr_i, mn_i = branch("pr-drift3", chg("lib_one.txt"), frm=D3), branch("main-drift3", chg("lib_two.txt"), frm=D3)
rc, out, err = helper(pr_i, mn_i, mkmap())
rc2, out2, err2 = helper(pr_i, mn_i, mkmap(commit=D3))
check("helper: an import added since the map's commit is a dependency the map cannot show (retest); the map made after it is current (skip)",
      rc == 1 and out.startswith("retest: main's side: mod_b.py adds or changes an import") and rc2 == 0 and out2.startswith("skip: "), (rc, out, rc2, out2))
D4 = branch("drift-path", {"lib_two.txt": "drift four\n"})
rc, out, err = helper(branch("pr-drift4", chg("lib_two.txt"), frm=D4), branch("main-drift4", chg("lib_shared.txt"), frm=D4), mkmap())
check("helper: a file changed on main before the PR branched and by the PR again is not 'changed by both sides' (the merge has no conflict): the answer comes from the suites that read them", rc == 1 and "both sides change" not in out and "suite(s) beta" in out, (rc, out, err))

# F2: checks the workflows run that no suite does
LOCK = "sub/tool_x.py.lock"
for side_nm, mk in (("PR", lambda p: (chg(p), chg("lib_two.txt"))), ("main's side", lambda p: (chg("lib_one.txt"), chg(p)))):
    rc, out, err = verdict("lock-" + side_nm[:2], *mk(LOCK))
    who = "the PR" if side_nm == "PR" else "main's side"
    check(f"helper: a *.lock file changed on the {side_nm}: retest, the workflow's lock check reads it", rc == 1 and out == f"retest: {who} changes {LOCK}, which the CI workflow's lock check reads", (rc, out))
blk = "# /// script\n# dependencies = ['a']\n# ///\n"
rc, out, err = verdict("blk-pr", {TOOLX: blk + body(TOOLX)}, chg("lib_two.txt"))
check("helper: the PR edits the # /// script block of a Python file: retest (the workflow checks the lock against it)", rc == 1 and out.startswith(f"retest: the PR changes the `# /// script` block of {TOOLX}"), (rc, out, err))
rc, out, err = verdict("blk-main", chg("lib_one.txt"), {TOOLX: blk + body(TOOLX)})
check("helper: main's side edits the # /// script block of a Python file: retest", rc == 1 and out.startswith(f"retest: main's side changes the `# /// script` block of {TOOLX}"), (rc, out, err))
rc, out, err = verdict("blk-gone", {TOOLX: body(TOOLX)}, chg("lib_two.txt"))
check("helper: a script block removed from a Python file: retest", rc == 1 and "`# /// script` block" in out, (rc, out, err))
rc, out, err = verdict("blk-body", {TOOLX: SCRIPT_BLOCK + body(TOOLX, "9")}, chg("lib_two.txt"))
check("helper: an edit to the body of a Python file with a script block, the block as it was: not a lock matter (skip)", rc == 0 and out.startswith("skip: "), (rc, out, err))
for path in ("tools/tool_text.py", "tools/text_check.py", "tests/tool_text.snapshot.json", "tools/clean_text.py", "tests/pyproject.toml", "tests/uv.lock"):
    nm = path.replace("/", "-").replace(".", "_")
    rc, out, err = verdict("chk-pr-" + nm, chg(path), chg("lib_two.txt"))
    rc2, out2, err2 = verdict("chk-main-" + nm, chg("lib_one.txt"), chg(path))
    check(f"helper: {path}, a check the workflows run outside the suites, changed by the PR or by main's side: retest, naming it", rc == 1 and rc2 == 1 and path in out and path in out2 and out.startswith("retest: the PR changes ") and out2.startswith("retest: main's side changes "), (path, out, out2))
named = set()
for wf in pathlib.Path(STACK, ".github/workflows").glob("*.yml"):
    named |= {n for n in re.findall(r"(?:tools|tests)/[\w./-]*\w\.(?:py|json|toml|lock)\b", wf.read_text()) if not n.endswith("_scenario.py")}   # a suite named in a comment (tests.yml names tests/suitemap_scenario.py) is in the map, not a check outside the suites
spec = importlib.util.spec_from_file_location("retest_skip_under_test", HELPER); RS = importlib.util.module_from_spec(spec); spec.loader.exec_module(RS)
check("the always-retest set holds every tools/ and tests/ file the workflows name (a check outside the suites reads its inputs from the tree); the scan found the ones expected",
      {"tools/tool_text.py", "tools/text_check.py", "tools/clean_text.py", "tests/uv.lock", "tests/suitemap.py", "tests/tool_text.snapshot.json"} <= named
      and not [n for n in sorted(named) if not RS.always_reason(n)] and RS.always_reason("any/dir/x.lock") and not RS.always_reason("lib_one.txt") and not RS.always_reason("tools/snapshot_regen.py"), (sorted(n for n in named if not RS.always_reason(n)), sorted(named)))

# the map
pr_m = branch("pr-map", chg("lib_one.txt")); mn_m = branch("main-map", chg("lib_two.txt"))
side = branch("side", chg("lib_two.txt"))
rc, out, err = helper(pr_m, mn_m, None, name="absent.json")
check("helper: a map file that is missing is a retest, saying so", rc == 1 and out == "retest: the suite map file cannot be read", (rc, out))
good_suites = mkmap()["suites"]
for nm, m, why in (("not-json", "{nope", "not JSON"), ("format", mkmap(format=2), "another format"), ("empty", mkmap(suites={}), "another format, or empty"),
                   ("nostrace", mkmap(strace=False), "no file measurement"), ("stale", mkmap(age_h=72), "stale: measured 72 h ago"),
                   ("untimed", {k: v for k, v in mkmap().items() if k != "measured"}, "says no time it was measured"),
                   ("foreign-commit", mkmap(commit="0" * 40), "its commit 0000000 is not in main's history"),
                   ("not-on-main", mkmap(commit=side), "is not in main's history"),
                   ("unclean", mkmap(suites={**good_suites, "beta": {**good_suites["beta"], "ok": False}}), "no clean measurement of suite beta"),
                   ("nofiles", mkmap(suites={**good_suites, "beta": {k: v for k, v in good_suites["beta"].items() if k != "files"}}), "no clean measurement of suite beta")):
    rc, out, err = helper(pr_m, mn_m, m, name=f"map-{nm}.json")
    check(f"helper: a map that is {nm} is a retest, saying so", rc == 1 and out.startswith("retest: ") and why in out, (nm, rc, out))
# A suite that failed only when measured (the release suite timed out at the measuring limit on main's run while it passes plainly in 280 s) is `ok: false` in the map, and used to refuse the
# whole map, so no PR could skip until main's next clean run. tests/suitemap.py now keeps the suite's last clean measurement beside it as `carry`; the helper reads the union of the two.
utc_ago = lambda h: (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=h)).isoformat(timespec="seconds")
def carry(at=C0, h=1, **over): return {"py": {}, "files": ["lib_two.txt", "lib_shared.txt"], "whole": [], "dirs": [""], "traced": utc_ago(h), "at": at, **over}
def timed_out_beta(c=None, commit=C0, **kw):   # beta as a run that timed out left it: not ok, and only part of what it reads
    e = {**good_suites["beta"], "ok": False, "files": [], "py": {}, "dirs": [], **kw}
    if c is not None: e["carry"] = c
    return mkmap(commit=commit, suites={**good_suites, "beta": e})
rc, out, err = helper(pr_m, mn_m, timed_out_beta(carry()), name="map-carry.json")
check("helper: a suite that failed only when measured, with its earlier clean measurement carried: the map is used, and the skip says whose reads are an earlier measurement's",
      rc == 0 and out.startswith("skip: ") and "suite(s) beta failed only when measured" in out and "(" + C0[:7] + ")" in out, (rc, out, err[-300:]))
rc, out, err = helper(pr_m, mn_m, timed_out_beta(carry(files=["lib_one.txt", "lib_two.txt"])), name="map-carry-both.json")
check("helper: the carried reads are the suite's: it reads both sides' files, so the retest stays, naming the suite", rc == 1 and out.startswith("retest: suite(s) beta read both what the PR changed"), (rc, out))
rc, out, err = helper(pr_m, mn_m, timed_out_beta(carry(files=["lib_two.txt"]), files=["lib_one.txt"]), name="map-carry-union.json")
check("helper: what the unclean run did measure is read with the carry (the union): a file only the partial run saw counts", rc == 1 and out.startswith("retest: suite(s) beta read both what the PR changed"), (rc, out))
for nm, m, why in (("stale", timed_out_beta(carry(h=72)), "its earlier one is stale: made 72 h ago"),
                   ("foreign", timed_out_beta(carry(at=side)), "is of commit " + side[:7] + ", which is not in main's history"),
                   ("untimed", timed_out_beta({k: v for k, v in carry().items() if k != "traced"}), "no clean measurement of suite beta"),
                   ("failed", timed_out_beta(carry(), failed=True), "no clean measurement of suite beta"),
                   ("malformed", timed_out_beta(carry(files="lib_two.txt")), "no clean measurement of suite beta")):
    rc, out, err = helper(pr_m, mn_m, m, name=f"map-carry-{nm}.json")
    check(f"helper: a carry that is {nm} does not stand in for a clean measurement: retest, saying so", rc == 1 and out.startswith("retest: ") and why in out, (nm, rc, out))
# a carried suite's reads are those of the commit its carry was made at: what changed on main since then is news, even when the map itself is newer
pr_c, mn_c = branch("pr-carry-drift", chg("lib_one.txt"), frm=D3), branch("main-carry-drift", chg("lib_two.txt"), frm=D3)
rc, out, err = helper(pr_c, mn_c, timed_out_beta(carry(), commit=D3), name="map-carry-drift.json")
rc2, out2, err2 = helper(pr_c, mn_c, mkmap(commit=D3), name="map-clean-drift.json")
check("helper: the drift is counted from the carry's commit: an import added after it (before the map's commit) retests; with a clean measurement at the map's commit it skips",
      rc == 1 and out.startswith("retest: main's side: mod_b.py adds or changes an import") and rc2 == 0 and out2.startswith("skip: "), (rc, out, rc2, out2))
# A file added after the carry's commit but before the map's is in the map's tree, yet no measurement from before it existed lists it, though the carried suite may read it (a listing of
# its directory): a change to it, on either side, retests. With a clean measurement at the map's commit the file is just one no suite lists: skip.
D5 = branch("added-new", {"lib_new.txt": "new file\n"})
pr_n, mn_n = branch("pr-new", chg("lib_new.txt"), frm=D5), branch("main-new", chg("lib_two.txt"), frm=D5)
pr_n2, mn_n2 = branch("pr-new2", chg("lib_two.txt"), frm=D5), branch("main-new2", chg("lib_new.txt"), frm=D5)
rc, out, err = helper(pr_n, mn_n, timed_out_beta(carry(), commit=D5), name="map-carry-new-pr.json")
rc2, out2, err2 = helper(pr_n2, mn_n2, timed_out_beta(carry(), commit=D5), name="map-carry-new-main.json")
rc3, out3, err3 = helper(pr_n, mn_n, mkmap(commit=D5), name="map-clean-new.json")
rc4, out4, err4 = helper(pr_n, mn_n, timed_out_beta(carry(files=["lib_two.txt", "lib_new.txt"]), commit=D5), name="map-carry-new-listed.json")
check("helper: a file added since the carry's commit, changed by the PR while main changes a file the carried suite reads: retest (it was a skip: the file is in the map's tree, in no suite's reads)",
      rc == 1 and out.startswith("retest: unknown to the suite map of " + D5[:7]) and "lib_new.txt" in out, (rc, out, err[-300:]))
check("helper: the same file changed by main's side while the PR changes a file the carried suite reads: retest", rc2 == 1 and out2.startswith("retest: unknown to the suite map of " + D5[:7]) and "lib_new.txt" in out2, (rc2, out2))
check("helper: the same change with a clean measurement at the map's commit: skip; with the carried suite listing the new file: the suite reads both sides, retest",
      rc3 == 0 and out3.startswith("skip: ") and rc4 == 1 and out4.startswith("retest: suite(s) beta read both"), (rc3, out3, rc4, out4))
rc_, out_, _ = helper(C0, C0, mkmap())
check("helper: no new commit on main means nothing to catch up on (a retest answer, never a skip)", rc_ == 1 and "no new commits" in out_, (rc_, out_))
rc, out, err = helper("nosuchrev", "main", mkmap())
check("helper: a revision git cannot read is a retest, not a crash", rc == 1 and out.startswith("retest: git "), (rc, out, err))
r = subprocess.run([sys.executable, HELPER, "--repo", str(rp), "--head", "main", "--main", "main"], capture_output=True, text=True)
check("helper: no map given is a retest", r.returncode == 1 and r.stdout.strip() == "retest: no suite map was given", (r.returncode, r.stdout))
bad_suites = {**good_suites, "alpha": {**good_suites["alpha"], "files": [["not", "hashable"]]}}   # a map this reads wrongly: a bug of the check, not a reason to retest
rc, out, err = helper(pr_m, mn_m, mkmap(suites=bad_suites), name="map-bug.json")
check("helper: an exception that is none of its reasons to retest (a map it reads wrongly): exit 2, a `retest: the check failed itself` line on stdout, the traceback on stderr (release.sh retests on anything but a skip)",
      rc == 2 and out.startswith("retest: the check failed itself (TypeError") and "Traceback" in err, (rc, out, err[-300:]))
doc = pathlib.Path(HELPER).read_text().split('"""')[1]
check("helper: the docstring states what the exit codes are (0 skip, 1 retest, 2 the check failed itself) and that the map's run commit is compared", "Exit 2: the check failed itself" in doc and "caught in\nmain()" in doc and "head sha equals the map's commit" in doc, doc[-900:])
many = {f"manyfile_{i:02d}.txt": "x\n" for i in range(15)}
many_map = mkmap(suites={**good_suites, "alpha": {**good_suites["alpha"], "files": ["lib_one.txt", "lib_shared.txt"] + list(many)}, "beta": {**good_suites["beta"], "dirs": []}})   # added files reach the suites that listed their directory: beta lists none here
rc, out, err = helper(branch("pr-many", many), branch("main-many", chg("lib_two.txt")), many_map)
check("helper: a side with 15 files names 12 of them and counts the rest", rc == 0 and "changed 15 file(s)" in out and "manyfile_11.txt and 3 more" in out and "manyfile_12.txt" not in out, (rc, out))

# the published map: the newest unexpired artifact named suitemap from a run on main, read with gh api and kept by artifact id
import io, zipfile
FAKEBIN = rt / "fakebin"; FAKEBIN.mkdir()
(FAKEBIN / "gh").write_text('''#!/bin/sh
echo "$*" >> "$FAKE_DIR/gh.log"
[ -z "${FAKE_FAIL:-}" ] || { echo "gh: boom" >&2; exit 1; }
case "$*" in
  "api repos/example-owner/stackshot/actions/artifacts?name=suitemap&per_page="*)   # honours per_page like the API: the first N of the newest-first list
    n="${2##*per_page=}"; python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); d["artifacts"]=d["artifacts"][:int(sys.argv[2])]; print(json.dumps(d))' "$FAKE_DIR/list.json" "$n" ;;
  "api repos/example-owner/stackshot/actions/artifacts/"*"/zip") [ -z "${FAKE_ZIPFAIL:-}" ] || exit 1; cat "$FAKE_DIR/map.zip" ;;
  *) exit 1 ;;
esac
'''); (FAKEBIN / "gh").chmod(0o755)
def zipped(m):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z: z.writestr("map.json", json.dumps(m))
    return b.getvalue()
def published(arts, m=None):
    (rt / "list.json").write_text(json.dumps({"artifacts": arts})); (rt / "map.zip").write_bytes(zipped(m or mkmap()))
    (rt / "gh.log").unlink(missing_ok=True)
ART = lambda i, **kw: {"id": i, "name": "suitemap", "expired": False, "workflow_run": {"head_branch": "main", "head_sha": C0}, **kw}
def slug_run(head, main_, cache, **env):
    (rt / "gh.log").unlink(missing_ok=True)
    r = subprocess.run([sys.executable, HELPER, "--repo", str(rp), "--head", head, "--main", main_, "--slug", "example-owner/stackshot", "--cache", str(cache)], capture_output=True, text=True, timeout=60,
                       env={**os.environ, "PATH": f"{FAKEBIN}:" + os.environ["PATH"], "FAKE_DIR": str(rt), **env})
    return r.returncode, r.stdout.strip(), (rt / "gh.log").read_text().splitlines() if (rt / "gh.log").exists() else []
pr_ = branch("pr-pub", chg("lib_one.txt")); mn_ = branch("main-pub", chg("lib_two.txt")); cache = rt / "cache"
published([ART(77)])
rc, out, calls = slug_run(pr_, mn_, cache)
check("helper: the published map is the newest artifact named suitemap: listed (one call), downloaded (one call), read from the zip's map.json, kept by artifact id",
      rc == 0 and out.startswith("skip: ") and len(calls) == 2 and calls[1].endswith("artifacts/77/zip") and sorted(p.name for p in cache.iterdir()) == ["suitemap-77.json"], (rc, out, calls, list(cache.iterdir())))
rc, out, calls = slug_run(pr_, mn_, cache, FAKE_ZIPFAIL="1")
check("helper: the same artifact again is read from the cache: only the list is asked, so a download that would fail does not matter", rc == 0 and out.startswith("skip: ") and len(calls) == 1, (rc, out, calls))
published([ART(78), ART(77)])
rc, out, calls = slug_run(pr_, mn_, cache)
check("helper: a newer artifact is downloaded and the older one in the cache goes", rc == 0 and calls[-1].endswith("artifacts/78/zip") and sorted(p.name for p in cache.iterdir()) == ["suitemap-78.json"], (rc, calls, list(cache.iterdir())))
published([ART(80, expired=True), ART(79, workflow_run={"head_branch": "some-branch"})])
rc, out, calls = slug_run(pr_, mn_, cache)
check("helper: an expired artifact, or one from a run that was not on main, is no map", rc == 1 and out.startswith("retest: no suite map is published") and len(calls) == 1, (rc, out, calls))
# queue branches publish a map on every push too: main's artifact can sit behind more than ten of theirs (the page the helper asks for must reach it)
QART = lambda i: ART(i, workflow_run={"head_branch": "queue/x", "head_sha": "e" * 40})
published([QART(200 + i) for i in range(12)] + [ART(77)])
rc, out, calls = slug_run(pr_, mn_, rt / "cache2q")
check("helper: main's map is found behind 12 newer artifacts from queue branches (one page asks for enough)", rc == 0 and out.startswith("skip: ") and calls[-1].endswith("artifacts/77/zip") and "per_page=100" in calls[0], (rc, out, calls))
published([])
rc, out, calls = slug_run(pr_, mn_, rt / "cache2")
check("helper: no artifact at all is a retest", rc == 1 and "no suite map is published" in out, (rc, out))
published([ART(81)])
rc, out, calls = slug_run(pr_, mn_, rt / "cache3", FAKE_FAIL="1")
check("helper: gh failing is a retest, not a crash", rc == 1 and out.startswith("retest: the suite map cannot be listed"), (rc, out))
rc, out, calls = slug_run(pr_, mn_, rt / "cache4", FAKE_ZIPFAIL="1")
check("helper: a download that fails is a retest, and nothing is cached", rc == 1 and "cannot be downloaded" in out and not (rt / "cache4").exists(), (rc, out))
(rt / "map.zip").write_bytes(b"this is not a zip")
rc, out, calls = slug_run(pr_, mn_, rt / "cache5")
check("helper: a download that is not a zip holding map.json is a retest", rc == 1 and "not a zip holding map.json" in out, (rc, out))
published([ART(82)], m=mkmap(age_h=100))
rc, out, calls = slug_run(pr_, mn_, rt / "cache6")
check("helper: the published map is judged like any other (this one is stale)", rc == 1 and "stale" in out, (rc, out))
published([ART(83, workflow_run={"head_branch": "main", "head_sha": "f" * 40})])
rc, out, calls = slug_run(pr_, mn_, rt / "cache7")
check("helper: the map says it is of one commit but the run that published it was on another: retest, saying so", rc == 1 and "the run that published it was on fffffff" in out, (rc, out))
published([ART(84, workflow_run={"head_branch": "main"})])
rc, out, calls = slug_run(pr_, mn_, rt / "cache8")
check("helper: GitHub names no commit for the publishing run: the map cannot be confirmed to be of its own commit: retest", rc == 1 and "a commit GitHub did not name" in out, (rc, out))
published([ART(85)])
rc, out, calls = slug_run(pr_, mn_, rt / "cache9")
check("helper: the run's head sha equals the map's commit: the map is used (skip)", rc == 0 and out.startswith("skip: "), (rc, out))
check("tests.yml publishes the map as the artifact release.sh reads, on main's push run only", "name: suitemap\n" in WF0 and "actions/upload-artifact@v4" in WF0 and
      WF0.split("publish the map for release.sh")[1].split("- name:")[0].count("github.event_name == 'push'") == 1, "workflow")
STEP = WF0.split("name: publish the map for release.sh")[1].split("- name:")[0]
check("tests.yml: the publishing step never turns main's run red (continue-on-error), a repeated upload of the same name replaces it (overwrite), and the map under the hidden folder .suitemap is uploaded (include-hidden-files)",
      "continue-on-error: true" in STEP and "overwrite: true" in STEP and "include-hidden-files: true" in STEP and "path: .suitemap/map.json" in STEP, STEP)
for fn in ("README.md", "CONTRIBUTING.md"):
    para = [ln for ln in pathlib.Path(STACK, fn).read_text().splitlines() if "tools/retest_skip.py" in ln and "suitemap" in ln][0]
    check(f"{fn}: the paragraph on the retest skip names tests/pyproject.toml, tests/uv.lock, *.lock and the script block among the always-retest changes, and the dependency rule",
          all(w in para for w in ("tests/pyproject.toml", "tests/uv.lock", "*.lock", "# /// script", "import")), fn)

# ---- 14. covering runs: a release is satisfied by a run on any commit that contains its merge commit M. Three PRs (#38, #41 and #42) merge close together
# in a row; main's workflow runs one run at a time and cancels a queued run when a newer push arrives, so the runs on #38's and #42's merges are cancelled, the run on
# #41's own merge passes, and the run on the newest commit is queued behind it. The history is linear, oldest first: A (#38's merge), B (#41's), C (#42's), D (the tip).
SA, SB, SC, SD = "a" * 40, "b" * 40, "c" * 40, "d" * 40
INC_HIST = ",".join([SA, SB, SC, SD])
INC_RUNS = json.dumps([{"databaseId": 14, "headSha": SD}, {"databaseId": 13, "headSha": SC}, {"databaseId": 12, "headSha": SB}, {"databaseId": 11, "headSha": SA}])
def inc(name, oid, **kw):   # the old path (no up-to-date tip is readable), release of the PR whose merge commit is OID, the four runs
    return scenario(name, **{**dict(merge="ok", runs=INC_RUNS, history=INC_HIST, merge_oid=oid), **kw})
s = inc("cover-41", SB, main11="replaced", main12="pass", main13="replaced", main14="queued")
check("#41: three merges, two runs cancelled, the run on its own merge passed, the tip still queued: deploys at once on M's passing run, pinned to M",
      s["rc"] == 0 and s["deployed"] and not s["sleeps"] and s["deploy_to"] == SB and "main's tests pass at bbbbbbb (run 12)" in s["log"] and "which contains" not in s["log"], (s["out"], s["sleeps"], s["deploy_to"]))
check("…a run on a commit before M is not read at all, and the release is green", "run view 11" not in s["gh"] and s["msg"].rstrip("\n").endswith(GREEN_ARGS) and "main at 0106c0d" in s["msg"], (s["gh"], s["msg"]))
s = inc("cover-38", SA, main11="replaced", main12="pass", main13="replaced", main14="queued")
check("#38: its own run was cancelled, the next run, on B which contains A, passed: deploys at B at once, and the log says the run is on a commit that contains the merge",
      s["rc"] == 0 and not s["sleeps"] and s["deploy_to"] == SB and "main's tests pass at bbbbbbb (run 12, on bbbbbbb, which contains aaaaaaa)" in s["log"]
      and "deploying bbbbbbb, the newest commit containing the merge aaaaaaa whose run passed" in s["log"], (s["log"], s["deploy_to"]))
s = inc("cover-42-later", SC, main13="replaced", main14="queued,queued,pending,pass")
check("#42: its run was cancelled and the tip's covering run is still queued, then going, then passes: waited for (polled every 20 s), then deployed at the tip's commit",
      s["rc"] == 0 and s["sleeps"] == ["20"] * 3 and s["deploy_to"] == SD and "main's tests pass at ddddddd (run 14, on ddddddd, which contains ccccccc)" in s["log"], (s["log"], s["sleeps"], s["deploy_to"]))
s = inc("cover-two-passed", SB, main11="replaced", main12="pass", main13="pass", main14="queued")
check("two runs that contain M passed: the deploy goes to the newest passed commit (C), the third still queued",
      s["rc"] == 0 and not s["sleeps"] and s["deploy_to"] == SC and "main's tests pass at ccccccc (run 13, on ccccccc, which contains bbbbbbb)" in s["log"], (s["log"], s["deploy_to"]))

# a cancelled run with no later run covering M: waited for until the cap, then failed (before the deploy) with both limits named; the cancelled run named
s = inc("cover-cancelled-only", SC, runs=json.dumps([{"databaseId": 13, "headSha": SC}]), main13="replaced", extra={"RELEASE_WAIT_MAIN": "60", "RELEASE_CAP_MAIN": "60"})
check("a cancelled run and no later run: not a failure, waited 20 s three times until the cap, then FAILED at main's tests (merged, not deployed) naming both limits and the cancelled run",
      s["rc"] == 1 and not s["deployed"] and s["sleeps"] == ["20"] * 3
      and "FAILED at main's tests: no finished run on main covers ccccccc after 1 min since the merge (the cap is 1 min) and 0 min since a covering run started (the limit is 1 min); the run 13 on ccccccc was cancelled and no later run covers ccccccc: merged, not deployed" in s["msg"],
      (s["msg"], s["sleeps"]))
check("…the lock is free after, and the red report got no fd 9", lock_free(s), s["client_fd9"])
check("…and the log said so once, at the first look (the wait was 1 min): the cancelled run named, a later run that contains the merge waited for, GitHub reads said honestly",
      s["log"].count("main's runs covering ccccccc were canceled (run 13 on ccccccc, the newest one); waiting for a later main run that contains it, reading main's runs from GitHub every 20 s") == 1, s["log"])
# the same state held for 12 min (a release that logged nothing for a long time): one line every 5 min on the test's clock (20 s sleeps), at 0, 5 and 10 min
s = inc("cover-cancelled-only-log", SC, runs=json.dumps([{"databaseId": 13, "headSha": SC}]), main13="replaced", extra={"RELEASE_WAIT_MAIN": "720", "RELEASE_CAP_MAIN": "720"})
check("only cancelled runs cover the merge for 12 min: a line every 5 min (three in all), not one per look and not none; the wait still ends at the cap with the same message",
      s["rc"] == 1 and not s["deployed"] and len(s["sleeps"]) == 36
      and s["log"].count("main's runs covering ccccccc were canceled (run 13 on ccccccc, the newest one); waiting for a later main run that contains it") == 3
      and "FAILED at main's tests: no finished run on main covers ccccccc after 12 min since the merge (the cap is 12 min)" in s["msg"], (s["log"], len(s["sleeps"]), s["msg"]))
s = inc("cover-cancelled-then-pass-log", SC, main13="replaced", main14="queued,pass")
check("a cancelled run with a later covering run (queued, then passing): that is not the canceled-only state, so no canceled line is logged",
      s["rc"] == 0 and "were canceled" not in s["log"], s["log"])
# the next state after a cancelled run: a later covering run going (read from GitHub, the ci-runs file lists nothing). It used to log nothing at all; now one line every 5 min on the test's clock
s = inc("cover-running-log", SC, main13="replaced", main14=",".join(["pending"] * 40 + ["pass"]))
RUNNING_LINE = "main's run 14 is running, on ddddddd, which contains ccccccc ("
check("a cancelled run, then the covering run going for 13 min (40 polls of 20 s): the log says so every 5 min (at 0, 5 and 10 min), with the run, its commit, the minutes so far and that GitHub is read, then it passes",
      s["rc"] == 0 and s["deploy_to"] == SD and len(s["sleeps"]) == 40
      and s["log"].count(RUNNING_LINE) == 3 and s["log"].count("min so far); waiting for it to finish, reading main's runs from GitHub every 20 s") == 3
      and RUNNING_LINE + "0 min so far)" in s["log"] and RUNNING_LINE + "5 min so far)" in s["log"] and RUNNING_LINE + "10 min so far)" in s["log"], (s["log"], len(s["sleeps"])))
s = inc("cover-running-short", SC, main13="replaced", main14="pending,pending,pass")
check("a covering run going for 40 s only: one line (the first look), not one per poll",
      s["rc"] == 0 and s["log"].count("is running, on ddddddd, which contains ccccccc (") == 1, s["log"])

# a failed covering run fails the release as before; the oldest commit that failed decides, and the log names its run
s = inc("cover-fail-own", SC, main13="fail", live=NOTLIVE)
check("a failed run on M itself: fails at once, merged and not deployed, red, no wait",
      s["rc"] == 1 and not s["deployed"] and not s["sleeps"] and "FAILED at main's tests: the run on main for ccccccc failed (run every suite, measured=failure;" in s["msg"]
      and "decided it" not in s["msg"] and "merged, not deployed" in s["msg"] and "--release" not in s["msg"], (s["msg"], s["sleeps"]))
s = inc("cover-fail-later", SB, main12="replaced", main13="fail", main14="pass", live=NOTLIVE)
check("M's own run was cancelled and the next commit's run failed, with no pass on M or between: the release fails, judged by that oldest failed commit, which the message and the log name; the later pass is not waited for",
      s["rc"] == 1 and not s["deployed"] and "run view 14" not in s["gh"]
      and "FAILED at main's tests: the run on main for ccccccc failed (run every suite, measured=failure;" in s["msg"]
      and "ccccccc is the oldest commit after the merge bbbbbbb whose run failed, and no run on bbbbbbb or between them passed, so that run decided it" in s["msg"]
      and "the run 13 on ccccccc decided: the oldest commit that failed after the merge bbbbbbb" in s["log"], (s["msg"], s["log"]))
s = inc("cover-fail-after-pass", SB, main12="pass", main13="fail", main14="fail")
check("M's run passed and a later commit's run failed (and the one after it too): the failure is that later commit's, not this release's: deploys at M, the log names the oldest failed run",
      s["rc"] == 0 and s["deployed"] and s["deploy_to"] == SB and "run view 14" not in s["gh"] and not s["sleeps"]
      and "the run 13 on ccccccc failed after the pass on bbbbbbb: judged by the oldest commit that failed, which is not this release, so the pass on bbbbbbb decides" in s["log"], (s["log"], s["deploy_to"]))
s = inc("cover-fail-between", SA, main11="pass", main12="fail", main13="pass", main14="queued")
check("A passed, B failed, C passed after it: the oldest failure bounds the pass, so the deploy goes to A, never to C",
      s["rc"] == 0 and s["deploy_to"] == SA and "main's tests pass at aaaaaaa (run 11)" in s["log"], (s["log"], s["deploy_to"]))

# the limit counts from when a covering run starts (in progress), not from the merge
RUN14 = json.dumps([{"databaseId": 14, "headSha": SD}])
s = inc("cover-wait-from-start", SD, runs=RUN14, main14="queued,queued,queued,queued,queued,pending,pending,pass", extra={"RELEASE_WAIT_MAIN": "60"})
check("queued for five polls (100 s, more than the 60 s limit), then 40 s in progress, then passes: deployed; the queue did not use the run's limit up",
      s["rc"] == 0 and s["deployed"] and s["sleeps"] == ["20"] * 7 and s["deploy_to"] == SD, (s["out"], s["sleeps"]))
s = inc("cover-wait-limit", SD, runs=RUN14, main14="queued,queued,pending", extra={"RELEASE_WAIT_MAIN": "60"})
check("queued for two polls, then in progress and never done: gives up 60 s after it started (five polls in all, not three), unknown, merged and not deployed, both limits named",
      s["rc"] == 1 and not s["deployed"] and s["sleeps"] == ["20"] * 5
      and "no finished run on main covers ddddddd after 1 min since the merge (the cap is 180 min) and 1 min since a covering run started (the limit is 1 min): merged, not deployed" in s["msg"], (s["msg"], s["sleeps"]))
s = inc("cover-wait-cap", SD, runs=RUN14, main14="queued", extra={"RELEASE_WAIT_MAIN": "60", "RELEASE_CAP_MAIN": "100"})
check("queued and never starting: the cap from the merge ends the wait (five polls), whatever the run's own limit",
      s["rc"] == 1 and not s["deployed"] and s["sleeps"] == ["20"] * 5 and "no finished run on main covers ddddddd after 1 min since the merge (the cap is 1 min) and 0 min since a covering run started" in s["msg"], (s["msg"], s["sleeps"]))
s = inc("cover-wait-restart", SD, runs=json.dumps([{"databaseId": 14, "headSha": SD}, {"databaseId": 15, "headSha": SD}]), main14="pending,pending,replaced", main15="pending,pending,pass", extra={"RELEASE_WAIT_MAIN": "60"})
check("a run going for 40 s is cancelled and another covering run starts: its limit starts again from its own start (not from the first), so it can finish",
      s["rc"] == 0 and s["deployed"] and "main's tests pass at ddddddd (run 15)" in s["log"], (s["out"], s["sleeps"]))

# the waits are read off the clock, not counted in polls: each look at main's runs costs 40 s here besides the 20 s sleep, so a 100 s cap ends after two sleeps, not five
s = inc("cover-clock", SD, runs=RUN14, main14="queued", poll_cost="40", extra={"RELEASE_WAIT_MAIN": "60", "RELEASE_CAP_MAIN": "100"})
check("a look that takes time counts: with 40 s a look and 20 s a sleep the 100 s cap is reached after two sleeps (counting sleeps would have waited five), the line naming the minutes from the clock",
      s["rc"] == 1 and not s["deployed"] and s["sleeps"] == ["20"] * 2 and "after 2 min since the merge (the cap is 1 min)" in s["msg"], (s["msg"], s["sleeps"]))
# a run on a commit this checkout does not have (not fetched yet) is skipped, whatever state GitHub says; a re-run of an older commit, with a later id, keeps its place by commit
s = inc("cover-unfetched", SB, runs=json.dumps([{"databaseId": 99, "headSha": "9" * 40}, *json.loads(INC_RUNS)]), main99="pass", main11="replaced", main12="pass", main13="replaced", main14="queued")
check("a main run on a commit the checkout does not have is no cover (not read at all), whatever its state: the release still deploys on B",
      s["rc"] == 0 and s["deploy_to"] == SB and "run view 99" not in s["gh"], (s["gh"], s["deploy_to"]))
s = inc("cover-rerun-order", SB, runs=json.dumps([{"databaseId": 12, "headSha": SB}, {"databaseId": 20, "headSha": SD}, {"databaseId": 21, "headSha": SC}]), main12="replaced", main20="fail", main21="pass")
check("a re-run of an older commit (C, run 21) created after the tip's run (D, run 20) keeps its place by commit: B cancelled, C passed, D failed after it: deploys at C (ordered by run id the failure on D would have come first and failed the release)",
      s["rc"] == 0 and s["deploy_to"] == SC and "the run 20 on ddddddd failed after the pass on ccccccc" in s["log"], (s["log"], s["deploy_to"]))

# the merge commit: from GitHub; the error path knows it already; when GitHub does not say, main's tip as before, said in the log
s = inc("cover-oid-view", SB, main12="pass", main13="replaced", main14="queued")
check("the merge commit is read from the PR (one call) before the wait", s["gh"].count("--json mergeCommit") == 1 and s["deploy_to"] == SB, s["gh"])
s = inc("cover-oid-a", SB, main12="pass", main13="replaced", main14="queued", merge="fail", after="merged", merged_from="1")
check("the merge call errored but the PR reads MERGED: the commit is the one that read gave (full sha), no further call for it",
      s["rc"] == 0 and "--json mergeCommit" not in s["gh"].replace("state,mergeCommit", "") and "merged at bbbbbbb; carrying on" in s["log"] and s["deploy_to"] == SB, (s["gh"], s["log"]))
s = scenario("cover-oid-none", merge="ok", merge_oid="none", history=f"{HEADSHA},0106c0de0106c0de0106c0de0106c0de0106c0de")
check("GitHub does not give the merge commit: three reads over two 5 s sleeps, then main's tip as it is (it contains the PR head), said in the log; it deploys on that tip's run",
      s["rc"] == 0 and s["sleeps"] == ["5", "5"] and "GitHub did not give the merge commit of PR #23; looking for main's runs on its tip 0106c0d as it is now (it contains the PR head)" in s["log"]
      and s["gh"].count("--json mergeCommit") == 3, (s["log"], s["sleeps"], s["gh"]))
s = scenario("cover-oid-stale", merge="ok", merge_oid="none", history=f"0106c0de0106c0de0106c0de0106c0de0106c0de,{HEADSHA}")
check("GitHub does not give the merge commit and origin/main is at a tip from before the merge (it does not contain the PR head): fails, merged and not deployed, never deploys the old tip on its pass",
      s["rc"] == 1 and not s["deployed"] and "FAILED at merge commit: cannot find the merge commit of PR #23: GitHub did not give it, and main's tip 0106c0d does not contain the PR head abc1234, so it is from before the merge" in s["msg"]
      and "run view" not in s["gh"], (s["msg"], s["gh"]))
s = scenario("cover-oid-fetch-fails", merge="ok", merge_oid="none", history=f"{HEADSHA},0106c0de0106c0de0106c0de0106c0de0106c0de", fetch_fails="999")
check("…and when that fetch fails (not silenced): three tries over two 2 s sleeps, then fails naming git's error, nothing deployed",
      s["rc"] == 1 and not s["deployed"] and s["sleeps"] == ["5", "5", "2", "2"]
      and "FAILED at merge commit: cannot find the merge commit of PR #23: GitHub did not give it and main cannot be fetched (error: fetching ref refs/remotes/origin/main failed: incorrect old value provided)" in s["msg"]
      and "run view" not in s["gh"], (s["msg"], s["sleeps"]))

# the same rule for the fast path's watch after the deploy (main_green post)
s = fast("post-covered", merge="ok", runs=json.dumps([{"databaseId": 8, "headSha": NEWER}, {"databaseId": 7, "headSha": MERGE}]), main7="cancelled", main8="pass")
check("after the fast deploy: the run on the merge was cancelled, a later run on a commit that contains it passed: not unknown, no rollback; recorded as the last good commit, the log names the later commit",
      s["rc"] == 0 and s["deploys"] == [MERGE] and not red(s) and s["lastgood"] == MERGE and "main's tests passed on 0106c0d (run 8, on 0107c0d, which contains 0106c0d)" in s["log"], (s["msgs"], s["log"], s["lastgood"]))
s = fast("post-covered-list", merge="ok", runs=json.dumps([{"databaseId": 8, "headSha": NEWER, "status": "completed", "conclusion": "success", "attempt": 1},
                                                            {"databaseId": 7, "headSha": MERGE, "status": "completed", "conclusion": "cancelled", "attempt": 1}]), main7="pass", main8="pass")
check("a run the list says is completed and cancelled is skipped with no run view; the later run decides, and the list asks for status, conclusion and attempt",
      s["rc"] == 0 and "run view 7" not in s["gh"] and "run view 8" in s["gh"] and "--json databaseId,headSha,status,conclusion,attempt" in s["gh"] and not red(s), (s["gh"], s["msgs"]))
s = fast("post-covered-later", merge="ok", runs=json.dumps([{"databaseId": 8, "headSha": NEWER}, {"databaseId": 7, "headSha": MERGE}]), main7="replaced", main8="queued,pending,pass")
check("…a covering run still queued is waited for (two 20 s polls) and passes: green",
      s["rc"] == 0 and s["deploys"] == [MERGE] and not red(s) and s["sleeps"] == ["20", "20"] and "(run 8, on 0107c0d, which contains 0106c0d)" in s["log"], (s["msgs"], s["sleeps"]))
s = fast("post-pass-then-fail", merge="ok", runs=json.dumps([{"databaseId": 8, "headSha": NEWER}, {"databaseId": 7, "headSha": MERGE}]), main7="pass", main8="fail", heads=f"{BASE},{MERGE}")
check("after the fast deploy: the run on the merge passed and the next commit's failed: not this release's, no rollback, the log names the failed run",
      s["rc"] == 0 and s["deploys"] == [MERGE] and not red(s) and s["lastgood"] == MERGE and "the run 8 on 0107c0d failed after the pass on 0106c0d" in s["log"], (s["msgs"], s["deploys"], s["log"]))
s = fast("post-fail-later", merge="ok", runs=json.dumps([{"databaseId": 8, "headSha": NEWER}, {"databaseId": 7, "headSha": MERGE}]), main7="replaced", main8="fail", heads=f"{BASE},{MERGE}")
check("after the fast deploy: the run on the merge was cancelled and the next commit's failed: rolled back to the last good commit, the report naming the commit that decided",
      s["rc"] == 1 and s["deploys"] == [MERGE, f"rollback {GOOD}"] and "the run on main for 0107c0d failed" in red(s)[0]
      and "0107c0d is the oldest commit after the merge 0106c0d whose run failed, and no run on 0106c0d or between them passed, so that run decided it" in red(s)[0], (s["deploys"], s["msgs"]))
# the board item on the post-deploy check: a finished green run whose step results are not in yet is waited for, never rolled back
s = fast("post-late", merge="ok", main7="late,late,pass")
check("after the fast deploy: completed and green but the suites step has no conclusion yet: waited for (two 20 s polls), then passes: no rollback, no red report, recorded as the last good commit",
      s["rc"] == 0 and s["deploys"] == [MERGE] and not red(s) and s["sleeps"] == ["20", "20"] and s["lastgood"] == MERGE and "main's tests passed on 0106c0d (run 7)" in s["log"], (s["rc"], s["deploys"], s["msgs"], s["sleeps"], s["lastgood"]))
s = fast("post-late-never", merge="ok", main7="late", heads=f"{BASE},{MERGE}", extra={"RELEASE_WAIT_STEPS": "60"})
check("after the fast deploy: the step results never arrive: given up after RELEASE_WAIT_STEPS and failed like any failed run (rolled back), the report saying the step results never arrived",
      s["rc"] == 1 and s["deploys"] == [MERGE, f"rollback {GOOD}"] and s["sleeps"] == ["20"] * 3 and "step results never arrived in 1 min" in red(s)[0], (s["deploys"], s["sleeps"], s["msgs"]))
s = fast("post-queued-forever", merge="ok", main7="queued", extra={"RELEASE_CAP_MAIN": "100"})
check("after the fast deploy: a covering run that never starts is given up at the cap, unknown: deployed and NOT rolled back, both limits named",
      s["rc"] == 1 and s["deploys"] == [MERGE] and s["sleeps"] == ["20"] * 5 and "the cap is 1 min) and 0 min since a covering run started (the limit is 90 min): deployed at 0106c0d and NOT rolled back" in red(s)[0], (s["msgs"], s["sleeps"]))


# ---- 15. the CI-run poller: sala keeps a file of the repo's newest runs; a fresh one that shows the commit's run still going makes a cycle wait with no GitHub call.
# Anything else (completed, not listed, exit 3/4/5, garbage, no salamander) is the GitHub read, which alone decides. salamander's calls are in s["sal"], one line each.
SAL_ARGS = f"ci-runs example-owner/stackshot --sha {HEADSHA} --max-age 120"
def pr_reads(s): return s["gh"].count("pr checks 23")
def run_lists(s): return s["gh"].count("run list --repo")
def fetches(s): return s["git"].splitlines().count("fetch --quiet origin main")
s = scenario("pr-wait-poller", merge="ok", salamander="running,queued,completed")
check("PR checks: the poller shows the head's run going (in progress, then queued): two cycles wait with no `gh pr checks`; it shows completed: the GitHub read, once, passes",
      s["rc"] == 0 and s["deployed"] and s["sleeps"] == ["20", "20"] and pr_reads(s) == 1 and "checks pass" in s["log"], (s["rc"], s["sleeps"], s["gh"], s["out"]))
check("PR checks: salamander is asked about the PR head, with the 120 s age, in the repo's own name; the log says the wait is on the ci-runs file (a line at the start)",
      s["sal"][0] == SAL_ARGS and s["log"].count("waiting on the ci-runs file, no GitHub call") == 1 and f"checks on {HEADSHA[:7]}: 1 of 1 run(s) of {HEADSHA[:7]} not completed" in s["log"], (s["sal"][:2], s["log"]))
s = scenario("pr-wait-poller-forever", merge="ok", salamander="running", extra={"RELEASE_WAIT_CHECKS": "300"})
check("PR checks: a run the poller shows going for good never makes a GitHub call, and the cap still ends the wait (5 min here): FAILED at checks, nothing merged",
      s["rc"] == 1 and not s["deployed"] and pr_reads(s) == 0 and len(s["sleeps"]) == 15 and "still pending after 5 min" in s["msg"] and not merges(s), (s["rc"], s["sleeps"][:3], s["gh"], s["msg"]))
s = scenario("pr-wait-poller-mixed", merge="ok", salamander="mixed,completed", checks="pass")
check("PR checks: one run of the commit completed and another still going counts as going (as sala's release.sh does), then the GitHub read",
      s["rc"] == 0 and s["sleeps"] == ["20"] and pr_reads(s) == 1, (s["sleeps"], s["gh"]))
s = scenario("pr-wait-poller-completed-fail", merge="ok", salamander="completed", checks="fail")
check("PR checks: the poller says completed (success) but the GitHub read says a check failed: the release fails on the GitHub read",
      s["rc"] == 1 and not s["deployed"] and pr_reads(s) == 1 and "FAILED at checks: a check failed" in s["msg"] and not merges(s), (s["rc"], s["msg"], s["gh"]))
s = scenario("pr-wait-poller-completed-pass", merge="ok", salamander="completed", salamander_conclusion="failure", checks="pass")
check("PR checks: the poller says the run completed with a failure but the GitHub read passes: it passes (the poller never fails a release)",
      s["rc"] == 0 and s["deployed"] and pr_reads(s) == 1 and "FAILED" not in s["log"], (s["rc"], s["log"]))
for mode in ("stale", "none", "unreadable", "usage", "garbage", "empty"):
    s = scenario(f"pr-wait-poller-{mode}", merge="ok", salamander=mode, checks="pending,pass")
    check(f"PR checks: salamander answers {mode} (exit 4 stale, 3 no file, 5 unreadable, 2 usage, 0 with no JSON, 0 with no run of the sha listed): every cycle is the GitHub read, a missing sha is no failure",
          s["rc"] == 0 and s["deployed"] and s["sleeps"] == ["20"] and pr_reads(s) == 2 and "ci-runs file" not in s["log"] and s["sal"] and s["sal"][0] == SAL_ARGS, (mode, s["rc"], s["sleeps"], s["gh"], s["log"]))
s = scenario("pr-wait-no-salamander", merge="ok", nosalamander=True, checks="pending,pass")
check("PR checks: no salamander on PATH: the GitHub read every cycle, nothing else changes",
      s["rc"] == 0 and s["deployed"] and s["sleeps"] == ["20"] and pr_reads(s) == 2 and not s["sal"] and "ci-runs file" not in s["log"], (s["rc"], s["sleeps"], s["gh"], s["sal"]))
s = scenario("pr-wait-poller-off", merge="ok", salamander="running", checks="pending,pass", extra={"RELEASE_CIRUNS_MAX_AGE": "0"})
check("RELEASE_CIRUNS_MAX_AGE=0: the poller is never asked, the GitHub read every cycle", s["rc"] == 0 and pr_reads(s) == 2 and not s["sal"], (s["gh"], s["sal"]))
s = scenario("pr-wait-poller-dated", merge="ok", salamander="running", checks="pending,pass", extra={"RELEASE_CIRUNS_MAX_AGE": "30"})
check("RELEASE_CIRUNS_MAX_AGE is the --max-age handed to salamander", s["sal"] and s["sal"][0] == SAL_ARGS.replace("--max-age 120", "--max-age 30"), s["sal"][:1])

# main's wait, the old path (3b): sequence of the stub's answers is the PR wait's first (one call), then one per look at main's run
s0 = scenario("main-wait-baseline", merge="ok", main="pending,pending,pass")
s = scenario("main-wait-poller", merge="ok", salamander="completed,running,queued,completed", main="pass")
check("main's wait: the poller shows main's push run of the merge going for two looks: no `gh run list`, no `gh run view`, and no git fetch either; the third look (completed) reads GitHub, which passes it",
      s["rc"] == 0 and s["deployed"] and s["sleeps"] == ["20", "20"] and run_lists(s) == 1 and s["gh"].count("run view 7") == 1 and "main's tests pass at 0106c0d (run 7)" in s["log"]
      and fetches(s) == fetches(s0) - 2, (s["rc"], s["sleeps"], s["gh"], fetches(s), fetches(s0), s["log"]))
check("main's wait: salamander is asked about the merge commit, and the log names the run that is waited on (a line at the start)",
      s["sal"][1] == "ci-runs example-owner/stackshot --sha 0106c0de0106c0de0106c0de0106c0de0106c0de --max-age 120"
      and s["log"].count("main's run 7 on 0106c0d: 1 of 1 run(s) of 0106c0d not completed") == 1 and "waiting on the ci-runs file, no GitHub call" in s["log"], (s["sal"], s["log"]))
s = scenario("main-wait-poller-completed-fail", merge="ok", salamander="completed", main="fail", live=NOTLIVE)
check("main's wait: the poller says the run completed (success) but the GitHub read says the suites failed: FAILED at main's tests, merged and not deployed",
      s["rc"] == 1 and not s["deployed"] and run_lists(s) == 1 and "FAILED at main's tests" in s["msg"] and "merged, not deployed" in s["msg"], (s["rc"], s["msg"]))
s = scenario("main-wait-poller-limit", merge="ok", salamander="completed,running", extra={"RELEASE_WAIT_MAIN": "60", "RELEASE_CAP_MAIN": "100000"})
check("main's wait: a run the poller shows going counts against WAIT_MAIN as a run from the GitHub read does, with no GitHub call: given up as unknown, merged and not deployed",
      s["rc"] == 1 and not s["deployed"] and run_lists(s) == 0 and "the limit is 1 min" in s["msg"] and "merged, not deployed" in s["msg"] and s["sleeps"] == ["20"] * 3, (s["rc"], s["sleeps"], s["gh"], s["msg"]))
s = scenario("main-wait-poller-pr-event", merge="ok", salamander="completed,running,running", salamander_event="pull_request", main="pass")
check("main's wait keeps main's push runs: a run of the merge commit that is a pull_request run, going, is not waited on; the GitHub read is made at once",
      s["rc"] == 0 and s["deployed"] and not s["sleeps"] and run_lists(s) == 1 and "waiting on the ci-runs file" not in s["log"], (s["sleeps"], s["gh"], s["log"]))
for mode in ("stale", "none", "unreadable", "empty"):
    s = scenario(f"main-wait-poller-{mode}", merge="ok", salamander=f"completed,{mode}", main="pending,pass")
    check(f"main's wait: salamander answers {mode}: the GitHub read (fetch, run list, run view) every look, as before",
          s["rc"] == 0 and s["deployed"] and s["sleeps"] == ["20"] and run_lists(s) == 2 and "ci-runs file" not in s["log"], (mode, s["sleeps"], s["gh"], s["log"]))
s = scenario("main-wait-no-salamander", merge="ok", nosalamander=True, main="pending,pass")
check("main's wait: no salamander on PATH: the GitHub read every look", s["rc"] == 0 and s["sleeps"] == ["20"] and run_lists(s) == 2 and not s["sal"], (s["sleeps"], s["gh"]))

# main's wait, the fast path (13): the run of the merge is watched after the deploy
s = fast("fast-poller", merge="ok", salamander="completed,running,running,completed", main="pass")
check("fast path: the deploy at the merge, then main's run watched through the poller: two looks with no GitHub call, the third reads GitHub and passes, recorded as last good; nothing else changes",
      s["rc"] == 0 and s["deploys"] == [MERGE] and s["order"] == [f"deploy:{MERGE}", "client:message", "run-view"] and s["sleeps"] == ["20", "20"] and run_lists(s) == 1 and s["lastgood"] == MERGE
      and not red(s) and lock_views(s) == ["free"] and "main's tests passed on 0106c0d (run 7)" in s["log"], (s["rc"], s["deploys"], s["order"], s["sleeps"], s["gh"], s["log"]))
s = fast("fast-poller-fail", merge="ok", salamander="completed,running,completed", main="fail", heads=f"{BASE},{MERGE}")
check("fast path: the poller shows the run completed and the GitHub read says it failed: rolled back to the last good commit, as without the poller",
      s["rc"] == 1 and s["deploys"] == [MERGE, f"rollback {GOOD}"] and "FAILED at main's tests: rolled back to 600d000" in red(s)[0] and run_lists(s) == 1, (s["deploys"], s["msgs"], s["gh"]))
s = fast("fast-poller-stale", merge="ok", salamander="completed,stale", main="pending,pass")
check("fast path: a stale poller file: the GitHub read at every look, polled every 20 s", s["rc"] == 0 and s["deploys"] == [MERGE] and s["sleeps"] == ["20"] and run_lists(s) == 2, (s["sleeps"], s["gh"]))

# the PR-checks wait looks every 60 s by default (RELEASE_POLL_PR; the suite sets 20) and shares its read between releases for RELEASE_GH_TTL s, like main's
s = scenario("pr-wait-default-poll", merge="ok", checks="pending,pending,pass", extra={"RELEASE_POLL_PR": ""})
check("PR checks: the default look is every 60 s", s["rc"] == 0 and s["deployed"] and s["sleeps"] == ["60", "60"] and pr_reads(s) == 3, (s["sleeps"], s["gh"], s["out"]))
s = scenario("pr-wait-default-cap", merge="ok", checks="pending", secs=240, extra={"RELEASE_POLL_PR": ""})
check("PR checks: the 50 min cap is the same at 60 s: 50 sleeps of 60 s, 51 looks, then FAILED at checks, nothing merged",
      s["rc"] == 1 and not s["deployed"] and s["sleeps"] == ["60"] * 50 and pr_reads(s) == 51 and "still pending after 50 min" in s["msg"] and not merges(s), (s["rc"], len(s["sleeps"]), pr_reads(s), s["msg"]))
s = scenario("pr-wait-cached", merge="ok", checks="pending,pass", extra={"RELEASE_GH_TTL": "300", "RELEASE_WAIT_CHECKS": "300"})
check("PR checks: a read is reused inside RELEASE_GH_TTL (fake sleeps move no clock): one `gh pr checks`, the pending answer reused until the cap",
      s["rc"] == 1 and pr_reads(s) == 1 and "still pending after 5 min" in s["msg"] and (s["dir"] / "releases/gh-cache").is_dir(), (s["rc"], pr_reads(s), s["msg"]))
s1 = scenario("pr-wait-shared-1", merge="ok", checks="pass", extra={"RELEASE_GH_TTL": "300"})
s2 = scenario("pr-wait-shared-2", merge="ok", checks="fail", reuse=s1, extra={"RELEASE_GH_TTL": "300"})
check("PR checks: a second release on the same box for the same head reads what the first read: no new `gh pr checks`, so it agrees with it",
      s1["rc"] == 0 and pr_reads(s1) == 1 and s2["rc"] == 0 and pr_reads(s2) == 1, (pr_reads(s1), s2["rc"], pr_reads(s2)))
s = scenario("pr-wait-cache-head", merge="ok", checks="pass", extra={"RELEASE_GH_TTL": "300"})
s_other = scenario("pr-wait-cache-other-head", merge="ok", checks="fail", reuse=s, prheads="1111111def5678abc1234def5678abc1234def56", head="1111111def5678abc1234def5678abc1234def56", extra={"RELEASE_GH_TTL": "300"})
check("PR checks: the cache key holds the PR head: another head asks GitHub again (a fresh answer, here a failure) and does not take the first head's pass",
      s["rc"] == 0 and s_other["rc"] == 1 and pr_reads(s_other) == 2 and "FAILED at checks" in s_other["msg"], (s_other["rc"], s_other["gh"], s_other["msg"]))
s = scenario("pr-wait-cache-private", merge="ok", checks="pass", extra={"RELEASE_GH_TTL": "300"})
check("PR checks: the cache folder is private to the user (mode 700)", oct((s["dir"] / "releases/gh-cache").stat().st_mode & 0o777) == "0o700", oct((s["dir"] / "releases/gh-cache").stat().st_mode & 0o777))

# ---- 16. the release queue (releases ran one after another with long idle gaps, each started only when the previous unit ended, although nothing
# stops a release from starting while another waits on main's run). `release.sh queue N [N...]` records PR numbers in order; the queue's running release (the driver) starts
# the next one itself when it is deployed; one that fails before its merge is skipped and the queue goes on; a failed main run for a merged one pauses it.
def q(name, *args, **kw):   # the front door: release.sh queue ...
    return scenario(name, args=args, front=True, pr="queue", **{"units": "", **kw})
QF = lambda queue, driver="23": {"releases/queue": "".join(f"{n}\n" for n in ([driver] if driver else []) + list(queue)), **({"releases/queue.driver": driver + "\n"} if driver else {})}   # the driver stays in the queue file until it is deployed
PAUSED = "PR #22 failed at main's tests after its merge, 2026-11-02T00:00:00Z\n"
s = q("q-add", "25", "35", "25")
check("queue: PRs are recorded in order (one queued twice stays where it is); with no queued release running the first one starts at once, as release.sh N, holds the queue, and stays in the queue file until it is deployed",
      s["rc"] == 0 and s["started"] == ["25"] and s["queue"] == ["25", "35"] and s["driver"] == "25" and "queued PR #25" in s["out"] and "PR #25 is queued already" in s["out"]
      and "release queue, in order: 25 35" in s["out"] and [l.split()[:3] for l in s["gh"].splitlines()] == [["pr", "checks", "25"], ["pr", "checks", "35"]], (s["rc"], s["started"], s["queue"], s["out"], s["gh"]))
s2 = q("q-add-more", "37", reuse=s, units="25")
check("queue: while the queue's release runs, a PR added waits in line (nothing started), and the output says who starts the next one",
      s2["rc"] == 0 and s2["started"] == ["25"] and s2["queue"] == ["25", "35", "37"] and "PR #25 is the queue's running release" in s2["out"], (s2["started"], s2["queue"], s2["out"]))
s3 = q("q-list", "--list", reuse=s, units="25")
check("queue --list: the queued PRs in order and the running one", s3["rc"] == 0 and "release queue, in order: 25 35 37" in s3["out"] and "driver: PR #25" in s3["out"], s3["out"])
s3 = q("q-drop", "--drop", "35", reuse=s, units="25")
check("queue --drop N: takes it out, the rest keep their order", s3["rc"] == 0 and s3["queue"] == ["25", "37"] and "dropped PR #35" in s3["out"] and "dropped PR #35" in s3["qlog"], (s3["queue"], s3["out"]))
s3 = q("q-drop-absent", "--drop", "999", reuse=s, units="25")
check("queue --drop of a PR that is not queued: exit 1, the queue unchanged", s3["rc"] == 1 and s3["queue"] == ["25", "37"] and "not in the release queue" in s3["out"], (s3["rc"], s3["out"]))
for nm, a in (("q-bad-number", ("abc",)), ("q-bad-empty", ()), ("q-bad-drop", ("--drop",)), ("q-bad-option", ("--fast",))):
    s3 = q(nm, *a)
    check(f"{nm}: refused with exit 2 and the usage, nothing queued or started", s3["rc"] == 2 and ("usage: release.sh queue" in s3["out"] or "is not a PR number" in s3["out"]) and not s3["queue"] and not s3["started"], (s3["rc"], s3["out"]))
s3 = q("q-start-fail", "25", "35", start_fail="25")
check("queue: a PR whose release cannot be started is logged and skipped, and the next one starts", s3["rc"] == 0 and s3["started"] == ["35"] and s3["driver"] == "35" and s3["queue"] == ["35"]
      and "could not start the release of PR #25" in s3["out"], (s3["started"], s3["out"]))
# queue refuses a PR with a failing check row (the releaser read `gh pr checks N` by hand before; now the command does): one read of the rows per PR not queued yet, refused with the failing rows printed, nothing queued, no bypass
def gh_checks(s): return [l.split()[2] for l in s["gh"].splitlines() if l.startswith("pr checks")]
s3 = q("q-check-fail", "25", "35", checks="fail")
check("queue: a PR with a failing check row is refused: exit 1, `refused: PR N has failing check rows:` and the row's name, state and link; nothing queued or started",
      s3["rc"] == 1 and "refused: PR 25 has failing check rows:\n  suites  FAILURE  https://ci.example/suites\n" in s3["out"] and "lint" not in s3["out"] and not s3["queue"] and not s3["started"]
      and "queued PR" not in s3["out"] and "refused PR #25: refused: PR 25 has failing check rows:" in s3["qlog"], (s3["rc"], s3["out"], s3["queue"], s3["started"], s3["qlog"]))
check("queue: every PR named is read and each failing one printed; one refusal queues none of them", "refused: PR 35 has failing check rows:" in s3["out"] and gh_checks(s3) == ["25", "35"], (s3["out"], s3["gh"]))
s3 = q("q-check-one-fails", "25", "35", checks="pass,fail")
check("queue: the PR with all rows passing is not refused, but the command queues nothing while another PR it names is (35 here fails)",
      s3["rc"] == 1 and "refused: PR 35 has failing check rows:" in s3["out"] and "refused: PR 25" not in s3["out"] and not s3["queue"] and not s3["started"], (s3["rc"], s3["out"], s3["queue"]))
s3 = q("q-check-shard", "25", checks="shardfail")
check("queue: a matrix shard row counts like any row (the shard's own line, the pending suites row and the passing shard are not printed)",
      s3["rc"] == 1 and "refused: PR 25 has failing check rows:\n  suites (shard 3/4)  FAILURE  https://ci.example/shard3\n" in s3["out"] and "shard 1/4" not in s3["out"] and "PENDING" not in s3["out"] and not s3["queue"],
      (s3["rc"], s3["out"], s3["queue"]))
for nm, cv, row in (("timedout", "timedout", "suites  TIMED_OUT  https://ci.example/timed-out"), ("cancel", "cancel", "suites  CANCELLED  https://ci.example/suites")):
    s3 = q(f"q-check-{nm}", "25", checks=cv)
    check(f"queue: a {nm} row refuses too", s3["rc"] == 1 and row in s3["out"] and not s3["queue"] and not s3["started"], (s3["rc"], s3["out"], s3["queue"]))
s3 = q("q-check-pending", "25", "35", checks="pending")
check("queue: a pending row does not refuse: both PRs are queued and the first one starts, as without the gate",
      s3["rc"] == 0 and s3["queue"] == ["25", "35"] and s3["started"] == ["25"] and "refused" not in s3["out"] and gh_checks(s3) == ["25", "35"], (s3["rc"], s3["out"], s3["queue"], s3["started"]))
s3 = q("q-check-skipping", "25", checks="skipping")
check("queue: skipped and passing rows queue the PR", s3["rc"] == 0 and s3["queue"] == ["25"] and s3["started"] == ["25"] and "refused" not in s3["out"], (s3["rc"], s3["out"], s3["queue"]))
s3 = q("q-check-pass", "25", "35", checks="pass")
check("queue: all rows passing queues the PRs (the read asks for the name, state, bucket and link of the rows)",
      s3["rc"] == 0 and s3["queue"] == ["25", "35"] and "queued PR #25" in s3["out"] and "pr checks 25 --repo example-owner/stackshot --json name,state,bucket,link" in s3["gh"], (s3["rc"], s3["out"], s3["queue"], s3["gh"]))
s3 = q("q-check-unreadable", "25", "35", checks="unreadable")
check("queue: a PR whose rows cannot be read (gh fails) is refused with gh's error, never queued blindly: exit 1, nothing queued or started",
      s3["rc"] == 1 and "refused: PR 25: its check rows could not be read, so it is not queued: GraphQL: Could not resolve to a PullRequest with the number of 25. (HTTP 502)" in s3["out"]
      and not s3["queue"] and not s3["started"], (s3["rc"], s3["out"], s3["queue"], s3["started"]))
s3 = q("q-check-nochecks", "25", checks="nochecks")
check("queue: gh saying no checks were reported on the PR yet is a read of no rows: queued", s3["rc"] == 0 and s3["queue"] == ["25"] and "refused" not in s3["out"], (s3["rc"], s3["out"], s3["queue"]))
s3 = q("q-check-already", "37", reuse=s, units="25", checks="fail")
check("queue: a PR queued already is not read again and keeps its place (its rows may fail now: the command adds nothing and refuses nothing)",
      s3["rc"] == 0 and s3["queue"] == ["25", "37"] and "PR #37 is queued already" in s3["out"] and "refused" not in s3["out"] and gh_checks(s3).count("37") == 1, (s3["rc"], s3["out"], s3["queue"], s3["gh"]))  # the one read is the earlier command's that queued it
s3 = q("q-check-has-no-bypass", "25", "--force", checks="fail")
check("queue: there is no bypass option: an option is only the usage error, and release.sh's text names none", s3["rc"] == 2 and not s3["queue"] and not re.search(r"RELEASE_[A-Z_]*(FORCE|SKIP_CHECK|BYPASS)", pathlib.Path(STACK, "release.sh").read_text()), (s3["rc"], s3["out"]))
home = subprocess.run(["bash", os.path.join(STACK, "release.sh"), "--help"], capture_output=True, text=True)
check("--help: names the queue's four forms and its rules", all(t in home.stdout for t in ("./release.sh queue N [N...]", "queue --list", "queue --drop N", "queue --resume", "pauses the queue", "skipped")), home.stdout[:200])

# the queue's release reaches "deployed": it starts the next queued PR's release then, before it waits on main's run
s = fast("q-deploy", merge="ok", files=QF(["25", "35"]), units="")
check("queue: the release that holds the queue starts the next queued PR when it is deployed (after the deploy and its report, before main's run), and hands the queue on",
      s["rc"] == 0 and s["deploys"] == [MERGE] and s["started"] == ["25"] and s["order"] == [f"deploy:{MERGE}", "client:message", "start:25", "run-view"]
      and s["queue"] == ["25", "35"] and s["driver"] == "25" and "release queue: started the release of PR #25 (1 more queued: 35)" in s["log"], (s["order"], s["started"], s["queue"], s["log"][-600:]))
s = scenario("q-deploy-old-path", merge="ok", files=QF(["25"]), units="")
check("queue: on the old path the next one starts at the deploy too (main's run passed before it)", s["rc"] == 0 and s["deployed"] and s["started"] == ["25"] and s["order"][-1] == "start:25" and s["queue"] == ["25"], (s["order"], s["started"]))
s = fast("q-deploy-last", merge="ok", files=QF([]), units="")
check("queue: the last queued release finds nothing more to start and lets go of the queue", s["rc"] == 0 and not s["started"] and not s["driver"] and "the release queue is empty" in s["log"], (s["started"], s["driver"]))
s = fast("q-deploy-other-driver", merge="ok", files=QF(["25"], driver="43"), units="43")
check("queue: a release started by hand while the queue's own release runs starts nothing from the queue", s["rc"] == 0 and not s["started"] and s["queue"] == ["43", "25"] and s["driver"] == "43", (s["started"], s["queue"]))
s = fast("q-deploy-dead-driver", merge="ok", files=QF(["25"], driver="43"), units="")
check("queue: a driver whose unit is gone (killed) does not stall the queue: the release that is deployed starts the queue again, with the killed one (still first in the file)", s["rc"] == 0 and s["started"] == ["43"] and s["driver"] == "43" and s["queue"] == ["43", "25"], (s["started"], s["driver"], s["queue"]))
s = fast("q-none", merge="ok", units="")
check("no queue: a release starts nothing and its report says nothing of a queue", s["rc"] == 0 and not s["started"] and "queue" not in s["msg"] and not s["driver"], (s["started"], s["msg"]))

# a queued PR whose checks fail, or that conflicts, is reported as ever and skipped: the queue goes on
s = scenario("q-skip-checks", merge="ok", checks="fail", files=QF(["25", "35"]), units="")
check("queue: a queued PR whose checks fail is FAILED at checks as ever, never merged, and skipped: the next queued PR starts and holds the queue",
      s["rc"] == 1 and not s["deployed"] and not merges(s) and "FAILED at checks: a check failed: suites=fail" in s["log"] and "FAILED at checks: a check failed: suites=fail" in s["msg"]
      and "skipped in the release queue" in s["msg"] and s["started"] == ["25"] and s["queue"] == ["25", "35"] and s["driver"] == "25" and not s["paused"]
      and "skipped PR #23: failed at checks before its merge" in s["qlog"], (s["rc"], s["started"], s["msg"], s["qlog"]))
s = scenario("q-skip-conflict", merge="ok", mergeable="CONFLICTING", files=QF(["25"]), units="")
check("queue: a queued PR that conflicts is FAILED at mergeable as ever and skipped: the next one starts",
      s["rc"] == 1 and "FAILED at mergeable: GitHub says CONFLICTING" in s["msg"] and s["started"] == ["25"] and not s["paused"], (s["started"], s["msg"]))
s = scenario("q-skip-not-driver", merge="ok", checks="fail", files=QF(["25"], driver="43"), units="43")
check("queue: a failure of a release that does not hold the queue starts nothing from it, and its report says nothing of a queue",
      s["rc"] == 1 and not s["started"] and "queue" not in s["msg"] and s["queue"] == ["43", "25"], (s["started"], s["msg"]))

# main's run fails for a merged release: the queue pauses, and the rollback and the red report run as ever
s = fast("q-main-fail", merge="ok", main="fail", heads=f"{BASE},{MERGE}", files=QF(["25", "35"]), units="")
check("queue: main's run fails after the deploy at the merge: rolled back and reported as ever, and the queue is paused (the next one had started at the deploy, the one after it waits)",
      s["rc"] == 1 and s["deploys"] == [MERGE, f"rollback {GOOD}"] and s["started"] == ["25"] and "FAILED at main's tests: rolled back to 600d000" in red(s)[0]
      and "PR #23 failed at main's tests after its merge" in s["paused"] and s["queue"] == ["25", "35"]
      and "the release queue is paused with 2 queued (25 35): release.sh queue --resume once main is fixed" in red(s)[0], (s["deploys"], s["started"], s["paused"], s["msgs"]))
sp = scenario("q-paused-next", reuse=s, pr="25", merge="ok", units="")
check("queue: a pause stops the release the queue had started already (25, started at 23's deploy, before the pause): FAILED at queue paused, nothing merged, no hand-off, still first in the queue",
      sp["rc"] == 1 and len(merges(sp)) == len(merges(s)) and sp["deploys"] == s["deploys"] and "FAILED at queue paused: the release queue is paused (PR #23 failed at main's tests after its merge" in sp["msg"]
      and "stopped before its merge, still first in the release queue" in sp["msg"] and sp["started"] == ["25"] and sp["queue"] == ["25", "35"] and not sp["driver"]
      and "PR #25 stopped by the pause before its merge: first in the queue" in sp["qlog"] and "PR #23 failed" in sp["paused"], (sp["rc"], sp["started"], sp["queue"], sp["msg"], sp["log"][-400:]))
sp = scenario("q-paused-hand", merge="ok", files={**QF(["25"], driver="43"), "releases/queue.paused": PAUSED}, units="43")
check("queue: a release started by hand while the queue is paused is not the queue's: it deploys as ever and starts nothing; the pause and the queue stay",
      sp["rc"] == 0 and sp["deployed"] and not sp["started"] and sp["queue"] == ["43", "25"] and sp["paused"] == PAUSED, (sp["rc"], sp["started"], sp["queue"], sp["paused"]))
# the order of a rollback: the pause is on disk first, the deploy lock is let go after it (the hook writes the pause, then the harness lets the lock go)
sp = fast("q-paused-at-lock", merge="ok", hold="until-waiting", lockhook=lambda d: (d / "releases/queue.paused").write_text(PAUSED), files=QF(["25"]), units="")
check("queue: a pause written before the deploy lock is let go (the rollback's order) stops the release that waits for the lock, there, before the merge",
      sp["rc"] == 1 and "another release holds the deploy lock; waiting" in sp["log"] and not merges(sp) and not sp["deploys"] and "FAILED at queue paused" in sp["msg"] and sp["queue"] == ["23", "25"] and not sp["driver"],
      (sp["rc"], sp["deploys"], sp["queue"], sp["msg"]))
sp = q("q-add-paused", "37", reuse=s)
check("queue: a PR added while it is paused waits; nothing starts", sp["rc"] == 0 and sp["started"] == ["25"] and sp["queue"] == ["25", "35", "37"] and "is paused" in sp["out"], (sp["started"], sp["out"]))
sp = q("q-list-paused", "--list", reuse=s)
check("queue --list says it is paused and why", "paused: PR #23 failed at main's tests after its merge" in sp["out"] and "release queue, in order: 25 35 37" in sp["out"], sp["out"])
sp = q("q-resume", "--resume", reuse=s)
check("queue --resume: the pause ends and the release the pause stopped (first in the queue) starts again", sp["rc"] == 0 and not sp["paused"] and sp["started"] == ["25", "25"] and sp["driver"] == "25" and sp["queue"] == ["25", "35", "37"]
      and "resumed" in sp["qlog"], (sp["started"], sp["queue"], sp["out"]))
s = scenario("q-old-path-main-fail", merge="ok", main="fail", live=NOTLIVE, files=QF(["25"]), units="")
check("queue: main's run fails on the old path (merged, not deployed): FAILED at main's tests as ever, nothing started, the queue paused; the failed PR leaves the queue",
      s["rc"] == 1 and not s["deployed"] and "FAILED at main's tests" in s["msg"] and "merged, not deployed" in s["msg"] and not s["started"] and s["queue"] == ["25"]
      and "PR #23 failed at main's tests after its merge" in s["paused"] and not s["driver"], (s["deployed"], s["started"], s["paused"], s["msg"]))
s = fast("q-main-unknown", merge="ok", main="replaced", files=QF(["25"]), units="", extra={"RELEASE_CAP_MAIN": "60"})
check("queue: a main run that cannot be read after the deploy is no failure of the code: reported as ever, the queue not paused (the next one started at the deploy)",
      s["rc"] == 1 and s["deploys"] == [MERGE] and "NOT rolled back, main's run was not read" in red(s)[0] and not s["paused"] and s["started"] == ["25"], (s["deploys"], s["paused"], s["msgs"]))
s = scenario("q-old-path-main-unknown", merge="ok", runs="[]", files=QF(["25", "35"]), units="", extra={"RELEASE_WAIT_MAIN": "60", "RELEASE_CAP_MAIN": "60"})
check("queue: on the old path a main run that cannot be read in time (merged, not deployed) is no failure: FAILED as ever, but the queue is NOT paused, the merged PR leaves it, and the next one starts",
      s["rc"] == 1 and not s["deployed"] and "no finished run on main covers 0106c0d" in s["msg"] and "merged, not deployed" in s["msg"] and not s["paused"]
      and "the release queue goes on" in s["msg"] and s["started"] == ["25"] and s["driver"] == "25" and s["queue"] == ["25", "35"], (s["paused"], s["started"], s["queue"], s["msg"]))

# the rollback takes out riders (releases deployed on top): they are merged and stay on main, so they are not queued again; the report and the log name them
s = fast("q-riders", merge="ok", main="fail", heads=f"{BASE},{LATER}", removed="5ec0000 Merge pull request #35 from agent/other;0107c0d Merge pull request #37 from agent/more", files=QF(["44"]), units="")
RIDER_NOTE = "rolled back with it, merged and not live: #35 #37; they go live with the next release once main is fixed, or ./deploy.sh once main's tip run is green"
check("queue: the PRs a rollback took out with the failed one (35, 37) are not queued again (they are merged: release.sh N would fail at pr state): the queue keeps only the one that was waiting (44), the failed PR is gone from it",
      s["rc"] == 1 and "PR #35 was rolled back with #23's failure" in "\n".join(s["msgs"]) and s["queue"] == ["44"] and "PR #23 failed at main's tests after its merge" in s["paused"]
      and "the release queue is paused with 1 queued (44)" in red(s)[0], (s["queue"], s["paused"], s["msgs"][-1]))
check("…the failed PR's report names them with how they go live, and the queue's log says they are not queued again; each one's own message says the same",
      RIDER_NOTE in red(s)[0] and "PR #35 was rolled back with PR #23: merged and not live, not queued again" in s["qlog"] and "PR #37 was rolled back with PR #23" in s["qlog"] and "back at the front" not in s["qlog"]
      and sum("it goes live with the next release once main is fixed, or ./deploy.sh once main's tip run is green" in m for m in s["msgs"]) == 2 and not any("release it again" in m for m in s["msgs"]), (s["qlog"], s["msgs"]))
s2 = q("q-riders-resume", "--resume", reuse=s)
check("queue --resume after that: the one that was waiting (44) is released again, the riders are not started", s2["rc"] == 0 and not s2["paused"] and s2["started"] == ["44", "44"] and s2["driver"] == "44" and s2["queue"] == ["44"], (s2["started"], s2["queue"], s2["out"]))
s = fast("q-no-riders", merge="ok", main="fail", heads=f"{BASE},{MERGE}", files=QF(["25"]), units="")
check("queue: a rollback that took nothing else out says nothing of riders", s["rc"] == 1 and "rolled back with it" not in red(s)[0], red(s)[0])

# the pause is on disk while the rollback holds the deploy lock, so a release waiting for the lock finds it when it gets it (it was written after the lock was let go)
s = fast("q-pause-first", merge="ok", main="fail", heads=f"{BASE},{MERGE}", files=QF(["25", "35"]), units="")
check("queue: a rollback writes the pause before its deploy runs (the lock is held and is let go after it), and the pause names the step",
      s["rc"] == 1 and s["deploys"] == [MERGE, f"rollback {GOOD}"] and s["paused_at_rollback"] == "present" and "PR #23 failed at main's tests after its merge" in s["paused"]
      and "written before the deploy lock was let go" in s["qlog"], (s["paused_at_rollback"], s["paused"], s["qlog"]))
s = fast("q-pause-first-plain", merge="ok", main="fail", heads=f"{BASE},{MERGE}")
check("no queue: a plain release.sh N whose rollback runs writes no pause at all", s["rc"] == 1 and s["deploys"] == [MERGE, f"rollback {GOOD}"] and s["paused_at_rollback"] == "absent" and not s["paused"], (s["paused_at_rollback"], s["paused"]))
s = fast("q-pause-first-deploy", merge="ok", deploy_fail="1", files=QF(["25"]), units="")
check("queue: a deploy that fails after the merge pauses the queue before the lock is let go too (the queue's log says so), and the report says it is paused",
      s["rc"] == 1 and "FAILED at deploy" in red(s)[0] and "PR #23 failed at deploy after its merge" in s["paused"] and "PR #23 failed at deploy after its merge (written before the deploy lock was let go)" in s["qlog"]
      and "the release queue is paused" in red(s)[0], (s["paused"], s["qlog"], s["msgs"]))

# a second release waits for the deploy lock while a rollback is made: it must stop at "queue paused" when it gets the lock, whoever gets it first. The rollback here is a recovery one (a release process
# ended before main's run was read), 25 was started by the queue and is waiting at the lock, the queue's log says it started 26 and the driver is 25 (it moved on at 26's deploy)
QLOG_a = "2026-11-02T00:00:00Z started PR #26 (release.sh queue); 2 in the queue\n"
seen = []
s = fast("q-lock-wait-rollback", merge="ok", runs=RUNS67, pending=PEND, main6="fail", heads=BASE, hold="until-waiting", side="25", lockhook=lambda d: seen.append((d / "releases/queue.paused").exists()),
         files={**QF([], driver="25"), "releases/queue.log": QLOG_a}, units="")
check("queue: a rollback of a PR the queue started pauses it before it takes the deploy lock: the pause is on disk when the lock held by another release is let go",
      s["rc"] == 0 and seen == [True] and s["deploys"][0] == f"rollback {GOOD}" and "PR #26 failed at main's tests after its merge" in s["paused"], (seen, s["deploys"], s["paused"], s["log"][-500:]))
check("…and the queued release that was waiting for the lock (25) stops at \"queue paused\" when it gets it: nothing merged for it, first in the queue again",
      s["side_rc"] == 1 and "another release holds the deploy lock; waiting" in s["side_log"] and "FAILED at queue paused" in s["side_log"] and "pr merge 25" not in s["gh"]
      and s["queue"] == ["25"] and "PR #25 stopped by the pause before its merge" in s["qlog"], (s["side_rc"], s["side_log"][-600:], s["queue"], s["gh"]))

# the recovery rollback of a PR the queue did not start pauses nothing, while the queue is in use
s = fast("q-recover-plain", merge="ok", runs=RUNS67, pending=PEND, main6="fail", heads=BASE, files=QF(["25"], driver="43"), units="43")
check("queue: a release that recovers a PR 26 the queue did not start (the driver is another PR, the queue's log has no start of 26) rolls it back as ever and pauses nothing",
      s["rc"] == 0 and s["deploys"][0] == f"rollback {GOOD}" and not s["paused"] and s["queue"] == ["43", "25"] and s["driver"] == "43" and s["paused_at_rollback"] == "absent", (s["paused"], s["queue"], s["driver"], s["msgs"]))
s = fast("q-recover-driver", merge="ok", runs=RUNS67, pending=PEND, main6="fail", heads=BASE, files=QF([], driver="26"), units="26")
check("queue: …and one the driver file names (26, started by the queue and not yet deployed) pauses it",
      s["rc"] == 0 and s["deploys"][0] == f"rollback {GOOD}" and "PR #26 failed at main's tests after its merge" in s["paused"] and s["paused_at_rollback"] == "present", (s["paused"], s["deploys"], s["msgs"]))

# a failure of a release the queue did not start pauses nothing
s = fast("q-plain-main-fail", merge="ok", main="fail", heads=f"{BASE},{MERGE}")
check("no queue: a plain release.sh N whose main run fails is rolled back and reported as ever and leaves no paused file", s["rc"] == 1 and s["deploys"] == [MERGE, f"rollback {GOOD}"] and "FAILED at main's tests: rolled back to 600d000" in red(s)[0]
      and not s["paused"] and "queue" not in red(s)[0] and not s["driver"] and not (s["dir"] / "releases/queue.paused").exists(), (s["paused"], s["msgs"]))
s = scenario("q-plain-old-path-fail", merge="ok", main="fail", live=NOTLIVE)
check("no queue: a plain release.sh N whose main run fails on the old path leaves no paused file", s["rc"] == 1 and "merged, not deployed" in s["msg"] and not (s["dir"] / "releases/queue.paused").exists(), s["msg"])
s = fast("q-hand-main-fail", merge="ok", main="fail", heads=f"{BASE},{MERGE}", files=QF(["25"], driver="43"), units="43")
check("queue: a release started by hand (the queue's own release is another one) whose main run fails is rolled back as ever and does not pause the queue", s["rc"] == 1 and "FAILED at main's tests: rolled back to 600d000" in red(s)[0]
      and not s["paused"] and s["queue"] == ["43", "25"] and s["driver"] == "43" and "queue" not in red(s)[0], (s["paused"], s["queue"], s["msgs"]))

# a queued release that is killed (its unit gone) is still in the queue file: listed, and --resume starts it again
s = q("q-killed-list", "--list", files=QF(["25"], driver="23"), units="")
check("queue --list: a killed queued release is still listed (first), and the output says its release is not running and that --resume starts it again",
      s["rc"] == 0 and "release queue, in order: 23 25" in s["out"] and "PR #23 was started by the queue but its release is not running" in s["out"] and "release.sh queue --resume starts it again" in s["out"], s["out"])
s2 = q("q-killed-resume", "--resume", reuse=s)
check("queue --resume: the killed release (first in the queue) is started again, the rest wait behind it", s2["rc"] == 0 and s2["started"] == ["23"] and s2["driver"] == "23" and s2["queue"] == ["23", "25"], (s2["started"], s2["queue"], s2["out"]))

# a queued release picks what the sessions need from its PR's files, as any release does (the queue passes no flag)
s = fast("q-pick-recycle", merge="ok", pickfiles="docs/a.md,client/hooks/session-start.sh", files=QF([]), units="")
check("queue: a queued PR that changes the start-loaded hook gets a recycle (recycle-due on the PR), reported green, with no warning",
      s["rc"] == 0 and "recycle-due" in s["msg"] and "session pick: recycle (from client/hooks/session-start.sh)" in s["log"] and "WARNING" not in s["log"] + s["msg"] and "--release" in s["msg"], (s["log"][-500:], s["msg"]))
s = fast("q-pick-per-call", merge="ok", pickfiles="docs/a.md,client.py,pages.py", files=QF([]), units="")
check("queue: a queued PR that changes only files run fresh at each call picks nothing: no recycle, green", s["rc"] == 0 and "recycle-due" not in s["msg"] and "session pick: nothing" in s["log"] and "--release" in s["msg"], (s["log"][-300:], s["msg"]))

# ---- 17. the merge queue, shadow (THE MERGE QUEUE, SHADOW at the top of release.sh; salamander's docs/mq.md, step 4). The host file (here the scenario's own XDG_CONFIG_HOME) says off | shadow | on; a fake
# `salamander mq` logs its calls in mq.log (add, wait) and answers from RT_MQ_ADD / RT_MQ_WAIT; a fake systemd-run starts the comparison unit at once, in the scenario.
MQ_ADD = "mq add 23 --repo example-owner/stackshot"
MQ_WAIT = "mq wait 23 --repo example-owner/stackshot --timeout 18000"
def same_as(s, b):   # the release did what `b` (a run with no queue) did: the same sleeps, gh calls and reports, each scenario's own folder (in the log path) set aside
    def sig(x): return (x["sleeps"], x["gh"].replace(str(x["dir"]), "D"), [m.replace(str(x["dir"]), "D") for m in x["msgs"]])
    return sig(s) == sig(b)
def mq_line(s): return next((l for l in s["log"].splitlines() if "merge queue (shadow): PR #23: " in l and "Old path:" in l), "")
base = scenario("mq-none", merge="ok")
check("merge queue: no host file is today's behaviour exactly: no queue call, no unit, no record, nothing about a queue in the log",
      base["rc"] == 0 and base["deployed"] and not base["mq"] and not base["sysrun"] and not base["mq_old"] and "merge queue" not in base["log"], (base["mq"], base["log"][-400:]))
s = scenario("mq-off", merge="ok", mqhost="off")
check("merge queue: mode off in the host file is the same: no queue call, no unit, the same sleeps, calls to gh and report as with no file",
      s["rc"] == 0 and s["deployed"] and not s["mq"] and not s["sysrun"] and "merge queue" not in s["log"] and same_as(s, base), (s["mq"], s["log"][-300:]))
s = scenario("mq-shadow-agree", merge="ok", mqhost="shadow")
check("shadow: the PR is queued (salamander mq add <pr> --repo <repo>) before the wait for its checks, the old path merges and deploys as ever, and the sleeps, gh calls and report are those of no queue",
      s["rc"] == 0 and s["deployed"] and s["mq"][0] == MQ_ADD and same_as(s, base)
      and 0 <= s["log"].index("merge queue (shadow): PR #23 queued") < s["log"].index("checks pass"), (s["mq"], s["log"]))
check("shadow: when the release ends a unit stackshot-mq-shadow-23-<run> is started for release.sh --mq-compare 23 <run> (the run = epoch and pid; working folder, XDG folder passed on), and it asks the queue for the verdict with the 5 h cap",
      len(s["sysrun"]) == 1 and re.search(r"--unit stackshot-mq-shadow-23-(\d+-\d+) ", s["sysrun"][0]) and re.search(r"/release\.sh --mq-compare 23 (\d+-\d+)$", s["sysrun"][0])
      and re.search(r"--unit stackshot-mq-shadow-23-(\S+) ", s["sysrun"][0]).group(1) == re.search(r"--mq-compare 23 (\S+)$", s["sysrun"][0]).group(1) and "-p WorkingDirectory=" in s["sysrun"][0]
      and f"--setenv=XDG_CONFIG_HOME={s['dir']}/xdg" in s["sysrun"][0] and s["mq"] == [MQ_ADD, MQ_WAIT], (s["sysrun"], s["mq"]))
check("shadow: the old path's record is written first (merged), and the log gets ONE comparison line: agree, with both sides named",
      s["mq_old"].startswith("merged\t") and len([l for l in s["log"].splitlines() if "Old path:" in l]) == 1 and "agree: the old path merged it and the queue's group passed" in mq_line(s)
      and "Old path: merged, live, main's tests passed" in mq_line(s) and "PR 23 tested: group g1 passed in shadow" in mq_line(s), (s["mq_old"], s["log"][-600:]))
check("shadow: the comparison line carries none of the words a waiter on the release log looks for (` done: `, ` FAILED `)",
      " done: " not in mq_line(s) and " FAILED " not in mq_line(s), mq_line(s))
s = scenario("mq-shadow-queue-fails", merge="ok", mqhost="shadow", mq_wait="failed")
check("shadow: the old path merged it and the queue's group failed: DISAGREE, in the log; the release is unchanged (done, green report)",
      s["rc"] == 0 and s["deployed"] and "DISAGREE: the old path merged it, the queue would not have" in mq_line(s) and "required check suites failed in group g1" in mq_line(s) and same_as(s, base), (mq_line(s), s["msgs"]))
s = scenario("mq-shadow-race", merge="ok", mqhost="shadow", mq_wait="ejected-merged")
check("shadow: the queue found the PR already merged by the old path: no comparison, said as a race, not a disagreement",
      s["rc"] == 0 and "no comparison: the old path merged the PR before the queue read it" in mq_line(s) and "DISAGREE" not in s["log"], mq_line(s))
s = scenario("mq-shadow-left-group", merge="ok", mqhost="shadow", mq_wait="ejected-left")
check("shadow: the old path merged the PR and the queue's only reason is that it left the group (the real merge closed it): no comparison, no verdict, neither agree nor DISAGREE",
      s["rc"] == 0 and "no comparison: no verdict, the real merge closed the PR before the queue's group finished" in mq_line(s) and "DISAGREE" not in s["log"] and "agree:" not in mq_line(s) and "left the group before the merge" in mq_line(s), mq_line(s))
s = scenario("mq-shadow-left-group-mainfail", merge="ok", mqhost="shadow", main="fail", live=NOTLIVE, mq_wait="ejected-left")
check("shadow: the same for a PR the old path merged and main's tests then failed: no verdict, not an agree",
      s["mq_old"].startswith("merged-failed\t") and "no comparison: no verdict, the real merge closed the PR" in mq_line(s) and "agree:" not in mq_line(s) and "DISAGREE" not in s["log"], (s["mq_old"], mq_line(s)))
s = scenario("mq-shadow-real-eject", merge="ok", mqhost="shadow", mq_wait="ejected-conflict")
check("shadow: a real eject reason (a conflict) after the old path merged the PR stays a DISAGREE",
      s["rc"] == 0 and "DISAGREE: the old path merged it, the queue would not have" in mq_line(s) and "conflict with main" in mq_line(s) and "no verdict" not in mq_line(s), mq_line(s))
s = scenario("mq-shadow-no-verdict", merge="ok", mqhost="shadow", mq_wait="gaveup")
check("shadow: the queue gave no verdict (exit 2): no comparison, the exit code and its words in the line", "no comparison: the queue gave no verdict" in mq_line(s) and "exit 2" in mq_line(s) and "gave up waiting" in mq_line(s), mq_line(s))
s = scenario("mq-shadow-error", merge="ok", mqhost="shadow", mq_wait="error")
check("shadow: a queue error on the wait (exit 7) is no comparison as well (it is salamander mq's own error), and the release is done", s["rc"] == 0 and s["deployed"] and "no comparison: salamander mq reported an error" in mq_line(s) and "exit 7" in mq_line(s), mq_line(s))
s = scenario("mq-shadow-refused-agree", merge="ok", mqhost="shadow", checks="fail", mq_wait="failed")
check("shadow: the PR's checks fail (the old path refuses it, FAILED at checks as ever, exit 1, a red report) and the queue's group failed too: agree",
      s["rc"] == 1 and not s["deployed"] and "FAILED at checks" in s["log"] and len(red(s)) == 1 and s["mq_old"].startswith("refused\t") and "agree: the old path refused it and the queue would not have merged it either" in mq_line(s)
      and "Old path: refused before the merge at checks: " in mq_line(s), (s["rc"], s["mq_old"], mq_line(s), s["log"][-500:]))
s = scenario("mq-shadow-refused-disagree", merge="ok", mqhost="shadow", checks="fail", mq_wait="tested")
check("shadow: the old path refuses the PR at its checks but the queue's group passed: DISAGREE", s["rc"] == 1 and "DISAGREE: the old path refused it, the queue would have merged it" in mq_line(s), mq_line(s))
s = scenario("mq-shadow-mainfail-disagree", merge="ok", mqhost="shadow", main="fail", live=NOTLIVE)
check("shadow: the old path merged it, main's tests failed it (merged, not deployed) and the queue's group passed: DISAGREE, the failure named",
      s["rc"] == 1 and s["mq_old"].startswith("merged-failed\t") and "DISAGREE: the old path merged it and main's tests then failed it, the queue's group passed" in mq_line(s) and "Old path: merged, then main's tests: " in mq_line(s), (s["mq_old"], mq_line(s)))
s = scenario("mq-shadow-mainfail-agree", merge="ok", mqhost="shadow", main="fail", live=NOTLIVE, mq_wait="failed")
check("shadow: the same with a queue group that failed too: agree", "agree: the old path merged it and main's tests then failed it, and the queue would not have merged it either" in mq_line(s), mq_line(s))
s = scenario("mq-shadow-lock-timeout", merge="ok", mqhost="shadow", hold=True, extra={"DEPLOY_LOCK_WAIT": "1"})
check("shadow: a release that stops at a lock decided nothing about the PR: queued, then no comparison (the old path did not decide), the exit status is the release's own",
      s["rc"] == 1 and "FAILED at deploy lock" in s["log"] and s["mq_old"].startswith("undecided\t") and "no comparison: the old path did not decide on the PR" in mq_line(s) and "Old path: stopped at deploy lock: " in mq_line(s), (s["rc"], mq_line(s)))
check("shadow: the failure's own report is the one a release without the queue sends (one red message)", len(red(s)) == 1 and "FAILED at deploy lock" in red(s)[0], s["msgs"])
# the queue or its tools missing or broken never fails or holds up a release
s = scenario("mq-shadow-add-fails", merge="ok", mqhost="shadow", mq_add="fail")
check("shadow: `mq add` refused (exit 1): one log line with its words, the release is done and unchanged, no wait, no unit, no record",
      s["rc"] == 0 and s["deployed"] and "salamander mq add exited 1 (salamander mq: mode is off for example-owner/stackshot" in s["log"] and "was not queued; the release goes on" in s["log"]
      and s["mq"] == [MQ_ADD] and not s["sysrun"] and not s["mq_old"] and same_as(s, base), (s["mq"], s["log"][-500:]))
# What is asserted is the timeout's own word and the hung process's end, never the wall time of the run: under strace and coverage a release takes several times its plain time, so no bound
# on seconds holds in both. The release logs "took more than ..." only when `timeout` ended the call (exit 124), and the stub, which became a sleep of 6 s under its own pid (mq-add.pid),
# is gone by the time the release has ended: killed, neither waited out nor left running.
s = scenario("mq-shadow-add-slow", merge="ok", mqhost="shadow", mq_add="slow", extra={"RELEASE_MQ_ADD_TIMEOUT": "1"})
hung = (s["dir"] / "mq-add.pid").read_text().strip() if (s["dir"] / "mq-add.pid").exists() else ""
check("shadow: `mq add` that hangs is cut at RELEASE_MQ_ADD_TIMEOUT (here 1 s): said in the log, its process is ended, the release is done and unchanged, no unit",
      s["rc"] == 0 and s["deployed"] and "salamander mq add took more than 1s, so PR #23 was not queued; the release goes on" in s["log"] and not s["sysrun"]
      and hung.isdigit() and not os.path.exists(f"/proc/{hung}"), (s["log"][-400:], hung))
s = scenario("mq-shadow-no-salamander", merge="ok", mqhost="shadow", nosalamander=True)
check("shadow: no salamander on PATH: one log line, the release is done, no unit and no record", s["rc"] == 0 and s["deployed"] and "salamander is not on PATH, so PR #23 was not queued" in s["log"] and not s["sysrun"] and not s["mq_old"], s["log"][-400:])
s = scenario("mq-shadow-unit-fails", merge="ok", mqhost="shadow", mq_unit_fail="1")
check("shadow: the comparison unit does not start: one log line pointing at `salamander mq status`, the release is done with its own exit status, the PR is queued and nothing waits for the verdict",
      s["rc"] == 0 and s["deployed"] and "the comparison unit did not start (Failed to start transient service unit" in s["log"] and "salamander mq status" in s["log"] and s["mq"] == [MQ_ADD], (s["mq"], s["log"][-400:]))
s = scenario("mq-shadow-unit-fails-red", merge="ok", mqhost="shadow", checks="fail", mq_unit_fail="1")
check("shadow: the unit failing to start leaves a failed release's exit status at 1", s["rc"] == 1 and "FAILED at checks" in s["log"] and "the comparison unit did not start" in s["log"], (s["rc"], s["log"][-400:]))
# mode on: the section 18 below (a lone PR takes this path unchanged, two or more go as a group); a host file that does not read is the old way
for nm, text in (("mq-bad-mode", 'mode = "shadwo"\n'), ("mq-bad-toml", 'mode = = shadow\n'), ("mq-bad-type", 'mode = 3\n')):
    s = scenario(nm, merge="ok", mqhost=text)
    check(f"a host file that does not read ({nm}): one log line, the queue is not used, the release goes the old way and is done", s["rc"] == 0 and s["deployed"] and "the host file does not read" in s["log"] and not s["mq"] and not s["sysrun"] and same_as(s, base), (s["rc"], s["log"][-400:]))
s = scenario("mq-host-no-mode", merge="ok", mqhost='remote = "git@github.com:example-owner/stackshot.git"\n')
check("a host file with no mode key is off (salamander's default too)", s["rc"] == 0 and s["deployed"] and not s["mq"] and "merge queue" not in s["log"], (s["mq"], s["log"][-300:]))
s = fast("mq-shadow-fast", merge="ok", mqhost="shadow")
check("shadow, up-to-date PR (deployed at the merge, main's run waited for after it): queued before the checks, compared after main's run passed, one line, the same deploy as without the queue",
      s["rc"] == 0 and s["deploys"] == [MERGE] and s["mq"] == [MQ_ADD, MQ_WAIT] and "agree: the old path merged it and the queue's group passed" in mq_line(s)
      and s["log"].index("main's tests passed on 0106c0d") < s["log"].index("Old path:"), (s["deploys"], s["mq"], s["log"][-700:]))
r = subprocess.run(["bash", str(s["dir"] / "box/release.sh"), "--mq-compare", "x"], env={**os.environ, "PATH": f"{s['dir']}/bin:" + os.environ["PATH"], "RT_DIR": str(s["dir"]), "XDG_CONFIG_HOME": str(s["dir"] / "xdg")}, capture_output=True, text=True, timeout=60)
check("release.sh --mq-compare with no PR number says its usage and exits 2", r.returncode == 2 and "usage: release.sh --mq-compare <pr> <run>" in r.stderr, (r.returncode, r.stderr))
r = subprocess.run(["bash", str(s["dir"] / "box/release.sh"), "--mq-compare", "23"], env={**os.environ, "PATH": f"{s['dir']}/bin:" + os.environ["PATH"], "RT_DIR": str(s["dir"]), "XDG_CONFIG_HOME": str(s["dir"] / "xdg")}, capture_output=True, text=True, timeout=60)
check("release.sh --mq-compare with no run says its usage and exits 2 as well", r.returncode == 2 and "usage: release.sh --mq-compare <pr> <run>" in r.stderr, (r.returncode, r.stderr))

# a rerun of the same PR while the first run's unit may still live (it waits up to 5 h): its own unit name and its own record; both comparisons land in the log
s1 = scenario("mq-rerun-1", merge="ok", mqhost="shadow", checks="fail", mq_wait="failed")
s2 = scenario("mq-rerun-2", merge="ok", mqhost="shadow", reuse=s1, mq_wait="tested")
units = [re.search(r"--unit (stackshot-mq-shadow-23-\S+) ", l).group(1) for l in s2["sysrun"]]
check("rerun: the second run of a PR starts its own unit (a different name from the first run's, which may still be waiting) and keeps its own record; the first run's record is not overwritten",
      len(units) == 2 and units[0] != units[1] and len(s2["mq_files"]) == 2 and s2["mq_old"].count("refused\t") == 1 and s2["mq_old"].count("merged\t") == 1, (s2["sysrun"], s2["mq_files"], s2["mq_old"]))
cmp_lines = [l for l in s2["log"].splitlines() if "Old path:" in l]
check("rerun: both runs are compared, each against its own record: the first agrees (refused, queue failed), the second agrees (merged, queue passed)",
      len(cmp_lines) == 2 and "agree: the old path refused it" in cmp_lines[0] and "agree: the old path merged it and the queue's group passed" in cmp_lines[1], cmp_lines)
# a deploy that fails after the merge says nothing about the PR's tests
s = scenario("mq-shadow-deploy-fails", merge="ok", mqhost="shadow", deploy_fail="1", mq_wait="tested")
check("shadow: the old path merged the PR and its deploy failed (healthz): not 'main's tests failed it', no DISAGREE, a no comparison that says the deploy failed",
      s["rc"] == 1 and "FAILED at deploy" in s["log"] and s["mq_old"].startswith("deploy-failed\t") and "no comparison: the old path merged it but its deploy failed" in mq_line(s) and "DISAGREE" not in s["log"], (s["rc"], s["mq_old"], mq_line(s), s["log"][-500:]))
s = scenario("mq-shadow-deploy-fails-queue-fails", merge="ok", mqhost="shadow", deploy_fail="1", mq_wait="failed")
check("shadow: the same with a queue group that failed: still no comparison (a deploy failure agrees with nothing)", "no comparison: the old path merged it but its deploy failed" in mq_line(s), mq_line(s))
# salamander's own error is no verdict, even at exit 1
s = scenario("mq-shadow-wait-hosterr", merge="ok", mqhost="shadow", mq_wait="hosterr")
check("shadow: `mq wait` exits 1 with salamander's own `salamander mq:` error (a host file): no comparison, never a DISAGREE from a queue that failed the PR",
      s["rc"] == 0 and "no comparison: salamander mq reported an error, not a verdict on the PR" in mq_line(s) and "DISAGREE" not in s["log"] and "unknown key" in mq_line(s), mq_line(s))
s = scenario("mq-shadow-wait-hosterr-refused", merge="ok", mqhost="shadow", checks="fail", mq_wait="hosterr")
check("shadow: the same for a PR the old path refused: no comparison, not an agree", "no comparison: salamander mq reported an error" in mq_line(s) and "agree" not in mq_line(s), mq_line(s))
# words a log waiter looks for are softened in what the line quotes
s = scenario("mq-shadow-quoted-words", merge="ok", mqhost="shadow", mq_wait="titled")
check("shadow: a queue line that quotes ` FAILED ` or ` done: ` is softened (failed, done) so a waiter on the release log never reads it as the release's result; the rest of the line is kept",
      mq_line(s) and " FAILED" not in mq_line(s) and " done:" not in mq_line(s) and "a title with failed at x and done y in it" in mq_line(s)
      and not any(" FAILED " in l or " done: " in l for l in s["log"].splitlines() if "merge queue" in l), mq_line(s))

# ---- 18. the merge queue, ON (THE MERGE QUEUE, ON in release.sh; salamander's docs/mq.md, step 5). The release queue routes by COUNT: one PR waiting is a lone release, the old path unchanged (no call to
# `salamander mq` at all, both of its shortcuts kept); two or more go as ONE group: `salamander mq add N1 N2...`, `mq wait` for each, one deploy of the merge, `done:` for each PR. The host file also names the deploy lock this
# script takes (`deploy_lock`), which is what keeps the queue's merge push out of a lone release's merge and deploy. The fake `salamander mq` answers `mq wait <pr>` per PR from RT_MQ_PRS (mq_prs=).
ON = 'mode = "on"\ndeploy_lock = "@DIR@/releases/deploy.lock"\n'
M1 = "a1a1a1a" + "0" * 33; M2 = "b2b2b2b" + "0" * 33; M3 = "c3c3c3c" + "0" * 33
HIST_G = ",".join([GOOD, BASE, M1, M2, M3])
GLOG = f"{M2} Merge pull request #25 from agent/two;{M1} Merge pull request #23 from agent/one"
MQ_ADD2 = "mq add 23 25 --repo example-owner/stackshot"
def wait_(n, slice_=300): return f"mq wait {n} --repo example-owner/stackshot --timeout {slice_}"
def prlog(s, n): p = s["dir"] / f"releases/pr-{n}.log"; return p.read_text() if p.exists() else ""
def glog(s): p = s["dir"] / "releases/group-23.log"; return p.read_text() if p.exists() else ""
def handed(s): d = s["dir"] / "releases/mq-on"; return sorted(p.name for p in d.iterdir()) if d.is_dir() else []
def grp(name, prs=("23", "25"), tip=M2, **kw):   # a group release of the PRs, as its unit runs it: the live checkout at BASE (main's tip before the group), the queue merged up to `tip`
    full = [m for m in (M1, M2, M3) if HIST_G.index(m) <= HIST_G.index(tip)]
    log = ";".join(f"{m} Merge pull request #{n} from agent/x" for m, n in reversed(list(zip(full, prs))))
    opts = dict(raw=["--run-group", *prs], pr=prs[0], mqhost=ON, units="", history=HIST_G, live=BASE, live_after=tip, tips=tip, fullshas=",".join(full), grouplog=log, docs=",".join(full),
                runs=json.dumps([{"databaseId": 7, "headSha": tip}]), mq_prs=",".join(f"{n}=merged@{m[:7]}" for m, n in zip(full, prs)))
    return fast(name, **{**opts, **kw})
def started_args(s): p = s["dir"] / "started-args"; return p.read_text().splitlines() if p.exists() else []

# -- a lone PR under mode on: the old path, no call to the queue at all
s = scenario("on-lone", merge="ok", mqhost=ON)
check("mode on, one PR: the old path exactly: merged, deployed, no `salamander mq` call of any kind, no unit, the same sleeps, gh calls and report as mode off; the log says it is released alone",
      s["rc"] == 0 and s["deployed"] and not s["mq"] and not s["sysrun"] and same_as(s, base) and "merge queue (on): PR #23 is released alone" in s["log"] and not handed(s), (s["rc"], s["mq"], s["log"][-500:]))
s = fast("on-lone-fast", merge="ok", mqhost=ON); b = fast("on-lone-fast-off", merge="ok")
check("mode on, one PR, the fast path (the live checkout is at main's tip): deployed at the merge with main's full run after, as in mode off, and no call to the queue", s["rc"] == 0 and not s["mq"] and same_as(s, b) and s["order"] == b["order"] and "main's full run follows" in s["msgs"][0], (s["order"], b["order"], s["mq"]))
s = fast("on-lone-skip", merge="ok", history=HIST_B, retest=SKIP, extra=SKIP_ON, mqhost=ON); b = fast("on-lone-skip-off", merge="ok", history=HIST_B, retest=SKIP, extra=SKIP_ON)
check("mode on, one PR, the retest skip (tools/retest_skip.py): the branch is not updated, the checks are not waited for again, deployed at the merge: the same as mode off, and no call to the queue",
      s["rc"] == 0 and not s["mq"] and "update-branch" not in s["gh"] and s["deploys"] == [MERGE] and same_as(s, b) and "was NOT retested" in s["msgs"][0] and len(rlog(s)) == 2, (s["rc"], s["mq"], s["gh"], s["log"][-400:]))
s = scenario("on-lone-nolock", merge="ok", mqhost='mode = "on"\n')
check("mode on without deploy_lock in the host file: refused before anything is touched (FAILED at mq mode, with the line to add), one red report, nothing merged or deployed, no call to the queue",
      s["rc"] == 1 and "FAILED at mq mode" in s["log"] and "deploy_lock" in s["log"] and s["lockfile"].name in s["log"] and "pr merge" not in s["gh"] and not s["deployed"] and len(red(s)) == 1 and not s["mq"], (s["rc"], s["log"][-500:], s["gh"]))
s = scenario("on-lone-otherlock", merge="ok", mqhost='mode = "on"\ndeploy_lock = "/somewhere/else.lock"\n')
check("mode on with a deploy_lock that is not the lock this script takes: refused the same way (the queue's push would not wait for a release), naming both files", s["rc"] == 1 and "FAILED at mq mode" in s["log"] and "/somewhere/else.lock" in s["log"] and not s["deployed"] and "pr merge" not in s["gh"], (s["rc"], s["log"][-500:]))
s = scenario("on-lone-marker", merge="ok", mqhost=ON, files={"releases/mq-on/pr-23": "2026-11-04T00:00:00Z handed to the merge queue by the group release led by PR #26\n"})
check("mode on: a PR a group release handed to the queue (its marker) is never merged by the old path: FAILED at mq line, naming `salamander mq drop`, nothing merged or deployed, no call to the queue, the marker stays",
      s["rc"] == 1 and "FAILED at mq line" in s["log"] and "salamander mq drop 23" in s["log"] and "pr merge" not in s["gh"] and not s["deployed"] and not s["mq"] and handed(s) == ["pr-23"], (s["rc"], s["log"][-500:], s["gh"]))
s = scenario("on-shadow-marker", merge="ok", mqhost="shadow", files={"releases/mq-on/pr-23": "x\n"})
check("a marker left in a folder under mode shadow changes nothing (the old path as ever)", s["rc"] == 0 and s["deployed"] and "mq line" not in s["log"], (s["rc"], s["log"][-300:]))

# -- the release queue routes by count
s = q("on-q-three", "23", "25", "35", mqhost=ON)
check("release queue, mode on, three waiting: ONE group release for all three, led by the first (its unit is the driver), started as release.sh --run-group; no PR started alone, no `salamander mq` call from the queue itself",
      s["rc"] == 0 and s["started"] == ["23"] and s["driver"] == "23" and s["queue"] == ["23", "25", "35"] and len(started_args(s)) == 1 and started_args(s)[0].endswith("/release.sh --run-group 23 25 35")
      and "one group through the merge queue" in s["qlog"] and not s["mq"], (s["rc"], s["started"], s["queue"], started_args(s), s["qlog"], s["out"]))
s = q("on-q-two", "23", "25", mqhost=ON)
check("release queue, mode on, two waiting: a group of two", s["started"] == ["23"] and started_args(s)[0].endswith("/release.sh --run-group 23 25"), (s["started"], started_args(s)))
s = q("on-q-one", "23", mqhost=ON)
check("release queue, mode on, one waiting: a lone release by the old path (release.sh --run 23), not a group",
      s["started"] == ["23"] and len(started_args(s)) == 1 and started_args(s)[0].endswith("/release.sh --run 23") and "--run-group" not in started_args(s)[0] and not s["mq"], (s["started"], started_args(s)))
for mode in ("shadow", "off"):
    s = q(f"on-q-three-{mode}", "23", "25", "35", mqhost=mode)
    check(f"release queue, mode {mode}, three waiting: as before, the first alone and the rest wait; no group", s["started"] == ["23"] and "--run-group" not in "".join(started_args(s)) and started_args(s)[0].endswith("/release.sh --run 23") and s["queue"] == ["23", "25", "35"], (s["started"], started_args(s)))
s = q("on-q-three-nofile", "23", "25", "35")
check("release queue, no host file, three waiting: as before", s["started"] == ["23"] and "--run-group" not in "".join(started_args(s)), (s["started"], started_args(s)))
s = q("on-q-startfail", "23", "25", "35", mqhost=ON, start_fail="23")
check("release queue, mode on: a group whose unit cannot start skips its first PR, the count is taken again, and the other two go as a group", s["started"] == ["25"] and started_args(s)[0].endswith("/release.sh --run-group 25 35") and s["queue"] == ["25", "35"] and "could not start the group release led by PR #23" in s["out"], (s["started"], started_args(s), s["queue"], s["out"]))
s = q("on-q-paused", "23", "25", mqhost=ON, files={"releases/queue.paused": "PR #22 failed\n"})
check("release queue, mode on, paused: nothing starts, group or not", s["started"] == [] and "paused" in s["out"], (s["started"], s["out"]))
s = scenario("on-group-door-one", raw=["--group", "23"], mqhost=ON, units="")
check("release.sh --group with one PR: usage, exit 2, nothing started", s["rc"] == 2 and "usage: release.sh --group" in s["out"] and not s["started"], (s["rc"], s["out"]))
s = scenario("on-rungroup-bad", raw=["--run-group", "23", "x"], mqhost=ON, units="")
check("release.sh --run-group with a word that is not a PR number: usage, exit 2, no queue call", s["rc"] == 2 and "usage: release.sh --run-group" in s["out"] and not s["mq"], (s["rc"], s["out"]))
s = scenario("on-group-door-running", raw=["--group", "23", "25"], mqhost=ON, units="23")
check("release.sh --group while the lead's unit runs: says so, exit 1, nothing started", s["rc"] == 1 and "already running" in s["out"] and not s["started"], (s["rc"], s["out"]))

# -- a group: one `mq add`, a wait for each, one deploy, a `done:` line per PR
s = grp("on-group-fast", files=QF(["25"]))
check("group of two (fast path): ONE `mq add 23 25`, then `mq wait` for each PR in turn, nothing else asked of the queue, no old-path merge (no gh pr merge, no update-branch)",
      s["rc"] == 0 and s["mq"] == [MQ_ADD2, wait_(23), wait_(25)] and "pr merge" not in s["gh"] and "update-branch" not in s["gh"], (s["rc"], s["mq"], s["gh"], glog(s)[-600:]))
check("group of two (fast path): deployed ONCE, at the later merge commit, pinned (DEPLOY_TO), before main's run is read; both merge commits go into the ride-along ledger first",
      s["deploys"] == [M2] and s["order"][:2] == [f"deploy:{M2}", "client:message"] and f"recorded the merge {M1[:7]} in the fast-ok ledger" in glog(s) and f"recorded the merge {M2[:7]} in the fast-ok ledger" in glog(s)
      and "ride along" in glog(s), (s["deploys"], s["order"], glog(s)[-900:]))
check("group of two: a `done:` line in EACH PR's own log (what a waiter and the board hooks read), the same sha; no FAILED in either",
      all(re.search(r"^.*done: [0-9a-f]{7}, restarted ", prlog(s, n), re.M) for n in (23, 25)) and all("FAILED" not in prlog(s, n) for n in (23, 25)), (prlog(s, 23), prlog(s, 25)))
check("group of two: ONE report per PR, each green on its own (--release green --pr <that PR>), each naming the other, with the fast deploy's note; the deploy ran under the deploy lock, not through fd 9 of its children",
      len(s["msgs"]) == 2 and s["msgs"][0].endswith("--release | green | --pr | https://github.com/example-owner/stackshot/pull/23") and s["msgs"][1].endswith("--pr | https://github.com/example-owner/stackshot/pull/25")
      and "merged by the merge queue in one group with #23 #25" in s["msgs"][0] and "main's full run follows" in s["msgs"][0] and s["locks"] == ["held"] and s["fd9"] == "closed", (s["msgs"], s["locks"], s["fd9"]))
check("group of two: main's run for the merge is read after the deploy and recorded (last good = the merge); the PRs are marked released; the markers are gone, the locks free",
      s["lastgood"] == M2 and len(s["released"]) == 2 and handed(s) == [] and lock_free(s) and upd_lock_free(s), (s["lastgood"], s["released"], handed(s)))
check("group of two, started by the release queue: both PRs leave the queue file and the driver goes (nothing else waits), nothing is started",
      s["queue"] == [] and s["driver"] == "" and s["started"] == [], (s["queue"], s["driver"], s["started"]))
s = grp("on-group-queue", files=QF(["25", "35"]))
check("group started by the release queue with a third PR waiting: both PRs of the group leave the queue, the third starts alone (the count is one) after the deploy", s["rc"] == 0 and s["queue"] == ["35"] and s["started"] == ["35"] and s["driver"] == "35", (s["queue"], s["started"], s["driver"], s["qlog"]))
s = grp("on-group-three", prs=("23", "25", "35"), tip=M3)
check("group of three: one `mq add 23 25 35`, three waits, one deploy at the last merge commit, three `done:` lines and three reports",
      s["rc"] == 0 and s["mq"][0] == "mq add 23 25 35 --repo example-owner/stackshot" and len(s["mq"]) == 4 and s["deploys"] == [M3] and all("done: " in prlog(s, n) for n in (23, 25, 35)) and len(s["msgs"]) == 3, (s["mq"], s["deploys"], s["msgs"]))
s = grp("on-group-nonfast", docs=f"{STRAY},{M1},{M2}")
check("group of two when the live checkout is not at main's tip (something merged and not deployed behind it): not the fast path; main's run for the merge is read BEFORE the single deploy, as on the old path, and the reason is in the log",
      s["rc"] == 0 and s["deploys"] == [M2] and s["order"][0] == "run-view" and "not deployed at the merge" in glog(s) and "(a) the live checkout" in glog(s) and all("done: " in prlog(s, n) for n in (23, 25)) and len(s["msgs"]) == 2, (s["order"], s["deploys"], glog(s)[-900:]))
s = grp("on-group-pick", pickfiles="docs/a.md,client/hooks/session-start.sh")
check("group of two: ONE session pick from the files of both PRs (the start-loaded hook asks for a recycle), the recycle flagged per PR", s["rc"] == 0 and "session pick: recycle" in glog(s) and s["msg"].count("recycle-due") == 2, (glog(s)[-600:], s["msg"]))

# -- the queue ejects or fails one PR: the rest still go out
s = grp("on-group-eject-second", prs=("23", "25"), tip=M1, mq_prs=f"23=merged@{M1[:7]},25=ejected", files=QF(["25"]))
check("group where the queue ejects the second PR: the first is deployed ONCE at its merge, with its `done:` line; the second is reported as a failed release of its own, with the queue's reason; the exit status is 1 (a PR failed)",
      s["rc"] == 1 and s["deploys"] == [M1] and "done: " in prlog(s, 23) and "FAILED at merge queue" in prlog(s, 25) and "conflicts with main or with PR #1 ahead of it" in prlog(s, 25) and "done: " not in prlog(s, 25)
      and "FAILED" not in prlog(s, 23), (s["rc"], s["deploys"], prlog(s, 23), prlog(s, 25), glog(s)[-600:]))
check("ejected second PR: one red report for it ([release] PR #25 FAILED at merge queue, naming the reason) and one green for the first; the group's failure pauses nothing and the queue goes on (both leave the queue file)",
      len(s["msgs"]) == 2 and sum("FAILED at merge queue" in m and "PR #25" in m for m in s["msgs"]) == 1 and sum("PR #23 merged and deployed" in m for m in s["msgs"]) == 1 and not s["paused"] and s["queue"] == [], (s["msgs"], s["paused"], s["queue"]))
check("ejected PR: its marker is gone (the queue no longer holds it) and it is not merged by the old path; no `mq drop` was needed", handed(s) == [] and "pr merge" not in s["gh"] and not any(l.startswith("mq drop") for l in s["mq"]), (handed(s), s["mq"]))
s = grp("on-group-eject-first", tip=M2, prs=("23", "25"), mq_prs=f"23=failed,25=merged@{M2[:7]}", docs=M2, grouplog=f"{M2} Merge pull request #25 from agent/x", fullshas=M2)
check("group where the queue fails the FIRST PR (its checks failed in the group): the second still goes out, once, with its `done:` line; the first reports the queue's reason", s["rc"] == 1 and s["deploys"] == [M2] and "done: " in prlog(s, 25) and "FAILED at merge queue" in prlog(s, 23) and "required check suites failed" in prlog(s, 23), (s["rc"], s["deploys"], prlog(s, 23), glog(s)[-500:]))
s = grp("on-group-none", mq_prs="23=failed,25=ejected", files=QF(["25", "35"]))
check("group where the queue merges none of them: nothing deployed, both reported failed with their reasons, no pause (they were the PRs' own failures), the queue goes on with the next PR",
      s["rc"] == 1 and not s["deployed"] and "FAILED at merge queue" in prlog(s, 23) and "FAILED at merge queue" in prlog(s, 25) and len(red(s)) == 2 and not s["paused"] and s["queue"] == ["35"] and s["started"] == ["35"], (s["rc"], s["msgs"], s["queue"], s["started"], s["paused"]))

# -- any failure of the queue itself ends in a clear line and a pause of the release queue, never a silent drop and never a merge by the old path
def paused_group(s, step):   # the failure is in the log, each PR's log, one red report, the release queue paused with the PRs still first in it, nothing deployed, and the old path merged nothing
    return (s["rc"] == 1 and f"FAILED at {step}" in glog(s) and all(f"FAILED at {step}" in prlog(s, n) for n in (23, 25)) and len(red(s)) == 1 and s["paused"] and "pr merge" not in s["gh"] and not s["deployed"])
s = grp("on-group-add-refused", mq_add="refused", files=QF(["25", "35"]))
check("mq add refused by salamander (its own `salamander mq:` message, exit 1): FAILED at mq add with the message, the queue paused with all three PRs still queued (first), nothing merged, no unit started for the next, the markers gone",
      paused_group(s, "mq add") and "is not open yet" in glog(s) and s["queue"] == ["23", "25", "35"] and not s["started"] and handed(s) == [], (s["rc"], glog(s)[-600:], s["queue"], s["paused"], handed(s)))
check("mq add refused: the PRs are let go of in the queue (a best-effort `mq drop` each) and told in the red report that `release.sh queue --resume` tries them again", s["mq"][1:] == ["mq drop 23 --repo example-owner/stackshot", "mq drop 25 --repo example-owner/stackshot"] and "queue --resume" in s["msgs"][0], (s["mq"], s["msgs"]))
s = scenario("on-group-after-refused", merge="ok", mqhost=ON, reuse=s)
check("…and the same PR released alone afterwards goes through the old path (no `mq line` refusal: the markers were cleared although the real `mq drop` of a PR never added exits 1 with `is not in the line`)",
      s["rc"] == 0 and s["deployed"] and "mq line" not in s["log"] and "pr merge" in s["gh"], (s["rc"], s["log"][-400:]))
s = grp("on-group-add-timeout", mq_add="timeout", extra={"RELEASE_MQ_ON_ADD_TIMEOUT": "1"}, files=QF(["25"]), secs=60)
check("mq add that never answers (cut at RELEASE_MQ_ON_ADD_TIMEOUT): FAILED at mq add, saying it took more than the cap; the release queue paused; nothing merged", paused_group(s, "mq add") and "took more than 1s" in glog(s), (s["rc"], glog(s)[-500:], s["paused"]))
s = grp("on-group-nosal", nosalamander=True, files=QF(["25"]))
check("no salamander on PATH: FAILED at mq, nothing merged, the release queue paused, no marker left", paused_group(s, "mq") and handed(s) == [], (s["rc"], glog(s)[-400:], handed(s)))
s = grp("on-group-wait-error", tip=M1, mq_prs=f"23=merged@{M1[:7]},25=error", files=QF(["25", "35"]))
check("mq wait fails with salamander's own error AFTER the first PR merged: the merged PR is DEPLOYED all the same (once, at its merge, with its `done:` line and its green report) and never logged FAILED; only the unresolved PR is: FAILED at mq wait with the message, dropped from the merge queue (the merged one is not), one red report for it",
      s["rc"] == 1 and s["deploys"] == [M1] and "done: " in prlog(s, 23) and "FAILED" not in prlog(s, 23) and "FAILED at mq wait" in prlog(s, 25) and "state file unreadable" in prlog(s, 25) and "done: " not in prlog(s, 25)
      and "mq drop 25 --repo example-owner/stackshot" in s["mq"] and "mq drop 23 --repo example-owner/stackshot" not in s["mq"] and "pr merge" not in s["gh"]
      and sum("FAILED at mq wait" in m and "PRs #25" in m for m in s["msgs"]) == 1 and sum("PR #23 merged and deployed" in m for m in s["msgs"]) == 1 and len(red(s)) == 1 and handed(s) == [], (s["rc"], glog(s)[-900:], s["mq"], s["msgs"]))
check("…and the release queue is paused (written before the deploy's lock was let go), the merged PR leaves the queue file, the unresolved one stays first with the one behind it, nothing is started",
      s["paused"] and s["queue"] == ["25", "35"] and s["started"] == [] and "mq wait" in s["paused"], (s["paused"], s["queue"], s["started"]))
s = grp("on-group-notinline", mq_prs="23=notinline,25=notinline", files=QF(["25"]))
check("mq wait says the PR is not in the line (exit 2, not a give-up): FAILED at mq wait, the release queue paused, nothing merged", paused_group(s, "mq wait") and "is not in the line" in glog(s), (s["rc"], glog(s)[-500:]))
s = grp("on-group-tested", mq_prs="23=tested,25=tested", files=QF(["25"]))
check("mq wait answers the shadow verdict (exit 3: the queue is not in mode on): not a verdict a group can use, FAILED at mq wait, paused, nothing merged", paused_group(s, "mq wait") and "exited 3" in glog(s), (s["rc"], glog(s)[-500:]))
s = grp("on-group-gaveup-paused", mq_prs="23=gaveup,25=gaveup", mq_status="paused", files=QF(["25"]))
check("a wait slice ran out and the queue says it is paused (mq status): FAILED at mq, with the queue's reason, the PRs dropped, the release queue paused, nothing merged, the markers gone",
      paused_group(s, "mq") and "the merge queue is paused: the merge push failed 5 times" in glog(s) and "mq drop 23 --repo example-owner/stackshot" in s["mq"] and any(l.startswith("mq status --json") for l in s["mq"]) and handed(s) == [], (s["rc"], glog(s)[-600:], s["mq"]))
s = grp("on-group-gaveup-blocked", mq_prs="23=gaveup,25=gaveup", mq_status="blocked", files=QF(["25"]))
check("the same for a queue that is blocked (a bad repo config): FAILED at mq with `blocked: bad repo config`", paused_group(s, "mq") and "blocked: bad repo config" in glog(s), (s["rc"], glog(s)[-500:]))
s = grp("on-group-gaveup-cap", mq_prs="23=gaveup,25=gaveup", extra={"RELEASE_MQ_WAIT_CAP": "700"}, files=QF(["25"]))
check("a queue that stays healthy but gives no verdict: the wait goes on in slices (each followed by one look at the queue) until RELEASE_MQ_WAIT_CAP, then FAILED at mq wait naming the cap, the PRs dropped, the release queue paused",
      paused_group(s, "mq wait") and "gave no verdict on PR #23 within 700s" in glog(s) and s["mq"].count(wait_(23)) + s["mq"].count(wait_(23, 100)) >= 2 and sum(l.startswith("mq status --json") for l in s["mq"]) >= 2 and "mq drop 25 --repo example-owner/stackshot" in s["mq"], (s["rc"], glog(s)[-600:], s["mq"]))
s = grp("on-group-drop-fails", tip=M1, mq_prs=f"23=merged@{M1[:7]},25=error", mq_drop="fail", mq_status="active", files=QF(["25"]))
check("a drop that fails for another reason (the queue state cannot be locked) while `mq status` still lists the PR as active: its marker stays (the old path refuses it) and the log says so, with the command",
      "could not be dropped from the merge queue (salamander mq drop 25: salamander mq: cannot lock the queue state)" in glog(s) and handed(s) == ["pr-25"] and s["paused"], (glog(s)[-600:], handed(s)))
s = scenario("on-group-after-drop-fails", merge="ok", mqhost=ON, reuse=s, raw=["25"], pr="25")
check("... and the old path then refuses PR 25 on its marker: nothing merged", s["rc"] == 1 and "FAILED at mq line" in prlog(s, 25) and "pr merge" not in s["gh"], (s["rc"], s["out"][-300:]))
s = grp("on-group-drop-fails-gone", tip=M1, mq_prs=f"23=merged@{M1[:7]},25=error", mq_drop="fail", files=QF(["25"]))
check("a drop that fails but `mq status` lists no active entry for the PR: the queue does not hold it, so the marker goes", handed(s) == [] and s["paused"], (glog(s)[-400:], handed(s)))
s = grp("on-group-mode-changed", mqhost="shadow", files=QF(["25"]))
check("the host file went from on to shadow before the group started: FAILED at mq mode, nothing handed to the queue (no `mq` call), the release queue paused with the PRs still first", paused_group(s, "mq mode") and not s["mq"] and "now \"shadow\"" in glog(s), (s["rc"], glog(s)[-400:], s["mq"]))
s = grp("on-group-nolock", mqhost='mode = "on"\n', files=QF(["25"]))
check("the host file lost its deploy_lock: FAILED at mq mode, nothing handed over, the release queue paused", paused_group(s, "mq mode") and not s["mq"] and "deploy_lock" in glog(s), (s["rc"], glog(s)[-400:]))
s = grp("on-group-qpaused", files={**QF(["25"]), "releases/queue.paused": "PR #22 failed at main's tests after its merge\n"})
check("a group the release queue started and a pause that came before it ran: nothing handed to the queue, nothing merged; the PRs stay first in the release queue", s["rc"] == 1 and "FAILED at queue paused" in glog(s) and not s["mq"] and not s["deployed"] and s["queue"] == ["23", "25"], (s["rc"], glog(s)[-400:], s["mq"], s["queue"]))
s = grp("on-group-byhand", mq_add="refused")
check("a group release run by hand (no queue driver): the same failure, but it pauses nothing in the release queue", s["rc"] == 1 and "FAILED at mq add" in glog(s) and not s["paused"], (s["rc"], glog(s)[-300:], s["paused"]))

# -- the real wording of salamander's answers (lib/mq/mq_cli.py): the blocked line (exit 2, no "gave up"), exit 4, a driver line on stderr before the verdict, a PR the queue ejects because it is merged already
s = grp("on-group-driverline", mq_driverline="1")
check("a line on stderr before the verdict (`driver started`, printed when `mq wait` had to start the driver again): the verdict is the line that starts with `PR n`, so the merge commit is found and the group deploys",
      s["rc"] == 0 and s["deploys"] == [M2] and "merge queue: PR 23 merged: merged in group g1 at a1a1a1a" in glog(s) and all("done: " in prlog(s, n) for n in (23, 25)), (s["rc"], s["deploys"], glog(s)[-600:]))
check("the real `mq add` answer (`PR n: queued` for each PR, then the `mode on: ...` line) is read: the log names the last line", "handed over in one call (mode on: tested groups are merged into main; driver started" in glog(s), glog(s)[:700])
s = grp("on-group-blocked", mq_prs="23=blocked,25=blocked", files=QF(["25"]))
check("the real blocked answer (`PR n is waiting and the queue is blocked: ...`, exit 2 with no `gave up`): FAILED at mq with the queue's reason, the PRs dropped, the release queue paused, nothing merged",
      paused_group(s, "mq") and "the merge queue is blocked" in glog(s) and "bad repo config" in glog(s) and "mq drop 23 --repo example-owner/stackshot" in s["mq"], (s["rc"], glog(s)[-500:]))
s = grp("on-group-skipped", mq_prs="23=skipped,25=skipped", files=QF(["25"]))
check("exit 4 (a replay that built the group and tested nothing): not a verdict a group can use, FAILED at mq wait naming the exit status, paused, nothing merged", paused_group(s, "mq wait") and "exited 4" in glog(s), (s["rc"], glog(s)[-500:]))
s = grp("on-group-ejected-merged", mq_prs=f"23=ejectedmerged,25=merged@{M2[:7]}", prstate_after=f"23=MERGED@{M1}")
check("the queue ejects a PR with `pull request is merged` and GitHub says it is merged (the queue merged it in an earlier push of the group): it is on main, so it is deployed with the group, `done:` in both logs, never logged FAILED, not dropped from the queue, no red report",
      s["rc"] == 0 and s["deploys"] == [M2] and all("done: " in prlog(s, n) and "FAILED" not in prlog(s, n) for n in (23, 25)) and "mq drop 23" not in "\n".join(s["mq"]) and red(s) == [] and handed(s) == [],
      (s["rc"], prlog(s, 23), s["deploys"], s["mq"], s["msgs"]))
s = grp("on-group-ejected-open", mq_prs=f"23=ejectedmerged,25=merged@{M2[:7]}", files=QF(["25"]))
check("…and the same ejection of a PR GitHub still shows open is that PR's failure with the queue's words (as before), the other goes out",
      s["rc"] == 1 and s["deploys"] == [M2] and "FAILED at merge queue" in prlog(s, 23) and "pull request is merged" in prlog(s, 23) and "done: " in prlog(s, 25), (s["rc"], prlog(s, 23), s["deploys"]))

# -- a merge happened, then the queue could not go on: the merged PRs are deployed, only the unresolved ones fail
s = grp("on-group-cap-merged", prs=("23", "25", "35"), tip=M2, mq_prs=f"23=merged@{M1[:7]},25=merged@{M2[:7]},35=gaveup", extra={"RELEASE_MQ_WAIT_CAP": "400"}, files=QF(["25", "35"]))
check("two PRs merged and the third gets no verdict within the cap: the two are deployed once (`done:` in both logs, no FAILED in either), the third alone is reported FAILED at mq wait (dropped from the queue), the release queue is paused with only the third left in it",
      s["rc"] == 1 and s["deploys"] == [M2] and all("done: " in prlog(s, n) and "FAILED" not in prlog(s, n) for n in (23, 25)) and "FAILED at mq wait" in prlog(s, 35) and "gave no verdict on PR #35 within 400s" in prlog(s, 35)
      and "mq drop 35 --repo example-owner/stackshot" in s["mq"] and s["paused"] and s["queue"] == ["35"] and s["started"] == [] and len(s["msgs"]) == 3, (s["rc"], s["deploys"], glog(s)[-900:], s["queue"], s["msgs"]))
check("…the reports: green for each merged PR, one red for the third naming the step and that the merged ones were deployed", sum("merged and deployed" in m for m in s["msgs"]) == 2 and sum("PRs #35 FAILED at mq wait" in m and "#23 #25, merged by the same group, are deployed next" in m for m in s["msgs"]) == 1, s["msgs"])
s = grp("on-group-paused-merged", tip=M1, mq_prs=f"23=merged@{M1[:7]},25=gaveup", mq_pauseq="1", files=QF(["25"]))
check("a pause of release.sh's own queue (a lone release rolled back) while the group waits for its second PR, after the first merged: the first is deployed, the second is dropped from the merge queue and reported FAILED at queue paused, stays first in the release queue; the original pause text stands",
      s["rc"] == 1 and s["deploys"] == [M1] and "done: " in prlog(s, 23) and "FAILED" not in prlog(s, 23) and "FAILED at queue paused" in prlog(s, 25) and "mq drop 25 --repo example-owner/stackshot" in s["mq"]
      and s["queue"] == ["25"] and s["started"] == [] and s["paused"].startswith("PR #22 failed at the main tests"), (s["rc"], s["deploys"], glog(s)[-700:], s["queue"], s["paused"]))
s = grp("on-group-paused-none", mq_prs="23=gaveup,25=gaveup", mq_pauseq="1", files=QF(["25"]))
check("the same pause with nothing merged yet: FAILED at queue paused, both PRs dropped from the merge queue, nothing merged or deployed, both stay first in the release queue, the driver goes, the pause is the one that was there",
      s["rc"] == 1 and "FAILED at queue paused" in glog(s) and all("FAILED at queue paused" in prlog(s, n) for n in (23, 25)) and not s["deployed"] and "pr merge" not in s["gh"] and s["queue"] == ["23", "25"] and s["driver"] == ""
      and s["paused"].startswith("PR #22 failed at the main tests") and handed(s) == [] and "mq drop 23 --repo example-owner/stackshot" in s["mq"], (s["rc"], glog(s)[-600:], s["queue"], s["driver"], s["paused"]))
s = grp("on-group-nosha", mq_prs=f"23=mergednosha,25=merged@{M2[:7]}", prstate_after=f"23=MERGED@{M1}", files=QF(["25"]))
check("an answer that names no merge commit: GitHub is asked for it (state, mergeCommit), and the group deploys at the later one", s["rc"] == 0 and s["deploys"] == [M2] and all("done: " in prlog(s, n) for n in (23, 25)), (s["rc"], s["deploys"], glog(s)[-600:]))
s = grp("on-group-nosha-lost", tip=M2, mq_prs=f"23=mergednosha,25=merged@{M2[:7]}", docs=M2, grouplog=f"{M2} Merge pull request #25 from agent/x", fullshas=M2, files=QF(["25"]))
check("…and when GitHub cannot name it either: that PR alone is reported merged, not live (FAILED at merge commit, never `done:`), the other is deployed", s["rc"] == 1 and s["deploys"] == [M2] and "FAILED at merge commit" in prlog(s, 23) and "merged, not live" in prlog(s, 23) and "done: " not in prlog(s, 23) and "done: " in prlog(s, 25), (s["rc"], prlog(s, 23), s["deploys"]))

# -- a PR merged on GitHub already (an earlier run of the group was killed after the queue merged it): deployed with the group, never handed to the queue again
s = grp("on-group-premerged", tip=M2, prstate=f"23=MERGED@{M1},25=OPEN", mq_prs=f"25=merged@{M2[:7]}", files=QF(["25"]))
check("one PR of the group is merged on GitHub already: only the other is handed to the queue (`mq add 25`, one wait), both are deployed once at the later merge commit, both get `done:`, neither is logged FAILED, and the report says the first had been merged by an earlier run",
      s["rc"] == 0 and s["mq"] == ["mq add 25 --repo example-owner/stackshot", wait_(25)] and s["deploys"] == [M2] and all("done: " in prlog(s, n) and "FAILED" not in prlog(s, n) for n in (23, 25)) and "#23 had been merged by an earlier run of this group" in s["msgs"][0] and handed(s) == [], (s["rc"], s["mq"], s["deploys"], s["msgs"]))
s = grp("on-group-premerged-all", tip=M2, prstate=f"23=MERGED@{M1},25=MERGED@{M2}", mq_prs="", files=QF(["25"]))
check("every PR of the group is merged on GitHub already: no call to the queue at all, one deploy of the later merge commit, `done:` for both", s["rc"] == 0 and not s["mq"] and s["deploys"] == [M2] and all("done: " in prlog(s, n) for n in (23, 25)), (s["rc"], s["mq"], s["deploys"], glog(s)[-500:]))
s = grp("on-group-closed", tip=M1, prstate="25=CLOSED", mq_prs=f"23=merged@{M1[:7]}", files=QF(["25"]))
check("a PR of the group that was closed meanwhile: reported FAILED at pr state on its own, never handed to the queue; the other goes through (`mq add 23`) and is deployed", s["rc"] == 1 and s["mq"][0] == "mq add 23 --repo example-owner/stackshot" and "FAILED at pr state" in prlog(s, 25) and s["deploys"] == [M1] and "done: " in prlog(s, 23), (s["rc"], s["mq"], prlog(s, 25)))

# -- the queue merges a group in one push: a PR whose wait is not reached (a pause, the cap, a queue error) may be on main already
s = grp("on-group-pause-then-merged", mq_prs=f"23=mergedpause@{M1[:7]}", prstate_after=f"25=MERGED@{M2}", files=QF(["25"]))
check("the first PR merged and release.sh's queue was paused right after, the second was merged by the same push: it is read from GitHub before it is dropped, so both are deployed once, `done:` in both logs, none FAILED, no drop of the second, no wait for it, no red report",
      s["rc"] == 0 and s["deploys"] == [M2] and all("done: " in prlog(s, n) and "FAILED" not in prlog(s, n) for n in (23, 25)) and not any("mq drop" in l or "mq wait 25" in l for l in s["mq"]) and red(s) == [] and handed(s) == [],
      (s["rc"], s["deploys"], glog(s)[-800:], s["mq"], s["msgs"]))
check("…and the pause that was there stands; nothing is started behind the group; both leave the release queue", s["paused"].startswith("PR #22 failed at the main tests") and s["started"] == [] and s["queue"] == [], (s["paused"], s["started"], s["queue"]))
s = grp("on-group-error-then-merged", mq_prs=f"23=merged@{M1[:7]},25=error", prstate_after=f"25=MERGED@{M2}", files=QF(["25"]))
check("a `salamander mq:` error on the second wait while GitHub shows it merged: deployed with the first, none FAILED, the unit ends 0",
      s["rc"] == 0 and s["deploys"] == [M2] and all("done: " in prlog(s, n) and "FAILED" not in prlog(s, n) for n in (23, 25)) and "mq drop 25" not in "\n".join(s["mq"]), (s["rc"], s["deploys"], glog(s)[-600:], s["mq"]))
s = grp("on-group-pause-one-merged", prs=("23", "25", "35"), tip=M2, mq_prs=f"23=mergedpause@{M1[:7]}", prstate_after=f"25=MERGED@{M2}", files=QF(["25", "35"]))
check("of the two PRs behind the first, one is merged on GitHub and one is not: the merged one is deployed, the other alone is FAILED (dropped from the queue, still first in the release queue), the release queue is paused",
      s["rc"] == 1 and s["deploys"] == [M2] and all("done: " in prlog(s, n) and "FAILED" not in prlog(s, n) for n in (23, 25)) and "FAILED at queue paused" in prlog(s, 35) and "mq drop 35 --repo example-owner/stackshot" in s["mq"] and "mq drop 25" not in "\n".join(s["mq"])
      and s["queue"] == ["35"] and s["paused"], (s["rc"], s["deploys"], glog(s)[-700:], s["queue"]))

s = grp("on-group-lost-and-unresolved", mq_prs="23=gaveup", mq_pauseq="1", prstate_after="23=MERGED#-", files=QF(["25"]))
check("the first PR is merged on GitHub with no commit to name (merged, not live), the release queue was paused while the group waited and the second is unresolved: the second is dropped from the merge queue and FAILED, the first is not called unmerged (`nothing was merged` is not said), nothing is deployed",
      s["rc"] == 1 and not s["deploys"] and "merged, not live" in prlog(s, 23) and "FAILED at queue paused" in prlog(s, 25) and "mq drop 25 --repo example-owner/stackshot" in s["mq"] and "nothing was merged" not in glog(s) and "mq drop 23" not in "\n".join(s["mq"]), (s["rc"], glog(s)[-900:], s["mq"]))
check("…the lost PR leaves the release queue file, the unresolved one stays first, the pause that was there stands, nothing is started",
      s["queue"] == ["25"] and s["paused"].startswith("PR #22 failed at the main tests") and s["started"] == [], (s["queue"], s["paused"], s["started"]))

# -- GitHub cannot be read when the group looks at a PR it has no answer for
s = grp("on-group-state-unreadable", tip=M1, mq_prs=f"23=mergedpause@{M1[:7]}", prstate_after=f"25=MERGED@{M2}", prstate_failn="99", files=QF(["25"]))
check("the first PR merged, the release queue was paused, and GitHub's state of the second cannot be read (twice, with a pause between): the second is NOT dropped from the merge queue and not called FAILED or not merged, its marker stays, it is reported unresolved with the reason, and the merged first is deployed",
      s["rc"] == 1 and s["deploys"] == [M1] and "done: " in prlog(s, 23) and "mq drop" not in "\n".join(s["mq"]) and handed(s) == ["pr-25"] and "pr state unreadable" in prlog(s, 25) and "FAILED" not in prlog(s, 25) and "3" in s["sleeps"], (s["rc"], s["deploys"], glog(s)[-900:], s["mq"], handed(s), s["sleeps"]))
check("…and it stays first in the release queue, which is paused", s["queue"] == ["25"] and s["paused"], (s["queue"], s["paused"]))
s = grp("on-group-state-flaky", mq_prs=f"23=mergedpause@{M1[:7]}", prstate_after=f"25=MERGED@{M2}", prstate_failn="1", files=QF(["25"]))
check("…one failed read is tried again: the second is then found merged and deployed with the first, none FAILED", s["rc"] == 0 and s["deploys"] == [M2] and all("done: " in prlog(s, n) and "FAILED" not in prlog(s, n) for n in (23, 25)) and "mq drop" not in "\n".join(s["mq"]), (s["rc"], s["deploys"], glog(s)[-600:]))

# -- a PR whose state is unknown is unresolved, never FAILED
s = grp("on-group-unknown-nothing", mq_prs="23=gaveup,25=gaveup", mq_pauseq="1", prstate_failn="99", prstate_after="999=OPEN", files=QF(["25"]))
check("the release queue was paused while the group waited, nothing is known to be merged and GitHub cannot be read: neither PR is logged FAILED (each gets the `unresolved ... pr state unreadable` line), neither is dropped from the merge queue, both markers stay, 'nothing was merged' is not claimed, both stay in the release queue",
      s["rc"] == 1 and all("unresolved at queue paused" in prlog(s, n) and "pr state unreadable" in prlog(s, n) and "FAILED" not in prlog(s, n) for n in (23, 25)) and "mq drop" not in "\n".join(s["mq"]) and handed(s) == ["pr-23", "pr-25"]
      and "nothing was merged" not in glog(s) and "no PR is known to be merged" in glog(s) and s["queue"] == ["23", "25"] and not s["deploys"], (s["rc"], glog(s)[-900:], s["mq"], handed(s), s["queue"]))
s = grp("on-group-unknown-ejected", mq_prs=f"23=ejectedmerged,25=merged@{M2[:7]}", prstate_failn="99", prstate_after="999=OPEN", files=QF(["25"]))
check("the queue ejects a PR as merged and GitHub's state of it cannot be read: it is NOT reported FAILED, not dropped, its marker stays, it is logged unresolved (pr state unreadable) and stays first in the release queue (paused); the PR that merged is deployed",
      s["rc"] == 1 and s["deploys"] == [M2] and "done: " in prlog(s, 25) and "unresolved" in prlog(s, 23) and "pr state unreadable" in prlog(s, 23) and "FAILED" not in prlog(s, 23) and "mq drop 23" not in "\n".join(s["mq"]) and handed(s) == ["pr-23"]
      and s["queue"] == ["23"] and s["paused"], (s["rc"], s["deploys"], prlog(s, 23), glog(s)[-700:], s["mq"], handed(s), s["queue"]))
s = grp("on-group-premerged-marker", tip=M2, prstate=f"23=MERGED@{M1},25=OPEN", mq_prs=f"25=merged@{M2[:7]}", files={**QF(["25"]), "releases/mq-on/pr-23": "2026-11-04T00:00:00Z handed to the merge queue by the group release led by PR #23\n"})
check("a PR merged by an earlier run of the group that left its marker: the marker is removed when the PR joins the deploy", s["rc"] == 0 and handed(s) == [] and all("done: " in prlog(s, n) for n in (23, 25)), (s["rc"], handed(s)))


# mq_landing on a real repository: the queue's --no-ff merges of three PR branches into a group branch, main moved to the group head by fast-forward
ml = pathlib.Path(_scratch.mkdtemp(prefix="releasetest-landing-")); dirs.append(ml)
mp = ml / "r"; g("init", "-q", "-b", "main", str(mp))
def mcommit(name, text, msg):
    (mp / name).write_text(text); g("add", "-A", cwd=mp); g("commit", "-qm", msg, cwd=mp); return g("rev-parse", "HEAD", cwd=mp)
c0 = mcommit("README.md", "0\n", "live")
heads = {}
for n in ("a", "b", "c"):
    g("checkout", "-q", "-b", "pr-" + n, c0, cwd=mp); heads[n] = mcommit(n + ".py", n + " = 1\n", "work " + n)
g("checkout", "-q", "-b", "group", c0, cwd=mp)
merges = {}
for n in ("a", "b", "c"):
    g("merge", "-q", "--no-ff", "-m", "Merge pull request #%d from agent/%s" % (ord(n) - 96, n), "pr-" + n, cwd=mp); merges[n] = g("rev-parse", "HEAD", cwd=mp)
g("update-ref", "refs/remotes/origin/main", merges["c"], cwd=mp)   # main is fast-forwarded to the group head
(ml / "h.sh").write_text('set -u\neval "$(sed -n \'/^mq_landing() {/,/^}/p\' "$1")"\ncd "$2"\nmq_landing "$3"\n')
def landing(h): return subprocess.run(["bash", str(ml / "h.sh"), os.path.join(STACK, "release.sh"), str(mp), h], env=genv, capture_output=True, text=True, timeout=60).stdout.strip()
check("real git: each PR head of a --no-ff group pushed by fast-forward lands on its own merge commit on main's first-parent line (the earliest one that has the head in its ancestry)", [landing(heads[n]) for n in "abc"] == [merges[n] for n in "abc"], ([landing(heads[n]) for n in "abc"], merges))
check("real git: a commit on the first-parent line itself is its own landing commit; a commit that is not in main prints nothing", landing(c0) == c0 and landing("0" * 40) == "", (landing(c0), landing("0" * 40)))

# -- the queue merges by fast-forward push: GitHub may name no merge commit for a PR, its head is on main then
H1 = "d1d1d1d" + "0" * 33; H2 = "d2d2d2d" + "0" * 33; H3 = "d3d3d3d" + "0" * 33   # PR heads: the second parent of the queue's --no-ff merge commits
HIST_H = ",".join([GOOD, BASE, M1, M2, M3, H1, H2, H3])
s = grp("on-group-ff-one", prstate=f"23=MERGED#{H1},25=OPEN", mq_prs=f"25=merged@{M2[:7]}", landing=f"{H1}={M2}/{M1}", fullshas=f"{M1},{M2},{H1}", files=QF(["25"]))
check("one PR merged already for which GitHub names no merge commit (the queue pushes the group head by fast-forward): its HEAD is not taken as the sha, the commit of main's first-parent line that brought it in is (the earliest: M1, not the later M2), so both are deployed once at M2, `done:` for both, none FAILED, and the ledger walk finds its merge",
      s["rc"] == 0 and s["deploys"] == [M2] and all("done: " in prlog(s, n) and "FAILED" not in prlog(s, n) for n in (23, 25)) and f"rev-list --first-parent --ancestry-path {H1}..origin/main" in s["git"] and "landed on main as a1a1a1a" in glog(s), (s["rc"], s["deploys"], glog(s)[-700:], s["git"][-500:]))
s = grp("on-group-ff-two", prs=("23", "25", "35"), tip=M3, mq_prs=f"23=mergedpause@{M1[:7]}", prstate_after=f"25=MERGED#{H2},35=MERGED#{H3}", landing=f"{H2}={M3}/{M2},{H3}={M3}", fullshas=f"{M1},{M2},{M3},{H2},{H3}", files=QF(["25", "35"]))
check("two PRs adopted after the first merged, each with a head and no merge commit: each is resolved to its own landing commit (M2 and M3, one line), the deploy is pinned to M3 (not to a head), all three get `done:`, none FAILED, no drop",
      s["rc"] == 0 and s["deploys"] == [M3] and all("done: " in prlog(s, n) and "FAILED" not in prlog(s, n) for n in (23, 25, 35)) and "mq drop" not in "\n".join(s["mq"]), (s["rc"], s["deploys"], glog(s)[-900:], s["mq"]))
s = grp("on-group-ff-ontheline", tip=M2, history=",".join([GOOD, BASE, H1, M2]), prstate=f"23=MERGED#{H1},25=OPEN", mq_prs=f"25=merged@{M2[:7]}", fplist=f"{M2},{H1}", fullshas=f"{H1},{M2}", docs=f"{H1},{M2}", grouplog=f"{M2} Merge pull request #25 from agent/x", files=QF(["25"]))
check("a head that is itself on main's first-parent line (merged by fast-forward) is its own landing commit",
      s["rc"] == 0 and s["deploys"] == [M2] and all("done: " in prlog(s, n) for n in (23, 25)) and "landed on main as d1d1d1d" in glog(s), (s["rc"], s["deploys"], glog(s)[-700:]))
s = grp("on-group-ff-nolanding", prstate=f"23=MERGED#{H1},25=OPEN", mq_prs=f"25=merged@{M2[:7]}", fullshas=f"{M1},{M2},{H1}", files=QF(["25"]))
check("…and a head that is not found on main's first-parent line is that PR alone reported merged, not live (FAILED at merge commit), the other is deployed, the lost one leaves the release queue",
      s["rc"] == 1 and s["deploys"] == [M2] and "FAILED at merge commit" in prlog(s, 23) and "merged, not live" in prlog(s, 23) and "done: " in prlog(s, 25) and "23" not in s["queue"], (s["rc"], prlog(s, 23), s["deploys"], s["queue"]))
s = grp("on-group-ff-nolanding-all", prstate=f"23=MERGED#{H1},25=MERGED#{H2}", mq_prs="", fullshas=f"{M1},{M2},{H1},{H2}", files=QF(["25"]))
check("every PR merged but none can be placed on main: nothing is deployed, both are merged, not live, the release queue is paused and both leave its file",
      s["rc"] == 1 and not s["deploys"] and all("merged, not live" in prlog(s, n) for n in (23, 25)) and s["paused"] and s["queue"] == [] and s["started"] == [], (s["rc"], s["deploys"], s["paused"], s["queue"]))
s = grp("on-group-premerged-nothing", tip=M2, prstate="23=MERGED#-,25=OPEN", mq_prs=f"25=merged@{M2[:7]}", docs=M2, grouplog=f"{M2} Merge pull request #25 from agent/x", fullshas=M2, files=QF(["25"]))
check("…and when GitHub names neither a merge commit nor a head: that PR alone is FAILED at pr state as merged, not live; the other is deployed",
      s["rc"] == 1 and s["deploys"] == [M2] and "FAILED at pr state" in prlog(s, 23) and "merged, not live" in prlog(s, 23) and "done: " in prlog(s, 25), (s["rc"], prlog(s, 23), s["deploys"]))
s = grp("on-group-nosha-lost-only", tip=M2, mq_prs="23=mergednosha,25=mergednosha", docs=M2, grouplog=f"{M2} Merge pull request #25 from agent/x", fullshas=M2, files=QF(["25"]))
check("every PR of the group merged but no commit can be named for either: nothing is deployed, both are reported merged, not live, and the release queue is PAUSED (not handed on), the merged PRs out of its file",
      s["rc"] == 1 and not s["deploys"] and all("merged, not live" in prlog(s, n) and "FAILED at merge commit" in prlog(s, n) for n in (23, 25)) and s["paused"] and s["queue"] == [] and s["started"] == [], (s["rc"], s["deploys"], s["paused"], s["queue"], s["started"]))

# -- the hand-off is release.sh's own 4 PRs; no key of the rules file changes it (the queue is a chain, an entry is one PR)
s = q("on-q-chain-nokey", "23", "25", "35", "37", "44", mqhost=ON, files={"box/.github/mergequeue.toml": 'queue_mode = "chain"\n'})
check("chain rules, no other key: five waiting go as a hand-off of the first four, the fifth waits for the next", s["started"] == ["23"] and started_args(s)[0].endswith("/release.sh --run-group 23 25 35 37"), (started_args(s), s["out"]))
s = q("on-q-stale-one", "23", "25", "35", mqhost=ON, files={"box/.github/mergequeue.toml": 'queue_mode = "chain"\ngroup_max = 1\n'})
check("a retired `group_max = 1` left in the rules file is not read: still a hand-off, not the one-at-a-time old path", s["started"] == ["23"] and started_args(s)[0].endswith("/release.sh --run-group 23 25 35"), (started_args(s), s["out"]))
s = q("on-q-stale-fifty", "23", "25", "35", "37", "44", "45", mqhost=ON, files={"box/.github/mergequeue.toml": 'queue_mode = "chain"\ngroup_max = 50\ninflight_max = 3\n'})
check("a retired `group_max = 50` is not read either: six waiting go as a hand-off of the first four", s["started"] == ["23"] and started_args(s)[0].endswith("/release.sh --run-group 23 25 35 37"), (started_args(s), s["out"]))
s = scenario("on-group-door-stale", raw=["--group", "23", "25", "35"], mqhost=ON, units="", files={"box/.github/mergequeue.toml": 'queue_mode = "chain"\ngroup_max = 1\n'})
check("release.sh --group with a retired `group_max = 1` in the rules file: not refused (the file is not read for the hand-off size)", "group_max" not in s["out"] and s["rc"] != 2, (s["rc"], s["out"]))

# -- queue --drop of a PR with a stale marker
STALE = "2026-11-04T00:00:00Z handed to the merge queue by the group release led by PR #23\n"
s = q("on-q-drop-stale", "--drop", "25", mqhost=ON, files={**QF(["25"]), "releases/mq-on/pr-25": STALE})
check("queue --drop of a PR whose marker is stale (its group release is gone and `mq status` no longer lists the PR): the marker is removed, named, and the PR is dropped as usual",
      s["rc"] == 0 and "stale marker" in s["out"] and "releases/mq-on/pr-25" in s["out"] and "dropped PR #25" in s["out"] and handed(s) == [] and s["queue"] == ["23"], (s["rc"], s["out"], handed(s), s["queue"]))
s = q("on-q-drop-stale-off", "--drop", "25", mqhost='mode = "off"\n', files={**QF(["25"]), "releases/mq-on/pr-25": STALE})
check("…the host file no longer on: the marker means nothing, it goes and the PR is dropped", s["rc"] == 0 and "dropped PR #25" in s["out"] and handed(s) == [], (s["rc"], s["out"], handed(s)))
s = q("on-q-drop-live", "--drop", "25", mqhost=ON, units="23", files={**QF(["25"]), "releases/mq-on/pr-25": STALE})
check("…but while its group release is running the marker is that release's own: refused, the marker path named, nothing changed",
      s["rc"] == 1 and "releases/mq-on/pr-25" in s["out"] and "dropped PR #25" not in s["out"] and handed(s) == ["pr-25"] and s["queue"] == ["23", "25"], (s["rc"], s["out"], handed(s), s["queue"]))

s = q("on-q-drop-bad-host", "--drop", "25", mqhost='mode = "bogus"\n', mq_status="error", files={**QF(["25"]), "releases/mq-on/pr-25": STALE})
check("queue --drop while the host file does not read (a file mid-edit) and `mq status` cannot be read either: the marker is NOT taken for stale, refused, the marker stays",
      s["rc"] == 1 and handed(s) == ["pr-25"] and "dropped PR #25" not in s["out"] and s["queue"] == ["23", "25"], (s["rc"], s["out"], handed(s), s["queue"]))
s = q("on-q-drop-bad-host-gone", "--drop", "25", mqhost='mode = "bogus"\n', files={**QF(["25"]), "releases/mq-on/pr-25": STALE})
check("…with a host file that does not read but `mq status` answering that the PR is not held: mq status decides, the marker goes", s["rc"] == 0 and handed(s) == [] and "dropped PR #25" in s["out"], (s["rc"], s["out"], handed(s)))


# -- both paths never handle one PR
s = grp("on-group-unit-running", units="25", files=QF(["25"]))
check("a PR of the group has its own release unit running (a lone release by hand): the group is refused before anything is handed over (FAILED at release running), no call to the queue, nothing merged, the release queue paused",
      paused_group(s, "release running") and not s["mq"] and "stackshot-release-25" in glog(s), (s["rc"], glog(s)[-400:], s["mq"]))
def drop_marker(d): (d / "releases/mq-on").mkdir(parents=True, exist_ok=True); (d / "releases/mq-on/pr-23").write_text("handed to the merge queue by the group release led by PR #26\n")
s = scenario("on-lone-marker-late", merge="ok", mqhost=ON, hold="until-waiting", lockhook=drop_marker)
check("a lone release that was clear at its start and waits for the deploy lock while a group takes its PR: the marker is read again under the lock, just before the merge: FAILED at mq line, nothing merged, nothing deployed",
      s["rc"] == 1 and "FAILED at mq line" in s["log"] and "while this release waited" in s["log"] and "pr merge" not in s["gh"] and not s["deployed"] and not s["mq"], (s["rc"], s["log"][-500:], s["gh"]))
for flag in ("--group", "--run-group"):
    s = scenario("on-dup" + flag, raw=[flag, "23", "23"], mqhost=ON, units="")
    check(f"release.sh {flag} 23 23: the same PR twice is refused (usage, exit 2), nothing started, no call to the queue", s["rc"] == 2 and "different PR numbers" in s["out"] and not s["started"] and not s["mq"], (s["rc"], s["out"]))
s = scenario("on-group-door-toomany", raw=["--group", "23", "25", "35", "37", "44"], mqhost=ON, units="")
check("release.sh --group with more PRs than one hand-off (4, release.sh's own number): refused with the number, nothing started", s["rc"] == 2 and "4 at most" in s["out"] and not s["started"], (s["rc"], s["out"]))
s = q("on-q-five", "23", "25", "35", "37", "44", mqhost=ON)
check("release queue, mode on, five waiting: one hand-off of the first four (release.sh's own 4); the fifth stays queued for the next hand-off",
      s["started"] == ["23"] and started_args(s)[0].endswith("/release.sh --run-group 23 25 35 37") and s["queue"] == ["23", "25", "35", "37", "44"] and "44" in s["out"] and "next hand-off" in s["out"], (s["started"], started_args(s), s["queue"], s["out"]))
s = q("on-q-drop-handed", "--drop", "25", mqhost=ON, mq_status="active", files={**QF(["25"]), "releases/mq-on/pr-25": "2026-11-04T00:00:00Z handed to the merge queue by the group release led by PR #23\n"})
check("queue --drop of a PR a group release handed to the merge queue: says so and what to run (salamander mq drop), is not reported as dropped, exit 1, the release queue unchanged",
      s["rc"] == 1 and "handed to the merge queue" in s["out"] and "salamander mq drop 25" in s["out"] and "dropped PR #25" not in s["out"] and "releases/mq-on/pr-25" in s["out"] and handed(s) == ["pr-25"] and s["queue"] == ["23", "25"], (s["rc"], s["out"], s["queue"]))
s = q("on-q-drop-plain", "--drop", "25", mqhost=ON, files=QF(["25"]))
check("queue --drop of a PR that is not with the merge queue: as before", s["rc"] == 0 and "dropped PR #25" in s["out"] and s["queue"] == ["23"], (s["rc"], s["out"], s["queue"]))

# -- after the merge: what the old path does for its own deploy and its own failures
s = grp("on-group-unknown-sha", fullshas="", files=QF(["25"]))
check("a merge commit the checkout cannot name after the fetch: FAILED at merge commit with `merged, not live (./deploy.sh by hand)`, the release queue paused (a merge happened: the merged PRs are out of its file), nothing deployed",
      s["rc"] == 1 and "FAILED at merge commit" in glog(s) and "merged, not live" in glog(s) and s["paused"] and not s["deployed"] and "pr merge" not in s["gh"], (s["rc"], glog(s)[-500:]))
s = grp("on-group-fetch-fails", fetch_fails="9", files=QF(["25"]))
check("main cannot be fetched after the merge: FAILED at merge commit, merged and not deployed, the release queue paused", s["rc"] == 1 and "FAILED at merge commit" in glog(s) and s["paused"] and not s["deployed"], (s["rc"], glog(s)[-400:]))
s = grp("on-group-deploy-fails", deploy_fail="1", files=QF(["25", "35"]))
check("the deploy of the merge fails (healthz): FAILED at deploy, one red report for the group, the release queue paused before the lock is let go, the third PR not started; no `done:` line in either PR's log",
      s["rc"] == 1 and "FAILED at deploy" in glog(s) and s["paused"] and not s["started"] and len(red(s)) == 1 and all("done: " not in prlog(s, n) for n in (23, 25)) and all("FAILED at deploy" in prlog(s, n) for n in (23, 25)), (s["rc"], glog(s)[-500:], s["paused"], s["started"]))
s = grp("on-group-main-fails", main="fail", heads=f"{BASE},{M2}", live=M2, removed=GLOG, covered=GLOG, files=QF(["25"]))
check("main's run fails on the group's merge after the fast deploy: rolled back to the last good commit, FAILED at main's tests, the release queue paused (pause on disk before the lock is let go), the PRs not marked released",
      s["rc"] == 1 and "FAILED at main's tests" in glog(s) and s["deploys"][-1].startswith("rollback") and s["paused"] and s["paused_at_rollback"] == "present" and not s["released"], (s["rc"], s["deploys"], glog(s)[-700:], s["paused"], s["paused_at_rollback"]))
check("…and the rollback names none of the group's own members as a rider (no `PR #23 was rolled back with #23`): no PR is told it was rolled back with itself, and no member gets a rolled-back marker",
      not any("was rolled back with" in m for m in s["msgs"]) and not (s["dir"] / "releases/pr-23.rolledback").exists() and not (s["dir"] / "releases/pr-25.rolledback").exists(), (s["msgs"],))
s = grp("on-group-lock-held", hold="until-waiting", files=QF(["25"]))   # never a fixed second: a measured start can reach the lock after it was let go
check("the deploy lock is held by a lone release (its merge or deploy under way): the group waits for it before its deploy, and the lock is the one the host file names (the queue's push takes the same file)",
      s["rc"] == 0 and "another release holds the deploy lock; waiting" in glog(s) and s["deploys"] == [M2], (s["rc"], glog(s)[-500:]))
src = pathlib.Path(STACK, "release.sh").read_text()
check("the code comment says how the two paths exclude each other (the host file's deploy_lock is the lock this script takes; one thing started at a time; the marker per handed PR)",
      "HOW THE TWO PATHS EXCLUDE EACH OTHER" in src and "deploy_lock" in src.split("HOW THE TWO PATHS EXCLUDE EACH OTHER", 1)[1][:900] and "MQ_HANDED" in src.split("HOW THE TWO PATHS EXCLUDE EACH OTHER", 1)[1][:1800])

long = polls_over()
if long: fails.append("no scenario polls more than %d times" % MAX_POLLS); print("FAIL no scenario polls more than %d times: %s" % (MAX_POLLS, long))   # the guard release_scenario.py counts as a check, here without adding to the count
finish()
