#!/usr/bin/env bash
# deploy.sh — the builder's one command on the server box: bring this checkout to origin/main and restart what the change
# touched. main is production: whatever is merged there is what this runs.
#
#   ./deploy.sh              fetch, fast-forward main, install changed units, restart the affected services, check health
#   ./deploy.sh --dry-run    say what would happen (the commits and the restarts), change nothing
#   DEPLOY_TO=<sha> ...      fast-forward to that commit of origin/main instead of its tip: release.sh pins the deploy to the commit
#                            main's tests passed on, so a merge another release landed meanwhile waits for its own run;
#                            a checkout that already contains the commit (a later release deployed past it) has nothing to do
#   DEPLOY_ROLLBACK=1 DEPLOY_TO=<sha> ...   go BACK to that older commit of origin/main: release.sh's rollback, when main's
#                            tests fail on a commit it deployed at the merge. Only the value 1 counts. Without it a DEPLOY_TO behind
#                            HEAD is "nothing to deploy" and a deploy never moves backward. Refused unless: the deploy lock is held
#                            (<paths.state>/releases/deploy.lock, or DEPLOY_LOCK_FILE; by hand: `flock <that file> env DEPLOY_ROLLBACK=1
#                            DEPLOY_TO=<sha> ./deploy.sh`); no tracked file is changed (staged or not), and no untracked file stands at a
#                            path the commit tracks (a reset would overwrite it; other untracked files, a .claude/ say, are left alone);
#                            HEAD is on origin/main; the commit is older than HEAD; and the commit's own deploy.sh
#                            knows the second step below. Two steps, so that the GOOD tree's deploy logic does the work: this script
#                            resets the checkout to the commit and re-runs the checked-out ./deploy.sh with DEPLOY_ROLLED_BACK_FROM=<the
#                            commit it came from>, which reads the restarts from the files that differ between the two, reinstalls the
#                            units, restarts, and checks health. A rollback does not undo what the rolled-back commits did to data or
#                            state, and does not disable a unit or timer they added (install.sh only ever adds), with one exception: the minute
#                            unit. A commit from before it has a deploy.sh that knows nothing of it and would leave it running against the older code, next to the older server's own runner (two
#                            runners, one lock), so when the unit is installed and the commit has no units/stackshot-minute.service.in, the first step runs `./install.sh minute-off` (stop, disable, remove)
#                            BEFORE the reset and the hand-over; if that cannot stop the unit the rollback stops there with the checkout untouched. What runs the runner after it is the older server: its
#                            own runner, a thread of the server, which comes up with the restart the older deploy.sh makes (the plan and the --dry-run say so in a note, and omit the unit). The unit is gone before the
#                            reset, and the order stays: if the reset or the older deploy.sh then fails, the server may run at "unit" with no runner, and this step prints a WARNING saying what to run (./install.sh units
#                            when the checkout did not move, then restart stackshot.service; otherwise just restart it)
#
# What restarts, by the files the fast-forward changed:
#   stackshot.service        any module the server imports (every *.py but the hub's, the clients' and the one-off scripts; the paths are the package's, stackshot/<area>/<module>.py),
#                            its unit, icons/* (their URLs carry a version read at the start, render.py ICON_V), fonts/*
#                            (the code font's, render.py font_href), shared/* (the shared color tool, read at import by ui/colortool.py), or
#                            stackshot/web/tools/text/*.md (the tools' text files, read at import by web/tools/textfile.py)
#   stackshot-minute.service whatever restarts stackshot.service for its code or data (it imports the server's modules: the same files, but not the unit files of the server and of its reload watcher),
#                            install.sh, or its unit; and only when that unit is installed, the instance's config still says [runner] process = "unit" (install.sh installs it only then and
#                            removes it at "inline") and the box is not a read-only standby (install.sh removes it there too: units/scope.sh standby()), so at "inline", the default, it is never in the plan
#                            nor restarted. A config that cannot be read counts as "unit" (a restart is harmless, a missing runner is not; install.sh decides). A restart is preceded by `systemctl --user reset-failed`: past its start
#                            limit a plain restart is refused, and under set -e that would stop the deploy before the hub, the puller and the health check (reset-failed exits 1 for a unit that is not failed, hence the `|| true`). It restarts right after the server
#                            (it waits for /healthz only at its own start). A rollback reads the same map, with the exception above for a commit from before the unit. A unit this very deploy installs for the first time is started
#                            by the restart but is not in a --dry-run's plan (nothing is installed yet when the plan is made: a first install has no unit file yet, and the plan reads the file)
#                            The setting [runner] process is read once at a start, so a deploy that flips it back to "inline" with the unit installed must restart the server in the same deploy (install.sh removes the
#                            unit, and a server started at "unit" runs no runner of its own): the plan restarts the server even for a docs-only change and prints a note saying why, never leaving the box with no runner.
#                            The unit is Type=simple, so a restart that succeeds and a /healthz that answers say nothing of the runner: after the health check and the republish, for a unit this deploy restarted,
#                            deploy.sh waits up to DEPLOY_MINUTE_WAIT seconds (default 90; 0 looks once) for it to be active AND for a heartbeat (status.json under <paths.state>/minute/, read through
#                            stackshot/core/runner_files.py) that comes from the unit's own process (the unit's MainPID or a process below it) and is newer than the restart; a unit that is failed ends the wait at once.
#                            A runner that does not show is one WARNING line (the unit, its state, what was seen of the heartbeat, and the systemctl and journalctl commands to run) and the deploy still exits 0, like a failed
#                            republish: the server runs the new code and the deploy is done by then, and a nonzero exit would read to release.sh as "merged, not live" and pause its queue for a runner that is only slow to start.
#                            The server's runner watchdog and `stackshot doctor` flag a runner that stays down. At "inline" (no unit restarted) there is no check and no wait.
#   anchor-hub.service       stackshot/anchors/anchor_hub.py, stackshot/anchors/anchorhub/*, anchors.py, project_registry.py, projects.py (apply() reaches it), push.py, fleet.py, liveness.py, routing.py, inbox.py, sessions_registry.py, interp.py, config.py (all under stackshot/), or its unit
#   stackshot-puller.service stackshot/fleet/puller.py, stackshot/fleet/client.py, stackshot/core/config.py, or its unit
# Code is restarted here, deliberately; stackshot-reload.path only reloads the config file (SIGHUP). It is still held
# while the units are reinstalled, so a config change never reloads a service whose unit is being replaced.
# After a server restart the board is published once more, so a change to the renderer is live at once and not at the next timer.
# A failed fast-forward (local commits, a dirty tree) stops everything: this checkout is deployed to, never worked in.
# The units are user units (systemctl --user, no sudo; the system scope was removed in an earlier change). A config that still names a
# removed mode ([units] scope = "system", a legacy [client] value) stops config.py, and so this script, before anything changes.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; cd "$HERE"
DRY=0; [ "${1:-}" = "--dry-run" ] && DRY=1
ROLLBACK=""; [ "${DEPLOY_ROLLBACK:-}" = 1 ] && ROLLBACK=1            # only exactly 1 turns it on
FROM="${DEPLOY_ROLLED_BACK_FROM:-}"                                   # set by the rolling-back step for the good tree's deploy.sh to finish with
G="git"
UV="$(command -v uv || echo "$HOME/.local/bin/uv")"     # a transient unit (release.sh) has no ~/.local/bin on its PATH
python3 stackshot/core/config.py check || exit 1; . "$HERE/units/scope.sh"      # server_ctl (systemctl --user), xdg_repair
if [ -n "$($G status --porcelain --untracked-files=no)" ]; then echo "deploy refused: the production checkout has local changes ($HERE); work happens on a branch in a worktree, not here" >&2; exit 1; fi
if [ -n "$FROM" ] && [ -z "$ROLLBACK" ]; then echo "deploy refused: DEPLOY_ROLLED_BACK_FROM is only for the second step of a rollback (DEPLOY_ROLLBACK=1)" >&2; exit 1; fi
if [ -n "$ROLLBACK" ] && [ $DRY = 0 ]; then   # the lock must be held by someone: release.sh holds it for its children, by hand `flock <file> env ... ./deploy.sh`
    LOCKF="${DEPLOY_LOCK_FILE:-$(python3 stackshot/core/config.py state releases)/deploy.lock}"; mkdir -p "$(dirname "$LOCKF")"
    if flock -n "$LOCKF" true 2>/dev/null; then echo "deploy refused: a rollback needs the deploy lock held; by hand: flock $LOCKF env DEPLOY_ROLLBACK=1 DEPLOY_TO=<sha> ./deploy.sh" >&2; exit 1; fi
fi
fetch_main() {   # release.sh's main_green fetches in this checkout too, outside the deploy lock: two fetches racing fail one ("incorrect old value
    local try    # provided"), and a second try finds the ref the other one set
    for try in 1 2 3 4 5; do $G fetch --quiet origin main 2>/dev/null && return 0; [ $try = 5 ] || sleep 1; done
    return 1
}
if ! fetch_main; then       # no remote, or a remote without main: say which, not git's raw error
    url="$($G remote get-url origin 2>/dev/null | sed -E 's#//[^/@]*@#//#' || true)"   # never a credential that sits in the URL
    echo "deploy refused: cannot fetch main from origin (${url:-no origin remote})" >&2; exit 1
fi
OLD="$($G rev-parse HEAD)"; NEW="$($G rev-parse origin/main)"; target="origin/main"
if [ -n "$ROLLBACK" ] && [ -z "${DEPLOY_TO:-}" ]; then echo "deploy refused: DEPLOY_ROLLBACK needs DEPLOY_TO=<the commit to go back to>" >&2; exit 1; fi
if [ -n "${DEPLOY_TO:-}" ]; then
    if ! $G cat-file -e "$DEPLOY_TO^{commit}" 2>/dev/null; then echo "deploy refused: DEPLOY_TO=$DEPLOY_TO is not a commit this checkout knows" >&2; exit 1; fi
    NEW="$($G rev-parse "$DEPLOY_TO^{commit}")"; target="$(git rev-parse --short "$NEW") (DEPLOY_TO)"
    if ! $G merge-base --is-ancestor "$NEW" origin/main; then echo "deploy refused: DEPLOY_TO=$DEPLOY_TO is not on origin/main" >&2; exit 1; fi
    if [ -n "$FROM" ]; then   # the second step: the checkout was reset to NEW by the script that came before this one (the commit's own deploy.sh)
        if [ "$OLD" != "$NEW" ] || ! $G cat-file -e "$FROM^{commit}" 2>/dev/null || ! $G merge-base --is-ancestor "$NEW" "$FROM"; then
            echo "deploy refused: DEPLOY_ROLLED_BACK_FROM=$FROM does not fit a checkout at $NEW" >&2; exit 1
        fi
        OLD="$($G rev-parse "$FROM^{commit}")"
    fi
    if [ -n "$ROLLBACK" ]; then
        if [ -z "$FROM" ]; then   # a reset to the target overwrites an untracked file that stands where the target tracks a path (or a folder over a file, or the reverse): those, and only those, are refused
            # NUL-separated and unquoted throughout (git's default quoting turns a non-ASCII name into octal escapes); a git that fails is a refusal, never "no clash"
            clash="$(python3 - "$NEW" <<'PYEOF'
import subprocess, sys
def z(*a):
    return subprocess.run(["git", *a], capture_output=True, check=True).stdout.split(b"\0")[:-1]
others = z("ls-files", "--others", "--exclude-standard", "-z")
bad = []
if others:
    tree = set(z("ls-tree", "-r", "-t", "-z", "--name-only", sys.argv[1]))     # every path the target tracks: files and folders
    files = set(z("ls-tree", "-r", "-z", "--name-only", sys.argv[1]))          # its files
    for o in others:
        parts = o.split(b"/")
        if o in tree or any(b"/".join(parts[:i]) in files for i in range(1, len(parts))): bad.append(o)   # the same path, or a folder over a file the target tracks
print(" ".join(x.decode("utf-8", "replace") for x in bad[:3]))
PYEOF
)" || { echo "deploy refused: cannot tell whether an untracked file stands where the target commit tracks a path (git failed), and a reset could overwrite one" >&2; exit 1; }
            if [ -n "$clash" ]; then echo "deploy refused: an untracked file stands where the target commit tracks a path, and a reset would overwrite it: $clash" >&2; exit 1; fi
        fi
        if ! $G merge-base --is-ancestor "$OLD" origin/main; then echo "deploy refused: a rollback starts from a commit on origin/main, and $OLD is not" >&2; exit 1; fi
        if [ "$OLD" != "$NEW" ] && ! $G merge-base --is-ancestor "$NEW" "$OLD"; then
            echo "deploy refused: DEPLOY_ROLLBACK=1 but $target is not older than HEAD ($OLD)" >&2; exit 1
        fi
    fi
    if [ -z "$ROLLBACK" ] && [ "$OLD" != "$NEW" ] && $G merge-base --is-ancestor "$NEW" "$OLD"; then
        echo "already contains $target (at $(git rev-parse --short HEAD), a later deploy); nothing to deploy"; exit 0
    fi
fi
if [ "$OLD" = "$NEW" ]; then echo "already at $target ($(git rev-parse --short HEAD)); nothing to deploy"; exit 0; fi
if [ -z "$ROLLBACK" ] && ! $G merge-base --is-ancestor "$OLD" "$NEW"; then echo "deploy refused: $target does not contain HEAD ($OLD); this checkout has commits of its own" >&2; exit 1; fi
files="$($G diff --name-only "$OLD" "$NEW")"
if [ -n "$ROLLBACK" ]; then echo "rolling back $(git rev-parse --short "$OLD") to $(git rev-parse --short "$NEW"), taking out:"; $G log --oneline "$NEW..$OLD" | sed 's/^/  /'
else echo "deploying $(git rev-parse --short "$OLD")..$(git rev-parse --short "$NEW"):"; $G log --oneline "$OLD..$NEW" | sed 's/^/  /'; fi
server=0; minute=0; hub=0; puller=0
MINUTE_UNIT="$HOME/.config/systemd/user/stackshot-minute.service"      # there only when install.sh put it there: [runner] process = "unit"
MINUTE_DROP=0; [ -n "$ROLLBACK" ] && [ -z "$FROM" ] && [ -f "$MINUTE_UNIT" ] && ! $G cat-file -e "$NEW:units/stackshot-minute.service.in" 2>/dev/null && MINUTE_DROP=1     # a rollback's first step to a commit from before the unit: its own deploy.sh knows nothing of the unit, so this one takes it out before it hands over
runner_mode() {   # [runner] process as the instance's config reads it ("inline" or "unit"), "unreadable" when the config cannot be read
    python3 -c 'from stackshot.core import config as c; print(c.runner_process())' 2>/dev/null || echo unreadable
}
minute_on() {   # the unit is installed, is not on its way out (a rollback to a commit from before it), the instance's config does not say "inline" (install.sh removes it there, so a deploy that flips the setting back neither plans nor restarts it) and the box is
    # no read-only standby (install.sh removes it there too); a config that cannot be read counts as "unit": install.sh decides
    [ $MINUTE_DROP = 0 ] && [ -f "$MINUTE_UNIT" ] && [ "$(runner_mode)" != inline ] && ! standby
}
minute_gone() {   # the unit is installed and the config reads "inline": install.sh is about to remove it, while a server started at "unit" (the setting is read at a start only) runs no runner of its own
    [ $MINUTE_DROP = 0 ] && [ -f "$MINUTE_UNIT" ] && [ "$(runner_mode)" = inline ]
}
while IFS= read -r f; do
    case "$f" in
        units/stackshot.service.in|units/stackshot-reload.*) server=1 ;;
        install.sh) server=1; minute=1 ;;      # it renders the minute unit as well
        units/stackshot-minute.service.in) minute=1 ;;
        units/anchor-hub.service.in) hub=1 ;;
        units/stackshot-puller.service.in) puller=1 ;;
        stackshot/anchors/anchor_hub.py|stackshot/anchors/anchorhub/*|stackshot/fleet/push.py) hub=1 ;;
        stackshot/anchors/merge_log.py) server=1; minute=1; hub=1 ;;      # the hub writes the merge log and the server reads it: both read the file at their start
        stackshot/anchors/event_log.py) server=1; minute=1; hub=1 ;;      # the same for the event log (events.jsonl): the hub writes it, the server's last-activity pass reads it
        pyproject.toml|uv.lock) server=1; minute=1; hub=1 ;;      # the units' pinned dependencies (uv run --project --locked): a new pin takes effect at the restart
        stackshot/cli.py) server=1; minute=1; hub=1 ;;      # the units start the server and the hub through it (the audit's oneshot reads it fresh)
        stackshot/web/tools/text/*.md) server=1; minute=1 ;;      # the tools' text files: read once at import by stackshot/web/tools/textfile.py
        icons/*) server=1; minute=1 ;;             # a new icon is a new ?v= in the manifest and the pages' links, read at the start
        fonts/*) server=1; minute=1 ;;             # the code font's ?v= is in the pages' stylesheet, read at the start (render.py font_href)
        shared/*) server=1; minute=1 ;;            # the shared color tool (shared/colortool.js) is read at import and inlined in every page (stackshot/web/ui/colortool.py)
        stackshot/fleet/puller.py|stackshot/fleet/client.py) puller=1 ;;
        stackshot/core/config.py) server=1; minute=1; hub=1; puller=1 ;;
        stackshot/core/retired_inputs.py) server=1; minute=1; puller=1 ;;      # client.py imports it: the puller's source
        stackshot/__init__.py|stackshot/__main__.py|stackshot/paths.py) server=1; minute=1; hub=1; puller=1 ;;      # every program finds the checkout's files through it
        stackshot/anchors/anchors.py|stackshot/projects/project_registry.py|stackshot/projects/projects.py|stackshot/fleet/fleet.py|stackshot/fleet/liveness.py|stackshot/router/routing.py|stackshot/fleet/inbox.py|stackshot/fleet/sessions_registry.py|stackshot/core/interp.py) server=1; minute=1; hub=1 ;;
        *.py) case "$f" in tests/*|stackshot/projects/rename_page.py|stackshot/projects/page_keeper.py|stackshot/anchors/anchor_hub_google_auth.py) ;; *) server=1; minute=1 ;; esac ;;
    esac
done <<< "$files"
swap=0; if minute_gone; then server=1; swap=1; fi   # the unit goes at "inline" and the server that ran without a runner (started at "unit") gets its own at its restart: in this same deploy, never left to a later one
plan=""; [ $server = 1 ] && plan="$plan stackshot.service"; [ $minute = 1 ] && minute_on && plan="$plan stackshot-minute.service"; [ $hub = 1 ] && plan="$plan anchor-hub.service"; [ $puller = 1 ] && plan="$plan stackshot-puller.service"
echo "restarts:${plan:- none}"
if [ $swap = 1 ]; then echo "note: stackshot-minute.service is installed but [runner] process reads \"inline\": install.sh removes it, and the server restarts in this deploy, since one started at \"unit\" runs no runner of its own"; fi
if [ $MINUTE_DROP = 1 ]; then echo "note: $target predates stackshot-minute.service, whose removal this deploy runs first (install.sh minute-off): its own deploy.sh knows nothing of it, and the older server's runner starts with its restart"; fi
if [ -n "$ROLLBACK" ] && [ -z "$FROM" ] && ! $G show "$NEW:deploy.sh" 2>/dev/null | grep -q DEPLOY_ROLLED_BACK_FROM; then
    echo "deploy refused: the deploy.sh of $target predates the rollback's second step; roll back by hand" >&2; exit 1
fi
[ $DRY = 1 ] && exit 0
if [ -n "$ROLLBACK" ] && [ -z "$FROM" ]; then   # step one: the checkout goes back, and the commit's own deploy.sh does the rest (its file map, its units, its restarts)
    if [ $MINUTE_DROP = 1 ]; then   # the minute unit would run on against the older server and checkout, and the older deploy.sh will never stop it: out first (stopped, disabled, removed), and a failure of that stops the rollback with the checkout untouched
        ./install.sh minute-off | sed 's/^/  /' || { echo "rollback stopped: stackshot-minute.service could not be stopped; the checkout is unchanged" >&2; exit 1; }
    fi
    if [ $MINUTE_DROP = 1 ]; then   # the unit is gone by now: if the reset or the older deploy.sh then fails, the server may run at "unit" with no runner, so this step stays here to say so (it is not an exec)
        rc=0; { $G reset --hard --quiet "$NEW" && env DEPLOY_ROLLED_BACK_FROM="$OLD" "$HERE/deploy.sh"; } || rc=$?
        [ $rc = 0 ] || echo "WARNING: the rollback to $target failed after stackshot-minute.service was removed, so the server may be running with no runner: if the checkout is still at $($G rev-parse --short "$OLD"), run ./install.sh units and restart stackshot.service (systemctl --user restart stackshot.service); if it moved, restart stackshot.service, so that the older server's own runner starts" >&2
        exit $rc
    fi
    $G reset --hard --quiet "$NEW"
    exec env DEPLOY_ROLLED_BACK_FROM="$OLD" "$HERE/deploy.sh"
fi
server_ctl stop stackshot-reload.path
trap 'server_ctl start stackshot-reload.path' EXIT
[ -n "$ROLLBACK" ] || $G merge --ff-only --quiet "$NEW"   # a rollback (second step) is at NEW already
./install.sh units | sed 's/^/  /'
if [ $server = 1 ]; then server_ctl restart stackshot.service; echo "  restarted stackshot.service"; fi
beat_since=""   # set when the minute unit was restarted here: the moment, for the check of its heartbeat after the health check
if [ $minute = 1 ] && minute_on; then beat_since="$(python3 -c 'import time; print(time.time())')"; systemctl --user reset-failed stackshot-minute.service 2>/dev/null || true; systemctl --user restart stackshot-minute.service; echo "  restarted stackshot-minute.service"; fi   # after the server (it waits for /healthz at its own start); not installed: [runner] process is not "unit"
if [ $hub = 1 ] && [ -f "$HOME/.config/systemd/user/anchor-hub.service" ]; then systemctl --user restart anchor-hub.service; echo "  restarted anchor-hub.service"; fi   # not installed: [anchor_hub] enabled is off
if [ $puller = 1 ]; then systemctl --user restart stackshot-puller.service; echo "  restarted stackshot-puller.service"; fi
port="$(python3 stackshot/core/config.py get server.port)"
# Wait up to 180 s: a start reads thousands of files in turn, and on a busy disk (a weekly fstrim, for one)
# it can take a minute while the server comes up fine; 60 s would call that a failed release.
HEALTH_WAIT=180; deadline=$((SECONDS + HEALTH_WAIT))
# The minute unit is Type=simple, so a restart that succeeds says nothing of the process: it can fail at its own start (a lock held, an import error) after the server's /healthz is fine. After the health check,
# for a unit this deploy restarted: wait up to MINUTE_WAIT seconds (DEPLOY_MINUTE_WAIT; 0 looks once and does not wait) for the unit to be active AND for a heartbeat (status.json under <state>/minute/, what the runner writes at
# the top of each round, read through runner_files.status_read) that is the unit's own process (its pid is the unit's MainPID or a descendant of it: `uv run` stays the parent of the runner) and newer than the restart.
# A unit that is "failed" ends the wait at once. A runner that does not show is a WARNING line and the deploy still exits 0, as the republish's: by then the server runs the new code and the deploy is done, and release.sh reads
# a nonzero exit as "merged, not live" and pauses its queue, which a runner that is only slow to start (it waits for /healthz, then imports the server's wiring, on a loaded box) must not do. The server's runner watchdog
# and `stackshot doctor` still flag a runner that stays down.
MINUTE_WAIT="${DEPLOY_MINUTE_WAIT:-90}"; case "$MINUTE_WAIT" in ''|*[!0-9]*) MINUTE_WAIT=90 ;; esac
minute_seen() {   # minute_seen <since> <MainPID>: 0 when the runner of this unit wrote a heartbeat at or after <since> (epoch seconds); else 1 with what it saw on stdout
    python3 -c 'import sys, time
from stackshot.core import runner_files as f
since, main = float(sys.argv[1]), int(sys.argv[2] or 0)
d = f.status_read(own=True)
if d is None:
    print("no heartbeat record"); sys.exit(1)
age = max(0, int(time.time() - float(d["heartbeat"])))
def of_unit(p):   # the pid is the MainPID of the unit or below it (`uv run` is the main process, the runner its child)
    while p > 1:
        if p == main:
            return True
        try:
            p = int(open("/proc/%d/stat" % p).read().rsplit(")", 1)[1].split()[1])
        except Exception:
            return False
    return False
if main <= 0 or not of_unit(d["pid"]):
    print("the last heartbeat, %d s ago, is from pid %d, not from this unit" % (age, d["pid"])); sys.exit(1)
if float(d["heartbeat"]) < since:
    print("the last heartbeat is %d s old, from before the restart" % age); sys.exit(1)' "$1" "$2" 2>/dev/null || { [ $? = 1 ] && return 1; echo "its heartbeat could not be read"; return 1; }
}
minute_check() {   # minute_check <since>: waits for the runner of the unit (see above); always 0: a runner that does not show is a WARNING line on stdout, never a failed deploy
    local mdeadline=$((SECONDS + MINUTE_WAIT)) st main seen=""
    while :; do
        st="$(systemctl --user is-active stackshot-minute.service 2>/dev/null || true)"
        main="$(systemctl --user show -p MainPID --value stackshot-minute.service 2>/dev/null || true)"
        if [ "$st" = active ]; then
            if seen="$(minute_seen "$1" "${main:-0}")"; then echo "  stackshot-minute.service: running (heartbeat seen)"; return 0; fi
        else seen=""; fi
        [ "$st" = failed ] || [ $SECONDS -ge $mdeadline ] && break
        sleep 2
    done
    echo "  WARNING: stackshot-minute.service is ${st:-unknown} and shows no runner heartbeat after the restart (${seen:-no heartbeat seen, the unit is not active}; waited up to ${MINUTE_WAIT} s); the deploy is done and the server is up, but the runner is not: systemctl --user status stackshot-minute.service, journalctl --user -u stackshot-minute.service -n 50 (the server's runner watchdog and stackshot doctor flag a runner that stays down)"
    return 0
}
while [ $SECONDS -lt $deadline ]; do
    if curl -sf -m 3 "http://127.0.0.1:${port}/healthz" >/dev/null; then
        echo "healthz ok at $(git rev-parse --short HEAD)"
        if [ $server = 1 ]; then      # the live board was rendered by the old code until now: one publish, so a release never lags its own deploy
            if out="$("$UV" run --project "$HERE" --locked --extra server stackshot publish publish 2>&1)"; then echo "  republished: $(echo "$out" | tail -1)"
            else echo "  WARNING: the republish failed ($(echo "$out" | tail -1)); the deploy itself is done and the timer publishes within 10 min"; fi
        fi
        if [ -n "$beat_since" ]; then minute_check "$beat_since"; fi      # only when this deploy restarted the minute unit (so never at "inline": it is not installed there)
        exit 0
    fi
    sleep 2
done
echo "healthz did not answer within ${HEALTH_WAIT} s after the deploy" >&2; exit 1
