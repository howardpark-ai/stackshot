#!/usr/bin/env bash
# install.sh — render stackshot's systemd units for this checkout and install them. The templates in
# units/*.in carry no path of any one machine: @CHECKOUT@ (this directory), @CONFIG@ (the instance config, config.py's
# answer, which stackshot-reload.path watches), @HOME@, @UV@, @PORT@ (server.port), @TZ@ (instance.timezone) @AUDIT_AT@
# ([audit] at, HH:MM or a list of them) and @AUDIT_PROJECT@ ([audit] project) are filled in here; the splitter's own (its ports, addresses, identity header, program and
# Caddyfile path) come from stackshot/core/frontdoor_splitter_config.py.
#
# Every unit is a user unit under ~/.config/systemd/user, driven with systemctl --user, and nothing here calls sudo: the
# server, its reload watcher and the portal sync are written for the user manager (no User= line, WantedBy=default.target,
# no Wants=network-online.target, the reload service reloads the server with systemctl --user), as the puller and anchor-hub
# always were. Lingering keeps them running without a login session and starts them at boot. The system scope under
# /etc/systemd/system was removed in an earlier change: a config that still says [units] scope = "system" (or names a removed [client]
# mode) is refused by config.py, and so by this script, with one line; and `units` refuses while a system-scope
# stackshot.service is still enabled or running on the box, so user units are never started over a live system instance
# (how such an instance moves: https://github.com/howardpark-ai/stackshot/blob/main/INSTALL.md#an-instance-installed-in-the-system-scope).
#
# Lingering: `units` and `puller` both make sure lingering is on for the user: when loginctl says it is not, they try `loginctl enable-linger <user>` (on systemd 255 or later polkit
# allows set-self-linger, so a user may switch it on for their own account), then `sudo -n loginctl enable-linger <user>`, and otherwise print a WARNING with the one command root runs once:
# `sudo loginctl enable-linger <user>`. Without it the user units stop at logout and do not start at boot.
# XDG_RUNTIME_DIR (a follow-up fix): units/scope.sh points it at /run/user/<uid> when a shell that is not a login left it
# unset and that directory exists; when `systemctl --user` still cannot reach the user manager, units and puller stop before
# installing anything and say what to do.
#
#   ./install.sh units              render and install the instance's units: stackshot.service, stackshot-reload.{service,path}
#                                   and stackshot-puller.service, plus stackshot-portal-sync.service and its drop-in only when
#                                   [portal] account_id is set, anchor-hub.service only when [anchor_hub] enabled = true, and
#                                   stackshot-audit.{service,timer} only when [audit] enabled = true (the timer enabled and
#                                   started: it only arms the schedule, the audit, or its cue in mode "agent", runs at [audit] at),
#                                   stackshot-memo-files-clean.{service,timer} on every box unless the run has STACKSHOT_READ_ONLY=1 (the daily pass over the memo-box files; the timer enabled and started, the service never started here),
#                                   stackshot-standby-push.{service,timer} only when [standby_copy] push_to is set (the timer enabled and
#                                   started, the service never started here: a start is a push), removed when it is empty,
#                                   and stackshot-minute.service only when [runner] process = "unit" (the default, so unless "inline" is set) on a box that is not a read-only
#                                   standby (the minute set's runner as a process of its own; "unit" is the default, so it is installed unless [runner] process = "inline" is set)
#                                   The front door's own (docs/front-door.md), after those and only for the tables the config has: stackshot-frontdoor.service ([frontdoor]), stackshot-signin.service
#                                   ([frontdoor_signin]), and stackshot-splitter.service with its Caddyfile (~/.config/stackshot/splitter.Caddyfile) when [frontdoor_splitter] and the tables it points at allow
#                                   a splitter: never while [server] port gives the board the splitter's port. These are installed and NEVER enabled or started here, --start included: enabling them is a
#                                   person's own step (systemctl --user enable --now ...). With --restart or --start one whose file changed is restarted only when it already runs. A config without the tables
#                                   changes nothing of the install; a unit an earlier run installed is never removed, and the installed splitter's own check (ExecStartPre) refuses a start the config no longer allows.
#   ./install.sh puller             the puller's user unit alone (a box that only fetches; never sudo)
#   ./install.sh render [name]      print the rendered unit(s), install nothing (no name: the units `units` would install, the splitter's Caddyfile among them);
#                                   the unit directory goes to stderr
#   options: --checkout DIR  --config FILE  --restart (restart the units whose file changed; otherwise only say which)
#            --start (after enabling, start the long-running units of this verb, or restart them if running; how setup
#            brings a fresh box up)  --quiet-hint (do not print the "changed, not restarted" hint; setup's own next line says
#            why the server is not started)  --force-host (see below)
#
# The server host (`units` only): the server's units belong on the box the instance's server runs on, and `units` refuses on any other, in one line on stderr, exit 1, before it touches lingering or a unit. The config names
# that host in [release] deploy_ssh (a name, an alias or user@host, or a host word: the host the server runs on, for a box that only runs release.sh) and says "not here" with [server] box = false; stackshot/core/config.py
# server_host_refusal() decides. A host that names this box (its own name or short name, or a loopback name or address) is the server host. A config that names no server host (deploy_ssh empty, [server] box unset or true) refuses
# nothing, as before. A read-only standby (units/scope.sh standby()) keeps its own path and is never refused. --force-host skips the check, for a deliberate install on another box (a server moved there before its config says so). deploy.sh, `stackshot setup` and `stackshot doctor` pass it: they run on the server host by nature.
# The check makes no lookup of its own (an ssh alias or a non-loopback address of this box is not recognized), a host word whose lookup does not resolve refuses, a deploy_ssh naming another box wins over [server] box = true,
# and a check that cannot run (a config it cannot read) refuses nothing.
# `render`, `puller` and `minute-off` are not checked: they install no server unit.
#
# Installing never restarts anything unless --restart or --start is given: deploy.sh restarts the server, the minute runner, anchor-hub and the
# puller when a change touches them (the reload path only reloads the config file). A unit whose rendered text is unchanged
# is left alone, so running this twice does nothing the second time. Enables each unit it installs. A unit whose condition
# is off is skipped, never removed or disabled: an existing one stays as it is. Two exceptions. The audit's pair:
# with [audit] enabled = false a timer installed by an earlier run is disabled and stopped and both files are removed, since
# a timer left behind would fire every day into a cue the server refuses. Its service is never restarted here: that would cue an audit.
# The standby push's pair is handled the same way, on [standby_copy] push_to: installed only when it is set, an installed pair disabled, stopped and removed when it is empty,
# and its service never restarted here (that would push).
# And stackshot-minute.service: with [runner] process back at "inline" (a value that is neither "inline" nor "unit" counts as inline), or on a box that is a read-only standby, the unit an earlier run
# installed is stopped, disabled and removed. At inline so a runner left running does not keep the lock the server's own runner needs; on a standby because its read-only state is read from the
# environment at a start only, so a runner that is already running cannot notice the change and would go on writing the board (the standby's drop-in reaches stackshot.service alone, and `stackshot minute`
# exits 4 on a standby only when it is started). The stop comes first and the file is removed only once the unit is off: when `disable --now` fails it tries `stop` and `disable` apart, and a unit that is still running after that keeps
# its file, the failure is printed on stderr, the other units are installed all the same, and the script exits 1 at its end (a unit removed while it runs would be left running with no file to stop it by).
# A failed state the unit leaves (a tripped start limit) is cleared with reset-failed after the removal, so it does not linger as "not-found failed".
#   ./install.sh minute-off         stop, disable and remove stackshot-minute.service whatever the setting says (deploy.sh's rollback to a commit from before the unit, whose own deploy.sh knows nothing of it);
#                                   exit 1 and the file kept when it cannot be stopped (or when systemctl is missing and the file exists); "not installed" and exit 0, with no systemctl needed, when there is nothing to remove
# CPUWeight=50 in the unit is ignored where the cpu controller is not delegated to the user manager (systemd then logs nothing and the weight does not apply); Nice=10 does.
set -euo pipefail
USER="${USER:-$(id -un)}"                     # unset under some sudo, cron and container shells; the units and loginctl need it
HERE="$(cd "$(dirname "$0")" && pwd)"
CHECKOUT="$HERE"; CONFIG=""; RESTART=0; START=0; QUIET_HINT=0; FORCE_HOST=0; VERB="${1:-}"; shift || true
ARGS=()
while [ $# -gt 0 ]; do
    case "$1" in
        --checkout) CHECKOUT="$(cd "$2" && pwd)"; shift 2 ;;
        --config) CONFIG="$2"; shift 2 ;;
        --restart) RESTART=1; shift ;;
        --start) START=1; shift ;;
        --quiet-hint) QUIET_HINT=1; shift ;;
        --force-host) FORCE_HOST=1; shift ;;
        *) ARGS+=("$1"); shift ;;
    esac
done
[ -n "$CONFIG" ] || CONFIG="$(python3 "$CHECKOUT/stackshot/core/config.py" file)"
CONFIG="$(python3 -c 'import os,sys; print(os.path.realpath(os.path.expanduser(sys.argv[1])))' "$CONFIG")"
PORT="$(STACKSHOT_CONFIG="$CONFIG" python3 "$CHECKOUT/stackshot/core/config.py" get server.port)"
TZNAME="$(STACKSHOT_CONFIG="$CONFIG" python3 "$CHECKOUT/stackshot/core/config.py" get instance.timezone)"; TZNAME="${TZNAME:-UTC}"
PORTAL=0; [ -n "$(STACKSHOT_CONFIG="$CONFIG" python3 "$CHECKOUT/stackshot/core/config.py" get portal.account_id)" ] && PORTAL=1       # the portal-sync unit and its drop-in
HUB=0; case "$(STACKSHOT_CONFIG="$CONFIG" python3 "$CHECKOUT/stackshot/core/config.py" get anchor_hub.enabled | tr '[:upper:]' '[:lower:]')" in true|1|yes) HUB=1 ;; esac   # anchor-hub's user unit
read -r AUDIT AUDIT_AT RUNNER_PROCESS AUDIT_PROJECT < <(STACKSHOT_CONFIG="$CONFIG" python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); from stackshot.core import config as c; print(int(c.audit_enabled()), ",".join(c.audit_at()), c.runner_process(), c.audit_project())' "$CHECKOUT")   # the audit's timer pair, its HH:MM times (comma-joined: one OnCalendar line each), and [runner] process ("inline" for any value but "unit")
# the front door's units: which of its tables the config has, and why there is no splitter to render ("" when there is one, "absent" with no [frontdoor_splitter] table)
read -r DOOR SIGNIN SPLITTER_WHY < <(STACKSHOT_CONFIG="$CONFIG" python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); from stackshot.core import config as c, frontdoor_splitter_config as sp; s = sp.parse()[0]; print(int(c.get("frontdoor") is not None), int(c.get("frontdoor_signin") is not None), "; ".join(sp.blocking(s)) if s.present else "absent")' "$CHECKOUT")
CADDYFILE="$HOME/.config/stackshot/splitter.Caddyfile"
PUSH=0; [ -n "$(STACKSHOT_CONFIG="$CONFIG" python3 "$CHECKOUT/stackshot/core/config.py" get standby_copy.push_to | tr -d '[:space:]')" ] && PUSH=1      # the standby push's timer pair
UV="$(command -v uv || echo "$HOME/.local/bin/uv")"
. "$HERE/units/scope.sh"      # UNIT_DIR, xdg_repair, user_manager_ok (config.py refused a removed mode above, with its line)
MEMO=1; [ "${STACKSHOT_READ_ONLY:-}" = 1 ] && MEMO=0      # the memo-box files' daily clean-up (docs/memo-files.md): not where this script runs with STACKSHOT_READ_ONLY=1 (a standby's copy of the data is the server's to change). No question to the user manager here: a standby set up by a drop-in gets the pair too, and the program itself does nothing there
MINUTE=0; MINUTE_OFF=inline; MINUTE_STUCK=0     # stackshot-minute.service: only at [runner] process = "unit", and never on a standby (`stackshot minute` exits 4 there); MINUTE_OFF says why it is not wanted
if [ "$RUNNER_PROCESS" = unit ]; then if standby; then MINUTE_OFF=standby; else MINUTE=1; MINUTE_OFF=""; fi; fi
minute_off() {   # stop and disable the minute unit: 0 once nothing of it runs, 1 (a line on stderr says what failed) when it still does. `disable --now` first; when it fails, `stop` and `disable` apart; then the unit's own state decides,
    # since a failed call can still have stopped it (a unit that is not loaded is "inactive") and a runner that survives would keep the runner's lock, so that the server's inline runner could not start
    local u=stackshot-minute.service err st
    err="$(systemctl --user disable --now --quiet "$u" 2>&1)" && return 0
    systemctl --user stop "$u" >/dev/null 2>&1 || true
    systemctl --user disable --quiet "$u" >/dev/null 2>&1 || true
    st="$(systemctl --user is-active "$u" 2>/dev/null || true)"
    case "$st" in active|activating|deactivating|reloading|refreshing) echo "  FAILED to stop $u (it is $st): ${err:-systemctl said nothing}" >&2; return 1 ;; esac
    return 0
}
minute_remove() {   # stop, disable and remove the installed minute unit, then clear a failed state it may leave (a unit that already tripped its start limit, or exited 3 or 4, lingers as "not-found failed" and the user manager reads degraded). 1 when it could not be stopped: its file stays
    minute_off || return 1
    rm -f "$UNIT_DIR/stackshot-minute.service"
    systemctl --user reset-failed stackshot-minute.service 2>/dev/null || true      # exits 1 for a unit that is not failed: nothing to clear
}
SERVERU=" stackshot.service stackshot-reload.service stackshot-reload.path stackshot-portal-sync.service stackshot.service.d-portal-sync.conf "   # the server's units: their header names the user manager
render() {   # render <name> → stdout: the template with its placeholders filled in
    local t="$HERE/units/$1.in"; [ -f "$t" ] || { echo "no template $t" >&2; return 1; }
    local kind=unit; case "$SERVERU" in *" $1 "*) kind=server ;; esac
    python3 - "$t" "$CHECKOUT" "$CONFIG" "$HOME" "$UV" "$PORT" "$TZNAME" "$kind" "$AUDIT_AT" "$AUDIT_PROJECT" "$CADDYFILE" <<'PY'
import os, re, sys
t, checkout, config, home, uv, port, tz, kind, audit_at, audit_project, caddyfile = sys.argv[1:12]
name = t.rsplit("/", 1)[1]
s = open(t, encoding="utf-8").read()
# a line that carries @AUDIT_AT@ is written once per time of [audit] at (audit_at is the comma-joined list), so the timer has one OnCalendar line for each
s = "".join("".join(l.replace("@AUDIT_AT@", t) for t in audit_at.split(",")) if "@AUDIT_AT@" in l else l for l in s.splitlines(keepends=True))
pairs = [("@CHECKOUT@", checkout), ("@CONFIG@", config), ("@HOME@", home), ("@UV@", uv), ("@PORT@", port), ("@TZ@", tz), ("@AUDIT_PROJECT@", audit_project)]
if name.startswith("stackshot-splitter."):      # the splitter's values come from the module that also says whether this config allows a splitter at all
    sys.path.insert(0, checkout)
    os.environ["STACKSHOT_CONFIG"] = config
    from stackshot.core import frontdoor_splitter_config as sp
    settings = sp.parse()[0]
    why = sp.blocking(settings)
    if why:
        sys.exit("%s: not rendered: %s" % (name[:-3], "; ".join(why)))
    pairs += [("@%s@" % k, v) for k, v in sp.values(settings).items()] + [("@CADDYFILE@", caddyfile)]
for k, v in pairs:
    s = s.replace(k, v)
if name.endswith(".Caddyfile.in"):      # a Caddyfile names its matchers with an @, so only a placeholder's own shape counts there
    left = [l for l in s.splitlines() if re.search(r"@[A-Z0-9_]+@", l.split("#")[0])]
else:
    left = [l for l in s.splitlines() if "@" in l and "@" in l.split("#")[0]]
if left:
    sys.exit("unrendered placeholder in %s: %s" % (t, left[0].strip()))
# The header is part of the installed bytes: it is kept word for word (the server units' one still says `[units] scope = "user"`,
# the key removed in an earlier change), so an upgrade reports every unit unchanged instead of re-installing them all.
head = ("# Rendered by install.sh from units/%s for the user manager ([units] scope = \"user\") — edit the template, not this file.\n" % name
        if kind == "server" else "# Rendered by install.sh from units/%s — edit the template, not this file.\n" % name)
sys.stdout.write(head + s)
PY
}
SERVER=(stackshot.service stackshot-reload.service stackshot-reload.path); [ $PORTAL = 1 ] && SERVER+=(stackshot-portal-sync.service)
USERU=(); [ $HUB = 1 ] && USERU+=(anchor-hub.service); USERU+=(stackshot-puller.service)
AUDITU=(stackshot-audit.service stackshot-audit.timer); [ $AUDIT = 1 ] && USERU+=("${AUDITU[@]}")
PUSHU=(stackshot-standby-push.service stackshot-standby-push.timer); [ $PUSH = 1 ] && USERU+=("${PUSHU[@]}")
MEMOU=(stackshot-memo-files-clean.service stackshot-memo-files-clean.timer); [ $MEMO = 1 ] && USERU+=("${MEMOU[@]}")
[ $MINUTE = 1 ] && USERU+=(stackshot-minute.service)
FRONTU=()      # installed by `units`, never enabled or started by this script
[ "$DOOR" = 1 ] && FRONTU+=(stackshot-frontdoor.service)
[ "$SIGNIN" = 1 ] && FRONTU+=(stackshot-signin.service)
[ -z "$SPLITTER_WHY" ] && FRONTU+=(stackshot-splitter.Caddyfile stackshot-splitter.service)
changed=()
put() {      # put <name> <dir> [file name, else <name>]  → installs when the rendered text differs
    local name="$1" dir="$2" file="${3:-$1}" tmp; tmp="$(mktemp)"; render "$name" > "$tmp"
    if [ -f "$dir/$file" ] && cmp -s "$tmp" "$dir/$file"; then rm -f "$tmp"; echo "  $name: unchanged"; return 0; fi
    install -D -m 0644 "$tmp" "$dir/$file"
    rm -f "$tmp"; changed+=("$name"); echo "  $name: installed → $dir/$file"
}
front_units() {   # the front door's files for the tables the config has; what an earlier run installed and this config no longer asks for is said, and stays
    local n u stays="; the installed unit stays as it is"
    for n in ${FRONTU[@]+"${FRONTU[@]}"}; do
        if [ "$n" = stackshot-splitter.Caddyfile ]; then
            [ -d "$(dirname "$CADDYFILE")" ] || install -d -m 0700 "$(dirname "$CADDYFILE")"      # the directory the secrets are kept in: private when this makes it
            put "$n" "$(dirname "$CADDYFILE")" "$(basename "$CADDYFILE")"
        else put "$n" "$UNIT_DIR"; fi
    done
    if [ "$DOOR" = 0 ] && [ -f "$UNIT_DIR/stackshot-frontdoor.service" ]; then echo "  stackshot-frontdoor.service: skipped (the config has no [frontdoor] table)$stays"; fi
    if [ "$SIGNIN" = 0 ] && [ -f "$UNIT_DIR/stackshot-signin.service" ]; then echo "  stackshot-signin.service: skipped (the config has no [frontdoor_signin] table)$stays"; fi
    u="$UNIT_DIR/stackshot-splitter.service"
    case "$SPLITTER_WHY" in
        "") ;;
        absent) if [ -f "$u" ]; then echo "  stackshot-splitter.service: skipped (the config has no [frontdoor_splitter] table)$stays, and its own check refuses to start it"; fi ;;
        *) if [ -f "$u" ]; then echo "  stackshot-splitter.service: skipped ($SPLITTER_WHY)$stays, and its own check refuses to start it"
           else echo "  stackshot-splitter.service: skipped ($SPLITTER_WHY)"; fi ;;
    esac
    if [ ${#FRONTU[@]} -gt 0 ]; then echo "  front door units: never enabled or started by this script (systemctl --user enable --now <unit> is your step; docs/front-door.md)"; fi
}
front_restart() {   # a front door unit whose file changed is restarted only when it runs already: nothing here starts one
    local n u seen=" "
    for n in ${changed[@]+"${changed[@]}"}; do
        case "$n" in
            stackshot-frontdoor.service|stackshot-signin.service|stackshot-splitter.service) u="$n" ;;
            stackshot-splitter.Caddyfile) u=stackshot-splitter.service ;;
            *) continue ;;
        esac
        case "$seen" in *" $u "*) continue ;; esac
        seen="$seen$u "
        case "$(systemctl --user is-active "$u" 2>/dev/null || true)" in
            active|activating|reloading)
                if systemctl --user restart "$u"; then echo "  restarted $u"; else echo "  FAILED to restart $u" >&2; return 1; fi ;;
        esac
    done
}
linger_state() {   # yes | no | unknown: logind's own answer, else its flag file (loginctl knows no user that is neither logged in nor lingering)
    local v=""; command -v loginctl >/dev/null 2>&1 && v="$(loginctl show-user "$USER" -p Linger --value 2>/dev/null || true)"
    case "$v" in yes|no) echo "$v"; return ;; esac
    if [ -d /var/lib/systemd/linger ]; then [ -e "/var/lib/systemd/linger/$USER" ] && echo yes || echo no; else echo unknown; fi
}
ensure_linger() {  # the user units keep running without a login session and start at boot
    [ "$(linger_state)" = yes ] && { echo "  lingering: on for $USER"; return 0; }
    if command -v loginctl >/dev/null 2>&1; then
        if loginctl --no-ask-password enable-linger "$USER" >/dev/null 2>&1 || sudo -n loginctl enable-linger "$USER" >/dev/null 2>&1; then
            if [ "$(linger_state)" = yes ]; then echo "  lingering: enabled for $USER (the user units now run without a login session and start at boot)"; return 0; fi
        fi
    fi
    echo "  WARNING: lingering is off for $USER, so the user units stop at logout and do not start at boot. Run this once as root:  sudo loginctl enable-linger $USER" >&2
}
UNITS_SAYS="user units: $UNIT_DIR (systemctl --user, no sudo)"
case "$VERB" in
    render)   # byte-identical to what `units` installs: no separator after a single unit, a comment line between several
        echo "# $UNITS_SAYS" >&2
        first=1
        for n in "${ARGS[@]:-${SERVER[@]} ${USERU[@]} ${FRONTU[*]:-}}"; do for m in $n; do [ $first = 1 ] || echo "# ---------------- $m"; first=0; render "$m"; done; done ;;
    units|puller)
        if [ "$VERB" = units ] && [ "$FORCE_HOST" = 0 ]; then      # the server's units go on the server host only: checked once, first, before lingering or any unit is touched; one line and exit 1 on another box
            why="$(STACKSHOT_CONFIG="$CONFIG" python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); from stackshot.core import config as c; print(c.server_host_refusal())' "$CHECKOUT" 2>/dev/null)" || why=""      # a config that names no server host, or a check that cannot run, refuses nothing
            if [ -n "$why" ] && ! standby; then echo "refused: $why (a deliberate install here: --force-host)" >&2; exit 1; fi      # a read-only standby keeps its own path
        fi
        echo "checkout $CHECKOUT · config $CONFIG · user $USER · $UNITS_SAYS"
        ensure_linger
        xdg_repair                           # enabling lingering just now may have made the runtime directory
        user_manager_ok || exit 1            # both verbs drive user units: stop before anything is half-installed
        if [ "$VERB" = units ]; then
            sysunit="${STACKSHOT_SYSTEM_UNIT_DIR:-/etc/systemd/system}/stackshot.service"      # (tests point it elsewhere)
            if [ -f "$sysunit" ] && { systemctl is-enabled -q stackshot.service 2>/dev/null || systemctl is-active -q stackshot.service 2>/dev/null; }; then
                # a stackshot installed in the system scope, removed in an earlier change, is still live on this box: user units started beside it
                # would race it for the port, so nothing is installed. A read of the system manager, no sudo; its unit files left
                # disabled and stopped after the move are not mentioned.
                echo "refused: $sysunit is enabled or running — a stackshot installed in the system scope, which was removed; move it to user units first (https://github.com/howardpark-ai/stackshot/blob/main/INSTALL.md#an-instance-installed-in-the-system-scope), or the two servers race for port $PORT" >&2
                exit 1
            fi
            for n in "${SERVER[@]}"; do put "$n" "$UNIT_DIR"; done
            if [ $PORTAL = 1 ]; then
                tmp="$(mktemp)"; render stackshot.service.d-portal-sync.conf > "$tmp"      # the drop-in that starts the portal re-sync after the server
                if ! cmp -s "$tmp" "$UNIT_DIR/stackshot.service.d/portal-sync.conf" 2>/dev/null; then
                    install -D -m 0644 "$tmp" "$UNIT_DIR/stackshot.service.d/portal-sync.conf"
                    echo "  stackshot.service.d/portal-sync.conf: installed"
                else echo "  stackshot.service.d/portal-sync.conf: unchanged"; fi; rm -f "$tmp"
            else
                echo "  stackshot-portal-sync.service, stackshot.service.d/portal-sync.conf: skipped ([portal] account_id is empty)"
            fi
            [ $HUB = 1 ] || echo "  anchor-hub.service: skipped ([anchor_hub] enabled is not true)"
            if [ $AUDIT = 0 ]; then         # the audit is off: a timer pair an earlier run installed goes, so it never fires into a refused cue
                if [ -f "$UNIT_DIR/stackshot-audit.timer" ] || [ -f "$UNIT_DIR/stackshot-audit.service" ]; then
                    systemctl --user disable --now --quiet stackshot-audit.timer 2>/dev/null || true
                    rm -f "$UNIT_DIR/stackshot-audit.timer" "$UNIT_DIR/stackshot-audit.service"
                    echo "  stackshot-audit.timer, stackshot-audit.service: disabled and removed ([audit] enabled is not true)"
                else
                    echo "  stackshot-audit.timer, stackshot-audit.service: skipped ([audit] enabled is not true)"
                fi
            fi
            if [ $PUSH = 0 ]; then          # no push target: a timer pair an earlier run installed goes, so it never fires into a refused push
                if [ -f "$UNIT_DIR/stackshot-standby-push.timer" ] || [ -f "$UNIT_DIR/stackshot-standby-push.service" ]; then
                    systemctl --user disable --now --quiet stackshot-standby-push.timer 2>/dev/null || true
                    rm -f "$UNIT_DIR/stackshot-standby-push.timer" "$UNIT_DIR/stackshot-standby-push.service"
                    systemctl --user reset-failed stackshot-standby-push.service 2>/dev/null || true
                    echo "  stackshot-standby-push.timer, stackshot-standby-push.service: disabled and removed ([standby_copy] push_to is empty)"
                else
                    echo "  stackshot-standby-push.timer, stackshot-standby-push.service: skipped ([standby_copy] push_to is empty)"
                fi
            fi
            if [ $MEMO = 0 ]; then          # STACKSHOT_READ_ONLY=1 in this run: a pair an earlier run installed goes
                if [ -f "$UNIT_DIR/stackshot-memo-files-clean.timer" ] || [ -f "$UNIT_DIR/stackshot-memo-files-clean.service" ]; then
                    systemctl --user disable --now --quiet stackshot-memo-files-clean.timer 2>/dev/null || true
                    rm -f "$UNIT_DIR/stackshot-memo-files-clean.timer" "$UNIT_DIR/stackshot-memo-files-clean.service"
                    systemctl --user reset-failed stackshot-memo-files-clean.service 2>/dev/null || true
                    echo "  stackshot-memo-files-clean.timer, stackshot-memo-files-clean.service: disabled and removed (STACKSHOT_READ_ONLY=1)"
                else
                    echo "  stackshot-memo-files-clean.timer, stackshot-memo-files-clean.service: skipped (STACKSHOT_READ_ONLY=1)"
                fi
            fi
            if [ $MINUTE = 0 ]; then       # not wanted: back at "inline" the server runs the runner again; on a standby `stackshot minute` exits 4 at its start, and a runner already running there is a writer the standby drop-in does not reach
                if [ -f "$UNIT_DIR/stackshot-minute.service" ]; then   # an installed unit goes, stopped first: a process cannot notice that its box became a standby, and a runner left running keeps the lock the server's own runner needs
                    if minute_remove; then
                        if [ "$MINUTE_OFF" = standby ]; then echo "  stackshot-minute.service: stopped, disabled and removed (this box is a read-only standby: a runner would write the board)"
                        else echo "  stackshot-minute.service: stopped, disabled and removed ([runner] process is not \"unit\"); the server runs no runner until it is restarted: systemctl --user restart stackshot.service"; fi
                    else      # still running: its file stays (a unit that is gone from disk but alive is one nobody can find), and the script ends with an error after the rest is installed
                        MINUTE_STUCK=1; echo "  stackshot-minute.service: its file is left in place, it could not be stopped; stop it (systemctl --user stop stackshot-minute.service), then run this again" >&2
                    fi
                elif [ "$MINUTE_OFF" = standby ]; then
                    echo "  stackshot-minute.service: skipped ([runner] process is \"unit\", but this box is a read-only standby)"
                else
                    echo "  stackshot-minute.service: skipped ([runner] process is not \"unit\")"
                fi
            fi
        fi
        for n in "${USERU[@]}"; do [ "$VERB" = units ] || [ "$n" = stackshot-puller.service ] || continue; put "$n" "$UNIT_DIR"; done
        if [ "$VERB" = units ]; then front_units; fi
        systemctl --user daemon-reload
        [ "$VERB" = units ] && { systemctl --user enable --quiet stackshot.service stackshot-reload.path 2>/dev/null || true; }
        [ "$VERB" = units ] && [ $HUB = 1 ] && systemctl --user enable --quiet anchor-hub.service 2>/dev/null || true
        [ "$VERB" = units ] && [ $MINUTE = 1 ] && systemctl --user enable --quiet stackshot-minute.service 2>/dev/null || true
        if [ "$VERB" = units ] && [ $AUDIT = 1 ]; then    # arming the timer runs nothing: the cue waits for [audit] at
            systemctl --user enable --now --quiet stackshot-audit.timer 2>/dev/null || true
            case " ${changed[*]:-} " in *" stackshot-audit.timer "*) systemctl --user restart stackshot-audit.timer 2>/dev/null || true ;; esac   # a new [audit] at
        fi
        if [ "$VERB" = units ] && [ $PUSH = 1 ]; then     # arming the timer: the first push is two minutes after the machine boots (at once when the timer starts later than that), then five minutes after each run starts
            systemctl --user enable --now --quiet stackshot-standby-push.timer 2>/dev/null || true
            case " ${changed[*]:-} " in *" stackshot-standby-push.timer "*) systemctl --user restart stackshot-standby-push.timer 2>/dev/null || true ;; esac
        fi
        if [ "$VERB" = units ] && [ $MEMO = 1 ]; then      # arming the timer: the clean-up runs at 04:20 each day; the service is never started here
            systemctl --user enable --now --quiet stackshot-memo-files-clean.timer 2>/dev/null || true
            case " ${changed[*]:-} " in *" stackshot-memo-files-clean.timer "*) systemctl --user restart stackshot-memo-files-clean.timer 2>/dev/null || true ;; esac
        fi
        systemctl --user enable --quiet stackshot-puller.service 2>/dev/null || true
        if [ "$START" = 1 ]; then          # start what this verb runs, or restart it if it is running (covers --restart too)
            failed=()
            start() {   # start <name>
                if [ "$1" = stackshot-minute.service ]; then systemctl --user reset-failed "$1" 2>/dev/null || true; fi      # past its start limit a plain restart is refused: clear the count first
                systemctl --user restart "$1" && echo "  started $1" || { echo "  FAILED to start $1" >&2; failed+=("$1"); }
            }
            if [ "$VERB" = units ]; then
                start stackshot.service; start stackshot-reload.path
                if [ $HUB = 1 ]; then start anchor-hub.service; fi
                if [ $MINUTE = 1 ]; then start stackshot-minute.service; fi      # after the server: it waits for /healthz only at its own start
            fi
            start stackshot-puller.service
            if [ "$VERB" = units ]; then front_restart || failed+=("a front door unit"); fi
            if [ ${#failed[@]} -gt 0 ]; then echo "not started: ${failed[*]}" >&2; exit 1; fi
        elif [ ${#changed[@]} -gt 0 ]; then
            if [ "$RESTART" = 1 ]; then
                for n in "${changed[@]}"; do
                    case "$n" in
                        stackshot-reload.service|stackshot-portal-sync.service|stackshot-audit.service|stackshot-audit.timer|stackshot-standby-push.service|stackshot-standby-push.timer|stackshot-memo-files-clean.service|stackshot-memo-files-clean.timer) ;;   # the audit's: a restart of its service would cue an audit, the push's would push; the timers are re-armed above
                        stackshot-frontdoor.service|stackshot-signin.service|stackshot-splitter.service|stackshot-splitter.Caddyfile) ;;   # front_restart below: only one that runs already
                        stackshot-minute.service) systemctl --user reset-failed "$n" 2>/dev/null || true; systemctl --user restart "$n" && echo "  restarted $n" ;;   # reset-failed first: past its start limit a plain restart is refused
                        *) systemctl --user restart "$n" && echo "  restarted $n" ;;
                    esac
                done
                front_restart || exit 1
            elif [ "$QUIET_HINT" = 0 ]; then
                echo "changed, not restarted: ${changed[*]}  (rerun with --restart, or restart them yourself)"
            fi
        fi
        [ $MINUTE_STUCK = 0 ] || { echo "not finished: stackshot-minute.service is still running" >&2; exit 1; } ;;
    minute-off)   # the minute unit stopped, disabled and removed, whatever the setting says: deploy.sh runs it before a rollback to a commit from before this unit, whose own deploy.sh knows nothing of it
        if [ ! -f "$UNIT_DIR/stackshot-minute.service" ]; then      # the file first: with nothing installed there is nothing to stop, and no systemctl is needed to say so
            echo "  stackshot-minute.service: not installed"
        elif ! command -v systemctl >/dev/null 2>&1; then      # fail closed: a unit file that cannot be stopped is not removed
            echo "  stackshot-minute.service: its file is left in place, it could not be stopped: systemctl is not available" >&2; exit 1
        else
            user_manager_ok || exit 1
            minute_remove || { echo "  stackshot-minute.service: its file is left in place, it could not be stopped; stop it (systemctl --user stop stackshot-minute.service), then run this again" >&2; exit 1; }
            systemctl --user daemon-reload
            echo "  stackshot-minute.service: stopped, disabled and removed"
        fi ;;
    *) sed -n '2,/^set -euo/{/^set -euo/!p}' "$0"; exit 2 ;;
esac
