#!/usr/bin/env bash
# install.sh — render stackshot's systemd units for this checkout and install them. The templates in
# units/*.in carry no path of any one machine: @CHECKOUT@ (this directory), @CONFIG@ (the instance config, config.py's
# answer, which stackshot-reload.path watches), @HOME@, @UV@, @PORT@ (server.port), @TZ@ (instance.timezone) @AUDIT_AT@
# ([audit] at, HH:MM or a list of them) and @AUDIT_PROJECT@ ([audit] project) are filled in here.
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
#                                   started: it only arms the schedule, the audit, or its cue in mode "agent", runs at [audit] at)
#   ./install.sh puller             the puller's user unit alone (a box that only fetches; never sudo)
#   ./install.sh render [name]      print the rendered unit(s), install nothing (no name: the units `units` would install);
#                                   the unit directory goes to stderr
#   options: --checkout DIR  --config FILE  --restart (restart the units whose file changed; otherwise only say which)
#            --start (after enabling, start the long-running units of this verb, or restart them if running; how setup
#            brings a fresh box up)  --quiet-hint (do not print the "changed, not restarted" hint; setup's own next line says
#            why the server is not started)
#
# Installing never restarts anything unless --restart or --start is given: deploy.sh restarts the server, anchor-hub and the
# puller when a change touches them (the reload path only reloads the config file). A unit whose rendered text is unchanged
# is left alone, so running this twice does nothing the second time. Enables each unit it installs. A unit whose condition
# is off is skipped, never removed or disabled: an existing one stays as it is. The one exception is the audit's pair:
# with [audit] enabled = false a timer installed by an earlier run is disabled and stopped and both files are removed, since
# a timer left behind would fire every day into a cue the server refuses. Its service is never restarted here: that would cue an audit.
set -euo pipefail
USER="${USER:-$(id -un)}"                     # unset under some sudo, cron and container shells; the units and loginctl need it
HERE="$(cd "$(dirname "$0")" && pwd)"
CHECKOUT="$HERE"; CONFIG=""; RESTART=0; START=0; QUIET_HINT=0; VERB="${1:-}"; shift || true
ARGS=()
while [ $# -gt 0 ]; do
    case "$1" in
        --checkout) CHECKOUT="$(cd "$2" && pwd)"; shift 2 ;;
        --config) CONFIG="$2"; shift 2 ;;
        --restart) RESTART=1; shift ;;
        --start) START=1; shift ;;
        --quiet-hint) QUIET_HINT=1; shift ;;
        *) ARGS+=("$1"); shift ;;
    esac
done
[ -n "$CONFIG" ] || CONFIG="$(python3 "$CHECKOUT/stackshot/core/config.py" file)"
CONFIG="$(python3 -c 'import os,sys; print(os.path.realpath(os.path.expanduser(sys.argv[1])))' "$CONFIG")"
PORT="$(STACKSHOT_CONFIG="$CONFIG" python3 "$CHECKOUT/stackshot/core/config.py" get server.port)"
TZNAME="$(STACKSHOT_CONFIG="$CONFIG" python3 "$CHECKOUT/stackshot/core/config.py" get instance.timezone)"; TZNAME="${TZNAME:-UTC}"
PORTAL=0; [ -n "$(STACKSHOT_CONFIG="$CONFIG" python3 "$CHECKOUT/stackshot/core/config.py" get portal.account_id)" ] && PORTAL=1       # the portal-sync unit and its drop-in
HUB=0; case "$(STACKSHOT_CONFIG="$CONFIG" python3 "$CHECKOUT/stackshot/core/config.py" get anchor_hub.enabled | tr '[:upper:]' '[:lower:]')" in true|1|yes) HUB=1 ;; esac   # anchor-hub's user unit
read -r AUDIT AUDIT_AT AUDIT_PROJECT < <(STACKSHOT_CONFIG="$CONFIG" python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); from stackshot.core import config as c; print(int(c.audit_enabled()), ",".join(c.audit_at()), c.audit_project())' "$CHECKOUT")   # the audit's timer pair, its HH:MM times (comma-joined: one OnCalendar line each)
UV="$(command -v uv || echo "$HOME/.local/bin/uv")"
. "$HERE/units/scope.sh"      # UNIT_DIR, xdg_repair, user_manager_ok (config.py refused a removed mode above, with its line)
SERVERU=" stackshot.service stackshot-reload.service stackshot-reload.path stackshot-portal-sync.service stackshot.service.d-portal-sync.conf "   # the server's units: their header names the user manager
render() {   # render <name> → stdout: the template with its placeholders filled in
    local t="$HERE/units/$1.in"; [ -f "$t" ] || { echo "no template $t" >&2; return 1; }
    local kind=unit; case "$SERVERU" in *" $1 "*) kind=server ;; esac
    python3 - "$t" "$CHECKOUT" "$CONFIG" "$HOME" "$UV" "$PORT" "$TZNAME" "$kind" "$AUDIT_AT" "$AUDIT_PROJECT" <<'PY'
import sys
t, checkout, config, home, uv, port, tz, kind, audit_at, audit_project = sys.argv[1:11]
s = open(t, encoding="utf-8").read()
# a line that carries @AUDIT_AT@ is written once per time of [audit] at (audit_at is the comma-joined list), so the timer has one OnCalendar line for each
s = "".join("".join(l.replace("@AUDIT_AT@", t) for t in audit_at.split(",")) if "@AUDIT_AT@" in l else l for l in s.splitlines(keepends=True))
for k, v in (("@CHECKOUT@", checkout), ("@CONFIG@", config), ("@HOME@", home), ("@UV@", uv), ("@PORT@", port), ("@TZ@", tz), ("@AUDIT_PROJECT@", audit_project)):
    s = s.replace(k, v)
left = [l for l in s.splitlines() if "@" in l and "@" in l.split("#")[0]]
if left:
    sys.exit("unrendered placeholder in %s: %s" % (t, left[0].strip()))
name = t.rsplit("/", 1)[1]
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
changed=()
put() {      # put <name> <dir>  → installs when the rendered text differs
    local name="$1" dir="$2" tmp; tmp="$(mktemp)"; render "$name" > "$tmp"
    if [ -f "$dir/$name" ] && cmp -s "$tmp" "$dir/$name"; then rm -f "$tmp"; echo "  $name: unchanged"; return 0; fi
    install -D -m 0644 "$tmp" "$dir/$name"
    rm -f "$tmp"; changed+=("$name"); echo "  $name: installed → $dir/$name"
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
        for n in "${ARGS[@]:-${SERVER[@]} ${USERU[@]}}"; do for m in $n; do [ $first = 1 ] || echo "# ---------------- $m"; first=0; render "$m"; done; done ;;
    units|puller)
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
        fi
        for n in "${USERU[@]}"; do [ "$VERB" = units ] || [ "$n" = stackshot-puller.service ] || continue; put "$n" "$UNIT_DIR"; done
        systemctl --user daemon-reload
        [ "$VERB" = units ] && { systemctl --user enable --quiet stackshot.service stackshot-reload.path 2>/dev/null || true; }
        [ "$VERB" = units ] && [ $HUB = 1 ] && systemctl --user enable --quiet anchor-hub.service 2>/dev/null || true
        if [ "$VERB" = units ] && [ $AUDIT = 1 ]; then    # arming the timer runs nothing: the cue waits for [audit] at
            systemctl --user enable --now --quiet stackshot-audit.timer 2>/dev/null || true
            case " ${changed[*]:-} " in *" stackshot-audit.timer "*) systemctl --user restart stackshot-audit.timer 2>/dev/null || true ;; esac   # a new [audit] at
        fi
        systemctl --user enable --quiet stackshot-puller.service 2>/dev/null || true
        if [ "$START" = 1 ]; then          # start what this verb runs, or restart it if it is running (covers --restart too)
            failed=()
            start() {   # start <name>
                systemctl --user restart "$1" && echo "  started $1" || { echo "  FAILED to start $1" >&2; failed+=("$1"); }
            }
            if [ "$VERB" = units ]; then
                start stackshot.service; start stackshot-reload.path
                if [ $HUB = 1 ]; then start anchor-hub.service; fi
            fi
            start stackshot-puller.service
            if [ ${#failed[@]} -gt 0 ]; then echo "not started: ${failed[*]}" >&2; exit 1; fi
        elif [ ${#changed[@]} -gt 0 ]; then
            if [ "$RESTART" = 1 ]; then
                for n in "${changed[@]}"; do
                    case "$n" in
                        stackshot-reload.service|stackshot-portal-sync.service|stackshot-audit.service|stackshot-audit.timer) ;;   # the audit's: a restart of its service would cue an audit; its timer is re-armed above
                        *) systemctl --user restart "$n" && echo "  restarted $n" ;;
                    esac
                done
            elif [ "$QUIET_HINT" = 0 ]; then
                echo "changed, not restarted: ${changed[*]}  (rerun with --restart, or restart them yourself)"
            fi
        fi ;;
    *) sed -n '2,/^set -euo/{/^set -euo/!p}' "$0"; exit 2 ;;
esac
