"""Scenario test for reboot-hooks/stackshot-hook: its unit verbs drive the user unit — no real sudo, no real systemd,
nothing outside a temp dir (HOME, the config and every state path live there; systemctl, sudo and curl are stubs).

Covers: status, start and stop go through `systemctl --user` and never call sudo; a config that still says [units] scope =
"system" (removed in) fails every verb with config.py's line as the summary (exit 1) before any systemctl call; the user
manager out of reach fails status with a summary line (exit 1) instead of reading as "stopped"; an unset XDG_RUNTIME_DIR is
pointed at the runtime directory when it exists (a boot restore with no login session); flush-stop on a stopped unit says
"already stopped"; status exit codes 0 / 3.

    tests/run-suite hook        → exit 0 / 1"""
import os, re, shutil, subprocess, sys, pathlib, tempfile
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
HOOK = os.path.join(STACK, "reboot-hooks", "stackshot-hook")
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="hooktest-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store (session links off)
home = T / "home"; home.mkdir(); (T / "bin").mkdir()
# systemctl: logs every call (with XDG_RUNTIME_DIR), is-active from the state file, start/stop write it; show-environment
# fails when the flag file says the user manager is out of reach
(T / "bin/systemctl").write_text(f'''#!/bin/sh
echo "systemctl $* XDG=${{XDG_RUNTIME_DIR:-}}" >> {tmp}/calls.log
for a in "$@"; do case "$a" in
  show-environment) [ -e {tmp}/no-manager ] && exit 1; exit 0 ;;
  is-active) [ "$(cat {tmp}/state 2>/dev/null)" = active ] && exit 0; exit 3 ;;
  start) echo active > {tmp}/state; exit 0 ;;
  stop) echo inactive > {tmp}/state; exit 0 ;;
esac; done
exit 0
''')
# sudo: `-n true` succeeds only when the flag file says sudo is passwordless; otherwise runs the rest of its arguments
(T / "bin/sudo").write_text(f'''#!/bin/sh
echo "sudo $*" >> {tmp}/calls.log
[ "$1" = -n ] && shift
if [ "$1" = true ]; then [ -e {tmp}/sudo-ok ] && exit 0; exit 1; fi
[ -e {tmp}/sudo-ok ] || exit 1
exec "$@"
''')
(T / "bin/curl").write_text(f'#!/bin/sh\n[ "$(cat {tmp}/state 2>/dev/null)" = active ]\n')   # /healthz answers while the unit runs
for n in ("systemctl", "sudo", "curl"): (T / "bin" / n).chmod(0o755)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:600]}" if got is not None else ""))

def conf(kind):
    """user = the example as it is (no [units] section since); system = an older config that still says scope = "system"."""
    assert re.search(r"(?m)^\[units\]", toml) is None
    t = toml if kind == "user" else toml + '\n[units]\nscope = "system"\n'
    p = T / f"{kind}.toml"; p.write_text(t, encoding="utf-8"); return str(p)

def hook(cfg, *args, state=None, sudo=False, manager=True, xdg=None, runbase=None):
    for f in ("calls.log", "sudo-ok", "no-manager"): (T / f).unlink(missing_ok=True)
    if state: (T / "state").write_text(state)
    if sudo: (T / "sudo-ok").touch()
    if not manager: (T / "no-manager").touch()
    env = {k: v for k, v in os.environ.items() if k not in ("STACKSHOT_CONFIG", "BOARD_MCP_CONFIG", "XDG_RUNTIME_DIR", "STACKSHOT_RUNTIME_BASE")}
    env.update({"PATH": f"{tmp}/bin:" + os.environ.get("PATH", ""), "HOME": str(home), "STACKSHOT_CONFIG": cfg})
    if xdg: env["XDG_RUNTIME_DIR"] = xdg
    env["STACKSHOT_RUNTIME_BASE"] = runbase or f"{tmp}/no-such-run"
    r = subprocess.run([HOOK, *args], capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL)
    calls = (T / "calls.log").read_text() if (T / "calls.log").exists() else ""
    last = (r.stdout.strip().splitlines() or [""])[-1]
    return r.returncode, last, calls, r.stdout + r.stderr

user, system = conf("user"), conf("system")
XDG = f"{tmp}/run-1"

rc, last, calls, out = hook(user, "status", state="active", xdg=XDG)
check("user: status running → exit 0", rc == 0 and last.startswith("stackshot running and healthy"), out)
check("user: status reads the unit with systemctl --user", "systemctl --user is-active -q stackshot.service" in calls, calls)
check("user: status never calls sudo", "sudo" not in calls, calls)
rc, last, calls, out = hook(user, "status", state="inactive", xdg=XDG)
check("user: status stopped → exit 3", rc == 3 and last.startswith("stackshot stopped"), out)
rc, last, calls, out = hook(user, "start", state="inactive", xdg=XDG)
check("user: start → running and healthy, exit 0", rc == 0 and last.startswith("stackshot running and healthy"), out)
check("user: start goes through systemctl --user start", "systemctl --user start stackshot.service" in calls, calls)
check("user: start never calls sudo", "sudo" not in calls, calls)
rc, last, calls, out = hook(user, "flush-stop", state="inactive", xdg=XDG)
check("user: flush-stop on a stopped unit → already stopped, exit 0", rc == 0 and "already stopped" in last, out)
rc, last, calls, out = hook(user, "status", state="active", manager=False, xdg=XDG)
check("user: manager out of reach → status fails with a summary line, exit 1",
      rc == 1 and last.startswith("stackshot status failed: systemctl --user cannot reach the user manager"), out)
rc, last, calls, out = hook(user, "start", state="inactive", manager=False, xdg=XDG)
check("user: manager out of reach → start fails before starting anything", rc == 1 and "start stackshot.service" not in calls, calls)
(T / "rb" / str(os.getuid())).mkdir(parents=True)
rc, last, calls, out = hook(user, "status", state="active", runbase=f"{tmp}/rb")
check("user: no XDG_RUNTIME_DIR (boot restore, no login) → pointed at the runtime directory",
      rc == 0 and f"is-active -q stackshot.service XDG={tmp}/rb/{os.getuid()}" in calls, calls)

rc, last, calls, out = hook(system, "status", state="active", sudo=True, xdg=XDG)
check('a config that still says [units] scope = "system": status fails with config.py\'s line as its summary, exit 1',
      rc == 1 and last.startswith('stackshot status failed: [units] scope = "system"') and "removed; " in last, out)
check("…before any systemctl or sudo call", calls == "", calls)
rc, last, calls, out = hook(system, "start", state="inactive", sudo=True, xdg=XDG)
check("…and so does start, starting nothing", rc == 1 and last.startswith("stackshot start failed: [units] scope") and calls == "", out)

rc, last, calls, out = hook(user, "nonsense")
check("usage: exit 2, the verbs listed", rc == 2 and "flush-stop" in out and "resume --since" in out, out)

shutil.rmtree(tmp, ignore_errors=True)
if fails:
    print(f"FAILED: {len(fails)} of {len(ran)} checks"); sys.exit(1)
print(f"ok: hook scenario, {len(ran)} checks")
