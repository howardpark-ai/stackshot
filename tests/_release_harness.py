"""tests/_release_harness.py: what the release suites share (a helper module, not a suite).

release.sh's scenarios are split over two suites to keep each one's measured run short: release_scenario.py (the merge, the deploy lock, main's tests, the fast path, the
update of a branch behind main) and release_queue_scenario.py (the ride-along ledger, the retest skip, covering runs, the CI-run poller, the release queue, the shadow
merge queue). Both copy release.sh into a scenario's own folder beside stubs, which are here with `scenario()` (one run of release.sh in such a folder, everything it did
read back as a dict), `check()`, `fast()` (an up-to-date PR) and the constants and small readers the sections of both suites use. A suite imports it whole:

    from _release_harness import *

and ends with `finish()`. The lists `fails`, `ran`, `dirs` and `POLLS` are this module's own, one set per suite process. Nothing here runs a check by itself.
"""
import fcntl, json, os, pathlib, re, shutil, subprocess, sys, tempfile, threading, time
import _scratch
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
fails = []; ran = []; dirs = []
NOTLIVE = "ba5e0000000000000000000000000000000000ba"   # RT_LIVE for an old-path release that fails on main: a checkout at a commit older than the merge (the git stub says "in it" for HEAD when RT_LIVE is unset)
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:800]}" if got is not None else ""))

GH_SH = r'''#!/bin/bash
# the waits ask `pr checks` once a cycle: answered here, in shell, so a measured run (coverage and strace -f in every Python start) does not pay a Python process for it; everything else, and a park, goes to gh.py
if [ "${1:-} ${2:-}" = "pr checks" ] && [ -z "${RT_PARK_AT:-}" ]; then
    echo "$*" >> "$RT_DIR/gh.log"
    cn=1; [ ! -e "$RT_DIR/checkreads" ] || cn=$(( $(< "$RT_DIR/checkreads") + 1 )); echo "$cn" > "$RT_DIR/checkreads"
    IFS=, read -ra seq <<< "${RT_CHECKS:-pass}"; i=$((cn - 1)); [ "$i" -lt "${#seq[@]}" ] || i=$((${#seq[@]} - 1)); cv="${seq[$i]}"
    # the rows carry gh's other fields too (state, link), as `--json name,state,bucket,link` returns them. Extra values for `release.sh queue`'s read of the rows: shardfail (a matrix shard row failed, the suites row
    # still pending), timedout (state TIMED_OUT, bucket fail), skipping (a skipped row and a passing one), unreadable (gh fails with an error), nochecks (gh says no checks were reported: exit 1 and the words)
    case "$cv" in
        lint) echo '[{"name": "lint", "state": "SUCCESS", "bucket": "pass", "link": "https://ci.example/lint"}]' ;;
        toolfail) echo '[{"name": "suites", "bucket": "pending"}, {"name": "tool-text", "bucket": "fail"}]' ;;
        shardfail) echo '[{"name": "suites (shard 1/4)", "state": "SUCCESS", "bucket": "pass", "link": "https://ci.example/shard1"}, {"name": "suites (shard 3/4)", "state": "FAILURE", "bucket": "fail", "link": "https://ci.example/shard3"}, {"name": "suites", "state": "PENDING", "bucket": "pending", "link": ""}]' ;;
        timedout) echo '[{"name": "suites", "state": "TIMED_OUT", "bucket": "fail", "link": "https://ci.example/timed-out"}]' ;;
        skipping) echo '[{"name": "docs", "state": "SKIPPED", "bucket": "skipping", "link": ""}, {"name": "suites", "state": "SUCCESS", "bucket": "pass", "link": "https://ci.example/suites"}]' ;;
        unreadable) echo "GraphQL: Could not resolve to a PullRequest with the number of $3. (HTTP 502)" >&2; exit 1 ;;
        nochecks) echo "no checks reported on the 'agent/topic' branch" >&2; exit 1 ;;
        *) case "$cv" in fail) st=FAILURE ;; pass) st=SUCCESS ;; pending) st=PENDING ;; cancel) st=CANCELLED ;; *) st="${cv^^}" ;; esac
           echo "[{\"name\": \"suites\", \"state\": \"$st\", \"bucket\": \"$cv\", \"link\": \"https://ci.example/suites\"}, {\"name\": \"lint\", \"state\": \"SUCCESS\", \"bucket\": \"pass\", \"link\": \"https://ci.example/lint\"}]" ;;
    esac
    exit 0
fi
exec python3 "$RT_DIR/bin/gh.py" "$@"
'''

GH = r'''#!/usr/bin/env python3
import json, os, sys
d = os.environ["RT_DIR"]; a = sys.argv[1:]
open(f"{d}/gh.log", "a").write(" ".join(a) + "\n")
def env(k, v=""): return os.environ.get(k, v)
if a[:2] == ["pr", "view"]:
    fields = a[a.index("--json") + 1]
    if (env("RT_PRSTATE") or env("RT_PRSTATE_AFTER")) and fields in ("state,mergeCommit", "state,mergeCommit,headRefOid"):   # THE MERGE QUEUE, ON: a group release reads each PR's state first: RT_PRSTATE = "<pr>=<OPEN|MERGED|CLOSED>[@<oid>][#<head oid>],..." (a PR not listed is OPEN; MERGED with only #<head> is a fast-forward merge GitHub names no merge commit for);
        # once `mq add` was called (mq.log exists) RT_PRSTATE_AFTER answers instead when it is set (the queue merged the PR meanwhile);
        # RT_PRSTATE_FAILN = n: after `mq add` the first n reads fail (a GitHub outage), counted in prstate_failed
        if env("RT_PRSTATE_FAILN") and os.path.exists(f"{d}/mq.log"):
            nf = int(open(f"{d}/prstate_failed").read()) if os.path.exists(f"{d}/prstate_failed") else 0
            if nf < int(env("RT_PRSTATE_FAILN")): open(f"{d}/prstate_failed", "w").write(str(nf + 1)); sys.stderr.write("gh: HTTP 502\n"); sys.exit(1)
        for kv in (env("RT_PRSTATE_AFTER") if env("RT_PRSTATE_AFTER") and os.path.exists(f"{d}/mq.log") else env("RT_PRSTATE")).split(","):
            if not kv: continue
            k, v = kv.split("=", 1)
            if k == a[2]:
                v, _, head = v.partition("#"); st, _, oid = v.partition("@"); print(json.dumps({"state": st, "mergeCommit": {"oid": oid} if oid else None, "headRefOid": "" if head == "-" else (head or "abc1234def5678abc1234def5678abc1234def56")})); sys.exit(0)
        print(json.dumps({"state": "OPEN", "mergeCommit": None, "headRefOid": "abc1234def5678abc1234def5678abc1234def56"})); sys.exit(0)
    if fields == "mergeCommit":   # the old path's merge commit M (main_green looks for the runs on commits that contain it): RT_MERGE_OID, else the first main tip; "none": GitHub does not say
        oid = env("RT_MERGE_OID") or env("RT_TIPS", "0106c0de0106c0de0106c0de0106c0de0106c0de").split(",")[0]
        print(json.dumps({"mergeCommit": None if oid == "none" else {"oid": oid}})); sys.exit(0)
    if "mergeable" in fields:
        mn = int(open(f"{d}/mviews").read()) + 1 if os.path.exists(f"{d}/mviews") else 1   # one value per read, the last repeated: RT_MERGEABLE (comma-separated)
        open(f"{d}/mviews", "w").write(str(mn)); mseq = env("RT_MERGEABLE", "MERGEABLE").split(",")
        print(json.dumps({"state": "OPEN", "mergeable": mseq[min(mn, len(mseq)) - 1], "title": env("RT_TITLE", "a change"), "headRefName": "agent/topic",
                          "isCrossRepository": env("RT_CROSS") == "1", "headRefOid": (env("RT_PRHEADS") or env("RT_HEAD", "abc1234def5678abc1234def5678abc1234def56")).split(",")[min(mn, len((env("RT_PRHEADS") or "x").split(","))) - 1]})); sys.exit(0)
    n = int(open(f"{d}/views").read()) + 1 if os.path.exists(f"{d}/views") else 1
    open(f"{d}/views", "w").write(str(n))
    if env("RT_AFTER") == "merged" and n >= int(env("RT_MERGED_FROM", "1")):
        print(json.dumps({"state": "MERGED", "mergeCommit": {"oid": env("RT_MERGE_OID") or "0106c0de0106c0de0106c0de0106c0de0106c0de"}}))
    else:
        print(json.dumps({"state": "OPEN", "mergeCommit": None}))
    sys.exit(0)
if a[:2] == ["pr", "list"]:   # the open PRs based on the merged head branch (retarget_and_delete_branch): RT_STACKED, comma-separated numbers, none by default; RT_LIST=fail: the call errors
    if env("RT_LIST") == "fail": print("HTTP 502: bad gateway", file=sys.stderr); sys.exit(1)
    print(json.dumps([{"number": int(x)} for x in env("RT_STACKED").split(",") if x])); sys.exit(0)
if a[:2] == ["pr", "edit"]:   # retarget one: RT_RETARGET=fail makes every retarget error, RT_RETARGET_FAIL a comma-separated list of the numbers that error
    if env("RT_RETARGET") == "fail" or a[2] in env("RT_RETARGET_FAIL").split(","): print("GraphQL: Could not resolve to a PullRequest (updatePullRequest)", file=sys.stderr); sys.exit(1)
    sys.exit(0)
if a[:2] == ["pr", "checks"]:
    cn = int(open(f"{d}/checkreads").read()) + 1 if os.path.exists(f"{d}/checkreads") else 1
    open(f"{d}/checkreads", "w").write(str(cn)); cseq = env("RT_CHECKS", "pass").split(","); cv = cseq[min(cn, len(cseq)) - 1]
    if env("RT_PARK_AT") and cn == int(env("RT_PARK_AT")):   # the release is waiting on its tests: the test looks at --status now
        import time; open(f"{d}/parked", "w").close()
        for _ in range(600):
            if os.path.exists(f"{d}/unpark"): break
            time.sleep(0.1)
    print(json.dumps([{"name": "lint", "bucket": "pass"}] if cv == "lint" else [{"name": "suites", "bucket": "pending"}, {"name": "tool-text", "bucket": "fail"}] if cv == "toolfail"
                     else [{"name": "suites", "bucket": cv}, {"name": "lint", "bucket": "pass"}])); sys.exit(0)
def update_lock_state():   # is the update lock held (by the release that called us) at this moment
    import fcntl
    lf = open(env("UPDATE_LOCK_FILE", f"{d}/releases/update.lock"), "a")
    try: fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB); fcntl.flock(lf, fcntl.LOCK_UN); return "free"
    except OSError: return "held"
if a[:1] == ["api"] and "/commits/" in a[1] and "/check-runs" in a[1]:   # the check runs of one commit (the tests job on the updated head); RT_CHECKRUNS: one answer per read, the last repeated: pass | none (not run on this commit)
    kn = int(open(f"{d}/crreads").read()) + 1 if os.path.exists(f"{d}/crreads") else 1
    open(f"{d}/crreads", "w").write(str(kn)); kseq = env("RT_CHECKRUNS", "pass").split(","); kv = kseq[min(kn, len(kseq)) - 1]
    print(json.dumps({"check_runs": [] if kv == "none" else [{"name": "suites", "status": "completed", "conclusion": "success", "head_sha": a[1].split("/commits/")[1].split("/")[0]}]})); sys.exit(0)
if a[:2] == ["pr", "update-branch"]:
    open(f"{d}/upd_fd5", "w").write("open" if os.path.lexists(f"/proc/{os.getpid()}/fd/5") else "closed"); open(f"{d}/upd_lock_at_update", "w").write(update_lock_state())   # the update lock is held, and not given to gh   # merges main into the PR branch; RT_UPDATE=fail is a conflict; RT_UTRACE: start of the update, with a real second in it (the two-release case)
    open(f"{d}/order.log", "a").write("update-branch\n")
    if env("RT_UTRACE"):
        import time; open(env("RT_UTRACE"), "a").write(f"update-branch {d}\n"); time.sleep(1)
    if env("RT_UPDATE") == "fail":
        print("HTTP 422: merge conflict between base and head", file=sys.stderr); sys.exit(1)
    sys.exit(0)
if env("RT_BG") and a[:2] in (["pr", "merge"], ["run", "list"]):   # a child that outlives its command: it keeps every descriptor it was given (close_fds=False)
    import subprocess; bgp = subprocess.Popen(["/usr/bin/sleep", "9"], start_new_session=True, close_fds=False, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    open(f"{d}/bgpids", "a").write(f"{bgp.pid}\n")
if a[:2] == ["pr", "merge"]:
    if env("RT_UTRACE"): open(env("RT_UTRACE"), "a").write(f"merge {d}\n")
    open(f"{d}/merge_fd5", "w").write("open" if os.path.lexists(f"/proc/{os.getpid()}/fd/5") else "closed"); open(f"{d}/upd_lock_at_merge", "w").write(update_lock_state())
    open(f"{d}/merge_fd9", "w").write("open" if os.path.lexists(f"/proc/{os.getpid()}/fd/9") else "closed")   # the lock must not reach gh
    if env("RT_MERGE") == "fail":
        print("Merging pull request...", file=sys.stderr); print("HTTP 504: We couldn't respond to your request in time.", file=sys.stderr); sys.exit(1)
    sys.exit(0)
if a[:1] == ["api"] and "/check-runs/" in a[1]:   # a job's annotations (main_green: a suite that failed only when measured)
    print(env("RT_ANN", "[]")); sys.exit(0)
if a[:1] == ["api"] and "/actions/workflows/" in a[1]:   # main's runs, newest first, 100 a page (the fast path's (b)): RT_RUNS in the shape gh run list uses
    if env("RT_GH_API_FAIL"): sys.exit(1)
    pg = a[1].rsplit("page=", 1)[-1]
    raw = env("RT_RUNS", json.dumps([{"databaseId": 7, "headSha": "0106c0de0106c0de0106c0de0106c0de0106c0de"}])) if pg == "1" else env("RT_RUNS_" + pg, "[]")   # RT_RUNS_2, _3 ...: the further pages
    try: print(json.dumps({"workflow_runs": [{"id": r["databaseId"], "head_sha": r["headSha"], "conclusion": r.get("conclusion")} for r in json.loads(raw)]}))
    except Exception: print(raw)
    sys.exit(0)
if a[:1] == ["api"] and "/pulls/" in a[1] and "/files" in a[1]:   # the files the PR changed (the session pick): RT_PICKFILES, comma-separated (server.py by default); fail: the read errors
    if env("RT_PICKFILES") == "fail": print("HTTP 502: bad gateway", file=sys.stderr); sys.exit(1)
    print("\n".join(x for x in env("RT_PICKFILES", "server.py").split(",") if x)); sys.exit(0)
if a[:1] == ["api"]:
    if a[1:3] == ["-X", "DELETE"]: sys.exit(0 if env("RT_DELETE") != "fail" else 1)
    sys.exit(0 if env("RT_BRANCH") == "present" else 1)
if a[:2] == ["run", "list"]:   # main's push runs (release.sh main_green): RT_RUNS, or one run of the merge commit
    open(f"{d}/clock-extra", "a").write(env("RT_POLL_COST", "0") + "\n")   # what a look costs on the test's clock
    print(env("RT_RUNS", json.dumps([{"databaseId": 7, "headSha": "0106c0de0106c0de0106c0de0106c0de0106c0de"}]))); sys.exit(0)
import fcntl
if a[:2] == ["run", "view"]:   # one state per look at a run, the last repeated: RT_MAIN<id> or RT_MAIN, comma-separated, of
    rid = a[2]                 # pass | pending (in progress) | queued | fail | miss | savefail | replaced (cancelled while queued) | cancelled (after it started) |
                               # late (completed and green, the suites step has no conclusion yet: GitHub fills the step results in later) | lateabsent (completed and green, the job shows no steps at all) |
                               # jobfail (completed, failed, no step at all)
    open(f"{d}/order.log", "a").write("run-view\n")
    if env("RT_NEWGOOD"): open(f"{d}/releases/last-good", "w").write(env("RT_NEWGOOD") + "\n")   # another release's main run passed meanwhile and recorded a newer commit
    n = int(open(f"{d}/runviews{rid}").read()) + 1 if os.path.exists(f"{d}/runviews{rid}") else 1
    open(f"{d}/runviews{rid}", "w").write(str(n))
    lf = open(env("DEPLOY_LOCK_FILE", f"{d}/releases/deploy.lock"), "a")   # the deploy lock while main is waited for: let go
    try: fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB); fcntl.flock(lf, fcntl.LOCK_UN); open(f"{d}/lock_at_view", "a").write("free\n")
    except OSError: open(f"{d}/lock_at_view", "a").write("held\n")
    pdir = f"{d}/releases/pending-verify"   # the pending-verify records as this look sees them: name, and whether a live process holds its lock
    for nm in sorted(os.listdir(pdir)) if os.path.isdir(pdir) else []:
        pf = open(f"{pdir}/{nm}", "a")
        try: fcntl.flock(pf, fcntl.LOCK_EX | fcntl.LOCK_NB); fcntl.flock(pf, fcntl.LOCK_UN); open(f"{d}/pending_at_view", "a").write(nm + ":free\n")
        except OSError: open(f"{d}/pending_at_view", "a").write(nm + ":locked\n")
    if env("RT_VIEWING_MARK"): open(env("RT_VIEWING_MARK"), "w").close()   # this release now waits on main's run (the two-release case)
    seq = env(f"RT_MAIN{rid}", env("RT_MAIN", "pass")).split(","); v = seq[min(n, len(seq)) - 1]
    import time
    for _ in range(600 if env("RT_VIEW_AFTER") else 0):   # main's run finishes only once another release has deployed (the two-release case)
        if os.path.exists(env("RT_VIEW_AFTER")): break
        time.sleep(0.1)
    if env("RT_GRAB") and v == env("RT_GRAB_ON", "pass"):   # the test takes the deploy lock before main's run reads green (or red: the rollback's lock)
        open(f"{d}/grab-request", "w").close()
        for _ in range(200):
            if os.path.exists(f"{d}/grabbed"): break
            time.sleep(0.05)
    suites, save, audit = {"pass": ("success",) * 3, "miss": ("success", "success", "failure"), "fail": ("failure", "success", "success"),
                           "savefail": ("success", "failure", "success"), "cancelled": ("cancelled", "skipped", "skipped")}.get(v, (None, None, None))
    steps = [] if v in ("pending", "queued", "replaced", "lateabsent", "jobfail") else [{"name": "the suite map", "conclusion": "success"}, {"name": "run every suite, measured", "conclusion": suites},
                                                     {"name": "save the map", "conclusion": save}, {"name": "audit the selection", "conclusion": audit}]
    print(json.dumps({"status": {"pending": "in_progress", "queued": "queued"}.get(v, "completed"),
                      "conclusion": {"pass": "success", "late": "success", "lateabsent": "success", "pending": "", "queued": "", "replaced": "cancelled", "cancelled": "cancelled"}.get(v, "failure"),
                      "jobs": [] if v == "replaced" else [{"databaseId": 900 + int(rid), "steps": steps}]})); sys.exit(0)
sys.exit(3)
'''
GIT = r'''#!/bin/sh
echo "$*" >> "$RT_DIR/git.log"
if [ -L /proc/$$/fd/5 ]; then echo open >> "$RT_DIR/git_fd5"; else echo closed >> "$RT_DIR/git_fd5"; fi   # the update lock must not reach git
if [ -n "${RT_BG:-}" ]; then case "$1" in fetch|merge-base) setsid sh -c 'exec /usr/bin/sleep 9' >/dev/null 2>&1 </dev/null & echo $! >> "$RT_DIR/bgpids" ;; esac; fi   # a child that outlives its command (git gc --auto)
case "$*" in
  "remote get-url origin") echo "git@github.com:example-owner/stackshot.git" ;;
  "rev-parse --short HEAD") echo "0106c0d" ;;
  "rev-list --first-parent origin/main") echo "${RT_FPLIST:-}" | tr , '\n' | sed '/^$/d' ;;   # origin/main's first-parent line, newest first (RT_FPLIST, comma-separated): a PR head on it was merged by fast-forward
  "rev-list --first-parent --ancestry-path "*"..origin/main")   # RT_LANDING = "<head>=<newest>/<...>/<oldest>,...": the first-parent commits of main that have the head in their ancestry, newest first
    h="${4%%..*}"; for kv in $(echo "${RT_LANDING:-}" | tr , ' '); do [ "${kv%%=*}" = "$h" ] && echo "${kv#*=}" | tr / '\n'; done ;;
  "show origin/main:.github/mergequeue.toml") printf '%s' "${RT_MAINTOML:-}"; [ -n "${RT_MAINTOML:-}" ] || exit 128 ;;   # the rules file as origin/main has it (what mq reads): unset = the file is not there
  "rev-parse HEAD")   # the deployed checkout's HEAD, one per call, the last repeated: RT_HEADS (comma-separated)
    n=$(( $(cat "$RT_DIR/heads" 2>/dev/null || echo 0) + 1 )); echo $n > "$RT_DIR/heads"
    echo "${RT_HEADS:-}" | tr , '\n' | sed -n "$n{p;q};\${p}" | tail -1 ;;
  "rev-parse --verify --quiet origin/main^{commit}")   # main's tip before the merge (the up-to-date test); unset: unreadable, so the old path. RT_BASES: one per call, the last repeated (main moves)
    if [ -n "${RT_BASES:-}" ]; then n=$(( $(cat "$RT_DIR/bases" 2>/dev/null || echo 0) + 1 )); echo $n > "$RT_DIR/bases"; echo "$RT_BASES" | tr , '\n' | sed -n "$n{p;q};\${p}" | tail -1
    else echo "${RT_BASE:-}"; fi ;;
  "rev-parse --verify --quiet "*"^{commit}")   # THE MERGE QUEUE, ON: the merge commit the queue named by its first 7 characters, in full: the one of RT_FULLSHAS (comma-separated) that starts with it; none: no output
    p="${4%%^*}"; for f in $(echo "${RT_FULLSHAS:-}" | tr , ' '); do case "$f" in "$p"*) echo "$f"; break ;; esac; done ;;
  "log --first-parent --format=%H %s "*) echo "${RT_GROUPLOG:-}" | tr ';' '\n' | sed '/^$/d' ;;   # the merge commits between the live checkout and the queue's merge, "<sha> <subject>" a line, ;-separated: RT_GROUPLOG
  "rev-parse "*"^1") echo "${RT_P1:-${RT_BASE:-}}" ;;                          # the merge commit's parents: the tip that was checked and the pinned head
  "rev-parse "*"^2") echo "${RT_P2:-${RT_HEAD:-abc1234def5678abc1234def5678abc1234def56}}" ;;
  "log --first-parent --reverse --format=%H %s "*)   # a rollback asks twice, in this order: the merges the failing run covers (RT_COVERED), then everything between the last good commit and the live HEAD (RT_REMOVED); ;-separated
    n=$(( $(cat "$RT_DIR/logn" 2>/dev/null || echo 0) + 1 )); echo $n > "$RT_DIR/logn"
    if [ $n = 1 ]; then echo "$RT_COVERED"; else echo "$RT_REMOVED"; fi | tr ';' '\n' | sed '/^$/d' ;;
  "rev-list --first-parent --reverse "*) echo "${RT_DOCS:-}" | tr , '\n' | sed '/^$/d' ;;   # the commits between the live HEAD and main's tip (the docs-only walk): RT_DOCS
  "-c core.quotePath=false diff --no-color --no-ext-diff --no-renames --src-prefix=a/ --dst-prefix=b/ "*) printf '%s\n' "${RT_DIFF:-}" ;;                                       # what each of them changed (RT_DIFF, a git diff)
  "rev-list "*) echo "$RT_RANGE" | tr , '\n' | sed '/^$/d' ;;   # the commits between the last good one and main's tip (the fast path's (b)): RT_RANGE, comma-separated
  "diff --diff-filter=A --name-only "*) echo "$RT_NEWUNITS" | tr , '\n' | sed '/^$/d' ;;   # unit files a rollback leaves installed (RT_NEWUNITS)
  "fetch --quiet origin main refs/pull/"*)   # RT_PRFETCH_FAIL set: every fetch of the PR head fails, from the RT_PRFETCH_FROM-th one on (default the first)
    n=$(( $(cat "$RT_DIR/prfetches" 2>/dev/null || echo 0) + 1 )); echo $n > "$RT_DIR/prfetches"
    [ -z "${RT_PRFETCH_FAIL:-}" ] || [ $n -lt "${RT_PRFETCH_FROM:-1}" ] || exit 1 ;;
  "cat-file -e "*) [ -z "${RT_NOHEAD:-}" ] || case "$*" in *"$RT_NOHEAD"*) exit 1 ;; esac ;;
  "rev-parse origin/main")   # main's tip, one per call, the last repeated: RT_TIPS (comma-separated), else the merge commit
    n=$(( $(cat "$RT_DIR/tips" 2>/dev/null || echo 0) + 1 )); echo $n > "$RT_DIR/tips"
    echo "${RT_TIPS:-0106c0de0106c0de0106c0de0106c0de0106c0de}" | tr , '\n' | sed -n "$n{p;q};\${p}" | tail -1 ;;
  "merge-base --is-ancestor "*)   # A is an ancestor of B in a linear history, oldest first: RT_HISTORY (comma-separated); B = HEAD is the live checkout, RT_LIVE (unset: A is in it)
    set -- $*; ia=0; ib=0; i=0
    if [ "$4" = HEAD ]; then
      if flock -n "${DEPLOY_LOCK_FILE:-$RT_DIR/releases/deploy.lock}" true; then echo free >> "$RT_DIR/lock_at_live"; else echo held >> "$RT_DIR/lock_at_live"; fi   # the check that a passed merge is still live: under the deploy lock
      lv="${RT_LIVE:-}"; [ ! -f "$RT_DIR/deployed" ] || [ -z "${RT_LIVE_AFTER:-}" ] || lv="$RT_LIVE_AFTER"   # RT_LIVE_AFTER: the live checkout once a deploy ran (a group release deploys a commit the checkout did not have)
      [ -n "$lv" ] || exit 0; set -- "$1" "$2" "$3" "$lv"
    fi
    for c in $(echo "${RT_HISTORY:-0106c0de0106c0de0106c0de0106c0de0106c0de,0107c0de0107c0de0107c0de0107c0de0107c0de}" | tr , ' '); do
      i=$((i+1)); [ "$c" = "$3" ] && ia=$i; [ "$c" = "$4" ] && ib=$i
    done
    [ $ia -gt 0 ] && [ $ib -ge $ia ] ;;
  "fetch --quiet origin main")   # RT_FETCH_FAILS: that many fetches fail first, as one racing another release's fetch in the same checkout does
    n=$(( $(cat "$RT_DIR/fetches" 2>/dev/null || echo 0) + 1 )); echo $n > "$RT_DIR/fetches"
    [ $n -gt "${RT_FETCH_FAILS:-0}" ] || { echo "error: fetching ref refs/remotes/origin/main failed: incorrect old value provided" >&2; exit 1; } ;;
  *) exit 0 ;;
esac
'''
FAKE_FM = r'''#!/usr/bin/env bash
# a stand-in for docs-merge.sh: the same shape (PYSRC in a quoted heredoc, diff-check <diff> <repo> <sha> <tmp>), and only .md files pass
PYSRC=$(cat <<'PYEOF'
import re, sys
def diff_check(path, repo, sha, tmp):
    files = re.findall(r"^diff --git a/(\S+) b/", open(path).read(), re.M)
    bad = [f for f in files if not f.endswith(".md")]
    for f in bad: print("REFUSED: %s:0 not a doc" % f)
    print("files=%d refused=%d" % (len(files), len(bad) or (0 if files else 1)), file=sys.stderr)
    sys.exit(3 if bad or not files else 0)
if sys.argv[1] == "diff-check": diff_check(*sys.argv[2:6])
PYEOF
)
'''
FAKE_FM_NOSUB = FAKE_FM.replace('if sys.argv[1] == "diff-check": diff_check(*sys.argv[2:6])', 'if sys.argv[1] == "pr-check": diff_check(*sys.argv[2:6])')   # a dispatch that does not know diff-check: exits 0, says nothing
REAL_DM = os.environ.get("RELEASE_TEST_DOCS_MERGE", "")   # a real docs-merge script to run the same checks against, when this box has one (set by the person running the suite)
SLEEP = '#!/bin/sh\necho "$*" >> "$RT_DIR/sleep.log"\n'
# the clock the release reads (date +%s): a fixed start plus every sleep it asked for plus what each look at main's runs cost (RT_POLL_COST), so the waits are read off a clock the test controls
DATE = ('#!/bin/sh\nif [ "$1" = "+%s" ]; then\n  [ -f "$RT_DIR/clock-base" ] || /usr/bin/date +%s > "$RT_DIR/clock-base"\n'
        '  add=$(cat "$RT_DIR/sleep.log" "$RT_DIR/clock-extra" 2>/dev/null | awk \'{s+=$1} END{print s+0}\')\n  echo $(( $(cat "$RT_DIR/clock-base") + add ))\nelse exec /usr/bin/date "$@"; fi\n')
CONFIG = ('import os, sys\nif sys.argv[1:] == ["state", "releases"]: print(os.environ["RT_DIR"] + "/releases")\n'
          'def recycle_when_idle(): return os.environ.get("RT_IDLE", "").split()\n'   # [fleet] recycle_when_idle: RT_IDLE, unset = none
          'def notice_cmd(): return os.environ.get("RT_NOTICE", "").split()\n')       # [fleet] notice_cmd: RT_NOTICE, unset = none
CLIENT = ('import os, sys\nif sys.argv[1:2] == ["released"]: open(os.environ["RT_DIR"] + "/released.log", "a").write(" | ".join(sys.argv[1:]) + "\\n"); print("stackshot: closed a1"); sys.exit(1 if os.environ.get("RT_RELEASED") == "fail" else 0)\n'   # the items call is logged apart: the report order below is about deploys and reports
          'open(os.environ["RT_DIR"] + "/messages.log", "a").write(" | ".join(sys.argv[1:]) + "\\n")\n'
          'open(os.environ["RT_DIR"] + "/order.log", "a").write("client:" + sys.argv[1] + "\\n")\n'
          'if os.environ.get("RT_BG"):\n import subprocess; open(os.environ["RT_DIR"] + "/bgpids", "a").write(str(subprocess.Popen(["/usr/bin/sleep", "9"], start_new_session=True, close_fds=False, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).pid) + "\\n")\n'
          'open(os.environ["RT_DIR"] + "/client_fd5", "a").write(("open" if os.path.lexists("/proc/self/fd/5") else "closed") + "\\n")\n'
          'open(os.environ["RT_DIR"] + "/client_fd9", "a").write(("open" if os.path.lexists("/proc/self/fd/9") else "closed") + "\\n")\n'   # the lock is gone before any report or recycle child starts
          'if sys.argv[1:2] == ["recycle-due"] and os.environ.get("RT_RECYCLE_DUE") == "fail": print("stackshot: no open item is anchored"); sys.exit(1)\n')
SALA = '#!/bin/sh\necho "$*" >> "$RT_DIR/sala.log"\nexit 1\n'     # never the host's sala: a recycle request is a stub that fails
NOTIFY = ('#!/bin/sh\nfor a in "$@"; do printf "%s\\0" "$a"; done >> "$RT_DIR/notice.log"\n'
          '[ -z "${RT_NOTICE_HANG:-}" ] || { echo $$ > "$RT_DIR/notice.pid"; exec /bin/sleep 600; }\n'   # RT_NOTICE_HANG: never finishes (its pid is kept; exec, so the timeout stops this very process)
          '[ -z "${RT_NOTICE_FAIL:-}" ] || exit 1\n')   # [fleet] notice_cmd's stand-in: logs each argument it gets, NUL-ended, so a newline inside one stays visible; the real command takes exactly one text argument
# a stand-in for `salamander ci-runs`, the CI-run poller's reader: never the host's. One answer per call, the last repeated: RT_SALAMANDER, comma-separated, of
# none (exit 3, no file; the default) | stale (4) | unreadable (5) | usage (2) | garbage (exit 0, not JSON) | empty (exit 0, no run of the sha listed) | running | queued | completed | mixed (one completed run of the sha and one running)
# RT_SALAMANDER_EVENT (push), RT_SALAMANDER_CONCLUSION (success) and RT_SALAMANDER_RUNID (7) shape the run it lists for the sha it was asked about.
# The default answer (none) comes from a shell stub: the measured run on main (coverage in every Python child, under strace -f) made one Python start per wait
# cycle of every scenario cost enough to push the suite past its 1800 s limit (main's run 9000001); the Python one below answers only a scenario that sets RT_SALAMANDER.
SALAMANDER_SH = ('#!/bin/sh\n'
                 # `salamander mq` (THE MERGE QUEUE, SHADOW): a stand-in that logs its arguments apart from ci-runs' (mq.log) and answers from RT_MQ_ADD (ok | fail | slow) and RT_MQ_WAIT
                 # (tested = exit 3, the shadow verdict | failed = 1 | ejected-merged = 1 with the queue's own words for a PR the old path merged first | ejected-left = 1, the PR left the group because the old path's merge closed it | ejected-conflict = 1, a real eject reason | gaveup = 2 | error = 7)
                 'if [ "${1:-}" = mq ]; then\n  echo "$*" >> "$RT_DIR/mq.log"\n'
                 # THE MERGE QUEUE, ON: RT_MQ_PRS = "<pr>=<kind>[@<sha7>],..." answers `mq wait <pr>` per PR (kinds: merged | failed | ejected | gaveup | error | notinline | tested), RT_MQ_STATUS = paused | blocked answers `mq status --json`,
                 # RT_MQ_DROP = fail makes `mq drop` exit 1; RT_MQ_ADD = refused is salamander's own refusal while its ON_OPEN switch is false, timeout never answers within the release's cap
                 '  if [ "${2:-}" = wait ] && [ -n "${RT_MQ_PRS:-}" ]; then\n'
                 '    [ -z "${RT_MQ_DRIVERLINE:-}" ] || echo "driver started (mq-example-owner__stackshot)" >&2   # what `mq wait` prints to stderr when it had to start the driver again: the first line of 2>&1\n'
                 '    for kv in $(echo "$RT_MQ_PRS" | tr , " "); do\n      [ "${kv%%=*}" = "$3" ] || continue; v="${kv#*=}"; k="${v%%@*}"; sh="${v#*@}"; [ "$sh" != "$v" ] || sh=a1b2c3d\n'
                 '      case "$k" in\n'
                 '        merged) echo "PR $3 merged: merged in group g1 at $sh [g1]"; exit 0 ;;\n'
                 '        mergednosha) echo "PR $3 merged: merged in group g1 [g1]"; exit 0 ;;\n'
                 '        mergedpause) echo "PR $3 merged: merged in group g1 at $sh [g1]"; echo "PR #22 failed at the main tests after its merge, 2026-11-04T00:00:00Z" > "$RT_DIR/releases/queue.paused"; exit 0 ;;   # merged, and release.sh queue is paused right after (a lone release rolled back)\n'
                 '        failed) echo "PR $3 failed: required check suites failed in group g1 [g1]"; echo "PR $3 failed: required check suites failed in group g1 [g1]" >&2; exit 1 ;;\n'
                 '        ejected) echo "PR $3 ejected: refused: conflicts with main or with PR #1 ahead of it (app.py) [g1]"; echo "PR $3 ejected: refused: conflicts with main or with PR #1 ahead of it (app.py) [g1]" >&2; exit 1 ;;\n'
                 '        gaveup) echo "${RT_MQ_SLICE_COST:-300}" >> "$RT_DIR/clock-extra"; [ -z "${RT_MQ_PAUSEQ:-}" ] || echo "PR #22 failed at the main tests after its merge, 2026-11-04T00:00:00Z" > "$RT_DIR/releases/queue.paused"; echo "PR $3: gave up waiting after 5s (still grouped)" >&2; exit 2 ;;\n'   # a slice that ran out took its time on the test clock
                 '        error) echo "salamander mq: state file unreadable" >&2; exit 1 ;;\n'
                 '        blocked) echo "PR $3 is waiting and the queue is blocked: bad repo config" >&2; exit 2 ;;\n'   # the real line: exit 2 without "gave up"
                 '        skipped) echo "PR $3 built, not tested (replay ci = skip: the group was built, nothing was pushed or tested; this is not a pass) [g1]"; exit 4 ;;\n'
                 '        ejectedmerged) echo "PR $3 ejected: pull request is merged [g1]"; echo "PR $3 ejected: pull request is merged [g1]" >&2; exit 1 ;;\n'
                 '        notinline) echo "PR $3 is not in the line" >&2; exit 2 ;;\n'
                 '        tested) echo "PR $3 tested: group g1 passed in shadow [g1]"; exit 3 ;;\n'
                 '      esac\n    done\n  fi\n'
                 '  if [ "${2:-}" = status ]; then case "${RT_MQ_STATUS:-}" in\n'
                 '    paused) echo \'{"paused": {"reason": "the merge push failed 5 times", "since": 1, "by": "driver"}, "blocked": null, "queue": []}\'; exit 0 ;;\n'
                 '    blocked) echo \'{"paused": null, "blocked": {"reason": "bad repo config", "since": 1}, "queue": []}\'; exit 0 ;;\n'
                 '    error) echo "salamander mq: cannot read the state file" >&2; exit 1 ;;\n'
                 '    active) echo \'{"paused": null, "blocked": null, "queue": [{"pr": 23, "state": "waiting"}, {"pr": 25, "state": "grouped"}, {"pr": 26, "state": "merged"}]}\'; exit 0 ;;\n'
                 '    *) echo \'{"paused": null, "blocked": null, "queue": []}\'; exit 0 ;;\n  esac; fi\n'
                 '  if [ "${2:-}" = drop ]; then\n'
                 '    [ -z "${RT_MQ_DROP:-}" ] || { echo "salamander mq: cannot lock the queue state" >&2; exit 1; }\n'
                 '    case "${RT_MQ_ADD:-ok}" in ok|slow) ;; *) echo "PR $3 is not in the line" >&2; exit 1 ;; esac   # an add that was refused or never answered queued nothing: the real drop says so and exits 1\n'
                 '    case ",${RT_MQ_PRS:-}," in *",$3=merged"*|*",$3=failed"*|*",$3=ejected"*|*",$3=ejectedmerged"*) echo "PR $3 is not in the line" >&2; exit 1 ;; esac   # settled already\n'
                 '    echo "PR $3 dropped"; exit 0\n  fi\n'
                 '  case "${2:-}" in\n'
                 '    add) case "${RT_MQ_ADD:-ok}" in\n'
                 '           refused) echo "salamander mq: mode \\"on\\" is not open yet (the merge step is built, the switch to it is a step of its own: docs/mq.md, Migration); use mode = \\"shadow\\". Nothing was queued." >&2; exit 1 ;;\n'
                 '           timeout) exec /usr/bin/sleep 30 ;;\n'
                 '           ok) for a in "$@"; do case "$a" in [0-9]*) echo "PR $a: queued" ;; esac; done; echo "mode on: tested groups are merged into main; driver started (mq-example-owner__stackshot)"; exit 0 ;;\n'
                 '           fail) echo "salamander mq: mode is off for example-owner/stackshot (host config /nowhere/example-owner__stackshot.toml); nothing was queued." >&2; exit 1 ;;\n'
                 '           slow) echo $$ > "$RT_DIR/mq-add.pid"; exec /usr/bin/sleep 6 ;;\n         esac ;;\n'
                 '    wait) case "${RT_MQ_WAIT:-tested}" in\n'
                 '           tested) echo "PR $3 tested: group g1 passed in shadow [g1]"; exit 3 ;;\n'
                 '           failed) echo "PR $3 failed: required check suites failed in group g1 [g1]"; echo "PR $3 failed: required check suites failed in group g1 [g1]" >&2; exit 1 ;;\n'
                 '           ejected-merged) echo "PR $3 ejected: pull request is merged [g1]"; echo "PR $3 ejected: pull request is merged [g1]" >&2; exit 1 ;;\n'
                 '           ejected-left) echo "PR $3 ejected: left the group before the merge (closed, changed or moved) [g27]"; echo "PR $3 ejected: left the group before the merge (closed, changed or moved) [g27]" >&2; exit 1 ;;\n'
                 '           ejected-conflict) echo "PR $3 ejected: conflict with main in group g27 [g27]"; echo "PR $3 ejected: conflict with main in group g27 [g27]" >&2; exit 1 ;;\n'
                 '           gaveup) echo "PR $3: gave up waiting after 5s (still grouped)" >&2; exit 2 ;;\n'
                 '           error) echo "salamander mq: state file unreadable" >&2; exit 7 ;;\n'
                 '           hosterr) echo "salamander mq: /nowhere/example-owner__stackshot.toml: unknown key \'colour\'" >&2; exit 1 ;;\n'   # host_or_exit: exit 1 like a failed PR, but its own words
                 '           titled) echo "PR $3 failed: a title with FAILED at x and done: y in it [g1]"; echo "PR $3 failed: a title with FAILED at x and done: y in it [g1]" >&2; exit 1 ;;\n         esac ;;\n'
                 '  esac\n  exit 2\nfi\n'
                 'echo "$*" >> "$RT_DIR/salamander.log"\n'
                 'case "${RT_SALAMANDER:-none}" in none) echo "no file" >&2; exit 3;; esac\nexec python3 "$RT_DIR/bin/salamander.py" "$@"\n')
# systemd-run for the shadow comparison unit: logs its arguments (systemd-run.log) and, like the unit would, runs the command after its options at once, in this environment (RT_MQ_UNIT_FAIL: it refuses)
SYSTEMD_RUN_MQ = ('#!/bin/sh\necho "$*" >> "$RT_DIR/systemd-run.log"\n'
                  '[ -z "${RT_MQ_UNIT_FAIL:-}" ] || { echo "Failed to start transient service unit: Unit stackshot-mq-shadow-a.service was already loaded" >&2; exit 1; }\n'
                  'while [ $# -gt 0 ]; do case "$1" in */release.sh) break ;; esac; shift; done\nexec "$@"\n')
SALAMANDER = r'''import json, os, sys, time
d = os.environ["RT_DIR"]; a = sys.argv[1:]
n = int(open(f"{d}/salcalls").read()) + 1 if os.path.exists(f"{d}/salcalls") else 1
open(f"{d}/salcalls", "w").write(str(n)); seq = os.environ.get("RT_SALAMANDER", "none").split(","); v = seq[min(n, len(seq)) - 1]
codes = {"none": (3, "no file"), "stale": (4, "file is older than --max-age"), "unreadable": (5, "unreadable"), "usage": (2, "usage")}
if v in codes: print(codes[v][1], file=sys.stderr); sys.exit(codes[v][0])
if v == "garbage": print("this is not json"); sys.exit(0)
sha = a[a.index("--sha") + 1] if "--sha" in a else ""
def run(status, rid=None):
    return {"id": int(rid or os.environ.get("RT_SALAMANDER_RUNID", "7")), "name": "tests", "head_sha": sha, "head_branch": "main", "event": os.environ.get("RT_SALAMANDER_EVENT", "push"),
            "status": status, "conclusion": os.environ.get("RT_SALAMANDER_CONCLUSION", "success") if status == "completed" else None, "run_attempt": 1}
runs = {"empty": [], "running": [run("in_progress")], "queued": [run("queued")], "completed": [run("completed")], "mixed": [run("completed", 3), run("in_progress")]}[v]
print(json.dumps({"repo": "example-owner/stackshot", "updated": int(time.time()) - 5, "updated_iso": "2026-10-29T00:00:00Z", "runs": runs}, separators=(",", ":"))); sys.exit(0)
'''
# PATH without a real salamander (box-a has one in ~/.local/bin): for the scenario that has none on PATH at all
CLEAN_PATH = os.pathsep.join(x for x in os.environ.get("PATH", "").split(os.pathsep) if not os.access(os.path.join(x or ".", "salamander"), os.X_OK))
DEPLOY = ('#!/bin/sh\ntouch "$RT_DIR/deployed"\necho "${DEPLOY_TO:-}" > "$RT_DIR/deploy_to"\n'   # the commit release.sh pinned the deploy to
          'echo "${DEPLOY_ROLLBACK:+rollback }${DEPLOY_TO:-}" >> "$RT_DIR/deploys"\necho "deploy:${DEPLOY_TO:-}" >> "$RT_DIR/order.log"\n'   # every deploy, in order (a rollback is marked)
          '[ -z "${DEPLOY_ROLLBACK:-}" ] || { [ -f "$RT_DIR/releases/queue.paused" ] && echo present || echo absent; } > "$RT_DIR/paused_at_rollback"\n'   # the pause must be on disk before the lock is let go
          '[ -z "${RT_CLOBBER:-}" ] || echo \'touch "$RT_DIR/stale-read"\' >> "$(dirname "$0")/release.sh"\n'   # a deploy replaces release.sh itself: what is appended must never be read
          '[ -z "${RT_DEPLOYED_MARK:-}" ] || touch "$RT_DEPLOYED_MARK"\n'   # what the lock looks like from inside a deploy: held by the release, and not inherited through fd 9
          'if flock -n "${DEPLOY_LOCK_FILE:-$RT_DIR/releases/deploy.lock}" true; then echo free > "$RT_DIR/lock_during"; else echo held > "$RT_DIR/lock_during"; fi\n'
          'cat "$RT_DIR/lock_during" >> "$RT_DIR/locks"\n'
          'if flock -n "${UPDATE_LOCK_FILE:-$RT_DIR/releases/update.lock}" true; then echo free > "$RT_DIR/upd_lock_at_deploy"; else echo held > "$RT_DIR/upd_lock_at_deploy"; fi\n'
          'for f in "$RT_DIR"/releases/pending-verify/pr-*; do [ -f "$f" ] || continue; if flock -n "$f" true; then echo "$(basename $f):free"; else echo "$(basename $f):locked"; fi; done >> "$RT_DIR/pending_at_deploy"\n'   # the record, as the deploy sees it
          'if [ -L /proc/$$/fd/7 ]; then echo open > "$RT_DIR/fd7"; else echo closed > "$RT_DIR/fd7"; fi\n'   # the lock as every deploy saw it, in order
          'if [ -L /proc/$$/fd/9 ]; then echo open > "$RT_DIR/fd9"; else echo closed > "$RT_DIR/fd9"; fi\n'
          '[ -z "${RT_TRACE:-}" ] || { echo "start $RT_DIR" >> "$RT_TRACE"; python3 -c "import time; time.sleep(1)"; echo "end $RT_DIR" >> "$RT_TRACE"; }\n'
          'echo "deploy: fast-forward"\necho "  restarted stackshot.service"\n'
          '[ -z "${RT_DEPLOY_FAIL:-}" ] || { echo "healthz did not answer"; exit 1; }\n'
          '[ -z "${RT_ROLLBACK_FAIL:-}" ] || [ -z "${DEPLOY_ROLLBACK:-}" ] || { echo "rollback: healthz did not answer"; exit 1; }\n')

POLLS = []   # (scenario, sleeps): checked at the end, see MAX_POLLS
MAX_POLLS = 200   # a scenario that waits main's run out to the default RELEASE_CAP_MAIN (3 h) polls 540 times: 40 s plainly, past
                  # its 100 s under coverage (a slow run on a busy box). lock-outside-checks' 150 are its point


# the release queue's scenarios: systemctl answers is-active from RT_ACTIVE (the PRs whose release unit runs), systemd-run starts nothing and writes down the PR it was asked to
# start (and start:<pr> in the order log); RT_START_FAIL: that PR's start fails. Never the host's systemd
SYSTEMCTL = ('#!/bin/sh\necho "$*" >> "$RT_DIR/systemctl.log"\nfor a; do u=$a; done\nq=0; case " $* " in *" --quiet "*) q=1 ;; esac\n'
             'for p in ${RT_ACTIVE:-}; do [ "$u" = "stackshot-release-$p.service" ] && { [ $q = 1 ] || echo active; exit 0; }; done\n[ $q = 1 ] || echo inactive; exit 3\n')
SYSTEMD_RUN = ('#!/bin/sh\nn=$(echo "$*" | sed -E \'s/.*--unit stackshot-release-([0-9]+).*/\\1/\')\n'
               '[ "$n" != "${RT_START_FAIL:-}" ] || { echo "Failed to start transient service unit: Unit stackshot-release-$n.service was already loaded" >&2; exit 1; }\n'
               'echo "$n" >> "$RT_DIR/started"\necho "start:$n" >> "$RT_DIR/order.log"\necho "$*" >> "$RT_DIR/started-args"\n')   # started-args: what each unit was asked to run (a group's PRs follow --run-group)

def scenario(name, args=(), front=False, hold=None, extra=None, grab=False, secs=None, pr="23", reuse=None, pending=None, kill_at=False, raw=None, units=None, files=None, lockhook=None, side=None, **env):
    """hold: a number of seconds, True (until the run ends) or "until-waiting" (until the release logs that it waits for the lock, then 0.3 s more)
    the lock file is held by this process, as another release's deploy would.
    grab: the lock is taken by this process when main's run is about to read green (after the merge let it go), and held to the end.
    secs: how long release.sh may take before the scenario fails as hung (default 120 s; 360 s in a measured run, where coverage and strace -f
    stretch every process start and a shared runner can stall one scenario past 120 s that takes about a second plainly).
    units: the release queue's scenarios (stub systemctl and systemd-run): the PRs whose release unit is running, space-separated ("" none).
    files: {path under the scenario's folder: text} written before the run (the queue's files, say).
    lockhook: called with the scenario's folder once the release waits for the lock, before the lock is let go (hold="until-waiting").
    side: the number of a second release (`release.sh --run <side>`, the same environment) that is started before this one and waits for the deploy lock the harness holds (needs hold=):
    this release starts only when the second one logs that it waits. Its exit code and log come back as side_rc and side_log."""
    if secs is None: secs = 360 if os.environ.get("COVERAGE_PROCESS_START") else 120   # a measured run (suitemap.py sets COVERAGE_PROCESS_START) gets longer
    d = reuse["dir"] if reuse else pathlib.Path(_scratch.mkdtemp(prefix=f"releasetest-{name}-"))   # reuse: the same state directory again, as a later start of release.sh sees it
    dirs.append(d); box = d / "box"; box.mkdir(exist_ok=True); (d / "bin").mkdir(exist_ok=True)
    if env.get("lastgood"): (d / "releases").mkdir(exist_ok=True); (d / "releases/last-good").write_text(env.pop("lastgood") + "\n")   # the record main's passing runs keep
    if env.get("marker"): (d / "releases").mkdir(exist_ok=True); (d / "releases" / f"pr-{pr}.rolledback").write_text(env.pop("marker") + "\n")   # another release's failure rolled this one back
    if env.get("pre_lockdir"): (d / "releases/last-good.lock").mkdir(parents=True); env.pop("pre_lockdir")                                 # the record's lock file is unusable
    if env.get("ledger") is not None: (d / "releases").mkdir(exist_ok=True); (d / "releases/fast-ok.json").write_text(env.pop("ledger"))   # the fast-ok ledger a release finds: its text as it stands
    if env.get("ledger_lockdir"): (d / "releases").mkdir(exist_ok=True); (d / "releases/fast-ok.json.lock").mkdir(); env.pop("ledger_lockdir")   # the ledger's lock file is unusable (a folder)
    shutil.copy(os.path.join(STACK, "release.sh"), box / "release.sh")
    for rel, text in (files or {}).items(): (d / rel).parent.mkdir(parents=True, exist_ok=True); (d / rel).write_text(text)
    if units is not None:
        for p, body in ((d / "bin/systemctl", SYSTEMCTL), (d / "bin/systemd-run", SYSTEMD_RUN)): p.write_text(body); p.chmod(0o755)
        env["active"] = units
    mqhost = env.pop("mqhost", None)   # THE MERGE QUEUE, SHADOW: the host file's text (a bare mode word is written as `mode = "<word>"`); None = no file. The folder is the scenario's own either way, never the real ~/.config
    if mqhost is not None:
        (d / "xdg/mergequeue").mkdir(parents=True, exist_ok=True)
        (d / "xdg/mergequeue/example-owner__stackshot.toml").write_text(mqhost.replace("@DIR@", str(d)) if "=" in mqhost else f'mode = "{mqhost}"\n')
        if units is None: (d / "bin/systemd-run").write_text(SYSTEMD_RUN_MQ); (d / "bin/systemd-run").chmod(0o755)
    nosal = env.pop("nosalamander", False)   # no `salamander` on PATH at all (the host's own is taken off it too); else the stub above answers, exit 3 (no file) unless RT_SALAMANDER says otherwise
    fm = env.pop("fm", None)   # docs-merge.sh as the allow-list: "fake" (a stub checker that accepts only .md paths), "real" (the one on this box), else none
    if fm in ("fake", "nosub"): (d / "docs-merge.sh").write_text(FAKE_FM if fm == "fake" else FAKE_FM_NOSUB)
    for p, body, x in ((box / "config.py", CONFIG, False), (box / "client.py", CLIENT, False), (box / "deploy.sh", DEPLOY, True),
                       (d / "bin/gh", GH_SH, True), (d / "bin/gh.py", GH, False), (d / "bin/git", GIT, True), (d / "bin/sleep", SLEEP, True), (d / "bin/sala", SALA, True), (d / "bin/notify", NOTIFY, True), (d / "bin/date", DATE, True), *(() if nosal else ((d / "bin/salamander", SALAMANDER_SH, True), (d / "bin/salamander.py", SALAMANDER, False)))):
        p.write_text(body); x and p.chmod(0o755)
    e = {**os.environ, "PATH": f"{d}/bin:" + (CLEAN_PATH if nosal else os.environ.get("PATH", "")), "RT_DIR": str(d), "XDG_CONFIG_HOME": str(d / "xdg"), "RELEASE_POLL_MAIN": "20", "RELEASE_POLL_PR": "20", "RELEASE_GH_TTL": "0", "RELEASE_SKIP_DISJOINT": "0", **{f"RT_{k.upper()}": v for k, v in env.items()}, **(extra or {})}   # the suite's waits are the 20 s ones it was written for, and no read is reused unless a scenario asks
    e["DOCS_MERGE_SCRIPT"] = {"fake": str(d / "docs-merge.sh"), "nosub": str(d / "docs-merge.sh"), "real": REAL_DM}.get(fm, str(d / "no-such-docs-merge.sh"))
    held = None; timer = None
    if hold is not None:
        (d / "releases").mkdir(exist_ok=True); held = open(d / "releases/deploy.lock", "w"); fcntl.flock(held, fcntl.LOCK_EX)
        if hold == "until-waiting":   # never a fixed time: a slow start (a measured run under strace) would reach the lock after it was let go
            def unhold(logs=(d / "releases" / f"pr-{pr}.log", d / "releases" / f"group-{pr}.log"), end=time.time() + 60):   # a lone release logs to its PR's file, a group's to the group's
                while time.time() < end and not any("another release holds the deploy lock; waiting" in (l.read_text() if l.exists() else "") for l in logs): time.sleep(0.05)
                time.sleep(0.3)
                if lockhook: lockhook(d)
                fcntl.flock(held, fcntl.LOCK_UN)
            timer = threading.Thread(target=unhold); timer.start()
        elif hold is not True: timer = threading.Timer(hold, lambda: fcntl.flock(held, fcntl.LOCK_UN)); timer.start()
    side_thread = None; side_res = {}
    if side:   # started before the pending record is written: it must not find it. It waits for the lock the harness holds; this release starts once it says so
        def run_side(): side_res["r"] = subprocess.run(["bash", str(box / "release.sh"), "--run", side], env=e, capture_output=True, text=True, timeout=secs)
        side_thread = threading.Thread(target=run_side); side_thread.start()
        slog = d / "releases" / f"pr-{side}.log"; end = time.time() + 60
        while time.time() < end and "another release holds the deploy lock; waiting" not in (slog.read_text() if slog.exists() else ""): time.sleep(0.05)
    pheld = []
    for pend in ([pending] if isinstance(pending, dict) else pending or []):   # records a release left: {"sha":, "pr":, "age": seconds, "held": a live process holds its lock}
        pf = d / "releases/pending-verify" / f"pr-{pend['pr']}"; pf.parent.mkdir(parents=True, exist_ok=True)
        pf.write_text(f"sha={pend['sha']}\npr={pend['pr']}\nepoch={int(time.time()) - pend.get('age', 60)}\ntime=then\n")
        if pend.get("held"): pheld.append(open(pf, "a")); fcntl.flock(pheld[-1], fcntl.LOCK_EX)
    grabber = None; done = threading.Event()
    if grab:
        e["RT_GRAB"] = "1"
        def grabbing():
            while not (d / "grab-request").exists() and not done.is_set(): done.wait(0.02)
            if done.is_set(): return
            lf = open(e.get("DEPLOY_LOCK_FILE", d / "releases/deploy.lock"), "a"); fcntl.flock(lf, fcntl.LOCK_EX); (d / "grabbed").touch()
            done.wait(); lf.close()
        grabber = threading.Thread(target=grabbing); grabber.start()
    argv = ["bash", str(box / "release.sh"), *(raw if raw is not None else [pr, *args] if front else ["--run", pr, *args])]   # raw: the arguments as given (the dry runs)
    if kill_at:   # SIGKILL the whole release (its process group) while it waits on main's run after the fast deploy: nothing of it runs again
        e["RT_VIEWING_MARK"] = str(d / "parked"); e["RT_VIEW_AFTER"] = str(d / "never")
        proc = subprocess.Popen(argv, env=e, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)
        for _ in range(1200):
            if (d / "parked").exists() or proc.poll() is not None: break
            time.sleep(0.05)
        try: os.killpg(proc.pid, 9)
        except ProcessLookupError: pass
        o, _ = proc.communicate(); r = subprocess.CompletedProcess(argv, proc.returncode, o, "")
    else: r = subprocess.run(argv, env=e, capture_output=True, text=True, timeout=secs)
    for ph in pheld: ph.close()
    if grabber: done.set(); grabber.join()
    if timer: timer.join()
    if side_thread: side_thread.join()
    if held: held.close()
    rd = lambda f: (d / f).read_text() if (d / f).exists() else ""
    POLLS.append((name, len(rd("sleep.log").split())))
    return {"rc": r.returncode, "out": r.stdout + r.stderr, "gh": rd("gh.log"), "sal": rd("salamander.log").splitlines(), "sleeps": rd("sleep.log").split(),
            "released": rd("released.log").splitlines(), "msg": rd("messages.log"), "deployed": (d / "deployed").exists(), "log": rd(f"releases/pr-{pr}.log"), "dir": d,
            "lock_during": rd("lock_during").strip(), "fd9": rd("fd9").strip(), "merge_fd9": rd("merge_fd9").strip(),
            "client_fd9": rd("client_fd9").split(), "client_fd5": rd("client_fd5").split(), "git_fd5": rd("git_fd5").split(), "upd_fd5": rd("upd_fd5"), "merge_fd5": rd("merge_fd5"),
            "ulock": [rd("upd_lock_at_update"), rd("upd_lock_at_merge"), rd("upd_lock_at_deploy").strip()], "deploy_to": rd("deploy_to").strip(),
            "deploys": rd("deploys").splitlines(), "locks": rd("locks").split(), "order": rd("order.log").split(), "lastgood": rd("releases/last-good").strip(),
            "msgs": [l for l in rd("messages.log").splitlines() if l.startswith("message |")],
            "pending_files": sorted(p.name for p in (d / "releases/pending-verify").iterdir()) if (d / "releases/pending-verify").is_dir() else [],
            "pending_at_view": rd("pending_at_view").split(), "pending_at_deploy": rd("pending_at_deploy").split(), "fd7": rd("fd7").strip(),
            "bgpids": [int(x) for x in rd("bgpids").split()], "notice": [a for a in rd("notice.log").split("\0")][:-1], "notice_pid": rd("notice.pid").strip(), "sala": rd("sala.log"), "lock_at_live": rd("lock_at_live").split(),"git": rd("git.log"),
            "lockfile": pathlib.Path(e.get("DEPLOY_LOCK_FILE", d / "releases/deploy.lock")),
            "side_rc": side_res["r"].returncode if side_res.get("r") else None, "side_log": rd(f"releases/pr-{side}.log") if side else "", "paused_at_rollback": rd("paused_at_rollback").strip(),
            "started": rd("started").split(), "queue": rd("releases/queue").split(), "driver": rd("releases/queue.driver").strip(), "paused": rd("releases/queue.paused"), "qlog": rd("releases/queue.log"),
            "mq": rd("mq.log").splitlines(), "mq_old": "".join(p.read_text() for p in sorted((d / "releases/mq-shadow").glob(f"pr-{pr}-*.old"))) if (d / "releases/mq-shadow").is_dir() else "", "mq_files": sorted(p.name for p in (d / "releases/mq-shadow").glob("*.old")) if (d / "releases/mq-shadow").is_dir() else [], "sysrun": rd("systemd-run.log").splitlines(), "ledger": rd("releases/fast-ok.json"), "ledger_files": sorted(p.name for p in (d / "releases").iterdir() if p.name.startswith("fast-ok")) if (d / "releases").is_dir() else []}

def lock_free(s):   # nothing the release left behind holds the lock, and no report child got fd 9
    if s["lockfile"].exists():
        lk = open(s["lockfile"], "a")
        try: fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError: return False
        finally: lk.close()
    return all(c == "closed" for c in s["client_fd9"])

def deletes(s): return [l for l in s["gh"].splitlines() if l.startswith("api -X DELETE")]
def refchecks(s): return [l for l in s["gh"].splitlines() if l.startswith("api repos/") and "/git/ref/" in l]   # the branch lookups, not a job's annotations

GREEN_ARGS = " | --sender | release | --release | green | --pr | https://github.com/example-owner/stackshot/pull/23"
HEADSHA = "abc1234def5678abc1234def5678abc1234def56"
def merges(s): return [l for l in s["gh"].splitlines() if l.startswith("pr merge")]
genv = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": os.devnull}
def g(*a, cwd=None): return subprocess.run(["git", *a], cwd=cwd, env=genv, capture_output=True, text=True, check=True).stdout.strip()
BASE = "ba5e0000000000000000000000000000000000ba"; MERGE = "0106c0de0106c0de0106c0de0106c0de0106c0de"; GOOD = "600d0000000000000000000000000000000000d1"
NEWER = "0107c0de0107c0de0107c0de0107c0de0107c0de"; LATER = "5ec00000000000000000000000000000000000c2"
HIST = ",".join([GOOD, BASE, HEADSHA, MERGE, LATER, NEWER])
GOOD_RUN = {"databaseId": 1, "headSha": GOOD, "conclusion": "success"}   # the run list reaches the last good commit (what (b) needs to call it readable)
def fast(name, **kw):   # an up-to-date PR (main's tip BASE is in its head's history), the checkout deployed at BASE (the live HEAD is main's tip), GOOD the recorded last good commit
    noreach = kw.pop("noreach", False)   # runs given: newest first; the last good commit's run is added at the end, unless the test is about the list not reaching it
    if "runs" not in kw: kw["runs"] = json.dumps([{"databaseId": 7, "headSha": MERGE}, GOOD_RUN])
    elif kw["runs"] != "not json" and not noreach: kw["runs"] = json.dumps([*json.loads(kw["runs"]), GOOD_RUN])
    return scenario(name, **{**dict(base=BASE, history=HIST, heads=BASE, lastgood=GOOD, good=GOOD), **kw})
def red(s): return [m for m in s["msgs"] if "FAILED" in m]
def lock_views(s): return (s["dir"] / "lock_at_view").read_text().split() if (s["dir"] / "lock_at_view").exists() else []
NEWPR = "b0b0000000000000000000000000000000000b0b"
MD = "diff --git a/docs/x.md b/docs/x.md\n--- a/docs/x.md\n+++ b/docs/x.md\n@@ -1 +1 @@\n-old\n+new"
CODE = "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-x = 1\n+x = 2"
PEND = {"sha": BASE, "pr": "26"}
RUNS67 = json.dumps([{"databaseId": 6, "headSha": BASE}, {"databaseId": 7, "headSha": MERGE}])
H1 = "d00d1000000000000000000000000000000000d1"; H2 = "d00d2000000000000000000000000000000000d2"; H3 = "d00d3000000000000000000000000000000000d3"
B2 = "ba5e2000000000000000000000000000000000b2"; B3 = "ba5e3000000000000000000000000000000000b3"; B4 = "ba5e4000000000000000000000000000000000b4"
TAIL = [MERGE, LATER, NEWER]
HIST_B = ",".join([GOOD, HEADSHA, BASE, *TAIL])                      # the PR head is behind main's tip BASE
HIST_1 = ",".join([GOOD, HEADSHA, BASE, H1, *TAIL])                 # after one update the head H1 contains BASE
def file_free(f):   # nobody holds a flock on this file
    if not pathlib.Path(f).exists(): return True
    lk = open(f, "a")
    try: fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB); return True
    except OSError: return False
    finally: lk.close()
def upd_lock_free(s): return file_free(s["dir"] / "releases" / "update.lock")
def at(log, *parts):   # the parts appear in the log in this order
    i = -1
    for p in parts:
        j = log.find(p, i + 1)
        if j < 0: return False
        i = j
    return True
UPD_LINE = "pr update-branch 23 --repo example-owner/stackshot"

def polls_over(): return [f"{n} ({k})" for n, k in POLLS if k > MAX_POLLS]

def finish():   # the end of a suite: its scratch folders go, the count is printed, the exit status says whether a check failed
    for d in dirs: shutil.rmtree(d, ignore_errors=True)
    print(f"{len(ran) - len(fails)}/{len(ran)} passed" + (f" — FAILED: {', '.join(fails)}" if fails else ""))
    sys.exit(1 if fails else 0)
