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
#                            state, and does not disable a unit or timer they added (install.sh only ever adds)
#
# What restarts, by the files the fast-forward changed:
#   stackshot.service        any module the server imports (every *.py but the hub's, the clients' and the one-off scripts; the paths are the package's, stackshot/<area>/<module>.py, and the old root forwarders),
#                            server.py.lock, its unit, icons/* (their URLs carry a version read at the start, render.py ICON_V), fonts/*
#                            (the code font's, render.py font_href), or shared/* (the shared color tool, read at import by ui/colortool.py)
#   anchor-hub.service       anchor-hub.py, anchor-hub.py.lock, anchorhub/*, anchors.py, project_registry.py, projects.py (apply() reaches it), push.py, fleet.py, liveness.py, routing.py, inbox.py, sessions_registry.py, interp.py, config.py, or its unit
#   stackshot-puller.service puller.py, client.py, config.py, or its unit
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
server=0; hub=0; puller=0
while IFS= read -r f; do
    case "$f" in
        units/stackshot.service.in|units/stackshot-reload.*|install.sh) server=1 ;;
        units/anchor-hub.service.in) hub=1 ;;
        units/stackshot-puller.service.in) puller=1 ;;
        anchor-hub.py|anchorhub/*|push.py|stackshot/anchors/anchor_hub.py|stackshot/anchors/anchorhub/*|stackshot/fleet/push.py) hub=1 ;;
        stackshot/anchors/merge_log.py) server=1; hub=1 ;;      # the hub writes the merge log and the server reads it: both read the file at their start
        stackshot/anchors/event_log.py) server=1; hub=1 ;;      # the same for the event log (events.jsonl): the hub writes it, the server's last-activity pass reads it
        pyproject.toml|uv.lock) server=1; hub=1 ;;      # the units' pinned dependencies (uv run --project --locked): a new pin takes effect at the restart
        stackshot/cli.py) server=1; hub=1 ;;      # the units start the server and the hub through it (the audit's oneshot reads it fresh)
        icons/*) server=1 ;;             # a new icon is a new ?v= in the manifest and the pages' links, read at the start
        fonts/*) server=1 ;;             # the code font's ?v= is in the pages' stylesheet, read at the start (render.py font_href)
        shared/*) server=1 ;;            # the shared color tool (shared/colortool.js) is read at import and inlined in every page (stackshot/web/ui/colortool.py)
        puller.py|stackshot/fleet/puller.py) puller=1 ;;
        client.py|stackshot/fleet/client.py) puller=1 ;;
        config.py|stackshot/core/config.py) server=1; hub=1; puller=1 ;;
        retired_inputs.py|stackshot/core/retired_inputs.py) server=1; puller=1 ;;      # client.py imports it: the puller's source
        stackshot/paths.py) server=1; hub=1; puller=1 ;;      # every program finds the checkout's files through it
        anchors.py|project_registry.py|projects.py|fleet.py|liveness.py|routing.py|inbox.py|sessions_registry.py|interp.py|stackshot/anchors/anchors.py|stackshot/projects/project_registry.py|stackshot/projects/projects.py|stackshot/fleet/fleet.py|stackshot/fleet/liveness.py|stackshot/router/routing.py|stackshot/fleet/inbox.py|stackshot/fleet/sessions_registry.py|stackshot/core/interp.py) server=1; hub=1 ;;
        *.py) case "$f" in rename_page.py|page_keeper.py|anchor-hub-google-auth.py|tests/*|stackshot/projects/rename_page.py|stackshot/projects/page_keeper.py|stackshot/anchors/anchor_hub_google_auth.py) ;; *) server=1 ;; esac ;;
    esac
done <<< "$files"
plan=""; [ $server = 1 ] && plan="$plan stackshot.service"; [ $hub = 1 ] && plan="$plan anchor-hub.service"; [ $puller = 1 ] && plan="$plan stackshot-puller.service"
echo "restarts:${plan:- none}"
if [ -n "$ROLLBACK" ] && [ -z "$FROM" ] && ! $G show "$NEW:deploy.sh" 2>/dev/null | grep -q DEPLOY_ROLLED_BACK_FROM; then
    echo "deploy refused: the deploy.sh of $target predates the rollback's second step; roll back by hand" >&2; exit 1
fi
[ $DRY = 1 ] && exit 0
if [ -n "$ROLLBACK" ] && [ -z "$FROM" ]; then   # step one: the checkout goes back, and the commit's own deploy.sh does the rest (its file map, its units, its restarts)
    $G reset --hard --quiet "$NEW"
    exec env DEPLOY_ROLLED_BACK_FROM="$OLD" "$HERE/deploy.sh"
fi
server_ctl stop stackshot-reload.path
trap 'server_ctl start stackshot-reload.path' EXIT
[ -n "$ROLLBACK" ] || $G merge --ff-only --quiet "$NEW"   # a rollback (second step) is at NEW already
./install.sh units | sed 's/^/  /'
if [ $server = 1 ]; then server_ctl restart stackshot.service; echo "  restarted stackshot.service"; fi
if [ $hub = 1 ] && [ -f "$HOME/.config/systemd/user/anchor-hub.service" ]; then systemctl --user restart anchor-hub.service; echo "  restarted anchor-hub.service"; fi   # not installed: [anchor_hub] enabled is off
if [ $puller = 1 ]; then systemctl --user restart stackshot-puller.service; echo "  restarted stackshot-puller.service"; fi
port="$(python3 stackshot/core/config.py get server.port)"
# Wait up to 180 s: a start reads thousands of files in turn, and on a busy disk (a weekly fstrim, for one)
# it can take a minute while the server comes up fine; 60 s would call that a failed release.
HEALTH_WAIT=180; deadline=$((SECONDS + HEALTH_WAIT))
while [ $SECONDS -lt $deadline ]; do
    if curl -sf -m 3 "http://127.0.0.1:${port}/healthz" >/dev/null; then
        echo "healthz ok at $(git rev-parse --short HEAD)"
        if [ $server = 1 ]; then      # the live board was rendered by the old code until now: one publish, so a release never lags its own deploy
            if out="$("$UV" run --project "$HERE" --locked --extra server stackshot publish publish 2>&1)"; then echo "  republished: $(echo "$out" | tail -1)"
            else echo "  WARNING: the republish failed ($(echo "$out" | tail -1)); the deploy itself is done and the timer publishes within 10 min"; fi
        fi
        exit 0
    fi
    sleep 2
done
echo "healthz did not answer within ${HEALTH_WAIT} s after the deploy" >&2; exit 1
