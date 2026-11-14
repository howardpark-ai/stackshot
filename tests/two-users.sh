#!/usr/bin/env bash
# tests/two-users.sh — prove that two users on one box each run their own stackshot server (one server per user).
#
# Run as root inside a fresh Ubuntu 24.04 container; it creates two users, alice and bob (no sudo), installs stackshot
# for each as that user, under that user's own config, state, secrets and systemd user units, on that user's own port
# (alice 8020, bob 8021), and checks that the two instances never meet. Each check prints PASS or FAIL; the exit status
# is the number of failures (0 = proven). It is a proof, not a CI job: it needs systemd, network (uv, its Python and the
# server's dependencies) and a few minutes.
#
#   # on the host, from a checkout of the branch to prove:
#   git bundle create /tmp/stackshot.bundle HEAD
#   lxc launch ubuntu:24.04 test-box             # or an image fingerprint from `lxc image list`
#   lxc file push /tmp/stackshot.bundle test-box/root/stackshot.bundle
#   lxc file push tests/two-users.sh test-box/root/two-users.sh
#   lxc exec test-box -- bash /root/two-users.sh /root/stackshot.bundle
#   # then the boot test: no one logs in, both instances must come back on their own
#   lxc restart test-box
#   lxc exec test-box -- bash /root/two-users.sh --after-boot
#
# $1 is a git bundle (the first ref it lists is checked out) or a checkout directory (copied). Each user gets their
# own copy in ~/stackshot. Setup runs with --force, so a second run on the same container rewrites the configs and
# proves the same again. The server's Google OAuth client is a placeholder pair: the server starts and answers /healthz
# and the machine-token API, which is all this proves; nobody signs in. The public base URLs (https://alice.example.test,
# https://bob.example.test) resolve nowhere, so doctor's "OAuth metadata reachable" line is expected to be missing.
set -u
USERS=(alice bob); declare -A PORT=([alice]=8020 [bob]=8021)
MARK=/root/two-users.mark                      # files newer than this outside the homes were written by the install
pass=0; fail=0
check() {   # check <name> <command…>: PASS when the command succeeds
    local name="$1"; shift
    if "$@" >/dev/null 2>&1; then echo "PASS  $name"; pass=$((pass + 1)); else echo "FAIL  $name"; fail=$((fail + 1)); fi
}
as() { local u="$1"; shift; su - "$u" -c "$*"; }                      # a login shell: pam_systemd sets XDG_RUNTIME_DIR
as_nologin() { local u="$1"; shift; runuser -u "$u" -- bash -c "cd ~ && $*"; }   # not a login: XDG_RUNTIME_DIR unset
http_code() { curl -s -o /dev/null -m 5 -w '%{http_code}' "$1"; }
listener_user() { local pid; pid="$(ss -Hltnp "sport = :$1" | grep -o 'pid=[0-9]*' | head -1 | cut -d= -f2)"; [ -n "$pid" ] && ps -o user= -p "$pid" | tr -d ' '; }
refused_by() { ! su - "$1" -c "cd ~/stackshot && STACKSHOT_URL=http://127.0.0.1:$2 python3 stackshot/fleet/client.py get whoami"; }   # <user> <port>
resolves_under() { su - "$1" -c "cd ~/stackshot && python3 stackshot/core/config.py $2" | grep -q "^$3/"; }                       # <user> <config.py verb> <dir>
wait_healthz() { for _ in $(seq 90); do [ "$(http_code "http://127.0.0.1:$1/healthz")" = 200 ] && return 0; sleep 2; done; return 1; }

[ "$(id -u)" = 0 ] || { echo "run as root inside the container" >&2; exit 2; }

# ---------------------------------------------------------------------------- the boot test (after `lxc restart`)
if [ "${1:-}" = "--after-boot" ]; then
    echo "== after boot, with nobody logged in"
    check "no login session exists (loginctl list-sessions is empty)" test -z "$(loginctl list-sessions --no-legend)"
    for u in "${USERS[@]}"; do
        check "$u: lingering is on" test -e "/var/lib/systemd/linger/$u"
        check "$u: /healthz on ${PORT[$u]} answers 200" wait_healthz "${PORT[$u]}"
        for unit in stackshot.service stackshot-reload.path stackshot-puller.service; do
            check "$u: $unit is active" test "$(systemctl --user -M "$u@" is-active "$unit")" = active
        done
        check "$u: the server on ${PORT[$u]} runs as $u" test "$(listener_user "${PORT[$u]}")" = "$u"
    done
    echo "== $pass passed, $fail failed"; exit "$fail"
fi

SRC="${1:?usage: two-users.sh <bundle or checkout dir> | --after-boot}"
SRC="$(realpath "$SRC")"

# ---------------------------------------------------------------------------- 1. the box: two plain users, lingering, nothing else
echo "== the box"
for u in "${USERS[@]}"; do
    id "$u" >/dev/null 2>&1 || useradd -m -s /bin/bash "$u"
    loginctl enable-linger "$u"               # root does this once per user; their user manager now runs without a login
done
for u in "${USERS[@]}"; do for _ in $(seq 30); do [ -d "/run/user/$(id -u "$u")" ] && break; sleep 1; done; done
check "alice and bob have no sudo" bash -c '! id -nG alice | grep -qw sudo && ! id -nG bob | grep -qw sudo'
sleep 1; touch "$MARK"; sleep 1

# ---------------------------------------------------------------------------- 2. install, each user as themselves
for u in "${USERS[@]}"; do
    h="$(getent passwd "$u" | cut -d: -f6)"; p="${PORT[$u]}"; U="${u^}"
    echo "== install as $u (port $p)"
    if [ -f "$SRC" ]; then
        install -o "$u" -g "$u" -m 0644 "$SRC" "$h/stackshot.bundle"
        as "$u" 'rm -rf ~/stackshot && git init -q -b main ~/stackshot && cd ~/stackshot && b=~/stackshot.bundle && git fetch -q "$b" "$(git bundle list-heads "$b" | awk "{print \$2}" | head -1)" && git reset -q --hard FETCH_HEAD'
    else
        rm -rf "$h/stackshot"; cp -a "$SRC" "$h/stackshot"; chown -R "$u:$u" "$h/stackshot"
    fi
    as "$u" 'command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1'
    as "$u" "cd ~/stackshot && bin/stackshot setup --yes --owner $U --tz UTC --base-url https://$u.example.test --emails $u@example.test --port $p --force" > "$h/setup.log" 2>&1
    check "$u: setup exits 0" grep -q "fill oauth.env" "$h/setup.log"
    # a placeholder Google client (not a credential: nobody signs in here), so doctor starts the server
    as "$u" "sed -i 's/^STACKSHOT_GOOGLE_CLIENT_ID=.*/STACKSHOT_GOOGLE_CLIENT_ID=two-users-test.apps.googleusercontent.com/; s/^STACKSHOT_GOOGLE_CLIENT_SECRET=.*/STACKSHOT_GOOGLE_CLIENT_SECRET=placeholder/' ~/.config/stackshot/oauth.env"
    as "$u" 'cd ~/stackshot && bin/stackshot doctor' > "$h/doctor-1.log" 2>&1
    as "$u" 'cd ~/stackshot && bin/stackshot client install' > "$h/client-install.log" 2>&1
    check "$u: client install wrote $u's settings.json" test -f "$h/.claude/settings.json"
done

# ---------------------------------------------------------------------------- 3. the two instances, side by side
echo "== the two instances"
for u in "${USERS[@]}"; do
    h="$(getent passwd "$u" | cut -d: -f6)"; p="${PORT[$u]}"; uid="$(id -u "$u")"
    check "$u: /healthz on $p answers 200" wait_healthz "$p"
    check "$u: the server on $p runs as $u" test "$(listener_user "$p")" = "$u"
    check "$u: the server is a user unit of $u's manager" test "$(systemctl --user -M "$u@" is-active stackshot.service)" = active
    check "$u: the puller runs" test "$(systemctl --user -M "$u@" is-active stackshot-puller.service)" = active
    check "$u: the puller process belongs to $u" bash -c "ps -eo user=,args= | grep -q '^$u .*puller.py'"
    check "$u: client.url points at $p" test "$(cat "$h/.config/stackshot/client.url")" = "http://127.0.0.1:$p"
    check "$u: client.py get whoami answers from $u's server (login shell)" as "$u" 'cd ~/stackshot && python3 stackshot/fleet/client.py get whoami | grep -q machine'
    check "$u: …and from a shell that is not a login" as_nologin "$u" 'cd ~/stackshot && python3 stackshot/fleet/client.py get whoami | grep -q machine'
    other=$([ "$u" = alice ] && echo bob || echo alice)
    check "$u: $u's token is refused by $other's server" refused_by "$u" "${PORT[$other]}"
    as_nologin "$u" './stackshot/bin/stackshot doctor' > "$h/doctor.log" 2>&1        # the non-login path (XDG_RUNTIME_DIR repaired)
    check "$u: doctor says server box" bash -c "head -1 '$h/doctor.log' | grep -q 'server box'"
    check "$u: doctor flags nothing but the placeholder URL's OAuth metadata and the data repository's missing origin" \
        bash -c "! grep -E '^  (missing|warn)' '$h/doctor.log' | grep -v -e 'OAuth metadata reachable' -e 'no origin remote'"
    check "$u: the four hooks are in $u's own settings.json, pointing at $u's checkout" python3 - "$h" <<'PY'
import json, sys
h = sys.argv[1]; s = json.load(open(f"{h}/.claude/settings.json"))["hooks"]
cmds = {ev: " ".join(x.get("command", "") for e in s.get(ev, []) for x in e.get("hooks", [])) for ev in ("SessionStart", "UserPromptSubmit", "Stop", "PostToolUse")}
sys.exit(0 if all(f"{h}/stackshot/client/hooks/" in c for c in cmds.values()) else 1)
PY
    for what in "file" "state publish.lock" "secrets client.token" "path paths.repo" "path paths.brain" "path paths.project_touch"; do
        check "$u: config.py $what is under $h" resolves_under "$u" "$what" "$h"
    done
    check "$u: the units are under $h/.config/systemd/user" test -f "$h/.config/systemd/user/stackshot.service" -a -f "$h/.config/systemd/user/stackshot-puller.service"
    check "$u: the runtime directory /run/user/$uid is $u's" test "$(stat -c %U "/run/user/$uid")" = "$u"
done
check "the two servers listen on different ports" test "${PORT[alice]}" != "${PORT[bob]}"
check "bob cannot set up a second instance on alice's port (setup refuses, writes nothing)" bash -c \
    "su - bob -c 'cd ~/stackshot && STACKSHOT_CONFIG=~/taken.toml bin/stackshot setup --yes --port ${PORT[alice]} --data ~/taken-data --no-systemd' | grep -q 'is taken on this box by alice' && test ! -e /home/bob/taken.toml -a ! -e /home/bob/taken-data"

# ---------------------------------------------------------------------------- 4. nothing written outside the two homes and /run/user
echo "== outside the homes"
check "no stackshot unit in /etc/systemd/system" bash -c '! ls /etc/systemd/system | grep -q -e stackshot -e anchor-hub'
check "no /etc/stackshot" test ! -e /etc/stackshot
new="$(find /etc /var /tmp /opt /srv /usr/local -xdev -newer "$MARK" \( -type f -o -type s -o -type d \) 2>/dev/null \
         | grep -v -E '^/var/log/|^/var/lib/systemd/(timers|catalog|coredump)|^/var/cache/|^/var/lib/apt/|^/var/lib/dpkg/|^/var/tmp/systemd-private|^/tmp/systemd-private|^/tmp$|^/var/tmp$|^/var/lib/private$' || true)"
uvlocks="$(echo "$new" | grep -E '^/tmp/uv-[0-9a-f]+\.lock$' || true)"      # uv's own empty lock files, named from each user's paths
stray="$(echo "$new" | grep -v -E '^/tmp/uv-[0-9a-f]+\.lock$' | grep . || true)"
[ -z "$uvlocks" ] || echo "      uv's own lock files: $(for f in $uvlocks; do printf '%s (%s) ' "$f" "$(stat -c %U "$f")"; done)"
[ -z "$stray" ] || { echo "      written outside the homes:"; echo "$stray" | sed 's/^/        /'; }
check "uv's /tmp lock files (if any) are one per user, each owned by alice or bob" \
    bash -c "for f in $(echo $uvlocks); do stat -c %U \"\$f\" | grep -qx -e alice -e bob || exit 1; done"
check "nothing new in /etc, /var, /tmp, /opt, /srv or /usr/local (logs and caches aside)" test -z "$stray"

echo "== $pass passed, $fail failed"
exit "$fail"
