# units/scope.sh — sourced by install.sh, deploy.sh and the reboot hooks: the units are user units under
# ~/.config/systemd/user, driven with systemctl --user, and nothing here calls sudo. (The system scope under
# /etc/systemd/system was removed in an earlier change; an instance still installed there moves first, see
# INSTALL.md: https://github.com/howardpark-ai/stackshot/blob/main/INSTALL.md#an-instance-installed-in-the-system-scope.
# A config that still says [units] scope = "system" is refused by config.py, and so by every script that reads it.)
#
# XDG_RUNTIME_DIR: `systemctl --user` finds the user manager through it, and only a login sets it (pam_systemd): `sudo -u`,
# `lxc exec --user` and cron leave it unset. xdg_repair points it at the user's runtime directory when it is unset and that
# directory exists (the user manager runs: lingering, or a session elsewhere); sourcing this file runs it once.
# STACKSHOT_RUNTIME_BASE replaces /run/user for the tests. user_manager_ok says so when the manager is still out of reach.
xdg_repair() {
    if [ -z "${XDG_RUNTIME_DIR:-}" ] && [ -d "${STACKSHOT_RUNTIME_BASE:-/run/user}/$(id -u)" ]; then
        export XDG_RUNTIME_DIR="${STACKSHOT_RUNTIME_BASE:-/run/user}/$(id -u)"
    fi
}
xdg_repair
user_manager_ok() {   # 0 when systemctl --user reaches the user manager; otherwise say what to do, 1
    systemctl --user show-environment >/dev/null 2>&1 && return 0
    echo '`systemctl --user` cannot reach your user manager: export XDG_RUNTIME_DIR=/run/user/$(id -u), or log in (ssh, console, su -, sudo -i)' >&2
    return 1
}
UNIT_DIR="$HOME/.config/systemd/user"

server_ctl() {   # server_ctl <systemctl args…>: systemctl for the server's units — the user manager's
    systemctl --user "$@"
}
