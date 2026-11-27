"""Scenario test for `stackshot standby-push` (stackshot/tools/standby_push.py, docs/standby-copy.md): a fake `ssh` first on PATH and a fake copy in the place of `standby-copy`,
real OS processes, no network, no server.

  1  the command    listed under `stackshot`, its help needs no config; the real copy command is this python's `-m stackshot standby-copy` with the flags after it; the ssh command starts with -F /dev/null
  2  both succeed   exit 0, standard output empty, the stream reaches ssh whole; ssh's argv is exactly the options of the design and ends with push_to, no remote command; the copy gets the
                    flags (--lock-timeout, --max-hold, --output-timeout, --extra twice); the state file says ok with `last_ok_at` set
  3  ssh fails      exit 1, one line of the push's own that names ssh and its exit code and not the copy; ssh's own stderr is passed through; `last_ok_at` kept from the run before
  4  copy fails     exit 1, one line that names the copy and its exit code and not ssh; ssh got the cut stream and ended; the copy's own line is passed through
  5  refusals       push_to empty, a key or a known_hosts file not set, missing or not a file, a push_to that starts with `-` or has a space, a bad push_timeout, a push_timeout above 540 (540 itself is
                    accepted): each exit 3 with one line; nothing runs and no state file
  6  the limits     push_timeout kills both children and exits 1; a child that ignores SIGTERM is killed 5 s later; SIGTERM, SIGINT, SIGHUP and SIGQUIT stop both and exit 143, 130, 129, 131; ssh ending
                    non-zero first stops the copy at once
  7  one at a time  a run while the lock is held exits 1 with one line, runs nothing and leaves the state file as it was
  8  the state file 0600, replaced whole (a new inode, no temporary file left, an old file kept when the rename fails), `last_ok_at` kept through failures
  9  ssh ends 0    the copy gets GRACE seconds after a clean ssh: a copy that ends 0 within it is a good run; one that ends 1 within it is named; one still running past it is stopped and the
                    run says "ssh ended before the copy did"; a child that cannot be started (no ssh on PATH, a copy that does not exist) gives one line, exit 1, no traceback, the started child stopped

    tests/run-suite standby_push        -> exit 0 / 1"""
import fcntl, json, os, pathlib, signal, subprocess, sys, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
sys.path.insert(0, SCR); sys.path.insert(0, STACK)
import _scratch

T = pathlib.Path(_scratch.mkdtemp(prefix="standbypushtest-"))
STATE, BIN, REC, HOME = T / "state", T / "bin", T / "rec", T / "home"
for d in (STATE, BIN, REC, HOME):
    d.mkdir()
KEY, KNOWN = T / "id_test", T / "known_hosts"
KEY.write_text("not a real key\n"); KNOWN.write_text("standby-host ssh-ed25519 AAAA\n")
TARGET = "user@standby-host"
PUSH_TIMEOUT = 30
STREAM = "STREAM-BYTES-" + "x" * 1000
fails = []; ran = []


def check(name, cond, got=None):
    ran.append(name)
    if not cond:
        fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:600]}" if got is not None else ""))


# The fake ssh: records its argv (one per line) and its stdin, then ends the way FAKE_SSH_MODE says. The fake copy writes a stream, then ends the way FAKE_COPY_MODE says.
(BIN / "ssh").write_text(f'''#!/bin/sh
printf '%s\\n' "$$" > {REC}/ssh.pid
for a in "$@"; do printf '%s\\n' "$a"; done > {REC}/ssh.argv
case "$FAKE_SSH_MODE" in
  hang) exec sleep 600 ;;
  deaf) trap '' TERM HUP INT; while :; do sleep 1; done ;;
  early) sleep "${{FAKE_SSH_DELAY:-0}}"; echo "ssh: connection refused (fake)" >&2; exit "${{FAKE_SSH_EXIT:-255}}" ;;
esac
cat > {REC}/ssh.stdin
echo "remote said hello"
[ "${{FAKE_SSH_EXIT:-0}}" = 0 ] || echo "ssh: fake failure" >&2
exit "${{FAKE_SSH_EXIT:-0}}"
''')
(BIN / "ssh").chmod(0o755)
FAKE_COPY = T / "fake_copy.py"
FAKE_COPY.write_text(f'''import os, signal, sys, time
open("{REC}/copy.pid", "w").write(str(os.getpid()))
open("{REC}/copy.argv", "w").write("\\n".join(sys.argv[1:]))
mode = os.environ.get("FAKE_COPY_MODE", "ok")
if mode == "deaf":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
if os.environ.get("FAKE_COPY_TRAP"):    # like standby-copy: SIGTERM is caught and the process exits 128 + 15
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
out = sys.stdout.buffer
if mode == "fail":
    out.write(b"PARTIAL"); out.flush()
    print("standby-copy: failed: fake trouble", file=sys.stderr); sys.exit(1)
out.write({STREAM!r}.encode()); out.flush()
if mode == "linger":    # the stream is complete and closed, then the copy goes on (its staging folder) for FAKE_COPY_LINGER seconds and ends with FAKE_COPY_EXIT
    os.close(1)
    time.sleep(float(os.environ.get("FAKE_COPY_LINGER", "0")))
    sys.exit(int(os.environ.get("FAKE_COPY_EXIT", "0")))
if mode in ("hang", "deaf"):
    while True: time.sleep(1)
if mode == "slow":      # still writing when ssh has gone
    for _ in range(600):
        time.sleep(0.1)
        try: out.write(b"more"); out.flush()
        except OSError: sys.exit(9)
''')
# The driver runs the real main() with the copy command replaced: the least that differs from `stackshot standby-push`.
DRIVER = T / "driver.py"
DRIVER.write_text(f'''import os, subprocess, sys, time
sys.path.insert(0, {STACK!r})
from stackshot.tools import standby_push as m
m.copy_command = lambda flags: [sys.executable, {str(FAKE_COPY)!r}, *flags]
if os.environ.get("STANDBY_PUSH_TEST_GRACE"):      # the copy's grace after a clean ssh, shortened so the checks stay fast
    m.GRACE = float(os.environ["STANDBY_PUSH_TEST_GRACE"])
if os.environ.get("STANDBY_PUSH_TEST_NO_COPY"):    # a copy that cannot be started; ssh, started first, is given time to start
    m.copy_command = lambda flags: ["/nonexistent/standby-copy"]
    real_popen = subprocess.Popen
    def slow_popen(cmd, *a, **k):
        if cmd and cmd[0] == "/nonexistent/standby-copy":
            time.sleep(0.5)
        return real_popen(cmd, *a, **k)
    subprocess.Popen = slow_popen
sys.exit(m.main(sys.argv[1:]))
''')


def config(name, **over):
    s = {"push_to": TARGET, "push_key": str(KEY), "push_known_hosts": str(KNOWN), "push_timeout": PUSH_TIMEOUT}
    s.update(over)
    lines = [f'[paths]\nstate = "{STATE}"\n\n[standby_copy]']
    for k, v in s.items():
        if v is not None:
            lines.append(f"{k} = {json.dumps(v)}")
    p = T / name
    p.write_text("\n".join(lines) + "\n")
    return str(p)


BASE_ENV = {"PATH": f"{BIN}:" + os.environ.get("PATH", ""), "HOME": str(HOME), "PYTHONDONTWRITEBYTECODE": "1"}


def clear():
    for p in REC.iterdir():
        p.unlink()


def env_for(cfg, **extra):
    return {**BASE_ENV, "STACKSHOT_CONFIG": cfg, **extra}


def run(cfg, *args, timeout=60, keep=False, **extra):
    if not keep:      # keep=True leaves the record folder alone, for a run started while another one's children are alive
        clear()
    try:
        r = subprocess.run([sys.executable, str(DRIVER), *args], capture_output=True, env=env_for(cfg, **extra), timeout=timeout, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:      # a run that does not end fails its checks by name, instead of stopping the suite
        return None, b"", f"the run did not end within {timeout} seconds"
    return r.returncode, r.stdout, r.stderr.decode()


def own_lines(err):
    return [l for l in err.splitlines() if l.startswith("standby-push:")]


def state():
    p = STATE / "standby-push.json"
    return json.loads(p.read_text()) if p.exists() else None


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:      # a zombie is as good as gone
        return pathlib.Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] != "Z"
    except OSError:
        return False


def wait_for(pred, secs=15):
    end = time.monotonic() + secs
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.05)
    return False


def pid_of(name):
    p = REC / name
    return int(p.read_text()) if p.exists() and p.read_text().strip() else None


def nothing_ran():
    return not any(REC.iterdir())


GOOD = config("good.toml")
EXPECTED = ["-F", "/dev/null", "-i", str(KEY), "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes", "-o", f"UserKnownHostsFile={KNOWN}", "-o", "GlobalKnownHostsFile=/dev/null",
            "-o", "ConnectTimeout=15", "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=4", "-o", "ControlMaster=no", "-o", "ControlPath=none", TARGET]

# ---- 1 the command
r = subprocess.run([sys.executable, "-m", "stackshot", "standby-push", "-h"], capture_output=True, text=True, cwd=STACK, env={**BASE_ENV, "STACKSHOT_CONFIG": str(T / "no-such.toml")}, timeout=60)
check("standby-push is a command of the package and its help needs no config", r.returncode == 0 and "--lock-timeout" in r.stdout and "--extra" in r.stdout, (r.returncode, r.stdout[-200:], r.stderr[-200:]))
r = subprocess.run([sys.executable, "-m", "stackshot", "--help"], capture_output=True, text=True, cwd=STACK, env=BASE_ENV, timeout=60)
check("the package's help lists standby-push next to standby-copy", "standby-push" in r.stdout and "standby-copy" in r.stdout, r.stdout[-300:])
sys.path.insert(0, STACK)
from stackshot.tools import standby_push as sp
check("the real copy command is this python, the package and `standby-copy` with the flags after it", sp.copy_command(["--max-hold", "3.0"]) == [sys.executable, "-m", "stackshot", "standby-copy", "--max-hold", "3.0"], sp.copy_command(["--max-hold", "3.0"]))
check("the ssh command starts with -F /dev/null, so no ssh config file is read", sp.ssh_command(TARGET, str(KEY), str(KNOWN))[:4] == ["ssh", "-F", "/dev/null", "-i"], sp.ssh_command(TARGET, str(KEY), str(KNOWN))[:6])

# ---- 2 both succeed
rc, out, err = run(GOOD, "--lock-timeout", "7", "--max-hold", "3", "--output-timeout", "9", "--extra", "/srv/one", "--extra", "/srv/two")
st = state()
check("both succeed: exit 0 and standard output empty", rc == 0 and out == b"", (rc, out[:100], err[-300:]))
check("both succeed: the stream reaches ssh whole", (REC / "ssh.stdin").read_text() == STREAM, (REC / "ssh.stdin").read_text()[:80] if (REC / "ssh.stdin").exists() else "no stdin")
check("both succeed: ssh's argv is every option of the design and the target, with no remote command", (REC / "ssh.argv").read_text().splitlines() == EXPECTED, (REC / "ssh.argv").read_text())
check("both succeed: the copy got the flags it was given", (REC / "copy.argv").read_text().splitlines() == ["--lock-timeout", "7.0", "--max-hold", "3.0", "--output-timeout", "9.0", "--extra", "/srv/one", "--extra", "/srv/two"],
      (REC / "copy.argv").read_text())
check("both succeed: nothing of the push's own on standard error, ssh's words passed through", own_lines(err) == [] and "remote said hello" not in out.decode(), err[-300:])
check("the state file says ok, with the keys of the design", st is not None and set(st) == {"at", "ok", "seconds", "error", "last_ok_at"} and st["ok"] is True and st["error"] == ""
      and st["last_ok_at"] == st["at"] and abs(st["at"] - time.time()) < 60 and isinstance(st["seconds"], float) and 0 <= st["seconds"] < 30, st)
good_at = st["last_ok_at"]
rc, out, err = run(GOOD)
check("no flags given: the copy gets none (its own defaults stand)", rc == 0 and (REC / "copy.argv").read_text() == "", (REC / "copy.argv").read_text())

# ---- 3 ssh fails
time.sleep(1.1)
rc, out, err = run(GOOD, FAKE_SSH_EXIT="7")
st = state()
check("ssh fails: exit 1, standard output empty", rc == 1 and out == b"", (rc, out))
check("ssh fails: one line of the push's own, naming ssh and its exit code, not the copy", len(own_lines(err)) == 1 and "ssh exited 7" in own_lines(err)[0] and "copy" not in own_lines(err)[0], err[-400:])
check("ssh fails: ssh's own stderr is passed through", "ssh: fake failure" in err, err[-400:])
check("ssh fails: the state says not ok, with the line, and last_ok_at kept", st["ok"] is False and "ssh exited 7" in st["error"] and "\n" not in st["error"] and st["last_ok_at"] >= good_at and st["last_ok_at"] < st["at"], st)
kept = st["last_ok_at"]
rc, out, err = run(GOOD, FAKE_SSH_EXIT="255", FAKE_SSH_MODE="early", FAKE_SSH_DELAY="1")
check("ssh ends before the stream is read: exit 1, the line names ssh (255); the copy is stopped, not waited for", rc == 1 and "ssh exited 255" in own_lines(err)[0], (rc, err[-400:]))
check("ssh ended first: the copy is gone", wait_for(lambda: pid_of("copy.pid") is not None and not alive(pid_of("copy.pid"))), pid_of("copy.pid"))
rc, out, err = run(GOOD, FAKE_SSH_EXIT="255", FAKE_SSH_MODE="early", FAKE_COPY_MODE="slow", FAKE_SSH_DELAY="1")
check("ssh ended first while the copy is still writing: exit 1, quickly, both gone", rc == 1 and state()["last_ok_at"] == kept and pid_of("copy.pid") is not None and not alive(pid_of("copy.pid")), (rc, err[-300:]))

# ---- 4 the copy fails
rc, out, err = run(GOOD, FAKE_COPY_MODE="fail")
st = state()
check("the copy fails: exit 1, standard output empty", rc == 1 and out == b"", (rc, out))
check("the copy fails: one line of the push's own, naming the copy and its exit code, not ssh", len(own_lines(err)) == 1 and "the copy exited 1" in own_lines(err)[0] and "ssh" not in own_lines(err)[0], err[-400:])
check("the copy fails: its own line is passed through", "standby-copy: failed: fake trouble" in err, err[-400:])
check("the copy fails: ssh got the cut stream and ended", (REC / "ssh.stdin").read_text() == "PARTIAL", (REC / "ssh.stdin").read_text() if (REC / "ssh.stdin").exists() else "no stdin")
check("the copy fails: the state says not ok and keeps last_ok_at", st["ok"] is False and "the copy exited 1" in st["error"] and st["last_ok_at"] == kept, st)
rc, out, err = run(GOOD, FAKE_COPY_MODE="fail", FAKE_SSH_EXIT="255")
check("both fail: one line that names both", rc == 1 and len(own_lines(err)) == 1 and "the copy exited 1" in own_lines(err)[0] and "ssh exited 255" in own_lines(err)[0], err[-400:])

# ---- 5 refusals
before = json.dumps(state())
cases = [
    ("push_to empty", config("r1.toml", push_to="")),
    ("push_to not set", config("r2.toml", push_to=None)),
    ("push_key not set", config("r3.toml", push_key=None)),
    ("push_key missing", config("r4.toml", push_key=str(T / "no-key"))),
    ("push_key a directory", config("r5.toml", push_key=str(T))),
    ("push_known_hosts not set", config("r6.toml", push_known_hosts=None)),
    ("push_known_hosts missing", config("r7.toml", push_known_hosts=str(T / "no-known"))),
    ("push_known_hosts a directory", config("r8.toml", push_known_hosts=str(T))),
    ("push_to starts with a dash", config("r9.toml", push_to="-oProxyCommand=x")),
    ("push_to has a space", config("r10.toml", push_to="user@host -x")),
    ("push_timeout is 0", config("r11.toml", push_timeout=0)),
    ("push_timeout is text", config("r12.toml", push_timeout="soon")),
    ("push_timeout above 540", config("r13.toml", push_timeout=541)),
]
for name, cfg in cases:
    base = json.dumps(state())
    rc, out, err = run(cfg)
    check(f"refused, {name}: exit 3, one line, standard output empty, nothing run, no state written", rc == 3 and out == b"" and len(err.strip().splitlines()) == 1 and err.startswith("standby-push: refused:")
          and nothing_ran() and json.dumps(state()) == base, (rc, err[-300:], list(REC.iterdir()), base, json.dumps(state())))
base = json.dumps(state())
rc, out, err = run(config("r14.toml", push_timeout=541))
check("push_timeout 541 is refused with the 540 ceiling and the unit's 10-minute start timeout named", rc == 3 and "above 540 seconds" in err and "10 minute" in err and nothing_ran() and json.dumps(state()) == base, (rc, err[-300:], base, json.dumps(state())))
rc, out, err = run(GOOD, "--lock-timeout", "0")
check("a time limit that is not above 0 is a usage error (exit 2) and runs nothing", rc == 2 and nothing_ran(), (rc, err[-200:]))

# ---- 6 the limits
def stopped_both(label):
    check(f"{label}: both children are gone", wait_for(lambda: pid_of("ssh.pid") and pid_of("copy.pid") and not alive(pid_of("ssh.pid")) and not alive(pid_of("copy.pid"))), (pid_of("ssh.pid"), pid_of("copy.pid")))


TIGHT = config("tight.toml", push_timeout=1)
last_ok_before = state()["last_ok_at"]
t0 = time.monotonic()
rc, out, err = run(TIGHT, FAKE_SSH_MODE="hang", FAKE_COPY_MODE="hang")
took = time.monotonic() - t0
st = state()
check("timeout: exit 1 after about push_timeout, one line, standard output empty", rc == 1 and out == b"" and 0.8 < took < 5 and len(own_lines(err)) == 1 and "timed out" in own_lines(err)[0], (rc, took, err[-300:]))
stopped_both("timeout")
check("timeout: the state says not ok with the line", st["ok"] is False and "timed out" in st["error"] and st["last_ok_at"] == last_ok_before, (st, last_ok_before))
t0 = time.monotonic()
rc, out, err = run(TIGHT, FAKE_SSH_MODE="deaf", FAKE_COPY_MODE="deaf")
took = time.monotonic() - t0
check("children that ignore SIGTERM are killed 5 s after it", rc == 1 and 5.5 < took < 12, (rc, took, err[-200:]))
stopped_both("SIGKILL after the grace")

for sig, code in ((signal.SIGTERM, 143), (signal.SIGINT, 130), (signal.SIGHUP, 129), (signal.SIGQUIT, 131)):
    clear()
    p = subprocess.Popen([sys.executable, str(DRIVER)], env=env_for(GOOD, FAKE_SSH_MODE="hang", FAKE_COPY_MODE="hang"), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        up = wait_for(lambda: pid_of("ssh.pid") and pid_of("copy.pid") and (REC / "ssh.argv").exists() and (REC / "copy.argv").exists())
        time.sleep(0.3)
        p.send_signal(sig)
        out, err = p.communicate(timeout=20)
    finally:
        if p.poll() is None:
            p.kill(); p.wait()
    check(f"{sig.name}: both started, then the command exits {code}, standard output empty", up and p.returncode == code and out == b"", (up, p.returncode, out, err.decode()[-300:]))
    stopped_both(sig.name)
    check(f"{sig.name}: one line says the signal and the state records it", len(own_lines(err.decode())) == 1 and f"signal {sig.value}" in own_lines(err.decode())[0] and state()["ok"] is False and f"signal {sig.value}" in state()["error"], (err.decode()[-300:], state()))

# ---- 7 one at a time
before = (STATE / "standby-push.json").read_bytes(); inode = (STATE / "standby-push.json").stat().st_ino
fd = os.open(STATE / "standby-push.lock", os.O_RDWR | os.O_CREAT, 0o600)
try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    rc, out, err = run(GOOD)
finally:
    os.close(fd)
check("a run while an earlier one holds the lock: exit 1, one line, nothing run", rc == 1 and out == b"" and len(err.strip().splitlines()) == 1 and "earlier push" in err and nothing_ran(), (rc, err[-300:], list(REC.iterdir())))
check("…and the state file is as it was", (STATE / "standby-push.json").read_bytes() == before and (STATE / "standby-push.json").stat().st_ino == inode)
# a second run while a first one really runs: the first holds the lock itself and its children are alive
clear()
first = subprocess.Popen([sys.executable, str(DRIVER)], env=env_for(GOOD, FAKE_SSH_MODE="hang", FAKE_COPY_MODE="hang"), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
ssh_first = copy_first = None
try:
    up = wait_for(lambda: pid_of("ssh.pid") and pid_of("copy.pid"))
    ssh_first, copy_first = pid_of("ssh.pid"), pid_of("copy.pid")
    live_before = (STATE / "standby-push.json").read_bytes() if (STATE / "standby-push.json").exists() else None
    rc, out, err = run(GOOD, keep=True)
    check("a run while a live push holds the lock: exit 1, one line saying an earlier push is still running, the second run starts nothing",
          up and rc == 1 and out == b"" and len(own_lines(err)) == 1 and "earlier push is still running" in own_lines(err)[0]
          and pid_of("ssh.pid") == ssh_first and pid_of("copy.pid") == copy_first and alive(ssh_first) and alive(copy_first), (up, rc, err[-300:], ssh_first, pid_of("ssh.pid")))
    check("…and the state file is as it was while the first push runs", ((STATE / "standby-push.json").read_bytes() if (STATE / "standby-push.json").exists() else None) == live_before, live_before)
finally:
    first.send_signal(signal.SIGTERM)
    try:
        first.communicate(timeout=20)
    except subprocess.TimeoutExpired:
        first.kill(); first.communicate()
check("…the first push is stopped by its signal, and its children are gone", ssh_first is not None and copy_first is not None and wait_for(lambda: not alive(ssh_first) and not alive(copy_first)), (ssh_first, copy_first))
rc, out, err = run(GOOD)
check("with the lock free again the next run goes through", rc == 0 and state()["ok"] is True and state()["last_ok_at"] > kept, (rc, err[-200:], state()))

# ---- 8 the state file
f = STATE / "standby-push.json"
check("the state file is 0600", (f.stat().st_mode & 0o777) == 0o600, oct(f.stat().st_mode))
ino = f.stat().st_ino
run(GOOD)
check("a new run replaces the file by a rename (a new inode), and no temporary file is left", f.stat().st_ino != ino and sorted(p.name for p in STATE.iterdir()) == ["standby-push.json", "standby-push.lock"], sorted(p.name for p in STATE.iterdir()))
os.umask(0o022)
old = f.read_bytes()
real = os.replace
def broken(*a, **k):
    raise OSError("no space (fake)")
sp.os.replace = broken
try:
    try:
        sp.write_state(str(STATE), False, time.time(), 1.0, "x")
        raised = False
    except OSError:
        raised = True
finally:
    sp.os.replace = real
check("a write that cannot be renamed leaves the old file whole and no temporary file", raised and f.read_bytes() == old and sorted(p.name for p in STATE.iterdir()) == ["standby-push.json", "standby-push.lock"], sorted(p.name for p in STATE.iterdir()))
f.write_text("not json")
sp.write_state(str(STATE), False, time.time(), 1.0, "x")
check("an unreadable old file counts as no last good run (0), and the new one is whole and 0600", json.loads(f.read_text())["last_ok_at"] == 0 and (f.stat().st_mode & 0o777) == 0o600, f.read_text())

# ---- 9 ssh ends 0: the copy's grace, and children that cannot start
rc, out, err = run(GOOD, FAKE_COPY_MODE="linger", FAKE_COPY_LINGER="0.5", FAKE_COPY_EXIT="0")
check("ssh ends 0, the copy ends 0 within the grace: exit 0, the state says ok", rc == 0 and out == b"" and own_lines(err) == [] and state()["ok"] is True, (rc, err[-300:], state()))
rc, out, err = run(GOOD, FAKE_COPY_MODE="linger", FAKE_COPY_LINGER="0.5", FAKE_COPY_EXIT="3")
check("ssh ends 0, the copy ends 1 within the grace: exit 1, one line naming the copy and its exit code, not ssh",
      rc == 1 and len(own_lines(err)) == 1 and "the copy exited 3" in own_lines(err)[0] and "ssh" not in own_lines(err)[0] and state()["ok"] is False, (rc, err[-300:]))
t0 = time.monotonic()
rc, out, err = run(GOOD, STANDBY_PUSH_TEST_GRACE="1", FAKE_COPY_MODE="linger", FAKE_COPY_LINGER="30", FAKE_COPY_EXIT="0")
took = time.monotonic() - t0
check("ssh ends 0, the copy still runs past the grace: exit 1 after about the grace, well under push_timeout, the line says ssh ended before the copy did",
      rc == 1 and 0.8 < took < PUSH_TIMEOUT / 2 and len(own_lines(err)) == 1 and "ssh ended before the copy did" in own_lines(err)[0] and state()["ok"] is False, (rc, took, err[-300:]))
check("…and the copy is stopped", wait_for(lambda: pid_of("copy.pid") is not None and not alive(pid_of("copy.pid"))), pid_of("copy.pid"))
rc, out, err = run(GOOD, STANDBY_PUSH_TEST_GRACE="1", FAKE_COPY_MODE="linger", FAKE_COPY_LINGER="30", FAKE_COPY_EXIT="0", FAKE_COPY_TRAP="1")
check("a copy that catches the stop and exits 143 is reported the same way: ssh ended before the copy did, its exit code not blamed",
      rc == 1 and len(own_lines(err)) == 1 and "ssh ended before the copy did" in own_lines(err)[0] and "143" not in own_lines(err)[0], (rc, err[-300:]))
(T / "empty").mkdir(exist_ok=True)
rc, out, err = run(GOOD, PATH=str(T / "empty"))
check("no ssh on PATH: exit 1, one line naming ssh as not started, no traceback, the state says not ok",
      rc == 1 and out == b"" and len(own_lines(err)) == 1 and "ssh could not be started" in own_lines(err)[0] and "Traceback" not in err and state()["ok"] is False, (rc, err[-400:]))
rc, out, err = run(GOOD, STANDBY_PUSH_TEST_NO_COPY="1", FAKE_SSH_MODE="hang")
check("the copy cannot be started: exit 1, one line naming the copy as not started, no traceback, the state says not ok",
      rc == 1 and len(own_lines(err)) == 1 and "the copy could not be started" in own_lines(err)[0] and "Traceback" not in err and state()["ok"] is False, (rc, err[-400:]))
ssh_pid = pid_of("ssh.pid")
check("…and the ssh started before it is stopped by the time the run returns", ssh_pid is not None and not alive(ssh_pid), ssh_pid)
if ssh_pid and alive(ssh_pid):      # only the ssh this test started (its recorded pid), so a failure leaves nothing running
    os.kill(ssh_pid, signal.SIGKILL)
rc, out, err = run(config("ok540.toml", push_timeout=540))
check("push_timeout 540 is accepted and the push runs", rc == 0 and out == b"" and state()["ok"] is True, (rc, err[-300:]))

print(("ok" if not fails else "FAILED") + f": standby push scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush()
sys.exit(1 if fails else 0)
